# -*- coding: utf-8 -*-
"""AI Chart 텔레그램 본문 회귀 테스트.

"100종목 분석" 이라고 써놓고 BUY 상위 10종목만 실어 보내서 목록이 잘려
나가던 문제(2026-08-15 사용자 리포트)를 막는다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scheduler import format_ai_chart_message, _AI_CHART_ROWS_PER_BLOCK


def _frame(n_buy=27, n_hold=24, n_sell=49):
    rows = []
    for sig, count in (('BUY', n_buy), ('HOLD', n_hold), ('SELL', n_sell)):
        for i in range(count):
            rows.append({
                '종목명': f'{sig}종목{i:02d}',
                '종목코드': f'{i:06d}',
                '시장': '코스피',
                'signal': sig,
                'confidence': 50 + (i % 45),
            })
    return pd.DataFrame(rows)


def test_message_lists_every_analyzed_stock():
    df = _frame()
    msg = format_ai_chart_message(df)

    for _, row in df.iterrows():
        assert f"({row['종목코드']})" in msg, f"{row['종목명']} 이 본문에서 누락됐다"
    assert msg.count('conf=') == len(df) == 100


def test_header_reports_full_counts():
    msg = format_ai_chart_message(_frame())
    assert '100종목' in msg
    assert 'BUY: 27' in msg and 'HOLD: 24' in msg and 'SELL: 49' in msg


def test_each_group_sorted_by_confidence_desc():
    msg = format_ai_chart_message(_frame())
    buy_section = msg.split('🟢 BUY ·')[1].split('🟡')[0]
    confs = [int(part.split('conf=')[1].split()[0].strip())
             for part in buy_section.split('\n') if 'conf=' in part]
    assert confs == sorted(confs, reverse=True)


def test_blocks_stay_splittable_for_send_telegram_long():
    """send_telegram_long 은 빈 줄 경계로만 자른다 — 한 블록이 4000자를 넘으면 안 된다."""
    msg = format_ai_chart_message(_frame())
    for block in msg.split('\n\n'):
        assert len(block) <= 4000, f"분할 불가능한 블록 ({len(block)}자)"
        assert block.count('conf=') <= _AI_CHART_ROWS_PER_BLOCK


def test_empty_signal_group_is_omitted():
    msg = format_ai_chart_message(_frame(n_buy=0, n_hold=3, n_sell=2))
    assert 'BUY: 0' in msg, '집계에는 0 이 보여야 한다'
    assert '🟢 BUY ·' not in msg, '항목이 없는 그룹은 목록 섹션을 만들지 않는다'
