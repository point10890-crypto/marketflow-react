/**
 * Recent Outcomes Board — 우측 하단 카드.
 *
 * 지난 N일(기본 30) 추천 종목의 forward outcomes 집계.
 *
 * KPI 카드 (Hit rate / Avg R / False positive / Sample size)
 * + 종목별 테이블 (entry_date / 5d return / status / hit)
 *
 * 단일 GET /api/admin/mirofish/outcomes/board 호출.
 * 60초 폴링 (outcomes 는 일일 1회 refresh 라 빈번한 폴링 불필요).
 */
import { useEffect, useMemo, useState } from 'react';
import { MiroFishBoardItem, MiroFishOutcomesBoard, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 60_000;
const WINDOW_OPTIONS = [7, 30, 60] as const;

function formatPct(value?: number | null, opts: { withSign?: boolean } = {}): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    const sign = opts.withSign && value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(1)}%`;
}

function formatDate(iso?: string | null): string {
    if (!iso) return '--';
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!m) return iso;
    return `${m[2]}-${m[3]}`;
}

function statusBadge(item: MiroFishBoardItem): { label: string; tone: string } {
    if (item.status === 'evaluated' || item.status === 'partial') {
        if (item.hit === true) return { label: '✅ 적중', tone: 'border-emerald-300/30 bg-emerald-300/15 text-emerald-200' };
        if (item.stopped) return { label: '🛑 손절', tone: 'border-rose-300/30 bg-rose-300/15 text-rose-200' };
        if (item.hit === false) return { label: '❌ 미달', tone: 'border-amber-300/30 bg-amber-300/15 text-amber-200' };
        return { label: '~ 평가', tone: 'border-amber-400/30 bg-amber-400/15 text-amber-300' };
    }
    if (item.status === 'pending') return { label: '⏳ 진행중', tone: 'border-white/10 bg-white/5 text-neutral-300' };
    if (item.status === 'missing_entry') return { label: '데이터 없음', tone: 'border-white/10 bg-white/5 text-neutral-500' };
    return { label: item.status || '--', tone: 'border-white/10 bg-white/5 text-neutral-400' };
}

function kpiTone(value: number | null | undefined, target: number, higherIsBetter = true): string {
    if (value === null || value === undefined) return 'text-neutral-400';
    const ok = higherIsBetter ? value >= target : value <= target;
    return ok ? 'text-emerald-300' : 'text-amber-300';
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
            <div className={`mt-1.5 text-lg font-black tabular-nums sm:mt-2 sm:text-xl ${tone ?? 'text-white'}`}>
                {value}
            </div>
            {sub && (
                <div className="mt-0.5 text-[10px] font-bold leading-snug text-neutral-500 sm:mt-1">
                    {sub}
                </div>
            )}
        </div>
    );
}

export default function RecentOutcomesBoard() {
    const [data, setData] = useState<MiroFishOutcomesBoard | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [windowDays, setWindowDays] = useState<number>(30);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const board = await mirofishApi.getOutcomesBoard({ days: windowDays, limit: 15 });
                if (cancelled) return;
                setData(board);
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

    const summary = data?.summary;
    const items = data?.items || [];
    const evaluatedCount = summary?.evaluated_count ?? 0;
    const pendingCount = summary?.pending_count ?? 0;

    const hitTone = useMemo(
        () => kpiTone(summary?.hit_rate_pct, summary?.targets.hit_rate_pct ?? 55, true),
        [summary],
    );
    const avgTone = useMemo(
        () => kpiTone(summary?.avg_forward_return_pct, summary?.targets.avg_return_pct ?? 1.5, true),
        [summary],
    );
    const fpTone = useMemo(
        () => kpiTone(summary?.false_positive_pct, summary?.targets.false_positive_pct ?? 20, false),
        [summary],
    );

    return (
        <section className="rounded-xl border border-emerald-300/15 bg-black/60 p-3  sm:p-4">
            <header className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-emerald-200/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-chart-line text-emerald-300" />
                        <span className="truncate">Recent Outcomes</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">추천 종목 실적 추적</h3>
                </div>
                <div className="inline-flex shrink-0 overflow-hidden rounded-md border border-white/10 bg-black/30">
                    {WINDOW_OPTIONS.map((days) => (
                        <button
                            key={days}
                            type="button"
                            onClick={() => setWindowDays(days)}
                            className={`min-h-[28px] px-2.5 py-1.5 text-[10px] font-black uppercase tracking-wider transition-colors sm:py-1 ${
                                windowDays === days
                                    ? 'bg-emerald-300/20 text-emerald-100'
                                    : 'text-neutral-500 hover:bg-white/5 hover:text-neutral-300 active:bg-white/10'
                            }`}
                        >
                            {days}d
                        </button>
                    ))}
                </div>
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}

            {/* KPI cards */}
            <div className="mt-3 grid grid-cols-2 gap-2">
                <KpiCard
                    label="Hit Rate"
                    value={formatPct(summary?.hit_rate_pct)}
                    sub={`목표 ≥${summary?.targets.hit_rate_pct ?? 55}% · n=${evaluatedCount}`}
                    tone={hitTone}
                />
                <KpiCard
                    label="Avg Return"
                    value={formatPct(summary?.avg_forward_return_pct, { withSign: true })}
                    sub={`목표 ≥+${summary?.targets.avg_return_pct ?? 1.5}%`}
                    tone={avgTone}
                />
                <KpiCard
                    label="False Positive"
                    value={formatPct(summary?.false_positive_pct)}
                    sub={`목표 <${summary?.targets.false_positive_pct ?? 20}%`}
                    tone={fpTone}
                />
                <KpiCard
                    label="진행중 / 완료"
                    value={`${pendingCount}/${evaluatedCount}`}
                    sub={`${data?.workflow_count ?? 0}개 워크플로우`}
                />
            </div>

            {/* 종목 목록 — mobile: card list / sm+: table */}
            <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-2.5 sm:p-3">
                <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-400 sm:text-[11px] sm:tracking-[0.18em]">
                        추천 이력 ({items.length}{data?.items_truncated ? `/${data?.total_items}` : ''})
                    </span>
                    {loading && <span className="text-[10px] font-bold uppercase text-neutral-500">loading</span>}
                </div>
                {items.length === 0 ? (
                    <div className="mt-2 rounded border border-white/5 bg-white/[0.02] p-4 text-center text-[11px] font-bold text-neutral-500">
                        {loading ? '불러오는 중...' : `최근 ${windowDays}일 추천 이력 없음`}
                    </div>
                ) : (
                    <>
                        {/* 모바일: 카드 리스트 (< sm) */}
                        <div className="mt-2 max-h-72 space-y-1.5 overflow-y-auto pr-1 sm:hidden">
                            {items.map((item, idx) => {
                                const badge = statusBadge(item);
                                const r5 = item.horizons?.['5'];
                                const r5Tone = r5 !== null && r5 !== undefined
                                    ? (r5 >= 0 ? 'text-emerald-300' : 'text-rose-300')
                                    : 'text-neutral-500';
                                return (
                                    <div
                                        key={`m-${item.workflow_id}-${item.symbol}-${idx}`}
                                        className="rounded-md border border-white/5 bg-white/[0.02] px-2.5 py-2 text-[11px] font-bold active:bg-white/[0.05]"
                                    >
                                        <div className="flex items-center justify-between gap-2">
                                            <div className="min-w-0 flex-1">
                                                <div className="truncate text-white">{item.name || item.symbol}</div>
                                                <div className="text-[9px] font-bold text-neutral-500 tabular-nums">
                                                    {item.symbol} · {formatDate(item.entry_date)}
                                                </div>
                                            </div>
                                            <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-black whitespace-nowrap ${badge.tone}`}>
                                                {badge.label}
                                            </span>
                                        </div>
                                        <div className="mt-1 flex items-center justify-between text-[10px] font-bold">
                                            <span className="text-neutral-500">5D 수익률</span>
                                            <span className={`font-mono tabular-nums ${r5Tone}`}>
                                                {r5 !== null && r5 !== undefined ? `${r5 >= 0 ? '+' : ''}${r5.toFixed(1)}%` : '--'}
                                            </span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {/* sm+ : 테이블 */}
                        <div className="mt-2 hidden max-h-64 overflow-y-auto sm:block">
                            <table className="w-full text-[11px] font-bold">
                                <thead className="sticky top-0 bg-black/95 text-neutral-500">
                                    <tr className="text-left">
                                        <th className="px-1 py-1 font-black uppercase tracking-wider">종목</th>
                                        <th className="px-1 py-1 text-right font-black uppercase tracking-wider">진입일</th>
                                        <th className="px-1 py-1 text-right font-black uppercase tracking-wider">5D</th>
                                        <th className="px-1 py-1 text-right font-black uppercase tracking-wider">상태</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((item, idx) => {
                                        const badge = statusBadge(item);
                                        const r5 = item.horizons?.['5'];
                                        return (
                                            <tr
                                                key={`t-${item.workflow_id}-${item.symbol}-${idx}`}
                                                className="border-t border-white/5 hover:bg-white/[0.03]"
                                            >
                                                <td className="px-1 py-1.5">
                                                    <div className="text-white">{item.name || item.symbol}</div>
                                                    <div className="text-[9px] font-bold text-neutral-500 tabular-nums">{item.symbol}</div>
                                                </td>
                                                <td className="px-1 py-1.5 text-right font-mono text-neutral-300 tabular-nums">
                                                    {formatDate(item.entry_date)}
                                                </td>
                                                <td className={`px-1 py-1.5 text-right font-mono tabular-nums ${
                                                    r5 !== null && r5 !== undefined ? (r5 >= 0 ? 'text-emerald-300' : 'text-rose-300') : 'text-neutral-500'
                                                }`}>
                                                    {r5 !== null && r5 !== undefined ? `${r5 >= 0 ? '+' : ''}${r5.toFixed(1)}%` : '--'}
                                                </td>
                                                <td className="px-1 py-1.5 text-right">
                                                    <span className={`inline-block rounded-full border px-1.5 py-0.5 text-[9px] font-black whitespace-nowrap ${badge.tone}`}>
                                                        {badge.label}
                                                    </span>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </>
                )}
                {summary && evaluatedCount === 0 && pendingCount > 0 && (
                    <div className="mt-2 rounded border border-amber-300/20 bg-amber-300/[0.05] p-2 text-[10px] font-bold text-amber-200 leading-snug">
                        ⚠ 평가 대기중 — daily_prices.csv 가 추천 진입일 이후 갱신되지 않음. outcomes refresh 필요.
                    </div>
                )}
            </div>
        </section>
    );
}
