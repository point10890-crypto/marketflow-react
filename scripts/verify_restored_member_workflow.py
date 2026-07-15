"""Boot MarketFlow against a restored DB copy and smoke-test member workflows.

Only counts and HTTP status codes are printed.  The script must never be pointed
at the live member database because app startup may run idempotent migrations.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    database = args.database.resolve()
    live_database = (root / "data" / "users.db").resolve()
    if database == live_database:
        raise SystemExit("Refusing to run restore verification against the live database")
    if not database.is_file():
        raise SystemExit(f"Restored database does not exist: {database}")

    os.environ["MARKETFLOW_BACKGROUND_WORKERS"] = "false"
    os.environ["WORKER_ALPHA_MONITOR_ENABLED"] = "0"
    sys.path.insert(0, str(root))
    os.chdir(root)

    from app import create_app
    from app.auth.decorators import generate_token
    from app.models.user import User

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "isolated-restore-drill-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
        }
    )
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        if admin is None:
            raise RuntimeError("Restored database has no admin account")
        token = generate_token(admin.id)
        counts = {
            "users": User.query.count(),
            "admins": User.query.filter_by(role="admin").count(),
        }

    headers = {"Authorization": f"Bearer {token}"}
    client = app.test_client()
    endpoint_statuses = {}
    for path in (
        "/api/auth/me",
        "/api/auth/subscription/status",
        "/api/admin/dashboard",
        "/api/admin/users?page=1&per_page=1",
        "/api/admin/subscriptions?page=1&per_page=1",
    ):
        response = client.get(path, headers=headers)
        endpoint_statuses[path] = response.status_code
        if response.status_code != 200:
            raise RuntimeError(f"Restore workflow smoke failed: {path} -> {response.status_code}")

    connection = sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro",
        uri=True,
        timeout=30,
    )
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()
    if quick_check != "ok":
        raise RuntimeError(f"Restored database quick_check failed: {quick_check}")

    print(
        json.dumps(
            {
                "status": "passed",
                "quick_check": quick_check,
                "counts": counts,
                "endpoints": endpoint_statuses,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
