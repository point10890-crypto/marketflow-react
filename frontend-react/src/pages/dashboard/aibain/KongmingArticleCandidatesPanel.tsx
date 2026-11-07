import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { ApiError, fetchAPI } from '@/lib/api';

const endpoint = '/api/admin/mirofish/kongming/article-candidates';
const refreshMs = 30_000;
const pageSize = 6;
const refreshButton = 'min-h-11 rounded-lg border border-[#526a83] px-3 py-2 font-medium text-sky-200 hover:bg-sky-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50';
const publisherUrl = /^https:\/\/www\.businesspost\.co\.kr\/BP\?command=article_view&num=[1-9]\d{0,9}$/;
const timeFormat = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit',
});

const categoryLabels: Record<string, string> = {
    contract: '계약·수주',
    earnings: '실적',
    capital_policy: '자본정책·행동주의',
    capacity: '설비·증설',
    regulatory: '허가·규제',
    risk: '위험',
    industry: '산업',
};

const certaintyLabels: Record<string, string> = {
    reported_unverified: '보도 내용',
    forecast: '전망 포함',
    opinion: '의견 기사',
};

const operationLabels = {
    ready: '최근 수집 성공',
    partial: '일부 수집 지연',
    error: '자동 수집 오류',
    waiting: '첫 자동 수집 대기',
};

interface ArticleCandidate {
    id: string;
    title: string;
    url: string;
    published_at: string;
    first_seen_at: string | null;
    entities: { symbol: string; name: string }[];
    event: { type: string; certainty: string };
    freshness: 'recent' | 'older_context';
    provenance?: 'kongming_archive' | 'marketflow_rss';
}

interface ArticleCandidates {
    items: ArticleCandidate[];
    candidate_article_count: number;
    recent_candidate_article_count: number;
    computed_at?: string | null;
    issuer_source_as_of?: string | null;
    operation: {
        state: keyof typeof operationLabels;
        last_poll_at?: string | null;
        next_poll_at?: string | null;
        last_body_received_at?: string | null;
        latest_published_at?: string | null;
    };
}

function validSnapshot(view: ArticleCandidates) {
    return Array.isArray(view?.items) && typeof operationLabels[view.operation?.state] === 'string'
        && Number.isInteger(view.candidate_article_count) && Number.isInteger(view.recent_candidate_article_count)
        && view.items.every(row => row && typeof row.id === 'string' && typeof row.title === 'string'
            && typeof row.url === 'string' && (row.freshness === 'recent' || row.freshness === 'older_context')
            && typeof row.event?.type === 'string' && typeof row.event.certainty === 'string'
            && Array.isArray(row.entities) && row.entities.every(entity => entity
                && typeof entity.symbol === 'string' && typeof entity.name === 'string'));
}

function ArticleTime({ value }: { value?: string | null }) {
    const timestamp = value ? Date.parse(value) : NaN;
    return value && Number.isFinite(timestamp)
        ? <time dateTime={value}>{timeFormat.format(timestamp)}</time>
        : <span>미확인</span>;
}

function articleLabel(labels: Record<string, string>, key: string, fallback: string) {
    return typeof labels[key] === 'string' ? labels[key] : fallback;
}

function verificationLink(articleId?: string) {
    return { search: articleId ? `?${new URLSearchParams({ article_id: articleId })}` : '', hash: '#catalyst-validation' };
}

function CandidateList({ items, label }: { items: ArticleCandidate[]; label: string }) {
    const [limit, setLimit] = useState(pageSize);
    if (!items.length) return <p className="py-2 text-slate-300">표시할 후보 기사가 없습니다.</p>;
    return (
        <>
            <ul className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
                {items.slice(0, limit).map(row => (
                    <li key={row.id} className="min-w-0 space-y-2 break-words rounded-xl border border-[#425565] p-3">
                        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300">
                            {row.entities.map(({ symbol, name }) => (
                                <span key={symbol}>{name} <code className="text-slate-400">{symbol}</code></span>
                            ))}
                        </div>
                        <h4 className="text-sm font-semibold leading-6 sm:text-base">
                            {publisherUrl.test(row.url) ? (
                                <a className="text-sky-300 underline-offset-4 hover:underline focus-visible:underline"
                                    href={row.url} target="_blank" rel="noopener noreferrer">{row.title}</a>
                            ) : row.title}
                        </h4>
                        <p className="text-xs text-slate-300">
                            {articleLabel(categoryLabels, row.event.type, '기타 재료')} · {articleLabel(certaintyLabels, row.event.certainty, '보도 유형 미확인')}
                        </p>
                        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs leading-5 text-slate-400">
                            <span>발행 <ArticleTime value={row.published_at} /></span>
                            <span>{row.provenance === 'kongming_archive' ? '원본 최초 수신' : '최초 수신'} <ArticleTime value={row.first_seen_at} /></span>
                        </div>
                        <Link className="inline-flex min-h-8 items-center text-xs font-semibold text-sky-300 underline-offset-4 hover:underline focus-visible:underline"
                            to={verificationLink(row.id)} aria-label={`${row.title} 공시·시세 검증 보기`}>공시·시세 검증 보기</Link>
                    </li>
                ))}
            </ul>
            {items.length > limit && (
                <button type="button" className={`mt-3 ${refreshButton}`}
                    onClick={() => setLimit(value => value + pageSize)}>
                    {label} 더 보기 ({items.length - limit}건)
                </button>
            )}
        </>
    );
}

export default function KongmingArticleCandidatesPanel() {
    const [view, setView] = useState<ArticleCandidates | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const mounted = useRef(false);
    const pending = useRef(false);
    const denied = useRef(false);

    const refresh = useCallback(async () => {
        if (pending.current || denied.current) return;
        pending.current = true;
        setBusy(true);
        try {
            const data = await fetchAPI<ArticleCandidates>(endpoint, 8000);
            if (!validSnapshot(data)) throw new Error('Invalid article candidates snapshot');
            if (mounted.current) {
                setView(data);
                setError(null);
            }
        } catch (failure) {
            if (!mounted.current) return;
            if (failure instanceof ApiError && (failure.status === 401 || failure.status === 403)) {
                denied.current = true;
                setView(null);
                setError('access');
            } else {
                setError('unavailable');
            }
        } finally {
            pending.current = false;
            if (mounted.current) setBusy(false);
        }
    }, []);

    useEffect(() => {
        mounted.current = true;
        if (document.visibilityState === 'visible') void refresh();
        return () => { mounted.current = false; };
    }, [refresh]);
    useAutoRefresh(refresh, refreshMs, error !== 'access');

    const recent = view?.items.filter(row => row.freshness === 'recent') ?? [];
    const archive = view?.items.filter(row => row.freshness === 'older_context') ?? [];
    const operation = view?.operation;

    return (
        <section id="article-candidates" className="ai-panel min-w-0 space-y-3 border border-[#30363f] p-4 sm:p-5"
            aria-labelledby="kongming-article-candidates-title">
            <header className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="kongming-article-candidates-title" className="ai-section-title text-lg">검출된 후보 리스트 · 기사 재료</h2>
                {error !== 'access' && (
                    <button type="button" disabled={busy} onClick={() => void refresh()} className={refreshButton}>
                        기사 후보 갱신
                    </button>
                )}
            </header>
            <p className="text-slate-300">
                비즈니스포스트 RSS에서 선별한 관찰 후보입니다. 각 기사에서 MarketFlow의 공시·시세 검증을 확인할 수 있습니다.
                {' '}<Link to={verificationLink()} className="text-sky-300 underline-offset-2 hover:underline">전체 검증 결과 보기</Link>
            </p>
            {error === 'access' && <p role="alert" className="text-amber-300">기사 후보 목록의 접근 권한을 확인해 주세요.</p>}
            {error === 'unavailable' && <p role="alert" className="text-amber-300">기사 후보 조회 실패{view ? ' · 이전 목록 표시 중' : ''}</p>}
            {!view && !error && <p role="status" className="text-slate-300">저장된 기사 후보를 불러오는 중입니다.</p>}
            {view && operation && (
                <>
                    <div className="space-y-1 rounded-lg border border-[#30363f] p-3 text-xs leading-5 text-slate-300">
                        <p>
                            <strong className={operation.state === 'ready' ? 'text-sky-200' : 'text-amber-300'}>
                                {error ? '수집 상태 확인 중' : operationLabels[operation.state]}
                            </strong>
                            {' · 화면 '}{refreshMs / 1000}초 조회 · 전체 후보 {view.candidate_article_count}건 · 한국시간
                        </p>
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                            <span>최근 수집 확인 <ArticleTime value={operation.last_poll_at} /></span>
                            <span>다음 수집 예정 <ArticleTime value={operation.next_poll_at} /></span>
                            <span>피드 최신 발행 <ArticleTime value={operation.latest_published_at} /></span>
                            <span>피드 마지막 수신 <ArticleTime value={operation.last_body_received_at} /></span>
                            <span>목록 갱신 <ArticleTime value={view.computed_at} /></span>
                            <span>종목 원장 기준일 {view.issuer_source_as_of ?? '미확인'}</span>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <h3 className="ai-section-title text-base">최근 72시간 발행 · {view.recent_candidate_article_count}건</h3>
                        <CandidateList items={recent} label="최근 기사" />
                    </div>
                    <details className="rounded-lg border border-[#30363f] p-3">
                        <summary className="cursor-pointer font-medium text-slate-100">이전 기사 · {archive.length}건</summary>
                        <div className="mt-3"><CandidateList items={archive} label="이전 기사" /></div>
                    </details>
                </>
            )}
        </section>
    );
}
