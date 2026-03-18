'use client';

import { useEffect, useState, useRef } from 'react';
import { usAPI, SmartMoneyDetail } from '@/lib/api';
import { createChart, IChartApi, CandlestickSeries, LineSeries, CandlestickData, LineData, Time } from 'lightweight-charts';

interface StockDetailModalProps {
    ticker: string;
    onClose: () => void;
}

export default function StockDetailModal({ ticker, onClose }: StockDetailModalProps) {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState<SmartMoneyDetail | null>(null);
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        loadData();
        return () => {
            if (chartRef.current) {
                chartRef.current.remove();
            }
        };
    }, [ticker]);

    useEffect(() => {
        if (data && data.chart.length > 0 && chartContainerRef.current) {
            renderChart();
            const handleResize = () => {
                if (chartContainerRef.current && chartRef.current) {
                    chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
                }
            };
            window.addEventListener('resize', handleResize);
            return () => {
                window.removeEventListener('resize', handleResize);
            };
        }
    }, [data]);

    const loadData = async () => {
        setLoading(true);
        try {
            const res = await usAPI.getSmartMoneyDetail(ticker);
            setData(res);
        } catch (error) {
            console.error('Failed to load detail:', error);
        } finally {
            setLoading(false);
        }
    };

    const renderChart = () => {
        if (!chartContainerRef.current || !data) return;

        // Clear existing chart
        if (chartRef.current) {
            chartRef.current.remove();
        }

        const chart = createChart(chartContainerRef.current, {
            width: chartContainerRef.current.clientWidth,
            height: 300,
            layout: {
                background: { color: '#1c1c1e' },
                textColor: '#d1d5db',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            crosshair: {
                mode: 1,
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                timeVisible: true,
            },
        });

        chartRef.current = chart;

        // Candlestick series (v5 API)
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e',
            downColor: '#ef4444',
            borderDownColor: '#ef4444',
            borderUpColor: '#22c55e',
            wickDownColor: '#ef4444',
            wickUpColor: '#22c55e',
        });

        const candleData: CandlestickData<Time>[] = data.chart.map(c => ({
            time: c.date as Time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        }));
        candleSeries.setData(candleData);

        // MA20 line (v5 API)
        const ma20Series = chart.addSeries(LineSeries, {
            color: '#3b82f6',
            lineWidth: 1,
        });
        const ma20Data: LineData<Time>[] = data.chart
            .filter(c => c.ma20 !== null)
            .map(c => ({
                time: c.date as Time,
                value: c.ma20!,
            }));
        ma20Series.setData(ma20Data);

        // MA50 line (v5 API)
        const ma50Series = chart.addSeries(LineSeries, {
            color: '#f59e0b',
            lineWidth: 1,
        });
        const ma50Data: LineData<Time>[] = data.chart
            .filter(c => c.ma50 !== null)
            .map(c => ({
                time: c.date as Time,
                value: c.ma50!,
            }));
        ma50Series.setData(ma50Data);

        chart.timeScale().fitContent();

        // Handle resize
    };

    const getChangeColor = (val: number) => {
        if (val > 0) return 'text-green-400';
        if (val < 0) return 'text-red-400';
        return 'text-gray-400';
    };

    const getScoreColor = (score: number) => {
        if (score >= 70) return 'text-green-400';
        if (score >= 50) return 'text-blue-400';
        if (score >= 30) return 'text-yellow-400';
        return 'text-red-400';
    };

    const getStageColor = (stage: string) => {
        if (stage.includes('Accumulation')) return 'bg-green-500/20 text-green-400';
        if (stage === 'Markup') return 'bg-blue-500/20 text-blue-400';
        if (stage.includes('Distribution')) return 'bg-red-500/20 text-red-400';
        return 'bg-gray-500/20 text-gray-400';
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                onClick={onClose}
            />

            {/* Modal */}
            <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl bg-[#1c1c1e] border border-white/10 shadow-2xl">
                {/* Header */}
                <div className="sticky top-0 z-10 bg-[#1c1c1e] border-b border-white/10 p-6">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                            <div>
                                <div className="flex items-center gap-3">
                                    <span className="text-3xl font-black text-white">{ticker}</span>
                                    {data?.smart_money?.grade && (
                                        <span className="px-2 py-1 rounded text-xs font-bold bg-blue-500/20 text-blue-400">
                                            {data.smart_money.grade.split(' ')[0]}
                                        </span>
                                    )}
                                </div>
                                <div className="text-sm text-gray-400 mt-1">{data?.name}</div>
                            </div>
                        </div>
                        <div className="flex items-center gap-4">
                            <div className="text-right">
                                <div className="text-2xl font-bold text-white">${data?.price?.toFixed(2)}</div>
                                <div className={`text-sm font-bold ${getChangeColor(data?.change_pct || 0)}`}>
                                    {(data?.change_pct || 0) >= 0 ? '+' : ''}{data?.change_pct?.toFixed(2)}%
                                </div>
                            </div>
                            <button
                                onClick={onClose}
                                className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                            >
                                <i className="fas fa-times text-gray-400 text-xl"></i>
                            </button>
                        </div>
                    </div>
                </div>

                {loading ? (
                    <div className="p-12 flex items-center justify-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
                    </div>
                ) : data ? (
                    <div className="p-6 space-y-6">
                        {/* Chart */}
                        <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-4">
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-bold text-white">6개월 차트</h3>
                                <div className="flex items-center gap-4 text-xs">
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-0.5 bg-blue-500"></span>
                                        <span className="text-gray-400">MA20</span>
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-0.5 bg-amber-500"></span>
                                        <span className="text-gray-400">MA50</span>
                                    </span>
                                </div>
                            </div>
                            <div ref={chartContainerRef} className="w-full" />
                        </div>

                        {/* Why Buy Section */}
                        {data.why_buy && data.why_buy.length > 0 && (
                            <div className="rounded-xl bg-gradient-to-br from-green-500/10 to-blue-500/10 border border-green-500/20 p-5">
                                <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                                    <i className="fas fa-lightbulb text-yellow-400"></i>
                                    왜 사야 하는가?
                                </h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {data.why_buy.map((reason, idx) => (
                                        <div
                                            key={idx}
                                            className="flex items-start gap-3 p-3 rounded-lg bg-white/5"
                                        >
                                            <div className="w-10 h-10 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0">
                                                <i className={`fas fa-${reason.icon} text-blue-400`}></i>
                                            </div>
                                            <div>
                                                <div className="font-bold text-white text-sm">{reason.title}</div>
                                                <div className="text-xs text-gray-400 mt-0.5">{reason.desc}</div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Smart Money / VCP Metrics */}
                        <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-5">
                            <h3 className="text-lg font-bold text-white mb-4">
                                {data.smart_money.strategy_type === 'VCP' ? 'VCP 분석 지표' : 'Smart Money 지표'}
                            </h3>

                            {data.smart_money.strategy_type === 'VCP' ? (
                                <>
                                    {/* VCP-specific metrics */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">VCP Score</div>
                                            <div className={`text-xl font-black ${getScoreColor(data.smart_money.swing_score || 0)}`}>
                                                {data.smart_money.swing_score?.toFixed(0) ?? 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Fund Score</div>
                                            <div className={`text-xl font-black ${getScoreColor(data.smart_money.fund_score || 0)}`}>
                                                {data.smart_money.fund_score?.toFixed(0) ?? 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">RS Rating</div>
                                            <div className={`text-xl font-black ${getScoreColor(data.smart_money.rs_score || 0)}`}>
                                                {data.smart_money.rs_score?.toFixed(0) ?? 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">EPS Growth</div>
                                            <div className={`text-xl font-black ${(data.smart_money.revenue_growth || 0) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                {data.smart_money.revenue_growth != null ? `${data.smart_money.revenue_growth.toFixed(0)}%` : 'N/A'}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Setup Phase</div>
                                            <div className="text-sm font-bold mt-1 text-white">
                                                {data.smart_money.sd_stage || 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Setup Type</div>
                                            <div className={`text-sm font-bold mt-1 px-2 py-0.5 rounded inline-block ${
                                                data.smart_money.setup_type === 'Breakout'
                                                    ? 'bg-green-500/20 text-green-400'
                                                    : 'bg-blue-500/20 text-blue-400'
                                            }`}>
                                                {data.smart_money.setup_type || 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Total Score</div>
                                            <div className="text-sm font-bold mt-1 text-white">
                                                {data.smart_money.composite_score?.toFixed(1) ?? 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Sector</div>
                                            <div className="text-sm font-bold mt-1 text-white">
                                                {data.sector || 'N/A'}
                                            </div>
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <>
                                    {/* Smart Money metrics (original) */}
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Composite</div>
                                            <div className={`text-xl font-black ${data.smart_money.composite_score != null ? getScoreColor(data.smart_money.composite_score) : 'text-gray-500'}`}>
                                                {data.smart_money.composite_score != null ? data.smart_money.composite_score.toFixed(1) : 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Swing</div>
                                            <div className={`text-xl font-black ${data.smart_money.swing_score != null ? getScoreColor(data.smart_money.swing_score) : 'text-gray-500'}`}>
                                                {data.smart_money.swing_score != null ? data.smart_money.swing_score.toFixed(1) : 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">Trend</div>
                                            <div className={`text-xl font-black ${data.smart_money.trend_score != null ? getScoreColor(data.smart_money.trend_score) : 'text-gray-500'}`}>
                                                {data.smart_money.trend_score != null ? data.smart_money.trend_score.toFixed(1) : 'N/A'}
                                            </div>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">RS vs SPY</div>
                                            <div className={`text-xl font-black ${data.smart_money.rs_vs_spy_20d != null ? getChangeColor(data.smart_money.rs_vs_spy_20d) : 'text-gray-500'}`}>
                                                {data.smart_money.rs_vs_spy_20d != null
                                                    ? `${data.smart_money.rs_vs_spy_20d >= 0 ? '+' : ''}${data.smart_money.rs_vs_spy_20d.toFixed(1)}%`
                                                    : 'N/A'}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">S/D Stage</div>
                                            <div className={`text-sm font-bold mt-1 px-2 py-0.5 rounded inline-block ${getStageColor(data.smart_money.sd_stage || '')}`}>
                                                {data.smart_money.sd_stage || 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">기관 보유 변화</div>
                                            <div className={`text-sm font-bold mt-1 ${data.smart_money.inst_pct != null ? getChangeColor(data.smart_money.inst_pct) : 'text-gray-500'}`}>
                                                {data.smart_money.inst_pct != null
                                                    ? `${data.smart_money.inst_pct >= 0 ? '+' : ''}${data.smart_money.inst_pct.toFixed(1)}%`
                                                    : 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">목표가 상승여력</div>
                                            <div className={`text-sm font-bold mt-1 ${data.smart_money.target_upside != null ? getChangeColor(data.smart_money.target_upside) : 'text-gray-500'}`}>
                                                {data.smart_money.target_upside != null
                                                    ? `+${data.smart_money.target_upside.toFixed(1)}%`
                                                    : 'N/A'}
                                            </div>
                                        </div>
                                        <div className="p-3 rounded-lg bg-white/5">
                                            <div className="text-[10px] text-gray-500 uppercase">실적 발표</div>
                                            <div className="text-sm font-bold mt-1 text-white">
                                                {data.smart_money.days_to_earnings
                                                    ? `${data.smart_money.days_to_earnings}일 후`
                                                    : data.smart_money.next_earnings || 'N/A'}
                                            </div>
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>

                        {/* Technical Indicators */}
                        <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-5">
                            <h3 className="text-lg font-bold text-white mb-4">기술적 지표</h3>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                <div className="p-3 rounded-lg bg-white/5">
                                    <div className="text-[10px] text-gray-500 uppercase">RSI (14)</div>
                                    <div className={`text-lg font-bold ${
                                        (data.technicals.rsi || 50) < 30 ? 'text-green-400' :
                                        (data.technicals.rsi || 50) > 70 ? 'text-red-400' : 'text-white'
                                    }`}>
                                        {data.technicals.rsi?.toFixed(1) || 'N/A'}
                                    </div>
                                    <div className="text-[10px] text-gray-500 mt-1">
                                        {(data.technicals.rsi || 50) < 30 ? '과매도' :
                                         (data.technicals.rsi || 50) > 70 ? '과매수' : '중립'}
                                    </div>
                                </div>
                                <div className="p-3 rounded-lg bg-white/5">
                                    <div className="text-[10px] text-gray-500 uppercase">MACD</div>
                                    <div className={`text-lg font-bold ${getChangeColor(data.technicals.macd_hist || 0)}`}>
                                        {data.technicals.macd_hist?.toFixed(3) || 'N/A'}
                                    </div>
                                    <div className="text-[10px] text-gray-500 mt-1">
                                        {(data.technicals.macd_hist || 0) > 0 ? '상승 신호' : '하락 신호'}
                                    </div>
                                </div>
                                <div className="p-3 rounded-lg bg-white/5">
                                    <div className="text-[10px] text-gray-500 uppercase">MA20</div>
                                    <div className="text-lg font-bold text-white">
                                        ${data.technicals.ma20?.toFixed(2) || 'N/A'}
                                    </div>
                                    <div className={`text-[10px] mt-1 ${
                                        data.price > (data.technicals.ma20 || 0) ? 'text-green-400' : 'text-red-400'
                                    }`}>
                                        {data.price > (data.technicals.ma20 || 0) ? '위' : '아래'}
                                    </div>
                                </div>
                                <div className="p-3 rounded-lg bg-white/5">
                                    <div className="text-[10px] text-gray-500 uppercase">MA50</div>
                                    <div className="text-lg font-bold text-white">
                                        ${data.technicals.ma50?.toFixed(2) || 'N/A'}
                                    </div>
                                    <div className={`text-[10px] mt-1 ${
                                        data.price > (data.technicals.ma50 || 0) ? 'text-green-400' : 'text-red-400'
                                    }`}>
                                        {data.price > (data.technicals.ma50 || 0) ? '위' : '아래'}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* AI Analysis */}
                        {data.ai_analysis?.summary && (() => {
                            // Try to parse JSON, fallback to plain text
                            let aiData: {
                                thesis?: string;
                                catalysts?: Array<{ point: string; evidence: string }>;
                                bear_cases?: Array<{ point: string; evidence: string }>;
                                data_conflicts?: string[];
                                key_metrics?: { pe?: number; growth?: number; rsi?: number; inst_pct?: number };
                                recommendation?: string;
                                confidence?: number;
                            } | null = null;

                            try {
                                // Remove markdown code block if present
                                let jsonStr = data.ai_analysis.summary;
                                if (jsonStr.includes('```json')) {
                                    jsonStr = jsonStr.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
                                } else if (jsonStr.includes('```')) {
                                    jsonStr = jsonStr.replace(/```\s*/g, '').trim();
                                }
                                aiData = JSON.parse(jsonStr);
                            } catch {
                                // Not JSON, will render as plain text
                            }

                            if (aiData && aiData.thesis) {
                                return (
                                    <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-5 space-y-5">
                                        {/* Header with Recommendation */}
                                        <div className="flex items-center justify-between">
                                            <h3 className="text-lg font-bold text-white flex items-center gap-2">
                                                <i className="fas fa-robot text-purple-400"></i>
                                                AI 투자 분석
                                            </h3>
                                            <div className="flex items-center gap-3">
                                                <span className={`px-3 py-1 rounded-full text-sm font-bold ${
                                                    aiData.recommendation === 'BUY' ? 'bg-green-500/20 text-green-400' :
                                                    aiData.recommendation === 'SELL' ? 'bg-red-500/20 text-red-400' :
                                                    'bg-yellow-500/20 text-yellow-400'
                                                }`}>
                                                    {aiData.recommendation}
                                                </span>
                                                <div className="flex items-center gap-1">
                                                    <span className="text-xs text-gray-500">신뢰도</span>
                                                    <span className="text-sm font-bold text-white">{aiData.confidence}%</span>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Thesis */}
                                        <div className="p-4 rounded-lg bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20">
                                            <div className="text-sm text-gray-300 leading-relaxed">{aiData.thesis}</div>
                                        </div>

                                        {/* Catalysts (Bull Case) */}
                                        {aiData.catalysts && aiData.catalysts.length > 0 && (
                                            <div>
                                                <h4 className="text-sm font-bold text-green-400 mb-3 flex items-center gap-2">
                                                    <i className="fas fa-arrow-trend-up"></i>
                                                    상승 요인 (Catalysts)
                                                </h4>
                                                <div className="space-y-2">
                                                    {aiData.catalysts.map((cat, idx) => (
                                                        <div key={idx} className="p-3 rounded-lg bg-green-500/5 border border-green-500/10">
                                                            <div className="font-medium text-white text-sm">{cat.point}</div>
                                                            <div className="text-xs text-gray-400 mt-1">{cat.evidence}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Bear Cases */}
                                        {aiData.bear_cases && aiData.bear_cases.length > 0 && (
                                            <div>
                                                <h4 className="text-sm font-bold text-red-400 mb-3 flex items-center gap-2">
                                                    <i className="fas fa-arrow-trend-down"></i>
                                                    리스크 요인 (Bear Case)
                                                </h4>
                                                <div className="space-y-2">
                                                    {aiData.bear_cases.map((bear, idx) => (
                                                        <div key={idx} className="p-3 rounded-lg bg-red-500/5 border border-red-500/10">
                                                            <div className="font-medium text-white text-sm">{bear.point}</div>
                                                            <div className="text-xs text-gray-400 mt-1">{bear.evidence}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Data Conflicts */}
                                        {aiData.data_conflicts && aiData.data_conflicts.length > 0 && (
                                            <div>
                                                <h4 className="text-sm font-bold text-yellow-400 mb-3 flex items-center gap-2">
                                                    <i className="fas fa-exclamation-triangle"></i>
                                                    데이터 충돌 주의
                                                </h4>
                                                <div className="space-y-2">
                                                    {aiData.data_conflicts.map((conflict, idx) => (
                                                        <div key={idx} className="p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/10">
                                                            <div className="text-xs text-gray-300">{conflict}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Key Metrics from AI */}
                                        {aiData.key_metrics && (
                                            <div className="grid grid-cols-4 gap-3 pt-3 border-t border-white/5">
                                                <div className="text-center">
                                                    <div className="text-[10px] text-gray-500 uppercase">P/E</div>
                                                    <div className="text-sm font-bold text-white">{aiData.key_metrics.pe?.toFixed(1) || 'N/A'}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-[10px] text-gray-500 uppercase">Growth</div>
                                                    <div className="text-sm font-bold text-green-400">{aiData.key_metrics.growth?.toFixed(1)}%</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-[10px] text-gray-500 uppercase">RSI</div>
                                                    <div className="text-sm font-bold text-white">{aiData.key_metrics.rsi?.toFixed(1)}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-[10px] text-gray-500 uppercase">기관 보유</div>
                                                    <div className="text-sm font-bold text-blue-400">{aiData.key_metrics.inst_pct?.toFixed(1)}%</div>
                                                </div>
                                            </div>
                                        )}

                                        {data.ai_analysis.generated_at && (
                                            <div className="text-[10px] text-gray-500 pt-2 border-t border-white/5">
                                                Generated: {data.ai_analysis.generated_at}
                                            </div>
                                        )}
                                    </div>
                                );
                            }

                            // Fallback: plain text
                            return (
                                <div className="rounded-xl bg-[#1c1c1e] border border-white/10 p-5">
                                    <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                                        <i className="fas fa-robot text-purple-400"></i>
                                        AI 분석
                                    </h3>
                                    <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                        {data.ai_analysis.summary}
                                    </div>
                                    {data.ai_analysis.generated_at && (
                                        <div className="text-[10px] text-gray-500 mt-3">
                                            Generated: {data.ai_analysis.generated_at}
                                        </div>
                                    )}
                                </div>
                            );
                        })()}
                    </div>
                ) : (
                    <div className="p-12 text-center text-gray-500">
                        데이터를 불러올 수 없습니다
                    </div>
                )}
            </div>
        </div>
    );
}
