"""Create and verify recoverable MarketFlow durable-data backups.

The member database is copied with SQLite's online backup API so the result is
consistent even while the production service is using WAL mode.  The script
prints only aggregate counts and paths; it never emits member records or
secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BACKUP_PREFIXES = ("durable_", "predeploy_")
CORE_TABLES = (
    "users",
    "subscription_requests",
    "admin_audit_log",
    "admin_notifications",
    "boards",
    "posts",
    "comments",
    "post_images",
    "purchase_requests",
)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro",
        uri=True,
        timeout=30,
    )
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    available = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    counts: dict[str, int] = {}
    for table in CORE_TABLES:
        if table in available:
            quoted = table.replace('"', '""')
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
            )
    return counts


def _database_facts(path: Path) -> dict[str, Any]:
    with _connect_read_only(path) as connection:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        return {
            "quick_check": quick_check,
            "foreign_key_violations": len(foreign_keys),
            "table_counts": _table_counts(connection),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_facts(path: Path) -> dict[str, int]:
    files = 0
    size = 0
    if path.is_dir():
        for candidate in path.rglob("*"):
            if candidate.is_file():
                files += 1
                size += candidate.stat().st_size
    return {"files": files, "bytes": size}


def _copy_tree_verified(source: Path, destination: Path) -> dict[str, int]:
    if not source.is_dir():
        return {"files": 0, "bytes": 0, "present": 0}
    source_facts = _tree_facts(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    destination_facts = _tree_facts(destination)
    if destination_facts != source_facts:
        raise RuntimeError(
            f"Directory verification failed for {source.name}: "
            f"source={source_facts}, backup={destination_facts}"
        )
    return {**destination_facts, "present": 1}


def _restrict_windows_acl(path: Path) -> None:
    """Keep backup contents limited to SYSTEM, Administrators, and the operator."""
    if os.name != "nt":
        return
    username = os.environ.get("USERNAME", "").strip()
    grants = [
        "*S-1-5-18:(OI)(CI)F",       # SYSTEM
        "*S-1-5-32-544:(OI)(CI)F",  # Builtin Administrators
    ]
    if username and username.upper() != "SYSTEM":
        grants.append(f"{username}:(OI)(CI)F")
    root_command = ["icacls", str(path), "/inheritance:r", "/grant:r", *grants, "/C"]
    completed = subprocess.run(root_command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Failed to restrict backup ACL (exit={completed.returncode})")
    # Reset descendants so they inherit the protected root ACL.  Applying
    # /inheritance:r recursively can otherwise leave child files with no ACEs.
    descendants = str(path / "*")
    reset = subprocess.run(
        ["icacls", descendants, "/reset", "/T", "/C"],
        capture_output=True,
        text=True,
        check=False,
    )
    if reset.returncode != 0:
        raise RuntimeError(f"Failed to propagate protected backup ACL (exit={reset.returncode})")


def _online_sqlite_backup(source: Path, destination: Path) -> None:
    source_connection = _connect_read_only(source)
    destination_connection = sqlite3.connect(destination, timeout=30)
    try:
        source_connection.backup(destination_connection, pages=1024, sleep=0.05)
        destination_connection.commit()
        destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        destination_connection.execute("PRAGMA journal_mode=DELETE")
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def _copy_runtime_files(root: Path, destination: Path) -> dict[str, int]:
    candidates = (
        root / ".env",
        root / "scheduler.py",
        root / "scripts" / "start_flask_task.ps1",
        root / "scripts" / "flask_watchdog_v2.ps1",
    )
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    size = 0
    for source in candidates:
        if not source.is_file():
            continue
        target = destination / source.name
        shutil.copy2(source, target)
        copied += 1
        size += target.stat().st_size
    return {"files": copied, "bytes": size}


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _prune_old_backups(output_root: Path, retention_days: int, current: Path) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for candidate in output_root.iterdir():
        if candidate == current or not candidate.is_dir():
            continue
        if not candidate.name.startswith(BACKUP_PREFIXES):
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            shutil.rmtree(candidate)
            removed += 1
    return removed


def create_backup(
    root: Path,
    output_root: Path,
    prefix: str,
    include_assets: bool,
    retention_days: int,
) -> dict[str, Any]:
    root = root.resolve()
    source_db = root / "data" / "users.db"
    if not source_db.is_file():
        raise FileNotFoundError(f"Member database is missing: {source_db}")

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{prefix}_{stamp}"
    destination.mkdir()

    backup_db = destination / "users.db"
    _online_sqlite_backup(source_db, backup_db)
    live_facts = _database_facts(source_db)
    backup_facts = _database_facts(backup_db)
    if live_facts != backup_facts:
        raise RuntimeError(f"Database verification mismatch: live={live_facts}, backup={backup_facts}")
    if backup_facts["quick_check"] != "ok":
        raise RuntimeError(f"Backup quick_check failed: {backup_facts['quick_check']}")

    restore_dir = destination / "restore_drill"
    restore_dir.mkdir()
    restored_db = restore_dir / "users.db"
    shutil.copy2(backup_db, restored_db)
    restored_facts = _database_facts(restored_db)
    if restored_facts != backup_facts or _sha256(restored_db) != _sha256(backup_db):
        raise RuntimeError("Isolated restore drill did not match the verified backup")

    payload: dict[str, Any] = {
        "status": "verified",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "backup_directory": str(destination),
        "database": {
            **backup_facts,
            "bytes": backup_db.stat().st_size,
            "sha256": _sha256(backup_db),
            "restore_drill": "passed",
        },
        "assets": {},
        "runtime_files": _copy_runtime_files(root, destination / "runtime"),
        "excluded": ["data/admin_mirofish/scanner_runs"],
    }

    if include_assets:
        payload["assets"] = {
            "community_uploads": _copy_tree_verified(
                root / "data" / "uploads" / "community",
                destination / "community_uploads",
            ),
            "mirofish_workflows": _copy_tree_verified(
                root / "data" / "admin_mirofish" / "workflows",
                destination / "mirofish_workflows",
            ),
        }

    _write_manifest(destination / "manifest.json", payload)
    _restrict_windows_acl(destination)
    payload["retention_removed"] = _prune_old_backups(
        output_root,
        retention_days,
        destination,
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(r"C:\bitman_marketfloww"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--prefix", choices=("durable", "predeploy"), default="durable")
    parser.add_argument("--include-assets", action="store_true")
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    output_root = args.output_root or args.root / "backups"
    try:
        result = create_backup(
            args.root,
            output_root,
            args.prefix,
            args.include_assets,
            args.retention_days,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    safe_summary = {
        "status": result["status"],
        "backup_directory": result["backup_directory"],
        "database": {
            "quick_check": result["database"]["quick_check"],
            "foreign_key_violations": result["database"]["foreign_key_violations"],
            "table_counts": result["database"]["table_counts"],
            "bytes": result["database"]["bytes"],
            "restore_drill": result["database"]["restore_drill"],
        },
        "assets": result["assets"],
        "runtime_files": result["runtime_files"],
        "retention_removed": result["retention_removed"],
    }
    print(json.dumps(safe_summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
