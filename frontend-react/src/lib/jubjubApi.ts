/**
 * 🪣 Jubjub API client — W 패턴 + 저점 매수 시그널.
 *
 * Endpoint: GET /api/wave/jubjub?min_score=60&limit=50
 */
import { fetchAPI } from './api';

export type JubjubBadge = 'imminent' | 'buy_now' | 'breakout' | 'late' | 'watching';
export type JubjubBadgeTone = 'amber' | 'emerald' | 'rose' | 'slate';

export interface JubjubTradePlan {
    entry_price: number;
    target_1: number;
    target_2: number;
    stop_price: number;
    entry_pct: number | null;
    target_1_pct: number | null;
    target_2_pct: number | null;
    stop_pct: number | null;
    rr_1: number | null;
    rr_2: number | null;
    pattern_depth: number;
    second_trough: number;
}

export interface JubjubScoreBreakdown {
    confidence: number;
    completion: number;
    proximity: number;
    volume: number;
    bias: number;
}

export interface JubjubCandidate {
    ticker: string;
    name: string;
    market: string;
    current_price: number;
    pattern_class: 'W';
    wave_type?: string;
    wave_label?: string;
    confidence: number;
    completion_pct: number;
    neckline_price: number;
    neckline_distance_pct: number;
    volume_confirmed: boolean;
    jubjub_score: number;
    jubjub_stars: number;
    jubjub_badge: JubjubBadge;
    jubjub_badge_label_ko: string;
    jubjub_badge_tone: JubjubBadgeTone;
    trade_plan: JubjubTradePlan;
    score_breakdown: JubjubScoreBreakdown;
}

export interface JubjubStats {
    imminent: number;
    buy_now: number;
    breakout: number;
    top_score: number | null;
    top_name: string | null;
}

export interface JubjubResponse {
    date?: string | null;
    updated_at?: string | null;
    market?: string;
    scan_count: number;
    jubjub_count: number;
    min_score: number;
    stats: JubjubStats;
    candidates: JubjubCandidate[];
    message?: string;
}

export async function getJubjubCandidates(
    params: { min_score?: number; limit?: number } = {},
): Promise<JubjubResponse> {
    const search = new URLSearchParams();
    if (params.min_score !== undefined) search.set('min_score', String(params.min_score));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    const qs = search.toString();
    return fetchAPI<JubjubResponse>(`/api/wave/jubjub${qs ? `?${qs}` : ''}`);
}
