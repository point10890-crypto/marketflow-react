# -*- coding: utf-8 -*-
"""온디맨드 심층 분석 — 검출 이력이 없는 종목도 에이전트 토론으로 판단 근거를 만든다.

기존 판단 브리프는 이미 쌓인 근거만 읽는 수동 조회라, 검출된 적 없는 종목은
"근거 부족"만 반환했다. 사용자가 어떤 종목을 물어도 4 애널리스트 → 불/베어 토론 →
리스크 판정을 실행하고 그 논거를 제시해야 한다.
"""
import pytest

from app.services.mirofish import decision_brief as db


# ─── 종목명 해석 (코드가 아니어도 찾는다) ───────────────────

UNIVERSE = {'005930': '삼성전자', '041190': '우리기술투자', '000660': 'SK하이닉스'}


def test_resolves_code_directly(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    assert db.resolve_symbol('005930') == ('005930', '삼성전자')


def test_resolves_short_code_with_padding(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    assert db.resolve_symbol('5930') == ('005930', '삼성전자')


def test_resolves_korean_company_name(monkeypatch):
    """사용자는 코드가 아니라 이름으로 검색한다."""
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    assert db.resolve_symbol('우리기술투자') == ('041190', '우리기술투자')


def test_resolves_name_ignoring_spaces(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    assert db.resolve_symbol(' SK 하이닉스 ') == ('000660', 'SK하이닉스')


def test_unknown_name_keeps_input_without_name(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    code, name = db.resolve_symbol('없는회사')
    assert code == '없는회사'
    assert name is None


def test_rejects_empty_symbol():
    with pytest.raises(ValueError):
        db.resolve_symbol('   ')


def test_build_decision_brief_uses_resolved_name(monkeypatch):
    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    for key in db.SOURCE_READERS:
        monkeypatch.setitem(db.SOURCE_READERS, key, lambda s: None)
    monkeypatch.setattr(db, '_read_regime', lambda: {'phase': None, 'gate_status': None,
                                                     'conflict': False})
    monkeypatch.setattr(db, '_read_news', lambda code: {'count': 0, 'items': []})
    out = db.build_decision_brief('우리기술투자')
    assert out['symbol'] == '041190'
    assert out['name'] == '우리기술투자'


# ─── 온디맨드 심층 분석 ─────────────────────────────────────

FAKE_RUN = {
    'id': 'ta_test', 'target': '우리기술투자', 'symbol': '041190',
    'method': 'llm', 'completed_at': '2026-08-29T10:00:00+00:00',
    'analyst_reports': [
        {'role': 'technical', 'title': '기술적', 'stance': 'bullish', 'score': 20.0,
         'summary': '거래량 증가', 'evidence': ['20일선 상회'], 'method': 'llm',
         'number_verification': {'verified': 2, 'unverified': 1, 'contradicted': 0}},
        {'role': 'fundamentals', 'title': '펀더멘털', 'stance': 'bearish', 'score': -10.0,
         'summary': '밸류 부담', 'evidence': [], 'method': 'llm',
         'number_verification': {'verified': 1, 'unverified': 3, 'contradicted': 1}},
    ],
    'research_debate': {
        'rounds': [{'round': 1, 'bull': {'message': '수급이 붙었다'},
                    'bear': {'message': '실적 근거가 약하다'}}],
        'bull_case': '수급이 붙었다', 'bear_case': '실적 근거가 약하다',
        'manager': {'stance': 'neutral', 'thesis': '방향성 불충분', 'confidence': 55.0},
        'method': 'llm',
    },
    'trader_risk': {'risk': {'assessment': '변동성 높음'}},
    'verdict': {'verdict': 'HOLD', 'confidence': 55.0, 'strong_buy': False},
}


def test_deep_analysis_returns_debate_and_reasoning(monkeypatch):
    from app.services.mirofish.tradingagents import engine

    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    monkeypatch.setattr(engine, 'run_deep_analysis',
                        lambda target, **kw: dict(FAKE_RUN, target=target))

    out = db.run_deep_analysis_for('우리기술투자')
    assert out['symbol'] == '041190'
    assert out['name'] == '우리기술투자'
    assert out['verdict']['verdict'] == 'HOLD'
    assert len(out['analysts']) == 2
    assert out['debate']['rounds'][0]['bull'] == '수급이 붙었다'
    assert out['debate']['manager']['thesis'] == '방향성 불충분'


def test_deep_analysis_aggregates_number_verification(monkeypatch):
    from app.services.mirofish.tradingagents import engine

    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    monkeypatch.setattr(engine, 'run_deep_analysis', lambda target, **kw: FAKE_RUN)
    out = db.run_deep_analysis_for('041190')
    assert out['verification'] == {'verified': 3, 'unverified': 4, 'contradicted': 1}


def test_deep_analysis_never_emits_trade_instruction(monkeypatch):
    """딥검증 verdict 는 참고 판정이지 매매 지시가 아니다 — status 어휘는 유지된다."""
    from app.services.mirofish.tradingagents import engine

    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)
    monkeypatch.setattr(engine, 'run_deep_analysis',
                        lambda target, **kw: dict(FAKE_RUN, verdict={'verdict': 'STRONG_BUY',
                                                                     'confidence': 90.0}))
    out = db.run_deep_analysis_for('041190')
    assert out['status'] in db.ALLOWED_STATUS


def test_deep_analysis_reports_failure_without_raising(monkeypatch):
    from app.services.mirofish.tradingagents import engine

    monkeypatch.setattr(db, 'load_universe', lambda: UNIVERSE)

    def boom(target, **kw):
        raise RuntimeError('LLM down')

    monkeypatch.setattr(engine, 'run_deep_analysis', boom)
    out = db.run_deep_analysis_for('041190')
    assert out['error']
    assert out['analysts'] == []


# ─── 유니버스 캐시 — 실패를 고착하지 않는다 ─────────────────

def test_load_universe_does_not_memoize_read_failure(monkeypatch, tmp_path):
    """첫 읽기 실패(파일 부재·재작성 중 잠금)가 빈 테이블로 영구 캐시되면 이름 해석이
    프로세스 재시작 전까지 죽는다 — 다음 호출은 다시 시도해야 한다."""
    monkeypatch.setattr(db, '_universe_cache', None)
    csv_path = tmp_path / 'korean_stocks_list.csv'
    monkeypatch.setattr(db, 'UNIVERSE_PATH', str(csv_path))

    assert db.load_universe() == {}
    assert db._universe_cache is None                  # 실패는 캐시하지 않는다

    csv_path.write_text('ticker,name\n005930,삼성전자\n', encoding='utf-8-sig')
    assert db.load_universe() == {'005930': '삼성전자'}
    assert db._universe_cache == {'005930': '삼성전자'}  # 성공은 캐시한다
