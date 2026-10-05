export type OpportunityAction = 'entry_candidate' | 'wait_next_session' | 'data_check' | 'skip';
export type OpportunityStrategy = 'momentum' | 'liquidity_breakout' | 'mean_reversion';
export interface OpportunityIdentity { decision_id: string; input_fingerprint: string; source_audit_hash: string }
export interface ProfitOpportunity extends OpportunityIdentity {
    opportunity_id: string; symbol: string; name: string; market: 'KR'; strategy_id: OpportunityStrategy; rank: number;
    action: OpportunityAction; label: string; why_stock: string; why_now: string; next_action: string;
    quote_session: string; source_at: string | null; current_price: number | null; quote_at: string | null; fetched_at: string | null;
    quote_source: 'KIS:J:FHKST03010200+FHKST01010100' | null; valid_until: string | null; reference_weight: number;
    plan: { basis: 'last_closed_price_reference' | 'observed_quote_reference'; entry_low: number; entry_high: number; stop_price: number; target_price: number; horizon_sessions: 10 };
    ranking: { stress_mean_net_return: number; standard_error: number; conservative_score: number; correlation_penalty: number;
        score: number; calibration_samples: number; confirmation_samples: number };
    kelly: { raw_fraction: number; fraction: .25; cap: .05; account_risk_cap: .01 };
    audit: { status: 'passed' | 'held' | 'unavailable'; reasons: string[]; independent_validation: false }; reasons: string[];
}
export interface OpportunityEngine extends OpportunityIdentity {
    schema_version: 1; policy_version: 'profit-opportunity-v1'; generated_at: string; latest_session: string; entry_session: string | null;
    valid_until: string | null; status: 'ready' | 'held'; research_only: true; live_orders: false;
    coverage: { inspected: number; eligible: number; selected: number }; candidates: ProfitOpportunity[];
    alternatives: Array<{ symbol: string; name: string; strategy_id: OpportunityStrategy; score: number | null; reason: string }>;
    stages: Array<{ id: string; status: 'passed' | 'held' | 'unavailable'; detail: string; count: number }>; reasons: string[];
    evaluation?: { basis: 'issued_opportunities_not_fills'; issued: number; pending: number; expired: number; observed: number; unobserved: number };
}
const invalid = '수익 기회 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const count = (value: unknown): value is number => finite(value) && Number.isSafeInteger(value) && value >= 0;
const positive = (value: unknown): value is number => finite(value) && value > 0;
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const symbol = (value: unknown): value is string => typeof value === 'string' && /^\d{6}$/.test(value);
const keys = (value: Record<string, unknown>, allowed: string[], optional: string[] = []) =>
    Object.keys(value).every(key => allowed.includes(key) || optional.includes(key)) && allowed.every(key => Object.prototype.hasOwnProperty.call(value, key));
const safeText = (value: unknown, max = 500): value is string => typeof value === 'string' && !!value.trim() && value.length <= max
    && !/[\u0000-\u001f\u007f]|[A-Za-z]:[\\/]|(?:^|\s)\/(?:home|srv|tmp|Users|private)\b|\.env\b|(?:api[_-]?key|access[_-]?token|secret)\s*[:=]|<[^>]*>|\bBearer\s|\bTraceback\b|(?:미래|예상)\s*승률|(?:수익|승률).*보장|100\s*%\s*보장/i.test(value);
const reasons = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(item => safeText(item, 160));
const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const timestamp = (value: unknown): value is string => typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
const nullableTime = (value: unknown) => value === null || timestamp(value);
const strategy = (value: unknown): value is OpportunityStrategy => typeof value === 'string' && ['momentum', 'liquidity_breakout', 'mean_reversion'].includes(value);
const auditStatus = (value: unknown) => typeof value === 'string' && ['passed', 'held', 'unavailable'].includes(value);
const near = (left: number, right: number) => Math.abs(left - right) <= Math.max(1e-8, Math.abs(right) * 1e-8);
const sessionClose = (value: string) => Date.parse(`${value}T15:30:00+09:00`);
const kstDay = (value: number) => new Date(value + 9 * 3600000).toISOString().slice(0, 10);
const sourceExpiry = (value: string) => (Math.floor((Date.parse(value) + 9 * 3600000) / 86400000) + 8) * 86400000 - 9 * 3600000;
const identityKeys = ['decision_id', 'input_fingerprint', 'source_audit_hash'];
const bound = (row: OpportunityIdentity, board: OpportunityIdentity) => identityKeys.every(key => row[key as keyof OpportunityIdentity] === board[key as keyof OpportunityIdentity]);
const blockedReasons = new Set(['saved_board_invalid', 'scan_unavailable', 'entry_window_changed', 'entry_window_unavailable', 'source_identity_unavailable']);
const blockingReason = (reason: string) => blockedReasons.has(reason)
    || /(?:stale|future|expired|mismatch|corrupt|refresh_failed|calendar_(?:unavailable|invalid|gap|revision)|quote_(?:unavailable|invalid)|source_(?:unavailable|failure)|missing_(?:source|fingerprint|window))/.test(reason);
function validCandidate(value: unknown, board: OpportunityEngine, index: number): value is ProfitOpportunity {
    if (!record(value) || !keys(value, [...identityKeys, 'opportunity_id', 'symbol', 'name', 'market', 'strategy_id', 'rank', 'action', 'label',
        'why_stock', 'why_now', 'next_action', 'quote_session', 'source_at', 'current_price', 'quote_at', 'fetched_at', 'quote_source', 'valid_until',
        'reference_weight', 'plan', 'ranking', 'kelly', 'audit', 'reasons'])
        || !identityKeys.every(key => hash(value[key])) || !bound(value as unknown as OpportunityIdentity, board)
        || !hash(value.opportunity_id) || !symbol(value.symbol) || !safeText(value.name, 100) || value.market !== 'KR' || !strategy(value.strategy_id)
        || value.rank !== index + 1 || !['entry_candidate', 'wait_next_session', 'data_check', 'skip'].includes(String(value.action))
        || !['label', 'why_stock', 'why_now', 'next_action'].every(key => safeText(value[key]))
        || value.quote_session !== board.latest_session || !nullableTime(value.source_at) || !nullableTime(value.quote_at) || !nullableTime(value.fetched_at)
        || !(value.current_price === null || positive(value.current_price))
        || !(value.quote_source === null || value.quote_source === 'KIS:J:FHKST03010200+FHKST01010100')
        || value.valid_until !== board.valid_until || !finite(value.reference_weight) || value.reference_weight < 0 || value.reference_weight > .05 + 1e-8
        || !reasons(value.reasons) || !record(value.plan) || !record(value.ranking) || !record(value.kelly) || !record(value.audit)) return false;
    const p = value.plan, r = value.ranking, k = value.kelly, a = value.audit;
    if (!keys(p, ['basis', 'entry_low', 'entry_high', 'stop_price', 'target_price', 'horizon_sessions'])
        || !['last_closed_price_reference', 'observed_quote_reference'].includes(String(p.basis)) || p.horizon_sessions !== 10
        || !['entry_low', 'entry_high', 'stop_price', 'target_price'].every(key => positive(p[key]))
        || !((p.stop_price as number) < (p.entry_low as number) && (p.entry_low as number) <= (p.entry_high as number) && (p.entry_high as number) < (p.target_price as number))
        || !keys(r, ['stress_mean_net_return', 'standard_error', 'conservative_score', 'correlation_penalty', 'score', 'calibration_samples', 'confirmation_samples'])
        || !['stress_mean_net_return', 'standard_error', 'conservative_score', 'correlation_penalty', 'score'].every(key => finite(r[key]))
        || (r.standard_error as number) < 0 || (r.correlation_penalty as number) < 0 || (r.correlation_penalty as number) > .01 + 1e-8
        || !count(r.calibration_samples) || !count(r.confirmation_samples)
        || !near(r.conservative_score as number, (r.stress_mean_net_return as number) - 1.96 * (r.standard_error as number))
        || !near(r.score as number, (r.conservative_score as number) - (r.correlation_penalty as number))
        || !keys(k, ['raw_fraction', 'fraction', 'cap', 'account_risk_cap']) || !finite(k.raw_fraction)
        || k.fraction !== .25 || k.cap !== .05 || k.account_risk_cap !== .01
        || value.reference_weight > Math.max(0, k.raw_fraction) * .25 + 1e-8
        || value.reference_weight * (1 - (p.stop_price as number) / (p.entry_low as number)) > .01 + 1e-8
        || !keys(a, ['status', 'reasons', 'independent_validation']) || !auditStatus(a.status) || !reasons(a.reasons) || a.independent_validation !== false) return false;
    if (value.current_price !== null && (value.quote_at === null || value.fetched_at === null || value.quote_source === null)) return false;
    if (value.action === 'entry_candidate' && (p.basis !== 'observed_quote_reference' || value.current_price === null
        || !near(value.current_price, p.entry_low as number) || value.reference_weight <= 0 || a.status !== 'passed')) return false;
    return true;
}
/** Public projection only: no raw internal fields or unbound guidance crosses this boundary. */
export function validateOpportunityEngine(value: unknown, binding?: { input_fingerprint?: string; latest_session?: string | null; source_audit_hash?: string }): OpportunityEngine {
    if (!record(value) || !keys(value, ['schema_version', 'policy_version', ...identityKeys, 'generated_at', 'latest_session', 'entry_session', 'valid_until',
        'status', 'research_only', 'live_orders', 'coverage', 'candidates', 'alternatives', 'stages', 'reasons'], ['evaluation'])
        || value.schema_version !== 1 || value.policy_version !== 'profit-opportunity-v1' || !identityKeys.every(key => hash(value[key]))
        || !timestamp(value.generated_at) || !date(value.latest_session) || !(value.entry_session === null || date(value.entry_session))
        || !nullableTime(value.valid_until) || (value.entry_session === null) !== (value.valid_until === null)
        || value.entry_session !== null && (value.entry_session <= value.latest_session || Date.parse(value.valid_until as string) !== sessionClose(value.entry_session))
        || !['ready', 'held'].includes(String(value.status)) || value.research_only !== true || value.live_orders !== false
        || !record(value.coverage) || !keys(value.coverage, ['inspected', 'eligible', 'selected'])
        || !['inspected', 'eligible', 'selected'].every(key => count((value.coverage as Record<string, unknown>)[key]))
        || !Array.isArray(value.candidates) || value.candidates.length > 3 || value.coverage.selected !== value.candidates.length
        || (value.coverage.selected as number) > (value.coverage.eligible as number) || (value.coverage.eligible as number) > (value.coverage.inspected as number)
        || !Array.isArray(value.alternatives) || value.alternatives.length > 10 || !Array.isArray(value.stages) || value.stages.length > 12 || !reasons(value.reasons)) throw new Error(invalid);
    const board = value as unknown as OpportunityEngine;
    if (binding && (binding.input_fingerprint !== undefined && board.input_fingerprint !== binding.input_fingerprint
        || binding.latest_session != null && board.latest_session !== binding.latest_session
        || binding.source_audit_hash !== undefined && board.source_audit_hash !== binding.source_audit_hash)) throw new Error(invalid);
    const symbols = new Set<string>(), opportunities = new Set<string>();
    let weight = 0, lastScore = Infinity;
    for (const [index, row] of board.candidates.entries()) {
        if (!validCandidate(row, board, index) || symbols.has(row.symbol) || opportunities.has(row.opportunity_id) || row.ranking.score > lastScore + 1e-8) throw new Error(invalid);
        symbols.add(row.symbol); opportunities.add(row.opportunity_id); weight += row.reference_weight; lastScore = row.ranking.score;
    }
    if (weight > .15 + 1e-8) throw new Error(invalid);
    for (const row of board.alternatives) {
        if (!record(row) || !keys(row, ['symbol', 'name', 'strategy_id', 'score', 'reason']) || !symbol(row.symbol) || !safeText(row.name, 100)
            || !strategy(row.strategy_id) || !(row.score === null || finite(row.score)) || !safeText(row.reason, 160) || symbols.has(row.symbol)) throw new Error(invalid);
        symbols.add(row.symbol);
    }
    const stages = new Set<string>();
    for (const row of board.stages) {
        if (!record(row) || !keys(row, ['id', 'status', 'detail', 'count']) || typeof row.id !== 'string'
            || !['data', 'setup', 'critic', 'diversification', 'risk', 'entry'].includes(row.id) || stages.has(row.id)
            || !auditStatus(row.status) || !safeText(row.detail) || !count(row.count)) throw new Error(invalid);
        stages.add(row.id);
    }
    const e = board.evaluation;
    if (e !== undefined && (!record(e) || !keys(e, ['basis', 'issued', 'pending', 'expired', 'observed', 'unobserved'])
        || e.basis !== 'issued_opportunities_not_fills' || !['issued', 'pending', 'expired', 'observed', 'unobserved'].every(key => count((e as unknown as Record<string, unknown>)[key]))
        || e.pending + e.expired + e.observed + e.unobserved !== e.issued)) throw new Error(invalid);
    return board;
}
export const opportunityActionLabels: Record<OpportunityAction, string> = {
    entry_candidate: '매수 제안 · 진입 조건 충족', wait_next_session: '매수 후보 · 다음 장 대기', data_check: '매수 후보 · 가격 확인 대기', skip: '진입 대기 · 가격 조건 미충족',
};
/** Rechecked with the panel clock, never upgrades a server WAIT or extends the original entry deadline. */
export function effectiveOpportunityEngine(board: OpportunityEngine, now = Date.now(), blocked = false): OpportunityEngine {
    const day = kstDay(now), time = (now + 9 * 3600000) % 86400000;
    const boardProblems = blocked || !board.entry_session || !board.valid_until
        || now >= Date.parse(board.valid_until) || board.reasons.some(blockingReason)
        || Date.parse(board.generated_at) > now || now >= sourceExpiry(`${board.latest_session}T00:00:00Z`);
    const beforeOpen = !!board.entry_session && (day < board.entry_session || day === board.entry_session && time < 9 * 3600000);
    const candidates = board.candidates.map(row => {
        const quote = Date.parse(row.quote_at ?? ''), fetched = Date.parse(row.fetched_at ?? ''), source = Date.parse(row.source_at ?? '');
        const problems = boardProblems || !Number.isFinite(source) || source > now || now >= sourceExpiry(row.source_at!)
            || row.audit.status !== 'passed' || [...row.reasons, ...row.audit.reasons].some(blockingReason);
        const fresh = !problems && bound(row, board) && day === board.entry_session && time >= 9 * 3600000 && time < 15.5 * 3600000
            && row.quote_source === 'KIS:J:FHKST03010200+FHKST01010100' && Number.isFinite(quote) && Number.isFinite(fetched)
            && quote <= now && fetched <= now && quote <= fetched && fetched - quote <= 120000
            && now - quote < 420000 && now - fetched < 420000 && kstDay(quote) === day && kstDay(fetched) === day;
        let action = row.action;
        if (problems) action = row.action === 'skip' ? 'skip' : 'data_check';
        else if (beforeOpen) action = row.action === 'skip' ? 'skip' : 'wait_next_session';
        else if (row.action === 'entry_candidate' && (board.status !== 'ready' || !fresh || row.plan.basis !== 'observed_quote_reference')) action = 'data_check';
        else if (fresh && row.current_price !== null && (row.current_price > row.plan.entry_high || row.current_price <= row.plan.stop_price || row.current_price >= row.plan.target_price)) action = 'skip';
        const downgrade = action !== row.action || !fresh;
        return { ...row, action, label: opportunityActionLabels[action],
            ...(downgrade ? { current_price: null, quote_at: null, fetched_at: null, quote_source: null,
                why_now: action === 'skip' ? '신규 진입 가격 조건을 충족하지 못했습니다.' : action === 'wait_next_session' ? '공식 다음 거래일의 새 가격 관측을 기다립니다.' : '최신 자료 또는 진입 유효기간을 다시 확인해야 합니다.',
                next_action: action === 'skip' ? '진입을 보류하고 새 연구 결과에서 조건을 다시 확인하세요.' : '저장 결과의 자료와 가격이 갱신될 때까지 진입을 기다리세요.' } : {}) };
    });
    return { ...board, status: boardProblems ? 'held' : board.status, candidates };
}
/** Shares AlphaLabPanel's one local timer; this function never fetches providers or status. */
export function opportunityClockExpirations(board: OpportunityEngine): number[] {
    return [Date.parse(board.valid_until ?? ''), sourceExpiry(`${board.latest_session}T00:00:00Z`),
        ...board.candidates.flatMap(row => [Date.parse(row.quote_at ?? '') + 420000, Date.parse(row.fetched_at ?? '') + 420000,
            ...(row.source_at ? [sourceExpiry(row.source_at)] : [])])].filter(Number.isFinite);
}
