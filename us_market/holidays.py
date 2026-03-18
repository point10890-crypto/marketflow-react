#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market - 휴일 및 거래일 유틸리티

update_all.py와 scheduler.py에서 공용으로 사용.
"""

from datetime import datetime, timedelta

# 미국 시장 휴일 (2025-2026)
US_MARKET_HOLIDAYS = [
    # 2025
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # MLK Day
    "2025-02-17",  # Presidents Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving
    "2025-12-25",  # Christmas
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
]


def get_last_trading_day(reference_date=None):
    """
    마지막 거래일 계산 (주말 및 미국 휴일 고려)

    Args:
        reference_date: 기준 날짜 (None이면 오늘)

    Returns:
        str: 마지막 거래일 (YYYY-MM-DD)
    """
    if reference_date is None:
        reference_date = datetime.now()

    # 현재 시간이 미국 장 마감 전이면 전일 기준
    # 미국 동부 시간 16:00 = 한국 시간 06:00 (썸머타임 시 05:00)
    # 안전하게 한국 시간 07:00 이전이면 전일 기준
    if reference_date.hour < 7:
        reference_date = reference_date - timedelta(days=1)

    check_date = reference_date.date()

    # 주말이거나 휴일이면 이전 거래일로
    while True:
        weekday = check_date.weekday()  # 0=월, 6=일

        # 주말 체크 (토=5, 일=6)
        if weekday >= 5:
            check_date -= timedelta(days=1)
            continue

        # 휴일 체크
        if check_date.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS:
            check_date -= timedelta(days=1)
            continue

        # 평일이고 휴일 아니면 거래일
        break

    return check_date.strftime("%Y-%m-%d")
