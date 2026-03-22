import { useEffect, useState, useCallback } from 'react';
import { usAPI } from '@/lib/api';
import { useIsMobile } from '@/hooks/useIsMobile';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface ETFFlow {
    ticker: string;
    name: string;
    category: string;
    close: number;
    flow_5d: number;
    flow_20d: number;
    flow_score: number;
    flow_status: string;
    price_5d: number;
    price_20d: number;
    vol_ratio: number;
    dollar_volume: number;
}

interface Sentiment {
    overall_score: number;
    sentiment: string;
    broad_market_score: number;
    risk_on_score: number;
    risk_off_score: number;
}

type SortKey = 'flow_score' | 'flow_5d' | 'flow_20d' | 'price_5d';

export default function UsEtfPage() {
    const isMobile = useIsMobile();
    const [loading, setLoading] = useState(true);
    const [flows, setFlows] = useState<ETFFlow[]>([]);
    const [sentiment, setSentiment] = useState<Sentiment | null>(null);
    const [aiAnalysis, setAiAnalysis] = useState('');
    const [activeCategory, setActiveCategory] = useState('All');
    const [sortBy, setSortBy] = useState<SortKey>('flow_score');
    const [sortAsc, setSortAsc] = useState(false);

    useEffect(() => { loadData(); }, []);
    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    const loadData = async () => {
        setLoading(true);
        try {
            const data = await usAPI.getEtfFlowAnalysis();
            setFlows(data.flows || []);
            setSentiment(data.sentiment || null);
            setAiAnalysis(data.ai_analysis || '');
        } catch (error) {
            console.error('Failed to load ETF:', error);
        } finally {
            setLoading(false);
        }
    };

    const categories = ['All', ...Array.from(new Set(flows.map(f => f.category)))];
    const filtered = activeCategory === 'All' ? flows : flows.filter(f => f.category === activeCategory);
    const sorted = [...filtered].sort((a, b) => {
        const diff = (a[sortBy] ?? 0) - (b[sortBy] ?? 0);
        return sortAsc ? diff : -diff;
    });

    const handleSort = (key: SortKey) => {
        if (sortBy === key) setSortAsc(!sortAsc);
        else { setSortBy(key); setSortAsc(false); }
    };

    const formatFlow = (val: number) => {
        if (val == null) return '-';
        const prefix = val >= 0 ? '+' : '';
        return `${prefix}${val.toFixed(2)}B`;
    };

    const getFlowColor = (val: number) => {
        if (val > 0) return 'text-green-400';
        if (val < 0) return 'text-red-400';
        return 'text-gray-400';
    };

    const getScoreColor = (score: number) => {
        if (score >= 70) return 'text-green-400';
        if (score >= 55) return 'text-cyan-400';
        if (score >= 45) return 'text-gray-400';
        if (score >= 30) return 'text-orange-400';
        return 'text-red-400';
    };

    const getStatusBadge = (status: string) => {
        const map: Record<string, string> = {
            'Strong Inflow': 'bg-green-500/20 text-green-400 border-green-500/30',
            'Inflow': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
            'Neutral': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
            'Outflow': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
            'Strong Outflow': 'bg-red-500/20 text-red-400 border-red-500/30',
        };
        return map[status] || map['Neutral'];
    };

    const getSentimentColor = (s: string) => {
        if (s.includes('Bullish') || s.includes('Risk-On')) return 'text-green-400';
        if (s.includes('Bearish') || s.includes('Risk-Off')) return 'text-red-400';
        return 'text-yellow-400';
    };

    return (
        <div className="space-y-4 md:space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/5 text-xs text-cyan-400 font-medium mb-3 md:mb-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-ping"></span>
                    Fund Flows
                </div>
                <h2 className="text-2xl md:text-3xl font-bold tracking-tighter text-white mb-1 md:mb-2">
                    ETF <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-400">Flows</span>
                </h2>
                <p className="text-gray-400 text-sm md:text-base">섹터 ETF 자금 유입/유출 분석</p>
            </div>

            {/* Sentiment Cards */}
            {sentiment && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-3">
                    <div className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
                        <div className="text-[10px] text-gray-500 mb-1">Overall</div>
                        <div className={`text-lg font-bold ${getSentimentColor(sentiment.sentiment)}`}>
                            {sentiment.overall_score}
                        </div>
                        <div className={`text-[10px] ${getSentimentColor(sentiment.sentiment)}`}>{sentiment.sentiment}</div>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
                        <div className="text-[10px] text-gray-500 mb-1">Broad Market</div>
                        <div className={`text-lg font-bold ${getScoreColor(sentiment.broad_market_score)}`}>
                            {sentiment.broad_market_score}
                        </div>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
                        <div className="text-[10px] text-gray-500 mb-1">Risk-On</div>
                        <div className={`text-lg font-bold ${getScoreColor(sentiment.risk_on_score)}`}>
                            {sentiment.risk_on_score}
                        </div>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
                        <div className="text-[10px] text-gray-500 mb-1">Risk-Off</div>
                        <div className={`text-lg font-bold ${getScoreColor(sentiment.risk_off_score)}`}>
                            {sentiment.risk_off_score}
                        </div>
                    </div>
                </div>
            )}

            {/* Category Filter */}
            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                {categories.map(cat => (
                    <button
                        key={cat}
                        onClick={() => setActiveCategory(cat)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                            activeCategory === cat
                                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                                : 'bg-[#1c1c1e] text-gray-400 border border-white/10 hover:border-white/20'
                        }`}
                    >
                        {cat}
                    </button>
                ))}
            </div>

            {/* ETF Flow Table */}
            {loading ? (
                <div className="space-y-2">
                    {Array.from({ length: 10 }).map((_, i) => (
                        <div key={i} className="h-14 rounded-xl bg-[#1c1c1e] border border-white/10 animate-pulse"></div>
                    ))}
                </div>
            ) : sorted.length === 0 ? (
                <div className="p-12 rounded-2xl bg-[#1c1c1e] border border-white/10 text-center">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-cyan-500/10 flex items-center justify-center">
                        <span className="text-2xl">💰</span>
                    </div>
                    <div className="text-gray-500 text-lg mb-2">No ETF flow data</div>
                    <div className="text-xs text-gray-600">스케줄러가 04:00에 자동 갱신합니다</div>
                </div>
            ) : isMobile ? (
                /* Mobile: Card view */
                <div className="space-y-2">
                    {sorted.map((flow) => (
                        <div key={flow.ticker} className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10">
                            <div className="flex items-center justify-between mb-2">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-bold text-white">{flow.ticker}</span>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${getStatusBadge(flow.flow_status)}`}>
                                            {flow.flow_status}
                                        </span>
                                    </div>
                                    <div className="text-[10px] text-gray-500 mt-0.5">{flow.name} · {flow.category}</div>
                                </div>
                                <div className="text-right shrink-0">
                                    <div className={`text-sm font-bold ${getScoreColor(flow.flow_score)}`}>{flow.flow_score}</div>
                                    <div className="text-[10px] text-gray-500">score</div>
                                </div>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                                <div className="text-center p-1.5 rounded-lg bg-white/[0.03] border border-white/5">
                                    <div className="text-[9px] text-gray-500 mb-0.5">5D Flow</div>
                                    <div className={`text-xs font-bold font-mono ${getFlowColor(flow.flow_5d)}`}>
                                        {formatFlow(flow.flow_5d)}
                                    </div>
                                </div>
                                <div className="text-center p-1.5 rounded-lg bg-white/[0.03] border border-white/5">
                                    <div className="text-[9px] text-gray-500 mb-0.5">20D Flow</div>
                                    <div className={`text-xs font-bold font-mono ${getFlowColor(flow.flow_20d)}`}>
                                        {formatFlow(flow.flow_20d)}
                                    </div>
                                </div>
                                <div className="text-center p-1.5 rounded-lg bg-white/[0.03] border border-white/5">
                                    <div className="text-[9px] text-gray-500 mb-0.5">5D Price</div>
                                    <div className={`text-xs font-bold font-mono ${flow.price_5d >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {flow.price_5d >= 0 ? '+' : ''}{flow.price_5d}%
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                /* Desktop: Table view */
                <div className="rounded-xl bg-[#1c1c1e] border border-white/10 overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-white/5">
                                    <th className="text-left py-3 px-4">ETF</th>
                                    <th className="text-left py-3 px-4">Category</th>
                                    <th className="text-right py-3 px-4 cursor-pointer hover:text-white" onClick={() => handleSort('flow_score')}>
                                        Score {sortBy === 'flow_score' ? (sortAsc ? '↑' : '↓') : ''}
                                    </th>
                                    <th className="text-center py-3 px-4">Status</th>
                                    <th className="text-right py-3 px-4 cursor-pointer hover:text-white" onClick={() => handleSort('flow_5d')}>
                                        5D Flow {sortBy === 'flow_5d' ? (sortAsc ? '↑' : '↓') : ''}
                                    </th>
                                    <th className="text-right py-3 px-4 cursor-pointer hover:text-white" onClick={() => handleSort('flow_20d')}>
                                        20D Flow {sortBy === 'flow_20d' ? (sortAsc ? '↑' : '↓') : ''}
                                    </th>
                                    <th className="text-right py-3 px-4 cursor-pointer hover:text-white" onClick={() => handleSort('price_5d')}>
                                        5D% {sortBy === 'price_5d' ? (sortAsc ? '↑' : '↓') : ''}
                                    </th>
                                    <th className="text-right py-3 px-4">Price</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sorted.map((flow) => (
                                    <tr key={flow.ticker} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                        <td className="py-3 px-4">
                                            <div className="font-bold text-white">{flow.ticker}</div>
                                            <div className="text-[10px] text-gray-500 truncate max-w-[140px]">{flow.name}</div>
                                        </td>
                                        <td className="py-3 px-4 text-xs text-gray-400">{flow.category}</td>
                                        <td className={`py-3 px-4 text-right font-bold ${getScoreColor(flow.flow_score)}`}>
                                            {flow.flow_score}
                                        </td>
                                        <td className="py-3 px-4 text-center">
                                            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${getStatusBadge(flow.flow_status)}`}>
                                                {flow.flow_status}
                                            </span>
                                        </td>
                                        <td className={`py-3 px-4 text-right font-mono text-sm ${getFlowColor(flow.flow_5d)}`}>
                                            {formatFlow(flow.flow_5d)}
                                        </td>
                                        <td className={`py-3 px-4 text-right font-mono text-sm ${getFlowColor(flow.flow_20d)}`}>
                                            {formatFlow(flow.flow_20d)}
                                        </td>
                                        <td className={`py-3 px-4 text-right font-mono text-sm ${flow.price_5d >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {flow.price_5d >= 0 ? '+' : ''}{flow.price_5d}%
                                        </td>
                                        <td className="py-3 px-4 text-right text-gray-300 font-mono text-sm">
                                            ${flow.close.toLocaleString()}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* AI Analysis */}
            {aiAnalysis && (
                <div className="p-4 md:p-6 rounded-xl bg-[#1c1c1e] border border-white/10">
                    <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                        <span>🤖</span> AI Flow Analysis
                    </h3>
                    <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
                        {aiAnalysis}
                    </div>
                </div>
            )}
        </div>
    );
}
