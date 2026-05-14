/**
 * Top3 차트 패널 — 네이버 금융 차트 이미지 기반.
 *
 * 이전엔 TradingView Lightweight Charts + 백엔드 /price-chart API (150MB
 * daily_prices.csv) 를 사용했지만 cold cache 시 fetch timeout 으로 차트가
 * 표시 안 되는 문제 반복. 네이버 금융의 공개 차트 이미지로 전환하면:
 *   - 백엔드 의존성 제거 (즉시 응답)
 *   - 네이버 CDN 인프라 활용 (빠름)
 *   - 일/주/월봉 탭 즉시 전환
 *   - 코드 단순 (Lightweight Charts SDK 제거)
 *
 * 컴포넌트 이름은 import 호환 위해 유지.
 */
import { useState } from 'react';
import { type MiroFishWorkflowAnalysisResult } from '@/lib/mirofishApi';

type ChartPeriod = 'day' | 'week' | 'month';

interface Top3TradingViewChartsProps {
    items: MiroFishWorkflowAnalysisResult[];
}

function workflowSymbol(item: MiroFishWorkflowAnalysisResult): string {
    return String(item.symbol || item.candidate?.symbol || '').trim();
}

function workflowName(item: MiroFishWorkflowAnalysisResult): string {
    return String(item.target || item.candidate?.display_name || item.symbol || 'TOP candidate');
}

function formatScore(value?: number): string {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(1) : '--';
}

function verdictTone(action?: string): string {
    const a = String(action || '').toUpperCase();
    if (a.includes('BUY')) return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (a.includes('SELL')) return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
}

/**
 * 네이버 금융 차트 이미지 URL.
 *
 * 패턴:
 *   - 일봉 캔들: https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{code}.png
 *   - 주봉 캔들: https://ssl.pstatic.net/imgfinance/chart/item/candle/week/{code}.png
 *   - 월봉 캔들: https://ssl.pstatic.net/imgfinance/chart/item/candle/month/{code}.png
 *
 * 6자리 KR ticker 기준. US 등 타 시장은 별도 처리 필요 (현재 미지원).
 * Cache-busting 을 위해 분 단위 timestamp 를 query 로 부착.
 */
function naverChartUrl(symbol: string, period: ChartPeriod, cacheBust: number): string {
    const code = String(symbol || '').replace(/\D/g, '').padStart(6, '0');
    return `https://ssl.pstatic.net/imgfinance/chart/item/candle/${period}/${code}.png?t=${cacheBust}`;
}

/** 네이버 종목 상세 페이지 — 차트 클릭 시 새 탭 */
function naverFinanceUrl(symbol: string): string {
    const code = String(symbol || '').replace(/\D/g, '').padStart(6, '0');
    return `https://finance.naver.com/item/main.naver?code=${code}`;
}

function NaverChartImage({ symbol, period }: { symbol: string; period: ChartPeriod }) {
    const [imgError, setImgError] = useState(false);
    // 1분 단위 cache-bust — 동일 1분 안엔 같은 URL 사용
    const cacheBust = Math.floor(Date.now() / 60000);
    const url = naverChartUrl(symbol, period, cacheBust);

    if (imgError) {
        return (
            <div className="flex h-[220px] items-center justify-center rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 text-center text-xs font-bold text-rose-100">
                네이버 차트 로딩 실패 — 종목 코드 확인
            </div>
        );
    }

    return (
        <a
            href={naverFinanceUrl(symbol)}
            target="_blank"
            rel="noopener noreferrer"
            className="block overflow-hidden rounded-lg border border-amber-500/15 bg-black/40 transition-transform hover:scale-[1.01]"
            title="네이버 금융 종목 페이지 새 탭 열기"
        >
            <img
                src={url}
                alt={`${symbol} ${period} chart`}
                loading="lazy"
                className="block h-auto w-full"
                style={{ minHeight: 180 }}
                onError={() => setImgError(true)}
            />
        </a>
    );
}

export default function Top3TradingViewCharts({ items }: Top3TradingViewChartsProps) {
    const topItems = items.slice(0, 3).filter((i) => workflowSymbol(i));
    const [period, setPeriod] = useState<ChartPeriod>('day');

    if (topItems.length === 0) return null;

    const periods: { key: ChartPeriod; label: string }[] = [
        { key: 'day', label: '일봉' },
        { key: 'week', label: '주봉' },
        { key: 'month', label: '월봉' },
    ];

    return (
        <div className="mt-4 rounded-lg border border-amber-500/15 bg-black/60 p-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-neutral-500">
                        NAVER CHARTS
                    </div>
                    <div className="mt-1 text-sm font-black text-neutral-100">
                        TOP3 차트 확인
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <div className="inline-flex overflow-hidden rounded-md border border-white/8 bg-black/40">
                        {periods.map((p) => (
                            <button
                                key={p.key}
                                type="button"
                                onClick={() => setPeriod(p.key)}
                                className={`min-h-[28px] px-2.5 py-1 text-[10px] font-black transition-colors ${
                                    period === p.key
                                        ? 'bg-white/[0.06] text-neutral-200'
                                        : 'text-neutral-600 hover:bg-white/[0.03] hover:text-neutral-300'
                                }`}
                            >
                                {p.label}
                            </button>
                        ))}
                    </div>
                    <div className="text-[10px] font-medium text-neutral-600 hidden sm:block">
                        source: Naver Finance
                    </div>
                </div>
            </div>

            <div className="mt-3 grid gap-3 xl:grid-cols-3">
                {topItems.map((item, index) => {
                    const symbol = workflowSymbol(item);
                    const action = item.verdict?.action || 'HOLD';
                    const confidence = item.verdict?.confidence_pct || 0;
                    return (
                        <article
                            key={`${symbol}-${item.run_id || index}`}
                            className="overflow-hidden rounded-lg border border-white/8 bg-black/40"
                        >
                            <div className="flex items-start justify-between gap-3 border-b border-white/8 p-3">
                                <div className="min-w-0">
                                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-neutral-500">
                                        TOP {index + 1} chart target
                                    </div>
                                    <div className="mt-1 truncate text-base font-black text-neutral-100">
                                        {workflowName(item)}
                                    </div>
                                    <div className="mt-1 font-mono text-[11px] font-bold text-neutral-500">
                                        {symbol} · {item.market || item.candidate?.market || 'KR'} · score {formatScore(item.final_score)}
                                    </div>
                                </div>
                                <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-black ${verdictTone(action)}`}>
                                    {action} {confidence}%
                                </span>
                            </div>

                            <div className="p-3">
                                <NaverChartImage symbol={symbol} period={period} />
                                <div className="mt-2 text-center text-[10px] font-bold text-neutral-600">
                                    클릭 → 네이버 금융 상세 페이지
                                </div>
                            </div>
                        </article>
                    );
                })}
            </div>
        </div>
    );
}
