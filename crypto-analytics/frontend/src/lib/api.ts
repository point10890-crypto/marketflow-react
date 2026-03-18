// API utility functions

const API_BASE = '';  // Empty = use Next.js proxy

export async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }
    return response.json();
}

// ═══════════════════════════════════════
// Crypto Market API Types & Functions
// ═══════════════════════════════════════

export interface CryptoSignal {
    symbol: string;
    exchange: string;
    signal_type: string;
    score: number;
    timeframe: string;
    pivot_high: number;
    vol_ratio: number;
    ml_win_prob?: number | null;
    created_at: string;
}

export interface CryptoMarketGate {
    status: string;
    gate: string;
    score: number;
    price?: number;
    ma200?: number;
    reasons?: string[];
    metrics?: Record<string, any>;
    generated_at?: string;
}

export interface CryptoBriefingData {
    timestamp: string;
    market_summary: {
        total_market_cap: number;
        total_market_cap_change_24h: number;
        btc_dominance: number;
        btc_dominance_change_24h: number;
        total_volume_24h: number;
        active_cryptocurrencies: number;
    };
    major_coins: Record<string, {
        price: number;
        change_24h: number;
        change_7d: number;
        volume_24h: number;
        market_cap: number;
    }>;
    top_movers: {
        gainers: Array<{ symbol: string; name: string; change_24h: number; price: number }>;
        losers: Array<{ symbol: string; name: string; change_24h: number; price: number }>;
    };
    fear_greed: { score: number; level: string; previous: number; change: number };
    funding_rates: Record<string, { rate: number; rate_pct: number; annualized_pct: number; sentiment: string }>;
    macro_correlations: { btc_pairs: Record<string, number> };
    market_gate: { gate: string; score: number; reasons: string[] } | null;
    sentiment_summary: { overall: string; factors: string[] };
    btc_price_history?: Array<{ date: string; price: number }>;
}

export interface CryptoPredictionData {
    timestamp: string;
    predictions: Record<string, {
        current_price: number;
        bullish_probability: number;
        bearish_probability: number;
        confidence_level: string;
        key_drivers: Array<{ feature: string; impact: number; value: number; direction: string }>;
    }>;
    model_info: {
        algorithm: string;
        training_accuracy: number;
        training_samples: number;
        last_trained: string;
        ensemble_models?: Array<{ name: string; accuracy: number; bullish: number }>;
    };
}

export interface CryptoRiskData {
    timestamp: string;
    portfolio_summary: {
        total_coins: number;
        portfolio_var_95_1d: number;
        portfolio_cvar_95_1d: number;
        risk_level: string;
    };
    correlation_matrix: { coins: string[]; values: number[][] };
    individual_risk: Record<string, { var_95_1d: number; max_dd_30d: number; volatility_30d: number }>;
    concentration: { btc_weight_pct: number; top3_weight_pct: number; warnings: string[] };
    alerts: Array<{ severity: string; message: string; coin: string }>;
}

// Lead-Lag Analysis Types
export interface LeadLagPair {
    var1: string;
    var2: string;
    optimal_lag: number;
    optimal_correlation: number;
    interpretation: string;
    p_value: number;
}

export interface GrangerResult {
    cause: string;
    effect: string;
    best_lag: number;
    best_p_value: number;
    is_significant: boolean;
    interpretation: string;
}

export interface LeadLagData {
    metadata: { target: string; period: string; max_lag: number; generated_at: string };
    lead_lag: LeadLagPair[];
    granger: GrangerResult[];
    data_summary?: { date_range: { start: string; end: string; periods: number } };
}

// Crypto Market API Client
export const cryptoAPI = {
    getVCPSignals: (limit = 50) =>
        fetchAPI<{ signals: CryptoSignal[]; count: number }>(`/api/crypto/vcp-signals?limit=${limit}`),
    getMarketGate: () => fetchAPI<CryptoMarketGate>('/api/crypto/market-gate'),
    getTimeline: () => fetchAPI<{ events: unknown[] }>('/api/crypto/timeline'),
    getMonthlyReport: () => fetchAPI<{ report: unknown }>('/api/crypto/monthly-report'),
    getLeadLag: () => fetchAPI<LeadLagData>('/api/crypto/lead-lag'),
    getBriefing: () => fetchAPI<CryptoBriefingData>('/api/crypto/briefing'),
    getPrediction: () => fetchAPI<CryptoPredictionData>('/api/crypto/prediction'),
    getRisk: () => fetchAPI<CryptoRiskData>('/api/crypto/risk'),
    getGateHistory: () => fetchAPI<{history: Array<{date: string; gate: string; score: number}>}>('/api/crypto/gate-history'),
    getPredictionHistory: () => fetchAPI<{history: Array<{date: string; bullish_probability: number; btc_price: number}>}>('/api/crypto/prediction-history'),
};
