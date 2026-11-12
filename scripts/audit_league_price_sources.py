# -*- coding: utf-8 -*-
"""예측 리그 가격 출처 점검 (읽기 전용).

  --csv              data/daily_prices.csv 에서 장 마감(15:40) 전에 수집된 당일 행의 월별 수
  --session DATE     league.db 에서 같은 종목·같은 날의 krx_regular 봉과 provider_daily 봉이 다른 수

두 번째 점검은 provider_daily 가 정규장 값과 얼마나 다른지 알려 준다. 채점은 krx_regular 만 쓴다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

PRE_CLOSE_BEFORE = '15:40'
FIELDS = ('open', 'high', 'low', 'close')


def preclose_share(csv_path: str) -> dict[str, dict[str, int]]:
    months: dict[str, dict[str, int]] = defaultdict(lambda: {'rows': 0, 'pre_close': 0})
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            day, stamp = (row.get('date') or '').strip(), (row.get('update_time') or '').strip()
            if len(day) != 10:
                continue
            bucket = months[day[:7]]
            bucket['rows'] += 1
            if stamp[:10] == day and stamp[11:16] < PRE_CLOSE_BEFORE:
                bucket['pre_close'] += 1
    return {month: dict(months[month]) for month in sorted(months)}


def compare_bases(conn, session: str) -> dict:
    from app.services.forecast_league import bars
    rows = conn.execute(
        'SELECT r.open AS ro, r.high AS rh, r.low AS rl, r.close AS rc, '
        'u.open AS uo, u.high AS uh, u.low AS ul, u.close AS uc FROM bars r '
        'JOIN bars u ON u.stock_code = r.stock_code AND u.session_date = r.session_date '
        'WHERE r.basis = ? AND u.basis = ? AND r.session_date = ?',
        (bars.BASIS_REGULAR, bars.BASIS_UNIVERSE, session)).fetchall()
    mismatch = {field: 0 for field in FIELDS}
    for row in rows:
        for field in FIELDS:
            if row['r' + field[0]] != row['u' + field[0]]:
                mismatch[field] += 1
    return {'session': session, 'compared': len(rows), 'mismatch': mismatch}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', action='store_true')
    parser.add_argument('--session')
    options = parser.parse_args(argv)
    report: dict = {}
    if options.csv:
        report['daily_prices_preclose'] = preclose_share(os.path.join(BASE_DIR, 'data', 'daily_prices.csv'))
    if options.session:
        from app.services.forecast_league import db
        with db.connect() as conn:
            report['bases'] = compare_bases(conn, options.session)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
