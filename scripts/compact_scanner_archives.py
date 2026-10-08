#!/usr/bin/env python3
"""Losslessly compress cold scanner JSONs in place with Windows compact LZX.

Default execution only inventories eligible files. --apply changes filesystem
compression, never JSON bytes or paths. No application imports, credentials,
network calls, archive deletion, or archive moves are used.

Example:
  python scripts/compact_scanner_archives.py --root C:\\bitman_marketfloww \
      --before 2026-10-01 --target-free-gib 20 --max-runs 10000 --apply
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator

GIB = 1024 ** 3
MAX_BATCH_FILES = 64
MAX_COMMAND_CHARS = 30000
MAX_RUNS = 10000
RUN_PATTERN = re.compile(r'mfas_(\d{8})\d{6}_[a-fA-F0-9]{12}')
REQUIRED_FILES = frozenset({
    'run.json', 'feature_vectors.json', 'evidence_ledger.json',
    'rejected_candidates.json', 'deepseek_rerank.json',
})
COMPACT_FLAGS = ['/C', '/F', '/EXE:LZX', '/Q']


class SafetyError(ValueError):
    """A target or operation does not meet the cold archive safety contract."""


class IntegrityError(SafetyError):
    pass


@dataclass(frozen=True)
class Options:
    root: Path
    before: date
    after: date | None = None
    apply: bool = False
    target_free_gib: float = 20
    max_runs: int = MAX_RUNS


def _today() -> date:
    return date.today()


def _is_reparse(path: Path) -> bool:
    """Reject redirects; WOF on a regular file is the LZX storage format itself."""
    info = path.lstat()
    if path.is_symlink():
        return True
    if not getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        return False
    # IO_REPARSE_TAG_WOF has no path traversal semantics. Reject every other
    # tag, and every reparse directory, including junctions and symbolic links.
    return not (getattr(info, 'st_reparse_tag', 0) == 0x80000017 and stat.S_ISREG(info.st_mode))


def _no_reparse_ancestors(path: Path) -> None:
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            if _is_reparse(item):
                raise SafetyError('reparse_target_rejected')


def validate_options(options: Options) -> Path:
    if not isinstance(options.before, date) or options.before > _today() - timedelta(days=7):
        raise SafetyError('before_must_be_at_least_seven_days_old')
    if options.after is not None and (not isinstance(options.after, date) or options.after >= options.before):
        raise SafetyError('after_must_precede_before')
    if not isinstance(options.max_runs, int) or isinstance(options.max_runs, bool) or not 1 <= options.max_runs <= MAX_RUNS:
        raise SafetyError('max_runs_must_be_between_1_and_10000')
    if not math.isfinite(options.target_free_gib) or options.target_free_gib <= 0:
        raise SafetyError('target_free_gib_must_be_positive')
    root = Path(options.root).absolute()
    _no_reparse_ancestors(root)
    if not root.is_dir():
        raise SafetyError('root_directory_missing')
    archive = root / 'data' / 'admin_mirofish' / 'scanner_runs'
    _no_reparse_ancestors(archive)
    if not archive.is_dir():
        raise SafetyError('scanner_archive_directory_missing')
    return archive.resolve(strict=True)


def validate_target(path: Path, archive: Path) -> Path:
    path = Path(path).absolute()
    _no_reparse_ancestors(path)
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(archive.resolve(strict=True))
    except ValueError:
        raise SafetyError('target_outside_scanner_archive') from None
    if not relative.parts or len(relative.parts) > 2:
        raise SafetyError('unexpected_archive_depth')
    if not resolved.exists():
        raise SafetyError('archive_target_missing')
    if resolved.is_file() and resolved.stat().st_nlink > 1:
        raise SafetyError('hardlinked_target_rejected')
    return resolved


def _run_date(path: Path) -> date | None:
    match = RUN_PATTERN.fullmatch(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), '%Y%m%d').date()
    except ValueError:
        return None


def _read_run_header(path: Path) -> dict:
    """Read only the bounded top-level header; never load candidate histories."""
    with path.open('r', encoding='utf-8-sig') as handle:
        text = handle.read(65536)
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != '{':
        return {}
    index += 1
    wanted = {'id', 'status', 'generated_at'}
    header = {}
    try:
        while index < len(text):
            while index < len(text) and (text[index].isspace() or text[index] == ','):
                index += 1
            if index >= len(text) or text[index] == '}':
                break
            key, index = decoder.raw_decode(text, index)
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text) or text[index] != ':':
                return {}
            index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            value, index = decoder.raw_decode(text, index)
            if key in wanted:
                header[key] = value
            if wanted <= header.keys():
                return header
    except (ValueError, TypeError):
        return {}
    return header


def _physical_size(path: Path) -> int:
    """Get allocated/compressed bytes, including Windows WOF LZX compression."""
    if os.name != 'nt':
        return path.stat().st_size  # Dry-run inventory remains portable.
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_size = kernel.GetCompressedFileSizeW
    get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_size.restype = wintypes.DWORD
    high = wintypes.DWORD()
    ctypes.set_last_error(0)
    low = get_size(str(path), ctypes.byref(high))
    error = ctypes.get_last_error()
    if low == 0xFFFFFFFF and error:
        raise OSError(error, 'compressed_size_query_failed')
    return (high.value << 32) | low


def _cold_run_files(run: Path, options: Options, archive: Path) -> list[Path] | None:
    run_date = _run_date(run)
    if run_date is None or run_date >= options.before or (options.after is not None and run_date < options.after) or not run.is_dir():
        return None
    run = validate_target(run, archive)
    files = list(run.iterdir())
    names = {p.name for p in files if p.is_file()}
    if not REQUIRED_FILES <= names or any(p.suffix.lower() == '.tmp' for p in files):
        return None
    json_files = sorted((p for p in files if p.is_file() and p.suffix.lower() == '.json'), key=lambda p: p.name)
    for path in json_files:
        validate_target(path, archive)
    if any(datetime.fromtimestamp(p.stat().st_mtime).date() >= options.before for p in json_files):
        return None  # Even an old run ID can have an active/recent writer.
    header = _read_run_header(run / 'run.json')
    if header.get('id') != run.name or header.get('status') != 'completed':
        return None
    try:
        if date.fromisoformat(str(header.get('generated_at') or '')[:10]) >= options.before:
            return None
    except ValueError:
        return None
    return json_files


def discover_files(options: Options) -> list[Path]:
    archive = validate_options(options)
    runs = sorted((p for p in archive.iterdir() if _run_date(p)), key=lambda p: p.name, reverse=True)
    latest = max(runs, key=lambda p: p.name) if runs else None
    selected = []
    selected_runs = 0
    for run in runs:
        if run == latest:
            continue
        json_files = _cold_run_files(run, options, archive)
        if json_files is None:
            continue
        eligible = []
        for path in json_files:
            logical = path.stat().st_size
            if logical and _physical_size(path) >= logical * 0.5:
                eligible.append(path)
        if eligible:
            selected.extend(eligible)
            selected_runs += 1
        if selected_runs >= options.max_runs:
            break
    return selected


def _compact_executable() -> str:
    if os.name == 'nt':
        # Resolve the Windows system binary, never a PATH-provided executable.
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        get_dir = kernel.GetSystemDirectoryW
        get_dir.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        get_dir.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_dir(buffer, len(buffer))
        if not length or length >= len(buffer):
            raise SafetyError('windows_system_directory_unavailable')
        return str(Path(buffer.value) / 'compact.exe')
    return 'compact.exe'


def command_length(paths: Iterable[Path]) -> int:
    command = subprocess.list2cmdline([_compact_executable(), *COMPACT_FLAGS, *(str(p) for p in paths)])
    # Windows limits UTF-16 code units, including the final NUL.
    return len(command.encode('utf-16-le')) // 2 + 1


def file_batches(paths: Iterable[Path], *, max_chars: int = MAX_COMMAND_CHARS) -> Iterator[list[Path]]:
    batch = []
    for path in paths:
        if command_length([path]) > max_chars:
            raise SafetyError('single_file_exceeds_command_line_limit')
        if batch and (len(batch) >= MAX_BATCH_FILES or command_length([*batch, path]) > max_chars):
            yield batch
            batch = []
        batch.append(path)
    if batch:
        yield batch


def _require_windows() -> None:
    if os.name != 'nt':
        raise SafetyError('apply_requires_windows')


def _run_compact(paths: list[Path]):
    return subprocess.run(
        [_compact_executable(), *COMPACT_FLAGS, *(str(p) for p in paths)],
        shell=False, capture_output=True, timeout=240, check=False,
    )


def _free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


def _fingerprint(path: Path) -> tuple[str, int, int]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise IntegrityError('input_changed_during_hash')
    return digest.hexdigest(), after.st_size, after.st_mtime_ns


def _write_manifest(root: Path, summary: dict) -> str:
    directory = root / 'data' / 'operations' / 'scanner_archive_compaction'
    _no_reparse_ancestors(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / f'compaction_{stamp}.json'
    fd, temporary = tempfile.mkstemp(prefix='.summary_', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(summary, handle, ensure_ascii=True, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return str(target)


def execute(options: Options, *, emit: Callable[[dict], None] | None = None) -> dict:
    archive = validate_options(options)
    root = Path(options.root).resolve(strict=True)
    emit = emit or (lambda item: print(json.dumps(item, ensure_ascii=True, sort_keys=True), flush=True))
    initial_free = _free_bytes(root)
    summary = {
        'operation': 'scanner_archive_lzx', 'apply': options.apply,
        'before': options.before.isoformat(), 'max_runs': options.max_runs,
        'after': options.after.isoformat() if options.after is not None else None,
        'target_free_bytes': int(options.target_free_gib * GIB),
        'eligible_files': 0, 'eligible_runs': 0, 'verified_files': 0,
        'batches': 0, 'logical_bytes': 0, 'physical_bytes_before': 0,
        'physical_bytes_after': 0, 'free_bytes_before': initial_free,
        'free_bytes_after': initial_free, 'status': 'dry_run' if not options.apply else 'completed',
    }
    try:
        if options.apply:
            _require_windows()
        if options.apply and initial_free >= summary['target_free_bytes']:
            summary['status'] = 'target_reached'
        else:
            files = discover_files(options)
            summary['eligible_files'] = len(files)
            summary['eligible_runs'] = len({p.parent for p in files})
            if not options.apply:
                summary['logical_bytes'] = sum(p.stat().st_size for p in files)
                summary['physical_bytes_before'] = sum(_physical_size(p) for p in files)
                summary['physical_bytes_after'] = summary['physical_bytes_before']
            else:
                for batch in file_batches(files):
                    if _free_bytes(root) >= summary['target_free_bytes']:
                        summary['status'] = 'target_reached'
                        break
                    fingerprints = {}
                    allocated = {}
                    for run in {path.parent for path in batch}:
                        if _cold_run_files(run, options, archive) is None:
                            raise SafetyError('run_no_longer_cold_and_complete')
                    for path in batch:
                        validate_target(path, archive)
                        fingerprints[path] = _fingerprint(path)
                        allocated[path] = _physical_size(path)
                    for path in batch:
                        validate_target(path, archive)
                        info = path.stat()
                        if (info.st_size, info.st_mtime_ns) != fingerprints[path][1:]:
                            raise IntegrityError('input_changed_before_compaction')
                    for run in {path.parent for path in batch}:
                        if _cold_run_files(run, options, archive) is None:
                            raise SafetyError('run_no_longer_cold_and_complete')
                    failure = None
                    try:
                        result = _run_compact(batch)
                        if result.returncode != 0:
                            failure = 'compact_nonzero_exit'
                    except (OSError, subprocess.SubprocessError):
                        failure = 'compact_execution_failed'
                    # A failed/partial compact command still requires byte verification.
                    for path in batch:
                        validate_target(path, archive)
                        after = _fingerprint(path)
                        if after[:2] != fingerprints[path][:2]:
                            raise IntegrityError('integrity_failed')
                    summary['batches'] += 1
                    summary['verified_files'] += len(batch)
                    summary['logical_bytes'] += sum(item[1] for item in fingerprints.values())
                    summary['physical_bytes_before'] += sum(allocated.values())
                    summary['physical_bytes_after'] += sum(_physical_size(p) for p in batch)
                    summary['free_bytes_after'] = _free_bytes(root)
                    emit({key: summary[key] for key in ('operation', 'batches', 'verified_files', 'eligible_files', 'free_bytes_after')})
                    if failure:
                        raise SafetyError(failure)
                    if summary['free_bytes_after'] >= summary['target_free_bytes']:
                        summary['status'] = 'target_reached'
                        break
    except IntegrityError:
        summary.update(status='aborted', error='integrity_failed')
    except SafetyError as exc:
        summary.update(status='aborted', error=str(exc))
    except (OSError, ValueError, TypeError):
        summary.update(status='aborted', error='filesystem_or_metadata_error')
    summary['free_bytes_after'] = _free_bytes(root)
    summary['reclaimed_bytes'] = max(0, summary['physical_bytes_before'] - summary['physical_bytes_after'])
    if options.apply:
        try:
            summary['manifest'] = _write_manifest(root, summary)
        except (OSError, SafetyError):
            summary['manifest_error'] = 'summary_write_failed'
    emit(summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(r'C:\bitman_marketfloww'))
    parser.add_argument('--before', required=True, type=date.fromisoformat)
    parser.add_argument('--after', type=date.fromisoformat, help='Optional inclusive lower date bound; before is exclusive.')
    parser.add_argument('--target-free-gib', type=float, default=20)
    parser.add_argument('--max-runs', type=int, default=MAX_RUNS)
    parser.add_argument('--apply', action='store_true', help='Apply lossless filesystem compression; default is dry-run.')
    args = parser.parse_args(argv)
    try:
        summary = execute(Options(**vars(args)))
    except (SafetyError, OSError):
        print(json.dumps({'status': 'aborted', 'error': 'invalid_or_unsafe_target'}), flush=True)
        return 2
    return 2 if summary['status'] == 'aborted' or summary.get('manifest_error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
