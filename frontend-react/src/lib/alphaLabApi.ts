import { fetchAuthAPI, postAuthAPI } from './api';

export interface AlphaLabPerformance {
    net_total_return: number | null;
    max_drawdown: number | null;
    trades: number;
    win_rate: number | null;
}
export interface AlphaLabStrategy {
    strategy_id: string;
    name: string;
    validation: { trades: number; win_rate: number | null; mean_net_return: number | null };
    test: AlphaLabPerformance;
    stress: AlphaLabPerformance;
    qualified: boolean;
    reasons: string[];
}
export type AlphaLabAction = 'buy' | 'wait' | 'avoid';
export interface AlphaLabProposal {
    action: AlphaLabAction;
    label: '매수 제안' | '진입 대기' | '매매 제외';
    reason: string;
    next_step: string;
    proposed_weight: number;
    input_session: string | null;
    derived_at: string;
    valid_until: string | null;
    plan_basis: 'last_closed_price_next_open_reference';
    order_allowed: false;
}
export interface AlphaLabProposalSummary {
    action: AlphaLabAction;
    headline: string;
    reason: string;
    buy_count: number;
    wait_count: number;
    avoid_count: number;
    policy_version: 'alpha-proposal-v1';
}
export interface AlphaLabCandidate {
    symbol: string;
    name: string;
    strategy_id: string;
    score: number;
    last_close: number | null;
    plan: { entry_price: number; stop_price: number; target_price: number; loss_fraction: number } | null;
    risk: { weight: number; status: string; reasons: string[]; p: number | null; kelly_raw: number | null; research_weight?: number };
    setup_active?: boolean;
    quote_session?: string | null;
    proposal?: AlphaLabProposal;
    reasons: string[];
}
export interface AlphaLabReport {
    schema_version: 1;
    mode: 'research';
    as_of: string;
    decision_at?: string;
    latest_session?: string | null;
    proposal_summary?: AlphaLabProposalSummary;
    universe: { ranked_count: number; quality_count: number; inspected_count: number; scope_date: string | null };
    provenance: {
        price_basis: string;
        price_adjustment_verified: boolean;
        historical_vintage_verified: boolean;
        point_in_time_universe_verified: boolean;
        current_cohort_bias: boolean;
        analysis_ready: boolean;
        captured_at?: string | null;
    };
    champion: { strategy_id: string | null; selection_basis: 'validation_only'; status: string; reasons: string[] };
    strategies: AlphaLabStrategy[];
    candidates: AlphaLabCandidate[];
    agents: Array<{ id: string; name: string; status: string; detail: string }>;
    warnings: string[];
    forward: { decisions: number; matured: number; win_rate: number | null; mean_net_return: number | null };
    protocol: {
        train_end: string;
        validation_end: string;
        test_start: string;
        horizon_sessions: number;
        source_references: Array<{ name: string; url: string }>;
    };
}
export interface AlphaLabStatus {
    schema_version: 1;
    state: 'missing' | 'running' | 'ready' | 'held' | 'failed';
    generated_at: string | null;
    report: AlphaLabReport | null;
    error: string | null;
}

const invalid = '전략 실험 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const count = (value: unknown): value is number => finite(value) && Number.isInteger(value) && value >= 0;
const fraction = (value: unknown) => finite(value) && value >= 0 && value <= 1;
const nullableFinite = (value: unknown) => value === null || finite(value);
const nullableRate = (value: unknown) => value === null || fraction(value);
const safeText = (value: unknown, max = 300): value is string => typeof value === 'string' && value.length <= max
    && !/[\u0000-\u001f]|[A-Za-z]:[\\/]|(?:^|\s)\/(?:home|srv|tmp|Users|private)\b|\.env\b|(?:api[_-]?key|access[_-]?token|secret)\s*[:=]/i.test(value);
const label = (value: unknown): value is string => safeText(value, 120) && !!value.trim();
const reasons = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(item => label(item));
const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const timestamp = (value: unknown): value is string => typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const utcTimestamp = (value: unknown): value is string => timestamp(value) && /(?:Z|\+00:00)$/.test(value);
const weight = (value: unknown): value is number => finite(value) && value >= 0 && value <= .2;
const proposalLabels = { buy: '매수 제안', wait: '진입 대기', avoid: '매매 제외' } as const;
const action = (value: unknown): value is AlphaLabAction => value === 'buy' || value === 'wait' || value === 'avoid';
function proposal(value: unknown): value is AlphaLabProposal {
    return record(value) && action(value.action) && value.label === proposalLabels[value.action]
        && safeText(value.reason) && !!value.reason.trim() && safeText(value.next_step) && !!value.next_step.trim()
        && weight(value.proposed_weight) && (value.action === 'buy' ? value.proposed_weight > 0 : value.proposed_weight === 0)
        && (value.input_session === null || date(value.input_session)) && utcTimestamp(value.derived_at)
        && (value.valid_until === null || utcTimestamp(value.valid_until))
        && value.plan_basis === 'last_closed_price_next_open_reference' && value.order_allowed === false;
}
function proposalSummary(value: unknown, candidates: AlphaLabCandidate[]): value is AlphaLabProposalSummary {
    if (!record(value) || !action(value.action) || !safeText(value.headline, 160) || !value.headline.trim()
        || !safeText(value.reason) || !value.reason.trim() || value.policy_version !== 'alpha-proposal-v1') return false;
    const counts = { buy: 0, wait: 0, avoid: 0 };
    candidates.forEach(row => { counts[row.proposal?.action ?? 'wait']++; });
    const expected = counts.buy ? 'buy' : counts.wait || !candidates.length ? 'wait' : 'avoid';
    return value.action === expected && value.buy_count === counts.buy && value.wait_count === counts.wait && value.avoid_count === counts.avoid;
}
const kstDay = (ms: number) => Math.floor((ms + 9 * 3600000) / 86400000);
const currentSourceBlocks = new Set(['stale_prices', 'stale_scope', 'future_source_capture', 'missing_current_price',
    'price_capture_before_session_close', 'input_pointer_unavailable', 'input_refresh_failed_previous_snapshot_retained',
    'source_refresh_failed', 'refresh_failed']);
function freshBuy(row: AlphaLabCandidate, report: AlphaLabReport, now: number): boolean {
    if (row.proposal?.action !== 'buy') return true;
    const capture = Date.parse(report.provenance.captured_at ?? '');
    const session = Date.parse(`${report.latest_session}T00:00:00+09:00`);
    const scope = Date.parse(`${report.universe.scope_date}T00:00:00+09:00`);
    const groups = [...report.warnings, ...report.champion.reasons, ...row.reasons, ...row.risk.reasons];
    return now < Date.parse(row.proposal.valid_until ?? '') && [capture, session, scope].every(value => Number.isFinite(value)
        && value <= now && kstDay(now) - kstDay(value) <= 7)
        && !groups.some(reason => currentSourceBlocks.has(reason) || reason.includes('refresh_failed'));
}
function validBuy(row: AlphaLabCandidate, report: AlphaLabReport): boolean {
    const p = row.proposal;
    if (p?.action !== 'buy') return true;
    const selected = report.strategies.find(strategy => strategy.strategy_id === row.strategy_id);
    const stopLoss = row.plan ? (row.plan.entry_price - row.plan.stop_price) / row.plan.entry_price : NaN;
    if (!selected || report.champion.strategy_id !== row.strategy_id || !selected.qualified
        || selected.validation.trades < 30 || !(selected.validation.mean_net_return !== null && selected.validation.mean_net_return > 0)
        || selected.test.trades < 30 || !(selected.test.net_total_return !== null && selected.test.net_total_return > 0)
        || selected.stress.trades < 30 || !(selected.stress.net_total_return !== null && selected.stress.net_total_return > 0)
        || row.setup_active !== true || !row.plan || row.risk.p === null || row.risk.p <= 0 || row.risk.p >= 1
        || row.plan.loss_fraction > .08 + 1e-10 || row.last_close === null || Math.abs(row.plan.entry_price - row.last_close) > Math.max(1e-9, row.last_close * 1e-9)
        || Math.abs(row.plan.loss_fraction - stopLoss) > Math.max(1e-10, 1e-7 * Math.max(Math.abs(row.plan.loss_fraction), Math.abs(stopLoss)))
        || p.proposed_weight * stopLoss > .01 + 1e-10
        || row.risk.research_weight === undefined || row.risk.research_weight <= 0
        || row.risk.research_weight !== undefined && p.proposed_weight > row.risk.research_weight + 1e-8
        || !report.latest_session || row.quote_session !== report.latest_session || p.input_session !== report.latest_session
        || !report.decision_at || !report.provenance.captured_at || !p.valid_until) return false;
    const now = Date.now();
    const decision = Date.parse(report.decision_at), captured = Date.parse(report.provenance.captured_at);
    return decision <= now && captured <= now && Date.parse(p.derived_at) <= now
        && captured <= decision
        && Date.parse(p.valid_until) === decision + 86400000;
}

function publicReference(value: unknown): boolean {
    if (!record(value) || !label(value.name) || typeof value.url !== 'string' || value.url.length > 1000) return false;
    try {
        const url = new URL(value.url);
        return url.protocol === 'https:' && !url.username && !url.password
            && !/^(?:localhost|127\.|0\.|192\.168\.|10\.|\[::1\])/i.test(url.hostname);
    } catch { return false; }
}
function performance(value: unknown): boolean {
    return record(value) && count(value.trades) && nullableRate(value.win_rate)
        && nullableFinite(value.net_total_return) && nullableFinite(value.max_drawdown)
        && (value.trades > 0 || value.win_rate === null);
}
function strategy(value: unknown): value is AlphaLabStrategy {
    return record(value) && label(value.strategy_id) && label(value.name) && typeof value.qualified === 'boolean'
        && reasons(value.reasons) && record(value.validation) && count(value.validation.trades)
        && nullableRate(value.validation.win_rate) && nullableFinite(value.validation.mean_net_return)
        && (value.validation.trades > 0 || value.validation.win_rate === null && value.validation.mean_net_return === null)
        && performance(value.test) && performance(value.stress);
}
function candidate(value: unknown, strategies: Set<string>): value is AlphaLabCandidate {
    if (!record(value) || typeof value.symbol !== 'string' || !/^\d{6}$/.test(value.symbol) || !label(value.name)
        || !label(value.strategy_id) || !strategies.has(value.strategy_id) || !finite(value.score)
        || !(value.last_close === null || finite(value.last_close) && value.last_close > 0)
        || !reasons(value.reasons) || !record(value.risk) || !finite(value.risk.weight)
        || value.risk.weight < 0 || value.risk.weight > .2 || !label(value.risk.status) || !reasons(value.risk.reasons)
        || !nullableRate(value.risk.p) || !nullableFinite(value.risk.kelly_raw)
        || value.risk.research_weight !== undefined && !weight(value.risk.research_weight)
        || value.setup_active !== undefined && typeof value.setup_active !== 'boolean'
        || value.quote_session !== undefined && !(value.quote_session === null || date(value.quote_session))
        || value.proposal !== undefined && !proposal(value.proposal)) return false;
    if (value.plan === null) return value.risk.weight === 0;
    const p = value.plan;
    return record(p) && finite(p.entry_price) && finite(p.stop_price) && finite(p.target_price)
        && p.stop_price > 0 && p.stop_price < p.entry_price && p.target_price > p.entry_price
        && finite(p.loss_fraction) && p.loss_fraction > 0 && p.loss_fraction < 1
        && Math.abs(p.loss_fraction - (p.entry_price - p.stop_price) / p.entry_price) < .0001;
}

function validReport(value: unknown): value is AlphaLabReport {
    if (!record(value) || value.schema_version !== 1 || value.mode !== 'research' || !timestamp(value.as_of)
        || !record(value.universe) || !record(value.provenance) || !record(value.champion)
        || !Array.isArray(value.strategies) || value.strategies.length > 12 || !value.strategies.every(strategy)
        || !Array.isArray(value.candidates) || value.candidates.length > 3 || !Array.isArray(value.agents)
        || value.agents.length > 12 || !reasons(value.warnings) || !record(value.forward) || !record(value.protocol)) return false;
    const u = value.universe;
    const p = value.provenance;
    const c = value.champion;
    const f = value.forward;
    const protocol = value.protocol;
    const ids = new Set(value.strategies.map(row => row.strategy_id));
    if (ids.size !== value.strategies.length || !count(u.ranked_count) || u.ranked_count > 100
        || !count(u.quality_count) || u.quality_count > u.ranked_count || !count(u.inspected_count)
        || u.inspected_count > u.quality_count || !(u.scope_date === null || date(u.scope_date))
        || !label(p.price_basis) || !['price_adjustment_verified', 'historical_vintage_verified', 'point_in_time_universe_verified', 'current_cohort_bias', 'analysis_ready'].every(key => typeof p[key] === 'boolean')
        || c.selection_basis !== 'validation_only' || !(c.strategy_id === null || label(c.strategy_id) && ids.has(c.strategy_id))
        || !label(c.status) || !reasons(c.reasons) || !count(f.decisions) || !count(f.matured)
        || !nullableRate(f.win_rate) || !nullableFinite(f.mean_net_return)
        || f.matured === 0 && (f.win_rate !== null || f.mean_net_return !== null)
        || !date(protocol.train_end) || !date(protocol.validation_end) || !date(protocol.test_start)
        || protocol.train_end >= protocol.validation_end || protocol.validation_end >= protocol.test_start
        || !count(protocol.horizon_sessions) || protocol.horizon_sessions < 1 || protocol.horizon_sessions > 252
        || !Array.isArray(protocol.source_references) || protocol.source_references.length > 20
        || !protocol.source_references.every(publicReference)) return false;
    if (value.decision_at !== undefined && !utcTimestamp(value.decision_at)
        || value.latest_session !== undefined && !(value.latest_session === null || date(value.latest_session))
        || p.captured_at !== undefined && p.captured_at !== null && !utcTimestamp(p.captured_at)) return false;
    const symbols = new Set<string>();
    let exposure = 0;
    for (const row of value.candidates) {
        if (!candidate(row, ids) || symbols.has(row.symbol)) return false;
        symbols.add(row.symbol); exposure += row.risk.weight;
    }
    if (value.proposal_summary !== undefined && !proposalSummary(value.proposal_summary, value.candidates)) return false;
    if (value.candidates.some(row => row.proposal?.action === 'buy') && !value.proposal_summary) return false;
    if (!value.candidates.every(row => validBuy(row, value as unknown as AlphaLabReport))) return false;
    return exposure <= .6 + 1e-8 && value.agents.every(row => record(row) && label(row.id) && label(row.name)
        && label(row.status) && safeText(row.detail));
}

/** Only finite, identified research evidence crosses the API boundary; raw worker errors are never rendered. */
export function validateAlphaLabStatus(value: unknown): AlphaLabStatus {
    if (!record(value) || value.schema_version !== 1 || !['missing', 'running', 'ready', 'held', 'failed'].includes(String(value.state))
        || !(value.generated_at === null || timestamp(value.generated_at)) || !(value.error === null || typeof value.error === 'string')
        || !(value.report === null || validReport(value.report))
        || ['ready', 'held'].includes(String(value.state)) && value.report === null) throw new Error(invalid);
    const status = value as unknown as AlphaLabStatus;
    if (!status.report) return status;
    const candidates = status.report.candidates.map(row => {
        const p = row.proposal;
        if (p?.action !== 'buy' || ['ready', 'held'].includes(status.state) && freshBuy(row, status.report!, Date.now())) return row;
        return { ...row, proposal: { ...p, action: 'wait' as const, label: '진입 대기' as const, proposed_weight: 0,
            reason: '제안이 만료되었거나 최신 검사 결과를 확인 중입니다.', next_step: '저장 결과를 다시 확인한 뒤 판단하세요.' } };
    });
    const summary = status.report.proposal_summary;
    if (candidates.every((row, index) => row === status.report!.candidates[index])) return status;
    const buy = candidates.filter(row => row.proposal?.action === 'buy').length;
    const wait = candidates.filter(row => !row.proposal || row.proposal.action === 'wait').length;
    const avoid = candidates.length - buy - wait;
    return { ...status, report: { ...status.report, candidates, proposal_summary: summary && { ...summary,
        action: buy ? 'buy' : wait || !candidates.length ? 'wait' : 'avoid', buy_count: buy, wait_count: wait, avoid_count: avoid,
        headline: buy ? summary.headline : '오늘 제안: 진입 대기', reason: '만료되었거나 갱신 중인 매수 제안은 대기로 전환했습니다.' } } };
}
export async function fetchAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await fetchAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', token));
}
export async function startAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await postAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', {}, token));
}
