"""Regression guard for the 2026-07-15 scrape-throughput collapse.

Investing.com rate-limits by serving a page whose entire body is the bare status
code ("403"). `_blocked_page_reason` only knew the phrase "403 forbidden", so the
row was classified as an *empty verdict* instead of a block: retryable, so the
loop kept hammering an already-blocked IP and the Cloudflare circuit breaker
never opened. Full cycles fell from 100% complete to 0.2% in a single day.
"""

import pytest

from app.services import manual_stock_analysis as svc


@pytest.mark.parametrize("body", ["403", "429", "503", "  403\n", "\n502\n"])
def test_status_only_body_is_treated_as_block(body):
    assert svc._blocked_page_reason(body) != ""


def test_status_only_block_trips_the_circuit_breaker_classifier():
    """The reason must flow through as a block error, not a generic failure."""
    reason = svc._blocked_page_reason("403")
    error = RuntimeError(f"target page blocked: {reason}")
    assert svc._is_block_error(error) is True


@pytest.mark.parametrize("marker", ["Too many requests", "Rate limit exceeded"])
def test_rate_limit_wording_is_treated_as_block(marker):
    assert svc._blocked_page_reason(f"{marker} - please try again later") != ""


@pytest.mark.parametrize(
    "body",
    [
        "",
        "삼성전자 매출 403억원 기록",
        "적극 매수\n반도체 및 반도체 장비\n목표가 429,000",
    ],
)
def test_normal_pages_are_not_flagged_as_blocked(body):
    """A status code appearing inside real content must not trip the breaker."""
    assert svc._blocked_page_reason(body) == ""


def test_known_block_phrases_still_detected():
    assert svc._blocked_page_reason("Access Denied") != ""
    assert svc._blocked_page_reason("Just a moment...") != ""
    assert svc._blocked_page_reason("Verify you are human") != ""
