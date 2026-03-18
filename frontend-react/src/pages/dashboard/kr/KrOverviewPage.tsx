

import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE, krAPI, KRMarketGate, KRSignalsResponse } from '@/lib/api';
import { useAutoRefresh, useSmartRefresh } from '@/hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface BacktestStats {
    status: string;
    count: number;
    win_rate: number;
    avg_return: number;
    profit_factor?: number;
    message?: string;
}

interface BacktestSummary {
    vcp: BacktestStats;
    closing_bet: BacktestStats;
}

// Arc gauge: renders a half-arc (180°) from left to right
function ArcGauge({ score, loading }: { score: number; loading: boolean }) {
    // Arc sits in a 200×110 viewBox (half-circle top half only)
    const cx = 100;
    const cy = 100;
    const r = 80;
    // full half-circle arc length = π * r
    const arcLen = Math.PI * r; // ≈ 251.33
    const filled = arcLen * Math.min(Math.max(score, 0), 100) / 100;
    const gap = arcLen - filled;

    // color stops based on score
    const needleAngle = -180 + (score / 100) * 180; // -180° (left) → 0° (right)
    const needleRad = (needleAngle * Math.PI) / 180;
    const nx = cx + (r - 4) * Math.cos(needleRad);
    const ny = cy + (r - 4) * Math.sin(needleRad);

    let arcColor = '#3b82f6'; // blue = bearish
    if (score >= 60) arcColor = '#f43f5e';       // rose = bullish
    else if (score >= 40) arcColor = '#f59e0b';  // amber = neutral

    return (
        <svg viewBox="0 0 200 110" className="w-full max-w-[140px] sm:max-w-[200px]" style={{ overflow: 'visible' }}>
            <defs>
                <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#3b82f6" />
                    <stop offset="45%" stopColor="#f59e0b" />
                    <stop offset="100%" stopColor="#f43f5e" />
                </linearGradient>
                <filter id="arcGlow">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
            </defs>

            {/* Track */}
            <path
                d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
                fill="none"
                stroke="#27272a"
                strokeWidth="10"
                strokeLinecap="round"
            />

            {/* Filled arc */}
            {!loading && score > 0 && (
                <path
                    d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
                    fill="none"
                    stroke="url(#arcGrad)"
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${filled} ${gap + 0.01}`}
                    filter="url(#arcGlow)"
                    style={{ transition: 'stroke-dasharray 1s ease-out' }}
                />
            )}

            {/* Tick marks */}
            {[0, 25, 50, 75, 100].map((v) => {
                const a = (-180 + (v / 100) * 180) * (Math.PI / 180);
                const x1 = cx + (r - 14) * Math.cos(a);
                const y1 = cy + (r - 14) * Math.sin(a);
                const x2 = cx + (r - 6) * Math.cos(a);
                const y2 = cy + (r - 6) * Math.sin(a);
                return <line key={v} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#3f3f46" strokeWidth="1.5" />;
            })}

            {/* Needle dot */}
            {!loading && (
                <>
                    <line
                        x1={cx} y1={cy}
                        x2={nx} y2={ny}
                        stroke={arcColor}
                        strokeWidth="2"
                        strokeLinecap="round"
                        style={{ transition: 'all 1s ease-out', opacity: 0.7 }}
                    />
                    <circle cx={cx} cy={cy} r="5" fill={arcColor} style={{ filter: `drop-shadow(0 0 6px ${arcColor})` }} />
                </>
            )}

            {/* Score label */}
            <text
                x={cx} y={cy - 16}
                textAnchor="middle"
                fontSize="28"
                fontWeight="bold"
                fill={loading ? '#52525b' : arcColor}
                style={{ transition: 'fill 0.5s' }}
            >
                {loading ? '--' : score}
            </text>
            <text x={cx} y={cy - 2} textAnchor="middle" fontSize="9" fill="#71717a" letterSpacing="2">
                / 100
            </text>
        </svg>
    );
}

// Mini sparkline bar (visual only — shows change magnitude)
function IndexBar({ changePct, isPositive }: { changePct: number; isPositive: boolean }) {
    // Map daily change to a % bar. Typical daily move: ±3%. Clamp to 0–100%.
    const magnitude = Math.min(Math.abs(changePct) / 3, 1) * 100;
    return (
        <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden mt-1.5">
            <div
                className={`h-full rounded-full transition-all duration-700 ${isPositive ? 'bg-rose-500' : 'bg-blue-500'}`}
                style={{ width: `${magnitude}%`, minWidth: magnitude > 0 ? '4px' : '0' }}
            />
        </div>
    );
}

export default function KRMarketOverview() {
    const [gateData, setGateData] = useState<KRMarketGate | null>(null);
    const [signalsData, setSignalsData] = useState<KRSignalsResponse | null>(null);
    const [backtestData, setBacktestData] = useState<BacktestSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<string>('');
    const [isRefreshing, setIsRefreshing] = useState(false);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        setIsRefreshing(true);
        try {
            const [gate, signals] = await Promise.all([
                krAPI.getMarketGate().catch(() => null),
                krAPI.getSignals().catch(() => null),
            ]);
            if (gate) setGateData(gate);
            if (signals) setSignalsData(signals);

            try {
                const btRes = await fetch(`${API_BASE}/api/kr/backtest-summary`);
                if (btRes.ok) {
                    setBacktestData(await btRes.json());
                }
            } catch { /* backtest-summary endpoint may not exist */ }

            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch (error) {
            console.error('Failed to load KR Market data:', error);
        } finally {
            setLoading(false);
            setTimeout(() => setIsRefreshing(false), 500);
        }
    };

    // 사일런트 자동 갱신 (30초)
    const silentRefresh = useCallback(async () => {
        try {
            const [gate, signals] = await Promise.all([
                krAPI.getMarketGate().catch(() => null),
                krAPI.getSignals().catch(() => null),
            ]);
            if (gate) setGateData(gate);
            if (signals) setSignalsData(signals);
            try {
                const btRes = await fetch(`${API_BASE}/api/kr/backtest-summary`);
                if (btRes.ok) setBacktestData(await btRes.json());
            } catch { /* silent */ }
            setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
        } catch { /* silent */ }
    }, []);
    useAutoRefresh(silentRefresh, 30000);
    useSmartRefresh(silentRefresh, ['jongga_v2_latest.json', 'kr_ai_analysis.json', 'daily_prices.csv'], 15000);

    usePullToRefreshRegister(useCallback(async () => { await loadData(); }, []));

    // Color Helpers (Korean Market Standard: Red=Up/Bullish, Blue=Down/Bearish)
    const getSentimentColor = (score: number) => {
        if (score >= 60) return 'text-rose-400';
        if (score >= 40) return 'text-amber-400';
        return 'text-blue-400';
    };

    const getSentimentLabel = (label: string | undefined) => {
        if (!label) return 'NEUTRAL';
        return label.toUpperCase();
    };

    const getSentimentBg = (score: number) => {
        if (score >= 60) return 'border-rose-500/30 bg-rose-500/10 text-rose-400';
        if (score >= 40) return 'border-amber-500/30 bg-amber-500/10 text-amber-400';
        return 'border-blue-500/30 bg-blue-500/10 text-blue-400';
    };

    const getSectorStyle = (signal: string) => {
        const s = signal?.toLowerCase();
        if (s === 'bullish') return { bar: 'bg-rose-500', text: 'text-rose-400', border: 'border-rose-500/20 bg-rose-500/5' };
        if (s === 'bearish') return { bar: 'bg-blue-500', text: 'text-blue-400', border: 'border-blue-500/20 bg-blue-500/5' };
        return { bar: 'bg-amber-500', text: 'text-amber-400', border: 'border-amber-500/20 bg-amber-500/5' };
    };

    const getChangeColor = (val: number) => val >= 0 ? 'text-rose-400' : 'text-blue-400';
    const fmtChange = (val: number | undefined) => {
        if (val === undefined || val === null) return '--';
        return (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
    };

    const score = gateData?.score ?? 0;
    const hasSectors = (gateData?.sectors?.length ?? 0) > 0;
    const totalSignals = signalsData?.signals?.length ?? 0;

    const vcpWinRate = backtestData?.vcp?.win_rate ?? 0;
    const vcpAvgReturn = backtestData?.vcp?.avg_return ?? 0;
    const vcpCount = backtestData?.vcp?.count ?? 0;
    const cbWinRate = backtestData?.closing_bet?.win_rate ?? 0;
    const cbAvgReturn = backtestData?.closing_bet?.avg_return ?? 0;
    const cbCount = backtestData?.closing_bet?.count ?? 0;
    const cbAccumulating = backtestData?.closing_bet?.status === 'Accumulating';

    return (
        <div className="flex flex-col gap-3 md:gap-4 animate-fade-in font-sans text-zinc-200 h-full">

            {/* ── Header ─────────────────────────────────────────────────────── */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-rose-500/30 bg-rose-500/10 text-[10px] text-rose-400 font-bold tracking-widest">
                        <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.8)]"></span>
                        KR ALPHA
                    </div>
                    <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                        Market <span className="text-transparent bg-clip-text bg-gradient-to-r from-rose-400 to-fuchsia-400">Overview</span>
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
                        <i className={`fas fa-sync-alt text-[11px] ${isRefreshing ? 'animate-spin text-rose-400' : 'text-zinc-500'}`}></i>
                    </button>
                </div>
            </div>

            {/* ── Row 1: Gauge + Market Indices + Quick Nav ──────────────────── */}
            <div className="grid grid-cols-12 gap-3">

                {/* Sentiment Gauge — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col items-center justify-between gap-2">
                    <div className="flex items-center justify-between w-full">
                        <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Sentiment</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${getSentimentBg(score)}`}>
                            {loading ? '…' : getSentimentLabel(gateData?.label)}
                        </span>
                    </div>

                    <ArcGauge score={score} loading={loading} />

                    {/* Legend */}
                    <div className="flex items-center justify-between w-full text-[9px] font-bold text-zinc-600 uppercase tracking-wider px-1">
                        <span className="text-blue-500">BEAR</span>
                        <span className="text-amber-500">NEUTRAL</span>
                        <span className="text-rose-500">BULL</span>
                    </div>
                </div>

                {/* KOSPI / KOSDAQ — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col justify-between gap-3">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Market Indices</span>

                    {/* KOSPI */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">KOSPI</span>
                            <span className={`text-xs font-bold ${getChangeColor(gateData?.kospi_change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(gateData?.kospi_change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : (
                                gateData?.kospi_close?.toLocaleString('ko-KR') ?? '--'
                            )}
                        </div>
                        <IndexBar
                            changePct={gateData?.kospi_change_pct ?? 0}
                            isPositive={(gateData?.kospi_change_pct ?? 0) >= 0}
                        />
                        <span className="text-[9px] text-zinc-600">
                            일변동폭 기준 {Math.abs(gateData?.kospi_change_pct ?? 0).toFixed(2)}% / 3.0%
                        </span>
                    </div>

                    <div className="border-t border-white/5" />

                    {/* KOSDAQ */}
                    <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-zinc-400">KOSDAQ</span>
                            <span className={`text-xs font-bold ${getChangeColor(gateData?.kosdaq_change_pct ?? 0)}`}>
                                {loading ? '--' : fmtChange(gateData?.kosdaq_change_pct)}
                            </span>
                        </div>
                        <div className="text-2xl font-bold text-white tracking-tight leading-none">
                            {loading ? (
                                <span className="text-zinc-600">----</span>
                            ) : (
                                gateData?.kosdaq_close?.toLocaleString('ko-KR') ?? '--'
                            )}
                        </div>
                        <IndexBar
                            changePct={gateData?.kosdaq_change_pct ?? 0}
                            isPositive={(gateData?.kosdaq_change_pct ?? 0) >= 0}
                        />
                        <span className="text-[9px] text-zinc-600">
                            일변동폭 기준 {Math.abs(gateData?.kosdaq_change_pct ?? 0).toFixed(2)}% / 3.0%
                        </span>
                    </div>
                </div>

                {/* Quick Nav — 4 cols */}
                <div className="col-span-12 sm:col-span-4 rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4 flex flex-col gap-2">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-1">Quick Access</span>

                    <Link
                        to="/dashboard/kr/closing-bet"
                        className="group flex items-center justify-between p-3 rounded-xl bg-rose-500/5 border border-rose-500/20 hover:bg-rose-500/10 hover:border-rose-500/40 transition-all"
                    >
                        <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-rose-500/15 flex items-center justify-center">
                                <i className="fas fa-fire text-rose-400 text-xs"></i>
                            </div>
                            <div>
                                <div className="text-xs font-bold text-white">종가베팅</div>
                                <div className="text-[10px] text-zinc-500">Closing Bet V2</div>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            {totalSignals > 0 && (
                                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30">
                                    {totalSignals}
                                </span>
                            )}
                            <i className="fas fa-chevron-right text-[10px] text-zinc-600 group-hover:text-rose-400 transition-colors"></i>
                        </div>
                    </Link>

                    <Link
                        to="/dashboard/kr/vcp"
                        className="group flex items-center justify-between p-3 rounded-xl bg-amber-500/5 border border-amber-500/20 hover:bg-amber-500/10 hover:border-amber-500/40 transition-all"
                    >
                        <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-amber-500/15 flex items-center justify-center">
                                <i className="fas fa-chart-line text-amber-400 text-xs"></i>
                            </div>
                            <div>
                                <div className="text-xs font-bold text-white">VCP 전략</div>
                                <div className="text-[10px] text-zinc-500">Volume Contraction</div>
                            </div>
                        </div>
                        <i className="fas fa-chevron-right text-[10px] text-zinc-600 group-hover:text-amber-400 transition-colors"></i>
                    </Link>

                    {/* Mini stats */}
                    <div className="mt-auto grid grid-cols-2 gap-2 pt-2">
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">오늘 시그널</div>
                            <div className="text-base font-bold text-white mt-0.5">{loading ? '--' : totalSignals}</div>
                        </div>
                        <div className="rounded-lg bg-zinc-900/60 border border-white/5 p-2 text-center">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-wider">시장 점수</div>
                            <div className={`text-base font-bold mt-0.5 ${getSentimentColor(score)}`}>{loading ? '--' : score}</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Row 2: Sector Grid ──────────────────────────────────────────── */}
            <div className="rounded-2xl bg-[#13151f] border border-white/5 p-3 md:p-4">
                <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Sector Performance</span>
                    <div className="flex gap-3 text-[9px] font-bold uppercase tracking-wider">
                        <span className="flex items-center gap-1 text-zinc-500"><span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>Bullish</span>
                        <span className="flex items-center gap-1 text-zinc-500"><span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>Neutral</span>
                        <span className="flex items-center gap-1 text-zinc-500"><span className="w-1.5 h-1.5 rounded-full bg-blue-500"></span>Bearish</span>
                    </div>
                </div>

                {loading ? (
                    <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2">
                        {Array.from({ length: 8 }).map((_, i) => (
                            <div key={i} className="h-14 rounded-xl bg-white/5 animate-pulse"></div>
                        ))}
                    </div>
                ) : !hasSectors ? (
                    <div className="flex flex-col items-center justify-center py-6 gap-2">
                        <div className="w-10 h-10 rounded-full bg-zinc-800/60 flex items-center justify-center">
                            <i className="fas fa-moon text-zinc-600 text-base"></i>
                        </div>
                        <span className="text-xs text-zinc-600 font-medium">Market Closed</span>
                        <span className="text-[10px] text-zinc-700">섹터 데이터는 장 마감 후 업데이트됩니다</span>
                    </div>
                ) : (
                    <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2">
                        {gateData?.sectors?.map((sector) => {
                            const style = getSectorStyle(sector.signal);
                            return (
                                <div
                                    key={sector.name}
                                    className={`relative p-2.5 rounded-xl border transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg cursor-default ${style.border}`}
                                >
                                    <div className="text-[10px] font-medium text-zinc-400 truncate leading-tight mb-1">{sector.name}</div>
                                    <div className={`text-sm font-bold ${style.text} leading-none`}>
                                        {sector.change_pct != null ? `${sector.change_pct >= 0 ? '+' : ''}${sector.change_pct.toFixed(2)}` : '--'}
                                        <span className="text-[9px] opacity-70">%</span>
                                    </div>
                                    <div className="w-full h-0.5 bg-zinc-800 rounded-full mt-1.5 overflow-hidden">
                                        <div
                                            className={`h-full rounded-full ${style.bar}`}
                                            style={{ width: `${Math.min(Math.abs(sector.change_pct ?? 0) / 3 * 100, 100)}%`, minWidth: '4px' }}
                                        />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* ── Row 3: KPI Cards ────────────────────────────────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">

                {/* A. Today's Signals */}
                <div className="group rounded-2xl bg-[#13151f] border border-white/5 hover:border-rose-500/20 transition-all p-3 md:p-4 relative overflow-hidden">
                    <div className="absolute inset-0 bg-rose-500/0 group-hover:bg-rose-500/3 transition-all rounded-2xl"></div>
                    <div className="relative">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">오늘 시그널</span>
                            <i className="fas fa-bolt text-zinc-700 group-hover:text-rose-500 transition-colors text-xs"></i>
                        </div>
                        <div className="flex items-baseline gap-1">
                            <span className="text-3xl font-bold text-white group-hover:text-rose-400 transition-colors">
                                {loading ? '--' : totalSignals}
                            </span>
                            <span className="text-xs text-zinc-600">개</span>
                        </div>
                        <div className="mt-2 text-[10px] text-zinc-600">VCP + 종가베팅 합산</div>
                    </div>
                </div>

                {/* B. VCP Win Rate */}
                <div className="group rounded-2xl bg-[#13151f] border border-white/5 hover:border-amber-500/20 transition-all p-3 md:p-4 relative overflow-hidden">
                    <div className="absolute inset-0 bg-amber-500/0 group-hover:bg-amber-500/3 transition-all rounded-2xl"></div>
                    <div className="relative">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">VCP 전략</span>
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20">WIN %</span>
                        </div>
                        <div className="flex items-baseline gap-1.5">
                            <span className="text-3xl font-bold text-white group-hover:text-amber-400 transition-colors">
                                {loading ? '--' : vcpWinRate}
                            </span>
                            <span className="text-sm text-zinc-600">%</span>
                            {!loading && vcpAvgReturn !== 0 && (
                                <span className={`text-[10px] font-bold px-1 py-0.5 rounded ${vcpAvgReturn >= 0 ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'}`}>
                                    {vcpAvgReturn >= 0 ? '+' : ''}{vcpAvgReturn}%
                                </span>
                            )}
                        </div>
                        <div className="mt-2 flex items-center gap-1.5">
                            <span className="text-[10px] text-zinc-600">{vcpCount}건 거래</span>
                            {backtestData?.vcp?.status === 'OK' && (
                                <i className="fas fa-circle-check text-[9px] text-emerald-600"></i>
                            )}
                        </div>
                    </div>
                </div>

                {/* C. Closing Bet Win Rate */}
                <div className="group rounded-2xl bg-[#13151f] border border-white/5 hover:border-emerald-500/20 transition-all p-3 md:p-4 relative overflow-hidden">
                    <div className="absolute inset-0 bg-emerald-500/0 group-hover:bg-emerald-500/3 transition-all rounded-2xl"></div>
                    <div className="relative">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">종가베팅</span>
                            {cbAccumulating ? (
                                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse">ACCUM</span>
                            ) : (
                                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">WIN %</span>
                            )}
                        </div>
                        {cbAccumulating ? (
                            <div>
                                <div className="flex items-center gap-2 text-sm font-bold text-amber-400">
                                    <i className="fas fa-database animate-pulse"></i>
                                    <span>수집 중...</span>
                                </div>
                                <div className="mt-2 text-[10px] text-zinc-600">2일 이상 데이터 필요</div>
                            </div>
                        ) : (
                            <>
                                <div className="flex items-baseline gap-1.5">
                                    <span className="text-3xl font-bold text-white group-hover:text-emerald-400 transition-colors">
                                        {loading ? '--' : cbWinRate}
                                    </span>
                                    <span className="text-sm text-zinc-600">%</span>
                                    {!loading && cbAvgReturn !== 0 && (
                                        <span className={`text-[10px] font-bold px-1 py-0.5 rounded ${cbAvgReturn >= 0 ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'}`}>
                                            {cbAvgReturn >= 0 ? '+' : ''}{cbAvgReturn}%
                                        </span>
                                    )}
                                </div>
                                <div className="mt-2 text-[10px] text-zinc-600">{cbCount}건 거래</div>
                            </>
                        )}
                    </div>
                </div>

                {/* D. Regime Status */}
                <div className="group rounded-2xl bg-[#13151f] border border-white/5 hover:border-fuchsia-500/20 transition-all p-3 md:p-4 relative overflow-hidden">
                    <div className="absolute inset-0 bg-fuchsia-500/0 group-hover:bg-fuchsia-500/3 transition-all rounded-2xl"></div>
                    <div className="relative">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">레짐 상태</span>
                            <i className="fas fa-shield-halved text-zinc-700 group-hover:text-fuchsia-500 transition-colors text-xs"></i>
                        </div>
                        {loading ? (
                            <div className="h-8 w-24 bg-zinc-800 rounded animate-pulse"></div>
                        ) : (
                            <>
                                <div className={`text-xl font-bold ${getSentimentColor(score)}`}>
                                    {score >= 60 ? 'RISK ON' : score >= 40 ? 'NEUTRAL' : 'RISK OFF'}
                                </div>
                                <div className="mt-2 flex items-center gap-1.5">
                                    <div className={`w-1.5 h-1.5 rounded-full ${score >= 60 ? 'bg-rose-500 animate-pulse' : score >= 40 ? 'bg-amber-500' : 'bg-blue-500'}`}></div>
                                    <span className="text-[10px] text-zinc-600">
                                        {score >= 60 ? '매수 우호적 환경' : score >= 40 ? '관망 구간' : '리스크 관리 우선'}
                                    </span>
                                </div>
                            </>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
