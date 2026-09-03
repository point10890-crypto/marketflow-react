# -*- coding: utf-8 -*-
"""피처 스냅샷 (Phase 1-B1) — 신호 시점의 원천 입력을 결과 JSON 에 남긴다.

캘리브레이션의 전제: 컴포넌트 점수만이 아니라 그 점수를 만든 원천값(거래대금·
등락률·수급·이평·52주고가·뉴스 ID·공시 유형·애널리스트 컨센서스)이 함께 저장돼야
가중치 변경의 효과를 재현할 수 있다. 기존 키/프론트 계약은 그대로다 (additive).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

import pytest

from engine.config import Grade
from engine.models import ChecklistDetail, ScoreDetail, Signal


def _populated_signal() -> Signal:
    return Signal(
        stock_code='005930', stock_name='삼성전자', market='KOSPI', sector='반도체',
        signal_date=date(2026, 9, 2), signal_time=datetime(2026, 9, 2, 14, 50, 0),
        grade=Grade.A,
        score=ScoreDetail(news=2, volume=3, chart=2, candle=1, consolidation=0,
                          supply=2, disclosure=1, analyst=2, financial=1,
                          llm_reason='호재', llm_source='gemini'),
        checklist=ChecklistDetail(has_news=True, volume_sufficient=True, is_new_high=True,
                                  is_breakout=False, ma_aligned=True, good_candle=True,
                                  supply_positive=True, has_disclosure=True,
                                  disclosure_types=['자사주취득']),
        current_price=80_000, entry_price=80_000, stop_price=76_000, target_price=88_000,
        trading_value=600_0000_0000, change_pct=7.5, volume_ratio=3.2,
        foreign_5d=120_000, inst_5d=30_000,
        news_items=[
            {'title': '삼성전자 HBM4 양산', 'source': '연합', 'published_at': '2026-09-02T09:00:00', 'url': 'https://x/1'},
            {'title': '외국인 순매수', 'source': '한경', 'published_at': '2026-09-02T10:00:00', 'url': 'https://x/2'},
        ],
        themes=['HBM', 'AI반도체'],
        high_52w=100_000,
        ma_values={'ma5': 79_000.0, 'ma10': 77_000.0, 'ma20': 75_000.0, 'ma60': 70_000.0},
        analyst_consensus={'consensus_score': 4.4, 'result': '적극매수', 'analyst_count': 12},
        disclosure_raw={'types': ['자사주취득'], 'score': 2, 'negative': False},
        financial_raw={'score': 1, 'detail': 'ROE 양호'},
    )


# ─── 종가베팅 V2 ───────────────────────────────────────────

def test_signal_to_dict_carries_feature_snapshot_with_raw_inputs():
    d = _populated_signal().to_dict()

    snap = d['feature_snapshot']
    assert snap['schema_version'] == 1
    assert snap['kind'] == 'jongga_v2'
    assert snap['snapshot_at'].startswith('2026-09-02T14:50')

    comp = snap['components']
    assert comp['news'] == 2 and comp['volume'] == 3 and comp['analyst'] == 2
    assert comp['total'] == 14

    raw = snap['raw']
    assert raw['trading_value'] == 600_0000_0000
    assert raw['volume_ratio'] == 3.2
    assert raw['change_pct'] == 7.5
    assert raw['foreign_5d'] == 120_000 and raw['inst_5d'] == 30_000
    assert raw['ma_aligned'] is True and raw['is_new_high'] is True and raw['is_breakout'] is False
    assert raw['ma5'] == 79_000.0 and raw['ma20'] == 75_000.0
    assert raw['high_52w'] == 100_000
    assert raw['high_52w_distance_pct'] == -20.0
    assert raw['disclosure_types'] == ['자사주취득'] and raw['disclosure_negative'] is False
    assert raw['analyst'] == {'consensus_score': 4.4, 'result': '적극매수', 'analyst_count': 12}
    assert raw['financial_score_raw'] == 1
    assert raw['themes'] == ['HBM', 'AI반도체']

    news = raw['news']
    assert len(news) == 2 and raw['news_count'] == 2
    assert news[0]['title'] == '삼성전자 HBM4 양산'
    assert news[0]['published_at'] == '2026-09-02T09:00:00'
    assert len(news[0]['id']) == 12
    assert news[0]['id'] != news[1]['id']


def test_feature_snapshot_news_capped_at_five_and_ids_are_stable():
    sig = _populated_signal()
    sig.news_items = [{'title': f'뉴스{i}', 'url': f'https://x/{i}'} for i in range(8)]
    a = sig.build_feature_snapshot()
    b = sig.build_feature_snapshot()
    assert len(a['raw']['news']) == 5
    assert a['raw']['news_count'] == 8
    assert [n['id'] for n in a['raw']['news']] == [n['id'] for n in b['raw']['news']]


def test_feature_snapshot_is_additive_and_tolerates_empty_signal():
    """기존 키는 그대로, 기본 Signal 도 스냅샷을 만들 수 있어야 한다 (직렬화 가능)."""
    d = Signal().to_dict()
    for key in ('stock_code', 'score', 'checklist', 'news_items', 'themes', 'trading_value'):
        assert key in d
    snap = d['feature_snapshot']
    assert snap['raw']['high_52w_distance_pct'] is None
    assert snap['raw']['analyst'] is None
    assert snap['raw']['news'] == []
    json.dumps(d, ensure_ascii=False)  # 직렬화 실패 없음


# ─── 주도주 ──────────────────────────────────────────────

def test_leading_row_snapshot_records_raw_inputs_and_time_context():
    from app.services import kis_screener

    candidate = {'code': '000001', 'name': '품질테스트', 'price': 1000, 'change_pct': 10.0,
                 'tr_amt': 500_0000_0000, 'volume': 100000, 'sector': 'T'}
    snap = kis_screener._build_leading_feature_snapshot(
        candidate,
        investor_row={'frgn_ntby_qty': '10', 'orgn_ntby_qty': '5', 'stck_bsop_date': '20260901'},
        foreign=10, inst=5, vol_ratio=200.0, volume_source_name='volume_amount_rank.prdy_vol',
        high_info={'high_52w': 2000, 'high_date': '20200101', 'distance_pct': 50.0},
        sector_count=3, market_cap_eok=12345, time_weight=0.8, scanned_at='2026-09-02T14:10:00',
    )
    assert snap['schema_version'] == 1 and snap['kind'] == 'leading'
    raw = snap['raw']
    assert raw['trading_value'] == 500_0000_0000
    assert raw['change_pct'] == 10.0
    assert raw['investor_foreign_net'] == 10 and raw['investor_inst_net'] == 5
    assert raw['investor_as_of_date'] == '20260901'
    assert raw['sector'] == 'T' and raw['sector_rising_count'] == 3
    assert raw['high_52w'] == 2000 and raw['high_52w_distance_pct'] == 50.0
    assert raw['market_cap_eok'] == 12345
    assert snap['time_context'] == {'weight': 0.8, 'scanned_at': '2026-09-02T14:10:00'}


def test_run_screening_rows_carry_snapshot_without_changing_score(monkeypatch):
    """스캔 결과 행에 스냅샷이 붙고, 점수 산식은 기존 그대로다."""
    from app.services import kis_screener

    row = {
        'mksc_shrn_iscd': '000001', 'stck_shrn_iscd': '000001', 'hts_kor_isnm': '품질테스트',
        'stck_prpr': '1000', 'prdy_ctrt': '10.0', 'acml_tr_pbmn': str(500_0000_0000),
        'acml_vol': '100000', 'bstp_cls_code': 'T', 'prdy_vol': '50000',
    }
    monkeypatch.setattr(kis_screener, 'get_token', lambda: 'token')
    monkeypatch.setattr(kis_screener, 'fetch_investor',
                        lambda token, code: [{'frgn_ntby_qty': '7', 'orgn_ntby_qty': '3'}])
    monkeypatch.setattr(kis_screener, 'fetch_price_detail',
                        lambda token, code: {'stck_prpr': '1000', 'w52_hgpr': '2000',
                                             'w52_lwpr': '500', 'w52_hgpr_date': '20200101'})
    monkeypatch.setattr(kis_screener, '_time_weight', lambda: 0.8)
    monkeypatch.setattr(kis_screener.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(kis_screener, '_save_result', lambda result: None)
    monkeypatch.setattr(kis_screener, 'fetch_volume_rank', lambda token, blng_code='3': [row])
    monkeypatch.setattr(kis_screener, 'fetch_fluctuation_rank', lambda token: [row])

    result = kis_screener.run_screening(force=True)
    item = result['candidate_pool'][0]

    snap = item['feature_snapshot']
    assert snap['kind'] == 'leading'
    assert snap['time_context']['weight'] == 0.8
    assert snap['raw']['investor_foreign_net'] == 7 and snap['raw']['investor_inst_net'] == 3
    assert snap['raw']['trading_value'] == item['trading_value']
    assert snap['raw']['change_pct'] == item['change_pct']
    # 점수 산식 불변: 컴포넌트 합(raw_score) × 시간가중 — 스냅샷은 점수에 개입하지 않는다
    components = item['score']
    raw = sum(components[k] for k in ('trading_value', 'momentum', 'smart_money',
                                      'volume_surge', 'sector', 'new_high'))
    assert item['raw_score'] == raw
    assert components['total'] == min(100, round(raw * 0.8))


# ─── feature_store 리더 ──────────────────────────────────────

def _write(path: str, payload: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)


def test_feature_store_reads_dated_archives_in_range(tmp_path):
    from app.services.mirofish import feature_store

    sig = _populated_signal().to_dict()
    _write(str(tmp_path / 'jongga_v2_results_20260901.json'), {'date': '2026-09-01', 'signals': [sig]})
    _write(str(tmp_path / 'jongga_v2_results_20260902.json'),
           {'date': '2026-09-02', 'signals': [sig, {'stock_code': 'NOSNAP', 'score': {}}]})
    _write(str(tmp_path / 'jongga_v2_results_20260905.json'), {'date': '2026-09-05', 'signals': [sig]})
    _write(str(tmp_path / 'jongga_v2_latest.json'), {'date': '2026-09-05', 'signals': [sig]})
    (tmp_path / 'jongga_v2_results_20260903.json').write_text('{not json', encoding='utf-8')

    rows = list(feature_store.iter_feature_snapshots(
        'jongga_v2', '2026-09-02', '20260904', data_dir=str(tmp_path)))
    assert [r['date'] for r in rows] == ['20260902']  # 범위 밖·손상·latest·스냅샷 없는 행 제외
    assert rows[0]['symbol'] == '005930' and rows[0]['grade'] == 'A' and rows[0]['score_total'] == 14
    assert rows[0]['snapshot']['raw']['trading_value'] == 600_0000_0000

    everything = list(feature_store.iter_feature_snapshots('jongga_v2', data_dir=str(tmp_path)))
    assert [r['date'] for r in everything] == ['20260901', '20260902', '20260905']


def test_feature_store_reads_leading_archives_and_defaults_to_data_dir(tmp_path, monkeypatch):
    from app.services.mirofish import feature_store

    monkeypatch.setattr(feature_store, 'DATA_DIR', str(tmp_path))
    _write(str(tmp_path / 'screener_leading_20260902.json'), {'results': [
        {'code': '000001', 'name': '품질테스트', 'grade': 'A', 'score': {'total': 66},
         'feature_snapshot': {'kind': 'leading', 'raw': {'change_pct': 10.0}, 'time_context': {'weight': 0.8}}},
    ]})
    rows = list(feature_store.iter_feature_snapshots('leading'))
    assert len(rows) == 1
    assert rows[0]['symbol'] == '000001' and rows[0]['name'] == '품질테스트'
    assert rows[0]['snapshot']['time_context']['weight'] == 0.8

    with pytest.raises(ValueError):
        list(feature_store.iter_feature_snapshots('unknown_kind'))
