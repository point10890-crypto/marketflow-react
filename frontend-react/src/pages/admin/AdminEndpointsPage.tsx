import { useEffect, useMemo, useRef, useState, type CompositionEvent as ReactCompositionEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { MiroFishAnalyst, MiroFishLayer, MiroFishLog, MiroFishNode, MiroFishRun, MiroFishStatus, MiroFishTargetSnapshot, mirofishApi } from '@/lib/mirofishApi';

const agentCounts = [3, 7, 10, 15];
const defaultTarget = '삼성전자';

const layerColors: Record<string, string> = {
    TARGET: 'bg-red-500',
    'CAUSAL HISTORY': 'bg-blue-500',
    'AI ANALYSTS': 'bg-violet-500',
    PREDICTIONS: 'bg-orange-400',
    VERDICT: 'bg-emerald-400',
};

function createEmptyRun(target = defaultTarget): MiroFishRun {
    return {
        target,
        display_name: target,
        status: 'idle',
        layers: [],
        logs: [],
        analysts: [],
        graph_nodes: [],
        prediction_nodes: [],
    };
}

const impactSteps = [
    { no: '01', ko: '대상 입력', en: 'TARGET', icon: 'fa-search' },
    { no: '02', ko: 'Brain 13D', en: 'BRAIN', icon: 'fa-brain' },
    { no: '03', ko: '그래프 추출', en: 'GRAPHRAG', icon: 'fa-link' },
    { no: '04', ko: '에이전트 토론', en: 'DEBATE', icon: 'fa-users' },
    { no: '05', ko: 'CIO 판정', en: 'VERDICT', icon: 'fa-gavel' },
];

const runSteps = ['입력', 'Brain 13D', 'GraphRAG', '에이전트', '리포트'];
const runStepEndpoints: EndpointKey[] = ['resolve', 'runDetail', 'graph', 'events', 'report'];
const phaseNumberById: Record<string, number> = {
    intake: 1,
    brain_snapshot: 2,
    graph_build: 3,
    analyst_mesh: 4,
    verdict: 5,
    report: 5,
};
type ApiState = 'checking' | 'ready' | 'error' | 'running';
type EndpointKey = 'status' | 'dataSources' | 'resolve' | 'history' | 'createRun' | 'runDetail' | 'graph' | 'events' | 'report';
type EndpointStatus = 'idle' | 'loading' | 'ok' | 'error';
type TargetCandidate = NonNullable<MiroFishTargetSnapshot['candidates']>[number];

const endpointDefinitions: Array<{ key: EndpointKey; method: string; path: string; title: string; icon: string; color: string }> = [
    { key: 'status', method: 'GET', path: '/api/admin/mirofish/status', title: 'Service Status', icon: 'fa-satellite-dish', color: 'text-cyan-300' },
    { key: 'dataSources', method: 'GET', path: '/api/admin/mirofish/data-sources', title: 'Data Sources', icon: 'fa-database', color: 'text-teal-300' },
    { key: 'resolve', method: 'GET', path: '/api/admin/mirofish/targets/resolve', title: 'Target Resolve', icon: 'fa-crosshairs', color: 'text-blue-300' },
    { key: 'history', method: 'GET', path: '/api/admin/mirofish/runs', title: 'Run History', icon: 'fa-clock-rotate-left', color: 'text-slate-300' },
    { key: 'createRun', method: 'POST', path: '/api/admin/mirofish/runs', title: 'Create Run', icon: 'fa-play', color: 'text-violet-300' },
    { key: 'runDetail', method: 'GET', path: '/api/admin/mirofish/runs/{id}', title: 'Run Detail', icon: 'fa-file-code', color: 'text-indigo-300' },
    { key: 'graph', method: 'GET', path: '/api/admin/mirofish/runs/{id}/graph', title: 'Graph Artifact', icon: 'fa-project-diagram', color: 'text-emerald-300' },
    { key: 'events', method: 'GET', path: '/api/admin/mirofish/runs/{id}/events', title: 'Event Feed', icon: 'fa-stream', color: 'text-amber-300' },
    { key: 'report', method: 'GET', path: '/api/admin/mirofish/runs/{id}/report', title: 'Report', icon: 'fa-scroll', color: 'text-rose-300' },
];

function clampCount(value: unknown, fallback: number) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
}

function verdictTone(verdict?: string) {
    const upper = (verdict || '').toUpperCase();
    if (upper.includes('BULL') || upper === 'BUY') return 'border-emerald-400 bg-emerald-500/10 text-emerald-500';
    if (upper.includes('BEAR') || upper === 'SELL') return 'border-rose-400 bg-rose-500/10 text-rose-500';
    return 'border-amber-400 bg-amber-500/10 text-amber-500';
}

function endpointStatusTone(state: EndpointStatus) {
    if (state === 'ok') return 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300';
    if (state === 'loading') return 'border-cyan-400/20 bg-cyan-400/10 text-cyan-300';
    if (state === 'error') return 'border-rose-400/20 bg-rose-400/10 text-rose-300';
    return 'border-white/10 bg-white/[0.04] text-gray-500';
}

function targetCandidateLabel(candidate?: TargetCandidate | null): string {
    return String(candidate?.display_name || candidate?.name || candidate?.symbol || '').trim();
}

function targetCandidateStartValue(candidate?: TargetCandidate | null): string {
    return targetCandidateLabel(candidate) || String(candidate?.symbol || '').trim();
}

function targetCandidateMatchLabel(candidate?: TargetCandidate | null): string {
    const matchType = String(candidate?.match_type || '');
    if (matchType.includes('initial')) return '초성';
    if (matchType.includes('exact')) return '정확';
    if (matchType.includes('prefix')) return '시작';
    if (matchType.includes('symbol')) return '코드';
    if (matchType.includes('alias')) return '별칭';
    return '관련';
}

function phaseFromRunState(run: MiroFishRun): number {
    if (run.status === 'completed') return 5;
    const phaseId = run.progress?.current_phase || run.events?.[run.events.length - 1]?.phase;
    if (phaseId && phaseNumberById[phaseId]) return phaseNumberById[phaseId];
    const percent = Number(run.progress?.percent || 0);
    if (percent >= 82) return 5;
    if (percent >= 62) return 4;
    if (percent >= 40) return 3;
    if (percent >= 20) return 2;
    return 1;
}

function isTerminalRun(run: MiroFishRun): boolean {
    return run.status === 'completed' || run.status === 'failed';
}

function formatElapsed(ms?: number) {
    const seconds = Math.max(0, Math.round((ms || 0) / 100) / 10);
    return `${seconds.toFixed(1)}s`;
}

function formatPrice(value: unknown): string {
    const numeric = typeof value === 'number'
        ? value
        : typeof value === 'string'
            ? Number(value.replace(/,/g, ''))
            : NaN;
    return Number.isFinite(numeric) ? numeric.toLocaleString('ko-KR') : '--';
}

function visibleLayers(run: MiroFishRun, phase: number): MiroFishLayer[] {
    const base = run.layers?.length
        ? run.layers
        : [
            { label: 'TARGET', count: run.target ? 1 : 0 },
            { label: 'CAUSAL HISTORY', count: run.graph_nodes?.length || 0 },
            { label: 'AI ANALYSTS', count: run.analysts?.length || 0 },
            { label: 'PREDICTIONS', count: run.prediction_nodes?.length || 0 },
            { label: 'VERDICT', count: run.verdict ? 1 : 0 },
        ];
    return base.map((layer) => {
        const label = layer.label.toUpperCase();
        const count = phase < 3 && label !== 'TARGET'
            ? 0
            : phase < 4 && label === 'PREDICTIONS'
                ? 0
                : phase < 5 && label === 'VERDICT'
                    ? 0
                    : layer.count;
        return { ...layer, label, count, color: layer.color || layerColors[label] || 'bg-slate-400' };
    });
}

function visibleLogs(run: MiroFishRun, phase: number): MiroFishLog[] {
    const logs = run.logs?.length ? run.logs : [];
    return logs.filter((log) => (log.phase || 1) <= phase);
}

function feedToneClass(tone?: string): string {
    if (!tone) return 'text-blue-800';
    if (tone.includes('cyan')) return 'text-cyan-800';
    if (tone.includes('teal')) return 'text-teal-800';
    if (tone.includes('violet')) return 'text-violet-800';
    if (tone.includes('emerald')) return 'text-emerald-800';
    if (tone.includes('rose') || tone.includes('red')) return 'text-rose-800';
    if (tone.includes('amber') || tone.includes('yellow')) return 'text-amber-800';
    if (tone.includes('blue')) return 'text-blue-800';
    return 'text-slate-800';
}

function analystPositions(analysts: MiroFishAnalyst[]): MiroFishNode[] {
    const xs = [31, 43, 55, 67, 76, 83, 89, 24, 50, 71];
    return analysts.map((analyst, index) => ({
        label: analyst.name,
        x: xs[index] ?? 50,
        y: index > 6 ? 82 : 75 + (index % 2),
    }));
}

function Stepper({ phase }: { phase: number }) {
    return (
        <section className="rounded-xl border border-white/30 bg-white/[0.86] p-5 text-slate-900 shadow-[0_22px_80px_rgba(124,58,237,0.18)]">
            <div className="relative grid gap-3 md:grid-cols-5">
                <div className="absolute left-[10%] right-[10%] top-12 hidden h-px bg-slate-300/70 md:block" />
                {impactSteps.map((step, index) => {
                    const active = index + 1 <= phase;
                    return (
                        <div key={step.no} className="relative flex flex-col items-center text-center">
                            <div className={`grid h-[72px] w-[72px] place-items-center rounded-2xl border text-sm font-black shadow-lg ${active ? 'border-blue-300 bg-gradient-to-br from-blue-500 to-violet-600 text-white ring-8 ring-blue-300/25' : 'border-slate-200 bg-white/90 text-slate-300'}`}>
                                {active ? <i className={`fas ${step.icon}`} /> : step.no}
                            </div>
                            <div className={`mt-3 text-xs font-black ${active ? 'text-slate-900' : 'text-slate-300'}`}>{step.ko}</div>
                            <div className={`mt-0.5 text-[10px] font-bold tracking-[0.18em] ${active ? 'text-blue-500' : 'text-slate-300'}`}>{step.en}</div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function TargetCard({ run }: { run: MiroFishRun }) {
    const change = Number(run.change_pct ?? 0);
    const price = formatPrice(run.price);
    return (
        <section className="rounded-xl border border-white/30 bg-white/[0.88] p-6 text-slate-900 shadow-[0_22px_80px_rgba(14,165,233,0.12)]">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-slate-400">
                        분석 대상
                        <span className="h-2 w-2 rounded-full bg-violet-600" />
                        <span className="text-violet-600">실시간 스트리밍</span>
                        <i className="fas fa-signal text-violet-500" />
                    </div>
                    <h2 className="mt-2 break-words text-4xl font-black tracking-tight">{run.display_name || run.target}</h2>
                    <div className="mt-5 h-1.5 w-72 max-w-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400" />
                </div>
                <div className="text-left md:text-right">
                    <div className="text-5xl font-black tracking-tight">{price}<span className="ml-2 text-lg font-bold text-slate-400">KRW</span></div>
                    <div className={`mt-2 inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-black ${change >= 0 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'}`}>
                        <i className={`fas ${change >= 0 ? 'fa-caret-up' : 'fa-caret-down'}`} />
                        {change.toFixed(2)}%
                    </div>
                </div>
            </div>
        </section>
    );
}

function KnowledgeGraph({ phase, run }: { phase: number; run: MiroFishRun }) {
    const isGraphReady = phase >= 3;
    const isPredictionReady = phase >= 4;
    const isVerdictReady = phase >= 5;
    const layers = visibleLayers(run, phase);
    const graphNodes = run.graph_nodes?.length ? run.graph_nodes : [];
    const analysts = run.analysts?.length ? run.analysts : [];
    const analystNodes = analystPositions(analysts);
    const predictionNodes = run.prediction_nodes?.length ? run.prediction_nodes : [];
    const verdict = run.verdict;
    const progressPercent = Math.max(0, Math.min(100, Number(run.progress?.percent || (isVerdictReady ? 100 : phase * 18))));
    const elapsedMs = run.progress?.elapsed_ms || run.performance?.elapsed_ms || 0;
    const elapsedSeconds = Math.max(1, elapsedMs / 1000);
    const eventCount = run.events?.length || run.logs?.length || run.performance?.events_count || 0;
    const edgeCount = run.graph_artifact?.edges?.length || run.performance?.graph_edges || 0;
    const streamRate = Math.max(1, Math.round((graphNodes.length + predictionNodes.length + analysts.length + edgeCount) / elapsedSeconds));
    const confidence = verdict?.confidence ?? (isVerdictReady ? 64 : Math.min(88, 42 + progressPercent));
    const activePhase = run.progress?.current_label || (phase >= 5 ? 'Final Verdict' : phase >= 4 ? 'Agent Debate' : phase >= 3 ? 'GraphRAG' : 'Target Intake');
    const graphLoad = Math.min(100, Math.round(((graphNodes.length + edgeCount) / Math.max(1, graphNodes.length + edgeCount + 8)) * 100));

    return (
        <section className="relative min-h-[500px] overflow-hidden rounded-xl border border-white/30 bg-[radial-gradient(circle_at_58%_70%,rgba(16,185,129,0.16),transparent_22%),radial-gradient(circle_at_28%_26%,rgba(99,102,241,0.16),transparent_24%),linear-gradient(180deg,rgba(248,250,252,0.96),rgba(226,232,240,0.94))] p-5 text-slate-900 shadow-[0_26px_90px_rgba(15,23,42,0.18)]">
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.13)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.11)_1px,transparent_1px)] bg-[size:44px_44px]" />
            <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/65 to-transparent" />
            {isGraphReady && (
                <div
                    className="pointer-events-none absolute left-0 right-0 z-[1] h-px bg-gradient-to-r from-transparent via-blue-500/70 to-transparent shadow-[0_0_28px_rgba(59,130,246,0.75)] transition-all duration-700"
                    style={{ top: `${Math.min(88, Math.max(15, progressPercent))}%` }}
                />
            )}
            <div className="absolute left-5 top-5 z-20 w-48 rounded-xl bg-white/80 p-4 shadow-xl shadow-slate-300/30">
                <div className="mb-3 text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">레이어</div>
                <div className="space-y-3">
                    {layers.map((layer) => (
                        <div key={layer.label} className="flex items-center gap-3 text-xs font-black">
                            <span className={`h-3 w-3 rounded-full ${layer.color} shadow`} />
                            <span className="flex-1">{layer.label}</span>
                            <span className="text-slate-500">{layer.count}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="absolute left-1/2 top-6 z-20 -translate-x-1/2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-500 shadow">
                지식 그래프 <span className="ml-2 inline-block h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div className="absolute right-5 top-20 z-30 w-56 rounded-2xl border border-slate-200/80 bg-white/88 p-4 shadow-2xl shadow-slate-400/20 backdrop-blur">
                <div className="flex items-center justify-between">
                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-slate-400">Live Compute</div>
                    <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-black text-emerald-700">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                        STREAM
                    </span>
                </div>
                <div className="mt-3 text-sm font-black text-slate-900">{activePhase}</div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400 transition-all duration-500" style={{ width: `${progressPercent}%` }} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] font-black">
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">PROGRESS</div><div className="text-blue-700">{progressPercent}%</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">RATE</div><div className="text-violet-700">{streamRate}/s</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">GRAPH</div><div className="text-emerald-700">{graphNodes.length}/{edgeCount}</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">CONF</div><div className="text-amber-700">{Math.round(confidence)}%</div></div>
                </div>
            </div>
            {isPredictionReady && (
                <div className="absolute right-40 top-6 z-20 hidden items-center gap-2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.12em] text-slate-500 shadow lg:flex">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    <span>강세 <b className="text-emerald-500">{verdict?.bullish ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-amber-400" />
                    <span>중립 <b className="text-amber-500">{verdict?.neutral ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-rose-500" />
                    <span>약세 <b className="text-rose-500">{verdict?.bearish ?? 0}</b></span>
                </div>
            )}

            {isGraphReady ? (
                <>
                    <svg className="absolute inset-0 z-[2] h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                        {graphNodes.map((node, index) => (
                            <line key={`${node.label}-${index}`} x1="30" y1="31" x2={node.x ?? 50} y2={node.y ?? 50} stroke="rgba(99,102,241,0.42)" strokeWidth="0.34" strokeDasharray="1.1 1.4">
                                <animate attributeName="stroke-dashoffset" from="0" to="-8" dur={`${2.1 + (index % 5) * 0.18}s`} repeatCount="indefinite" />
                            </line>
                        ))}
                        {isPredictionReady && predictionNodes.map((node, index) => {
                            const source = analystNodes[index] ?? analystNodes[0];
                            return (
                                <line key={`pred-${node.label}`} x1={source.x} y1={source.y} x2={node.x ?? 50} y2={node.y ?? 65} stroke="rgba(245,158,11,0.48)" strokeWidth="0.42" strokeDasharray="1.3 1.6">
                                    <animate attributeName="stroke-dashoffset" from="0" to="-9" dur={`${1.7 + (index % 4) * 0.16}s`} repeatCount="indefinite" />
                                </line>
                            );
                        })}
                        {isVerdictReady && predictionNodes.map((node) => (
                            <line key={`verdict-${node.label}`} x1={node.x ?? 50} y1={node.y ?? 65} x2="58" y2="92" stroke="rgba(16,185,129,0.52)" strokeWidth="0.48" strokeDasharray="1.4 1.2">
                                <animate attributeName="stroke-dashoffset" from="0" to="-10" dur="1.65s" repeatCount="indefinite" />
                            </line>
                        ))}
                    </svg>

                    <div className="absolute left-[30%] top-[31%] z-10 -translate-x-1/2 -translate-y-1/2 text-center">
                        <div className="absolute left-1/2 top-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 animate-ping rounded-full border border-red-400/35" />
                        <div className="relative grid h-16 w-16 place-items-center rounded-full border-2 border-red-400 bg-red-500/15 text-red-500 shadow-[0_0_0_8px_rgba(248,113,113,0.13),0_0_36px_rgba(248,113,113,0.30)]">
                            <i className="fas fa-warning" />
                        </div>
                        <div className="-mt-1 max-w-[140px] truncate rounded border border-red-300 bg-white px-2 py-0.5 text-[10px] font-black">{run.display_name || run.target}</div>
                    </div>

                    {graphNodes.map((node, index) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 50}%` }}>
                            <div className="mx-auto h-5 w-5 animate-pulse rounded-full border-2 border-indigo-400 bg-indigo-300/45 shadow-[0_0_18px_rgba(99,102,241,0.28)]" style={{ animationDelay: `${(index % 6) * 120}ms` }} />
                            <div className="-mt-0.5 max-w-[78px] truncate rounded border border-indigo-200 bg-white px-1.5 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {analystNodes.map((node, index) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x}%`, top: `${node.y}%` }}>
                            <div className="mx-auto h-8 w-8 animate-pulse rounded-full border-2 border-violet-400 bg-violet-300/45 shadow-[0_0_22px_rgba(139,92,246,0.26)]" style={{ animationDelay: `${(index % 5) * 150}ms` }} />
                            <div className="-mt-0.5 max-w-[84px] truncate rounded border border-violet-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isPredictionReady && predictionNodes.map((node) => (
                        <div key={node.label} className="absolute z-20 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 65}%` }}>
                            <div className={`mx-auto h-7 w-7 rounded-full border-2 ${node.verdict === 'bull' ? 'border-emerald-400 bg-emerald-300/40' : node.verdict === 'bear' ? 'border-rose-400 bg-rose-300/40' : 'border-amber-400 bg-amber-300/40'}`} />
                            <div className="max-w-[96px] truncate rounded border border-orange-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isVerdictReady && (
                        <div className="absolute left-[58%] top-[92%] z-30 -translate-x-1/2 -translate-y-1/2 text-center">
                            <div className="mx-auto h-20 w-20 rounded-full border-4 border-emerald-400 bg-emerald-300/45 shadow-[0_0_0_10px_rgba(16,185,129,0.12),0_0_42px_rgba(16,185,129,0.38)]" />
                            <div className="-mt-1 rounded border border-emerald-300 bg-white px-3 py-1 text-sm font-black text-emerald-600">{verdict?.label || 'HOLD'}</div>
                        </div>
                    )}
                    <div className="absolute bottom-5 left-5 right-5 z-30 grid gap-2 rounded-2xl border border-white/60 bg-white/80 p-3 shadow-xl shadow-slate-400/20 backdrop-blur md:grid-cols-4">
                        {[
                            { label: 'GRAPH LOAD', value: `${graphLoad}%`, bar: graphLoad, color: 'from-blue-500 to-indigo-500' },
                            { label: 'EVENTS', value: eventCount, bar: Math.min(100, eventCount * 8), color: 'from-cyan-500 to-teal-400' },
                            { label: 'ANALYST MESH', value: analysts.length, bar: Math.min(100, analysts.length * 10), color: 'from-violet-500 to-fuchsia-500' },
                            { label: 'VERDICT CONF', value: `${Math.round(confidence)}%`, bar: Math.round(confidence), color: 'from-emerald-500 to-lime-400' },
                        ].map((metric) => (
                            <div key={metric.label} className="min-w-0">
                                <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">
                                    <span>{metric.label}</span>
                                    <span className="text-slate-900">{metric.value}</span>
                                </div>
                                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
                                    <div className={`h-full rounded-full bg-gradient-to-r ${metric.color} transition-all duration-700`} style={{ width: `${metric.bar}%` }} />
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            ) : (
                <>
                    <div className="absolute inset-x-12 bottom-8 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
                    <div className="absolute bottom-5 right-5 text-xs font-bold text-slate-300">Waiting for graph nodes</div>
                </>
            )}
        </section>
    );
}

function FeedPanel({ phase, run }: { phase: number; run: MiroFishRun }) {
    const logs = visibleLogs(run, phase);
    return (
        <section className="min-h-[430px] rounded-xl border border-slate-300/70 bg-white/[0.94] p-5 text-slate-950 shadow-[0_18px_70px_rgba(15,23,42,0.12)]">
            <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-red-400" />
                    <span className="h-3 w-3 rounded-full bg-yellow-400" />
                    <span className="h-3 w-3 rounded-full bg-emerald-400" />
                    <span className="ml-2 text-[11px] font-black uppercase tracking-[0.2em] text-slate-600">Feed</span>
                </div>
                <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs font-black text-white">{logs.length}</span>
            </div>
            <div className="space-y-4 font-mono text-sm leading-6">
                {logs.map((log, index) => (
                    <div key={`${log.time || index}-${log.text}`} className="flex gap-3">
                        <span className="shrink-0 font-bold text-slate-500">{log.time || 'live'}</span>
                        <span className={`font-black ${feedToneClass(log.tone)}`}>{log.text}</span>
                    </div>
                ))}
                {phase < 5 && <div className="h-5 w-1.5 animate-pulse rounded bg-blue-500" />}
            </div>
        </section>
    );
}

function ProgressPerformancePanel({ run, apiState }: { run: MiroFishRun; apiState: ApiState }) {
    const percent = Math.max(0, Math.min(100, Number(run.progress?.percent || (apiState === 'running' ? 2 : 0))));
    const elapsed = run.progress?.elapsed_ms || run.performance?.elapsed_ms || 0;
    const eventCount = run.events?.length || run.logs?.length || run.performance?.events_count || 0;
    const graphNodes = run.graph_artifact?.nodes?.length || run.performance?.graph_nodes || run.graph_nodes?.length || 0;
    const graphEdges = run.graph_artifact?.edges?.length || run.performance?.graph_edges || 0;
    const currentLabel = run.progress?.current_label || run.progress?.current_phase || run.status || 'waiting';
    const phaseDurations = run.performance?.phase_durations_ms || {};

    return (
        <section className="rounded-xl border border-white/20 bg-white/[0.88] p-4 text-slate-900 shadow-[0_18px_70px_rgba(59,130,246,0.14)]">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                    <div className="text-[11px] font-black uppercase tracking-[0.22em] text-slate-400">Live Pipeline Performance</div>
                    <div className="mt-1 text-xl font-black text-slate-900">{currentLabel}</div>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs font-black">
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">진행</div><div className="text-blue-600">{percent}%</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">경과</div><div className="text-violet-600">{formatElapsed(elapsed)}</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">그래프</div><div className="text-emerald-600">{graphNodes}/{graphEdges}</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">이벤트</div><div className="text-amber-600">{eventCount}</div></div>
                </div>
            </div>
            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400 transition-all duration-500" style={{ width: `${percent}%` }} />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-6">
                {impactSteps.map((step) => {
                    const phaseId = Object.keys(phaseNumberById).find((key) => phaseNumberById[key] === Number(step.no));
                    const duration = phaseId ? phaseDurations[phaseId] : undefined;
                    const active = phaseFromRunState(run) >= Number(step.no);
                    return (
                        <div key={step.no} className={`rounded-lg border px-3 py-2 text-[11px] font-black ${active ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white/60 text-slate-400'}`}>
                            <div>{step.ko}</div>
                            <div className="mt-1 font-mono text-[10px] opacity-70">{duration === undefined ? '--' : formatElapsed(duration)}</div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function SignalSummaryCard({ run }: { run: MiroFishRun }) {
    const score = run.brain?.score;
    const scoreValue = clampCount(score, 0);
    return (
        <section className="max-w-3xl rounded-xl border border-white/30 bg-white/90 p-4 text-slate-900 shadow-[0_18px_70px_rgba(124,58,237,0.16)]">
            <div className="flex items-center gap-5">
                <div className="grid h-24 w-24 shrink-0 place-items-center rounded-full border-4 border-blue-200 bg-blue-50 text-center shadow-inner">
                    <div>
                        <div className="text-2xl font-black text-blue-600">{score === undefined ? '--' : scoreValue}</div>
                        <div className="text-[10px] font-bold text-slate-400">/100</div>
                    </div>
                </div>
                <div className="min-w-0 flex-1">
                    <div className="text-lg font-black text-blue-700">Brain 시그널 요약</div>
                    <div className="mt-3 grid grid-cols-2 gap-4 text-xs font-bold text-slate-400 sm:grid-cols-4">
                        <span>체제</span>
                        <span className="text-slate-700">{run.brain?.regime || 'neutral'}</span>
                        <span>위기 단계</span>
                        <span className="text-slate-700">{run.brain?.crisis || 'Lv.2'}</span>
                    </div>
                    <div className="mt-5 h-2 rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-gradient-to-r from-blue-400 via-violet-400 to-emerald-300" style={{ width: `${Math.min(100, Math.max(0, scoreValue))}%` }} />
                    </div>
                </div>
            </div>
        </section>
    );
}

function FinalVerdictPanel({ run }: { run: MiroFishRun }) {
    const verdict = run.verdict;
    return (
        <section className="relative overflow-hidden rounded-xl border border-emerald-200/20 bg-emerald-700 p-8 text-white shadow-[0_26px_90px_rgba(16,185,129,0.22)] md:p-12">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_36%,rgba(255,255,255,0.22),rgba(255,255,255,0)_24%),linear-gradient(135deg,rgba(6,95,70,0.9),rgba(5,150,105,0.95))]" />
            <div className="relative mx-auto flex min-h-[430px] max-w-5xl flex-col items-center justify-center text-center">
                <div className="mb-6 flex items-center gap-4 text-[11px] font-black uppercase tracking-[0.45em] text-emerald-100/50">
                    <span>최종 판정</span>
                    <span className="h-px w-12 bg-emerald-100/30" />
                </div>
                <h2 className="text-[76px] font-black leading-none tracking-tight text-white md:text-[152px]">{verdict?.label || 'HOLD'}</h2>
                <p className="mt-7 text-base font-bold text-emerald-50/65 md:text-lg">{verdict?.summary || 'MiroFish 실데이터 판정이 도착했습니다.'}</p>
                <div className="mt-10 grid h-36 w-36 place-items-center rounded-full border-[7px] border-white/90 bg-white/5 shadow-[0_0_60px_rgba(255,255,255,0.16)]">
                    <div>
                        <div className="text-[11px] font-black uppercase tracking-[0.28em] text-emerald-50/45">확신도</div>
                        <div className="text-4xl font-black text-white">{verdict?.confidence ?? 64}%</div>
                    </div>
                </div>
                <div className="mt-10 grid w-full max-w-3xl grid-cols-2 gap-3 md:grid-cols-4">
                    {[
                        { label: '강세', value: verdict?.bullish ?? 0, color: 'text-emerald-100' },
                        { label: '약세', value: verdict?.bearish ?? 0, color: 'text-rose-200' },
                        { label: '중립', value: verdict?.neutral ?? 0, color: 'text-white' },
                        { label: '시계열', value: verdict?.horizon || '1M', color: 'text-white' },
                    ].map((stat) => (
                        <div key={stat.label} className="rounded-xl border border-white/15 bg-white/10 px-5 py-4 backdrop-blur">
                            <div className="text-[10px] font-black uppercase tracking-[0.25em] text-emerald-50/35">{stat.label}</div>
                            <div className={`mt-2 text-3xl font-black ${stat.color}`}>{stat.value}</div>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}

function ImpactPanel({ phase, run, apiState }: { phase: number; run: MiroFishRun; apiState: ApiState }) {
    const analysts = run.analysts?.length ? run.analysts : [];
    const verdict = run.verdict;
    return (
        <div className="space-y-4">
            <ProgressPerformancePanel run={run} apiState={apiState} />
            <Stepper phase={phase} />
            <TargetCard run={run} />
            {phase >= 5 && <SignalSummaryCard run={run} />}
            <div className="grid gap-4 lg:grid-cols-[1fr_0.64fr]">
                <KnowledgeGraph phase={phase} run={run} />
                <FeedPanel phase={phase} run={run} />
            </div>
            {phase >= 4 && (
                <section className="space-y-3">
                    <div className="flex items-center justify-between px-1">
                        <h2 className="text-sm font-black uppercase tracking-[0.18em] text-white/35">애널리스트 ({analysts.length})</h2>
                        <div className="text-xs font-black uppercase tracking-[0.16em]">
                            <span className="text-emerald-400">강세 {verdict?.bullish ?? 0}</span>
                            <span className="mx-3 text-white/25">|</span>
                            <span className="text-red-400">약세 {verdict?.bearish ?? 0}</span>
                        </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                        {analysts.map((card) => (
                            <div key={card.name} className={`rounded-xl border border-white/20 bg-white/90 p-4 text-slate-900 shadow-xl shadow-black/10 border-t-4 ${verdictTone(card.verdict).split(' ')[0]}`}>
                                <div className="flex items-center gap-3">
                                    <div className="grid h-12 w-12 place-items-center rounded-full bg-slate-100 ring-1 ring-slate-200">
                                        <i className={`fas ${card.icon || 'fa-user-tie'} text-slate-500`} />
                                    </div>
                                    <div className="min-w-0">
                                        <div className="font-black text-slate-900">{card.name}</div>
                                        <div className="truncate text-xs font-bold text-slate-400">{card.role || 'MiroFish analyst'}</div>
                                    </div>
                                </div>
                                <div className={`mt-4 inline-flex rounded-full px-2.5 py-1 text-[10px] font-black ${verdictTone(card.verdict).replace('border-emerald-400 ', '').replace('border-rose-400 ', '').replace('border-amber-400 ', '')}`}>
                                    {card.verdict || 'NEUTRAL'} {card.confidence ? `${card.confidence}%` : ''}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
            {phase >= 5 && <FinalVerdictPanel run={run} />}
        </div>
    );
}

export default function AdminEndpointsPage() {
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [phase, setPhase] = useState(1);
    const [target, setTarget] = useState(defaultTarget);
    const [agentCount, setAgentCount] = useState(10);
    const [run, setRun] = useState<MiroFishRun>(() => createEmptyRun());
    const [status, setStatus] = useState<MiroFishStatus | null>(null);
    const [targetSnapshot, setTargetSnapshot] = useState<MiroFishTargetSnapshot | null>(null);
    const [activeCandidateIndex, setActiveCandidateIndex] = useState(0);
    const [recentRuns, setRecentRuns] = useState<MiroFishRun[]>([]);
    const [dataSourceCount, setDataSourceCount] = useState(0);
    const [endpointState, setEndpointState] = useState<Record<EndpointKey, EndpointStatus>>(() => Object.fromEntries(endpointDefinitions.map((item) => [item.key, 'idle'])) as Record<EndpointKey, EndpointStatus>);
    const [apiState, setApiState] = useState<ApiState>('checking');
    const [errorText, setErrorText] = useState<string | null>(null);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);
    const lastStartAtRef = useRef(0);
    const targetValueRef = useRef(defaultTarget);
    const resolveRequestRef = useRef(0);
    const pendingCompositionStartRef = useRef(false);

    function markEndpoint(key: EndpointKey, state: EndpointStatus) {
        setEndpointState((current) => ({ ...current, [key]: state }));
    }

    useEffect(() => {
        let alive = true;
        async function boot() {
            markEndpoint('status', 'loading');
            markEndpoint('history', 'loading');
            markEndpoint('dataSources', 'loading');
            try {
                const [statusData, historyData, sourcesData] = await Promise.all([
                    mirofishApi.getStatus(),
                    mirofishApi.listRuns(),
                    mirofishApi.getDataSources(),
                ]);
                if (!alive) return;
                setStatus(statusData);
                setRecentRuns(historyData.runs);
                setDataSourceCount(Array.isArray(sourcesData?.files) ? sourcesData.files.filter((file: any) => file.exists).length : 0);
                setApiState('ready');
                markEndpoint('status', 'ok');
                markEndpoint('history', 'ok');
                markEndpoint('dataSources', 'ok');
                setRun((current) => ({ ...current, brain: statusData.brain || current.brain, pipeline: statusData.pipeline || current.pipeline }));
            } catch (error) {
                if (!alive) return;
                setApiState('error');
                setStatus({ ready: false, source: 'api unavailable', pipeline: { status: 'unavailable' } });
                markEndpoint('status', 'error');
                markEndpoint('history', 'error');
                markEndpoint('dataSources', 'error');
                setErrorText(error instanceof Error ? error.message : 'MiroFish API 연결 실패');
            }
        }
        boot();
        return () => {
            alive = false;
        };
    }, []);

    useEffect(() => {
        if (!activeRunId || !isAnalyzing) return;
        let alive = true;
        const runId = activeRunId;

        async function refreshRun() {
            try {
                const hydrated = await mirofishApi.hydrateRun(runId);
                if (!alive) return;
                setRun(hydrated);
                setPhase(phaseFromRunState(hydrated));
                markEndpoint('runDetail', 'ok');
                markEndpoint('graph', 'ok');
                markEndpoint('events', 'ok');
                if (hydrated.report?.markdown) markEndpoint('report', 'ok');

                if (hydrated.status === 'failed') {
                    setApiState('error');
                    setErrorText(hydrated.progress?.error || 'MiroFish run failed.');
                    setActiveRunId(null);
                    markEndpoint('createRun', 'error');
                    return;
                }

                if (hydrated.status === 'completed') {
                    setApiState('ready');
                    setActiveRunId(null);
                    setPhase(5);
                    mirofishApi.listRuns()
                        .then((data) => {
                            setRecentRuns(data.runs);
                            markEndpoint('history', 'ok');
                        })
                        .catch(() => markEndpoint('history', 'error'));
                }
            } catch (error) {
                if (!alive) return;
                setApiState('error');
                setErrorText(error instanceof Error ? error.message : 'MiroFish run polling failed.');
                markEndpoint('runDetail', 'error');
            }
        }

        refreshRun();
        const timer = window.setInterval(refreshRun, 1000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [activeRunId, isAnalyzing]);

    useEffect(() => {
        const nextTarget = target.trim();
        if (!nextTarget || apiState === 'running') return;
        let alive = true;
        const requestId = resolveRequestRef.current + 1;
        resolveRequestRef.current = requestId;
        markEndpoint('resolve', 'loading');
        const timer = window.setTimeout(() => {
            mirofishApi.resolveTarget(nextTarget)
                .then((snapshot) => {
                    if (!alive || resolveRequestRef.current !== requestId) return;
                    setTargetSnapshot(snapshot);
                    setActiveCandidateIndex(0);
                    markEndpoint('resolve', 'ok');
                })
                .catch(() => {
                    if (!alive || resolveRequestRef.current !== requestId) return;
                    setTargetSnapshot(null);
                    setActiveCandidateIndex(0);
                    markEndpoint('resolve', 'error');
                });
        }, 450);
        return () => {
            alive = false;
            window.clearTimeout(timer);
        };
    }, [target, apiState]);

    const brainSignals = useMemo(() => {
        const brain = status?.brain || run.brain;
        return [
            { label: 'BRAIN', value: brain?.score === undefined ? '--' : String(brain.score), tone: 'text-violet-300' },
            { label: 'REGIME', value: brain?.regime || '--', tone: 'text-slate-200' },
            { label: 'CRISIS', value: brain?.crisis || '--', tone: 'text-amber-300' },
        ];
    }, [run.brain, status]);

    const endpointMetrics = useMemo<Record<EndpointKey, string>>(() => ({
        status: status?.pipeline?.status || 'not loaded',
        dataSources: `${dataSourceCount} files`,
        resolve: targetSnapshot?.resolved?.symbol || targetSnapshot?.resolved?.asset_type || 'waiting',
        history: `${recentRuns.length} runs`,
        createRun: run.id ? String(run.status || 'created') : 'idle',
        runDetail: run.id ? String(run.id).slice(0, 24) : '{id}',
        graph: `${run.graph_artifact?.nodes?.length || 0} nodes / ${run.graph_artifact?.edges?.length || 0} edges`,
        events: `${run.events?.length || 0} events`,
        report: run.report?.markdown ? `${run.report.markdown.length} chars` : 'waiting',
    }), [dataSourceCount, recentRuns.length, run, status, targetSnapshot]);

    const targetCandidates = useMemo<TargetCandidate[]>(() => {
        const query = target.trim();
        if (!query || targetSnapshot?.target?.trim() !== query) return [];
        return (targetSnapshot.candidates || []).filter((candidate) => targetCandidateStartValue(candidate));
    }, [target, targetSnapshot]);

    const activeCandidate = targetCandidates[activeCandidateIndex] || targetCandidates[0] || null;

    function getStartTarget(inputValue?: string) {
        const typedTarget = (inputValue ?? targetValueRef.current ?? target).trim();
        if (activeCandidate) return targetCandidateStartValue(activeCandidate) || typedTarget || defaultTarget;
        return typedTarget || defaultTarget;
    }

    function selectTargetCandidate(candidate: TargetCandidate, shouldStart = false) {
        const nextTarget = targetCandidateStartValue(candidate);
        if (!nextTarget) return;
        targetValueRef.current = nextTarget;
        setTarget(nextTarget);
        setTargetSnapshot(null);
        setActiveCandidateIndex(0);
        markEndpoint('resolve', 'loading');
        if (shouldStart) requestStart(nextTarget);
    }

    function handleTargetKeyNavigation(event: ReactKeyboardEvent<HTMLInputElement>) {
        if (!targetCandidates.length) return;
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveCandidateIndex((index) => (index + 1) % targetCandidates.length);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveCandidateIndex((index) => (index - 1 + targetCandidates.length) % targetCandidates.length);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            setTargetSnapshot(null);
            setActiveCandidateIndex(0);
        }
    }

    async function handleStart(targetOverride?: string) {
        if (apiState === 'running') return;
        const nextTarget = (targetOverride ?? targetValueRef.current ?? target).trim() || defaultTarget;
        setErrorText(null);
        setIsAnalyzing(true);
        setApiState('running');
        setActiveRunId(null);
        setPhase(1);
        setRun({ ...createEmptyRun(nextTarget), status: 'running', progress: { percent: 1, current_phase: 'intake', current_label: 'Target Intake', elapsed_ms: 0 } });
        markEndpoint('createRun', 'loading');
        markEndpoint('runDetail', 'idle');
        markEndpoint('graph', 'idle');
        markEndpoint('events', 'idle');
        markEndpoint('report', 'idle');
        try {
            const data = await mirofishApi.startRun({ target: nextTarget, agent_count: agentCount, mode: 'full', async: true });
            const baseRun = { ...data, target: data.target || nextTarget, display_name: data.display_name || data.target || nextTarget };
            setRun(baseRun);
            setPhase(phaseFromRunState(baseRun));
            markEndpoint('createRun', 'ok');
            markEndpoint('runDetail', 'loading');
            markEndpoint('graph', 'loading');
            markEndpoint('events', 'loading');
            markEndpoint('report', 'loading');
            const runId = String(baseRun.id || '');
            if (!runId) throw new Error('MiroFish run id was not returned.');
            setActiveRunId(runId);
        } catch (error) {
            setIsAnalyzing(false);
            setActiveRunId(null);
            setRun((current) => ({ ...current, status: 'api_error' }));
            setApiState('error');
            markEndpoint('createRun', 'error');
            markEndpoint('runDetail', 'error');
            markEndpoint('graph', 'error');
            markEndpoint('events', 'error');
            markEndpoint('report', 'error');
            setErrorText(error instanceof Error ? error.message : 'MiroFish API unavailable. Live data was not loaded.');
        }
    }

    function requestStart(targetOverride?: string) {
        const now = Date.now();
        if (apiState === 'running' || now - lastStartAtRef.current < 600) return;
        lastStartAtRef.current = now;
        void handleStart(targetOverride);
    }

    function isEnterKey(event: ReactKeyboardEvent<HTMLElement>) {
        const native = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
        return event.key === 'Enter' || event.code === 'Enter' || event.key === 'NumpadEnter' || native.keyCode === 13;
    }

    function isComposing(event: ReactKeyboardEvent<HTMLElement> | ReactCompositionEvent<HTMLInputElement>) {
        const native = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
        return Boolean(native.isComposing || native.keyCode === 229);
    }

    return (
        <div className="space-y-5">
            <section className="relative overflow-hidden rounded-xl border border-white/[0.07] bg-[#111113]">
                <div className="absolute inset-0 bg-[linear-gradient(120deg,rgba(20,184,166,0.22),rgba(124,58,237,0.24)_46%,rgba(245,158,11,0.16))]" />
                <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(9,9,11,0.10),rgba(9,9,11,0.74))]" />

                <div className="relative px-5 py-7 md:px-8 md:py-10">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-bold text-white/80 backdrop-blur">
                            <i className="fas fa-lock text-red-300" />
                            관리자 전용 리서치 콘솔
                        </div>
                        <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold ${apiState === 'error' ? 'border-rose-300/20 bg-rose-300/10 text-rose-200' : 'border-cyan-300/20 bg-cyan-300/10 text-cyan-200'}`}>
                            <i className="fas fa-satellite-dish" />
                            {apiState === 'checking' ? 'MiroFish 점검 중' : apiState === 'running' ? '분석 실행 중' : apiState === 'error' ? 'API 오류' : 'MiroFish 준비됨'}
                        </div>
                    </div>

                    <div className="mt-8 max-w-4xl">
                        <h1 className="text-[40px] font-black leading-[0.98] tracking-tight text-white md:text-[72px]">
                            MiroFish Market Brain
                            <span className="block bg-gradient-to-r from-cyan-200 via-violet-300 to-amber-200 bg-clip-text text-transparent">
                                GraphRAG Analysis
                            </span>
                        </h1>
                        <p className="mt-5 max-w-2xl text-base font-semibold leading-7 text-slate-300 md:text-lg">
                            Brain 시그널 · 인과 메모리 · 5인 에이전트 토론 · CIO 판정을 관리자 MiroFish API 로 연결합니다.
                        </p>
                    </div>

                    <div className="mt-6 flex flex-wrap gap-2">
                        {brainSignals.map((signal) => (
                            <span key={signal.label} className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/80 px-4 py-2 text-xs font-black text-slate-500 shadow-lg shadow-black/10">
                                <span className="tracking-[0.18em]">{signal.label}</span>
                                <span className={`${signal.tone} text-sm`}>{signal.value}</span>
                            </span>
                        ))}
                    </div>

                    <form
                        className="mt-8 max-w-4xl rounded-xl border border-cyan-300/40 bg-white/90 p-2 shadow-[0_18px_70px_rgba(34,211,238,0.22)]"
                        onSubmit={(event) => {
                            event.preventDefault();
                            const formTarget = new FormData(event.currentTarget).get('target');
                            requestStart(getStartTarget(typeof formTarget === 'string' ? formTarget : targetValueRef.current));
                        }}
                        onKeyDownCapture={(event) => {
                            if (!isEnterKey(event)) return;
                            if (isComposing(event)) {
                                pendingCompositionStartRef.current = true;
                                return;
                            }
                            event.preventDefault();
                            event.stopPropagation();
                            const input = event.currentTarget.elements.namedItem('target') as HTMLInputElement | null;
                            requestStart(getStartTarget(input?.value));
                        }}
                        onKeyUpCapture={(event) => {
                            if (!isEnterKey(event) || isComposing(event)) return;
                            event.preventDefault();
                            event.stopPropagation();
                            const input = event.currentTarget.elements.namedItem('target') as HTMLInputElement | null;
                            requestStart(getStartTarget(input?.value));
                        }}
                    >
                        <div className="flex flex-col gap-2 sm:flex-row">
                            <label className="flex min-h-12 flex-1 items-center gap-3 px-3 text-slate-500">
                                <i className="fas fa-search text-lg" />
                                <input
                                    name="target"
                                    className="w-full bg-transparent text-base font-bold text-slate-900 outline-none placeholder:text-slate-400"
                                    placeholder="삼성전자, NVDA, BTC, FOMC 등 분석 대상 입력"
                                    value={target}
                                    onChange={(event) => {
                                        const nextTarget = event.target.value;
                                        targetValueRef.current = nextTarget;
                                        setTarget(nextTarget);
                                        setTargetSnapshot(null);
                                        setActiveCandidateIndex(0);
                                        markEndpoint('resolve', 'idle');
                                    }}
                                    onKeyDown={(event) => {
                                        handleTargetKeyNavigation(event);
                                    }}
                                    onCompositionEnd={(event) => {
                                        const shouldStart = pendingCompositionStartRef.current;
                                        pendingCompositionStartRef.current = false;
                                        const composedTarget = event.currentTarget.value;
                                        targetValueRef.current = composedTarget;
                                        if (shouldStart) window.setTimeout(() => requestStart(composedTarget), 0);
                                    }}
                                />
                            </label>
                            <button
                                type="submit"
                                disabled={apiState === 'running'}
                                className="min-h-12 rounded-lg bg-gradient-to-r from-blue-600 to-violet-600 px-6 text-sm font-black text-white shadow-lg shadow-violet-600/25 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-75"
                            >
                                {apiState === 'running' ? '분석 중' : '분석 시작'}
                            </button>
                        </div>
                    </form>

                    {targetCandidates.length > 0 && (
                        <div className="mt-2 max-w-4xl overflow-hidden rounded-xl border border-white/15 bg-slate-950/82 text-sm shadow-2xl shadow-black/25 backdrop-blur">
                            <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">
                                <span>Autocomplete</span>
                                <span>{targetCandidates.length} candidates</span>
                            </div>
                            <div className="max-h-72 overflow-y-auto p-1">
                                {targetCandidates.map((candidate, index) => {
                                    const active = index === activeCandidateIndex;
                                    const label = targetCandidateLabel(candidate);
                                    return (
                                        <button
                                            key={`${candidate.symbol}-${candidate.display_name}-${index}`}
                                            type="button"
                                            onMouseDown={(event) => event.preventDefault()}
                                            onClick={() => selectTargetCandidate(candidate)}
                                            onDoubleClick={() => selectTargetCandidate(candidate, true)}
                                            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${active ? 'bg-cyan-400/[0.14] text-white ring-1 ring-cyan-300/35' : 'text-slate-200 hover:bg-white/[0.08]'}`}
                                        >
                                            <span className={`grid h-8 w-8 place-items-center rounded-lg ${active ? 'bg-cyan-300 text-slate-950' : 'bg-white/10 text-cyan-200'}`}>
                                                <i className="fas fa-magnifying-glass-chart text-xs" />
                                            </span>
                                            <span className="min-w-0 flex-1">
                                                <span className="block truncate font-black">{label}</span>
                                                <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-400">
                                                    {candidate.symbol || 'keyword'} · {candidate.market || 'KR'} · {candidate.yahoo_ticker || 'ticker pending'}
                                                </span>
                                            </span>
                                            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${active ? 'border-cyan-200/60 bg-cyan-200/[0.18] text-cyan-50' : 'border-white/10 bg-white/5 text-slate-400'}`}>
                                                {targetCandidateMatchLabel(candidate)}
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {errorText && <div className="mt-3 max-w-4xl rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-xs font-bold text-amber-100">{errorText}</div>}

                    {targetSnapshot && (
                        <div className="mt-3 flex max-w-4xl flex-wrap gap-2 text-xs font-bold">
                            <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1.5 text-cyan-100">
                                {targetSnapshot.resolved?.display_name || targetSnapshot.target}
                            </span>
                            <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-slate-200">
                                {targetSnapshot.resolved?.symbol || 'keyword'} · {targetSnapshot.resolved?.market || 'UNKNOWN'}
                            </span>
                            <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1.5 text-emerald-100">
                                source files {targetSnapshot.source_files?.length || 0}
                            </span>
                            <span className="rounded-full border border-violet-300/20 bg-violet-300/10 px-3 py-1.5 text-violet-100">
                                signals {targetSnapshot.signal_count || 0}
                            </span>
                            {targetSnapshot.kis?.enabled && (
                                <span className={`rounded-full border px-3 py-1.5 ${targetSnapshot.kis.found ? 'border-cyan-300/20 bg-cyan-300/10 text-cyan-100' : 'border-slate-300/20 bg-white/10 text-slate-200'}`}>
                                    {targetSnapshot.kis.found ? 'KIS live' : 'KIS standby'}
                                </span>
                            )}
                        </div>
                    )}

                    <div className="mt-5 flex flex-wrap items-center gap-3">
                        <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/75 px-4 py-2 text-xs font-bold text-slate-500 backdrop-blur">
                            <span>에이전트</span>
                            <button type="button" onClick={() => setAgentCount((value) => Math.max(1, value - 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700">-</button>
                            <span className="text-xl font-black text-violet-600">{agentCount}</span>
                            <button type="button" onClick={() => setAgentCount((value) => Math.min(15, value + 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700">+</button>
                        </div>
                        <div className="flex items-center gap-1 rounded-xl border border-white/15 bg-white/45 p-1 backdrop-blur">
                            {agentCounts.map((count) => (
                                <button key={count} type="button" onClick={() => setAgentCount(count)} className={`h-8 min-w-8 rounded-lg px-2 text-xs font-black ${count === agentCount ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/30' : 'text-slate-500 hover:bg-white/60'}`}>
                                    {count}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </section>

            {isAnalyzing && <ImpactPanel phase={phase} run={run} apiState={apiState} />}

            <div className="grid gap-3 lg:grid-cols-3">
                {endpointDefinitions.map((endpoint) => {
                    const state = endpointState[endpoint.key];
                    return (
                        <section key={endpoint.key} className="rounded-xl border border-white/[0.07] bg-[#141416] p-5">
                            <div className="flex items-start justify-between gap-3">
                                <span className="grid h-10 w-10 place-items-center rounded-lg bg-white/[0.06]">
                                    <i className={`fas ${endpoint.icon} ${endpoint.color}`} />
                                </span>
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${endpointStatusTone(state)}`}>
                                    {state.toUpperCase()}
                                </span>
                            </div>
                            <h2 className="mt-4 text-lg font-black text-white">{endpoint.title}</h2>
                            <div className="mt-2 flex items-center gap-2 font-mono text-[11px] font-bold text-gray-500">
                                <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-cyan-200">{endpoint.method}</span>
                                <span className="truncate">{endpoint.path}</span>
                            </div>
                            <p className="mt-3 truncate text-sm font-bold text-gray-400">{endpointMetrics[endpoint.key]}</p>
                        </section>
                    );
                })}
            </div>

            <section className="rounded-xl border border-white/[0.07] bg-[#141416] p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 className="text-lg font-black text-white">파이프라인 상태</h2>
                        <p className="mt-1 text-sm text-gray-500">
                            {status?.pipeline?.status || '/api/admin/mirofish/status 응답 대기 중'}
                        </p>
                    </div>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${apiState === 'error' ? 'border-rose-500/20 bg-rose-500/10 text-rose-300' : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'}`}>
                        {apiState === 'error' ? 'API 오류' : 'API 연결'}
                    </span>
                </div>

                <div className="mt-5 grid gap-2 md:grid-cols-5">
                    {runSteps.map((step, index) => {
                        const linkedState = endpointState[runStepEndpoints[index]];
                        const ready = linkedState === 'ok' && (!isAnalyzing || index + 1 <= phase);
                        return (
                            <div key={step} className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-[11px] font-black uppercase tracking-[0.14em] text-gray-600">단계 {index + 1}</span>
                                    <span className={`h-2 w-2 rounded-full ${ready ? 'bg-emerald-400' : linkedState === 'error' ? 'bg-rose-400' : 'bg-amber-400/70'}`} />
                                </div>
                                <div className="mt-3 text-sm font-bold text-white">{step}</div>
                                <div className="mt-1 text-xs text-gray-500">{ready ? '엔드포인트 확인' : linkedState === 'error' ? '오류' : '대기 중'}</div>
                            </div>
                        );
                    })}
                </div>
            </section>
        </div>
    );
}
