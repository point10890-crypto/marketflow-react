'use client';

import { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { cryptoAPI } from '@/lib/api';
import type { CryptoBriefingData, CryptoMarketGate, CryptoSignal, CryptoPredictionData, CryptoRiskData } from '@/lib/api';
import HelpButton from '@/components/ui/HelpButton';
import { createChart, IChartApi, AreaSeries, CrosshairMode, Time, LineData } from 'lightweight-charts';

const MAJOR_COINS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'] as const;

const COIN_ICONS: Record<string, string> = {
    BTC: 'fab fa-bitcoin',
    ETH: 'fab fa-ethereum',
    SOL: 'fas fa-sun',
    BNB: 'fas fa-coins',
    XRP: 'fas fa-water',
};

export default function CryptoOverviewDashboard() {
    const [loading, setLoading] = useState(true);
    const [briefing, setBriefing] = useState<CryptoBriefingData | null>(null);
    const [gate, setGate] = useState<CryptoMarketGate | null>(null);
    const [signals, setSignals] = useState<CryptoSignal[]>([]);
    const [prediction, setPrediction] = useState<CryptoPredictionData | null>(null);
    const [risk, setRisk] = useState<CryptoRiskData | null>(null);
    const [gateHistory, setGateHistory] = useState<Array<{date: string; gate: string; score: number}>>([]);

    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [briefingRes, gateRes, signalsRes, predictionRes, riskRes, gateHistoryRes] = await Promise.all([
                cryptoAPI.getBriefing().catch(() => null),
                cryptoAPI.getMarketGate().catch(() => null),
                cryptoAPI.getVCPSignals(10).catch(() => null),
                cryptoAPI.getPrediction().catch(() => null),
                cryptoAPI.getRisk().catch(() => null),
                cryptoAPI.getGateHistory().catch(() => null),
            ]);

            setBriefing(briefingRes);
            setGate(gateRes);

            // Filter signals to today only
            const today = new Date().toISOString().split('T')[0];
            const allSignals = signalsRes?.signals ?? [];
            const todaySignals = allSignals.filter(s => {
                const signalDate = (s.created_at.split(' ')[0] || s.created_at.split('T')[0]);
                return signalDate === today;
            });
            setSignals(todaySignals.length > 0 ? todaySignals : allSignals);

            setPrediction(predictionRes);
            setRisk(riskRes);
            setGateHistory(gateHistoryRes?.history ?? []);
        } catch (error) {
            console.error('Failed to load crypto overview data:', error);
        } finally {
            setLoading(false);
        }
    };

    // BTC 30-Day Price Chart
    useEffect(() => {
        if (!briefing?.btc_price_history || briefing.btc_price_history.length === 0 || !chartContainerRef.current) return;

        if (chartRef.current) {
            chartRef.current.remove();
            chartRef.current = null;
        }

        const chart = createChart(chartContainerRef.current, {
            width: chartContainerRef.current.clientWidth,
            height: 200,
            layout: { background: { color: 'transparent' }, textColor: '#6b7280' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
            crosshair: { mode: CrosshairMode.Normal },
        });
        chartRef.current = chart;

        const areaSeries = chart.addSeries(AreaSeries, {
            lineColor: '#eab308',
            topColor: 'rgba(234,179,8,0.3)',
            bottomColor: 'rgba(234,179,8,0.02)',
            lineWidth: 2,
        });

        // Use last 30 entries for the mini chart
        const last30 = briefing.btc_price_history.slice(-30);
        const chartData: LineData<Time>[] = last30.map(d => ({
            time: d.date as Time,
            value: d.price,
        }));
        areaSeries.setData(chartData);
        chart.timeScale().fitContent();

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
            chartRef.current = null;
        };
    }, [briefing]);

    // ── Helper functions ──

    const getGateColorClass = (gateLabel: string | undefined) => {
        switch (gateLabel) {
            case 'GREEN': return 'text-green-400';
            case 'YELLOW': return 'text-yellow-400';
            case 'RED': return 'text-red-400';
            default: return 'text-gray-400';
        }
    };

    const getGateBadgeClass = (gateLabel: string | undefined) => {
        switch (gateLabel) {
            case 'GREEN': return 'bg-green-500/20 text-green-400 border-green-500/30';
            case 'YELLOW': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
            case 'RED': return 'bg-red-500/20 text-red-400 border-red-500/30';
            default: return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
        }
    };

    const getStatusBadgeClass = (status: string | undefined) => {
        switch (status) {
            case 'RISK_ON': return 'bg-green-500/20 text-green-400 border-green-500/30';
            case 'RISK_OFF': return 'bg-red-500/20 text-red-400 border-red-500/30';
            default: return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        }
    };

    const getFearGreedColor = (score: number) => {
        if (score >= 75) return 'text-green-400';
        if (score >= 55) return 'text-emerald-400';
        if (score >= 45) return 'text-yellow-400';
        if (score >= 25) return 'text-orange-400';
        return 'text-red-400';
    };

    const getChangeColor = (change: number) => {
        if (change > 0) return 'text-green-400';
        if (change < 0) return 'text-red-400';
        return 'text-gray-400';
    };

    const getSignalTypeBadge = (type: string) => {
        switch (type) {
            case 'BREAKOUT': return 'bg-green-500/20 text-green-400';
            case 'APPROACHING': return 'bg-yellow-500/20 text-yellow-400';
            default: return 'bg-gray-500/20 text-gray-400';
        }
    };

    const getRiskLevelColor = (level: string | undefined) => {
        switch (level?.toUpperCase()) {
            case 'LOW': return 'bg-green-500/20 text-green-400 border-green-500/30';
            case 'MODERATE': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
            case 'HIGH': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
            case 'CRITICAL': return 'bg-red-500/20 text-red-400 border-red-500/30';
            default: return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
        }
    };

    const formatPrice = (price: number | undefined) => {
        if (!price) return '--';
        if (price >= 1000) return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
        if (price >= 1) return `$${price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
        return `$${price.toFixed(4)}`;
    };

    const gateScore = gate?.score ?? 0;
    const gateLabel = gate?.gate ?? (gateScore >= 72 ? 'GREEN' : gateScore >= 48 ? 'YELLOW' : 'RED');
    const fearGreed = briefing?.fear_greed;
    const btcData = briefing?.major_coins?.BTC;
    const btcPred = prediction?.predictions?.BTC ?? prediction?.predictions?.btc;

    // Circular gauge SVG helper
    const CircularGauge = ({ score, size = 96, strokeWidth = 6, colorClass }: { score: number; size?: number; strokeWidth?: number; colorClass: string }) => {
        const radius = (size / 2) - strokeWidth;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference - (circumference * Math.min(score, 100) / 100);
        const center = size / 2;

        return (
            <svg className="w-full h-full -rotate-90" viewBox={`0 0 ${size} ${size}`}>
                <circle
                    cx={center} cy={center} r={radius}
                    stroke="currentColor" strokeWidth={strokeWidth}
                    fill="transparent" className="text-white/5"
                />
                <circle
                    cx={center} cy={center} r={radius}
                    stroke="currentColor" strokeWidth={strokeWidth}
                    fill="transparent"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                    className={`${colorClass} transition-all duration-1000 ease-out`}
                />
            </svg>
        );
    };

    // Skeleton loader
    const SkeletonCard = ({ className = '' }: { className?: string }) => (
        <div className={`bg-[#2c2c2e] border border-white/10 rounded-xl animate-pulse ${className}`} />
    );

    return (
        <div className="space-y-8">
            {/* ═══ 1. Header ═══ */}
            <div>
                <div className="flex items-center gap-3 mb-2">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-yellow-500/20 bg-yellow-500/5 text-xs text-yellow-400 font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-ping"></span>
                        Crypto Market
                    </div>
                    {!loading && gate && (
                        <span className={`px-3 py-1 rounded-full text-xs font-bold border ${getGateBadgeClass(gateLabel)}`}>
                            Gate: {gateLabel}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-3">
                    <h2 className="text-4xl md:text-5xl font-bold tracking-tighter text-white leading-tight mb-2">
                        Crypto <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-400 to-orange-400">Market Overview</span>
                    </h2>
                    <HelpButton title="Crypto Market Overview" sections={[
                        { heading: '작동 원리', body: 'BTC Market Gate는 추세(35%) + 변동성(18%) + 참여도(18%) + 시장 폭(18%) + 레버리지(11%)로 0~100점 산출. GREEN(\u226572): 적극 매수, YELLOW(48~71): 관망, RED(<48): 매수 금지.' },
                        { heading: '해석 방법', body: 'VCP 시그널: 가격 수축 패턴 돌파 감지. Score가 높을수록 패턴 품질 우수. BREAKOUT=돌파 완료, APPROACHING=돌파 임박. BTC Prediction: ML 앙상블로 5일 후 방향 예측.' },
                        { heading: '활용 팁', body: 'Gate가 GREEN일 때 Score 60+ 시그널에 집중. Risk Level이 HIGH 이상이면 포지션 축소 권고. Fear & Greed 25 이하는 역발상 매수 구간.' },
                    ]} />
                </div>
                <p className="text-gray-400 text-lg">종합 시장 건강도 & VCP 시그널 & 리스크 관리</p>
            </div>

            {/* ═══ 2. Top Hero Row (3 cards) ═══ */}
            <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* BTC Market Gate */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-white/20 transition-colors relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity text-yellow-500">
                        <i className="fas fa-shield-alt text-4xl"></i>
                    </div>
                    <h3 className="text-sm font-bold text-gray-400 mb-4 flex items-center gap-2">
                        BTC Market Gate
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse"></span>
                    </h3>
                    {loading ? (
                        <div className="flex flex-col items-center py-4">
                            <div className="w-24 h-24 rounded-full bg-white/5 animate-pulse" />
                            <div className="mt-3 w-20 h-6 rounded-full bg-white/5 animate-pulse" />
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-2">
                            <div className="relative w-24 h-24 flex items-center justify-center">
                                <CircularGauge score={gateScore} size={96} strokeWidth={6} colorClass={getGateColorClass(gateLabel)} />
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <span className={`text-2xl font-black ${getGateColorClass(gateLabel)}`}>
                                        {gateScore}
                                    </span>
                                    <span className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">Score</span>
                                </div>
                            </div>
                            <div className={`mt-3 px-3 py-1 rounded-full text-xs font-bold border ${getStatusBadgeClass(gate?.status)}`}>
                                {gate?.status ?? 'N/A'}
                            </div>
                        </div>
                    )}
                </div>

                {/* Fear & Greed */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-white/20 transition-colors relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity text-purple-500">
                        <i className="fas fa-heart-pulse text-4xl"></i>
                    </div>
                    <h3 className="text-sm font-bold text-gray-400 mb-4 flex items-center gap-2">
                        Fear & Greed Index
                        <span className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse"></span>
                    </h3>
                    {loading ? (
                        <div className="flex flex-col items-center py-4">
                            <div className="w-24 h-24 rounded-full bg-white/5 animate-pulse" />
                            <div className="mt-3 w-20 h-6 rounded-full bg-white/5 animate-pulse" />
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-2">
                            <div className="relative w-24 h-24 flex items-center justify-center">
                                <CircularGauge
                                    score={fearGreed?.score ?? 0}
                                    size={96}
                                    strokeWidth={6}
                                    colorClass={getFearGreedColor(fearGreed?.score ?? 0)}
                                />
                                <div className="absolute inset-0 flex flex-col items-center justify-center">
                                    <span className={`text-2xl font-black ${getFearGreedColor(fearGreed?.score ?? 0)}`}>
                                        {fearGreed?.score ?? '--'}
                                    </span>
                                    <span className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">F&G</span>
                                </div>
                            </div>
                            <div className="mt-3 px-3 py-1 rounded-full text-xs font-bold border bg-white/5 border-white/10 text-gray-300">
                                {fearGreed?.level ?? 'N/A'}
                            </div>
                        </div>
                    )}
                </div>

                {/* BTC Price */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-white/20 transition-colors relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity text-yellow-500">
                        <i className="fab fa-bitcoin text-4xl"></i>
                    </div>
                    <h3 className="text-sm font-bold text-gray-400 mb-4 flex items-center gap-2">
                        BTC Price
                        <span className="w-1.5 h-1.5 rounded-full bg-orange-500 animate-pulse"></span>
                    </h3>
                    {loading ? (
                        <div className="flex flex-col items-center py-6">
                            <div className="w-40 h-10 rounded bg-white/5 animate-pulse" />
                            <div className="mt-3 w-24 h-6 rounded bg-white/5 animate-pulse" />
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-4">
                            <div className="text-3xl md:text-4xl font-black text-white tracking-tight">
                                {btcData ? formatPrice(btcData.price) : '--'}
                            </div>
                            {btcData && (
                                <div className={`mt-2 flex items-center gap-1 text-lg font-bold ${getChangeColor(btcData.change_24h)}`}>
                                    <i className={`fas fa-caret-${btcData.change_24h >= 0 ? 'up' : 'down'}`}></i>
                                    {btcData.change_24h >= 0 ? '+' : ''}{btcData.change_24h.toFixed(2)}%
                                    <span className="text-xs text-gray-500 font-normal ml-1">24h</span>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </section>

            {/* ═══ 2.5 Gate History Timeline ═══ */}
            {!loading && gateHistory.length > 0 && (
                <section className="bg-[#2c2c2e] border border-white/10 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Gate History</h3>
                        <span className="text-[10px] text-gray-600">Last {Math.min(gateHistory.length, 10)} checks</span>
                    </div>
                    <div className="flex items-center gap-2 overflow-x-auto pb-1">
                        {gateHistory.slice(-10).map((entry, idx) => {
                            const dotColor = entry.gate === 'GREEN' ? 'bg-green-500' : entry.gate === 'YELLOW' ? 'bg-yellow-500' : 'bg-red-500';
                            const borderColor = entry.gate === 'GREEN' ? 'border-green-500/30' : entry.gate === 'YELLOW' ? 'border-yellow-500/30' : 'border-red-500/30';
                            return (
                                <div key={idx} className="flex flex-col items-center gap-1 min-w-[48px] group" title={`${entry.date} - ${entry.gate} (${entry.score})`}>
                                    <div className={`w-4 h-4 rounded-full ${dotColor} border-2 ${borderColor} transition-transform group-hover:scale-125`} />
                                    <span className="text-[9px] text-gray-500 font-mono">{entry.score}</span>
                                    <span className="text-[8px] text-gray-600 font-mono whitespace-nowrap">{entry.date.split(' ')[0]?.slice(5)}</span>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* ═══ 3. Major Coins Row (5 small cards) ═══ */}
            <section>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                        <span className="w-1 h-5 bg-yellow-500 rounded-full"></span>
                        Major Coins
                    </h3>
                    <span className="text-[10px] text-gray-500 font-mono uppercase tracking-wider">24h Change</span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {loading ? (
                        Array.from({ length: 5 }).map((_, i) => (
                            <SkeletonCard key={i} className="h-24 p-4" />
                        ))
                    ) : (
                        MAJOR_COINS.map((coin) => {
                            const coinData = briefing?.major_coins?.[coin];
                            return (
                                <div
                                    key={coin}
                                    className="bg-[#2c2c2e] border border-white/10 rounded-xl p-4 hover:border-white/20 transition-colors"
                                >
                                    <div className="flex items-center gap-2 mb-2">
                                        <i className={`${COIN_ICONS[coin] ?? 'fas fa-coins'} text-yellow-500 text-sm`}></i>
                                        <span className="text-sm font-bold text-white">{coin}</span>
                                    </div>
                                    <div className="text-lg font-black text-white">
                                        {coinData ? formatPrice(coinData.price) : '--'}
                                    </div>
                                    {coinData && (
                                        <div className={`text-xs font-bold ${getChangeColor(coinData.change_24h)}`}>
                                            <i className={`fas fa-caret-${coinData.change_24h >= 0 ? 'up' : 'down'} mr-0.5`}></i>
                                            {coinData.change_24h >= 0 ? '+' : ''}{coinData.change_24h.toFixed(2)}%
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            </section>

            {/* ═══ 3.5 BTC 30-Day Price Chart ═══ */}
            {!loading && briefing?.btc_price_history && briefing.btc_price_history.length > 0 && (
                <section>
                    <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                        <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                            <span className="w-1 h-4 bg-yellow-500 rounded-full"></span>
                            BTC 30-Day Price
                        </h3>
                        <div ref={chartContainerRef} className="w-full" />
                    </div>
                </section>
            )}

            {/* ═══ 4. Quick Stats Row (3 cards) ═══ */}
            {!loading && (
                <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    {/* VCP Signals */}
                    <Link
                        href="/dashboard/crypto/signals"
                        className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-yellow-500/30 transition-colors group"
                    >
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">VCP Signals</span>
                            <i className="fas fa-arrow-right text-gray-600 group-hover:text-yellow-400 transition-colors text-xs"></i>
                        </div>
                        <div className="text-3xl font-black text-white group-hover:text-yellow-400 transition-colors">
                            {signals.length}
                        </div>
                        <div className="mt-1 text-xs text-gray-500">
                            Active signals detected
                        </div>
                        <div className="mt-2 text-xs text-yellow-400 font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                            View All &rarr;
                        </div>
                    </Link>

                    {/* BTC Prediction */}
                    <Link
                        href="/dashboard/crypto/prediction"
                        className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-blue-500/30 transition-colors group"
                    >
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">BTC Prediction</span>
                            <i className="fas fa-arrow-right text-gray-600 group-hover:text-blue-400 transition-colors text-xs"></i>
                        </div>
                        {btcPred ? (
                            <>
                                <div className={`text-2xl font-black ${btcPred.bullish_probability >= 60 ? 'text-green-400' : btcPred.bullish_probability <= 40 ? 'text-red-400' : 'text-yellow-400'}`}>
                                    {btcPred.bullish_probability >= 50 ? 'Bullish' : 'Bearish'}
                                </div>
                                <div className="mt-1 text-xs text-gray-500">
                                    {btcPred.bullish_probability.toFixed(1)}% bullish probability
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="text-2xl font-black text-gray-500">N/A</div>
                                <div className="mt-1 text-xs text-gray-600">No prediction data</div>
                            </>
                        )}
                        <div className="mt-2 text-xs text-blue-400 font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                            View Details &rarr;
                        </div>
                    </Link>

                    {/* Risk Level */}
                    <Link
                        href="/dashboard/crypto/risk"
                        className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 hover:border-orange-500/30 transition-colors group"
                    >
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Risk Level</span>
                            <i className="fas fa-arrow-right text-gray-600 group-hover:text-orange-400 transition-colors text-xs"></i>
                        </div>
                        {risk?.portfolio_summary ? (
                            <>
                                <span className={`inline-block px-3 py-1 rounded-full text-sm font-black border ${getRiskLevelColor(risk.portfolio_summary.risk_level)}`}>
                                    {risk.portfolio_summary.risk_level?.toUpperCase() ?? 'N/A'}
                                </span>
                                <div className="mt-2 text-xs text-gray-500">
                                    VaR (95%, 1d): ${Math.abs(risk.portfolio_summary.portfolio_var_95_1d).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="text-2xl font-black text-gray-500">N/A</div>
                                <div className="mt-1 text-xs text-gray-600">No risk data</div>
                            </>
                        )}
                        <div className="mt-2 text-xs text-orange-400 font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                            View Dashboard &rarr;
                        </div>
                    </Link>
                </section>
            )}

            {/* ═══ 5. Top VCP Signals Table (compact, 5 rows) ═══ */}
            <section>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                        <span className="w-1 h-5 bg-yellow-500 rounded-full"></span>
                        Top VCP Signals
                        <span className="text-[10px] text-gray-500 font-normal ml-1">Today</span>
                    </h3>
                    <Link href="/dashboard/crypto/signals" className="text-xs text-yellow-400 hover:text-yellow-300 font-medium transition-colors">
                        View All Signals <i className="fas fa-arrow-right ml-1"></i>
                    </Link>
                </div>

                {loading ? (
                    <div className="space-y-3">
                        {Array.from({ length: 5 }).map((_, i) => (
                            <SkeletonCard key={i} className="h-14" />
                        ))}
                    </div>
                ) : signals.length === 0 ? (
                    <div className="p-12 rounded-xl bg-[#2c2c2e] border border-white/10 text-center">
                        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-yellow-500/10 flex items-center justify-center">
                            <i className="fab fa-bitcoin text-2xl text-yellow-500"></i>
                        </div>
                        <div className="text-gray-500 text-lg mb-2">No VCP signals available</div>
                        <div className="text-xs text-gray-600">Run: python3 crypto_market/run_scan.py</div>
                    </div>
                ) : (
                    <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-white/5">
                                        <th className="text-left py-3 px-4">Symbol</th>
                                        <th className="text-left py-3 px-4">Type</th>
                                        <th className="text-right py-3 px-4">Score</th>
                                        <th className="text-right py-3 px-4">Pivot High</th>
                                        <th className="text-left py-3 px-4">Timeframe</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {signals.slice(0, 5).map((signal, idx) => (
                                        <tr
                                            key={signal.symbol + idx}
                                            className="border-b border-white/5 last:border-b-0 hover:bg-white/5 transition-colors"
                                        >
                                            <td className="py-3 px-4">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-yellow-400 text-[10px] font-mono">{signal.exchange}</span>
                                                    <span className="text-white font-bold text-sm">{signal.symbol}</span>
                                                </div>
                                            </td>
                                            <td className="py-3 px-4">
                                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${getSignalTypeBadge(signal.signal_type)}`}>
                                                    {signal.signal_type}
                                                </span>
                                            </td>
                                            <td className="py-3 px-4 text-right">
                                                <span className="text-white font-bold text-sm">{signal.score}</span>
                                            </td>
                                            <td className="py-3 px-4 text-right text-gray-400 font-mono text-sm">
                                                ${signal.pivot_high.toFixed(4)}
                                            </td>
                                            <td className="py-3 px-4 text-gray-500 text-sm">
                                                {signal.timeframe}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </section>

            {/* ═══ 6. Quick Links Grid (2x2) ═══ */}
            <section>
                <div className="flex items-center mb-4">
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                        <span className="w-1 h-5 bg-orange-500 rounded-full"></span>
                        Quick Access
                    </h3>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {[
                        {
                            href: '/dashboard/crypto/briefing',
                            icon: 'fa-newspaper',
                            color: 'amber',
                            title: 'Market Briefing',
                            desc: 'AI 기반 시장 요약, Fear & Greed, 탑 무버',
                        },
                        {
                            href: '/dashboard/crypto/signals',
                            icon: 'fa-bolt',
                            color: 'yellow',
                            title: 'VCP Signals',
                            desc: '변동성 수축 패턴 돌파 스캔 전체 리스트',
                        },
                        {
                            href: '/dashboard/crypto/prediction',
                            icon: 'fa-brain',
                            color: 'blue',
                            title: 'ML Prediction',
                            desc: 'BTC/ETH 방향 예측 & 핵심 드라이버 분석',
                        },
                        {
                            href: '/dashboard/crypto/risk',
                            icon: 'fa-shield-halved',
                            color: 'orange',
                            title: 'Risk Dashboard',
                            desc: 'VaR/CVaR, 상관관계, 집중도 경고',
                        },
                    ].map((link) => (
                        <Link
                            key={link.href}
                            href={link.href}
                            className="bg-[#2c2c2e] border border-white/10 rounded-xl p-5 hover:border-white/20 transition-colors group"
                        >
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className={`text-sm font-bold text-white group-hover:text-${link.color}-400 transition-colors flex items-center gap-2`}>
                                        <i className={`fas ${link.icon} text-${link.color}-500`}></i>
                                        {link.title}
                                    </div>
                                    <div className="text-xs text-gray-500 mt-1">{link.desc}</div>
                                </div>
                                <i className={`fas fa-arrow-right text-gray-600 group-hover:text-${link.color}-400 transition-colors`}></i>
                            </div>
                        </Link>
                    ))}
                </div>
            </section>

            {/* Footer */}
            <div className="text-center text-xs text-gray-600">
                {briefing?.timestamp
                    ? `Data as of ${new Date(briefing.timestamp).toLocaleString('ko-KR')}`
                    : 'Loading market data...'}
            </div>
        </div>
    );
}
