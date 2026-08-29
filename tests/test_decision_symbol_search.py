# -*- coding: utf-8 -*-
"""종목 검색 — 코드·종목명·별칭·초성 전부로 찾는다.

기존 GraphRAG 엔티티 리졸버(``graphrag.resolver``)를 그대로 쓴다. 그 안에 이미
초성(ㅅㅅㅈㅈ→삼성전자), 별칭(하닉→SK하이닉스), 접두·퍼지 매칭이 구현되어 있는데
판단 화면만 CSV 단순 조회를 쓰고 있어서 이름·초성 조회가 먹지 않았다.

리졸버가 없는 환경(entities.db 미초기화 = 개발 PC)에서도 조회가 죽으면 안 되므로
CSV 유니버스 폴백을 남긴다.
"""
import pytest

from app.services.mirofish import decision_brief as db


UNIVERSE = {'005930': '삼성전자', '000660': 'SK하이닉스', '041190': '우리기술투자'}


def _match(name, symbol, confidence, reason='exact_name'):
    return {'name_ko': name, 'symbol': symbol, 'confidence': confidence,
            'reason': reason, 'entity_id': f'kr:{symbol}', 'market': 'KOSPI'}


@pytest.fixture()
def universe(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: dict(UNIVERSE))


def _stub_resolver(monkeypatch, matches, *, error=None):
    from app.services.mirofish.graphrag import resolver

    def fake(query, hint_market=None, limit=5):
        out = {'query': query, 'matches': list(matches)}
        if error:
            out['error'] = error
        return out

    monkeypatch.setattr(resolver, 'resolve', fake)


# ─── 리졸버 연동 ────────────────────────────────────────────

def test_chosung_resolves_through_graphrag(universe, monkeypatch):
    """초성만 입력해도 종목을 찾아야 한다 — 기존 리졸버가 이미 하는 일이다."""
    _stub_resolver(monkeypatch, [_match('삼성전자', '005930', 0.85, 'chosung_exact')])
    assert db.resolve_symbol('ㅅㅅㅈㅈ') == ('005930', '삼성전자')


def test_alias_resolves_through_graphrag(universe, monkeypatch):
    _stub_resolver(monkeypatch, [_match('SK하이닉스', '000660', 0.95, 'exact_alias')])
    assert db.resolve_symbol('하닉') == ('000660', 'SK하이닉스')


def test_highest_confidence_match_wins(universe, monkeypatch):
    _stub_resolver(monkeypatch, [
        _match('삼성전자', '005930', 0.95),
        _match('삼성전기', '009150', 0.72, 'fuzzy'),
    ])
    assert db.resolve_symbol('삼전')[0] == '005930'


def test_low_confidence_only_still_resolves(universe, monkeypatch):
    """퍼지 후보뿐이어도 조회 자체를 막지 않는다 — 화면이 후보를 보여준다."""
    _stub_resolver(monkeypatch, [_match('한미반도체', '042700', 0.62, 'fuzzy')])
    assert db.resolve_symbol('한미반도')[0] == '042700'


# ─── 폴백: 리졸버가 없거나 죽어도 조회는 산다 ───────────────

def test_falls_back_to_universe_when_db_not_initialized(universe, monkeypatch):
    _stub_resolver(monkeypatch, [], error='entities.db not initialized')
    assert db.resolve_symbol('삼성전자') == ('005930', '삼성전자')


def test_falls_back_when_resolver_raises(universe, monkeypatch):
    from app.services.mirofish.graphrag import resolver

    def boom(*_a, **_kw):
        raise RuntimeError('db locked')

    monkeypatch.setattr(resolver, 'resolve', boom)
    assert db.resolve_symbol('삼성전자') == ('005930', '삼성전자')


def test_six_digit_code_never_needs_the_resolver(universe, monkeypatch):
    from app.services.mirofish.graphrag import resolver

    def boom(*_a, **_kw):
        raise AssertionError('코드 입력에 리졸버를 부르면 안 된다')

    monkeypatch.setattr(resolver, 'resolve', boom)
    assert db.resolve_symbol('005930') == ('005930', '삼성전자')


def test_blank_input_is_still_rejected(universe):
    with pytest.raises(ValueError):
        db.resolve_symbol('   ')


def test_unknown_input_does_not_raise(universe, monkeypatch):
    _stub_resolver(monkeypatch, [])
    code, name = db.resolve_symbol('없는회사')
    assert code and name is None


# ─── 후보 검색 (자동완성) ───────────────────────────────────

def test_search_returns_ranked_candidates(universe, monkeypatch):
    _stub_resolver(monkeypatch, [
        _match('삼성전자', '005930', 0.85, 'chosung_exact'),
        _match('상신전자', '263810', 0.85, 'chosung_exact'),
    ])
    out = db.search_symbols('ㅅㅅㅈㅈ')
    assert [c['symbol'] for c in out['candidates']] == ['005930', '263810']
    assert out['candidates'][0]['name'] == '삼성전자'


def test_search_reports_the_matching_reason(universe, monkeypatch):
    """왜 이 후보가 나왔는지 보여야 사용자가 고를 수 있다."""
    _stub_resolver(monkeypatch, [_match('SK하이닉스', '000660', 0.95, 'exact_alias')])
    assert db.search_symbols('하닉')['candidates'][0]['reason'] == 'exact_alias'


def test_search_falls_back_to_universe_substring(universe, monkeypatch):
    _stub_resolver(monkeypatch, [], error='entities.db not initialized')
    out = db.search_symbols('하이닉스')
    assert '000660' in [c['symbol'] for c in out['candidates']]


def test_search_respects_the_limit(universe, monkeypatch):
    _stub_resolver(monkeypatch, [_match(f'종목{i}', f'00000{i}', 0.7) for i in range(9)])
    assert len(db.search_symbols('종목', limit=3)['candidates']) == 3


def test_search_on_blank_query_returns_nothing(universe):
    assert db.search_symbols('  ')['candidates'] == []


def test_search_never_raises_on_resolver_failure(universe, monkeypatch):
    from app.services.mirofish.graphrag import resolver
    monkeypatch.setattr(resolver, 'resolve',
                        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError('x')))
    assert db.search_symbols('삼성')['candidates'] is not None


def test_search_marks_a_bare_code_as_exact(universe, monkeypatch):
    _stub_resolver(monkeypatch, [])
    out = db.search_symbols('005930')
    assert out['candidates'][0]['symbol'] == '005930'
    assert out['candidates'][0]['name'] == '삼성전자'


# ─── 리졸버 계약: 매칭 근거 키 ──────────────────────────────
# resolver._row_to_match 는 근거를 'match_reason' 에 담는다('reason' 아님).
# 이 키를 잘못 읽으면 화면에 "초성"·"별칭" 대신 밋밋한 기본값이 뜬다.

def test_reads_the_resolver_reason_key(universe, monkeypatch):
    from app.services.mirofish.graphrag import resolver
    monkeypatch.setattr(resolver, 'resolve', lambda q, hint_market=None, limit=5: {
        'matches': [{'name_ko': '삼성전자', 'symbol': '005930',
                     'confidence': 0.85, 'match_reason': 'chosung_exact'}]})
    assert db.search_symbols('ㅅㅅㅈㅈ')['candidates'][0]['reason'] == 'chosung_exact'


def test_resolver_contract_still_uses_match_reason():
    """리졸버가 키 이름을 바꾸면 여기서 먼저 깨져야 한다."""
    import inspect
    from app.services.mirofish.graphrag import resolver
    assert "'match_reason'" in inspect.getsource(resolver._row_to_match)
