import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { evidenceSourceUrl, type EvidenceFinding } from '@/lib/evidenceReview';
import { fetchTop3Advisor, type AdvisorPick, type AdvisorRow, type AdvisorSource, type Top3Advisor } from '@/lib/top3Advisor';

const clock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
const roles = { analyst: '재료 분석', critic: '위험 반론', chair: '최종 비교' };
const stageLabels: Record<string, string> = { SUCCESS_PRIMARY: '완료', SUCCESS_FALLBACK: '대체 모델 완료', RECOVERED_RESPONSE: '저장 응답 복구',
    WAITING: '대기', IN_PROGRESS: '진행 중', UNVERIFIED: '확인 미완료', UNKNOWN: '응답 확인 필요' };
const reasons: Record<string, string> = {
    t_stat_below_two: '순수익의 통계 검증 기준 미충족', no_validation_qualified_champion: '검증 조건을 통과한 전략 없음',
    historical_price_vintage_unverified: '과거 가격 자료의 당시 수집 시점 미확인', historical_vintage_unverified: '과거 자료의 당시 제공 시점 미확인',
    point_in_time_universe_unverified: '당시 종목 목록 검증 대기', corporate_action_adjustment_unverified: '기업행사 가격 보정 미확인',
    source_vintage_and_corporate_action_adjustment_not_certified: '당시 자료 시점·기업행사 가격 보정 미확인',
    leadership_watchlist_not_entry_approval: '주도주 관찰 단계 · 진입 승인 전', article_source_unavailable: '뉴스 자료 확인 대기',
    verification_source_unavailable: '공시·시세 검증 자료 확인 대기', forward_validation_pending: '선정 이후 성과 관측 중',
};
const claimLabels = { reported: '보도 내용', inference: '해석', verified: '검증 근거', missing: '미확인' };
function Time({ value }: { value?: string | null }) {
    return value ? <time dateTime={value}>{clock.format(Date.parse(value))}</time> : <>미확인</>;
}
function Findings({ title, items, empty }: { title: string; items: EvidenceFinding[]; empty: string }) {
    return <div><dt className="text-xs font-semibold text-slate-400">{title}</dt><dd className="mt-1 text-sm leading-6 text-slate-200">
        {items.length ? items.map((f, i) => <p key={i}><span className="mr-1 text-xs text-sky-200">{claimLabels[f.claim_status]}</span>{f.text}</p>) : empty}
    </dd></div>;
}
function Arguments({ row }: { row: AdvisorRow }) {
    return <dl className="space-y-3"><Findings title="선정 근거" items={row.strengths} empty="저장된 정량 지표로 비교했습니다. 추가 재료 근거는 확인 대기입니다." />
        <Findings title="주의할 점" items={row.risks} empty="추가 위험 분석 확인 대기" />
        <Findings title="다음 확인" items={row.what_to_watch} empty="최신 공시·시세와 진입 조건을 확인하세요." /></dl>;
}
function Sources({ sources, findings }: { sources: AdvisorSource[]; findings: EvidenceFinding[] }) {
    return <ul className="space-y-3 text-xs leading-5">{sources.map(s => {
        const url = evidenceSourceUrl(s.url);
        const quotes = [...new Set(findings.flatMap(f => f.quotes).filter(q => q.evidence_id === s.evidence_id).map(q => q.quote))];
        return <li key={s.evidence_id} className="space-y-1 border-t border-slate-700 pt-2">
            {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-sky-200 underline">{s.title}</a> : <p>{s.title}</p>}
            <p className="text-slate-400">{s.source} · {s.verification_status === 'sealed' ? '저장 분석' : ['verified', 'verified_numeric_claims'].includes(s.verification_status) ? '대조 완료' : '확인 대기'}</p>
            <p className="text-slate-400">발행 <Time value={s.published_at} /> · 수집 <Time value={s.fetched_at} /></p>
            {typeof s.available_at_original_decision === 'boolean' && <p className="text-slate-400">{s.available_at_original_decision ? '선정 당시 자료' : '선정 이후 추가 자료'}</p>}
            {quotes.map(q => <blockquote key={q} className="border-l-2 border-sky-700 pl-2">“{q}”</blockquote>)}
        </li>;
    })}</ul>;
}
function Pick({ pick, view }: { pick: AdvisorPick; view: Top3Advisor }) {
    const findings = [...pick.strengths, ...pick.risks, ...pick.what_to_watch];
    const sources = view.sources.filter(s => s.target_symbols.includes(pick.symbol));
    const money = (v?: number | null) => v == null ? '미확인' : `${Math.round(v).toLocaleString('ko-KR')}원`;
    return <article className="min-w-0 space-y-4 rounded-xl border border-[#425565] bg-[#10181f] p-4 [overflow-wrap:anywhere]" aria-label={`어드바이저 ${pick.rank}위 ${pick.name}`}>
        <header className="flex items-start gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-sky-400/30 bg-sky-400/10 text-lg font-bold text-sky-200">{pick.rank}</span>
            <div className="min-w-0"><h3 className="text-lg font-bold text-white">{pick.name}</h3><p className="mt-1 text-xs text-slate-400">{pick.symbol} · 한국 · {pick.basis === 'leadership_watchlist' ? '주도주 관찰' : pick.basis === 'issued_opportunities' ? '저장 제안 비교' : '연구 후보'}</p></div></header>
        <p className="rounded-md border border-amber-300/20 bg-amber-300/5 px-2.5 py-2 text-xs font-semibold text-amber-200">{pick.entry_status === 'ready' ? '원래 진입 조건 재확인' : '진입 조건 확인 필요'}</p>
        <Arguments row={pick} />
        <details className="border-t border-slate-700 text-xs text-slate-300"><summary className="flex min-h-11 cursor-pointer items-center font-semibold text-sky-200">가격·진입 조건·출처 보기</summary>
            <div className="space-y-3 pb-2"><p>저장 가격 기준 <Time value={pick.source_at} /> (한국시간)</p><p>참고 기준가 {money(pick.reference_price)}</p>
                {pick.plan ? <dl className="space-y-2">{([['참고 진입', pick.plan.entry_price], ['참고 손절', pick.plan.stop_price], ['참고 목표', pick.plan.target_price]] as const).map(([label, value]) => <div key={label} className="flex flex-wrap justify-between gap-2"><dt>{label}</dt><dd className="tabular-nums text-white">{money(value)}</dd></div>)}<p className="text-slate-400">원래 결정의 참고 가격입니다. 최신 시세와 체결 가격은 별도로 확인하세요.</p></dl> : <p>저장된 진입·손절·목표 계획이 없습니다.</p>}
                {!!pick.hold_reasons.length && <ul className="list-disc space-y-1 pl-4 text-amber-200">{pick.hold_reasons.map(r => <li key={r}>{reasons[r] ?? `추가 검증 조건: ${r}`}</li>)}</ul>}
                <Sources sources={sources} findings={findings} />
            </div>
        </details>
        <Link to={`/dashboard/ai-bain/chart-predict?code=${pick.symbol}`} aria-label={`${pick.name} 차트·가격 조건 보기`} className="flex min-h-11 items-center justify-center rounded-lg border border-[#365372] bg-[#1b2c40] px-3 text-sm font-semibold text-sky-200 hover:bg-[#243c56] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300">차트·가격 조건 보기 <span aria-hidden="true" className="ml-2">→</span></Link>
    </article>;
}

function SavedAdvisor({ token }: { token?: string }) {
    const heading = useId();
    const [view, setView] = useState<Top3Advisor | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const mounted = useRef(false); const pending = useRef(false); const denied = useRef(false);
    const controller = useRef<AbortController | null>(null);
    const refresh = useCallback(async () => {
        if (!mounted.current || pending.current || denied.current) return;
        pending.current = true; const request = new AbortController(); controller.current = request;
        setLoading(true);
        try {
            const next = await fetchTop3Advisor(token, request.signal);
            if (mounted.current && !request.signal.aborted) { setView(next); setError(null); }
        } catch (failure) {
            if (!mounted.current || request.signal.aborted) return;
            setView(null);
            const access = failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status));
            denied.current = access; setError(access ? 'access' : 'unavailable');
        } finally {
            if (controller.current === request) { pending.current = false; if (mounted.current) setLoading(false); }
        }
    }, [token]);
    useEffect(() => {
        mounted.current = true;
        if (document.visibilityState === 'visible') void refresh();
        return () => { mounted.current = false; controller.current?.abort(); pending.current = false; };
    }, [refresh]);
    useAutoRefresh(refresh, 30000, error !== 'access');
    return <section id="top3-advisor" aria-labelledby={heading} className="ai-panel min-w-0 scroll-mt-20 space-y-4 border border-[#365372] p-4 sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="mb-1 text-xs font-semibold text-sky-300">뉴스·공시·가격 근거 비교</p><h2 id={heading} className="ai-section-title text-xl">TOP3 어드바이저</h2><p className="mt-2 text-sm leading-6 text-slate-300">재료 분석 → 위험 반론 → 최종 비교. 먼저 살펴볼 종목과 확인할 조건을 모았습니다.</p></div>
            <button type="button" onClick={() => void refresh()} disabled={loading || error === 'access'} className="min-h-11 rounded-lg border border-[#365372] px-3 text-sm font-semibold text-sky-200 hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50">TOP3 저장 결과 새로고침</button></header>
        {loading && !view && <p role="status" className="py-4 text-sm text-slate-300">저장된 TOP3를 불러오는 중…</p>}
        {error && <p role="alert" className="text-sm text-amber-200">{error === 'access' ? 'TOP3 이용 권한을 확인해 주세요. 로그인 상태와 AI 브레인 구독을 확인하세요.' : 'TOP3 조회가 지연되고 있습니다. 잠시 후 저장 결과를 다시 조회해 주세요.'}</p>}
        {view && <>
            <div className="space-y-2 rounded-lg border border-slate-700 bg-[#101318] p-3 text-xs leading-5 text-slate-300">
                <p className="font-semibold text-sky-200">{view.debate.debate_complete ? '3단계 토론 완료 · 연구 순위' : '저장 지표 순위 · 토론 미완료'}</p>
                <div className="flex flex-wrap gap-x-4 gap-y-1"><span>선정 자료 <Time value={view.source_origin_at} /></span><span>비교 작성 <Time value={view.generated_at} /></span><span>한국시간</span></div>
                <p>비교 후보 {view.coverage.pool ?? 0}종목 · 최근 뉴스 {view.coverage.with_recent_news ?? 0}종목 · 공시 검증 {view.coverage.with_verified_filings ?? 0}종목 · 시세 검증 {view.coverage.with_verified_prices ?? 0}종목</p>
                {view.top3.length > 0 && !view.coverage.with_recent_news && <p className="text-amber-200">비교 후보에 연결된 최근 뉴스가 없습니다. 현재 순위는 저장된 정량 근거를 중심으로 비교한 결과입니다.</p>}
            </div>
            {view.top3.length ? <div className="grid min-w-0 gap-3 lg:grid-cols-3">{view.top3.map(pick => <Pick key={pick.symbol} pick={pick} view={view} />)}</div>
                : <div className="rounded-lg border border-slate-700 p-4 text-sm leading-6 text-slate-300"><p className="font-semibold text-white">현재 표시할 TOP3가 없습니다.</p><p>{view.status === 'stale' ? '선정 자료가 갱신되어 새 비교를 기다리고 있습니다.' : view.status === 'missing' ? '아직 저장된 분석 자료가 없습니다.' : '자료와 분석 상태를 확인한 뒤 결과를 표시합니다.'}</p></div>}
            <details className="min-w-0 border-t border-slate-700 text-sm leading-6 text-slate-300 [overflow-wrap:anywhere]"><summary className="flex min-h-11 cursor-pointer items-center font-semibold text-sky-200">에이전트 토론·검증 상태</summary>
                <div className="space-y-4">{view.debate.stages.map(stage => <div key={stage.role} className="min-w-0 space-y-2 border-t border-slate-700 pt-3"><h3 className="font-semibold text-white">{roles[stage.role]} · <span>{stageLabels[stage.status] ?? '확인 대기'}</span></h3>
                    <p className="text-xs text-slate-400">{stage.provider ?? '모델 대기'}{stage.model ? ` · ${stage.model}` : ''} · <Time value={stage.generated_at} /></p>
                    {stage.fallback_reason && <p className="text-xs text-amber-200">기본 모델 이용 제한으로 대체 분석 또는 저장 근거를 사용합니다.</p>}
                    {stage.rows.map(row => <details key={row.symbol} className="rounded-lg border border-slate-700 px-3"><summary className="flex min-h-11 cursor-pointer items-center text-sky-200">{row.name} · {row.symbol}</summary><div className="pb-3"><Arguments row={row} /></div></details>)}
                </div>)}
                {!!view.warnings.length && <div><h3 className="font-semibold">자료 검증 사항</h3><ul className="list-disc pl-4 text-xs text-amber-200">{view.warnings.map(w => <li key={w}>{reasons[w] ?? w}</li>)}</ul></div>}
                <p className="text-xs text-slate-400">비교 자료 기준 <Time value={view.source_cutoff_at} /> · 순위는 수익 확률이 아닙니다. 기존 진입 판단과 가격 계획을 변경하지 않습니다.</p>
            </div></details>
        </>}
        <p className="text-xs leading-5 text-slate-400">5분마다 새 분석 자료 확인 · 화면은 30초마다 저장 결과 조회 · 실계좌 주문 없음</p>
    </section>;
}
export default function Top3AdvisorPanel({ token }: { token?: string }) {
    return <SavedAdvisor key={token ?? 'anonymous'} token={token} />;
}
