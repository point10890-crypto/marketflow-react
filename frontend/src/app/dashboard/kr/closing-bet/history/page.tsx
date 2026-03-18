'use client';

import { useEffect, useState, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface PricePoint {
    d: string;  // date
    h: number;  // high
    c: number;  // close
    hp: number; // high pct from entry
    cp: number; // close pct from entry
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
}

type SortKey = 'signal_date' | 'roi_pct' | 'score_total' | 'days_held' | 'stock_name' | 'grade' | 'max_high_pct';
type OutcomeFilter = 'ALL' | 'TARGET_HIT' | 'STOP_HIT' | 'OPEN';

export default function CumulativeHistoryPage() {
    const [loading, setLoading] = useState(true);
    const [signals, setSignals] = useState<CumulativeSignal[]>([]);
    const [stats, setStats] = useState<CumulativeStats | null>(null);
    const [sortBy, setSortBy] = useState<SortKey>('signal_date');
    const [sortAsc, setSortAsc] = useState(false);
    const [filter, setFilter] = useState<OutcomeFilter>('ALL');
    const [gradeFilter, setGradeFilter] = useState<string>('ALL');
    const [expandedRow, setExpandedRow] = useState<string | null>(null);

    useEffect(() => {
        loadData();
    }, []);

    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    const loadData = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/api/kr/jongga-v2/cumulative`);
            if (res.ok) {
                const data = await res.json();
                setSignals(data.signals || []);
                setStats(data.stats || null);
            }
        } catch (error) {
            console.error('Failed to load cumulative data:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSort = (key: SortKey) => {
        if (sortBy === key) {
            setSortAsc(!sortAsc);
        } else {
            setSortBy(key);
            setSortAsc(key === 'stock_name');
        }
    };

    const filtered = signals.filter(s => {
        if (filter !== 'ALL' && s.outcome !== filter) return false;
        if (gradeFilter !== 'ALL' && s.grade !== gradeFilter) return false;
        return true;
    });

    const sorted = [...filtered].sort((a, b) => {
        const av = a[sortBy] ?? '';
        const bv = b[sortBy] ?? '';
        if (typeof av === 'string') {
            return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
        }
        return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });

    const outcomeLabel = (o: string) => {
        switch (o) {
            case 'TARGET_HIT': return 'WIN';
            case 'STOP_HIT': return 'LOSS';
            default: return 'OPEN';
        }
    };

    const outcomeStyle = (o: string) => {
        switch (o) {
            case 'TARGET_HIT': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
            case 'STOP_HIT': return 'bg-red-500/20 text-red-400 border-red-500/30';
            default: return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
        }
    };

    const gradeStyle = (g: string) => {
        switch (g) {
            case 'S': return 'bg-indigo-500/20 text-indigo-400';
            case 'A': return 'bg-rose-500/20 text-rose-400';
            case 'B': return 'bg-blue-500/20 text-blue-400';
            default: return 'bg-gray-500/20 text-gray-400';
        }
    };

    const SortIcon = ({ column }: { column: SortKey }) => {
        if (sortBy !== column) return <span className="text-gray-600 ml-1">↕</span>;
        return <span className="text-indigo-400 ml-1">{sortAsc ? '↑' : '↓'}</span>;
    };

    const ThBtn = ({ column, label, align = 'left' }: { column: SortKey; label: string; align?: string }) => (
        <th
            className={`px-3 py-3 text-[10px] uppercase tracking-wider font-bold cursor-pointer hover:text-indigo-400 transition-colors whitespace-nowrap ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} ${sortBy === column ? 'text-indigo-400' : 'text-gray-500'}`}
            onClick={() => handleSort(column)}
        >
            {label}<SortIcon column={column} />
        </th>
    );

    const grades = ['S', 'A', 'B', 'C'];
    const gradeCounts = grades.reduce((acc, g) => {
        acc[g] = signals.filter(s => s.grade === g).length;
        return acc;
    }, {} as Record<string, number>);

    const targetPct = stats?.target_pct || 9;
    const stopPct = stats?.stop_pct || 5;

    const toggleRow = (key: string) => {
        setExpandedRow(expandedRow === key ? null : key);
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-indigo-500/20 bg-indigo-500/5 text-xs text-indigo-400 font-medium mb-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-ping"></span>
                    Performance Tracker
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                            Cumulative <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-cyan-400">Results</span>
                        </h2>
                        <p className="text-gray-400">
                            2026년 1월~ 종가베팅 V2 누적 성과
                            <span className="ml-2 text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                                Target +{targetPct}%
                            </span>
                            <span className="ml-1 text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-bold">
                                Stop -{stopPct}%
                            </span>
                        </p>
                    </div>
                    <button
                        onClick={loadData}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white hover:bg-white/10 transition-all disabled:opacity-50"
                    >
                        <i className={`fas fa-sync-alt mr-2 ${loading ? 'animate-spin' : ''}`}></i>
                        Refresh
                    </button>
                </div>
            </div>

            {/* Stats Cards */}
            {stats && !loading && (
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    <StatCard label="Total Signals" value={stats.total} />
                    <StatCard
                        label="Win Rate"
                        value={`${stats.win_rate}%`}
                        color={stats.win_rate >= 50 ? 'text-emerald-400' : stats.win_rate >= 35 ? 'text-yellow-400' : 'text-red-400'}
                    />
                    <StatCard label="Wins" value={stats.wins} color="text-emerald-400" />
                    <StatCard label="Losses" value={stats.losses} color="text-red-400" />
                    <StatCard label="Open" value={stats.open} color="text-yellow-400" />
                    <StatCard label="Avg ROI" value={`${stats.avg_roi > 0 ? '+' : ''}${stats.avg_roi}%`} color={stats.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                    <StatCard label="Total ROI" value={`${stats.total_roi > 0 ? '+' : ''}${stats.total_roi}%`} color={stats.total_roi >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                    <StatCard label="Avg Days" value={stats.avg_days_held} />
                    <StatCard label="Price Date" value={stats.latest_price_date} small />
                    <StatCard
                        label="Profit Factor"
                        value={stats.losses > 0 ? ((stats.wins * targetPct) / (stats.losses * stopPct)).toFixed(2) : '---'}
                        color="text-cyan-400"
                    />
                </div>
            )}

            {/* Grade ROI Cards */}
            {stats && stats.grade_roi && !loading && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {['S', 'A', 'B'].map(grade => {
                        const gr = stats.grade_roi[grade];
                        if (!gr || gr.count === 0) return null;
                        const gradeColors: Record<string, string> = {
                            S: 'from-indigo-500/20 to-purple-500/20 border-indigo-500/30',
                            A: 'from-rose-500/20 to-orange-500/20 border-rose-500/30',
                            B: 'from-blue-500/20 to-cyan-500/20 border-blue-500/30',
                        };
                        const textColors: Record<string, string> = {
                            S: 'text-indigo-400',
                            A: 'text-rose-400',
                            B: 'text-blue-400',
                        };
                        return (
                            <div key={grade} className={`p-4 rounded-xl bg-gradient-to-br ${gradeColors[grade]} border`}>
                                <div className="flex items-center justify-between mb-3">
                                    <span className={`text-lg font-black ${textColors[grade]}`}>{grade} Grade</span>
                                    <span className="text-xs text-gray-500">{gr.count} trades</span>
                                </div>
                                <div className="grid grid-cols-3 gap-2 text-center">
                                    <div>
                                        <div className="text-[10px] text-gray-500 uppercase">Win Rate</div>
                                        <div className={`text-sm font-bold ${gr.win_rate >= 50 ? 'text-emerald-400' : gr.win_rate >= 35 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {gr.win_rate}%
                                        </div>
                                    </div>
                                    <div>
                                        <div className="text-[10px] text-gray-500 uppercase">Avg ROI</div>
                                        <div className={`text-sm font-bold ${gr.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                            {gr.avg_roi > 0 ? '+' : ''}{gr.avg_roi}%
                                        </div>
                                    </div>
                                    <div>
                                        <div className="text-[10px] text-gray-500 uppercase">W/L</div>
                                        <div className="text-sm font-bold text-white">
                                            {gr.wins}/{gr.losses}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Win/Loss Bar */}
            {stats && stats.total > 0 && !loading && (
                <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-4">
                    <div className="flex items-center gap-3 mb-3">
                        <span className="text-xs text-gray-500 font-bold uppercase tracking-widest">Win/Loss Distribution</span>
                    </div>
                    <div className="flex h-6 rounded-full overflow-hidden bg-white/5">
                        {stats.wins > 0 && (
                            <div className="bg-emerald-500 flex items-center justify-center text-[10px] font-bold text-white" style={{ width: `${(stats.wins / stats.total) * 100}%` }}>
                                {stats.wins}W
                            </div>
                        )}
                        {stats.open > 0 && (
                            <div className="bg-gray-600 flex items-center justify-center text-[10px] font-bold text-white" style={{ width: `${(stats.open / stats.total) * 100}%` }}>
                                {stats.open}
                            </div>
                        )}
                        {stats.losses > 0 && (
                            <div className="bg-red-500 flex items-center justify-center text-[10px] font-bold text-white" style={{ width: `${(stats.losses / stats.total) * 100}%` }}>
                                {stats.losses}L
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-[10px] text-gray-500">
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500"></span> Target +{targetPct}% Hit ({((stats.wins / stats.total) * 100).toFixed(0)}%)</span>
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-600"></span> Open ({((stats.open / stats.total) * 100).toFixed(0)}%)</span>
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Stop -{stopPct}% Hit ({((stats.losses / stats.total) * 100).toFixed(0)}%)</span>
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs text-gray-500 font-bold">Outcome:</span>
                {(['ALL', 'TARGET_HIT', 'STOP_HIT', 'OPEN'] as OutcomeFilter[]).map(f => (
                    <button key={f} onClick={() => setFilter(f)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${filter === f ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}
                    >
                        {f === 'ALL' ? `All (${signals.length})` : f === 'TARGET_HIT' ? `Win (${signals.filter(s => s.outcome === f).length})` : f === 'STOP_HIT' ? `Loss (${signals.filter(s => s.outcome === f).length})` : `Open (${signals.filter(s => s.outcome === f).length})`}
                    </button>
                ))}
                <span className="text-xs text-gray-500 font-bold ml-4">Grade:</span>
                <button onClick={() => setGradeFilter('ALL')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${gradeFilter === 'ALL' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}
                >All</button>
                {grades.map(g => gradeCounts[g] > 0 && (
                    <button key={g} onClick={() => setGradeFilter(g)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${gradeFilter === g ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}
                    >{g} ({gradeCounts[g]})</button>
                ))}
            </div>

            {/* Table */}
            {loading ? (
                <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-8">
                    <div className="space-y-3">
                        {Array.from({ length: 10 }).map((_, i) => (
                            <div key={i} className="h-10 rounded bg-white/5 animate-pulse"></div>
                        ))}
                    </div>
                </div>
            ) : sorted.length === 0 ? (
                <div className="p-12 rounded-2xl bg-[#1c1c1e] border border-white/10 text-center">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-indigo-500/10 flex items-center justify-center">
                        <i className="fas fa-chart-line text-2xl text-indigo-500"></i>
                    </div>
                    <div className="text-gray-500 text-lg mb-2">No signals found</div>
                </div>
            ) : (
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
                                    <ThBtn column="max_high_pct" label="Max High" align="right" />
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-left whitespace-nowrap">Price Trail</th>
                                    <ThBtn column="days_held" label="Days" align="right" />
                                    <ThBtn column="score_total" label="Score" align="right" />
                                    <th className="px-3 py-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold text-left">Themes</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sorted.map((s, idx) => {
                                    const rowKey = `${s.stock_code}-${s.signal_date}`;
                                    const isExpanded = expandedRow === rowKey;
                                    return (
                                        <>
                                            <tr
                                                key={rowKey}
                                                onClick={() => s.price_trail.length > 0 && toggleRow(rowKey)}
                                                className={`border-b border-white/5 transition-colors ${s.price_trail.length > 0 ? 'cursor-pointer' : ''} ${isExpanded ? 'bg-indigo-500/10' : s.outcome === 'TARGET_HIT' ? 'bg-emerald-500/[0.02] hover:bg-emerald-500/[0.05]' : s.outcome === 'STOP_HIT' ? 'bg-red-500/[0.02] hover:bg-red-500/[0.05]' : 'hover:bg-indigo-500/5'}`}
                                            >
                                                <td className="px-3 py-2.5 text-xs text-gray-500 font-mono text-center">{idx + 1}</td>
                                                <td className="px-3 py-2.5 text-xs text-gray-300 font-mono whitespace-nowrap">{s.signal_date}</td>
                                                <td className="px-3 py-2.5 text-center">
                                                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${gradeStyle(s.grade)}`}>{s.grade}</span>
                                                </td>
                                                <td className="px-3 py-2.5">
                                                    <div className="text-sm font-bold text-white truncate max-w-[120px]">{s.stock_name}</div>
                                                    <div className="text-[10px] text-gray-500 font-mono">{s.stock_code} <span className={s.market === 'KOSPI' ? 'text-blue-400' : 'text-rose-400'}>{s.market}</span></div>
                                                </td>
                                                <td className="px-3 py-2.5 text-xs text-gray-400 text-right font-mono">{s.entry_price.toLocaleString()}</td>
                                                <td className="px-3 py-2.5 text-center">
                                                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${outcomeStyle(s.outcome)}`}>
                                                        {outcomeLabel(s.outcome)}
                                                    </span>
                                                </td>
                                                <td className={`px-3 py-2.5 text-sm font-bold text-right font-mono ${s.roi_pct > 0 ? 'text-emerald-400' : s.roi_pct < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                                                    {s.roi_pct > 0 ? '+' : ''}{s.roi_pct}%
                                                </td>
                                                <td className={`px-3 py-2.5 text-xs font-bold text-right font-mono ${s.max_high_pct >= targetPct ? 'text-emerald-400' : s.max_high_pct > 0 ? 'text-yellow-400' : 'text-gray-500'}`}>
                                                    {s.max_high_pct > 0 ? `+${s.max_high_pct.toFixed(1)}%` : '-'}
                                                </td>
                                                <td className="px-3 py-2.5">
                                                    <MiniTrail trail={s.price_trail} targetPct={targetPct} stopPct={stopPct} />
                                                </td>
                                                <td className="px-3 py-2.5 text-xs text-gray-400 text-right font-mono">{s.days_held}d</td>
                                                <td className="px-3 py-2.5 text-sm font-bold text-indigo-400 text-right">{s.score_total}</td>
                                                <td className="px-3 py-2.5">
                                                    <div className="flex flex-wrap gap-1 max-w-[120px]">
                                                        {s.themes.slice(0, 2).map((t, i) => (
                                                            <span key={i} className="px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 text-[9px] whitespace-nowrap">{t}</span>
                                                        ))}
                                                        {s.themes.length > 2 && <span className="text-[9px] text-gray-500">+{s.themes.length - 2}</span>}
                                                    </div>
                                                </td>
                                            </tr>
                                            {/* Expanded Price Trail */}
                                            {isExpanded && s.price_trail.length > 0 && (
                                                <tr key={`${rowKey}-detail`}>
                                                    <td colSpan={12} className="bg-[#141416] border-b border-white/5">
                                                        <div className="px-6 py-4">
                                                            <div className="flex items-center gap-4 mb-3">
                                                                <span className="text-xs font-bold text-gray-400">
                                                                    Daily Price Trail - {s.stock_name} ({s.signal_date})
                                                                </span>
                                                                <span className="text-[10px] text-gray-500">
                                                                    Entry: {s.entry_price.toLocaleString()} | Target(+{targetPct}%): {s.target_price.toLocaleString()} | Stop(-{stopPct}%): {s.stop_price.toLocaleString()}
                                                                </span>
                                                            </div>
                                                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                                                                {s.price_trail.map((pt, i) => {
                                                                    const hitTarget = pt.hp >= targetPct;
                                                                    const hitStop = pt.cp <= -stopPct;
                                                                    return (
                                                                        <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${hitTarget ? 'bg-emerald-500/10 border-emerald-500/20' : hitStop ? 'bg-red-500/10 border-red-500/20' : 'bg-white/[0.02] border-white/5'}`}>
                                                                            <span className="text-[10px] text-gray-500 font-mono w-20">{pt.d}</span>
                                                                            <div className="flex-1">
                                                                                <div className="flex items-center gap-2">
                                                                                    <span className="text-[10px] text-gray-500">H</span>
                                                                                    <span className="text-xs font-mono font-bold text-white">{pt.h.toLocaleString()}</span>
                                                                                    <span className={`text-[10px] font-bold font-mono ${pt.hp >= targetPct ? 'text-emerald-400' : pt.hp > 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                                                                                        {pt.hp > 0 ? '+' : ''}{pt.hp}%
                                                                                    </span>
                                                                                    {hitTarget && <span className="text-[9px] text-emerald-400 font-bold">TARGET</span>}
                                                                                </div>
                                                                                <div className="flex items-center gap-2">
                                                                                    <span className="text-[10px] text-gray-500">C</span>
                                                                                    <span className="text-xs font-mono text-gray-400">{pt.c.toLocaleString()}</span>
                                                                                    <span className={`text-[10px] font-mono ${pt.cp > 0 ? 'text-emerald-400/60' : 'text-red-400/60'}`}>
                                                                                        {pt.cp > 0 ? '+' : ''}{pt.cp}%
                                                                                    </span>
                                                                                </div>
                                                                            </div>
                                                                            {/* Mini progress bar */}
                                                                            <div className="w-16 h-4 relative">
                                                                                <div className="absolute inset-0 bg-white/5 rounded-full overflow-hidden">
                                                                                    <div
                                                                                        className={`h-full rounded-full ${pt.hp >= targetPct ? 'bg-emerald-500' : pt.hp > 0 ? 'bg-yellow-500/60' : 'bg-red-500/40'}`}
                                                                                        style={{ width: `${Math.min(Math.max((pt.hp / targetPct) * 100, 0), 100)}%` }}
                                                                                    ></div>
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                            {s.llm_reason && (
                                                                <div className="mt-3 text-xs text-gray-500 italic">
                                                                    <i className="fas fa-robot mr-1 text-indigo-500"></i>
                                                                    {s.llm_reason}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    <div className="px-4 py-3 border-t border-white/5 flex items-center justify-between text-xs text-gray-500">
                        <span>Showing {sorted.length} of {signals.length} signals (click row to expand price trail)</span>
                        <span>Price data: {stats?.latest_price_date || '-'}</span>
                    </div>
                </div>
            )}
        </div>
    );
}

/** Mini inline sparkline showing daily highs vs target */
function MiniTrail({ trail, targetPct, stopPct }: { trail: PricePoint[]; targetPct: number; stopPct: number }) {
    if (!trail || trail.length === 0) {
        return <span className="text-[10px] text-gray-600">-</span>;
    }

    const maxDots = 7;
    const pts = trail.slice(0, maxDots);

    return (
        <div className="flex items-center gap-0.5" title={pts.map(p => `${p.d}: high ${p.hp > 0 ? '+' : ''}${p.hp}%`).join('\n')}>
            {pts.map((pt, i) => {
                const ratio = pt.hp / targetPct; // 0~1+ (how close to target)
                let color = 'bg-gray-600';
                if (pt.hp >= targetPct) color = 'bg-emerald-400';
                else if (pt.hp >= targetPct * 0.6) color = 'bg-yellow-400';
                else if (pt.hp > 0) color = 'bg-yellow-600';
                else if (pt.hp <= -stopPct) color = 'bg-red-400';
                else color = 'bg-red-600/50';

                const height = Math.max(4, Math.min(16, 4 + Math.abs(ratio) * 12));

                return (
                    <div
                        key={i}
                        className={`w-1.5 rounded-full ${color} transition-all`}
                        style={{ height: `${height}px` }}
                    ></div>
                );
            })}
            {trail.length > maxDots && (
                <span className="text-[9px] text-gray-600 ml-0.5">+{trail.length - maxDots}</span>
            )}
        </div>
    );
}

function StatCard({ label, value, color = 'text-white', small = false }: {
    label: string;
    value: string | number;
    color?: string;
    small?: boolean;
}) {
    return (
        <div className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1 font-bold">{label}</div>
            <div className={`${small ? 'text-sm' : 'text-xl'} font-black ${color} font-mono`}>{value}</div>
        </div>
    );
}
