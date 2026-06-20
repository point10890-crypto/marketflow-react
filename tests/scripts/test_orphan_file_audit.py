import sqlite3


def _prepare_repo(tmp_path):
    repo = tmp_path
    data_dir = repo / "data"
    upload_dir = data_dir / "uploads" / "community"
    upload_dir.mkdir(parents=True)
    db_file = data_dir / "users.db"
    con = sqlite3.connect(str(db_file))
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            title TEXT,
            file_url TEXT,
            file_name TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    con.commit()
    con.close()
    return repo, upload_dir, db_file


def test_orphan_file_audit_reports_zero_when_files_exist(monkeypatch, tmp_path):
    import orphan_file_audit

    repo, upload_dir, db_file = _prepare_repo(tmp_path)
    (upload_dir / "present.pdf").write_text("ok", encoding="utf-8")
    con = sqlite3.connect(str(db_file))
    con.execute(
        "INSERT INTO posts (id, title, file_url, file_name) VALUES (1, 'present', '/api/community/uploads/present.pdf', 'present.pdf')"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(orphan_file_audit, "REPO_ROOT", repo)

    payload = orphan_file_audit.run_audit()

    assert payload["ok"] is True
    assert payload["scanned"] == 1
    assert payload["total"] == 0
    assert payload["orphans"] == []


def test_orphan_file_audit_reports_missing_files(monkeypatch, tmp_path):
    import orphan_file_audit

    repo, _upload_dir, db_file = _prepare_repo(tmp_path)
    con = sqlite3.connect(str(db_file))
    con.execute(
        "INSERT INTO posts (id, title, file_url, file_name, created_at) VALUES (7, 'missing', '/api/community/uploads/missing.zip', 'missing.zip', '2026-06-20')"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(orphan_file_audit, "REPO_ROOT", repo)

    payload = orphan_file_audit.run_audit(max_orphans=10)

    assert payload["ok"] is True
    assert payload["scanned"] == 1
    assert payload["total"] == 1
    assert payload["orphans"][0]["post_id"] == 7
    assert payload["orphans"][0]["stored_filename"] == "missing.zip"
