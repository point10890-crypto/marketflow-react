import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
    usAPI, USMarketGate, CumulativePerformanceSummary,
    PortfolioIndex, DecisionSignalData,
    MarketRegimeData, IndexPredictionData, RiskAlertData, SectorRotationData,
} from '@/lib/api';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import StockDetailModal from '@/components/us/StockDetailModal';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

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
                <linearGradient id="usArcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#ef4444" />
                    <stop offset="45%" stopColor="#f59e0b" />
                    <stop offset="100%" stopColor="#10b981" />
                </linearGradient>
                <filter id="usArcGlow">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
            </defs>
            <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="#27272a" strokeWidth="10" strokeLinecap="round" />
            {!loading && score > 0 && (
                <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="url(#usArcGrad)" strokeWidth="10" strokeLinecap="round" strokeDasharray={`${filled} ${gap + 0.01}`} filter="url(#usArcGlow)" style={{ transition: 'stroke-dasharray 1s ease-out' }} />
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
function IndexBar({ changePct, isPositive: isPos }: { changePct: number; isPositive?: boolean }) {
    const magnitude = Math.min(Math.abs(changePct) / 3, 1) * 100;
    const isPositive = isPos ?? changePct >= 0;
    return (
        <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden mt-1.5">
            <div
                className={`h-full rounded-full transition-all duration-700 ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`}
                style={{ width: `${magnitude}%`, minWidth: magnitude > 0 ? '4px' : '0' }}
            />
        </div>
    );
}

export default function UsOverviewPage() {
    const [loading, setLoading] = useState(true);
    const [indices, setIndices] = useState<PortfolioIndex[]>([]);
    const [gateData, setGateData] = useState<USMarketGate | null>(null);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [perfData, setPerfData] = useState<CumulativePerformanceSummary | null>(null);
    const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
    const [decisionSignal, setDecisionSignal] = useState<DecisionSignalData | null>(null);
    const [regimeData, setRegimeData] = useState<MarketRegimeData | null>(null);
    const [predictionData, setPredictionData] = useState<IndexPredictionData | null>(null);
    const [riskData, setRiskData] = useState<RiskAlertData | null>(null);
    const [sectorData, setSectorData] = useState<SectorRotationData | null>(null);
    const [isRefreshing, setIsRefreshing] = useState(false);

    useEffect(() => { loadData(); }, []);

    const loadData = async () => {
        setLoading(true);
        setIsRefreshing(true);
        try {
            const [portfolioRes, gateRes, perfRes, dsRes, regimeRes, predRes, riskRes, sectorRes] = await Promise.all([
                usAPI.getPortfolio().catch(() => null),
                usAPI.getMarketGate().catch(() => null),
                usAPI.getCumulativePerformance().catch(() => null),
                usAPI.getDecisionSignal().catch(() => null),
                usAPI.getMarketRegime().catch(() => null),
                usAPI.getIndexPrediction().catch(() => null),
                usAPI.getRiskAlerts().catch(() => null),
                usAPI.getSectorRotation().catch(() => null),
            ]);
            setIndices(portfolioRes?.market_indices ?? []);
            setGateData(gateRes);
            if (perfRes?.summary) setPerfData(perfRes.summary);
            setDecisionSignal(dsRes);
            setRegimeData(regimeRes);
            setPredictionData(predRes);
            setRiskData(riskRes);
            setSectorData(sectorRes);
            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch (err) {
            console.error('Failed to load US Market data:', err);
        } finally {
            setLoading(false);
            setTimeout(() => setIsRefreshing(false), 500);
        }
    };

    const silentRefresh = useCallback(async () => {
        try {
            const [portfolioRes, gateRes, perfRes, dsRes, regimeRes, predRes, riskRes, sectorRes] = await Promise.all([
                usAPI.getPortfolio().catch(() => null),
                usAPI.getMarketGate().catch(() => null),
                usAPI.getCumulativePerformance().catch(() => null),
                usAPI.getDecisionSignal().catch(() => null),
                usAPI.getMarketRegime().catch(() => null),
                usAPI.getIndexPrediction().catch(() => null),
                usAPI.getRiskAlerts().catch(() => null),
                usAPI.getSectorRotation().catch(() => null),
            ]);
            setIndices(portfolioRes?.market_indices ?? []);
            setGateData(gateRes);
            if (perfRes?.summary) setPerfData(perfRes.summary);
            setDecisionSignal(dsRes);
            setRegimeData(regimeRes);
            setPredictionData(predRes);
            setRiskData(riskRes);
            setSectorData(sectorRes);
            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch { /* silent */ }
    }, []);

    useAutoRefresh(silentRefresh, 30000);

    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    // Color helpers
    const getGateBg = (s: number) => s >= 70 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : s >= 40 ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-red-500/30 bg-red-500/10 text-red-400';
    const getGateLabel = (gate?: string) => gate?.toUpperCase() ?? 'N/A';
    const getChangeColor = (c: number) => c >= 0 ? 'text-emerald-400' : 'text-red-400';
    const fmtChange = (v: number | undefined) => v === undefined || v === null ? '--' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;

    const getActionLabel = (a: string) => a?.replace('_', ' ').toUpperCase() ?? 'N/A';

    const gateScore = gateData?.score ?? 0;
    const spyPred = predictionData?.predictions?.spy ?? predictionData?.predictions?.SPY;

    return (
        <div className="flex flex-col gap-3 md:gap-4 animate-fade-in font-sans text-zinc-200 h-full">

            {/* ── Header ─────────────────────────────────────────────────── */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-blue-500/30 bg-blue-500/10 text-[10px] text-blue-400 font-bold tracking-widest">
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
                        US ALPHA
                    </div>
                    <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                        Market <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">Overview</span>
                    </h2>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-[10px] text-zinc-500 font-mono hidden sm:block">{lastUpdated || '--:--'}</span>
                    <button
                        onClick={loadData}
                        disabled={isRefreshing}
                        title="Refresh"
                        className="w-8 h-8 rounded-lg bg-zinc-900 border border-white/10 flex items-center justify-center hover:border-white/20 hover:bg-white/5 transition-all"
                    >
                        <svg className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-blue-400' : 'text-zinc-500'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    </button>
                </div>
            </div>

            {/* ── Row 1: Gauge + Indices + Quick Nav ──────────────────── */}
            <div className="grid grid-cols-12 gap-3">

                {/* Sentiment Gauge — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col items-center justify-between gap-2">
                    <div className="flex items-center justify-between w-full">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Gate</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${getGateBg(gateScore)}`}>
                            {loading ? '...' : getGateLabel(gateData?.gate ?? gateData?.label)}
                        </span>
                    </div>
                    <ArcGauge score={gateScore} loading={loading} />
                    <div className="flex items-center justify-between w-full text-[9px] font-bold text-zinc-600 uppercase tracking-wider px-1">
                        <span className="text-red-500">RISK OFF</span>
                        <span className="text-amber-500">NEUTRAL</span>
                        <span className="text-emerald-500">RISK ON</span>
                    </div>
                </div>

                {/* Major Indices — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col justify-between gap-3">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Indices</span>

                    {/* S&P 500 */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">{indices[0]?.name ?? 'S&P 500'}</span>
                            <span className={`text-xs font-bold ${getChangeColor(indices[0]?.change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(indices[0]?.change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : (
                                indices[0]?.price?.toLocaleString() ?? '--'
                            )}
                        </div>
                        <IndexBar
                            changePct={indices[0]?.change_pct ?? 0}
                            isPositive={(indices[0]?.change_pct ?? 0) >= 0}
                        />
                        <span className="text-[9px] text-zinc-600">
                            일변동폭 기준 {Math.abs(indices[0]?.change_pct ?? 0).toFixed(2)}% / 3.0%
                        </span>
                    </div>

                    <div className="border-t border-white/5" />

                    {/* NASDAQ */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">{indices[1]?.name ?? 'NASDAQ'}</span>
                            <span className={`text-xs font-bold ${getChangeColor(indices[1]?.change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(indices[1]?.change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : (
                                indices[1]?.price?.toLocaleString() ?? '--'
                            )}
                        </div>
                        <IndexBar
                            changePct={indices[1]?.change_pct ?? 0}
                            isPositive={(indices[1]?.change_pct ?? 0) >= 0}
                        />
                        <span className="text-[9px] text-zinc-600">
                            일변동폭 기준 {Math.abs(indices[1]?.change_pct ?? 0).toFixed(2)}% / 3.0%
                        </span>
                    </div>
                </div>

                {/* Quick Nav — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col gap-2">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-1">Quick Access</span>

                    <Link
                        to="/dashboard/us/etf"
                        className="group flex items-center justify-between p-3 rounded-xl bg-blue-500/5 border border-blue-500/20 hover:bg-blue-500/10 hover:border-blue-500/40 transition-all"
                    >
                        <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-blue-500/15 flex items-center justify-center">
                                <svg className="w-3.5 h-3.5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" /></svg>
                            </div>
                            <div>
                                <div className="text-xs font-bold text-white">ETF Flows</div>
                                <div className="text-[10px] text-zinc-500">자금 흐름 추적</div>
                            </div>
                        </div>
                        <svg className="w-3 h-3 text-zinc-600 group-hover:text-blue-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                    </Link>

                    <Link
                        to="/dashboard/us/vcp"
                        className="group flex items-center justify-between p-3 rounded-xl bg-amber-500/5 border border-amber-500/20 hover:bg-amber-500/10 hover:border-amber-500/40 transition-all"
                    >
                        <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-amber-500/15 flex items-center justify-center">
                                <svg className="w-3.5 h-3.5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
                            </div>
                            <div>
                                <div className="text-xs font-bold text-white">VCP 전략</div>
                                <div className="text-[10px] text-zinc-500">Volume Contraction</div>
                            </div>
                        </div>
                        <svg className="w-3 h-3 text-zinc-600 group-hover:text-amber-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                    </Link>

                    {/* Mini stats */}
                    <div className="mt-auto grid grid-cols-2 gap-2 pt-2">
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">Gate Score</div>
                            <div className={`text-base font-bold mt-0.5 ${gateScore >= 70 ? 'text-emerald-400' : gateScore >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                                {loading ? '--' : gateScore}
                            </div>
                        </div>
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">Win Rate</div>
                            <div className={`text-base font-bold mt-0.5 ${(perfData?.win_rate ?? 0) >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {perfData?.win_rate ?? '--'}%
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Row 2: Decision Signal Strip ────────────────────────── */}
            <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Decision Signal Components</span>
                    {decisionSignal && (
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                            decisionSignal.score >= 60 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' :
                            decisionSignal.score >= 40 ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' :
                            'border-red-500/30 bg-red-500/10 text-red-400'
                        }`}>
                            {getActionLabel(decisionSignal.action)} · {decisionSignal.score}
                        </span>
                    )}
                </div>

                {loading ? (
                    <div className="grid grid-cols-5 gap-2">
                        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-14 rounded-xl bg-white/5 animate-pulse" />)}
                    </div>
                ) : !decisionSignal ? (
                    <div className="flex flex-col items-center justify-center py-6 gap-2">
                        <div className="w-10 h-10 rounded-full bg-zinc-800/60 flex items-center justify-center">
                            <svg className="w-4 h-4 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                        </div>
                        <span className="text-xs text-zinc-600 font-medium">Market Closed</span>
                        <span className="text-[10px] text-zinc-700">데이터는 장 마감 후 업데이트됩니다</span>
                    </div>
                ) : (
                    <div className="grid grid-cols-5 gap-2">
                        {[
                            { label: 'Gate', val: `${decisionSignal.components?.market_gate?.score ?? '--'}`, c: decisionSignal.components?.market_gate?.contribution ?? 0 },
                            { label: 'Regime', val: (decisionSignal.components?.regime?.regime ?? '--').replace('_', ' '), c: decisionSignal.components?.regime?.contribution ?? 0 },
                            { label: 'ML Pred', val: `${(decisionSignal.components?.prediction?.spy_bullish ?? 0).toFixed(0)}%`, c: decisionSignal.components?.prediction?.contribution ?? 0 },
                            { label: 'Risk', val: decisionSignal.components?.risk?.level ?? '--', c: decisionSignal.components?.risk?.contribution ?? 0 },
                            { label: 'Sector', val: decisionSignal.components?.sector_phase?.phase ?? '--', c: decisionSignal.components?.sector_phase?.contribution ?? 0 },
                        ].map(comp => (
                            <div key={comp.label} className="relative p-2.5 rounded-xl border border-white/5 bg-white/[0.02] hover:-translate-y-0.5 hover:shadow-lg transition-all cursor-default">
                                <div className="text-[10px] font-medium text-zinc-500 mb-1">{comp.label}</div>
                                <div className="text-sm font-bold text-white leading-none">{comp.val}</div>
                                <div className={`text-[10px] font-bold mt-1 ${comp.c > 0 ? 'text-emerald-400' : comp.c < 0 ? 'text-red-400' : 'text-zinc-600'}`}>
                                    {comp.c > 0 ? '+' : ''}{comp.c != null ? comp.c.toFixed(1) : '0.0'}
                                </div>
                                <div className="w-full h-0.5 bg-zinc-800 rounded-full mt-1.5 overflow-hidden">
                                    <div
                                        className={`h-full rounded-full ${comp.c > 0 ? 'bg-emerald-500' : comp.c < 0 ? 'bg-red-500' : 'bg-amber-500'}`}
                                        style={{ width: `${Math.min(Math.abs(comp.c ?? 0) / 15 * 100, 100)}%`, minWidth: '4px' }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* ── Row 3: KPI Cards (4개) ──────────────────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">

                {/* A. Regime */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Regime</span>
                    </div>
                    <div className={`text-xl font-bold ${regimeData?.regime === 'risk_on' ? 'text-emerald-400' : regimeData?.regime === 'risk_off' ? 'text-red-400' : regimeData?.regime === 'crisis' ? 'text-red-500' : 'text-amber-400'}`}>
                        {loading ? '--' : regimeData?.regime?.replace('_', ' ').toUpperCase() ?? 'N/A'}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${regimeData?.regime === 'risk_on' ? 'bg-emerald-500 animate-pulse' : regimeData?.regime === 'risk_off' || regimeData?.regime === 'crisis' ? 'bg-red-500' : 'bg-amber-500'}`} />
                        <span className="text-[10px] text-zinc-600">Confidence: {regimeData?.confidence?.toFixed(0) ?? '--'}%</span>
                    </div>
                </div>

                {/* B. SPY Prediction */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">SPY Prediction</span>
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-500 border border-violet-500/20">ML</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                        <span className={`text-3xl font-bold ${(spyPred?.bullish_probability ?? 50) >= 60 ? 'text-emerald-400' : (spyPred?.bullish_probability ?? 50) <= 40 ? 'text-red-400' : 'text-amber-400'}`}>
                            {loading ? '--' : spyPred?.bullish_probability?.toFixed(0) ?? '--'}
                        </span>
                        <span className="text-sm text-zinc-600">%</span>
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-600">
                        Expected: {spyPred?.predicted_return_pct ? `${spyPred.predicted_return_pct > 0 ? '+' : ''}${spyPred.predicted_return_pct.toFixed(2)}%` : '--'}
                    </div>
                </div>

                {/* C. Business Cycle */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Cycle</span>
                    </div>
                    <div className="text-xl font-bold text-teal-400">
                        {loading ? '--' : sectorData?.rotation_signals?.current_phase ?? 'N/A'}
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-600">
                        Lead: {sectorData?.rotation_signals?.leading_sectors?.slice(0, 2).join(', ') ?? '--'}
                    </div>
                </div>

                {/* D. Risk */}
                <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Risk</span>
                    </div>
                    <div className={`text-xl font-bold ${riskData?.portfolio_summary?.risk_level === 'Low' ? 'text-emerald-400' : riskData?.portfolio_summary?.risk_level === 'High' ? 'text-red-400' : 'text-amber-400'}`}>
                        {loading ? '--' : riskData?.portfolio_summary?.risk_level ?? 'N/A'}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${riskData?.portfolio_summary?.risk_level === 'Low' ? 'bg-emerald-500' : riskData?.portfolio_summary?.risk_level === 'High' ? 'bg-red-500 animate-pulse' : 'bg-amber-500'}`} />
                        <span className="text-[10px] text-zinc-600">
                            VaR: ${Math.abs(riskData?.portfolio_summary?.portfolio_var_95_5d ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </span>
                    </div>
                </div>
            </div>

            {/* Stock Detail Modal */}
            {selectedTicker && (
                <StockDetailModal
                    ticker={selectedTicker}
                    onClose={() => setSelectedTicker(null)}
                />
            )}
        </div>
    );
}
