"""DART 재무 스냅샷 수집 — 백테스트용 시점 정확 데이터.

왜 회계연도가 아니라 공시일로 잘라야 하는가
--------------------------------------------
삼성전자 FY2025 사업보고서는 **2026-03-10** 에 접수됐다. 회계연도만 보고
FY2025 숫자를 2026년 1월 백테스트에 넣으면 그 시점에 존재하지도 않던 데이터를
쓰는 것이다. 응답의 `rcept_no` 앞 8자리가 접수일자이므로 이를 함께 저장하고,
소비 측(`disclosures`/`financials` 신호)이 `접수일 <= 기준일` 로 잘라 쓴다.

`fnlttMultiAcnt.json` 은 corp_code 를 한 번에 여러 개 받는다. 종목당 1회로
호출하면 2,444종목 x 3개년 = 7,332회지만, 50개씩 묶으면 약 150회로 끝난다.

사용:
  python scripts/collect_dart_financials.py                    # 최근 3개년
  python scripts/collect_dart_financials.py --years 2024 2025
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

OUT_DIR = os.path.join(BASE_DIR, 'data', 'dart_financials')
CORP_CODES = os.path.join(BASE_DIR, 'data', 'dart_corp_codes.json')
UNIVERSE = os.path.join(BASE_DIR, 'data', 'goodrich_universe_tickers.json')
API = 'https://opendart.fss.or.kr/api/fnlttMultiAcnt.json'

BATCH = 50            # 실측으로 안전하게 통과하는 크기
ANNUAL_REPORT = '11011'
RETRY = 3
SLEEP = 0.15

# 백테스트에서 쓸 계정만 남긴다. 전체를 저장하면 종목당 30행씩 불어난다.
WANTED_ACCOUNTS = {
    '자산총계', '부채총계', '자본총계',
    '매출액', '영업이익', '당기순이익', '당기순이익(손실)',
}


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
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f'DART 호출 실패: {last}')


def _amount(text: str) -> float | None:
    cleaned = str(text or '').replace(',', '').strip()
    if not cleaned or cleaned == '-':
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_year(key: str, corp_codes: list[str], year: str) -> list[dict]:
    """한 개년 재무. 종목별 1행으로 접어서 반환한다."""
    folded: dict[str, dict] = {}

    for start in range(0, len(corp_codes), BATCH):
        chunk = corp_codes[start:start + BATCH]
        payload = _call(key, corp_code=','.join(chunk),
                        bsns_year=year, reprt_code=ANNUAL_REPORT)
        status = payload.get('status')
        if status == '013':           # 해당 배치에 자료 없음
            time.sleep(SLEEP)
            continue
        if status != '000':
            raise RuntimeError(f'{year} status={status} {payload.get("message")}')

        for item in payload.get('list') or []:
            account = str(item.get('account_nm') or '').strip()
            if account not in WANTED_ACCOUNTS:
                continue
            ticker = str(item.get('stock_code') or '').strip()
            if len(ticker) != 6:
                continue
            rcept_no = str(item.get('rcept_no') or '')
            row = folded.setdefault(ticker, {
                'stock_code': ticker,
                'bsns_year': year,
                # rcept_no 앞 8자리가 접수일자 — 시점 게이팅의 근거
                'rcept_dt': rcept_no[:8],
                'accounts': {},
            })
            value = _amount(item.get('thstrm_amount'))
            if value is not None:
                # 연결(CFS)이 먼저 오면 그것을 쓰고, 없으면 개별(OFS)로 채운다
                row['accounts'].setdefault(account, value)
        time.sleep(SLEEP)

    return list(folded.values())


def main() -> int:
    parser = argparse.ArgumentParser(description='DART 재무 스냅샷 수집')
    parser.add_argument('--years', nargs='+', default=['2023', '2024', '2025'])
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    key = _key()
    with open(CORP_CODES, encoding='utf-8') as f:
        corp_map = json.load(f)
    if os.path.isfile(UNIVERSE):
        with open(UNIVERSE, encoding='utf-8') as f:
            tickers = json.load(f)
    else:
        tickers = sorted(corp_map)
    codes = [corp_map[t] for t in tickers if t in corp_map]
    print(f'대상 {len(codes):,}종목 x {len(args.years)}개년 '
          f'-> 약 {(len(codes) // BATCH + 1) * len(args.years)}회 호출')

    os.makedirs(OUT_DIR, exist_ok=True)
    started = time.time()
    for year in args.years:
        path = os.path.join(OUT_DIR, f'{year}.jsonl')
        if os.path.isfile(path) and not args.force:
            print(f'  {year}: 건너뜀 (이미 있음)')
            continue
        rows = fetch_year(key, codes, year)
        tmp = f'{path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        os.replace(tmp, path)
        dates = sorted({r['rcept_dt'] for r in rows if r['rcept_dt']})
        span = f'{dates[0]} ~ {dates[-1]}' if dates else '(접수일 없음)'
        print(f'  {year}: {len(rows):,}종목  접수일 {span}  ({time.time() - started:.0f}s)')

    print(f'완료 -> {OUT_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
