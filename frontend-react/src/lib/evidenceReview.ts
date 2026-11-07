import { API_BASE, ApiError, authHeaders, fetchWithTimeout } from './api';

export type ReviewKind = 'article' | 'candidate';
export interface EvidenceFinding { text: string; claim_status: 'reported' | 'inference' | 'verified' | 'missing'; evidence_ids: string[]; quotes: Array<{ evidence_id: string; quote: string }> }
export interface EvidenceReview {
    id: string; input_fingerprint: string; source_input_fingerprint: string | null;
    decision_id: string | null; article_id: string | null; generated_at: string; source_cutoff_at: string; source_origin_at?: string;
    status: 'SUCCESS_PRIMARY' | 'SUCCESS_FALLBACK' | 'UNVERIFIED' | 'IN_PROGRESS';
    provider: string | null; model: string | null; fallback_reason: string | null; freshness: 'current' | 'stale';
    review_scope: 'current_evidence_not_original_decision';
    candidate_basis?: 'research_watchlist' | 'issued_opportunities' | null; original_status?: string | null;
    omitted_findings?: number;
    rows: Array<{ symbol: string; name: string; market: 'KR'; strengths: EvidenceFinding[]; risks: EvidenceFinding[]; what_to_watch: EvidenceFinding[] }>;
    sources: Array<{ evidence_id: string; title: string; url: string | null; published_at: string | null;
        fetched_at: string | null; source: string; verification_status: string; available_at_original_decision?: boolean }>;
}
export interface EvidenceReviewSnapshot {
    schema_version: 1; kind: ReviewKind; status: 'ready' | 'degraded' | 'waiting' | 'stale' | 'unavailable';
    last_run_at: string | null; empty_reason?: string | null; items: EvidenceReview[];
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown, max = 2000): value is string => typeof value === 'string' && !!value.trim() && value.length <= max
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(value);
const nullableText = (value: unknown) => value === null || text(value);
const timestamp = (value: unknown): value is string => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const nullableTime = (value: unknown) => value === null || timestamp(value);
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

/** Source links are limited to the two publishers in this evidence pipeline. */
export function evidenceSourceUrl(value: string | null): string | null {
    if (!value) return null;
    if (/^https:\/\/www\.businesspost\.co\.kr\/BP\?command=article_view&num=[1-9]\d{0,9}$/.test(value)
        || /^https:\/\/dart\.fss\.or\.kr\/dsaf001\/main\.do\?rcpNo=\d{14}$/.test(value)) return value;
    return null;
}

function validReview(value: unknown, kind: ReviewKind): value is EvidenceReview {
    if (!object(value) || !text(value.id, 160) || !hash(value.input_fingerprint)
        || !(value.source_input_fingerprint === null || hash(value.source_input_fingerprint))
        || !timestamp(value.generated_at) || !timestamp(value.source_cutoff_at)
        || Date.parse(value.source_cutoff_at) > Date.parse(value.generated_at)
        || value.source_origin_at !== undefined && (!timestamp(value.source_origin_at) || Date.parse(value.source_origin_at) > Date.parse(value.source_cutoff_at))
        || !['SUCCESS_PRIMARY', 'SUCCESS_FALLBACK', 'UNVERIFIED', 'IN_PROGRESS'].includes(String(value.status))
        || !['current', 'stale'].includes(String(value.freshness)) || value.review_scope !== 'current_evidence_not_original_decision'
        || !nullableText(value.provider) || !nullableText(value.model) || !nullableText(value.fallback_reason)
        || value.omitted_findings !== undefined && (typeof value.omitted_findings !== 'number'
            || !Number.isInteger(value.omitted_findings) || value.omitted_findings < 0 || value.omitted_findings > 24)
        || !Array.isArray(value.rows) || value.rows.length > 8 || !Array.isArray(value.sources) || value.sources.length > 80) return false;
    if (kind === 'candidate' && (!hash(value.decision_id) || !hash(value.source_input_fingerprint)
        || !['research_watchlist', 'issued_opportunities'].includes(String(value.candidate_basis)) || value.rows.length > 3)
        || kind === 'article' && !text(value.article_id, 160)) return false;
    if (['SUCCESS_PRIMARY', 'SUCCESS_FALLBACK'].includes(String(value.status)) && (!text(value.provider) || !text(value.model))) return false;
    if (!value.sources.every(source => object(source) && text(source.evidence_id, 200) && text(source.title)
        && nullableText(source.url) && nullableTime(source.published_at) && nullableTime(source.fetched_at)
        && (source.available_at_original_decision === undefined || typeof source.available_at_original_decision === 'boolean')
        && text(source.source) && text(source.verification_status))) return false;
    const ids = new Set(value.sources.map(source => source.evidence_id));
    if (ids.size !== value.sources.length) return false;
    const findings = (rows: unknown) => Array.isArray(rows) && rows.length <= 8 && rows.every(finding => object(finding)
        && text(finding.text) && ['reported', 'inference', 'verified', 'missing'].includes(String(finding.claim_status))
        && Array.isArray(finding.evidence_ids) && finding.evidence_ids.length > 0
        && finding.evidence_ids.every(id => typeof id === 'string' && ids.has(id)) && Array.isArray(finding.quotes)
        && finding.quotes.length <= 8 && finding.quotes.every(quote => object(quote) && text(quote.quote)
            && typeof quote.evidence_id === 'string' && (finding.evidence_ids as string[]).includes(quote.evidence_id)));
    const symbolPattern = kind === 'article' ? /^[0-9A-Z]{6}$/ : /^\d{6}$/;
    return value.rows.every(row => object(row) && typeof row.symbol === 'string' && symbolPattern.test(row.symbol)
        && text(row.name, 100) && row.market === 'KR' && findings(row.strengths) && findings(row.risks) && findings(row.what_to_watch))
        && new Set(value.rows.map(row => row.symbol)).size === value.rows.length;
}

export function validateEvidenceReviews(value: unknown, kind: ReviewKind): EvidenceReviewSnapshot {
    if (!object(value) || value.schema_version !== 1 || value.kind !== kind
        || !['ready', 'degraded', 'waiting', 'stale', 'unavailable'].includes(String(value.status))
        || !nullableTime(value.last_run_at) || !Array.isArray(value.items) || value.items.length > (kind === 'article' ? 100 : 1)
        || !value.items.every(review => validReview(review, kind))) throw new Error('저장된 AI 분석을 확인하지 못했습니다.');
    return value as unknown as EvidenceReviewSnapshot;
}

/** A saved-artifact GET. No generation endpoint or error body is exposed here. */
export async function fetchEvidenceReviews(kind: ReviewKind, token?: string, signal?: AbortSignal): Promise<EvidenceReviewSnapshot> {
    const path = kind === 'article' ? 'kongming/article-evidence-reviews' : 'alpha-lab/candidate-review';
    const response = await fetchWithTimeout(`${API_BASE}/api/admin/mirofish/${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : authHeaders(), signal,
    }, 8000);
    if (!response.ok) throw new ApiError('저장된 AI 분석 조회 실패', response.status);
    return validateEvidenceReviews(await response.json(), kind);
}
