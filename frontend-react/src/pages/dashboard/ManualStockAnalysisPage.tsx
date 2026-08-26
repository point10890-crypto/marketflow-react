import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE, authHeaders, fetchWithTimeout } from '@/lib/api';
import { getRunFreshness, type FreshnessLevel } from '@/lib/dataFreshness';
import { buildSuggestions, type SearchIndex } from '@/lib/searchSuggestions';

interface ManualRunSummary {
    run_id: string;
    title: string;
    created_at: string;
    updated_at?: string;
    record_count: number;
    source_record_count?: number;
    source_path?: string;
    source_kind: string;
    cycle_date?: string;
    cycle_number?: number | null;
    cycle_label?: string;
    status?: string;
    summary: Record<string, number>;
}

interface ManualRecord {
    rank: number;
    stock_name: string;
    ticker: string;
    market: string;
    industry: string;
    source_url: string;
    raw_result: string;
    result: string;
    analyzed_at: string;
    scrape_state?: 'pending' | 'scraping' | 'completed' | 'error';
    scrape_fallback?: string;
    stale_from?: string;
    error?: string;
    technical_result?: string;
    analyst_sentiment?: string;
    sector?: string;
    employees?: string;
    market_country?: string;
    target_price?: string;
    upside_potential?: string;
}

interface ManualRunDetail extends ManualRunSummary {
    filtered_count: number;
    records: ManualRecord[];
    /** Stocks that held a different opinion last cycle and are 적극 매수 now. */
    upgraded_count?: number;
}

interface ManualStockHistoryItem {
    run_id: string;
    cycle_label: string;
    run_title?: string;
    created_at: string;
    updated_at: string;
    rank?: number;
    stock_name: string;
    ticker: string;
    market: string;
    industry: string;
    result: string;
    raw_result?: string;
    analyzed_at: string;
    scrape_state?: string;
    technical_result?: string;
    analyst_sentiment?: string;
    target_price?: string;
    upside_potential?: string;
}

interface ManualStockHistory {
    query: string;
    target: {
        stock_name: string;
        ticker: string;
        market: string;
        industry: string;
    } | null;
    items: ManualStockHistoryItem[];
    count: number;
    truncated: boolean;
}

interface ScraperLoopStatus {
    running: boolean;
    state: string;
    max_rows: number;
    interval_sec: number;
    timeout_sec: number;
    source_path: string;
    source_record_count: number;
    cycle: number;
    mode?: string;
    auto_start?: boolean;
    current_cycle_label?: string;
    cycle_started_at?: string;
    iterations: number;
    processed: number;
    total: number;
    current_rank: number | null;
    current_stock: string;
    current_industry: string;
    current_result: string;
    last_run_id: string;
    last_record_count: number;
    last_started_at: string;
    last_finished_at: string;
    next_run_at: string;
    last_error: string;
    /** Newest run file's write time — the disk-truth liveness stamp, polled every 1-2.5s. */
    last_data_at?: string;
}

const DEFAULT_FILTERS = ['적극 매수', '매수', '중립', '매도', '적극 매도', '분석중', '오류'];

// Diverging bull -> bear scale (Korean convention: red = up/buy, blue = down/sell).
// Muted, cohesive tints so the dark shell stays calm; badge = chip style, solid = distribution bar.
const RESULT_STYLES: Record<string, { badge: string; solid: string; dot: string }> = {
    '적극 매수': { badge: 'text-rose-200 bg-rose-500/12 border-rose-400/25', solid: '#f43f5e', dot: 'bg-rose-400' },
    '매수': { badge: 'text-amber-200 bg-amber-500/12 border-amber-400/25', solid: '#f59e0b', dot: 'bg-amber-400' },
    '중립': { badge: 'text-slate-200 bg-slate-400/10 border-slate-300/20', solid: '#94a3b8', dot: 'bg-slate-400' },
    '매도': { badge: 'text-sky-200 bg-sky-500/12 border-sky-400/25', solid: '#38bdf8', dot: 'bg-sky-400' },
    '적극 매도': { badge: 'text-indigo-200 bg-indigo-500/12 border-indigo-400/25', solid: '#818cf8', dot: 'bg-indigo-400' },
    '분석중': { badge: 'text-violet-200 bg-violet-500/12 border-violet-400/25', solid: '#a78bfa', dot: 'bg-violet-400' },
    '오류': { badge: 'text-rose-300 bg-rose-600/12 border-rose-500/25', solid: '#fb7185', dot: 'bg-rose-500' },
};

const RATING_ORDER = ['적극 매수', '매수', '중립', '매도', '적극 매도'];

// Virtual filter (not a verdict): an earlier date held a different opinion, now 적극 매수.
// Compared day over day, not cycle over cycle -- verdicts do not move within a day.
// Deliberately outside RATING_ORDER so it never enters the distribution bar, whose
// segments must sum to the evaluated total.
const UPGRADE_FILTER = '적극매수 전환';

const LOOP_LABELS: Record<string, string> = {
    starting: '시작 중',
    scraping: '스크래핑 중',
    waiting: '대기 중',
    error_waiting: '오류 후 대기',
    blocked_waiting: '차단 감지 · 회복 대기',
    stopping: '중지 중',
    stopped: '중지됨',
};

// Friendly labels for internal scrape_fallback codes (avoid raw jargon in the UI).
const FALLBACK_LABELS: Record<string, string> = {
    collection_gap: '수집 지연',
    stale_cache: '직전값 유지',
    retry_fresh_session: '재시도 성공',
};

function fallbackLabel(code?: string) {
    if (!code) return '';
    return FALLBACK_LABELS[code] || code;
}

// Soften raw scraper exceptions (e.g. "RuntimeError: target page blocked: cloudflare").
function friendlyError(err?: string) {
    if (!err) return '';
    const lower = err.toLowerCase();
    if (lower.includes('cloudflare') || lower.includes('blocked') || lower.includes('captcha')) {
        return '일시적 수집 차단 (Cloudflare) · 잠시 후 자동 재수집';
    }
    if (lower.includes('timeout') || lower.includes('page load')) {
        return '페이지 응답 지연 · 자동 재수집';
    }
    return err;
}

function resultBadge(result: string) {
    return RESULT_STYLES[result]?.badge || 'text-slate-300 bg-white/5 border-white/10';
}

function resultSolid(result: string) {
    return RESULT_STYLES[result]?.solid || '#64748b';
}

function buildRunLabel(run: ManualRunSummary) {
    const created = run.created_at ? run.created_at.slice(0, 10) : '';
    if (run.cycle_label) return run.cycle_label;
    return `${created} · ${run.title || run.run_id}`;
}

function formatRunTimestamp(value?: string) {
    if (!value) return '--';
    return value.replace('T', ' ').slice(0, 16);
}

// Only standard Tailwind opacity steps (5/10/20/30/40/50): in-between values like
// /12 or /35 are not generated here and silently render with no background.
const FRESHNESS_STYLES: Record<FreshnessLevel, { pill: string; icon: string }> = {
    fresh: { pill: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200', icon: 'fa-circle-check' },
    warn: { pill: 'border-amber-400/40 bg-amber-500/20 text-amber-100', icon: 'fa-triangle-exclamation' },
    stale: { pill: 'border-rose-400/50 bg-rose-500/20 text-rose-100 animate-pulse', icon: 'fa-triangle-exclamation' },
    unknown: { pill: 'border-white/10 bg-white/5 text-slate-400', icon: 'fa-circle-question' },
};

function runStatusLabel(status?: string) {
    if (status === 'running') return '진행중';
    // Cut short by a Cloudflare block and queued to continue after the cool-off --
    // still the freshest data, so it stays selectable unlike a stale run.
    if (status === 'blocked') return '차단 대기';
    if (status === 'error') return '오류';
    if (status === 'completed') return '완료';
    return status || '기록';
}

function runStatusClass(status?: string) {
    if (status === 'running') return 'border-cyan-300/40 bg-cyan-400/15 text-cyan-100';
    if (status === 'blocked') return 'border-amber-400/40 bg-amber-500/20 text-amber-100';
    if (status === 'error') return 'border-rose-300/40 bg-rose-500/15 text-rose-100';
    if (status === 'completed') return 'border-emerald-300/35 bg-emerald-500/12 text-emerald-100';
    return 'border-white/10 bg-white/5 text-slate-300';
}

function summaryPreview(summary: Record<string, number> = {}) {
    return Object.entries(summary)
        .filter(([, count]) => Number(count) > 0)
        .slice(0, 3);
}

function formatSeconds(seconds: number) {
    if (!Number.isFinite(seconds)) return '--';
    if (seconds <= 0) return 'immediate';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.round(minutes / 60)}h`;
}

export default function ManualStockAnalysisPage() {
    const [runs, setRuns] = useState<ManualRunSummary[]>([]);
    const [filters, setFilters] = useState<string[]>([]);
    const [selectedRunId, setSelectedRunId] = useState('');
    const [selectedResult, setSelectedResult] = useState('all');
    const [query, setQuery] = useState('');
    const [searchIndex, setSearchIndex] = useState<SearchIndex | null>(null);
    const [suggestOpen, setSuggestOpen] = useState(false);
    const [suggestActive, setSuggestActive] = useState(0);
    const [detail, setDetail] = useState<ManualRunDetail | null>(null);
    const [stockHistory, setStockHistory] = useState<ManualStockHistory | null>(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyMessage, setHistoryMessage] = useState('');
    const [loopStatus, setLoopStatus] = useState<ScraperLoopStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const loopRunRef = useRef('');
    const pollInFlightRef = useRef(false);
    const hasManualRunSelectionRef = useRef(false);
    const selectedRunIdRef = useRef('');

    const selectedRun = useMemo(
        () => runs.find((run) => run.run_id === selectedRunId) || null,
        [runs, selectedRunId],
    );
    const selectedMatchesLoopRun = !!loopStatus?.last_run_id && selectedRunId === loopStatus.last_run_id;
    const isSelectedLoopRun = !!loopStatus?.running && selectedMatchesLoopRun;
    const isStoppedLoopRunSelection = selectedMatchesLoopRun && !loopStatus?.running;
    const shouldStreamSelectedRun = isSelectedLoopRun
        || (!isStoppedLoopRunSelection && selectedRun?.status === 'running');

    const fetchRuns = useCallback(async (preferredRunId?: string) => {
        setLoading(true);
        setMessage('');
        try {
            const res = await fetchWithTimeout(`${API_BASE}/api/manual-stock-analysis/runs`, {
                headers: authHeaders(),
            }, 15000);
            if (!res.ok) throw new Error(`회차 목록 조회 실패 (${res.status})`);
            const data = await res.json();
            const nextRuns: ManualRunSummary[] = data.runs || [];
            setRuns(nextRuns);
            setFilters((data.result_filters || DEFAULT_FILTERS).filter((filter: string) => filter !== '미분류'));
            const preferredRun = preferredRunId
                ? nextRuns.find((run) => run.run_id === preferredRunId && run.status !== 'stale')
                : null;
            const selectedRunCandidate = selectedRunId
                ? nextRuns.find((run) => run.run_id === selectedRunId)
                : null;
            const selectedIsStoppedLoopRun = !!selectedRunCandidate
                && selectedRunCandidate.run_id === loopStatus?.last_run_id
                && !loopStatus?.running;
            const selectedIsUsable = !!selectedRunCandidate
                && selectedRunCandidate.status !== 'stale'
                && !selectedIsStoppedLoopRun;
            const fallbackRun = nextRuns.find((run) => run.status !== 'stale');
            const nextSelected = preferredRun
                ? preferredRun.run_id
                : selectedIsUsable
                    ? selectedRunCandidate.run_id
                    : fallbackRun?.run_id || '';
            selectedRunIdRef.current = nextSelected;
            setSelectedRunId(nextSelected);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '회차 목록 조회 실패');
        } finally {
            setLoading(false);
        }
    }, [loopStatus?.last_run_id, loopStatus?.running, selectedRunId]);

    const fetchRunDetail = useCallback(async (options?: { silent?: boolean }) => {
        if (!selectedRunId) {
            setDetail(null);
            return;
        }
        const requestedRunId = selectedRunId;
        const silent = !!options?.silent;
        if (!silent) {
            setLoading(true);
            setMessage('');
        }
        const params = new URLSearchParams();
        params.set('result', selectedResult);
        if (query.trim()) params.set('q', query.trim());
        if (shouldStreamSelectedRun) {
            params.set('live', '1');
        }
        try {
            const res = await fetchWithTimeout(`${API_BASE}/api/manual-stock-analysis/runs/${requestedRunId}?${params.toString()}`, {
                headers: authHeaders(),
            }, 15000);
            if (!res.ok) throw new Error(`분석 목록 조회 실패 (${res.status})`);
            const nextDetail: ManualRunDetail = await res.json();
            if (selectedRunIdRef.current === requestedRunId) {
                setDetail(nextDetail);
            }
        } catch (err) {
            if (!silent) {
                setMessage(err instanceof Error ? err.message : '분석 목록 조회 실패');
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    }, [query, selectedResult, selectedRunId, shouldStreamSelectedRun]);

    const fetchLoopStatus = useCallback(async () => {
        try {
            const res = await fetchWithTimeout(`${API_BASE}/api/manual-stock-analysis/scraper-loop`, {
                headers: authHeaders(),
            }, 8000);
            if (!res.ok) return;
            const data: ScraperLoopStatus = await res.json();
            setLoopStatus(data);
            if (data.running && data.last_run_id && !hasManualRunSelectionRef.current && selectedRunId !== data.last_run_id) {
                setSelectedResult('all');
                setQuery('');
            }
            if (data.running && data.last_run_id && !hasManualRunSelectionRef.current
                && (data.last_run_id !== loopRunRef.current || selectedRunId !== data.last_run_id)) {
                await fetchRuns(data.last_run_id);
                loopRunRef.current = data.last_run_id;
            } else if (!data.running) {
                loopRunRef.current = '';
            }
        } catch {
            // Keep the table usable even if the loop endpoint is temporarily unavailable.
        }
    }, [fetchRuns, selectedRunId]);

    const fetchStockHistory = useCallback(async (value: string) => {
        const cleanQuery = value.trim();
        if (!cleanQuery) {
            setStockHistory(null);
            setHistoryMessage('');
            setHistoryLoading(false);
            return;
        }
        setHistoryLoading(true);
        setHistoryMessage('');
        try {
            const params = new URLSearchParams();
            params.set('q', cleanQuery);
            params.set('limit', '1000');
            const res = await fetchWithTimeout(`${API_BASE}/api/manual-stock-analysis/history?${params.toString()}`, {
                headers: authHeaders(),
            }, 15000);
            if (!res.ok) throw new Error(`분석 이력 조회 실패 (${res.status})`);
            setStockHistory(await res.json());
        } catch (err) {
            setHistoryMessage(err instanceof Error ? err.message : '분석 이력 조회 실패');
        } finally {
            setHistoryLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchRuns();
        fetchLoopStatus();
    }, [fetchLoopStatus, fetchRuns]);

    useEffect(() => {
        const id = window.setTimeout(() => fetchRunDetail(), 250);
        return () => window.clearTimeout(id);
    }, [fetchRunDetail]);

    // Fetched once: the whole universe (~2,300 stocks) so typing never hits the network.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await fetchWithTimeout(`${API_BASE}/api/manual-stock-analysis/search-index`, {
                    headers: authHeaders(),
                }, 15000);
                if (!res.ok) return;
                const data: SearchIndex = await res.json();
                if (!cancelled) setSearchIndex(data);
            } catch {
                // Autocomplete is an assist, not a requirement -- the box still searches.
            }
        })();
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        const cleanQuery = query.trim();
        if (!cleanQuery) {
            setStockHistory(null);
            setHistoryMessage('');
            setHistoryLoading(false);
            return undefined;
        }
        const id = window.setTimeout(() => fetchStockHistory(cleanQuery), 300);
        return () => window.clearTimeout(id);
    }, [fetchStockHistory, query]);

    useEffect(() => {
        const id = window.setInterval(async () => {
            if (pollInFlightRef.current) return;
            pollInFlightRef.current = true;
            try {
                await fetchLoopStatus();
                if (loopStatus?.running || shouldStreamSelectedRun) {
                    await fetchRunDetail({ silent: true });
                }
            } finally {
                pollInFlightRef.current = false;
            }
        }, loopStatus?.running || shouldStreamSelectedRun ? 1000 : 2500);
        return () => window.clearInterval(id);
    }, [fetchLoopStatus, fetchRunDetail, loopStatus?.running, shouldStreamSelectedRun]);

    const exportUrl = useMemo(() => {
        if (!selectedRunId) return '';
        const params = new URLSearchParams();
        params.set('result', selectedResult);
        if (query.trim()) params.set('q', query.trim());
        return `${API_BASE}/api/manual-stock-analysis/runs/${selectedRunId}/export?${params.toString()}`;
    }, [query, selectedResult, selectedRunId]);

    const summary = detail?.summary || selectedRun?.summary || {};
    const total = detail?.filtered_count ?? selectedRun?.record_count ?? 0;
    const unfilteredTotal = detail?.record_count ?? selectedRun?.record_count ?? total;
    const visibleRecords = (detail?.records || []).slice(0, 500);
    const hiddenRecordCount = Math.max(0, (detail?.records?.length || 0) - visibleRecords.length);
    const loopTotal = loopStatus?.total || loopStatus?.source_record_count || 0;
    const loopProcessed = loopStatus?.processed || 0;
    const loopProgress = loopTotal > 0 ? Math.min(100, Math.round((loopProcessed / loopTotal) * 100)) : 0;
    const isLoopRunning = !!loopStatus?.running;
    const isLiveRunSelected = shouldStreamSelectedRun;
    // Liveness comes from when data last hit disk, not the loop's in-memory flag:
    // the 2026-07-15 freeze showed the flag can look idle while nobody notices.
    // Prefer the polled stamp — the runs list is only fetched on mount, so on its
    // own it would keep showing "stale" after the pipeline recovered.
    const latestRunUpdatedAt = useMemo(
        () => runs.reduce((latest, run) => (run.updated_at && run.updated_at > latest ? run.updated_at : latest), ''),
        [runs],
    );
    const upgradedCount = Number(detail?.upgraded_count) || 0;
    const lastDataAt = loopStatus?.last_data_at || latestRunUpdatedAt;
    const freshness = getRunFreshness(lastDataAt);
    const suggestions = useMemo(
        () => (suggestOpen ? buildSuggestions(searchIndex, query) : []),
        [query, searchIndex, suggestOpen],
    );

    const applySuggestion = useCallback((value: string) => {
        setQuery(value);
        setSuggestOpen(false);
        setSuggestActive(0);
    }, []);

    const handleSearchKeyDown = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Escape') {
            setSuggestOpen(false);
            return;
        }
        if (!suggestions.length) return;
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setSuggestActive((current) => (current + 1) % suggestions.length);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setSuggestActive((current) => (current - 1 + suggestions.length) % suggestions.length);
        } else if (event.key === 'Enter') {
            const picked = suggestions[suggestActive];
            if (picked) {
                event.preventDefault();
                applySuggestion(picked.value);
            }
        }
    }, [applySuggestion, suggestActive, suggestions]);
    const freshnessStyle = FRESHNESS_STYLES[freshness.level];
    const runHistory = runs.slice(0, 18);
    const stockHistoryItems = stockHistory?.items || [];
    const showStockHistory = !!query.trim();
    const stockHistoryTarget = stockHistory?.target;
    const stockHistoryTitle = stockHistoryTarget?.stock_name
        ? `${stockHistoryTarget.stock_name}${stockHistoryTarget.ticker ? ` (${stockHistoryTarget.ticker})` : ''}`
        : query.trim();

    // Smart analytics: bull -> bear signal distribution across the selected run.
    const distribution = useMemo(() => {
        const segments = RATING_ORDER.map((label) => ({ label, count: Number(summary[label]) || 0 }))
            .filter((seg) => seg.count > 0);
        const ratingTotal = segments.reduce((acc, seg) => acc + seg.count, 0);
        const buyCount = (Number(summary['적극 매수']) || 0) + (Number(summary['매수']) || 0);
        const sellCount = (Number(summary['매도']) || 0) + (Number(summary['적극 매도']) || 0);
        const buyRatio = ratingTotal > 0 ? Math.round((buyCount / ratingTotal) * 100) : 0;
        const extras = ['분석중', '오류'].map((label) => ({ label, count: Number(summary[label]) || 0 }))
            .filter((seg) => seg.count > 0);
        return { segments, ratingTotal, buyCount, sellCount, buyRatio, extras };
    }, [summary]);

    const selectHistoryRun = (runId: string) => {
        hasManualRunSelectionRef.current = true;
        selectedRunIdRef.current = runId;
        setSelectedRunId(runId);
        setSelectedResult('all');
        setQuery('');
    };

    const applyResultFilter = (result: string) => {
        setSelectedResult(result);
    };

    return (
        <div className="space-y-4 md:space-y-5">
            {/* ===== HERO + LIVE COMMAND BAR ===== */}
            <section className="relative overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-4 shadow-2xl shadow-black/30 md:p-6">
                <div
                    className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full opacity-[0.12] blur-3xl"
                    style={{ background: 'radial-gradient(circle, #CC785C 0%, transparent 70%)' }}
                />
                <div className="relative flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0">
                        <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.24em] text-orange-400/90 md:text-[11px]">
                            <i className="fas fa-robot text-[11px]" />
                            Manual Scraper Service
                        </div>
                        <h1 className="mt-2 text-[1.7rem] font-black leading-tight tracking-tight text-white md:text-[2.4rem]">
                            AI 주식 분석
                        </h1>
                        <p className="mt-2 max-w-2xl text-[13px] font-medium leading-6 text-slate-400 md:text-sm">
                            외부 보드형 AI 분석 결과를 우선주·상폐 종목을 제외하고 순번대로 무한 반복 분석합니다.
                            분석일자·회차는 자동 기록되며, 한 사이클이 끝나면 즉시 다음 사이클로 이어집니다.
                        </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                        <span className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-bold ${
                            isLoopRunning
                                ? 'border-emerald-400/30 bg-emerald-500/12 text-emerald-200'
                                : 'border-white/12 bg-white/5 text-slate-300'
                        }`}>
                            <span className={`h-2 w-2 rounded-full ${isLoopRunning ? 'animate-pulse bg-emerald-400' : 'bg-slate-500'}`} />
                            {isLoopRunning ? 'LIVE · 자동 루프 작동 중' : '자동 루프 대기 중'}
                        </span>
                        {exportUrl && (
                            <a
                                href={exportUrl}
                                className="inline-flex items-center gap-2 rounded-full border border-orange-400/30 bg-orange-500/10 px-3.5 py-2 text-xs font-bold text-orange-200 transition hover:bg-orange-500/20"
                            >
                                <i className="fas fa-file-excel text-[11px]" />
                                엑셀 다운로드
                            </a>
                        )}
                    </div>
                </div>

                {/* Live loop strip */}
                <div className="relative mt-5 rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex items-center gap-3">
                            <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-base ${
                                isLoopRunning ? 'bg-cyan-500/15 text-cyan-300' : 'bg-white/5 text-slate-400'
                            }`}>
                                <i className="fas fa-satellite-dish" />
                            </div>
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <h2 className="text-base font-bold text-white">실시간 스크래퍼 루프</h2>
                                    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${
                                        isLoopRunning
                                            ? 'border-cyan-400/30 bg-cyan-500/12 text-cyan-200'
                                            : 'border-white/10 bg-white/5 text-slate-400'
                                    }`}>
                                        {LOOP_LABELS[loopStatus?.state || 'stopped'] || loopStatus?.state || '중지됨'}
                                    </span>
                                    <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[10px] font-semibold text-slate-400">
                                        {formatSeconds(loopStatus?.interval_sec ?? 0)} 간격
                                    </span>
                                    <span
                                        title={lastDataAt ? `마지막 데이터 갱신: ${lastDataAt}` : '갱신 기록 없음'}
                                        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${freshnessStyle.pill}`}
                                    >
                                        <i className={`fas ${freshnessStyle.icon} text-[9px]`} />
                                        {freshness.level === 'stale' ? `갱신 중단 · ${freshness.label}` : freshness.label}
                                    </span>
                                </div>
                                <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
                                    {loopStatus?.source_path || 'E:\\다운로드\\stock_data_final.xlsx'}
                                </div>
                            </div>
                        </div>
                        <div className="flex items-center gap-4 text-right">
                            <div>
                                <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">진행</div>
                                <div className="font-black tabular-nums text-white">
                                    {loopProcessed}<span className="text-slate-500">/{loopTotal}</span>
                                </div>
                            </div>
                            <div>
                                <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">회차</div>
                                <div className="font-black tabular-nums text-white">{loopStatus?.cycle || loopStatus?.iterations || 0}</div>
                            </div>
                            <div>
                                <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">진척률</div>
                                <div className={`font-black tabular-nums ${isLoopRunning ? 'text-cyan-300' : 'text-slate-300'}`}>{loopProgress}%</div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/40">
                        <div
                            className={`h-full rounded-full bg-gradient-to-r from-cyan-400 to-emerald-400 transition-all duration-500 ${isLoopRunning ? 'animate-pulse' : ''}`}
                            style={{ width: `${loopProgress}%` }}
                        />
                    </div>

                    <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
                        <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                            <i className="fas fa-crosshairs text-[11px] text-cyan-400/80" />
                            <span className="text-slate-500">현재</span>
                            <span className="truncate font-semibold text-white">{loopStatus?.current_stock || '--'}</span>
                        </div>
                        <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                            <i className="fas fa-industry text-[11px] text-slate-500" />
                            <span className="text-slate-500">산업</span>
                            <span className="truncate font-semibold text-slate-200">{loopStatus?.current_industry || '--'}</span>
                        </div>
                        <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                            <i className="fas fa-gavel text-[11px] text-slate-500" />
                            <span className="text-slate-500">판정</span>
                            <span className="truncate font-semibold text-slate-200">{loopStatus?.current_result || '--'}</span>
                        </div>
                        <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                            <i className="fas fa-clock text-[11px] text-slate-500" />
                            <span className="text-slate-500">다음</span>
                            <span className="truncate font-semibold text-slate-200">{loopStatus?.next_run_at || '--'}</span>
                        </div>
                    </div>
                    {loopStatus?.last_error && (
                        <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200">
                            <i className="fas fa-triangle-exclamation mt-0.5 text-[11px]" />
                            <span>{loopStatus.last_error}</span>
                        </div>
                    )}
                </div>
            </section>

            {/* ===== SMART SIGNAL DISTRIBUTION ===== */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-4 shadow-2xl shadow-black/20 md:p-5">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                        <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-orange-400/90 md:text-[11px]">
                            Signal Distribution
                        </div>
                        <h2 className="mt-1 text-lg font-bold text-white md:text-xl">분석 신호 분포</h2>
                    </div>
                    <div className="text-right">
                        <div className="text-[11px] font-semibold text-slate-500">
                            평가 {distribution.ratingTotal.toLocaleString('ko-KR')}종목
                            {(loading || historyLoading) && <span className="ml-2 text-slate-600">…</span>}
                        </div>
                        <div className="text-sm font-black tabular-nums">
                            {distribution.buyRatio >= 50
                                ? <span className="text-rose-300">매수 우위 {distribution.buyRatio}%</span>
                                : <span className="text-sky-300">매도 우위 {100 - distribution.buyRatio}%</span>}
                        </div>
                    </div>
                </div>

                {/* Stacked distribution bar */}
                <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-white/5">
                    {distribution.ratingTotal === 0 ? (
                        <div className="h-full w-full bg-white/[0.04]" />
                    ) : (
                        distribution.segments.map((seg) => (
                            <button
                                type="button"
                                key={seg.label}
                                onClick={() => applyResultFilter(seg.label)}
                                title={`${seg.label} ${seg.count}종목`}
                                className="h-full transition-all duration-500 hover:brightness-125"
                                style={{ width: `${(seg.count / distribution.ratingTotal) * 100}%`, background: resultSolid(seg.label) }}
                            />
                        ))
                    )}
                </div>

                {/* Clickable legend = filter */}
                <div className="mt-4 flex flex-wrap gap-2">
                    <button
                        type="button"
                        onClick={() => applyResultFilter('all')}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition ${
                            selectedResult === 'all'
                                ? 'border-white/25 bg-white/10 text-white'
                                : 'border-white/10 bg-white/5 text-slate-400 hover:bg-white/10'
                        }`}
                    >
                        전체 <span className="tabular-nums">{unfilteredTotal.toLocaleString('ko-KR')}</span>
                    </button>
                    <button
                        type="button"
                        onClick={() => applyResultFilter(UPGRADE_FILTER)}
                        title="이전 날짜의 판정은 적극 매수가 아니었는데 이번 회차에 적극 매수로 바뀐 종목 (판정은 하루 안에는 바뀌지 않아 전일 대비로 비교합니다)"
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition border-emerald-400/30 bg-emerald-500/10 text-emerald-200 ${
                            selectedResult === UPGRADE_FILTER ? 'ring-2 ring-white/40' : 'opacity-90 hover:opacity-100'
                        } ${upgradedCount === 0 ? 'opacity-40' : ''}`}
                    >
                        <i className="fas fa-arrow-trend-up text-[10px]" />
                        {UPGRADE_FILTER} <span className="tabular-nums">{upgradedCount.toLocaleString('ko-KR')}</span>
                    </button>
                    {[...RATING_ORDER, ...distribution.extras.map((e) => e.label)].map((label) => {
                        const count = Number(summary[label]) || 0;
                        if (count === 0 && !RATING_ORDER.includes(label)) return null;
                        const active = selectedResult === label;
                        return (
                            <button
                                type="button"
                                key={label}
                                onClick={() => applyResultFilter(label)}
                                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition ${resultBadge(label)} ${
                                    active ? 'ring-2 ring-white/40' : 'opacity-90 hover:opacity-100'
                                } ${count === 0 ? 'opacity-40' : ''}`}
                            >
                                <span className={`h-2 w-2 rounded-full ${RESULT_STYLES[label]?.dot || 'bg-slate-400'}`} />
                                {label} <span className="tabular-nums">{count.toLocaleString('ko-KR')}</span>
                            </button>
                        );
                    })}
                    {message && <span className="self-center text-xs font-medium text-amber-300">{message}</span>}
                </div>

                {/* Run + search controls */}
                <div className="mt-4 grid gap-3 border-t border-white/[0.06] pt-4 lg:grid-cols-[1.2fr_0.7fr_1fr]">
                    <label className="block">
                        <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">회차</span>
                        <div className="relative">
                            <i className="fas fa-layer-group pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[12px] text-slate-500" />
                            <select
                                value={selectedRunId}
                                onChange={(event) => selectHistoryRun(event.target.value)}
                                className="h-11 w-full appearance-none rounded-xl border border-white/10 bg-black/30 pl-9 pr-4 text-sm font-semibold text-white outline-none transition focus:border-orange-400/50"
                            >
                                {runs.length === 0 && <option value="">등록된 회차 없음</option>}
                                {runs.map((run) => (
                                    <option key={run.run_id} value={run.run_id} className="bg-[#16161a]">{buildRunLabel(run)}</option>
                                ))}
                            </select>
                        </div>
                    </label>
                    <label className="block">
                        <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">판정</span>
                        <div className="relative">
                            <i className="fas fa-filter pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[12px] text-slate-500" />
                            <select
                                value={selectedResult}
                                onChange={(event) => setSelectedResult(event.target.value)}
                                className="h-11 w-full appearance-none rounded-xl border border-white/10 bg-black/30 pl-9 pr-4 text-sm font-semibold text-white outline-none transition focus:border-orange-400/50"
                            >
                                <option value="all" className="bg-[#16161a]">전체</option>
                                {/* Listed so picking the chip does not leave this control blank. */}
                                <option value={UPGRADE_FILTER} className="bg-[#16161a]">{UPGRADE_FILTER}</option>
                                {(filters.length ? filters : DEFAULT_FILTERS).map((filter) => (
                                    <option key={filter} value={filter} className="bg-[#16161a]">{filter}</option>
                                ))}
                            </select>
                        </div>
                    </label>
                    <label className="block">
                        <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">검색</span>
                        <div className="relative">
                            <i className="fas fa-magnifying-glass pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[12px] text-slate-500" />
                            <input
                                value={query}
                                onChange={(event) => {
                                    setQuery(event.target.value);
                                    setSuggestOpen(true);
                                    setSuggestActive(0);
                                }}
                                onFocus={() => setSuggestOpen(true)}
                                // Delayed so a click on a suggestion lands before the list closes.
                                onBlur={() => window.setTimeout(() => setSuggestOpen(false), 120)}
                                onKeyDown={handleSearchKeyDown}
                                placeholder="종목명, 코드, 산업"
                                autoComplete="off"
                                role="combobox"
                                aria-expanded={suggestions.length > 0}
                                aria-controls="manual-search-suggestions"
                                className="h-11 w-full rounded-xl border border-white/10 bg-black/30 pl-9 pr-4 text-sm font-semibold text-white outline-none transition placeholder:text-slate-600 focus:border-orange-400/50"
                            />
                            {suggestions.length > 0 && (
                                <ul
                                    id="manual-search-suggestions"
                                    role="listbox"
                                    className="absolute left-0 right-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-xl border border-white/10 bg-[#141418] py-1 shadow-2xl shadow-black/60"
                                >
                                    {suggestions.map((suggestion, index) => (
                                        <li key={`${suggestion.type}-${suggestion.value}`}>
                                            <button
                                                type="button"
                                                role="option"
                                                aria-selected={index === suggestActive}
                                                onMouseEnter={() => setSuggestActive(index)}
                                                onMouseDown={(event) => event.preventDefault()}
                                                onClick={() => applySuggestion(suggestion.value)}
                                                className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition ${
                                                    index === suggestActive ? 'bg-white/[0.07]' : 'bg-transparent'
                                                }`}
                                            >
                                                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold ${
                                                    suggestion.type === 'stock'
                                                        ? 'bg-orange-400/20 text-orange-200'
                                                        : 'bg-sky-400/20 text-sky-200'
                                                }`}>
                                                    {suggestion.type === 'stock' ? '종목' : '산업'}
                                                </span>
                                                <span className="min-w-0 flex-1 truncate text-sm font-semibold text-white">
                                                    {suggestion.label}
                                                </span>
                                                {suggestion.hint && (
                                                    <span className="shrink-0 truncate font-mono text-[10px] text-slate-500">
                                                        {suggestion.hint}
                                                    </span>
                                                )}
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </label>
                </div>
            </section>

            {/* ===== ROUND HISTORY (mobile) ===== */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-4 md:hidden">
                <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                        <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-orange-400/90">
                            Round History
                        </div>
                        <h2 className="mt-1 text-base font-bold text-white">분석회차 히스토리</h2>
                    </div>
                    <span className="shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-bold text-slate-300">
                        {runs.length.toLocaleString('ko-KR')}회차
                    </span>
                </div>
                <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                    {runHistory.slice(0, 8).map((run, index) => {
                        const active = run.run_id === selectedRunId;
                        return (
                            <button
                                type="button"
                                key={`mobile-history-${run.run_id}`}
                                onClick={() => selectHistoryRun(run.run_id)}
                                className={`shrink-0 rounded-xl border px-3 py-2 text-left transition ${
                                    active
                                        ? 'border-cyan-300/50 bg-cyan-400/12 text-white'
                                        : 'border-white/10 bg-white/[0.02] text-slate-300'
                                }`}
                            >
                                <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                                    #{index + 1}
                                </div>
                                <div className="mt-1 max-w-[9rem] truncate text-xs font-bold">
                                    {run.cycle_label || run.title || formatRunTimestamp(run.created_at)}
                                </div>
                                <div className="mt-1 text-[10px] font-medium text-slate-500 tabular-nums">
                                    {Number(run.record_count || 0).toLocaleString('ko-KR')} rows
                                </div>
                            </button>
                        );
                    })}
                    {runHistory.length === 0 && (
                        <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] px-4 py-3 text-xs font-medium text-slate-500">
                            저장된 분석회차가 아직 없습니다.
                        </div>
                    )}
                </div>
            </section>

            {/* ===== ROUND HISTORY (desktop) ===== */}
            <section className="hidden rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-4 md:block md:p-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                        <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-orange-400/90 md:text-[11px]">
                            Analysis Round History
                        </div>
                        <h2 className="mt-1 text-lg font-bold text-white md:text-xl">분석회차 히스토리</h2>
                        <p className="mt-1 text-xs font-medium text-slate-500">
                            저장된 회차를 클릭하면 해당 결과로 즉시 전환합니다. 실시간 루프 회차는 완료 전까지 계속 갱신됩니다.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs font-bold">
                        <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-slate-300 tabular-nums">
                            {runs.length.toLocaleString('ko-KR')} rounds
                        </span>
                        <span className="rounded-full border border-cyan-300/20 bg-cyan-500/10 px-3 py-1.5 text-cyan-100">
                            selected {selectedRun ? formatRunTimestamp(selectedRun.created_at) : '--'}
                        </span>
                    </div>
                </div>

                <div className="mt-4 grid max-h-[240px] gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
                    {runHistory.map((run, index) => {
                        const active = run.run_id === selectedRunId;
                        const preview = summaryPreview(run.summary);
                        return (
                            <button
                                type="button"
                                key={run.run_id}
                                onClick={() => selectHistoryRun(run.run_id)}
                                className={`group rounded-xl border p-3 text-left transition ${
                                    active
                                        ? 'border-cyan-300/50 bg-cyan-500/[0.08] shadow-lg shadow-cyan-950/20'
                                        : 'border-white/[0.07] bg-white/[0.02] hover:border-cyan-300/30 hover:bg-white/[0.04]'
                                }`}
                            >
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                                            #{index + 1} · {formatRunTimestamp(run.created_at)}
                                        </div>
                                        <div className="mt-1 truncate text-sm font-bold text-white">
                                            {run.title || run.run_id}
                                        </div>
                                    </div>
                                    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-bold ${runStatusClass(run.status)}`}>
                                        {runStatusLabel(run.status)}
                                    </span>
                                </div>
                                <div className="mt-3 grid grid-cols-3 gap-2 text-xs font-bold">
                                    <div className="rounded-lg border border-white/[0.06] bg-black/20 px-2 py-1.5">
                                        <div className="text-[9px] uppercase tracking-widest text-slate-500">rows</div>
                                        <div className="mt-0.5 tabular-nums text-white">{Number(run.record_count || 0).toLocaleString('ko-KR')}</div>
                                    </div>
                                    <div className="rounded-lg border border-white/[0.06] bg-black/20 px-2 py-1.5">
                                        <div className="text-[9px] uppercase tracking-widest text-slate-500">source</div>
                                        <div className="mt-0.5 tabular-nums text-white">{Number(run.source_record_count || run.record_count || 0).toLocaleString('ko-KR')}</div>
                                    </div>
                                    <div className="rounded-lg border border-white/[0.06] bg-black/20 px-2 py-1.5">
                                        <div className="text-[9px] uppercase tracking-widest text-slate-500">updated</div>
                                        <div className="mt-0.5 truncate text-white">{formatRunTimestamp(run.updated_at || run.created_at)}</div>
                                    </div>
                                </div>
                                <div className="mt-3 flex min-h-6 flex-wrap gap-1.5">
                                    {preview.length > 0 ? preview.map(([label, count]) => (
                                        <span key={label} className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${resultBadge(label)}`}>
                                            {label} {Number(count).toLocaleString('ko-KR')}
                                        </span>
                                    )) : (
                                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                                            no summary
                                        </span>
                                    )}
                                </div>
                            </button>
                        );
                    })}
                    {runHistory.length === 0 && (
                        <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] p-5 text-sm font-medium text-slate-500">
                            아직 저장된 분석회차가 없습니다. 페이지가 열리면 자동 루프가 시작되고 회차별 히스토리가 자동으로 쌓입니다.
                        </div>
                    )}
                </div>
            </section>

            {/* ===== STOCK SEARCH HISTORY ===== */}
            {showStockHistory && (
                <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0e0e11] shadow-2xl shadow-black/20">
                    <div className="flex flex-col gap-2 border-b border-white/[0.06] px-4 py-4 md:flex-row md:items-center md:justify-between md:px-5">
                        <div>
                            <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-orange-400/90">Search History</div>
                            <h2 className="mt-1 text-lg font-bold text-white">{stockHistoryTitle} 분석 이력</h2>
                        </div>
                        <div className="text-left text-xs font-medium leading-5 text-slate-400 md:text-right">
                            {historyLoading
                                ? '분석이력 조회 중…'
                                : `${Number(stockHistory?.count || 0).toLocaleString('ko-KR')}건`}
                            {stockHistory?.truncated ? ' · 일부 표시' : ''}
                        </div>
                    </div>

                    {historyMessage && (
                        <div className="border-b border-amber-400/20 bg-amber-500/10 px-4 py-3 text-xs font-medium text-amber-200 md:px-5">
                            {historyMessage}
                        </div>
                    )}

                    {!historyLoading && stockHistoryItems.length === 0 && !historyMessage && (
                        <div className="px-4 py-6 text-sm font-medium text-slate-500 md:px-5">
                            해당 종목명 또는 티커로 저장된 분석이력이 아직 없습니다.
                        </div>
                    )}

                    {stockHistoryItems.length > 0 && (
                        <>
                            {/* Mobile cards */}
                            <div className="block px-3 py-3 md:hidden">
                                <div className="space-y-2">
                                    {stockHistoryItems.map((item, index) => (
                                        <article
                                            key={`stock-history-mobile-${item.run_id}-${item.rank}-${item.analyzed_at}`}
                                            className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4"
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">
                                                        #{index + 1} · {item.market || 'MARKET'}
                                                    </div>
                                                    <div className="mt-1 text-sm font-bold text-white">
                                                        {item.cycle_label || item.run_title || formatRunTimestamp(item.created_at)}
                                                    </div>
                                                    <div className="mt-1 text-xs font-medium text-slate-500">
                                                        {item.analyzed_at || '--'}
                                                    </div>
                                                </div>
                                                <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-bold ${resultBadge(item.result)}`}>
                                                    {item.result}
                                                </span>
                                            </div>
                                            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] font-medium text-slate-400">
                                                <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                                                    순번 <b className="ml-1 tabular-nums text-white">{item.rank ?? '-'}</b>
                                                </div>
                                                <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                                                    산업 <b className="ml-1 text-white">{item.industry || '-'}</b>
                                                </div>
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            </div>

                            {/* Desktop table */}
                            <div className="hidden overflow-auto md:block">
                                <table className="min-w-full text-sm">
                                    <thead className="bg-white/[0.03] text-xs uppercase tracking-[0.14em] text-slate-400">
                                        <tr>
                                            <th className="w-24 border-b border-white/[0.06] px-4 py-3 text-center font-bold">순번</th>
                                            <th className="border-b border-white/[0.06] px-4 py-3 text-center font-bold">분석회차</th>
                                            <th className="w-44 border-b border-white/[0.06] px-4 py-3 text-center font-bold">분석결과</th>
                                            <th className="w-80 border-b border-white/[0.06] px-4 py-3 text-center font-bold">분석일시</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {stockHistoryItems.map((item, index) => (
                                            <tr key={`stock-history-${item.run_id}-${item.rank}-${item.analyzed_at}`} className="border-b border-white/[0.04] transition hover:bg-white/[0.02]">
                                                <td className="px-4 py-3 text-center font-bold tabular-nums text-slate-300">{index + 1}</td>
                                                <td className="px-4 py-3 text-center font-medium text-slate-200">
                                                    {item.cycle_label || item.run_title || formatRunTimestamp(item.created_at)}
                                                </td>
                                                <td className="px-4 py-3 text-center">
                                                    <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-bold ${resultBadge(item.result)}`}>
                                                        {item.result}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 text-center font-medium text-slate-400">
                                                    {item.analyzed_at || '--'}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </section>
            )}

            {/* ===== MAIN ANALYSIS TABLE ===== */}
            <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0e0e11] shadow-2xl shadow-black/20">
                <div className="flex flex-col gap-2 border-b border-white/[0.06] px-4 py-4 md:flex-row md:items-center md:justify-between md:px-5">
                    <div>
                        <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-orange-400/90">Analysis Table</div>
                        <h2 className="mt-1 text-lg font-bold text-white">AI 주식 분석 결과</h2>
                    </div>
                    <div className="flex items-center gap-2 text-left text-xs font-medium leading-5 text-slate-400 md:text-right">
                        {isLiveRunSelected && (
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-bold text-cyan-200">
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
                                LIVE
                            </span>
                        )}
                        <span>
                            {isLiveRunSelected
                                ? `${isLoopRunning ? '실시간 갱신 중' : '최근 루프 결과'} · ${loopProcessed}/${loopTotal} · ${loopStatus?.current_stock || '대기'}`
                                : hiddenRecordCount > 0
                                ? `화면 ${visibleRecords.length.toLocaleString('ko-KR')}건 · 추가 ${hiddenRecordCount.toLocaleString('ko-KR')}건은 엑셀 다운로드`
                                : detail?.created_at || selectedRun?.created_at || '--'}
                        </span>
                    </div>
                </div>

                {/* Mobile cards */}
                <div className="block px-3 py-3 md:hidden">
                    <div className="space-y-3 md:max-h-[calc(100dvh-280px)] md:min-h-[420px] md:overflow-y-auto md:pr-1">
                        {visibleRecords.map((record) => (
                            <article
                                key={`mobile-${record.rank}-${record.stock_name}-${record.ticker}`}
                                className={`rounded-xl border p-4 transition ${
                                    record.scrape_state === 'scraping'
                                        ? 'border-cyan-400/40 bg-cyan-500/[0.06] ring-1 ring-cyan-400/20'
                                        : 'border-white/[0.07] bg-white/[0.02]'
                                }`}
                            >
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
                                            #{record.rank} · {record.market || 'MARKET'}
                                        </div>
                                        <h3 className="mt-1 truncate text-base font-bold text-white">
                                            {record.stock_name}
                                        </h3>
                                        {record.ticker && (
                                            <div className="mt-0.5 font-mono text-xs font-bold text-slate-500">{record.ticker}</div>
                                        )}
                                    </div>
                                    <span className={`shrink-0 rounded-full border px-3 py-1 text-xs font-bold ${resultBadge(record.result)}`}>
                                        {record.result}
                                    </span>
                                </div>

                                <div className="mt-3 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
                                    <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">산업</div>
                                    <div className="mt-1 text-sm font-semibold text-slate-200">{record.industry || '미분류'}</div>
                                    {record.sector && (
                                        <div className="mt-1 text-[11px] font-bold text-sky-300">부문 {record.sector}</div>
                                    )}
                                </div>

                                <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] font-bold">
                                    {record.analyst_sentiment && (
                                        <span className="rounded-full border border-rose-400/25 bg-rose-500/10 px-2 py-1 text-rose-200">
                                            애널 {record.analyst_sentiment}
                                        </span>
                                    )}
                                    {record.technical_result && (
                                        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-slate-300">
                                            기술 {record.technical_result}
                                        </span>
                                    )}
                                    {record.target_price && (
                                        <span className="rounded-full border border-emerald-400/25 bg-emerald-500/10 px-2 py-1 text-emerald-200">
                                            목표 {record.target_price}
                                        </span>
                                    )}
                                    {record.upside_potential && (
                                        <span className="rounded-full border border-orange-400/25 bg-orange-500/10 px-2 py-1 text-orange-200">
                                            여력 {record.upside_potential}
                                        </span>
                                    )}
                                    {record.scrape_fallback === 'stale_cache' ? (
                                        <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-1 text-amber-200">
                                            직전값 유지{record.stale_from ? ` · ${record.stale_from}` : ''}
                                        </span>
                                    ) : record.scrape_fallback && (
                                        <span className="rounded-full border border-violet-400/25 bg-violet-500/10 px-2 py-1 text-violet-200">
                                            {fallbackLabel(record.scrape_fallback)}
                                        </span>
                                    )}
                                    {record.scrape_state === 'scraping' && (
                                        <span className="inline-flex animate-pulse items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/15 px-2 py-1 text-cyan-200">
                                            <i className="fas fa-spinner fa-spin text-[9px]" /> 진행중
                                        </span>
                                    )}
                                </div>

                                {record.error && (
                                    <div className="mt-3 rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200">
                                        {friendlyError(record.error)}
                                    </div>
                                )}

                                <div className="mt-3 flex items-center justify-between border-t border-white/[0.06] pt-3 text-[11px] font-medium text-slate-500">
                                    <span>분석일시</span>
                                    <span className="text-right text-slate-300">{record.analyzed_at}</span>
                                </div>
                            </article>
                        ))}
                        {!loading && (!detail?.records || detail.records.length === 0) && (
                            <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] px-5 py-12 text-center text-sm font-medium text-slate-500">
                                표시할 AI 주식 분석 결과가 없습니다. 자동 루프가 기본 소스 전체를 순차 분석하면 이 영역에 실시간으로 출력됩니다.
                            </div>
                        )}
                    </div>
                </div>

                {/* Desktop table */}
                <div className="hidden max-h-[calc(100vh-380px)] min-h-[460px] overflow-auto md:block">
                    <table className="min-w-full text-sm">
                        <thead className="sticky top-0 z-10 bg-[#16161a] text-xs uppercase tracking-[0.14em] text-slate-400">
                            <tr>
                                <th className="border-b border-white/[0.07] px-4 py-3 text-center font-bold">순번</th>
                                <th className="border-b border-white/[0.07] px-4 py-3 text-left font-bold">종목명</th>
                                <th className="border-b border-white/[0.07] px-4 py-3 text-left font-bold">산업</th>
                                <th className="border-b border-white/[0.07] px-4 py-3 text-center font-bold">분석결과</th>
                                <th className="border-b border-white/[0.07] px-4 py-3 text-center font-bold">분석일시</th>
                            </tr>
                        </thead>
                        <tbody>
                            {visibleRecords.map((record) => (
                                <tr
                                    key={`${record.rank}-${record.stock_name}-${record.ticker}`}
                                    className={`border-b border-white/[0.04] transition ${
                                        record.scrape_state === 'scraping'
                                            ? 'bg-cyan-500/[0.06] ring-1 ring-inset ring-cyan-400/25'
                                            : 'hover:bg-white/[0.025]'
                                    }`}
                                >
                                    <td className="px-4 py-3 text-center font-bold tabular-nums text-slate-400">{record.rank}</td>
                                    <td className="px-4 py-3 text-left">
                                        <div className="font-bold text-white">{record.stock_name}</div>
                                        <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                                            {record.ticker && <span className="font-mono font-bold text-slate-500">{record.ticker}</span>}
                                            {record.market && <span className="font-bold uppercase tracking-widest text-slate-600">{record.market}</span>}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-left">
                                        <div className="font-semibold text-slate-300">{record.industry || '미분류'}</div>
                                        {record.sector && (
                                            <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-sky-300/90">
                                                부문 {record.sector}
                                            </div>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-bold ${resultBadge(record.result)}`}>
                                            {record.result}
                                        </span>
                                        <div className="mt-2 flex flex-wrap justify-center gap-1.5 text-[10px] font-bold">
                                            {record.analyst_sentiment && (
                                                <span className="rounded-full border border-rose-400/25 bg-rose-500/10 px-2 py-0.5 text-rose-200">
                                                    애널 {record.analyst_sentiment}
                                                </span>
                                            )}
                                            {record.technical_result && (
                                                <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-300">
                                                    기술 {record.technical_result}
                                                </span>
                                            )}
                                            {record.target_price && (
                                                <span className="rounded-full border border-emerald-400/25 bg-emerald-500/10 px-2 py-0.5 text-emerald-200">
                                                    목표 {record.target_price}
                                                </span>
                                            )}
                                            {record.upside_potential && (
                                                <span className="rounded-full border border-orange-400/25 bg-orange-500/10 px-2 py-0.5 text-orange-200">
                                                    여력 {record.upside_potential}
                                                </span>
                                            )}
                                            {record.scrape_fallback === 'stale_cache' ? (
                                                <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-amber-200">
                                                    직전값 유지{record.stale_from ? ` · ${record.stale_from}` : ''}
                                                </span>
                                            ) : record.scrape_fallback && (
                                                <span className="rounded-full border border-violet-400/25 bg-violet-500/10 px-2 py-0.5 text-violet-200">
                                                    {fallbackLabel(record.scrape_fallback)}
                                                </span>
                                            )}
                                        </div>
                                        {record.error && (
                                            <div className="mx-auto mt-2 max-w-md truncate rounded-lg border border-rose-400/25 bg-rose-500/10 px-2 py-1 text-[10px] font-medium text-rose-200">
                                                {friendlyError(record.error)}
                                            </div>
                                        )}
                                        {record.scrape_state === 'scraping' && (
                                            <span className="mt-2 inline-flex animate-pulse items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/15 px-2 py-0.5 text-[10px] font-bold text-cyan-200">
                                                <i className="fas fa-spinner fa-spin text-[9px]" /> 진행중
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-center font-medium text-slate-400">{record.analyzed_at}</td>
                                </tr>
                            ))}
                            {!loading && (!detail?.records || detail.records.length === 0) && (
                                <tr>
                                    <td colSpan={5} className="px-6 py-16 text-center text-sm font-medium text-slate-500">
                                        표시할 AI 주식 분석 결과가 없습니다. 자동 루프가 기본 소스 전체를 순차 분석하면 이 표에 실시간으로 출력됩니다.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    );
}
