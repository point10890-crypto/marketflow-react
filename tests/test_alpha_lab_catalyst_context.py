# 뉴스와 최초 가격 검출의 순수 분류·시간 계약을 검증한다.
from copy import deepcopy
import importlib
import importlib.util

import pytest

from app.services.mirofish.alpha_lab import opportunity_store, store

FIRST = '2026-10-07T09:46:02Z'
DECISION = '2026-10-09T10:00:00Z'
CAPTURE = '2026-10-09T11:00:00Z'


def module():
    name = 'app.services.mirofish.alpha_lab.catalyst_context'
    assert importlib.util.find_spec(name), 'catalyst chronology context is not implemented'
    return importlib.import_module(name)


def board(clock=DECISION, identity='d', symbols=('000660',)):
    return dict(schema_version=1, policy_version='profit-opportunity-v1',
        decision_id=identity*64, input_fingerprint='a'*64, source_audit_hash='b'*64,
        generated_at=clock, candidates=[dict(symbol=symbol, name='SK하이닉스' if symbol == '000660' else symbol,
            opportunity_id=str(i)*64) for i, symbol in enumerate(symbols, 1)])


def journal(tmp_path, current=None):
    opportunity_store.register_board(tmp_path, board(FIRST, 'c'))
    opportunity_store.register_board(tmp_path, current or board())
    return opportunity_store.read_journal(tmp_path)


def event(title='SK하이닉스 저평가, IBK 매수 의견', *, digest='e', url='https://www.asiae.co.kr/article/202610070123',
          published='2026-10-07T00:00:00Z', collected='2026-10-07T01:00:00Z', **overrides):
    value = dict(content_hash=digest*64, title=title, summary='', link=url,
        source='asiae_stock', grade='B', published_ts=published, collected_at=collected, symbols=['000660'])
    value.update(overrides)
    return value


def validation():
    return dict(status='collecting', hypothesis='price_setup_leads_catalyst_72h_v1', horizon_hours=72,
        started_at=CAPTURE, enrolled_decisions=0, matured_decisions=0, coincidence_rejected=False)


def build(tmp_path, events, current=None):
    current = current or board()
    return module().build_catalyst_context(current, journal(tmp_path, current), events,
        validation=validation(), now=CAPTURE)


@pytest.mark.parametrize(('title', 'stage', 'polarity'), [
    ('SK하이닉스 저평가, 목표주가 상향', 'valuation_opinion', 'supportive'),
    ('SK하이닉스 용인 부지 점검', 'site_inspection', 'unknown'),
    ('SK하이닉스 용인 반도체 전력·용수 인프라 확충', 'infrastructure', 'supportive'),
    ('SK하이닉스 신규 공장 투자 확정', 'investment', 'supportive'),
    ('SK하이닉스 신규 공장 투자 검토', 'investment', 'unknown'),
    ('SK하이닉스 공급계약 체결', 'contract', 'supportive'),
    ('SK하이닉스 수주 실패', 'contract', 'adverse'),
    ('SK하이닉스 영업이익 90% 감소', 'earnings', 'adverse'),
    ('SK하이닉스 영업이익 감소, 매출 증가', 'earnings', 'mixed'),
    ('SK하이닉스 거래정지 해소', 'other', 'supportive'),
    ('SK하이닉스 거래정지', 'other', 'adverse'),
])
def test_stage_and_polarity_distinguish_negation_and_provisional_actions(title, stage, polarity):
    result = module().classify_event(title)
    assert result == dict(stage=stage, polarity=polarity)


@pytest.mark.parametrize('title', ['SK하이닉스 거래정지 해소 실패', 'SK하이닉스 거래정지 미해소',
    'SK하이닉스 거래정지 해제 예정', 'SK하이닉스 거래정지 해소 위해 대응'])
def test_failed_or_pending_risk_release_is_not_a_reported_release(title):
    assert module().classify_event(title) == dict(stage='other', polarity='adverse')


@pytest.mark.parametrize(('title', 'stage', 'polarity'), [
    ('SK하이닉스 신규 공장 착공 검토', 'investment', 'unknown'),
    ('SK하이닉스 투자 발표 예정', 'investment', 'unknown'),
    ('SK하이닉스 공장 투자 확정 아니다', 'investment', 'unknown'),
    ('SK하이닉스 수주 확정 안됐다', 'contract', 'unknown'),
    ('SK하이닉스 거래정지 해제되지 않아', 'other', 'adverse'),
    ('SK하이닉스 상장폐지 위험 해소되지 않아', 'other', 'adverse'),
    ('SK하이닉스 거래재개 검토', 'other', 'unknown'),
    ('SK하이닉스 공급계약 체결 검토', 'contract', 'unknown'),
    ('SK하이닉스 전력 공급 지원 논의', 'infrastructure', 'unknown'),
    ('SK하이닉스 미확정 투자 발표 계획', 'investment', 'unknown'),
    ('SK하이닉스 영업이익 증가하지 않아', 'earnings', 'unknown'),
])
def test_pending_or_negated_positive_words_do_not_assert_completed_catalyst(title, stage, polarity):
    assert module().classify_event(title) == dict(stage=stage, polarity=polarity)


@pytest.mark.parametrize(('title', 'stage'), [
    ('SK하이닉스 신규 공장 착공 완료', 'investment'),
    ('SK하이닉스 신규 공장 투자 확정됐다', 'investment'),
    ('SK하이닉스 공급계약 체결했다', 'contract'),
    ('SK하이닉스 수주 확정됐다', 'contract'),
    ('SK하이닉스 거래정지 해제됐다', 'other'),
    ('SK하이닉스 거래재개 확정', 'other'),
    ('SK하이닉스 신규 공장 착공 완료, 추가 투자는 검토', 'investment'),
])
def test_asserted_completion_remains_supportive_without_borrowing_later_clause_modifiers(title, stage):
    assert module().classify_event(title) == dict(stage=stage, polarity='supportive')


def test_site_inspection_with_intervening_words_does_not_become_confirmed_investment():
    assert module().classify_event('SK하이닉스 용인 공장 부지 공사현황 점검') == dict(
        stage='site_inspection', polarity='unknown')


def test_original_clock_is_earliest_issued_decision_and_model_use_stays_false(tmp_path):
    value = build(tmp_path, [event()])
    assert value['decision_at'] == DECISION and value['captured_at'] == CAPTURE
    assert value['rows'][0]['first_detected_at'] == FIRST
    assert value['rows'][0]['first_decision_id'] == 'c'*64
    assert value['rows'][0]['events'][0]['timing'] == 'captured_before_first'
    assert value['rows'][0]['events'][0]['grade'] == 'B'
    assert value['used_in_selection'] is False and value['association_status'] == 'unproven'
    assert 'win_rate' not in value['validation'] and 'probability' not in str(value)


@pytest.mark.parametrize('title', ['SK스퀘어 주주환원 강화·목표주가 상향', '유니슨 사업 보고회',
    'SK증권 투자 세미나 개최', 'SK하이닉스테크 신규 계약', '1000660 관련 보도'])
def test_summary_only_or_compound_company_mention_is_not_attributed_as_target_catalyst(tmp_path, title):
    raw = event(title, summary='SK하이닉스 보유 지분과 산업 동향을 함께 설명한다.')
    original = deepcopy(raw)
    context = build(tmp_path, [raw])
    assert context['rows'][0]['events'] == []
    assert raw == original


@pytest.mark.parametrize(('symbol', 'name', 'title'), [
    ('000660', 'SK하이닉스', 'SK하이닉스가 저평가됐다'),
    ('000660', 'SK하이닉스', 'SK하이닉스는 용인 부지를 점검했다'),
    ('000660', 'SK하이닉스', 'SK 하이닉스 투자 확정'),
    ('000660', 'SK하이닉스', 'sk 하이닉스 공급계약 체결'),
    ('000660', 'SK하이닉스', 'SK하이닉스와 삼성전자 실적 공개'),
    ('000660', 'SK하이닉스', '종목코드 000660 저평가 의견'),
    ('005930', '삼성전자', '삼성전자의 실적 발표'),
    ('005930', '삼성전자', '005930 공급계약 체결'),
])
def test_direct_title_company_particles_mixed_space_and_exact_codes_are_accepted(tmp_path, symbol, name, title):
    current = board(symbols=(symbol,))
    current['candidates'][0]['name'] = name
    context = build(tmp_path, [event(title, symbols=[symbol])], current)
    assert len(context['rows'][0]['events']) == 1
    assert context['rows'][0]['events'][0]['title'] == title


def test_saved_summary_only_context_is_omitted_until_explicit_refresh_filters_its_target_titles(tmp_path):
    value = build(tmp_path, [event()])
    value['rows'][0]['events'][0]['title'] = 'SK스퀘어 주주환원 강화·목표주가 상향'
    value['snapshot_id'] = store._hash({k:v for k,v in value.items() if k != 'snapshot_id'})
    assert module().public_catalyst_context(value, board(), now=CAPTURE) is None


def test_chronology_separates_late_capture_from_post_detection_report(tmp_path):
    late = event(digest='f', published='2026-10-07T02:00:00+09:00', collected='2026-10-08T00:00:00Z')
    post = event('SK하이닉스 용인 부지 점검', digest='9', url='https://www.asiae.co.kr/article/202610070999',
        published='2026-10-08T00:00:00Z', collected='2026-10-08T00:30:00Z')
    value = build(tmp_path, [late, post])
    assert [row['timing'] for row in value['rows'][0]['events']] == [
        'published_before_captured_after', 'reported_after_first']
    assert value['rows'][0]['events'][1]['published_at'] == '2026-10-08T00:00:00Z'


@pytest.mark.parametrize('overrides', [
    dict(published_ts=None), dict(published_ts='2026-10-07T00:00:00'),
    dict(collected_at='2026-10-07T01:00:00'), dict(published_ts='2026-10-10T00:00:00Z'),
    dict(collected_at='2026-10-10T00:00:00Z'),
    dict(published_ts='2026-10-07T02:00:00Z', collected_at='2026-10-07T01:00:00Z'),
    dict(grade='S'), dict(link='javascript:alert(1)'), dict(link='https://attacker.test/1'),
    dict(link='https://www.asiae.co.kr@attacker.test/1'),
    dict(link='https://www.asiae.co.kr:80/article/1'), dict(link='http://www.asiae.co.kr:443/article/1'),
    dict(link='https://www.asiae.co.kr/article/a\\b'), dict(link='https://www.asiae.co.kr/article/%0a'),
    dict(link='https://www.asiae.co.kr/article/%2eenv'), dict(link='https://www.asiae.co.kr/article/%ZZ'),
    dict(link='https://www.asiae.co.kr/article/%61pi_key%3Dfoo'),
    dict(title='<script>SK하이닉스 저평가</script>'), dict(source='traceback'),
    dict(source='asiae_\u202estock'), dict(title='SK하이닉스 예상 상승 확률 90%'),
])
def test_unusable_clocks_or_sources_are_omitted_without_inferred_dates(tmp_path, overrides):
    value = build(tmp_path, [event(**overrides)])
    assert value['rows'][0]['events'] == []


def test_url_and_content_dedupe_keep_earliest_capture_and_group_repeat_reports(tmp_path):
    duplicate = event(digest='f', collected='2026-10-08T00:00:00Z')
    same_content = event(url='https://www.asiae.co.kr/article/other', collected='2026-10-08T00:30:00Z')
    one = event('SK하이닉스 용인 부지 점검', digest='1', url='https://www.asiae.co.kr/article/one',
        published='2026-10-08T02:00:00Z', collected='2026-10-08T02:30:00Z')
    two = event('용인 SK하이닉스 부지 현장 시찰', digest='2', url='https://www.mk.co.kr/news/economy/2',
        source='mk_economy', published='2026-10-08T02:20:00Z', collected='2026-10-08T02:40:00Z')
    value = build(tmp_path, [duplicate, same_content, two, event(), one])
    rows = value['rows'][0]['events']
    assert len(rows) == 3 and rows[0]['collected_at'] == '2026-10-07T01:00:00Z'
    assert rows[1]['event_group'] == rows[2]['event_group']
    assert rows[1]['event_id'] != rows[2]['event_id']
    assert 'corroboration' not in str(value) and 'score' not in str(value)


def test_eight_event_bound_keeps_original_pre_capture_and_preserves_candidate_order(tmp_path):
    current = board(symbols=('005930', '000660', '035420'))
    events = [event()]
    for i in range(12):
        events.append(event('SK하이닉스 수주 계약 '+str(i), digest=format(i, 'x'),
            url='https://www.asiae.co.kr/article/'+str(i), published=f'2026-10-08T{i:02d}:00:00Z',
            collected=f'2026-10-08T{i:02d}:30:00Z'))
    value = build(tmp_path, events, current)
    assert [row['symbol'] for row in value['rows']] == ['005930', '000660', '035420']
    assert len(value['rows'][1]['events']) == 8
    assert value['rows'][1]['events'][0]['timing'] == 'captured_before_first'


def test_balanced_display_keeps_pre_detection_evidence_and_immutable_article_first_capture(tmp_path):
    old = event('삼성전자 자사주, SK하이닉스 관련 보도', digest='a',
        url='https://www.asiae.co.kr/article/old', published='2026-08-29T00:00:00Z',
        collected='2026-08-29T01:00:00Z')
    nearest = event('SK하이닉스 저평가 IBK 매수 의견', digest='b',
        url='https://www.asiae.co.kr/article/nearest', published='2026-10-07T00:00:00Z',
        collected='2026-10-07T01:00:00Z')
    recaptured = deepcopy(nearest)
    recaptured.update(content_hash='c'*64, collected_at='2026-10-08T02:00:00Z')
    events = [old, nearest, recaptured]
    for i in range(10):
        events.append(event('SK하이닉스 공급계약 '+str(i), digest=format(i, 'x'),
            url='https://www.asiae.co.kr/article/post-'+str(i), published=f'2026-10-08T{i:02d}:00:00Z',
            collected=f'2026-10-08T{i:02d}:30:00Z'))
    selected = build(tmp_path, events)['rows'][0]['events']
    assert len(selected) == 8
    before = [row for row in selected if row['timing'] == 'captured_before_first']
    assert [row['url'] for row in before] == ['https://www.asiae.co.kr/article/old', 'https://www.asiae.co.kr/article/nearest']
    assert before[1]['collected_at'] == '2026-10-07T01:00:00Z'
    assert [row['url'] for row in selected if row['timing'] != 'captured_before_first'] == [
        'https://www.asiae.co.kr/article/post-'+str(i) for i in range(4, 10)]


def test_balanced_display_keeps_morning_opinion_and_later_pending_report_against_many_post_reports(tmp_path):
    morning = event('SK하이닉스 저평가 IBK 의견', digest='b', url='https://www.asiae.co.kr/article/morning')
    later = event('삼성전자·SK하이닉스 실적 발표 하루 앞두고 외인·기관 엇갈린 선택', digest='c',
        url='https://www.asiae.co.kr/article/pending', published='2026-10-07T07:22:42Z',
        collected='2026-10-07T08:08:03Z')
    events = [morning, later]
    for i in range(10):
        events.append(event('SK하이닉스 후속 보도 '+str(i), digest=format(i, 'x'),
            url='https://www.asiae.co.kr/article/after-'+str(i), published=f'2026-10-08T{i:02d}:00:00Z',
            collected=f'2026-10-08T{i:02d}:30:00Z'))
    selected = build(tmp_path, events)['rows'][0]['events']
    assert len(selected) == 8
    assert [row['url'] for row in selected[:2]] == ['https://www.asiae.co.kr/article/morning',
        'https://www.asiae.co.kr/article/pending']
    assert all(row['timing'] == 'captured_before_first' for row in selected[:2])
    assert selected[0]['collected_at'] == '2026-10-07T01:00:00Z'
    assert selected[1]['collected_at'] == '2026-10-07T08:08:03Z'


@pytest.mark.parametrize(('pre_count', 'after_count', 'expected_pre', 'expected_after'), [
    (6, 10, [2,3,4,5], [6,7,8,9]),
    (10, 0, [2,3,4,5,6,7,8,9], []),
    (0, 10, [], [2,3,4,5,6,7,8,9]),
    (2, 10, [0,1], [4,5,6,7,8,9]),
    (10, 2, [4,5,6,7,8,9], [0,1]),
])
def test_balanced_display_preserves_both_sides_and_backfills_unused_capacity(tmp_path, pre_count, after_count,
        expected_pre, expected_after):
    events = []
    for i in range(pre_count):
        events.append(event('SK하이닉스 검출 전 보도 '+str(i), content_hash=format(i+1000,'064x'),
            url='https://www.asiae.co.kr/article/pre-'+str(i), published=f'2026-10-07T{i:02d}:00:00Z',
            collected=f'2026-10-07T{i:02d}:01:00Z'))
    for i in range(after_count):
        events.append(event('SK하이닉스 검출 후 보도 '+str(i), content_hash=format(i+2000,'064x'),
            url='https://www.asiae.co.kr/article/post-'+str(i), published=f'2026-10-08T{i:02d}:00:00Z',
            collected=f'2026-10-08T{i:02d}:01:00Z'))
    selected = build(tmp_path, events)['rows'][0]['events']
    assert len(selected) == 8
    assert [row['url'] for row in selected if row['timing'] == 'captured_before_first'] == [
        'https://www.asiae.co.kr/article/pre-'+str(i) for i in expected_pre]
    assert [row['url'] for row in selected if row['timing'] != 'captured_before_first'] == [
        'https://www.asiae.co.kr/article/post-'+str(i) for i in expected_after]


def test_corrupt_issued_row_cannot_produce_a_retroactive_first_detection(tmp_path):
    saved = journal(tmp_path)
    saved['issued'][0]['board']['generated_at'] = '2026-09-01T00:00:00Z'
    with pytest.raises(ValueError, match='journal'):
        module().build_catalyst_context(board(), saved, [event()], validation=validation(), now=CAPTURE)


@pytest.mark.parametrize(('field', 'replacement'), [
    ('used_in_selection', True), ('association_status', 'proven'),
    ('input_fingerprint', 'f'*64), ('decision_at', FIRST), ('snapshot_id', '0'*64),
])
def test_public_projection_rejects_identity_or_selection_claim_tampering(tmp_path, field, replacement):
    value = build(tmp_path, [event()])
    value[field] = replacement
    assert module().public_catalyst_context(value, board(), now=CAPTURE) is None


def test_public_projection_rejects_resealed_semantic_time_or_extra_field_tampering(tmp_path):
    original = build(tmp_path, [event()])
    for mutate in (
        lambda v: v['rows'][0]['events'][0].update(timing='reported_after_first'),
        lambda v: v['rows'][0].update(first_detected_at='2026-10-10T00:00:00Z'),
        lambda v: v['validation'].update(matured_decisions=1),
        lambda v: v.update(private_path='C:/secret'),
    ):
        value = deepcopy(original)
        mutate(value)
        value['snapshot_id'] = store._hash({k:v for k,v in value.items() if k != 'snapshot_id'})
        assert module().public_catalyst_context(value, board(), now=CAPTURE) is None


def test_public_projection_returns_owned_copy_and_requires_timezone(tmp_path):
    value = build(tmp_path, [event()])
    public = module().public_catalyst_context(value, board(), now='2026-10-09T20:00:00+09:00')
    assert public == value and public is not value
    public['rows'][0]['events'].clear()
    assert len(value['rows'][0]['events']) == 1
    assert module().public_catalyst_context(value, board(), now='2026-10-09T11:00:00') is None
