import { postAuthAPI } from './api';
import { effectiveOpportunityEngine, type OpportunityEngine } from './opportunityEngine';

export const agentRoleIds = ['regime', 'fx_liquidity', 'flow', 'disclosure', 'sector', 'event', 'micro', 'sentiment', 'auditor', 'leader', 'risk_guard', 'review'] as const;
export const agentRoleLabels: Record<string, string> = { regime: '시장 국면', fx_liquidity: '환율·유동성', flow: '외국인 수급', disclosure: '공시·재무', sector: '업종·테마', event: '일정·이벤트', micro: '시세·진입 조건', sentiment: '뉴스·심리', auditor: '출처 감사', leader: '판단 종합', risk_guard: '계좌 위험', review: '결과 검토' };
const reasonLabels: Record<string, string> = {
    direction_independent_sources_missing: '방향 판단의 독립 출처 두 계통 확인 필요', risk_independent_sources_missing: '위험 판단의 독립 출처 두 계통 확인 필요',
    direction_independent_sources: '방향 판단의 독립 출처', risk_independent_sources: '위험 판단의 독립 출처', independent_sources_insufficient: '독립 출처 두 계통 확인 필요',
    required_core_sources_missing: '핵심 판단의 독립 출처 확인 필요', certified_evidence_unavailable: '인증된 추가 출처 없음', source_audit_held: '독립 출처 감사 보류',
    social_only_core_claims: '뉴스·사회 관심만으로 방향을 판단할 수 없습니다.', calibrated_probability: '미래 확률 검증 자료',
    fx_and_flow_missing: '외국인 수급·환율 자료 확인 필요', missing_flow_and_fx: '외국인 수급·환율 자료 확인 필요', flow_and_fx_unavailable: '외국인 수급·환율 자료 확인 필요',
    foreign_flow: '외국인 수급', fx: '환율', entry_not_current: '현재 진입 조건 확인 필요', quote_unavailable: '현재 가격 확인 필요',
    quote_stale_or_future: '현재 가격의 관측 시각 확인 필요', quote_outside_entry: '진입 가격 범위 이탈', quote_stale: '현재 가격 갱신 필요',
    entry_window_expired: '신규 진입 유효기간 종료', entry_window_unavailable: '신규 진입 거래일 확인 필요', plan_unavailable: '참고 가격 계획 확인 필요',
    window_expired: '신규 진입 유효기간 종료', source_stale: '출처 자료 갱신 필요', theme_unavailable: '종목 테마 확인 필요',
    predeclared_oos_pending: '사전 선언한 별도 검증 구간의 성과 대기', calibration_pending: '미래 확률 검증 대기', manual_approval_required: 'CIO 수동 검토 필요',
    forward_validation_pending: '새 결정 이후 전향 검증 대기', research_reference_only: '연구 참고 한도 계산', strategy_promotion_held: '전향 검증·전략 승인 대기',
    forecast_unavailable: '미래 확률 검증 자료 없음', gap_losses_may_exceed_planned_loss: '갭 하락은 계획 손실을 초과할 수 있습니다.',
    daily_loss_limit: '오늘 손실 한도 1.5% 도달', weekly_loss_limit: '이번 주 손실 한도 4% 도달', daily_stop: '오늘 손실 한도 1.5% 도달', weekly_stop: '이번 주 손실 한도 4% 도달',
    position_limit_reached: '동시 보유 3종목 한도 도달', holding_theme_mismatch: '입력 보유 종목과 저장 테마 확인 필요', cash_floor: '현금 40% 유지 조건 확인 필요',
    cash_floor_reached: '현금 40% 유지 한도 도달', symbol_cap_reached: '종목별 참고 비중 한도 도달', theme_cap_reached: '동일 테마 30% 한도 도달',
    minimum_quantity_unavailable: '현재 한도로 1주를 계산할 수 없습니다.', quantity_not_representable: '수량 계산 범위 확인 필요',
    reference_plan_invalid: '참고 가격·Kelly 비중 확인 필요', opportunity_identity_mismatch: '연구 종목 식별자 확인 필요', agent_identity_mismatch: '출처 검사 종목 식별자 확인 필요',
    current_entry_unavailable: '현재 진입 조건 확인 필요', agent_entry_unavailable: '출처·진입 조건 재확인 필요', forecast_contract_invalid: '확률 자료 계약 확인 필요',
    plan_expired_or_unavailable: '계획 만료 또는 유효기간 확인 필요', current_quote_unavailable: '현재 가격 확인 필요', current_quote_stale_or_future: '현재 가격의 관측 시각 확인 필요',
    invalidation_identity_mismatch: '진입·손절 기준 일치 여부 확인 필요', source_contract_invalid: '출처 자료 계약 확인 필요', current_opportunities_unavailable: '현재 저장된 연구 후보 확인 필요',
    agent_desk_unavailable: '출처 검사 계약 확인 필요', agent_desk_stale_or_future: '출처 검사 갱신 시각 확인 필요', entry_session_mismatch: '공식 진입 거래일 확인 필요',
    account_required: '계좌 정보 입력 필요', account_unknown_fields: '계좌 입력 항목 확인 필요', account_exposure_inconsistent: '총자산·현금·보유 평가금액 일치 여부 확인 필요',
    account_positions_required: '현재 보유 목록 확인 필요', account_positions_invalid: '현재 보유 목록·테마·평가금액 확인 필요', account_positions_confirmed_required: '보유 목록 또는 무보유 확인 필요', account_positions_confirmed_invalid: '보유 목록 또는 무보유 확인 필요',
    evidence_record_invalid: '출처 자료 형식 확인 필요', evidence_records_invalid: '출처 자료 목록 확인 필요', evidence_records_limit: '출처 자료 목록 한도 확인 필요',
    evidence_identity_mismatch: '출처와 연구 종목 일치 여부 확인 필요', evidence_role_invalid: '출처 검사 역할 확인 필요', evidence_kind_invalid: '출처 유형 확인 필요',
    evidence_source_grade_invalid: '출처 신뢰 등급 확인 필요', evidence_claim_invalid: '출처가 뒷받침하는 판단 확인 필요', evidence_lineage_missing: '출처의 원본 계통 확인 필요', evidence_source_missing: '출처 원본 확인 필요',
    evidence_unavailable: '사용 가능한 출처 자료 없음', evidence_confidence_invalid: '출처 신뢰 기록 확인 필요', evidence_timestamp_invalid: '출처 자료 시각 확인 필요',
    evidence_cutoff_invalid: '연구 결정 기준 시각 확인 필요', evidence_after_decision: '연구 결정 이후 자료는 당시 판단에서 제외', evidence_time_order_invalid: '공개·확보 시각 순서 확인 필요',
    evidence_expired: '출처 자료 유효기간 종료', evidence_stale: '출처 자료 갱신 필요',
    evidence_semantics_missing: '근거의 방향·수치·단위 확인 필요', evidence_semantics_invalid: '근거의 방향·수치·단위가 올바르지 않습니다.',
    evidence_direction_conflict: '같은 판단 근거의 방향 충돌', evidence_id_conflict: '같은 근거 식별자의 내용 충돌', evidence_id_invalid: '근거 식별자 확인 필요',
    evidence_bundle_missing: '저장 근거 묶음 없음', evidence_bundle_invalid: '저장 근거 묶음 확인 필요', evidence_bundle_corrupt: '저장 근거 묶음 무결성 확인 필요',
    evidence_bundle_identity_mismatch: '근거 묶음과 현재 결정 일치 여부 확인 필요', evidence_decision_mismatch: '근거와 현재 결정 일치 여부 확인 필요',
    evidence_policy_hash_mismatch: '저장 근거의 정책 식별자 확인 필요', policy_hash_mismatch: '저장 정책 식별자 확인 필요',
    desk_evidence_missing: '저장 근거 묶음 없음', desk_evidence_integrity: '저장 근거 묶음 무결성 확인 필요', desk_policy_changed: '저장 정책 식별자 변경',
    directional_semantics_missing: '근거의 방향·수치·단위 확인 필요', directional_semantics: '근거의 방향·수치·단위',
    flow_required_for_plan: '외국인 수급 확인 후 계좌 계획 계산', disclosure_required_for_plan: '공시 자료 확인 후 계좌 계획 계산',
    desk_market_guard_invalid: '현재 시장 가드 형식 확인 필요', desk_market_guard_held: '현재 시장 가드 확인 보류',
    market_entry_window_unavailable: '신규 진입 거래일 확인 필요', market_entry_window_expired: '신규 진입 유효기간 종료',
    market_state_missing: '현재 시장 상태 자료 없음', market_state_invalid: '현재 시장 상태 형식 확인 필요', market_state_stale: '현재 시장 상태 갱신 필요',
    market_identity_mismatch: '현재 시장 상태와 종목·결정 일치 여부 확인 필요', market_source_missing: '현재 시장 상태의 출처 확인 필요', market_source_grade_invalid: '현재 시장 상태의 출처 등급 확인 필요',
    market_timestamp_invalid: '현재 시장 상태의 관측 시각 확인 필요', market_timestamp_future: '미래 시각의 시장 상태 제외', market_time_order_invalid: '시장 상태의 공개·확보 시각 순서 확인 필요',
    market_now_invalid: '시장 검사 기준 시각 확인 필요', market_policy_invalid: '시장 검사 정책 확인 필요', market_session_invalid: '현재 거래 세션 확인 필요',
    market_session_unavailable: '현재 거래 세션 확인 필요', market_session_not_continuous: '연속 거래 세션 확인 필요', market_session_closed: '신규 진입 가능한 거래 시간 확인 필요',
    market_outside_plan_session: '신규 진입 가능한 거래 시간 확인 필요', market_guard_expired: '현재 시장 가드 갱신 필요',
    market_weekend: '현재 거래일 확인 필요', market_expiration_invalid: '현재 시장 상태 유효기간 확인 필요', market_state_expired: '현재 시장 상태 유효기간 종료',
    market_vi_active: '변동성 완화장치 발동', market_vi_cooldown: '변동성 완화장치 해제 후 대기',
    market_sidecar_active: '사이드카 발동', market_sidecar_cooldown: '사이드카 해제 후 대기',
    market_circuit_active: '서킷브레이커 발동', market_circuit_cooldown: '서킷브레이커 해제 후 대기',
};
export function agentDeskReasonLabel(code: string): string {
    const field = /^account_(equity|available_cash|daily_pnl|weekly_pnl)_(required|invalid)$/.exec(code);
    if (field) return `${({ equity: '총자산', available_cash: '주문 가능 현금', daily_pnl: '오늘 손익', weekly_pnl: '이번 주 손익' } as Record<string, string>)[field[1]]} 확인 필요`;
    const marketEvent = /^market_(vi|sidecar|circuit)_(flag_invalid|release_missing|release_invalid|release_future|release_after_capture)$/.exec(code);
    if (marketEvent) return `${({ vi: '변동성 완화장치', sidecar: '사이드카', circuit: '서킷브레이커' } as Record<string, string>)[marketEvent[1]]} ${marketEvent[2] === 'flag_invalid' ? '발동 상태 확인 필요' : '해제 시각 확인 필요'}`;
    return reasonLabels[code] ?? agentRoleLabels[code] ?? '저장 근거 확인 필요';
}
export function agentDeskHoldMessage(codes: string[]): string {
    if (codes.some(code => ['fx_and_flow_missing', 'missing_flow_and_fx', 'flow_and_fx_unavailable'].includes(code))) return '외국인 수급·환율 자료 확인 전에는 계좌 수량을 제공하지 않습니다.';
    if (codes.some(code => ['daily_loss_limit', 'daily_stop'].includes(code))) return '오늘 손실 한도에 도달해 신규 진입을 중단합니다.';
    if (codes.some(code => ['weekly_loss_limit', 'weekly_stop'].includes(code))) return '이번 주 손실 한도에 도달해 신규 진입을 중단합니다.';
    if (codes.some(code => /source_audit_held|independent_sources_missing|social_only/.test(code))) return '방향·위험 판단의 독립 출처를 확인한 뒤 계좌 한도를 다시 계산하세요.';
    if (codes.some(code => /(?:quote|entry|plan|evidence).*(?:expired|stale|unavailable|not_current)/.test(code))) return '최신 가격·출처와 진입 유효기간을 확인한 뒤 다시 계산하세요.';
    return codes.length ? agentDeskReasonLabel(codes[0]) : '실제 계좌 입력과 현재 조건을 함께 확인하세요.';
}
export interface AgentDesk {
    schema_version: 1; policy_version: 'evidence-account-v1'; generated_at: string; order_allowed: false;
    roles: Array<{ id: string; title: string; status: 'passed' | 'held' | 'unavailable'; detail: string }>;
    candidates: Array<{ opportunity_id: string; symbol: string; name: string; state: 'No-trade' | 'Watch' | 'Conditional plan' | 'Exit review';
        audit: { status: 'passed' | 'held'; reasons: string[]; independent_sources: number };
        probability: { kind: 'unavailable'; bull: null; base: null; bear: null; reason: string };
        invalidation: { price_below: number | null; price_above: number | null; valid_until: string | null; detail: string }; missing: string[] }>;
    promotion: { stage: 'M0'; reasons: string[] };
    contract?: AgentDeskEvidenceContract;
}
export interface AgentDeskEvidenceContract {
    schema_version: 1; policy_version: 'desk-evidence-v2'; policy_hash: string; decision_id: string | null;
    evidence_snapshot_id: string | null; evidence_status: 'ready' | 'missing' | 'held';
    market_checks: Array<{ symbol: string; opportunity_id: string; status: 'passed' | 'held'; reasons: string[]; valid_until: string | null }>;
}
export interface AccountInput {
    equity: number; available_cash: number; daily_pnl: number; weekly_pnl: number; positions_confirmed: true;
    positions: Array<{ symbol: string; theme: string; market_value: number }>;
}
export interface AccountPlan {
    schema_version: 1; policy_version: 'evidence-account-v1'; status: 'ready' | 'held' | 'halt'; reasons: string[];
    generated_at: string; valid_until: string | null; order_allowed: false;
    limits: { trade_risk: number; daily_stop: number; weekly_stop: number; symbol_cap: number; theme_cap: number; cash_floor: number };
    plans: Array<{ opportunity_id: string; symbol: string; name: string; status: 'ready' | 'held' | 'halt'; reasons: string[];
        quantity: number | null; weight: number; budget: number; planned_loss: number;
        entry_price: number | null; stop_price: number | null; target_price: number | null }>;
}
const invalid = '계좌·근거 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown): v is number => finite(v) && Number.isSafeInteger(v) && v >= 0;
const positive = (v: unknown): v is number => finite(v) && v > 0;
const symbol = (v: unknown): v is string => typeof v === 'string' && /^\d{6}$/.test(v) && v !== '000000';
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length && expected.every(k => Object.prototype.hasOwnProperty.call(v, k));
const text = (v: unknown, max = 500): v is string => typeof v === 'string' && !!v.trim() && v.length <= max
    && !/[\u0000-\u001f\u007f]|[A-Za-z]:[\\/]|(?:^|\s)\/(?:home|srv|tmp|Users|private)\b|\.env\b|(?:api[_-]?key|access[_-]?token|secret)\s*[:=]|<[^>]*>|\bBearer\s|\bTraceback\b|(?:미래|예상|상승|하락|강세|약세)\s*(?:승률|확률)\s*[:=]?\s*\d|\b(?:bull|base|bear|forecast|predicted|calibrated)\s+(?:probability|win\s*rate)\s*[:=]?\s*\d|(?:수익|승률).*보장|100\s*%\s*보장/i.test(v);
const reasons = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 100 && v.every(item => text(item, 300));
const timestamp = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
    && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const nullableTime = (v: unknown) => v === null || timestamp(v);
const nullablePositive = (v: unknown) => v === null || positive(v);
const status = (v: unknown) => typeof v === 'string' && ['ready', 'held', 'halt'].includes(v);
const near = (a: number, b: number) => Math.abs(a - b) <= Math.max(1e-6, Math.abs(b) * 1e-8);
export function agentDeskInspectionFresh(desk: AgentDesk, now = Date.now()): boolean {
    const generated = Date.parse(desk.generated_at);
    return Number.isFinite(generated) && generated <= now + 60000 && now < generated + 420000;
}

/** Validate the server's receipt and binding; the client does not recompute its policy hash. */
function validateEvidenceContract(value: unknown, board?: OpportunityEngine): asserts value is AgentDeskEvidenceContract {
    if (!record(value) || !keys(value, ['schema_version', 'policy_version', 'policy_hash', 'decision_id', 'evidence_snapshot_id', 'evidence_status', 'market_checks'])
        || value.schema_version !== 1 || value.policy_version !== 'desk-evidence-v2' || !hash(value.policy_hash)
        || !(value.decision_id === null || hash(value.decision_id)) || !(value.evidence_snapshot_id === null || hash(value.evidence_snapshot_id))
        || !['ready', 'missing', 'held'].includes(String(value.evidence_status))
        || value.evidence_status === 'ready' && !hash(value.evidence_snapshot_id)
        || (board ? !hash(board.decision_id) || value.decision_id !== board.decision_id : value.decision_id !== null)
        || !Array.isArray(value.market_checks) || value.market_checks.length > 3 || value.market_checks.length !== (board?.candidates.length ?? 0)) throw new Error(invalid);
    for (const [index, check] of value.market_checks.entries()) {
        const bound = board?.candidates[index];
        if (!record(check) || !keys(check, ['symbol', 'opportunity_id', 'status', 'reasons', 'valid_until'])
            || !bound || !symbol(check.symbol) || check.symbol !== bound.symbol || !hash(check.opportunity_id) || check.opportunity_id !== bound.opportunity_id
            || !['passed', 'held'].includes(String(check.status)) || !reasons(check.reasons) || !nullableTime(check.valid_until)
            || check.status === 'passed' && (check.reasons.length !== 0 || !timestamp(check.valid_until) || !timestamp(bound.valid_until)
                || Date.parse(check.valid_until) > Date.parse(bound.valid_until))) throw new Error(invalid);
    }
}

/** Optional projection is bound to the same displayed opportunities; unsupported claims never render. */
export function validateAgentDesk(value: unknown, board?: OpportunityEngine, now = Date.now()): AgentDesk {
    const hasContract = record(value) && Object.prototype.hasOwnProperty.call(value, 'contract');
    if (!record(value) || !keys(value, ['schema_version', 'policy_version', 'generated_at', 'order_allowed', 'roles', 'candidates', 'promotion', ...(hasContract ? ['contract'] : [])])
        || value.schema_version !== 1 || value.policy_version !== 'evidence-account-v1' || value.order_allowed !== false
        || !timestamp(value.generated_at) || Date.parse(value.generated_at) > now + 60000
        || !Array.isArray(value.roles) || value.roles.length !== 12 || !Array.isArray(value.candidates) || value.candidates.length > 3
        || value.candidates.length !== (board?.candidates.length ?? 0) || !record(value.promotion)
        || !keys(value.promotion, ['stage', 'reasons']) || value.promotion.stage !== 'M0' || !reasons(value.promotion.reasons)) throw new Error(invalid);
    if (hasContract) validateEvidenceContract(value.contract, board);
    const roles = new Set<string>();
    for (const role of value.roles) {
        if (!record(role) || !keys(role, ['id', 'title', 'status', 'detail']) || typeof role.id !== 'string'
            || !agentRoleIds.some(id => id === role.id) || roles.has(role.id) || !text(role.title, 100) || !text(role.detail)
            || !['passed', 'held', 'unavailable'].includes(String(role.status))) throw new Error(invalid);
        roles.add(role.id);
    }
    for (const [index, row] of value.candidates.entries()) {
        const bound = board?.candidates[index];
        if (!record(row) || !keys(row, ['opportunity_id', 'symbol', 'name', 'state', 'audit', 'probability', 'invalidation', 'missing'])
            || !bound || !hash(row.opportunity_id) || row.opportunity_id !== bound.opportunity_id || row.symbol !== bound.symbol || row.name !== bound.name
            || !['No-trade', 'Watch', 'Conditional plan', 'Exit review'].includes(String(row.state)) || !reasons(row.missing)
            || !record(row.audit) || !keys(row.audit, ['status', 'reasons', 'independent_sources']) || !['passed', 'held'].includes(String(row.audit.status))
            || !reasons(row.audit.reasons) || !count(row.audit.independent_sources) || row.audit.independent_sources > 100
            || row.audit.status === 'passed' && (row.audit.independent_sources < 2 || row.audit.reasons.length !== 0)
            || !record(row.probability) || !keys(row.probability, ['kind', 'bull', 'base', 'bear', 'reason'])
            || row.probability.kind !== 'unavailable' || row.probability.bull !== null || row.probability.base !== null || row.probability.bear !== null
            || !text(row.probability.reason) || !record(row.invalidation) || !keys(row.invalidation, ['price_below', 'price_above', 'valid_until', 'detail'])
            || !nullablePositive(row.invalidation.price_below) || !nullablePositive(row.invalidation.price_above) || !nullableTime(row.invalidation.valid_until)
            || row.invalidation.price_below !== bound.plan.stop_price || row.invalidation.price_above !== bound.plan.entry_high
            || (bound.valid_until === null ? row.invalidation.valid_until !== null
                : !timestamp(row.invalidation.valid_until) || Date.parse(row.invalidation.valid_until) > Date.parse(bound.valid_until))
            || !text(row.invalidation.detail)) throw new Error(invalid);
    }
    return value as unknown as AgentDesk;
}

/** Blank, boolean or nonfinite values are never account facts. */
export function validAccountInput(value: unknown): value is AccountInput {
    if (!record(value) || !keys(value, ['equity', 'available_cash', 'daily_pnl', 'weekly_pnl', 'positions_confirmed', 'positions'])
        || !positive(value.equity) || value.equity > 1e15 || !finite(value.available_cash) || value.available_cash < 0 || value.available_cash > value.equity
        || !finite(value.daily_pnl) || !finite(value.weekly_pnl) || Math.abs(value.daily_pnl) > 1e15 || Math.abs(value.weekly_pnl) > 1e15
        || value.positions_confirmed !== true || !Array.isArray(value.positions) || value.positions.length > 100) return false;
    const symbols = new Set<string>(); let exposure = 0;
    for (const row of value.positions) {
        if (!record(row) || !keys(row, ['symbol', 'theme', 'market_value']) || !symbol(row.symbol) || symbols.has(row.symbol)
            || !text(row.theme, 80) || !positive(row.market_value) || row.market_value > value.equity) return false;
        symbols.add(row.symbol); exposure += row.market_value;
    }
    return exposure + value.available_cash <= value.equity + 1e-6;
}
export function validateAccountPlan(value: unknown, board: OpportunityEngine, desk: AgentDesk, account: AccountInput, now = Date.now()): AccountPlan {
    if (Object.prototype.hasOwnProperty.call(desk, 'contract')) validateEvidenceContract(desk.contract, board);
    if (!validAccountInput(account) || !record(value) || !keys(value, ['schema_version', 'policy_version', 'status', 'reasons', 'generated_at', 'valid_until', 'order_allowed', 'limits', 'plans'])
        || value.schema_version !== 1 || value.policy_version !== 'evidence-account-v1' || value.order_allowed !== false || !status(value.status) || !reasons(value.reasons)
        || !timestamp(value.generated_at) || Date.parse(value.generated_at) > now + 60000 || !nullableTime(value.valid_until)
        || !record(value.limits) || !keys(value.limits, ['trade_risk', 'daily_stop', 'weekly_stop', 'symbol_cap', 'theme_cap', 'cash_floor'])
        || value.limits.trade_risk !== .005 || value.limits.daily_stop !== -.015 || value.limits.weekly_stop !== -.04
        || value.limits.symbol_cap !== .05 || value.limits.theme_cap !== .3 || value.limits.cash_floor !== .4
        || !Array.isArray(value.plans) || value.plans.length > 3) throw new Error(invalid);
    const plan = value as unknown as AccountPlan;
    const effective = effectiveOpportunityEngine(board, now);
    const ids = new Set<string>(); let budget = 0; let ready = 0;
    for (const p of plan.plans) {
        const row = board.candidates.find(r => r.opportunity_id === p.opportunity_id);
        const audit = desk.candidates.find(r => r.opportunity_id === p.opportunity_id);
        if (!record(p) || !keys(p, ['opportunity_id', 'symbol', 'name', 'status', 'reasons', 'quantity', 'weight', 'budget', 'planned_loss', 'entry_price', 'stop_price', 'target_price'])
            || !row || !audit || ids.has(p.opportunity_id) || p.symbol !== row.symbol || p.name !== row.name || !status(p.status) || !reasons(p.reasons)
            || !finite(p.weight) || p.weight < 0 || p.weight > Math.min(.05, row.reference_weight) + 1e-8
            || !finite(p.budget) || p.budget < 0 || !finite(p.planned_loss) || p.planned_loss < 0
            || !nullablePositive(p.entry_price) || !nullablePositive(p.stop_price) || !nullablePositive(p.target_price)) throw new Error(invalid);
        ids.add(p.opportunity_id);
        if (p.status !== 'ready') {
            if (p.quantity !== null || p.weight !== 0 || p.budget !== 0 || p.planned_loss !== 0) throw new Error(invalid);
            continue;
        }
        const flowAndFxMissing = audit.missing.includes('flow') && audit.missing.includes('fx_liquidity')
            || audit.missing.includes('foreign_flow') && audit.missing.includes('fx');
        const market = desk.contract?.market_checks.find(check => check.opportunity_id === p.opportunity_id);
        if (!desk.contract || desk.contract.evidence_status !== 'ready' || market?.status !== 'passed' || market.reasons.length !== 0
            || !market.valid_until || now >= Date.parse(market.valid_until) || !plan.valid_until
            || Date.parse(plan.valid_until) > Date.parse(market.valid_until)) throw new Error(invalid);
        if (plan.status !== 'ready' || !count(p.quantity) || p.quantity < 1 || audit.audit.status !== 'passed' || audit.audit.independent_sources < 2
            || audit.audit.reasons.length !== 0 || flowAndFxMissing || !['Watch', 'Conditional plan'].includes(audit.state)
            || effective.candidates.find(r => r.opportunity_id === p.opportunity_id)?.action !== 'entry_candidate'
            || p.entry_price !== row.plan.entry_high || p.stop_price !== row.plan.stop_price || p.target_price !== row.plan.target_price
            || !near(p.budget, p.quantity * p.entry_price) || !near(p.weight, p.budget / account.equity)
            || !near(p.planned_loss, p.quantity * (p.entry_price - p.stop_price)) || p.planned_loss > account.equity * .005 + 1e-6
            || p.budget + (account.positions.find(r => r.symbol === p.symbol)?.market_value ?? 0) > account.equity * Math.min(.05, row.reference_weight) + 1e-6) throw new Error(invalid);
        const deadline = Math.min(Date.parse(row.valid_until ?? ''), Date.parse(audit.invalidation.valid_until ?? ''),
            Date.parse(row.quote_at ?? '') + 420000, Date.parse(row.fetched_at ?? '') + 420000);
        if (!plan.valid_until || !Number.isFinite(deadline) || Date.parse(plan.valid_until) > deadline) throw new Error(invalid);
        budget += p.budget; ready++;
    }
    if (plan.status === 'ready' && (!ready || !plan.valid_until || now >= Date.parse(plan.valid_until) || Date.parse(plan.valid_until) <= Date.parse(plan.generated_at)
        || !agentDeskInspectionFresh(desk, now) || Date.parse(plan.valid_until) > Date.parse(desk.generated_at) + 420000
        || !board.valid_until || Date.parse(plan.valid_until) > Date.parse(board.valid_until) || account.daily_pnl <= -.015 * account.equity || account.weekly_pnl <= -.04 * account.equity
        || budget > account.available_cash - .4 * account.equity + 1e-6 || new Set([...account.positions.map(p => p.symbol), ...plan.plans.filter(p => p.status === 'ready').map(p => p.symbol)]).size > 3)) throw new Error(invalid);
    return plan;
}
/** No account information is stored; the existing protected transport receives only this request. */
export async function requestAccountPlan(account: AccountInput, board: OpportunityEngine, desk: AgentDesk, token?: string): Promise<AccountPlan> {
    if (!validAccountInput(account)) throw new Error(invalid);
    const response = await postAuthAPI<unknown>('/api/admin/mirofish/alpha-lab/account-plan', {
        account, opportunity_ids: board.candidates.map(row => row.opportunity_id),
    }, token);
    return validateAccountPlan(response, board, desk, account);
}
