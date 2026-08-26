# -*- coding: utf-8 -*-
"""P1 정밀도 측정 기반 복구 — 비용 차감(net) 지표 + intelligence 아티팩트 재빌드.

마스터 플랜 P1 (docs/superpowers/specs/2026-08-24-goal-definition-master-plan.md):
  P1-a: top3_metrics/interaction_map 이 "파일 없을 때만 빌드"되어 정체 → 재빌드 경로
  P1-b: 검출/페이퍼 성과가 비용 미차감(gross) → 왕복 0.23% + 슬리피지 net 병기
"""
import json

import pytest


# ─── costs 공용 모듈 ─────────────────────────────────────────

def test_round_trip_cost_default(monkeypatch):
    from app.services.mirofish import costs
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    assert costs.round_trip_cost_pct() == pytest.approx(0.23)


def test_round_trip_cost_with_slippage_env(monkeypatch):
    from app.services.mirofish import costs
    monkeypatch.setenv('MIROFISH_SLIPPAGE_PCT', '0.10')
    assert costs.round_trip_cost_pct() == pytest.approx(0.33)


def test_round_trip_cost_bad_env_falls_back(monkeypatch):
    from app.services.mirofish import costs
    monkeypatch.setenv('MIROFISH_SLIPPAGE_PCT', 'not-a-number')
    assert costs.round_trip_cost_pct() == pytest.approx(0.23)


def test_net_return_pct(monkeypatch):
    from app.services.mirofish import costs
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    assert costs.net_return_pct(2.60) == pytest.approx(2.37)


# ─── detection_lab: gross 지표에 net 블록 병기 ────────────────

def _trade(ret, phase='leader_market', exit_date='2026-08-01', reason='target'):
    return {'return_pct': ret, 'exit_date': exit_date, 'exit_reason': reason,
            'phase': phase, 'holding_days': 3}


def test_detection_lab_metrics_net_block(monkeypatch):
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    from app.services.mirofish import detection_lab as dl
    m = dl._metrics([_trade(8.0), _trade(-7.0, reason='stop')])
    net = m['net']
    assert net['round_trip_cost_pct'] == pytest.approx(0.23)
    assert net['expectancy_pct'] == pytest.approx(0.5 - 0.23)
    assert net['win_rate_pct'] == 50.0
    assert net['profit_factor'] == pytest.approx((8.0 - 0.23) / (7.0 + 0.23), abs=0.01)
    # 기존 gross 필드는 그대로 유지 (net 은 병기이지 대체가 아니다)
    assert m['expectancy_pct'] == pytest.approx(0.5)
    ph = m['by_phase']['leader_market']
    assert ph['net_expectancy_pct'] == pytest.approx(ph['expectancy_pct'] - 0.23)


def test_detection_lab_net_flips_marginal_win(monkeypatch):
    """gross 로는 승리(+0.2%)지만 비용 후 패배 — net 승률이 이를 드러내야 한다."""
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    from app.services.mirofish import detection_lab as dl
    m = dl._metrics([_trade(0.2)])
    assert m['win_rate_pct'] == 100.0
    assert m['net']['win_rate_pct'] == 0.0


def test_detection_lab_metrics_net_empty():
    from app.services.mirofish import detection_lab as dl
    m = dl._metrics([])
    assert m['net']['expectancy_pct'] == 0.0
    assert m['net']['round_trip_cost_pct'] > 0


# ─── paper performance_summary: net 병기 ─────────────────────

def test_paper_performance_summary_net(monkeypatch):
    monkeypatch.delenv('MIROFISH_SLIPPAGE_PCT', raising=False)
    from app.services.mirofish import paper_positions as pp
    monkeypatch.setattr(pp, 'load_ledger', lambda: {
        'pending': [], 'open': [],
        'closed': [{'exit_date': '2026-08-20', 'return_pct': 8.0}],
    })
    s = pp.performance_summary(days=30, today='2026-08-24')
    assert s['round_trip_cost_pct'] == pytest.approx(0.23)
    assert s['net_avg_return_pct'] == pytest.approx(8.0 - 0.23)
    assert s['net_cumulative_return_pct'] == pytest.approx(8.0 - 0.23)
    # gross 유지
    assert s['avg_return_pct'] == pytest.approx(8.0)


# ─── top3_metrics_summary: 신선도(generated_at/stale) 노출 ────

def test_top3_summary_exposes_freshness_fresh(monkeypatch, tmp_path):
    from app.services.mirofish.intelligence import top3_metrics
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    top3_metrics.build_top3_metrics(runs=[], write=True)
    s = top3_metrics.top3_metrics_summary()
    assert s['generated_at']
    assert s['stale'] is False


def test_top3_summary_stale_when_old(monkeypatch, tmp_path):
    from app.services.mirofish.intelligence import top3_metrics
    path = tmp_path / 't3.json'
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(path))
    path.write_text(json.dumps({
        'schema_version': 'mirofish.top3_metrics.v1',
        'generated_at': '2026-06-20T00:00:00+00:00',
        'evaluated_runs': 3, 'qualified_runs': 0,
        'total_evaluated_items': 9, 'insufficient': True,
        'pooled': {}, 'macro': {},
    }), encoding='utf-8')
    s = top3_metrics.top3_metrics_summary()
    assert s['stale'] is True
    assert s['generated_at'] == '2026-06-20T00:00:00+00:00'


def test_top3_summary_missing_artifact_is_stale(monkeypatch, tmp_path):
    from app.services.mirofish.intelligence import top3_metrics
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 'none.json'))
    monkeypatch.setattr(top3_metrics, 'build_top3_metrics',
                        lambda **kw: (_ for _ in ()).throw(RuntimeError('no data')))
    s = top3_metrics.top3_metrics_summary()
    assert s['stale'] is True


# ─── agent_actions: refresh_intelligence 액션 ────────────────

def test_refresh_intelligence_action_rebuilds_artifacts(monkeypatch):
    from app.services.mirofish import agent_actions
    from app.services.mirofish.intelligence import top3_metrics as t3
    from app.services.mirofish.intelligence import interactions as inter
    calls = []
    monkeypatch.setattr(t3, 'build_top3_metrics',
                        lambda **kw: calls.append('t3') or {'evaluated_runs': 7})
    monkeypatch.setattr(inter, 'build_interaction_map',
                        lambda **kw: calls.append('imap') or {'evaluated_count': 42})
    res = agent_actions.execute_decisions(
        [{'action': 'refresh_intelligence', 'reason': 'stale artifact'}], dry_run=False)
    assert res[0]['action'] == 'refresh_intelligence'
    assert res[0]['status'] == 'applied'
    assert calls == ['t3', 'imap']


# ─── run_maintenance: 정체 시 재빌드 결정 발행 ────────────────

def _fresh_obs(top3):
    return {
        'backtest': {'stale': False},
        'outcome': {'evaluated_count': 999},
        'top3_metrics': top3,
    }


def test_maintenance_refreshes_stale_intelligence(monkeypatch):
    from app.services.mirofish import alpha_brain_agent as agent
    from app.services.mirofish.intelligence import top3_metrics as t3
    from app.services.mirofish.intelligence import interactions as inter
    monkeypatch.setattr(t3, 'build_top3_metrics', lambda **kw: {'evaluated_runs': 1})
    monkeypatch.setattr(inter, 'build_interaction_map', lambda **kw: {'evaluated_count': 1})
    results = agent.run_maintenance(_fresh_obs({'stale': True}), dry_run=True)
    assert any(r.get('action') == 'refresh_intelligence' and r.get('status') == 'applied'
               for r in results)


def test_maintenance_skips_fresh_intelligence():
    from app.services.mirofish import alpha_brain_agent as agent
    results = agent.run_maintenance(_fresh_obs({'stale': False, 'evaluated_runs': 5}), dry_run=True)
    assert not any(r.get('action') == 'refresh_intelligence' for r in results)
