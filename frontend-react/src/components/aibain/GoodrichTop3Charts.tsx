import { useState } from 'react';

type ChartPeriod = 'day' | 'week' | 'month';

interface GoodrichChartPick {
    rank?: number;
    symbol: string;
    name: string;
    score?: number;
}

interface GoodrichTop3ChartsProps {
    picks: GoodrichChartPick[];
}

const periods: Array<{ key: ChartPeriod; label: string }> = [
    { key: 'day', label: '일봉' },
    { key: 'week', label: '주봉' },
    { key: 'month', label: '월봉' },
];

function normalizeSymbol(symbol: string) {
    return String(symbol || '').replace(/\D/g, '').padStart(6, '0');
}

function chartUrl(symbol: string, period: ChartPeriod) {
    const cacheMinute = Math.floor(Date.now() / 60000);
    return `https://ssl.pstatic.net/imgfinance/chart/item/candle/${period}/${normalizeSymbol(symbol)}.png?t=${cacheMinute}`;
}

function financeUrl(symbol: string) {
    return `https://finance.naver.com/item/main.naver?code=${normalizeSymbol(symbol)}`;
}

export default function GoodrichTop3Charts({ picks }: GoodrichTop3ChartsProps) {
    const [period, setPeriod] = useState<ChartPeriod>('day');
    const [failedSymbols, setFailedSymbols] = useState<Record<string, boolean>>({});
    const top3 = picks.slice(0, 3).filter((pick) => normalizeSymbol(pick.symbol) !== '000000');

    if (top3.length === 0) return null;

    return (
        <section className="rounded-2xl border border-emerald-400/15 bg-[#10161a] p-4 sm:p-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.2em] text-emerald-300">Verified price charts</div>
                    <h2 className="mt-1 text-lg font-black text-white">TOP 3 종목 차트</h2>
                    <p className="mt-1 text-xs text-slate-500">실제 종목코드 기준 네이버 금융 캔들 차트</p>
                </div>
                <div className="inline-flex overflow-hidden rounded-xl border border-white/10 bg-black/30" aria-label="차트 기간">
                    {periods.map((item) => (
                        <button
                            key={item.key}
                            type="button"
                            aria-pressed={period === item.key}
                            onClick={() => setPeriod(item.key)}
                            className={`min-h-10 px-4 text-xs font-black transition-colors ${
                                period === item.key
                                    ? 'bg-emerald-400 text-slate-950'
                                    : 'text-slate-500 hover:bg-white/5 hover:text-slate-200'
                            }`}
                        >
                            {item.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
                {top3.map((pick, index) => {
                    const symbol = normalizeSymbol(pick.symbol);
                    const failed = failedSymbols[`${symbol}-${period}`];
                    return (
                        <article key={symbol} className="overflow-hidden rounded-2xl border border-white/[0.08] bg-black/25">
                            <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-3">
                                <div className="min-w-0">
                                    <div className="text-[10px] font-black text-emerald-300">TOP {pick.rank ?? index + 1}</div>
                                    <h3 className="truncate text-base font-black text-white">{pick.name}</h3>
                                    <div className="font-mono text-[11px] text-slate-500">{symbol}</div>
                                </div>
                                {pick.score != null && (
                                    <span className="rounded-lg bg-emerald-400/10 px-2.5 py-1.5 text-xs font-black text-emerald-200">
                                        {pick.score.toFixed(1)}
                                    </span>
                                )}
                            </div>

                            <div className="p-3">
                                {failed ? (
                                    <div className="grid min-h-48 place-items-center rounded-xl border border-rose-400/20 bg-rose-400/[0.05] px-4 text-center text-xs font-bold text-rose-200">
                                        차트 이미지를 불러오지 못했습니다.
                                    </div>
                                ) : (
                                    <a
                                        href={financeUrl(symbol)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="block overflow-hidden rounded-xl bg-white"
                                        title={`${pick.name} 네이버 금융 열기`}
                                    >
                                        <img
                                            src={chartUrl(symbol, period)}
                                            alt={`${pick.name} ${period} 캔들 차트`}
                                            loading="lazy"
                                            className="block min-h-48 w-full object-contain"
                                            onError={() => setFailedSymbols((current) => ({ ...current, [`${symbol}-${period}`]: true }))}
                                        />
                                    </a>
                                )}
                            </div>
                        </article>
                    );
                })}
            </div>
        </section>
    );
}
