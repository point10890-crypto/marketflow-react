'use client';

import { useEffect, useState, useRef } from 'react';
import { cryptoAPI, CryptoBriefingData } from '@/lib/api';
import HelpButton from '@/components/ui/HelpButton';
import { createChart, IChartApi, AreaSeries, CrosshairMode, Time, LineData } from 'lightweight-charts';

export default function CryptoBriefingPage() {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState<CryptoBriefingData | null>(null);

    const btcChartContainerRef = useRef<HTMLDivElement>(null);
    const btcChartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const res = await cryptoAPI.getBriefing();
            setData(res);
        } catch (error) {
            console.error('Failed to load crypto briefing:', error);
        } finally {
            setLoading(false);
        }
    };

    // BTC Price (90d) Chart
    useEffect(() => {
        if (!data?.btc_price_history || data.btc_price_history.length === 0 || !btcChartContainerRef.current) return;

        if (btcChartRef.current) {
            btcChartRef.current.remove();
            btcChartRef.current = null;
        }

        const chart = createChart(btcChartContainerRef.current, {
            width: btcChartContainerRef.current.clientWidth,
            height: 300,
            layout: { background: { color: 'transparent' }, textColor: '#6b7280' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
            crosshair: { mode: CrosshairMode.Normal },
        });
        btcChartRef.current = chart;

        const areaSeries = chart.addSeries(AreaSeries, {
            lineColor: '#eab308',
            topColor: 'rgba(234,179,8,0.3)',
            bottomColor: 'rgba(234,179,8,0.02)',
            lineWidth: 2,
        });

        const chartData: LineData<Time>[] = data.btc_price_history.map(d => ({
            time: d.date as Time,
            value: d.price,
        }));
        areaSeries.setData(chartData);
        chart.timeScale().fitContent();

        const handleResize = () => {
            if (btcChartContainerRef.current) {
                chart.applyOptions({ width: btcChartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
            btcChartRef.current = null;
        };
    }, [data]);

    const formatLargeNumber = (n: number) => {
        if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
        if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
        if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
        return `$${n.toLocaleString()}`;
    };

    const formatPrice = (price: number) => {
        if (price >= 1000) return `$${price.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
        if (price >= 1) return `$${price.toFixed(2)}`;
        return `$${price.toFixed(4)}`;
    };

    const getChangeColor = (val: number) => val >= 0 ? 'text-green-400' : 'text-red-400';
    const getChangeBg = (val: number) => val >= 0 ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400';

    const getFearGreedColor = (score: number) => {
        if (score <= 25) return '#ef4444';
        if (score <= 45) return '#f97316';
        if (score <= 55) return '#eab308';
        if (score <= 75) return '#84cc16';
        return '#22c55e';
    };

    const getFearGreedLevel = (score: number) => {
        if (score <= 25) return 'Extreme Fear';
        if (score <= 45) return 'Fear';
        if (score <= 55) return 'Neutral';
        if (score <= 75) return 'Greed';
        return 'Extreme Greed';
    };

    const getCorrelationColor = (val: number) => {
        if (val >= 0.5) return 'text-green-400';
        if (val >= 0) return 'text-gray-400';
        if (val >= -0.5) return 'text-yellow-400';
        return 'text-red-400';
    };

    const coinLabels: Record<string, string> = {
        BTC: 'Bitcoin',
        ETH: 'Ethereum',
        SOL: 'Solana',
        BNB: 'BNB',
        XRP: 'XRP',
    };

    if (loading) {
        return (
            <div className="space-y-6 animate-pulse">
                <div className="h-16 bg-[#2c2c2e] rounded-xl w-1/3"></div>
                <div className="grid grid-cols-3 gap-4">
                    {[1, 2, 3].map(i => <div key={i} className="h-32 bg-[#2c2c2e] rounded-xl"></div>)}
                </div>
                <div className="grid grid-cols-5 gap-4">
                    {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-36 bg-[#2c2c2e] rounded-xl"></div>)}
                </div>
                <div className="grid grid-cols-2 gap-4">
                    <div className="h-64 bg-[#2c2c2e] rounded-xl"></div>
                    <div className="h-64 bg-[#2c2c2e] rounded-xl"></div>
                </div>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
                <div className="w-20 h-20 rounded-2xl bg-yellow-500/10 flex items-center justify-center border border-yellow-500/20">
                    <i className="fab fa-bitcoin text-4xl text-yellow-500"></i>
                </div>
                <h2 className="text-2xl font-bold text-white">No Briefing Data</h2>
                <p className="text-gray-500">Run the crypto briefing script to generate data.</p>
                <div className="bg-black/40 rounded-xl p-4 border border-white/5">
                    <code className="text-sm text-yellow-400 font-mono">python3 crypto_market/crypto_briefing.py</code>
                </div>
            </div>
        );
    }

    const { market_summary, major_coins, top_movers, fear_greed, funding_rates, macro_correlations } = data;
    const fearGreedColor = getFearGreedColor(fear_greed.score);
    const rotation = (fear_greed.score / 100) * 180 - 90;

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-yellow-500/20 bg-yellow-500/5 text-xs text-yellow-400 font-medium mb-4">
                    <span className="relative flex h-1.5 w-1.5">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-yellow-500"></span>
                    </span>
                    Crypto Intelligence
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <div className="flex items-center gap-3">
                            <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                                Crypto Market <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-400 to-orange-400">Briefing</span>
                            </h2>
                            <HelpButton title="Crypto Briefing 가이드" sections={[
                                { heading: '작동 원리', body: '암호화폐 시장 전체의 주요 데이터를 한눈에 요약합니다.\n\n- Total Market Cap: 전체 암호화폐 시가총액\n- BTC Dominance: 비트코인이 전체 시장에서 차지하는 비중\n- 24h Volume: 24시간 총 거래량\n- Fear & Greed: 시장 심리 지수 (0=극도의 공포, 100=극도의 탐욕)' },
                                { heading: '해석 방법', body: '- Fear & Greed 20 이하: 극도의 공포 -> 역발상 매수 기회\n- Fear & Greed 80 이상: 극도의 탐욕 -> 차익 실현 고려\n- BTC Dominance 상승: 알트코인 약세, BTC 중심 시장\n- BTC Dominance 하락: 알트코인 강세 (알트시즌 가능성)\n- Funding Rate 양수: 롱 과열, 숏 스퀴즈 주의\n- Funding Rate 음수: 숏 과열, 반등 가능성' },
                                { heading: '활용 팁', body: '- Top Movers로 당일 시장 테마 파악\n- Macro Correlations에서 BTC-SPY 상관관계가 높으면 전통 금융 영향 큼\n- BTC-Gold 상관관계 상승 시 안전자산 내러티브 강화\n- Funding Rate가 극단적이면 가격 반전 가능성 높음' },
                            ]} />
                        </div>
                        <p className="text-gray-400">암호화폐 시장 종합 브리핑</p>
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

            {/* Top Row - Market Overview */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Total Market Cap */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-24 h-24 bg-yellow-500/5 rounded-full blur-2xl -mr-6 -mt-6"></div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest font-bold mb-1">Total Market Cap</div>
                    <div className="text-3xl font-black text-white tracking-tight">
                        {formatLargeNumber(market_summary.total_market_cap)}
                    </div>
                    <div className={`text-sm font-bold mt-2 ${getChangeColor(market_summary.total_market_cap_change_24h)}`}>
                        {market_summary.total_market_cap_change_24h >= 0 ? '+' : ''}{market_summary.total_market_cap_change_24h.toFixed(2)}%
                        <span className="text-gray-500 font-normal text-xs ml-1">24h</span>
                    </div>
                </div>

                {/* BTC Dominance */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-24 h-24 bg-orange-500/5 rounded-full blur-2xl -mr-6 -mt-6"></div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest font-bold mb-1">BTC Dominance</div>
                    <div className="text-3xl font-black text-orange-400 tracking-tight">
                        {market_summary.btc_dominance.toFixed(1)}%
                    </div>
                    <div className="mt-3 w-full bg-white/5 rounded-full h-2 overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-orange-500 to-yellow-500 rounded-full transition-all" style={{ width: `${market_summary.btc_dominance}%` }}></div>
                    </div>
                    <div className={`text-xs font-medium mt-2 ${getChangeColor(market_summary.btc_dominance_change_24h)}`}>
                        {market_summary.btc_dominance_change_24h >= 0 ? '+' : ''}{market_summary.btc_dominance_change_24h.toFixed(2)}% 24h
                    </div>
                </div>

                {/* 24h Volume */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-2xl -mr-6 -mt-6"></div>
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest font-bold mb-1">24h Volume</div>
                    <div className="text-3xl font-black text-blue-400 tracking-tight">
                        {formatLargeNumber(market_summary.total_volume_24h)}
                    </div>
                    <div className="text-xs text-gray-500 mt-2">
                        {market_summary.active_cryptocurrencies?.toLocaleString() ?? '--'} active coins
                    </div>
                </div>
            </div>

            {/* BTC Price (90d) Chart */}
            {data.btc_price_history && data.btc_price_history.length > 0 && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-1 h-4 bg-yellow-500 rounded-full"></span>
                        BTC Price (90d)
                    </h3>
                    <div ref={btcChartContainerRef} className="w-full" />
                </div>
            )}

            {/* Major Coins Grid */}
            <div>
                <div className="flex items-center gap-2 mb-3">
                    <span className="w-1 h-5 bg-yellow-500 rounded-full"></span>
                    <h3 className="text-base font-bold text-white">Major Coins</h3>
                    <div className="flex-1 h-px bg-white/5"></div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    {Object.entries(major_coins).slice(0, 5).map(([symbol, coin]) => {
                        const is24hUp = coin.change_24h >= 0;
                        const is7dUp = coin.change_7d >= 0;
                        return (
                            <div key={symbol} className={`bg-[#2c2c2e] border border-white/10 rounded-xl p-5 transition-all hover:border-yellow-500/30 hover:shadow-lg group`}>
                                <div className="flex items-center gap-2 mb-3">
                                    <span className="text-sm font-black text-white">{symbol}</span>
                                    <span className="text-[10px] text-gray-500">{coinLabels[symbol] || symbol}</span>
                                </div>
                                <div className="text-xl font-black text-white tracking-tight mb-3">
                                    {formatPrice(coin.price)}
                                </div>
                                <div className="flex gap-3 text-xs">
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">24h</div>
                                        <div className={`font-bold ${is24hUp ? 'text-green-400' : 'text-red-400'}`}>
                                            {is24hUp ? '+' : ''}{coin.change_24h.toFixed(2)}%
                                        </div>
                                    </div>
                                    <div>
                                        <div className="text-[9px] text-gray-600 uppercase">7d</div>
                                        <div className={`font-bold ${is7dUp ? 'text-green-400' : 'text-red-400'}`}>
                                            {is7dUp ? '+' : ''}{coin.change_7d.toFixed(2)}%
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Two Columns: Top Movers + Fear & Greed */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Top Movers */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-green-500/10 flex items-center justify-center text-green-500">
                            <i className="fas fa-fire text-xs"></i>
                        </span>
                        Top Movers (24h)
                    </h3>

                    {/* Gainers */}
                    <div className="mb-4">
                        <div className="text-[10px] text-green-400 uppercase tracking-widest font-bold mb-2">Gainers</div>
                        <div className="space-y-1.5">
                            {top_movers.gainers.slice(0, 5).map((coin, i) => (
                                <div key={coin.symbol} className="flex items-center justify-between p-2 rounded-lg hover:bg-white/5 transition-colors">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] text-gray-600 w-4">{i + 1}</span>
                                        <span className="text-sm font-bold text-white">{coin.symbol}</span>
                                        <span className="text-[10px] text-gray-500 truncate max-w-[80px]">{coin.name}</span>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <span className="text-xs text-gray-400 font-mono">{formatPrice(coin.price)}</span>
                                        <span className="text-xs font-bold text-green-400 w-16 text-right">+{coin.change_24h.toFixed(2)}%</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Losers */}
                    <div>
                        <div className="text-[10px] text-red-400 uppercase tracking-widest font-bold mb-2">Losers</div>
                        <div className="space-y-1.5">
                            {top_movers.losers.slice(0, 5).map((coin, i) => (
                                <div key={coin.symbol} className="flex items-center justify-between p-2 rounded-lg hover:bg-white/5 transition-colors">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] text-gray-600 w-4">{i + 1}</span>
                                        <span className="text-sm font-bold text-white">{coin.symbol}</span>
                                        <span className="text-[10px] text-gray-500 truncate max-w-[80px]">{coin.name}</span>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <span className="text-xs text-gray-400 font-mono">{formatPrice(coin.price)}</span>
                                        <span className="text-xs font-bold text-red-400 w-16 text-right">{coin.change_24h.toFixed(2)}%</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Fear & Greed */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 flex flex-col items-center justify-center">
                    <h3 className="text-sm font-bold text-white mb-6 flex items-center gap-2 self-start">
                        <span className="w-6 h-6 rounded bg-yellow-500/10 flex items-center justify-center text-yellow-500">
                            <i className="fas fa-gauge-high text-xs"></i>
                        </span>
                        Fear & Greed Index
                    </h3>

                    {/* Semicircle Gauge */}
                    <div className="relative w-48 h-24 overflow-hidden mb-2">
                        <div className="absolute w-48 h-48 rounded-full"
                            style={{
                                background: `conic-gradient(from 180deg, #B71C1C 0deg, #FF5722 45deg, #FFC107 90deg, #4CAF50 135deg, #00C853 180deg, transparent 180deg)`,
                                clipPath: 'polygon(0 0, 100% 0, 100% 50%, 0 50%)',
                            }}
                        />
                        {/* Needle */}
                        <div
                            className="absolute bottom-0 left-1/2 w-1 h-20 bg-white origin-bottom rounded-full shadow-lg transition-transform duration-1000 ease-out"
                            style={{ transform: `translateX(-50%) rotate(${rotation}deg)` }}
                        />
                        <div className="absolute bottom-0 left-1/2 w-4 h-4 -translate-x-1/2 translate-y-1/2 rounded-full bg-white shadow-lg" />
                    </div>

                    {/* Score */}
                    <div className="text-center mt-4">
                        <div className="text-5xl font-black tracking-tighter" style={{ color: fearGreedColor }}>
                            {fear_greed.score}
                        </div>
                        <div className="text-lg font-bold mt-1" style={{ color: fearGreedColor }}>
                            {fear_greed.level || getFearGreedLevel(fear_greed.score)}
                        </div>
                        {fear_greed.previous !== undefined && (
                            <div className="text-xs text-gray-500 mt-2">
                                Previous: {fear_greed.previous}
                                <span className={`ml-2 font-bold ${getChangeColor(fear_greed.change)}`}>
                                    ({fear_greed.change >= 0 ? '+' : ''}{fear_greed.change})
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Scale */}
                    <div className="w-full flex justify-between text-[9px] text-gray-500 mt-4 px-6">
                        <span>Extreme Fear</span>
                        <span>Neutral</span>
                        <span>Extreme Greed</span>
                    </div>
                </div>
            </div>

            {/* Bottom Row: Funding Rates + Macro Correlations */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Funding Rates */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-purple-500/10 flex items-center justify-center text-purple-500">
                            <i className="fas fa-percentage text-xs"></i>
                        </span>
                        Funding Rates
                    </h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-white/10">
                                    <th className="text-left py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider">Pair</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider">Rate</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider">Annualized</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider">Sentiment</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(funding_rates).map(([pair, rate]) => (
                                    <tr key={pair} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                        <td className="py-3 px-3 font-bold text-white">{pair}</td>
                                        <td className={`py-3 px-3 text-right font-mono font-bold ${getChangeColor(rate.rate_pct)}`}>
                                            {rate.rate_pct >= 0 ? '+' : ''}{rate.rate_pct.toFixed(4)}%
                                        </td>
                                        <td className={`py-3 px-3 text-right font-mono ${getChangeColor(rate.annualized_pct)}`}>
                                            {rate.annualized_pct >= 0 ? '+' : ''}{rate.annualized_pct.toFixed(1)}%
                                        </td>
                                        <td className="py-3 px-3 text-right">
                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                                rate.sentiment === 'Bullish' ? 'bg-green-500/20 text-green-400' :
                                                rate.sentiment === 'Bearish' ? 'bg-red-500/20 text-red-400' :
                                                'bg-gray-500/20 text-gray-400'
                                            }`}>
                                                {rate.sentiment}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Macro Correlations */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-teal-500/10 flex items-center justify-center text-teal-500">
                            <i className="fas fa-link text-xs"></i>
                        </span>
                        Macro Correlations (BTC vs)
                    </h3>
                    <div className="space-y-4">
                        {Object.entries(macro_correlations.btc_pairs).map(([pair, corr]) => {
                            const absCorr = Math.abs(corr);
                            const barWidth = absCorr * 100;
                            const isPositive = corr >= 0;
                            return (
                                <div key={pair}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-sm font-medium text-gray-300">{pair}</span>
                                        <span className={`text-sm font-bold font-mono ${getCorrelationColor(corr)}`}>
                                            {corr >= 0 ? '+' : ''}{corr.toFixed(3)}
                                        </span>
                                    </div>
                                    <div className="relative h-2 bg-white/5 rounded-full overflow-hidden">
                                        <div className="absolute inset-y-0 left-1/2 w-px bg-white/10"></div>
                                        {isPositive ? (
                                            <div
                                                className="absolute inset-y-0 left-1/2 bg-green-500/60 rounded-r-full transition-all"
                                                style={{ width: `${barWidth / 2}%` }}
                                            />
                                        ) : (
                                            <div
                                                className="absolute inset-y-0 bg-red-500/60 rounded-l-full transition-all"
                                                style={{ width: `${barWidth / 2}%`, right: '50%' }}
                                            />
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                    <div className="flex justify-between text-[9px] text-gray-600 mt-3 px-1">
                        <span>-1.0 (Inverse)</span>
                        <span>0</span>
                        <span>+1.0 (Correlated)</span>
                    </div>
                </div>
            </div>

            {/* Sentiment Summary */}
            {data.sentiment_summary && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-blue-500/10 flex items-center justify-center text-blue-500">
                            <i className="fas fa-comments text-xs"></i>
                        </span>
                        Market Sentiment
                    </h3>
                    <div className="flex items-center gap-3 mb-3">
                        <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                            data.sentiment_summary.overall === 'Bullish' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                            data.sentiment_summary.overall === 'Bearish' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                            'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                        }`}>
                            {data.sentiment_summary.overall}
                        </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {data.sentiment_summary.factors.map((factor, i) => (
                            <span key={i} className="px-2.5 py-1 rounded-lg bg-white/5 text-xs text-gray-400 border border-white/5">
                                {factor}
                            </span>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
