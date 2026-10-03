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


def render_stock_catalogue(report, attribution):
    """Show supplied stock identities without promoting preliminary quality to alpha."""
    def cell(value):
        return html.escape(str(value))
    data, quant = report.get('data', {}), report.get('quant', {})
    ranked, quality = data.get('ranked', []), data.get('quality', {})
    results = {}
    for row in quality.get('results', []):
        results.setdefault(row['symbol'], []).append(row)
    eligible = set(data.get('eligible_symbols', []))
    groups = dict(passed=[], held=[], pending=[])
    for row in ranked:
        matches = results.get(row['symbol'], [])
        evidence = matches[0] if len(matches) == 1 else {}
        if any(evidence.get(key) != row.get(key) for key in ('symbol', 'name', 'market')):
            evidence = {}
        group = ('passed' if evidence.get('quality_pass') is True and row['symbol'] in eligible else
                 'held' if evidence.get('quality_pass') is False else 'pending')
        groups[group].append((row, evidence))
    checked = data.get('status') == 'ready' and quant.get('qualification_complete') is True
    candidates = {row['symbol'] for row in quant.get('candidates', [])} if checked else set()
    qualified = {row['symbol'] for row in quant.get('qualified', [])} if checked else set()
    approved = {row['symbol']: row['final_weight'] for row in attribution['rows']
                if attribution['status'] == 'ready'}
    title = '합성 검증 종목' if report['synthetic'] else '실제 조사 종목'
    as_of = quality.get('as_of') or quant.get('as_of') or (ranked[0].get('date') if ranked else '자료 없음')
    content = [f'<section id="stocks" class="stock-catalogue"><h2>{title}</h2>',
        f'<p>보고서 기준 {cell(as_of)} · 입력 시총 상위 {len(ranked)}종목 · '
        f'재무 1차 통과 {len(groups["passed"])}종목 · 재무 1차 보류 {len(groups["held"])}종목 · '
        f'CIO 승인 목표 {sum(weight > 0 for weight in approved.values())}종목</p>']
    if not checked:
        content.append('<p class="stock-state"><strong>승률·켈리 검사 대기</strong> — 가격 이력·재무 최초 공시·출처 검증이 '
                       '완료되지 않아 최종 통계 검사를 진행하지 않았습니다. 아래는 입력 종목과 1차 재무 판정입니다. '
                       '현재 매수 추천 목록이 아닙니다.</p>')
    elif report['synthetic']:
        content.append('<p class="stock-state">동작 검증용 합성 종목입니다. 실제 종목 검출이나 투자 성과를 뜻하지 않습니다.</p>')
    else:
        content.append(f'<p class="stock-state">현재 진입 신호 {len(candidates)}종목. 통계 통과 여부와 CIO 승인 목표를 함께 확인하세요.</p>')
    labels = dict(quality_passed='재무 1차 통과', high_debt_ratio='부채비율 기준 초과',
        nonpositive_net_income='순이익 0 이하', nonpositive_operating_profit='영업이익 0 이하',
        missing_financial_net_income='순이익 자료 누락')
    for group, heading in [('passed', '재무 1차 통과'), ('held', '재무 1차 보류'), ('pending', '재무 자료 확인 대기')]:
        rows = groups[group]
        if not rows:
            continue
        content.append(f'<h3>{heading} {len(rows)}종목</h3>' if group == 'passed' else
                       f'<details><summary>{heading} {len(rows)}종목과 사유</summary>')
        content.append('<div class="scroll stock-table"><table><thead><tr><th>입력 시총 순위</th><th>종목명 · 코드</th>'
                       '<th>시장</th><th>1차 재무 판정</th><th>승률 검사</th><th>켈리 배정</th></tr></thead><tbody>')
        for row, evidence in rows:
            symbol = row['symbol']
            financial = ('재무 1차 통과' if group == 'passed' else '자료 확인 대기' if group == 'pending'
                         else labels.get(evidence.get('reason'), evidence.get('reason', '재무 보류')))
            statistical = ('재무 기준 보류' if group == 'held' else '승률 검사 대기' if not checked else
                           '현재 진입 신호' if symbol in candidates else
                           '통계 통과 · 현재 진입 신호 없음' if symbol in qualified else '통계 미통과 / 미확정')
            allocation = (f'승인 목표 {approved[symbol]:.2%}' if symbol in approved else
                          '미계산' if not checked else '추가 체결 없음' if attribution['status'] == 'duplicate_day' else '미승인')
            content.append(f'<tr><td>{cell(row.get("rank", "—"))}</td><td><strong>{cell(row["name"])}</strong>'
                           f'<small class="stock-code">{cell(symbol)}</small></td><td>{cell(row["market"])}</td>'
                           f'<td>{cell(financial)}</td><td>{cell(statistical)}</td><td>{cell(allocation)}</td></tr>')
        content.append('</tbody></table></div>')
        if group != 'passed':
            content.append('</details>')
    if not ranked:
        content.append('<p>이 실행에는 입력된 종목 목록이 없습니다.</p>')
    content.append('</section>')
    return ''.join(content)


def export_report(report, out, *, preserve_source=False):
    from app.utils.atomic_json import write_json_atomic
    from app.services.mirofish.trading_agents.kelly_attribution import build_kelly_attribution, render_kelly_section
    attribution = build_kelly_attribution(report)  # Validate before creating/exporting files.
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if not preserve_source:
        write_json_atomic(str(out / 'report.json'), report)
    write_json_atomic(str(out / 'kelly_attribution.json'), attribution)
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
<style>body{{font:15px/1.7 system-ui;color:#e8eef3;background:#111820;margin:0}}main{{max-width:1100px;margin:auto;padding:28px 20px;overflow-wrap:anywhere}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #354250;padding:9px;text-align:left}}
td{{overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
.kelly{{border:1px solid #354250;border-radius:12px;padding:20px;margin:24px 0;background:#17222c}}
.formula{{font-size:20px;color:#91d9dd}}.muted{{color:#a8b8c7;font-size:13px}}
.kelly-state{{border-left:3px solid #f3bf77;background:#202a34;padding:14px 18px;margin:18px 0}}
.kelly-stock{{border-top:1px solid #354250;padding-top:12px;margin-top:20px}}
.kelly-flow{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:18px 0}}
.kelly-flow>div{{border:1px solid #40515f;border-radius:8px;padding:12px;min-width:0}}
.kelly-flow small,.kelly-flow span{{display:block;color:#a8b8c7;font-size:12px}}
.kelly-flow b{{display:block;font-size:25px;margin:6px 0}}.kelly-flow .kelly-final{{border-color:#64c6bd;background:#203934}}
.stock-catalogue{{border:1px solid #40515f;border-radius:12px;padding:20px;margin:24px 0;background:#17222c}}
.stock-state{{border-left:3px solid #f3bf77;background:#202a34;padding:12px 16px}}
.stock-table{{max-height:520px;overflow:auto}}.stock-table th{{position:sticky;top:0;background:#20303d;z-index:1}}
.stock-table table{{min-width:700px}}.stock-code{{display:block;color:#a8b8c7;font-size:12px}}
details{{margin:18px 0}}summary{{cursor:pointer;color:#a8b8c7}}
@media(max-width:760px){{.kelly-flow{{grid-template-columns:repeat(2,minmax(0,1fr))}}main{{padding:18px 12px}}.kelly{{padding:14px}}}}
</style>
<main><p>{label}</p><h1>특화 에이전트 → CIO → 가상 체결</h1>
<p>실행 {cell(report['run_id'])} · 상태 {cell(report['status'])} · 가상 체결 {len(report['execution']['fills'])}건</p>
<p>현재 TOP100 코호트의 연구 실행입니다. 실주문은 전송하지 않으며 미래 승률·수익을 보장하지 않습니다.
20%는 종목 비중 상한입니다. 합성 검증 결과는 실제 투자 성과가 아닙니다.</p>
{render_stock_catalogue(report, attribution)}
{render_kelly_section(attribution)}
<h2>판정 근거</h2><pre>{cell(json.dumps(reasons, ensure_ascii=False, indent=2))}</pre>
<p>CIO: {cell(report['approval']['decision'])} · {cell(report['approval'].get('reason', ''))}</p>
<h2>학습·검증 통과 종목</h2><div class="scroll"><table><tr><th>종목</th><th>검증 표본</th><th>관측 승률</th><th>Wilson 하한</th></tr>{target_rows}</table></div>
<details><summary>비중 및 가상 체결 원문</summary><pre>{cell(json.dumps(dict(targets=report['risk']['targets'], execution=report['execution']), ensure_ascii=False, indent=2))}</pre></details>
<details><summary>메시지 연결 및 복구 기록</summary><div class="scroll"><table><tr><th>단계</th><th>SHA-256 메시지 ID</th></tr>{stage_rows}</table></div></details></main></html>'''
    temporary = out / 'report.html.tmp'
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(out / 'report.html')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true', help='Manufactured fixture; no empirical performance claim')
    mode.add_argument('--request', type=Path, help='Explicit message input JSON; no key fields permitted')
    mode.add_argument('--acquired-data', type=Path, help='Acquired price/financial audit directory; remains unverified')
    mode.add_argument('--render-report', type=Path, help='Re-export a stored report; no actors, acquisition, or ledger access')
    parser.add_argument('--cohort', type=Path, default=ROOT / 'data/kelly_research/large_cap_20261001_v2/report.json')
    parser.add_argument('--database', type=Path, default=ROOT / 'data/kelly_research/trading_agents/agents.sqlite')
    parser.add_argument('--out', type=Path, default=ROOT / 'data/kelly_research/trading_agents/latest')
    parser.add_argument('--run-id', help='Required for execution; same ID resumes identical input')
    args = parser.parse_args(argv)
    if not args.render_report and not args.run_id:
        parser.error('--run-id is required for execution')
    try:
        if args.render_report:
            source = args.render_report.resolve()
            if source in {(args.out / filename).resolve()
                          for filename in ('kelly_attribution.json', 'report.html', 'report.html.tmp')}:
                raise ValueError('Stored report collides with an output path')
            report = read_json(args.render_report)
            if args.run_id and args.run_id != report['run_id']:
                raise ValueError('Stored report run ID differs')
            export_report(report, args.out,
                          preserve_source=(args.out / 'report.json').resolve() == args.render_report.resolve())
            print(json.dumps(dict(run_id=report['run_id'], status=report['status'], mode='report-view',
                                  new_execution=False, report=str((args.out / 'report.html').resolve()))))
            return 0
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
