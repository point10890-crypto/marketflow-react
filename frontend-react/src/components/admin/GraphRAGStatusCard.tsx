import { useEffect, useState } from 'react';
import { MiroFishGraphRAGStatus, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 60_000;

const PHASE_ORDER: Array<{ key: keyof NonNullable<MiroFishGraphRAGStatus['phase']>; label: string }> = [
    { key: 'A_skeleton', label: 'A · Skeleton' },
    { key: 'B_resolver', label: 'B · Resolver' },
    { key: 'C_workflow_enrichment', label: 'C · Workflow' },
    { key: 'D_ui', label: 'D · UI' },
    { key: 'E_mcp', label: 'E · MCP' },
    { key: 'F_eval', label: 'F · Eval' },
];

function stateBadgeTone(state: string): string {
    if (state === 'ready') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200';
    if (state === 'degraded') return 'border-amber-400/30 bg-amber-400/10 text-amber-200';
    if (state === 'error') return 'border-rose-400/30 bg-rose-400/10 text-rose-200';
    return 'border-neutral-400/20 bg-neutral-400/10 text-neutral-300';
}

function stateLabel(state: string): string {
    if (state === 'ready') return 'READY';
    if (state === 'degraded') return 'DEGRADED';
    if (state === 'error') return 'ERROR';
    if (state === 'not_initialized') return 'NOT INIT';
    return state.toUpperCase();
}

function phaseDot(done: boolean): string {
    return done ? 'bg-emerald-400/80' : 'bg-neutral-500/40';
}

function phaseTone(done: boolean): string {
    return done
        ? 'border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-100'
        : 'border-white/10 bg-white/[0.03] text-neutral-400';
}

function formatNumber(n: number | undefined | null): string {
    if (n === undefined || n === null || Number.isNaN(n)) return '--';
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
}

export default function GraphRAGStatusCard() {
    const [data, setData] = useState<MiroFishGraphRAGStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const snap = await mirofishApi.graphrag.getStatus();
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

    const state = data?.state || 'not_initialized';
    const entityCount = data?.entities?.entity_count ?? 0;
    const aliasCount = data?.entities?.alias_count ?? 0;
    const shadowMode = Boolean(data?.flags?.shadow_mode);
    const cacheTtl = data?.flags?.cache_ttl_sec ?? 0;
    const phase = data?.phase || {};
    const mcp = data?.mcp || {};
    const mcpRegistered = Boolean(mcp.registered);
    const mcpModuleAvailable = Boolean(mcp.module_available);

    return (
        <section className="rounded-xl border border-amber-500/15 bg-black/60 p-3 sm:p-4">
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-diagram-project text-amber-400" />
                        <span className="truncate">GraphRAG Status</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">Knowledge graph control</h3>
                </div>
                <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black tracking-wider ${stateBadgeTone(state)}`}>
                    {loading && !data ? 'CHECK' : stateLabel(state)}
                </span>
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}
            {data?.entities?.error && (
                <div className="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/10 px-3 py-2 text-xs font-bold text-amber-100 break-words">
                    Entity DB: {data.entities.error}
                </div>
            )}
            {mcp.error && (
                <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    MCP: {mcp.error}
                </div>
            )}

            <div className="mt-3 grid grid-cols-3 gap-2">
                <div className="rounded-lg border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">Entities</div>
                    <div className="mt-1 text-base font-black text-white tabular-nums">{formatNumber(entityCount)}</div>
                    <div className="text-[10px] font-bold text-neutral-500">{formatNumber(aliasCount)} aliases</div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">Shadow</div>
                    <div className={`mt-1 text-base font-black tabular-nums ${shadowMode ? 'text-amber-300' : 'text-emerald-300'}`}>
                        {shadowMode ? 'ON' : 'OFF'}
                    </div>
                    <div className="text-[10px] font-bold text-neutral-500">read-only mode</div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">Cache TTL</div>
                    <div className="mt-1 text-base font-black text-white tabular-nums">{cacheTtl ? Math.round(cacheTtl / 60) : '--'}</div>
                    <div className="text-[10px] font-bold text-neutral-500">minutes</div>
                </div>
            </div>

            <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">MCP Tools</div>
                    <div className={`mt-1 text-sm font-black ${mcpRegistered ? 'text-emerald-300' : mcpModuleAvailable ? 'text-amber-300' : 'text-rose-300'}`}>
                        {mcpRegistered ? `${mcp.tool_count || 0} registered` : mcpModuleAvailable ? 'module ready' : 'missing'}
                    </div>
                    <div className="text-[10px] font-bold text-neutral-500">{mcp.state || 'not_seen'}</div>
                </div>
                <div className="rounded-lg border border-white/10 bg-black/30 p-2">
                    <div className="text-[10px] font-black uppercase tracking-[0.14em] text-neutral-500">Resolver</div>
                    <div className={`mt-1 text-sm font-black ${data?.endpoints_live?.entities_resolve ? 'text-emerald-300' : 'text-amber-300'}`}>
                        {data?.endpoints_live?.entities_resolve ? 'online' : 'needs index'}
                    </div>
                    <div className="text-[10px] font-bold text-neutral-500">entities/resolve</div>
                </div>
            </div>

            <div className="mt-3">
                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-neutral-500 sm:text-[11px] sm:tracking-[0.18em]">
                    Phase Progress
                </div>
                <div className="mt-2 grid grid-cols-3 gap-1.5">
                    {PHASE_ORDER.map(({ key, label }) => {
                        const done = Boolean(phase[key]);
                        return (
                            <div key={key} className={`rounded-md border px-1.5 py-1 text-[10px] font-bold ${phaseTone(done)}`}>
                                <div className="flex items-center gap-1">
                                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${phaseDot(done)}`} />
                                    <span className="truncate">{label}</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {data && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-1 text-[10px] font-bold text-neutral-500">
                    <span className="truncate">
                        backend · {data.flags?.vector_backend || 'chroma'} · {data.flags?.embedding_model?.split('/').pop() || 'bge-m3'}
                    </span>
                    <span className="whitespace-nowrap tabular-nums">{data.asof?.slice(11, 16) || '--'}</span>
                </div>
            )}
        </section>
    );
}
