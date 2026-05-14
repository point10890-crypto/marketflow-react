/**
 * Phase G: 전체 MCP 스캔 + 워크플로우 outcome 통계 KPI 카드.
 *
 * 상단: total_signals / evaluated / hit_rate / IC 4개 KPI.
 * 본문: by_market 그리드, by_strategy_tag 상위 5개, top_performers 5종목.
 *
 * 단일 GET /api/admin/mirofish/graphrag/scan-history-performance.
 * 60초 폴링 (집계는 디스크 IO 가 비싸므로 30초 backend 캐시 + 60초 UI 폴링).
 */
import { useEffect, useMemo, useState } from 'react';
import { MiroFishScanPerformanceResponse, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 60_000;
const WINDOW_OPTIONS = [30, 60, 90] as const;

function formatPct(value: number | null | undefined, opts: { withSign?: boolean } = {}): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    const sign = opts.withSign && value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(1)}%`;
}

function formatRate(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return `${(value * 100).toFixed(1)}%`;
}

function formatIc(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return value.toFixed(3);
}

function rateTone(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'text-neutral-400';
    if (value >= 0.6) return 'text-emerald-300';
    if (value <= 0.3) return 'text-rose-300';
    return 'text-amber-300';
}

function returnTone(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'text-neutral-400';
    if (value >= 5) return 'text-emerald-300';
    if (value <= -3) return 'text-rose-300';
    return 'text-amber-300';
}

interface KpiCardProps {
    label: string;
    value: string;
    sub?: string;
    tone?: string;
}

function KpiCard({ label, value, sub, tone }: KpiCardProps) {
    return (
        <div className="rounded-lg border border-white/10 bg-black/30 p-2.5 sm:p-3">
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500 sm:tracking-[0.18em]">
                {label}
            </div>
            <div className={`mt-0.5 text-lg font-black sm:text-xl ${tone || 'text-white'}`}>{value}</div>
            {sub && <div className="text-[10px] font-bold text-neutral-400">{sub}</div>}
        </div>
    );
}

export default function ScanPerformanceCard() {
    const [data, setData] = useState<MiroFishScanPerformanceResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [windowDays, setWindowDays] = useState<number>(60);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const snap = await mirofishApi.graphrag.getScanPerformance(windowDays);
                if (cancelled) return;
                setData(snap);
                setError(null);
            } catch (err) {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : 'load failed');
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        load();
        const id = setInterval(load, POLL_INTERVAL_MS);
        return () => {
            cancelled = true;
            clearInterval(id);
        };
    }, [windowDays]);

    const topTags = useMemo(() => {
        if (!data?.by_strategy_tag) return [];
        return Object.entries(data.by_strategy_tag)
            .map(([tag, stat]) => ({ tag, ...stat }))
            .sort((a, b) => (b.hit_rate || 0) - (a.hit_rate || 0))
            .slice(0, 5);
    }, [data]);

    const marketEntries = useMemo(() => {
        if (!data?.by_market) return [];
        return Object.entries(data.by_market)
            .map(([mkt, stat]) => ({ mkt, ...stat }))
            .sort((a, b) => b.n - a.n);
    }, [data]);

    const topPerformers = data?.top_performers || [];

    return (
        <section className="rounded-xl border border-amber-500/15 bg-black/60 p-3 sm:p-4">
            <header className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-chart-line text-amber-400" />
                        <span className="truncate">Scan Performance</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">MCP 추천 통계 (KPI / IC)</h3>
                </div>
                <div className="flex shrink-0 items-center gap-1 text-[10px] font-bold">
                    {WINDOW_OPTIONS.map((d) => (
                        <button
                            key={d}
                            type="button"
                            onClick={() => setWindowDays(d)}
                            className={`rounded-full border px-2 py-0.5 transition ${
                                d === windowDays
                                    ? 'border-amber-400/40 bg-amber-400/15 text-amber-200'
                                    : 'border-white/10 bg-white/5 text-neutral-400 hover:bg-white/10'
                            }`}
                        >
                            {d}D
                        </button>
                    ))}
                </div>
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}

            {/* KPI 4종 */}
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <KpiCard
                    label="추천 신호"
                    value={loading && !data ? '--' : String(data?.total_signals ?? 0)}
                    sub={`평가 ${data?.evaluated ?? 0} · 대기 ${data?.pending ?? 0}`}
                />
                <KpiCard
                    label="Hit rate"
                    value={loading && !data ? '--' : formatRate(data?.hit_rate ?? null)}
                    sub={`hit ${data?.hit_count ?? 0} / miss ${data?.miss_count ?? 0}`}
                    tone={rateTone(data?.hit_rate)}
                />
                <KpiCard
                    label="평균 수익률"
                    value={loading && !data ? '--' : formatPct(data?.avg_return_pct ?? null, { withSign: true })}
                    sub={`window ${data?.window_days ?? windowDays}d`}
                    tone={returnTone(data?.avg_return_pct)}
                />
                <KpiCard
                    label="IC (α vs return)"
                    value={loading && !data ? '--' : formatIc(data?.ic_signal_to_return ?? null)}
                    sub="Pearson, 표본 ≥3"
                    tone={
                        data?.ic_signal_to_return && data.ic_signal_to_return > 0.05
                            ? 'text-emerald-300'
                            : data?.ic_signal_to_return && data.ic_signal_to_return < -0.05
                                ? 'text-rose-300'
                                : 'text-amber-300'
                    }
                />
            </div>

            {/* 시장별 + 태그별 */}
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-white/10 bg-black/30 p-2.5">
                    <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">시장별</div>
                    {marketEntries.length === 0 ? (
                        <div className="mt-2 text-[11px] text-neutral-500">데이터 없음</div>
                    ) : (
                        <ul className="mt-1.5 space-y-1">
                            {marketEntries.slice(0, 4).map(({ mkt, n, hit_rate, avg_return_pct }) => (
                                <li key={mkt} className="flex items-center justify-between text-[11px] font-bold">
                                    <span className="text-neutral-300">{mkt}</span>
                                    <span className="flex items-center gap-2">
                                        <span className={rateTone(hit_rate)}>{formatRate(hit_rate)}</span>
                                        <span className={returnTone(avg_return_pct)}>
                                            {formatPct(avg_return_pct, { withSign: true })}
                                        </span>
                                        <span className="text-neutral-500">n={n}</span>
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2.5">
                    <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">전략 태그 Top 5</div>
                    {topTags.length === 0 ? (
                        <div className="mt-2 text-[11px] text-neutral-500">표본 부족 (n &lt; 2)</div>
                    ) : (
                        <ul className="mt-1.5 space-y-1">
                            {topTags.map(({ tag, n, hit_rate, avg_return_pct }) => (
                                <li key={tag} className="flex items-center justify-between text-[11px] font-bold">
                                    <span className="truncate text-neutral-300">{tag}</span>
                                    <span className="flex items-center gap-2">
                                        <span className={rateTone(hit_rate)}>{formatRate(hit_rate)}</span>
                                        <span className={returnTone(avg_return_pct)}>
                                            {formatPct(avg_return_pct, { withSign: true })}
                                        </span>
                                        <span className="text-neutral-500">n={n}</span>
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </div>

            {/* Top performers */}
            <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-2.5">
                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">Top performers</div>
                {topPerformers.length === 0 ? (
                    <div className="mt-2 text-[11px] text-neutral-500">평가 완료 종목 없음</div>
                ) : (
                    <ul className="mt-1.5 space-y-1">
                        {topPerformers.map((p) => (
                            <li key={p.symbol} className="flex items-center justify-between text-[11px] font-bold">
                                <span className="truncate text-neutral-200">
                                    {p.display_name}
                                    <span className="ml-1 text-neutral-500">({p.symbol})</span>
                                </span>
                                <span className="flex items-center gap-2">
                                    <span className={rateTone(p.hit_rate)}>{formatRate(p.hit_rate)}</span>
                                    <span className={returnTone(p.avg_return_pct)}>
                                        {formatPct(p.avg_return_pct, { withSign: true })}
                                    </span>
                                    <span className="text-neutral-500">n={p.n}</span>
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
            </div>

            {data?.generated_at && (
                <div className="mt-2 text-right text-[10px] font-bold text-neutral-500">
                    asof {data.generated_at.slice(0, 19).replace('T', ' ')} · scanned {data.scanner_runs_scanned ?? 0}
                    runs / {data.workflow_count_scanned ?? 0} workflows
                </div>
            )}
        </section>
    );
}
