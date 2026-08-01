"""DART 공시 아카이브 수집 — 백테스트용 시점 정확 데이터.

왜 필요한가
-----------
검출 점수에 공시/호재를 넣으려면 **그 시점에 알 수 있었던 공시만** 봐야 한다.
`engine/dart_collector.py` 는 종목코드로 최근 공시를 조회하는 라이브 경로라
과거 세션 재현에 쓸 수 없다. 여기서는 날짜 구간으로 전 종목 공시를 긁어
월별 JSONL 로 적재하고, 소비 측이 `rcept_dt <= 기준일` 로 잘라 쓴다.

규모 (실측): 코스피+코스닥 월 약 11,000건, 31개월 약 34만건, API 약 3,500회.
DART 일일 한도 20,000회 안에서 하루면 끝난다.

사용:
  python scripts/collect_dart_disclosures.py                # 2024-01 ~ 현재
  python scripts/collect_dart_disclosures.py --from 202601  # 특정 월부터
  python scripts/collect_dart_disclosures.py --force        # 기존 월도 다시
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

OUT_DIR = os.path.join(BASE_DIR, 'data', 'dart_disclosures')
API = 'https://opendart.fss.or.kr/api/list.json'
PAGE_COUNT = 100
MARKETS = ('Y', 'K')          # 코스피 / 코스닥. 나머지(코넥스·기타)는 유니버스 밖이다.
RETRY = 3
SLEEP_BETWEEN_CALLS = 0.12    # DART 를 두드리지 않도록 여유를 둔다


def _key() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, '.env'))
    except ImportError:
        pass
    key = (os.getenv('DART_API_KEY') or '').strip()
    if not key:
        raise SystemExit('DART_API_KEY 가 없습니다 (.env 확인)')
    return key


def _call(key: str, **params) -> dict:
    params['crtfc_key'] = key
    url = f'{API}?{urllib.parse.urlencode(params)}'
    last = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f'DART 호출 실패: {last}')


def _months(start: str, end: str) -> list[str]:
    out = []
    year, month = int(start[:4]), int(start[4:6])
    while f'{year}{month:02d}' <= end:
        out.append(f'{year}{month:02d}')
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def fetch_month(key: str, month: str) -> list[dict]:
    """한 달치 공시. 상장 종목코드가 있는 행만 남긴다."""
    begin = f'{month}01'
    finish = f'{month}{calendar.monthrange(int(month[:4]), int(month[4:6]))[1]:02d}'
    rows: list[dict] = []

    for market in MARKETS:
        page = 1
        while True:
            payload = _call(key, bgn_de=begin, end_de=finish, corp_cls=market,
                            page_no=page, page_count=PAGE_COUNT)
            status = payload.get('status')
            if status == '013':       # 조회 결과 없음
                break
            if status != '000':
                raise RuntimeError(f'{month}/{market} status={status} {payload.get("message")}')

            for item in payload.get('list') or []:
                code = str(item.get('stock_code') or '').strip()
                if not code or code == ' ':
                    continue          # 비상장(채권 발행사 등)
                rows.append({
                    'rcept_dt': str(item.get('rcept_dt') or ''),
                    'stock_code': code.zfill(6),
                    'corp_name': item.get('corp_name') or '',
                    'report_nm': item.get('report_nm') or '',
                    'corp_cls': market,
                    'rcept_no': item.get('rcept_no') or '',
                    'flr_nm': item.get('flr_nm') or '',
                })

            total_page = int(payload.get('total_page') or 1)
            if page >= total_page:
                break
            page += 1
            time.sleep(SLEEP_BETWEEN_CALLS)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description='DART 공시 아카이브 수집')
    parser.add_argument('--from', dest='start', default='202401', help='시작 월 YYYYMM')
    parser.add_argument('--to', dest='end', default=time.strftime('%Y%m'), help='종료 월 YYYYMM')
    parser.add_argument('--force', action='store_true', help='이미 받은 월도 다시 받기')
    args = parser.parse_args()

    key = _key()
    os.makedirs(OUT_DIR, exist_ok=True)
    months = _months(args.start, args.end)
    print(f'대상 {len(months)}개월: {months[0]} ~ {months[-1]}')

    total = 0
    started = time.time()
    for month in months:
        path = os.path.join(OUT_DIR, f'{month}.jsonl')
        if os.path.isfile(path) and not args.force:
            with open(path, encoding='utf-8') as f:
                existing = sum(1 for line in f if line.strip())
            total += existing
            print(f'  {month}: 건너뜀 (이미 {existing:,}건)')
            continue

        rows = fetch_month(key, month)
        tmp = f'{path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        os.replace(tmp, path)
        total += len(rows)
        print(f'  {month}: {len(rows):,}건  (누적 {total:,}, {time.time() - started:.0f}s)')

    print(f'완료: {total:,}건 -> {OUT_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
