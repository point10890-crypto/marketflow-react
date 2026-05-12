/**
 * Today's Pipeline — 우측 상단 카드.
 *
 * Live market context (KR session + gate + VIX) + 오늘의 검출 funnel +
 * 7일 KPI 요약 + 다음 스캔 ETA.
 *
 * 단일 GET /api/admin/mirofish/pipeline/today 호출.
 * 30초 폴링으로 자동 갱신.
 */
import { useEffect, useMemo, useState } from 'react';
import { MiroFishPipelineToday, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 30_000;

function formatTime(iso?: string | null): string {
    if (!iso) return '--';
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '--';
        return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Seoul' });
    } catch {
        return '--';
    }
}

function formatDelta(value?: number | null): { label: string; tone: string } {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return { label: '--', tone: 'text-slate-500' };
    }
    const sign = value >= 0 ? '+' : '';
    const tone = value >= 0 ? 'text-emerald-300' : 'text-rose-300';
    return { label: `${sign}${value.toFixed(2)}%`, tone };
}

function phaseLabel(phase?: string): { ko: string; tone: string } {
    switch (phase) {
        case 'regular_session':
            return { ko: '🟢 장중', tone: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-200' };
        case 'pre_open':
            return { ko: '🟡 장 시작전', tone: 'border-amber-300/30 bg-amber-300/10 text-amber-200' };
        case 'after_close':
            return { ko: '⚫ 장 마감', tone: 'border-slate-300/20 bg-slate-300/10 text-slate-300' };
        case 'closed_weekend':
            return { ko: '⚫ 주말 휴장', tone: 'border-slate-300/20 bg-slate-300/10 text-slate-300' };
        default:
            return { ko: phase || '--', tone: 'border-white/10 bg-white/5 text-slate-300' };
    }
}

function vixTone(level?: string | null): string {
    if (level === 'low') return 'text-emerald-300';
    if (level === 'moderate') return 'text-cyan-200';
    if (level === 'elevated') return 'text-amber-300';
    if (level === 'high') return 'text-rose-300';
    return 'text-slate-300';
}

interface FunnelStep {
    label: string;
    value: number;
    width: number; // 0..100
}

function buildFunnel(data: MiroFishPipelineToday | null): FunnelStep[] {
    if (!data) return [];
    const pool = data.funnel.scanner_pool || 0;
    const max = Math.max(pool, 1);
    return [
        { label: 'Scanner', value: pool, width: 100 },
        { label: 'Batch 5', value: data.funnel.batch_new_candidates || 0, width: Math.round(((data.funnel.batch_new_candidates || 0) / max) * 100) },
        { label: 'GraphRAG', value: data.funnel.graphrag_uploaded || 0, width: Math.round(((data.funnel.graphrag_uploaded || 0) / max) * 100) },
        { label: 'Top 3', value: data.funnel.top3_ready || 0, width: Math.round(((data.funnel.top3_ready || 0) / max) * 100) },
    ];
}

export default function TodaysPipelineCard() {
    const [data, setData] = useState<MiroFishPipelineToday | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const snap = await mirofishApi.getPipelineToday();
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
    }, []);

    const funnel = useMemo(() => buildFunnel(data), [data]);
    const phase = phaseLabel(data?.market?.kr?.phase);
    const kospiDelta = formatDelta(data?.market?.kr?.kospi_change_pct);
    const kosdaqDelta = formatDelta(data?.market?.kr?.kosdaq_change_pct);

    return (
        <section className="rounded-xl border border-cyan-300/15 bg-slate-950/60 p-4 shadow-[0_18px_70px_rgba(34,211,238,0.10)]">
            <header className="flex items-center justify-between">
                <div>
                    <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-cyan-200/70">
                        <i className="fas fa-satellite-dish text-cyan-300" />
                        Today&apos;s Pipeline
                    </div>
                    <h3 className="mt-1 text-base font-black text-white">시장 + 검출 + KPI</h3>
                </div>
                {loading && (
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">loading...</span>
                )}
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100">
                    {error}
                </div>
            )}

            {/* KR 마켓 펄스 */}
            <div className="mt-4 rounded-lg border border-white/10 bg-black/30 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <span className="text-base">🇰🇷</span>
                        <span className="text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">KR Market</span>
                    </div>
                    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-black ${phase.tone}`}>
                        {phase.ko}
                    </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] font-bold">
                    <div>
                        <div className="text-slate-500">KOSPI</div>
                        <div className={`mt-0.5 text-base font-black ${kospiDelta.tone}`}>{kospiDelta.label}</div>
                    </div>
                    <div>
                        <div className="text-slate-500">KOSDAQ</div>
                        <div className={`mt-0.5 text-base font-black ${kosdaqDelta.tone}`}>{kosdaqDelta.label}</div>
                    </div>
                </div>
                {data?.market?.kr?.gate_label && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-slate-500">Gate</span>
                        <span className="text-cyan-200">
                            {data.market.kr.gate_label}{' '}
                            {data.market.kr.gate_score !== null && data.market.kr.gate_score !== undefined && (
                                <span className="text-slate-500">({data.market.kr.gate_score})</span>
                            )}
                        </span>
                    </div>
                )}
                {(data?.market?.us?.vix !== null && data?.market?.us?.vix !== undefined) && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-slate-500">VIX</span>
                        <span className={vixTone(data.market.us.vix_level)}>
                            {Number(data.market.us.vix).toFixed(1)}
                            <span className="ml-1 text-slate-500">({data.market.us.vix_level || '--'})</span>
                        </span>
                    </div>
                )}
                {data?.market?.us?.fear_greed_score !== null && data?.market?.us?.fear_greed_score !== undefined && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-slate-500">Fear &amp; Greed</span>
                        <span className="text-amber-200">
                            {data.market.us.fear_greed_score}{' '}
                            <span className="text-slate-500">{data.market.us.fear_greed_label || ''}</span>
                        </span>
                    </div>
                )}
            </div>

            {/* Detection Funnel */}
            <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-3">
                <div className="flex items-center justify-between">
                    <span className="text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">Detection Funnel</span>
                    <span className="text-[10px] font-bold text-slate-500">오늘 스캔 {data?.funnel?.scanner_runs_today ?? 0}회</span>
                </div>
                <div className="mt-2 space-y-1.5">
                    {funnel.map((step) => (
                        <div key={step.label} className="flex items-center gap-2 text-[11px] font-bold">
                            <span className="w-16 shrink-0 text-slate-400">{step.label}</span>
                            <div className="flex-1 overflow-hidden rounded-sm bg-white/[0.04]">
                                <div
                                    className="h-3 rounded-sm bg-gradient-to-r from-cyan-500/60 via-cyan-400/70 to-emerald-400/80 transition-all"
                                    style={{ width: `${Math.max(2, Math.min(100, step.width))}%` }}
                                />
                            </div>
                            <span className="w-8 shrink-0 text-right text-white">{step.value}</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* KPI 7d/30d */}
            <div className="mt-3 grid grid-cols-2 gap-2">
                {(['kpi_7d', 'kpi_30d'] as const).map((key) => {
                    const kpi = data?.[key];
                    const hit = kpi?.hit_rate_pct;
                    const avg = kpi?.avg_return_pct;
                    return (
                        <div key={key} className="rounded-lg border border-white/10 bg-black/30 p-3">
                            <div className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">
                                {key === 'kpi_7d' ? '7D' : '30D'} KPI
                            </div>
                            <div className="mt-2 flex items-baseline gap-1">
                                <span className="text-xl font-black text-white">
                                    {hit !== null && hit !== undefined ? `${hit.toFixed(0)}%` : '--'}
                                </span>
                                <span className="text-[10px] font-bold text-slate-500">hit rate</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between text-[10px] font-bold">
                                <span className="text-slate-500">avg R</span>
                                <span className={avg !== null && avg !== undefined ? (avg >= 0 ? 'text-emerald-300' : 'text-rose-300') : 'text-slate-500'}>
                                    {avg !== null && avg !== undefined ? `${avg >= 0 ? '+' : ''}${avg.toFixed(2)}%` : '--'}
                                </span>
                            </div>
                            <div className="mt-0.5 flex items-center justify-between text-[10px] font-bold text-slate-500">
                                <span>샘플</span>
                                <span>{kpi?.sample_size ?? 0}건</span>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Next ETA */}
            <div className="mt-3 flex items-center justify-between rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-[11px] font-bold">
                <span className="text-slate-500">⏰ 다음 자동 스캔</span>
                <span className="font-mono text-cyan-200">
                    {formatTime(data?.next?.next_scheduled_scan_at)}
                </span>
            </div>
        </section>
    );
}
