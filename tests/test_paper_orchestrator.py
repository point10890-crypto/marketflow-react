# -*- coding: utf-8 -*-
"""오케스트레이터 회귀 — 4국면 매핑과 스케줄 등록을 고정한다."""
import inspect
import json

import pytest

import scheduler
from app.services.mirofish import paper_orchestrator as po
from app.services.mirofish.intelligence import regime


@pytest.fixture()
def timeline(tmp_path, monkeypatch):
    path = tmp_path / 'regime_timeline.json'
    monkeypatch.setattr(regime, 'REGIME_TIMELINE_PATH', str(path))

    def write(points):
        by_date = {d: {'breadth': b, 'regime': r} for d, b, r in points}
        path.write_text(json.dumps({'by_date': by_date}), encoding='utf-8')
    return write


def _days(*breadths):
    """breadth 시퀀스를 (date, breadth, regime) 로 — regime 은 임계값으로 산출."""
    out = []
    for i, b in enumerate(breadths):
        regime_label = 'RISK_ON' if b >= 0.60 else 'RISK_OFF' if b <= 0.40 else 'NEUTRAL'
        out.append((f'2026-08-{i + 1:02d}', b, regime_label))
    return out


def test_phase_uptrend_broadening(timeline):
    timeline(_days(0.61, 0.62, 0.63, 0.64, 0.65, 0.66))
    assert po.market_phase()['phase'] == 'uptrend_broadening'


def test_phase_downtrend(timeline):
    timeline(_days(0.38, 0.37, 0.36, 0.35, 0.35, 0.34))
    assert po.market_phase()['phase'] == 'downtrend'


def test_phase_rebound_early_from_risk_off(timeline):
    timeline(_days(0.30, 0.31, 0.32, 0.34, 0.36, 0.38))
    p = po.market_phase()
    assert p['phase'] == 'rebound_early'
    assert p['regime'] == 'RISK_OFF'


def test_phase_leader_market_neutral_flat(timeline):
    timeline(_days(0.50, 0.50, 0.51, 0.50, 0.50, 0.51))
    assert po.market_phase()['phase'] == 'leader_market'


def test_phase_survives_missing_timeline(tmp_path, monkeypatch):
    monkeypatch.setattr(regime, 'REGIME_TIMELINE_PATH', str(tmp_path / 'nope.json'))
    p = po.market_phase()
    assert p['phase'] in po.PHASE_LABEL


def test_alpha_timeline_registered_in_schedule():
    src = inspect.getsource(scheduler.Scheduler.setup_schedules)
    for key in ("'alpha_morning_top'", "'alpha_close_signals'", "'alpha_performance_brief'"):
        assert key in src, f'{key} 미등록'
    assert 'ALPHA_INTRADAY_TIMES' in src


def test_alpha_timeline_registered_in_missed_recovery():
    src = inspect.getsource(scheduler.check_and_run_missed_tasks)
    for key in ("'alpha_morning_top'", "'alpha_close_signals'", "'alpha_performance_brief'"):
        assert key in src, f'{key} 놓친-복구 미등록'


def test_close_cycle_message_includes_disclaimer():
    msg = po._close_cycle_message(
        entered=[{'name': 'SK텔레콤', 'symbol': '017670', 'entry_price': 106.0,
                  'target_price': 114.5, 'stop_price': 98.6}],
        exits=[],
    )
    assert '가상 매매' in msg and '투자 권유가 아닙니다' in msg
    assert 'SK텔레콤' in msg
