import { useEffect, useState, useCallback, useMemo } from 'react';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import { usAPI, API_BASE, type USAIChartSignal, type USAIChartAnalysisResponse } from '@/lib/api';
import { useIsMobile } from '@/hooks/useIsMobile';

// ── Signal badge ─────────────────────────────────────────────────────────────

const SIGNAL_STYLE: Record<string, string> = {
    BUY: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30',
    HOLD: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
    SELL: 'bg-red-500/20 text-red-400 border border-red-500/30',
};

function SignalBadge({ signal }: { signal: string }) {
    return (
        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${SIGNAL_STYLE[signal] ?? SIGNAL_STYLE['HOLD']}`}>
            {signal}
        </span>
    );
}

// ── Confidence bar ───────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
    const color = value >= 80 ? 'bg-emerald-500' : value >= 60 ? 'bg-yellow-500' : 'bg-red-500';
    return (
        <div className="flex items-center gap-2 w-full">
            <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
            </div>
            <span className="text-[10px] text-gray-400 tabular-nums w-7 text-right">{value}</span>
        </div>
    );
}

// ── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, accent, icon }: { label: string; value: string | number; accent: string; icon: string }) {
    return (
        <div className="flex flex-col gap-1 bg-[#13151f] border border-white/[0.07] rounded-2xl p-4">
            <div className="flex items-center gap-1.5">
                <i className={`fas ${icon} text-[10px]`} style={{ color: accent }} />
                <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">{label}</span>
            </div>
            <span className="text-2xl font-bold tabular-nums" style={{ color: accent }}>{value}</span>
        </div>
    );
}

// ── MA / RSI / Volume tag ────────────────────────────────────────────────────

function Tag({ label, value, color }: { label: string; value: string; color: string }) {
    return (
        <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${color}`}>
            {label}: {value}
        </span>
    );
}

function getMAColor(v: string) {
    if (v === 'bullish_aligned') return 'bg-emerald-500/20 text-emerald-400';
    if (v === 'bearish_aligned') return 'bg-red-500/20 text-red-400';
    return 'bg-gray-500/20 text-gray-400';
}
function getRSIColor(v: string) {
    if (v === 'oversold') return 'bg-emerald-500/20 text-emerald-400';
    if (v === 'overbought') return 'bg-red-500/20 text-red-400';
    return 'bg-gray-500/20 text-gray-400';
}
function getVolColor(v: string) {
    if (v === 'increasing') return 'bg-blue-500/20 text-blue-400';
    if (v === 'decreasing') return 'bg-orange-500/20 text-orange-400';
    return 'bg-gray-500/20 text-gray-400';
}

function maLabel(v: string) {
    if (v === 'bullish_aligned') return 'Bullish';
    if (v === 'bearish_aligned') return 'Bearish';
    return 'Mixed';
}
function rsiLabel(v: string) {
    if (v === 'oversold') return 'Oversold';
    if (v === 'overbought') return 'Overbought';
    return 'Neutral';
}
function volLabel(v: string) {
    if (v === 'increasing') return 'Up';
    if (v === 'decreasing') return 'Down';
    return 'Flat';
}

// ── Sort options ─────────────────────────────────────────────────────────────

type SortKey = 'confidence' | 'signal' | 'sector' | 'name';
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
    { key: 'confidence', label: 'Confidence' },
    { key: 'signal', label: 'Signal' },
    { key: 'sector', label: 'Sector' },
    { key: 'name', label: 'Name' },
];

const SIGNAL_ORDER: Record<string, number> = { BUY: 0, HOLD: 1, SELL: 2 };

// ── Filter options ───────────────────────────────────────────────────────────

type FilterSignal = 'ALL' | 'BUY' | 'HOLD' | 'SELL';

// ── Main Component ───────────────────────────────────────────────────────────

export default function UsAIChartPage() {
    const [data, setData] = useState<USAIChartAnalysisResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [sortKey, setSortKey] = useState<SortKey>('confidence');
    const [filterSignal, setFilterSignal] = useState<FilterSignal>('ALL');
    const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
    const isMobile = useIsMobile();

    const loadData = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const result = await usAPI.getAIChartAnalysis();
            setData(result);
        } catch {
            setError('Failed to load data');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadData(); }, [loadData]);
    usePullToRefreshRegister(loadData);

    const filtered = useMemo(() => {
        if (!data?.signals) return [];
        let list = data.signals;
        if (filterSignal !== 'ALL') {
            list = list.filter(s => s.signal === filterSignal);
        }
        return [...list].sort((a, b) => {
            switch (sortKey) {
                case 'confidence': return b.confidence - a.confidence;
                case 'signal': return (SIGNAL_ORDER[a.signal] ?? 1) - (SIGNAL_ORDER[b.signal] ?? 1);
                case 'sector': return a.sector.localeCompare(b.sector);
                case 'name': return a.name.localeCompare(b.name);
                default: return 0;
            }
        });
    }, [data, sortKey, filterSignal]);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="flex flex-col items-center justify-center h-64 gap-3">
                <i className="fas fa-exclamation-triangle text-2xl text-red-400" />
                <span className="text-gray-400 text-sm">{error ?? 'No data'}</span>
                <button onClick={loadData} className="text-xs text-blue-400 underline">Retry</button>
            </div>
        );
    }

    const { summary } = data;
    const buyCount = summary.by_signal?.BUY ?? 0;
    const holdCount = summary.by_signal?.HOLD ?? 0;
    const sellCount = summary.by_signal?.SELL ?? 0;

    return (
        <div className="flex flex-col gap-5 pb-8">
            {/* Header */}
            <div className="flex flex-col gap-1 pt-1">
                <div className="flex items-center gap-2">
                    <i className="fas fa-robot text-cyan-400" />
                    <h1 className="text-xl font-bold text-white">US AI Chart Analysis</h1>
                </div>
                <p className="text-[11px] text-gray-500">
                    Gemini Vision · S&P 500 Top 100 Technical Analysis
                    {data.updated_at && <span className="ml-2 text-gray-600">({data.updated_at})</span>}
                </p>
            </div>

            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard label="Total" value={summary.total} accent="#22d3ee" icon="fa-chart-bar" />
                <StatCard label="BUY" value={buyCount} accent="#34d399" icon="fa-arrow-up" />
                <StatCard label="HOLD" value={holdCount} accent="#fbbf24" icon="fa-minus" />
                <StatCard label="SELL" value={sellCount} accent="#f87171" icon="fa-arrow-down" />
            </div>

            {/* Signal Distribution Bar */}
            <div className="bg-[#13151f] border border-white/[0.07] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">Signal Distribution</span>
                    <span className="text-[10px] text-gray-600">Avg Confidence {summary.avg_confidence}%</span>
                </div>
                <div className="flex gap-3 mb-3">
                    {(['BUY', 'HOLD', 'SELL'] as const).map(sig => {
                        const cnt = summary.by_signal?.[sig] ?? 0;
                        const pct = summary.total > 0 ? (cnt / summary.total) * 100 : 0;
                        return (
                            <div key={sig} className="flex flex-col items-center gap-1 flex-1">
                                <SignalBadge signal={sig} />
                                <span className="text-sm font-bold text-white tabular-nums">{cnt}</span>
                                <span className="text-[9px] text-gray-600">{pct.toFixed(0)}%</span>
                            </div>
                        );
                    })}
                </div>
                <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5">
                    {[
                        { key: 'BUY', color: '#34d399' },
                        { key: 'HOLD', color: '#fbbf24' },
                        { key: 'SELL', color: '#f87171' },
                    ].map(({ key, color }) => {
                        const cnt = summary.by_signal?.[key] ?? 0;
                        const pct = summary.total > 0 ? (cnt / summary.total) * 100 : 0;
                        return pct > 0 ? (
                            <div key={key} className="rounded-full" style={{ width: `${pct}%`, background: color }} />
                        ) : null;
                    })}
                </div>
            </div>

            {/* Download */}
            <div className="flex justify-end">
                <a
                    href={`${API_BASE}/api/us/ai-chart-analysis/download`}
                    download
                    className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/20 transition-all"
                >
                    <i className="fas fa-file-excel" />
                    Excel Download
                </a>
            </div>

            {/* Filters & Sort */}
            <div className="flex flex-wrap items-center gap-2">
                {(['ALL', 'BUY', 'HOLD', 'SELL'] as const).map(f => (
                    <button
                        key={f}
                        onClick={() => setFilterSignal(f)}
                        className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all border ${
                            filterSignal === f
                                ? 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30'
                                : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/5'
                        }`}
                    >
                        {f === 'ALL' ? 'All' : f} {f !== 'ALL' && <span className="text-gray-600 ml-0.5">({summary.by_signal?.[f] ?? 0})</span>}
                    </button>
                ))}
                <div className="flex-1" />
                <div className="flex items-center gap-1">
                    <span className="text-[10px] text-gray-600">Sort:</span>
                    {SORT_OPTIONS.map(opt => (
                        <button
                            key={opt.key}
                            onClick={() => setSortKey(opt.key)}
                            className={`px-2 py-1 rounded text-[10px] font-semibold transition-all ${
                                sortKey === opt.key
                                    ? 'text-white bg-white/10'
                                    : 'text-gray-600 hover:text-gray-400'
                            }`}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Signal Cards */}
            <div className="flex flex-col gap-2">
                {filtered.length === 0 && (
                    <div className="text-center text-gray-500 text-sm py-12">No signals found</div>
                )}
                {filtered.map((s, idx) => {
                    const isExpanded = expandedIdx === idx;
                    return (
                        <div
                            key={`${s.ticker}-${idx}`}
                            className="bg-[#13151f] border border-white/[0.07] rounded-2xl overflow-hidden transition-all hover:border-white/[0.12]"
                        >
                            <button
                                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                                className="w-full px-4 py-3 flex items-center gap-3 text-left"
                            >
                                <SignalBadge signal={s.signal} />

                                <div className="flex flex-col min-w-0 flex-1">
                                    <span className="text-sm font-semibold text-white truncate">{s.name}</span>
                                    <span className="text-[10px] text-gray-600">{s.ticker} · {s.sector}</span>
                                </div>

                                {!isMobile && (
                                    <div className="flex items-center gap-1.5 shrink-0">
                                        <Tag label="MA" value={maLabel(s.ma_status)} color={getMAColor(s.ma_status)} />
                                        <Tag label="RSI" value={rsiLabel(s.rsi_zone)} color={getRSIColor(s.rsi_zone)} />
                                        <Tag label="Vol" value={volLabel(s.volume_trend)} color={getVolColor(s.volume_trend)} />
                                    </div>
                                )}

                                <div className={`${isMobile ? 'w-16' : 'w-28'} shrink-0`}>
                                    <ConfidenceBar value={s.confidence} />
                                </div>

                                <i className={`fas fa-chevron-down text-[10px] text-gray-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                            </button>

                            {isExpanded && (
                                <div className="px-4 pb-4 border-t border-white/[0.05]">
                                    {isMobile && (
                                        <div className="flex items-center gap-1.5 pt-3 pb-2">
                                            <Tag label="MA" value={maLabel(s.ma_status)} color={getMAColor(s.ma_status)} />
                                            <Tag label="RSI" value={rsiLabel(s.rsi_zone)} color={getRSIColor(s.rsi_zone)} />
                                            <Tag label="Vol" value={volLabel(s.volume_trend)} color={getVolColor(s.volume_trend)} />
                                        </div>
                                    )}
                                    <div className="pt-3 pb-2">
                                        <img
                                            src={`${API_BASE}/api/us/ai-chart-image/${s.ticker}`}
                                            alt={`${s.name} chart`}
                                            className="w-full rounded-lg border border-white/[0.06]"
                                            loading="lazy"
                                            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                        />
                                    </div>
                                    <div className="flex flex-col gap-1.5 pt-2">
                                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-widest">Analysis Reasons</span>
                                        {s.reasons.map((r, i) => (
                                            <div key={i} className="flex gap-2 text-xs text-gray-300">
                                                <span className="text-gray-600 shrink-0">{i + 1}.</span>
                                                <span>{r}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            <div className="text-center text-[10px] text-gray-600">
                Showing {filtered.length} of {summary.total} stocks
            </div>
        </div>
    );
}
