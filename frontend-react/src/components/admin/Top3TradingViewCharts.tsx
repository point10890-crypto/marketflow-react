import { useEffect, useMemo, useRef, useState } from 'react';
import {
    createChart,
    CandlestickSeries,
    HistogramSeries,
    type CandlestickData,
    type HistogramData,
    type IChartApi,
    type Time,
} from 'lightweight-charts';

import {
    type MiroFishPriceChartPoint,
    type MiroFishPriceChartResponse,
    type MiroFishWorkflowAnalysisResult,
    mirofishApi,
} from '@/lib/mirofishApi';

type ChartLoadState = {
    status: 'loading' | 'ready' | 'error';
    data?: MiroFishPriceChartResponse;
    error?: string;
};

interface Top3TradingViewChartsProps {
    items: MiroFishWorkflowAnalysisResult[];
}

function workflowSymbol(item: MiroFishWorkflowAnalysisResult): string {
    return String(item.symbol || item.candidate?.symbol || '').trim();
}

function workflowName(item: MiroFishWorkflowAnalysisResult): string {
    return String(item.target || item.candidate?.display_name || item.symbol || 'TOP candidate');
}

function uniqueChartPoints(points: MiroFishPriceChartPoint[]): MiroFishPriceChartPoint[] {
    const byDate = new Map<string, MiroFishPriceChartPoint>();
    points
        .filter((point) => point?.date && Number.isFinite(Number(point.close)))
        .sort((a, b) => String(a.date).localeCompare(String(b.date)))
        .forEach((point) => byDate.set(String(point.date), point));
    return Array.from(byDate.values());
}

function formatScore(value?: number): string {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue.toFixed(1) : '--';
}

function formatPrice(value?: number): string {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue.toLocaleString('ko-KR') : '--';
}

function verdictTone(action?: string): string {
    const normalized = String(action || '').toUpperCase();
    if (normalized.includes('BUY')) return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (normalized.includes('SELL')) return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
}

function MiniTradingViewChart({ points, height = 220 }: { points: MiroFishPriceChartPoint[]; height?: number }) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const chartPoints = useMemo(() => uniqueChartPoints(points), [points]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container || chartPoints.length === 0) return;

        if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) {
            return;
        }

        if (chartRef.current) {
            chartRef.current.remove();
            chartRef.current = null;
        }

        const width = Math.max(container.clientWidth || 360, 280);
        let chart: IChartApi | null = null;
        try {
            chart = createChart(container, {
                width,
                height,
                layout: {
                    background: { color: '#0f172a' },
                    textColor: '#cbd5e1',
                },
                grid: {
                    vertLines: { color: 'rgba(148,163,184,0.12)' },
                    horzLines: { color: 'rgba(148,163,184,0.12)' },
                },
                crosshair: { mode: 1 },
                rightPriceScale: { borderColor: 'rgba(148,163,184,0.25)' },
                timeScale: {
                    borderColor: 'rgba(148,163,184,0.25)',
                    timeVisible: false,
                    secondsVisible: false,
                },
                handleScroll: {
                    vertTouchDrag: false,
                    horzTouchDrag: true,
                    mouseWheel: true,
                    pressedMouseMove: true,
                },
                handleScale: {
                    pinch: true,
                    axisPressedMouseMove: true,
                    mouseWheel: true,
                },
            });
        } catch (error) {
            console.warn('[MiroFish] TradingView chart render skipped', error);
            return;
        }

        chartRef.current = chart;
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#ef4444',
            downColor: '#3b82f6',
            borderUpColor: '#ef4444',
            borderDownColor: '#3b82f6',
            wickUpColor: '#f87171',
            wickDownColor: '#60a5fa',
        });
        const candleData: CandlestickData<Time>[] = chartPoints.map((point) => ({
            time: point.date as Time,
            open: Number(point.open),
            high: Number(point.high),
            low: Number(point.low),
            close: Number(point.close),
        }));
        candleSeries.setData(candleData);

        const volumeSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });
        const volumeData: HistogramData<Time>[] = chartPoints.map((point) => ({
            time: point.date as Time,
            value: Number(point.volume || 0),
            color: Number(point.close) >= Number(point.open)
                ? 'rgba(239,68,68,0.24)'
                : 'rgba(59,130,246,0.24)',
        }));
        volumeSeries.setData(volumeData);
        chart.timeScale().fitContent();

        const handleResize = () => {
            if (!containerRef.current || !chartRef.current) return;
            chartRef.current.applyOptions({
                width: Math.max(containerRef.current.clientWidth || 360, 280),
                height,
            });
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chartRef.current?.remove();
            chartRef.current = null;
        };
    }, [chartPoints, height]);

    if (chartPoints.length === 0) {
        return (
            <div className="flex h-[220px] items-center justify-center rounded-lg border border-dashed border-white/15 bg-slate-950/55 text-xs font-bold text-slate-500">
                price history waiting
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            data-no-swipe
            data-chart-points={chartPoints.length}
            className="h-[220px] w-full overflow-hidden rounded-lg border border-cyan-300/15 bg-slate-950"
            style={{ height, touchAction: 'none' }}
        />
    );
}

export default function Top3TradingViewCharts({ items }: Top3TradingViewChartsProps) {
    const topItems = useMemo(() => items.slice(0, 3).filter((item) => workflowSymbol(item)), [items]);
    const symbolsKey = topItems.map(workflowSymbol).join('|');
    const [charts, setCharts] = useState<Record<string, ChartLoadState>>({});

    useEffect(() => {
        if (!symbolsKey) {
            setCharts({});
            return;
        }
        let cancelled = false;
        const symbols = symbolsKey.split('|').filter(Boolean);
        setCharts((previous) => {
            const next: Record<string, ChartLoadState> = {};
            symbols.forEach((symbol) => {
                next[symbol] = previous[symbol]?.status === 'ready'
                    ? previous[symbol]
                    : { status: 'loading' };
            });
            return next;
        });

        Promise.all(symbols.map(async (symbol) => {
            try {
                const data = await mirofishApi.getPriceChart(symbol, 120);
                return [symbol, { status: 'ready', data } satisfies ChartLoadState] as const;
            } catch (error) {
                return [symbol, {
                    status: 'error',
                    error: error instanceof Error ? error.message : String(error),
                } satisfies ChartLoadState] as const;
            }
        })).then((results) => {
            if (cancelled) return;
            setCharts((previous) => {
                const next = { ...previous };
                results.forEach(([symbol, state]) => {
                    next[symbol] = state;
                });
                return next;
            });
        });

        return () => {
            cancelled = true;
        };
    }, [symbolsKey]);

    if (topItems.length === 0) return null;

    return (
        <div className="mt-4 rounded-lg border border-cyan-300/15 bg-slate-950/65 p-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-cyan-200/70">
                        TradingView charts
                    </div>
                    <div className="mt-1 text-sm font-black text-white">
                        TOP3 차트 확인
                    </div>
                </div>
                <div className="text-[11px] font-bold text-slate-500">
                    source: daily_prices.csv / TradingView Lightweight
                </div>
            </div>

            <div className="mt-3 grid gap-3 xl:grid-cols-3">
                {topItems.map((item, index) => {
                    const symbol = workflowSymbol(item);
                    const chartState = charts[symbol] || { status: 'loading' };
                    const chart = chartState.data;
                    const latest = chart?.latest || chart?.chart?.[chart.chart.length - 1];
                    const action = item.verdict?.action || 'HOLD';
                    const confidence = item.verdict?.confidence_pct || 0;
                    return (
                        <article
                            key={`${symbol}-${item.run_id || index}`}
                            className="overflow-hidden rounded-lg border border-white/10 bg-black/25 shadow-[0_18px_50px_rgba(15,23,42,0.28)]"
                        >
                            <div className="flex items-start justify-between gap-3 border-b border-white/10 p-3">
                                <div className="min-w-0">
                                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-200/65">
                                        TOP {index + 1} chart target
                                    </div>
                                    <div className="mt-1 truncate text-base font-black text-white">
                                        {workflowName(item)}
                                    </div>
                                    <div className="mt-1 font-mono text-[11px] font-bold text-slate-500">
                                        {symbol} · {item.market || item.candidate?.market || 'KR'} · score {formatScore(item.final_score)}
                                    </div>
                                </div>
                                <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-black ${verdictTone(action)}`}>
                                    {action} {confidence}%
                                </span>
                            </div>

                            <div className="p-3">
                                <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-bold">
                                    <span className="rounded-full border border-white/10 bg-white/8 px-2 py-1 text-slate-300">
                                        close {formatPrice(latest?.close)}
                                    </span>
                                    <span className="rounded-full border border-white/10 bg-white/8 px-2 py-1 text-slate-300">
                                        candles {chart?.count ?? '--'}
                                    </span>
                                    <span className="rounded-full border border-white/10 bg-white/8 px-2 py-1 text-slate-300">
                                        {latest?.date || '--'}
                                    </span>
                                </div>

                                {chartState.status === 'loading' && (
                                    <div className="flex h-[220px] items-center justify-center rounded-lg border border-white/10 bg-slate-950/70 text-xs font-black text-cyan-200">
                                        loading chart...
                                    </div>
                                )}
                                {chartState.status === 'error' && (
                                    <div className="flex h-[220px] items-center justify-center rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 text-center text-xs font-bold text-rose-100">
                                        {chartState.error || 'chart request failed'}
                                    </div>
                                )}
                                {chartState.status === 'ready' && (
                                    <MiniTradingViewChart points={chart?.chart || []} />
                                )}
                            </div>
                        </article>
                    );
                })}
            </div>
        </div>
    );
}
