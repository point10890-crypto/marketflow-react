import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { catalystOutcomeSourceUrl, fetchCatalystOutcomes, type CatalystCandidate, type CatalystHorizon,
    type CatalystOutcomeCase, type CatalystOutcomes, type OutcomeFilter } from '@/lib/catalystOutcomes';

const clock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
const percent = new Intl.NumberFormat('ko-KR', { style: 'percent', maximumFractionDigits: 2, signDisplay: 'exceptZero' });
const amount = (value: number) => `${Math.round(value).toLocaleString('ko-KR')}원`;
const button = 'min-h-11 rounded-lg border border-[#425565] px-3 text-sm font-semibold text-sky-200 hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50';
const statusLabels: Record<CatalystOutcomes['status'], string> = { ready: '저장 결과 확인', partial: '일부 자료 수집 중', missing: '첫 저장 결과 대기', stale: '자료 갱신 지연', failed: '자료 갱신 실패' };
const horizonLabels: Record<CatalystHorizon['status'], string> = { completed: '완료', pending: '관측 중', missing: '가격 누락', blocked: '검증 제외', revised: '원본 수정 · 제외' };
const verificationLabels: Record<string, string> = {
    verified_numeric_claims: '보도 내 명시 금액 대조 통과', related_filing_found: '관련 공시 확인 · 보도 주장 미확정',
    verified: '저장 검증 근거 있음 · 범위 확인 필요', no_matching_filing: '관련 공시 미발견',
    unverified: '검증 대기', pending: '검증 대기', waiting: '검증 대기', source_unavailable: '검증 자료 누락',
    reported: '보도 내용 · 별도 대조 필요', not_verified: '별도 대조 미완료',
};
const sourceLabels: Record<string, string> = { verification: '보존 검증 재료', businesspost: '비즈니스포스트', omni: '저장 매체 뉴스', surge_trace: '급등 추적 근거' };
function Time({ value }: { value: string | null }) {
    return value ? <time dateTime={value}>{/^\d{4}-\d{2}-\d{2}$/.test(value) ? value : clock.format(Date.parse(value))}</time> : <>미확인</>;
}
function SourceTitle({ title, url }: { title: string; url: string | null }) {
    const href = catalystOutcomeSourceUrl(url);
    return href ? <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-sky-200 underline decoration-sky-600 underline-offset-4">{title}</a> : <p>{title}</p>;
}
function Verification({ value }: { value: string }) {
    return <span>{verificationLabels[value] ?? '검증 범위 미확인'}</span>;
}
function Candidate({ row }: { row: CatalystCandidate }) {
    return <article aria-label={`상승 지속 후보 ${row.rank}위 ${row.name}`} className="min-w-0 space-y-3 rounded-xl border border-[#425565] bg-[#10181f] p-3 [overflow-wrap:anywhere] sm:p-4">
        <header className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><h4 className="text-lg font-bold text-white">{row.rank}. {row.name}</h4><p className="text-xs text-slate-400">{row.symbol} · 한국 주식</p></div><p className="text-sm font-semibold tabular-nums text-sky-200">점수 {row.score.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}</p></header>
        <ul className="space-y-1 text-sm leading-6 text-slate-200">{row.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
        <p className="text-xs leading-5 text-slate-300">과거 상승 {row.historical.positive} / 완료 {row.historical.matured}건 · 평균 순수익 {percent.format(row.historical.mean_net_return)}</p>
        <div className="space-y-2 border-t border-slate-700 pt-3"><p className="text-xs text-slate-300">{row.price_session} KIS 완료 일봉 · 기준가 {amount(row.price)}</p>
            <dl className="grid min-w-0 grid-cols-3 gap-2 text-xs leading-5">{([['참고 진입', row.plan.entry_price], ['참고 손절', row.plan.stop_price], ['참고 목표', row.plan.target_price]] as const).map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-slate-400">{label}</dt><dd className="font-semibold tabular-nums text-white">{amount(value)}</dd></div>)}</dl>
            <p className="text-xs leading-5 text-slate-400">완료 일봉의 참고 가격입니다. 현재 체결 가격과 다를 수 있습니다.</p></div>
        <div className="text-xs leading-5"><p className="font-semibold text-amber-200">후보 해제·재확인 조건</p><ul className="mt-1 space-y-1 text-slate-300">{row.invalidation.map((reason, i) => <li key={i}>{reason}</li>)}</ul></div>
        <div className="space-y-1 border-t border-slate-700 pt-1 text-xs leading-5"><SourceTitle title={row.latest_event.title} url={row.latest_event.url} />
            <p className="text-slate-300"><Verification value={row.latest_event.verification} /></p><p className="text-slate-400">최초 수집 <Time value={row.latest_event.first_seen_at} /></p><p className="text-slate-400">가격 수집 <Time value={row.price_fetched_at} /></p></div>
        <Link to={`/dashboard/ai-bain/chart-predict?code=${row.symbol}`} className={`${button} flex items-center justify-center`} aria-label={`${row.name} 차트·가격 보기`}>차트·가격 보기</Link>
    </article>;
}
function OutcomeCase({ row }: { row: CatalystOutcomeCase }) {
    return <article aria-label={`${row.name} 과거 재료 ${row.id}`} className="min-w-0 space-y-3 rounded-lg border border-slate-700 p-3 text-sm leading-6 [overflow-wrap:anywhere] sm:p-4">
        <header><h4 className="font-semibold text-white">{row.name} <span className="text-xs font-normal text-slate-400">{row.symbol}</span></h4><SourceTitle title={row.title} url={row.url} /></header>
        <div className="space-y-1 text-xs leading-5 text-slate-300"><p>{sourceLabels[row.source] ?? row.source} · <Verification value={row.verification} /></p>
            <p className={row.analysis_basis === 'retrospective' ? 'text-amber-200' : 'text-sky-200'}>{row.analysis_basis === 'retrospective' ? '사후 수집 · 예측 통계 제외' : '당시 수신 기록 기준'}</p>
            {row.exclusion && <p className="font-semibold text-amber-200">{row.exclusion === 'withdrawn' ? '철회된 재료 · 통계·후보 선정 제외' : '분석 제외 · 근거 확인 필요'}</p>}
            <p>발행 시각 <Time value={row.published_at} /></p><p>수신 시각 <Time value={row.first_seen_at} /></p></div>
        <dl className="grid min-w-0 grid-cols-3 gap-2 rounded-lg bg-[#10181f] p-2 text-xs leading-5">{(['5', '10', '20'] as const).map(days => {
            const h = row.horizons[days]; const revised = h.source_revision || h.status === 'revised';
            const completed = h.status === 'completed' && !revised;
            return <div key={days} className="min-w-0"><dt className="text-slate-400">{days}거래일</dt><dd className="font-semibold tabular-nums text-slate-100">{completed && h.net_return !== null ? percent.format(h.net_return) : revised ? '원본 수정' : horizonLabels[h.status]}</dd><dd className="text-slate-400">{completed ? row.exclusion ? '보존 수익 · 통계 제외' : '비용 반영 순수익' : revised || row.exclusion ? '통계 제외' : '수익 미확정'}</dd></div>;
        })}</dl>
        <details className="min-w-0 text-xs leading-5 text-slate-300"><summary className="flex min-h-11 cursor-pointer items-center font-semibold text-sky-200">진입·청산과 가격 근거</summary><div className="space-y-3 pb-1">
            <p>관측 기준 <Time value={row.anchor_at} /> · 기준일 다음 거래일 종가 진입</p>
            {(['5', '10', '20'] as const).map(days => { const h = row.horizons[days]; return <div key={days} className="space-y-1 border-t border-slate-700 pt-2"><p className="font-semibold text-white">{days}거래일 · {h.source_revision ? '원본 수정 · 통계 제외' : horizonLabels[h.status]}</p>
                <p>진입 {h.entry_date ?? '대기'} · {h.entry_price === null ? '가격 미확인' : amount(h.entry_price)}</p><p>청산 {h.exit_date ?? '대기'} · {h.exit_price === null ? '가격 미확인' : amount(h.exit_price)}</p>
                <p>비용 전 {h.gross_return === null ? '미확인' : percent.format(h.gross_return)} · 종가 기준 최대 상승 {h.mfe === null ? '미확인' : percent.format(h.mfe)} · 종가 기준 최대 하락 {h.mae === null ? '미확인' : percent.format(h.mae)}</p>
            </div>; })}<p>가격 출처 {row.price_source} · 수집 <Time value={row.price_fetched_at} /></p></div></details>
    </article>;
}

function SavedOutcomes({ token }: { token?: string }) {
    const heading = useId(); const inputId = useId();
    const [filter, setFilter] = useState<OutcomeFilter>('rising'); const [page, setPage] = useState(1);
    const [code, setCode] = useState(''); const [symbol, setSymbol] = useState<string | undefined>(); const [searchError, setSearchError] = useState('');
    const [view, setView] = useState<CatalystOutcomes | null>(null); const [loading, setLoading] = useState(true);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const mounted = useRef(false); const pending = useRef(false); const denied = useRef(false); const controller = useRef<AbortController | null>(null);
    const refresh = useCallback(async () => {
        if (!mounted.current || pending.current || denied.current || document.visibilityState !== 'visible') return;
        const request = new AbortController(); controller.current = request; pending.current = true; setLoading(true);
        try {
            const result = await fetchCatalystOutcomes({ filter, page, page_size: 10, symbol }, token, request.signal);
            if (mounted.current && !request.signal.aborted && controller.current === request) { setView(result); setError(null); }
        } catch (failure) {
            if (!mounted.current || request.signal.aborted || controller.current !== request) return;
            setView(null);
            const access = failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status));
            denied.current = access; setError(access ? 'access' : 'unavailable');
        } finally {
            if (controller.current === request) { pending.current = false; if (mounted.current) setLoading(false); }
        }
    }, [filter, page, symbol, token]);
    useEffect(() => {
        mounted.current = true; setView(null); setLoading(true);
        void refresh();
        return () => { mounted.current = false; controller.current?.abort(); pending.current = false; };
    }, [refresh]);
    useAutoRefresh(refresh, 30000, error !== 'access');
    const search = (event: FormEvent) => {
        event.preventDefault(); const next = code.trim();
        if (next && !/^\d{6}$/.test(next)) { setSearchError('종목 코드는 숫자 6자리로 입력해 주세요.'); return; }
        setSearchError(''); setSymbol(next || undefined); setPage(1);
    };
    const analysisCompletedWithGaps = view?.operation.state === 'complete_with_gaps';
    return <section id="catalyst-outcomes" aria-labelledby={heading} className="ai-panel min-w-0 scroll-mt-20 space-y-4 border border-[#365372] p-3 [overflow-wrap:anywhere] sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 id={heading} className="ai-section-title text-xl">재료 이후 상승 추적</h2><p className="mt-2 text-sm leading-6 text-slate-300">보존한 뉴스·공시 재료의 이후 성과와 지금 다시 살펴볼 상승 지속 후보를 확인합니다.</p></div>
            <button type="button" onClick={() => void refresh()} disabled={loading || error === 'access'} className={button} aria-label="상승 추적 저장 결과 새로고침">저장 결과 새로고침</button></header>
        <p className="text-xs leading-5 text-slate-400">매일 10:00 · 15:00 갱신 (한국시간) · 화면이 보일 때 30초마다 저장 결과 조회</p>
        {loading && !view && <p role="status" className="py-3 text-sm text-slate-300">저장된 상승 추적을 불러오는 중…</p>}
        {error && <p role="alert" className="text-sm text-amber-200">{error === 'access' ? '상승 추적 이용 권한을 확인해 주세요. 로그인 상태와 공명 이용 권한을 확인하세요.' : '상승 추적 조회가 지연되고 있습니다. 잠시 후 저장 결과를 다시 조회해 주세요.'}</p>}
        {view && <>
            <div className="space-y-2 rounded-lg border border-slate-700 bg-[#101318] p-3 text-xs leading-5 text-slate-300"><p className={`font-semibold ${view.status === 'ready' ? 'text-sky-200' : 'text-amber-200'}`}>{view.status === 'partial' && analysisCompletedWithGaps ? '일부 원본 미완료 · 보존 기록 분석 완료' : view.status === 'partial' && view.operation.pending_symbols === 0 ? '일부 자료 누락 · 저장 결과 확인' : statusLabels[view.status]} · 가격 기준 {view.as_of_session ?? '미확인'}</p>
                <p>최근 갱신 <Time value={view.generated_at} /> · 다음 예정 <Time value={view.schedule.next_run_at} /></p>
                <p>보존 재료 {view.coverage.events_total}건 · 상승 {view.coverage.positive_events}건 / 완료 {view.coverage.matured_events}건</p>
                <p>상승·완료 집계는 철회된 재료를 제외합니다.</p>
                <p>가격 확보 {view.coverage.priced_symbols} / {view.coverage.symbols_total}종목 · 가격 미확보 {view.coverage.unpriced_events}건 · 검증 제외 {view.coverage.excluded_events}건</p>
                <p>가격 수집 대기 {view.operation.pending_symbols}종목 · 최근 시도 <Time value={view.operation.last_attempt_at} /></p>
                {view.operation.error && !(analysisCompletedWithGaps && view.operation.error === 'source_coverage_partial') && <p className="text-amber-200">일부 자료 처리에 실패했습니다. 완료된 자료는 보존하며 다음 실행에서 다시 확인합니다.</p>}
            </div>
            <div className="space-y-3"><h3 className="font-semibold text-white">상승 지속 후보 {view.candidates.length}종목</h3><p className="text-xs leading-5 text-slate-400">점수는 저장 근거의 비교 순위이며 수익 확률이 아닙니다. 과거 상승이 향후 수익을 보장하지 않습니다.</p>
                {view.candidates.length ? <div className="grid min-w-0 gap-3 lg:grid-cols-3">{view.candidates.map(row => <Candidate key={row.symbol} row={row} />)}</div> : <p className="rounded-lg border border-slate-700 p-3 text-sm text-slate-300">현재 조건을 통과한 상승 지속 후보가 없습니다.</p>}</div>
        </>}
        <div className="space-y-3 border-t border-slate-700 pt-4"><h3 className="font-semibold text-white">과거 재료 이후 성과</h3>
            <div className="flex flex-wrap gap-2" role="group" aria-label="과거 사례 범위">{([['rising', '상승 사례'], ['all', '전체 사례']] as const).map(([value, label]) => <button key={value} type="button" disabled={error === 'access'} aria-pressed={filter === value} onClick={() => { setFilter(value); setPage(1); }} className={`${button} ${filter === value ? 'bg-[#1b2c40] ring-1 ring-sky-600' : ''}`}>{label}</button>)}</div>
            <p className="text-xs leading-5 text-slate-400">상승 사례: 원본 수정 없는 10거래일 순수익 &gt; 0. 전체 사례에는 손실·관측 중·가격 누락도 포함합니다.</p>
            <form onSubmit={search} className="space-y-2"><label htmlFor={inputId} className="block text-xs font-semibold text-slate-300">종목 코드</label><div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-2"><input id={inputId} type="text" inputMode="numeric" autoComplete="off" value={code} maxLength={30} disabled={error === 'access'} aria-invalid={!!searchError} aria-describedby={searchError ? `${inputId}-error` : undefined} onChange={event => setCode(event.target.value)} placeholder="예: 005930" className="min-h-11 min-w-0 w-full rounded-lg border border-[#425565] bg-[#101318] px-3 text-base text-white placeholder:text-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300" /><button type="submit" disabled={error === 'access'} className={button}>검색</button></div>
                {searchError && <p id={`${inputId}-error`} role="alert" className="text-xs text-amber-200">{searchError}</p>}
                {symbol && <button type="button" disabled={error === 'access'} onClick={() => { setCode(''); setSymbol(undefined); setPage(1); setSearchError(''); }} className={button}>{symbol} 검색 해제</button>}</form>
            {view && <><p className="text-xs text-slate-300">조건에 맞는 {view.pagination.total}건 중 {view.cases.length}건 표시</p>
                {view.cases.length ? <div className="grid min-w-0 gap-3 md:grid-cols-2">{view.cases.map(row => <OutcomeCase key={row.id} row={row} />)}</div> : <p className="py-3 text-sm text-slate-300">현재 조회 조건에 맞는 저장 사례가 없습니다. 전체 사례 또는 다른 종목 코드를 확인하세요.</p>}
                <nav aria-label="과거 사례 페이지" className="flex flex-wrap items-center justify-between gap-2"><button type="button" className={button} disabled={page <= 1 || loading} onClick={() => setPage(current => Math.max(1, current - 1))} aria-label="이전 사례">이전</button><span className="text-xs tabular-nums text-slate-300">{view.pagination.page} / {Math.max(1, view.pagination.pages)} 페이지</span><button type="button" className={button} disabled={page >= view.pagination.pages || loading} onClick={() => setPage(current => current + 1)} aria-label="다음 사례">다음</button></nav>
            </>}
        </div>
        <div className="space-y-2 border-t border-slate-700 pt-3 text-xs leading-5 text-slate-400"><p>관측 기준일 다음 거래일 종가 진입 · 5/10/20거래일 종가 청산 · 수수료 5bp, 슬리피지 5bp, 매도세 20bp 가정. 최대 상승·하락은 종가 기준이며 장중 고가·저가를 반영하지 않습니다. 시장 대비 초과수익 검증 전입니다.</p>
            {view?.limitations.map((line, i) => <p key={i}>{line}</p>)}
            {view && <details><summary className="flex min-h-11 cursor-pointer items-center text-sky-200">보존 출처별 범위</summary><ul className="space-y-1 pb-2">{Object.entries(view.coverage.source_counts).map(([source, total]) => <li key={source}>{sourceLabels[source] ?? source} · {total}건</li>)}</ul></details>}
        </div>
    </section>;
}
export default function CatalystOutcomesPanel({ token }: { token?: string }) {
    return <SavedOutcomes key={token ?? 'anonymous'} token={token} />;
}
