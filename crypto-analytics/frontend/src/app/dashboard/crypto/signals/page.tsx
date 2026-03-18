'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts';
import { cryptoAPI, CryptoSignal, CryptoMarketGate, LeadLagData } from '@/lib/api';
import HelpButton from '@/components/ui/HelpButton';

interface KlineData {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

function SignalChartModal({ signal, onClose }: { signal: CryptoSignal; onClose: () => void }) {
    const chartRef = useRef<HTMLDivElement>(null);
    const [klines, setKlines] = useState<KlineData[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [analysis, setAnalysis] = useState<string | null>(null);
    const [analysisLoading, setAnalysisLoading] = useState(false);

    useEffect(() => {
        const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('keydown', handleKey);
        document.body.style.overflow = 'hidden';
        return () => { document.removeEventListener('keydown', handleKey); document.body.style.overflow = ''; };
    }, [onClose]);

    useEffect(() => {
        const fetchKlines = async () => {
            try {
                const binanceSymbol = signal.symbol.replace('/', '');
                const intervalMap: Record<string, string> = { '4h': '4h', '1d': '1d', '1h': '1h' };
                const interval = intervalMap[signal.timeframe] || '4h';
                const limit = signal.timeframe === '1d' ? 120 : 200;

                const res = await fetch(
                    `https://api.binance.com/api/v3/klines?symbol=${binanceSymbol}&interval=${interval}&limit=${limit}`
                );
                if (!res.ok) throw new Error(`Binance API ${res.status}`);
                const data = await res.json();

                const parsed: KlineData[] = data.map((k: (string | number)[]) => ({
                    time: new Date(k[0] as number).toISOString().split('T')[0] +
                        (interval !== '1d' ? 'T' + new Date(k[0] as number).toISOString().split('T')[1] : ''),
                    open: parseFloat(k[1] as string),
                    high: parseFloat(k[2] as string),
                    low: parseFloat(k[3] as string),
                    close: parseFloat(k[4] as string),
                    volume: parseFloat(k[5] as string),
                }));
                setKlines(parsed);

                // Fetch LLM analysis with current price
                const currentPrice = parsed.length > 0 ? parsed[parsed.length - 1].close : 0;
                fetchAnalysis(currentPrice);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to fetch data');
            } finally {
                setLoading(false);
            }
        };

        const fetchAnalysis = async (currentPrice: number) => {
            setAnalysisLoading(true);
            try {
                const res = await fetch('/api/crypto/signal-analysis', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: signal.symbol,
                        signal_type: signal.signal_type,
                        score: signal.score,
                        pivot_high: signal.pivot_high,
                        vol_ratio: signal.vol_ratio,
                        timeframe: signal.timeframe,
                        current_price: currentPrice,
                    }),
                });
                if (!res.ok) throw new Error('Analysis API failed');
                const data = await res.json();
                setAnalysis(data.analysis);
            } catch {
                setAnalysis(null);
            } finally {
                setAnalysisLoading(false);
            }
        };

        fetchKlines();
    }, [signal]);

    useEffect(() => {
        if (!chartRef.current || klines.length === 0) return;

        const chart = createChart(chartRef.current, {
            width: chartRef.current.clientWidth,
            height: 320,
            layout: { background: { color: '#1c1c1e' }, textColor: '#9ca3af', fontSize: 12 },
            grid: { vertLines: { color: '#2c2c2e' }, horzLines: { color: '#2c2c2e' } },
            crosshair: { mode: 0 },
            rightPriceScale: { borderColor: '#2c2c2e' },
            timeScale: { borderColor: '#2c2c2e', timeVisible: signal.timeframe !== '1d' },
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e', downColor: '#ef4444',
            borderUpColor: '#22c55e', borderDownColor: '#ef4444',
            wickUpColor: '#22c55e', wickDownColor: '#ef4444',
        });

        const candleData = klines.map(k => ({
            time: (signal.timeframe === '1d'
                ? k.time.split('T')[0]
                : Math.floor(new Date(k.time).getTime() / 1000)) as never,
            open: k.open, high: k.high, low: k.low, close: k.close,
        }));
        candleSeries.setData(candleData);

        // Pivot high line
        if (signal.pivot_high > 0) {
            candleSeries.createPriceLine({
                price: signal.pivot_high,
                color: '#f59e0b',
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: `Pivot $${signal.pivot_high.toFixed(4)}`,
            });

            // Take Profit line (10% above pivot)
            const tp = signal.pivot_high * 1.10;
            candleSeries.createPriceLine({
                price: tp,
                color: 'rgba(34,197,94,0.6)',
                lineWidth: 1,
                lineStyle: 1,
                axisLabelVisible: true,
                title: `TP +10%`,
            });

            // Stop Loss line (2% below pivot)
            const sl = signal.pivot_high * 0.98;
            candleSeries.createPriceLine({
                price: sl,
                color: 'rgba(239,68,68,0.6)',
                lineWidth: 1,
                lineStyle: 1,
                axisLabelVisible: true,
                title: `SL -2%`,
            });
        }

        // ML Win Prob overlay badge
        if (signal.ml_win_prob != null && chartRef.current) {
            const badge = document.createElement('div');
            const prob = signal.ml_win_prob;
            const color = prob >= 50 ? '#22c55e' : prob >= 35 ? '#eab308' : '#ef4444';
            badge.innerHTML = `<span style="
                position:absolute; top:8px; left:8px; z-index:10;
                background:rgba(0,0,0,0.7); backdrop-filter:blur(4px);
                border:1px solid ${color}40; border-radius:8px;
                padding:4px 10px; font-size:11px; font-weight:700;
                color:${color}; font-family:monospace;
            ">ML ${prob.toFixed(1)}% ${prob >= 50 ? 'WIN' : 'LOSS'}</span>`;
            chartRef.current.style.position = 'relative';
            chartRef.current.appendChild(badge);
        }

        // Volume
        const volumeSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
        });
        volumeSeries.setData(klines.map(k => ({
            time: (signal.timeframe === '1d'
                ? k.time.split('T')[0]
                : Math.floor(new Date(k.time).getTime() / 1000)) as never,
            value: k.volume,
            color: k.close >= k.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
        })));

        chart.timeScale().fitContent();

        const handleResize = () => {
            if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
        };
        window.addEventListener('resize', handleResize);
        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [klines, signal]);

    const lastPrice = klines.length > 0 ? klines[klines.length - 1].close : 0;
    const firstPrice = klines.length > 0 ? klines[0].open : 0;
    const priceChange = firstPrice > 0 ? ((lastPrice - firstPrice) / firstPrice * 100) : 0;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />
            <div className="relative w-full max-w-2xl z-10 bg-[#1c1c1e] border border-white/10 rounded-2xl overflow-hidden shadow-2xl max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 w-8 h-8 rounded-full bg-white/10 border border-white/20 text-white hover:bg-white/20 transition-all flex items-center justify-center text-sm z-20"
                >
                    ✕
                </button>

                {/* Header */}
                <div className="px-6 py-4 border-b border-white/5">
                    <div className="flex items-center gap-3">
                        <span className="text-xl font-black text-white">{signal.symbol}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            signal.signal_type === 'BREAKOUT' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'
                        }`}>
                            {signal.signal_type}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-white/5 text-[10px] font-mono text-gray-400">
                            {signal.timeframe.toUpperCase()}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-yellow-500/10 text-[10px] font-bold text-yellow-400">
                            Score {signal.score}
                        </span>
                        {signal.ml_win_prob != null && (
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                signal.ml_win_prob >= 50 ? 'bg-green-500/20 text-green-400' :
                                signal.ml_win_prob >= 35 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-red-500/20 text-red-400'
                            }`}>
                                ML {signal.ml_win_prob.toFixed(1)}%
                            </span>
                        )}
                    </div>
                    {klines.length > 0 && (
                        <div className="flex items-center gap-4 mt-2">
                            <span className="text-lg font-mono font-bold text-white">${lastPrice.toFixed(lastPrice < 1 ? 6 : 2)}</span>
                            <span className={`text-sm font-bold ${priceChange >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%
                            </span>
                            {signal.pivot_high > 0 && (
                                <span className="text-xs text-gray-500">
                                    Pivot: <span className="text-amber-400 font-mono">${signal.pivot_high.toFixed(4)}</span>
                                    {lastPrice > 0 && (
                                        <span className={`ml-1 ${lastPrice >= signal.pivot_high ? 'text-green-400' : 'text-gray-400'}`}>
                                            ({((lastPrice / signal.pivot_high - 1) * 100).toFixed(1)}%)
                                        </span>
                                    )}
                                </span>
                            )}
                        </div>
                    )}
                </div>

                {/* Chart */}
                <div className="px-4 py-3">
                    {loading && (
                        <div className="h-[320px] flex items-center justify-center">
                            <div className="flex flex-col items-center gap-3">
                                <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin"></div>
                                <span className="text-sm text-gray-500">Loading chart data...</span>
                            </div>
                        </div>
                    )}
                    {error && (
                        <div className="h-[320px] flex items-center justify-center">
                            <div className="text-center">
                                <div className="text-red-400 text-sm mb-2">{error}</div>
                                <div className="text-gray-600 text-xs">Binance API may not have this pair</div>
                            </div>
                        </div>
                    )}
                    {!loading && !error && <div ref={chartRef} />}
                </div>

                {/* AI Analysis */}
                <div className="px-6 py-4 border-t border-white/5">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="w-2 h-2 rounded-full bg-purple-500 animate-pulse"></div>
                        <span className="text-[10px] font-bold text-purple-400 uppercase tracking-wider">AI Signal Analysis</span>
                        <span className="text-[10px] text-gray-600 ml-auto">GPT-4o-mini</span>
                    </div>
                    {analysisLoading ? (
                        <div className="flex items-center gap-3 py-4">
                            <div className="w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
                            <span className="text-sm text-gray-500">분석 중...</span>
                        </div>
                    ) : analysis ? (
                        <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap bg-[#2c2c2e] rounded-xl p-3 border border-white/5 max-h-[150px] overflow-y-auto">
                            {analysis}
                        </div>
                    ) : (
                        <div className="text-sm text-gray-600 py-2">분석을 불러올 수 없습니다</div>
                    )}
                </div>

                {/* Footer Info */}
                <div className="px-6 py-3 border-t border-white/5 flex items-center justify-between text-[10px] text-gray-600">
                    <span>Vol Ratio: <span className="text-gray-400 font-mono">{signal.vol_ratio.toFixed(2)}x</span></span>
                    <span>Detected: {new Date(signal.created_at).toLocaleString('ko-KR')}</span>
                    <span className="text-amber-500/50">Amber line = Pivot High</span>
                </div>
            </div>
        </div>
    );
}

function ChartModal({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
    useEffect(() => {
        const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('keydown', handleKey);
        document.body.style.overflow = 'hidden';
        return () => { document.removeEventListener('keydown', handleKey); document.body.style.overflow = ''; };
    }, [onClose]);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
            <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />
            <div className="relative max-w-[95vw] max-h-[95vh] z-10" onClick={e => e.stopPropagation()}>
                <button
                    onClick={onClose}
                    className="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-white/10 border border-white/20 text-white hover:bg-white/20 transition-all flex items-center justify-center text-sm backdrop-blur-sm z-20"
                >
                    ✕
                </button>
                <img src={src} alt={alt} className="max-w-[95vw] max-h-[90vh] rounded-xl border border-white/10 shadow-2xl object-contain" />
                <div className="text-center mt-3 text-sm text-gray-400">{alt}</div>
            </div>
        </div>
    );
}

export default function CryptoSignalsPage() {
    const [loading, setLoading] = useState(true);
    const [signals, setSignals] = useState<CryptoSignal[]>([]);
    const [gateData, setGateData] = useState<CryptoMarketGate | null>(null);
    const [charts, setCharts] = useState<string[]>([]);
    const [leadLag, setLeadLag] = useState<LeadLagData | null>(null);
    const [modalImg, setModalImg] = useState<{ src: string; alt: string } | null>(null);
    const [selectedSignal, setSelectedSignal] = useState<CryptoSignal | null>(null);
    const [filterType, setFilterType] = useState<string>('ALL');
    const [minScore, setMinScore] = useState<number>(0);
    const [filterTimeframe, setFilterTimeframe] = useState<string>('all');
    const [filterDate, setFilterDate] = useState<string>('');
    const closeModal = useCallback(() => setModalImg(null), []);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [signalsRes, gateRes, chartsRes, leadLagRes] = await Promise.all([
                cryptoAPI.getVCPSignals(100).catch(() => ({ signals: [], count: 0 })),
                cryptoAPI.getMarketGate().catch(() => null),
                fetch('/api/crypto/lead-lag/charts/list').then(r => r.json()).catch(() => ({ charts: [] })),
                cryptoAPI.getLeadLag().catch(() => null),
            ]);

            setSignals(signalsRes.signals || []);
            setGateData(gateRes);
            setCharts(chartsRes.charts || []);
            setLeadLag(leadLagRes);
        } catch (error) {
            console.error('Failed to load signals data:', error);
        } finally {
            setLoading(false);
        }
    };

    const getGateColor = (score: number) => {
        if (score >= 70) return 'text-green-500';
        if (score >= 40) return 'text-yellow-500';
        return 'text-red-500';
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'RISK_ON': return 'bg-green-500/20 text-green-400 border-green-500/30';
            case 'RISK_OFF': return 'bg-red-500/20 text-red-400 border-red-500/30';
            default: return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        }
    };

    const getSignalTypeBadge = (type: string) => {
        switch (type) {
            case 'BREAKOUT': return 'bg-green-500/20 text-green-400';
            case 'APPROACHING': return 'bg-yellow-500/20 text-yellow-400';
            default: return 'bg-gray-500/20 text-gray-400';
        }
    };

    const getScoreColor = (score: number) => {
        if (score >= 80) return 'text-green-400';
        if (score >= 60) return 'text-yellow-400';
        if (score >= 40) return 'text-orange-400';
        return 'text-red-400';
    };

    const availableDates = [...new Set(signals.map(s => s.created_at.split(' ')[0] || s.created_at.split('T')[0]))].sort().reverse();

    const filteredSignals = signals.filter(s => {
        if (filterType !== 'ALL' && s.signal_type !== filterType) return false;
        if (s.score < minScore) return false;
        if (filterTimeframe !== 'all' && s.timeframe !== filterTimeframe) return false;
        if (filterDate) {
            const signalDate = s.created_at.split(' ')[0] || s.created_at.split('T')[0];
            if (signalDate !== filterDate) return false;
        }
        return true;
    });

    const breakoutCount = signals.filter(s => s.signal_type === 'BREAKOUT').length;
    const approachingCount = signals.filter(s => s.signal_type === 'APPROACHING').length;

    const heatmaps = charts.filter(c => c.includes('heatmap'));
    const granger = charts.filter(c => c.includes('granger'));
    const ccf = charts.filter(c => c.includes('ccf'));

    if (loading) {
        return (
            <div className="space-y-6 animate-pulse">
                <div className="h-16 bg-[#2c2c2e] rounded-xl w-1/3"></div>
                <div className="grid grid-cols-4 gap-4">
                    {[1, 2, 3, 4].map(i => <div key={i} className="h-28 bg-[#2c2c2e] rounded-xl"></div>)}
                </div>
                <div className="h-12 bg-[#2c2c2e] rounded-xl"></div>
                <div className="space-y-3">
                    {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-14 bg-[#2c2c2e] rounded-xl"></div>)}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-yellow-500/20 bg-yellow-500/5 text-xs text-yellow-400 font-medium mb-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-ping"></span>
                    Crypto Alpha
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <div className="flex items-center gap-3">
                            <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                                Crypto <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-400 to-orange-400">VCP Signals</span>
                            </h2>
                            <HelpButton title="Crypto VCP Signals 가이드" sections={[
                                { heading: '작동 원리', body: '암호화폐 시장에서 VCP(Volatility Contraction Pattern)를 스캔합니다.\n\n- BTC Market Gate: BTC 가격 vs MA200 기반 시장 건강도\n  - RISK_ON: BTC > MA200, 알트코인 매수 환경\n  - RISK_OFF: BTC < MA200, 보수적 접근\n- VCP 스캔: 가격 수축 반복 후 돌파 임박 코인 탐지' },
                                { heading: '신호 유형', body: '- BREAKOUT: 이미 피봇 고점을 돌파한 코인. 추격 매수는 주의\n- APPROACHING: 돌파 임박 코인. 진입 준비\n\n- Score 80+: 매우 강한 신호\n- Score 60-80: 유효한 신호\n- Score 40 미만: 약한 신호, 추가 확인 필요' },
                                { heading: '필터 활용', body: '- Signal Type: BREAKOUT/APPROACHING 필터링\n- Min Score: 최소 점수 기준 설정\n- Timeframe: 4h(단기) / 1d(일봉) 선택\n\nGate Score 70+ 환경에서 Score 60+ 신호에 집중하세요.' },
                                { heading: 'Lead-Lag 분석', body: '- Correlation Heatmap: 코인 간 상관관계\n- Granger Causality: 인과관계 방향 (어떤 코인이 선행하는지)\n- CCF: 교차상관 함수로 시차 관계 확인\n\nBTC가 선행 후 알트코인 추종하는 패턴이 일반적입니다.' },
                            ]} />
                        </div>
                        <p className="text-gray-400">암호화폐 변동성 수축 패턴 스캔 & Lead-Lag 분석</p>
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

            {/* Stats Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {/* Gate Score */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-5 relative overflow-hidden group">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                        BTC Market Gate
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse"></span>
                    </div>
                    <div className="flex flex-col items-center py-1">
                        <div className="relative w-20 h-20 flex items-center justify-center">
                            <svg className="w-full h-full -rotate-90">
                                <circle cx="40" cy="40" r="34" stroke="currentColor" strokeWidth="5" fill="transparent" className="text-white/5" />
                                <circle
                                    cx="40" cy="40" r="34"
                                    stroke="currentColor"
                                    strokeWidth="5"
                                    fill="transparent"
                                    strokeDasharray="214"
                                    strokeDashoffset={214 - (214 * (gateData?.score ?? 0) / 100)}
                                    className={`${getGateColor(gateData?.score ?? 0)} transition-all duration-1000 ease-out`}
                                />
                            </svg>
                            <div className="absolute inset-0 flex items-center justify-center">
                                <span className={`text-lg font-black ${getGateColor(gateData?.score ?? 0)}`}>
                                    {gateData?.score ?? '--'}
                                </span>
                            </div>
                        </div>
                        <div className={`mt-2 px-3 py-0.5 rounded-full text-[10px] font-bold border ${getStatusBadge(gateData?.status ?? 'NEUTRAL')}`}>
                            {gateData?.status ?? 'N/A'}
                        </div>
                    </div>
                </div>

                {/* Total Signals */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-5 relative overflow-hidden group hover:border-yellow-500/30 transition-all">
                    <div className="absolute top-0 right-0 w-20 h-20 bg-yellow-500/10 rounded-full blur-[25px] -translate-y-1/2 translate-x-1/2"></div>
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Total Signals</div>
                    <div className="text-4xl font-black text-white group-hover:text-yellow-400 transition-colors">
                        {signals.length}
                    </div>
                    <div className="mt-2 text-xs text-gray-500">Active patterns detected</div>
                </div>

                {/* Breakout Count */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-5 relative overflow-hidden group hover:border-green-500/30 transition-all">
                    <div className="absolute top-0 right-0 w-20 h-20 bg-green-500/10 rounded-full blur-[25px] -translate-y-1/2 translate-x-1/2"></div>
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Breakouts</div>
                    <div className="text-4xl font-black text-white group-hover:text-green-400 transition-colors">
                        {breakoutCount}
                    </div>
                    <div className="mt-2 text-xs text-gray-500">Confirmed breakouts</div>
                </div>

                {/* Approaching Count */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-5 relative overflow-hidden group hover:border-yellow-500/30 transition-all">
                    <div className="absolute top-0 right-0 w-20 h-20 bg-yellow-500/10 rounded-full blur-[25px] -translate-y-1/2 translate-x-1/2"></div>
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Approaching</div>
                    <div className="text-4xl font-black text-white group-hover:text-yellow-400 transition-colors">
                        {approachingCount}
                    </div>
                    <div className="mt-2 text-xs text-gray-500">Nearing breakout</div>
                </div>
            </div>

            {/* Filter Bar */}
            <div className="flex flex-wrap items-center gap-4 p-4 bg-[#2c2c2e] border border-white/10 rounded-xl">
                <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">Type</span>
                    <select
                        value={filterType}
                        onChange={e => setFilterType(e.target.value)}
                        className="bg-[#1c1c1e] border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-yellow-500/50"
                    >
                        <option value="ALL">ALL</option>
                        <option value="BREAKOUT">BREAKOUT</option>
                        <option value="APPROACHING">APPROACHING</option>
                    </select>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">Min Score</span>
                    <input
                        type="range"
                        min={0}
                        max={100}
                        value={minScore}
                        onChange={e => setMinScore(Number(e.target.value))}
                        className="w-24 accent-yellow-500"
                    />
                    <span className="text-xs text-yellow-400 font-bold w-8">{minScore}</span>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">Timeframe</span>
                    <div className="flex rounded-lg overflow-hidden border border-white/10">
                        {['all', '4h', '1d'].map(tf => (
                            <button
                                key={tf}
                                onClick={() => setFilterTimeframe(tf)}
                                className={`px-3 py-1.5 text-xs font-bold transition-all ${
                                    filterTimeframe === tf
                                        ? 'bg-yellow-500/20 text-yellow-400'
                                        : 'bg-[#1c1c1e] text-gray-500 hover:text-gray-300'
                                }`}
                            >
                                {tf === 'all' ? 'ALL' : tf.toUpperCase()}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">Date</span>
                    <select
                        value={filterDate}
                        onChange={e => setFilterDate(e.target.value)}
                        className="bg-[#1c1c1e] border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-yellow-500/50"
                    >
                        <option value="">ALL</option>
                        {availableDates.map(d => (
                            <option key={d} value={d}>{d}</option>
                        ))}
                    </select>
                </div>

                <div className="ml-auto text-xs text-gray-500">
                    {filteredSignals.length} / {signals.length} signals
                </div>
            </div>

            {/* Signals Table */}
            <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                        <span className="w-1 h-5 bg-yellow-500 rounded-full"></span>
                        VCP Signals
                    </h3>
                    <span className="text-[10px] text-gray-500 font-mono uppercase tracking-wider">Click row to view chart & AI analysis</span>
                </div>

                {filteredSignals.length === 0 ? (
                    <div className="p-12 text-center">
                        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-yellow-500/10 flex items-center justify-center">
                            <i className="fab fa-bitcoin text-2xl text-yellow-500"></i>
                        </div>
                        <div className="text-gray-500 text-lg mb-2">No matching signals</div>
                        <div className="text-xs text-gray-600">Adjust filters or run: python3 crypto_market/run_scan.py</div>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-white/5">
                                    <th className="text-left py-3 px-4">Symbol</th>
                                    <th className="text-left py-3 px-4">Type</th>
                                    <th className="text-right py-3 px-4">Score</th>
                                    <th className="text-right py-3 px-4">ML Win</th>
                                    <th className="text-right py-3 px-4">Pivot High</th>
                                    <th className="text-right py-3 px-4">Vol Ratio</th>
                                    <th className="text-left py-3 px-4">Timeframe</th>
                                    <th className="text-left py-3 px-4">Created</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredSignals.map((signal, idx) => (
                                    <tr
                                        key={signal.symbol + idx}
                                        className="border-b border-white/5 hover:bg-yellow-500/5 transition-colors cursor-pointer group"
                                        onClick={() => setSelectedSignal(signal)}
                                    >
                                        <td className="py-3 px-4">
                                            <div className="flex items-center gap-2">
                                                <span className="text-yellow-400 text-xs font-mono">{signal.exchange}</span>
                                                <span className="text-white font-bold">{signal.symbol}</span>
                                            </div>
                                        </td>
                                        <td className="py-3 px-4">
                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${getSignalTypeBadge(signal.signal_type)}`}>
                                                {signal.signal_type}
                                            </span>
                                        </td>
                                        <td className="py-3 px-4 text-right">
                                            <span className={`font-bold ${getScoreColor(signal.score)}`}>{signal.score}</span>
                                        </td>
                                        <td className="py-3 px-4 text-right">
                                            {signal.ml_win_prob != null ? (
                                                <span className={`font-bold font-mono text-sm ${
                                                    signal.ml_win_prob >= 50 ? 'text-green-400' :
                                                    signal.ml_win_prob >= 35 ? 'text-yellow-400' : 'text-red-400'
                                                }`}>
                                                    {signal.ml_win_prob.toFixed(1)}%
                                                </span>
                                            ) : (
                                                <span className="text-gray-600 text-xs">--</span>
                                            )}
                                        </td>
                                        <td className="py-3 px-4 text-right text-gray-400 font-mono text-sm">
                                            ${signal.pivot_high.toFixed(4)}
                                        </td>
                                        <td className="py-3 px-4 text-right text-gray-400 font-mono text-sm">
                                            {signal.vol_ratio.toFixed(2)}x
                                        </td>
                                        <td className="py-3 px-4 text-gray-500 text-sm">{signal.timeframe}</td>
                                        <td className="py-3 px-4 text-gray-500 text-xs">
                                            {new Date(signal.created_at).toLocaleString('ko-KR')}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* ═══ Lead-Lag Macro Intelligence ═══ */}
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-xl font-bold text-white flex items-center gap-3">
                            <span className="w-1.5 h-8 bg-gradient-to-b from-blue-400 to-purple-500 rounded-full"></span>
                            Macro Lead-Lag Intelligence
                        </h3>
                        <p className="text-gray-500 text-sm mt-1 ml-5">
                            거시경제 지표 vs BTC 상관관계 · Granger 인과성 분석
                            {leadLag?.metadata?.generated_at && (
                                <span className="ml-2 text-gray-600">
                                    Updated {new Date(leadLag.metadata.generated_at).toLocaleDateString('ko-KR')}
                                </span>
                            )}
                        </p>
                    </div>
                </div>

                {/* Leading & Lagging Indicators Summary */}
                {leadLag?.lead_lag && leadLag.lead_lag.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Leading Indicators */}
                        <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                            <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                                <span className="text-xs font-bold text-emerald-400 uppercase tracking-wider">Leading Indicators</span>
                                <span className="text-[10px] text-gray-600 ml-auto">BTC보다 선행</span>
                            </div>
                            <div className="divide-y divide-white/5">
                                {leadLag.lead_lag
                                    .filter(p => p.optimal_lag > 0)
                                    .sort((a, b) => Math.abs(b.optimal_correlation) - Math.abs(a.optimal_correlation))
                                    .slice(0, 5)
                                    .map((pair, i) => (
                                    <div key={pair.var1} className="px-5 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors">
                                        <span className="text-[10px] font-bold text-gray-600 w-4">{i + 1}</span>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-bold text-white">{pair.var1}</span>
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                                                    {pair.optimal_lag}M ahead
                                                </span>
                                            </div>
                                        </div>
                                        <div className="text-right">
                                            <span className={`text-sm font-mono font-bold ${pair.optimal_correlation > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                {pair.optimal_correlation > 0 ? '+' : ''}{pair.optimal_correlation.toFixed(3)}
                                            </span>
                                        </div>
                                        <div className="w-16 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                            <div
                                                className={`h-full rounded-full ${pair.optimal_correlation > 0 ? 'bg-emerald-500' : 'bg-red-500'}`}
                                                style={{ width: `${Math.abs(pair.optimal_correlation) * 100}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Lagging Indicators */}
                        <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                            <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                                <span className="text-xs font-bold text-blue-400 uppercase tracking-wider">Lagging Indicators</span>
                                <span className="text-[10px] text-gray-600 ml-auto">BTC가 선행</span>
                            </div>
                            <div className="divide-y divide-white/5">
                                {leadLag.lead_lag
                                    .filter(p => p.optimal_lag < 0)
                                    .sort((a, b) => Math.abs(b.optimal_correlation) - Math.abs(a.optimal_correlation))
                                    .slice(0, 5)
                                    .map((pair, i) => (
                                    <div key={pair.var1} className="px-5 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors">
                                        <span className="text-[10px] font-bold text-gray-600 w-4">{i + 1}</span>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-bold text-white">{pair.var1}</span>
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono">
                                                    {Math.abs(pair.optimal_lag)}M behind
                                                </span>
                                            </div>
                                        </div>
                                        <div className="text-right">
                                            <span className={`text-sm font-mono font-bold ${pair.optimal_correlation > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                {pair.optimal_correlation > 0 ? '+' : ''}{pair.optimal_correlation.toFixed(3)}
                                            </span>
                                        </div>
                                        <div className="w-16 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                            <div
                                                className={`h-full rounded-full ${pair.optimal_correlation > 0 ? 'bg-blue-500' : 'bg-red-500'}`}
                                                style={{ width: `${Math.abs(pair.optimal_correlation) * 100}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}

                {/* Granger Causality — Predictive Indicators */}
                {leadLag?.granger && leadLag.granger.filter(g => g.is_significant).length > 0 && (
                    <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                        <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></div>
                            <span className="text-xs font-bold text-amber-400 uppercase tracking-wider">Granger Predictive Indicators</span>
                            <span className="text-[10px] text-gray-600 ml-auto">통계적으로 BTC 가격을 예측 가능한 지표 (p &lt; 0.05)</span>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-px bg-white/5">
                            {leadLag.granger
                                .filter(g => g.is_significant)
                                .sort((a, b) => a.best_p_value - b.best_p_value)
                                .slice(0, 12)
                                .map(g => (
                                <div key={g.cause} className="bg-[#2c2c2e] p-4 text-center hover:bg-white/5 transition-colors">
                                    <div className="text-xs font-bold text-white mb-1">{g.cause}</div>
                                    <div className="text-[10px] text-amber-400 font-mono mb-2">
                                        lag {g.best_lag} · p={g.best_p_value.toFixed(4)}
                                    </div>
                                    <div className="mx-auto w-10 h-10 rounded-full border-2 border-amber-500/30 flex items-center justify-center">
                                        <span className={`text-xs font-black ${g.best_p_value < 0.01 ? 'text-amber-400' : 'text-amber-500/70'}`}>
                                            {g.best_p_value < 0.001 ? '***' : g.best_p_value < 0.01 ? '**' : '*'}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Chart Images — Click to Expand */}
                {charts.length > 0 && (
                    <div className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {heatmaps.length > 0 && (
                                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                                    <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                                        <div className="w-2 h-2 rounded-full bg-purple-500"></div>
                                        <span className="text-xs font-bold text-purple-400 uppercase tracking-wider">Cross-Correlation Matrix</span>
                                        <span className="text-[10px] text-gray-600 ml-auto">Click to expand</span>
                                    </div>
                                    <div className="p-3 cursor-pointer" onClick={() => setModalImg({ src: `/api/crypto/lead-lag/charts/${heatmaps[0]}`, alt: 'Cross-Correlation Matrix · Macro Indicators vs BTC' })}>
                                        <img src={`/api/crypto/lead-lag/charts/${heatmaps[0]}`} alt="Macro-BTC Correlation Heatmap" className="w-full rounded-lg hover:opacity-90 transition-opacity" />
                                    </div>
                                </div>
                            )}
                            {granger.length > 0 && (
                                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                                    <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                                        <div className="w-2 h-2 rounded-full bg-orange-500"></div>
                                        <span className="text-xs font-bold text-orange-400 uppercase tracking-wider">Granger Causality Network</span>
                                        <span className="text-[10px] text-gray-600 ml-auto">Click to expand</span>
                                    </div>
                                    <div className="p-3 cursor-pointer" onClick={() => setModalImg({ src: `/api/crypto/lead-lag/charts/${granger[0]}`, alt: 'Granger Causality · What Predicts BTC?' })}>
                                        <img src={`/api/crypto/lead-lag/charts/${granger[0]}`} alt="Granger Causality Test Results" className="w-full rounded-lg hover:opacity-90 transition-opacity" />
                                    </div>
                                </div>
                            )}
                        </div>

                        {ccf.length > 0 && (
                            <div className="bg-[#2c2c2e] border border-white/10 rounded-xl overflow-hidden">
                                <div className="px-5 py-3 border-b border-white/5 flex items-center gap-2">
                                    <div className="w-2 h-2 rounded-full bg-cyan-500"></div>
                                    <span className="text-xs font-bold text-cyan-400 uppercase tracking-wider">Cross-Correlation Functions</span>
                                    <span className="text-[10px] text-gray-600 ml-auto">Top Predictive Indicators · Click to expand</span>
                                </div>
                                <div className="p-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                                    {ccf.slice(0, 6).map(chart => {
                                        const label = chart.replace('ccf_', '').replace(/_\d{8}_\d+\.png$/, '').replace(/_/g, ' ');
                                        return (
                                            <div
                                                key={chart}
                                                className="group relative cursor-pointer"
                                                onClick={() => setModalImg({ src: `/api/crypto/lead-lag/charts/${chart}`, alt: `CCF · ${label} → BTC` })}
                                            >
                                                <img src={`/api/crypto/lead-lag/charts/${chart}`} alt={label} className="w-full rounded-lg border border-white/5 group-hover:border-cyan-500/30 group-hover:opacity-90 transition-all" />
                                                <div className="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-black/70 text-[10px] font-bold text-cyan-400 backdrop-blur-sm">
                                                    {label}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {!leadLag && charts.length === 0 && (
                    <div className="p-12 rounded-2xl bg-[#2c2c2e] border border-white/10 text-center">
                        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-blue-500/10 flex items-center justify-center">
                            <i className="fas fa-chart-line text-2xl text-blue-500"></i>
                        </div>
                        <div className="text-gray-500 text-lg mb-2">No Lead-Lag analysis available</div>
                        <div className="text-xs text-gray-600">Analysis runs automatically at 03:00 daily</div>
                    </div>
                )}
            </div>

            {/* Signal Chart Modal */}
            {selectedSignal && <SignalChartModal signal={selectedSignal} onClose={() => setSelectedSignal(null)} />}

            {/* Chart Lightbox Modal */}
            {modalImg && <ChartModal src={modalImg.src} alt={modalImg.alt} onClose={closeModal} />}
        </div>
    );
}
