import { evolutionArmIds, validateEvolutionContext, type EvolutionArmId, type EvolutionContext } from '@/lib/evolutionContext';
import type { OpportunityIdentity } from '@/lib/opportunityEngine';

const arms: Record<EvolutionArmId, { label: string; detail: string }> = {
    control: { label: '기존 선정 · 대조군', detail: '기존 선정 종목을 다음 장 시가로 모의 관측합니다.' },
    'entry-band-v1': { label: '진입 밴드 확인', detail: '같은 선정에서 다음 장 시가가 고정 진입 구간 안에 있을 때만 관측합니다.' },
    'recovery-confirmed-v1': { label: '회복 확인', detail: '전체 적격 후보에서 양봉과 전일 종가 회복 조건을 추가합니다.' },
    'positive-rank-v1': { label: '양수 순위', detail: '기존 근거와 상관 검사를 유지하고 최종 점수가 양수인 후보만 선택합니다.' },
};
const phases: Record<EvolutionContext['phase'], string> = {
    collecting_nomination: '후보 지명 관측 중', embargo: '선행 결과 성숙 간격', collecting_confirmation: '별도 확인 관측 중',
    maturing: '마지막 결과 종료 대기', awaiting_review: '연구 후보 · 검토 대기', incumbent_retained: '기존 정책 유지',
};
const reasonLabels: Record<string, string> = {
    current_identity_mismatch: '현재 화면의 선정과 관측 자료가 일치하지 않습니다.',
    current_selection_unavailable: '현재 화면의 선정에 연결된 전향 관측 자료가 아직 없습니다.',
    last_refresh_failed: '최근 관측 갱신에 실패하여 저장 자료를 확인해야 합니다.',
    awaiting_first_prospective_decision: '첫 전향 선정 관측을 기다립니다.',
    future_window_incomplete: '고정된 미래 평가 구간이 아직 완료되지 않았습니다.',
    fixed_window_incomplete: '고정된 미래 평가 구간이 아직 완료되지 않았습니다.',
    awaiting_nomination_labels: '후보 지명 구간의 종료 결과를 기다립니다.',
    no_fixed_nominated_challenger: '고정된 지명 비교군이 아직 없습니다.',
    nomination_coverage_unresolved_at_fixed_boundary: '고정 지명 시점까지 대응 결과가 해결되지 않아 비교군을 지명하지 않았습니다.',
    fixed_nomination_paired_stress_mean: '후보 지명 구간의 비용 2배 대응 평균으로 비교군을 고정했습니다.',
    confirmation_coverage_unresolved: '별도 확인 구간에 종료되지 않거나 누락된 대응 결과가 있습니다.',
    declared_window_coverage_unresolved: '전체 고정 평가 구간의 대응 결과가 아직 모두 해결되지 않았습니다.',
    revised_coverage: '자료 변경이 확인된 관측 결과가 있어 엄격한 집계와 후보 판단에서 제외합니다.',
    unverifiable_input_provenance: '입력 자료의 수집 시점과 출처를 검증하지 못했습니다.',
    historical_vintage_unverified: '과거 자료가 당시에도 같은 내용으로 제공되었는지 검증되지 않았습니다.',
    corporate_action_adjustment_unverified: '기업행사에 따른 수정주가 반영을 검증하지 못했습니다.',
    current_quality_cohort_survivorship_bias: '현재 적격 종목 목록을 사용해 생존 편향이 남아 있습니다.',
    paper_costs_and_fills_not_brokerage_execution: '모의 비용과 체결 가정을 사용하며 실제 증권사 체결과 다를 수 있습니다.',
    insufficient_control_entered_outcomes: '대조군의 수정되지 않은 진입 완료 표본이 부족합니다.',
    insufficient_confirmation_blocks: '서로 겹치지 않는 별도 확인 구간 표본이 부족합니다.',
    confirmation_nonpositive_normal_mean: '별도 확인 구간의 순평균이 양수 조건을 충족하지 못했습니다.',
    confirmation_nonpositive_stress_mean: '별도 확인 구간의 비용 2배 순평균이 양수 조건을 충족하지 못했습니다.',
    confirmation_nonpositive_paired_advantage: '별도 확인 구간의 대조군 대비 대응 우위가 양수 조건을 충족하지 못했습니다.',
    confirmation_nonpositive_paired_stress_advantage: '별도 확인 구간의 비용 2배 대응 우위가 양수 조건을 충족하지 못했습니다.',
    confirmation_block_lower_bound_nonpositive: '별도 확인 구간의 보수적 차이 지표가 양수 조건을 충족하지 못했습니다.',
    confirmation_downside_tail_worse_or_unknown: '별도 확인 구간의 하방 꼬리 손실이 악화되었거나 확인되지 않았습니다.',
    nomination_window_incomplete: '후보 지명 관측 구간이 아직 완료되지 않았습니다.',
    confirmation_window_incomplete: '별도 확인 관측 구간이 아직 완료되지 않았습니다.',
    labels_pending: '아직 종료되지 않은 관측 결과가 있습니다.',
    recovery_not_confirmed: '종가 회복 조건을 확인하지 못했습니다.',
    source_revision: '원래 결과 이후 자료 변경이 확인되어 엄격한 집계에서 제외합니다.',
    revised_evidence: '자료 변경 결과가 있어 연구 후보 판단을 보류합니다.',
    no_challenger_qualified: '고정 검증 조건을 통과한 비교군이 없습니다.',
    insufficient_entered_outcomes: '수정되지 않은 진입 완료 표본이 부족합니다.',
    insufficient_blocks: '서로 겹치지 않는 확인 구간 표본이 부족합니다.',
    provenance_unverified: '입력 자료의 수집 시점과 출처 검증이 완료되지 않았습니다.',
    stress_net_not_positive: '비용 2배 순성과가 양수 조건을 충족하지 못했습니다.',
    paired_advantage_not_positive: '대조군 대비 대응 우위가 양수 조건을 충족하지 못했습니다.',
    downside_tail_worsened: '하방 꼬리 손실이 대조군보다 악화되었습니다.',
};
const explain = (reason: string) => reasonLabels[reason] ?? reason;
const pct = (value: number | null) => value === null ? '미산출' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
const points = (value: number | null) => value === null ? '미산출' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%p`;
const loss = (value: number | null) => value === null ? '미산출' : `${(value * 100).toFixed(2)}%`;
const clock = (value: string) => `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST`;
const linkClass = 'flex !min-h-11 max-w-full flex-wrap items-center gap-x-2 rounded py-2 text-left font-semibold text-[#acd3ff] underline decoration-[#365372] underline-offset-4 [overflow-wrap:anywhere] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';
const disclosureClass = 'min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';

export default function AlphaLabEvolutionPanel({ context, board, now = Date.now(), onSelectSymbol }: {
    context?: unknown; board?: OpportunityIdentity; now?: number; onSelectSymbol?: (symbol: string) => void;
}) {
    const value = validateEvolutionContext(context, board, now);
    if (!value) return null;
    const mismatch = value.binding_status !== 'current';
    const held = mismatch || value.status === 'held';
    const selectionHeld = held || value.reasons.includes('current_selection_unavailable');
    const reviewReasons = [...new Set([...value.reasons, ...value.review.reasons])];
    const reviewLabel = held ? '연구 후보 판단 보류' : value.review.status === 'awaiting_review' ? '연구 후보 · 검토 대기'
        : value.review.status === 'rejected' ? '기존 정책 유지' : '연구 후보 판단 보류';
    return <section aria-label="알파 진화 관측" className="mb-5 min-w-0 space-y-4 border-t border-[#30363f] pt-4 text-base leading-relaxed [overflow-wrap:anywhere] sm:text-sm">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
            <div className="min-w-0"><h3 className="font-semibold text-gray-100">알파 진화 관측</h3>
                <p className="mt-1 text-gray-300">세 가지 고정 가설을 기존 선정과 같은 결정일에 비교합니다.</p></div>
            <span className={`max-w-full rounded border px-2 py-1 font-semibold ${held ? 'border-amber-400/25 text-amber-200' : 'border-[#365372] text-[#acd3ff]'}`}>{mismatch ? '현재 선정 연결 보류' : value.status === 'held' ? '자료 확인 보류' : phases[value.phase]}</span>
        </div>
        <div className="min-w-0 space-y-2 border-l-2 border-[#365372] pl-3">
            <p className="text-gray-300">저장 단계: {phases[value.phase]}</p>
            <p className="font-semibold text-gray-100">다음 단계</p><p className="text-gray-300">{value.next_step}</p>
            <p className="tabular-nums text-gray-400">결정 등록 {value.window.enrolled_sessions}/{value.window.decision_sessions}거래일<br />대조군 결과 해결 {value.window.resolved_sessions}거래일</p>
            <p className="tabular-nums text-gray-400">지명 {value.window.nomination_sessions} · 간격 {value.window.embargo_sessions} · 별도 확인 {value.window.confirmation_sessions}거래일<br />추가 종료 관측 {value.window.maturation_observed}/{value.window.maturation_sessions}거래일</p>
        </div>
        <p className="text-gray-400">누적 대응 모의 관심목록 성과입니다. 각 결정일의 세 칸을 같은 비중으로 계산하며 계좌 수익이나 실제 체결을 뜻하지 않습니다. 미완료·자료 변경 결과는 엄격한 대응 집계에 포함하지 않습니다.</p>
        <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">{evolutionArmIds.map(id => {
            const arm = value.arms.find(row => row.id === id)!;
            const selections = selectionHeld ? [] : arm.selected;
            return <article key={id} aria-label={arms[id].label} className="min-w-0 rounded-lg border border-[#303f4b] bg-[#121a22] p-3 sm:p-4">
                <h4 className="font-semibold text-gray-100">{arms[id].label}</h4><p className="mt-1 text-gray-400">{arms[id].detail}</p>
                <div className="mt-3 min-w-0 border-t border-[#30363f] pt-2"><p className="font-semibold text-gray-200">현재 고정 선정</p>
                    {selections.length ? <ul>{selections.map(row => <li key={row.symbol} className="min-w-0">{onSelectSymbol
                        ? <button type="button" className={linkClass} onClick={() => onSelectSymbol(row.symbol)} aria-label={`${row.name} ${row.symbol} 상세 분석`}><span>{row.name}</span><span className="font-mono text-gray-400">{row.symbol}</span></button>
                        : <a className={linkClass} href={`/dashboard/ai-bain/chart-predict?code=${row.symbol}`} aria-label={`${row.name} ${row.symbol} 상세 분석`}><span>{row.name}</span><span className="font-mono text-gray-400">{row.symbol}</span></a>}</li>)}</ul>
                        : <p className="mt-1 text-gray-400">{selectionHeld ? '현재 선정 연결 확인 대기' : value.window.enrolled_sessions === 0 ? '첫 전향 선정 관측 대기' : '현재 조건 통과 종목 없음 · 빈 칸 유지'}</p>}
                </div>
                <dl className="mt-3 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 tabular-nums">
                    <div className="min-w-0"><dt className="text-gray-400">대응 순평균</dt><dd className="mt-1 font-mono font-semibold text-gray-100">{pct(arm.metrics.mean_net_return)}</dd></div>
                    <div className="min-w-0"><dt className="text-gray-400">비용 2배 순평균</dt><dd className="mt-1 font-mono font-semibold text-gray-100">{pct(arm.metrics.stress_mean_net_return)}</dd></div>
                </dl>
                <p className="mt-3 tabular-nums text-gray-300">대응 완료 {arm.counts.paired_sessions}거래일 · 결과 확정 {arm.counts.resolved}칸<br />종료 {arm.counts.closed} · 진입 생략 {arm.counts.skipped} · 빈 칸 {arm.counts.cash} · 미체결 {arm.counts.unfilled}<br />수정 제외 {arm.counts.revised} · 대기 {arm.counts.pending} · 관측 중 {arm.counts.open} · 자료 누락 {arm.counts.missing}</p>
                {arm.reasons.length > 0 && <ul className="mt-2 space-y-1 text-gray-400">{arm.reasons.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul>}
                <details className="mt-2 min-w-0 border-t border-[#30363f]"><summary className={disclosureClass}>대조군 차이 · 놓친 기회</summary><div className="space-y-2 pb-2 text-gray-400">
                    <p className="tabular-nums">대조군 대비 평균 {points(arm.metrics.paired_advantage)}<br />비용 2배 차이 {points(arm.metrics.stress_paired_advantage)}<br />하방 꼬리 손실 {loss(arm.metrics.downside_tail_loss)}</p>
                    <p className="tabular-nums">놓친 대조군 이익 {arm.counts.missed_control_winners} · 피한 대조군 손실 {arm.counts.avoided_control_losers}</p>
                </div></details>
            </article>;
        })}</div>
        <div className="min-w-0 space-y-2 border-t border-[#30363f] pt-3">
            <h4 className="font-semibold text-gray-100">{reviewLabel}</h4>
            <p className="text-gray-300">{value.nomination.status === 'fixed' && value.nomination.arm_id ? `지명 비교군: ${arms[value.nomination.arm_id].label}` : value.nomination.status === 'none' ? '지명할 비교군 없음' : '지명 비교군: 관측 대기'} · {explain(value.nomination.reason)}</p>
            {reviewReasons.length > 0 && <ul className="space-y-1 text-gray-400">{reviewReasons.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul>}
            {value.review.limitations.length > 0 && <div className="space-y-1 text-gray-400"><p className="font-semibold text-gray-200">관측의 한계</p><ul className="space-y-1">{value.review.limitations.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul></div>}
            <p className="text-gray-400">고정 평가를 통과해도 연구 후보로 검토를 기다립니다. 승인 노출 0 · 주문 실행 없음.</p>
            <details className="min-w-0 border-t border-[#30363f]"><summary className={disclosureClass}>연구 검토 근거 · 저장 시각</summary><div className="space-y-2 pb-2 text-gray-400">
                <p className="tabular-nums">별도 확인 진입 결과 {value.review.entered_outcomes} · 대조군 {value.review.control_entered_outcomes}<br />겹치지 않는 {value.window.block_sessions}거래일 구간 {value.review.completed_blocks}/{value.window.minimum_blocks}</p>
                <p className="tabular-nums">선택 비교군 순평균 {pct(value.review.normal_mean)} · 비용 2배 {pct(value.review.stress_mean)}<br />대조군 차이 {points(value.review.paired_advantage)} · 비용 2배 차이 {points(value.review.stress_paired_advantage)}<br />구간별 보수적 차이 지표 {points(value.review.block_lower_bound)} · 꼬리 손실 변화 {points(value.review.downside_tail_delta)}</p>
                <p>구간이 같은 시장과 보유 기간의 영향을 공유할 수 있습니다. 고정 연구 지표이며 신뢰구간이나 확률을 뜻하지 않습니다.</p>
                <p className="tabular-nums">고정 선언 <time dateTime={value.declared_at}>{clock(value.declared_at)}</time><br />관측 저장 <time dateTime={value.generated_at}>{clock(value.generated_at)}</time></p>
            </div></details>
        </div>
    </section>;
}
