import { fetchAuthAPI, postAuthAPI } from './api';
import type { AlphaLabCandidate, AlphaLabOpportunityCandidate, AlphaLabOpportunityPhase, AlphaLabProposal } from './alphaLabApi';
import type { ChartAnalogueCandidate } from './chartAnalogueApi';

export type AdminDiagnosticPhase = Omit<AlphaLabOpportunityPhase, 'win_rate' | 'mean_net_return' | 'stress_mean_net_return' | 'last_exit_session'> & {
    win_rate: number | null; mean_net_return: number | null; stress_mean_net_return: number | null; last_exit_session: string | null;
};
export interface AdminStockAnalysisResult {
    candidate: AlphaLabCandidate & { proposal: AlphaLabProposal; evidence?: AlphaLabOpportunityCandidate['evidence'] };
    latest_session: string;
    analyzed_at: string;
    input_fingerprint: string;
    source: { mode: 'saved_snapshot' | 'targeted_collection'; captured_at: string; price_basis: string;
        price_adjustment_verified: boolean; historical_vintage_verified: boolean; point_in_time_universe_verified: boolean };
    quality: { status: 'passed' | 'blocked' | 'unavailable'; reasons: string[] };
    stages: Array<{ id: string; label: string; state: 'complete' | 'held' }>;
    warnings: string[];
    diagnostics: Array<{ strategy_id: string; setup_active: boolean; reasons: string[];
        calibration: AdminDiagnosticPhase | null; confirmation: AdminDiagnosticPhase | null }>;
}
export interface AdminStockAnalysisStatus {
    schema_version: 1;
    policy_version: 'admin-symbol-alpha-v1';
    state: 'missing' | 'running' | 'ready' | 'held' | 'failed';
    target: { symbol: string; name: string; market: 'KR' };
    generated_at: string | null;
    error: string | null;
    result: AdminStockAnalysisResult | null;
}

const endpoint = '/api/admin/mirofish/stock-analysis';
const invalid = '종목 분석 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const positive = (v: unknown): v is number => finite(v) && v > 0;
const text = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0 && v.length <= 600 && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v);
const reasons = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 80 && v.every(text);
const nullableFinite = (v: unknown) => v === null || finite(v);
const fraction = (v: unknown) => finite(v) && v >= 0 && v <= 1;
const weight = (v: unknown) => finite(v) && v >= 0 && v <= .05 + 1e-10;
const near = (a: number, b: number) => Math.abs(a - b) <= Math.max(1e-6, Math.abs(b) * 1e-8);
const symbolCode = (v: unknown): v is string => typeof v === 'string' && /^\d{6}$/.test(v);
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
    && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const timestamp = (v: unknown): v is string => typeof v === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v)
    && Number.isFinite(Date.parse(v));
const notFuture = (v: unknown): v is string => timestamp(v) && Date.parse(v) <= Date.now() + 60000;

function phase(value: unknown): value is AlphaLabOpportunityPhase {
    if (!record(value) || !['samples', 'wins', 'losses', 'zeros'].every(key => Number.isInteger(value[key]) && (value[key] as number) >= 0)
        || !fraction(value.win_rate) || !['mean_net_return', 'stress_mean_net_return', 'compounded_trade_return', 'stress_compounded_trade_return'].every(key => finite(value[key]))
        || !nullableFinite(value.t_stat) || !date(value.start) || !date(value.end) || !date(value.last_exit_session)
        || value.start > value.end || value.last_exit_session < value.start || value.last_exit_session > value.end) return false;
    const samples = value.samples as number, wins = value.wins as number;
    return samples === wins + (value.losses as number) + (value.zeros as number)
        && near(value.win_rate as number, samples ? wins / samples : 0);
}
function diagnosticPhase(value: unknown): value is AdminDiagnosticPhase {
    if (record(value) && value.samples === 0) return value.wins === 0 && value.losses === 0 && value.zeros === 0
        && value.win_rate === null && value.mean_net_return === null && value.stress_mean_net_return === null
        && value.compounded_trade_return === 0 && value.stress_compounded_trade_return === 0
        && value.last_exit_session === null && value.t_stat === null && date(value.start) && date(value.end) && value.start <= value.end;
    return phase(value);
}
function validCandidate(value: unknown, result: Record<string, unknown>, target: Record<string, unknown>): boolean {
    if (!record(value) || value.symbol !== target.symbol || value.name !== target.name || !text(value.strategy_id) || !finite(value.score)
        || !(value.last_close === null || positive(value.last_close)) || !record(value.risk) || !reasons(value.reasons)
        || value.setup_active !== undefined && typeof value.setup_active !== 'boolean'
        || value.quote_session !== undefined && value.quote_session !== null && value.quote_session !== result.latest_session) return false;
    const risk = value.risk;
    if (risk.weight !== 0 || !text(risk.status) || !reasons(risk.reasons) || !(risk.p === null || fraction(risk.p))
        || !nullableFinite(risk.kelly_raw) || risk.research_weight !== undefined && !weight(risk.research_weight)
        || risk.quarter_kelly_fraction !== undefined && !(finite(risk.quarter_kelly_fraction) && risk.quarter_kelly_fraction >= 0)
        || risk.planned_account_risk !== undefined && !(finite(risk.planned_account_risk) && risk.planned_account_risk >= 0 && risk.planned_account_risk <= .01 + 1e-10)) return false;
    const p = value.proposal;
    if (!record(p) || !['buy', 'wait', 'avoid'].includes(String(p.action))
        || p.label !== ({ buy: '매수 제안', wait: '진입 대기', avoid: '매매 제외' } as Record<string, string>)[String(p.action)]
        || !text(p.reason) || !text(p.next_step) || !weight(p.proposed_weight)
        || !(p.input_session === null || p.input_session === result.latest_session) || !notFuture(p.derived_at)
        || !(p.valid_until === null || timestamp(p.valid_until))
        || p.plan_basis !== 'last_closed_price_next_open_reference' || p.order_allowed !== false
        || p.action !== 'buy' && p.proposed_weight !== 0
        || p.action === 'buy' && (!positive(p.proposed_weight) || p.input_session !== result.latest_session)) return false;
    const plan = value.plan;
    if (plan !== null) {
        if (!record(plan) || !positive(plan.entry_price) || !positive(plan.stop_price) || !positive(plan.target_price)
            || !positive(plan.atr) || !positive(plan.loss_fraction) || plan.entry_price !== value.last_close
            || plan.stop_price >= plan.entry_price || plan.target_price <= plan.entry_price || plan.loss_fraction > .08 + 1e-10) return false;
        const distance = Math.min(2 * plan.atr, plan.entry_price * .08);
        if (!near(plan.stop_price, plan.entry_price - distance) || !near(plan.target_price, plan.entry_price + 2 * distance)
            || !near(plan.loss_fraction, distance / plan.entry_price)
            || (p.proposed_weight as number) * plan.loss_fraction > .01 + 1e-10) return false;
        if (risk.planned_account_risk !== undefined && risk.research_weight !== undefined
            && !near(risk.planned_account_risk as number, (risk.research_weight as number) * plan.loss_fraction)) return false;
    } else if (p.action === 'buy') return false;
    if (p.action === 'buy' && (value.setup_active !== true || !positive(risk.research_weight)
        || (p.proposed_weight as number) > (risk.research_weight as number) + 1e-10)) return false;
    if (value.entry_guard !== undefined) {
        const g = value.entry_guard;
        if (!record(g) || g.policy_version !== 'reference-chase-cap-v1' || g.symbol !== target.symbol || g.as_of !== result.latest_session
            || g.input_fingerprint !== result.input_fingerprint || g.reference_price !== value.last_close
            || g.max_chase_fraction !== .02 || !positive(g.max_entry_price) || !positive(g.reference_price)
            || !near(g.max_entry_price, g.reference_price * 1.02)
            || g.applies_to !== 'manual_next_open_reference' || g.backtest_applied !== false) return false;
    }
    if (value.evidence !== undefined) {
        const e = value.evidence;
        if (!record(e) || e.selection_basis !== 'calibration_stress_mean_then_confirmation'
            || typeof e.stronger_evidence !== 'boolean' || e.retrospective !== true || e.independent_validation !== false
            || !phase(e.calibration) || !phase(e.confirmation) || e.calibration.end >= e.confirmation.start
            || e.confirmation.end !== result.latest_session) return false;
        if (p.action === 'buy') {
            if (e.calibration.samples < 30 || e.confirmation.samples < 10 || e.calibration.wins < 1 || e.calibration.losses < 1
                || e.confirmation.wins < 1 || e.confirmation.losses < 1 || !record(plan)
                || !positive(e.calibration.stress_mean_net_return) || !positive(e.confirmation.stress_mean_net_return)
                || !positive(e.calibration.mean_net_return) || !positive(e.confirmation.mean_net_return)
                || !positive(e.calibration.compounded_trade_return) || !positive(e.calibration.stress_compounded_trade_return)
                || !positive(e.confirmation.compounded_trade_return) || !positive(e.confirmation.stress_compounded_trade_return)
                || !positive(risk.kelly_raw) || !positive(risk.quarter_kelly_fraction) || !positive(plan.loss_fraction)
                || !near(risk.quarter_kelly_fraction, risk.kelly_raw * .25)
                || !near(risk.research_weight as number, Math.min(risk.quarter_kelly_fraction, .05, .01 / plan.loss_fraction))
                || !near(p.proposed_weight as number, risk.research_weight as number)
                || !near(risk.p as number, e.calibration.wins / (e.calibration.wins + e.calibration.losses))
                || !near(value.score as number, e.calibration.stress_mean_net_return)
                || e.stronger_evidence && (e.confirmation.samples < 30 || !finite(e.calibration.t_stat) || e.calibration.t_stat < 2
                    || !finite(e.confirmation.t_stat) || e.confirmation.t_stat < 2)) return false;
        }
    } else if (p.action === 'buy') return false;
    return true;
}

export function validateAdminStockAnalysis(value: unknown, requestedSymbol: string): AdminStockAnalysisStatus {
    if (!symbolCode(requestedSymbol) || !record(value) || value.schema_version !== 1 || value.policy_version !== 'admin-symbol-alpha-v1'
        || !['missing', 'running', 'ready', 'held', 'failed'].includes(String(value.state)) || !record(value.target)
        || value.target.symbol !== requestedSymbol || value.target.market !== 'KR' || !text(value.target.name)
        || !(value.generated_at === null || notFuture(value.generated_at)) || !(value.error === null || typeof value.error === 'string')) throw new Error(invalid);
    if (value.result === null) {
        if (['ready', 'held'].includes(String(value.state))) throw new Error(invalid);
        return value as unknown as AdminStockAnalysisStatus;
    }
    const r = value.result;
    if (!record(r) || !date(r.latest_session) || r.latest_session > new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10) || !notFuture(r.analyzed_at)
        || typeof r.input_fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(r.input_fingerprint)
        || !record(r.source) || !['saved_snapshot', 'targeted_collection'].includes(String(r.source.mode))
        || !notFuture(r.source.captured_at) || !text(r.source.price_basis)
        || !['price_adjustment_verified', 'historical_vintage_verified', 'point_in_time_universe_verified'].every(key => typeof (r.source as Record<string, unknown>)[key] === 'boolean')
        || Date.parse(r.source.captured_at as string) > Date.parse(r.analyzed_at as string) + 60000
        || !record(r.quality) || !['passed', 'blocked', 'unavailable'].includes(String(r.quality.status)) || !reasons(r.quality.reasons)
        || !Array.isArray(r.stages) || r.stages.length > 20 || !r.stages.every(s => record(s) && text(s.id) && text(s.label) && ['complete', 'held'].includes(String(s.state)))
        || !reasons(r.warnings) || !Array.isArray(r.diagnostics) || r.diagnostics.length > 12
        || !r.diagnostics.every(d => record(d) && text(d.strategy_id) && typeof d.setup_active === 'boolean' && reasons(d.reasons)
            && (d.calibration === null || diagnosticPhase(d.calibration)) && (d.confirmation === null || diagnosticPhase(d.confirmation)))
        || !validCandidate(r.candidate, r, value.target)) throw new Error(invalid);
    return value as unknown as AdminStockAnalysisStatus;
}

const sourceExpiry = (value: string) => (Math.floor((Date.parse(value) + 9 * 3600000) / 86400000) + 8) * 86400000 - 9 * 3600000;
/** This is display safety: no numeric plan, allocation or entry date is generated in the browser. */
export function effectiveAdminStockProposal(status: AdminStockAnalysisStatus, blocked = false, now = Date.now()): AlphaLabProposal | null {
    const result = status.result;
    if (!result) return null;
    const p = result.candidate.proposal;
    if (p.action !== 'buy') return p;
    const expired = !p.valid_until || now >= Date.parse(p.valid_until)
        || now >= sourceExpiry(result.source.captured_at) || now >= sourceExpiry(`${result.latest_session}T00:00:00+09:00`);
    if (!blocked && status.state === 'ready' && result.quality.status === 'passed' && result.source.price_basis !== 'unknown' && !expired) return p;
    return { ...p, action: 'wait', label: '진입 대기', proposed_weight: 0,
        reason: expired ? '제안 또는 입력 자료의 유효기간이 지나 진입을 기다립니다.'
            : result.quality.status !== 'passed' ? '재무 품질 조건을 확인하기 전에는 진입을 기다립니다.'
                : '최신 분석을 확인 중이거나 조회에 실패하여 이전 매수 제안을 보류합니다.',
        next_step: '저장 결과를 다시 조회하거나 분석을 재실행한 뒤 판단하세요.' };
}
function requireSymbol(symbol: string): void {
    if (!symbolCode(symbol)) throw new Error('국내 종목 코드 6자리를 입력해 주세요.');
}
export async function searchAdminStockCandidates(query: string, token?: string): Promise<ChartAnalogueCandidate[]> {
    const q = query.trim();
    if (!q) return [];
    if (q.length > 80) throw new Error('종목 검색어가 너무 깁니다.');
    try {
        const response = await fetchAuthAPI<unknown>(`${endpoint}/search?q=${encodeURIComponent(q)}&limit=8`, token, 8000);
        if (!record(response) || !Array.isArray(response.candidates)) throw new Error(invalid);
        const found: ChartAnalogueCandidate[] = [], seen = new Set<string>();
        for (const candidate of response.candidates) {
            if (!record(candidate) || !symbolCode(candidate.symbol) || candidate.market !== 'KR' || !text(candidate.name) || seen.has(candidate.symbol)) continue;
            found.push({ symbol: candidate.symbol, name: candidate.name }); seen.add(candidate.symbol);
            if (found.length === 8) break;
        }
        return found;
    } catch { throw new Error('종목 검색을 완료하지 못했습니다. 다시 시도해 주세요.'); }
}
export async function fetchAdminStockAnalysis(symbol: string, token?: string): Promise<AdminStockAnalysisStatus> {
    requireSymbol(symbol);
    try { return validateAdminStockAnalysis(await fetchAuthAPI<unknown>(`${endpoint}/${symbol}`, token, 15000), symbol); }
    catch { throw new Error('저장 분석 결과를 불러오지 못했습니다.'); }
}
export async function startAdminStockAnalysis(symbol: string, token?: string): Promise<AdminStockAnalysisStatus> {
    requireSymbol(symbol);
    try { return validateAdminStockAnalysis(await postAuthAPI<unknown>(endpoint, { symbol }, token, 30000), symbol); }
    catch { throw new Error('종목 분석을 시작하지 못했습니다. 저장 결과를 확인하거나 다시 실행해 주세요.'); }
}
