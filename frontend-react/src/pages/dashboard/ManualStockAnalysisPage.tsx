import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE, authHeaders } from '@/lib/api';

interface ManualRunSummary {
    run_id: string;
    title: string;
    created_at: string;
    record_count: number;
    source_kind: string;
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
    return `${created} · ${run.title || run.run_id}`;
}

function formatSeconds(seconds: number) {
    if (!Number.isFinite(seconds) || seconds <= 0) return '--';
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
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const [loopInterval, setLoopInterval] = useState(1);
    const fileRef = useRef<HTMLInputElement | null>(null);
    const loopRunRef = useRef('');

    const selectedRun = useMemo(
        () => runs.find((run) => run.run_id === selectedRunId) || null,
        [runs, selectedRunId],
    );

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
            const preferredExists = preferredRunId && nextRuns.some((run) => run.run_id === preferredRunId);
            const selectedExists = selectedRunId && nextRuns.some((run) => run.run_id === selectedRunId);
            const nextSelected = preferredExists
                ? preferredRunId
                : selectedExists
                    ? selectedRunId
                    : nextRuns[0]?.run_id || '';
            setSelectedRunId(nextSelected);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '회차 목록 조회 실패');
        } finally {
            setLoading(false);
        }
    }, [selectedRunId]);

    const fetchRunDetail = useCallback(async () => {
        if (!selectedRunId) {
            setDetail(null);
            return;
        }
        setLoading(true);
        setMessage('');
        const params = new URLSearchParams();
        params.set('result', selectedResult);
        if (query.trim()) params.set('q', query.trim());
        if (loopStatus?.running && loopStatus.last_run_id && selectedRunId === loopStatus.last_run_id) {
            params.set('live', '1');
        }
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/runs/${selectedRunId}?${params.toString()}`, {
                headers: authHeaders(),
            });
            if (!res.ok) throw new Error(`분석 목록 조회 실패 (${res.status})`);
            setDetail(await res.json());
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '분석 목록 조회 실패');
        } finally {
            setLoading(false);
        }
    }, [loopStatus?.last_run_id, loopStatus?.running, query, selectedResult, selectedRunId]);

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
            if (data.last_run_id && (data.last_run_id !== loopRunRef.current || selectedRunId !== data.last_run_id)) {
                await fetchRuns(data.last_run_id);
                loopRunRef.current = data.last_run_id;
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
            if (loopStatus?.running) fetchRunDetail();
        }, loopStatus?.running ? 1000 : 2500);
        return () => window.clearInterval(id);
    }, [fetchLoopStatus, fetchRunDetail, loopStatus?.running]);

    const handleUpload = async (file: File | null) => {
        if (!file) return;
        setBusy(true);
        setMessage('');
        const form = new FormData();
        form.append('file', file);
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/runs/upload`, {
                method: 'POST',
                headers: authHeaders(),
                body: form,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || `업로드 실패 (${res.status})`);
            setSelectedRunId(data.run?.run_id || '');
            setMessage('결과 Excel 업로드가 완료되었습니다.');
            await fetchRuns(data.run?.run_id);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '업로드 실패');
        } finally {
            setBusy(false);
            if (fileRef.current) fileRef.current.value = '';
        }
    };

    const runScraper = async () => {
        setBusy(true);
        setMessage('');
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/runs/scrape`, {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ max_rows: 0, timeout_sec: 10 }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || `스크래퍼 실행 실패 (${res.status})`);
            setSelectedRunId(data.run?.run_id || '');
            setMessage(`전체 스크래프 완료: ${data.run?.record_count || 0}건`);
            await fetchRuns(data.run?.run_id);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '스크래퍼 실행 실패');
        } finally {
            setBusy(false);
            fetchLoopStatus();
        }
    };

    const startLoop = async () => {
        setBusy(true);
        setMessage('');
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/scraper-loop/start`, {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({
                    max_rows: 0,
                    interval_sec: loopInterval * 60,
                    timeout_sec: 10,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || `루프 시작 실패 (${res.status})`);
            loopRunRef.current = '';
            setLoopStatus(data);
            setMessage('실시간 스크래퍼 루프가 시작되었습니다.');
            await fetchLoopStatus();
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '루프 시작 실패');
        } finally {
            setBusy(false);
        }
    };

    const stopLoop = async () => {
        setBusy(true);
        setMessage('');
        try {
            const res = await fetch(`${API_BASE}/api/manual-stock-analysis/scraper-loop/stop`, {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || `루프 중지 실패 (${res.status})`);
            setLoopStatus(data);
            setMessage('실시간 스크래퍼 루프를 중지했습니다.');
        } catch (err) {
            setMessage(err instanceof Error ? err.message : '루프 중지 실패');
        } finally {
            setBusy(false);
        }
    };

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
    const isLiveRunSelected = isLoopRunning && !!loopStatus?.last_run_id && selectedRunId === loopStatus.last_run_id;

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
                            기본 소스는 E:\다운로드\stock_data.xlsx이며, 스크래퍼 루프가 전체 종목을 순번대로 반복 분석합니다.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <label className="flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 text-xs font-black text-slate-300">
                            cycle delay
                            <input
                                type="number"
                                min={1}
                                max={1440}
                                value={loopInterval}
                                onChange={(event) => setLoopInterval(Math.max(1, Math.min(1440, Number(event.target.value) || 15)))}
                                className="h-7 w-16 rounded-lg border border-white/10 bg-black/40 px-2 text-right text-white outline-none"
                            />
                            min
                        </label>
                        <button
                            type="button"
                            onClick={runScraper}
                            disabled={busy}
                            className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-4 py-2 text-sm font-black text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                        >
                            1회 전체 스크래프
                        </button>
                        <button
                            type="button"
                            onClick={startLoop}
                            disabled={busy || isLoopRunning}
                            className="rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-4 py-2 text-sm font-black text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                            무한 루프 시작
                        </button>
                        <button
                            type="button"
                            onClick={stopLoop}
                            disabled={busy || !isLoopRunning}
                            className="rounded-xl border border-slate-500/40 bg-white/5 px-4 py-2 text-sm font-black text-slate-200 transition hover:bg-white/10 disabled:opacity-50"
                        >
                            루프 중지
                        </button>
                        <input
                            ref={fileRef}
                            type="file"
                            accept=".xlsx,.xls"
                            className="hidden"
                            onChange={(event) => handleUpload(event.target.files?.[0] || null)}
                        />
                        <button
                            type="button"
                            onClick={() => fileRef.current?.click()}
                            disabled={busy}
                            className="rounded-xl border border-orange-400/25 bg-orange-500/10 px-4 py-2 text-sm font-black text-orange-200 transition hover:bg-orange-500/20 disabled:opacity-50"
                        >
                            결과 Excel 업로드
                        </button>
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
                                    {formatSeconds(loopStatus?.interval_sec || loopInterval * 60)} interval
                                </span>
                                <span className="rounded-full border border-cyan-400/20 bg-cyan-500/10 px-3 py-1 text-xs font-black text-cyan-100">
                                    source {loopStatus?.source_record_count || unfilteredTotal || 0}
                                </span>
                            </div>
                            <div className="mt-2 text-xs font-bold text-slate-500">
                                {loopStatus?.source_path || 'E:\\다운로드\\stock_data.xlsx'}
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-right text-xs font-black text-slate-400 sm:grid-cols-4">
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">진행</div>
                                <div className="text-lg text-white">{loopProcessed}/{loopTotal}</div>
                            </div>
                            <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                                <div className="text-slate-500">회차</div>
                                <div className="text-lg text-white">{loopStatus?.iterations || 0}</div>
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
                            ? `실시간 루프 갱신 중 · ${loopProcessed}/${loopTotal} · ${loopStatus?.current_stock || '대기'}`
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
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center">{record.industry || '미분류'}</td>
                                    <td className="border-b border-r border-slate-200 px-4 py-3 text-center">
                                        <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-black ${resultClass(record.result)}`}>
                                            {record.result}
                                        </span>
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
                                        표시할 AI 주식 분석 결과가 없습니다. 무한 루프 시작으로 기본 소스 전체를 순차 분석해 주세요.
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
