"""Scanner directory cache concurrency; temporary files, no provider calls."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.mirofish import alpha_scanner


@pytest.fixture
def runs(tmp_path, monkeypatch):
    root = tmp_path / "scanner_runs"
    root.mkdir()
    for day, suffix in (("01", "aaaaaaaaaaaa"), ("02", "bbbbbbbbbbbb")):
        folder = root / f"mfas_202610{day}120000_{suffix}"
        folder.mkdir()
        (folder / "run.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(alpha_scanner, "SCANNER_RUNS_ROOT", str(root))
    monkeypatch.setenv("MIROFISH_RUN_PATHS_TTL_SECONDS", "30")
    alpha_scanner._invalidate_run_paths_cache()
    yield root
    alpha_scanner._invalidate_run_paths_cache()


def test_concurrent_cold_requests_share_one_directory_scan(runs, monkeypatch):
    # All callers observe the same initial miss before any scan can publish.
    # The cache must recheck after acquiring the shared rebuild lock.
    barrier = threading.Barrier(8)
    seen = set()
    guard = threading.Lock()

    class ConcurrentMissCache(dict):
        def get(self, key, default=None):
            with guard:
                first_read = threading.get_ident() not in seen
                seen.add(threading.get_ident())
                value = super().get(key, default)
            if first_read:
                barrier.wait(timeout=5)
            return value

    monkeypatch.setattr(alpha_scanner, "_RUN_PATHS_CACHE", ConcurrentMissCache())
    scan = alpha_scanner._scan_latest_run_paths
    calls = []

    def counted(root):
        calls.append(root)
        return scan(root)

    monkeypatch.setattr(alpha_scanner, "_scan_latest_run_paths", counted)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(alpha_scanner._latest_scanner_run_paths) for _ in range(8)]
        results = [future.result(timeout=10) for future in futures]
    assert len(calls) == 1
    assert len(results[0]) == 2
    assert all(result == results[0] for result in results)


def test_slow_scan_gets_full_ttl_from_completion(runs, monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(alpha_scanner.time_mod, "time", lambda: clock["now"])
    monkeypatch.setattr(alpha_scanner.time_mod, "monotonic", lambda: clock["now"])
    scan = alpha_scanner._scan_latest_run_paths
    calls = []

    def slow_scan(root):
        calls.append(root)
        clock["now"] += 31  # A cold rebuild can take longer than the 30-second TTL.
        return scan(root)

    monkeypatch.setattr(alpha_scanner, "_scan_latest_run_paths", slow_scan)
    first = alpha_scanner._latest_scanner_run_paths()
    clock["now"] += 29
    assert alpha_scanner._latest_scanner_run_paths() == first
    assert len(calls) == 1
    clock["now"] += 2
    assert alpha_scanner._latest_scanner_run_paths() == first
    assert len(calls) == 2


def test_wall_clock_adjustment_does_not_expire_monotonic_cache(runs, monkeypatch):
    clock = {"wall": 1000.0, "monotonic": 1.0}
    monkeypatch.setattr(alpha_scanner.time_mod, "time", lambda: clock["wall"])
    monkeypatch.setattr(alpha_scanner.time_mod, "monotonic", lambda: clock["monotonic"])
    scan = alpha_scanner._scan_latest_run_paths
    calls = []
    monkeypatch.setattr(alpha_scanner, "_scan_latest_run_paths", lambda root: calls.append(root) or scan(root))
    first = alpha_scanner._latest_scanner_run_paths()
    clock["wall"] += 3600
    clock["monotonic"] += 1
    assert alpha_scanner._latest_scanner_run_paths() == first
    assert len(calls) == 1


def test_invalidation_during_rebuild_cannot_republish_an_old_snapshot(runs, monkeypatch):
    entered, release, invalidating, invalidated = (threading.Event() for _ in range(4))
    scan = alpha_scanner._scan_latest_run_paths
    calls = []

    def delayed_snapshot(root):
        snapshot = scan(root)
        calls.append(root)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=5)
        return snapshot

    def invalidate():
        invalidating.set()
        alpha_scanner._invalidate_run_paths_cache()
        invalidated.set()

    monkeypatch.setattr(alpha_scanner, "_scan_latest_run_paths", delayed_snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(alpha_scanner._latest_scanner_run_paths)
        assert entered.wait(timeout=5)
        latest = runs / "mfas_20261003120000_cccccccccccc"
        latest.mkdir()
        header = latest / "run.json"
        header.write_text("{}", encoding="utf-8")
        os.utime(header, (2_000_000_000, 2_000_000_000))
        writer = pool.submit(invalidate)
        assert invalidating.wait(timeout=5)
        # Unlocked invalidation finishes now and the old builder can overwrite it.
        # Locked invalidation waits for publication, then removes that snapshot.
        invalidated.wait(timeout=0.1)
        release.set()
        reader.result(timeout=5)
        writer.result(timeout=5)
    paths = alpha_scanner._latest_scanner_run_paths()
    assert paths[0] == str(header)
    assert len(calls) == 2


def test_failed_scan_releases_lock_and_does_not_cache_failure(runs, monkeypatch):
    scan = alpha_scanner._scan_latest_run_paths
    calls = []

    def fail_once(root):
        calls.append(root)
        if len(calls) == 1:
            raise OSError("unavailable directory")
        return scan(root)

    monkeypatch.setattr(alpha_scanner, "_scan_latest_run_paths", fail_once)
    with pytest.raises(OSError, match="unavailable directory"):
        alpha_scanner._latest_scanner_run_paths()
    with ThreadPoolExecutor(max_workers=1) as pool:
        recovered = pool.submit(alpha_scanner._latest_scanner_run_paths).result(timeout=5)
    assert len(recovered) == 2
    assert alpha_scanner._latest_scanner_run_paths() == recovered
    assert len(calls) == 2
