"""GET-only Alpha Core route contract tests."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from flask import Flask

import app.auth.decorators as auth
import app.routes.kr_alpha_core as route
from app.routes.kr_alpha_core import kr_alpha_core_bp


def _user(*, active: bool = True):
    return SimpleNamespace(
        status="approved",
        is_admin=False,
        is_aibain_active=active,
    )


def _app(monkeypatch) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-only"
    app.register_blueprint(kr_alpha_core_bp, url_prefix="/api/kr/alpha-core")
    monkeypatch.setattr(auth, "_get_current_user", lambda: _user())
    return app


def test_missing_database_is_graceful_and_get_does_not_create_it(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("ALPHACLAW_MODE", raising=False)
    missing = tmp_path / "not-created" / "paper.db"
    monkeypatch.setattr(route, "_paper_db_path", lambda: missing)
    client = _app(monkeypatch).test_client()

    responses = {
        name: client.get(f"/api/kr/alpha-core/{name}")
        for name in (
            "status",
            "portfolio",
            "risk-decisions",
            "hypotheses",
            "ledger",
        )
    }

    assert {response.status_code for response in responses.values()} == {200}
    assert responses["status"].get_json()["status"] == "not_initialized"
    assert responses["status"].get_json()["mode"] == "shadow"
    assert responses["status"].get_json()["ledger_environment"] == "paper"
    assert responses["status"].get_json()["risk_state"] == "BLOCK_NEW"
    assert responses["portfolio"].get_json()["cash_krw"] is None
    assert responses["risk-decisions"].get_json()["items"] == []
    assert responses["hypotheses"].get_json()["status"] == "not_implemented"
    assert responses["ledger"].get_json()["items"] == []
    assert all(
        response.headers["Cache-Control"]
        == "no-cache, no-store, must-revalidate"
        for response in responses.values()
    )
    assert not missing.exists()


def test_routes_project_reader_data_and_forward_bounded_filters(monkeypatch):
    monkeypatch.setenv("ALPHACLAW_MODE", "paper")
    calls = []

    class FakeReader:
        def status(self):
            return {
                "schema_version": "alpha_core.paper_ledger.status.v1",
                "environment": "paper",
                "mode": "paper",
                "kill_state": "NORMAL",
                "event_count": 8,
                "intent_counts": {"proposed": 2, "filled": 1},
                "risk_decision_counts": {"approved": 1, "rejected": 1},
                "fill_count": 1,
                "unreconciled_count": 1,
                "outbox_pending_count": 0,
                "last_event_at": "2026-08-24T01:00:00Z",
                "integrity": {"status": "ok", "ok": True},
            }

        def portfolio(self):
            return {
                "schema_version": "alpha_core.portfolio.v1",
                "cash_krw": 900_000,
                "reserved_cash_krw": 100_000,
                "positions": [],
                "gross_exposure_krw": 0,
                "net_exposure_krw": 0,
                "nav_krw": 900_000,
                "drawdown_pct": 0.0,
                "as_of": "2026-08-24T01:00:00Z",
            }

        def list_risk_decisions(self, **kwargs):
            calls.append(("risk", kwargs))
            return [
                {
                    "intent_id": "poi_1",
                    "decision": "approved",
                    "reason_codes": ["ALL_LIMITS_PASS"],
                }
            ]

        def list_events(self, **kwargs):
            calls.append(("events", kwargs))
            return [{"event_id": 8, "event_type": "risk.approved"}]

    monkeypatch.setattr(route, "_open_reader", lambda: FakeReader())
    client = _app(monkeypatch).test_client()

    status = client.get("/api/kr/alpha-core/status").get_json()
    portfolio = client.get("/api/kr/alpha-core/portfolio").get_json()
    decisions = client.get(
        "/api/kr/alpha-core/risk-decisions"
        "?limit=9999&decision=approved&intent_id=poi_1"
    ).get_json()
    ledger = client.get(
        "/api/kr/alpha-core/ledger"
        "?limit=25&after_id=7&aggregate_id=poi_1&event_type=risk.approved"
    ).get_json()

    assert status["counts"] == {
        "events": 8,
        "intents": 3,
        "risk_decisions": 2,
        "fills": 1,
        "unreconciled": 1,
        "outbox_pending": 0,
    }
    assert status["risk_state"] == "NORMAL"
    assert status["ledger_risk_state"] == "NORMAL"
    assert status["mode"] == "paper"
    shadow_status = route._status_projection(FakeReader().status(), mode="shadow")
    assert shadow_status["risk_state"] == "BLOCK_NEW"
    assert shadow_status["ledger_risk_state"] == "NORMAL"
    assert portfolio["cash"] == portfolio["cash_krw"] == 900_000
    assert portfolio["nav"] == 900_000
    assert decisions["count"] == ledger["count"] == 1
    assert decisions["items"][0]["reasons"] == ["ALL_LIMITS_PASS"]
    assert ledger["pending"] == 2
    assert ledger["reconcile_required"] is True
    assert calls == [
        (
            "risk",
            {"limit": 500, "decision": "approved", "intent_id": "poi_1"},
        ),
        (
            "events",
            {
                "limit": 25,
                "after_id": 7,
                "aggregate_id": "poi_1",
                "event_type": "risk.approved",
            },
        ),
    ]


def test_routes_require_aibain_and_expose_no_mutation_methods(monkeypatch):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-only"
    app.register_blueprint(kr_alpha_core_bp, url_prefix="/api/kr/alpha-core")
    monkeypatch.setattr(auth, "_get_current_user", lambda: _user(active=False))
    client = app.test_client()

    assert client.get("/api/kr/alpha-core/status").status_code == 403

    monkeypatch.setattr(auth, "_get_current_user", lambda: _user(active=True))
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/kr/alpha-core/status")
        assert response.status_code == 405

    rules = [
        rule
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/kr/alpha-core/")
    ]
    assert len(rules) == 5
    assert all(not ({"POST", "PUT", "PATCH", "DELETE"} & rule.methods) for rule in rules)


def test_live_mode_configuration_fails_closed_before_ledger_access(monkeypatch):
    monkeypatch.setenv("ALPHACLAW_MODE", "live")
    monkeypatch.setattr(
        route,
        "_open_reader",
        lambda: (_ for _ in ()).throw(AssertionError("must not open ledger")),
    )
    response = _app(monkeypatch).test_client().get("/api/kr/alpha-core/status")

    assert response.status_code == 503
    assert response.get_json()["status"] == "configuration_error"
    assert response.get_json()["risk_state"] == "BLOCK_NEW"
    assert response.get_json()["error"]["code"] == "ALPHA_CORE_MODE_INVALID"


def test_initialized_database_is_read_through_real_query_only_service(
    monkeypatch, tmp_path
):
    from app.services.alpha_core import PaperLedger

    monkeypatch.setenv("ALPHACLAW_MODE", "shadow")
    db_path = tmp_path / "paper.db"
    PaperLedger(db_path=db_path, mode="shadow").initialize()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    monkeypatch.setattr(route, "_paper_db_path", lambda: db_path)

    client = _app(monkeypatch).test_client()
    status = client.get("/api/kr/alpha-core/status")
    portfolio = client.get("/api/kr/alpha-core/portfolio")
    ledger = client.get("/api/kr/alpha-core/ledger")

    assert status.status_code == portfolio.status_code == ledger.status_code == 200
    assert status.get_json()["available"] is True
    assert status.get_json()["mode"] == "shadow"
    assert status.get_json()["ledger_environment"] == "paper"
    assert status.get_json()["quality"]["ok"] is True
    assert portfolio.get_json()["cash_krw"] is None
    assert ledger.get_json()["items"] == []
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_route_uses_alpha_core_default_database_path_contract(monkeypatch, tmp_path):
    from app.services.alpha_core import default_db_path

    configured = tmp_path / "isolated-paper.db"
    monkeypatch.setenv("ALPHA_CORE_DB_PATH", str(configured))

    assert route._paper_db_path() == default_db_path() == configured.resolve()
