import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import ChartAnalogueSymbolSearch from '@/components/aibain/ChartAnalogueSymbolSearch';
import { effectiveAdminStockProposal, fetchAdminStockAnalysis, searchAdminStockCandidates, startAdminStockAnalysis,
    type AdminDiagnosticPhase, type AdminStockAnalysisStatus } from '@/lib/adminStockAnalysisApi';

const button = 'min-h-11 rounded-lg border border-[#365372] px-3 py-2 text-sm font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] disabled:cursor-wait disabled:opacity-50';
const money = (value: number | null | undefined) => value == null ? '계산 대기' : `${Math.round(value).toLocaleString('ko-KR')}원`;
const percent = (value: number | null | undefined) => value == null ? '관측 대기' : `${(value * 100).toFixed(1)}%`;
const time = (value: string | null) => value ? `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST` : '확인 대기';
const strategyNames: Record<string, string> = { reference_only: '참고 가격 계산', momentum: '추세 지속', liquidity_breakout: '거래량 동반 돌파',
    mean_reversion: '과매도 회복', opportunity_mean_reversion: '과매도 회복', opportunity_liquidity_breakout: '거래량 동반 돌파', opportunity_momentum: '추세 지속' };
const reasonNames: Record<string, string> = {
    quality_not_passed: '재무 품질 조건 미충족', quality_unavailable: '재무 품질 자료 확인 대기', quality_blocked: '재무 품질 조건으로 매수 보류',
    financial_quality_blocked: '재무 품질 조건으로 매수 보류', outside_quality_cohort: '재무 우량 목록 밖의 종목',
    insufficient_union_history: '고정 탐색에 필요한 가격 이력 부족', insufficient_history: '가격 이력 부족', insufficient_samples: '완료 거래 표본 부족',
    entry_setup_inactive: '현재 진입 조건 미충족', no_eligible_strategy: '검증 조건을 통과한 전략 없음', no_qualified_strategy: '검증 조건을 통과한 전략 없음',
    missing_prices: '가격 자료 없음', stale_prices: '최근 가격 갱신 대기', source_stale: '입력 자료 갱신 대기',
    missing_current_quote: '입력 거래일 가격 없음', source_verification_required: '자료의 수집·보정 시점 검증 대기',
    calendar_unavailable: '공식 거래일 달력 확인 대기', calendar_stale: '공식 거래일 달력 갱신 대기', window_expired: '신규 진입 제안 기간 종료',
    price_adjustment_unverified: '수정주가 여부 미확인', historical_vintage_unverified: '당시 제공된 자료 시점 미확인',
    point_in_time_universe_unverified: '당시 종목 목록 미확인', current_quality_cohort_survivorship_bias: '현재 우량 종목 목록의 생존 편향이 남아 있습니다.',
    source_vintage_and_corporate_action_adjustment_not_certified: '당시 자료 시점·기업행사 가격 보정 미인증',
    research_weights_not_order_approval: '제안 비중은 직접 판단용이며 주문 권한이 없습니다.',
    new_retrospective_policy_not_untouched_validation: '과거 자료를 탐색한 정책이며 독립 검증 성과가 아닙니다.',
    multiple_symbol_and_setup_screening: '여러 종목과 조건을 탐색한 선택 효과가 남아 있습니다.',
    stronger_statistical_evidence_not_met: '엄격한 통계 진단 조건 미충족', source_refresh_failed: '자료 갱신 실패',
    targeted_collection_failed: '선택 종목 자료 수집 실패', saved_snapshot_used: '저장된 가격 스냅샷 사용',
    setup_inactive: '현재 진입 조건 미충족', no_positive_current_setup_evidence: '현재 조건에서 양의 순손익 근거를 확인하지 못했습니다.',
    insufficient_completed_outcomes: '검증을 완료한 거래 표본 부족', both_return_signs_required: '상승·하락 거래를 함께 비교할 표본이 부족합니다.',
    nonpositive_mean_net_return: '과거 조건일 평균 순손익이 양수가 아닙니다.',
    nonpositive_stress_mean_net_return: '비용을 2배로 적용한 평균 순손익이 양수가 아닙니다.',
    nonpositive_compounded_trade_return: '과거 거래 합성 수익이 양수가 아닙니다.',
    nonpositive_stress_compounded_trade_return: '비용을 2배로 적용한 거래 합성 수익이 양수가 아닙니다.',
    manual_exploratory_research_only: '직접 판단용 탐색적 연구 제안입니다.', source_and_cio_approval_required: '자료 인증과 CIO 실투자 승인을 확인해야 합니다.',
    corporate_action_adjustment_unverified: '액면분할·배당 등 기업행사 가격 보정 여부 미확인',
    current_cohort_survivorship_bias: '현재 종목 목록을 사용하므로 생존 편향이 남아 있습니다.',
    administrator_selected_cohort_retrospective: '관리자가 선택한 종목을 과거 자료로 검토한 결과이며 독립 검증 성과가 아닙니다.',
    official_calendar_unavailable: '공식 거래일 달력 확인 대기', historical_calendar_unverified: '과거 거래일 달력 검증 대기',
    financial_quality_unavailable: '재무 품질 자료 확인 대기', price_capture_before_session_close: '장 종료 전에 수집된 가격이므로 종가 확정 확인이 필요합니다.',
};
const reason = (value: string) => reasonNames[value] ?? '추가 자료 확인이 필요합니다.';
function Diagnostic({ label, phase }: { label: string; phase: AdminDiagnosticPhase | null }) {
    return <p className="break-words text-xs leading-relaxed tabular-nums text-gray-400">{label} · {phase
        ? `${phase.samples}건 / 평균 순손익 ${percent(phase.mean_net_return)} / 비용 2배 ${percent(phase.stress_mean_net_return)}`
        : '비교 자료 없음'}</p>;
}

export default function AdminStockAnalysisPanel() {
    const { user, token, loading } = useAuth();
    if (loading || user?.role !== 'admin' || user.status !== 'approved' || !token) return null;
    return <AdminStockAnalysisContent />;
}

function AdminStockAnalysisContent() {
    const { token } = useAuth();
    const [params] = useSearchParams();
    const location = useLocation();
    const navigate = useNavigate();
    const rawCode = params.get('adminCode') ?? '';
    const code = /^\d{6}$/.test(rawCode) ? rawCode : '';
    const identity = `${token ?? ''}:${code}`;
    const [saved, setSaved] = useState<{ identity: string; status: AdminStockAnalysisStatus } | null>(null);
    const [pending, setPending] = useState<'read' | 'start' | null>(null);
    const [error, setError] = useState('');
    const [now, setNow] = useState(Date.now);
    const generation = useRef(0);
    const inFlight = useRef<number | null>(null);
    const jobStarted = useRef<number | null>(null);
    const status = saved?.identity === identity ? saved.status : null;

    const request = useCallback(async (kind: 'read' | 'start', background = false) => {
        if (!code || inFlight.current !== null) return;
        const current = generation.current;
        inFlight.current = current; setPending(kind); setError('');
        if (!background) jobStarted.current = Date.now();
        try {
            const next = kind === 'start' ? await startAdminStockAnalysis(code, token ?? undefined)
                : await fetchAdminStockAnalysis(code, token ?? undefined);
            if (generation.current !== current) return;
            setSaved(previous => ({ identity, status: { ...next,
                result: next.result ?? (['running', 'failed'].includes(next.state) && previous?.identity === identity ? previous.status.result : null) } }));
            if (next.state !== 'running') jobStarted.current = null;
            setNow(Date.now());
        } catch {
            if (generation.current === current) setError(kind === 'start'
                ? '분석을 시작하지 못했습니다. 저장 결과를 확인하거나 다시 실행해 주세요.'
                : '저장 분석 결과를 불러오지 못했습니다. 다시 조회해 주세요.');
        } finally {
            if (generation.current === current) { inFlight.current = null; setPending(null); }
        }
    }, [code, token, identity]);

    useEffect(() => {
        generation.current += 1; inFlight.current = null; jobStarted.current = null;
        setSaved(null); setError(''); setPending(null); setNow(Date.now());
        if (code) void request('read');
        return () => { generation.current += 1; };
    }, [request, code]);

    useEffect(() => {
        if (status?.state !== 'running' || pending || error) return;
        const timer = setTimeout(() => {
            if (jobStarted.current !== null && Date.now() - jobStarted.current >= 8 * 60000) {
                setError('분석이 예상보다 오래 걸립니다. 저장 결과를 다시 조회해 주세요.');
                return;
            }
            void request('read', true);
        }, 3000);
        return () => clearTimeout(timer);
    }, [status?.state, pending, error, request]);

    useEffect(() => {
        const refreshTime = () => setNow(Date.now());
        const visible = () => { if (document.visibilityState === 'visible') refreshTime(); };
        window.addEventListener('focus', refreshTime); document.addEventListener('visibilitychange', visible);
        return () => { window.removeEventListener('focus', refreshTime); document.removeEventListener('visibilitychange', visible); };
    }, []);
    useEffect(() => {
        if (!status?.result || status.result.candidate.proposal.action !== 'buy') return;
        const result = status.result;
        const sourceEnd = (value: string) => (Math.floor((Date.parse(value) + 9 * 3600000) / 86400000) + 8) * 86400000 - 9 * 3600000;
        const times = [Date.parse(result.candidate.proposal.valid_until ?? ''), sourceEnd(result.source.captured_at), sourceEnd(`${result.latest_session}T00:00:00+09:00`)];
        const next = Math.min(...times.filter(value => value > now));
        if (!Number.isFinite(next)) return;
        const timer = setTimeout(() => setNow(Date.now()), Math.min(next - now, 2147483647));
        return () => clearTimeout(timer);
    }, [status, now]);

    const select = useCallback((symbol: string) => {
        const updated = new URLSearchParams(params);
        updated.set('adminCode', symbol);
        navigate({ pathname: location.pathname, search: `?${updated.toString()}`, hash: location.hash });
    }, [params, navigate, location.pathname, location.hash]);
    const result = status?.result;
    const proposal = status ? effectiveAdminStockProposal(status, !!pending || !!error, now) : null;
    const nextStep = proposal?.action === 'wait' ? proposal.next_step.replace(/(?:매수 후보 )?검출(?:을)?\s*갱신/g, '분석 실행') : proposal?.next_step;
    const candidate = result?.candidate;
    const stateLabel = status?.state === 'running' ? '분석 진행 중' : status?.state === 'failed' ? '분석 실패'
        : status?.state === 'missing' ? '저장 결과 없음' : status?.state === 'held' ? '분석 보류' : status ? '저장 결과 확인' : '종목 선택 대기';

    return <section id="admin-stock-analysis" aria-labelledby="admin-stock-analysis-heading" className="my-4 min-w-0 space-y-3 rounded-lg border border-[#365372] bg-[#111922] p-3 text-white sm:p-4">
        <header className="flex min-w-0 flex-wrap items-start justify-between gap-3">
            <div className="min-w-0"><h3 id="admin-stock-analysis-heading" className="text-sm font-semibold text-[#acd3ff]">관리자 전용 종목 검색 분석</h3>
                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-gray-400">종목을 선택해 재무 품질과 가격 조건을 확인하고, 같은 정책으로 매매 제안과 참고 가격을 계산합니다.</p></div>
        </header>
        <section className="min-w-0 rounded-lg border border-[#303f4b] bg-[#121a22] p-3 sm:p-4" aria-label="분석 종목 선택">
            <ChartAnalogueSymbolSearch symbol={code} token={token ?? undefined} onSelect={select}
                fetchCandidates={searchAdminStockCandidates} submitLabel="종목 선택" idPrefix="admin-stock"
                hint="국내 종목명 · 6자리 코드 · 초성 검색 · 종목을 선택한 뒤 분석을 실행하세요." />
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#303f4b] pt-3">
                <button type="button" className={button} disabled={!code || !!pending || status?.state === 'running'} onClick={() => void request('start')}>{pending === 'start' ? '분석 시작 중…' : '분석 실행'}</button>
                <button type="button" className={button} disabled={!code || !!pending} onClick={() => void request('read')}>저장 결과 새로고침</button>
                <span className="min-w-0 break-words text-xs text-gray-400">{code ? `${code} · KR` : '선택한 종목 없음'}</span>
            </div>
        </section>
        {!!rawCode && !code && <p role="alert" className="text-sm text-amber-200">국내 종목 코드 6자리를 선택해 주세요.</p>}
        {error && <p role="alert" className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-200">{error}</p>}
        <p role="status" className="break-words text-xs text-gray-400">{pending === 'read' ? '저장 결과 조회 중…' : pending === 'start' ? '분석 요청 중…' : stateLabel}
            {status?.state === 'running' && ' · 저장된 진행 상태를 확인합니다.'}</p>
        {candidate && result && proposal && <>
            <article aria-label={`${candidate.name} ${candidate.symbol} 분석 결과`} className="min-w-0 rounded-lg border border-[#3b4d5c] bg-[#121a22] p-4">
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0"><h4 className="break-words text-lg font-semibold">{candidate.name}</h4><p className="mt-1 font-mono text-xs text-gray-400">{candidate.symbol} · KR · {strategyNames[candidate.strategy_id] ?? candidate.strategy_id}</p></div>
                    <span className={`rounded border px-2 py-1 text-xs font-bold ${proposal.action === 'buy' ? 'border-[#497368] text-teal-200' : 'border-[#796b4e] text-amber-200'}`}>{proposal.action.toUpperCase()} · {proposal.label}</span>
                </div>
                <p className="mt-3 break-words text-sm leading-relaxed text-gray-100">{proposal.reason}</p>
                <dl className="mt-4 grid min-w-0 grid-cols-2 gap-3 border-y border-[#365372] py-4 sm:grid-cols-4">{[
                    ['제안 비중', percent(proposal.proposed_weight)], ['참고 진입', money(candidate.plan?.entry_price)],
                    ['참고 손절', money(candidate.plan?.stop_price)], ['참고 목표', money(candidate.plan?.target_price)],
                ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-gray-400">{label}</dt><dd className="mt-1 break-words font-mono text-lg font-semibold tabular-nums text-gray-100">{value}</dd></div>)}</dl>
                <p className="mt-3 text-xs font-semibold text-[#acd3ff]">마지막 종가 기준 참고 계산 · 다음 장 시가 확인 후 진입·손절·비중 재계산</p>
                {proposal.action !== 'buy' && <p className="mt-1 text-xs text-amber-200">대기·제외 상태의 가격은 참고 계산입니다. 신규 진입 제안이 아닙니다.</p>}
                <div className="mt-3 grid min-w-0 gap-2 text-xs text-gray-400 sm:grid-cols-2">
                    <p className="break-words tabular-nums">기준 종가 {money(candidate.last_close)} · 계획 손실폭 {percent(candidate.plan?.loss_fraction)}</p>
                    <p className="break-words tabular-nums">입력 거래일 {proposal.input_session ?? result.latest_session} · 보유 계획 최대 10거래일</p>
                    {candidate.entry_guard && <p className="break-words tabular-nums">추격 매수 상한 (+2%) {money(candidate.entry_guard.max_entry_price)}</p>}
                    <p className="break-words tabular-nums">제안 만료 {time(proposal.valid_until)}</p>
                </div>
                <p className="mt-3 break-words text-xs leading-relaxed text-[#acd3ff]">다음 행동 · {nextStep}</p>
                <p className="mt-2 text-xs leading-relaxed text-gray-400">쿼터 켈리 · 종목 한도 5% · 계좌 계획 손실 한도 1%. 제안은 직접 판단용 의견이며 체결·보유·자동 주문을 뜻하지 않습니다.</p>
                {proposal.action === 'avoid' && <p className="mt-2 text-xs text-gray-400">신규매수 제외 의견이며 보유 주식의 매도 지시가 아닙니다.</p>}
            </article>
            <section aria-label="자료와 품질 확인" className="min-w-0 rounded-lg border border-[#303f4b] p-4">
                <h4 className="text-sm font-semibold">자료와 품질 확인</h4>
                <div className="mt-3 grid min-w-0 gap-3 text-xs sm:grid-cols-2">
                    <p className="break-words text-gray-300">자료 경로 · {result.source.mode === 'saved_snapshot' ? '저장 스냅샷 사용' : '선택 종목 신규 수집'}</p>
                    <p className={`break-words ${result.quality.status === 'passed' ? 'text-teal-200' : 'text-amber-200'}`}>재무 품질 · {result.quality.status === 'passed' ? '조건 통과' : result.quality.status === 'blocked' ? '조건 미충족 · 매수 보류' : '자료 확인 대기'}</p>
                    <p className="break-words tabular-nums text-gray-400">자료 수집 {time(result.source.captured_at)}</p><p className="break-words tabular-nums text-gray-400">분석 기준 {time(result.analyzed_at)}</p>
                    <p className="break-words text-gray-400">가격 기준 · {result.source.price_basis === 'provider_reported_unverified' ? '제공자 가격 · 보정 여부 미인증' : result.source.price_basis === 'unadjusted' ? '미수정 가격' : result.source.price_basis === 'unknown' ? '가격 기준 확인 대기' : result.source.price_basis}</p>
                    <p className="break-words text-gray-400">가격 보정 {result.source.price_adjustment_verified ? '확인' : '미확인'} · 당시 자료 시점 {result.source.historical_vintage_verified ? '확인' : '미확인'} · 당시 종목 목록 {result.source.point_in_time_universe_verified ? '확인' : '미확인'}</p>
                </div>
                {!!result.quality.reasons.length && <ul className="mt-3 space-y-1 text-xs text-amber-200">{result.quality.reasons.map(value => <li key={value} className="break-words">{reason(value)}</li>)}</ul>}
                <ol className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-gray-400">{result.stages.map(stage => <li key={stage.id}>{stage.label} · {stage.state === 'complete' ? '완료' : '대기'}</li>)}</ol>
            </section>
            <details className="min-w-0 rounded-lg border border-[#303f4b] p-4">
                <summary className="min-h-10 cursor-pointer text-sm font-semibold text-[#acd3ff]">검증 근거와 전략 진단</summary>
                <p className="mt-2 text-xs leading-relaxed text-gray-400">과거 조건일을 형성 구간과 최근 확인 구간으로 나눈 탐색적 근거입니다. 평균 순손익은 제안 비중의 계좌 성과나 미래 수익률이 아닙니다.</p>
                {candidate.evidence && <div className="mt-3 space-y-2"><Diagnostic label="선택 전략 · 형성 구간" phase={candidate.evidence.calibration} /><Diagnostic label="선택 전략 · 최근 확인" phase={candidate.evidence.confirmation} /></div>}
                <ul className="mt-3 space-y-3">{result.diagnostics.map(diagnostic => <li key={diagnostic.strategy_id} className="min-w-0 border-t border-[#303f4b] pt-3">
                    <h5 className="break-words text-xs font-semibold text-gray-300">{strategyNames[diagnostic.strategy_id] ?? diagnostic.strategy_id} · {diagnostic.setup_active ? '현재 조건 활성' : '현재 조건 미충족'}</h5>
                    <div className="mt-2 space-y-1"><Diagnostic label="형성 구간" phase={diagnostic.calibration} /><Diagnostic label="최근 확인" phase={diagnostic.confirmation} /></div>
                    {!!diagnostic.reasons.length && <p className="mt-2 break-words text-xs leading-relaxed text-amber-200">{diagnostic.reasons.map(reason).join(' · ')}</p>}
                </li>)}</ul>
                <ul className="mt-3 space-y-1 text-xs leading-relaxed text-gray-400">{Array.from(new Set([...candidate.reasons, ...candidate.risk.reasons, ...result.warnings])).map(value => <li key={value} className="break-words">{reason(value)}</li>)}</ul>
            </details>
        </>}
        {status?.state === 'missing' && <p className="text-sm text-gray-400">이 종목의 저장된 분석이 없습니다. 분석 실행으로 현재 자료를 확인하세요.</p>}
        {status?.state === 'failed' && !result && <p className="text-sm text-amber-200">분석을 완료하지 못했습니다. 저장 결과를 확인하거나 다시 실행해 주세요.</p>}
    </section>;
}
