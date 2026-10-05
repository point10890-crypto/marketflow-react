import { fetchAuthAPI, postAuthAPI } from './api';
import { validateOpportunityEngine, type OpportunityEngine } from './opportunityEngine';

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
export type AlphaLabAnalystId = 'rev_5' | 'low_vol_60' | 'anti_max_21' | 'attention_fade';
export interface AlphaLabAnalystContext {
    schema_version: 1;
    policy_version: 'quality-analyst-context-v1';
    symbol: string;
    as_of: string;
    input_fingerprint: string;
    scope: 'current_quality_cohort';
    cohort_count: number;
    comparison_count: number;
    status: 'ready' | 'unavailable';
    score: number | null;
    favorable_count: number;
    caution_count: number;
    neutral_count: number;
    analysts: Array<{ id: AlphaLabAnalystId; metric_value: number | null; percentile: number | null;
        stance: 'favorable' | 'caution' | 'neutral' | 'unavailable' }>;
    reasons: string[];
}
export interface AlphaLabEntryGuard {
    policy_version: 'reference-chase-cap-v1';
    symbol: string;
    as_of: string;
    input_fingerprint: string;
    reference_price: number;
    max_chase_fraction: .02;
    max_entry_price: number;
    applies_to: 'manual_next_open_reference';
    backtest_applied: false;
}
export interface AlphaLabCandidate {
    symbol: string;
    name: string;
    strategy_id: string;
    score: number;
    last_close: number | null;
    plan: { entry_price: number; stop_price: number; target_price: number; loss_fraction: number; atr?: number } | null;
    risk: { weight: number; status: string; reasons: string[]; p: number | null; kelly_raw: number | null; research_weight?: number; quarter_kelly_fraction?: number; planned_account_risk?: number };
    setup_active?: boolean;
    quote_session?: string | null;
    proposal?: AlphaLabProposal;
    analyst_context?: AlphaLabAnalystContext;
    entry_guard?: AlphaLabEntryGuard;
    reasons: string[];
}
export interface AlphaLabOpportunityPhase {
    samples: number; wins: number; losses: number; zeros: number; win_rate: number;
    mean_net_return: number; stress_mean_net_return: number;
    compounded_trade_return: number; stress_compounded_trade_return: number;
    start: string; end: string; last_exit_session: string; t_stat: number | null;
    return_basis?: 'compounded_nonoverlapping_unit_notional_trades_not_account_allocation';
}
export interface AlphaLabOpportunityCandidate extends AlphaLabCandidate {
    evidence: {
        selection_basis: 'calibration_stress_mean_then_confirmation';
        stronger_evidence: boolean; retrospective: true; independent_validation: false;
        calibration: AlphaLabOpportunityPhase; confirmation: AlphaLabOpportunityPhase;
    };
}
export interface AlphaLabOpportunityScan {
    policy_version: 'quality-setup-opportunity-v1';
    selection_basis: 'calibration_stress_mean_then_confirmation';
    status: 'ready' | 'held';
    latest_session: string | null;
    lookback_sessions: 1260; calibration_sessions: 1008; confirmation_sessions: 252; horizon_sessions: 10;
    inspected_count: number; eligible_count: number; active_setup_count: number; reasons: string[]; warnings?: string[];
    forward?: AlphaLabReport['forward'];
    audit_hash?: string;
}
export interface AlphaLabOpportunitySummary extends Omit<AlphaLabProposalSummary, 'policy_version'> {
    policy_version: 'quality-setup-opportunity-v1';
}
export interface AlphaLabReport {
    schema_version: 1;
    mode: 'research';
    as_of: string;
    decision_at?: string;
    latest_session?: string | null;
    input_fingerprint?: string;
    proposal_window?: AlphaLabProposalWindow;
    proposal_summary?: AlphaLabProposalSummary;
    buy_candidates?: AlphaLabOpportunityCandidate[];
    opportunity_scan?: AlphaLabOpportunityScan;
    opportunity_summary?: AlphaLabOpportunitySummary;
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
    operations?: AlphaLabOperations;
    opportunity_engine?: OpportunityEngine;
}
export interface AlphaLabProposalWindow {
    policy_version: 'next-session-proposal-v1'; input_fingerprint: string; opportunity_audit_hash: string;
    origin_at: string; entry_session: string | null; valid_until: string | null; calendar_source: 'KIS:CTCA0903R';
}
export interface AlphaLabMonitorQuote {
    symbol: string; price: number | null; quote_at: string | null; fetched_at: string | null; opening_price: number | null;
    source: 'KIS:J:FHKST03010200+FHKST01010100';
    entry_state: 'wait_open' | 'within_band' | 'above_ceiling' | 'below_stop' | 'target_reached' | 'closed' | 'stale' | 'unavailable';
    reference_price: number; entry_ceiling: number; stop_price: number; target_price: number;
    adjusted_plan?: { entry_price: number; stop_price: number; target_price: number; loss_fraction: number; proposed_weight: number } | null;
    reasons: string[];
}
export interface AlphaLabOperations {
    schema_version: 1; policy_version: 'alpha-cadence-v1'; generated_at: string;
    cadence: { timezone: 'Asia/Seoul'; research_time: '18:45'; monitor_interval_seconds: 300;
        market_state: 'open' | 'closed' | 'holiday' | 'unknown'; calendar_status: 'ready' | 'held' | 'failed';
        calendar_checked_at: string | null; last_scan_at: string | null; next_scan_at: string | null;
        last_monitor_at: string | null; next_monitor_at: string | null; reasons: string[] };
    monitoring: { status: 'ready' | 'held' | 'failed'; decision_at: string | null; origin_at: string | null;
        input_fingerprint: string | null; opportunity_audit_hash: string | null; entry_session: string | null;
        valid_until: string | null; observed_at: string | null; quotes: AlphaLabMonitorQuote[]; reasons: string[] };
    paper: { decisions: number; matured: number; win_rate: number | null; mean_net_return: number | null;
        counts: { pending: number; open: number; unfilled: number; missing_session: number; source_revision: number; closed: number };
        excluded_revised_closed: number; basis: 'frozen_watchlist_next_open_outcomes_not_account_pnl'; entry_guard_applied: false;
        revision_policy?: 'preserve_terminal_result_exclude_revised_closed_from_statistics' };
}

const invalid = '매수 후보 검출 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
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
const fingerprint = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const onlyKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
// Server decision/assessment clocks may lead the browser slightly; source freshness and expiry stay strict.
const maxServerClockAheadMs = 60_000;
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
function proposalSummary(value: unknown, candidates: AlphaLabCandidate[], policy = 'alpha-proposal-v1'): boolean {
    if (!record(value) || !action(value.action) || !safeText(value.headline, 160) || !value.headline.trim()
        || !safeText(value.reason) || !value.reason.trim() || value.policy_version !== policy) return false;
    const counts = { buy: 0, wait: 0, avoid: 0 };
    candidates.forEach(row => { counts[row.proposal?.action ?? 'wait']++; });
    const expected = counts.buy ? 'buy' : counts.wait || !candidates.length ? 'wait' : 'avoid';
    return value.action === expected && value.buy_count === counts.buy && value.wait_count === counts.wait && value.avoid_count === counts.avoid;
}
const kstDay = (ms: number) => Math.floor((ms + 9 * 3600000) / 86400000);
const sessionClose = (session: string) => Date.parse(`${session}T15:30:00+09:00`);
const nullableTimestamp = (value: unknown) => value === null || utcTimestamp(value);
const nullablePositive = (value: unknown) => value === null || finite(value) && value > 0;
const near = (actual: number, expected: number) => Math.abs(actual - expected) <= Math.max(1e-8, Math.abs(expected) * 1e-8);
function proposalWindow(value: unknown, report: AlphaLabReport): value is AlphaLabProposalWindow {
    if (!record(value) || !onlyKeys(value, ['policy_version', 'input_fingerprint', 'opportunity_audit_hash', 'origin_at', 'entry_session', 'valid_until', 'calendar_source'])
        || value.policy_version !== 'next-session-proposal-v1' || value.calendar_source !== 'KIS:CTCA0903R'
        || !fingerprint(value.input_fingerprint) || value.input_fingerprint !== report.input_fingerprint
        || !fingerprint(value.opportunity_audit_hash) || value.opportunity_audit_hash !== report.opportunity_scan?.audit_hash
        || !utcTimestamp(value.origin_at) || !report.decision_at || Date.parse(value.origin_at) > Date.parse(report.decision_at)) return false;
    if (value.entry_session === null || value.valid_until === null) return value.entry_session === null && value.valid_until === null;
    if (!date(value.entry_session) || !utcTimestamp(value.valid_until)) return false;
    const delta = kstDay(sessionClose(value.entry_session)) - kstDay(Date.parse(value.origin_at));
    return delta > 0 && delta <= 7 && Date.parse(value.valid_until) === sessionClose(value.entry_session);
}
function monitorIdentity(operations: AlphaLabOperations, report: AlphaLabReport | null): boolean {
    const m = operations.monitoring, w = report?.proposal_window;
    return !!report && m.input_fingerprint === report.input_fingerprint && m.opportunity_audit_hash === report.opportunity_scan?.audit_hash
        && !!m.decision_at && !!report.decision_at && Date.parse(m.decision_at) === Date.parse(report.decision_at)
        && !!m.origin_at && Date.parse(m.origin_at) <= Date.parse(report.decision_at)
        && (!w || m.origin_at === w.origin_at && m.entry_session === w.entry_session && m.valid_until === w.valid_until);
}
function certifiedWindow(report: AlphaLabReport, operations?: AlphaLabOperations): boolean {
    const w = report.proposal_window;
    return !!w?.entry_session && !!w.valid_until && !!operations && monitorIdentity(operations, report)
        && operations.cadence.calendar_status === 'ready' && !!operations.cadence.calendar_checked_at
        && !operations.cadence.reasons.some(reason => ['calendar_unavailable', 'calendar_invalid', 'calendar_stale', 'calendar_gap', 'calendar_revision', 'monitor_corrupt'].includes(reason))
        && !operations.monitoring.reasons.some(reason => reason === 'calendar_revision');
}
function opportunityExpiry(report: AlphaLabReport): number | null {
    return report.proposal_window ? report.proposal_window.valid_until ? Date.parse(report.proposal_window.valid_until) : null
        : Date.parse(report.decision_at ?? '') + 86400000;
}
const currentSourceBlocks = new Set(['stale_prices', 'stale_scope', 'future_source_capture', 'missing_current_price',
    'price_capture_before_session_close', 'input_pointer_unavailable', 'input_refresh_failed_previous_snapshot_retained',
    'source_refresh_failed', 'refresh_failed']);
function freshBuy(row: AlphaLabCandidate, report: AlphaLabReport, now: number, opportunity = false, operations?: AlphaLabOperations): boolean {
    if (row.proposal?.action !== 'buy') return true;
    const capture = Date.parse(report.provenance.captured_at ?? '');
    const session = Date.parse(`${report.latest_session}T00:00:00+09:00`);
    const scope = Date.parse(`${report.universe.scope_date}T00:00:00+09:00`);
    const groups = [...report.warnings, ...report.champion.reasons, ...row.reasons, ...row.risk.reasons];
    return (!opportunity || !report.proposal_window || certifiedWindow(report, operations))
        && now < Date.parse(row.proposal.valid_until ?? '') && [capture, session, scope].every(value => Number.isFinite(value)
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
    return decision <= now + maxServerClockAheadMs && captured <= now && Date.parse(p.derived_at) <= now + maxServerClockAheadMs
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
        && Math.abs(p.loss_fraction - (p.entry_price - p.stop_price) / p.entry_price) < .0001
        && (p.atr === undefined || finite(p.atr) && p.atr > 0);
}
const analystIds = ['rev_5', 'low_vol_60', 'anti_max_21', 'attention_fade'] as const;
const analystReasons = new Set(['insufficient_cohort', 'missing_prices', 'missing_current_quote', 'insufficient_history',
    'sparse_factor_window', 'invalid_observation', 'flagged_observation', 'latest_quote_nontradable', 'nonpositive_amount_mean']);
const percentile = (value: unknown): value is number => finite(value) && value >= 0 && value <= 100;
const analystStance = (rank: number) => rank >= 66.666667 ? 'favorable' : rank <= 33.333333 ? 'caution' : 'neutral';
function guidanceBinding(value: Record<string, unknown>, row: AlphaLabCandidate, report: AlphaLabReport): boolean {
    return value.symbol === row.symbol && date(value.as_of) && value.as_of === row.quote_session
        && value.as_of === report.latest_session && fingerprint(value.input_fingerprint)
        && value.input_fingerprint === report.input_fingerprint;
}
function analystContext(value: unknown, row: AlphaLabCandidate, report: AlphaLabReport): value is AlphaLabAnalystContext {
    if (!record(value) || !onlyKeys(value, ['schema_version', 'policy_version', 'symbol', 'as_of', 'input_fingerprint', 'scope',
        'cohort_count', 'comparison_count', 'status', 'score', 'favorable_count', 'caution_count', 'neutral_count', 'analysts', 'reasons'])
        || value.schema_version !== 1 || value.policy_version !== 'quality-analyst-context-v1' || value.scope !== 'current_quality_cohort'
        || !guidanceBinding(value, row, report) || !count(value.cohort_count) || value.cohort_count !== report.universe.quality_count
        || !count(value.comparison_count) || value.comparison_count > value.cohort_count
        || (value.status !== 'ready' && value.status !== 'unavailable') || !count(value.favorable_count) || !count(value.caution_count)
        || !count(value.neutral_count) || !reasons(value.reasons) || !value.reasons.every(reason => analystReasons.has(reason))
        || !Array.isArray(value.analysts) || value.analysts.length !== analystIds.length) return false;
    const ready = value.status === 'ready';
    const counts = { favorable: 0, caution: 0, neutral: 0 };
    let total = 0;
    for (const [index, analyst] of value.analysts.entries()) {
        if (!record(analyst) || !onlyKeys(analyst, ['id', 'metric_value', 'percentile', 'stance']) || analyst.id !== analystIds[index]) return false;
        if (!ready) {
            if (analyst.metric_value !== null || analyst.percentile !== null || analyst.stance !== 'unavailable') return false;
            continue;
        }
        if (!finite(analyst.metric_value) || !percentile(analyst.percentile)
            || (index === 0 || index === 2 ? analyst.metric_value <= -1 : analyst.metric_value < 0)) return false;
        const stance = analystStance(analyst.percentile);
        if (analyst.stance !== stance) return false;
        counts[stance]++; total += analyst.percentile;
    }
    return ready ? value.comparison_count >= 8 && percentile(value.score) && Math.abs(value.score - total / analystIds.length) <= 1e-6
        && value.favorable_count === counts.favorable && value.caution_count === counts.caution && value.neutral_count === counts.neutral
        : value.score === null && value.favorable_count === 0 && value.caution_count === 0 && value.neutral_count === 0;
}
function entryGuard(value: unknown, row: AlphaLabCandidate, report: AlphaLabReport): value is AlphaLabEntryGuard {
    return record(value) && onlyKeys(value, ['policy_version', 'symbol', 'as_of', 'input_fingerprint', 'reference_price',
        'max_chase_fraction', 'max_entry_price', 'applies_to', 'backtest_applied'])
        && value.policy_version === 'reference-chase-cap-v1' && guidanceBinding(value, row, report)
        && finite(value.reference_price) && value.reference_price > 0 && value.reference_price === row.last_close
        && value.max_chase_fraction === .02 && finite(value.max_entry_price)
        && Math.abs(value.max_entry_price - Math.round(value.reference_price * 1.02 * 1e6) / 1e6) <= 1e-6
        && value.applies_to === 'manual_next_open_reference' && value.backtest_applied === false;
}
function additionalGuidance(row: AlphaLabCandidate, report: AlphaLabReport): boolean {
    return (row.analyst_context === undefined || analystContext(row.analyst_context, row, report))
        && (row.entry_guard === undefined || entryGuard(row.entry_guard, row, report));
}
const opportunityPolicy = 'quality-setup-opportunity-v1';
const opportunityBasis = 'calibration_stress_mean_then_confirmation';
const opportunityStrategies = new Set(['momentum', 'liquidity_breakout', 'mean_reversion']);
function opportunityPhase(value: unknown, minimum: number): value is AlphaLabOpportunityPhase {
    return record(value) && count(value.samples) && value.samples >= minimum
        && count(value.wins) && value.wins > 0 && count(value.losses) && value.losses > 0 && count(value.zeros)
        && value.wins + value.losses + value.zeros === value.samples && finite(value.win_rate)
        && Math.abs(value.win_rate - value.wins / value.samples) <= 1e-8
        && ['mean_net_return', 'stress_mean_net_return', 'compounded_trade_return', 'stress_compounded_trade_return'].every(key => finite(value[key]) && value[key] > 0)
        && finite(value.stress_mean_net_return) && finite(value.mean_net_return) && value.stress_mean_net_return <= value.mean_net_return + 1e-10
        && (value.return_basis === undefined || value.return_basis === 'compounded_nonoverlapping_unit_notional_trades_not_account_allocation')
        && nullableFinite(value.t_stat) && date(value.start) && date(value.end) && date(value.last_exit_session)
        && value.start <= value.last_exit_session && value.last_exit_session <= value.end && value.start < value.end;
}
function opportunityCandidate(value: unknown, report: AlphaLabReport): value is AlphaLabOpportunityCandidate {
    if (!candidate(value, opportunityStrategies) || !record(value) || !record(value.evidence) || !additionalGuidance(value, report)) return false;
    const e = value.evidence;
    if (e.selection_basis !== opportunityBasis || typeof e.stronger_evidence !== 'boolean' || e.retrospective !== true || e.independent_validation !== false
        || !opportunityPhase(e.calibration, 30) || !opportunityPhase(e.confirmation, 10)
        || e.calibration.end >= e.confirmation.start || !report.latest_session || e.confirmation.end !== report.latest_session
        || Math.abs(value.score - e.calibration.stress_mean_net_return) > 1e-8
        || value.risk.weight !== 0 || value.risk.research_weight === undefined || value.risk.research_weight <= 0 || value.risk.research_weight > .05
        || value.risk.p === null || Math.abs(value.risk.p - e.calibration.wins / (e.calibration.wins + e.calibration.losses)) > 1e-8
        || value.risk.kelly_raw === null || value.risk.kelly_raw <= 0
        || value.setup_active !== true || value.quote_session !== report.latest_session || !value.plan
        || 'approved_weight' in value && value.approved_weight !== 0
        || !finite(value.risk.quarter_kelly_fraction) || value.risk.quarter_kelly_fraction <= 0
        || Math.abs(value.risk.quarter_kelly_fraction - value.risk.kelly_raw * .25) > 1e-8
        || record(value.risk) && value.risk.planned_account_risk !== undefined && (!finite(value.risk.planned_account_risk) || value.risk.planned_account_risk < 0 || value.risk.planned_account_risk > .01 + 1e-10)) return false;
    if (e.stronger_evidence && (e.confirmation.samples < 30 || e.calibration.t_stat === null || e.calibration.t_stat < 2
        || e.confirmation.t_stat === null || e.confirmation.t_stat < 2)) return false;
    const plan = value.plan;
    const stopLoss = (plan.entry_price - plan.stop_price) / plan.entry_price;
    if (plan.loss_fraction > .08 + 1e-10 || value.last_close === null
        || Math.abs(plan.entry_price - value.last_close) > Math.max(1e-9, value.last_close * 1e-9)
        || Math.abs(plan.loss_fraction - stopLoss) > Math.max(1e-10, 1e-7 * Math.max(Math.abs(plan.loss_fraction), Math.abs(stopLoss)))
        || value.risk.research_weight * stopLoss > .01 + 1e-10
        || Math.abs(value.risk.research_weight - Math.min(value.risk.quarter_kelly_fraction, .05, .01 / stopLoss)) > 1e-8) return false;
    const p = value.proposal;
    if (p?.action !== 'buy') return true;
    if (p.proposed_weight > .05 || Math.abs(p.proposed_weight - value.risk.research_weight) > 1e-8 || p.proposed_weight * stopLoss > .01 + 1e-10
        || p.input_session !== report.latest_session || !report.decision_at || !report.provenance.captured_at) return false;
    const decision = Date.parse(report.decision_at), capture = Date.parse(report.provenance.captured_at), now = Date.now();
    const expiry = opportunityExpiry(report);
    return decision <= now + maxServerClockAheadMs && capture <= decision && Date.parse(p.derived_at) <= now + maxServerClockAheadMs
        && (expiry === null || !!p.valid_until && Date.parse(p.valid_until) === expiry);
}
function validOpportunities(report: AlphaLabReport): boolean {
    const r = report as unknown as Record<string, unknown>;
    if (r.buy_candidates === undefined && r.opportunity_scan === undefined && r.opportunity_summary === undefined) return true;
    if (!Array.isArray(r.buy_candidates) || r.buy_candidates.length > 3 || !record(r.opportunity_scan)) return false;
    const scan = r.opportunity_scan;
    if (scan.policy_version !== opportunityPolicy || scan.selection_basis !== opportunityBasis || !['ready', 'held'].includes(String(scan.status))
        || scan.latest_session !== report.latest_session || scan.lookback_sessions !== 1260 || scan.calibration_sessions !== 1008
        || scan.confirmation_sessions !== 252 || scan.horizon_sessions !== 10 || !count(scan.inspected_count) || scan.inspected_count > report.universe.quality_count
        || !count(scan.eligible_count) || scan.eligible_count < r.buy_candidates.length || scan.eligible_count > scan.inspected_count
        || !count(scan.active_setup_count) || scan.active_setup_count > scan.inspected_count * 3 || !reasons(scan.reasons)
        || scan.warnings !== undefined && !reasons(scan.warnings)) return false;
    if (scan.audit_hash !== undefined && !fingerprint(scan.audit_hash)) return false;
    if (scan.forward !== undefined && (!record(scan.forward) || !count(scan.forward.decisions) || !count(scan.forward.matured)
        || !nullableRate(scan.forward.win_rate) || !nullableFinite(scan.forward.mean_net_return)
        || scan.forward.matured === 0 && (scan.forward.win_rate !== null || scan.forward.mean_net_return !== null))) return false;
    if (r.approval !== undefined && (!record(r.approval) || r.approval.approved_exposure !== 0 || r.approval.live_orders !== false)) return false;
    const symbols = new Set<string>();
    for (const row of r.buy_candidates) {
        if (!opportunityCandidate(row, report) || symbols.has(row.symbol)) return false;
        symbols.add(row.symbol);
    }
    return r.opportunity_summary === undefined ? !r.buy_candidates.some(row => row.proposal?.action === 'buy')
        : proposalSummary(r.opportunity_summary, r.buy_candidates, opportunityPolicy);
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
        || value.input_fingerprint !== undefined && !fingerprint(value.input_fingerprint)
        || p.captured_at !== undefined && p.captured_at !== null && !utcTimestamp(p.captured_at)) return false;
    if (value.proposal_window !== undefined && !proposalWindow(value.proposal_window, value as unknown as AlphaLabReport)) return false;
    const symbols = new Set<string>();
    let exposure = 0;
    for (const row of value.candidates) {
        if (!candidate(row, ids) || symbols.has(row.symbol) || !additionalGuidance(row, value as unknown as AlphaLabReport)) return false;
        symbols.add(row.symbol); exposure += row.risk.weight;
    }
    if (value.proposal_summary !== undefined && !proposalSummary(value.proposal_summary, value.candidates)) return false;
    if (value.candidates.some(row => row.proposal?.action === 'buy') && !value.proposal_summary) return false;
    if (!value.candidates.every(row => validBuy(row, value as unknown as AlphaLabReport))) return false;
    if (!validOpportunities(value as unknown as AlphaLabReport)) return false;
    return exposure <= .6 + 1e-8 && value.agents.every(row => record(row) && label(row.id) && label(row.name)
        && label(row.status) && safeText(row.detail));
}

const operationalReasons = new Set(['missing_report', 'invalid_report', 'identity_mismatch', 'research_unavailable',
    'calendar_unavailable', 'calendar_invalid', 'calendar_stale', 'calendar_gap', 'calendar_revision', 'market_closed', 'before_open', 'after_close',
    'window_expired', 'source_stale', 'quote_unavailable', 'quote_invalid', 'quote_stale', 'quote_future', 'quote_symbol_mismatch',
    'opening_revision', 'above_ceiling', 'below_stop', 'target_reached', 'monitor_corrupt', 'capacity_exceeded']);
const operationalReasonList = (value: unknown) => reasons(value) && value.every(reason => operationalReasons.has(reason));
const monitorSource = 'KIS:J:FHKST03010200+FHKST01010100';
const quoteStates = ['wait_open', 'within_band', 'above_ceiling', 'below_stop', 'target_reached', 'closed', 'stale', 'unavailable'];
function monitorQuote(value: unknown, report: AlphaLabReport | null, bound: boolean): value is AlphaLabMonitorQuote {
    if (!record(value) || !onlyKeys(value, ['symbol', 'price', 'quote_at', 'fetched_at', 'opening_price', 'source', 'entry_state',
        'reference_price', 'entry_ceiling', 'stop_price', 'target_price', 'adjusted_plan', 'reasons'])
        || typeof value.symbol !== 'string' || !/^\d{6}$/.test(value.symbol) || !nullablePositive(value.price)
        || !nullablePositive(value.opening_price) || !nullableTimestamp(value.quote_at) || !nullableTimestamp(value.fetched_at)
        || value.source !== monitorSource || typeof value.entry_state !== 'string' || !quoteStates.includes(value.entry_state)
        || !operationalReasonList(value.reasons) || !finite(value.reference_price) || value.reference_price <= 0
        || !finite(value.entry_ceiling) || Math.abs(value.entry_ceiling - Math.round(value.reference_price * 1.02 * 1e6) / 1e6) > 1e-6
        || !finite(value.stop_price) || value.stop_price <= 0 || value.stop_price >= value.reference_price
        || !finite(value.target_price) || value.target_price <= value.reference_price) return false;
    const row = report?.buy_candidates?.find(candidate => candidate.symbol === value.symbol);
    if (bound && (!row?.plan || value.reference_price !== row.last_close || value.stop_price !== row.plan.stop_price
        || value.target_price !== row.plan.target_price)) return false;
    const p = value.adjusted_plan;
    const observed = value.price !== null && value.opening_price !== null;
    if (observed && value.entry_state === 'within_band' && (value.opening_price as number > value.entry_ceiling
        || (value.opening_price as number) < value.stop_price || !record(p))) return false;
    if (observed && value.entry_state === 'above_ceiling' && ((value.opening_price as number) <= value.entry_ceiling || p != null)) return false;
    if (observed && value.entry_state === 'below_stop' && (value.opening_price as number) >= value.stop_price && !record(p)) return false;
    if (observed && value.entry_state === 'target_reached' && !record(p)) return false;
    if (p === undefined || p === null) return true;
    if (!record(p) || !onlyKeys(p, ['entry_price', 'stop_price', 'target_price', 'loss_fraction', 'proposed_weight'])
        || !finite(p.entry_price) || p.entry_price <= 0 || p.entry_price !== value.opening_price
        || !finite(p.stop_price) || p.stop_price <= 0 || p.stop_price >= p.entry_price
        || !finite(p.target_price) || p.target_price <= p.entry_price || !finite(p.loss_fraction) || p.loss_fraction <= 0 || p.loss_fraction > .08 + 1e-10
        || !finite(p.proposed_weight) || p.proposed_weight <= 0 || p.proposed_weight > .05
        || !near(p.loss_fraction, (p.entry_price - p.stop_price) / p.entry_price) || p.proposed_weight * p.loss_fraction > .01 + 1e-10) return false;
    if (observed && (value.entry_state === 'within_band' && ((value.price as number) <= p.stop_price || (value.price as number) >= p.target_price)
        || value.entry_state === 'target_reached' && (value.price as number) < p.target_price
        || value.entry_state === 'below_stop' && (value.opening_price as number) >= value.stop_price && (value.price as number) > p.stop_price)) return false;
    if (bound) {
        if (!row?.plan?.atr || !row.risk.research_weight || p.proposed_weight > row.risk.research_weight + 1e-8) return false;
        const distance = Math.min(2 * row.plan.atr, p.entry_price * .08);
        if (!near(p.stop_price, p.entry_price - distance) || !near(p.target_price, p.entry_price + 2 * distance)) return false;
    }
    return true;
}
function validOperations(value: unknown, report: AlphaLabReport | null): value is AlphaLabOperations {
    if (!record(value) || !onlyKeys(value, ['schema_version', 'policy_version', 'generated_at', 'cadence', 'monitoring', 'paper'])
        || value.schema_version !== 1 || value.policy_version !== 'alpha-cadence-v1' || !utcTimestamp(value.generated_at)
        || Date.parse(value.generated_at) > Date.now() + maxServerClockAheadMs || !record(value.cadence) || !record(value.monitoring) || !record(value.paper)) return false;
    const c = value.cadence, m = value.monitoring, p = value.paper;
    if (!onlyKeys(c, ['timezone', 'research_time', 'monitor_interval_seconds', 'market_state', 'calendar_status', 'calendar_checked_at',
        'last_scan_at', 'next_scan_at', 'last_monitor_at', 'next_monitor_at', 'reasons'])
        || c.timezone !== 'Asia/Seoul' || c.research_time !== '18:45' || c.monitor_interval_seconds !== 300
        || typeof c.market_state !== 'string' || !['open', 'closed', 'holiday', 'unknown'].includes(c.market_state)
        || typeof c.calendar_status !== 'string' || !['ready', 'held', 'failed'].includes(c.calendar_status)
        || !['calendar_checked_at', 'last_scan_at', 'next_scan_at', 'last_monitor_at', 'next_monitor_at'].every(key => nullableTimestamp(c[key]))
        || !operationalReasonList(c.reasons)) return false;
    if (!onlyKeys(m, ['status', 'decision_at', 'origin_at', 'input_fingerprint', 'opportunity_audit_hash', 'entry_session', 'valid_until', 'observed_at', 'quotes', 'reasons'])
        || typeof m.status !== 'string' || !['ready', 'held', 'failed'].includes(m.status)
        || !['decision_at', 'origin_at', 'valid_until', 'observed_at'].every(key => nullableTimestamp(m[key]))
        || !(m.input_fingerprint === null || fingerprint(m.input_fingerprint)) || !(m.opportunity_audit_hash === null || fingerprint(m.opportunity_audit_hash))
        || !(m.entry_session === null || date(m.entry_session)) || (m.entry_session === null) !== (m.valid_until === null)
        || m.entry_session !== null && Date.parse(m.valid_until as string) !== sessionClose(m.entry_session as string)
        || !Array.isArray(m.quotes) || m.quotes.length > 3 || !operationalReasonList(m.reasons)) return false;
    const operations = value as unknown as AlphaLabOperations;
    const bound = monitorIdentity(operations, report);
    const symbols = new Set<string>();
    for (const quote of m.quotes) {
        if (!monitorQuote(quote, report, bound) || symbols.has(quote.symbol)) return false;
        symbols.add(quote.symbol);
    }
    const counts = p.counts;
    if (!onlyKeys(p, ['decisions', 'matured', 'win_rate', 'mean_net_return', 'counts', 'excluded_revised_closed', 'basis', 'entry_guard_applied', 'revision_policy'])
        || !count(p.decisions) || !count(p.matured) || !nullableRate(p.win_rate) || !nullableFinite(p.mean_net_return)
        || !record(counts) || !onlyKeys(counts, ['pending', 'open', 'unfilled', 'missing_session', 'source_revision', 'closed'])
        || !['pending', 'open', 'unfilled', 'missing_session', 'source_revision', 'closed'].every(key => count(counts[key]))
        || !count(p.excluded_revised_closed) || p.excluded_revised_closed > (counts.closed as number)
        || p.matured !== (counts.closed as number) - p.excluded_revised_closed
        || (p.matured === 0 ? p.win_rate !== null || p.mean_net_return !== null : !finite(p.win_rate) || !finite(p.mean_net_return))
        || p.basis !== 'frozen_watchlist_next_open_outcomes_not_account_pnl' || p.entry_guard_applied !== false
        || p.revision_policy !== undefined && p.revision_policy !== 'preserve_terminal_result_exclude_revised_closed_from_statistics') return false;
    return true;
}
/** Reevaluated on idle/focus as well as GET: old prices cannot survive a failed or expired observation. */
export function liveAlphaLabMonitoring(status: AlphaLabStatus, now = Date.now(), blocked = false): AlphaLabOperations['monitoring'] | null {
    const operations = status.operations;
    if (!operations) return null;
    const m = operations.monitoring;
    const bound = monitorIdentity(operations, status.report);
    const localTime = ((now + 9 * 3600000) % 86400000 + 86400000) % 86400000;
    const active = !blocked && bound && ['ready', 'held'].includes(status.state) && status.report?.opportunity_scan?.status === 'ready'
        && !status.report.opportunity_scan.reasons.some(reason => currentSourceBlocks.has(reason) || reason.includes('refresh_failed'))
        && operations.cadence.calendar_status === 'ready' && operations.cadence.market_state === 'open' && m.status === 'ready'
        && localTime >= 9 * 3600000 && localTime < 15.5 * 3600000
        && !m.reasons.some(reason => ['identity_mismatch', 'research_unavailable', 'source_stale', 'quote_unavailable', 'quote_invalid', 'monitor_corrupt'].includes(reason));
    const quotes = m.quotes.map(quote => {
        const at = Date.parse(quote.quote_at ?? ''), fetched = Date.parse(quote.fetched_at ?? '');
        const fresh = active && quote.price !== null && quote.opening_price !== null && Number.isFinite(at) && Number.isFinite(fetched)
            && at <= now + maxServerClockAheadMs && fetched <= now + maxServerClockAheadMs && at <= fetched && fetched - at <= 120000
            && now - at < 420000 && now - fetched < 420000 && kstDay(at) === kstDay(now)
            && !!m.entry_session && kstDay(at) >= kstDay(sessionClose(m.entry_session))
            && !['stale', 'unavailable', 'wait_open', 'closed'].includes(quote.entry_state);
        if (fresh) return quote;
        const untouched = quote.price === null && ['wait_open', 'closed', 'unavailable', 'stale'].includes(quote.entry_state);
        return { ...quote, price: null, opening_price: null, adjusted_plan: null,
            entry_state: (!bound ? 'unavailable' : untouched ? quote.entry_state : 'stale') as AlphaLabMonitorQuote['entry_state'],
            reasons: untouched && bound ? quote.reasons : Array.from(new Set([...quote.reasons, !bound ? 'identity_mismatch' : 'quote_stale'])) };
    });
    return { ...m, status: active || m.status === 'failed' ? m.status : 'held', quotes };
}
/** Only finite, identified research evidence crosses the API boundary; raw worker errors are never rendered. */
export function validateAlphaLabStatus(value: unknown): AlphaLabStatus {
    if (!record(value) || value.schema_version !== 1 || !['missing', 'running', 'ready', 'held', 'failed'].includes(String(value.state))
        || !(value.generated_at === null || timestamp(value.generated_at)) || !(value.error === null || typeof value.error === 'string')
        || !(value.report === null || validReport(value.report))
        || ['ready', 'held'].includes(String(value.state)) && value.report === null
        || value.operations !== undefined && !validOperations(value.operations, value.report as AlphaLabReport | null)) throw new Error(invalid);
    if (value.opportunity_engine !== undefined) validateOpportunityEngine(value.opportunity_engine, {
        input_fingerprint: (value.report as AlphaLabReport | null)?.input_fingerprint,
        latest_session: (value.report as AlphaLabReport | null)?.latest_session,
        source_audit_hash: (value.report as AlphaLabReport | null)?.opportunity_scan?.audit_hash,
    });
    const status = value as unknown as AlphaLabStatus;
    if (!status.report) return { ...status, operations: status.operations ? { ...status.operations, monitoring: liveAlphaLabMonitoring(status)! } : undefined };
    const normalizeProposal = (row: AlphaLabCandidate, opportunity = false) => {
        const p = row.proposal;
        const scanReady = !opportunity || status.report!.opportunity_scan?.status === 'ready'
            && !status.report!.opportunity_scan.reasons.some(reason => currentSourceBlocks.has(reason) || reason.includes('refresh_failed'));
        if (p?.action !== 'buy' || scanReady && ['ready', 'held'].includes(status.state) && freshBuy(row, status.report!, Date.now(), opportunity, status.operations)) return p;
        return { ...p, action: 'wait' as const, label: '진입 대기' as const, proposed_weight: 0,
            reason: '제안이 만료되었거나 최신 검사 결과를 확인 중입니다.', next_step: '저장 결과를 다시 확인한 뒤 판단하세요.' };
    };
    const candidates = status.report.candidates.map(row => { const p = normalizeProposal(row); return p === row.proposal ? row : { ...row, proposal: p }; });
    const buyCandidates = status.report.buy_candidates?.map(row => { const p = normalizeProposal(row, true); return p === row.proposal ? row : { ...row, proposal: p }; });
    const normalizedSummary = <T extends AlphaLabProposalSummary | AlphaLabOpportunitySummary>(summary: T | undefined, rows: AlphaLabCandidate[], oldRows: AlphaLabCandidate[]) => {
        if (!summary || rows.every((row, index) => row === oldRows[index])) return summary;
        const buy = rows.filter(row => row.proposal?.action === 'buy').length;
        const wait = rows.filter(row => !row.proposal || row.proposal.action === 'wait').length;
        return { ...summary, action: (buy ? 'buy' : wait || !rows.length ? 'wait' : 'avoid') as AlphaLabAction,
            buy_count: buy, wait_count: wait, avoid_count: rows.length - buy - wait, headline: buy ? summary.headline : '오늘 제안: 진입 대기',
            reason: '만료되었거나 갱신 중인 매수 제안은 대기로 전환했습니다.' };
    };
    return { ...status, operations: status.operations ? { ...status.operations, monitoring: liveAlphaLabMonitoring(status)! } : undefined,
        report: { ...status.report, candidates, buy_candidates: buyCandidates,
        proposal_summary: normalizedSummary(status.report.proposal_summary, candidates, status.report.candidates),
        opportunity_summary: buyCandidates && normalizedSummary(status.report.opportunity_summary, buyCandidates, status.report.buy_candidates!) } };
}
export async function fetchAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await fetchAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', token));
}
export async function startAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await postAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', {}, token));
}
