import { useEffect, useState, useCallback } from 'react';
import { fetchAPI } from '../../../lib/api';
import { useAutoRefresh, useSmartRefresh } from '../../../hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '../../../components/layout/PullToRefreshProvider';

interface VCPSignal {
    symbol: string;
    name: string;
    market?: string;
    price?: number;
    composite?: { composite_score: number; rating: string; entry_ready: boolean };
    trend_template?: { score: number; passed: boolean };
    vcp_pattern?: { score: number; valid_vcp: boolean; num_contractions?: number; pivot_price?: number };
    volume_pattern?: { score: number; dry_up_ratio?: number };
    pivot_proximity?: { score: number; distance_from_pivot_pct?: number; trade_status?: string };
    relative_strength?: { score: number; rs_rank_estimate?: number };
    stage?: { stage: number; stage_label?: string };
}

interface VCPData {
    metadata: { market: string; generated_at?: string; gate?: string; gate_score?: number };
    summary: { total_screened?: number; stage2_passed?: number; vcp_found?: number; entry_ready?: number };
    signals: VCPSignal[];
}

function ScoreBar({ score, label, color }: { score: number; label: string; color: string }) {
    return (
        <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 w-8 text-right">{label}</span>
            <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(score, 100)}%` }} />
            </div>
            <span className="text-[10px] text-gray-400 w-6">{score}</span>
        </div>
    );
}

function getRatingColor(rating?: string): string {
    if (!rating) return 'text-gray-400';
    if (rating.includes('Textbook')) return 'text-emerald-400';
    if (rating.includes('Strong')) return 'text-blue-400';
    if (rating.includes('Good')) return 'text-yellow-400';
    return 'text-gray-400';
}

function getScoreColor(score: number): string {
    if (score >= 80) return 'bg-emerald-500';
    if (score >= 70) return 'bg-blue-500';
    if (score >= 60) return 'bg-yellow-500';
    return 'bg-gray-500';
}

export default function UsVcpPage() {
    const [data, setData] = useState<VCPData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dates, setDates] = useState<string[]>([]);
    const [selectedDate, setSelectedDate] = useState<string>('latest');

    useEffect(() => {
        fetchAPI<string[]>('/api/us/vcp-enhanced/dates').then(setDates).catch(() => {});
    }, []);

    const loadData = useCallback(async (date: string) => {
        setLoading(true);
        setError(null);
        try {
            const url = date === 'latest' ? '/api/us/vcp-enhanced' : `/api/us/vcp-enhanced/history/${date}`;
            const result = await fetchAPI<VCPData>(url);
            setData(result);
        } catch (e: any) {
            setError(e.message || 'Failed to load data');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadData(selectedDate); }, [selectedDate, loadData]);

    const silentRefresh = useCallback(async () => {
        if (selectedDate !== 'latest') return;
        await loadData('latest');
    }, [loadData, selectedDate]);
    useAutoRefresh(silentRefresh, 60000, selectedDate === 'latest');
    useSmartRefresh(silentRefresh, ['vcp_us_latest.json'], 15000, selectedDate === 'latest');
    usePullToRefreshRegister(useCallback(async () => { await loadData(selectedDate); }, [loadData, selectedDate]));

    const signals = data?.signals || [];
    const meta = data?.metadata;
    const summary = data?.summary;

    return (
        <div className="flex flex-col gap-4 h-full min-h-0">
            <div className="flex items-end justify-between shrink-0">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <i className="fas fa-bolt text-emerald-400 text-sm" />
                        <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-widest">US VCP SIGNALS</span>
                    </div>
                    <h2 className="text-2xl font-extrabold tracking-tight text-white">
                        US Market{' '}
                        <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-300 to-emerald-500">VCP</span>
                    </h2>
                    <p className="text-xs text-gray-500 mt-1">Minervini SEPA — US Market Screening</p>
                </div>
                <div className="flex items-center gap-3">
                    {meta?.generated_at && (
                        <span className="text-[10px] text-gray-600">Updated: {new Date(meta.generated_at).toLocaleString()}</span>
                    )}
                    <select
                        value={selectedDate}
                        onChange={e => setSelectedDate(e.target.value)}
                        className="text-[11px] bg-[#13151f] border border-white/10 rounded-lg px-3 py-1.5 text-gray-300 focus:outline-none focus:border-emerald-500/50"
                    >
                        <option value="latest">Latest Report</option>
                        {dates.map(d => (
                            <option key={d} value={d}>{d}</option>
                        ))}
                    </select>
                </div>
            </div>

            {meta && (
                <div className="flex items-center gap-4 px-4 py-3 rounded-xl bg-[#13151f] border border-white/[0.06] shrink-0">
                    {meta.gate && (
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] text-gray-500 uppercase">Gate</span>
                            <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                                meta.gate === 'GREEN' ? 'bg-emerald-500/20 text-emerald-400' :
                                meta.gate === 'YELLOW' ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-red-500/20 text-red-400'
                            }`}>{meta.gate}</span>
                        </div>
                    )}
                    {meta.gate_score != null && (
                        <span className="text-xs text-gray-400">Score: <b className="text-white">{meta.gate_score}</b></span>
                    )}
                    <div className="h-4 w-px bg-white/10" />
                    {summary?.total_screened != null && <span className="text-[11px] text-gray-500">Screened: <b className="text-gray-300">{summary.total_screened}</b></span>}
                    {summary?.vcp_found != null && <span className="text-[11px] text-gray-500">VCP Found: <b className="text-yellow-400">{summary.vcp_found}</b></span>}
                    {summary?.entry_ready != null && <span className="text-[11px] text-gray-500">Entry Ready: <b className="text-emerald-400">{summary.entry_ready}</b></span>}
                </div>
            )}

            <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
                {loading && (
                    <div className="flex items-center justify-center py-20">
                        <div className="w-6 h-6 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
                {error && <div className="text-center py-12 text-red-400 text-sm">{error}</div>}
                {!loading && !error && signals.length === 0 && (
                    <div className="text-center py-20 text-gray-500">
                        <i className="fas fa-search text-3xl mb-3 block opacity-30" />
                        <p className="text-sm">No VCP signals detected for US Market</p>
                    </div>
                )}
                {!loading && signals.map((signal, i) => (
                    <div key={`${signal.symbol}-${i}`} className="p-4 rounded-xl bg-[#13151f] border border-white/[0.06] hover:border-white/10 transition-colors">
                        <div className="flex items-start justify-between mb-3">
                            <div>
                                <div className="flex items-center gap-2">
                                    <span className="text-white font-bold">{signal.symbol}</span>
                                    <span className="text-gray-500 text-sm">{signal.name}</span>
                                    {signal.composite?.entry_ready && (
                                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-400">ENTRY READY</span>
                                    )}
                                </div>
                                {signal.stage?.stage_label && <span className="text-[10px] text-gray-600 mt-0.5 block">{signal.stage.stage_label}</span>}
                            </div>
                            <div className="flex items-center gap-3">
                                {signal.price != null && <span className="text-sm text-gray-300 font-mono">${signal.price.toLocaleString()}</span>}
                                {signal.composite?.composite_score != null && (
                                    <div className="flex items-center gap-1.5">
                                        <div className={`w-2 h-2 rounded-full ${getScoreColor(signal.composite.composite_score)}`} />
                                        <span className="text-lg font-bold text-white">{signal.composite.composite_score.toFixed(0)}</span>
                                    </div>
                                )}
                                {signal.composite?.rating && (
                                    <span className={`text-[11px] font-semibold ${getRatingColor(signal.composite.rating)}`}>{signal.composite.rating}</span>
                                )}
                            </div>
                        </div>
                        <div className="grid grid-cols-5 gap-3">
                            {signal.trend_template && <ScoreBar score={signal.trend_template.score} label="Trend" color="bg-blue-500" />}
                            {signal.vcp_pattern && <ScoreBar score={signal.vcp_pattern.score} label="VCP" color="bg-yellow-500" />}
                            {signal.volume_pattern && <ScoreBar score={signal.volume_pattern.score} label="Vol" color="bg-purple-500" />}
                            {signal.pivot_proximity && <ScoreBar score={signal.pivot_proximity.score} label="Pivot" color="bg-emerald-500" />}
                            {signal.relative_strength && <ScoreBar score={signal.relative_strength.score} label="RS" color="bg-orange-500" />}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
