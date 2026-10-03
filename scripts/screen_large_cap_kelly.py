#!/usr/bin/env python3
"""Inspect only market-cap-leading quality stocks; no orders or AI calls.

This is a dated current-cohort screen. It never backdates current market caps
into the independent historical Kelly backtest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/services/mirofish'))
sys.path.insert(0, str(ROOT / 'app/utils'))
sys.path.insert(0, str(ROOT / 'scripts'))
from atomic_json import write_json_atomic
from backtest_winrate_kelly import load_price_csv

LISTING_BASE = 'https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx'
DART_API = 'https://opendart.fss.or.kr/api/fnlttMultiAcnt.json'


def load_prices(path, symbols):
    # A newly listed large cap without cached history is held explicitly; its
    # missing bars must not substitute another stock or weaken the backtest.
    return load_price_csv(path, symbols, allow_missing_symbols=True)


def iso_day(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('Dates must use YYYY-MM-DD')
    return value


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a monetary amount')
    result = float(str(value).replace(',', '').strip())
    if not math.isfinite(result):
        raise ValueError('Nonfinite monetary amount')
    return result


def load_listing(path: Path, as_of: str):
    """Load a dated listing. Security classification is an explicit heuristic."""
    iso_day(as_of)
    rows = []
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not {'Code', 'Name', 'Market', 'Marcap', 'Volume'}.issubset(reader.fieldnames or []):
            raise ValueError('Listing requires Code, Name, Market, Marcap, Volume')
        for raw in reader:
            symbol = str(raw['Code']).strip()
            name = str(raw['Name']).strip()
            upper = name.upper()
            if '스팩' in name or re.search(r'\bSPAC\b', upper):
                kind = 'spac'
            elif re.match(r'^(KODEX|TIGER|ACE|SOL|RISE|PLUS|HANARO|KOSEF|KBSTAR|ARIRANG)\s', upper) or 'ETF' in upper or 'ETN' in upper:
                kind = 'fund'
            elif re.search(r'우(?:[BC]|\d+[BC]?)?$', name) or (re.fullmatch(r'\d{6}', symbol) and not symbol.endswith('0')):
                kind = 'preferred'
            elif re.fullmatch(r'\d{6}', symbol) and symbol.endswith('0'):
                kind = 'common'
            else:
                kind = 'unknown'
            rows.append(dict(symbol=symbol, name=name, market=raw['Market'].strip(),
                             market_cap=_number(raw['Marcap']), volume=_number(raw['Volume']),
                             share_type=kind, source='dated_KRX_listing_input', date=as_of))
    return rows, dict(path=str(Path(path).resolve()), sha256=sha256(path), as_of=as_of,
                      rows=len(rows), share_type_method='code_and_name_rule',
                      official_share_type_verified=False)


def normalize_dart(rows, *, period_end: str, fetched_at: str):
    """Keep one receipt and statement scope; prefer CFS, never fill from OFS."""
    iso_day(period_end)
    groups = {}
    fields = {'자본총계': ('equity', 'BS'), '부채총계': ('liabilities', 'BS'),
              '영업이익': ('operating_profit', 'IS'), '영업이익(손실)': ('operating_profit', 'IS'),
              '당기순이익': ('net_income', 'IS'), '당기순이익(손실)': ('net_income', 'IS')}
    for raw in rows:
        receipt = str(raw.get('rcept_no') or '')
        fs = raw.get('fs_div')
        symbol = str(raw.get('stock_code') or '')
        if not re.fullmatch(r'\d{14}', receipt) or fs not in {'CFS', 'OFS'} or raw.get('currency') != 'KRW':
            continue
        account = fields.get(raw.get('account_nm'))
        if not account:
            continue
        field, expected_statement = account
        if raw.get('sj_div') != expected_statement and not (expected_statement == 'IS' and raw.get('sj_div') == 'CIS'):
            continue
        key = (symbol, receipt, fs)
        row = groups.setdefault(key, dict(symbol=symbol, fs_div=fs, rcept_no=receipt,
            available_date=(datetime.strptime(receipt[:8], '%Y%m%d').date() + timedelta(days=1)).isoformat(),
            period_end=period_end, fetched_at=fetched_at, source=DART_API,
            equity=None, liabilities=None, operating_profit=None, net_income=None,
            income_basis='year_to_date', currency='KRW'))
        if expected_statement == 'IS' and not period_end.endswith('12-31'):
            # Half/third-quarter thstrm_amount can represent only three months.
            # Do not call it year-to-date or fill an absent cumulative amount.
            amount = raw.get('thstrm_add_amount')
        else:
            amount = raw.get('thstrm_amount')
        if str(amount or '').strip() in {'', '-'}:
            continue
        value = _number(amount)
        if row[field] is not None and row[field] != value:
            raise ValueError(f'Conflicting DART account: {symbol} {field} {receipt}')
        row[field] = value
    # Choose CFS when present within a receipt; incomplete CFS stays incomplete.
    preferred = {}
    for (symbol, receipt, fs), row in groups.items():
        key = (symbol, receipt)
        if key not in preferred or fs == 'CFS':
            preferred[key] = row
    return sorted(preferred.values(), key=lambda row: (row['symbol'], row['available_date']))


def _get_bytes(url, params=None):
    request = Request(url + ('?' + urlencode(params) if params else ''), headers={'User-Agent': 'MarketFlow-large-cap-research/1.0'})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        raise ValueError(f'Source request failed: HTTP {error.code}') from None
    except (URLError, TimeoutError):
        # A DART request URL contains the secret. Never include it in an error.
        raise ValueError('Source request failed: network/timeout') from None


def fetch_listing(as_of, out):
    iso_day(as_of)
    path = out / 'sources' / f'listing_{as_of}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(_get_bytes(f'{LISTING_BASE}/{as_of}.csv'))
    return path


def fetch_financials(symbols, *, mapping_path, env_file, year, report_code, out):
    from dotenv import dotenv_values
    mapping = json.loads(Path(mapping_path).read_text(encoding='utf-8'))
    corp_codes = [mapping[symbol] for symbol in sorted(symbols) if symbol in mapping]
    key = (dotenv_values(env_file).get('DART_API_KEY') or '').strip()
    if not key:
        raise ValueError('DART_API_KEY is not configured in the selected project')
    fetched_at = datetime.now(timezone.utc).isoformat()
    normalized, calls, capture_times = [], 0, []
    ends = {'11013': '03-31', '11012': '06-30', '11014': '09-30', '11011': '12-31'}
    for offset in range(0, len(corp_codes), 50):
        codes = corp_codes[offset:offset + 50]
        identity = hashlib.sha256(','.join(codes).encode()).hexdigest()[:16]
        cache = out / 'sources' / f'dart_{year}_{report_code}_{identity}.json'
        if cache.exists():
            envelope = json.loads(cache.read_text(encoding='utf-8'))
            cached_at = datetime.fromisoformat(envelope['fetched_at'])
            age = datetime.now(timezone.utc) - cached_at
            fresh = timedelta(0) <= age < timedelta(days=1)
        else:
            fresh = False
        if not fresh:
            payload = json.loads(_get_bytes(DART_API, dict(crtfc_key=key, corp_code=','.join(codes),
                                                        bsns_year=year, reprt_code=report_code)))
            calls += 1
            if payload.get('status') not in {'000', '013'}:
                raise ValueError(f'DART returned status {payload.get("status")}')
            envelope = {'fetched_at': fetched_at, 'source': DART_API, 'payload': payload}
            cache.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(str(cache), envelope)
        capture_times.append(envelope['fetched_at'])
        normalized.extend(normalize_dart(envelope['payload'].get('list') or [],
            period_end=f'{year}-{ends[report_code]}', fetched_at=envelope['fetched_at']))
    normalized = [row for row in normalized if row['symbol'] in symbols]
    path = out / 'sources' / 'financials.json'
    write_json_atomic(str(path), normalized)
    return normalized, dict(source=DART_API, path=str(path.resolve()), sha256=sha256(path),
        calls_this_run=calls, requested_symbols=len(symbols), matched_corp_codes=len(corp_codes),
        financial_symbols=len({row['symbol'] for row in normalized}), year=year, report_code=report_code,
        fetched_at_by_batch=capture_times, currency='KRW', historical_vintage_verified=False)


def _table(rows, fields):
    def cell(value):
        return html.escape('—' if value is None else str(value))
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{cell(f)}</th>' for f in fields) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{cell(row.get(f))}</td>' for f in fields) + '</tr>' for row in rows) + '</tbody></table></div>'


def export_report(report, out):
    json.dumps(report, allow_nan=False)
    out.mkdir(parents=True, exist_ok=True)
    write_json_atomic(str(out / 'report.json'), report)
    rows = report['quality']['results']
    fields = sorted({field for row in rows for field in row})
    with (out / 'universe.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    scope, quality, technical = report['scope'], report['quality'], report['technical']
    page = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>시총 상위 우량주 검사</title><style>body{background:#111820;color:#e7edf2;font:15px/1.7 system-ui;margin:0}main{max-width:1200px;padding:28px 20px;margin:auto}h1{font-size:26px}h2{font-size:19px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #354250;padding:9px;text-align:left}th,a{color:#84c9f0}.note{border-left:3px solid #e2b15e;padding:12px 18px;background:#202730}</style><main>'
    page += f'<h1>시총 상위 {scope["top_n"]} 우량주 검사</h1><p>기준일 {report["as_of"]} · 순위 대상 {scope["ranked_count"]}개 · 재무 기준 통과 {len(quality["passed"])}개 · 당일 가격 후보 {len(technical["candidates"])}개</p>'
    page += '<p>상위 순위를 먼저 고정한 뒤 자본·영업이익·순이익 양수, 부채비율 150% 이하, 공시 후 180일 이내, 기준일 거래량 양수 조건을 적용합니다. 탈락한 자리는 101위 이하로 채우지 않습니다.</p><div class="note">'
    page += ''.join(f'<p>{html.escape(note)}</p>' for note in report['limitations']) + '</div>'
    page += '<h2>당일 가격 후보</h2>' + _table(technical['candidates'], ['symbol', 'name', 'z_score', 'last_daily_return', 'reason'])
    view = [dict(row, status='통과' if row.get('quality_pass') else '제외·보류') for row in rows]
    page += '<h2>시총 순위와 재무 판정</h2>' + _table(view, ['rank', 'symbol', 'name', 'market_cap', 'status', 'reason', 'debt_ratio'])
    page += '<p>검사 근거와 전체 결과: <a href="report.json">report.json</a> · <a href="universe.csv">universe.csv</a></p></main></html>'
    (out / 'report.html').write_text(page, encoding='utf-8')


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prices', required=True, type=Path)
    p.add_argument('--as-of', required=True)
    p.add_argument('--top-n', type=int, default=100)
    p.add_argument('--listing', type=Path)
    p.add_argument('--fetch-listing', action='store_true')
    p.add_argument('--financials', type=Path)
    p.add_argument('--fetch-financials', action='store_true')
    p.add_argument('--corp-codes', type=Path, default=ROOT / 'data/dart_corp_codes.json')
    p.add_argument('--env-file', type=Path, default=ROOT / '.env')
    p.add_argument('--year', type=int, default=2026)
    p.add_argument('--report-code', choices=['11013', '11012', '11014', '11011'], default='11012')
    p.add_argument('--out', type=Path, default=ROOT / 'data/kelly_research/large_cap_latest')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        from large_cap_universe import select_large_caps, evaluate_quality, current_technical
        iso_day(args.as_of)
        if not 1 <= args.top_n <= 100:
            raise ValueError('top-n must be between 1 and 100; full-market price scans are disabled')
        if bool(args.listing) == bool(args.fetch_listing):
            raise ValueError('Choose --listing or --fetch-listing')
        if args.financials and args.fetch_financials:
            raise ValueError('Choose local financials or explicit fetch, not both')
        listing_path = args.listing or fetch_listing(args.as_of, args.out)
        listing, listing_evidence = load_listing(listing_path, args.as_of)
        if args.fetch_listing:
            listing_evidence['source_url'] = f'{LISTING_BASE}/{args.as_of}.csv'
            listing_evidence['provider'] = 'FinanceDataReader KRX-derived dated cache'
        ranked = select_large_caps(listing, as_of=args.as_of, top_n=args.top_n)
        symbols = {row['symbol'] for row in ranked['ranked']}
        if not symbols:
            raise ValueError('No eligible common-stock market-cap rows')
        if args.fetch_financials:
            financials, financial_evidence = fetch_financials(symbols, mapping_path=args.corp_codes,
                env_file=args.env_file, year=args.year, report_code=args.report_code, out=args.out)
        elif args.financials:
            financials = json.loads(args.financials.read_text(encoding='utf-8'))
            financial_evidence = dict(path=str(args.financials.resolve()), sha256=sha256(args.financials))
        else:
            financials, financial_evidence = [], {'status': 'missing'}
        quality = evaluate_quality(ranked['ranked'], financials, as_of=args.as_of)
        # The reader filters before parsing price numbers; all lower-ranked stocks are ignored.
        prices, price_evidence = load_prices(args.prices, symbols)
        technical = current_technical(prices, quality['passed'], as_of=args.as_of)
        report = dict(schema_version=1, as_of=args.as_of,
            scope=dict(type='market_cap_top_quality_current_cohort', top_n=args.top_n,
                       ranked_count=len(ranked['ranked']), lower_ranks_scanned=False),
            ranking=ranked, quality=quality, technical=technical, qualified_60pct_symbols=[],
            historical_validation=dict(status='not_verified',
                reason='historical_market_caps_and_financial_vintages_required'),
            input_evidence=dict(listing=listing_evidence, financials=financial_evidence, prices=price_evidence,
                                generated_at=datetime.now(timezone.utc).isoformat(), live_orders=False),
            limitations=[
                '당일 2σ 하락 후보는 관찰 대상입니다. 승률 60% 검증 완료 종목이나 매수 권고가 아닙니다.',
                '시총 순위는 기준일 스냅샷입니다. 현재 시총·재무를 과거로 소급하지 않으며 과거 검증은 별도 보류합니다.',
                '보통주 분류는 코드·이름 규칙이며 공식 종목 유형 확인을 대체하지 않습니다. 관리종목·상폐 위험 전체를 검증하지 않습니다.',
                'DART 공시 접수일 다음 날부터 공개된 것으로 취급합니다. 수집 시점의 정정 상태와 과거 vintage 일치는 별도 확인이 필요합니다.',
                '부채비율 150% 규칙은 금융업에도 동일하게 적용하는 보수적인 연구 기준입니다. 모든 우량주를 포괄하지 않습니다.',
            ])
        export_report(report, args.out)
        print(json.dumps(dict(status='complete', as_of=args.as_of, ranked=len(symbols),
            quality_passed=len(quality['passed']), price_candidates=technical['candidates'],
            certified_60pct_count=0, report=str((args.out / 'report.html').resolve())), ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
