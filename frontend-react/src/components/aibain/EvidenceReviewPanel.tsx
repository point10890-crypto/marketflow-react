import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { fetchEvidenceReviews, evidenceSourceUrl, type EvidenceFinding, type EvidenceReview, type EvidenceReviewSnapshot, type ReviewKind } from '@/lib/evidenceReview';

interface Props {
    kind: ReviewKind; token?: string; articleIds?: string[];
    binding?: { decision_id: string; input_fingerprint: string } | null; blocked?: boolean;
}
const timeFormat = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const providers: Record<string, string> = { anthropic: 'Anthropic', deepseek: 'DeepSeek', openai: 'OpenAI' };
const fallbackReasons: Record<string, string> = {
    insufficient_balance: '기본 모델 크레딧 부족', authentication: '기본 모델 연결 확인 필요',
    model_unavailable: '기본 모델 이용 불가', breaker_open: '기본 모델 연결 지연', budget_exhausted: '설정한 분석 예산 도달',
    insufficient_credit: '기본 모델 크레딧 부족', credit_exhausted: '기본 모델 크레딧 부족', insufficient_credits: '기본 모델 크레딧 부족',
    budget_exceeded: '설정한 분석 예산 도달', budget_blocked: '설정한 분석 예산 도달', daily_budget_exhausted: '설정한 분석 예산 도달',
    authentication_error: '기본 모델 연결 확인 필요', auth_error: '기본 모델 연결 확인 필요',
    timeout: '기본 모델 응답 지연', provider_unavailable: '기본 모델 연결 지연', circuit_open: '기본 모델 연결 지연',
};
const sourceStatus: Record<string, string> = { reported_unverified: '보도 내용 · 확인 대기', verified_numeric_claims: '공시 수치 대조 완료',
    verified: '대조 완료', unverified: '확인 대기', no_matching_filing: '대응 공시 확인 대기', sealed: '저장된 정량 분석' };
const claimStatus: Record<EvidenceFinding['claim_status'], string> = { reported: '원문 보고', inference: 'AI 해석', verified: '공시 수치 대조', missing: '미확인' };
function Time({ value }: { value: string | null }) {
    return value ? <time dateTime={value}>{timeFormat.format(Date.parse(value))}</time> : <span>미확인</span>;
}
function Findings({ title, items }: { title: string; items: EvidenceFinding[] }) {
    return <div className="min-w-0"><dt className="font-semibold text-slate-100">{title}</dt><dd className="mt-1 text-slate-300">
        {items.length ? <ul className="space-y-2">{items.map((item, index) => <li key={index}><span className="mr-1.5 text-xs font-medium text-slate-400">{claimStatus[item.claim_status]}</span><span>{item.text}</span></li>)}</ul> : '검증을 통과한 해석 없음'}
    </dd></div>;
}
function Review({ review, kind }: { review: EvidenceReview; kind: ReviewKind }) {
    const successful = review.status === 'SUCCESS_PRIMARY' || review.status === 'SUCCESS_FALLBACK';
    const provider = review.provider ? providers[review.provider] ?? review.provider : '확인되지 않음';
    return <article className="min-w-0 space-y-3 break-words rounded-lg border border-[#425565] p-3 [overflow-wrap:anywhere]">
        {kind === 'article' && <h4 className="text-sm font-semibold text-slate-100">{review.sources.find(source => source.url?.includes('businesspost.co.kr'))?.title ?? '기사 재료 검토'}</h4>}
        {kind === 'candidate' && <p className="text-sm font-semibold text-slate-100">{review.candidate_basis === 'research_watchlist' ? `연구 후보 ${review.rows.length}종목 비교` : `상위 후보 ${review.rows.length}종목 비교`}</p>}
        <div className="space-y-1 text-xs leading-5">
            <p className={successful ? 'text-sky-200' : 'text-amber-200'}>{review.status === 'SUCCESS_FALLBACK' ? '대체 분석' : review.status === 'SUCCESS_PRIMARY' ? 'AI 분석' : review.status === 'IN_PROGRESS' ? '분석 준비 중' : 'AI 확인 미완료 · 저장 근거'}{successful ? ` · ${provider} · ${review.model}` : ''}</p>
            {review.fallback_reason && <p className="text-amber-200">{fallbackReasons[review.fallback_reason] ?? '기본 모델 분석을 완료하지 못해 저장 가능한 근거를 표시합니다.'}</p>}
            {(review.omitted_findings ?? 0) > 0 && <p className="text-amber-200">근거 검증을 통과하지 못한 해석 {review.omitted_findings}개 제외</p>}
            {review.freshness === 'stale' && <p className="text-amber-200">이전 자료 기준 · 최신 자료 반영 대기</p>}
            {review.candidate_basis === 'research_watchlist' && <p className="text-slate-300">연구 관찰 후보의 근거 비교입니다. 기존 판단{review.original_status === 'held' ? ' 보류 상태' : ''}와 가격·비중을 유지합니다.</p>}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-400"><span>분석 작성 <Time value={review.generated_at} /></span><span>자료 기준 <Time value={review.source_cutoff_at} /></span>{kind === 'candidate' && review.source_origin_at && <span>선정 기준 <Time value={review.source_origin_at} /></span>}<span>한국시간</span></div>
        </div>
        <ol className="space-y-3">{review.rows.map((row, index) => <li key={row.symbol} className="min-w-0 border-t border-[#30363f] pt-3">
            <h5 className="mb-2 text-sm font-semibold text-slate-100">{kind === 'candidate' ? `${index + 1}. ` : ''}{row.name} <span className="font-normal text-slate-400">{row.symbol} · 한국</span></h5>
            <dl className="grid min-w-0 gap-3 text-sm leading-6 md:grid-cols-3"><Findings title="주목할 근거" items={row.strengths} /><Findings title="주의할 점" items={row.risks} /><Findings title="다음 확인" items={row.what_to_watch} /></dl>
        </li>)}</ol>
        <details className="min-w-0 border-t border-[#30363f] pt-1 text-xs leading-5"><summary className="flex min-h-11 cursor-pointer items-center font-medium text-sky-200">출처·인용 확인 ({review.sources.length}개)</summary>
            <ul className="space-y-3 pb-1">{review.sources.map(source => {
                const url = evidenceSourceUrl(source.url);
                const quotes = [...new Set(review.rows.flatMap(row => [...row.strengths, ...row.risks, ...row.what_to_watch])
                    .flatMap(finding => finding.quotes).filter(quote => quote.evidence_id === source.evidence_id).map(quote => quote.quote))];
                return <li key={source.evidence_id} className="min-w-0 space-y-1 text-slate-300">{url
                    ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-sky-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300">{source.title}</a>
                    : <p>{source.title}</p>}
                    <p>{source.source} · {sourceStatus[source.verification_status] ?? '검증 상태 확인 필요'}</p>
                    {kind === 'candidate' && typeof source.available_at_original_decision === 'boolean' && <p className="text-slate-400">{source.available_at_original_decision ? '선정 당시 자료' : '선정 이후 추가 자료'}</p>}
                    <div className="flex flex-wrap gap-x-3 text-slate-400"><span>발행 <Time value={source.published_at} /></span><span>수집 <Time value={source.fetched_at} /></span></div>
                    {quotes.map(quote => <blockquote key={quote} className="border-l-2 border-[#425565] pl-2 text-slate-300">“{quote}”</blockquote>)}
                </li>;
            })}</ul>
        </details>
    </article>;
}

function SavedReviews({ kind, token, articleIds, binding, blocked = false }: Props) {
    const heading = useId();
    const [view, setView] = useState<EvidenceReviewSnapshot | null>(null);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const [limit, setLimit] = useState(3);
    const mounted = useRef(false); const pending = useRef(false); const denied = useRef(false);
    const controller = useRef<AbortController | null>(null);
    const refresh = useCallback(async () => {
        if (!mounted.current || pending.current || denied.current) return;
        pending.current = true; const request = new AbortController(); controller.current = request;
        try {
            const next = await fetchEvidenceReviews(kind, token, request.signal);
            if (mounted.current && !request.signal.aborted) { setView(next); setError(null); }
        } catch (failure) {
            if (!mounted.current || request.signal.aborted) return;
            if (failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status))) {
                denied.current = true; setView(null); setError('access');
            } else setError('unavailable');
        } finally { if (controller.current === request) pending.current = false; }
    }, [kind, token]);
    useEffect(() => {
        mounted.current = true;
        if (document.visibilityState === 'visible') void refresh();
        return () => { mounted.current = false; controller.current?.abort(); pending.current = false; };
    }, [refresh]);
    useAutoRefresh(refresh, 300_000, error !== 'access');
    const visible = blocked ? [] : view?.items.filter(review => kind === 'article' ? articleIds?.includes(review.article_id ?? '')
        : !!binding && review.decision_id === binding.decision_id && review.source_input_fingerprint === binding.input_fingerprint) ?? [];
    return <section aria-labelledby={heading} className="my-4 min-w-0 space-y-3 border-t border-[#30363f] pt-4">
        <header><h3 id={heading} className="ai-section-title text-base">{kind === 'article' ? '재료 AI 분석' : '상위 후보 근거 비교'}</h3>
            <p className="mt-1 text-xs leading-5 text-slate-400">저장된 자료를 해석한 참고 분석입니다. {kind === 'candidate' ? '원래 후보 순서와 정량 판단을 유지합니다.' : '공시·시세 검증과 함께 확인하세요.'}</p></header>
        {error === 'access' ? <p role="alert" className="text-xs text-amber-200">AI 분석의 접근 권한을 확인해 주세요.</p> : <>
            {error === 'unavailable' && <p role="status" className="text-xs text-amber-200">조회 지연{visible.length ? ' · 이전 저장 결과 표시 중' : ' · 저장된 분석 확인 대기'}</p>}
            {!view && !error && <p role="status" className="min-h-12 text-xs text-slate-300">저장된 AI 분석을 불러오는 중입니다.</p>}
            {view && !visible.length && <p className="text-xs leading-5 text-slate-300">{blocked || kind === 'candidate' && !binding ? '현재 선정 자료 확인 후 비교를 표시합니다.' : '현재 자료에 연결된 AI 분석을 기다리고 있습니다.'}</p>}
            {view && visible.length > 0 && (['unavailable', 'stale'].includes(view.status)
                || view.status === 'degraded' && visible.some(review => !['SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'].includes(review.status) || review.freshness === 'stale'))
                && <p className="text-xs text-amber-200">분석 갱신 지연 · 각 결과의 작성 시각과 자료 기준을 확인하세요.</p>}
            <div className="space-y-3">{visible.slice(0, limit).map(review => <Review key={review.id} review={review} kind={kind} />)}</div>
            {visible.length > limit && <button type="button" onClick={() => setLimit(value => value + 3)} className="min-h-11 rounded-lg border border-[#526a83] px-3 text-xs font-medium text-sky-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300">저장 분석 더 보기 ({visible.length - limit}건)</button>}
        </>}
    </section>;
}
export default function EvidenceReviewPanel(props: Props) {
    // A changed account cannot inherit an in-memory saved review or pending request.
    return <SavedReviews key={`${props.kind}:${props.token ?? 'current-auth'}`} {...props} />;
}
