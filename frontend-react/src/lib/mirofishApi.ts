import { fetchAuthAPI, postAuthAPI } from './api';

export type MiroFishVerdict = 'BUY' | 'SELL' | 'HOLD' | 'BULLISH' | 'BEARISH' | 'NEUTRAL';

export interface MiroFishLayer {
    label: string;
    count: number;
    color?: string;
}

export interface MiroFishLog {
    time?: string;
    text: string;
    tone?: string;
    phase?: number;
}

export interface MiroFishAnalyst {
    name: string;
    role?: string;
    verdict?: MiroFishVerdict | string;
    confidence?: number;
    icon?: string;
}

export interface MiroFishNode {
    label: string;
    x?: number;
    y?: number;
    kind?: 'target' | 'history' | 'analyst' | 'prediction' | 'verdict';
    verdict?: string;
}

export interface MiroFishGraphNode {
    id?: string;
    label?: string;
    type?: string;
    layer?: string;
    score?: number;
    [key: string]: any;
}

export interface MiroFishGraphEdge {
    source?: string;
    target?: string;
    label?: string;
    weight?: number;
    layer?: string;
    [key: string]: any;
}

export interface MiroFishGraphArtifact {
    run_id?: string;
    target?: string;
    source?: string;
    schema_version?: number;
    nodes: MiroFishGraphNode[];
    edges: MiroFishGraphEdge[];
    layers?: Array<Record<string, any>>;
}

export interface MiroFishReport {
    run_id?: string;
    format?: string;
    markdown: string;
}

export interface MiroFishEvent {
    ts?: string;
    level?: string;
    phase?: string;
    message?: string;
    payload?: Record<string, any>;
}

export interface MiroFishEventsResponse {
    run_id?: string;
    events: MiroFishEvent[];
    next_index?: number;
    total?: number;
    has_more?: boolean;
}

export interface MiroFishTargetSnapshot {
    target?: string;
    source?: string;
    resolved?: {
        input?: string;
        symbol?: string | null;
        name?: string;
        display_name?: string;
        market?: string;
        asset_type?: string;
    };
    price?: Record<string, any>;
    signals?: Record<string, any>;
    signal_count?: number;
    briefing_count?: number;
    dart_available?: boolean;
    source_files?: string[];
    built_at?: string;
}

export interface MiroFishRun {
    id?: string | number;
    target: string;
    display_name?: string;
    symbol?: string | null;
    market?: string | null;
    source?: string;
    price?: number | string;
    change_pct?: number;
    mode?: string;
    status?: string;
    layers?: MiroFishLayer[];
    logs?: MiroFishLog[];
    analysts?: MiroFishAnalyst[];
    graph_nodes?: MiroFishNode[];
    prediction_nodes?: MiroFishNode[];
    verdict?: {
        label?: MiroFishVerdict | string;
        confidence?: number;
        bullish?: number;
        bearish?: number;
        neutral?: number;
        horizon?: string;
        summary?: string;
    };
    brain?: {
        score?: number;
        regime?: string;
        crisis?: string;
    };
    pipeline?: {
        graph_links?: number;
        similar_events?: number;
        agent_count?: number;
        status?: string;
        graph_method?: string;
        debate_method?: string;
        cio_method?: string;
    };
    artifacts?: Record<string, string>;
    data_context?: {
        source_files?: string[];
        signals?: Record<string, any>;
        briefing_count?: number;
        dart_available?: boolean;
        built_at?: string;
    };
    graph_artifact?: MiroFishGraphArtifact;
    report?: MiroFishReport;
    events?: MiroFishEvent[];
}

export interface MiroFishStatus {
    ready?: boolean;
    source?: string;
    brain?: {
        score?: number;
        regime?: string;
        crisis?: string;
    };
    pipeline?: {
        graph_links?: number;
        similar_events?: number;
        agent_count?: number;
        status?: string;
    };
    updated_at?: string;
}

export interface StartMiroFishRunRequest {
    target: string;
    agent_count: number;
    mode: 'full' | string;
}

type RawObject = Record<string, any>;

const phaseByName: Record<string, number> = {
    intake: 1,
    brain_snapshot: 2,
    graph_build: 3,
    analyst_mesh: 4,
    verdict: 5,
    report: 5,
};

const toneByPhase: Record<number, string> = {
    1: 'text-blue-300',
    2: 'text-cyan-300',
    3: 'text-teal-400',
    4: 'text-violet-400',
    5: 'text-emerald-400',
};

const analystIcons = [
    'fa-compass',
    'fa-water',
    'fa-shield-halved',
    'fa-bolt',
    'fa-globe-asia',
    'fa-chart-line',
    'fa-coins',
    'fa-link',
    'fa-clipboard-check',
    'fa-clock',
];

function asObject(value: unknown): RawObject {
    return value && typeof value === 'object' ? value as RawObject : {};
}

function asNumber(value: unknown, fallback = 0): number {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
}

function asPercent(value: unknown, fallback = 0): number {
    const numberValue = asNumber(value, fallback);
    if (numberValue > 0 && numberValue <= 1) return Math.round(numberValue * 100);
    return Math.round(numberValue);
}

function normalizePhase(value: unknown, fallback = 1): number {
    if (typeof value === 'number') return value;
    const key = String(value || '').toLowerCase();
    return phaseByName[key] ?? fallback;
}

function normalizeBrain(rawValue: unknown): MiroFishRun['brain'] {
    const raw = asObject(rawValue);
    return {
        score: asPercent(raw.score ?? raw.alignment_score, 50),
        regime: String(raw.regime ?? 'neutral').replace(/_/g, ' '),
        crisis: String(raw.crisis ?? raw.crisis_level ?? 'Lv.2'),
    };
}

function normalizePipeline(rawValue: unknown, statusValue?: unknown): MiroFishStatus['pipeline'] {
    const raw = asObject(rawValue);
    return {
        graph_links: asNumber(raw.graph_links ?? raw.links, 0),
        similar_events: asNumber(raw.similar_events ?? raw.events, 0),
        agent_count: asNumber(raw.agent_count ?? raw.max_agent_count, 0),
        status: String(raw.status ?? statusValue ?? 'ready'),
    };
}

function normalizeAnalyst(rawValue: unknown, index: number): MiroFishAnalyst {
    const raw = asObject(rawValue);
    const stance = String(raw.verdict ?? raw.stance ?? 'NEUTRAL').toUpperCase();
    const verdict: MiroFishVerdict = stance === 'BUY'
        ? 'BULLISH'
        : stance === 'SELL'
            ? 'BEARISH'
            : stance === 'HOLD'
                ? 'NEUTRAL'
                : stance as MiroFishVerdict;

    return {
        name: String(raw.name ?? raw.id ?? `Agent ${index + 1}`),
        role: String(raw.role ?? raw.note ?? 'MiroFish analyst'),
        verdict,
        confidence: asPercent(raw.confidence, 60),
        icon: String(raw.icon ?? analystIcons[index % analystIcons.length] ?? 'fa-user-tie'),
    };
}

function normalizeAnalysts(rawValue: unknown): MiroFishAnalyst[] {
    return Array.isArray(rawValue) ? rawValue.map(normalizeAnalyst) : [];
}

function normalizeLog(rawValue: unknown, index: number): MiroFishLog {
    const raw = asObject(rawValue);
    const phase = normalizePhase(raw.phase, Math.min(5, index + 1));
    return {
        phase,
        time: String(raw.time ?? raw.timestamp ?? raw.created_at ?? 'live'),
        text: String(raw.text ?? raw.message ?? raw.event ?? 'MiroFish event'),
        tone: String(raw.tone ?? toneByPhase[phase] ?? 'text-blue-300'),
    };
}

function normalizeLogs(rawValue: unknown): MiroFishLog[] {
    return Array.isArray(rawValue) ? rawValue.map(normalizeLog) : [];
}

function normalizeNode(rawValue: unknown): MiroFishNode {
    const raw = asObject(rawValue);
    return {
        label: String(raw.label ?? raw.name ?? raw.id ?? 'node'),
        x: raw.x === undefined ? undefined : asNumber(raw.x),
        y: raw.y === undefined ? undefined : asNumber(raw.y),
        kind: raw.kind,
        verdict: raw.verdict,
    };
}

function normalizeNodes(rawValue: unknown): MiroFishNode[] | undefined {
    if (!Array.isArray(rawValue)) return undefined;
    return rawValue.map(normalizeNode);
}

function normalizeVerdict(rawValue: unknown, analysts: MiroFishAnalyst[]): MiroFishRun['verdict'] {
    const raw = asObject(rawValue);
    const label = String(raw.label ?? raw.action ?? 'HOLD').toUpperCase() as MiroFishVerdict;
    const bullish = raw.bullish ?? analysts.filter((analyst) => String(analyst.verdict).includes('BULL')).length;
    const bearish = raw.bearish ?? analysts.filter((analyst) => String(analyst.verdict).includes('BEAR')).length;
    const neutral = raw.neutral ?? analysts.filter((analyst) => String(analyst.verdict).includes('NEUT') || analyst.verdict === 'HOLD').length;

    return {
        label,
        confidence: asPercent(raw.confidence ?? raw.confidence_pct, 50),
        bullish: asNumber(bullish, 3),
        bearish: asNumber(bearish, 0),
        neutral: asNumber(neutral, 4),
        horizon: String(raw.horizon ?? raw.time_horizon ?? '1M').toUpperCase(),
        summary: String(raw.summary ?? `${bullish} analysts bullish, ${bearish} bearish, ${neutral} neutral.`),
    };
}

function normalizeLayers(
    rawValue: unknown,
    analysts: MiroFishAnalyst[],
    verdict?: MiroFishRun['verdict'],
    graphNodeCount = 0,
    predictionNodeCount = 0,
): MiroFishLayer[] {
    if (Array.isArray(rawValue) && rawValue.length > 0) {
        return rawValue.map((layer) => {
            const raw = asObject(layer);
            return {
                label: String(raw.label ?? raw.name ?? 'LAYER').toUpperCase(),
                count: asNumber(raw.count, 0),
                color: raw.color,
            };
        });
    }

    return [
        { label: 'TARGET', count: 1 },
        { label: 'CAUSAL HISTORY', count: graphNodeCount },
        { label: 'AI ANALYSTS', count: analysts.length },
        { label: 'PREDICTIONS', count: predictionNodeCount },
        { label: 'VERDICT', count: verdict ? 1 : 0 },
    ];
}

function normalizePredictionNodes(rawValue: unknown, analysts: MiroFishAnalyst[]): MiroFishNode[] | undefined {
    const nodes = normalizeNodes(rawValue);
    if (nodes?.length) return nodes;
    if (!analysts.length) return undefined;

    const xs = [40, 35, 43, 56, 70, 75, 81, 30, 50, 67];
    return analysts.slice(0, 10).map((analyst, index) => {
        const verdict = String(analyst.verdict || '').toLowerCase();
        return {
            label: `${analyst.name} ${analyst.verdict || 'NEUTRAL'}`,
            x: xs[index] ?? 50,
            y: 65 + ((index % 4) * 3),
            verdict: verdict.includes('bull') ? 'bull' : verdict.includes('bear') ? 'bear' : 'neutral',
        };
    });
}

const graphCoords = [
    [35, 42], [42, 38], [50, 40], [58, 37], [66, 43], [72, 48],
    [62, 54], [53, 57], [44, 55], [36, 59], [29, 50], [77, 56],
    [69, 62], [48, 64], [40, 68], [57, 48], [73, 38], [31, 66],
];

function normalizeGraph(payload: any): MiroFishGraphArtifact {
    const raw = asObject(payload);
    return {
        ...raw,
        run_id: raw.run_id,
        target: raw.target,
        source: raw.source,
        schema_version: asNumber(raw.schema_version, 1),
        nodes: Array.isArray(raw.nodes) ? raw.nodes.map((node) => asObject(node) as MiroFishGraphNode) : [],
        edges: Array.isArray(raw.edges) ? raw.edges.map((edge) => asObject(edge) as MiroFishGraphEdge) : [],
        layers: Array.isArray(raw.layers) ? raw.layers.map((layer) => asObject(layer)) : [],
    };
}

function nodesFromGraphArtifact(graph?: MiroFishGraphArtifact): MiroFishNode[] {
    if (!graph?.nodes?.length) return [];
    return graph.nodes
        .filter((node) => {
            const type = String(node.type || '').toLowerCase();
            return !['target', 'brain', 'verdict', 'analyst'].includes(type);
        })
        .slice(0, 24)
        .map((node, index) => {
            const coord = graphCoords[index % graphCoords.length] ?? [50, 50];
            const yOffset = index >= graphCoords.length ? 8 : 0;
            return {
                label: String(node.label || node.id || 'node'),
                x: coord[0],
                y: Math.min(74, coord[1] + yOffset),
                kind: 'history',
            };
        });
}

function normalizeReport(payload: any): MiroFishReport {
    const raw = asObject(payload);
    return {
        run_id: raw.run_id,
        format: String(raw.format || 'markdown'),
        markdown: String(raw.markdown || ''),
    };
}

function normalizeEvent(rawValue: unknown): MiroFishEvent {
    const raw = asObject(rawValue);
    return {
        ts: raw.ts ? String(raw.ts) : undefined,
        level: raw.level ? String(raw.level) : undefined,
        phase: raw.phase ? String(raw.phase) : undefined,
        message: raw.message ? String(raw.message) : undefined,
        payload: asObject(raw.payload),
    };
}

function normalizeEvents(payload: any): MiroFishEventsResponse {
    const raw = asObject(payload);
    return {
        run_id: raw.run_id,
        events: Array.isArray(raw.events) ? raw.events.map(normalizeEvent) : [],
        next_index: asNumber(raw.next_index, 0),
        total: asNumber(raw.total, 0),
        has_more: Boolean(raw.has_more),
    };
}

function timeFromEvent(event: MiroFishEvent): string {
    const payloadTime = event.payload?.time;
    if (payloadTime) return String(payloadTime);
    if (!event.ts) return 'live';
    const parsed = new Date(event.ts);
    return Number.isNaN(parsed.getTime()) ? String(event.ts) : parsed.toLocaleTimeString('ko-KR', { hour12: false });
}

function logFromEvent(event: MiroFishEvent, index: number): MiroFishLog {
    const phase = normalizePhase(event.phase, Math.min(5, index + 1));
    return {
        phase,
        time: timeFromEvent(event),
        text: String(event.payload?.text || event.message || 'MiroFish event'),
        tone: toneByPhase[phase] || 'text-blue-300',
    };
}

export function attachMiroFishArtifacts(
    run: MiroFishRun,
    graph?: MiroFishGraphArtifact,
    report?: MiroFishReport,
    events?: MiroFishEventsResponse,
): MiroFishRun {
    const graphNodes = nodesFromGraphArtifact(graph);
    const eventLogs = events?.events?.length ? events.events.map(logFromEvent) : undefined;
    return {
        ...run,
        graph_artifact: graph || run.graph_artifact,
        report: report || run.report,
        events: events?.events || run.events,
        graph_nodes: graphNodes.length ? graphNodes : run.graph_nodes,
        logs: eventLogs?.length ? eventLogs : run.logs,
    };
}

function normalizeStatus(payload: any): MiroFishStatus {
    const raw = asObject(payload);
    const limits = asObject(raw.limits);
    const pipeline = normalizePipeline(raw.pipeline ?? {
        graph_links: raw.graph_links,
        similar_events: raw.similar_events,
        agent_count: limits.max_agent_count,
        status: raw.mode ?? raw.service,
    }, raw.mode ?? raw.service);

    return {
        ready: Boolean(raw.ready),
        source: String(raw.source ?? raw.service ?? raw.mode ?? 'mirofish'),
        brain: normalizeBrain(raw.brain ?? raw.brain_summary),
        pipeline,
        updated_at: raw.updated_at,
    };
}

function unwrapRun(payload: any, target: string): MiroFishRun {
    const run = payload?.run ?? payload?.data ?? payload?.result ?? payload;
    const normalizedTarget = run?.target ?? run?.ticker ?? run?.symbol ?? target;
    const analysts = normalizeAnalysts(run?.analysts);
    const verdict = normalizeVerdict(run?.verdict, analysts);
    const pipeline = normalizePipeline(run?.pipeline, run?.status);
    const graphNodes = normalizeNodes(run?.graph_nodes);
    const predictionNodes = normalizePredictionNodes(run?.prediction_nodes, analysts);

    return {
        ...run,
        target: String(normalizedTarget),
        display_name: String(run?.display_name ?? run?.name ?? run?.target_name ?? normalizedTarget),
        price: run?.price ?? run?.current_price,
        change_pct: asNumber(run?.change_pct ?? run?.change_percent, 0),
        layers: normalizeLayers(run?.layers, analysts, verdict, graphNodes?.length ?? 0, predictionNodes?.length ?? 0),
        logs: normalizeLogs(run?.logs),
        analysts,
        graph_nodes: graphNodes,
        prediction_nodes: predictionNodes,
        verdict,
        brain: normalizeBrain(run?.brain ?? run?.brain_summary),
        pipeline,
    };
}

export const mirofishApi = {
    getStatus: async () => normalizeStatus(await fetchAuthAPI<any>('/api/admin/mirofish/status')),
    getDataSources: async () => fetchAuthAPI<any>('/api/admin/mirofish/data-sources'),
    resolveTarget: async (target: string) => fetchAuthAPI<MiroFishTargetSnapshot>(`/api/admin/mirofish/targets/resolve?target=${encodeURIComponent(target)}`),
    listRuns: async () => {
        const payload = await fetchAuthAPI<any>('/api/admin/mirofish/runs');
        const runs = Array.isArray(payload?.runs) ? payload.runs.map((run: unknown) => unwrapRun(run, '')) : [];
        return { runs };
    },
    getRun: async (runId: string) => unwrapRun(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}`), ''),
    getGraph: async (runId: string) => normalizeGraph(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/graph`)),
    getReport: async (runId: string) => normalizeReport(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/report`)),
    getEvents: async (runId: string, since = 0, limit = 200) => normalizeEvents(
        await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/events?since=${since}&limit=${limit}`),
    ),
    hydrateRun: async (runId: string, baseRun?: MiroFishRun) => {
        const [detail, graph, report, events] = await Promise.all([
            baseRun ? Promise.resolve(baseRun) : mirofishApi.getRun(runId),
            mirofishApi.getGraph(runId),
            mirofishApi.getReport(runId),
            mirofishApi.getEvents(runId),
        ]);
        return attachMiroFishArtifacts(detail, graph, report, events);
    },
    startRun: async (request: StartMiroFishRunRequest) => {
        const payload = await postAuthAPI<any>('/api/admin/mirofish/runs', request);
        return unwrapRun(payload, request.target);
    },
};
