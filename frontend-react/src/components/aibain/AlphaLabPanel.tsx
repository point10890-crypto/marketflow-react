import { useEffect, useId, useRef, useState } from 'react';
import { fetchAlphaLab, startAlphaLab, type AlphaLabCandidate, type AlphaLabReport, type AlphaLabStatus } from '@/lib/alphaLabApi';

const numberPct = (value: number | null, signed = false) => value === null ? '대기' : `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const money = (value: number | null) => value === null ? '대기' : `${Math.round(value).toLocaleString('ko-KR')}원`;
const clock = (value: string) => `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST`;
const reasonLabels: Record<string, string> = {
    historical_vintage_unverified: '당시 제공되었던 가격·공시 시점 검증 대기',
    historical_price_vintage_unverified: '당시 가격 자료의 수집 시점 검증 대기',
    point_in_time_universe_unverified: '당시 종목 목록 검증 대기',
    current_cohort_bias: '현재 종목 목록의 생존 편향이 남아 있습니다.',
    current_cohort_bias_present: '현재 종목 목록의 생존 편향이 남아 있습니다.',
    forward_validation_pending: '새 결정 이후 전향 관측 성과 누적 대기',
    forward_validation_required: '새 결정 이후 전향 관측 필요',
    stress_gate_failed: '비용·하락 스트레스 검사 조건 미충족',
    validation_insufficient: '검증 표본 부족', insufficient_validation_trades: '검증 거래 표본 부족',
    no_qualified_strategy: '고정된 검증 조건을 통과한 전략 없음',
    no_validation_champion: '검증 구간에서 선택할 전략 없음',
    analysis_not_ready: '분석 자료 준비 대기', missing_prices: '가격 자료 부족', stale_prices: '최근 가격 갱신 대기',
    price_adjustment_unverified: '수정주가 여부 검증 대기', missing_index: '가격 색인 준비 대기',
    kelly_held: '모의 비중 보류', risk_held: '리스크 조건 미충족',
    trend_strength: '가격 추세 관찰',
    heldout_test_net_loss: '고정 테스트 구간의 순수익이 음수입니다.',
    heldout_cost_stress_net_loss: '고정 테스트의 비용 스트레스 구간 순수익이 음수입니다.',
    heldout_insufficient_completed_outcomes: '고정 테스트의 관측 완료 거래가 최소 30건보다 적습니다.',
    source_verification_required: '자료의 수집·보정 시점 검증 대기',
    input_refresh_failed_previous_snapshot_retained: '자료 갱신에 실패하여 이전 정상 스냅샷을 사용합니다.',
    entry_setup_inactive: '현재 진입 조건 미충족',
    recent_fixed_split_not_full_multiyear_walkforward: '최근 자료를 시간순으로 고정 분리한 실험입니다. 여러 해의 시점을 반복 이동하는 검증은 완료되지 않았습니다.',
    correlated_outcomes_not_independent_trials: '같은 시장 국면을 공유하는 결과가 서로 연관될 수 있어 독립 시행으로 인증하지 않습니다.',
    hypothetical_costs_and_liquidity_not_guaranteed: '비용과 유동성은 모의 가정입니다. 실제 체결 비용·유동성 보장을 뜻하지 않습니다.',
    diagnostic_backtest_10pct_not_approved_allocation: '진단용 백테스트의 10% 비중은 승인된 실투자 비중이 아닙니다.',
    allocation_caps_allow_subsequent_price_drift: '진입 때 비중 상한을 적용해도 이후 가격 변동으로 비중이 상한을 넘을 수 있습니다.',
    current_cohort_survivorship_bias: '현재 종목 목록을 사용하므로 생존 편향이 남아 있습니다.',
    corporate_action_adjustment_unverified: '액면분할·배당 등 기업행사의 가격 보정 여부 미확인',
    research_allocations_not_investment_approval: '연구 비중은 실투자 승인이 아닙니다.',
    research_only_cio_approval_required: '연구 근거이며 CIO의 실투자 승인이 필요합니다.',
    t_stat_below_two: '평균 순수익의 통계 진단 기준 미충족',
    no_validation_qualified_champion: '검증 조건을 통과한 선택 전략 없음',
};
const explain = (reason: string) => reasonLabels[reason] ?? reason;
const stateLabels: Record<string, string> = {
    done: '완료', ready: '준비', held: '보류', running: '진행 중', pending: '대기', missing: '자료 대기',
    failed: '실패', passed: '통과', blocked: '보류', complete: '완료', watch: '관찰', qualified: '조건 통과',
    research: '연구', collecting: '관측 누적 중',
};
const stateText = (state: string) => stateLabels[state] ?? state;
const buttonClass = 'min-h-11 rounded-lg border border-[#365372] px-3 py-2 text-xs font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] disabled:cursor-wait disabled:opacity-50';

function Candidate({ row, report, onSelectSymbol }: { row: AlphaLabCandidate; report: AlphaLabReport; onSelectSymbol?: (symbol: string) => void }) {
    const strategy = report.strategies.find(item => item.strategy_id === row.strategy_id);
    const reasons = Array.from(new Set([...row.risk.reasons, ...row.reasons]));
    return <article aria-label={`관찰 후보 ${row.name} ${row.symbol}`} className="min-w-0 rounded-lg border border-[#3b4d5c] bg-[#121a22] p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0"><h4 className="break-words text-base font-semibold">{row.name}</h4><p className="mt-1 font-mono text-xs text-gray-400">{row.symbol} · KR</p></div>
            <span className="rounded border border-[#796b4e] px-2 py-1 text-[11px] text-amber-200">관찰 후보</span>
        </div>
        <p className="mt-3 break-words text-xs text-gray-300">{strategy?.name ?? row.strategy_id} · 점수 {row.score.toFixed(3)}</p>
        <p className="mt-1 text-[11px] text-gray-400">점수는 전략 내 상대 평가이며 상승 확률이 아닙니다.</p>
        <dl className="mt-3 divide-y divide-[#30363f] text-xs tabular-nums">
            {[
                ['기준 종가', money(row.last_close)], ['모의 진입', money(row.plan?.entry_price ?? null)],
                ['모의 손절', money(row.plan?.stop_price ?? null)], ['모의 목표', money(row.plan?.target_price ?? null)],
                ['계획 손실폭', numberPct(row.plan?.loss_fraction ?? null)],
            ].map(([label, value]) => <div key={label} className="flex flex-wrap items-center justify-between gap-2 py-2"><dt className="text-gray-400">{label}</dt><dd className="font-mono text-gray-100">{value}</dd></div>)}
        </dl>
        <div className="mt-3 border-y border-[#497368] py-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-gray-300">모의 비중</span><strong className="font-mono text-lg tabular-nums text-teal-200">{numberPct(row.risk.weight)}</strong></div>
            <p className="mt-1 text-[11px] text-gray-400">하프 켈리 · 종목 한도 20% · {stateText(row.risk.status)}</p>
            <p className="mt-1 text-[11px] tabular-nums text-gray-400">검증 상승 빈도 {numberPct(row.risk.p)} · 원 켈리 {numberPct(row.risk.kelly_raw)}</p>
        </div>
        {reasons.length > 0 && <ul className="mt-3 space-y-1 break-words text-[11px] leading-relaxed text-gray-400">{reasons.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul>}
        {onSelectSymbol ? <button type="button" onClick={() => onSelectSymbol(row.symbol)} className={`${buttonClass} mt-4 w-full`}>종목 상세 · 차트 사례</button>
            : <a href={`/dashboard/ai-bain/chart-predict?code=${row.symbol}`} className={`${buttonClass} mt-4 flex items-center justify-center`}>종목 상세 · 차트 사례</a>}
    </article>;
}

function Evidence({ report, previous, onSelectSymbol }: { report: AlphaLabReport; previous: boolean; onSelectSymbol?: (symbol: string) => void }) {
    const champion = report.strategies.find(row => row.strategy_id === report.champion.strategy_id);
    const provenance = report.provenance;
    const forward = report.forward;
    const exposure = report.candidates.reduce((sum, row) => sum + row.risk.weight, 0);
    return <div className="space-y-4">
        {previous && <p className="rounded-lg border border-amber-400/20 p-3 text-xs leading-relaxed text-amber-200">이전 검증 결과입니다. 새 실험이 완료될 때까지 아래 자료의 분석 기준 시각을 확인해 주세요.</p>}
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-[#30363f] py-3 text-xs sm:grid-cols-4">
            {[
                ['검사 종목', `${report.universe.inspected_count} / ${report.universe.quality_count}`],
                ['종목 목록 기준', report.universe.scope_date ?? '미확인'],
                ['모의 노출', numberPct(exposure)], ['분석 기준', clock(report.as_of)],
            ].map(([label, value]) => <div key={label} className="min-w-0"><p className="text-[11px] text-gray-400">{label}</p><p className="mt-1 break-words font-mono text-xs tabular-nums text-gray-100">{value}</p></div>)}
        </div>
        <div className="rounded-lg border border-amber-400/25 bg-[#242119] p-3 text-xs leading-relaxed text-amber-100">
            <p className="font-semibold">연구·모의 분석 · 실투자 승인 없음</p>
            <p className="mt-1">검증 구간에서 선택한 전략: {champion?.name ?? '선택 보류'} · {stateText(report.champion.status)}. 진입·손절·목표는 가격 자료로 계산한 모의 계획입니다.</p>
            {report.champion.reasons.length > 0 && <ul className="mt-2 space-y-1 break-words text-[11px] text-amber-200/90">{report.champion.reasons.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul>}
        </div>
        <div><h3 className="ai-section-title text-sm">전략 대결 · 검증에서 선택, 고정 구간에서 평가</h3>
            <p className="mb-3 mt-1 text-[11px] leading-relaxed text-gray-400">테스트와 스트레스 결과를 보고 우승 전략을 바꾸지 않습니다. 수익률과 낙폭은 비용을 반영한 모의 관측치입니다.</p>
            <div className="max-w-full overflow-x-auto rounded-lg border border-[#30363f]" tabIndex={0} aria-label="전략 비교 표 가로 스크롤">
                <table aria-label="전략 검증 비교" className="w-full min-w-[730px] text-right text-[11px] tabular-nums">
                    <thead className="bg-[#161d26] text-gray-400"><tr><th scope="col" className="px-3 py-3 text-left">전략</th><th scope="col" className="px-2">검증 거래</th><th scope="col" className="px-2">검증 상승 빈도</th><th scope="col" className="px-2">검증 평균 순수익</th><th scope="col" className="px-2">테스트 순수익 / 낙폭</th><th scope="col" className="px-2">스트레스 순수익 / 낙폭</th><th scope="col" className="px-3">조건</th></tr></thead>
                    <tbody>{report.strategies.map(row => <tr key={row.strategy_id} className="border-t border-[#30363f]">
                        <th scope="row" className="px-3 py-3 text-left font-medium"><span>{row.name}</span>{row.strategy_id === report.champion.strategy_id && <span className="mt-1 block text-[10px] text-[#acd3ff]">검증 구간 선택</span>}</th>
                        <td className="px-2">{row.validation.trades}</td><td className="px-2">{numberPct(row.validation.win_rate)}</td><td className="px-2">{numberPct(row.validation.mean_net_return, true)}</td>
                        <td className="px-2">{numberPct(row.test.net_total_return, true)} / {numberPct(row.test.max_drawdown)}<span className="mt-1 block text-[10px] text-gray-400">{row.test.trades}거래</span></td>
                        <td className="px-2">{numberPct(row.stress.net_total_return, true)} / {numberPct(row.stress.max_drawdown)}<span className="mt-1 block text-[10px] text-gray-400">{row.stress.trades}거래</span></td>
                        <td className={`px-3 ${row.qualified ? 'text-teal-200' : 'text-amber-200'}`}>{row.qualified ? '모의 조건 통과' : '보류'}</td>
                    </tr>)}</tbody>
                </table>
            </div>
            {report.strategies.some(row => row.reasons.length > 0) && <details className="mt-2 text-[11px] text-gray-400"><summary className="cursor-pointer py-2 text-[#acd3ff]">전략별 보류·검증 사유</summary><ul className="mt-1 space-y-2 break-words">{report.strategies.filter(row => row.reasons.length > 0).map(row => <li key={row.strategy_id}><strong className="text-gray-200">{row.name}</strong> · {row.reasons.map(explain).join(' · ')}</li>)}</ul></details>}
        </div>
        <div><h3 className="ai-section-title mb-3 text-sm">현재 관찰 후보 · 종목 → 가격 계획 → 모의 비중</h3>
            {report.candidates.length > 0 ? <div className="grid min-w-0 gap-3 lg:grid-cols-3">{report.candidates.map(row => <Candidate key={row.symbol} row={row} report={report} onSelectSymbol={onSelectSymbol} />)}</div>
                : <p className="rounded-lg border border-[#30363f] p-4 text-xs text-gray-400">표시할 관찰 후보가 없습니다. 자료 상태와 전략별 보류 사유를 확인해 주세요.</p>}
        </div>
        <div><h3 className="ai-section-title mb-2 text-sm">에이전트 검출 상태</h3><ul aria-label="에이전트 진행 상태" className="grid gap-x-5 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">{report.agents.map(agent => <li key={agent.id} className="min-w-0 border-t border-[#30363f] py-2"><div className="flex flex-wrap items-center justify-between gap-2 text-xs"><span className="font-medium text-gray-200">{agent.name}</span><span className={['failed', 'held', 'blocked'].includes(agent.status) ? 'text-amber-200' : 'text-[#acd3ff]'}>{stateText(agent.status)}</span></div><p className="mt-1 break-words text-[11px] leading-relaxed text-gray-400">{agent.detail}</p></li>)}</ul></div>
        <div className="rounded-lg border border-[#303f4b] p-3 text-xs leading-relaxed text-gray-400"><h3 className="font-semibold text-gray-200">전향 모의성과 · {forward.matured === 0 ? '전향 관측 대기' : '결과 누적 중'}</h3><p className="mt-2 tabular-nums">고정 결정 {forward.decisions}건 · 관측 완료 {forward.matured}건 · 상승 빈도 {numberPct(forward.win_rate)} · 평균 순수익 {numberPct(forward.mean_net_return, true)}</p><p className="mt-1 text-[11px]">새 결정 이후 결과가 쌓여야 성과를 읽을 수 있습니다. 과거 전략 비교와 전향 관측은 별도 근거입니다.</p></div>
        <details className="border-t border-[#30363f] pt-3 text-[11px] leading-relaxed text-gray-400"><summary className="cursor-pointer py-1 text-xs font-semibold text-[#acd3ff]">자료 시점 · 고정 실험 기준 · 출처</summary><div className="mt-3 space-y-2">
            <p>훈련 종료 {report.protocol.train_end} · 검증 종료 {report.protocol.validation_end} · 고정 테스트 시작 {report.protocol.test_start} · 보유 기준 {report.protocol.horizon_sessions}거래일</p>
            <p>가격 기준 {provenance.price_basis === 'provider_adjusted' ? '공급자 수정주가' : provenance.price_basis} · 수정 여부 {provenance.price_adjustment_verified ? '확인' : '미확인'} · 분석 자료 {provenance.analysis_ready ? '준비' : '대기'}</p>
            <p>당시 자료 수집 시점 {provenance.historical_vintage_verified ? '확인' : '미확인'} · 당시 종목 목록 {provenance.point_in_time_universe_verified ? '확인' : '미확인'} · 현재 종목 목록 편향 {provenance.current_cohort_bias ? '남아 있음' : '없음'}</p>
            <p>모의 비중은 검증 근거와 리스크 조건을 통과한 범위에서만 표시합니다. 수치가 없으면 대기로 남기며 상승 확률이나 승인된 계좌 비중으로 사용하지 않습니다.</p>
            {report.warnings.length > 0 && <ul className="space-y-1 break-words">{report.warnings.map(reason => <li key={reason}>{explain(reason)}</li>)}</ul>}
            {report.protocol.source_references.length > 0 && <ul className="space-y-1">{report.protocol.source_references.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-9 items-center break-words text-[#acd3ff] underline underline-offset-4">{source.name}</a></li>)}</ul>}
        </div></details>
    </div>;
}

export default function AlphaLabPanel({ token, onSelectSymbol }: { token?: string; onSelectSymbol?: (symbol: string) => void }) {
    const heading = useId();
    const generation = useRef(0);
    const mounted = useRef(false);
    const previousToken = useRef(token);
    const [snapshot, setSnapshot] = useState<AlphaLabStatus | null>(null);
    const [reading, setReading] = useState(true);
    const [posting, setPosting] = useState(false);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const accept = (next: AlphaLabStatus) => setSnapshot(old => ({ ...next,
        report: next.report ?? (['running', 'failed'].includes(next.state) ? old?.report ?? null : null),
    }));
    useEffect(() => {
        mounted.current = true;
        let active = true;
        const current = ++generation.current;
        if (previousToken.current !== token) { previousToken.current = token; setSnapshot(null); }
        setReading(true); setPosting(false); setError('');
        fetchAlphaLab(token).then(next => { if (active && current === generation.current) accept(next); })
            .catch(() => { if (active && current === generation.current) setError('저장된 전략 실험 결과를 불러오지 못했습니다. 다시 조회해 주세요.'); })
            .finally(() => { if (active && current === generation.current) setReading(false); });
        return () => { active = false; mounted.current = false; ++generation.current; };
    }, [token, revision]);
    const state = snapshot?.state;
    useEffect(() => {
        if (state !== 'running' || reading || posting) return;
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            const current = ++generation.current;
            try {
                const next = await fetchAlphaLab(token);
                if (!active || current !== generation.current) return;
                accept(next);
                if (next.state === 'running') timer = setTimeout(poll, 4000);
            } catch {
                if (active && current === generation.current) setError('실험 진행 상태를 확인하지 못했습니다. 저장 결과를 다시 확인해 주세요.');
            }
        };
        timer = setTimeout(poll, 4000);
        return () => { active = false; clearTimeout(timer); };
    }, [state, token, revision, reading, posting]);
    const start = async () => {
        if (reading || posting || state === 'running') return;
        const current = ++generation.current;
        setPosting(true); setError('');
        try { const next = await startAlphaLab(token); if (mounted.current && current === generation.current) accept(next); }
        catch { if (mounted.current && current === generation.current) setError('전략 실험을 시작하지 못했습니다. 저장 결과를 확인하고 다시 실행해 주세요.'); }
        finally { if (mounted.current && current === generation.current) setPosting(false); }
    };
    const problem = error || (state === 'failed' ? '전략 실험을 완료하지 못했습니다. 이전 결과를 보존했습니다. 자료 상태를 확인하고 다시 실행해 주세요.' : '');
    return <section aria-labelledby={heading} className="ai-panel min-w-0 border border-[#30363f] p-4 text-white sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 id={heading} className="ai-section-title text-lg">전략 실험실 · 에이전트 검출</h2><p className="mt-2 max-w-2xl text-xs leading-relaxed text-gray-400">추세·유동성·되돌림·통계 전략을 같은 조건에서 비교하고, 검증 근거로 관찰 종목과 모의 가격 계획을 연결합니다.</p></div><span className="rounded border border-[#365372] bg-[#1b2c40] px-2 py-1 text-[11px] font-semibold text-[#acd3ff]">RESEARCH · 모의 전용</span></div>
        <div className="my-4 flex flex-wrap gap-2"><button type="button" onClick={start} disabled={reading || posting || state === 'running'} className={`${buttonClass} bg-[#1b2c40]`}>전략 실험 실행</button><button type="button" onClick={() => setRevision(value => value + 1)} disabled={reading || posting} className={buttonClass}>저장 결과 새로고침</button></div>
        {reading && <p role="status" className="min-h-16 py-4 text-xs text-gray-400">저장된 전략 실험 결과 확인 중…</p>}
        {!reading && (posting || state === 'running') && <p role="status" className="mb-4 rounded-lg border border-[#365372] bg-[#1b2c40] p-3 text-xs text-[#acd3ff]">전략 실험 진행 중 · 완료된 저장 결과를 자동 확인합니다.</p>}
        {problem && <p role="alert" className="mb-4 rounded-lg border border-amber-400/25 p-3 text-xs leading-relaxed text-amber-200">{problem}</p>}
        {!reading && !snapshot?.report && !problem && state !== 'running' && !posting && <p className="py-4 text-xs leading-relaxed text-gray-400">저장된 전략 실험 결과가 없습니다. 실행 버튼으로 고정된 모의 검사를 시작해 주세요.</p>}
        {snapshot?.report && <Evidence report={snapshot.report} previous={state === 'running' || state === 'failed' || !!error} onSelectSymbol={onSelectSymbol} />}
    </section>;
}
