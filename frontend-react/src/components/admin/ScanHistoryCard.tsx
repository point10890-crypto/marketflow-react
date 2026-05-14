/**
 * Phase G: 종목별 스캔 히스토리 테이블.
 *
 * 정렬: scan_count | alpha_avg | workflow_count | hit_rate | avg_return.
 * 색상: hit_rate ≥ 60% 에메랄드, ≤ 30% 로즈, 중간 앰버. alpha_avg ≥ 70 강조.
 * 종목 클릭 → 인라인 expand (workflow rank/verdict/outcome 표시).
 *
 * 단일 GET /api/admin/mirofish/graphrag/scan-history.
 * 60초 폴링.
 */
import { Fragment, useEffect, useMemo, useState } from 'react';
import {
    MiroFishScanHistoryItem,
    MiroFishScanHistoryResponse,
    MiroFishSymbolHistoryResponse,
    mirofishApi,
} from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 60_000;
const WINDOW_OPTIONS = [30, 60, 90] as const;
const ALPHA_OPTIONS = [0, 50, 60, 70] as const;
const TABLE_LIMIT = 50;

type SortKey = 'scan_count' | 'alpha_avg' | 'workflow_count' | 'hit_rate' | 'avg_return';

function formatPct(value: number | null | undefined, opts: { withSign?: boolean } = {}): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    const sign = opts.withSign && value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(1)}%`;
}

function formatRate(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return `${(value * 100).toFixed(0)}%`;
}

function rateTone(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'text-neutral-500';
    if (value >= 0.6) return 'text-emerald-300';
    if (value <= 0.3) return 'text-rose-300';
    return 'text-amber-300';
}

function alphaTone(value: number): string {
    if (value >= 70) return 'text-emerald-200';
    if (value >= 60) return 'text-amber-200';
    if (value >= 50) return 'text-neutral-200';
    return 'text-neutral-400';
}

function returnTone(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'text-neutral-500';
    if (value >= 5) return 'text-emerald-300';
    if (value <= -3) return 'text-rose-300';
    return 'text-amber-300';
}

function formatDate(s: string | undefined | null): string {
    if (!s) return '--';
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    return m ? `${m[2]}-${m[3]}` : s;
}

function sortItems(items: MiroFishScanHistoryItem[], key: SortKey): MiroFishScanHistoryItem[] {
    const sorted = [...items];
    sorted.sort((a, b) => {
        if (key === 'scan_count') return b.scan_count - a.scan_count || b.alpha_avg - a.alpha_avg;
        if (key === 'alpha_avg') return b.alpha_avg - a.alpha_avg || b.scan_count - a.scan_count;
        if (key === 'workflow_count') return b.workflow_count - a.workflow_count || b.alpha_avg - a.alpha_avg;
        if (key === 'hit_rate') {
            const ha = a.outcome.hit_rate ?? -1;
            const hb = b.outcome.hit_rate ?? -1;
            return hb - ha || (b.outcome.evaluated_count - a.outcome.evaluated_count);
        }
        if (key === 'avg_return') {
            const ra = a.outcome.avg_forward_return_pct ?? -999;
            const rb = b.outcome.avg_forward_return_pct ?? -999;
            return rb - ra || (b.outcome.evaluated_count - a.outcome.evaluated_count);
        }
        return 0;
    });
    return sorted;
}

interface DetailRowProps {
    detail: MiroFishSymbolHistoryResponse | null;
    loading: boolean;
    error: string | null;
}

function DetailRow({ detail, loading, error }: DetailRowProps) {
    if (loading) {
        return (
            <tr>
                <td colSpan={7} className="border-t border-white/5 px-3 py-2 text-[11px] text-neutral-400">
                    로딩 중...
                </td>
            </tr>
        );
    }
    if (error) {
        return (
            <tr>
                <td colSpan={7} className="border-t border-white/5 px-3 py-2 text-[11px] text-rose-300">
                    {error}
                </td>
            </tr>
        );
    }
    if (!detail) return null;

    const wfs = detail.workflows.slice(0, 5);

    return (
        <tr>
            <td colSpan={7} className="border-t border-white/5 bg-black/40 px-3 py-2">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <div>
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">
                            워크플로우 진입 ({detail.workflows.length})
                        </div>
                        {wfs.length === 0 ? (
                            <div className="mt-1 text-[11px] text-neutral-500">진입 기록 없음</div>
                        ) : (
                            <ul className="mt-1 space-y-1">
                                {wfs.map((w) => {
                                    const o = w.outcome;
                                    const status = o.status;
                                    const hitText = o.hit === true ? 'HIT' : o.hit === false ? 'MISS' : status;
                                    const hitTone = o.hit === true
                                        ? 'text-emerald-300'
                                        : o.hit === false
                                            ? 'text-rose-300'
                                            : 'text-neutral-400';
                                    return (
                                        <li key={w.workflow_id} className="flex items-center justify-between gap-2 text-[11px] font-bold">
                                            <span className="truncate text-neutral-300">
                                                {w.date} · #{w.rank ?? '?'} {w.verdict.action || 'N/A'}
                                            </span>
                                            <span className="flex items-center gap-2">
                                                <span className={hitTone}>{hitText}</span>
                                                <span className={returnTone(o.forward_return_pct)}>
                                                    {formatPct(o.forward_return_pct, { withSign: true })}
                                                </span>
                                            </span>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>
                    <div>
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500">
                            스캐너 등장 ({detail.scans.length})
                        </div>
                        {detail.scans.length === 0 ? (
                            <div className="mt-1 text-[11px] text-neutral-500">기록 없음</div>
                        ) : (
                            <ul className="mt-1 space-y-1">
                                {detail.scans.slice(0, 5).map((s) => (
                                    <li
                                        key={`${s.scanner_run_id}-${s.symbol}`}
                                        className="flex items-center justify-between gap-2 text-[11px] font-bold"
                                    >
                                        <span className="truncate text-neutral-300">
                                            {s.date} · #{s.rank ?? '?'} {s.action}
                                        </span>
                                        <span className="flex items-center gap-2">
                                            <span className={alphaTone(s.alpha_score)}>α{s.alpha_score.toFixed(0)}</span>
                                            <span className="text-neutral-500">r{s.risk_score.toFixed(0)}</span>
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </div>
            </td>
        </tr>
    );
}

export default function ScanHistoryCard() {
    const [data, setData] = useState<MiroFishScanHistoryResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [windowDays, setWindowDays] = useState<number>(30);
    const [minAlpha, setMinAlpha] = useState<number>(0);
    const [sortKey, setSortKey] = useState<SortKey>('scan_count');
    const [expanded, setExpanded] = useState<string | null>(null);
    const [detail, setDetail] = useState<MiroFishSymbolHistoryResponse | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const snap = await mirofishApi.graphrag.getScanHistory({
                    days: windowDays,
                    limit: TABLE_LIMIT,
                    min_alpha: minAlpha,
                });
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
    }, [windowDays, minAlpha]);

    const handleToggle = async (symbol: string) => {
        if (expanded === symbol) {
            setExpanded(null);
            setDetail(null);
            return;
        }
        setExpanded(symbol);
        setDetail(null);
        setDetailLoading(true);
        setDetailError(null);
        try {
            const d = await mirofishApi.graphrag.getSymbolHistory(symbol, windowDays * 2);
            setDetail(d);
        } catch (err) {
            setDetailError(err instanceof Error ? err.message : 'load failed');
        } finally {
            setDetailLoading(false);
        }
    };

    const items = useMemo(() => sortItems(data?.items || [], sortKey), [data, sortKey]);

    const HeaderButton = ({ k, label, align = 'right' }: { k: SortKey; label: string; align?: 'left' | 'right' }) => (
        <button
            type="button"
            onClick={() => setSortKey(k)}
            className={`text-[10px] font-black uppercase tracking-[0.14em] transition ${
                sortKey === k ? 'text-amber-300' : 'text-neutral-500 hover:text-neutral-300'
            } ${align === 'left' ? 'text-left' : 'text-right w-full'}`}
        >
            {label}
            {sortKey === k && <span className="ml-0.5">▼</span>}
        </button>
    );

    return (
        <section className="rounded-xl border border-amber-500/15 bg-black/60 p-3 sm:p-4">
            <header className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-magnifying-glass-chart text-amber-400" />
                        <span className="truncate">Scan History</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">
                        종목별 스캔 + 워크플로우 + Outcome
                    </h3>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1 text-[10px] font-bold">
                    {WINDOW_OPTIONS.map((d) => (
                        <button
                            key={`d-${d}`}
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
                    <span className="mx-1 text-neutral-700">·</span>
                    {ALPHA_OPTIONS.map((a) => (
                        <button
                            key={`a-${a}`}
                            type="button"
                            onClick={() => setMinAlpha(a)}
                            className={`rounded-full border px-2 py-0.5 transition ${
                                a === minAlpha
                                    ? 'border-emerald-400/40 bg-emerald-400/15 text-emerald-200'
                                    : 'border-white/10 bg-white/5 text-neutral-400 hover:bg-white/10'
                            }`}
                        >
                            α≥{a}
                        </button>
                    ))}
                </div>
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}

            {/* Summary 라인 */}
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div className="rounded-lg border border-white/10 bg-black/30 p-2 text-center">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">고유종목</div>
                    <div className="text-base font-black text-white">
                        {loading && !data ? '--' : data?.total_unique_symbols ?? 0}
                    </div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2 text-center">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">총 스캔</div>
                    <div className="text-base font-black text-white">
                        {loading && !data ? '--' : data?.total_scans ?? 0}
                    </div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2 text-center">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">평가 hit</div>
                    <div className={`text-base font-black ${rateTone(data?.summary?.hit_rate)}`}>
                        {loading && !data ? '--' : formatRate(data?.summary?.hit_rate)}
                    </div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2 text-center">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">평균 수익</div>
                    <div className={`text-base font-black ${returnTone(data?.summary?.avg_return_pct)}`}>
                        {loading && !data
                            ? '--'
                            : formatPct(data?.summary?.avg_return_pct, { withSign: true })}
                    </div>
                </div>
            </div>

            {/* Table */}
            <div className="mt-3 overflow-x-auto rounded-lg border border-white/10">
                <table className="w-full min-w-[640px] text-[11px]">
                    <thead className="bg-black/40">
                        <tr>
                            <th className="px-3 py-2">
                                <HeaderButton k="scan_count" label="종목 / 스캔수" align="left" />
                            </th>
                            <th className="px-2 py-2 text-right">
                                <HeaderButton k="alpha_avg" label="α 평균" />
                            </th>
                            <th className="px-2 py-2 text-right">
                                <span className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">
                                    최근일
                                </span>
                            </th>
                            <th className="px-2 py-2 text-right">
                                <HeaderButton k="workflow_count" label="Top3 진입" />
                            </th>
                            <th className="px-2 py-2 text-right">
                                <HeaderButton k="hit_rate" label="Hit %" />
                            </th>
                            <th className="px-2 py-2 text-right">
                                <HeaderButton k="avg_return" label="평균 수익" />
                            </th>
                            <th className="px-2 py-2 text-right text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">
                                ⇕
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && !data && (
                            <tr>
                                <td colSpan={7} className="px-3 py-4 text-center text-neutral-500">로딩 중...</td>
                            </tr>
                        )}
                        {!loading && items.length === 0 && (
                            <tr>
                                <td colSpan={7} className="px-3 py-4 text-center text-neutral-500">
                                    데이터 없음
                                </td>
                            </tr>
                        )}
                        {items.map((it) => {
                            const isOpen = expanded === it.symbol;
                            return (
                                <Fragment key={it.symbol}>
                                    <tr
                                        className={`border-t border-white/5 hover:bg-white/[0.03] cursor-pointer ${
                                            isOpen ? 'bg-white/[0.04]' : ''
                                        }`}
                                        onClick={() => handleToggle(it.symbol)}
                                    >
                                        <td className="px-3 py-2">
                                            <div className="font-bold text-white">{it.display_name}</div>
                                            <div className="text-[10px] font-bold text-neutral-500">
                                                {it.symbol} · {it.market} · {it.scan_count}회
                                            </div>
                                        </td>
                                        <td className={`px-2 py-2 text-right font-black ${alphaTone(it.alpha_avg)}`}>
                                            {it.alpha_avg.toFixed(1)}
                                            <div className="text-[10px] font-bold text-neutral-500">
                                                {it.alpha_min.toFixed(0)}–{it.alpha_max.toFixed(0)}
                                            </div>
                                        </td>
                                        <td className="px-2 py-2 text-right text-neutral-300">
                                            {formatDate(it.scan_last_date)}
                                        </td>
                                        <td className="px-2 py-2 text-right">
                                            <div className="font-bold text-white">{it.workflow_count}</div>
                                            {it.workflow_count > 0 && (
                                                <div className="text-[10px] font-bold text-neutral-500">
                                                    {Object.entries(it.verdict_actions || {})
                                                        .map(([k, v]) => `${k}${v}`)
                                                        .join(' ')}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-2 py-2 text-right">
                                            <span className={`font-black ${rateTone(it.outcome.hit_rate)}`}>
                                                {formatRate(it.outcome.hit_rate)}
                                            </span>
                                            <div className="text-[10px] font-bold text-neutral-500">
                                                평가 {it.outcome.evaluated_count} / 대기 {it.outcome.pending_count}
                                            </div>
                                        </td>
                                        <td className="px-2 py-2 text-right">
                                            <span
                                                className={`font-black ${returnTone(
                                                    it.outcome.avg_forward_return_pct,
                                                )}`}
                                            >
                                                {formatPct(it.outcome.avg_forward_return_pct, { withSign: true })}
                                            </span>
                                            {it.outcome.best_return_pct !== null && (
                                                <div className="text-[10px] font-bold text-neutral-500">
                                                    best{' '}
                                                    <span className={returnTone(it.outcome.best_return_pct)}>
                                                        {formatPct(it.outcome.best_return_pct, { withSign: true })}
                                                    </span>
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-2 py-2 text-right text-[10px] text-neutral-500">
                                            {isOpen ? '▲' : '▼'}
                                        </td>
                                    </tr>
                                    {isOpen && (
                                        <DetailRow
                                            detail={detail}
                                            loading={detailLoading}
                                            error={detailError}
                                        />
                                    )}
                                </Fragment>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {data?.generated_at && (
                <div className="mt-2 text-right text-[10px] font-bold text-neutral-500">
                    asof {data.generated_at.slice(0, 19).replace('T', ' ')} · returned {data.returned_items} / {data.total_unique_symbols}
                </div>
            )}
        </section>
    );
}
