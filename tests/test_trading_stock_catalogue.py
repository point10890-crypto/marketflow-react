import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def renderer():
    spec = importlib.util.spec_from_file_location('stock_catalogue_cli', ROOT / 'scripts/run_specialized_trading_agents.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_stock_catalogue


def actual_report():
    ranked = [dict(rank=1, symbol='005930', name='삼성전자', market='KOSPI', date='2026-10-01'),
              dict(rank=2, symbol='000660', name='SK하이닉스', market='KOSPI', date='2026-10-01'),
              dict(rank=3, symbol='373220', name='LG에너지솔루션', market='KOSPI', date='2026-10-01')]
    quality = [dict(row, quality_pass=row['symbol'] != '373220',
                    reason='nonpositive_net_income' if row['symbol'] == '373220' else 'quality_passed')
               for row in ranked]
    return dict(synthetic=False, data=dict(status='blocked', ranked=ranked,
        eligible_symbols=['005930', '000660'], quality=dict(as_of='2026-10-01', results=quality)),
        quant=dict(qualification_complete=False, candidates=[], qualified=[]))


def pending_view():
    return dict(status='pending', rows=[])


def test_real_names_and_codes_visible_while_statistical_detection_is_pending():
    report = actual_report()
    original = copy.deepcopy(report)
    markup = renderer()(report, pending_view())
    assert '실제 조사 종목' in markup and '2026-10-01' in markup
    assert '삼성전자' in markup and '005930' in markup and 'SK하이닉스' in markup
    assert '재무 1차 통과 2종목' in markup
    assert '승률·켈리 검사 대기' in markup
    assert '미계산' in markup and '0.00%' not in markup
    assert '현재 매수 추천 목록이 아닙니다' in markup
    assert markup.index('삼성전자') < markup.index('<details>')
    assert report == original


def test_financial_holds_include_actual_symbol_and_human_readable_reason():
    markup = renderer()(actual_report(), pending_view())
    assert '재무 1차 보류 1종목' in markup
    assert 'LG에너지솔루션' in markup and '373220' in markup
    assert '순이익 0 이하' in markup


def test_synthetic_output_is_explicit_and_does_not_claim_actual_stocks():
    report = actual_report()
    report['synthetic'] = True
    markup = renderer()(report, pending_view())
    assert '합성 검증 종목' in markup
    assert '실제 조사 종목' not in markup


def test_qualified_but_no_current_signal_is_not_promoted_to_new_detection():
    report = actual_report()
    report['data']['status'] = 'ready'
    report['quant'].update(qualification_complete=True, qualified=[report['data']['ranked'][0]])
    markup = renderer()(report, dict(status='held', rows=[]))
    assert '통계 통과 · 현재 진입 신호 없음' in markup
    assert '미승인' in markup


def test_ready_attribution_shows_only_recorded_approved_target():
    report = actual_report()
    report['data']['status'] = 'ready'
    report['quant'].update(qualification_complete=True, candidates=[report['data']['ranked'][0]])
    view = dict(status='ready', rows=[dict(symbol='005930', final_weight=.1)])
    markup = renderer()(report, view)
    assert '현재 진입 신호' in markup and '승인 목표 10.00%' in markup
    assert 'CIO 승인 목표 1종목' in markup


def test_missing_or_conflicting_financial_identity_is_pending_not_passed():
    report = actual_report()
    report['data']['quality']['results'][0]['name'] = '다른 종목'
    report['data']['quality']['results'] = report['data']['quality']['results'][:1]
    markup = renderer()(report, pending_view())
    assert '재무 자료 확인 대기 3종목' in markup
    assert '재무 1차 통과 0종목' in markup


def test_names_and_unmapped_reasons_are_html_escaped():
    report = actual_report()
    report['data']['ranked'][2]['name'] = '<script>alert(1)</script>'
    report['data']['quality']['results'][2].update(
        name='<script>alert(1)</script>', reason='<img src=x onerror=alert(1)>')
    markup = renderer()(report, pending_view())
    assert '<script>' not in markup and '<img' not in markup
    assert '&lt;script&gt;' in markup and '&lt;img' in markup
