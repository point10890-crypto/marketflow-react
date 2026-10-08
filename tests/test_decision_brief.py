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


def test_cap_deducts_history_gaps_once():
    """검출계열(scanner/paper 등) 공백은 미검출 종목이면 정상 — 1회만 합산 감산한다."""
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(
        sigs, data_gaps=['scanner', 'paper'], phase='uptrend_broadening',
        agreement=db.summarize_agreement(sigs))
    assert cap == pytest.approx(0.65)
    assert len(reasons) == 1


def test_cap_deducts_each_non_history_gap_plus_history_once():
    """검출계열 밖의 공백은 개별 감산, 검출계열은 묶어서 1회 감산."""
    sigs = [_sig('claw', 'positive', 'A'), _sig('jongga', 'positive', 'A')]
    cap, reasons = db.compute_confidence_cap(
        sigs, data_gaps=['scanner', 'paper', 'regime'], phase='uptrend_broadening',
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
    # 모든 리더를 먼저 막는다 — 스텁 밖 리더(price/flow/sector_rs/risk)가 실 KIS HTTP
    # 호출·실데이터를 치면 검증 대상 판정이 호스트/장세에 따라 달라진다.
    for name in db.SOURCE_READERS:
        monkeypatch.setitem(db.SOURCE_READERS, name, lambda s: None)
    for name, fn in mapping.items():
        monkeypatch.setitem(db.SOURCE_READERS, name, fn)
    # 뉴스 원장도 운영 data/omni/omni.db 를 생성·조회하면 안 된다.
    monkeypatch.setattr(db, '_read_news', lambda code: {'count': 0, 'items': []})


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


@pytest.mark.parametrize('candidate', [
    {'symbol': '005930', 'name': '삼성전자', 'rank': 2, 'action': 'BUY', 'alpha_score': 88, 'risk_score': 15},
    {'code': '005930', 'stock_name': '삼성전자', 'rank': 2, 'verdict': 'BUY', 'score': 88, 'risk': 15},
])
def test_build_scanner_reference_is_bounded_and_preserves_reader_registry(tmp_path, monkeypatch, candidate):
    import json
    from app.services.mirofish import alpha_scanner
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    root = tmp_path / 'runs'
    header = root / run_id / 'run.json'
    header.parent.mkdir(parents=True)
    header.write_text(json.dumps({'id': run_id, 'status': 'completed',
                                  'generated_at': '2026-08-31T09:30:00+09:00',
                                  'candidates': [candidate]}), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(root))
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', lambda **kwargs: pytest.fail('archive enumeration forbidden'))
    _stub_sources(monkeypatch, {'scanner': db._src_scanner})
    _regime_stub(monkeypatch)
    registry_before = dict(db.SOURCE_READERS)
    result = db.build_decision_brief('005930', scanner_run_id=run_id)
    scanner = next(signal for signal in result['signals'] if signal['source'] == 'scanner')
    assert scanner['detail'] == {'rank': 2, 'action': 'BUY', 'alpha_score': 88,
                                'risk_score': 15, 'run_id': run_id,
                                'lookup_basis': 'monitor_reference'}
    assert scanner['as_of'] == '2026-08-31T09:30:00+09:00'
    assert result['name'] == '삼성전자'
    assert db.SOURCE_READERS == registry_before


def test_default_scanner_reader_keeps_normal_latest_contract(monkeypatch):
    from app.services.mirofish import alpha_scanner
    calls = []
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates',
                        lambda **kwargs: calls.append(kwargs) or {'generated_at': 'latest',
                        'candidates': [{'symbol': '005930', 'rank': 1, 'action': 'HOLD', 'alpha_score': 77}]})
    monkeypatch.setattr(alpha_scanner, 'read_scanner_candidates', lambda *args: pytest.fail('default must use latest'))
    _stub_sources(monkeypatch, {'scanner': db._src_scanner})
    _regime_stub(monkeypatch)
    result = db.build_decision_brief('005930')
    scanner = next(signal for signal in result['signals'] if signal['source'] == 'scanner')
    assert calls == [{'limit': 20}]
    assert scanner['as_of'] == 'latest'
    assert scanner['detail'] == {'rank': 1, 'action': 'HOLD', 'alpha_score': 77, 'risk_score': None}


def test_missing_scanner_reference_is_a_gap_without_latest_fallback(tmp_path, monkeypatch):
    from app.services.mirofish import alpha_scanner
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'empty'))
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', lambda **kwargs: pytest.fail('archive enumeration forbidden'))
    _stub_sources(monkeypatch, {'scanner': db._src_scanner})
    _regime_stub(monkeypatch)
    result = db.build_decision_brief('005930', scanner_run_id='mfas_20260831093000_aaaaaaaaaaaa')
    assert 'scanner' in result['data_gaps']
    assert 'scanner' in result['errors']
    assert not any(signal['source'] == 'scanner' for signal in result['signals'])


@pytest.mark.parametrize('case', ['unsafe', 'identity_mismatch', 'running', 'incomplete', 'malformed_candidates', 'malformed_candidate'])
def test_bounded_scanner_rejects_invalid_reference_header(tmp_path, monkeypatch, case):
    import json
    from app.services.mirofish import alpha_scanner
    run_id = 'mfas_20260831093000_aaaaaaaaaaaa'
    root = tmp_path / 'runs'
    header = root / run_id / 'run.json'
    header.parent.mkdir(parents=True)
    run = {'id': run_id, 'status': 'completed',
           'candidates': [{'symbol': '005930', 'action': 'BUY', 'alpha_score': 99}]}
    if case == 'unsafe':
        run_id = '../outside'
    elif case == 'identity_mismatch':
        run['id'] = 'mfas_20260831103000_bbbbbbbbbbbb'
    elif case == 'running':
        run['status'] = 'running'
    elif case == 'incomplete':
        run.pop('candidates')
    elif case == 'malformed_candidates':
        run['candidates'] = {'symbol': '005930'}
    else:
        run['candidates'].append(None)
    header.write_text(json.dumps(run), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(root))
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_candidates', lambda **kwargs: pytest.fail('archive enumeration forbidden'))
    _stub_sources(monkeypatch, {'scanner': db._src_scanner})
    _regime_stub(monkeypatch)
    result = db.build_decision_brief('005930', scanner_run_id=run_id)
    assert 'scanner' in result['errors']
    assert 'scanner' in result['data_gaps']
    assert not any(signal['source'] == 'scanner' for signal in result['signals'])
