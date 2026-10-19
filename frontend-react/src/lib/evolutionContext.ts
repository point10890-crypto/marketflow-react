import type { OpportunityIdentity } from './opportunityEngine';

export type EvolutionArmId = 'control' | 'entry-band-v1' | 'recovery-confirmed-v1' | 'positive-rank-v1';
export interface EvolutionMetrics {
    mean_net_return: number | null; stress_mean_net_return: number | null;
    paired_advantage: number | null; stress_paired_advantage: number | null; downside_tail_loss: number | null;
}
export interface EvolutionArm {
    id: EvolutionArmId; label: string;
    selected: Array<{ symbol: string; name: string; market: 'KR'; strategy_id: string; slot: number }>;
    counts: { entered: number; resolved: number; closed: number; skipped: number; cash: number; unfilled: number;
        pending: number; open: number; missing: number; revised: number; paired_sessions: number;
        missed_control_winners: number; avoided_control_losers: number };
    metrics: EvolutionMetrics; reasons: string[];
}
export interface EvolutionContext {
    schema_version: 1; protocol_version: 'alpha-evolution-v1'; protocol_hash: string;
    generated_at: string; declared_at: string; status_id: string; status: 'ready' | 'held';
    binding: OpportunityIdentity;
    phase: 'collecting_nomination' | 'embargo' | 'collecting_confirmation' | 'maturing' | 'awaiting_review' | 'incumbent_retained';
    next_step: string; research_only: true; live_orders: false; approved_exposure: 0;
    return_basis: 'equal_three_slot_watchlist_not_account_pnl';
    window: { decision_sessions: number; nomination_sessions: number; embargo_sessions: number; confirmation_sessions: number; maturation_sessions: number;
        block_sessions: number; minimum_blocks: number; enrolled_sessions: number; resolved_sessions: number; maturation_observed: number };
    nomination: { status: 'pending' | 'fixed' | 'none'; arm_id: EvolutionArmId | null; session_count: 36; reason: string };
    review: { status: 'collecting' | 'awaiting_review' | 'rejected'; arm_id: EvolutionArmId | null; reasons: string[]; limitations: string[];
        entered_outcomes: number; control_entered_outcomes: number; completed_blocks: number;
        normal_mean: number | null; stress_mean: number | null; paired_advantage: number | null;
        stress_paired_advantage: number | null; block_lower_bound: number | null; downside_tail_delta: number | null };
    arms: EvolutionArm[]; reasons: string[];
    /** Browser-derived binding state; never an authorization or a strategy promotion. */
    binding_status?: 'current' | 'mismatch';
}

export const evolutionArmIds: EvolutionArmId[] = ['control', 'entry-band-v1', 'recovery-confirmed-v1', 'positive-rank-v1'];
const identityKeys = ['decision_id', 'input_fingerprint', 'source_audit_hash'] as const;
const metricKeys = ['mean_net_return', 'stress_mean_net_return', 'paired_advantage', 'stress_paired_advantage', 'downside_tail_loss'];
const reviewMetricKeys = ['normal_mean', 'stress_mean', 'paired_advantage', 'stress_paired_advantage', 'block_lower_bound', 'downside_tail_delta'];
const countKeys = ['entered', 'resolved', 'closed', 'skipped', 'cash', 'unfilled', 'pending', 'open', 'missing', 'revised', 'paired_sessions', 'missed_control_winners', 'avoided_control_losers'];
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const keys = (v: Record<string, unknown>, required: string[], optional: string[] = []) => required.every(key => Object.prototype.hasOwnProperty.call(v, key))
    && Object.keys(v).every(key => required.includes(key) || optional.includes(key));
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max = 300): v is string => typeof v === 'string' && !!v.trim() && v.length <= max
    && !/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069<>\\]|[A-Za-z]:\/|\/(?:home|srv|tmp|users|private|etc|var|root)\b|\.env\b|(?:미래|예상|상승|하락)\s*(?:승률|확률)\s*[:=]?\s*\d|(?:수익|승률).*보장/i.test(v)
    && !/(?:^|[^a-z0-9])(?:api[_-]?key|access[_-]?token|secret|password|credentials?|authorization|bearer|traceback|token[_-]?cache)(?:$|[^a-z0-9])/i.test(v);
const reasons = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 30 && v.every(item => text(item, 300));
const count = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= 1_000_000;
// Bounds prevent arithmetic overflow while preserving signed descriptive paper returns.
const metric = (v: unknown): v is number | null => v === null || typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 100;
function timestamp(v: unknown): v is string {
    return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
        && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
}
const validArmId = (v: unknown): v is EvolutionArmId => evolutionArmIds.includes(v as EvolutionArmId);
const oneOf = (v: unknown, allowed: string[]): v is string => typeof v === 'string' && allowed.includes(v);
const challenger = (v: unknown) => validArmId(v) && v !== 'control';
function validArm(value: unknown, window: EvolutionContext['window']): value is EvolutionArm {
    if (!record(value) || !keys(value, ['id', 'label', 'selected', 'counts', 'metrics', 'reasons']) || !validArmId(value.id) || !text(value.label, 100)
        || !Array.isArray(value.selected) || value.selected.length > 3 || !reasons(value.reasons)
        || !record(value.counts) || !keys(value.counts, countKeys) || !countKeys.every(key => count(value.counts && (value.counts as Record<string, unknown>)[key]))
        || !record(value.metrics) || !keys(value.metrics, metricKeys) || !metricKeys.every(key => metric(value.metrics && (value.metrics as Record<string, unknown>)[key]))) return false;
    const arm = value as unknown as EvolutionArm, c = arm.counts;
    const total = c.closed + c.skipped + c.cash + c.unfilled + c.pending + c.open + c.missing;
    if (total !== window.enrolled_sessions * 3 || c.entered !== c.closed + c.open + c.missing || c.resolved !== c.closed + c.skipped + c.cash + c.unfilled
        || c.revised > total || c.paired_sessions > window.resolved_sessions || c.paired_sessions > Math.floor(c.resolved / 3)
        || c.missed_control_winners > total || c.avoided_control_losers > total
        || c.paired_sessions === 0 && Object.values(arm.metrics).some(v => v !== null)
        || arm.metrics.downside_tail_loss !== null && arm.metrics.downside_tail_loss < 0) return false;
    const symbols = new Set<string>(), slots = new Set<number>();
    for (const row of arm.selected) {
        if (!record(row) || !keys(row, ['symbol', 'name', 'market', 'strategy_id', 'slot']) || typeof row.symbol !== 'string' || !/^\d{6}$/.test(row.symbol) || row.symbol === '000000'
            || !text(row.name, 120) || row.market !== 'KR' || !oneOf(row.strategy_id, ['momentum', 'liquidity_breakout', 'mean_reversion'])
            || !count(row.slot) || row.slot < 1 || row.slot > 3 || symbols.has(row.symbol) || slots.has(row.slot)) return false;
        symbols.add(row.symbol); slots.add(row.slot);
    }
    return true;
}
const nullMetrics = (): EvolutionMetrics => ({ mean_net_return: null, stress_mean_net_return: null, paired_advantage: null, stress_paired_advantage: null, downside_tail_loss: null });

/** Invalid optional evidence disappears; foreign bindings become a visible, non-authorizing hold. */
export function validateEvolutionContext(value: unknown, board?: OpportunityIdentity, now = Date.now()): EvolutionContext | undefined {
    if (!Number.isFinite(now) || !record(value) || !keys(value, ['schema_version', 'protocol_version', 'protocol_hash', 'generated_at', 'declared_at', 'status_id', 'status',
        'binding', 'phase', 'next_step', 'research_only', 'live_orders', 'approved_exposure', 'return_basis', 'window', 'nomination', 'review', 'arms', 'reasons'], ['binding_status'])
        || value.schema_version !== 1 || value.protocol_version !== 'alpha-evolution-v1' || !hash(value.protocol_hash) || !hash(value.status_id)
        || !timestamp(value.generated_at) || !timestamp(value.declared_at) || Date.parse(value.generated_at) > now || Date.parse(value.declared_at) > Date.parse(value.generated_at)
        || !oneOf(value.status, ['ready', 'held']) || !record(value.binding) || !keys(value.binding, [...identityKeys]) || !identityKeys.every(key => hash((value.binding as Record<string, unknown>)[key]))
        || !oneOf(value.phase, ['collecting_nomination', 'embargo', 'collecting_confirmation', 'maturing', 'awaiting_review', 'incumbent_retained'])
        || !text(value.next_step) || value.research_only !== true || value.live_orders !== false || value.approved_exposure !== 0 || value.return_basis !== 'equal_three_slot_watchlist_not_account_pnl'
        || !reasons(value.reasons)
        || !record(value.window) || !keys(value.window, ['decision_sessions', 'nomination_sessions', 'embargo_sessions', 'confirmation_sessions', 'maturation_sessions', 'block_sessions', 'minimum_blocks', 'enrolled_sessions', 'resolved_sessions', 'maturation_observed'])
        || !Object.values(value.window).every(count) || !record(value.nomination) || !record(value.review) || !Array.isArray(value.arms) || value.arms.length !== 4) return undefined;
    const result = value as unknown as EvolutionContext, w = result.window, n = result.nomination, r = result.review;
    if (w.nomination_sessions !== 36 || w.embargo_sessions !== 10 || w.confirmation_sessions !== 60 || w.decision_sessions !== w.nomination_sessions + w.embargo_sessions + w.confirmation_sessions
        || w.maturation_sessions !== 10 || w.block_sessions !== 10 || w.minimum_blocks !== 6 || w.enrolled_sessions > w.decision_sessions || w.resolved_sessions > w.enrolled_sessions || w.maturation_observed > w.maturation_sessions
        || !keys(value.nomination, ['status', 'arm_id', 'session_count', 'reason']) || !['pending', 'fixed', 'none'].includes(n.status) || n.session_count !== w.nomination_sessions || !text(n.reason)
        || (n.status === 'fixed' ? !challenger(n.arm_id) : n.arm_id !== null)
        || !keys(value.review, ['status', 'arm_id', 'reasons', 'limitations', 'entered_outcomes', 'control_entered_outcomes', 'completed_blocks', ...reviewMetricKeys]) || !['collecting', 'awaiting_review', 'rejected'].includes(r.status) || !reasons(r.reasons) || !reasons(r.limitations)
        || !count(r.entered_outcomes) || !count(r.control_entered_outcomes) || !count(r.completed_blocks)
        || r.entered_outcomes > w.confirmation_sessions * 3 || r.control_entered_outcomes > w.confirmation_sessions * 3 || r.completed_blocks > w.confirmation_sessions / w.block_sessions
        || !(r.arm_id === null || challenger(r.arm_id)) || !reviewMetricKeys.every(key => metric((value.review as Record<string, unknown>)[key]))
        || r.arm_id !== null && r.arm_id !== n.arm_id || !result.arms.every(arm => validArm(arm, w))
        || new Set(result.arms.map(arm => arm.id)).size !== 4) return undefined;
    if (result.phase === 'awaiting_review' && r.status !== 'awaiting_review' || result.phase === 'incumbent_retained' && r.status !== 'rejected') return undefined;
    const current = !!board && identityKeys.every(key => result.binding[key] === board[key]);
    const reviewArms = result.arms.filter(arm => arm.id === 'control' || arm.id === r.arm_id);
    if (current && r.status === 'awaiting_review' && (result.phase !== 'awaiting_review' || n.status !== 'fixed' || r.arm_id !== n.arm_id || w.enrolled_sessions !== w.decision_sessions || w.resolved_sessions !== w.decision_sessions
        || reviewArms.some(arm => arm.counts.revised > 0 || arm.counts.paired_sessions !== w.decision_sessions)
        || r.entered_outcomes < 30 || r.control_entered_outcomes < 30 || r.completed_blocks < w.minimum_blocks || r.normal_mean === null || r.normal_mean <= 0 || r.stress_mean === null || r.stress_mean <= 0 || r.paired_advantage === null || r.paired_advantage <= 0
        || r.stress_paired_advantage === null || r.stress_paired_advantage <= 0 || r.block_lower_bound === null || r.block_lower_bound <= 0 || r.downside_tail_delta === null || r.downside_tail_delta > 0)) return undefined;
    if (current) return { ...result, binding_status: 'current' };
    return { ...result, status: 'held', binding_status: 'mismatch', next_step: '현재 선정과 저장 관측의 연결을 확인하세요.',
        arms: result.arms.map(arm => ({ ...arm, selected: [], metrics: nullMetrics() })),
        review: { ...r, normal_mean: null, stress_mean: null, paired_advantage: null, stress_paired_advantage: null, block_lower_bound: null, downside_tail_delta: null },
        reasons: [...new Set([...result.reasons, 'current_identity_mismatch'])] };
}
