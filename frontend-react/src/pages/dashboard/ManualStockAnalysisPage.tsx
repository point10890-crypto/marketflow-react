import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE, authHeaders } from '@/lib/api';

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
}

const DEFAULT_FILTERS = ['적극 매수', '매수', '중립', '매도', '적극 매도', '분석중', '오류'];

const RESULT_COLORS: Record<string, string> = {
    '적극 매수': 'text-red-500 bg-red-500/10 border-red-400/30',
    '매수': 'text-orange-400 bg-orange-500/10 border-orange-400/30',
    '중립': 'text-yellow-500 bg-yellow-500/10 border-yellow-400/30',
    '매도': 'text-blue-500 bg-blue-500/10 border-blue-400/30',
    '적극 매도': 'text-indigo-500 bg-indigo-500/10 border-indigo-400/30',
    '분석중': 'text-violet-400 bg-violet-500/10 border-violet-400/30',
    '오류': 'text-rose-400 bg-rose-500/10 border-rose-400/30',
};

const LOOP_LABELS: Record<string, string> = {
    starting: '시작 중',
    scraping: '스크래핑 중',
    waiting: '대기 중',
    error_waiting: '오류 후 대기',
    stopping: '중지 중',
    stopped: '중지됨',
};

function resultClass(result: string) {
    return RESULT_COLORS[result] || 'text-slate-500 bg-slate-500/10 border-slate-300';
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

function runStatusLabel(status?: string) {
    if (status === 'running') return '진행중';
    if (status === 'error') return '오류';
    if (status === 'completed') return '완료';
    return status || '기록';
}

function runStatusClass(status?: string) {
    if (status === 'running') return 'border-cyan-300/40 bg-cyan-400/15 text-cyan-100';
    if (status === 'error') return 'border-rose-300/40 bg-rose-500/15 text-rose-100';
    if (status === 'completed') return 'border-emerald-300/35 bg-emerald-500/12 text-emerald-100';
    return 'border-slate-500/30 bg-white/5 text-slate-300';
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
    const [detail, setDetail] = useState<ManualRunDetail | null>(null);
    const [loopStatus, setLoopStatus] = useState<ScraperLoopStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const loopRunRef = useRef('');

    const selectedRun = useMemo(
        () => runs.find((run) => run.run_id === selectedRunId) || null,
        [runs, selectedRunId],
    );
    const selectedMatchesLoopRun = !!loopStatus?.last_run_id && selectedRunId === loopStatus.last_run_id;
    const isSelectedLoopRun = !!loopStatus?.running && selectedMatchesLoopRun;
    const isStoppedLoopRunSelection = selectedMatchesLoopRun && !loopStatus?.running;
    const shouldStreamSelectedRun = isSelectedLoopRun
        || (!isStoppedLoopRunSelection && (selectedRun?.status === 'running' || detail?.status === 'running'));

    const fetchRuns = useCallback(async (preferredRunId?: string) => {
        setLoading(true);
        setMessage('');
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/runs`, {
                headers: authHeaders(),
            });
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
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/runs/${selectedRunId}?${params.toString()}`, {
                headers: authHeaders(),
            });
            if (!res.ok) throw new Error(`분석 목록 조회 실패 (${res.status})`);
            setDetail(await res.json());
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
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/scraper-loop`, {
                headers: authHeaders(),
            });
            if (!res.ok) return;
            const data: ScraperLoopStatus = await res.json();
            setLoopStatus(data);
            if (data.running && data.last_run_id && selectedRunId !== data.last_run_id) {
                setSelectedResult('all');
                setQuery('');
            }
            if (data.running && data.last_run_id && (data.last_run_id !== loopRunRef.current || selectedRunId !== data.last_run_id)) {
                await fetchRuns(data.last_run_id);
                loopRunRef.current = data.last_run_id;
            } else if (!data.running) {
                loopRunRef.current = '';
            }
        } catch {
            // Keep the table usable even if the loop endpoint is temporarily unavailable.
        }
    }, [fetchRuns, selectedRunId]);

    useEffect(() => {
        fetchRuns();
        fetchLoopStatus();
    }, [fetchLoopStatus, fetchRuns]);

    useEffect(() => {
        fetchRunDetail();
    }, [fetchRunDetail]);

    useEffect(() => {
        const id = window.setTimeout(() => fetchRunDetail(), 250);
        return () => window.clearTimeout(id);
    }, [fetchRunDetail, query]);

    useEffect(() => {
        const id = window.setInterval(() => {
            fetchLoopStatus();
            if (loopStatus?.running || shouldStreamSelectedRun) fetchRunDetail({ silent: true });
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
    const runHistory = runs.slice(0, 18);

    const selectHistoryRun = (runId: string) => {
        setSelectedRunId(runId);
        setSelectedResult('all');
        setQuery('');
    };

    const applyResultFilter = (result: string) => {
        setSelectedResult(result);
    };

    return (
        <div className="space-y-5">
            <section className="rounded-2xl border border-white/10 bg-[#101114] p-5 shadow-2xl shadow-black/20">
                <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                    <div>
                        <div className="mb-2 text-[11px] font-black uppercase tracking-[0.22em] text-orange-400">
                            Manual Scraper Service
                        </div>
                        <h1 className="text-2xl font-black tracking-tight text-white md:text-4xl">
                            AI 주식 분석 목록
                        </h1>
                        <p className="mt-2 max-w-3xl text-sm font-semibold leading-6 text-slate-400">
                            외부 보드형 AI 분석 결과를 MarketFlow 안에서 별도 서비스로 조회합니다.
                            기본 소스는 E:\다운로드\stock_data_final.xlsx이며, 우선주·상폐 종목을 제외한 최신 목록을 순번대로 반복 분석합니다.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-start gap-2">
                        <span className={`rounded-xl border px-4 py-2 text-sm font-black ${
                            isLoopRunning
                                ? 'animate-pulse border-emerald-400/30 bg-emerald-500/15 text-emerald-100'
                                : 'border-cyan-400/25 bg-cyan-500/10 text-cyan-100'
                        }`}>
                            자동 무한 루프 {isLoopRunning ? '작동 중' : '준비 중'}
                        </span>
                        <span className="rounded-xl border border-white/10 bg-black/25 px-4 py-2 text-sm font-black text-slate-200">
                            한 사이클 완료 후 즉시 다음 사이클
                        </span>
                        <span className="rounded-xl border border-cyan-400/20 bg-cyan-500/10 px-4 py-2 text-sm font-black text-cyan-100">
                            {loopStatus?.current_cycle_label || '분석일자/회차 자동 기록'}
                        </span>
                        {exportUrl && (
                            <a
                                href={exportUrl}
                                className="rounded-xl border border-yellow-400/25 bg-yellow-500/10 px-4 py-2 text-sm font-black text-yellow-100 transition hover:bg-yellow-500/20"
                            >
                                엑셀 다운로드
                            </a>
                        )}
                    </div>
                </div>

                <div className="mt-6 rounded-2xl border border-cyan-400/15 bg-cyan-950/15 p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div>
                            <div className="text-[11px] font-black uppercase tracking-[0.22em] text-cyan-300">
                                Realtime Scraper Loop
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2">
                                <h2 className="text-xl font-black text-white">실시간 스크래퍼 루프</h2>
                                <span className={`rounded-full border px-3 py-1 text-xs font-black ${
                                    isLoopRunning
                                        ? 'animate-pulse border-emerald-400/30 bg-emerald-500/15 text-emerald-200'
                                        : 'border-slate-500/30 bg-white/5 text-slate-400'
                                }`}>
                                    {LOOP_LABELS[loopStatus?.state || 'stopped'] || loopStatus?.state || '중지됨'}
                                </span>
                                <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs font-black text-slate-300">
                                    {formatSeconds(loopStatus?.interval_sec ?? 0)} interval
                                </span>
                                <span className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-xs font-black text-cyan-100">
                                    source {loopStatus?.source_record_count || unfilteredTotal || 0}
                                </span>
                            </div>
                            <div className="mt-2 text-xs font-bold text-slate-500">
                                {loopStatus?.source_path || 'E:\\다운로드\\stock_data_final.xlsx'}
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-right text-xs font-black text-slate-400 sm:grid-cols-4">
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">진행</div>
                                <div className="text-lg text-white">{loopProcessed}/{loopTotal}</div>
                            </div>
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">회차</div>
                                <div className="text-lg text-white">{loopStatus?.cycle || loopStatus?.iterations || 0}</div>
                            </div>
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">최근</div>
                                <div className="text-lg text-white">{loopStatus?.last_record_count || 0}</div>
                            </div>
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">상태</div>
                                <div className={isLoopRunning ? 'text-lg text-emerald-300' : 'text-lg text-slate-300'}>
                                    {isLoopRunning ? 'LIVE' : 'IDLE'}
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-black/35">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-violet-400 to-emerald-400 transition-all duration-500"
                            style={{ width: `${loopProgress}%` }}
                        />
                    </div>

                    <div className="mt-4 grid gap-3 text-sm font-bold text-slate-300 md:grid-cols-2 xl:grid-cols-5">
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">현재 종목</div>
                            <div className="mt-1 text-white">{loopStatus?.current_stock || '--'}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">산업</div>
                            <div className="mt-1 text-white">{loopStatus?.current_industry || '--'}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">현재 판정</div>
                            <div className="mt-1 text-white">{loopStatus?.current_result || '--'}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">최근 완료</div>
                            <div className="mt-1 text-white">{loopStatus?.last_finished_at || '--'}</div>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">다음 실행</div>
                            <div className="mt-1 text-white">{loopStatus?.next_run_at || '--'}</div>
                        </div>
                    </div>
                    {loopStatus?.last_error && (
                        <div className="mt-3 rounded-xl border border-rose-400/25 bg-rose-500/10 px-4 py-3 text-xs font-bold text-rose-200">
                            {loopStatus.last_error}
                        </div>
                    )}
                </div>

                <div className="mt-6 rounded-2xl border border-white/10 bg-black/20 p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                        <div>
                            <div className="text-[11px] font-black uppercase tracking-[0.22em] text-orange-300">
                                Analysis Round History
                            </div>
                            <h2 className="mt-1 text-xl font-black text-white">분석회차 히스토리</h2>
                            <p className="mt-1 text-xs font-bold text-slate-500">
                                저장된 회차를 클릭하면 해당 분석 결과로 즉시 전환합니다. 실시간 루프 회차도 완료 전까지 계속 갱신됩니다.
                            </p>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs font-black">
                            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-slate-300">
                                {runs.length.toLocaleString('ko-KR')} rounds
                            </span>
                            <span className="rounded-full border border-cyan-300/20 bg-cyan-500/10 px-3 py-1.5 text-cyan-100">
                                selected {selectedRun ? formatRunTimestamp(selectedRun.created_at) : '--'}
                            </span>
                        </div>
                    </div>

                    <div className="mt-4 grid max-h-[260px] gap-2 overflow-y-auto pr-1 md:grid-cols-2 xl:grid-cols-3">
                        {runHistory.map((run, index) => {
                            const active = run.run_id === selectedRunId;
                            const preview = summaryPreview(run.summary);
                            return (
                                <button
                                    type="button"
                                    key={run.run_id}
                                    onClick={() => selectHistoryRun(run.run_id)}
                                    className={`group rounded-2xl border p-3 text-left transition ${
                                        active
                                            ? 'border-cyan-300/55 bg-cyan-500/15 shadow-lg shadow-cyan-950/30'
                                            : 'border-white/10 bg-white/[0.03] hover:border-cyan-300/35 hover:bg-cyan-500/10'
                                    }`}
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">
                                                #{index + 1} · {formatRunTimestamp(run.created_at)}
                                            </div>
                                            <div className="mt-1 truncate text-sm font-black text-white">
                                                {run.title || run.run_id}
                                            </div>
                                        </div>
                                        <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-black ${runStatusClass(run.status)}`}>
                                            {runStatusLabel(run.status)}
                                        </span>
                                    </div>
                                    <div className="mt-3 grid grid-cols-3 gap-2 text-xs font-black">
                                        <div className="rounded-xl border border-white/10 bg-black/20 px-2 py-2">
                                            <div className="text-[9px] uppercase tracking-widest text-slate-500">rows</div>
                                            <div className="mt-1 text-white">{Number(run.record_count || 0).toLocaleString('ko-KR')}</div>
                                        </div>
                                        <div className="rounded-xl border border-white/10 bg-black/20 px-2 py-2">
                                            <div className="text-[9px] uppercase tracking-widest text-slate-500">source</div>
                                            <div className="mt-1 text-white">{Number(run.source_record_count || run.record_count || 0).toLocaleString('ko-KR')}</div>
                                        </div>
                                        <div className="rounded-xl border border-white/10 bg-black/20 px-2 py-2">
                                            <div className="text-[9px] uppercase tracking-widest text-slate-500">updated</div>
                                            <div className="mt-1 truncate text-white">{formatRunTimestamp(run.updated_at || run.created_at)}</div>
                                        </div>
                                    </div>
                                    <div className="mt-3 flex min-h-7 flex-wrap gap-1.5">
                                        {preview.length > 0 ? preview.map(([label, count]) => (
                                            <span key={label} className={`rounded-full border px-2 py-1 text-[10px] font-black ${resultClass(label)}`}>
                                                {label} {Number(count).toLocaleString('ko-KR')}
                                            </span>
                                        )) : (
                                            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-1 text-[10px] font-black text-slate-500">
                                                no summary
                                            </span>
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                        {runHistory.length === 0 && (
                            <div className="rounded-2xl border border-dashed border-white/15 bg-white/[0.03] p-5 text-sm font-bold text-slate-500">
                                아직 저장된 분석회차가 없습니다. 페이지가 열리면 자동 루프가 시작되고 회차별 히스토리가 자동으로 쌓입니다.
                            </div>
                        )}
                    </div>
                </div>

                <div className="mt-6 grid gap-3 lg:grid-cols-[1.1fr_0.7fr_0.8fr]">
                    <label className="block">
                        <span className="mb-2 block text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">회차</span>
                        <select
                            value={selectedRunId}
                            onChange={(event) => setSelectedRunId(event.target.value)}
                            className="h-12 w-full rounded-xl border border-white/10 bg-black/30 px-4 text-sm font-bold text-white outline-none focus:border-orange-400/50"
                        >
                            {runs.length === 0 && <option value="">등록된 회차 없음</option>}
                            {runs.map((run) => (
                                <option key={run.run_id} value={run.run_id}>{buildRunLabel(run)}</option>
                            ))}
                        </select>
                    </label>
                    <label className="block">
                        <span className="mb-2 block text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">판정</span>
                        <select
                            value={selectedResult}
                            onChange={(event) => setSelectedResult(event.target.value)}
                            className="h-12 w-full rounded-xl border border-white/10 bg-black/30 px-4 text-sm font-bold text-white outline-none focus:border-orange-400/50"
                        >
                            <option value="all">전체</option>
                            {(filters.length ? filters : DEFAULT_FILTERS).map((filter) => (
                                <option key={filter} value={filter}>{filter}</option>
                            ))}
                        </select>
                    </label>
                    <label className="block">
                        <span className="mb-2 block text-[11px] font-black uppercase tracking-[0.18em] text-slate-500">검색</span>
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="종목명, 코드, 산업"
                            className="h-12 w-full rounded-xl border border-white/10 bg-black/30 px-4 text-sm font-bold text-white outline-none placeholder:text-slate-600 focus:border-orange-400/50"
                        />
                    </label>
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-2">
                    <button
                        type="button"
                        onClick={() => applyResultFilter('all')}
                        className={`rounded-full border px-3 py-1.5 text-xs font-black transition ${
                            selectedResult === 'all'
                                ? 'border-cyan-300/50 bg-cyan-400/15 text-cyan-100 shadow-lg shadow-cyan-950/30'
                                : 'border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/40 hover:bg-cyan-400/10'
                        }`}
                    >
                        전체 {unfilteredTotal.toLocaleString('ko-KR')}
                    </button>
                    {Object.entries(summary).map(([label, count]) => (
                        <button
                            type="button"
                            key={label}
                            onClick={() => applyResultFilter(label)}
                            className={`rounded-full border px-3 py-1.5 text-xs font-black transition ${resultClass(label)} ${
                                selectedResult === label
                                    ? 'ring-2 ring-white/50 shadow-lg shadow-black/20'
                                    : 'hover:ring-1 hover:ring-white/30'
                            }`}
                        >
                            {label} {Number(count).toLocaleString('ko-KR')}
                        </button>
                    ))}
                    {loading && <span className="text-xs font-bold text-slate-500">loading...</span>}
                    {message && <span className="text-xs font-bold text-amber-300">{message}</span>}
                </div>
            </section>

            <section className="overflow-hidden rounded-2xl border border-white/10 bg-[#f4f4f5] text-slate-950 shadow-2xl shadow-black/20">
                <div className="flex items-center justify-between border-b border-slate-300/70 bg-white px-5 py-4">
                    <div>
                        <div className="text-xs font-black uppercase tracking-[0.2em] text-orange-600">Analysis Table</div>
                        <h2 className="text-lg font-black">AI 주식 분석 결과</h2>
                    </div>
                    <div className="text-right text-xs font-bold text-slate-500">
                        {isLiveRunSelected
                            ? `${isLoopRunning ? '실시간 루프 갱신 중' : '최근 루프 결과 출력 중'} · ${loopProcessed}/${loopTotal} · ${loopStatus?.current_stock || '대기'}`
                            : hiddenRecordCount > 0
                            ? `화면 ${visibleRecords.length.toLocaleString('ko-KR')}건 표시 · 추가 ${hiddenRecordCount.toLocaleString('ko-KR')}건은 엑셀 다운로드`
                            : detail?.created_at || selectedRun?.created_at || '--'}
                    </div>
                </div>

                <div className="max-h-[calc(100vh-380px)] min-h-[460px] overflow-auto">
                    <table className="min-w-full border-collapse text-sm">
                        <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-[0.14em] text-slate-600">
                            <tr>
                                <th className="border-b border-r border-slate-300 px-4 py-3 text-center">순번</th>
                                <th className="border-b border-r border-slate-300 px-4 py-3 text-center">종목명</th>
                                <th className="border-b border-r border-slate-300 px-4 py-3 text-center">산업</th>
                                <th className="border-b border-r border-slate-300 px-4 py-3 text-center">분석결과</th>
                                <th className="border-b border-slate-300 px-4 py-3 text-center">분석일시</th>
                            </tr>
                        </thead>
                        <tbody>
                            {visibleRecords.map((record) => (
                                <tr
                                    key={`${record.rank}-${record.stock_name}-${record.ticker}`}
                                    className={`hover:bg-orange-50 ${
                                        record.scrape_state === 'scraping'
                                            ? 'bg-cyan-50 ring-1 ring-inset ring-cyan-300'
                                            : 'odd:bg-white even:bg-slate-50'
                                    }`}
                                >
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center font-bold">{record.rank}</td>
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center font-bold">
                                        <div>{record.stock_name}{record.ticker ? ` (${record.ticker})` : ''}</div>
                                        {record.market && <div className="text-[11px] font-black uppercase tracking-widest text-slate-400">{record.market}</div>}
                                    </td>
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center">
                                        <div className="font-semibold">{record.industry || '미분류'}</div>
                                        {record.sector && (
                                            <div className="mt-1 text-[11px] font-black uppercase tracking-widest text-blue-700">
                                                부문 {record.sector}
                                            </div>
                                        )}
                                    </td>
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center">
                                        <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-black ${resultClass(record.result)}`}>
                                            {record.result}
                                        </span>
                                        <div className="mt-2 flex flex-wrap justify-center gap-1.5 text-[10px] font-black">
                                            {record.analyst_sentiment && (
                                                <span className="rounded-full border border-red-200 bg-red-50 px-2 py-1 text-red-600">
                                                    애널 {record.analyst_sentiment}
                                                </span>
                                            )}
                                            {record.technical_result && (
                                                <span className="rounded-full border border-slate-200 bg-white px-2 py-1 text-slate-600">
                                                    기술 {record.technical_result}
                                                </span>
                                            )}
                                            {record.target_price && (
                                                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700">
                                                    목표 {record.target_price}
                                                </span>
                                            )}
                                            {record.upside_potential && (
                                                <span className="rounded-full border border-orange-200 bg-orange-50 px-2 py-1 text-orange-700">
                                                    여력 {record.upside_potential}
                                                </span>
                                            )}
                                            {record.scrape_fallback && (
                                                <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-violet-700">
                                                    {record.scrape_fallback}
                                                </span>
                                            )}
                                        </div>
                                        {record.error && (
                                            <div className="mx-auto mt-2 max-w-md truncate rounded-lg border border-rose-200 bg-rose-50 px-2 py-1 text-[10px] font-bold text-rose-600">
                                                {record.error}
                                            </div>
                                        )}
                                        {record.scrape_state === 'scraping' && (
                                            <span className="ml-2 inline-flex animate-pulse rounded-full border border-cyan-300 bg-cyan-100 px-2 py-1 text-[10px] font-black text-cyan-700">
                                                진행중
                                            </span>
                                        )}
                                    </td>
                                    <td className="border-b border-slate-200 px-4 py-3 text-center font-medium">{record.analyzed_at}</td>
                                </tr>
                            ))}
                            {!loading && (!detail?.records || detail.records.length === 0) && (
                                <tr>
                                    <td colSpan={5} className="px-6 py-16 text-center text-sm font-bold text-slate-500">
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
