import { API_BASE, ApiError, authHeaders, fetchWithTimeout } from './api';
import type { EvidenceFinding } from './evidenceReview';

export interface AdvisorRow {
    symbol: string; name: string; market: 'KR';
    strengths: EvidenceFinding[]; risks: EvidenceFinding[]; what_to_watch: EvidenceFinding[];
}
export interface AdvisorPick extends AdvisorRow {
    rank: number; baseline_rank: number; score: number; basis: string; entry_status: string;
    source_at: string | null; reference_price: number | null; hold_reasons: string[]; evidence_ids: string[];
    score_components: { news_count?: number; official_evidence_available?: boolean; price_evidence_available?: boolean };
    plan: Partial<Record<'entry_price' | 'entry_low' | 'entry_high' | 'stop_price' | 'target_price' | 'loss_fraction' | 'horizon_sessions', number | null>> | null;
}
export interface AdvisorSource {
    evidence_id: string; title: string; source: string; url: string | null; verification_status: string;
    published_at: string | null; fetched_at: string | null; target_symbols: string[]; available_at_original_decision?: boolean;
}
export interface Top3Advisor {
    schema_version: 1; status: 'ready' | 'degraded' | 'stale' | 'missing' | 'unavailable';
    generated_at: string | null; source_origin_at: string | null; source_cutoff_at: string | null;
    decision_id: string | null; input_fingerprint: string | null; empty_reason: string | null; live_orders: false;
    coverage: Partial<Record<'inspected' | 'pool' | 'shortlisted' | 'with_recent_news' | 'with_verified_filings' | 'with_verified_prices' | 'source_count', number>>;
    warnings: string[]; top3: AdvisorPick[]; sources: AdvisorSource[];
    debate: { debate_complete: boolean; ranking_basis: string; stages: Array<{
        role: 'analyst' | 'critic' | 'chair'; status: string; generated_at?: string | null;
        provider?: string | null; model?: string | null; fallback_reason?: string | null; rows: AdvisorRow[];
    }> };
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 4000;
const time = (v: unknown) => v === null || typeof v === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const list = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 80 && v.every(text);
const completed = new Set(['SUCCESS_PRIMARY', 'SUCCESS_FALLBACK', 'RECOVERED_RESPONSE']);

/** Reject malformed ranks, unsafe prices and unbound findings before rendering. */
export function validateTop3Advisor(value: unknown): Top3Advisor {
    const invalid = () => { throw new Error('저장된 TOP3 응답을 확인하지 못했습니다.'); };
    if (!object(value) || value.schema_version !== 1 || value.live_orders !== false
        || !['ready', 'degraded', 'stale', 'missing', 'unavailable'].includes(String(value.status))
        || !time(value.generated_at) || !time(value.source_origin_at) || !time(value.source_cutoff_at)
        || !object(value.coverage) || !Object.values(value.coverage).every(v => number(v) && Number.isInteger(v) && v >= 0)
        || !list(value.warnings) || !Array.isArray(value.top3) || value.top3.length > 3
        || !Array.isArray(value.sources) || value.sources.length > 80 || !object(value.debate)) return invalid();
    if (!value.sources.every(s => object(s) && text(s.evidence_id) && text(s.title) && text(s.source)
        && text(s.verification_status) && (s.url === null || text(s.url)) && time(s.published_at) && time(s.fetched_at)
        && list(s.target_symbols))) return invalid();
    const sources = new Map(value.sources.map(s => [s.evidence_id, s]));
    if (sources.size !== value.sources.length) return invalid();
    const findings = (v: unknown, symbol: string) => Array.isArray(v) && v.length <= 8 && v.every(f => object(f) && text(f.text)
        && ['reported', 'inference', 'verified', 'missing'].includes(String(f.claim_status)) && list(f.evidence_ids) && f.evidence_ids.length > 0
        && f.evidence_ids.every(id => sources.get(id)?.target_symbols.includes(symbol))
        && Array.isArray(f.quotes) && f.quotes.length <= 8 && f.quotes.every(q => object(q) && text(q.quote) && (f.evidence_ids as string[]).includes(String(q.evidence_id))));
    const row = (r: unknown) => object(r) && typeof r.symbol === 'string' && /^\d{6}$/.test(r.symbol) && text(r.name) && r.market === 'KR'
        && findings(r.strengths, r.symbol) && findings(r.risks, r.symbol) && findings(r.what_to_watch, r.symbol);
    if (!value.top3.every((r, i) => row(r) && r.rank === i + 1 && number(r.baseline_rank) && Number.isInteger(r.baseline_rank) && r.baseline_rank > 0
        && number(r.score) && text(r.basis) && text(r.entry_status) && time(r.source_at)
        && (r.reference_price === null || number(r.reference_price) && r.reference_price > 0)
        && list(r.hold_reasons) && list(r.evidence_ids) && r.evidence_ids.every((id: string) => sources.has(id)) && object(r.score_components)
        && (r.plan === null || object(r.plan) && Object.values(r.plan).every(v => v === null || number(v) && v >= 0)))) return invalid();
    if (new Set(value.top3.map(r => r.symbol)).size !== value.top3.length
        || !['ready', 'degraded'].includes(String(value.status)) && value.top3.length > 0) return invalid();
    const debate = value.debate;
    if (typeof debate.debate_complete !== 'boolean' || !['grounded_debate', 'deterministic_research'].includes(String(debate.ranking_basis))
        || !Array.isArray(debate.stages) || debate.stages.length > 3
        || !debate.stages.every(s => object(s) && ['analyst', 'critic', 'chair'].includes(String(s.role)) && text(s.status)
            && (s.generated_at === undefined || time(s.generated_at)) && Array.isArray(s.rows) && s.rows.length <= 6 && s.rows.every(row))) return invalid();
    if (new Set(debate.stages.map(s => s.role)).size !== debate.stages.length
        || debate.debate_complete && (debate.stages.length !== 3 || !debate.stages.every(s => completed.has(s.status)) || debate.ranking_basis !== 'grounded_debate')
        || value.status === 'ready' && !debate.debate_complete) return invalid();
    return value as unknown as Top3Advisor;
}

/** Saved GET only. Viewing or refreshing never starts paid inference. */
export async function fetchTop3Advisor(token?: string, signal?: AbortSignal): Promise<Top3Advisor> {
    const response = await fetchWithTimeout(`${API_BASE}/api/admin/mirofish/alpha-lab/top3-advisor`, {
        headers: token ? { Authorization: `Bearer ${token}` } : authHeaders(), signal,
    }, 8000);
    if (!response.ok) throw new ApiError('저장된 TOP3 조회 실패', response.status);
    return validateTop3Advisor(await response.json());
}
