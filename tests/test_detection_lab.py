# -*- coding: utf-8 -*-
"""Detection Alpha Lab 회귀 — 리플레이의 lookahead 안전성과 규칙 변형을 고정한다.

핵심 불변식:
- 진입은 검출 다음 거래일 시가 (라이브 포지션 엔진과 동일 의미론)
- 보유 중 심볼 재검출 무시, 같은 봉 손절·익절 동시 관통 시 손절 우선
- 필터(레짐/Stage2)와 ATR 계산은 검출일/진입 전일까지의 데이터만 사용
"""
import pytest

from app.services.mirofish import detection_lab as dl


def _bars(start_day, prices):
    """prices: [(open, high, low, close)] — 2026-06-01 부터 연속 날짜."""
    out = []
    for i, (o, h, l, c) in enumerate(prices):
        d = start_day + i
        out.append({'date': f'2026-06-{d:02d}', 'open': o, 'high': h, 'low': l, 'close': c})
    return out


FLAT = [(100, 101, 99, 100)] * 20


def test_replay_enters_next_day_open_and_hits_target():
    detections = [{'date': '2026-06-01', 'symbol': 'AAA', 'name': 'A종목'}]
    series = {'AAA': _bars(1, [(100, 101, 99, 100),      # 6/01 검출일
                               (102, 103, 101, 102),      # 6/02 진입 (시가 102)
                               (104, 112, 103, 110)]      # 목표 110.16 → 고가 112 도달
                          + FLAT)}
    result = dl.replay(detections, series, dl.RuleSet())
    assert len(result['trades']) == 1
    t = result['trades'][0]
    assert t['entry_date'] == '2026-06-02'
    assert t['entry_price'] == 102
    assert t['exit_reason'] == 'target'
    assert t['return_pct'] == pytest.approx(8.0)


def test_replay_stop_priority_and_metrics():
    detections = [
        {'date': '2026-06-02', 'symbol': 'AAA', 'name': 'A'},
        {'date': '2026-06-02', 'symbol': 'BBB', 'name': 'B'},
    ]
    series = {
        # AAA: 진입 100 → 같은 봉 고저가 목표/손절 관통 → 손절 -7%
        'AAA': _bars(1, [(100, 101, 99, 100), (100, 101, 99, 100),
                         (100, 115, 85, 100)] + FLAT),
        # BBB: 진입 100 → 목표 도달 +8%
        'BBB': _bars(1, [(100, 101, 99, 100), (100, 101, 99, 100),
                         (100, 109, 99, 108)] + FLAT),
    }
    result = dl.replay(detections, series, dl.RuleSet())
    assert {t['exit_reason'] for t in result['trades']} == {'stop', 'target'}
    m = result['metrics']
    assert m['trades'] == 2
    assert m['win_rate_pct'] == pytest.approx(50.0)
    assert m['expectancy_pct'] == pytest.approx((8.0 - 7.0) / 2, abs=0.01)
    assert m['profit_factor'] == pytest.approx(8.0 / 7.0, abs=0.01)


def test_replay_ignores_redetection_while_open():
    detections = [
        {'date': '2026-06-02', 'symbol': 'AAA', 'name': 'A'},
        {'date': '2026-06-04', 'symbol': 'AAA', 'name': 'A'},  # 보유 중 재검출
    ]
    series = {'AAA': _bars(1, FLAT)}
    result = dl.replay(detections, series, dl.RuleSet())
    assert len(result['trades']) == 1  # expiry 1건만


def test_expiry_exit_after_max_hold():
    detections = [{'date': '2026-06-01', 'symbol': 'AAA', 'name': 'A'}]
    series = {'AAA': _bars(1, FLAT)}
    result = dl.replay(detections, series, dl.RuleSet(max_hold_days=8))
    t = result['trades'][0]
    assert t['exit_reason'] == 'expiry'
    assert t['holding_days'] == 8


def test_regime_gate_skips_downtrend_detection():
    detections = [{'date': '2026-06-02', 'symbol': 'AAA', 'name': 'A'}]
    series = {'AAA': _bars(1, FLAT)}
    phases = {'2026-06-02': 'downtrend'}
    rules = dl.RuleSet(regime_gate=True)
    result = dl.replay(detections, series, rules, phase_by_date=phases)
    assert result['trades'] == []
    assert result['metrics']['skipped_by_filter'] == 1


def test_stage2_filter_requires_price_above_rising_ma():
    """검출일 종가가 150MA 아래(하락 추세 종목)면 진입하지 않는다."""
    # 200일 하락 시계열: 종가가 항상 150MA 아래
    falling = [(300 - i, 301 - i, 299 - i, 300 - i) for i in range(200)]
    rising = [(100 + i, 101 + i, 99 + i, 100 + i) for i in range(200)]
    series = {
        'DOWN': [{'date': f'2025-{m:02d}-{d:02d}', 'open': o, 'high': h, 'low': l, 'close': c}
                 for (o, h, l, c), (m, d) in zip(falling, dl._date_seq(200))],
        'UP': [{'date': f'2025-{m:02d}-{d:02d}', 'open': o, 'high': h, 'low': l, 'close': c}
               for (o, h, l, c), (m, d) in zip(rising, dl._date_seq(200))],
    }
    last_date = series['UP'][-1]['date']
    detections = [
        {'date': last_date, 'symbol': 'DOWN', 'name': 'D'},
        {'date': last_date, 'symbol': 'UP', 'name': 'U'},
    ]
    # 진입 + 만료 청산까지 가능한 봉 추가
    for sym in ('DOWN', 'UP'):
        last = series[sym][-1]
        for d in range(5, 15):
            series[sym].append({**last, 'date': f'2026-01-{d:02d}'})

    rules = dl.RuleSet(stage2_filter=True)
    result = dl.replay(detections, series, rules)
    symbols = [t['symbol'] for t in result['trades']]
    assert 'UP' in symbols
    assert 'DOWN' not in symbols


def test_atr_exit_uses_pre_entry_data_only():
    """ATR 은 진입 전일까지 — 진입 이후 봉이 ATR 을 바꾸면 lookahead."""
    # TR=2 로 안정된 20봉 → ATR14 = 2. 목표 = entry + 2*2 = 104, 손절 = entry - 1.5*2 = 97
    stable = [(100, 101, 99, 100)] * 20
    detections = [{'date': '2026-06-20', 'symbol': 'AAA', 'name': 'A'}]
    series = {'AAA': _bars(1, stable + [(100, 105, 99, 104)])}  # 6/21 진입 100, 고가 105
    result = dl.replay(detections, series, dl.RuleSet(exit_mode='atr',
                                                      atr_target_mult=2.0,
                                                      atr_stop_mult=1.5))
    t = result['trades'][0]
    assert t['exit_reason'] == 'target'
    assert t['exit_price'] == pytest.approx(104.0)   # 100 + 2×ATR(2)


def test_metrics_include_phase_breakdown_and_mdd():
    detections = [
        {'date': '2026-06-02', 'symbol': 'AAA', 'name': 'A'},
        {'date': '2026-06-08', 'symbol': 'BBB', 'name': 'B'},
    ]
    series = {
        'AAA': _bars(1, [(100, 101, 99, 100)] * 2 + [(100, 115, 92, 93)] + FLAT),   # 손절
        'BBB': _bars(1, [(100, 101, 99, 100)] * 8 + [(100, 109, 99, 108)] + FLAT),  # 익절
    }
    phases = {'2026-06-02': 'leader_market', '2026-06-08': 'uptrend_broadening'}
    result = dl.replay(detections, series, dl.RuleSet(), phase_by_date=phases)
    m = result['metrics']
    assert 'by_phase' in m and 'leader_market' in m['by_phase']
    assert m['max_drawdown_pct'] <= 0
    assert 'by_exit_reason' in m


def test_collect_detections_dedupes_same_day(tmp_path, monkeypatch):
    import json, os
    monkeypatch.setattr(dl, 'WORKFLOWS_ROOT', str(tmp_path))
    for i, wf_id in enumerate(['mcp_20260601000000_aa', 'mcp_20260601120000_bb']):
        d = tmp_path / wf_id
        d.mkdir()
        (d / 'workflow.json').write_text(json.dumps({
            'id': wf_id, 'created_at': '2026-06-01T0%d:00:00+00:00' % i,
            'top3': [
                {'symbol': '005930', 'market': 'KOSPI', 'final_score': 80,
                 'verdict': {'action': 'BUY', 'target': '삼성전자'}},
                {'symbol': '000660', 'market': 'KOSPI', 'final_score': 70,
                 'verdict': {'action': 'HOLD', 'target': 'SK하이닉스'}},
            ],
        }), encoding='utf-8')
    detections = dl.collect_historical_detections()
    assert len(detections) == 1                # 같은 날 같은 심볼 1건 + HOLD 제외
    assert detections[0]['symbol'] == '005930'
    assert detections[0]['date'] == '2026-06-01'
