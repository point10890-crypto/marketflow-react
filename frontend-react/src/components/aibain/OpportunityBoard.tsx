import { effectiveOpportunityEngine, opportunityActionLabels, type OpportunityEngine, type OpportunityStrategy } from '@/lib/opportunityEngine';

const money = (value: number | null) => value === null ? '관측 대기' : `${Math.round(value).toLocaleString('ko-KR')}원`;
const pct = (value: number, signed = false) => `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const clock = (value: string | null) => value ? `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST` : '미확인';
const names: Record<OpportunityStrategy, string> = { momentum: '추세 지속', liquidity_breakout: '거래량 동반 돌파', mean_reversion: '과매도 회복' };
const stageNames: Record<string, string> = { data: '자료', setup: '가격 조건', critic: '반대 근거', diversification: '분산', risk: '비중', entry: '진입 시점' };
const stateNames = { passed: '통과', held: '보류', unavailable: '자료 부족' };
const disclosure = 'cursor-pointer rounded py-2 text-xs font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';
const reasons: Record<string, string> = { correlation_unavailable: '종목 간 가격 연관성을 확인하지 못해 불확실성 차감 적용',
    window_expired: '최초 진입 유효기간 종료', source_stale: '입력 자료 갱신 대기', quote_stale: '가격 관측 갱신 대기',
    calendar_unavailable: '공식 거래일 확인 대기', identity_mismatch: '연구 결정과 관측 자료 식별자 확인 대기' };
const explanation = (codes: string[]) => Array.from(new Set(codes.map(code => reasons[code] ?? '저장 근거의 제한 사항을 확인해야 합니다.'))).join(' · ');

export default function OpportunityBoard({ board, now, blocked = false, onSelectSymbol }: {
    board: OpportunityEngine; now: number; blocked?: boolean; onSelectSymbol?: (symbol: string) => void;
}) {
    const view = effectiveOpportunityEngine(board, now, blocked);
    const weight = view.candidates.reduce((sum, row) => sum + row.reference_weight, 0);
    return <section aria-label="수익 기회 순위" className="mb-5 min-w-0 space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3 border-y border-[#365372] py-3">
            <div className="min-w-0"><h3 className="text-base font-semibold text-gray-100">수익 기회 순위</h3>
                <p className="mt-1 text-xs leading-relaxed text-gray-300">종목 · 현재 조건 · 다음 행동 순서로 확인하세요.</p></div>
            <div className="text-[11px] leading-relaxed tabular-nums text-gray-400">검사 {view.coverage.inspected} · 근거 통과 {view.coverage.eligible} · 선택 {view.coverage.selected}<br />참고 총비중 {pct(weight)} / 상한 15%</div>
        </div>
        <p className="break-words text-[11px] leading-relaxed text-gray-400">과거 자료로 탐색한 새 순위 정책입니다. 독립 검증과 미래 수익 확률은 인증되지 않았습니다. 진입·체결·계좌 성과를 뜻하지 않습니다.</p>
        {blocked && <p className="text-xs text-amber-200">결과를 확인 중이거나 갱신에 실패하여 현재 진입 안내를 보류합니다.</p>}
        {view.candidates.length === 0 ? <p className="rounded-lg border border-[#30363f] p-4 text-xs text-gray-300">현재 선택된 기회 후보가 없습니다. 다음 저장 연구와 자료 상태를 확인하세요.</p>
            : <div className="grid min-w-0 gap-3 lg:grid-cols-3">{view.candidates.map(row => <article key={row.opportunity_id}
                aria-label={`${row.rank}위 ${row.name} ${row.symbol}`} className="min-w-0 rounded-lg border border-[#3b4d5c] bg-[#121a22] p-4">
                <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><span className="text-xs font-semibold text-[#acd3ff]">{row.rank}위</span>
                    <h4 className="mt-1 break-words text-base font-semibold text-gray-100">{row.name}</h4><p className="mt-1 text-[11px] tabular-nums text-gray-400">{row.symbol} · KR · {names[row.strategy_id]}</p></div>
                    <span className={`rounded border px-2 py-1 text-[11px] font-semibold ${row.action === 'entry_candidate' ? 'border-[#365372] text-[#acd3ff]' : 'border-amber-400/25 text-amber-200'}`}>{opportunityActionLabels[row.action]}</span></div>
                <dl className="mt-3 divide-y divide-[#30363f] text-xs tabular-nums">{[
                    ['현재 관측 가격', money(row.current_price)], ['참고 진입 범위', `${money(row.plan.entry_low)} ~ ${money(row.plan.entry_high)}`],
                    ['참고 손절', money(row.plan.stop_price)], ['참고 목표', money(row.plan.target_price)], ['참고 비중', pct(row.reference_weight)],
                ].map(([label, value]) => <div key={label} className="flex flex-wrap items-center justify-between gap-2 py-2"><dt className="text-gray-400">{label}</dt><dd className="font-mono text-gray-100">{value}</dd></div>)}</dl>
                <p className="mt-2 text-[11px] leading-relaxed text-gray-400">{row.plan.basis === 'observed_quote_reference' ? '저장된 현재 가격 관측 기준' : '최근 종가 기준'} · 최대 {row.plan.horizon_sessions}거래일 · 1/4 Kelly 참고 · 종목 상한 5% · 계좌 계획 손실 상한 1%</p>
                <dl className="mt-3 space-y-2 border-t border-[#30363f] pt-3 text-xs leading-relaxed">{[
                    ['이 종목인 이유', row.why_stock], ['현재 판단', row.why_now], ['다음 행동', row.next_action],
                ].map(([label, value]) => <div key={label}><dt className="font-semibold text-gray-200">{label}</dt><dd className="mt-1 break-words text-gray-300">{value}</dd></div>)}</dl>
                <p className="mt-3 text-[11px] leading-relaxed tabular-nums text-gray-400">진입 거래일 {view.entry_session ?? '공식 달력 확인 대기'}<br />최초 유효기한 {clock(row.valid_until)}<br />관측 {clock(row.quote_at)} · 저장 {clock(row.fetched_at)}</p>
                {onSelectSymbol && <button type="button" onClick={() => onSelectSymbol(row.symbol)} aria-label={`${row.name} 상세 분석`}
                    className="mt-3 min-h-11 w-full rounded-lg border border-[#365372] px-3 py-2 text-xs font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">종목 상세 분석</button>}
                <details className="mt-3 border-t border-[#30363f] pt-1"><summary className={disclosure}>순위 계산 · 출처 확인</summary><div className="space-y-2 text-[11px] leading-relaxed text-gray-400">
                    <p className="tabular-nums">비용 2배 과거 평균 {pct(row.ranking.stress_mean_net_return, true)} · 표준오차 {pct(row.ranking.standard_error)}<br />불확실성 차감 점수 {pct(row.ranking.conservative_score, true)} · 상관 차감 {pct(row.ranking.correlation_penalty)} · 최종 {pct(row.ranking.score, true)}</p>
                    <p>표준오차의 1.96배를 뺀 순위용 점수입니다. 독립 표본의 신뢰구간이나 미래 승률로 해석하지 않습니다.</p>
                    <p className="tabular-nums">형성 {row.ranking.calibration_samples}건 · 확인 {row.ranking.confirmation_samples}건 · 최근 입력 거래일 {row.quote_session}</p>
                    <p className="break-words">입력 가격: 저장 공급자 종가 스냅샷 · 수집 {clock(row.source_at)}<br />현재 관측: {row.quote_source ? 'KIS 국내 주식 가격 API' : '조회 근거 확인 대기'}</p>
                    <p>자료 감사 {stateNames[row.audit.status]} · 독립 검증 미인증</p>
                    {row.reasons.length + row.audit.reasons.length > 0 && <p>{explanation([...row.reasons, ...row.audit.reasons])}</p>}
                    <p className="break-all font-mono">결정 {row.decision_id}<br />입력 {row.input_fingerprint}<br />출처 감사 {row.source_audit_hash}</p>
                </div></details>
            </article>)}</div>}
        <details className="border-t border-[#30363f] pt-1"><summary className={disclosure}>검사 단계 · 대안 · 관측 기록</summary><div className="space-y-3 text-[11px] leading-relaxed text-gray-400">
            <ul className="grid gap-x-5 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">{view.stages.map(stage => <li key={stage.id} className="min-w-0"><strong className="text-gray-200">{stageNames[stage.id]} · {stateNames[stage.status]} · {stage.count}건</strong><p className="mt-1 break-words">{stage.detail}</p></li>)}</ul>
            {view.reasons.length > 0 && <p>{explanation(view.reasons)}</p>}
            {view.alternatives.length > 0 && <><p className="font-semibold text-gray-200">연구 대안 · 진입 안내 아님</p><ul className="space-y-1">{view.alternatives.map(row => <li key={row.symbol} className="break-words">{row.name} {row.symbol} · {names[row.strategy_id]} · {row.score === null ? '미산출' : `순위 점수 ${pct(row.score, true)}`} · {explanation([row.reason])}</li>)}</ul></>}
            {view.evaluation && <div><p className="font-semibold text-gray-200">발행 기회 기록 · 체결 기준 아님</p><p className="mt-1 tabular-nums">발행 {view.evaluation.issued} · 대기 {view.evaluation.pending} · 기간 종료 {view.evaluation.expired} · 관측 {view.evaluation.observed} · 미관측 {view.evaluation.unobserved}</p><p className="mt-1">실제 진입 근거 없이 성공률·수익률을 계산하지 않습니다. 미관측은 미체결을 뜻하지 않습니다.</p></div>}
            <p className="tabular-nums">순위 생성 {clock(view.generated_at)} · 최초 유효기한 {clock(view.valid_until)}</p>
        </div></details>
    </section>;
}
