import { effectiveOpportunityEngine, opportunityActionLabels, type LeadershipObservation, type OpportunityEngine, type OpportunityStrategy } from '@/lib/opportunityEngine';

const money = (value: number | null) => value === null ? '관측 대기' : `${Math.round(value).toLocaleString('ko-KR')}원`;
const pct = (value: number, signed = false) => `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const clock = (value: string | null) => value ? `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST` : '미확인';
const names: Record<OpportunityStrategy, string> = { momentum: '추세 지속', liquidity_breakout: '거래량 동반 돌파', mean_reversion: '과매도 회복' };
const stageNames: Record<string, string> = { data: '자료', setup: '가격 조건', critic: '반대 근거', diversification: '분산', risk: '비중', entry: '진입 시점' };
const stateNames = { passed: '통과', held: '보류', unavailable: '자료 부족' };
const disclosure = 'min-h-11 cursor-pointer rounded py-3 text-base font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] sm:text-sm';
const reasons: Record<string, string> = { correlation_unavailable: '종목 간 가격 연관성을 확인하지 못해 불확실성 차감 적용',
    window_expired: '최초 진입 유효기간 종료', source_stale: '입력 자료 갱신 대기', quote_stale: '가격 관측 갱신 대기',
    calendar_unavailable: '공식 거래일 확인 대기', identity_mismatch: '연구 결정과 관측 자료 식별자 확인 대기' };
const explanation = (codes: string[]) => Array.from(new Set(codes.map(code => reasons[code] ?? '저장 근거의 제한 사항을 확인해야 합니다.'))).join(' · ');
const observedReturn = (value: number | null) => value === null ? '확인 대기' : pct(value, true);
const checkNames = { top3: '코호트 상위 3위', fresh: '1개월 +10~40%', trend: '상승 추세', near_high: '52주 고가 75% 이상' } as const;
const breadthNames = { broad: '상승 확산', mixed: '혼재', weak: '상승 범위 제한', unknown: '확인 자료 부족' } as const;
function LeadershipDetails({ row, waiting }: { row: LeadershipObservation; waiting: boolean }) {
    return <div aria-label={`${row.name} 저장 가격 조건`} className="mt-3 space-y-2 border-t border-[#30363f] pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
            <span className="rounded border border-[#365372] px-2 py-1 font-semibold tabular-nums text-[#acd3ff]">가격 조건 {row.points}/{row.available_checks}</span>
            <span className="text-gray-400">{waiting ? '저장 관측 · 갱신 대기' : '저장 가격 관측'}</span>
        </div>
        <ul className="flex flex-wrap gap-1.5 text-[11px]">{(Object.keys(checkNames) as Array<keyof typeof checkNames>).map(key => <li key={key}
            className={`rounded border px-1.5 py-1 ${!waiting && row.checks[key] === true ? 'border-[#365372] text-[#acd3ff]' : 'border-[#30363f] text-gray-400'}`}>
            {checkNames[key]} · {row.checks[key] === null ? '대기' : row.checks[key] ? '통과' : '미충족'}
        </li>)}</ul>
        <p className="text-[11px] leading-relaxed tabular-nums text-gray-400">3개월 {observedReturn(row.ret_63)} · 52주 고가 대비 {observedReturn(row.from_high_252)}</p>
    </div>;
}

export default function OpportunityBoard({ board, now, blocked = false, onSelectSymbol }: {
    board: OpportunityEngine; now: number; blocked?: boolean; onSelectSymbol?: (symbol: string) => void;
}) {
    const view = effectiveOpportunityEngine(board, now, blocked);
    const weight = view.candidates.reduce((sum, row) => sum + row.reference_weight, 0);
    const leadership = view.leadership_context;
    const leadershipWaiting = blocked || view.status !== 'ready' || !view.candidates.some(row => row.action === 'entry_candidate');
    return <section aria-label="수익 기회 순위" className="mb-5 min-w-0 space-y-3 text-base leading-relaxed [&_button]:!min-h-11 [&_summary]:!min-h-11 sm:text-sm">
        <div className="flex flex-wrap items-start justify-between gap-3 border-y border-[#365372] py-3">
            <div className="min-w-0"><h3 className="text-base font-semibold text-gray-100">수익 기회 순위</h3>
                <p className="mt-1 leading-relaxed text-gray-300">종목 · 현재 조건 · 다음 행동 순서로 확인하세요.</p></div>
            <div className="text-sm leading-relaxed tabular-nums text-gray-400">검사 {view.coverage.inspected} · 근거 통과 {view.coverage.eligible} · 선택 {view.coverage.selected}<br />참고 총비중 {pct(weight)} / 상한 15%</div>
        </div>
        <p className="break-words text-sm leading-relaxed text-gray-400">과거 자료로 탐색한 새 순위 정책입니다. 독립 검증과 미래 수익 확률은 인증되지 않았습니다. 진입·체결·계좌 성과를 뜻하지 않습니다.</p>
        {blocked && <p className="text-xs text-amber-200">결과를 확인 중이거나 갱신에 실패하여 현재 진입 안내를 보류합니다.</p>}
        {leadership && <div role="status" aria-label="저장 가격 분포" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#30363f] bg-[#121a22] px-3 py-2.5 text-xs">
            <p className="font-medium text-gray-200">{leadership.market.state === 'unknown' ? '확인 자료 부족' : leadershipWaiting ? '저장 관측 · 갱신 대기' : `저장 코호트 · ${breadthNames[leadership.market.state]}`}</p>
            <p className="tabular-nums text-gray-400">{leadership.latest_session} 종가 · 품질 코호트 200일선 위 {leadership.cohort.above_ma200}/{leadership.cohort.valid}종목
                {leadership.market.ratio !== null && ` (${pct(leadership.market.ratio)})`}</p>
        </div>}
        {view.candidates.length === 0 ? <p className="rounded-lg border border-[#30363f] p-4 text-xs text-gray-300">현재 선택된 기회 후보가 없습니다. 다음 저장 연구와 자료 상태를 확인하세요.</p>
            : <div className="grid min-w-0 gap-3 lg:grid-cols-3">{view.candidates.map(row => <article key={row.opportunity_id}
                aria-label={`${row.rank}위 ${row.name} ${row.symbol}`} className="min-w-0 rounded-lg border border-[#3b4d5c] bg-[#121a22] p-4">
                <div className="space-y-2"><div className="min-w-0"><span className="text-sm font-semibold text-[#acd3ff]">{row.rank}위</span>
                    <h4 className="mt-1 break-words text-xl font-semibold text-gray-100">{row.name}</h4><p className="mt-1 text-sm tabular-nums text-gray-400">{row.symbol} · KR · {names[row.strategy_id]}</p></div>
                    <p className={`w-fit max-w-full rounded border px-2 py-1 font-semibold ${row.action === 'entry_candidate' ? 'border-[#365372] text-[#acd3ff]' : 'border-amber-400/25 text-amber-200'}`}>{opportunityActionLabels[row.action]}</p></div>
                <dl className="mt-4 divide-y divide-[#30363f] tabular-nums">{[
                    ['참고 진입 범위', `${money(row.plan.entry_low)} ~ ${money(row.plan.entry_high)}`],
                    ['참고 손절', money(row.plan.stop_price)], ['참고 목표', money(row.plan.target_price)],
                ].map(([label, value]) => <div key={label} className="flex flex-wrap items-center justify-between gap-2 py-2"><dt className="text-gray-400">{label}</dt><dd className="font-mono text-gray-100">{value}</dd></div>)}</dl>
                <p className="mt-2 text-sm leading-relaxed tabular-nums text-gray-400">현재 관측 가격 {money(row.current_price)} · 참고 비중 {pct(row.reference_weight)}</p>
                <dl className="mt-3 space-y-3 border-t border-[#30363f] pt-3 leading-relaxed">{[
                    ['다음 행동', row.next_action], ['현재 판단', row.why_now],
                ].map(([label, value]) => <div key={label}><dt className="font-semibold text-gray-200">{label}</dt><dd className="mt-1 break-words text-gray-300">{value}</dd></div>)}</dl>
                <div className="mt-3 border-t border-[#30363f] pt-3"><p className="font-semibold text-gray-200">무효 조건</p><p className="mt-1 tabular-nums text-gray-300">손절 {money(row.plan.stop_price)} 이하 · 진입 상한 {money(row.plan.entry_high)} 초과 · 목표 도달 시 신규 진입 보류</p></div>
                <p className="mt-3 leading-relaxed tabular-nums text-gray-300">진입 거래일 {view.entry_session ?? '공식 달력 확인 대기'}<br />최초 유효기한 {clock(row.valid_until)}</p>
                {onSelectSymbol && <button type="button" onClick={() => onSelectSymbol(row.symbol)} aria-label={`${row.name} 상세 분석`}
                    className="mt-3 min-h-11 w-full rounded-lg border border-[#365372] px-3 py-2 text-base font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] sm:text-sm">종목 상세 분석</button>}
                <details className="mt-3 border-t border-[#30363f] pt-1"><summary className={disclosure}>순위 계산 · 출처 확인</summary><div className="space-y-2 text-sm leading-relaxed text-gray-400">
                    <p><span className="font-semibold text-gray-200">이 종목인 이유</span><br />{row.why_stock}</p>
                    <p>{row.plan.basis === 'observed_quote_reference' ? '저장된 현재 가격 관측 기준' : '최근 종가 기준'} · 최대 {row.plan.horizon_sessions}거래일 · 1/4 Kelly 참고 · 종목 상한 5% · 계좌 계획 손실 상한 1%</p>
                    {leadership?.selected.find(observation => observation.symbol === row.symbol) && <LeadershipDetails row={leadership.selected.find(observation => observation.symbol === row.symbol)!} waiting={leadershipWaiting || row.action !== 'entry_candidate'} />}
                    <p className="tabular-nums">관측 {clock(row.quote_at)} · 저장 {clock(row.fetched_at)}</p>
                    <p className="tabular-nums">비용 2배 과거 평균 {pct(row.ranking.stress_mean_net_return, true)} · 표준오차 {pct(row.ranking.standard_error)}<br />불확실성 차감 점수 {pct(row.ranking.conservative_score, true)} · 상관 차감 {pct(row.ranking.correlation_penalty)} · 최종 {pct(row.ranking.score, true)}</p>
                    <p>표준오차의 1.96배를 뺀 순위용 점수입니다. 독립 표본의 신뢰구간이나 미래 승률로 해석하지 않습니다.</p>
                    <p className="tabular-nums">형성 {row.ranking.calibration_samples}건 · 확인 {row.ranking.confirmation_samples}건 · 최근 입력 거래일 {row.quote_session}</p>
                    <p className="break-words">입력 가격: 저장 공급자 종가 스냅샷 · 수집 {clock(row.source_at)}<br />현재 관측: {row.quote_source ? 'KIS 국내 주식 가격 API' : '조회 근거 확인 대기'}</p>
                    <p>자료 감사 {stateNames[row.audit.status]} · 독립 검증 미인증</p>
                    {row.reasons.length + row.audit.reasons.length > 0 && <p>{explanation([...row.reasons, ...row.audit.reasons])}</p>}
                    <p className="break-all font-mono">결정 {row.decision_id}<br />입력 {row.input_fingerprint}<br />출처 감사 {row.source_audit_hash}</p>
                </div></details>
            </article>)}</div>}
        {leadership && leadership.watchlist.length > 0 && <section aria-label="추가 추세 연구" className="space-y-2 border-t border-[#30363f] pt-3">
            <div className="flex flex-wrap items-end justify-between gap-2"><h4 className="text-sm font-semibold text-gray-200">추가 추세 연구 후보 · {leadership.watchlist.length}종목</h4>
                <p className="text-[11px] text-gray-400">{leadership.latest_session} 저장 종가 기준{leadershipWaiting ? ' · 갱신 대기' : ''}</p></div>
            <p className="text-[11px] leading-relaxed text-gray-400">현재 품질 코호트의 상승 추세 관측입니다. 기존 비용·위험 연구 정책의 TOP3와 별도로 비교하세요.</p>
            <div className="min-w-0 rounded border border-[#30363f]">
                <table aria-label="추가 추세 연구 후보" className="block !w-full !min-w-0 text-right !text-base tabular-nums [&_td]:!whitespace-normal [&_th]:!whitespace-normal md:table md:!text-sm">
                    <thead className="hidden bg-[#151d26] text-gray-400 md:table-header-group"><tr><th scope="col" className="px-3 py-2 text-left">상승 추세 내 순위 · 종목</th>
                        <th scope="col" className="px-3 py-2">최근 3개월</th><th scope="col" className="px-3 py-2">52주 고가 대비</th>
                        <th scope="col" className="px-3 py-2">참고 종가</th><th scope="col" className="px-3 py-2">가격 조건</th></tr></thead>
                    <tbody className="block md:table-row-group">{leadership.watchlist.map(row => <tr key={row.symbol} className="grid min-w-0 grid-cols-2 border-t border-[#30363f] pb-3 md:table-row md:pb-0">
                        <th scope="row" className="col-span-2 min-w-0 px-3 py-1 text-left font-normal"><span className="mr-2 text-gray-400">{row.rank ?? '—'}</span>
                            {onSelectSymbol ? <button type="button" onClick={() => onSelectSymbol(row.symbol)} aria-label={`${row.name} 상세 분석`}
                                className="min-h-11 max-w-full break-words rounded px-1 text-left text-xl font-medium text-[#acd3ff] underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] md:text-sm">{row.name}</button>
                                : <span className="break-words text-xl font-medium text-gray-200 md:text-sm">{row.name}</span>}<span className="ml-2 text-sm text-gray-400">{row.symbol}</span></th>
                        <td className="min-w-0 px-3 py-2 text-left text-gray-200 md:text-right"><span className="mb-1 block text-sm text-gray-400 md:hidden" aria-hidden="true">최근 3개월</span>{observedReturn(row.ret_63)}</td><td className="min-w-0 px-3 py-2 text-left text-gray-300 md:text-right"><span className="mb-1 block text-sm text-gray-400 md:hidden" aria-hidden="true">52주 고가 대비</span>{observedReturn(row.from_high_252)}</td>
                        <td className="min-w-0 px-3 py-2 text-left text-gray-200 md:text-right"><span className="mb-1 block text-sm text-gray-400 md:hidden" aria-hidden="true">참고 종가</span><span className="font-mono">{money(row.reference_price)}</span></td><td className="min-w-0 px-3 py-2 text-left text-gray-300 md:text-right"><span className="mb-1 block text-sm text-gray-400 md:hidden" aria-hidden="true">가격 조건</span>{row.points}/{row.available_checks}</td>
                    </tr>)}</tbody>
                </table>
            </div>
        </section>}
        {leadership && <details className="border-t border-[#30363f] pt-1"><summary className={disclosure}>가격 조건 · 추세 관측 기준</summary>
            <div className="space-y-2 text-[11px] leading-relaxed text-gray-400"><p>품질 코호트 안에서 상승 추세 품질·52주 고가 근접도·3개월 수익을 고정 규칙으로 비교한 관측 순위입니다. 학습된 위원회 점수나 미래 수익 확률이 아닙니다.</p>
                <p>가격 조건은 코호트 상위 3위, 1개월 +10~40%, 종가 &gt; 50 &gt; 150 &gt; 200일선과 200일선 상승, 52주 고가의 75% 이상입니다. 확인하지 못한 조건은 대기로 남깁니다.</p>
                <p>TOP3에는 과매도 회복 연구 후보도 포함될 수 있습니다. 네 가지 가격 조건은 추세 주도 관측을 설명하며, 모든 전략에 적용되는 수익 확신 점수가 아닙니다.</p>
                <p>200일선 위 종목 비율은 저장된 품질 코호트의 가격 분포입니다. KOSPI 지수나 전체 시장 날씨를 뜻하지 않으며, 기존 진입 조건과 Kelly 비중을 바꾸지 않습니다.</p>
            </div>
        </details>}
        <details className="border-t border-[#30363f] pt-1"><summary className={disclosure}>검사 단계 · 대안 · 관측 기록</summary><div className="space-y-3 text-[11px] leading-relaxed text-gray-400">
            <ul className="grid gap-x-5 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">{view.stages.map(stage => <li key={stage.id} className="min-w-0"><strong className="text-gray-200">{stageNames[stage.id]} · {stateNames[stage.status]} · {stage.count}건</strong><p className="mt-1 break-words">{stage.detail}</p></li>)}</ul>
            {view.reasons.length > 0 && <p>{explanation(view.reasons)}</p>}
            {view.alternatives.length > 0 && <><p className="font-semibold text-gray-200">연구 대안 · 진입 안내 아님</p><ul className="space-y-1">{view.alternatives.map(row => <li key={row.symbol} className="break-words">{row.name} {row.symbol} · {names[row.strategy_id]} · {row.score === null ? '미산출' : `순위 점수 ${pct(row.score, true)}`} · {explanation([row.reason])}</li>)}</ul></>}
            {view.evaluation && <div><p className="font-semibold text-gray-200">발행 기회 기록 · 체결 기준 아님</p><p className="mt-1 tabular-nums">발행 {view.evaluation.issued} · 대기 {view.evaluation.pending} · 기간 종료 {view.evaluation.expired} · 관측 {view.evaluation.observed} · 미관측 {view.evaluation.unobserved}</p><p className="mt-1">실제 진입 근거 없이 성공률·수익률을 계산하지 않습니다. 미관측은 미체결을 뜻하지 않습니다.</p></div>}
            <p className="tabular-nums">순위 생성 {clock(view.generated_at)} · 최초 유효기한 {clock(view.valid_until)}</p>
        </div></details>
    </section>;
}
