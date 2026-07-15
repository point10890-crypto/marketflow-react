import json
import time

from flask import Flask

from app.routes import wave as wave_route
from engine import jubjub_analyzer


def test_wave_latest_does_not_wait_for_every_halted_check(tmp_path, monkeypatch):
    signals = [
        {
            "ticker": f"{index:06d}",
            "best_pattern": {
                "confidence": 80,
                "pattern_class": "W",
            },
        }
        for index in range(20)
    ]
    (tmp_path / "wave_screener_latest.json").write_text(
        json.dumps(
            {
                "date": "2026-07-15",
                "signal_count": len(signals),
                "signals": signals,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(wave_route, "_WAVE_DIR", str(tmp_path))
    monkeypatch.setattr(wave_route, "_HALTED_FILTER_BUDGET_SEC", 0.05)
    wave_route._screener_cache.clear()

    def slow_check(_ticker):
        time.sleep(0.25)
        return False

    monkeypatch.setattr(jubjub_analyzer, "_is_halted_or_invalid", slow_check)
    app = Flask(__name__)
    app.register_blueprint(wave_route.wave_bp, url_prefix="/api/wave")

    started = time.perf_counter()
    response = app.test_client().get("/api/wave/screener/latest?limit=20")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.5
    payload = response.get_json()
    assert payload["signal_count"] == 20
    assert payload["halted_filter_complete"] is False
    assert payload["halted_filter_checked"] == 0


def test_wave_jubjub_uses_same_halted_check_budget(tmp_path, monkeypatch):
    signals = [
        {
            "ticker": f"{index:06d}",
            "price": 100,
            "best_pattern": {
                "confidence": 85,
                "pattern_class": "W",
                "completion_pct": 90,
                "neckline_price": 101,
                "neckline_distance_pct": -1,
                "volume_confirmed": True,
                "bullish_bias": 0.7,
                "points": [],
            },
        }
        for index in range(20)
    ]
    (tmp_path / "wave_screener_latest.json").write_text(
        json.dumps({"signal_count": len(signals), "signals": signals}),
        encoding="utf-8",
    )
    monkeypatch.setattr(wave_route, "_WAVE_DIR", str(tmp_path))
    monkeypatch.setattr(wave_route, "_HALTED_FILTER_BUDGET_SEC", 0.05)
    wave_route._screener_cache.clear()

    def slow_check(_ticker):
        time.sleep(0.25)
        return False

    monkeypatch.setattr(jubjub_analyzer, "_is_halted_or_invalid", slow_check)
    app = Flask(__name__)
    app.register_blueprint(wave_route.wave_bp, url_prefix="/api/wave")

    started = time.perf_counter()
    response = app.test_client().get("/api/wave/jubjub?min_score=60&limit=20")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.5
    payload = response.get_json()
    assert payload["jubjub_count"] == 20
    assert payload["halted_filter_complete"] is False
    assert payload["halted_filter_checked"] == 0
