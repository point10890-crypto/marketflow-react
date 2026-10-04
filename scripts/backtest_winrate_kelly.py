#!/usr/bin/env python3
"""Offline win-rate / Kelly research; no broker, credentials or network calls."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _day(value: str) -> str:
    value = str(value).strip()
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError(f'Invalid ISO date: {value}')
    return value


def _number(value: str, label: str, *, positive=False) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "nonnegative"}')
    return number


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_price_csv(path: Path, symbols: set[str] | None = None, *,
                   allow_missing_symbols: bool = False) -> tuple[list[dict], dict]:
    path = Path(path)
    prices, bases, sources, read = [], set(), set(), 0
    capture_after = False
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if not fields.intersection({'symbol', 'ticker', 'code'}) or 'date' not in fields:
            raise ValueError('Prices require symbol/ticker/code and date columns')
        if not fields.intersection({'close', 'current_price'}):
            raise ValueError('Prices require close or current_price; opens are never inferred')
        for row in reader:
            read += 1
            symbol = str(row.get('symbol') or row.get('ticker') or row.get('code') or '').strip()
            if not symbol:
                raise ValueError(f'Empty symbol at CSV row {read + 1}')
            if symbols is not None and symbol not in symbols:
                continue
            day = _day(row['date'])
            item = {'symbol': symbol, 'name': str(row.get('name') or symbol).strip(),
                    'date': day, 'close': _number(row.get('close') or row.get('current_price'), 'close', positive=True)}
            if str(row.get('open') or '').strip():
                item['open'] = _number(row['open'], 'open', positive=True)
            if str(row.get('volume') or '').strip():
                item['volume'] = _number(row['volume'], 'volume')
            prices.append(item)
            if row.get('price_basis'):
                bases.add(row['price_basis'])
            if row.get('source_id'):
                sources.add(row['source_id'])
            if row.get('update_time'):
                captured = datetime.fromisoformat(row['update_time'].replace('Z', '+00:00'))
                capture_after |= captured.date().isoformat() > day
    if not prices and not allow_missing_symbols:
        raise ValueError('No selected price rows')
    missing = sorted((symbols or set()) - {row['symbol'] for row in prices})
    if missing and not allow_missing_symbols:
        raise ValueError('Requested symbols are absent from the input CSV')
    return prices, {'path': str(path.resolve()), 'sha256': _hash(path), 'rows_read': read,
                    'rows_selected': len(prices), 'price_basis': sorted(bases), 'source_ids': sorted(sources),
                    'has_actual_open': all('open' in row for row in prices),
                    'has_volume': all('volume' in row for row in prices),
                    'captured_after_price_date': capture_after,
                    'historical_vintage_verified': False, 'historical_universe_verified': False,
                    'missing_symbols': missing}


def load_fundamental_csv(path: Path, symbols: set[str] | None = None) -> list[dict]:
    rows = []
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'symbol', 'available_date', 'market_cap', 'debt_ratio', 'tradable'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Fundamentals require symbol, available_date, market_cap, debt_ratio, tradable')
        for row in reader:
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
                raise ValueError('Fundamental required fields cannot be missing or empty')
            symbol = row['symbol'].strip()
            if not symbol:
                raise ValueError('Empty fundamental symbol')
            if symbols is not None and symbol not in symbols:
                continue
            flag = row['tradable'].strip().lower()
            if flag not in {'true', 'false', '1', '0'}:
                raise ValueError('tradable must be true/false or 1/0')
            rows.append({'symbol': symbol, 'available_date': _day(row['available_date']),
                         'market_cap': _number(row['market_cap'], 'market_cap'),
                         'debt_ratio': _number(row['debt_ratio'], 'debt_ratio'),
                         'tradable': flag in {'true', '1'}})
    return rows


def load_market_volatility_csv(path: Path) -> tuple[list[dict], dict]:
    """Read supplied availability dates, without claiming they are independently verified."""
    path = Path(path)
    rows, dates, sources = [], set(), set()
    required = {'available_date', 'vix_index', 'source_id'}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('VIX requires available_date, vix_index, source_id columns')
        for row in reader:
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
                raise ValueError('VIX required evidence cannot be missing or empty')
            day = _day(row['available_date'])
            if day in dates:
                raise ValueError('Duplicate VIX available_date is ambiguous')
            dates.add(day)
            source = row['source_id'].strip()
            sources.add(source)
            rows.append({'available_date': day, 'vix_index': _number(row['vix_index'], 'vix_index'),
                         'source_id': source})
    if not rows:
        raise ValueError('VIX CSV must contain at least one observation')
    return sorted(rows, key=lambda row: row['available_date']), {
        'path': str(path.resolve()), 'sha256': _hash(path), 'rows': len(rows),
        'source_ids': sorted(sources), 'availability_verified': False,
        'date_semantics': 'available_date is supplied by the caller; execution uses previous-session cutoff'}


def demo_data() -> tuple[list[dict], list[dict]]:
    """Manufactured mean-reversion and weak controls, not an empirical market result."""
    rng = random.Random(601020)
    days, cursor = [], date(2018, 1, 2)
    while len(days) < 1600:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    prices, fundamentals = [], []
    for stock, symbol in enumerate(('DEMO_A', 'DEMO_B', 'DEMO_C', 'DEMO_INDEX')):
        close = 100.0
        for index, day in enumerate(days):
            previous = close
            phase, cycle = (index + stock * 3) % 10, (index + stock * 3) // 10
            ret = rng.uniform(-0.004, 0.004)
            if symbol != 'DEMO_INDEX':
                if phase == 0:
                    ret = -0.06
                elif phase in (2, 3):
                    ret = 0.03 if cycle % 5 else -0.014
                elif symbol == 'DEMO_C' and phase == 5:
                    ret = -0.045
            else:
                ret += 0.00015
            close *= 1 + ret
            prices.append({'symbol': symbol, 'name': symbol, 'date': day,
                           'open': previous * (1 + ret / 3), 'close': close, 'volume': 1_000_000.0})
            if index % 60 == 0:
                fundamentals.append({'symbol': symbol, 'available_date': day,
                                     'market_cap': 1e12, 'debt_ratio': 50., 'tradable': True})
    return prices, fundamentals


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                             if isinstance(value, (dict, list)) else value for key, value in row.items()})


def _table(rows: list[dict], fields: list[str]) -> str:
    def cell(value):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return html.escape(str(value if value is not None else '—'))
    return ('<div class="table-scroll"><table><thead><tr>' + ''.join(f'<th>{cell(key)}</th>' for key in fields)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{cell(row.get(key))}</td>' for key in fields)
                                            + '</tr>' for row in rows) + '</tbody></table></div>')


def _percent(value):
    return f'{100 * value:.2f}%' if isinstance(value, (int, float)) else '—'


def _qualification_view(report):
    reasons = {'qualified': '조건 통과', 'missing_fundamental': '시점별 재무 자료 없음',
               'stale_fundamental': '재무 자료 만료', 'not_tradable': '거래 불가',
               'market_cap_filter': '시가총액 미달', 'debt_ratio_filter': '부채비율 초과',
               'insufficient_samples': '거래 표본 부족', 'insufficient_payoff_evidence': '손익비 근거 부족',
               'low_win_rate': '승률 미달', 'low_payoff': '손익비 미달',
               'nonpositive_net_expectancy': '기대 순수익 미달', 'low_wilson_lower_bound': '신뢰하한 미달',
               'validation_price_gap_or_insufficient_lookback': '검증 가격/기간 부족', 'benchmark_only': '비교 기준 종목'}
    rows = []
    for item in report['qualification']:
        reason = str(item.get('reason', ''))
        phase = '학습: ' if reason.startswith('train_') else '검증: ' if reason.startswith('validation_') else ''
        key = reason.split('_', 1)[1] if phase and reason not in reasons else reason
        train, validation = item['train'], item['validation']
        row = {'종목': f'{item.get("name", item["symbol"])} ({item["symbol"]})',
                     '판정': '선택' if item['symbol'] in report['selected_symbols'] else '조건 통과' if item['eligible'] else '보류',
                     '사유': phase + reasons.get(key, key), '학습 표본': train['samples'],
                     '학습 승률': _percent(train['win_rate']), '검증 표본': validation['samples'],
                     '검증 승률': _percent(validation['win_rate']), '검증 신뢰하한': _percent(validation['win_lower']),
                     '검증 손익비': f'{validation["payoff"]:.2f}' if validation['payoff'] is not None else '—',
                     '초기 비중 상한': _percent(item['target_weight'])}
        if item.get('test'):
            row.update({'최종 표본': item['test']['samples'], '최종 승률': _percent(item['test']['win_rate'])})
        rows.append(row)
    return rows


def _kelly_calculation_rows(report: dict) -> list[dict]:
    rows = []
    for item in report['qualification']:
        calculation = item.get('kelly_calculation', {})
        two_point = calculation.get('two_point', {})
        rows.append({'symbol': item['symbol'], 'name': item.get('name', item['symbol']),
                     'eligible': item['eligible'], 'reason': item['reason'],
                     'selected': item['symbol'] in report['selected_symbols'],
                     'model': calculation.get('model'),
                     **{key: two_point.get(key) for key in (
                         'p', 'gain_fraction', 'loss_fraction', 'sample_count', 'wins', 'losses', 'zeros')},
                     'two_point_fraction': two_point.get('raw_fraction'),
                     **{key: calculation.get(key) for key in (
                         'empirical_fraction', 'raw_fraction', 'kelly_fraction', 'fractional_fraction',
                         'capped_fraction', 'stock_volatility_guard', 'vix_index', 'vix_status',
                         'vix_available_date', 'vix_source_id')},
                     'target_weight': item['target_weight'], 'approval_status': 'research_only'})
    return rows


def _kelly_calculation_view(rows: list[dict]) -> list[dict]:
    return [{'종목': f'{row["name"]} ({row["symbol"]})', '모델': row['model'],
             '검증 p': _percent(row['p']), '평균 순이익 b': _percent(row['gain_fraction']),
             '평균 순손실 a': _percent(row['loss_fraction']), '순손익 0 표본': row['zeros'],
             '일반화 원값': _percent(row['two_point_fraction']),
             '실측 분포 원값': _percent(row['empirical_fraction']),
             '적용 원값': _percent(row['raw_fraction']), '적용 배율': row['kelly_fraction'],
             '보정 후': _percent(row['fractional_fraction']), '20% 상한 후': _percent(row['capped_fraction']),
             'VIX': row['vix_index'] if row['vix_index'] is not None else '미입력',
             'VIX 이용가능일': row['vix_available_date'], 'VIX 출처': row['vix_source_id'],
             '자격 판정': '통과' if row['eligible'] else '보류',
             '연구 비중': _percent(row['target_weight'])} for row in rows]


def export_report(report: dict, out: Path) -> None:
    sys.path.insert(0, str(ROOT / 'app/utils'))
    from atomic_json import write_json_atomic
    # Validate finite JSON before producing any success artifact.
    json.dumps(report, allow_nan=False)
    out.mkdir(parents=True, exist_ok=True)
    write_json_atomic(str(out / 'report.json'), report)
    portfolio = report['portfolio']
    curve, fills, qualification = portfolio['equity_curve'], portfolio['fills'], report['qualification']
    _write_csv(out / 'equity_curve.csv', curve, ['date', 'equity', 'cash', 'exposure', 'weights'])
    _write_csv(out / 'fills.csv', fills, ['date', 'symbol', 'side', 'quantity', 'price', 'cost', 'reason', 'signal_date'])
    q_fields = sorted({key for row in qualification for key in row})
    _write_csv(out / 'qualification.csv', qualification, q_fields or ['symbol'])
    calculations = _kelly_calculation_rows(report)
    calculation_fields = list(calculations[0]) if calculations else ['symbol', 'model', 'target_weight']
    _write_csv(out / 'kelly_calculations.csv', calculations, calculation_fields)
    calculation_view = _kelly_calculation_view(calculations)
    demo = report['input_evidence']['kind'] == 'synthetic_demo'
    label = '합성 데이터 · 실행 검증용' if demo else '실제 입력 CSV · 과거 자료 연구'
    warnings = report['input_evidence']['limitations']
    metrics = portfolio['metrics']
    summary = (f'총 순수익률 {_percent(metrics["total_return"])} · 최대 낙폭 {_percent(metrics["max_drawdown"])}'
               f' · 가상 체결 {metrics["fill_count"]}건 · 누적 비용 {metrics["total_cost"]:.6f} (시작 자산 1.0)')
    cfg = report['config']
    assumptions = (f'체결 기준: {cfg["execution_price"]} (신호 다음 시장일) · 보유기간: {cfg["horizon"]}시장일'
                   f' · 수수료: {cfg["cost_bps"]}bp/편도 · 슬리피지: {cfg["slippage_bps"]}bp/편도'
                   f' · 매도세: {cfg["sell_tax_bps"]}bp · 일일 재조정: {"사용" if cfg["rebalance"] else "미사용"}')
    gates = (f'기간별 최소 {cfg["min_samples"]}표본 · 관측 승률 {_percent(cfg["min_win_rate"])} 이상'
             f' · 손익비 {cfg["min_payoff"]} 이상 · 신뢰하한 {_percent(cfg["min_win_lower"])} 이상'
             f' · 켈리 모델 {cfg.get("kelly_model", "empirical")} · 기본 배율 {cfg["kelly_fraction"]} · 종목/전체 비중 상한 '
             f'{_percent(cfg["max_weight"])}/{_percent(cfg["max_exposure"])}')
    view = _qualification_view(report)
    comparison = (f'벤치마크 {report["benchmark"]["symbol"]}: 총 순수익률 '
                  f'{_percent(report["benchmark"]["metrics"]["total_return"])}') if report.get('benchmark') else '벤치마크 미지정'
    evaluation = report.get('evaluation')
    errors = (f'고정기간 검출 평가: 적중 {evaluation["true_positive"]} · 오검출 {evaluation["false_positive"]}'
              f' · 미검출 {evaluation["false_negative"]} · 올바른 제외 {evaluation["true_negative"]}'
              ' (입력 종목의 완료된 신호 기회만 평가하며, 재조정 포트폴리오의 체결 승률과 다릅니다.)') if evaluation else ''
    page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>승률·켈리 백테스트</title><style>
body{{margin:0;background:#111820;color:#e7edf2;font:15px/1.7 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:32px 20px}}
h1{{font-size:28px}}h2{{font-size:20px;margin-top:30px}}.label{{color:#64d9c6}}.note{{border-left:3px solid #e2b15e;padding:12px 20px;background:#202730}}
.table-scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #354250;vertical-align:top}}
th{{color:#84c9f0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#84c9f0}}
</style><main><p class="label">{label}</p><h1>승률 60% · 비중 20% 가설 검증</h1>
<p>학습 → 검증 → 최종 포트폴리오 테스트. 20%는 종목 비중 상한이며 미래 승률이나 파산 방지를 보장하지 않습니다.</p>
<p>{html.escape(assumptions)}</p>
<p>{html.escape(gates)}</p>
<div class="note">{''.join(f'<p>{html.escape(note)}</p>' for note in warnings)}</div>
<h2>검증 조건과 선택 종목</h2><pre>{html.escape(json.dumps(report['splits'], ensure_ascii=False, indent=2))}</pre>
<p>선택: {html.escape(', '.join(report['selected_symbols']) or '조건 충족 종목 없음')}</p>
{_table(view, list(view[0]) if view else ['종목', '판정', '사유'])}<h2>최종 테스트 성과</h2><p>{html.escape(summary)}</p><p>{html.escape(comparison)}</p><p>{html.escape(errors)}</p>
<h2>켈리 계산 과정</h2>
<p>일반화 모델: f* = p/a − (1−p)/b. a와 b는 비용 차감 후 실제 검증 표본의 평균 손실·이익률입니다.
p는 순손익 0 표본을 제외한 조건부 승률이며, 손익비 b/a와 b는 서로 다른 값입니다.
두 평균으로 압축한 근사값과 실제 순수익률 분포의 로그성장 최적값을 함께 표시합니다.</p>
<p>일반 상태는 설정 배율(기본 하프 0.5), VIX ≥ 30은 최대 쿼터 0.25를 먼저 적용한 뒤 20% 상한을 적용합니다.
큰 원값에서는 쿼터여도 20% 상한에 도달할 수 있습니다. 종목 변동성 가드는 상한 적용 후 별도로 비중을 줄입니다.
미입력 VIX는 정상 시장으로 입증된 값이 아니며, 설정 배율을 사용하는 정책 기본값입니다.
통계·재무 자격이 보류된 종목의 계산은 진단이며 연구 비중은 0%입니다.</p>
{_table(calculation_view, list(calculation_view[0]) if calculation_view else ['종목', '연구 비중'])}
<p>데이터 프레임용 계산 원장은 <a href="kelly_calculations.csv">kelly_calculations.csv</a>에서 내려받을 수 있습니다.</p>
<p>전체 숫자와 가정은 <a href="report.json">report.json</a>, 일별 자산은 <a href="equity_curve.csv">equity_curve.csv</a>, 체결은 <a href="fills.csv">fills.csv</a>에서 확인하세요.</p>
<h2>가상 체결 내역 (최근 30건)</h2>{_table(fills[-30:], ['date', 'symbol', 'side', 'quantity', 'price', 'cost', 'reason'])}
<p>실제 주문 없음. <a href="https://www.stat.berkeley.edu/~aldous/Real_World/kelly.html">Kelly의 수익분포·로그성장 정의</a> ·
<a href="https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf">반복 백테스트와 과적합 연구</a></p></main></html>'''
    (out / 'report.html').write_text(page, encoding='utf-8')


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--prices', type=Path)
    source.add_argument('--demo', action='store_true')
    p.add_argument('--fundamentals', type=Path)
    p.add_argument('--symbols', help='Comma-separated exact codes, with leading zeros retained')
    p.add_argument('--benchmark')
    p.add_argument('--train-end')
    p.add_argument('--validation-end')
    p.add_argument('--test-end')
    p.add_argument('--out', type=Path, default=ROOT / 'data/kelly_research/latest')
    p.add_argument('--execution-price', choices=['open', 'close'], default='close')
    p.add_argument('--lookback', type=int, default=60)
    p.add_argument('--horizon', type=int, default=5)
    p.add_argument('--min-samples', type=int, default=30)
    p.add_argument('--min-win-lower', type=float, default=.60)
    p.add_argument('--cost-bps', type=float, default=5.)
    p.add_argument('--slippage-bps', type=float, default=10.)
    p.add_argument('--sell-tax-bps', type=float, default=0.)
    p.add_argument('--kelly-model', choices=['empirical', 'generalized'], default='empirical',
                   help='Empirical log growth or generalized two-point net-return approximation')
    p.add_argument('--vix-csv', type=Path, help='Dated available_date,vix_index,source_id observations')
    p.add_argument('--kelly-fraction', type=float, default=.5)
    p.add_argument('--rebalance', action='store_true', help='Experimental constant-weight daily rebalancing')
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        symbols = {item.strip() for item in args.symbols.split(',') if item.strip()} if args.symbols else None
        if args.demo:
            if args.fundamentals or args.symbols:
                raise ValueError('--demo cannot be mixed with external fundamentals/symbols')
            prices, fundamentals = demo_data()
            evidence = {'kind': 'synthetic_demo', 'seed': 601020,
                        'historical_vintage_verified': False, 'historical_universe_verified': False}
            benchmark = args.benchmark or 'DEMO_INDEX'
        else:
            prices, evidence = load_price_csv(args.prices, symbols)
            fundamentals = load_fundamental_csv(args.fundamentals, symbols) if args.fundamentals else []
            evidence['kind'] = 'csv_research'
            if args.fundamentals:
                evidence['fundamentals_path'] = str(args.fundamentals.resolve())
                evidence['fundamentals_sha256'] = _hash(args.fundamentals)
            benchmark = args.benchmark
        market_volatility = None
        if args.vix_csv:
            market_volatility, evidence['market_volatility'] = load_market_volatility_csv(args.vix_csv)
        else:
            evidence['market_volatility'] = {'status': 'missing', 'availability_verified': False}
        days = sorted({row['date'] for row in prices})
        if len(days) < 20:
            raise ValueError('At least 20 distinct market sessions are required')
        train_end = args.train_end or days[int(len(days) * .6) - 1]
        validation_end = args.validation_end or days[int(len(days) * .8) - 1]
        test_end = args.test_end or days[-1]
        config = {key: getattr(args, key) for key in (
            'execution_price', 'lookback', 'horizon', 'min_samples', 'min_win_lower', 'cost_bps',
            'slippage_bps', 'sell_tax_bps', 'kelly_fraction', 'kelly_model', 'rebalance')}
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / 'app/services/mirofish'))
        from kelly_research import run_research
        report = run_research(prices, fundamentals, train_end=train_end, validation_end=validation_end,
                              test_end=test_end, benchmark_symbol=benchmark, config=config,
                              market_volatility=market_volatility)
        evidence.update({'live_orders': False, 'generated_at': datetime.now(timezone.utc).isoformat(),
                         'limitations': [
            '합성 데이터는 실행 검증용입니다. 실제 종목의 검출력·승률을 입증하지 않습니다.' if args.demo else
            '입력 종목 범위의 연구입니다. 과거 상장 구성·상폐 손실·조정주가 vintage를 검증하지 않아 생존편향 제거를 주장하지 않습니다.',
            '2σ 하락은 시험할 평균회귀 가설이며, 저평가나 반등 확률 60%를 자동으로 의미하지 않습니다.',
            '검증 후 선택을 동결합니다. 최종 테스트 수익으로 종목이나 파라미터를 다시 고르지 않습니다.',
            'Wilson 하한은 독립 이항 표본 가정의 보조 지표입니다. 상관·시장 변화·다중검정 문제를 해결하거나 미래 승률을 보장하지 않습니다.',
            '기본 켈리는 실측 순수익률의 로그성장 최적화입니다. generalized는 비용 차감 검증 표본의 평균 이익·손실로 압축한 두 점 근사입니다. 20% 상한은 파산 방지 보장이 아닙니다.',
            '수수료·슬리피지·매도세율은 입력 가정입니다. 기본 매도세 0은 현행 한국 세율을 뜻하지 않습니다.',
        ]})
        evidence['limitations'].append('VIX 이용가능일은 CSV 제공자의 주장입니다. 실제 체결에는 이전 시장일에 이용 가능했던 값만 쓰지만 과거 시점 자료의 진위를 독립 검증하지 않습니다.' if market_volatility else
                                      'VIX 자료 미입력: 시장 고위험 여부를 판단할 수 없어 설정 켈리 배율을 적용합니다.')
        if args.rebalance:
            evidence['limitations'].append('일일 비중 재조정은 고정 보유기간 표본과 다른 손익을 만듭니다. 최종 포트폴리오 성과를 별도로 평가하세요.')
        if not fundamentals:
            evidence['limitations'].append('시점별 재무자료가 없어 재무 안전성 판정을 보류합니다. 통과 종목을 임의로 만들지 않습니다.')
        if not args.demo and not evidence['has_volume']:
            evidence['limitations'].append('일부 또는 전체 거래량 자료가 없어 거래정지·체결 가능성을 완전히 확인할 수 없습니다.')
        report['input_evidence'] = evidence
        export_report(report, args.out)
        print(json.dumps({'status': 'complete', 'input_kind': evidence['kind'],
                          'selected_symbols': report['selected_symbols'],
                          'report': str((args.out / 'report.html').resolve()),
                          'metrics': report['portfolio']['metrics']}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
