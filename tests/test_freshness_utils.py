import json
import os
from datetime import datetime, timedelta

from app.utils.freshness import attach_freshness, build_freshness


def test_build_freshness_uses_content_timestamp_over_recent_mtime(tmp_path):
    source = tmp_path / "vcp_kr_latest.json"
    old_ts = (datetime.now() - timedelta(days=30)).isoformat()
    payload = {"metadata": {"generated_at": old_ts}, "signals": []}
    source.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(source, None)

    freshness = build_freshness(str(source), payload, max_age_hours=96)

    assert freshness["basis"] == "content_timestamp"
    assert freshness["is_stale"] is True
    assert "expired" in freshness["stale_reasons"]


def test_attach_freshness_marks_current_payload_fresh(tmp_path):
    source = tmp_path / "vcp_crypto_latest.json"
    payload = {"metadata": {"generated_at": datetime.now().isoformat()}, "signals": []}
    source.write_text(json.dumps(payload), encoding="utf-8")

    data = attach_freshness(payload, str(source), max_age_hours=12)

    assert data["metadata"]["freshness"]["is_stale"] is False
