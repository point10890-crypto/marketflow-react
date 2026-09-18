'use client';

import { useEffect, useState, useCallback } from 'react';
import { fetchAPI } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import StockLink from '@/components/stock/StockLink';
import { useIsMobile } from '@/hooks/useIsMobile';

interface PricePoint {
    d: string;
    h: number;
    c: number;
    hp: number;
    cp: number;
}

interface CumulativeSignal {
    stock_code: string;
    stock_name: string;
    market: string;
    signal_date: string;
    grade: string;
    score_total: number;
    entry_price: number;
    target_price: number;
    stop_price: number;
    outcome: 'TARGET_HIT' | 'STOP_HIT' | 'OPEN';
    outcome_date: string | null;
    outcome_price: number;
    roi_pct: number;
    hold_roi_pct: number;
    days_held: number;
    current_price: number;
    max_high: number;
    max_high_pct: number;
    price_trail: PricePoint[];
    themes: string[];
    llm_reason: string;
    change_pct: number;
}

interface GradeROI {
    count: number;
    wins: number;
    losses: number;
    avg_roi: number;
    total_roi: number;
    win_rate: number;
    hold_avg_roi?: number;
    hold_win_rate?: number;
}

interface CumulativeStats {
    total: number;
    wins: number;
    losses: number;
    open: number;
    win_rate: number;
    avg_roi: number;
    total_roi: number;
    avg_days_held: number;
    latest_price_date: string;
    target_pct: number;
    stop_pct: number;
    grade_roi: Record<string, GradeROI>;
    hold_avg_roi?: number;
    hold_total_roi?: number;
    hold_median_roi?: number;
    hold_win_rate?: number;
    hold_wins?: number;
    hold_losses?: number;
}

interface CumulativeData {
    signals: CumulativeSignal[];
    stats: CumulativeStats;
}

type SortKey = 'signal_date' | 'roi_pct' | 'hold_roi_pct' | 'score_total' | 'days_held' | 'stock_name' | 'grade' | 'max_high_pct';
type OutcomeFilter = 'ALL' | 'TARGET_HIT' | 'STOP_HIT' | 'OPEN';

export default function ClosingBetHistoryPage() {
    const isMobile = useIsMobile();
    const [loading, setLoading] = useState(true);
    const [signals, setSignals] = useState<CumulativeSignal[]>([]);
    const [stats, setStats] = useState<CumulativeStats | null>(null);
    const [sortBy, setSortBy] = useState<SortKey>('signal_date');
    const [sortAsc, setSortAsc] = useState(false);
    const [filter, setFilter] = useState<OutcomeFilter>('ALL');
    const [gradeFilter, setGradeFilter] = useState<string>('ALL');
    const [expandedRow, setExpandedRow] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const PAGE_SIZE = 100;

    useEffect(() => { loadData(); }, []);
    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    const loadData = async () => {
        setLoading(true);
        try {
            const data = await fetchAPI<CumulativeData>('/api/kr/cumulative-return', 60000);
            setSignals(data.signals || []);
            setStats(data.stats || null);
        } catch { /* empty */ } finally {
            setLoading(false);
        }
    };

    const handleSort = (key: SortKey) => {
        if (sortBy === key) setSortAsc(!sortAsc);
        else { setSortBy(key); setSortAsc(key === 'stock_name'); }
    };

    const searchTrim = search.trim().toLowerCase();
    const filtered = signals.filter(s => {
        if (filter !== 'ALL' && s.outcome !== filter) return false;
        if (gradeFilter !== 'ALL' && s.grade !== gradeFilter) return false;
        if (searchTrim && !s.stock_name.toLowerCase().includes(searchTrim) && !s.stock_code.includes(searchTrim)) return false;
        return true;
    });
    // 필터/검색 변경 시 페이지 리셋
    const filterKey = `${filter}-${gradeFilter}-${searchTrim}`;
    const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
    if (filterKey !== prevFilterKey) { setPrevFilterKey(filterKey); setPage(1); }

    const sorted = [...filtered].sort((a, b) => {
        const av = a[sortBy] ?? '';
        const bv = b[sortBy] ?? '';
        if (typeof av === 'string') return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
        return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });

    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    const safePage = Math.min(page, totalPages);
    const paged = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
    const pageOffset = (safePage - 1) * PAGE_SIZE;

    const outcomeLabel = (o: string) => o === 'TARGET_HIT' ? 'WIN' : o === 'STOP_HIT' ? 'LOSS' : 'OPEN';
    const outcomeStyle = (o: string) => o === 'TARGET_HIT' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : o === 'STOP_HIT' ? 'bg-red-500/20 text-red-400 border-red-500/30' : 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    const gradeStyle = (g: string) => g === 'S' ? 'bg-indigo-500/20 text-indigo-400' : g === 'A' ? 'bg-rose-500/20 text-rose-400' : g === 'B' ? 'bg-blue-500/20 text-blue-400' : 'bg-gray-500/20 text-gray-400';

    const grades = ['S', 'A', 'B', 'C'];
    const gradeCounts = grades.reduce((acc, g) => { acc[g] = signals.filter(s => s.grade === g).length; return acc; }, {} as Record<string, number>);
    const targetPct = stats?.target_pct || 9;
    const stopPct = stats?.stop_pct || 5;

    /* ─── Sort helpers (desktop table) ─── */
    const SortIcon = ({ column }: { column: SortKey }) => {
        if (sortBy !== column) return <span className="text-gray-600 ml-1">↕</span>;
        return <span className="text-indigo-400 ml-1">{sortAsc ? '↑' : '↓'}</span>;
    };

    const ThBtn = ({ column, label, align = 'left' }: { column: SortKey; label: string; align?: string }) => (
        <th className={`px-3 py-3 text-[10px] uppercase tracking-wider font-bold cursor-pointer hover:text-indigo-400 transition-colors whitespace-nowrap ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} ${sortBy === column ? 'text-indigo-400' : 'text-gray-500'}`} onClick={() => handleSort(column)}>
            {label}<SortIcon column={column} />
        </th>
    );

    return (
        <div className="space-y-4 md:space-y-6">
            {/* ─── Header ─── */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-indigo-500/20 bg-indigo-500/5 text-xs text-indigo-400 font-medium mb-3">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-ping"></span>
                    Performance Tracker
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-2xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-1">
                            Cumulative <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-cyan-400">Results</span>
                        </h2>
                        <p className="text-gray-400 text-xs md:text-sm flex flex-wrap items-center gap-1">
                            <span>2026.01~ V2 누적 성과</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">+{targetPct}%</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-bold">-{stopPct}%</span>
                        </p>
                    </div>
                    <button onClick={loadData} disabled={loading} className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white hover:bg-white/10 transition-all disabled:opacity-50 shrink-0">
                        {loading ? '...' : '↻'}
                    </button>
                </div>
            </div>

            {/* ─── Stats Cards ─── */}
            {stats && !loading && (
                <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-6 gap-2 md:gap-3">
                    <StatCard label="Total" value={stats.total} />
                    <StatCard label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? 'text-emerald-400' : stats.win_rate >= 35 ? 'text-yellow-400' : 'text-red-400'} />
                    <StatCard label="W / L / O" value={`${stats.wins}/${stats.losses}/${stats.open}`} />
                    <StatCard label="Avg ROI" value={`${stats.avg_roi > 0 ? '+' : ''}${stats.avg_roi}%`} color={stats.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                    <StatCard label="Avg Days" value={stats.avg_days_held} />
                    <StatCard label="PF" value={stats.losses > 0 ? ((stats.wins * targetPct) / (stats.losses * stopPct)).toFixed(2) : '-'} color="text-cyan-400" />
                </div>
            )}

            {/* ─── Grade ROI Cards ─── */}
            {stats && stats.grade_roi && !loading && (
                <div className="grid grid-cols-3 gap-2 md:gap-3">
                    {['S', 'A', 'B'].map(grade => {
                        const gr = stats.grade_roi[grade];
                        if (!gr || gr.count === 0) return null;
                        const colors: Record<string, string> = { S: 'from-indigo-500/20 to-purple-500/20 border-indigo-500/30', A: 'from-rose-500/20 to-orange-500/20 border-rose-500/30', B: 'from-blue-500/20 to-cyan-500/20 border-blue-500/30' };
                        const textCol: Record<string, string> = { S: 'text-indigo-400', A: 'text-rose-400', B: 'text-blue-400' };
                        return (
                            <div key={grade} className={`p-3 rounded-xl bg-gradient-to-br ${colors[grade]} border`}>
                                <div className="flex items-center justify-between mb-2">
                                    <span className={`text-sm md:text-lg font-black ${textCol[grade]}`}>{grade}</span>
                                    <span className="text-[10px] text-gray-500">{gr.count}</span>
                                </div>
                                <div className="space-y-1 text-center">
                                    <div className="flex justify-between text-[10px]">
                                        <span className="text-gray-500">WR</span>
                                        <span className={`font-bold ${gr.win_rate >= 50 ? 'text-emerald-400' : gr.win_rate >= 35 ? 'text-yellow-400' : 'text-red-400'}`}>{gr.win_rate}%</span>
                                    </div>
                                    <div className="flex justify-between text-[10px]">
                                        <span className="text-gray-500">ROI</span>
                                        <span className={`font-bold ${gr.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{gr.avg_roi > 0 ? '+' : ''}{gr.avg_roi}%</span>
                                    </div>
                                    <div className="flex justify-between text-[10px]">
                                        <span className="text-gray-500">W/L</span>
                                        <span className="font-bold text-white">{gr.wins}/{gr.losses}</span>
                                    </div>
                                    {gr.hold_avg_roi !== undefined && (
                                        <div className="flex justify-between text-[10px] pt-1 border-t border-white/10">
                                            <span className="text-gray-500">Hold</span>
                                            <span className={`font-bold ${(gr.hold_avg_roi ?? 0) >= 0 ? 'text-amber-400' : 'text-red-400'}`}>{(gr.hold_avg_roi ?? 0) > 0 ? '+' : ''}{gr.hold_avg_roi}%</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* ─── Buy & Hold Comparison ─── */}
            {stats && stats.hold_avg_roi !== undefined && !loading && (
                <div className="rounded-xl bg-gradient-to-br from-amber-500/10 to-orange-500/10 border border-amber-500/20 p-3 md:p-5">
                    <div className="flex items-center gap-2 mb-3">
                        <span className="text-amber-400 font-black text-sm">Buy & Hold</span>
                        <span className="text-[9px] text-gray-500 px-1.5 py-0.5 rounded bg-white/5 border border-white/10">보유 시</span>
                    </div>
                    <div className="grid grid-cols-3 md:grid-cols-6 gap-2 md:gap-3">
                        <div className="text-center">
                            <div className="text-[9px] text-gray-500 uppercase font-bold">Avg</div>
                            <div className={`text-base md:text-xl font-black font-mono ${(stats.hold_avg_roi ?? 0) >= 0 ? 'text-amber-400' : 'text-red-400'}`}>{(stats.hold_avg_roi ?? 0) > 0 ? '+' : ''}{stats.hold_avg_roi}%</div>
                        </div>
                        <div className="text-center">
                            <div className="text-[9px] text-gray-500 uppercase font-bold">Median</div>
                            <div className={`text-base md:text-xl font-black font-mono ${(stats.hold_median_roi ?? 0) >= 0 ? 'text-amber-400' : 'text-red-400'}`}>{(stats.hold_median_roi ?? 0) > 0 ? '+' : ''}{stats.hold_median_roi}%</div>
                        </div>
                        <div className="text-center">
                            <div className="text-[9px] text-gray-500 uppercase font-bold">WR</div>
                            <div className={`text-base md:text-xl font-black font-mono ${(stats.hold_win_rate ?? 0) >= 50 ? 'text-amber-400' : 'text-red-400'}`}>{stats.hold_win_rate}%</div>
                        </div>
                        {!isMobile && <>
                            <div className="text-center">
                                <div className="text-[9px] text-gray-500 uppercase font-bold">Total</div>
                                <div className={`text-xl font-black font-mono ${(stats.hold_total_roi ?? 0) >= 0 ? 'text-amber-400' : 'text-red-400'}`}>{(stats.hold_total_roi ?? 0) > 0 ? '+' : ''}{stats.hold_total_roi}%</div>
                            </div>
                            <div className="text-center">
                                <div className="text-[9px] text-gray-500 uppercase font-bold">Wins</div>
                                <div className="text-xl font-black font-mono text-emerald-400">{stats.hold_wins}</div>
                            </div>
                            <div className="text-center">
                                <div className="text-[9px] text-gray-500 uppercase font-bold">Losses</div>
                                <div className="text-xl font-black font-mono text-red-400">{stats.hold_losses}</div>
                            </div>
                        </>}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-gray-500">
                        <span>Strategy {stats.avg_roi > 0 ? '+' : ''}{stats.avg_roi}%</span>
                        <span className="text-gray-600">vs</span>
                        <span className="text-amber-400">Hold {(stats.hold_avg_roi ?? 0) > 0 ? '+' : ''}{stats.hold_avg_roi}%</span>
                        <span className={`font-bold ${(stats.hold_avg_roi ?? 0) > stats.avg_roi ? 'text-amber-400' : 'text-emerald-400'}`}>
                            {(stats.hold_avg_roi ?? 0) > stats.avg_roi ? 'Hold' : 'Strategy'} +{Math.abs((stats.hold_avg_roi ?? 0) - stats.avg_roi).toFixed(1)}%
                        </span>
                    </div>
                </div>
            )}

            {/* ─── Win/Loss Bar ─── */}
            {stats && stats.total > 0 && !loading && (
                <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-3">
                    <span className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">Win/Loss</span>
                    <div className="flex h-5 rounded-full overflow-hidden bg-white/5 mt-2">
                        {stats.wins > 0 && <div className="bg-emerald-500 flex items-center justify-center text-[9px] font-bold text-white" style={{ width: `${(stats.wins / stats.total) * 100}%` }}>{stats.wins}W</div>}
                        {stats.open > 0 && <div className="bg-gray-600 flex items-center justify-center text-[9px] font-bold text-white" style={{ width: `${(stats.open / stats.total) * 100}%` }}>{stats.open}</div>}
                        {stats.losses > 0 && <div className="bg-red-500 flex items-center justify-center text-[9px] font-bold text-white" style={{ width: `${(stats.losses / stats.total) * 100}%` }}>{stats.losses}L</div>}
                    </div>
                </div>
            )}

            {/* ─── Filters + Search ─── */}
            <div className="flex flex-wrap items-center gap-1.5 md:gap-3">
                {(['ALL', 'TARGET_HIT', 'STOP_HIT', 'OPEN'] as OutcomeFilter[]).map(f => (
                    <button key={f} onClick={() => setFilter(f)} className={`px-2.5 py-1 rounded-lg text-[10px] md:text-xs font-bold transition-all ${filter === f ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10'}`}>
                        {f === 'ALL' ? `All ${signals.length}` : f === 'TARGET_HIT' ? `W ${signals.filter(s => s.outcome === f).length}` : f === 'STOP_HIT' ? `L ${signals.filter(s => s.outcome === f).length}` : `O ${signals.filter(s => s.outcome === f).length}`}
                    </button>
                ))}
                <span className="text-gray-600">|</span>
                <button onClick={() => setGradeFilter('ALL')} className={`px-2.5 py-1 rounded-lg text-[10px] md:text-xs font-bold transition-all ${gradeFilter === 'ALL' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10'}`}>All</button>
                {grades.map(g => gradeCounts[g] > 0 && (
                    <button key={g} onClick={() => setGradeFilter(g)} className={`px-2.5 py-1 rounded-lg text-[10px] md:text-xs font-bold transition-all ${gradeFilter === g ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10'}`}>{g}</button>
                ))}
                <div className="ml-auto flex items-center gap-1.5">
                    <div className="relative">
                        <input
                            type="text"
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="종목명 / 코드 검색"
                            className="w-36 md:w-48 pl-7 pr-2 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500/40 focus:bg-white/[0.07] transition-all"
                        />
                        <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 text-[10px]">🔍</span>
                        {search && (
                            <button onClick={() => setSearch('')} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white text-[10px] transition-colors">✕</button>
                        )}
                    </div>
                    {searchTrim && <span className="text-[10px] text-indigo-400 font-bold">{filtered.length}건</span>}
                </div>
            </div>

            {/* ─── Mobile Sort Selector ─── */}
            {isMobile && !loading && sorted.length > 0 && (
                <div className="flex items-center gap-2 text-[10px]">
                    <span className="text-gray-500 font-bold">Sort:</span>
                    {([['signal_date', 'Date'], ['roi_pct', 'ROI'], ['hold_roi_pct', 'Hold'], ['grade', 'Grade'], ['score_total', 'Score']] as [SortKey, string][]).map(([key, label]) => (
                        <button key={key} onClick={() => handleSort(key)} className={`px-2 py-0.5 rounded ${sortBy === key ? 'bg-indigo-500/20 text-indigo-400' : 'text-gray-500 bg-white/5'} font-bold`}>
                            {label}{sortBy === key && (sortAsc ? '↑' : '↓')}
                        </button>
                    ))}
                </div>
            )}

            {/* ─── Signal List ─── */}
            {loading ? (
                <div className="space-y-3">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-20 rounded-xl bg-white/5 animate-pulse" />)}</div>
            ) : sorted.length === 0 ? (
                <div className="p-12 rounded-2xl bg-[#1c1c1e] border border-white/10 text-center">
                    <div className="text-gray-500 text-lg">No signals found</div>
                </div>
            ) : isMobile ? (
                /* ═══ Mobile Card Layout ═══ */
                <div className="space-y-2">
                    {paged.map((s, idx) => {
                        const rowKey = `${s.stock_code}-${s.signal_date}`;
                        const isExpanded = expandedRow === rowKey;
                        const outcomeBg = s.outcome === 'TARGET_HIT' ? 'border-emerald-500/20' : s.outcome === 'STOP_HIT' ? 'border-red-500/20' : 'border-white/10';
                        return (
                            <div key={rowKey}
                                onClick={() => setExpandedRow(isExpanded ? null : rowKey)}
                                className={`rounded-xl bg-[#1c1c1e] border ${outcomeBg} p-3 transition-all active:scale-[0.99] ${isExpanded ? 'ring-1 ring-indigo-500/30' : ''}`}>
                                {/* Row 1: Header */}
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <span className="text-[10px] text-gray-600 font-mono w-5 shrink-0">{pageOffset + idx + 1}</span>
                                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${gradeStyle(s.grade)}`}>{s.grade}</span>
                                        <div className="min-w-0">
                                            <StockLink code={s.stock_code} market={s.market} className="text-sm font-bold text-white truncate block">{s.stock_name}</StockLink>
                                            <span className="text-[10px] text-gray-500 font-mono">{s.stock_code} <span className={s.market === 'KOSPI' ? 'text-blue-400' : 'text-rose-400'}>{s.market}</span></span>
                                        </div>
                                    </div>
                                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold border shrink-0 ${outcomeStyle(s.outcome)}`}>{outcomeLabel(s.outcome)}</span>
                                </div>
                                {/* Row 2: Key Metrics */}
                                <div className="grid grid-cols-4 gap-1 text-center">
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">ROI</div>
                                        <div className={`text-xs font-bold font-mono ${s.roi_pct > 0 ? 'text-emerald-400' : s.roi_pct < 0 ? 'text-red-400' : 'text-gray-400'}`}>{s.roi_pct > 0 ? '+' : ''}{s.roi_pct}%</div>
                                    </div>
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">Hold</div>
                                        <div className={`text-xs font-bold font-mono ${s.hold_roi_pct > 0 ? 'text-amber-400' : s.hold_roi_pct < 0 ? 'text-red-400' : 'text-gray-500'}`}>{s.hold_roi_pct > 0 ? '+' : ''}{s.hold_roi_pct}%</div>
                                    </div>
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">Max</div>
                                        <div className={`text-xs font-bold font-mono ${s.max_high_pct >= targetPct ? 'text-emerald-400' : s.max_high_pct > 0 ? 'text-yellow-400' : 'text-gray-500'}`}>{s.max_high_pct > 0 ? `+${s.max_high_pct.toFixed(1)}%` : '-'}</div>
                                    </div>
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">Score</div>
                                        <div className="text-xs font-bold font-mono text-indigo-400">{s.score_total}</div>
                                    </div>
                                </div>
                                {/* Row 3: Sub info */}
                                <div className="flex items-center justify-between mt-2 text-[10px] text-gray-500">
                                    <span className="font-mono">{s.signal_date.slice(5)}</span>
                                    <span className="font-mono">{s.entry_price.toLocaleString()} → {s.current_price.toLocaleString()}</span>
                                    <span>{s.days_held}d</span>
                                    <MiniTrail trail={s.price_trail} targetPct={targetPct} stopPct={stopPct} />
                                </div>
                                {/* Expanded: themes + llm_reason */}
                                {isExpanded && (
                                    <div className="mt-2 pt-2 border-t border-white/5 space-y-1.5">
                                        {s.themes.length > 0 && (
                                            <div className="flex flex-wrap gap-1">
                                                {s.themes.map((t, i) => <span key={i} className="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 text-[9px]">{t}</span>)}
                                            </div>
                                        )}
                                        {s.llm_reason && <p className="text-[10px] text-gray-400 leading-relaxed">{s.llm_reason}</p>}
                                        <div className="grid grid-cols-3 gap-2 text-[10px] text-gray-500">
                                            <div>Target: <span className="text-emerald-400">{s.target_price.toLocaleString()}</span></div>
                                            <div>Stop: <span className="text-red-400">{s.stop_price.toLocaleString()}</span></div>
                                            {s.outcome_date && <div>Hit: <span className="text-white">{s.outcome_date.slice(5)}</span></div>}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                    <Pagination currentPage={safePage} totalPages={totalPages} onPageChange={setPage} totalItems={sorted.length} />
                </div>
            ) : (
                /* ═══ Desktop Table Layout ═══ */
                <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-white/10 bg-white/[0.02]">
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-center w-10">#</th>
                                    <ThBtn column="signal_date" label="Date" />
                                    <ThBtn column="grade" label="Grade" align="center" />
                                    <ThBtn column="stock_name" label="Name" />
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-right">Entry</th>
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-center">Outcome</th>
                                    <ThBtn column="roi_pct" label="ROI" align="right" />
                                    <ThBtn column="hold_roi_pct" label="Hold" align="right" />
                                    <ThBtn column="max_high_pct" label="Max High" align="right" />
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-left whitespace-nowrap">Price Trail</th>
                                    <ThBtn column="days_held" label="Days" align="right" />
                                    <ThBtn column="score_total" label="Score" align="right" />
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-left">Themes</th>
                                </tr>
                            </thead>
                            <tbody>
                                {paged.map((s, idx) => {
                                    const rowKey = `${s.stock_code}-${s.signal_date}`;
                                    const isExpanded = expandedRow === rowKey;
                                    return (
                                        <tr key={rowKey} onClick={() => s.price_trail.length > 0 && setExpandedRow(isExpanded ? null : rowKey)}
                                            className={`border-b border-white/5 transition-colors ${s.price_trail.length > 0 ? 'cursor-pointer' : ''} ${isExpanded ? 'bg-indigo-500/10' : s.outcome === 'TARGET_HIT' ? 'bg-emerald-500/[0.02] hover:bg-emerald-500/[0.05]' : s.outcome === 'STOP_HIT' ? 'bg-red-500/[0.02] hover:bg-red-500/[0.05]' : 'hover:bg-indigo-500/5'}`}>
                                            <td className="px-3 py-2.5 text-xs text-gray-500 font-mono text-center">{pageOffset + idx + 1}</td>
                                            <td className="px-3 py-2.5 text-xs text-gray-300 font-mono whitespace-nowrap">{s.signal_date}</td>
                                            <td className="px-3 py-2.5 text-center"><span className={`px-2 py-0.5 rounded text-[10px] font-bold ${gradeStyle(s.grade)}`}>{s.grade}</span></td>
                                            <td className="px-3 py-2.5">
                                                <div className="text-sm font-bold text-white truncate max-w-[120px]"><StockLink code={s.stock_code} market={s.market}>{s.stock_name}</StockLink></div>
                                                <div className="text-[10px] text-gray-500 font-mono">{s.stock_code} <span className={s.market === 'KOSPI' ? 'text-blue-400' : 'text-rose-400'}>{s.market}</span></div>
                                            </td>
                                            <td className="px-3 py-2.5 text-xs text-gray-400 text-right font-mono">{s.entry_price.toLocaleString()}</td>
                                            <td className="px-3 py-2.5 text-center"><span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${outcomeStyle(s.outcome)}`}>{outcomeLabel(s.outcome)}</span></td>
                                            <td className={`px-3 py-2.5 text-sm font-bold text-right font-mono ${s.roi_pct > 0 ? 'text-emerald-400' : s.roi_pct < 0 ? 'text-red-400' : 'text-gray-400'}`}>{s.roi_pct > 0 ? '+' : ''}{s.roi_pct}%</td>
                                            <td className={`px-3 py-2.5 text-xs font-bold text-right font-mono ${s.hold_roi_pct > 0 ? 'text-amber-400' : s.hold_roi_pct < 0 ? 'text-red-400' : 'text-gray-500'}`}>{s.hold_roi_pct > 0 ? '+' : ''}{s.hold_roi_pct}%</td>
                                            <td className={`px-3 py-2.5 text-xs font-bold text-right font-mono ${s.max_high_pct >= targetPct ? 'text-emerald-400' : s.max_high_pct > 0 ? 'text-yellow-400' : 'text-gray-500'}`}>{s.max_high_pct > 0 ? `+${s.max_high_pct.toFixed(1)}%` : '-'}</td>
                                            <td className="px-3 py-2.5"><MiniTrail trail={s.price_trail} targetPct={targetPct} stopPct={stopPct} /></td>
                                            <td className="px-3 py-2.5 text-xs text-gray-400 text-right font-mono">{s.days_held}d</td>
                                            <td className="px-3 py-2.5 text-sm font-bold text-indigo-400 text-right">{s.score_total}</td>
                                            <td className="px-3 py-2.5">
                                                <div className="flex flex-wrap gap-1 max-w-[120px]">
                                                    {s.themes.slice(0, 2).map((t, i) => <span key={i} className="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 text-[9px] whitespace-nowrap">{t}</span>)}
                                                    {s.themes.length > 2 && <span className="text-[9px] text-gray-500">+{s.themes.length - 2}</span>}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    <Pagination currentPage={safePage} totalPages={totalPages} onPageChange={setPage} totalItems={sorted.length} />
                </div>
            )}
        </div>
    );
}

function MiniTrail({ trail, targetPct, stopPct }: { trail: PricePoint[]; targetPct: number; stopPct: number }) {
    if (!trail || trail.length === 0) return <span className="text-[10px] text-gray-600">-</span>;
    const pts = trail.slice(0, 7);
    return (
        <div className="flex items-center gap-0.5">
            {pts.map((pt, i) => {
                const ratio = pt.hp / targetPct;
                const color = pt.hp >= targetPct ? 'bg-emerald-400' : pt.hp >= targetPct * 0.6 ? 'bg-yellow-400' : pt.hp > 0 ? 'bg-yellow-600' : pt.hp <= -stopPct ? 'bg-red-400' : 'bg-red-600/50';
                return <div key={i} className={`w-1.5 rounded-full ${color}`} style={{ height: `${Math.max(4, Math.min(16, 4 + Math.abs(ratio) * 12))}px` }} />;
            })}
            {trail.length > 7 && <span className="text-[9px] text-gray-600 ml-0.5">+{trail.length - 7}</span>}
        </div>
    );
}

function Pagination({ currentPage, totalPages, onPageChange, totalItems }: { currentPage: number; totalPages: number; onPageChange: (p: number) => void; totalItems: number }) {
    if (totalPages <= 1) return <div className="px-4 py-3 border-t border-white/5 text-center text-[10px] text-gray-600">{totalItems} signals</div>;

    // 보이는 페이지 번호: 현재 기준 앞뒤 2개 + 첫/끝
    const pages: (number | '...')[] = [];
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
            pages.push(i);
        } else if (pages[pages.length - 1] !== '...') {
            pages.push('...');
        }
    }

    return (
        <div className="px-4 py-3 border-t border-white/5 flex items-center justify-between gap-2">
            <span className="text-[10px] text-gray-600 shrink-0">{totalItems}건</span>
            <div className="flex items-center gap-1">
                <button onClick={() => onPageChange(Math.max(1, currentPage - 1))} disabled={currentPage <= 1}
                    className="w-7 h-7 rounded-lg text-xs font-bold flex items-center justify-center bg-white/5 text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
                    ‹
                </button>
                {pages.map((p, i) =>
                    p === '...' ? (
                        <span key={`dots-${i}`} className="text-[10px] text-gray-600 px-1">…</span>
                    ) : (
                        <button key={p} onClick={() => onPageChange(p)}
                            className={`w-7 h-7 rounded-lg text-xs font-bold flex items-center justify-center transition-all ${
                                p === currentPage
                                    ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
                                    : 'bg-white/5 text-gray-400 hover:bg-white/10'
                            }`}>
                            {p}
                        </button>
                    )
                )}
                <button onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))} disabled={currentPage >= totalPages}
                    className="w-7 h-7 rounded-lg text-xs font-bold flex items-center justify-center bg-white/5 text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
                    ›
                </button>
            </div>
            <span className="text-[10px] text-gray-600 shrink-0">{currentPage}/{totalPages}</span>
        </div>
    );
}

function StatCard({ label, value, color = 'text-white' }: { label: string; value: string | number; color?: string }) {
    return (
        <div className="p-2.5 md:p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
            <div className="text-[9px] md:text-[10px] text-gray-500 uppercase tracking-widest mb-0.5 font-bold truncate">{label}</div>
            <div className={`text-base md:text-xl font-black ${color} font-mono`}>{value}</div>
        </div>
    );
}
