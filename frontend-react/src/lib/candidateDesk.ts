export interface CandidateDeskPhase {
    samples: number; wins: number; win_rate: number | null; mean_net_return: number | null;
    stress_mean_net_return: number | null; block_count: number; unique_symbols: number;
}
export interface CandidateModelEvidence extends CandidateDeskPhase {
    expected_net_return: number; expected_stress_net_return: number; training_end: string; neighbors_exclude_target: true;
}
export interface CandidateDeskModel {
    name: 'causal-context-neighbors-v1'; status: 'experimental'; training_end: string | null;
    comparison_interpretation: 'v3_unconditional_retrospective_control_not_v4_holdout'; validation: 'forward_collecting';
}
export interface CandidateMonitorQuote {
    symbol: string; state: 'within_band' | 'skip' | 'unavailable'; price?: number; opening_price?: number;
    quote_at?: string; fetched_at?: string; source?: 'KIS:J:FHKST03010200+FHKST01010100';
}
export interface CandidateDeskMonitoring {
    state: 'waiting' | 'closed' | 'monitoring' | 'held' | 'failed' | 'stale' | 'unavailable';
    checked_at: string | null; decision_id: string | null; quotes: CandidateMonitorQuote[];
}
export interface DeskCandidate {
    symbol: string; name: string; rank: number; strength_score: number; quote_session: string; reason_facts: string[];
    plan: { entry_price: number; entry_upper: number; stop_price: number; target_price: number; horizon_sessions: 10; loss_fraction: number };
    risk: { reference_weight: number; kelly_fraction: .25; raw_kelly: number; approved_exposure: 0; live_orders: false };
    model_evidence?: CandidateModelEvidence;
}
export interface CandidateDesk {
    schema_version: 1; policy_version: 'cross-sectional-candidates-v3' | 'contextual-candidates-v4'; state: 'ready' | 'held' | 'failed' | 'running';
    decision_id: string; input_fingerprint: string; generated_at: string; latest_session: string;
    entry_session: string | null; valid_until: string | null;
    source: { provider: 'KIS'; venue: 'KRX'; adjusted_requested: true; captured_at: string;
        historical_vintage_verified: false; corporate_action_adjustment_verified: false };
    candidates: DeskCandidate[]; funnel: Array<{ id: string; label: string; count: number }>;
    evidence: { formation: CandidateDeskPhase; confirmation: CandidateDeskPhase }; reasons: string[];
    model?: CandidateDeskModel;
    monitoring?: CandidateDeskMonitoring;
    live_orders: false; approved_exposure: 0;
}

const DAY = 86400000, KST = 9 * 3600000;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e12;
const count = (v: unknown): v is number => finite(v) && Number.isSafeInteger(v) && v >= 0 && v <= 1_000_000;
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max = 300): v is string => typeof v === 'string' && !!v.trim() && v.length <= max
    && !/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069<>\\]|[A-Za-z]:\/|\/(?:home|srv|tmp|users|private|etc|var|root)\b|\.env\b|(?:미래|예상|상승|하락)\s*(?:승률|확률)\s*[:=]?\s*\d|(?:수익|승률).*보장/i.test(v)
    && !/(?:^|[^a-z0-9])(?:api[_-]?key|access[_-]?token|secret|password|credentials?|authorization|bearer|traceback|token[_-]?cache)(?:$|[^a-z0-9])/i.test(v);
const texts = (v: unknown, max = 30): v is string[] => Array.isArray(v) && v.length <= max && v.every(item => text(item));
function session(v: unknown): v is string {
    return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(`${v}T00:00:00Z`))
        && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
}
function timestamp(v: unknown): v is string {
    return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/.test(v)
        && session(v.slice(0, 10)) && Number.isFinite(Date.parse(v)) && !/[+-]14:(?!00)/.test(v);
}
const kstDay = (ms: number) => new Date(ms + KST).toISOString().slice(0, 10);
function completedSession(day: string, at: string) {
    const ms = Date.parse(at), local = kstDay(ms);
    return day < local || day === local && ms >= Date.parse(`${day}T20:30:00+09:00`);
}
function phase(v: unknown): v is CandidateDeskPhase {
    if (!record(v) || !count(v.samples) || !count(v.wins) || v.wins > v.samples || !count(v.block_count)
        || !count(v.unique_symbols) || v.block_count > v.samples || v.unique_symbols > Math.min(v.samples, 100)) return false;
    if (v.samples === 0) return v.wins === 0 && v.block_count === 0 && v.unique_symbols === 0
        && v.win_rate === null && v.mean_net_return === null && v.stress_mean_net_return === null;
    return finite(v.win_rate) && v.win_rate >= 0 && v.win_rate <= 1 && Math.abs(v.win_rate - v.wins / v.samples) <= 1e-5
        && finite(v.mean_net_return) && finite(v.stress_mean_net_return) && v.block_count > 0 && v.unique_symbols > 0;
}
function candidate(v: unknown, latest: string, weightLimit: number): v is DeskCandidate {
    if (!record(v) || typeof v.symbol !== 'string' || !/^\d{6}$/.test(v.symbol) || v.symbol === '000000'
        || !text(v.name, 120) || !count(v.rank) || v.rank < 1 || v.rank > 3 || !finite(v.strength_score)
        || v.quote_session !== latest || !texts(v.reason_facts, 12) || !v.reason_facts.length || !record(v.plan) || !record(v.risk)) return false;
    const p = v.plan, r = v.risk;
    return ['entry_price', 'entry_upper', 'stop_price', 'target_price', 'loss_fraction'].every(key => finite(p[key]) && p[key] > 0)
        && (p.stop_price as number) < (p.entry_price as number) && (p.entry_price as number) <= (p.entry_upper as number)
        && (p.entry_upper as number) < (p.target_price as number) && p.horizon_sessions === 10
        && (p.loss_fraction as number) <= .08 + 1e-8
        && Math.abs((p.entry_price as number) * (1 - (p.loss_fraction as number)) - (p.stop_price as number)) <= 1e-5
        && finite(r.reference_weight) && r.reference_weight > 0 && r.reference_weight <= weightLimit
        && r.kelly_fraction === .25 && finite(r.raw_kelly) && r.raw_kelly > 0 && r.raw_kelly <= 1
        && r.reference_weight <= r.raw_kelly * .25 + 1e-8 && r.reference_weight * (p.loss_fraction as number) <= .01
        && r.approved_exposure === 0 && r.live_orders === false;
}
const pickPhase = (p: CandidateDeskPhase): CandidateDeskPhase => ({ samples: p.samples, wins: p.wins, win_rate: p.win_rate,
    mean_net_return: p.mean_net_return, stress_mean_net_return: p.stress_mean_net_return, block_count: p.block_count, unique_symbols: p.unique_symbols });
function contextualModel(value: unknown, latest: string): value is CandidateDeskModel {
    return record(value) && value.name === 'causal-context-neighbors-v1' && value.status === 'experimental'
        && (value.training_end === null || session(value.training_end) && value.training_end < latest)
        && value.comparison_interpretation === 'v3_unconditional_retrospective_control_not_v4_holdout' && value.validation === 'forward_collecting';
}
function localEvidence(value: unknown, cutoff: string | null): value is CandidateModelEvidence {
    if (!cutoff || !phase(value) || !record(value) || value.training_end !== cutoff || value.neighbors_exclude_target !== true
        || value.samples < 30 || value.block_count < 5 || value.unique_symbols < 5) return false;
    return ['mean_net_return', 'stress_mean_net_return', 'expected_net_return', 'expected_stress_net_return'].every(key => finite(value[key]) && value[key] > 0);
}
const pickLocalEvidence = (p: CandidateModelEvidence): CandidateModelEvidence => ({ ...pickPhase(p), expected_net_return: p.expected_net_return,
    expected_stress_net_return: p.expected_stress_net_return, training_end: p.training_end, neighbors_exclude_target: true });
const monitorSource = 'KIS:J:FHKST03010200+FHKST01010100';
const unavailableMonitor = (): CandidateDeskMonitoring => ({ state: 'unavailable', checked_at: null, decision_id: null, quotes: [] });
const freshTime = (v: unknown, now: number): v is string => timestamp(v) && /(?:Z|\+00:00)$/.test(v)
    && Date.parse(v) <= now && now - Date.parse(v) < 420000;
const inEntryHours = (at: string | number, day: string | null) => day !== null
    && (typeof at === 'number' ? at : Date.parse(at)) >= Date.parse(`${day}T09:00:00+09:00`)
    && (typeof at === 'number' ? at : Date.parse(at)) < Date.parse(`${day}T15:30:00+09:00`);
function monitoring(value: unknown, desk: CandidateDesk, now: number): CandidateDeskMonitoring {
    if (!record(value) || !['waiting', 'closed', 'monitoring', 'held', 'failed', 'stale', 'unavailable'].includes(String(value.state))
        || value.decision_id !== desk.decision_id || !freshTime(value.checked_at, now)
        || Date.parse(value.checked_at) < Date.parse(desk.generated_at) || !Array.isArray(value.quotes) || value.quotes.length > 3) return unavailableMonitor();
    if (value.state === 'monitoring' && (!inEntryHours(now, desk.entry_session) || !inEntryHours(value.checked_at, desk.entry_session))) return unavailableMonitor();
    const identified = new Map<string, Record<string, unknown>[]>();
    for (const row of value.quotes) {
        if (!record(row) || typeof row.symbol !== 'string' || !desk.candidates.some(candidate => candidate.symbol === row.symbol)) continue;
        identified.set(row.symbol, [...identified.get(row.symbol) ?? [], row]);
    }
    const quotes = Array.from(identified, ([symbol, rows]): CandidateMonitorQuote => {
        const raw = rows[0];
        const unavailable: CandidateMonitorQuote = { symbol, state: 'unavailable' };
        if (rows.length !== 1 || raw.state === 'unavailable') return unavailable;
        if (!['within_band', 'skip'].includes(String(raw.state)) || !finite(raw.price) || raw.price <= 0
            || !finite(raw.opening_price) || raw.opening_price <= 0 || raw.source !== monitorSource
            || !freshTime(raw.quote_at, now) || !freshTime(raw.fetched_at, now)
            || Date.parse(raw.quote_at) > Date.parse(raw.fetched_at) || Date.parse(raw.fetched_at) > Date.parse(value.checked_at as string)
            || Date.parse(raw.fetched_at) - Date.parse(raw.quote_at) > 120000
            || !inEntryHours(raw.quote_at, desk.entry_session) || !inEntryHours(raw.fetched_at, desk.entry_session)) return unavailable;
        const plan = desk.candidates.find(candidate => candidate.symbol === symbol)!.plan;
        const within = [raw.price, raw.opening_price].every(price => price > plan.stop_price && price <= plan.entry_upper && price < plan.target_price);
        if (raw.state === 'within_band' && !within) return unavailable;
        return { symbol, state: raw.state as 'within_band' | 'skip', price: raw.price, opening_price: raw.opening_price,
            quote_at: raw.quote_at, fetched_at: raw.fetched_at, source: monitorSource };
    });
    return { state: value.state as CandidateDeskMonitoring['state'], checked_at: value.checked_at, decision_id: desk.decision_id, quotes };
}

/** A corrupt optional desk cannot invalidate the legacy API or cross into an actionable card. */
export function validateCandidateDesk(value: unknown, now = Date.now()): CandidateDesk | undefined {
    if (!Number.isFinite(now) || !record(value) || value.schema_version !== 1
        || !['cross-sectional-candidates-v3', 'contextual-candidates-v4'].includes(String(value.policy_version))
        || !['ready', 'held', 'failed', 'running'].includes(String(value.state)) || !hash(value.decision_id) || !hash(value.input_fingerprint)
        || !timestamp(value.generated_at) || Date.parse(value.generated_at) > now || !session(value.latest_session)
        || !record(value.source) || value.source.provider !== 'KIS' || value.source.venue !== 'KRX' || value.source.adjusted_requested !== true
        || value.source.historical_vintage_verified !== false || value.source.corporate_action_adjustment_verified !== false
        || !timestamp(value.source.captured_at) || Date.parse(value.source.captured_at) > Date.parse(value.generated_at)
        || !completedSession(value.latest_session, value.generated_at) || !completedSession(value.latest_session, value.source.captured_at)
        || !(value.entry_session === null || session(value.entry_session)) || !(value.valid_until === null || timestamp(value.valid_until))
        || (value.entry_session === null) !== (value.valid_until === null)
        || value.entry_session !== null && (value.entry_session <= kstDay(Date.parse(value.generated_at))
            || Date.parse(value.valid_until as string) !== Date.parse(`${value.entry_session}T15:30:00+09:00`))
        || !Array.isArray(value.candidates) || value.candidates.length > 3
        || !value.candidates.every(row => candidate(row, value.latest_session as string, value.policy_version === 'contextual-candidates-v4' ? .01 : .05))
        || !Array.isArray(value.funnel) || value.funnel.length > 20
        || !value.funnel.every(row => record(row) && text(row.id, 80) && text(row.label, 120) && count(row.count))
        || !record(value.evidence) || !phase(value.evidence.formation) || !phase(value.evidence.confirmation)
        || !texts(value.reasons) || value.live_orders !== false || value.approved_exposure !== 0) return undefined;
    const v = value as unknown as CandidateDesk;
    const contextual = v.policy_version === 'contextual-candidates-v4';
    if (contextual && (!contextualModel(value.model, v.latest_session)
        || !v.candidates.every(row => localEvidence(row.model_evidence, (value.model as CandidateDeskModel).training_end)))) return undefined;
    if (new Set(v.candidates.map(row => row.symbol)).size !== v.candidates.length
        || v.candidates.some((row, index) => index > 0 && row.rank <= v.candidates[index - 1].rank)
        || new Set(v.funnel.map(row => row.id)).size !== v.funnel.length) return undefined;
    if (v.state === 'ready' && v.candidates.length) {
        if (!v.entry_session || !v.valid_until) return undefined;
        const { formation: f, confirmation: c } = v.evidence;
        if (!contextual && (f.samples < 30 || c.samples < 10 || f.block_count < 5 || c.block_count < 3 || f.unique_symbols < 5
            || !(f.mean_net_return! > 0 && f.stress_mean_net_return! > 0 && c.mean_net_return! > 0 && c.stress_mean_net_return! > 0))) return undefined;
    }
    // Copy only consumed fields: additional audit fields may exist without leaking into the UI.
    return { schema_version: 1, policy_version: v.policy_version, state: v.state, decision_id: v.decision_id,
        input_fingerprint: v.input_fingerprint, generated_at: v.generated_at, latest_session: v.latest_session,
        entry_session: v.entry_session, valid_until: v.valid_until,
        source: { provider: 'KIS', venue: 'KRX', adjusted_requested: true, captured_at: v.source.captured_at,
            historical_vintage_verified: false, corporate_action_adjustment_verified: false },
        candidates: v.candidates.map(row => ({ symbol: row.symbol, name: row.name, rank: row.rank, strength_score: row.strength_score,
            quote_session: row.quote_session, reason_facts: [...row.reason_facts],
            plan: { entry_price: row.plan.entry_price, entry_upper: row.plan.entry_upper, stop_price: row.plan.stop_price,
                target_price: row.plan.target_price, horizon_sessions: 10, loss_fraction: row.plan.loss_fraction },
            risk: { reference_weight: row.risk.reference_weight, kelly_fraction: .25, raw_kelly: row.risk.raw_kelly, approved_exposure: 0, live_orders: false },
            ...(contextual ? { model_evidence: pickLocalEvidence(row.model_evidence!) } : {}) })),
        funnel: v.funnel.map(row => ({ id: row.id, label: row.label, count: row.count })),
        evidence: { formation: pickPhase(v.evidence.formation), confirmation: pickPhase(v.evidence.confirmation) },
        ...(contextual ? { model: { name: v.model!.name, status: v.model!.status, training_end: v.model!.training_end,
            comparison_interpretation: v.model!.comparison_interpretation, validation: v.model!.validation } } : {}),
        ...(value.monitoring !== undefined ? { monitoring: monitoring(value.monitoring, v, now) } : {}),
        reasons: [...v.reasons], live_orders: false, approved_exposure: 0 };
}

function deskExpirations(desk: CandidateDesk): number[] {
    return [Date.parse(desk.valid_until ?? ''), Date.parse(desk.source.captured_at) + 7 * DAY,
        Date.parse(`${desk.latest_session}T00:00:00+09:00`) + 8 * DAY].filter(Number.isFinite);
}
export function candidateDeskClockExpirations(desk: CandidateDesk): number[] {
    return [...deskExpirations(desk), ...(desk.entry_session ? [Date.parse(`${desk.entry_session}T00:00:00+09:00`), Date.parse(`${desk.entry_session}T09:00:00+09:00`)] : []),
        ...(desk.monitoring?.checked_at ? [Date.parse(desk.monitoring.checked_at) + 420000] : []),
        ...desk.monitoring?.quotes.flatMap(quote => [quote.quote_at, quote.fetched_at].flatMap(at => at ? [Date.parse(at) + 420000] : [])) ?? []].filter(Number.isFinite);
}
export interface CandidateEntryView {
    state: 'conditional' | 'within_band' | 'skip' | 'waiting' | 'unavailable'; reference_weight: number; quote?: CandidateMonitorQuote;
}
export function candidateDeskEntryView(desk: CandidateDesk | undefined, symbol: string, now = Date.now(), blocked = false): CandidateEntryView {
    const current = !blocked && desk ? validateCandidateDesk(desk, now) : undefined;
    const row = current?.candidates.find(candidate => candidate.symbol === symbol);
    if (!current || !row || current.state !== 'ready' || !current.entry_session || !current.valid_until
        || !deskExpirations(current).every(expiry => now < expiry)) return { state: 'unavailable', reference_weight: 0 };
    if (kstDay(now) < current.entry_session) return { state: 'conditional', reference_weight: row.risk.reference_weight };
    if (!inEntryHours(now, current.entry_session) || current.monitoring?.state !== 'monitoring') return { state: 'waiting', reference_weight: 0 };
    const quote = current.monitoring.quotes.find(quote => quote.symbol === symbol);
    if (!quote || quote.state === 'unavailable') return { state: 'waiting', reference_weight: 0 };
    return { state: quote.state, reference_weight: quote.state === 'within_band' ? row.risk.reference_weight : 0, quote };
}
export function candidateDeskEntryAvailable(desk: CandidateDesk | undefined, now = Date.now(), blocked = false): boolean {
    return !!desk && desk.candidates.some(row => ['conditional', 'within_band'].includes(candidateDeskEntryView(desk, row.symbol, now, blocked).state));
}
