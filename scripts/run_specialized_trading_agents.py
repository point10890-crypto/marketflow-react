#!/usr/bin/env python3
"""Offline asyncio stock-research actors with a durable, paper-only ledger."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def next_weekday(day):
    cursor = date.fromisoformat(day) + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def latest_capture(values):
    """Preserve actual acquisition clocks; generation/resume time is not a capture."""
    parsed = []
    for value in values:
        if value is None:
            continue
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError('Actual capture must have an explicit timezone')
        parsed.append((moment, value))
    return max(parsed, key=lambda row: row[0])[1] if parsed else None


def demo_request():
    """Manufactured profitable patterns to exercise the full path, never evidence of alpha."""
    from scripts.backtest_winrate_kelly import demo_data
    prices, fundamentals = demo_data()
    days = sorted({row['date'] for row in prices})[:1591]
    as_of = days[-1]
    names = {'DEMO_A': ('000001', '합성 종목 A'), 'DEMO_B': ('000002', '합성 종목 B'),
             'DEMO_C': ('000003', '합성 종목 C'), 'DEMO_INDEX': ('069500', '합성 비교 지수')}
    prices = [dict(row, symbol=names[row['symbol']][0], name=names[row['symbol']][1])
              for row in prices if row['date'] <= as_of]
    fundamentals = [dict(row, symbol=names[row['symbol']][0])
                    for row in fundamentals if row['available_date'] <= as_of]
    universe = [dict(symbol=symbol, name=name, market='KOSPI', market_cap=1e12 - index * 1e9,
                     volume=1e6, share_type='common', source='synthetic_fixture', date=as_of)
                for index, (symbol, name) in enumerate(names.values())]
    capture = as_of + 'T16:00:00+09:00'
    available = (date.fromisoformat(as_of) - timedelta(days=45)).isoformat()
    period = (date.fromisoformat(as_of) - timedelta(days=90)).isoformat()
    current = [dict(symbol=row['symbol'], available_date=available, period_end=period,
                    equity=100., liabilities=50., net_income=10., operating_profit=20., fs_div='CFS',
                    source='synthetic_fixture', fetched_at=capture) for row in universe]
    sources = dict(universe=universe, prices=prices, current_financials=current, fundamentals=fundamentals)
    execution_date = next_weekday(as_of)
    last_prices = {row['symbol']: row['close'] for row in prices if row['date'] == as_of}
    return dict(as_of=as_of, universe=universe, current_financials=current, prices=prices,
                fundamentals=fundamentals, benchmark_symbol='069500', account_id='paper-synthetic-demo',
                evidence=dict(synthetic=True, trusted_fixture=True, price_adjustment_verified=True,
                              financial_vintage_verified=True,
                              source_timestamps={key: capture for key in sources},
                              source_hashes={key: digest(value) for key, value in sources.items()}),
                splits=dict(train_end=days[int(len(days) * .6) - 1],
                            validation_end=days[int(len(days) * .8) - 1], test_end=as_of),
                config={}, portfolio=dict(cash=1e6, positions={}),
                execution=dict(date=execution_date, quotes={symbol: dict(price=price, volume=1e6,
                    date=execution_date, source='synthetic_next_session_assumption')
                    for symbol, price in last_prices.items()}, cost_bps=5., slippage_bps=10., sell_tax_bps=0.))


def acquired_request(history, cohort):
    """Audit acquired files but never promote unverified history into trading evidence."""
    history, cohort = Path(history), Path(cohort)
    ranking_report = read_json(cohort)
    universe = ranking_report['ranking']['ranked']
    current_path = cohort.parent / 'sources/financials.json'
    current = read_json(current_path)
    price_report = read_json(history / 'prices/report.json')
    financial_report = read_json(history / 'financials/collection_report.json')
    price_path = history / 'prices/prices.csv'
    financial_path = history / 'financials/financials.json'
    if file_digest(price_path) != price_report['prices_sha256']:
        raise ValueError('Acquired price file digest differs')
    if file_digest(financial_path) != financial_report['financials_sha256']:
        raise ValueError('Acquired financial file digest differs')
    symbols = {row['symbol'] for row in universe}
    if len(symbols) != len(universe) or not 1 <= len(symbols) <= 100:
        raise ValueError('Acquired cohort must have one to one hundred unique symbols')
    if set(price_report['selected_symbols']) != symbols:
        raise ValueError('Acquired prices belong to a different cohort')
    as_of = ranking_report['as_of']
    price_capture = latest_capture([row.get('captured_at') for row in price_report.get('symbols', [])])
    current_capture = latest_capture([row.get('fetched_at') for row in current])
    financial_capture = latest_capture([row.get('fetched_at') for row in financial_report.get('captures', [])])
    listing = ranking_report.get('input_evidence', {}).get('listing', {})
    universe_capture = latest_capture([listing.get('fetched_at'), listing.get('captured_at')])
    return dict(as_of=as_of, universe=universe, current_financials=current, prices=[], fundamentals=[],
                evidence=dict(synthetic=False, price_adjustment_verified=False, financial_vintage_verified=False,
                    source_timestamps=dict(universe=universe_capture, prices=price_capture,
                                           current_financials=current_capture,
                                           fundamentals=financial_capture),
                    source_hashes=dict(universe=file_digest(cohort), prices=price_report['prices_sha256'],
                                       current_financials=file_digest(current_path),
                                       fundamentals=financial_report['financials_sha256'])),
                acquisition=dict(price_rows_available=price_report['total_rows'],
                    financial_rows_available=financial_report['records'],
                    history_directory=str(history.resolve()), cohort_file=str(cohort.resolve()),
                    historical_rows_withheld=True,
                    reason='Corporate-action adjustment and first-filing numerical vintages are unverified'),
                splits=dict(train_end='2019-12-31', validation_end='2023-12-31', test_end=as_of),
                config={}, account_id='paper-acquired-audit', portfolio=dict(cash=1e6, positions={}),
                execution=dict(date=next_weekday(as_of), quotes={}, cost_bps=5., slippage_bps=10., sell_tax_bps=0.))


def export_report(report, out):
    from app.utils.atomic_json import write_json_atomic
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json_atomic(str(out / 'report.json'), report)
    def cell(value):
        return html.escape(str(value))
    stage_rows = ''.join(f'<tr><td>{cell(row["stage"])}</td><td>{cell(row["message_id"])}</td></tr>'
                         for row in report['stages'])
    target_rows = ''.join(f'<tr><td>{cell(row["name"])} ({cell(row["symbol"])})</td>'
        f'<td>{row["validation"]["samples"]}</td><td>{row["validation"]["win_rate"]:.1%}</td>'
        f'<td>{row["validation"]["win_lower"]:.1%}</td></tr>' for row in report['quant']['qualified'])
    reasons = report['data'].get('reasons', []) + report['quant'].get('reasons', []) + report['risk'].get('reasons', [])
    label = '합성 데이터 · 동작 검증' if report['synthetic'] else '실제 자료 · 검증 상태 점검'
    content = f'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>특화 에이전트 실행 보고서</title>
<style>body{{font:15px/1.7 system-ui;color:#e8eef3;background:#111820;margin:0}}main{{max-width:1100px;margin:auto;padding:28px 20px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #354250;padding:9px;text-align:left}}
td{{overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<main><p>{label}</p><h1>특화 에이전트 → CIO → 가상 체결</h1>
<p>실행 {cell(report['run_id'])} · 상태 {cell(report['status'])} · 가상 체결 {len(report['execution']['fills'])}건</p>
<p>현재 TOP100 코호트의 연구 실행입니다. 실주문은 전송하지 않으며 미래 승률·수익을 보장하지 않습니다.
20%는 종목 비중 상한입니다. 합성 검증 결과는 실제 투자 성과가 아닙니다.</p>
<h2>판정 근거</h2><pre>{cell(json.dumps(reasons, ensure_ascii=False, indent=2))}</pre>
<p>CIO: {cell(report['approval']['decision'])} · {cell(report['approval'].get('reason', ''))}</p>
<h2>학습·검증 통과 종목</h2><div class="scroll"><table><tr><th>종목</th><th>검증 표본</th><th>관측 승률</th><th>Wilson 하한</th></tr>{target_rows}</table></div>
<h2>비중 및 가상 체결</h2><pre>{cell(json.dumps(dict(targets=report['risk']['targets'], execution=report['execution']), ensure_ascii=False, indent=2))}</pre>
<h2>메시지 연결 및 복구 기록</h2><div class="scroll"><table><tr><th>단계</th><th>SHA-256 메시지 ID</th></tr>{stage_rows}</table></div></main></html>'''
    temporary = out / 'report.html.tmp'
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(out / 'report.html')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true', help='Manufactured fixture; no empirical performance claim')
    mode.add_argument('--request', type=Path, help='Explicit message input JSON; no key fields permitted')
    mode.add_argument('--acquired-data', type=Path, help='Acquired price/financial audit directory; remains unverified')
    parser.add_argument('--cohort', type=Path, default=ROOT / 'data/kelly_research/large_cap_20261001_v2/report.json')
    parser.add_argument('--database', type=Path, default=ROOT / 'data/kelly_research/trading_agents/agents.sqlite')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/kelly_research/trading_agents/latest')
    parser.add_argument('--run-id', required=True, help='Same ID resumes identical input; different input is rejected')
    args = parser.parse_args(argv)
    try:
        from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator
        from app.services.mirofish.trading_agents.models import create_message
        request = demo_request() if args.demo else (read_json(args.request) if args.request
                                                    else acquired_request(args.acquired_data, args.cohort))
        create_message(args.run_id, 'request', {'input': request})  # Reject credentials before creating a database.
        report = asyncio.run(TradingOrchestrator(args.database).run(request, run_id=args.run_id))
        export_report(report, args.out)
        print(json.dumps(dict(run_id=args.run_id, status=report['status'], mode='paper', synthetic=report['synthetic'],
            ranked=len(report['data']['ranked']), quality=len(report['data']['eligible_symbols']),
            candidates=len(report['quant']['candidates']), fills=len(report['execution']['fills']),
            report=str((args.out / 'report.json').resolve())), ensure_ascii=True))
        return 0
    except Exception as error:
        # External input and exception messages may contain credentials; print only the error class.
        print(json.dumps(dict(status='error', error_type=type(error).__name__, mode='paper')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
