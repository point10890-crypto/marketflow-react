import { useEffect, useMemo, useState } from 'react';
import { MiroFishOperatingStage, MiroFishPipelineToday, MiroFishScannerAlertEvent, mirofishApi } from '@/lib/mirofishApi';

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

function formatNumber(value?: number | string | null): string {
    if (value === null || value === undefined || value === '') return '--';
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return number.toLocaleString('ko-KR');
}

function formatAlertScore(value?: number | null): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return Number(value).toFixed(0);
}

function alertActionLabel(action?: string | null): { label: string; tone: string } {
    if (action === 'BUY_CANDIDATE') return { label: 'BUY 후보', tone: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200' };
    if (action === 'WATCH') return { label: '관찰', tone: 'border-amber-300/25 bg-amber-300/10 text-amber-200' };
    if (action === 'REJECT') return { label: '제외', tone: 'border-rose-300/25 bg-rose-300/10 text-rose-200' };
    return { label: action || '--', tone: 'border-white/10 bg-white/[0.05] text-neutral-300' };
}

function alertChangeLabel(value?: number | null): { label: string; tone: string } {
    if (value === null || value === undefined || Number.isNaN(value)) return { label: '--', tone: 'text-neutral-500' };
    const sign = value >= 0 ? '+' : '';
    return {
        label: `${sign}${Number(value).toFixed(2)}%`,
        tone: value >= 0 ? 'text-emerald-300' : 'text-rose-300',
    };
}

function formatDelta(value?: number | null): { label: string; tone: string } {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return { label: '--', tone: 'text-neutral-500' };
    }
    const sign = value >= 0 ? '+' : '';
    const tone = value >= 0 ? 'text-emerald-300' : 'text-rose-300';
    return { label: `${sign}${value.toFixed(2)}%`, tone };
}

function formatPct(value?: number | null, digits = 0): string {
    if (value === null || value === undefined || Number.isNaN(value)) return '--';
    return `${value.toFixed(digits)}%`;
}

function phaseLabel(phase?: string): { label: string; tone: string } {
    switch (phase) {
        case 'regular_session':
            return { label: 'KR open', tone: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-200' };
        case 'pre_open':
            return { label: 'Pre-open', tone: 'border-amber-300/30 bg-amber-300/10 text-amber-200' };
        case 'after_close':
            return { label: 'Closed', tone: 'border-neutral-300/20 bg-neutral-300/10 text-neutral-300' };
        case 'closed_weekend':
            return { label: 'Weekend', tone: 'border-neutral-300/20 bg-neutral-300/10 text-neutral-300' };
        default:
            return { label: phase || '--', tone: 'border-white/10 bg-white/5 text-neutral-300' };
    }
}

function vixTone(level?: string | null): string {
    if (level === 'low') return 'text-emerald-300';
    if (level === 'moderate') return 'text-amber-300';
    if (level === 'elevated') return 'text-amber-300';
    if (level === 'high') return 'text-rose-300';
    return 'text-neutral-300';
}

function fearIndexTone(tone?: string | null): string {
    if (tone === 'danger') return 'text-rose-300';
    if (tone === 'warning') return 'text-amber-300';
    if (tone === 'calm') return 'text-emerald-300';
    if (tone === 'risk') return 'text-cyan-300';
    return 'text-neutral-300';
}

interface FunnelStep {
    label: string;
    value: number;
    width: number;
}

interface OpsStage {
    id: string;
    label: string;
    value: string;
    detail: string;
    state: 'done' | 'active' | 'idle' | 'blocked';
    progress: number;
}

function buildFunnel(data: MiroFishPipelineToday | null): FunnelStep[] {
    if (!data) return [];
    const funnel: Partial<MiroFishPipelineToday['funnel']> = data.funnel || {};
    const pool = funnel.scanner_pool || 0;
    const max = Math.max(pool, 1);
    return [
        { label: 'Scanner', value: pool, width: 100 },
        { label: 'Batch 5', value: funnel.batch_new_candidates || 0, width: Math.round(((funnel.batch_new_candidates || 0) / max) * 100) },
        { label: 'GraphRAG', value: funnel.graphrag_uploaded || 0, width: Math.round(((funnel.graphrag_uploaded || 0) / max) * 100) },
        { label: 'Top 3', value: funnel.top3_ready || 0, width: Math.round(((funnel.top3_ready || 0) / max) * 100) },
    ];
}

function operatingStageState(status?: string): OpsStage['state'] {
    if (status === 'complete') return 'done';
    if (status === 'running' || status === 'ready') return 'active';
    if (status === 'attention') return 'blocked';
    return 'idle';
}

function operatingStageValue(stage: MiroFishOperatingStage): string {
    if (stage.total === null || stage.total === undefined) return String(stage.count ?? 0);
    return `${stage.count ?? 0}/${stage.total}`;
}

function buildOpsStages(data: MiroFishPipelineToday | null): OpsStage[] {
    const operatingStages = data?.operating_workflow?.stages || [];
    if (operatingStages.length) {
        return operatingStages.map((stage) => ({
            id: stage.id,
            label: stage.label,
            value: operatingStageValue(stage),
            detail: stage.objective || stage.status || '--',
            state: operatingStageState(stage.status),
            progress: Number(stage.progress_pct || 0),
        }));
    }

    const funnel: Partial<MiroFishPipelineToday['funnel']> = data?.funnel || {};
    const scannerRuns = funnel.scanner_runs_today ?? 0;
    const batchCount = funnel.batch_new_candidates ?? 0;
    const graphCount = funnel.graphrag_uploaded ?? 0;
    const top3Count = funnel.top3_ready ?? 0;
    const alertsCount = data?.alerts_today?.scanner_alerts_today ?? 0;
    const evaluated = data?.kpi_7d?.sample_size ?? 0;
    const pending = data?.kpi_7d?.pending_count ?? 0;
    const workflowStatus = String(funnel.latest_workflow_status || '').toLowerCase();
    const scannerEnabled = data?.next?.scanner_enabled !== false;

    return [
        {
            id: 'scanner',
            label: 'Auto scan',
            value: scannerEnabled ? `${scannerRuns}` : 'off',
            detail: `next ${formatTime(data?.next?.next_scheduled_scan_at)}`,
            state: !scannerEnabled ? 'blocked' : scannerRuns > 0 ? 'done' : 'idle',
            progress: scannerRuns > 0 ? 100 : 0,
        },
        {
            id: 'batch',
            label: 'Queue',
            value: `${Math.min(batchCount, 5)}/5`,
            detail: `${batchCount} new candidates`,
            state: batchCount > 0 ? 'active' : scannerRuns > 0 ? 'done' : 'idle',
            progress: Math.min(100, (batchCount / 5) * 100),
        },
        {
            id: 'graphrag',
            label: 'GraphRAG',
            value: `${graphCount}`,
            detail: workflowStatus || 'await batch',
            state: graphCount > 0 ? 'done' : batchCount > 0 ? 'active' : 'idle',
            progress: batchCount > 0 ? Math.min(100, (graphCount / batchCount) * 100) : 0,
        },
        {
            id: 'top3',
            label: 'Top3',
            value: `${top3Count}`,
            detail: funnel.latest_workflow_id ? 'ranked workflow' : 'ranking',
            state: top3Count > 0 ? 'done' : graphCount > 0 ? 'active' : 'idle',
            progress: Math.min(100, (top3Count / 3) * 100),
        },
        {
            id: 'telegram',
            label: 'Telegram',
            value: `${alertsCount}`,
            detail: `last ${formatTime(data?.alerts_today?.scanner_last_alert_at)}`,
            state: alertsCount > 0 ? 'done' : top3Count > 0 ? 'active' : 'idle',
            progress: alertsCount > 0 ? 100 : 0,
        },
        {
            id: 'outcomes',
            label: 'Validate',
            value: formatPct(data?.kpi_7d?.hit_rate_pct),
            detail: `${evaluated} checked / ${pending} pending`,
            state: evaluated > 0 ? 'done' : top3Count > 0 ? 'active' : 'idle',
            progress: evaluated > 0 ? 100 : 0,
        },
    ];
}

function stageTone(state: OpsStage['state']): string {
    if (state === 'done') return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (state === 'active') return 'border-amber-400/25 bg-amber-400/10 text-amber-100';
    if (state === 'blocked') return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    return 'border-white/10 bg-white/[0.04] text-neutral-300';
}

function stageDot(state: OpsStage['state']): string {
    if (state === 'done') return 'bg-emerald-300';
    if (state === 'active') return 'bg-amber-400 animate-pulse';
    if (state === 'blocked') return 'bg-rose-300';
    return 'bg-white/25';
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
    const opsStages = useMemo(() => buildOpsStages(data), [data]);
    const phase = phaseLabel(data?.market?.kr?.phase);
    const kospiDelta = formatDelta(data?.market?.kr?.kospi_change_pct);
    const kosdaqDelta = formatDelta(data?.market?.kr?.kosdaq_change_pct);
    const operating = data?.operating_workflow;
    const alertEvents = useMemo<MiroFishScannerAlertEvent[]>(
        () => (data?.alerts_today?.recent_scanner_alerts || []).slice(0, 4),
        [data],
    );

    return (
        <section className="rounded-xl border border-amber-400/15 bg-black/60 p-3  sm:p-4">
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-satellite-dish text-amber-400" />
                        <span className="truncate">Today&apos;s Pipeline</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">Alpha ops lane</h3>
                </div>
                {loading && (
                    <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-neutral-500">loading...</span>
                )}
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}

            <div className="mt-3 rounded-lg border border-amber-400/15 bg-amber-400/[0.05] p-2.5 sm:mt-4 sm:p-3">
                <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.16em] text-amber-300/80 sm:text-[11px] sm:tracking-[0.18em]">
                        Operating Workflow
                    </span>
                    <span className="text-[10px] font-bold text-neutral-500 whitespace-nowrap">
                        {operating ? `${operating.overall_status} ${formatPct(operating.overall_progress_pct, 0)}` : data?.funnel?.freshness_status || 'source --'}
                    </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5 sm:gap-2">
                    {opsStages.map((stage, index) => (
                        <div key={stage.id || stage.label} className={`rounded-lg border p-2 ${stageTone(stage.state)}`}>
                            <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-[10px] font-black uppercase tracking-[0.12em] text-current/70">
                                    {index + 1}. {stage.label}
                                </span>
                                <span className={`h-2 w-2 shrink-0 rounded-full ${stageDot(stage.state)}`} />
                            </div>
                            <div className="mt-1 text-base font-black text-white tabular-nums">{stage.value}</div>
                            <div className="mt-0.5 truncate text-[10px] font-bold text-neutral-500">{stage.detail}</div>
                            <div className="mt-2 h-1 overflow-hidden rounded-full bg-black/30">
                                <div
                                    className="h-full rounded-full bg-current/70 transition-all"
                                    style={{ width: `${Math.max(2, Math.min(100, stage.progress))}%` }}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="mt-3 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.055] p-2.5 sm:p-3">
                <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.16em] text-cyan-200/80 sm:text-[11px] sm:tracking-[0.18em]">
                        Scanner Alerts
                    </span>
                    <span className="text-[10px] font-bold text-neutral-500 whitespace-nowrap">
                        today {data?.alerts_today?.scanner_alerts_today ?? 0}
                    </span>
                </div>
                {alertEvents.length > 0 ? (
                    <div className="mt-2 space-y-1.5">
                        {alertEvents.map((event, index) => {
                            const action = alertActionLabel(event.action);
                            const change = alertChangeLabel(event.price?.change_rate ?? null);
                            return (
                                <div key={event.event_key || `${event.symbol}-${event.sent_at}-${index}`} className="rounded-lg border border-white/10 bg-black/25 px-2.5 py-2">
                                    <div className="flex items-center justify-between gap-2">
                                        <div className="min-w-0">
                                            <div className="truncate text-xs font-black text-white">
                                                {event.display_name || event.symbol || '--'}
                                            </div>
                                            <div className="mt-0.5 truncate font-mono text-[10px] text-neutral-500">
                                                {event.symbol || '--'} · {event.market || 'KR'} · {formatTime(event.sent_at)}
                                            </div>
                                        </div>
                                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black ${action.tone}`}>
                                            {action.label}
                                        </span>
                                    </div>
                                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] font-bold">
                                        <span className="text-neutral-500">가격 <span className="font-mono text-neutral-200">{formatNumber(event.price?.current_price)}</span></span>
                                        <span className={`font-mono ${change.tone}`}>{change.label}</span>
                                        <span className="text-neutral-500">A <span className="font-mono text-cyan-200">{formatAlertScore(event.alpha_score)}</span></span>
                                        <span className="text-neutral-500">R <span className="font-mono text-amber-200">{formatAlertScore(event.risk_score)}</span></span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <div className="mt-2 rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 text-[11px] font-bold text-neutral-500">
                        신규 이벤트가 발생하면 이 영역에 즉시 표시됩니다.
                    </div>
                )}
            </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-2.5 sm:p-3">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                    <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-400 sm:text-[11px] sm:tracking-[0.18em]">KR Market</span>
                    </div>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-black whitespace-nowrap ${phase.tone}`}>
                        {phase.label}
                    </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] font-bold">
                    <div>
                        <div className="text-neutral-500">KOSPI</div>
                        <div className={`mt-0.5 text-sm font-black sm:text-base ${kospiDelta.tone}`}>{kospiDelta.label}</div>
                    </div>
                    <div>
                        <div className="text-neutral-500">KOSDAQ</div>
                        <div className={`mt-0.5 text-sm font-black sm:text-base ${kosdaqDelta.tone}`}>{kosdaqDelta.label}</div>
                    </div>
                </div>
                {data?.market?.kr?.gate_label && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-neutral-500">Gate</span>
                        <span className="text-amber-300">
                            {data.market.kr.gate_label}{' '}
                            {data.market.kr.gate_score !== null && data.market.kr.gate_score !== undefined && (
                                <span className="text-neutral-500">({data.market.kr.gate_score})</span>
                            )}
                        </span>
                    </div>
                )}
                {data?.market?.us?.vix !== null && data?.market?.us?.vix !== undefined && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-neutral-500">VIX</span>
                        <span className={vixTone(data.market.us.vix_level)}>
                            {Number(data.market.us.vix).toFixed(1)}
                            <span className="ml-1 text-neutral-500">({data.market.us.vix_level || '--'})</span>
                        </span>
                    </div>
                )}
                {data?.market?.us?.fear_greed_score !== null && data?.market?.us?.fear_greed_score !== undefined && (
                    <div className="mt-2 flex items-center justify-between text-[11px] font-bold">
                        <span className="text-neutral-500">Fear &amp; Greed</span>
                        <span className="text-amber-200">
                            {data.market.us.fear_greed_score}{' '}
                            <span className="text-neutral-500">{data.market.us.fear_greed_label || ''}</span>
                        </span>
                    </div>
                )}
                {data?.fear_index && (
                    <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[11px] font-bold">
                        <span className="text-neutral-500">공포지수</span>
                        <span className={`text-right ${fearIndexTone(data.fear_index.tone)}`}>
                            {data.fear_index.score !== null && data.fear_index.score !== undefined ? Number(data.fear_index.score).toFixed(0) : '--'}
                            <span className="ml-1 text-neutral-500">{data.fear_index.level_label || data.fear_index.level || ''}</span>
                        </span>
                    </div>
                )}
            </div>

            <div className="mt-3 rounded-lg border border-white/10 bg-black/30 p-2.5 sm:p-3">
                <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-400 sm:text-[11px] sm:tracking-[0.18em]">Detection Funnel</span>
                    <span className="text-[10px] font-bold text-neutral-500 whitespace-nowrap">
                        today {data?.funnel?.scanner_runs_today ?? 0} runs
                    </span>
                </div>
                <div className="mt-2 space-y-1.5">
                    {funnel.map((step) => (
                        <div key={step.label} className="flex items-center gap-1.5 text-[11px] font-bold sm:gap-2">
                            <span className="w-14 shrink-0 text-neutral-400 sm:w-16">{step.label}</span>
                            <div className="flex-1 overflow-hidden rounded-sm bg-white/[0.04]">
                                <div
                                    className="h-3 rounded-sm bg-gradient-to-r from-amber-500/60 via-amber-400/70 to-emerald-400/80 transition-all"
                                    style={{ width: `${Math.max(2, Math.min(100, step.width))}%` }}
                                />
                            </div>
                            <span className="w-7 shrink-0 text-right text-white tabular-nums sm:w-8">{step.value}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
                {(['kpi_7d', 'kpi_30d'] as const).map((key) => {
                    const kpi = data?.[key];
                    const hit = kpi?.hit_rate_pct;
                    const avg = kpi?.avg_return_pct;
                    return (
                        <div key={key} className="rounded-lg border border-white/10 bg-black/30 p-2.5 sm:p-3">
                            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500 sm:tracking-[0.18em]">
                                {key === 'kpi_7d' ? '7D' : '30D'} KPI
                            </div>
                            <div className="mt-1.5 flex items-baseline gap-1 sm:mt-2">
                                <span className="text-lg font-black text-white tabular-nums sm:text-xl">
                                    {hit !== null && hit !== undefined ? `${hit.toFixed(0)}%` : '--'}
                                </span>
                                <span className="text-[10px] font-bold text-neutral-500">hit</span>
                            </div>
                            <div className="mt-1 flex items-center justify-between text-[10px] font-bold">
                                <span className="text-neutral-500">avg R</span>
                                <span className={`tabular-nums ${avg !== null && avg !== undefined ? (avg >= 0 ? 'text-emerald-300' : 'text-rose-300') : 'text-neutral-500'}`}>
                                    {avg !== null && avg !== undefined ? `${avg >= 0 ? '+' : ''}${avg.toFixed(2)}%` : '--'}
                                </span>
                            </div>
                            <div className="mt-0.5 flex items-center justify-between text-[10px] font-bold text-neutral-500">
                                <span>sample</span>
                                <span className="tabular-nums">{kpi?.sample_size ?? 0}</span>
                            </div>
                        </div>
                    );
                })}
            </div>

            <div className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-[11px] font-bold sm:px-3">
                <span className="text-neutral-500 truncate">Auto scan ETA</span>
                <span className="font-mono text-amber-300 tabular-nums whitespace-nowrap">
                    {formatTime(data?.next?.next_scheduled_scan_at)}
                </span>
            </div>
        </section>
    );
}
