// 고정 가격 결정에 귀속된 선택적 뉴스 대조 자료만 화면으로 전달한다.
import type { OpportunityEngine, OpportunityIdentity } from './opportunityEngine';

export type CatalystTiming = 'captured_before_first' | 'published_before_captured_after' | 'reported_after_first';
export type CatalystStage = 'valuation_opinion' | 'site_inspection' | 'infrastructure' | 'investment' | 'contract' | 'earnings' | 'other';
export interface CatalystEvent {
    event_id: string; event_group: string; title: string; url: string; source: string; grade: 'B';
    published_at: string; collected_at: string; stage: CatalystStage;
    polarity: 'supportive' | 'adverse' | 'mixed' | 'unknown'; timing: CatalystTiming;
}
export interface CatalystRow {
    symbol: string; name: string; first_detected_at: string; first_decision_id: string; events: CatalystEvent[];
}
export interface CatalystContext extends OpportunityIdentity {
    schema_version: 1; policy_version: 'alpha-catalyst-context-v1'; decision_at: string; captured_at: string; snapshot_id: string;
    status: 'ready' | 'unavailable'; used_in_selection: false; association_status: 'unproven'; rows: CatalystRow[];
    validation: { status: 'collecting'; hypothesis: 'price_setup_leads_catalyst_72h_v1'; horizon_hours: 72;
        started_at: string; enrolled_decisions: number; matured_decisions: 0; coincidence_rejected: false };
}
const identityKeys = ['decision_id', 'input_fingerprint', 'source_audit_hash'] as const;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length
    && expected.every(key => Object.prototype.hasOwnProperty.call(v, key));
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && !!v.trim() && v.length <= max
    && !/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069<>\\]|(?:^|[\s"'/])[A-Za-z]:\/|\/(?:home|srv|tmp|users|private|etc|var|root)\b|\.env\b|(?:미래|예상|상승|하락)\s*(?:승률|확률)\s*[:=]?\s*\d|(?:수익|승률).*보장/i.test(v)
    && !/(?:^|[^a-z0-9])(?:api[_-]?key|access[_-]?token|secret|password|credentials?|authorization|bearer|traceback|token[_-]?cache)(?:$|[^a-z0-9])/i.test(v);
function timestamp(v: unknown): v is string {
    if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/.test(v)) return false;
    const day = `${v.slice(0, 10)}T00:00:00Z`;
    return Number.isFinite(Date.parse(v)) && Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === v.slice(0, 10)
        && !/[+-]14:(?!00)/.test(v);
}
// Issued journals preserve six fractional digits; Date.parse alone discards the last three.
interface Instant { seconds: number; microseconds: number }
const instant = (value: string): Instant => ({ seconds: Math.floor(Date.parse(value) / 1000),
    microseconds: Number((/\.(\d{1,6})(?:Z|[+-])/.exec(value)?.[1] ?? '').padEnd(6, '0')) });
const compareTime = (left: Instant, right: Instant) => left.seconds === right.seconds
    ? left.microseconds - right.microseconds : left.seconds - right.seconds;
function publicUrl(v: unknown): v is string {
    if (!text(v, 2000) || !/^https?:\/\//i.test(v) || /[\s\\]/.test(v)) return false;
    try {
        const url = new URL(v);
        const host = url.hostname.toLowerCase();
        const allowedHosts = ['yna.co.kr', 'yna.kr', 'hankyung.com', 'mk.co.kr', 'mt.co.kr', 'asiae.co.kr'];
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password
            || url.port && url.port !== (url.protocol === 'https:' ? '443' : '80')
            || !allowedHosts.some(allowed => host === allowed || host.endsWith(`.${allowed}`))) return false;
        let decoded = v;
        for (let i = 0; i < 3; i++) {
            const next = decodeURIComponent(decoded);
            if (!text(next, 2000) || /[\\]|(?:javascript|data|file):/i.test(next)) return false;
            if (decoded === next) break;
            decoded = next;
        }
        return true;
    } catch { return false; }
}
const count = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= 1_000_000;
function validEvent(v: unknown, first: Instant, captured: Instant): v is CatalystEvent {
    if (!record(v) || !keys(v, ['event_id', 'event_group', 'title', 'url', 'source', 'grade', 'published_at', 'collected_at', 'stage', 'polarity', 'timing'])
        || !hash(v.event_id) || !hash(v.event_group) || !text(v.title, 260) || !publicUrl(v.url) || !text(v.source, 64) || v.grade !== 'B'
        || !timestamp(v.published_at) || !timestamp(v.collected_at)
        || !['valuation_opinion', 'site_inspection', 'infrastructure', 'investment', 'contract', 'earnings', 'other'].includes(String(v.stage))
        || !['supportive', 'adverse', 'mixed', 'unknown'].includes(String(v.polarity))) return false;
    const published = instant(v.published_at), collected = instant(v.collected_at);
    if (compareTime(published, collected) > 0 || compareTime(collected, captured) > 0) return false;
    if (v.timing === 'captured_before_first') return compareTime(collected, first) <= 0;
    if (v.timing === 'published_before_captured_after') return compareTime(published, first) <= 0 && compareTime(collected, first) > 0;
    return v.timing === 'reported_after_first' && compareTime(published, first) > 0;
}
/** Invalid optional evidence disappears without changing the board, source payload, or original price decision. */
export function validateCatalystContext(value: unknown, board?: OpportunityEngine, now = Date.now()): CatalystContext | undefined {
    if (!board || !Number.isFinite(now) || !record(value)
        || !keys(value, ['schema_version', 'policy_version', ...identityKeys, 'decision_at', 'captured_at', 'snapshot_id', 'status', 'used_in_selection', 'association_status', 'rows', 'validation'])
        || value.schema_version !== 1 || value.policy_version !== 'alpha-catalyst-context-v1'
        || !identityKeys.every(key => hash(value[key]) && value[key] === board[key]) || !hash(value.snapshot_id)
        || !timestamp(value.decision_at) || !timestamp(value.captured_at) || !timestamp(board.generated_at)
        || compareTime(instant(value.decision_at), instant(board.generated_at)) !== 0
        || compareTime(instant(value.decision_at), instant(value.captured_at)) > 0
        || compareTime(instant(value.captured_at), { seconds: Math.floor(now / 1000), microseconds: Math.floor((now % 1000 + 1000) % 1000) * 1000 }) > 0
        || !['ready', 'unavailable'].includes(String(value.status)) || value.used_in_selection !== false || value.association_status !== 'unproven'
        || !Array.isArray(value.rows) || value.rows.length > 3 || value.rows.length !== board.candidates.length
        || !record(value.validation)) return undefined;
    const captured = instant(value.captured_at), decision = instant(value.decision_at);
    const validation = value.validation;
    if (!keys(validation, ['status', 'hypothesis', 'horizon_hours', 'started_at', 'enrolled_decisions', 'matured_decisions', 'coincidence_rejected'])
        || validation.status !== 'collecting' || validation.hypothesis !== 'price_setup_leads_catalyst_72h_v1' || validation.horizon_hours !== 72
        || !timestamp(validation.started_at) || compareTime(instant(validation.started_at), captured) > 0 || !count(validation.enrolled_decisions)
        || validation.matured_decisions !== 0 || validation.coincidence_rejected !== false) return undefined;
    for (const [index, row] of value.rows.entries()) {
        const selected = board.candidates[index];
        if (!record(row) || !keys(row, ['symbol', 'name', 'first_detected_at', 'first_decision_id', 'events'])
            || !/^\d{6}$/.test(String(row.symbol)) || row.symbol === '000000' || row.symbol !== selected.symbol
            || !text(row.name, 120) || row.name !== selected.name || !hash(row.first_decision_id) || !timestamp(row.first_detected_at)
            || compareTime(instant(row.first_detected_at), decision) > 0 || !Array.isArray(row.events) || row.events.length > 8) return undefined;
        const ids = new Set<string>(), urls = new Set<string>();
        for (const event of row.events) {
            if (!validEvent(event, instant(row.first_detected_at), captured) || ids.has(event.event_id) || urls.has(event.url)) return undefined;
            ids.add(event.event_id); urls.add(event.url);
        }
    }
    return value as unknown as CatalystContext;
}
