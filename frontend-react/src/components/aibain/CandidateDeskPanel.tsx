import { candidateDeskEntryAvailable, candidateDeskEntryView, validateCandidateDesk, type CandidateDesk, type CandidateDeskPhase, type CandidateModelEvidence } from '@/lib/candidateDesk';

const money = (n: number) => `${Math.round(n).toLocaleString('ko-KR')}원`;
const pct = (n: number | null) => n === null ? '관측 대기' : `${(n * 100).toFixed(1)}%`;
const evidencePct = (n: number | null) => n === null ? '관측 대기' : `${(n * 100).toFixed(2)}%`;
const clock = (v: string | null) => v ? `${new Date(Date.parse(v) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST` : '공식 거래일 확인 대기';
const disclosure = 'min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';
const funnelNames: Record<string, string> = { inspected: '검사 종목', current_setup: '가격·거래량 통과',
    pooled_evidence: '과거 검증 통과', eligible: '조건부 제안 가능', returned: '선택 종목', selected: '선택 종목',
    training_events: '학습 거래 사례', model_context: '유사 조건 통과' };
const reasonNames: Record<string, string> = {
    no_current_setup: '현재 추세·상대강도·거래대금 조건을 통과한 종목 없음',
    no_positive_context_proposals: '현재 후보의 유사 조건에서 비용 차감 기대값이 양수인 종목 없음',
    insufficient_union_history: '고정 학습·비교 구간을 구성할 가격 이력 부족',
    entry_window_unavailable: '새 공식 진입 거래일 확인 필요 · 이전 계획 만료',
    refresh_unavailable: '새 분석 갱신 중이거나 갱신 실패 · 이전 계획 비활성',
    formation_samples_insufficient: '형성 구간의 완료 관측 부족', confirmation_samples_insufficient: '확인 구간의 완료 관측 부족',
    formation_blocks_insufficient: '형성 구간의 시장 국면 표본 부족', confirmation_blocks_insufficient: '확인 구간의 시장 국면 표본 부족',
    formation_symbols_insufficient: '형성 구간의 종목 분산 부족', formation_net_nonpositive: '형성 구간의 비용 차감 수익 조건 미충족',
    confirmation_net_nonpositive: '확인 구간의 비용 차감 수익 조건 미충족', formation_stress_nonpositive: '형성 구간의 비용 2배 조건 미충족',
    confirmation_stress_nonpositive: '확인 구간의 비용 2배 조건 미충족', no_active_setup: '현재 가격·거래량 조건을 통과한 종목 없음',
    input_refresh_failed_previous_snapshot_retained: '자료 갱신 실패 · 이전 계획 보존', calendar_unavailable: '공식 거래일 확인 대기',
    source_stale: '가격 자료 갱신 대기', source_revision: '출처 수정 자료 확인 대기',
    formation_insufficient_completed_events: '형성 구간의 완료 관측 부족', confirmation_insufficient_completed_events: '확인 구간의 완료 관측 부족',
    formation_insufficient_calendar_blocks: '형성 구간의 시장 국면 표본 부족', confirmation_insufficient_calendar_blocks: '확인 구간의 시장 국면 표본 부족',
    formation_insufficient_unique_symbols: '형성 구간의 종목 분산 부족',
    formation_nonpositive_mean_net_return: '형성 구간의 비용 차감 수익 조건 미충족', confirmation_nonpositive_mean_net_return: '확인 구간의 비용 차감 수익 조건 미충족',
    formation_nonpositive_stress_mean_net_return: '형성 구간의 비용 2배 조건 미충족', confirmation_nonpositive_stress_mean_net_return: '확인 구간의 비용 2배 조건 미충족',
};
function factLabel(fact: string) {
    let match = /^20-session return ([+-]?[\d.]+%); cohort median ([+-]?[\d.]+%)\.$/.exec(fact);
    if (match) return `20거래일 수익률 ${match[1]} · 코호트 중앙값 ${match[2]}`;
    match = /^60-session return ([+-]?[\d.]+%); SMA20 above SMA60\.$/.exec(fact);
    if (match) return `60거래일 수익률 ${match[1]} · 20일선이 60일선 상회`;
    match = /^20-session average traded value KRW ([\d,]+)\.$/.exec(fact);
    if (match) return `20거래일 평균 거래대금 ${match[1]}원`;
    match = /^Other-symbol context: (\d+) events, (\d+) calendar blocks\.$/.exec(fact);
    if (match) return `다른 종목 유사 사례 ${match[1]}건 · 달력 블록 ${match[2]}개`;
    match = /^Experimental cost-stress expectation ([+-]?[\d.]+%); forward validation collecting\.$/.exec(fact);
    if (match) return `실험 모델 비용 2배 추정 ${match[1]} · 전향 검증 중`;
    match = /^Prior-20-high ratio ([\d.]+); volume ratio capped at 3: ([\d.]+)\.$/.exec(fact);
    return match ? `직전 20거래일 고가 비율 ${match[1]} · 거래량 비율 ${match[2]} (상한 3)` : fact;
}
function PhaseEvidence({ label, phase }: { label: string; phase: CandidateDeskPhase }) {
    return <div className="min-w-0 border-t border-[#30363f] py-3">
        <h5 className="font-semibold text-gray-200">{label}</h5>
        <p className="mt-1 tabular-nums">완료 {phase.samples}건 · 수익 관측 {phase.wins}건 · 관측 수익 빈도 {pct(phase.win_rate)}</p>
        <p className="mt-1 tabular-nums">비용 차감 평균 {evidencePct(phase.mean_net_return)} · 비용 2배 평균 {evidencePct(phase.stress_mean_net_return)}</p>
        <p className="mt-1 tabular-nums">10거래일 달력 블록 {phase.block_count}개 · 종목 {phase.unique_symbols}개</p>
    </div>;
}
function LocalModelEvidence({ name, evidence }: { name: string; evidence: CandidateModelEvidence }) {
    return <section aria-label={`${name} 유사 사례 통계`} className="mt-3 min-w-0 space-y-1 border-t border-[#30363f] pt-3 text-xs leading-relaxed text-gray-400">
        <h5 className="font-semibold text-gray-200">학습 구간 유사 사례</h5>
        <p className="tabular-nums">완료 {evidence.samples}건 · 달력 블록 {evidence.block_count}개 · 종목 {evidence.unique_symbols}개</p>
        <p className="tabular-nums">과거 수익 관측 {evidence.wins}건 · 관측 빈도 {pct(evidence.win_rate)}</p>
        <p className="tabular-nums">유사 사례 순평균 {evidencePct(evidence.mean_net_return)} · 비용 2배 순평균 {evidencePct(evidence.stress_mean_net_return)}</p>
        <p className="tabular-nums text-gray-300">모델 추정 순수익 {evidencePct(evidence.expected_net_return)} · 비용 2배 추정 {evidencePct(evidence.expected_stress_net_return)}</p>
        <p>미래 승률로 보정되지 않은 모델 추정값입니다.</p>
        <p className="tabular-nums">학습 마감 {evidence.training_end} · 해당 종목 제외</p>
    </section>;
}

export default function CandidateDeskPanel({ desk, now, blocked = false, onSelectSymbol }: {
    desk?: CandidateDesk; now: number; blocked?: boolean; onSelectSymbol?: (symbol: string) => void;
}) {
    const view = validateCandidateDesk(desk, now);
    if (!view) return <section aria-label="시장 비교 후보" className="mb-5 min-w-0 rounded-lg border border-amber-400/25 p-4 text-sm leading-relaxed text-amber-200">
        <p role="status">시장 비교 후보를 확인할 수 없습니다. 저장 결과를 새로고침해 주세요.</p>
        <p className="mt-2 text-xs">신규 진입 불가 · 후보 자료의 출처와 시점을 확인해야 합니다.</p>
    </section>;
    const available = candidateDeskEntryAvailable(view, now, blocked);
    const contextual = view.policy_version === 'contextual-candidates-v4';
    return <section aria-label="시장 비교 후보" className="mb-5 min-w-0 space-y-3 text-base leading-relaxed [&_button]:!min-h-11 [&_summary]:!min-h-11 sm:text-sm">
        <div className="min-w-0 border-t border-[#365372] pt-4">
            <h3 className="text-base font-semibold text-gray-100">시장 비교 후보</h3>
            <p className="mt-1 text-sm text-gray-400">{contextual ? '과거의 비슷한 시장 조건을 현재 자료와 대조한 실험 모델입니다. 새 결정 이후 관측으로 검증합니다.' : '같은 거래일의 추세·상대강도와 비용 검증으로 선별했습니다. 순위는 현재 가격 구조를 비교한 값입니다.'}</p>
        </div>
        {contextual && <p className="rounded-lg border border-[#365372] bg-[#1b2c40] px-3 py-2 text-sm font-semibold text-[#acd3ff]">{available ? '실험적 조건부 매수 후보 · 전향 검증 중' : '실험 정책 · 전향 검증 중 · 신규 진입 불가'}</p>}
        <dl aria-label="후보 선별 단계" className="flex flex-wrap gap-x-5 gap-y-2 rounded-lg border border-[#30363f] bg-[#121a22] px-3 py-2 text-xs tabular-nums">
            {view.funnel.map(row => <div key={row.id} className="flex items-baseline gap-2"><dt className="text-gray-400">{funnelNames[row.id] ?? row.label}</dt><dd className="font-semibold text-gray-100">{row.count}</dd></div>)}
        </dl>
        {!available && <p role="status" className="rounded-lg border border-amber-400/25 p-3 text-sm text-amber-200">신규 진입 불가 · {view.state === 'running' ? '결과 저장 중입니다.' : view.state === 'failed' ? '갱신에 실패했습니다.' : view.state === 'held' ? '검증 또는 자료 조건이 충족되지 않았습니다.' : '유효기간 또는 자료 시점을 다시 확인해야 합니다.'}</p>}
        {view.candidates.length === 0 ? <p className="rounded-lg border border-[#30363f] p-4 text-sm text-gray-300">현재 조건을 통과한 후보가 없습니다.</p>
            : <div className="grid min-w-0 gap-3 xl:grid-cols-3">{view.candidates.map(row => {
                const entry = candidateDeskEntryView(view, row.symbol, now, blocked);
                const rowAvailable = entry.state === 'conditional' || entry.state === 'within_band';
                const label = entry.state === 'skip' ? '진입 제외 · 가격 조건 이탈' : entry.state === 'waiting' ? '시가 확인 대기'
                    : rowAvailable ? contextual ? '실험적 조건부 매수 후보' : '조건부 매수 제안' : '신규 진입 불가';
                return <article key={row.symbol}
                aria-label={`${row.rank}위 ${row.name} ${row.symbol}`} className="min-w-0 rounded-lg border border-[#3b4d5c] bg-[#121a22] p-4">
                <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0">
                    <p className="text-sm font-semibold text-[#acd3ff]">{row.rank}위</p>
                    <h4 className="mt-1 break-words text-xl font-semibold text-gray-100">{row.name}</h4>
                    <p className="mt-1 text-sm tabular-nums text-gray-400">{row.symbol} · KRX</p>
                </div><span className={`w-fit max-w-full rounded border px-2 py-1 text-sm font-semibold ${rowAvailable ? 'border-[#365372] text-[#acd3ff]' : 'border-amber-400/25 text-amber-200'}`}>{label}</span></div>
                <div className="mt-3"><p className="font-semibold text-gray-200">선정 이유</p>
                    <ul className="mt-1 list-inside list-disc space-y-1 break-words text-sm text-gray-300">{row.reason_facts.map((fact, index) => <li key={index}>{factLabel(fact)}</li>)}</ul></div>
                <dl className="mt-3 divide-y divide-[#30363f] text-sm tabular-nums">{[
                    ['기준 진입', money(row.plan.entry_price)], ['추격 상한 (+2%)', money(row.plan.entry_upper)],
                    ['참고 손절', money(row.plan.stop_price)], ['참고 목표', money(row.plan.target_price)],
                ].map(([label, value]) => <div key={label} className="flex flex-wrap items-center justify-between gap-2 py-2"><dt className="text-gray-400">{label}</dt><dd className="font-mono text-gray-100">{value}</dd></div>)}</dl>
                <p className="mt-2 text-sm tabular-nums text-gray-300">최대 {row.plan.horizon_sessions}거래일 · 연구 참고 비중 {pct(entry.reference_weight)}</p>
                {!rowAvailable && <p className="mt-1 text-xs tabular-nums text-gray-400">저장 계획 비중 {pct(row.risk.reference_weight)} · 현재 비활성</p>}
                <p className="mt-1 text-xs text-gray-400">1/4 Kelly · 종목당 상한 {contextual ? '1%' : '5%'} · 승인 노출 0 · 주문 실행 없음</p>
                {contextual && row.model_evidence && <LocalModelEvidence name={row.name} evidence={row.model_evidence} />}
                <div className="mt-3 space-y-1 border-t border-[#30363f] pt-3 text-sm tabular-nums text-gray-400">
                    {entry.state === 'within_band' && entry.quote && <><p className="text-gray-200">현재 관측 {money(entry.quote.price!)} · 시가 {money(entry.quote.opening_price!)}</p><p>시세 시각 {clock(entry.quote.quote_at!)}</p></>}
                    <p>KIS · KRX · {row.quote_session} 종가</p>
                    <p>자료 수집 {clock(view.source.captured_at)}</p>
                    <p>진입 거래일 {view.entry_session ?? '확인 대기'}</p><p>유효기한 {clock(view.valid_until)}</p>
                </div>
                <p className="mt-2 break-words text-xs text-gray-400">상한 초과·손절선 이하 시 진입하지 않습니다. 실제 시가로 가격을 다시 계산합니다. 저장 종가는 실제 체결가가 아닙니다.</p>
                {onSelectSymbol && <button type="button" onClick={() => onSelectSymbol(row.symbol)} aria-label={`${row.name} ${row.symbol} 상세 분석`}
                    className="mt-3 min-h-11 w-full rounded-lg border border-[#365372] px-3 py-2 text-base font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] sm:text-sm">종목 상세 분석</button>}
            </article>; })}</div>}
        {view.reasons.length > 0 && <div className="min-w-0 text-xs leading-relaxed text-amber-200"><h4 className="font-semibold">보류·제외 사유</h4><ul className="mt-1 space-y-1 break-words">{view.reasons.map((reason, index) => <li key={index}>{reasonNames[reason] ?? '저장된 검증 조건 또는 자료 상태를 확인하세요.'} <span className="text-gray-400">({reason})</span></li>)}</ul></div>}
        <details className="min-w-0 border-t border-[#30363f] text-sm text-gray-400"><summary className={disclosure}>{contextual ? '기존 정책 대조군 · 한계' : '과거 검증 근거 · 한계'}</summary>
            <div className="space-y-2 pb-2 text-xs leading-relaxed">
                {contextual && <p>v3의 조건 없는 과거 대조군입니다. v4의 미사용 검증 구간이나 검증된 투자 우위를 뜻하지 않습니다.</p>}
                <PhaseEvidence label={contextual ? 'v3 대조군 · 형성 구간' : '형성 구간'} phase={view.evidence.formation} />
                <PhaseEvidence label={contextual ? 'v3 대조군 · 최근 126거래일' : '확인 구간'} phase={view.evidence.confirmation} />
                <p>같은 날 선정된 종목은 시장 국면을 공유하므로 독립 시행으로 취급하지 않습니다. 표본의 과거 수익 빈도는 미래 확률로 보정되지 않았습니다.</p>
                <p>현재 품질 코호트의 과거 자료를 사용한 회고 검증입니다. 당시 종목 목록·수집 시점과 기업행사 보정은 검증되지 않았습니다. 수정주가 요청은 보정 완료 인증을 뜻하지 않습니다.</p>
                <p>코호트 중앙값은 공식 시장 벤치마크가 아닙니다. 선택 거래의 평균 수익은 계좌 손익이나 독립 시장 초과수익을 뜻하지 않습니다.</p>
                <p className="tabular-nums">결정 생성 {clock(view.generated_at)}</p>
            </div>
        </details>
    </section>;
}
