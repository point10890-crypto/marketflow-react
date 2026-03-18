

import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { cryptoAPI, CryptoAsset, CryptoDominance, CryptoMarketGate, CryptoBriefingData } from '../../../lib/api';
import { useAutoRefresh } from '../../../hooks/useAutoRefresh';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { usePullToRefreshRegister } from '../../../components/layout/PullToRefreshProvider';

interface GateHistoryEntry {
    date: string;
    gate: string;
    score: number;
}

// ── Arc Gauge (half-arc 180°) ─────────────────────────────────────────────────
function ArcGauge({ score, loading }: { score: number; loading: boolean }) {
    const cx = 100, cy = 100, r = 80;
    const arcLen = Math.PI * r;
    const filled = arcLen * Math.min(Math.max(score, 0), 100) / 100;
    const gap = arcLen - filled;
    const needleAngle = -180 + (score / 100) * 180;
    const needleRad = (needleAngle * Math.PI) / 180;
    const nx = cx + (r - 4) * Math.cos(needleRad);
    const ny = cy + (r - 4) * Math.sin(needleRad);
    let arcColor = '#ef4444';
    if (score >= 70) arcColor = '#10b981';
    else if (score >= 40) arcColor = '#f59e0b';

    return (
        <svg viewBox="0 0 200 110" className="w-full max-w-[140px] sm:max-w-[200px]" style={{ overflow: 'visible' }}>
            <defs>
                <linearGradient id="cryptoArcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#ef4444" />
                    <stop offset="45%" stopColor="#f59e0b" />
                    <stop offset="100%" stopColor="#10b981" />
                </linearGradient>
                <filter id="cryptoArcGlow">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
            </defs>
            <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="#27272a" strokeWidth="10" strokeLinecap="round" />
            {!loading && score > 0 && (
                <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="url(#cryptoArcGrad)" strokeWidth="10" strokeLinecap="round" strokeDasharray={`${filled} ${gap + 0.01}`} filter="url(#cryptoArcGlow)" style={{ transition: 'stroke-dasharray 1s ease-out' }} />
            )}
            {[0, 25, 50, 75, 100].map((v) => {
                const a = (-180 + (v / 100) * 180) * (Math.PI / 180);
                const x1 = cx + (r - 14) * Math.cos(a), y1 = cy + (r - 14) * Math.sin(a);
                const x2 = cx + (r - 6) * Math.cos(a), y2 = cy + (r - 6) * Math.sin(a);
                return <line key={v} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#3f3f46" strokeWidth="1.5" />;
            })}
            {!loading && (
                <>
                    <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={arcColor} strokeWidth="2" strokeLinecap="round" style={{ transition: 'all 1s ease-out', opacity: 0.7 }} />
                    <circle cx={cx} cy={cy} r="5" fill={arcColor} style={{ filter: `drop-shadow(0 0 6px ${arcColor})` }} />
                </>
            )}
            <text x={cx} y={cy - 16} textAnchor="middle" fontSize="28" fontWeight="bold" fill={loading ? '#52525b' : arcColor} style={{ transition: 'fill 0.5s' }}>
                {loading ? '--' : score}
            </text>
            <text x={cx} y={cy - 2} textAnchor="middle" fontSize="9" fill="#71717a" letterSpacing="2">/ 100</text>
        </svg>
    );
}

// ── Index Bar ─────────────────────────────────────────────────────────────────
function IndexBar({ changePct }: { changePct: number }) {
    const magnitude = Math.min(Math.abs(changePct) / 10, 1) * 100; // crypto: ±10% scale
    const isPositive = changePct >= 0;
    return (
        <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden mt-1.5">
            <div
                className={`h-full rounded-full transition-all duration-700 ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`}
                style={{ width: `${magnitude}%`, minWidth: magnitude > 0 ? '4px' : '0' }}
            />
        </div>
    );
}

export default function CryptoOverviewPage() {
    const [cryptos, setCryptos] = useState<CryptoAsset[]>([]);
    const [dominance, setDominance] = useState<CryptoDominance | null>(null);
    const [gate, setGate] = useState<CryptoMarketGate | null>(null);
    const [gateHistory, setGateHistory] = useState<GateHistoryEntry[]>([]);
    const [briefing, setBriefing] = useState<CryptoBriefingData | null>(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState('');
    const [isRefreshing, setIsRefreshing] = useState(false);

    useEffect(() => { loadData(); }, []);

    const loadData = async () => {
        setLoading(true);
        setIsRefreshing(true);
        try {
            const [overviewRes, domRes, gateRes, histRes, briefRes] = await Promise.allSettled([
                cryptoAPI.getOverview(),
                cryptoAPI.getDominance(),
                cryptoAPI.getMarketGate(),
                cryptoAPI.getGateHistory(),
                cryptoAPI.getBriefing(),
            ]);
            if (overviewRes.status === 'fulfilled') setCryptos(overviewRes.value.cryptos);
            if (domRes.status === 'fulfilled') setDominance(domRes.value);
            if (gateRes.status === 'fulfilled') setGate(gateRes.value);
            if (histRes.status === 'fulfilled') setGateHistory(histRes.value.history || []);
            if (briefRes.status === 'fulfilled') setBriefing(briefRes.value);
            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch (e) {
            console.error('Failed to load crypto data:', e);
        } finally {
            setLoading(false);
            setTimeout(() => setIsRefreshing(false), 500);
        }
    };

    const silentRefresh = useCallback(async () => {
        try {
            const [overviewRes, domRes, gateRes, histRes, briefRes] = await Promise.allSettled([
                cryptoAPI.getOverview(),
                cryptoAPI.getDominance(),
                cryptoAPI.getMarketGate(),
                cryptoAPI.getGateHistory(),
                cryptoAPI.getBriefing(),
            ]);
            if (overviewRes.status === 'fulfilled') setCryptos(overviewRes.value.cryptos);
            if (domRes.status === 'fulfilled') setDominance(domRes.value);
            if (gateRes.status === 'fulfilled') setGate(gateRes.value);
            if (histRes.status === 'fulfilled') setGateHistory(histRes.value.history || []);
            if (briefRes.status === 'fulfilled') setBriefing(briefRes.value);
            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch { /* silent */ }
    }, []);
    useAutoRefresh(silentRefresh, 30000);
    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    const isMobile = useIsMobile();

    const getChangeColor = (val: number) => val >= 0 ? 'text-emerald-400' : 'text-red-400';
    const fmtChange = (v: number | undefined) => v === undefined || v === null ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
    const formatPrice = (p: number) => p >= 1 ? `$${p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : `$${p.toFixed(4)}`;
    const formatVolume = (v: number) => {
        if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
        if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
        return `$${v.toLocaleString()}`;
    };

    const getGateBg = (s: number) => s >= 70 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : s >= 40 ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-red-500/30 bg-red-500/10 text-red-400';
    const getGateLabel = (g?: string) => g?.toUpperCase() ?? 'N/A';
    const gateScore = gate?.score ?? 0;
    const fearGreedValue = briefing?.fear_greed?.score ?? 0;
    const btcAsset = cryptos.find(c => c.ticker === 'BTC') ?? cryptos[0] ?? null;
    const ethAsset = cryptos.find(c => c.ticker === 'ETH') ?? cryptos[1] ?? null;

    return (
        <div className="flex flex-col gap-3 md:gap-4 animate-fade-in font-sans text-zinc-200 h-full">

            {/* ── Header ─────────────────────────────────────────────── */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-yellow-500/30 bg-yellow-500/10 text-[10px] text-yellow-400 font-bold tracking-widest">
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse shadow-[0_0_8px_rgba(234,179,8,0.8)]" />
                        CRYPTO
                    </div>
                    <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                        Market <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-400 to-amber-400">Overview</span>
                    </h2>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-[10px] text-zinc-500 font-mono hidden sm:block">{lastUpdated || '--:--'}</span>
                    <button
                        onClick={loadData}
                        disabled={isRefreshing}
                        className="w-8 h-8 rounded-lg bg-zinc-900 border border-white/10 flex items-center justify-center hover:border-white/20 hover:bg-white/5 transition-all"
                    >
                        <svg className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-yellow-400' : 'text-zinc-500'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    </button>
                </div>
            </div>

            {/* ── Row 1: Gate Gauge + BTC/ETH Indices + Quick Nav ──── */}
            <div className="grid grid-cols-12 gap-3">

                {/* Gate Gauge — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col items-center justify-between gap-2">
                    <div className="flex items-center justify-between w-full">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Gate</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${getGateBg(gateScore)}`}>
                            {loading ? '...' : getGateLabel(gate?.gate)}
                        </span>
                    </div>
                    <ArcGauge score={gateScore} loading={loading} />
                    <div className="flex items-center justify-between w-full text-[9px] font-bold text-zinc-600 uppercase tracking-wider px-1">
                        <span className="text-red-500">FEAR</span>
                        <span className="text-amber-500">NEUTRAL</span>
                        <span className="text-emerald-500">GREED</span>
                    </div>
                </div>

                {/* BTC / ETH — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col justify-between gap-3">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Indices</span>

                    {/* BTC */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">Bitcoin</span>
                            <span className={`text-xs font-bold ${getChangeColor(btcAsset?.change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(btcAsset?.change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : btcAsset ? formatPrice(btcAsset.price) : '--'}
                        </div>
                        <IndexBar changePct={btcAsset?.change_pct ?? 0} />
                        <span className="text-[9px] text-zinc-600">
                            24h변동 {Math.abs(btcAsset?.change_pct ?? 0).toFixed(2)}% / 10.0%
                        </span>
                    </div>

                    <div className="border-t border-white/5" />

                    {/* ETH */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">Ethereum</span>
                            <span className={`text-xs font-bold ${getChangeColor(ethAsset?.change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(ethAsset?.change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : ethAsset ? formatPrice(ethAsset.price) : '--'}
                        </div>
                        <IndexBar changePct={ethAsset?.change_pct ?? 0} />
                        <span className="text-[9px] text-zinc-600">
                            24h변동 {Math.abs(ethAsset?.change_pct ?? 0).toFixed(2)}% / 10.0%
                        </span>
                    </div>
                </div>

                {/* Quick Nav — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col gap-2">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-1">Quick Access</span>

                    <Link
                        to="/dashboard/crypto/signals"
                        className="group flex items-center justify-between p-3 rounded-xl bg-orange-500/5 border border-orange-500/20 hover:bg-orange-500/10 hover:border-orange-500/40 transition-all"
                    >
                        <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-orange-500/15 flex items-center justify-center">
                                <svg className="w-3.5 h-3.5 text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
                            </div>
                            <div>
                                <div className="text-xs font-bold text-white">VCP Signals</div>
                                <div className="text-[10px] text-zinc-500">패턴 시그널</div>
                            </div>
                        </div>
                        <svg className="w-3 h-3 text-zinc-600 group-hover:text-orange-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                    </Link>

                    {/* Mini stats */}
                    <div className="mt-auto grid grid-cols-2 gap-2 pt-2">
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">Fear & Greed</div>
                            <div className={`text-base font-bold mt-0.5 ${fearGreedValue >= 60 ? 'text-emerald-400' : fearGreedValue >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                                {loading ? '--' : fearGreedValue || '--'}
                            </div>
                        </div>
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">BTC Dom</div>
                            <div className="text-base font-bold mt-0.5 text-orange-400">
                                {briefing?.market_summary?.btc_dominance != null ? `${briefing.market_summary.btc_dominance.toFixed(1)}%` : '--'}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Row 2: Gate History Timeline ──────────────────────── */}
            {gateHistory.length > 0 && (
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Gate History</span>
                        <span className="text-[10px] text-zinc-600">Last {Math.min(gateHistory.length, 10)} entries</span>
                    </div>
                    <div className="flex items-center gap-3 overflow-x-auto pb-1">
                        {gateHistory.slice(-10).map((h, i) => {
                            const color = h.gate === 'GREEN' ? 'bg-emerald-500' : h.gate === 'YELLOW' ? 'bg-amber-500' : 'bg-red-500';
                            const textColor = h.gate === 'GREEN' ? 'text-emerald-400' : h.gate === 'YELLOW' ? 'text-amber-400' : 'text-red-400';
                            return (
                                <div key={i} className="flex flex-col items-center min-w-[48px] p-1.5 rounded-lg hover:bg-white/[0.03] transition-colors">
                                    <div className={`w-2.5 h-2.5 rounded-full ${color} shadow-lg`} />
                                    <div className={`text-[10px] font-bold mt-1 ${textColor}`}>{h.score}</div>
                                    <div className="text-[9px] text-zinc-600">{h.date.split(' ')[0].slice(5)}</div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* ── Row 3: KPI Cards (4개) ───────────────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {/* BTC Dominance */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">BTC Dominance</span>
                    </div>
                    <div className="text-xl font-bold text-orange-400">
                        {loading ? '--' : briefing?.market_summary?.btc_dominance ? `${briefing.market_summary.btc_dominance.toFixed(1)}%` : 'N/A'}
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-600">
                        Sentiment: {dominance?.sentiment ?? '--'}
                    </div>
                </div>

                {/* Fear & Greed */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Fear & Greed</span>
                    </div>
                    <div className={`text-3xl font-bold ${fearGreedValue >= 60 ? 'text-emerald-400' : fearGreedValue >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                        {loading ? '--' : fearGreedValue || '--'}
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-600">
                        {fearGreedValue <= 25 ? 'Extreme Fear' : fearGreedValue <= 45 ? 'Fear' : fearGreedValue <= 55 ? 'Neutral' : fearGreedValue <= 75 ? 'Greed' : 'Extreme Greed'}
                    </div>
                </div>

                {/* BTC RSI */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">BTC RSI</span>
                    </div>
                    <div className={`text-xl font-bold ${(dominance?.btc_rsi ?? 50) > 70 ? 'text-red-400' : (dominance?.btc_rsi ?? 50) > 50 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {loading ? '--' : dominance?.btc_rsi?.toFixed(1) ?? 'N/A'}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${(dominance?.btc_rsi ?? 50) > 70 ? 'bg-red-500' : (dominance?.btc_rsi ?? 50) > 50 ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`} />
                        <span className="text-[10px] text-zinc-600">
                            {(dominance?.btc_rsi ?? 50) > 70 ? 'Overbought' : (dominance?.btc_rsi ?? 50) > 50 ? 'Bullish' : (dominance?.btc_rsi ?? 50) > 30 ? 'Neutral' : 'Oversold'}
                        </span>
                    </div>
                </div>

                {/* 30D Performance */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">BTC 30D</span>
                    </div>
                    <div className={`text-xl font-bold ${(dominance?.btc_30d_change ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {loading ? '--' : dominance?.btc_30d_change !== undefined ? `${dominance.btc_30d_change >= 0 ? '+' : ''}${dominance.btc_30d_change.toFixed(1)}%` : 'N/A'}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${(dominance?.btc_30d_change ?? 0) >= 0 ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'}`} />
                        <span className="text-[10px] text-zinc-600">Monthly trend</span>
                    </div>
                </div>
            </div>

            {/* ── Row 4: Top Coins Table / Card ─────────────────────── */}
            {cryptos.length > 0 && (
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <div className="w-1 h-4 bg-yellow-500 rounded-full" />
                        <h3 className="text-sm font-bold text-white">Top Coins</h3>
                        <span className="px-1.5 py-0.5 bg-yellow-500/15 text-yellow-400 text-[10px] font-bold rounded-full border border-yellow-500/20">
                            {cryptos.length}
                        </span>
                    </div>

                    {/* Mobile: Card View */}
                    {isMobile ? (
                        <div className="flex flex-col gap-2">
                            {cryptos.slice(0, 10).map((c, idx) => (
                                <div key={c.ticker} className="rounded-xl bg-[#13151f] border border-white/[0.06] p-3 flex items-center gap-3">
                                    <div className="text-[10px] text-zinc-600 font-mono w-4 text-center flex-shrink-0">{idx + 1}</div>
                                    <div className="w-7 h-7 rounded-md bg-gradient-to-br from-yellow-500/20 to-amber-500/20 border border-white/[0.08] flex items-center justify-center text-white font-bold text-[10px] flex-shrink-0">
                                        {c.ticker.slice(0, 3)}
                                    </div>
                                    <div className="flex flex-col min-w-0 flex-1">
                                        <span className="text-white font-semibold text-[13px] truncate">{c.name}</span>
                                        <span className="text-[10px] text-zinc-600 font-mono">{c.ticker}</span>
                                    </div>
                                    <div className="flex flex-col items-end flex-shrink-0">
                                        <span className="text-xs text-white font-mono font-medium">{formatPrice(c.price)}</span>
                                        <span className={`text-[11px] font-mono font-bold ${getChangeColor(c.change_pct)}`}>{fmtChange(c.change_pct)}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        /* Desktop: Table View */
                        <div className="rounded-xl bg-[#13151f] border border-white/[0.06] overflow-hidden">
                            <div className="overflow-x-auto">
                                <table className="w-full text-left border-collapse">
                                    <thead>
                                        <tr className="text-[10px] text-zinc-500 border-b border-white/[0.04] uppercase tracking-wider bg-white/[0.02]">
                                            <th className="px-3 py-2.5 font-medium text-center w-8">#</th>
                                            <th className="px-3 py-2.5 font-medium">Coin</th>
                                            <th className="px-3 py-2.5 font-medium text-right">Price</th>
                                            <th className="px-3 py-2.5 font-medium text-right">24h</th>
                                            <th className="px-3 py-2.5 font-medium text-right">Volume</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/[0.04] text-[13px]">
                                        {cryptos.slice(0, 10).map((c, idx) => (
                                            <tr key={c.ticker} className="hover:bg-white/[0.03] transition-colors">
                                                <td className="px-3 py-2.5 text-center text-[10px] text-zinc-600 font-mono">{idx + 1}</td>
                                                <td className="px-3 py-2.5">
                                                    <div className="flex items-center gap-2.5">
                                                        <div className="w-7 h-7 rounded-md bg-gradient-to-br from-yellow-500/20 to-amber-500/20 border border-white/[0.08] flex items-center justify-center text-white font-bold text-[10px] flex-shrink-0">
                                                            {c.ticker.slice(0, 3)}
                                                        </div>
                                                        <div className="flex flex-col min-w-0">
                                                            <span className="text-white font-semibold text-[13px]">{c.name}</span>
                                                            <span className="text-[10px] text-zinc-600 font-mono">{c.ticker}</span>
                                                        </div>
                                                    </div>
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-xs text-white font-medium">
                                                    {formatPrice(c.price)}
                                                </td>
                                                <td className={`px-3 py-2.5 text-right font-mono text-xs font-bold ${getChangeColor(c.change_pct)}`}>
                                                    {fmtChange(c.change_pct)}
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-500">
                                                    {formatVolume(c.volume_24h)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
