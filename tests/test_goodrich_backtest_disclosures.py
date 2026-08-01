"""disclosures.py — 시점 정확 공시 신호 단위 테스트."""
import json

from app.services.mirofish.goodrich_backtest import disclosures as D


def _write(tmp_path, month, rows):
    path = tmp_path / f'{month}.jsonl'
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return path


def _row(code, dt, name):
    return {'stock_code': code, 'rcept_dt': dt, 'report_nm': name,
            'corp_name': 'X', 'corp_cls': 'Y', 'rcept_no': dt + '000001'}


def test_classify_separates_positive_from_negative():
    assert D.classify('주요사항보고서(자기주식취득결정)') == D.STRONG_POSITIVE_SCORE
    assert D.classify('현금ㆍ현물배당결정') == D.MODERATE_POSITIVE_SCORE
    assert D.classify('주요사항보고서(유상증자결정)') == D.NEGATIVE_SCORE
    assert D.classify('임원ㆍ주요주주특정증권등소유상황보고서') == 0


def test_negative_keywords_win_over_positive_in_mixed_titles():
    """'유상증자' 가 들어간 제목은 다른 키워드가 섞여도 악재로 본다.

    예: '주요사항보고서(유상증자결정)' 이 정정되며 제목에 '배당' 이 함께
    등장하는 경우가 있다. 호재로 집계하면 부호가 뒤집힌다.
    """
    assert D.classify('[기재정정]주요사항보고서(유상증자결정) 및 배당 관련') == D.NEGATIVE_SCORE


def test_prior_excludes_the_entry_day_itself(tmp_path):
    """list.json 에는 시각이 없다. 당일 16시 공시는 15:27 검출 시점에 알 수 없으므로
    진입일 당일은 통째로 제외한다 — 애매하면 배제가 안전하다."""
    _write(tmp_path, '202601', [
        _row('000001', '20260105', '단일판매ㆍ공급계약체결'),
        _row('000001', '20260108', '주요사항보고서(자기주식취득결정)'),
    ])
    book = D.load_disclosures(str(tmp_path))

    got = [nm for _, nm in book.prior('000001', '2026-01-08', days=10)]

    assert got == ['단일판매ㆍ공급계약체결']


def test_prior_respects_the_lookback_window(tmp_path):
    _write(tmp_path, '202601', [
        _row('000001', '20260101', '단일판매ㆍ공급계약체결'),
        _row('000001', '20260107', '주요사항보고서(자기주식취득결정)'),
    ])
    book = D.load_disclosures(str(tmp_path))

    got = [nm for _, nm in book.prior('000001', '2026-01-09', days=5)]

    assert got == ['주요사항보고서(자기주식취득결정)']


def test_future_disclosures_never_change_the_score(tmp_path):
    """하네스의 핵심 성질 — 미래 공시를 넣어도 과거 점수가 움직이면 안 된다."""
    base = [_row('000001', '20260105', '단일판매ㆍ공급계약체결')]
    _write(tmp_path, '202601', base)
    before = D.load_disclosures(str(tmp_path)).score('000001', '2026-01-08')

    _write(tmp_path, '202601', base + [
        _row('000001', '20260109', '주요사항보고서(자기주식취득결정)'),
        _row('000001', '20260120', '주요사항보고서(자기주식취득결정)'),
    ])
    after = D.load_disclosures(str(tmp_path)).score('000001', '2026-01-08')

    assert before == after


def test_score_is_bounded_so_one_noisy_name_cannot_dominate(tmp_path):
    """공시를 20건 낸 종목이 점수를 독식하면 랭킹이 공시 건수 순이 된다."""
    _write(tmp_path, '202601', [
        _row('000001', '20260105', '주요사항보고서(자기주식취득결정)')
        for _ in range(20)
    ])
    book = D.load_disclosures(str(tmp_path))

    assert book.score('000001', '2026-01-08') == D.MAX_SCORE


def test_negative_disclosures_push_the_score_down(tmp_path):
    _write(tmp_path, '202601', [
        _row('000001', '20260105', '주요사항보고서(유상증자결정)'),
        _row('000002', '20260105', '단일판매ㆍ공급계약체결'),
    ])
    book = D.load_disclosures(str(tmp_path))

    assert book.score('000001', '2026-01-08') < 0 < book.score('000002', '2026-01-08')


def test_unknown_ticker_scores_zero_not_an_error(tmp_path):
    _write(tmp_path, '202601', [_row('000001', '20260105', '단일판매ㆍ공급계약체결')])

    assert D.load_disclosures(str(tmp_path)).score('999999', '2026-01-08') == 0.0


def test_missing_directory_yields_an_empty_book(tmp_path):
    book = D.load_disclosures(str(tmp_path / 'nope'))

    assert book.score('000001', '2026-01-08') == 0.0
    assert book.tickers() == []


def test_keyword_lists_stay_in_sync_with_the_live_collector():
    """사전을 복사해두면 운영이 키워드를 추가할 때 재현물만 뒤처진다."""
    from engine import dart_collector

    assert D.STRONG_KEYWORDS is dart_collector.TITLE_STRONG_KEYWORDS
    assert D.MODERATE_KEYWORDS is dart_collector.TITLE_MODERATE_KEYWORDS
    assert D.NEGATIVE_KEYWORDS is dart_collector.TITLE_NEGATIVE_KEYWORDS
