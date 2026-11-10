import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { fetchSurgeTraces, surgeSourceUrl, type SurgeEvidence, type SurgeTrace, type SurgeTraceView } from '@/lib/surgeTrace';

const clock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const sessionDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' });
const money = (value: number | null) => value === null ? '미확인' : `${value.toLocaleString('ko-KR', { maximumFractionDigits: 20 })}원`;
const percent = (value: number | null) => value === null ? '미확인' : `${value > 0 ? '+' : ''}${value.toLocaleString('ko-KR', { maximumFractionDigits: 20 })}%`;
const labels: Record<string, string> = { prior_material: '유력 재료 후보', post_report: '사후 보도', unresolved: '원인 미확인', source_incomplete: '원인 미확인 · 출처 확인 미완료' };
const states: Record<string, string> = { ready: '저장 결과', partial: '일부 출처 확인 미완료', stale: '시세 자료 갱신 필요', no_surge: '조건에 맞는 급등 관측 없음', unavailable: '자료 이용 불가', waiting: '수집 대기' };
const sourceStates: Record<string, string> = { fresh: '관측 자료 확인', historical: '장외 저장 관측 · 현재 시세가 아닙니다.', stale: '오래된 관측 자료 · 최신 시세 확인 필요', future: '관측 시각 확인 필요', paper: '실제 시장 시세 확인 필요', incomplete: '시세 자료 일부 미확인', unavailable: '시세 자료 이용 불가', regressed: '시세 자료 시각 역행 · 확인 필요', identity_unavailable: '종목 정보 대조 미완료', source_conflict: '시세 자료 간 불일치', unverified_quote_mode: '시세 조회 방식 확인 필요', unknown_market_status: '시장 운영 상태 미확인' };
const sourceNames: Record<string, string> = { omni: 'Omni 뉴스', businesspost: '비즈니스포스트', kongming: '제갈공명 기사', google_news: 'Google 뉴스', google_rss: 'Google 뉴스', opendart: 'OpenDART', dart: 'OpenDART' };
const checks: Record<string, string> = { ready: '확인 완료', empty: '관련 자료 없음', error: '수집 실패', pending: '확인 대기' };
const timing = { before_observation: '관측 전 발표', after_observation: '관측 후 보도', same_day_unknown: '당일 선후 미확인', unknown: '발표 선후 미확인' };
const direction = { positive: '긍정 재료', negative: '부정 재료', neutral: '방향 중립', mixed: '호재·위험 혼재' };
const categories: Record<string, string> = { contract: '계약', earnings: '실적', risk: '위험', policy: '정책', investment: '투자', product: '제품', approval: '승인', financing: '자금 조달', ownership: '지분', regulatory: '인허가·규제', capacity: '시설·생산능력', capital_policy: '자본 정책', price_movement: '주가 동향', other: '기타 사건' };
const verification: Record<string, string> = { reported_unverified: '보도 내용 · 추가 확인 필요', issuer_matched: '공시 대상 기업 일치', issuer_verified: '공시 대상 기업 일치', issuer_symbol_and_title_match: '종목 코드·기사 제목 대조', issuer_title_match: '기사 제목의 기업명 대조', issuer_registry_match: '공시 기업 등록정보 대조', official_disclosure: '공식 공시', verified: '출처 대조 완료', unverified: '확인 대기' };
const limitations: Record<string, string> = {
    source_universe_partial: '스크리너가 확보한 관측 범위이며 전 종목 조사 결과는 아닙니다.',
    historical_observation: '저장된 시세 관측이며 현재 시세가 아닙니다.',
    causality_unproven: '상승과 재료 사이의 인과관계는 입증되지 않았습니다.',
    retrospective_discovery: '시세 관측 이후 확보한 자료가 포함돼 있습니다.',
    disclosure_intraday_timing_unknown: '일자만 제공된 공시는 당일 발표 선후를 확인할 수 없습니다.',
    source_errors: '일부 출처 수집에 실패했습니다.',
    omni_archive_freshness_unknown: '보관된 Omni 기사 조회이며 최신 수집 상태는 확인되지 않았습니다.',
    evidence_revision_timing_unknown: '정정된 기사 내용의 발표 선후는 확인되지 않았습니다.',
    risk_or_opposing_evidence: '위험·반대 재료도 함께 확인됐습니다.',
};
function Time({ value }: { value: string | null }) {
    if (!value) return <>미확인</>;
    return <time dateTime={value}>{value.length === 10 ? value : clock.format(Date.parse(value))}</time>;
}
function Evidence({ item }: { item: SurgeEvidence }) {
    const url = surgeSourceUrl(item.url);
    return <li className="min-w-0 space-y-2 border-t border-slate-700 py-3 [overflow-wrap:anywhere]">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs"><span className="font-semibold text-sky-200">{timing[item.timing]}</span><span className={['negative', 'mixed'].includes(item.direction) ? 'font-semibold text-amber-200' : 'text-slate-300'}>{direction[item.direction]}</span></div>
        {url ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-sm font-semibold leading-6 text-sky-200 underline decoration-sky-200/40 underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300">{item.title}</a> : <p className="text-sm font-semibold leading-6 text-slate-200">{item.title}</p>}
        <p className="text-xs text-slate-400">{item.kind === 'disclosure' ? '공시' : '뉴스'} · {item.publisher ?? '발행처 미확인'} · {item.source ? sourceNames[item.source] ?? item.source : '수집 출처 미확인'}{item.category && ` · ${categories[item.category] ?? '사건 유형 미확인'}`}</p>
        <dl className="grid gap-2 text-xs sm:grid-cols-2"><div><dt className="text-slate-400">발표</dt><dd className="mt-1 text-slate-200">{item.published_precision === 'date' && item.published_at ? `${item.published_at} (시간 미확인)` : <Time value={item.published_at} />}</dd></div>
            <div><dt className="text-slate-400">최초 수신</dt><dd className="mt-1 text-slate-200"><Time value={item.first_received_at} /></dd></div></dl>
        {item.discovered_after_observation === true && <p className="text-xs font-semibold text-amber-200">관측 후 확보한 자료</p>}
        <p className="text-xs text-slate-400">{item.verification ? verification[item.verification] ?? '내용 확인 미완료' : '내용 확인 미완료'}{item.duplicate_count !== null && item.duplicate_count > 1 && ` · 같은 내용의 자료 ${item.duplicate_count}건`}</p>
    </li>;
}
function Trace({ row }: { row: SurgeTrace }) {
    return <article aria-label={`${row.name} 급등 이유`} className="min-w-0 space-y-3 rounded-xl border border-[#425565] bg-[#10181f] p-3 [overflow-wrap:anywhere] sm:p-4">
        <header className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><h3 className="text-lg font-bold text-white">{row.name}</h3><p className="mt-1 text-xs text-slate-400">{row.symbol} · {row.market} · 관측 세션 {row.session}</p></div>
            <span className="rounded-md border border-sky-300/25 bg-sky-300/5 px-2 py-1 text-xs font-semibold text-sky-200">{labels[row.status] ?? '미확인'}</span></header>
        {row.session < sessionDate.format(new Date())
            ? <p className="text-xs font-semibold text-amber-200">과거 세션 관측 · 현재 시세가 아닙니다.</p>
            : row.limitations.includes('historical_observation') && <p className="text-xs font-semibold text-amber-200">저장 시세 관측 · 현재 시세가 아닙니다.</p>}
        <dl className="grid gap-2 sm:grid-cols-3"><div><dt className="text-xs text-slate-400">관측 등락률</dt><dd className="mt-1 text-xl font-bold tabular-nums text-rose-300">{percent(row.change_pct)}</dd></div><div><dt className="text-xs text-slate-400">관측 가격</dt><dd className="mt-1 font-semibold tabular-nums text-white">{money(row.price)}</dd></div><div><dt className="text-xs text-slate-400">관측 거래대금</dt><dd className="mt-1 tabular-nums text-slate-200">{money(row.trading_value)}</dd></div></dl>
        <p className="text-sm leading-6 text-slate-200">{row.summary ?? '저장된 자료에서 설명할 만한 재료를 확인하지 못했습니다.'}</p>
        <dl className="grid gap-2 text-xs sm:grid-cols-2"><div><dt className="text-slate-400">시세 관측</dt><dd className="mt-1 text-slate-200"><Time value={row.price_observed_at} /></dd></div><div><dt className="text-slate-400">서비스 최초 발견</dt><dd className="mt-1 text-slate-200"><Time value={row.first_detected_at} /></dd></div></dl>
        <details className="border-t border-slate-700"><summary className="flex min-h-11 cursor-pointer items-center text-sm font-semibold text-sky-200">재료 근거·발표 시각 보기</summary>
            {row.evidence.length ? <><ul>{row.evidence.map(item => <Evidence key={item.id} item={item} />)}</ul><p className="pb-3 text-xs leading-5 text-slate-400">관측 전 발표된 자료도 상승 원인을 입증하지 않습니다. 검색 결과와 중복 보도 수는 독립 근거 수가 아닙니다.</p></> : <p className="pb-3 text-sm text-slate-300">연결된 재료 근거가 없습니다.</p>}
        </details>
        <details className="border-t border-slate-700"><summary className="flex min-h-11 cursor-pointer items-center text-sm font-semibold text-sky-200">출처 확인·수집 상태</summary>
            <div className="space-y-3 pb-2 text-xs leading-5 text-slate-300">{row.checks.length ? <ul className="space-y-3">{row.checks.map((check, i) => <li key={`${check.source}:${i}`}><p className={check.status === 'error' ? 'text-amber-200' : undefined}>{sourceNames[check.source] ?? check.source} · {checks[check.status] ?? '미확인'}</p><p>확인 <Time value={check.checked_at} /> · {check.count === null ? '결과 수 미확인' : `조회 결과 ${check.count}건`}</p></li>)}</ul> : <p>출처 확인 상태 미확인</p>}
                {row.limitations.length > 0 && <ul className="list-disc space-y-1 pl-4 text-amber-200">{row.limitations.map((line, i) => <li key={i}>{limitations[line] ?? (/^[a-z][a-z0-9_]+$/.test(line) ? '추가 확인이 필요한 자료입니다.' : line)}</li>)}</ul>}</div>
        </details>
    </article>;
}
function SavedSurgeTraces() {
    const heading = useId(); const search = useId();
    const [view, setView] = useState<SurgeTraceView | null>(null);
    const [query, setQuery] = useState(''); const [loading, setLoading] = useState(true);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const mounted = useRef(false); const pending = useRef(false); const denied = useRef(false);
    const refresh = useCallback(async () => {
        if (!mounted.current || pending.current || denied.current || document.visibilityState !== 'visible') return;
        pending.current = true; setLoading(true);
        try {
            const next = await fetchSurgeTraces();
            if (mounted.current) { setView(next); setError(null); }
        } catch (failure) {
            if (!mounted.current) return;
            setView(null);
            const access = failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status));
            denied.current = access; setError(access ? 'access' : 'unavailable');
        } finally { pending.current = false; if (mounted.current) setLoading(false); }
    }, []);
    useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; }; }, [refresh]);
    useAutoRefresh(refresh, 30000, error !== 'access');
    const normalized = query.trim().toLocaleLowerCase('ko-KR');
    const rows = view?.items.filter(row => `${row.name} ${row.symbol}`.toLocaleLowerCase('ko-KR').includes(normalized)) ?? [];
    return <section id="surge-traces" aria-labelledby={heading} aria-busy={loading} className="ai-panel min-w-0 scroll-mt-20 space-y-4 border border-[#365372] p-4 sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 id={heading} className="ai-section-title text-xl">급등 이유 역추적</h2><p className="mt-2 text-sm leading-6 text-slate-300">급등이 관측된 종목에서 출발해 뉴스·공시의 발표 시각과 상승 재료 후보를 확인합니다.</p></div>
            <button type="button" onClick={() => void refresh()} disabled={loading || error === 'access'} className="min-h-11 shrink-0 rounded-lg border border-[#526a83] px-3 py-2 text-sm font-semibold text-sky-200 hover:bg-sky-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50">급등 저장 결과 새로고침</button></header>
        {loading && !view && <p role="status" className="py-4 text-sm text-slate-300">저장된 급등 관측 결과를 불러오는 중…</p>}
        {error && <p role="alert" className="text-sm leading-6 text-amber-200">{error === 'access' ? '급등 이유 역추적 이용 권한을 확인해 주세요. 로그인 상태와 AI 브레인 구독을 확인하세요.' : '급등 결과 조회가 지연되고 있습니다. 잠시 후 저장 결과를 다시 조회해 주세요.'}</p>}
        {view && <><div className="space-y-2 rounded-lg border border-slate-700 bg-[#101318] p-3 text-xs leading-5 text-slate-300"><p className="font-semibold text-sky-200">{states[view.status] ?? '미확인'} · {sourceStates[view.operation.source_status] ?? '시세 자료 상태 미확인'}</p><p>선정 기준 등락률 +{view.threshold.change_pct.toLocaleString('ko-KR')}% 이상 · 거래대금 {money(view.threshold.trading_value)} 이상</p>
            <p>시세 자료 <Time value={view.source_as_of} /> · 저장 결과 <Time value={view.generated_at} /> · 한국시간</p><p>서비스 최초 발견은 실제 급등 시작 시각이 아닙니다.</p></div>
            {view.items.length > 0 && <div><label htmlFor={search} className="mb-2 block text-xs font-semibold text-slate-300">급등 종목 이름 또는 코드 검색</label><input id={search} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="종목명 또는 6자리 코드" className="min-h-11 w-full min-w-0 rounded-lg border border-[#526a83] bg-[#101318] px-3 text-sm text-white placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300" /></div>}
            {rows.length ? <div className="min-w-0 space-y-3">{rows.map(row => <Trace key={row.id} row={row} />)}</div> : <div className="rounded-lg border border-slate-700 p-4 text-sm leading-6 text-slate-300"><p>{view.items.length ? '저장된 결과에 일치하는 종목이 없습니다.' : '현재 표시할 급등 관측 결과가 없습니다.'}</p><p className="mt-1 text-xs text-slate-400">{states[view.status] ?? '결과 상태 미확인'}</p></div>}
            <details className="border-t border-slate-700 text-xs leading-5 text-slate-300"><summary className="flex min-h-11 cursor-pointer items-center font-semibold text-sky-200">수집 작업 상태</summary><div className="space-y-1 pb-2"><p>작업 상태 {({ ready: '완료', running: '진행 중', partial: '일부 미완료', waiting: '대기', error: '수집 실패', unavailable: '이용 불가' } as Record<string, string>)[view.operation.state] ?? '미확인'}</p><p>마지막 실행 <Time value={view.operation.last_run_at} /></p><p>처리 {view.operation.processed ?? '미확인'} · 대기 {view.operation.pending ?? '미확인'}</p></div></details>
        </>}
        <p className="text-xs leading-5 text-slate-400">30초마다 저장 결과 조회 · 추가 유료 AI 호출 및 실계좌 주문 없음 · 재료 후보는 매수 승인이 아닙니다.</p>
    </section>;
}
export default function SurgeTracePanel({ token }: { token?: string }) {
    return <SavedSurgeTraces key={token ?? 'anonymous'} />;
}
