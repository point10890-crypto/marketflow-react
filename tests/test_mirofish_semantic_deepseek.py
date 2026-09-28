import copy
import importlib
import pytest
from tests.test_mirofish_semantic_decisions import candidate


def adapter():
    return importlib.import_module('app.services.mirofish.semantic_deepseek')


def answer(m):
    return {'answers': {k: {'label': options[-1], 'quote': ''} for k, options in m.LABELS.items()}}


def test_labels_are_not_calibrated_probabilities():
    m = adapter()
    from app.services.mirofish.semantic_decisions import build_request
    p = build_request(candidate())
    raw = answer(m)
    raw['answers']['contract_termination'] = {'label': 'yes', 'quote': '계약 해지를 확정했다'}
    checked = m.validate(raw, p)
    assert checked['features']['contract_termination_yes'] == 1
    assert checked['probability_semantics'] == 'categorical_not_calibrated'
    raw['answers']['contract_termination']['quote'] = 'invented'
    with pytest.raises(ValueError): m.validate(raw, p)


def test_missing_answer_invalid_label_and_false_quote_rejected():
    m = adapter()
    from app.services.mirofish.semantic_decisions import build_request
    p = build_request(candidate())
    for mutate in ('missing', 'label', 'quote'):
        raw = answer(m)
        if mutate == 'missing': raw['answers'].pop('relevance')
        if mutate == 'label': raw['answers']['relevance']['label'] = 'bullish'
        if mutate == 'quote': raw['answers']['relevance'] = {'label': 'direct', 'quote': ''}
        with pytest.raises(ValueError): m.validate(raw, p)


def test_deepseek_evaluation_cached_and_isolated(monkeypatch, tmp_path):
    m = adapter()
    from app.services.mirofish import semantic_decisions as s
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER', 'deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED', 'true')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'secret-test')
    snapshot = s.record_snapshot([candidate()], workflow_id='test', decision_at=candidate()['source_cutoff'], root=tmp_path)
    calls = []
    def transport(payload, key):
        calls.append(payload)
        return {'model': m.model(), 'decision': answer(m), 'usage': {'input_tokens': 50, 'output_tokens': 20}}
    r = s.evaluate_snapshot(snapshot['id'], root=tmp_path, transport=transport)
    assert r['validated_count'] == 1 and r['provider'] == 'deepseek'
    assert r['ranking_effect'] == 'none'
    s.evaluate_snapshot(snapshot['id'], root=tmp_path, transport=transport)
    assert len(calls) == 1
    assert s.read_evaluation(snapshot['id'], root=tmp_path)['provider'] == 'deepseek'
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER', 'jev')
    assert s.read_evaluation(snapshot['id'], root=tmp_path)['status'] == 'not_evaluated'


def test_enrichment_uses_current_observation_not_historical_cutoff(tmp_path):
    from app.services.mirofish import semantic_decisions as s
    original = s.record_snapshot([candidate()], workflow_id='test', decision_at=candidate()['source_cutoff'], root=tmp_path)
    from app.services.mirofish.semantic_sources import enrich_snapshot
    now = '2026-09-29T00:00:00+00:00'
    new = enrich_snapshot(original['id'], root=tmp_path, now=now,
        reader=lambda symbol, limit: [{'title': '가상기업A 계약 해지', 'link': 'https://example.com/a',
            'published_ts': 1790550000}])
    snapshot = s.read_snapshot(new['id'], root=tmp_path)
    assert snapshot['decision_at'] == now
    assert s.read_snapshot(original['id'], root=tmp_path)['decision_at'] != now
    added = snapshot['candidates'][0]['source_packets'][0]
    assert added['fetched_at'] == now
    assert added['content']['text'] == '가상기업A 계약 해지'


def test_incomplete_provider_output_rejected():
    m = adapter()
    from app.services.mirofish.semantic_decisions import build_request
    raw = {'model': m.model(), 'usage': {'input_tokens': 1, 'output_tokens': 1},
           'provider_response': {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}}
    with pytest.raises(ValueError, match='incomplete_output'):
        m.check_response(raw, build_request(candidate()))


def test_budget_defers_and_resume_reuses_completed(monkeypatch, tmp_path):
    m = adapter()
    from app.services.mirofish import semantic_decisions as s
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER', 'deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED', 'true')
    monkeypatch.setenv('MIROFISH_SEMANTIC_BATCH_CALL_LIMIT', '1')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'secret-test')
    snap = s.record_snapshot([candidate('A'), candidate('B')], workflow_id='budget',
                            decision_at=candidate()['source_cutoff'], root=tmp_path)
    calls = []
    def transport(payload, key):
        calls.append(payload)
        return {'model': m.model(), 'decision': answer(m), 'usage': {'input_tokens': 5, 'output_tokens': 5}}
    r = s.evaluate_snapshot(snap['id'], root=tmp_path, transport=transport)
    assert r['results'][1]['status'] == 'deferred'
    r = s.evaluate_snapshot(snap['id'], root=tmp_path, transport=transport)
    assert r['validated_count'] == 2 and len(calls) == 2


def test_request_has_fixed_budget_and_no_generated_probabilities():
    m = adapter()
    from app.services.mirofish.semantic_decisions import build_request
    payload = m.request(build_request(candidate()))
    assert payload['max_tokens'] == 1800
    assert payload['thinking']['type'] == 'disabled'
    assert payload['response_format']['type'] == 'json_object'


def test_legacy_jev_uncertain_claim_is_not_retried(monkeypatch, tmp_path):
    from app.services.mirofish import semantic_decisions as s
    monkeypatch.setenv('MIROFISH_JEV_LIVE_ENABLED', 'true')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-test')
    c = candidate()
    snap = s.record_snapshot([c], workflow_id='legacy', decision_at=c['source_cutoff'], root=tmp_path)
    fingerprint = s._hash({'version': s.VERSION, 'request': s.build_request(c, decision_at=c['source_cutoff'])})
    assert s._claim(fingerprint, tmp_path) is None
    s._finish(fingerprint, tmp_path, {'status': 'uncertain', 'features': None})
    def no_call(*args):
        pytest.fail('legacy uncertain claim must not call provider again')
    r = s.evaluate_snapshot(snap['id'], root=tmp_path, transport=no_call)
    assert r['results'][0]['status'] == 'uncertain'


def test_wrapper_quote_repair_preserves_raw_and_rejects_changed_words():
    m=adapter()
    from app.services.mirofish.semantic_decisions import build_request
    p=build_request(candidate())
    raw=answer(m)
    raw['answers']['relevance']={'label':'direct','quote':p['state']['evidence'][0]['text']+'"'}
    checked=m.validate(raw,p)
    assert checked['answers']['relevance']['quote']==p['state']['evidence'][0]['text']
    assert checked['normalized_quotes']==['relevance']
    assert raw['answers']['relevance']['quote'].endswith('"')
    raw['answers']['relevance']['quote']='"완전히 다른 주장"'
    with pytest.raises(ValueError): m.validate(raw,p)


def test_revalidate_saved_response_makes_no_provider_call(monkeypatch,tmp_path):
    from app.services.mirofish import semantic_decisions as s
    from app.utils.atomic_json import write_json_atomic
    m=adapter()
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER','deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED','true')
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    c=candidate(); snap=s.record_snapshot([c],workflow_id='repair',decision_at=c['source_cutoff'],root=tmp_path)
    r=s.evaluate_snapshot(snap['id'],root=tmp_path,transport=lambda *_: {'model':m.model(),'decision':{},'usage':{'input_tokens':2,'output_tokens':1}})
    fp=r['results'][0]['fingerprint']
    raw={'model':m.model(),'decision':answer(m),'usage':{'input_tokens':2,'output_tokens':1}}
    write_json_atomic(str(tmp_path/'responses'/(fp+'.json')),{'response':raw})
    monkeypatch.setattr(m,'transport',lambda *_:pytest.fail('offline revalidation must not call API'))
    repaired=s.revalidate_snapshot(snap['id'],root=tmp_path)
    assert repaired['validated_count']==1
    assert repaired['results'][0]['revalidated_from_saved_response'] is True


def test_revalidate_empty_choices_retains_failure(monkeypatch,tmp_path):
    from app.services.mirofish import semantic_decisions as s
    m=adapter()
    monkeypatch.setenv('MIROFISH_SEMANTIC_PROVIDER','deepseek')
    monkeypatch.setenv('MIROFISH_SEMANTIC_LIVE_ENABLED','true')
    monkeypatch.setenv('DEEPSEEK_API_KEY','test')
    c=candidate(); snap=s.record_snapshot([c],workflow_id='malformed',decision_at=c['source_cutoff'],root=tmp_path)
    s.evaluate_snapshot(snap['id'],root=tmp_path,transport=lambda *_:{'model':m.model(),'provider_response':{'choices':[]}})
    r=s.revalidate_snapshot(snap['id'],root=tmp_path)
    assert r['results'][0]['status']=='failed'
