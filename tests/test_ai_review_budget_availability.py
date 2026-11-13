"""Read-only review budget projections and preserved admission diagnostics."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.ai_routing import budget as budget_module
from app.services.ai_routing.budget import EvidenceReviewBudget
from app.services.ai_routing.contracts import RoutingRequest, TokenUsage
from app.services.ai_routing.providers import AdapterResponse
from app.services.ai_routing.router import AIRouter
from app.services.ai_routing.store import RoutingStore


NOW = datetime(2026, 11, 13, 23, 59, tzinfo=timezone.utc)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_BUDGET_USD', '1')
    monkeypatch.setattr(budget_module, '_utc_now_datetime', lambda: NOW)
    return EvidenceReviewBudget(RoutingStore(tmp_path / 'usage.sqlite3'))


def reserve(manager, identifier, **overrides):
    values = dict(request=RoutingRequest(operation='news_event_extract', prompt='Evidence',
        run_id=identifier, request_id=identifier), provider='anthropic',
        input_tokens=100, output_tokens=20, estimated_cost_usd=Decimal('0.1'),
        pricing_version='fixture')
    values.update(overrides)
    return manager.reserve_attempt(**values)


def test_missing_ledger_summary_does_not_create_directory_or_database(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '20')
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_BUDGET_USD', '0.5')
    path = tmp_path / 'missing' / 'usage.sqlite3'
    summary = EvidenceReviewBudget(RoutingStore(path)).daily_summary(now=NOW)
    assert summary['status'] == 'ok'
    assert summary['used_calls'] == 0 and summary['used_cost_usd'] == '0'
    assert summary['max_calls'] == 20 and summary['max_cost_usd'] == '0.5'
    assert summary['article_remaining_calls'] == 11
    assert summary['resets_at_utc'] == '2026-11-14T00:00:00+00:00'
    assert not path.parent.exists()
    assert json.loads(json.dumps(summary)) == summary


def test_summary_uses_actuals_holds_all_providers_and_only_current_day(manager):
    paid = reserve(manager, 'paid')
    manager.settle(paid.reservation_id, TokenUsage(input_tokens=10, output_tokens=2),
                   actual_cost_usd=Decimal('0.02'))
    zero = reserve(manager, 'zero', provider='deepseek')
    manager.settle(zero.reservation_id, TokenUsage(input_tokens=0, output_tokens=0),
                   actual_cost_usd=Decimal('0'))
    reserve(manager, 'uncertain', provider='openai', estimated_cost_usd=Decimal('0.3'))
    released = reserve(manager, 'released')
    manager.release_claimed(released.reservation_id)
    old = reserve(manager, 'previous-day')
    with manager.store.transaction(write=True) as connection:
        connection.execute('UPDATE budget_reservations SET billing_day_utc=? WHERE reservation_id=?',
                           ('2026-11-12', old.reservation_id))
        before = list(connection.execute('SELECT * FROM budget_reservations'))
    summary = EvidenceReviewBudget(RoutingStore(manager.store.db_path)).daily_summary(now=NOW)
    assert summary['status'] == 'ok'
    assert summary['used_calls'] == 3
    assert Decimal(summary['used_cost_usd']) == Decimal('0.32')
    assert Decimal(summary['remaining_cost_usd']) == Decimal('0.68')
    assert summary['remaining_calls'] == 97
    assert summary['article_remaining_calls'] == 88
    assert summary['unknown_cost_rows'] == 0 and summary['hold_reason'] is None
    with manager.store.transaction() as connection:
        assert list(connection.execute('SELECT * FROM budget_reservations')) == before
    assert not any(key in summary for key in ('request_id', 'run_id', 'owner_token'))


@pytest.mark.parametrize('bad_cost', [None, 'invalid', 'NaN', '-1'])
def test_unknown_or_invalid_cost_never_reports_spendable_usd(manager, bad_cost):
    permit = reserve(manager, 'unknown')
    with manager.store.transaction(write=True) as connection:
        connection.execute('UPDATE budget_reservations SET reserved_cost_usd=? WHERE reservation_id=?',
                           (bad_cost, permit.reservation_id))
    summary = manager.daily_summary(now=NOW)
    assert summary['used_calls'] == 1
    assert summary['unknown_cost_rows'] == 1
    assert summary['used_cost_usd'] is None and summary['remaining_cost_usd'] is None
    assert summary['hold_reason'] == 'daily_cost_unknown'


def test_legacy_schema_is_not_migrated_and_unreadable_ledger_fails_closed(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE budget_reservations (request_id TEXT)')
    original = path.read_bytes()
    summary = EvidenceReviewBudget(RoutingStore(path)).daily_summary(now=NOW)
    assert summary['status'] == 'unavailable'
    assert summary['hold_reason'] == 'ledger_unavailable'
    assert summary['used_calls'] is None and summary['article_remaining_calls'] is None
    assert path.read_bytes() == original


@pytest.mark.parametrize('calls,cost,expected', [
    ('0', '1', 'daily_call_cap'),
    ('100', '0', 'daily_usd_cap'),
    ('9', '1', 'top3_capacity_reserved'),
])
def test_summary_distinguishes_article_capacity_holds(tmp_path, monkeypatch, calls, cost, expected):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', calls)
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_BUDGET_USD', cost)
    summary = EvidenceReviewBudget(RoutingStore(tmp_path / 'absent.sqlite3')).daily_summary(now=NOW)
    assert summary['hold_reason'] == expected


class LocalAdapter:
    endpoint = 'fixture.generate'

    def __init__(self):
        self.calls = 0

    def generate(self, request, *, model, max_output_tokens):
        self.calls += 1
        return AdapterResponse('{}', TokenUsage(input_tokens=10, output_tokens=2))


def test_router_keeps_specific_article_hold_and_generic_public_reason(manager, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '9')
    adapter = LocalAdapter()
    result = AIRouter({'anthropic': adapter}, store=manager.store).route_text(RoutingRequest(
        operation='news_event_extract', prompt='Evidence', request_id='article',
        run_id='article', caller_endpoint='scheduled_evidence_review'))
    assert result.fallback_reason == 'budget_exhausted'
    assert result.budget_hold_reason == 'top3_capacity_reserved'
    assert adapter.calls == 0


def test_new_run_rechecks_admission_but_retains_paid_request_fence(manager, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '0')
    adapter = LocalAdapter()
    request = RoutingRequest(operation='news_event_extract', prompt='Evidence',
                             request_id='stable', run_id='first')
    router = AIRouter({'anthropic': adapter}, store=manager.store)
    blocked = router.route_text(request)
    assert blocked.budget_hold_reason == 'daily_hard_cap'
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    assert router.route_text(request).fallback_reason == 'budget_exhausted'
    succeeded = router.route_text(replace(request, run_id='after-reset'))
    assert succeeded.text == '{}' and succeeded.budget_hold_reason is None
    replay = router.route_text(replace(request, run_id='another-run'))
    assert replay.budget_hold_reason == 'duplicate_request'
    assert adapter.calls == 1


def test_router_preserves_additional_openai_budget_denial(manager, monkeypatch):
    monkeypatch.setenv('AI_OPENAI_DAILY_BUDGET_USD', '0.000001')
    adapter = LocalAdapter()
    result = AIRouter({'openai': adapter}, store=manager.store).route_text(RoutingRequest(
        operation='news_event_extract', prompt='Evidence', request_id='openai', run_id='openai'))
    assert result.fallback_reason == 'budget_exhausted'
    assert result.budget_hold_reason == 'daily_hard_cap'
    assert adapter.calls == 0
    assert manager.daily_summary(now=NOW)['used_calls'] == 0
