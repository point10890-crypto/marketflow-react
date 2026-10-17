"""scanner_runs 조회 비용 — run 디렉토리마다 stat/JSON 로드를 하지 않는다.

miniPC 실측(2026-10-18): scanner_runs 392,408개에서 엔트리당 isfile+getmtime 으로
`_scan_latest_run_paths` 가 17.1s 걸려 5003 의 다른 요청까지 10s 타임아웃을 넘겼다.
run id(`mfas_<generated_at UTC 14자리>_<sha12>`) 자체가 정렬 키이므로 stat 없이 정렬한다.
"""
import json
import os
from datetime import datetime

import pytest

from app.services.mirofish import alpha_scanner, pipeline_overview


def _make_run(root, name, payload=None, mtime=None):
    folder = root / name
    folder.mkdir()
    path = folder / 'run.json'
    path.write_text(json.dumps(payload if payload is not None else {'id': name}), encoding='utf-8')
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def runs_root(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    root.mkdir()
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(root))
    monkeypatch.setattr(pipeline_overview, 'SCANNER_RUNS_ROOT', str(root))
    alpha_scanner._invalidate_run_paths_cache()
    yield root
    alpha_scanner._invalidate_run_paths_cache()


def test_stamped_runs_sort_by_id_without_per_entry_stat(runs_root, monkeypatch):
    names = [f'mfas_202610{day:02d}120000_{day:012x}' for day in range(1, 31)]
    for name in names:
        _make_run(runs_root, name)

    def no_stat(*_args, **_kwargs):
        raise AssertionError('stamped run ids must not be stat-ed one by one')

    monkeypatch.setattr(alpha_scanner.os.path, 'isfile', no_stat)
    monkeypatch.setattr(alpha_scanner.os.path, 'getmtime', no_stat)

    paths = alpha_scanner._scan_latest_run_paths(str(runs_root))

    assert paths == [str(runs_root / name / 'run.json') for name in sorted(names, reverse=True)]


def test_newest_generated_run_wins_even_if_older_run_was_rewritten(runs_root):
    older = _make_run(runs_root, 'mfas_20261001120000_aaaaaaaaaaaa', mtime=2_000_000_000)
    newer = _make_run(runs_root, 'mfas_20261002120000_bbbbbbbbbbbb', mtime=1_900_000_000)

    assert alpha_scanner._scan_latest_run_paths(str(runs_root)) == [str(newer), str(older)]


def test_legacy_unstamped_runs_still_listed_by_mtime(runs_root):
    stamped = _make_run(runs_root, 'mfas_20261001120000_aaaaaaaaaaaa')
    legacy_new = _make_run(runs_root, 'legacy_run_new', mtime=2_000_000_000)  # 2033 UTC
    legacy_old = _make_run(runs_root, 'legacy_run_old', mtime=1_000_000_000)  # 2001 UTC
    (runs_root / 'legacy_no_header').mkdir()

    paths = alpha_scanner._scan_latest_run_paths(str(runs_root))

    assert paths == [str(legacy_new), str(stamped), str(legacy_old)]


def test_readers_skip_stamped_dir_without_header(runs_root):
    (runs_root / 'mfas_20261003120000_cccccccccccc').mkdir()  # 생성 중이거나 손상된 런
    _make_run(runs_root, 'mfas_20261002120000_bbbbbbbbbbbb', {
        'id': 'mfas_20261002120000_bbbbbbbbbbbb',
        'candidates': [{'symbol': '000001', 'rank': 1}],
    })

    assert alpha_scanner.read_latest_scanner_run()['id'] == 'mfas_20261002120000_bbbbbbbbbbbb'
    latest = alpha_scanner.read_latest_scanner_candidates(limit=5)
    assert latest['run_id'] == 'mfas_20261002120000_bbbbbbbbbbbb'


def test_list_scanner_runs_reads_only_requested_headers(runs_root, monkeypatch):
    names = [f'mfas_202610{day:02d}120000_{day:012x}' for day in range(1, 21)]
    for day, name in enumerate(names, start=1):
        _make_run(runs_root, name, {
            'id': name,
            'status': 'completed',
            'generated_at': f'2026-10-{day:02d}T12:00:00+00:00',
        })
    reads = []
    real_read = alpha_scanner._read_json
    monkeypatch.setattr(alpha_scanner, '_read_json', lambda path: reads.append(path) or real_read(path))

    summaries = alpha_scanner.list_scanner_runs(limit=3)

    assert [item['id'] for item in summaries] == sorted(names, reverse=True)[:3]
    assert len(reads) == 3


def test_count_runs_today_only_parses_todays_utc_window(runs_root, monkeypatch):
    # KST 2026-05-18 = UTC 05-17 15:00 ~ 05-18 15:00
    for name in (
        'mfas_20260517143000_aaaaaaaaaaaa',  # 05-17 23:30 KST
        'mfas_20260517150000_bbbbbbbbbbbb',  # 05-18 00:00 KST
        'mfas_20260518000000_cccccccccccc',  # 05-18 09:00 KST
        'mfas_20260518145959_dddddddddddd',  # 05-18 23:59 KST
        'mfas_20260518150000_eeeeeeeeeeee',  # 05-19 00:00 KST
    ):
        (runs_root / name).mkdir()
    for day in range(1, 200):
        (runs_root / f'mfas_2025{(day % 12) + 1:02d}{(day % 28) + 1:02d}120000_{day:012x}').mkdir()
    parsed = []
    real_parse = pipeline_overview._scanner_run_datetime_from_id
    monkeypatch.setattr(
        pipeline_overview,
        '_scanner_run_datetime_from_id',
        lambda name: parsed.append(name) or real_parse(name),
    )
    monkeypatch.setattr(
        pipeline_overview,
        '_read_json_safe',
        lambda *_a, **_k: pytest.fail('stamped run ids need no header read'),
    )

    now_kst = datetime(2026, 5, 18, 8, 50, tzinfo=pipeline_overview.KST)

    assert pipeline_overview._count_scanner_runs_today(now_kst) == 3
    assert len(parsed) <= 5
