import json
from datetime import datetime

import scheduler


def test_jongga_artifact_date_prevents_duplicate_restart_run(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.Config, "DATA_DIR", str(tmp_path))
    path = tmp_path / "jongga_v2_latest.json"
    path.write_text(json.dumps({"date": "2026-07-15", "signals": []}), encoding="utf-8")

    assert scheduler._jongga_artifact_is_today(datetime(2026, 7, 15, 16, 0)) is True
    assert scheduler._jongga_artifact_is_today(datetime(2026, 7, 16, 9, 0)) is False


def test_jongga_artifact_rejects_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.Config, "DATA_DIR", str(tmp_path))
    (tmp_path / "jongga_v2_latest.json").write_text("not-json", encoding="utf-8")

    assert scheduler._jongga_artifact_is_today(datetime(2026, 7, 15, 16, 0)) is False
