"""lotto_analysis 단위 테스트."""
import json
import logging
import time
import pytest
from datetime import datetime
from unittest.mock import MagicMock


def _workflow(monkeypatch, tmp_path):
    import lotto_analysis as lotto
    draw = {'drwNo': 1243, 'drwNoDate': '2026-09-26', 'bnusNo': 7,
            **{f'drwtNo{i}': i for i in range(1, 7)},
            'source': 'dhlottery_official',
            'source_url': 'https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd=1243',
            'fetched_at': '2026-10-02T00:00:00Z'}
    posts = {}
    calls = []
    candidates = {'균형형': {'desc': '균형', 'sets': [{'numbers': [1, 2, 3, 4, 5, 6], 'score': 95}]}}
    monkeypatch.setattr(lotto, 'WORKFLOW_DIR', str(tmp_path / 'lotto'), raising=False)
    from datetime import timezone
    monkeypatch.setattr(lotto, '_utc_now', lambda: datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc), raising=False)
    monkeypatch.setattr(lotto, 'load_history', lambda: [draw.copy()])
    monkeypatch.setattr(lotto, 'refresh_history', lambda rows: rows)
    monkeypatch.setattr(lotto, 'ensure_fresh_history', lambda rows: None)
    monkeypatch.setattr(lotto, 'login', lambda: 'fake-token')
    monkeypatch.setattr(lotto, 'fetch_official_draw', lambda no: draw.copy(), raising=False)
    monkeypatch.setattr(lotto, 'generate_candidates', lambda *args, **kwargs: calls.append('generate') or candidates)
    monkeypatch.setattr(lotto, 'generate_lotto_post_openai', lambda *args: calls.append('write') or
                        {'title': 'LLM title', 'content': '<p>새 추천 설명</p>{{IMAGE}}', 'image_prompt': 'balls'})
    monkeypatch.setattr(lotto, 'ensure_image_html', lambda content, *args: (content.replace('{{IMAGE}}', '<img src="/test.png" />'), 'test'))

    class Response:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = json.dumps(payload)
        def json(self):
            return self._payload

    def get(url, **kwargs):
        if '/boards/lotto-ai/posts' in url:
            return Response({'posts': [p for p in posts.values() if not p['is_notice']],
                             'notices': [p for p in posts.values() if p['is_notice']], 'total_pages': 1,
                             'board': {'slug': 'lotto-ai'}})
        post_id = int(url.rsplit('/', 1)[-1])
        return Response({'post': posts[post_id]})

    def post(url, **kwargs):
        payload = kwargs['json']
        post_id = max(posts, default=0) + 1
        posts[post_id] = {'id': post_id, **payload, 'board': {'slug': 'lotto-ai'},
                          'is_notice': False, 'created_at': '2026-10-02T00:00:00'}
        calls.append(('post', payload['title'], payload['content']))
        return Response(posts[post_id], 201)

    def put(url, **kwargs):
        if url.endswith('/notice'):
            post_id = int(url.split('/')[-2])
            posts[post_id]['is_notice'] = True
        else:
            post_id = int(url.rsplit('/', 1)[-1])
            posts[post_id].update(kwargs['json'])
        return Response({'is_notice': True})

    monkeypatch.setattr(lotto.requests, 'get', get)
    monkeypatch.setattr(lotto.requests, 'post', post)
    monkeypatch.setattr(lotto.requests, 'put', put)
    return lotto, posts, calls, draw, candidates, Response


def test_workflow_posts_result_before_recommendation_and_reuses_verified_posts(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    result = lotto.run_lotto_analysis_post()
    assert result and len(posts) == 2
    publications = [item for item in calls if isinstance(item, tuple)]
    assert '제1243회' in publications[0][1] and '결과' in publications[0][1]
    assert '제1244회' in publications[1][1] and '추천' in publications[1][1]
    content = publications[1][2]
    assert content.index('지난 추천 결과') < content.index('data-lotto-recommendations')
    assert '대조 보류' in content and '/dashboard/community/post/1' in content
    before = list(calls)
    assert lotto.run_lotto_analysis_post()['skipped'] is True
    assert calls == before


def test_results_only_never_generates_candidates_or_calls_llm(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    assert lotto.run_lotto_analysis_post(results_only=True)
    assert len(posts) == 1 and all(isinstance(call, tuple) for call in calls)


def test_workflow_remote_query_failure_blocks_publication(monkeypatch, tmp_path):
    lotto, posts, _, _, _, Response = _workflow(monkeypatch, tmp_path)
    monkeypatch.setattr(lotto.requests, 'get', lambda *args, **kwargs: Response({}, 503))
    assert lotto.run_lotto_analysis_post() is False
    assert not posts


def test_workflow_unconfirmed_official_draw_blocks_recommendation(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    monkeypatch.setattr(lotto, 'fetch_official_draw', lambda no: None)
    assert lotto.run_lotto_analysis_post() is False
    assert not posts and not calls


def test_result_lookup_does_not_confuse_next_recommendation_duplicate(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    posts[9] = {'id': 9, 'title': '제1244회 로또 추천 결과 — 추첨 결과', 'content': '<p>다른 결과</p>',
                'board': {'slug': 'lotto-ai'}, 'is_notice': True, 'created_at': '2026-10-02T00:00:00'}
    assert lotto.run_lotto_analysis_post()
    assert any('제1244회 AI 로또 분석' in p['title'] for p in posts.values())
    assert calls.count('generate') == 1


def test_workflow_pin_failure_reuses_post_and_prepared_candidates(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, Response = _workflow(monkeypatch, tmp_path)
    original_put = lotto.requests.put
    def fail_recommendation_pin(url, **kwargs):
        post_id = int(url.split('/')[-2])
        if '제1244회' in posts[post_id]['title']:
            return Response({}, 503)
        return original_put(url, **kwargs)
    monkeypatch.setattr(lotto.requests, 'put', fail_recommendation_pin)
    assert lotto.run_lotto_analysis_post() is False
    assert len(posts) == 2
    monkeypatch.setattr(lotto.requests, 'put', original_put)
    assert lotto.run_lotto_analysis_post()
    assert len(posts) == 2 and calls.count('generate') == calls.count('write') == 1
    assert all(p['is_notice'] for p in posts.values())


def test_workflow_publication_body_mismatch_is_not_completed(monkeypatch, tmp_path):
    lotto, posts, _, _, _, _ = _workflow(monkeypatch, tmp_path)
    original_get = lotto.requests.get
    def altered_get(url, **kwargs):
        response = original_get(url, **kwargs)
        if '/posts/' in url:
            response._payload = {'post': {**response._payload['post'], 'content': '<p>changed</p>'}}
        return response
    monkeypatch.setattr(lotto.requests, 'get', altered_get)
    assert lotto.run_lotto_analysis_post() is False
    assert len(posts) == 1


def test_workflow_singleflight_blocks_parallel_run(monkeypatch, tmp_path):
    from filelock import FileLock
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    root = tmp_path / 'lotto'
    root.mkdir(parents=True)
    with FileLock(str(root / 'workflow.lock')):
        assert lotto.run_lotto_analysis_post() is False
    assert not posts and not calls


def _existing_recommendation(lotto, posts, draw_no, candidates, post_id=2, created_at='2026-10-02T00:00:00'):
    body = lotto.canonical_recommendation_html(draw_no, candidates) + '<p>기존 설명 유지</p><img src="/original.png" />'
    posts[post_id] = {'id': post_id, 'title': f'제{draw_no}회 AI 로또 분석', 'content': body,
                      'board': {'slug': 'lotto-ai'}, 'is_notice': True, 'created_at': created_at}
    return body


def test_existing_recommendation_preface_preserves_numbers_and_image_without_regeneration(monkeypatch, tmp_path):
    lotto, posts, calls, _, candidates, _ = _workflow(monkeypatch, tmp_path)
    original = _existing_recommendation(lotto, posts, 1244, candidates)
    assert lotto.run_lotto_analysis_post()['skipped']
    assert posts[2]['content'].endswith(original)
    assert posts[2]['content'].count('data-lotto-review-link') == 1
    assert 'generate' not in calls and 'write' not in calls
    first_body = posts[2]['content']
    assert lotto.run_lotto_analysis_post()['skipped']
    assert posts[2]['content'] == first_body


def test_preface_put_failure_retries_only_the_failed_stage(monkeypatch, tmp_path):
    lotto, posts, calls, _, candidates, Response = _workflow(monkeypatch, tmp_path)
    original = _existing_recommendation(lotto, posts, 1244, candidates)
    original_put = lotto.requests.put
    monkeypatch.setattr(lotto.requests, 'put', lambda url, **kwargs:
                        Response({}, 503) if not url.endswith('/notice') else original_put(url, **kwargs))
    assert lotto.run_lotto_analysis_post() is False
    assert posts[2]['content'] == original
    monkeypatch.setattr(lotto.requests, 'put', original_put)
    assert lotto.run_lotto_analysis_post()['skipped']
    assert posts[2]['content'].endswith(original)
    assert len(posts) == 2 and 'generate' not in calls and 'write' not in calls


def test_post_response_loss_recovers_identical_recommendation_without_duplicate(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    original_post = lotto.requests.post
    def lose_response(url, **kwargs):
        response = original_post(url, **kwargs)
        if '제1244회' in kwargs['json']['title']:
            raise lotto.requests.Timeout('response lost after commit')
        return response
    monkeypatch.setattr(lotto.requests, 'post', lose_response)
    assert lotto.run_lotto_analysis_post() is False
    assert len(posts) == 2
    body = posts[2]['content']
    monkeypatch.setattr(lotto.requests, 'post', original_post)
    assert lotto.run_lotto_analysis_post()['skipped']
    assert len(posts) == 2 and posts[2]['content'] == body
    assert calls.count('generate') == calls.count('write') == 1


def test_result_uses_published_original_numbers_and_archives_observed_snapshot(monkeypatch, tmp_path):
    lotto, posts, calls, _, candidates, _ = _workflow(monkeypatch, tmp_path)
    original = _existing_recommendation(lotto, posts, 1243, candidates, created_at='2026-09-25T08:00:00')
    assert lotto.run_lotto_analysis_post(results_only=True)
    report = lotto._load_publication('result', 1243)
    assert report['report']['summary']['winning_sets'] == 1
    assert report['report']['rows'][0]['rank'] == 1
    assert report['source_post']['content_hash'] == lotto._content_hash(original)
    assert lotto._load_publication('recommendation', 1243)['original_post']['content'] == original
    assert 'generate' not in calls and 'write' not in calls


def test_recommendation_uses_official_latest_draw_instead_of_divergent_history(monkeypatch, tmp_path):
    lotto, _, _, draw, _, _ = _workflow(monkeypatch, tmp_path)
    different = {**draw, 'drwtNo1': 10}
    monkeypatch.setattr(lotto, 'load_history', lambda: [different])
    assert lotto.run_lotto_analysis_post()
    state = lotto._load_publication('recommendation', 1244)
    assert state['stats']['last_draw']['numbers'] == [1, 2, 3, 4, 5, 6]


def test_llm_changed_recommendation_numbers_are_replaced_without_another_paid_call(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    def incorrect_draft(*args):
        calls.append('write')
        return {'title': 'bad', 'content': '<h2>제1244회 추천 번호</h2><h3>균형형</h3>'
                '<li>세트 1: <strong>10, 11, 12, 13, 14, 15</strong></li>{{IMAGE}}'}
    monkeypatch.setattr(lotto, 'generate_lotto_post_openai', incorrect_draft)
    assert lotto.run_lotto_analysis_post()
    content = next(p['content'] for p in posts.values() if '제1244회' in p['title'])
    assert '10, 11, 12, 13, 14, 15' not in content
    assert '1, 2, 3, 4, 5, 6' in content and calls.count('write') == 1


def test_official_provenance_failure_cannot_publish_a_pending_result(monkeypatch, tmp_path):
    lotto, posts, _, draw, _, _ = _workflow(monkeypatch, tmp_path)
    monkeypatch.setattr(lotto, 'fetch_official_draw', lambda no: {**draw, 'source_url': 'https://mirror.invalid'})
    assert lotto.run_lotto_analysis_post(results_only=True) is False
    assert not posts


def test_new_recommendation_after_draw_cutoff_never_generates_or_posts(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    from datetime import timezone
    monkeypatch.setattr(lotto, '_utc_now', lambda: datetime(2026, 10, 3, 11, 40, tzinfo=timezone.utc), raising=False)
    assert lotto.run_lotto_analysis_post() is False
    assert len(posts) == 1 and 'generate' not in calls and 'write' not in calls


def test_recommendation_crossing_cutoff_during_draft_cannot_publish(monkeypatch, tmp_path):
    lotto, posts, calls, _, candidates, _ = _workflow(monkeypatch, tmp_path)
    from datetime import timezone
    clock = [datetime(2026, 10, 3, 11, 30, tzinfo=timezone.utc)]
    monkeypatch.setattr(lotto, '_utc_now', lambda: clock[0], raising=False)
    def delayed_draft(*args):
        calls.append('write')
        clock[0] = datetime(2026, 10, 3, 11, 40, tzinfo=timezone.utc)
        return {'content': '<p>long draft</p>{{IMAGE}}'}
    monkeypatch.setattr(lotto, 'generate_lotto_post_openai', delayed_draft)
    assert lotto.run_lotto_analysis_post() is False
    assert len(posts) == 1 and calls.count('write') == 1


@pytest.mark.parametrize('payload', [
    {'posts': []}, {'posts': [], 'notices': [], 'total_pages': 1},
    {'posts': [], 'notices': [], 'total_pages': '1', 'board': {'slug': 'lotto-ai'}},
    {'posts': [], 'notices': [], 'total_pages': 1, 'board': {'slug': 'notice'}},
])
def test_incomplete_board_response_is_not_treated_as_missing_post(monkeypatch, tmp_path, payload):
    lotto, posts, calls, _, _, Response = _workflow(monkeypatch, tmp_path)
    monkeypatch.setattr(lotto.requests, 'get', lambda *args, **kwargs: Response(payload))
    assert lotto.run_lotto_analysis_post() is False
    assert not posts and not calls


def test_live_legacy_titles_are_matched_without_regenerating_this_weeks_numbers(monkeypatch, tmp_path):
    lotto, posts, calls, _, candidates, _ = _workflow(monkeypatch, tmp_path)
    _existing_recommendation(lotto, posts, 1243, candidates, post_id=245, created_at='2026-09-25T08:01:09')
    posts[245]['title'] = '로또 6/45 제1243회 통계 분석과 추천 조합'
    original = _existing_recommendation(lotto, posts, 1244, candidates, post_id=255)
    posts[255]['title'] = '로또 6/45 제1244회 주간 통계 분석과 추천 조합'
    assert lotto.run_lotto_analysis_post()['post_id'] == 255
    assert len(posts) == 3 and posts[255]['content'].endswith(original)
    report = lotto._load_publication('result', 1243)
    assert report['source_post']['post_id'] == 245 and report['report']['summary']['winning_sets'] == 1
    assert 'generate' not in calls and 'write' not in calls


def _past_recommendation_for_embedded_review(lotto, posts):
    past = {'안정형': {'desc': '지난 추천', 'sets': [
        {'numbers': [1, 2, 3, 10, 11, 12], 'score': 75},
        {'numbers': [10, 11, 12, 13, 14, 15], 'score': 60},
    ]}}
    _existing_recommendation(lotto, posts, 1243, past, post_id=245, created_at='2026-09-25T08:01:09')


def test_next_recommendation_embeds_all_previous_sets_and_official_result_in_one_post(monkeypatch, tmp_path):
    lotto, posts, _, _, _, _ = _workflow(monkeypatch, tmp_path)
    _past_recommendation_for_embedded_review(lotto, posts)
    result = lotto.run_lotto_analysis_post()
    assert result
    body = posts[result['post_id']]['content']
    report = lotto._load_publication('result', 1243)['report']
    assert report['content'] in body
    assert 'data-lotto-result="1" data-draw-no="1243"' in body
    assert '1, 2, 3, 10, 11, 12' in body and '10, 11, 12, 13, 14, 15' in body
    assert '본번호 일치' in body and '대조 등수' in body and '미당첨 1조합' in body
    assert body.index(report['content']) < body.index('data-lotto-recommendations')
    assert lotto.extract_recommendation_sets(body, 1244) == [
        {'style': '균형형', 'set_index': 1, 'numbers': [1, 2, 3, 4, 5, 6]},
    ]


def test_full_previous_result_with_legacy_current_numbers_repairs_once_without_mixing_draws(monkeypatch, tmp_path):
    lotto, posts, calls, _, _, _ = _workflow(monkeypatch, tmp_path)
    _past_recommendation_for_embedded_review(lotto, posts)
    legacy = ('<h2>제1244회 후보 조합</h2><h3>균형형 — 이번 추천</h3>'
              '<ul><li>세트 1: <strong>1, 2, 3, 4, 5, 6</strong> / 점수 95</li></ul>'
              '<img src="/legacy-original.png" />')
    posts[255] = {'id': 255, 'title': '로또 6/45 제1244회 통계 분석과 추천 조합', 'content': legacy,
                  'board': {'slug': 'lotto-ai'}, 'is_notice': True, 'created_at': '2026-10-02T08:00:00'}
    assert lotto.run_lotto_analysis_post()['post_id'] == 255
    first = posts[255]['content']
    assert first.endswith(legacy) and '1, 2, 3, 10, 11, 12' in first
    assert lotto.extract_recommendation_sets(first, 1244) == [
        {'style': '균형형', 'set_index': 1, 'numbers': [1, 2, 3, 4, 5, 6]},
    ]
    assert lotto.run_lotto_analysis_post()['skipped']
    assert posts[255]['content'] == first and first.count('data-lotto-review-link') == 1
    assert 'generate' not in calls and 'write' not in calls


def test_embedded_pending_review_keeps_the_original_comparison_hold_reason(monkeypatch, tmp_path):
    lotto, posts, _, _, _, _ = _workflow(monkeypatch, tmp_path)
    result = lotto.run_lotto_analysis_post()
    assert result
    state = lotto._load_publication('result', 1243)
    body = posts[result['post_id']]['content']
    assert state['report']['content'] in body
    assert state['report']['summary']['reason'] in body and '대조 보류' in body
    assert 'data-lotto-result="1"' in body


def test_parse_llm_json_allows_raw_newlines_in_content():
    import lotto_analysis

    raw = '{"title":"t","content":"<p>a\nb</p>","image_prompt":"balls"}'

    parsed = lotto_analysis._parse_llm_json(raw)

    assert parsed["title"] == "t"
    assert parsed["content"] == "<p>a\nb</p>"


def test_generate_lotto_post_openai_uses_configured_model(monkeypatch):
    import lotto_analysis

    class FakeResponses:
        def __init__(self):
            self.model = None
            self.input = None

        def create(self, model, input):
            self.model = model
            self.input = input
            payload = {
                "title": "제1231회 AI 로또 분석",
                "content": "<p>안녕하세요.</p>",
                "image_prompt": "lotto balls, no text",
            }
            return type("Response", (), {"output_text": json.dumps(payload)})()

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    fake_client = FakeClient()
    monkeypatch.setenv("LOTTO_OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setattr(lotto_analysis, "get_openai_client", lambda: fake_client)

    stats = {
        "total_draws": 1230,
        "last_draw": {
            "drwNo": 1230,
            "date": "2026-06-27",
            "numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
        "hot_10": [13, 18, 28, 41, 9, 44],
        "cold_10": [3, 2, 5, 7, 10, 15],
        "hot_30": [11, 22, 33, 44, 5, 16],
        "cold_30": [1, 4, 8, 12, 19, 27],
        "odd_even": {"odd_pct": 50.0, "even_pct": 50.0},
        "sum_stats": {"mean": 135.0, "stddev": 20.0},
        "section_dist": {"1-10": 1.0},
        "consecutive_pct": 20.0,
        "gap": {1: 3, 2: 7, 3: 1, 4: 9},
    }
    candidates = {
        "balanced": {
            "desc": "balanced set",
            "sets": [{"numbers": [1, 10, 14, 20, 38, 39], "score": 100.0}],
        }
    }

    post = lotto_analysis.generate_lotto_post_openai(stats, candidates)

    assert fake_client.responses.model == "gpt-5.5"
    assert "draw number 1231" in fake_client.responses.input
    assert post["provider"] == "openai"
    assert post["model"] == "gpt-5.5"
    assert "{{IMAGE}}" in post["content"]


def test_expected_latest_draw_date_uses_previous_draw_before_saturday_cutoff():
    import lotto_analysis

    expected = lotto_analysis._expected_latest_draw_date(datetime(2026, 7, 4, 11, 0))

    assert expected.strftime("%Y-%m-%d") == "2026-06-27"


def test_expected_latest_draw_date_uses_current_saturday_after_draw_cutoff():
    import lotto_analysis

    expected = lotto_analysis._expected_latest_draw_date(datetime(2026, 7, 4, 21, 1))

    assert expected.strftime("%Y-%m-%d") == "2026-07-04"


@pytest.mark.parametrize(('now', 'latest_date', 'stale'), [
    (datetime(2026, 10, 2, 17, 0), '2026-09-26', False),
    (datetime(2026, 10, 2, 17, 0), '2026-09-19', True),
    (datetime(2026, 10, 3, 20, 59), '2026-09-26', False),
    (datetime(2026, 10, 3, 21, 0), '2026-10-03', False),
    (datetime(2026, 10, 3, 21, 0), '2026-09-26', True),
])
def test_default_kst_freshness_compares_draw_dates_without_timezone_error(monkeypatch, now, latest_date, stale):
    import lotto_analysis as lotto
    from datetime import timedelta, timezone
    from types import SimpleNamespace

    clock = now.replace(tzinfo=timezone(timedelta(hours=9)))
    alerts = []
    # Exercise the default now() path, including its KST-aware timestamp.
    monkeypatch.setattr(lotto, 'datetime', SimpleNamespace(now=lambda tz=None: clock, strptime=datetime.strptime))
    monkeypatch.setattr(lotto, '_alert_telegram', alerts.append)
    draws = [{'drwNo': 1243, 'drwNoDate': latest_date}]
    if stale:
        with pytest.raises(lotto.LottoFetchError, match='7일 지연'):
            lotto.ensure_fresh_history(draws)
        assert len(alerts) == 1
    else:
        lotto.ensure_fresh_history(draws)
        assert not alerts


def test_lotteryextreme_recent_history_parser(monkeypatch):
    import lotto_analysis

    html = """
    <TABLE class='results3'>
    <tr class='cy'><td class='cx'>2026-06-27 (2026년 06월 27일) (1230) &nbsp;</tr>
    <TR><TD class='c1'><ul class='displayball' style='justify-content:center'><li>3<li>8<li>9<li>22<li>28<li>42<li class="dbx"> <li>45</ul></tr>
    <tr class='cy'><td class='cx'>2026-06-20 (2026년 06월 20일) (1229) &nbsp;</tr>
    <TR><TD class='c1'><ul class='displayball' style='justify-content:center'><li>12<li>13<li>29<li>34<li>37<li>42<li class="dbx"> <li>16</ul></tr>
    </TABLE>
    """

    class FakeResponse:
        status_code = 200
        text = html

    monkeypatch.setattr(lotto_analysis.requests, "get", lambda *args, **kwargs: FakeResponse())

    draw = lotto_analysis._fetch_draw_from_lotteryextreme(1229)

    assert draw == {
        "drwNo": 1229,
        "drwNoDate": "2026-06-20",
        "drwtNo1": 12,
        "drwtNo2": 13,
        "drwtNo3": 29,
        "drwtNo4": 34,
        "drwtNo5": 37,
        "drwtNo6": 42,
        "bnusNo": 16,
    }


def test_generate_lotto_post_fallback_contains_draw_and_candidates():
    import lotto_analysis

    stats = {
        "last_draw": {
            "drwNo": 1230,
            "date": "2026-06-27",
            "numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
        "hot_10": [13, 18, 28, 41, 9, 44],
        "cold_10": [3, 2, 5, 7, 10, 15],
        "odd_even": {"odd_pct": 50.0, "even_pct": 50.0},
        "sum_stats": {"mean": 135.0, "stddev": 20.0},
        "gap": {1: 3, 2: 7, 3: 1, 4: 9},
    }
    candidates = {
        "안정형": {
            "desc": "분산형",
            "sets": [{"numbers": [1, 10, 14, 20, 38, 39], "score": 100.0}],
        }
    }

    post = lotto_analysis.generate_lotto_post_fallback(stats, candidates, reason="unit test")

    assert "제1231회" in post["title"]
    assert "1, 10, 14, 20, 38, 39" in post["content"]
    assert "LLM 문장 생성기" in post["content"]
    # 폴백 본문의 플레이스홀더가 f-string 에 먹혀 {IMAGE} 로 새면 이미지가 엉뚱한 데 붙는다
    assert "{{IMAGE}}" in post["content"]


def _image_stats_candidates():
    stats = {
        "last_draw": {"drwNo": 1236, "date": "2026-08-01",
                      "numbers": [1, 2, 3, 4, 5, 6], "bonus": 7},
    }
    candidates = {
        "안정형": {"desc": "분산형",
                 "sets": [{"numbers": [3, 11, 19, 28, 34, 42], "score": 95.0}]},
    }
    return stats, candidates


def test_generate_image_creates_client_when_none(monkeypatch):
    """GPT-5.5 가 본문을 쓰는 정상 경로에서도 Nano Banana 가 호출돼야 한다.

    회귀 대상: `generate_image(client, ...) if client else None` 때문에
    제1231~1236회 게시글이 Nano Banana 를 통째로 건너뛴 사고.
    """
    import lotto_analysis
    import sys
    from types import ModuleType, SimpleNamespace

    # The unit owns a fake provider client, so isolate its SDK config constructor
    # too. Native SDK imports are neither a provider contract test nor network QA.
    sdk = ModuleType('google.genai')
    sdk.types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setitem(sys.modules, 'google.genai', sdk)

    made = {}

    class _Part:
        class inline_data:
            data = b"PNGDATA"

    class _Client:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                made["model"] = kwargs.get("model")
                made['modalities'] = kwargs['config'].response_modalities
                response = MagicMock()
                response.candidates = [MagicMock(content=MagicMock(parts=[_Part()]))]
                return response

    monkeypatch.setattr(lotto_analysis, "get_gemini_client", lambda: _Client())

    assert lotto_analysis.generate_image(None, "prompt") == b"PNGDATA"
    assert made['modalities'] == ['TEXT', 'IMAGE']
    assert made["model"] == "gemini-2.5-flash-image"


def test_ensure_image_html_falls_back_to_local_png(monkeypatch, tmp_path):
    """외부 이미지 API 가 전부 죽어도 <img> 는 반드시 들어간다."""
    import lotto_analysis

    stats, candidates = _image_stats_candidates()
    monkeypatch.setattr(lotto_analysis, "generate_image", lambda *a, **k: None)
    monkeypatch.setattr(lotto_analysis, "generate_openai_image", lambda *a, **k: None)
    monkeypatch.setattr(lotto_analysis, "UPLOAD_DIR", str(tmp_path))
    alerts = []
    monkeypatch.setattr(lotto_analysis, "_alert_telegram", lambda text: alerts.append(text))

    content, source = lotto_analysis.ensure_image_html(
        "<p>본문</p>\n{{IMAGE}}", "prompt", stats, candidates
    )

    assert source == "local_card"
    assert '<img src="/api/community/uploads/' in content
    assert content.endswith('.png" alt="AI 로또 분석 일러스트" '
                            'style="width:100%;max-width:680px;border-radius:12px;'
                            'margin:16px auto;display:block;" />')
    assert "{{IMAGE}}" not in content
    assert alerts, "로컬 폴백을 쓰면 텔레그램 경보가 나가야 한다"
    saved = list(tmp_path.glob("*.png"))
    assert len(saved) == 1 and saved[0].stat().st_size > 0


def test_ensure_image_html_never_saves_svg(monkeypatch, tmp_path):
    """svg 는 serve_upload() 화이트리스트에 없어 404 → 저장 자체를 금지."""
    import lotto_analysis

    stats, candidates = _image_stats_candidates()
    monkeypatch.setattr(lotto_analysis, "generate_image", lambda *a, **k: None)
    monkeypatch.setattr(lotto_analysis, "generate_openai_image", lambda *a, **k: None)
    monkeypatch.setattr(lotto_analysis, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(lotto_analysis, "_alert_telegram", lambda text: None)

    content, _ = lotto_analysis.ensure_image_html("<p>본문</p>", "prompt", stats, candidates)

    assert not list(tmp_path.glob("*.svg"))
    assert ".svg" not in content
    assert not hasattr(lotto_analysis, "save_svg_image")
    assert not hasattr(lotto_analysis, "generate_openai_svg_image")


def test_ensure_image_html_inserts_when_placeholder_missing(monkeypatch, tmp_path):
    """LLM 이 {{IMAGE}} 를 빠뜨려도 이미지는 본문 상단에 들어간다."""
    import lotto_analysis

    stats, candidates = _image_stats_candidates()
    monkeypatch.setattr(lotto_analysis, "generate_image", lambda *a, **k: b"\x89PNG-fake")
    monkeypatch.setattr(lotto_analysis, "UPLOAD_DIR", str(tmp_path))

    content, source = lotto_analysis.ensure_image_html(
        "<p>플레이스홀더 없는 본문</p>", "prompt", stats, candidates
    )

    assert source == "nano_banana"
    assert content.startswith('<img src="/api/community/uploads/')
    assert "<p>플레이스홀더 없는 본문</p>" in content


def test_render_fallback_card_png_is_a_real_png():
    """로컬 폴백은 외부 호출 없이 실제 PNG 를 만들어야 한다."""
    import lotto_analysis

    stats, candidates = _image_stats_candidates()
    data = lotto_analysis.render_fallback_card_png(stats, candidates)

    assert data and data[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(data)).size == (1280, 720)


def test_existing_lotto_post_for_draw_detects_visible_duplicate(monkeypatch, tmp_db):
    import sqlite3
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute(
        "INSERT INTO posts (id, board_id, title, content, is_notice, created_at) VALUES (133, 7, '제1229회 AI 로또 분석', '', 1, '2026-06-19')"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))

    existing = lotto_analysis._existing_lotto_post_for_draw(1229)

    assert existing == {'post_id': 133, 'title': '제1229회 AI 로또 분석'}


def test_logger_used_for_errors(caplog, clean_env, monkeypatch):
    """run_lotto_analysis_post 에서 예외 발생 시 traceback 이 logger 로 기록되어야 함.

    회귀 보호: 과거 print() 만 사용해서 traceback 이 사라졌던 결함 ①.
    """
    # load_history 가 raise 하도록 강제
    import lotto_analysis
    # Task 3 의 idempotency guard 가 추가된 후에도 정상 흐름 진입하도록 mock
    # (raising=False — Task 1 시점에는 함수 미정의일 수 있음)
    monkeypatch.setattr(lotto_analysis, '_has_today_lotto_post', lambda: False, raising=False)
    monkeypatch.setattr(lotto_analysis, 'load_history',
                        MagicMock(side_effect=RuntimeError("forced test failure")))

    with caplog.at_level(logging.ERROR, logger='lotto_analysis'):
        result = lotto_analysis.run_lotto_analysis_post(dry_run=False)

    assert result is False, "예외 시 False 반환 유지"

    # traceback 이 logger 로 기록되었는지 검증
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1, "ERROR 레벨 로그가 최소 1건 있어야 함"

    has_traceback = any(
        r.exc_info is not None or 'forced test failure' in r.getMessage()
        for r in error_records
    )
    assert has_traceback, "logger.exception 또는 logger.error(exc_info=True) 사용 필요"


def test_create_post_has_timeout(monkeypatch):
    """create_post 의 requests.post 호출이 timeout 인자를 가져야 함.

    회귀 보호: timeout 없는 requests.post 가 무한 hang 가능했던 결함 ③.
    """
    import lotto_analysis
    captured = {}

    def fake_post(url, **kwargs):
        captured['kwargs'] = kwargs
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {'id': 999}
        return resp

    monkeypatch.setattr(lotto_analysis.requests, 'post', fake_post)

    lotto_analysis.create_post('fake_token', 'lotto-ai', 'title', '<p>body</p>')

    assert 'timeout' in captured['kwargs'], "create_post 의 requests.post 에 timeout 인자 필수"
    assert captured['kwargs']['timeout'] >= 15, "timeout 은 최소 15초 이상"


def test_pin_notice_has_timeout(monkeypatch):
    """pin_notice 의 requests.put 호출이 timeout 인자를 가져야 함."""
    import lotto_analysis
    captured = {}

    def fake_put(url, **kwargs):
        captured['kwargs'] = kwargs
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr(lotto_analysis.requests, 'put', fake_put)

    lotto_analysis.pin_notice('fake_token', 999)

    assert 'timeout' in captured['kwargs'], "pin_notice 의 requests.put 에 timeout 인자 필수"
    assert captured['kwargs']['timeout'] >= 15


def test_local_admin_token_no_create_app(monkeypatch, clean_env, tmp_db):
    """_local_admin_token() 이 `from app import create_app` 을 호출하지 않아야 함.

    회귀 보호: 결함 ⑤ — 과거에는 매 호출마다 create_app() 으로 Flask 인스턴스를
    만들어 모든 background worker 가 재시작되었음. 경량화 버전은 sqlite3 + HMAC 만 사용.
    """
    import sys
    import sqlite3
    import lotto_analysis

    # tmp_db 에 admin user 1명 삽입
    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute(
        "INSERT INTO users (id, email, role) VALUES (3, ?, 'admin')",
        ('point10890@gmail.com',)
    )
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')

    # `from app import create_app` 가 호출되면 즉시 에러
    # (이 라인이 함수 안에 lazy import 가 아니라 module-level import 면 fail)
    if 'app' in sys.modules:
        monkeypatch.setattr(sys.modules['app'], 'create_app',
                            MagicMock(side_effect=AssertionError("create_app called!")))

    token = lotto_analysis._local_admin_token()

    assert token is not None, "admin user 가 있는데 token 반환 안 됨"
    # Token 포맷: "user_id:expiry:sig" (32 hex chars)
    parts = token.split(':')
    assert len(parts) == 3, f"token 포맷 불일치: {token}"
    assert parts[0] == '3', f"user_id 불일치: {parts[0]}"
    assert int(parts[1]) > int(time.time()), "expiry 가 미래여야 함"
    assert len(parts[2]) == 32, "signature 가 32자여야 함 (truncated HMAC-SHA256)"


def test_local_admin_token_returns_none_without_admin(monkeypatch, clean_env, tmp_db):
    """admin user 없으면 None 반환 (raise 하지 않음)."""
    import sqlite3
    import lotto_analysis

    # users 테이블만 있고 admin 없는 상태
    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))

    assert lotto_analysis._local_admin_token() is None


def test_local_admin_token_signature_matches_flask(monkeypatch, clean_env, tmp_db):
    """경량화된 token 의 signature 가 Flask 의 generate_token 과 비트-동일해야 함.

    같은 (user_id, expiry, SECRET_KEY) 입력에 대해 동일 출력. 그래야 Flask 의
    validate_token() 이 통과함.
    """
    import sqlite3
    import hmac
    import hashlib
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute("INSERT INTO users (id, email, role) VALUES (3, 'a@b', 'admin')")
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    secret = 'unit-test-secret-7891'
    monkeypatch.setenv('SECRET_KEY', secret)

    token = lotto_analysis._local_admin_token()
    assert token is not None

    user_id_str, expiry_str, sig = token.split(':')
    expected_sig = hmac.new(
        secret.encode(),
        f"{user_id_str}:{expiry_str}".encode(),
        hashlib.sha256
    ).hexdigest()[:32]
    assert sig == expected_sig, "Flask generate_token 과 동일 signature 알고리즘이어야 함"


def test_login_falls_back_to_local_token_when_no_env(monkeypatch, clean_env, tmp_db):
    """ADMIN_TOKEN/PASSWORD 미설정 시 _local_admin_token() 으로 fallback."""
    import sqlite3
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute("INSERT INTO users (id, email, role) VALUES (3, 'admin@test', 'admin')")
    con.commit()
    con.close()

    import importlib
    importlib.reload(lotto_analysis)
    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    monkeypatch.setenv('SECRET_KEY', 'test-secret')

    # requests.post 가 호출되면 fail (HTTP path 가지 않아야)
    def fail_post(*args, **kwargs):
        raise AssertionError("HTTP login should not be called when password is unset")
    monkeypatch.setattr(lotto_analysis.requests, 'post', fail_post)

    token = lotto_analysis.login()

    assert token is not None
    assert token.startswith('3:'), f"local token expected, got: {token}"
