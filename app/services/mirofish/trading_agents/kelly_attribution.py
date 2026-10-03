"""Read-only Kelly attribution; never changes frozen evidence or paper orders."""
from __future__ import annotations

import hashlib
import html
import json
import math

from .models import create_message


def number(value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Finite numerical evidence is required')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError('Numerical evidence exceeds its bounds')
    return float(value)


def binary_kelly(p, b):
    """Binary stake fraction, with a full stake lost on failure; not stock weight."""
    p, b = number(p, 0, 1), number(b, 0)
    if b <= 0:
        raise ValueError('Payoff must be positive')
    return p - (1. - p) / b


def same(left, right):
    return math.isclose(number(left), number(right), abs_tol=1e-9, rel_tol=1e-9)


def build_kelly_attribution(report):
    # Reject credential-bearing/nonfinite JSON before any export. No journal is opened.
    create_message('kelly-view', 'request', {'input': report})
    if report.get('paper_only') is not True or report.get('live_orders') is not False:
        raise ValueError('This view requires a paper-only report')
    encoded = json.dumps(report, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    view = dict(schema_version=1, run_id=report['run_id'], synthetic=report['synthetic'],
        report_sha256=hashlib.sha256(encoded).hexdigest(), source_split='validation',
        evidence_basis='recorded_report_not_recomputed_return_samples',
        objective='argmax[0 <= f <= 1] mean(log(1 + f * R_i))',
        reference_example=dict(win_rate=.6, payoff=1., full_kelly=binary_kelly(.6, 1.),
                               half_kelly=.5 * binary_kelly(.6, 1.)),
        status='pending', rows=[], decisions=[], approved_exposure=None,
        portfolio_scale=None, new_fill_count=len(report.get('execution', {}).get('fills', [])))
    data, quant, risk = (report.get(key, {}) for key in ('data', 'quant', 'risk'))
    if data.get('status') != 'ready' or quant.get('qualification_complete') is not True:
        return view
    if risk.get('status') != 'approved':
        view['status'] = 'held'
        return view
    try:
        fraction = number(risk['kelly_fraction'], 0, .5)
        cap = number(risk['max_weight'], 0, .2)
        threshold = number(risk['volatility_threshold'], 0)
        maximum = min(number(risk['max_exposure'], 0, .6), 1 - number(risk['min_cash'], .4, 1))
        equity = number(risk['portfolio_equity'], 0)
        if fraction <= 0 or cap <= 0 or threshold <= 0:
            raise ValueError('Missing positive limits')
        targets = {key: number(value, 0, cap) for key, value in risk['targets'].items()}
        evidence = risk['candidate_evidence']
        symbols = [row['symbol'] for row in evidence]
        if len(symbols) > 3 or len(symbols) != len(set(symbols)):
            raise ValueError('Duplicate or excessive candidate evidence')
        if not set(symbols).issubset(targets) or {key for key, value in targets.items() if value > 0} - set(symbols):
            raise ValueError('Targets and evidence disagree')
        rows = []
        for record in evidence:
            metrics = record['validation']
            n = metrics['samples']
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise ValueError('Missing validation samples')
            p, b = number(metrics['win_rate'], 0, 1), number(metrics['payoff'], 0)
            gain, loss = number(metrics['avg_win'], 0), number(metrics['avg_loss'], 0)
            if gain <= 0 or loss <= 0 or not same(b, gain / loss):
                raise ValueError('Validation payoff does not match recorded means')
            empirical = number(record['estimated_kelly'], 0, 1)
            partial = fraction * empirical
            capped = min(cap, partial)
            volatility = number(record['prior_volatility'], 0)
            reduced = volatility > threshold
            multiplier = .5 if reduced else 1.
            if record['high_volatility_reduction'] is not reduced or not same(record['base_target_weight'], capped):
                raise ValueError('Recorded cap/volatility steps disagree')
            rows.append(dict(symbol=record['symbol'], name=record['name'], market=record['market'],
                validation_samples=n, win_rate=p, payoff=b, avg_win=gain, avg_loss=loss,
                win_lower=number(metrics['win_lower'], 0, 1),
                binary_stake_diagnostic=binary_kelly(p, b), empirical_kelly=empirical,
                kelly_fraction=fraction, fractional_kelly=partial, max_weight=cap,
                capped_weight=capped, prior_volatility=volatility,
                volatility_threshold=threshold, volatility_multiplier=multiplier,
                pre_exposure_weight=capped * multiplier))
        total = sum(row['pre_exposure_weight'] for row in rows)
        scale = min(1., maximum / total) if total > 0 else 1.
        approval = report.get('approval', {}).get('decision') == 'approved'
        execution = report.get('execution', {})
        duplicate = execution.get('status') == 'duplicate_day'
        nav = (number(execution['nav_after'], 0)
               if approval and execution.get('status') == 'executed' else None)
        for row, record in zip(rows, evidence):
            weight = row['pre_exposure_weight'] * scale
            if not same(record['target_weight'], weight) or not same(targets[row['symbol']], weight):
                raise ValueError('Recorded final targets disagree with the Kelly path')
            buys = [fill for fill in execution.get('fills', [])
                    if fill['symbol'] == row['symbol'] and fill['side'] == 'BUY']
            row.update(portfolio_scale=scale, final_weight=weight,
                planned_amount=equity * weight if approval and not duplicate else None,
                post_cost_nav=nav, post_cost_target_value=nav * weight if nav is not None else None,
                buy_cash_debit=sum(-number(fill['cash_delta']) for fill in buys) if nav is not None else None)
        # Selection decisions use frozen qualification and current candidate identity, never test outcomes.
        fresh = {row['symbol'] for row in quant.get('candidates', [])}
        decisions = []
        for row in quant.get('qualification', []):
            symbol = row['symbol']
            reason = ('allocated' if targets.get(symbol, 0) > 0 else
                      'zero_risk_weight' if symbol in symbols else
                      'exit_target' if symbol in targets else
                      'not_selected' if symbol in fresh else
                      'no_current_entry_signal' if row.get('eligible') is True else row.get('reason', 'unqualified'))
            decisions.append(dict(symbol=symbol, name=row['name'], reason=reason,
                                  final_weight=targets.get(symbol, 0.) if approval else None))
        view.update(status='duplicate_day' if duplicate and approval else 'ready' if approval else 'held',
                    rows=rows, decisions=decisions, portfolio_scale=scale,
                    approved_exposure=sum(targets.values()) if approval and not duplicate else None)
    except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError):
        view.update(status='inconsistent', rows=[], decisions=[], approved_exposure=None, portfolio_scale=None)
    return view


def render_kelly_section(view):
    def esc(value):
        return html.escape(str(value))
    def pct(value):
        return '계산 대기' if value is None else f'{value:.2%}'
    def money(value):
        return '배정 미승인 / 미체결' if value is None else f'{value:,.2f}원'
    reference = view['reference_example']
    section = ['<section id="kelly" class="kelly"><h2>검출 결과 → 켈리 공식 → 투자 비중</h2>',
        '<p class="formula">기본 이항식: f* = p − (1 − p) / b</p>',
        f'<p>설명용 가정: 승률 60% · 손익비 1 → Full Kelly {pct(reference["full_kelly"])} '
        f'→ Half Kelly {pct(reference["half_kelly"])}. 이 예시는 실제 투자 비중이 아닙니다.</p>',
        '<p>주식 비중 계산: <strong>f* = argmax<sub>0 ≤ f ≤ 1</sub> 평균 ln(1 + f × Rᵢ)</strong>. '
        'Rᵢ는 검증 기간의 개별 비용 차감 주식 수익률입니다. 이항식은 실패 시 베팅액 전액을 잃는 가정이므로 '
        '주식 비중 계산에는 실제 손실 폭과 수익률 분포를 반영합니다.</p>',
        '<p class="muted">저장된 검증 근거와 Risk 계산 기록을 대조한 표시입니다. 원 수익률 표본을 재추정하거나 '
        '새 CIO 승인을 발행하지 않습니다. 종목당 20%는 상한이며, 켈리는 손실 위험을 없애지 않습니다.</p>']
    if view['status'] == 'pending':
        section.append('<div class="kelly-state"><strong>실제 종목 켈리 계산 대기</strong><p>가격 보정·최초 공시 재무·출처 시각 검증을 '
                       '완료한 뒤 승률 p, 손익비 b, 개별 순수익 Rᵢ를 계산합니다. 현재 승인된 투자 비중과 투자 금액은 없습니다.</p></div>')
    elif view['status'] == 'inconsistent':
        section.append('<div class="kelly-state">켈리 계산 기록 불일치: 승인 비중과 금액을 표시하지 않습니다.</div>')
    elif view['status'] == 'held':
        section.append('<div class="kelly-state">CIO 또는 Risk 보류: 계산된 비중은 검토용이며 투자 금액은 미승인입니다.</div>')
    elif view['status'] == 'duplicate_day':
        section.append('<div class="kelly-state">당일 실행 기록 재사용 · 추가 체결 0건. 아래 비중은 이번 요청의 검토 목표이며 '
                       '기존 체결 비중을 확인한 값이 아닙니다. 추가 실행되지 않았습니다.</div>')
    for row in view['rows']:
        section.extend([f'<article class="kelly-stock"><h3>{esc(row["name"])} · {esc(row["symbol"])} · {esc(row["market"])}</h3>',
            f'<p>검증 {row["validation_samples"]}표본 · 관측 승률 <strong>{pct(row["win_rate"])}</strong> '
            f'· Wilson 하한 {pct(row["win_lower"])} · 손익비 <strong>{row["payoff"]:.3f}</strong> '
            f'· 평균 이익 {pct(row["avg_win"])} / 평균 손실 {pct(row["avg_loss"])}</p>',
            f'<p class="muted">이항식 비교값 {pct(row["binary_stake_diagnostic"])} '
            '(0% 수익도 실패로 단순화한 두 결과 진단값; 주식 배정에 사용하지 않음).</p>',
            '<div class="kelly-flow">',
            f'<div><small>① 순수익 표본 Kelly</small><b>{pct(row["empirical_kelly"])}</b><span>0~100% 무레버리지 제약</span></div>',
            f'<div><small>② {"하프 켈리" if row["kelly_fraction"] == .5 else "부분 켈리"} × {pct(row["kelly_fraction"])}</small><b>{pct(row["fractional_kelly"])}</b><span>Kelly × 안전 계수</span></div>',
            f'<div><small>③ 종목 상한 {pct(row["max_weight"])}</small><b>{pct(row["capped_weight"])}</b><span>상한 적용 후 비중</span></div>',
            f'<div><small>④ 변동성 × {row["volatility_multiplier"]:g}</small><b>{pct(row["pre_exposure_weight"])}</b>'
            f'<span>σ {pct(row["prior_volatility"])} / 기준 {pct(row["volatility_threshold"])}</span></div>',
            f'<div class="kelly-final"><small>⑤ 전체 노출 × {row["portfolio_scale"]:g}</small><b>{pct(row["final_weight"])}</b><span>최종 목표 비중</span></div></div>',
            f'<p>비용 전 배정 계획 <strong>{money(row["planned_amount"])}</strong> · '
            f'비용 후 목표 평가액 <strong>{money(row["post_cost_target_value"])}</strong></p>',
            f'<p class="muted">비용 후 순자산 {money(row["post_cost_nav"])} · 이 실행의 매수 현금 지출 '
            f'{money(row["buy_cash_debit"])} (수수료·슬리피지 반영).</p></article>'])
    labels = dict(allocated='최종 배정', exit_target='기존 보유분 청산 목표',
                  zero_risk_weight='현금·전체 노출 한도: 목표 비중 0%',
                  not_selected='포지션 한도 / 비중 조건으로 미배정',
                  no_current_entry_signal='통계 통과 · 현재 신규 진입 신호 없음',
                  train_low_payoff='학습 손익비 기준 미달', benchmark_only='비교 지수 · 투자 대상 제외')
    if view['status'] == 'duplicate_day':
        labels.update(allocated='이번 요청 검토 목표 · 추가 체결 없음', exit_target='청산 검토 목표 · 추가 체결 없음')
    elif view['status'] == 'held':
        labels.update(allocated='Risk 검토 비중 · CIO 미승인', exit_target='청산 검토 목표 · CIO 미승인')
    if view['decisions']:
        section.append('<h3>통계 자격이 최종 배정으로 이어지는 이유</h3><div class="scroll"><table><tr><th>종목</th><th>판정</th><th>목표 비중</th></tr>')
        section.extend(f'<tr><td>{esc(row["name"])} ({esc(row["symbol"])})</td>'
                       f'<td>{esc(labels.get(row["reason"], row["reason"]))}</td><td>{pct(row["final_weight"])}</td></tr>'
                       for row in view['decisions'])
        section.append('</table></div>')
    section.append('</section>')
    return ''.join(section)
