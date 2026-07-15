"""Read-only MiniPC pre-deployment audit for durable MarketFlow data.

The report intentionally contains counts, timestamps, sizes, and integrity
results only. It never prints member names, email addresses, password hashes,
tokens, post content, or filenames from member uploads.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path


def emit(section: str, **values: object) -> None:
    fields = "|".join(f"{key}={value}" for key, value in values.items())
    print(f"{section}|{fields}", flush=True)


def connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def scalar(connection: sqlite3.Connection, query: str) -> object:
    return connection.execute(query).fetchone()[0]


def audit_database(root: Path) -> None:
    path = root / "data" / "users.db"
    for suffix, label in (("", "db"), ("-wal", "wal"), ("-shm", "shm")):
        candidate = Path(str(path) + suffix)
        stat = candidate.stat() if candidate.is_file() else None
        emit(
            "DB_FILE",
            kind=label,
            exists=int(stat is not None),
            bytes=stat.st_size if stat else 0,
            mtime_ns=stat.st_mtime_ns if stat else 0,
        )
    if not path.is_file():
        emit("DB", ready=0, reason="users_db_missing")
        return

    connection = connect_read_only(path)
    connection.execute("PRAGMA query_only=ON")
    emit(
        "DB",
        journal_mode=scalar(connection, "PRAGMA journal_mode"),
        quick_check=scalar(connection, "PRAGMA quick_check"),
    )
    foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    emit("DB", foreign_key_violations=len(foreign_key_violations))
    violation_groups = collections.Counter(
        (str(row[0]), str(row[2]), str(row[3])) for row in foreign_key_violations
    )
    for (table, parent, foreign_key_id), count in sorted(violation_groups.items()):
        emit(
            "FK_VIOLATION_GROUP",
            table=table,
            parent=parent,
            foreign_key_id=foreign_key_id,
            count=count,
        )

    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    emit("DB", tables=",".join(tables))
    for table in tables:
        safe_table = table.replace('"', '""')
        emit("ROW_COUNT", table=table, count=scalar(connection, f'SELECT COUNT(*) FROM "{safe_table}"'))

    required_user_columns = {
        "id", "email", "password_hash", "name", "status", "tier", "role",
        "pro_expires_at", "aibain_enabled", "aibain_expires_at", "pro_paused_at",
    }
    user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    emit(
        "USER_SCHEMA",
        required_present=int(required_user_columns <= user_columns),
        missing=",".join(sorted(required_user_columns - user_columns)),
    )

    aggregates = {
        "role": "SELECT COALESCE(role,'NULL'), COUNT(*) FROM users GROUP BY role ORDER BY role",
        "status": "SELECT COALESCE(status,'NULL'), COUNT(*) FROM users GROUP BY status ORDER BY status",
        "tier": "SELECT COALESCE(tier,'NULL'), COUNT(*) FROM users GROUP BY tier ORDER BY tier",
    }
    if table_exists(connection, "subscription_requests"):
        aggregates["subscription_status"] = (
            "SELECT COALESCE(status,'NULL'), COUNT(*) "
            "FROM subscription_requests GROUP BY status ORDER BY status"
        )
    for name, query in aggregates.items():
        rows = connection.execute(query).fetchall()
        emit("AGGREGATE", name=name, values=json.dumps(rows, separators=(",", ":")))

    checks = {
        "users_missing_email": "SELECT COUNT(*) FROM users WHERE email IS NULL OR trim(email)=''",
        "users_duplicate_email": (
            "SELECT COUNT(*) FROM (SELECT lower(email) FROM users "
            "GROUP BY lower(email) HAVING COUNT(*) > 1)"
        ),
        "users_missing_password_hash": (
            "SELECT COUNT(*) FROM users WHERE password_hash IS NULL OR trim(password_hash)=''"
        ),
        "users_non_bcrypt_hash": "SELECT COUNT(*) FROM users WHERE password_hash NOT LIKE '$2%'",
        "approved_paid_members": (
            "SELECT COUNT(*) FROM users "
            "WHERE status='approved' AND tier IN ('pro','premium')"
        ),
        "admins": "SELECT COUNT(*) FROM users WHERE role='admin'",
        "aibain_enabled": "SELECT COUNT(*) FROM users WHERE aibain_enabled=1",
        "approved_pro_past_expiry": (
            "SELECT COUNT(*) FROM users WHERE status='approved' AND tier='pro' "
            "AND pro_expires_at IS NOT NULL AND pro_expires_at < CURRENT_TIMESTAMP "
            "AND pro_paused_at IS NULL"
        ),
        "aibain_enabled_past_expiry": (
            "SELECT COUNT(*) FROM users WHERE aibain_enabled=1 "
            "AND aibain_expires_at IS NOT NULL AND aibain_expires_at < CURRENT_TIMESTAMP"
        ),
        "paused_without_active_aibain": (
            "SELECT COUNT(*) FROM users WHERE pro_paused_at IS NOT NULL AND "
            "(aibain_enabled=0 OR (aibain_expires_at IS NOT NULL "
            "AND aibain_expires_at < CURRENT_TIMESTAMP))"
        ),
        "latest_user_created_at": "SELECT COALESCE(MAX(created_at),'') FROM users",
    }
    optional_checks = {
        "latest_subscription_created_at": (
            "subscription_requests", "SELECT COALESCE(MAX(created_at),'') FROM subscription_requests"
        ),
        "latest_post_created_at": ("posts", "SELECT COALESCE(MAX(created_at),'') FROM posts"),
        "latest_audit_created_at": (
            "admin_audit_log", "SELECT COALESCE(MAX(created_at),'') FROM admin_audit_log"
        ),
        "orphan_subscription_users": (
            "subscription_requests",
            "SELECT COUNT(*) FROM subscription_requests s "
            "LEFT JOIN users u ON u.id=s.user_id WHERE u.id IS NULL",
        ),
        "orphan_post_authors": (
            "posts",
            "SELECT COUNT(*) FROM posts p LEFT JOIN users u ON u.id=p.author_id WHERE u.id IS NULL",
        ),
        "orphan_post_boards": (
            "posts",
            "SELECT COUNT(*) FROM posts p LEFT JOIN boards b ON b.id=p.board_id WHERE b.id IS NULL",
        ),
        "orphan_comment_posts": (
            "comments",
            "SELECT COUNT(*) FROM comments c LEFT JOIN posts p ON p.id=c.post_id WHERE p.id IS NULL",
        ),
        "orphan_comment_authors": (
            "comments",
            "SELECT COUNT(*) FROM comments c LEFT JOIN users u ON u.id=c.author_id WHERE u.id IS NULL",
        ),
    }
    for name, query in checks.items():
        emit("DB_CHECK", name=name, value=scalar(connection, query))
    for name, (required_table, query) in optional_checks.items():
        if table_exists(connection, required_table):
            emit("DB_CHECK", name=name, value=scalar(connection, query))

    audit_community_files(root, connection)
    connection.close()


def audit_community_files(root: Path, connection: sqlite3.Connection) -> None:
    upload_root = root / "data" / "uploads" / "community"
    actual_files = {entry.name for entry in upload_root.iterdir() if entry.is_file()} if upload_root.is_dir() else set()
    references_by_source: dict[str, set[str]] = {
        "post_images": set(),
        "post_file_url": set(),
        "post_content": set(),
    }
    if table_exists(connection, "post_images"):
        references_by_source["post_images"].update(
            str(row[0]) for row in connection.execute("SELECT filename FROM post_images") if row[0]
        )
    if table_exists(connection, "posts"):
        for file_url, content in connection.execute("SELECT file_url, content FROM posts"):
            if file_url:
                references_by_source["post_file_url"].add(str(file_url).rsplit("/", 1)[-1])
            if content:
                references_by_source["post_content"].update(
                    match.rsplit("/", 1)[-1]
                    for match in re.findall(r"/api/community/uploads/[0-9A-Za-z_.-]+", str(content))
                )
    references = set().union(*references_by_source.values())
    emit(
        "COMMUNITY_FILES",
        directory_exists=int(upload_root.is_dir()),
        files=len(actual_files),
        db_references=len(references),
        missing_references=len(references - actual_files),
        unreferenced_files=len(actual_files - references),
        bytes=sum((upload_root / name).stat().st_size for name in actual_files),
    )
    for source, source_references in references_by_source.items():
        emit(
            "COMMUNITY_REFERENCE_SOURCE",
            source=source,
            references=len(source_references),
            missing=len(source_references - actual_files),
        )


def audit_backups(root: Path) -> None:
    backup_roots = [root / "backups", root / "backup", root / "data" / "backups", root / "deploy" / "backups"]
    db_candidates: list[Path] = []
    zip_db_members = 0
    total_files = 0
    latest_mtime_ns = 0
    for backup_root in backup_roots:
        if not backup_root.is_dir():
            continue
        for path in backup_root.rglob("*"):
            if not path.is_file():
                continue
            total_files += 1
            latest_mtime_ns = max(latest_mtime_ns, path.stat().st_mtime_ns)
            lower_name = path.name.lower()
            if lower_name.endswith((".db", ".sqlite", ".sqlite3")) or "users.db" in lower_name:
                db_candidates.append(path)
            if lower_name.endswith(".zip"):
                try:
                    with zipfile.ZipFile(path) as archive:
                        zip_db_members += sum(
                            1
                            for name in archive.namelist()
                            if name.lower().endswith(("users.db", ".sqlite", ".sqlite3"))
                        )
                except (OSError, zipfile.BadZipFile):
                    pass
    emit(
        "BACKUPS",
        roots_present=sum(1 for path in backup_roots if path.is_dir()),
        files=total_files,
        latest_mtime_ns=latest_mtime_ns,
        sqlite_candidates=len(db_candidates),
        sqlite_zip_members=zip_db_members,
    )
    for index, path in enumerate(sorted(db_candidates, key=lambda item: item.stat().st_mtime_ns, reverse=True)[:5], 1):
        try:
            connection = connect_read_only(path)
            connection.execute("PRAGMA query_only=ON")
            integrity = scalar(connection, "PRAGMA quick_check")
            users = scalar(connection, "SELECT COUNT(*) FROM users") if table_exists(connection, "users") else -1
            subscriptions = (
                scalar(connection, "SELECT COUNT(*) FROM subscription_requests")
                if table_exists(connection, "subscription_requests") else -1
            )
            connection.close()
            emit(
                "BACKUP_DB",
                index=index,
                age_order=index,
                bytes=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
                integrity=integrity,
                users=users,
                subscriptions=subscriptions,
            )
        except sqlite3.Error as exc:
            emit("BACKUP_DB", index=index, integrity="error", error=type(exc).__name__)


def audit_workflows(root: Path) -> None:
    workflow_root = root / "data" / "admin_mirofish" / "workflows"
    workflow_dirs = [entry for entry in os.scandir(workflow_root) if entry.is_dir() and not entry.name.startswith("_")] if workflow_root.is_dir() else []
    statuses: collections.Counter[str] = collections.Counter()
    workflow_json_errors = 0
    outcomes_present = 0
    outcomes_errors = 0
    latest_mtime_ns = 0
    latest_status = ""
    running_age_buckets: collections.Counter[str] = collections.Counter()
    now_ns = time.time_ns()
    for entry in workflow_dirs:
        workflow_path = Path(entry.path) / "workflow.json"
        if not workflow_path.is_file():
            workflow_json_errors += 1
            continue
        stat = workflow_path.stat()
        try:
            payload = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
            status = str(payload.get("status") or payload.get("state") or "unknown")
            statuses[status] += 1
            if status == "running":
                age_hours = max(0.0, (now_ns - stat.st_mtime_ns) / 3_600_000_000_000)
                if age_hours < 1:
                    running_age_buckets["lt_1h"] += 1
                elif age_hours < 24:
                    running_age_buckets["1h_to_24h"] += 1
                else:
                    running_age_buckets["gte_24h"] += 1
            if stat.st_mtime_ns >= latest_mtime_ns:
                latest_mtime_ns = stat.st_mtime_ns
                latest_status = status
        except (OSError, ValueError, TypeError):
            workflow_json_errors += 1
        outcomes_path = Path(entry.path) / "outcomes.json"
        if outcomes_path.is_file():
            outcomes_present += 1
            try:
                json.loads(outcomes_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                outcomes_errors += 1
    emit(
        "WORKFLOWS",
        directories=len(workflow_dirs),
        statuses=json.dumps(sorted(statuses.items()), separators=(",", ":")),
        workflow_json_errors=workflow_json_errors,
        outcomes_present=outcomes_present,
        outcomes_errors=outcomes_errors,
        latest_mtime_ns=latest_mtime_ns,
        latest_status=latest_status,
        running_age_buckets=json.dumps(sorted(running_age_buckets.items()), separators=(",", ":")),
    )

    scanner_root = root / "data" / "admin_mirofish" / "scanner_runs"
    scanner_dirs = 0
    latest_scanner_mtime_ns = 0
    if scanner_root.is_dir():
        for entry in os.scandir(scanner_root):
            if entry.is_dir():
                scanner_dirs += 1
                latest_scanner_mtime_ns = max(latest_scanner_mtime_ns, entry.stat().st_mtime_ns)
    emit(
        "SCANNER_RUNS",
        directories=scanner_dirs,
        latest_mtime_ns=latest_scanner_mtime_ns,
    )

    for relative in (
        "data/scheduler_last_run.json",
        "data/jongga_v2_latest.json",
        "data/admin_mirofish/workflows/_state/scanner_event_state.json",
    ):
        path = root / relative
        if not path.is_file():
            emit("JSON_ARTIFACT", path=relative, exists=0, valid=0)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            valid = isinstance(payload, (dict, list))
        except (OSError, ValueError, TypeError):
            valid = False
        emit(
            "JSON_ARTIFACT",
            path=relative,
            exists=1,
            valid=int(valid),
            bytes=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,
        )


def audit_capacity(root: Path) -> None:
    total, used, free = shutil.disk_usage(root)
    emit("DISK", total_bytes=total, used_bytes=used, free_bytes=free, free_pct=round(free * 100 / total, 2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(r"C:\bitman_marketfloww"))
    args = parser.parse_args()
    root = args.root.resolve()
    audit_capacity(root)
    audit_database(root)
    audit_backups(root)
    audit_workflows(root)


if __name__ == "__main__":
    main()
