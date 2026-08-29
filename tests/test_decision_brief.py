# -*- coding: utf-8 -*-
"""종목 판단 브리프 — 여러 독립 소스를 한 종목 기준으로 팬아웃 집계해 합의/이견을 드러낸다.

Orca(stablyai/orca)의 "하나의 프롬프트를 여러 에이전트에 팬아웃 → 결과 비교 → 승자 선택"
패턴을 매매 판단에 이식한 것. 단, 에이전트를 새로 돌리지 않고 시스템이 이미 보유한
읽기전용 근거를 비교한다. 매수/매도 판정 어휘는 구조적으로 생성될 수 없다.
"""
import pytest

from app.services.mirofish import decision_brief as db


# ─── 심볼 정규화 ────────────────────────────────────────────

def test_normalize_symbol_pads_kr_code():
    assert db.normalize_symbol('5930') == '005930'
    assert db.normalize_symbol(' 005930 ') == '005930'


def test_normalize_symbol_keeps_non_numeric():
    assert db.normalize_symbol('aapl') == 'AAPL'


def test_normalize_symbol_rejects_empty():
    with pytest.raises(ValueError):
        db.normalize_symbol('   ')


# ─── 합의/이견 요약 ─────────────────────────────────────────

def _sig(source, stance, grade='A'):
    return {'source': source, 'stance': stance, 'grade': grade, 'as_of': '2026-08-28', 'detail': {}}


def test_agreement_aligned_when_only_positive():
    a = db.summarize_agreement([_sig('claw', 'positive'), _sig('jongga', 'positive'),
                                _sig('scanner', 'neutral')])
    assert a['positive'] == 2 and a['negative'] == 0
    assert a['verdict'] == 'aligned'


def test_agreement_conflicted_when_both_directions():
    a = db.summarize_agreement([_sig('claw', 'positive'), _sig('detection', 'negative'),
                                _sig('jongga', 'positive')])
    assert a['verdict'] == 'conflicted'


def test_agreement_insufficient_when_all_absent():
    a = db.summarize_agreement([_sig('claw', 'absent'), _sig('jongga', 'absent')])
    assert a['verdict'] == 'insufficient'
    assert a['ratio'] is None


# ─── 신뢰 상한 (결정론) ─────────────────────────────────────

def test_cap_full_when_evidence_complete():
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(
        sigs, data_gaps=[], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs))
    assert cap == pytest.approx(0.75)
    assert reasons == []


def test_cap_deducts_for_each_data_gap():
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(
        sigs, data_gaps=['scanner', 'paper'], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs))
    assert cap == pytest.approx(0.55)
    assert len(reasons) == 2


def test_cap_deducts_when_sa_evidence_under_two():
    sigs = [_sig('claw', 'positive', 'A'), _sig('tradingagents', 'positive', 'B')]
    cap, _ = db.compute_confidence_cap(sigs, data_gaps=[], phase='uptrend_broadening',
                                       agreement=db.summarize_agreement(sigs))
    assert cap == pytest.approx(0.60)


def test_cap_hard_ceiling_in_negative_phase():
    """Detection Lab 실측: 하락·반등초입 국면은 기대값 음수 — 상한을 강제한다."""
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(sigs, data_gaps=[], phase='downtrend',
                                             agreement=db.summarize_agreement(sigs))
    assert cap <= 0.40
    assert any('phase' in r for r in reasons)


def test_cap_never_below_floor():
    sigs = [_sig('claw', 'positive', 'C')]
    cap, _ = db.compute_confidence_cap(
        sigs, data_gaps=['a', 'b', 'c', 'd', 'e', 'f'], phase='downtrend',
        agreement=db.summarize_agreement(sigs))
    assert cap >= 0.10


# ─── 상태 판정 (매수/매도 어휘 금지) ────────────────────────

def test_status_watch_when_aligned_positive_with_evidence():
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    assert db.decide_status(sigs, db.summarize_agreement(sigs)) == 'watch'


def test_status_avoid_when_sa_evidence_insufficient():
    sigs = [_sig('tradingagents', 'positive', 'B'), _sig('detection', 'positive', 'B')]
    assert db.decide_status(sigs, db.summarize_agreement(sigs)) == 'avoid_data_gap'


def test_status_neutral_when_conflicted():
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'negative', 'A')]
    assert db.decide_status(sigs, db.summarize_agreement(sigs)) == 'neutral'


def test_status_vocabulary_excludes_trade_actions():
    assert 'buy' not in db.ALLOWED_STATUS
    assert 'sell' not in db.ALLOWED_STATUS
    assert set(db.ALLOWED_STATUS) == {'watch', 'neutral', 'avoid_data_gap'}


# ─── 통합: 소스 팬아웃 + 장애 격리 ──────────────────────────

def _stub_sources(monkeypatch, mapping):
    for name, fn in mapping.items():
        monkeypatch.setitem(db.SOURCE_READERS, name, fn)


def _regime_stub(monkeypatch, phase='uptrend_broadening', gate='GREEN', conflict=False):
    monkeypatch.setattr(db, '_read_regime',
                        lambda: {'phase': phase, 'gate_status': gate, 'conflict': conflict})


def test_build_aggregates_sources_and_computes_agreement(monkeypatch):
    _stub_sources(monkeypatch, {
        'claw': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-28',
                           'detail': {'grade': 'A', 'score': 66}, 'name': '대우건설'},
        'jongga': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-27',
                             'detail': {'grade': 'S'}},
        'scanner': lambda s: None,
        'detection': lambda s: None,
        'tradingagents': lambda s: None,
        'paper': lambda s: None,
        'observation': lambda s: None,
    })
    _regime_stub(monkeypatch)
    out = db.build_decision_brief('047040')
    assert out['symbol'] == '047040'
    assert out['name'] == '대우건설'
    assert out['status'] == 'watch'
    assert out['agreement']['verdict'] == 'aligned'
    assert 'scanner' in out['data_gaps']
    assert out['confidence_cap'] < 0.75  # 공백 차감 반영
    assert out['schema_version'] == 'mirofish.decision_brief.v1'


def test_build_isolates_failing_source(monkeypatch):
    def boom(_s):
        raise RuntimeError('source down')

    _stub_sources(monkeypatch, {
        'claw': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-28', 'detail': {}},
        'jongga': boom,
        'scanner': lambda s: None,
        'detection': lambda s: None,
        'tradingagents': lambda s: None,
        'paper': lambda s: None,
        'observation': lambda s: None,
    })
    _regime_stub(monkeypatch)
    out = db.build_decision_brief('005930')
    assert 'jongga' in out['errors']
    assert any(s['source'] == 'claw' for s in out['signals'])
    assert out['status'] in db.ALLOWED_STATUS


def test_build_marks_avoid_when_everything_absent(monkeypatch):
    _stub_sources(monkeypatch, {k: (lambda s: None) for k in db.SOURCE_READERS})
    _regime_stub(monkeypatch, phase=None, gate=None)
    out = db.build_decision_brief('000660')
    assert out['status'] == 'avoid_data_gap'
    assert out['agreement']['verdict'] == 'insufficient'
    assert len(out['data_gaps']) == len(db.SOURCE_READERS)


def test_build_emits_invalidators_for_open_position(monkeypatch):
    _stub_sources(monkeypatch, {
        'claw': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-28', 'detail': {}},
        'jongga': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-27', 'detail': {}},
        'scanner': lambda s: None,
        'detection': lambda s: None,
        'tradingagents': lambda s: None,
        'paper': lambda s: {'stance': 'positive', 'grade': 'A', 'as_of': '2026-08-27',
                            'detail': {'state': 'open', 'stop_price': 4650.0, 'target_price': 5400.0}},
        'observation': lambda s: None,
    })
    _regime_stub(monkeypatch)
    out = db.build_decision_brief('047040')
    types = {i['type'] for i in out['invalidators']}
    assert 'STOP_LEVEL' in types
    assert all(i.get('mode') == 'shadow' for i in out['invalidators'])


def test_missing_observation_ledger_is_gap_not_error(monkeypatch, tmp_path):
    """관측 원장이 아직 없는 호스트에서는 오류가 아니라 데이터 공백으로 다룬다."""
    from marketflow_claw import memory
    empty_db = tmp_path / 'claw.db'
    with memory.connect(path=str(empty_db)):
        pass  # 기본 스키마만 — 관측 테이블 없음
    monkeypatch.setattr(memory, 'DB_PATH', str(empty_db))
    assert db.SOURCE_READERS['observation']('005930') is None


# ─── L4 연동: 기계적 검증이 신뢰 상한에 반영된다 ────────────

def test_cap_deducts_for_unverified_numbers():
    """LLM 서술의 미검증 수치는 신뢰 상한을 낮춘다 (number_guard 연동)."""
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    base, _ = db.compute_confidence_cap(
        sigs, data_gaps=[], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs))
    lowered, reasons = db.compute_confidence_cap(
        sigs, data_gaps=[], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs),
        verification={'verified': 1, 'unverified': 3, 'contradicted': 0})
    assert lowered < base
    assert any('verif' in r or '검증' in r for r in reasons)


def test_cap_unaffected_when_all_numbers_verified():
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(
        sigs, data_gaps=[], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs),
        verification={'verified': 5, 'unverified': 0, 'contradicted': 0})
    assert cap == pytest.approx(0.75)
    assert reasons == []
