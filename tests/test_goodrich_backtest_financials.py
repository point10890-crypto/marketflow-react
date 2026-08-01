"""financials.py — 시점 정확 재무 신호 단위 테스트."""
import json

from app.services.mirofish.goodrich_backtest import financials as F


def _write(tmp_path, year, rows):
    with open(tmp_path / f'{year}.jsonl', 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def _row(code, rcept_dt, year='2025', **accounts):
    base = {'자산총계': 1000.0, '부채총계': 400.0, '자본총계': 600.0,
            '매출액': 500.0, '영업이익': 50.0, '당기순이익(손실)': 40.0}
    base.update(accounts)
    return {'stock_code': code, 'bsns_year': year,
            'rcept_dt': rcept_dt, 'accounts': base}


def test_report_is_invisible_before_it_was_filed(tmp_path):
    """삼성전자 FY2025 는 2026-03-10 에 접수됐다. 회계연도만 보고 1월에 쓰면
    그 시점에 존재하지 않던 데이터를 쓰는 것이다."""
    _write(tmp_path, '2025', [_row('000001', '20260310')])
    book = F.load_financials(str(tmp_path))

    assert book.latest('000001', '2026-01-15') is None
    assert book.latest('000001', '2026-03-11') is not None


def test_filing_day_itself_is_excluded(tmp_path):
    """접수 시각을 모르므로 당일은 배제한다 — 공시 신호와 같은 규칙."""
    _write(tmp_path, '2025', [_row('000001', '20260310')])

    assert F.load_financials(str(tmp_path)).latest('000001', '2026-03-10') is None


def test_latest_filed_report_wins_not_the_newest_fiscal_year(tmp_path):
    """정정공시로 과거 연도가 나중에 접수되기도 한다(실측: FY2023 이 2026-06 접수).
    회계연도가 아니라 접수일 기준으로 최신을 골라야 한다."""
    _write(tmp_path, '2024', [_row('000001', '20260620', year='2024', 자본총계=999.0)])
    _write(tmp_path, '2025', [_row('000001', '20260310', year='2025', 자본총계=600.0)])
    book = F.load_financials(str(tmp_path))

    assert book.latest('000001', '2026-07-01')['accounts']['자본총계'] == 999.0


def test_capital_impairment_is_the_strongest_penalty(tmp_path):
    _write(tmp_path, '2025', [
        _row('000001', '20260310', 자본총계=-100.0, 부채총계=1100.0),
        _row('000002', '20260310'),
    ])
    book = F.load_financials(str(tmp_path))

    assert book.health_score('000001', '2026-04-01') == F.MIN_SCORE
    assert book.health_score('000002', '2026-04-01') > 0


def test_high_leverage_scores_below_low_leverage(tmp_path):
    _write(tmp_path, '2025', [
        _row('000001', '20260310', 부채총계=900.0, 자본총계=100.0),   # 900%
        _row('000002', '20260310', 부채총계=200.0, 자본총계=800.0),   # 25%
    ])
    book = F.load_financials(str(tmp_path))

    assert book.health_score('000001', '2026-04-01') < book.health_score('000002', '2026-04-01')


def test_operating_loss_scores_below_operating_profit(tmp_path):
    _write(tmp_path, '2025', [
        _row('000001', '20260310', 영업이익=-80.0, **{'당기순이익(손실)': -90.0}),
        _row('000002', '20260310', 영업이익=80.0),
    ])
    book = F.load_financials(str(tmp_path))

    assert book.health_score('000001', '2026-04-01') < book.health_score('000002', '2026-04-01')


def test_score_is_bounded(tmp_path):
    _write(tmp_path, '2025', [
        _row('000001', '20260310', 부채총계=1.0, 자본총계=999.0, 영업이익=490.0),
    ])
    book = F.load_financials(str(tmp_path))
    score = book.health_score('000001', '2026-04-01')

    assert F.MIN_SCORE <= score <= F.MAX_SCORE


def test_unknown_ticker_is_neutral_not_penalised(tmp_path):
    """재무를 못 받은 종목을 감점하면 신규상장·수집누락이 랭킹에서 밀린다."""
    _write(tmp_path, '2025', [_row('000001', '20260310')])

    assert F.load_financials(str(tmp_path)).health_score('999999', '2026-04-01') == 0.0


def test_zero_revenue_does_not_raise(tmp_path):
    _write(tmp_path, '2025', [_row('000001', '20260310', 매출액=0.0)])

    assert isinstance(F.load_financials(str(tmp_path)).health_score('000001', '2026-04-01'), float)


def test_missing_directory_yields_an_empty_book(tmp_path):
    book = F.load_financials(str(tmp_path / 'nope'))

    assert book.tickers() == []
    assert book.health_score('000001', '2026-04-01') == 0.0
