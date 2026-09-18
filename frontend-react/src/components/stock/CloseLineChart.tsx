import { useEffect, useRef } from 'react';
import { createChart, IChartApi, LineSeries, LineData, Time } from 'lightweight-charts';

export interface ClosePoint { date: string; close: number }

/**
 * 종가 라인 차트 (lightweight-charts v5) — StockDetailModal 의 차트 패턴을 라인 하나로 줄인 것.
 * 높이 고정(안정 치수). 데이터가 비면 캔버스를 만들지 않는다.
 */
export default function CloseLineChart({ points, height = 240 }: { points: ClosePoint[]; height?: number }) {
    const ref = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        const el = ref.current;
        if (!el || points.length === 0) return;
        chartRef.current?.remove();
        const chart = createChart(el, {
            width: el.clientWidth,
            height,
            layout: { background: { color: '#0f1117' }, textColor: '#9ca3af' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
            crosshair: { mode: 1 },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
        });
        chartRef.current = chart;
        const up = points[points.length - 1].close >= points[0].close;
        const series = chart.addSeries(LineSeries, { color: up ? '#f87171' : '#60a5fa', lineWidth: 2 });
        const data: LineData<Time>[] = points.map((p) => ({ time: p.date as Time, value: p.close }));
        series.setData(data);
        chart.timeScale().fitContent();

        const onResize = () => { if (ref.current) chart.applyOptions({ width: ref.current.clientWidth }); };
        window.addEventListener('resize', onResize);
        return () => {
            window.removeEventListener('resize', onResize);
            chart.remove();
            chartRef.current = null;
        };
    }, [points, height]);

    if (points.length === 0) {
        return (
            <div style={{ height }} className="grid place-items-center text-[12px] text-gray-600">
                가격 데이터 없음
            </div>
        );
    }
    return <div ref={ref} style={{ height }} className="w-full" data-testid="close-line-chart" />;
}
