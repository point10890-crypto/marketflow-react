# -*- coding: utf-8 -*-
"""Alpha Position Engine 회귀 테스트 — 알파캐치형 완결 신호의 규칙을 고정한다.

핵심 불변식:
- 진입은 검출 **다음 거래일 시가** (lookahead 금지 — 검출일 종가 진입은 성과 부풀리기)
- 청산 우선순위: 손절 > 목표가 (같은 날 둘 다 터치하면 보수적으로 손절 처리)
- 보유 만료(거래일 기준)는 종가 청산, CIO SELL 전환은 조기 종가 청산
- 종목당 동시 1포지션, 원장 무결성(open→closed 이동, 중복 신호 금지)
"""
import json

import pytest

from app.services.mirofish import paper_positions as pp


@pytest.fixture()
def ledger_path(tmp_path, monkeypatch):
    path = tmp_path / 'paper_positions.json'
    monkeypatch.setattr(pp, 'LEDGER_PATH', str(path))
    monkeypatch.delenv('MIROFISH_PAPER_DISABLED', raising=False)
    return path


def _prices(rows):
    """rows: [(date, open, high, low, close)] -> pp 가격 시퀀스 포맷."""
    return [
        {'date': d, 'open': o, 'high': h, 'low': l, 'close': c}
        for d, o, h, l, c in rows
    ]


SAMPLE_WORKFLOW = {
    'id': 'mcp_test_1',
    'created_at': '2026-08-14T06:10:00+00:00',
    'top3': [
        {
            'symbol': '017670', 'market': 'KOSPI', 'final_score': 88.5,
            'run_id': 'mfas_x', 'verdict': {'action': 'BUY', 'target': 'SK텔레콤'},
        },
        {
            'symbol': '005930', 'market': 'KOSPI', 'final_score': 80.0,
            'run_id': 'mfas_x', 'verdict': {'action': 'HOLD', 'target': '삼성전자'},
        },
    ],
}


def test_ingest_registers_only_buy_verdicts(ledger_path):
    created = pp.ingest_detections(SAMPLE_WORKFLOW)
    ledger = pp.load_ledger()
    symbols = [p['symbol'] for p in ledger['pending']]
    assert symbols == ['017670']          # HOLD 는 진입 대상 아님
    assert created == 1
    assert ledger['pending'][0]['name'] == 'SK텔레콤'


def test_ingest_skips_symbol_already_open(ledger_path):
    pp.ingest_detections(SAMPLE_WORKFLOW)
    pp.settle_pending(lambda sym: _prices([
        ('2026-08-14', 100, 105, 99, 104),
        ('2026-08-16', 106, 108, 105, 107),
    ]))
    # 같은 종목 재검출 → 중복 진입 금지
    again = pp.ingest_detections({**SAMPLE_WORKFLOW, 'id': 'mcp_test_2'})
    assert again == 0


def test_settle_uses_next_trading_day_open(ledger_path):
    pp.ingest_detections(SAMPLE_WORKFLOW)  # 검출일 2026-08-14
    entered = pp.settle_pending(lambda sym: _prices([
        ('2026-08-14', 100, 105, 99, 104),   # 검출일 — 이 날 가격으로 진입하면 lookahead
        ('2026-08-16', 106, 108, 105, 107),  # 다음 거래일 (주말 건너뜀)
    ]))
    assert len(entered) == 1
    pos = pp.load_ledger()['open'][0]
    assert pos['entry_date'] == '2026-08-16'
    assert pos['entry_price'] == 106          # 다음 거래일 '시가'
    assert pos['target_price'] == pytest.approx(106 * 1.08)
    assert pos['stop_price'] == pytest.approx(106 * 0.93)


def test_settle_waits_until_next_day_exists(ledger_path):
    """검출일까지의 데이터만 있으면 아직 체결하지 않고 pending 유지."""
    pp.ingest_detections(SAMPLE_WORKFLOW)
    entered = pp.settle_pending(lambda sym: _prices([
        ('2026-08-14', 100, 105, 99, 104),
    ]))
    assert entered == []
    assert len(pp.load_ledger()['pending']) == 1


def _open_position(entry_price=100.0, entry_date='2026-08-16'):
    ledger = pp.load_ledger()
    ledger['open'].append({
        'id': 'pos_1', 'symbol': '017670', 'name': 'SK텔레콤', 'market': 'KOSPI',
        'entry_date': entry_date, 'entry_price': entry_price,
        'target_price': round(entry_price * 1.08, 2),
        'stop_price': round(entry_price * 0.93, 2),
        'workflow_id': 'mcp_test_1', 'detected_at': '2026-08-14',
    })
    pp.save_ledger(ledger)
    return ledger['open'][0]


def test_exit_on_target_hit(ledger_path):
    _open_position(100.0)
    signals = pp.evaluate_positions(
        lambda sym: _prices([
            ('2026-08-16', 100, 101, 99, 100),
            ('2026-08-17', 102, 109, 101, 107),   # 고가 109 ≥ 목표 108
        ]),
        cio_actions={},
    )
    assert len(signals) == 1
    s = signals[0]
    assert s['exit_reason'] == 'target'
    assert s['exit_price'] == pytest.approx(108.0)  # 목표가 체결 가정
    ledger = pp.load_ledger()
    assert ledger['open'] == []
    assert ledger['closed'][0]['return_pct'] == pytest.approx(8.0)


def test_stop_takes_priority_over_target_same_day(ledger_path):
    """같은 날 고가·저가가 목표/손절 둘 다 관통하면 보수적으로 손절로 기록."""
    _open_position(100.0)
    signals = pp.evaluate_positions(
        lambda sym: _prices([
            ('2026-08-16', 100, 101, 99, 100),
            ('2026-08-17', 100, 110, 90, 95),
        ]),
        cio_actions={},
    )
    assert signals[0]['exit_reason'] == 'stop'
    assert signals[0]['exit_price'] == pytest.approx(93.0)


def test_exit_on_holding_expiry_close(ledger_path):
    _open_position(100.0, entry_date='2026-08-01')
    rows = [('2026-08-%02d' % d, 100, 101, 99, 100.5) for d in range(1, 13)]
    signals = pp.evaluate_positions(
        lambda sym: _prices(rows), cio_actions={}, max_hold_days=8,
    )
    assert len(signals) == 1
    assert signals[0]['exit_reason'] == 'expiry'
    # 8번째 거래일 종가
    assert signals[0]['exit_date'] == '2026-08-08'
    assert signals[0]['exit_price'] == pytest.approx(100.5)


def test_exit_on_cio_sell_flip(ledger_path):
    _open_position(100.0)
    signals = pp.evaluate_positions(
        lambda sym: _prices([
            ('2026-08-16', 100, 101, 99, 100),
            ('2026-08-17', 100, 102, 99, 101),
        ]),
        cio_actions={'017670': 'SELL'},
    )
    assert signals[0]['exit_reason'] == 'cio_sell'
    assert signals[0]['exit_price'] == pytest.approx(101)


def test_no_duplicate_close(ledger_path):
    """이미 청산된 포지션은 다시 평가·신호 발행되지 않는다."""
    _open_position(100.0)
    feed = lambda sym: _prices([
        ('2026-08-16', 100, 101, 99, 100),
        ('2026-08-17', 102, 109, 101, 107),
    ])
    first = pp.evaluate_positions(feed, cio_actions={})
    second = pp.evaluate_positions(feed, cio_actions={})
    assert len(first) == 1 and second == []
    assert len(pp.load_ledger()['closed']) == 1


def test_intraday_check_emits_target_signal(ledger_path):
    _open_position(100.0)
    signals = pp.intraday_check({'017670': {'price': 108.5}})
    assert len(signals) == 1
    assert signals[0]['exit_reason'] == 'target'
    assert pp.load_ledger()['open'] == []


def test_kill_switch_blocks_everything(ledger_path, monkeypatch):
    monkeypatch.setenv('MIROFISH_PAPER_DISABLED', 'true')
    assert pp.ingest_detections(SAMPLE_WORKFLOW) == 0
    assert pp.settle_pending(lambda sym: []) == []
    assert pp.evaluate_positions(lambda sym: [], cio_actions={}) == []


def test_performance_summary(ledger_path):
    ledger = pp.load_ledger()
    ledger['closed'] = [
        {'symbol': 'A', 'return_pct': 8.0, 'exit_date': '2026-08-10', 'exit_reason': 'target'},
        {'symbol': 'B', 'return_pct': -7.0, 'exit_date': '2026-08-12', 'exit_reason': 'stop'},
        {'symbol': 'C', 'return_pct': 3.0, 'exit_date': '2026-08-14', 'exit_reason': 'expiry'},
    ]
    pp.save_ledger(ledger)
    perf = pp.performance_summary(days=30, today='2026-08-17')
    assert perf['trades'] == 3
    assert perf['win_rate_pct'] == pytest.approx(66.7, abs=0.1)
    assert perf['avg_return_pct'] == pytest.approx((8 - 7 + 3) / 3, abs=0.01)
    assert perf['cumulative_return_pct'] == pytest.approx(3.55, abs=0.1)  # 복리
