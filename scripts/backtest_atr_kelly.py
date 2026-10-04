#!/usr/bin/env python3
"""Reproducible OHLCV barrier backtest and Matplotlib charts; no live orders."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / 'app/services/mirofish'
if str(ENGINE_PATH) not in sys.path:
    sys.path.insert(0, str(ENGINE_PATH))


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _code(value: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', value):
        raise ValueError('Symbol must be a nonempty safe identifier')
    return value


def load_ohlcv_csv(path: Path, symbols: set[str] | None = None) -> tuple[list[dict], dict]:
    """Keep real OHLCV; never derive a high/low/open from a closing price."""
    from atr_trade_plan import validate_ohlcv
    path = Path(path)
    rows, read, capture_after, bases, sources = [], 0, False, set(), set()
    symbol_bases = {}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if not {'date', 'open', 'high', 'low', 'volume'}.issubset(fields):
            raise ValueError('OHLCV requires date, open, high, low and volume')
        if not fields.intersection({'code', 'ticker', 'symbol'}) or not fields.intersection({'close', 'current_price'}):
            raise ValueError('OHLCV requires symbol/ticker/code and close/current_price')
        for raw in reader:
            read += 1
            identifiers = {raw[key].strip() for key in ('code', 'ticker', 'symbol') if raw.get(key)}
            if len(identifiers) > 1:
                raise ValueError(f'Conflicting symbol identifier aliases at CSV row {read + 1}')
            code = _code(raw.get('code') or raw.get('ticker') or raw.get('symbol') or '')
            if symbols is not None and code not in symbols:
                continue
            row = {'code': code, 'name': str(raw.get('name') or code), 'date': raw['date']}
            for key in ('open', 'high', 'low', 'volume'):
                row[key] = float(raw[key])
            row['close'] = float(raw.get('close') or raw.get('current_price'))
            rows.append(row)
            if raw.get('update_time'):
                capture = datetime.fromisoformat(raw['update_time'].replace('Z', '+00:00'))
                local_capture = capture.astimezone(ZoneInfo('Asia/Seoul')) if capture.tzinfo else capture
                if local_capture.date().isoformat() == raw['date'] and local_capture.time() < time(15, 30):
                    raise ValueError(f'Apparent intraday capture at CSV row {read + 1}; completed daily OHLCV required')
                if local_capture.date().isoformat() < raw['date']:
                    raise ValueError(f'Capture precedes price date at CSV row {read + 1}')
                capture_after |= local_capture.date().isoformat() > raw['date']
            if raw.get('price_basis'):
                basis = raw['price_basis'].strip()
                symbol_bases.setdefault(code, set()).add(basis)
                if len(symbol_bases[code]) > 1:
                    raise ValueError(f'Mixed price basis for symbol {code}')
                bases.add(basis)
            if raw.get('source_id'):
                sources.add(raw['source_id'])
    if not rows:
        raise ValueError('No selected OHLCV rows')
    missing = (symbols or set()) - {row['code'] for row in rows}
    if missing:
        raise ValueError('Requested symbols missing from OHLCV: ' + ', '.join(sorted(missing)))
    rows = validate_ohlcv(rows)
    return rows, {'kind': 'provided_price_csv', 'path': str(path.resolve()), 'sha256': _hash(path),
                  'rows_read': read, 'rows_selected': len(rows),
                  'price_basis': sorted(bases), 'source_ids': sorted(sources),
                  'captured_after_price_date': capture_after,
                  'capture_timezone_verified': False,
                  'historical_vintage_verified': False, 'historical_universe_verified': False,
                  'point_in_time_fundamentals': False, 'live_orders': False,
                  'date_from': min(row['date'] for row in rows),
                  'date_through': max(row['date'] for row in rows)}


def _csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                             if isinstance(value, (list, dict)) else value for key, value in row.items()})


def _plot_api():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = {font.name for font in font_manager.fontManager.ttflist}
    plt.rcParams.update({'font.family': 'Malgun Gothic' if 'Malgun Gothic' in fonts else 'DejaVu Sans',
                         'font.size': 11, 'axes.unicode_minus': False, 'axes.spines.top': False,
                         'axes.spines.right': False, 'figure.facecolor': 'white',
                         'axes.labelcolor': '#20252b', 'text.color': '#20252b',
                         'axes.edgecolor': '#a9afb7', 'savefig.facecolor': 'white'})
    return plt


def _days(rows):
    return [date.fromisoformat(row['date']) for row in rows]


def _boundaries(axis, settings):
    for key, label in (('train_end', '학습 종료'), ('validation_end', '검증 종료')):
        axis.axvline(date.fromisoformat(settings[key]), linestyle=':', color='#69717c', linewidth=1,
                     label=label)


def _finish(figure, path, plt):
    figure.savefig(path, dpi=145, bbox_inches='tight')
    plt.close(figure)


def render_charts(report: dict, out: Path) -> list[str]:
    plt = _plot_api()
    import matplotlib.dates as mdates
    files = []
    colors = ('#225fa8', '#703e93', '#276b64', '#a76517')
    for item in report['symbols']:
        bars, trades = item['bars'], item['trades']
        dates = _days(bars)
        fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.8), constrained_layout=True)
        fig.suptitle(f"{item['name']} ({item['code']}) · ATR/-2σ 가격 연구", fontsize=18, ha='left', x=.06)
        ax = axes[0]
        ax.set_title(f"실제 일봉 {bars[0]['date']} ~ {bars[-1]['date']} · 14세션 단순 ATR / 20세션 표본 표준편차", loc='left', fontsize=11)
        ax.plot(dates, [row['close'] for row in bars], color=colors[0], label='종가')
        ax.plot(dates, [row.get('lower_band') for row in bars], color='#69717c', linestyle='--', label='-2σ 하단 밴드')
        signals = [row for row in bars if row.get('signal')]
        ax.scatter(_days(signals), [row['close'] for row in signals], marker='v', facecolors='none',
                   edgecolors=colors[1], s=36, label='종가 신호', zorder=4)
        _boundaries(ax, report['settings'])
        ax.set_ylabel('가격 (원)')
        ax.grid(axis='y', alpha=.17)
        ax.legend(loc='upper left', ncol=3, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

        filled = [trade for trade in trades if trade.get('entry_date')]
        trade = filled[-1] if filled else None
        start, end = max(0, len(bars) - 80), len(bars)
        if trade:
            ix = next(i for i, bar in enumerate(bars) if bar['date'] == trade['signal_date'])
            exit_ix = next((i for i, bar in enumerate(bars) if bar['date'] == trade.get('exit_date')), len(bars) - 1)
            start, end = max(0, ix - 12), min(len(bars), exit_ix + 12)
        focus = bars[start:end]
        ax = axes[1]
        ax.plot(_days(focus), [row['close'] for row in focus], color=colors[0], label='종가')
        ax.vlines(_days(focus), [row['low'] for row in focus], [row['high'] for row in focus],
                  color='#8a949f', alpha=.55, label='실제 고가·저가')
        if trade:
            end_day = date.fromisoformat(trade.get('exit_date') or bars[-1]['date'])
            start_day = date.fromisoformat(trade['signal_date'])
            for key, label, color, style in (('stop_price', '계획 손절가', colors[1], '--'),
                                           ('target_price', '계획 목표가', colors[2], ':'),
                                           ('entry_price', '실제 진입가', '#434b55', '-.')):
                ax.hlines(trade[key], start_day, end_day, colors=color, linestyles=style, label=label)
            ax.scatter([date.fromisoformat(trade['entry_date'])], [trade['entry_price']], marker='^',
                       s=85, color=colors[0], zorder=5, label='진입 체결')
            if trade.get('exit_date'):
                ax.scatter([end_day], [trade['exit_price']], marker='X', s=85, color=colors[1], label='청산 체결', zorder=5)
            reason = {'target': '목표', 'stop': '손절', 'stop_gap': '갭 손절',
                      'target_gap': '갭 목표', 'time_exit': '보유기간 만료'}.get(trade.get('exit_reason'), trade.get('exit_reason') or '열린 포지션')
            ax.set_title(f"최근 체결 상세 · 신호 {trade['signal_date']} / {reason} · 순수익 {_pct(trade.get('net_return'))}", loc='left')
        else:
            ax.set_title('최근 가격 · 체결 거래 없음', loc='left')
        ax.set_ylabel('가격 (원)')
        ax.grid(axis='y', alpha=.17)
        ax.legend(loc='upper left', ncol=3, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        filename = f"price_{_code(item['code'])}.png"
        _finish(fig, out / filename, plt)
        files.append(filename)

    fig, axes = plt.subplots(2, 1, figsize=(13.5, 9), constrained_layout=True)
    fig.suptitle('가격 전략 관찰과 켈리 배분을 분리해서 보기', fontsize=18, ha='left', x=.06)
    for index, item in enumerate(report['symbols']):
        curve, bars, color = item['price_study_equity'], item['bars'], colors[index % len(colors)]
        if curve:
            axes[0].plot(_days(curve), [row['equity'] for row in curve], color=color, label=f"{item['name']} 전략")
        axes[0].plot(_days(bars), [row['close'] / bars[0]['close'] for row in bars], color=color,
                     linestyle='--', alpha=.55, label=f"{item['name']} 가격 보유")
        kcurve = item.get('kelly_test_equity', [])
        if kcurve:
            axes[1].plot(_days(kcurve), [row['equity'] for row in kcurve], color=color,
                         label=f"{item['name']} · 비중 {_pct(item['research_weight'])}")
    axes[0].set_title('종목별 전 기간 단위자본 가격 연구 · 비용 차감 / 배분 포트폴리오 아님', loc='left', fontsize=11)
    axes[1].set_title('최종 평가 기간 켈리 모의계좌 · 검증 종료 때 비중 고정 / 보류 종목은 현금 유지', loc='left', fontsize=11)
    for ax in axes:
        ax.axhline(1, color='#747b84', linewidth=.8)
        ax.set_ylabel('자산 지수 (시작=1)')
        ax.grid(axis='y', alpha=.17)
        ax.legend(loc='upper left', ncol=3, fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    _boundaries(axes[0], report['settings'])
    _finish(fig, out / 'equity.png', plt)
    files.append('equity.png')

    fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
    names, wins, losses, zeros = [], [], [], []
    for item in report['symbols']:
        metric = item['phase_metrics']['test']
        names.append(f"{item['name']}\n({item['code']})")
        wins.append(metric['wins']); losses.append(metric['losses']); zeros.append(metric['zeros'])
    positions = list(range(len(names)))
    ax.bar(positions, wins, color='#225fa8', label='순수익 양수', edgecolor='#20252b', linewidth=.5)
    ax.bar(positions, losses, bottom=wins, color='#e4dcec', hatch='//', label='순수익 음수', edgecolor='#703e93', linewidth=.5)
    ax.bar(positions, zeros, bottom=[a+b for a,b in zip(wins, losses)], color='#c7cdd4', label='순수익 0')
    for ix, item in enumerate(report['symbols']):
        metric = item['phase_metrics']['test']
        ax.text(ix, wins[ix]+losses[ix]+zeros[ix]+.2, win_caption(metric), ha='center', fontsize=11)
    ax.set_xticks(positions, names)
    ax.set_ylim(0, max([a+b+c for a,b,c in zip(wins,losses,zeros)], default=0)+2)
    ax.set_ylabel('완료 거래 수 (회)')
    ax.set_title(f"최종 평가 · 승률의 실제 분모 | {report['periods'].get('test_start')} ~ {report['periods'].get('test_end')}", loc='left', fontsize=16, pad=18)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.legend(loc='upper right', ncol=3, fontsize=10)
    ax.grid(axis='y', alpha=.17)
    _finish(fig, out / 'summary.png', plt)
    files.append('summary.png')
    return files


def _pct(value):
    return f'{value*100:.2f}%' if isinstance(value, (int, float)) else '미산출'


def win_caption(metric):
    return f"n={metric['wins']+metric['losses']} · 0수익={metric['zeros']} · 승률 {_pct(metric['p'])}"


def _escape(value):
    return html.escape(str(value if value is not None else '미산출'))


def render_html(report: dict, files: list[str]) -> str:
    evidence = report['input_evidence']
    reasons = {'train_insufficient_trades': '학습 거래 표본 부족',
               'validation_insufficient_trades': '검증 거래 표본 부족',
               'train_low_win_rate': '학습 승률 미달', 'validation_low_win_rate': '검증 승률 미달',
               'train_low_payoff_ratio': '학습 손익비 미달', 'validation_low_payoff_ratio': '검증 손익비 미달',
               'train_insufficient_payoff_evidence': '학습 이익·손실 표본 미충족',
               'validation_insufficient_payoff_evidence': '검증 이익·손실 표본 미충족',
               'train_nonpositive_net_edge': '학습 평균 순수익 미달',
               'validation_nonpositive_net_edge': '검증 평균 순수익 미달',
               'insufficient_two_point_evidence': '켈리 계산의 이익·손실 근거 부족',
               'nonpositive_generalized_kelly': '켈리 계산값이 0 이하'}
    rows, sections = [], []
    for item in report['symbols']:
        train, val, test = (item['phase_metrics'][key] for key in ('train', 'validation', 'test'))
        calculation = item['kelly_calculation']
        held = calculation.get('held_reasons', [])
        reason = ' / '.join(reasons.get(key, key) for key in held)
        rows.append('<tr>' + ''.join(f'<td>{_escape(value)}</td>' for value in (
            f"{item['name']} ({item['code']})", f"{train['completed_count']}회 / {_pct(train['p'])}",
            f"{val['completed_count']}회 / {_pct(val['p'])}", f"{test['completed_count']}회 / {_pct(test['p'])}",
            _pct(item['research_weight']), '연구 조건 통과' if item['evidence_qualified'] else '보류')) + '</tr>')
        two = calculation.get('two_point', {})
        note = (f"검증 체결 기준 p={_pct(two.get('p'))}, 평균 순이익 b={_pct(two.get('gain_fraction'))}, "
                f"평균 순손실 a={_pct(two.get('loss_fraction'))}. "
                f"f*=p/a−(1−p)/b → {_pct(calculation.get('raw_fraction'))}; "
                f"프랙셔널 적용 {_pct(calculation.get('fractional_fraction'))}; "
                f"상한 적용 {_pct(calculation.get('capped_fraction'))}; 실제 연구 배분 {_pct(item['research_weight'])}.")
        sections.append(f'<section><h2>{_escape(item["name"])} ({_escape(item["code"])})</h2><p>{_escape(note)}</p>'
                        f'<p>{_escape(reason) if reason else "가격 전략의 연구 표본 조건 통과"} · 운영 매수 승인: 보류 (시점별 재무·유니버스 미검증)</p>'
                        f'<img src="price_{_code(item["code"])}.png" alt="{_escape(item["name"])} 진입·손절·목표가 차트"></section>')
    downloads = ' · '.join(f'<a href="{filename}">{_escape(filename)}</a>' for filename in
                           ('report.json', 'trades.csv', 'signals.csv', 'metrics.csv', *files))
    settings = report['settings']
    lineage = evidence.get('lineage_audit', {}).get('declared', {})
    excluded = lineage.get('excluded_dates_at_or_after')
    source_note = (f"입력 감사 기록은 {excluded} 이후 전체 구간을 제외한 정제본이라고 선언합니다. " if excluded else '')
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATR·켈리 실제 가격 백테스트</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#20252b;font:16px/1.65 'Malgun Gothic',system-ui,sans-serif}}
main{{max-width:1320px;margin:0 auto;padding:32px 24px 64px}}h1{{font-size:30px;line-height:1.3}}h2{{font-size:23px}}
section{{background:white;padding:24px;margin:24px 0;border:1px solid #dce1e7;border-radius:10px}}p{{margin:10px 0}}.muted{{color:#5f6874}}
img{{display:block;width:100%;height:auto;margin-top:16px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;white-space:nowrap}}
td,th{{padding:12px;text-align:left;border-bottom:1px solid #e2e5e9}}th{{background:#f2f4f6}}a{{color:#225fa8}}code{{overflow-wrap:anywhere}}
@media(max-width:600px){{main{{padding:16px 10px}}h1{{font-size:24px}}section{{padding:16px}}}}
</style><main><h1>ATR·−2σ 진입과 켈리 비중<br>실제 가격 백테스트</h1>
<p class="muted">연구용 · {_escape(evidence['date_from'])} ~ {_escape(evidence['date_through'])} · {_escape(evidence['rows_selected'])}개 일봉 · 현재 종목 검출·실계좌 주문 아님</p>
<section><h2>먼저 볼 결과</h2><p>학습·검증은 승률과 손익비를 확인하고, 최종 평가의 가격 전략 거래와 켈리 모의계좌는 분리해 확인합니다. 학습 {_escape(settings['min_train_trades'])}회·검증 {_escape(settings['min_validation_trades'])}회 이상, 각 순승률 {_pct(settings['min_win_rate'])} 이상, 평균 순손익비 {_escape(settings['min_payoff_ratio'])} 이상이 연구 배분 조건입니다. 조건을 충족하지 못하면 배분은 0%입니다.</p>
<div class="scroll"><table><thead><tr><th>종목</th><th>학습 / 순승률</th><th>검증 / 순승률</th><th>최종 평가 / 순승률</th><th>연구 비중</th><th>판정</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>20%는 자동 매수 비중이 아닌 종목별 최대 상한입니다. 가정 승률을 입력하지 않았습니다. VIX 관측 자료는 없으므로 시장 상태를 확인했다고 표시하지 않습니다.</p></section>
{''.join(sections)}<section><h2>결과를 읽는 방법</h2><p>실선은 전략의 단위자본 가격 연구, 점선은 같은 종목의 가격 보유 비교입니다. 보유 비교는 배당·거래비용을 포함한 시장지수 벤치마크가 아닙니다. 켈리 차트는 최종 평가 구간만 별도로 재생합니다.</p>
<img src="equity.png" alt="가격 전략과 최종 평가 켈리 모의계좌"><img src="summary.png" alt="최종 평가의 완료 거래 수와 순승률"></section>
<section><h2>계산·체결 기준</h2><p>종가 ≤ 20세션 평균 − 2 × 표본 표준편차일 때 계획 생성. ATR은 요청 수식대로 14세션 True Range의 단순 평균입니다. 진입=min(하단 밴드, 종가), 손절=max(진입−2ATR, 진입×0.92), 목표=진입+2×계획 손절폭.</p>
<p>신호 당일 체결 금지. 다음 {_escape(settings['order_expiry_sessions'])}개 관측 세션 동안 지정가 진입, 최대 {_escape(settings['max_holding_sessions'])}개 관측 세션 보유. 갭 손절은 시가 체결, 동일 봉 손절·목표 접촉은 손절 우선, 봉 중간 진입의 당일 목표 체결은 인정하지 않습니다. 거래량 0이면 체결하지 않습니다.</p>
<p>편도 수수료 {_escape(settings['fee_bps'])}bp, 편도 슬리피지 {_escape(settings['slippage_bps'])}bp, 매도세 {_escape(settings['tax_bps'])}bp는 연구 가정입니다. 8%는 계획 손절폭이고 갭 발생 시 실제 손실이 이를 넘을 수 있습니다. 켈리와 비중 상한은 파산 방지를 보장하지 않습니다.</p>
<p>학습 종료 {_escape(settings['train_end'])} / 검증 종료 {_escape(settings['validation_end'])}. 경계를 넘어 열린 거래는 해당 구간 승률 계산에서 제외하며, 최종 평가 결과로 검증 비중을 다시 맞추지 않습니다. 2점 켈리는 순수익 평균을 사용한 근사이며 수익분포 전체의 로그 최적해와 같지 않을 수 있습니다.</p>
<p>공식 참고: <a href="https://www.bollingerbands.com/bollinger-band-rules">Bollinger 규칙</a> · <a href="https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr">ATR 정의</a> · <a href="https://www.edwardothorp.com/wp-content/uploads/2016/11/TheKellyCriterionAndTheStockMarket.pdf">Thorp의 Kelly 설명</a></p></section>
<section><h2>입력과 재현</h2><p>{_escape(source_note)}저장된 가격의 과거 수집 시점, 수정주가 기준, 당시 종목 유니버스와 재무 안전성은 검증되지 않았습니다. 이 결과로 우량주 조건이나 현재 투자 가능성을 입증할 수 없습니다.</p>
<p>가격 파일 SHA-256: <code>{_escape(evidence['sha256'])}</code></p><p>{downloads}</p></section></main></html>'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, required=True, help='Actual OHLCV CSV')
    parser.add_argument('--symbols', help='Comma-separated explicit symbols, preserving leading zeros')
    parser.add_argument('--train-end', required=True)
    parser.add_argument('--validation-end', required=True)
    parser.add_argument('--input-audit', type=Path, help='Optional declared lineage audit (not a verification override)')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from atr_kelly_research import ATRKellyConfig, run_atr_kelly_backtest
        symbols = {_code(value) for value in args.symbols.split(',')} if args.symbols else None
        prices, evidence = load_ohlcv_csv(args.prices, symbols)
        if args.input_audit:
            declared = json.loads(args.input_audit.read_text(encoding='utf-8-sig'))
            if not isinstance(declared, dict):
                raise ValueError('Input audit must be a JSON object')
            evidence['lineage_audit'] = {'sha256': _hash(args.input_audit), 'declared': declared}
        report = run_atr_kelly_backtest(prices, config=ATRKellyConfig(
            train_end=args.train_end, validation_end=args.validation_end))
        report['input_evidence'] = evidence
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='atr-render-', dir=args.out.parent) as temporary:
            stage = Path(temporary)
            files = render_charts(report, stage)
            _csv(stage / 'trades.csv', report['trades'], ['code', 'name', 'phase', 'signal_date', 'entry_date',
                 'exit_date', 'entry_price', 'exit_price', 'stop_price', 'target_price', 'exit_reason',
                 'gross_return', 'net_return', 'calibration_included'])
            _csv(stage / 'signals.csv', [{**signal, 'code': item['code'], 'name': item['name']}
                 for item in report['symbols'] for signal in item['signals']],
                 ['code', 'name', 'signal_date', 'status', 'entry_price', 'stop_price', 'target_price', 'atr', 'lower_band'])
            _csv(stage / 'metrics.csv', [dict(code=item['code'], name=item['name'], phase=phase, **metric)
                 for item in report['symbols'] for phase, metric in item['phase_metrics'].items()],
                 ['code', 'name', 'phase', 'completed_count', 'wins', 'losses', 'zeros', 'p', 'payoff_ratio', 'mean_net_return'])
            (stage / 'report.html').write_text(render_html(report, files), encoding='utf-8')
            (stage / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            args.out.mkdir(parents=True, exist_ok=True)
            for filename in [*files, 'trades.csv', 'signals.csv', 'metrics.csv', 'report.html', 'report.json']:
                (stage / filename).replace(args.out / filename)
        print(json.dumps({'report': str((args.out / 'report.html').resolve()),
                          'symbols': len(report['symbols']), 'trades': len(report['trades']),
                          'production_eligible': False}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, OSError, ImportError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
