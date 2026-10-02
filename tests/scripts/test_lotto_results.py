"""Official draw integrity and published recommendation result regressions."""

from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

import pytest


KST = timezone(timedelta(hours=9))
AFTER_DRAW = datetime(2026, 9, 27, 9, 0, tzinfo=KST)


def draw():
    return {
        "drwNo": 1243, "drwNoDate": "2026-09-26",
        **{f"drwtNo{i}": n for i, n in enumerate([9, 18, 24, 38, 43, 44], 1)},
        "bnusNo": 35,
    }


def verified_draw():
    return dict(draw(), source="dhlottery_official",
                source_url="https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd=1243",
                fetched_at="2026-09-27T00:00:00+00:00")


def official_item(**changes):
    item = {
        "ltEpsd": 1243, "ltRflYmd": "20260926",
        **{f"tm{i}WnNo": n for i, n in enumerate([9, 18, 24, 38, 43, 44], 1)},
        "bnsWnNo": 35,
        **{f"rnk{i}WnAmt": n for i, n in enumerate([2592525282, 45087397, 1443902, 50000, 5000], 1)},
    }
    return dict(item, **changes)


def session_for(items):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": {"list": items}}
    session = Mock()
    session.get.return_value = response
    return session


def test_official_fetch_selects_exact_draw_from_surrounding_draws():
    from scripts import lotto_results as results

    session = session_for([official_item(ltEpsd=1242, ltRflYmd="20260919"), official_item()])
    actual = results.fetch_official_draw(1243, now=AFTER_DRAW, session=session)

    assert actual["drwNo"] == 1243
    assert actual["drwNoDate"] == "2026-09-26"
    assert results.get_numbers(actual) == [9, 18, 24, 38, 43, 44]
    assert actual["bnusNo"] == 35
    assert actual["source"] == "dhlottery_official"
    assert "selectPstLt645InfoNew.do" in actual["source_url"]
    assert actual["prizes"]["2"] == 45087397
    assert session.get.call_args.kwargs["params"]["srchLtEpsd"] == 1243
    assert session.get.call_args.kwargs["timeout"] <= 20


def test_draw_not_yet_finalized_never_calls_network():
    from scripts import lotto_results as results

    session = session_for([official_item()])
    assert results.fetch_official_draw(1243, now=datetime(2026, 9, 26, 20, 59, tzinfo=KST), session=session) is None
    session.get.assert_not_called()


def test_official_empty_or_wrong_draw_is_not_a_result():
    from scripts import lotto_results as results

    assert results.fetch_official_draw(1243, now=AFTER_DRAW, session=session_for([])) is None
    assert results.fetch_official_draw(1243, now=AFTER_DRAW, session=session_for([official_item(ltEpsd=1242)])) is None


@pytest.mark.parametrize("change", [
    {"drwtNo2": 9}, {"drwtNo1": 0}, {"drwtNo6": 46}, {"bnusNo": 44},
    {"bnusNo": True}, {"drwNoDate": "2026-09-19"}, {"drwNo": 1242},
])
def test_draw_integrity_rejects_invalid_official_data(change):
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.validate_draw(dict(draw(), **change), expected_draw_no=1243, now=AFTER_DRAW)


def test_future_draw_validation_blocks_fabricated_result():
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.validate_draw(draw(), now=datetime(2026, 9, 26, 18, 0, tzinfo=KST))


@pytest.mark.parametrize("numbers,rank", [
    ([44, 43, 38, 24, 18, 9], 1), ([9, 18, 24, 38, 43, 35], 2),
    ([9, 18, 24, 38, 43, 1], 3), ([9, 18, 24, 38, 35, 1], 4),
    ([9, 18, 24, 35, 1, 2], 5), ([9, 18, 35, 1, 2, 3], None),
    ([1, 2, 3, 4, 5, 6], None),
])
def test_rank_counts_bonus_only_for_second_prize(numbers, rank):
    from scripts import lotto_results as results

    actual = results.evaluate_set(numbers, draw())
    assert actual["rank"] == rank
    assert actual["match_count"] == len(set(numbers) & {9, 18, 24, 38, 43, 44})
    assert actual["bonus_match"] == (35 in numbers)
    assert actual["label"] == (f"{rank}등" if rank else "미당첨")


@pytest.mark.parametrize("numbers", [[1, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [True, 2, 3, 4, 5, 6]])
def test_invalid_recommendation_is_not_silently_counted(numbers):
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.evaluate_set(numbers, draw())


def candidates():
    return {"안정형": {"desc": "균형", "sets": [
        {"numbers": [9, 18, 24, 38, 43, 35], "score": 90},
        {"numbers": [1, 2, 3, 4, 5, 6], "score": 80},
    ]}, "실험형": {"desc": "실험", "sets": [{"numbers": [9, 18, 24, 35, 1, 2], "score": 70}]}}


def test_canonical_table_round_trip_preserves_all_styles_and_sets():
    from scripts import lotto_results as results

    html = results.canonical_recommendation_html(1243, candidates())
    recovered = results.extract_recommendation_sets(html, draw_no=1243)
    assert recovered == [
        {"style": "안정형", "set_index": 1, "numbers": [9, 18, 24, 38, 43, 35]},
        {"style": "안정형", "set_index": 2, "numbers": [1, 2, 3, 4, 5, 6]},
        {"style": "실험형", "set_index": 1, "numbers": [9, 18, 24, 35, 1, 2]},
    ]
    with pytest.raises(results.LottoResultError):
        results.extract_recommendation_sets(html, draw_no=1244)


def test_legacy_recovery_ignores_draw_and_hot_numbers_outside_recommendation_section():
    from scripts import lotto_results as results

    html = """<h2>지난 회차 복기</h2><p><strong>9, 18, 24, 38, 43, 44</strong></p>
    <h2>🔥 핫넘버</h2><p><strong>1, 2, 3, 4, 5, 6</strong></p>
    <h2>🎯 AI 추천 번호 (제1243회)</h2><h3>안정형 — 균형</h3>
    <ul><li><strong>3, 11, 19, 28, 34, 42</strong> (1세트 · 점수 95)</li></ul>
    <h3>실험형</h3><p><strong>9, 18, 24, 35, 1, 2</strong> — 실험</p>
    <h2>면책 고지</h2><strong>7, 8, 9, 10, 11, 12</strong>"""
    assert results.extract_recommendation_sets(html, draw_no=1243) == [
        {"style": "안정형", "set_index": 1, "numbers": [3, 11, 19, 28, 34, 42]},
        {"style": "실험형", "set_index": 1, "numbers": [9, 18, 24, 35, 1, 2]},
    ]


@pytest.mark.parametrize("html", [
    "<strong>1,2,3,4,5,6</strong>",
    "<h2>지난 회차 당첨번호</h2><strong>1,2,3,4,5,6</strong>",
    "<h2>AI 추천 번호 (제1242회)</h2><strong>1,2,3,4,5,6</strong>",
    "<h2>AI 추천 번호 (제1243회)</h2><strong>1,1,2,3,4,5</strong>",
])
def test_unverifiable_legacy_recommendations_fail_closed(html):
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.extract_recommendation_sets(html, draw_no=1243)


def test_result_report_contains_every_set_including_non_winners_and_original_link():
    from scripts import lotto_results as results

    rows = results.extract_recommendation_sets(results.canonical_recommendation_html(1243, candidates()), draw_no=1243)
    source = {"post_id": 77, "title": "제1243회 추천", "created_at": "2026-09-25T09:00:00", "url": "https://bit-man.net/dashboard/community/post/77"}
    report = results.build_result_report(verified_draw(), rows, source)
    assert report["summary"]["total_sets"] == 3
    assert report["summary"]["winning_sets"] == 2
    assert report["summary"]["non_winning_sets"] == 1
    assert len(report["rows"]) == 3
    assert "미당첨" in report["content"]
    assert "2등" in report["content"] and "5등" in report["content"]
    assert "post/77" in report["content"]
    assert "35" in report["content"] and "1243" in report["title"]


def test_empty_recommendations_are_unverifiable_not_all_losing():
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.build_result_report(verified_draw(), [], {"post_id": 77})


def test_original_post_timestamp_is_utc_and_must_precede_broadcast():
    from scripts import lotto_results as results

    assert results.recommendation_created_before_draw("2026-09-26 11:34:59", 1243)
    assert not results.recommendation_created_before_draw("2026-09-26 11:35:00", 1243)
    assert not results.recommendation_created_before_draw("2026-09-26T20:36:00+09:00", 1243)
    assert not results.recommendation_created_before_draw("", 1243)


def test_late_original_post_cannot_be_claimed_as_prior_recommendation():
    from scripts import lotto_results as results

    source = {"post_id": 77, "created_at": "2026-09-26 11:40:00"}
    rows = [{"style": "안정형", "set_index": 1, "numbers": [9, 18, 24, 38, 43, 44]}]
    with pytest.raises(results.LottoResultError):
        results.build_result_report(verified_draw(), rows, source)


def test_legacy_report_discloses_current_post_recovery_without_pre_draw_snapshot():
    from scripts import lotto_results as results

    source = {"post_id": 77, "created_at": "2026-09-25 08:01:09.432104", "recovery_kind": "legacy_html"}
    rows = [{"style": "안정형", "set_index": 1, "numbers": [1, 2, 3, 4, 5, 6]}]
    report = results.build_result_report(verified_draw(), rows, source)
    assert "현재 본문" in report["content"]
    assert "고정 스냅샷" in report["content"]
    assert "실제 구매" in report["content"]


def test_real_1243_published_legacy_layout_recovers_all_twelve_sets():
    from scripts import lotto_results as results

    sets = {
        "안정형": [[11, 12, 15, 20, 37, 41], [3, 4, 19, 20, 26, 31], [6, 15, 23, 28, 31, 40], [4, 16, 20, 27, 35, 45]],
        "균형형": [[10, 12, 22, 33, 37, 45], [14, 21, 26, 29, 31, 34], [10, 11, 21, 27, 31, 39], [3, 23, 31, 35, 41, 45]],
        "실험형": [[3, 12, 26, 27, 43, 45], [17, 21, 31, 36, 37, 45], [13, 17, 21, 40, 42, 43], [9, 10, 13, 16, 17, 18]],
    }
    html = "<h2>최근 당첨 결과 요약</h2><strong>2, 4, 10, 16, 31, 41</strong><h2>제1243회 후보 조합</h2>"
    for style, numbers in sets.items():
        html += f"<h3>{style} - 설명</h3><ul>"
        for index, row in enumerate(numbers, 1):
            html += f"<li>세트 {index}: <strong>{', '.join(map(str, row))}</strong> / 점수: 85.0</li>"
        html += "</ul>"
    html += "<h2>마무리 안내</h2>"
    recovered = results.extract_recommendation_sets(html, draw_no=1243)
    assert len(recovered) == 12
    assert [row["numbers"] for row in recovered] == [row for numbers in sets.values() for row in numbers]
    report = results.build_result_report(verified_draw(), recovered, {"post_id": 245, "created_at": "2026-09-25 08:01:09.432104"})
    assert report["summary"]["non_winning_sets"] == 12
    assert report["summary"]["winning_sets"] == 0
    assert max(row["match_count"] for row in report["rows"]) == 2


@pytest.mark.parametrize("change", [
    {"tm2WnNo": 9}, {"bnsWnNo": 44}, {"ltRflYmd": "20260919"},
    {"ltRflYmd": "2026-09-26"}, {"tm1WnNo": True}, {"rnk1WnAmt": -1},
])
def test_official_fetch_never_accepts_corrupt_winning_data(change):
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.fetch_official_draw(1243, now=AFTER_DRAW, session=session_for([official_item(**change)]))


def test_official_duplicate_exact_draw_cannot_choose_a_convenient_result():
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.fetch_official_draw(1243, now=AFTER_DRAW, session=session_for([official_item(), official_item()]))


@pytest.mark.parametrize("payload", [None, {}, {"data": {}}, {"data": {"list": "unavailable"}}])
def test_official_unavailable_or_invalid_response_has_clear_domain_error(payload):
    from scripts import lotto_results as results

    session = session_for([])
    session.get.return_value.json.return_value = payload
    with pytest.raises(results.LottoResultError):
        results.fetch_official_draw(1243, now=AFTER_DRAW, session=session)


@pytest.mark.parametrize("change", [
    {"source": "lottolyzer"}, {"source_url": "https://unofficial.invalid/result"},
    {"source_url": ""}, {"fetched_at": ""}, {"fetched_at": "not-a-time"},
])
def test_report_requires_official_verification_provenance(change):
    from scripts import lotto_results as results

    rows = [{"style": "안정형", "set_index": 1, "numbers": [1, 2, 3, 4, 5, 6]}]
    source = {"post_id": 77, "created_at": "2026-09-25 08:00:00"}
    with pytest.raises(results.LottoResultError):
        results.build_result_report(dict(verified_draw(), **change), rows, source)


def test_partial_legacy_last_set_must_not_disappear_from_report():
    from scripts import lotto_results as results

    html = "<h2>제1243회 후보 조합</h2><h3>안정형</h3><li>세트 1: <strong>1,2,3,4,5,6</strong></li><li>세트 2: <strong>7,8,9,10,11</strong></li>"
    with pytest.raises(results.LottoResultError):
        results.extract_recommendation_sets(html, draw_no=1243)


def test_official_validation_reused_by_pending_report_without_recommendations():
    from scripts import lotto_results as results

    assert results.validate_official_draw(verified_draw(), expected_draw_no=1243, now=AFTER_DRAW) == verified_draw()
    with pytest.raises(results.LottoResultError):
        results.validate_official_draw(draw(), expected_draw_no=1243, now=AFTER_DRAW)


@pytest.mark.parametrize("change", [
    {"source_url": "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do?srchLtEpsd=1242"},
    {"fetched_at": "2026-09-26T20:00:00+09:00"},
    {"fetched_at": "2026-09-27T00:00:00"},
    {"fetched_at": "2026-09-28T00:00:00+00:00"},
])
def test_official_validation_rejects_wrong_round_or_invalid_verification_time(change):
    from scripts import lotto_results as results

    with pytest.raises(results.LottoResultError):
        results.validate_official_draw(dict(verified_draw(), **change), expected_draw_no=1243, now=AFTER_DRAW)


@pytest.mark.parametrize("last_set", [
    "<li>세트 2: <span>7,8,9,10,11,12</span></li>",
    "<li><span>7,8,9,10,11,12</span></li>",
    "<li>세트 2: 7;8;9;10;11;12</li>",
])
def test_mixed_unparsed_last_set_never_becomes_a_partial_success_report(last_set):
    from scripts import lotto_results as results

    html = "<h2>제1243회 후보 조합</h2><h3>안정형</h3><li>세트 1: <strong>1,2,3,4,5,6</strong></li>" + last_set
    with pytest.raises(results.LottoResultError):
        results.extract_recommendation_sets(html, draw_no=1243)


def test_nested_paragraph_does_not_mistake_the_same_set_for_an_unparsed_extra_set():
    from scripts import lotto_results as results

    html = "<h2>제1243회 후보 조합</h2><h3>안정형</h3><li><p>세트 1: <strong>1,2,3,4,5,6</strong></p></li>"
    assert results.extract_recommendation_sets(html, draw_no=1243) == [{"style": "안정형", "set_index": 1, "numbers": [1, 2, 3, 4, 5, 6]}]
