import { useEffect, useRef } from 'react';
import {
    createChart, IChartApi,
    CandlestickSeries, LineSeries, HistogramSeries,
    CandlestickData, LineData, HistogramData, Time,
    createSeriesMarkers,
} from 'lightweight-charts';

export interface ChartDataPoint {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export interface PatternPoint {
    index: number;
    date: string;
    price: number;
    type: string; // HIGH or LOW
}

export interface PatternOverlay {
    points: PatternPoint[];
    pattern_class: string;
    wave_type: string;
    wave_label: string;
    neckline_price: number;
    confidence: number;
    completion_pct: number;
    neckline_distance_pct: number;
    bullish_bias: number;
    volume_confirmed: boolean;
}

interface PatternChartProps {
    chartData: ChartDataPoint[];
    patterns?: PatternOverlay[];
    turningPoints?: PatternPoint[];
    height?: number;
    selectedPatternIdx?: number;
}

export default function PatternChart({
    chartData,
    patterns = [],
    turningPoints = [],
    height = 400,
    selectedPatternIdx,
}: PatternChartProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        if (!containerRef.current || chartData.length === 0) return;
        renderChart();
        const handleResize = () => {
            if (containerRef.current && chartRef.current) {
                chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);
        return () => {
            window.removeEventListener('resize', handleResize);
            if (chartRef.current) {
                chartRef.current.remove();
                chartRef.current = null;
            }
        };
    }, [chartData, patterns, selectedPatternIdx]);

    const renderChart = () => {
        if (!containerRef.current) return;
        if (chartRef.current) {
            chartRef.current.remove();
        }

        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height,
            layout: {
                background: { color: '#0a0a0b' },
                textColor: '#9ca3af',
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.03)' },
                horzLines: { color: 'rgba(255,255,255,0.03)' },
            },
            crosshair: { mode: 1 },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
        });
        chartRef.current = chart;

        // ── Candlestick ──
        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#22c55e',
            downColor: '#ef4444',
            borderDownColor: '#ef4444',
            borderUpColor: '#22c55e',
            wickDownColor: '#ef4444',
            wickUpColor: '#22c55e',
        });

        const candleData: CandlestickData<Time>[] = chartData.map(c => ({
            time: c.date as Time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        }));
        candleSeries.setData(candleData);

        // ── Volume histogram ──
        const volumeSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
        });
        const volData: HistogramData<Time>[] = chartData.map(c => ({
            time: c.date as Time,
            value: c.volume,
            color: c.close >= c.open ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)',
        }));
        volumeSeries.setData(volData);

        // ── Turning point markers (v5 API) ──
        const allPoints = turningPoints.length > 0 ? turningPoints : [];
        if (allPoints.length > 0) {
            const markers = allPoints.map(tp => ({
                time: tp.date as Time,
                position: tp.type === 'HIGH' ? 'aboveBar' as const : 'belowBar' as const,
                color: tp.type === 'HIGH' ? '#f59e0b' : '#3b82f6',
                shape: tp.type === 'HIGH' ? 'arrowDown' as const : 'arrowUp' as const,
                text: tp.type === 'HIGH' ? 'H' : 'L',
            }));
            createSeriesMarkers(candleSeries, markers);
        }

        // ── Selected pattern neckline ──
        const pat = selectedPatternIdx !== undefined ? patterns[selectedPatternIdx] : patterns[0];
        if (pat) {
            // Neckline horizontal line
            const necklineData: LineData<Time>[] = [
                { time: pat.points[0].date as Time, value: pat.neckline_price },
                { time: pat.points[4].date as Time, value: pat.neckline_price },
            ];
            const necklineSeries = chart.addSeries(LineSeries, {
                color: '#f97316',
                lineWidth: 2,
                lineStyle: 2, // dashed
                crosshairMarkerVisible: false,
            });
            necklineSeries.setData(necklineData);

            // P1-P5 connecting line
            const patternLine: LineData<Time>[] = pat.points.map(p => ({
                time: p.date as Time,
                value: p.price,
            }));
            const patLineSeries = chart.addSeries(LineSeries, {
                color: pat.pattern_class === 'W' ? '#22d3ee' : '#f472b6',
                lineWidth: 2,
                crosshairMarkerVisible: false,
            });
            patLineSeries.setData(patternLine);
        }

        chart.timeScale().fitContent();
    };

    return (
        <div ref={containerRef} className="w-full rounded-xl overflow-hidden border border-white/5" />
    );
}
