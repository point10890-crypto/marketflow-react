"""Storage recovery must preserve archive bytes and stay inside cold run paths."""
import importlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def compact(monkeypatch):
    module = importlib.import_module('scripts.compact_scanner_archives')
    monkeypatch.setattr(module, '_today', lambda: date(2026, 10, 8))
    monkeypatch.setattr(module, '_require_windows', lambda: None)
    monkeypatch.setattr(module, '_physical_size', lambda path: path.stat().st_size)
    monkeypatch.setattr(module, '_free_bytes', lambda root: 0)
    return module


def _run(root, day='20260912', *, status='completed', complete=True):
    folder = root / 'data' / 'admin_mirofish' / 'scanner_runs' / f'mfas_{day}090000_abcdef012345'
    folder.mkdir(parents=True)
    header = {'id': folder.name, 'status': status, 'generated_at': f'{day[:4]}-{day[4:6]}-{day[6:]}T09:00:00+00:00'}
    (folder / 'run.json').write_text(json.dumps(header), encoding='utf-8')
    if complete:
        for name in ('feature_vectors.json', 'evidence_ledger.json', 'rejected_candidates.json', 'deepseek_rerank.json'):
            (folder / name).write_text('{"synthetic": "' + 'x' * 200 + '"}', encoding='utf-8')
    stamp = datetime(2026, 9, 12).timestamp()
    for path in folder.iterdir():
        os.utime(path, (stamp, stamp))
    return folder


def _root(tmp_path):
    root = tmp_path / 'workspace with spaces'
    _run(root, '20261008')  # The latest/current run must always remain excluded.
    return root


def _options(compact, root, **overrides):
    values = dict(root=root, before=date(2026, 10, 1), apply=False, target_free_gib=20, max_runs=10000)
    values.update(overrides)
    return compact.Options(**values)


def test_cutoff_must_be_at_least_seven_days_old_and_max_runs_is_bounded(compact, tmp_path):
    root = _root(tmp_path)
    for values in ({'before': date(2026, 10, 2)}, {'max_runs': 10001}, {'max_runs': 0}, {'target_free_gib': -1}):
        with pytest.raises(compact.SafetyError):
            compact.validate_options(_options(compact, root, **values))


def test_discovery_excludes_recent_incomplete_and_unknown_runs(compact, tmp_path):
    root = _root(tmp_path)
    cold = _run(root)
    _run(root, '20260913', status='running')
    _run(root, '20260914', complete=False)
    _run(root, '20261002')
    (cold / 'keep.txt').write_text('untouched', encoding='utf-8')
    files = compact.discover_files(_options(compact, root))
    assert len(files) == 5
    assert all(path.parent == cold and path.suffix == '.json' for path in files)


def test_target_outside_archive_and_reparse_files_are_rejected(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    cold = _run(root)
    archive = root / 'data' / 'admin_mirofish' / 'scanner_runs'
    with pytest.raises(compact.SafetyError):
        compact.validate_target(root / 'unrelated.json', archive)
    real = compact._is_reparse
    monkeypatch.setattr(compact, '_is_reparse', lambda path: path == cold / 'run.json' or real(path))
    with pytest.raises(compact.SafetyError):
        compact.validate_target(cold / 'run.json', archive)


def test_dry_run_does_not_write_manifest_or_invoke_compact(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr(compact, '_run_compact', lambda paths: pytest.fail('dry-run invoked compact'))
    summary = compact.execute(_options(compact, root), emit=lambda item: None)
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert summary['status'] == 'dry_run' and summary['eligible_files'] == 5
    assert before == after
    assert not (root / 'data' / 'operations').exists()


def test_already_compressed_files_are_skipped(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    monkeypatch.setattr(compact, '_physical_size', lambda path: path.stat().st_size // 4)
    assert compact.discover_files(_options(compact, root)) == []


def test_batches_respect_windows_command_line_limit(compact, tmp_path):
    paths = [tmp_path / ('x' * 70 + str(i) + '.json') for i in range(30)]
    batches = list(compact.file_batches(paths, max_chars=500))
    assert len(batches) > 1
    assert [p for batch in batches for p in batch] == paths
    for batch in batches:
        assert compact.command_length(batch) <= 500
    with pytest.raises(compact.SafetyError):
        list(compact.file_batches([tmp_path / ('x' * 500)], max_chars=100))


def test_changed_bytes_abort_immediately_and_are_reported(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    calls = []
    def mutate(paths):
        calls.append(list(paths))
        paths[0].write_bytes(b'changed')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(compact, '_run_compact', mutate)
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'aborted'
    assert summary['error'] == 'integrity_failed'
    assert len(calls) == 1 and summary['verified_files'] == 0
    assert Path(summary['manifest']).is_file()


def test_free_space_target_stops_after_first_verified_batch(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    _run(root, '20260913')
    calls = []
    monkeypatch.setattr(compact, 'MAX_BATCH_FILES', 2)
    def fake(paths):
        calls.append(list(paths))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(compact, '_run_compact', fake)
    monkeypatch.setattr(compact, '_free_bytes', lambda root: 30 * 1024**3 if calls else 0)
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'target_reached'
    assert len(calls) == 1 and summary['verified_files'] == 2
    assert summary['free_bytes_after'] == 30 * 1024**3


def test_no_compact_call_if_free_target_already_met(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    monkeypatch.setattr(compact, '_free_bytes', lambda root: 25 * 1024**3)
    monkeypatch.setattr(compact, '_run_compact', lambda paths: pytest.fail('target already reached'))
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'target_reached' and summary['verified_files'] == 0


def test_compact_argv_is_direct_lzx_and_does_not_expose_output(compact, tmp_path, monkeypatch):
    seen = {}
    def fake(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(compact.subprocess, 'run', fake)
    path = tmp_path / 'file with spaces.json'
    compact._run_compact([path])
    assert seen['argv'][1:4] == ['/C', '/F', '/EXE:LZX']
    assert seen['argv'][-1] == str(path)
    assert seen['kwargs'].get('shell', False) is False
    assert seen['kwargs']['capture_output'] is True


def test_max_runs_and_recent_writer_exclusion(compact, tmp_path):
    root = _root(tmp_path)
    first = _run(root)
    second = _run(root, '20260913')
    files = compact.discover_files(_options(compact, root, max_runs=1))
    assert len(files) == 5 and all(path.parent == second for path in files)
    stamp = datetime(2026, 10, 7).timestamp()
    os.utime(first / 'evidence_ledger.json', (stamp, stamp))
    files = compact.discover_files(_options(compact, root))
    assert len(files) == 5 and all(path.parent == second for path in files)


def test_input_change_before_compact_prevents_external_command(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    original = compact._fingerprint
    changed = []
    def fingerprint(path):
        value = original(path)
        if not changed:
            path.write_bytes(b'changed after its initial hash')
            changed.append(path)
        return value
    monkeypatch.setattr(compact, '_fingerprint', fingerprint)
    monkeypatch.setattr(compact, '_run_compact', lambda paths: pytest.fail('changed input compressed'))
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'aborted' and summary['error'] == 'integrity_failed'


def test_compact_nonzero_exit_is_verified_then_aborted(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    _run(root)
    monkeypatch.setattr(compact, '_run_compact', lambda paths: SimpleNamespace(returncode=1))
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'aborted' and summary['error'] == 'compact_nonzero_exit'
    assert summary['verified_files'] == 5


def test_native_compressed_size_combines_high_and_low_words(tmp_path, monkeypatch):
    module = importlib.import_module('scripts.compact_scanner_archives')
    native = module._physical_size
    class SizeCall:
        def __call__(self, path, high):
            high._obj.value = 2
            return 123
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(module.ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(GetCompressedFileSizeW=SizeCall()), raising=False)
    monkeypatch.setattr(module.ctypes, 'set_last_error', lambda value: None, raising=False)
    monkeypatch.setattr(module.ctypes, 'get_last_error', lambda: 0, raising=False)
    assert native(tmp_path / 'synthetic.json') == (2 << 32) | 123


def test_wof_regular_file_is_allowed_but_directory_and_link_tags_are_rejected(monkeypatch):
    import stat
    module = importlib.import_module('scripts.compact_scanner_archives')
    class FakePath:
        def __init__(self, mode, tag):
            self.info = SimpleNamespace(st_file_attributes=0x400, st_reparse_tag=tag, st_mode=mode)
        def lstat(self):
            return self.info
        def is_symlink(self):
            return False
    assert module._is_reparse(FakePath(stat.S_IFREG, 0x80000017)) is False
    assert module._is_reparse(FakePath(stat.S_IFDIR, 0x80000017)) is True
    assert module._is_reparse(FakePath(stat.S_IFREG, 0xA000000C)) is True


def test_run_restart_after_discovery_is_rejected_before_compact(compact, tmp_path, monkeypatch):
    root = _root(tmp_path)
    cold = _run(root)
    original = compact.discover_files
    def discover(options):
        files = original(options)
        path = cold / 'run.json'
        stamp = path.stat().st_mtime
        data = json.loads(path.read_text(encoding='utf-8'))
        data['status'] = 'running'
        path.write_text(json.dumps(data), encoding='utf-8')
        os.utime(path, (stamp, stamp))  # Test completion status independent of freshness.
        return files
    monkeypatch.setattr(compact, 'discover_files', discover)
    monkeypatch.setattr(compact, '_run_compact', lambda paths: pytest.fail('restarted run compressed'))
    summary = compact.execute(_options(compact, root, apply=True), emit=lambda item: None)
    assert summary['status'] == 'aborted' and summary['error'] == 'run_no_longer_cold_and_complete'


def test_after_must_precede_before(compact, tmp_path):
    root = _root(tmp_path)
    for after in (date(2026, 10, 1), date(2026, 10, 2)):
        with pytest.raises(compact.SafetyError):
            compact.validate_options(_options(compact, root, after=after))


def test_after_is_inclusive_and_before_is_exclusive(compact, tmp_path):
    root = _root(tmp_path)
    _run(root)
    selected = _run(root, '20260913')
    _run(root, '20260914')
    files = compact.discover_files(_options(compact, root, after=date(2026, 9, 13), before=date(2026, 9, 14)))
    assert len(files) == 5 and all(path.parent == selected for path in files)


def test_newest_eligible_cold_run_is_selected_without_touching_latest(compact, tmp_path):
    root = _root(tmp_path)
    _run(root)
    recent_cold = _run(root, '20260930')
    _run(root, '20261002')  # Too recent, even though not the latest run.
    files = compact.discover_files(_options(compact, root, max_runs=1))
    assert len(files) == 5 and all(path.parent == recent_cold for path in files)
