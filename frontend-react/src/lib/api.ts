// API utility functions
//
// Architecture:
//   Dev:  Vite proxy /api/* → Flask 5001 (vite.config.ts)
//   Prod: VITE_API_BASE_URL → Cloudflare Tunnel → Flask 5001

export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
export const API_HEADERS: Record<string, string> = {};

export async function fetchAPI<T>(endpoint: string): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    try {
        const response = await fetch(url, {
            signal: controller.signal,
            headers: API_HEADERS,
        });
        clearTimeout(timeoutId);
        if (!response.ok) {
            throw new Error(`API Error: ${endpoint} (${response.status})`);
        }
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        console.error(`[fetchAPI Error] ${url}:`, error);
        throw error;
    }
}

export async function postAPI<T>(endpoint: string, body?: any): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
            body: body ? JSON.stringify(body) : undefined,
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!response.ok) {
            const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
            throw new Error(err.error || `API Error: ${endpoint} (${response.status})`);
        }
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        console.error(`[postAPI Error] ${url}:`, error);
        throw error;
    }
}

// KR Market API Types
export interface KRSignal {
    ticker: string;
    name: string;
    market: 'KOSPI' | 'KOSDAQ';
    signal_date: string;
    entry_price: number;
    current_price: number;
    return_pct: number;
    foreign_5d: number;
    inst_5d: number;
    score: number;
    contraction_ratio: number;
}

export interface KRSignalsResponse {
    signals: KRSignal[];
    error?: string;
}

export interface KRMarketGate {
    score: number;
    label: string;
    kospi_close: number;
    kospi_change_pct: number;
    kosdaq_close: number;
    kosdaq_change_pct: number;
    sectors: KRSector[];
}

export interface KRSector {
    name: string;
    change_pct: number;
    signal: 'bullish' | 'neutral' | 'bearish';
}

export interface AIRecommendation {
    action: 'BUY' | 'SELL' | 'HOLD';
    confidence: number;
    reason: string;
}

export interface KRAIAnalysis {
    signals: Array<{
        ticker: string;
        gpt_recommendation?: AIRecommendation;
        gemini_recommendation?: AIRecommendation;
    }>;
    market_indices?: {
        kospi?: { value: number; change_pct: number };
        kosdaq?: { value: number; change_pct: number };
    };
}

// KR Market API functions
export const krAPI = {
    getSignals: () => fetchAPI<KRSignalsResponse>('/api/kr/signals'),
    getMarketGate: () => fetchAPI<KRMarketGate>('/api/kr/market-gate'),
    getAIAnalysis: () => fetchAPI<KRAIAnalysis>('/api/kr/ai-analysis'),
    getVCPEnhanced: () => fetchAPI<any>('/api/kr/vcp-enhanced'),
    getLeadingStocks: () => fetchAPI<any>('/api/kr/screener/leading'),
};

// ── Jongga V2 (종가베팅) Types ──────────────────────────────────────────────

export interface JonggaV2ScoreDetail {
    news: number;
    volume: number;
    chart: number;
    candle: number;
    consolidation: number;
    supply: number;
    disclosure: number;
    analyst: number;
    financial: number;
    total: number;
    llm_reason?: string;
    llm_source?: string;
}

export interface JonggaV2Signal {
    stock_code: string;
    stock_name: string;
    market: string;
    sector?: string;
    grade: 'S' | 'A' | 'B' | 'C';
    change_pct: number;
    trading_value: number;
    current_price: number;
    entry_price: number;
    stop_price: number;
    target_price: number;
    quantity?: number;
    position_size?: number;
    r_value?: number;
    r_multiplier?: number;
    foreign_5d: number;
    inst_5d: number;
    volume_ratio?: number;
    score: JonggaV2ScoreDetail;
    news_items?: string[];
    themes?: string[];
}

export interface JonggaV2AIPick {
    stock_code: string;
    stock_name: string;
    rank: number;
    confidence: 'HIGH' | 'MEDIUM' | 'LOW';
    reason: string;
    risk: string;
    expected_return?: string;
    source?: string;
}

export interface JonggaV2Result {
    date: string;
    total_candidates: number;
    filtered_count: number;
    signals: JonggaV2Signal[];
    by_grade: { S: number; A: number; B: number; C: number };
    by_market?: { KOSPI: number; KOSDAQ: number };
    processing_time_ms?: number;
    updated_at?: string;
    claude_picks?: {
        picks: JonggaV2AIPick[];
        consensus_count?: number;
        market_view?: string;
        top_themes?: string[];
        generated_at?: string;
    };
}

export interface JonggaPerformanceSummary {
    total_days: number;
    total_s: number;
    total_a: number;
    total_b: number;
    avg_s_per_day: number;
    avg_a_per_day: number;
    avg_signals_per_day: number;
}

export interface JonggaPerformanceHistory {
    date: string;
    by_grade: { S: number; A: number; B: number; C?: number };
    filtered_count: number;
    top_signal: { name: string; grade: string; change_pct: number; score: number } | null;
    market_view: string;
}

export interface JonggaPerformanceData {
    history: JonggaPerformanceHistory[];
    summary: JonggaPerformanceSummary;
}

// Jongga V2 API
export const jonggaAPI = {
    getLatest: () => fetchAPI<JonggaV2Result>('/api/kr/jongga-v2/latest'),
    getDates: () => fetchAPI<{ dates: string[] }>('/api/kr/jongga-v2/dates'),
    getPerformance: () => fetchAPI<JonggaPerformanceData>('/api/kr/jongga-v2/performance'),
    getTodaySummary: () => fetchAPI<{
        date: string;
        by_grade: { S: number; A: number; B: number };
        filtered_count: number;
        top_signal: {
            stock_code: string; stock_name: string; grade: string;
            change_pct: number; score_total: number;
            entry_price: number; stop_price: number; target_price: number;
            llm_reason: string;
        } | null;
        market_view: string;
        top_themes: string[];
    }>('/api/kr/jongga-v2/today-summary'),
};

// US Market API Types
export interface USMarketIndex {
    name: string;
    ticker: string;
    price: number;
    change: number;
    change_pct: number;
}

export interface USMarketGate {
    gate: 'GREEN' | 'YELLOW' | 'RED';
    score: number;
    status: 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF';
    label?: string;
    reasons: string[];
    metrics?: {
        rsi?: number;
        vix?: number;
        spy_price?: number;
    };
    spy: {
        price: number;
        ma50: number;
        ma200: number;
        rsi: number;
        change_1d: number;
        change_5d: number;
    };
}

// US Market Extended Types (us-market-pro)
export interface PortfolioIndex {
    name: string;
    price: string | number;
    change: string | number;
    change_pct: number;
    color?: string;
}

export interface SmartMoneyStock {
    ticker: string;
    name: string;
    sector: string;
    price: number;
    price_at_rec: number;
    change_pct: number;
    composite_score: number;
    swing_score: number;
    trend_score: number;
    grade: string;
    recommendation: string;
    ai_summary?: string;
}

export interface SmartMoneyDetail {
    ticker: string;
    name: string;
    sector: string;
    price: number;
    change_pct: number;
    chart: Array<{
        date: string;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
        ma20: number | null;
        ma50: number | null;
        rsi: number | null;
        macd: number | null;
        macd_signal: number | null;
        macd_hist: number | null;
    }>;
    technicals: any;
    smart_money: any;
    ai_analysis: { summary: string; generated_at: string };
    why_buy: Array<{ type: string; icon: string; title: string; desc: string }>;
}

export interface SectorRotationData {
    timestamp: string;
    performance_matrix: Record<string, any>;
    rotation_signals: {
        current_phase: string;
        phase_confidence: number;
        phase_scores: Record<string, number>;
        leading_sectors: string[];
        lagging_sectors: string[];
        rotation_velocity: number;
    };
    relative_strength_history: { dates: string[]; sectors: Record<string, number[]> };
    money_flow: { inflows: any[]; outflows: any[]; regime_change_alert: boolean };
    rotation_clock: { phases: Record<string, any>; current_angle: number };
}

export interface RiskAlertData {
    timestamp: string;
    portfolio_summary: {
        total_picks: number;
        portfolio_var_95_5d: number;
        portfolio_cvar_95_5d: number;
        risk_level: string;
    };
    drawdowns: Record<string, any>;
    concentration?: any;
    alerts: Array<{ alert_type: string; severity: string; ticker: string | null; message: string; value: number | null; threshold: number }>;
}

export interface EarningsImpactData {
    timestamp: string;
    sector_profiles: Record<string, any>;
    upcoming_earnings: Array<{
        ticker: string; sector: string; earnings_date: string; days_until: number;
        signal: string; confidence: number; implied_move_pct: number | null;
        historical_avg_move: number; recommendation_ko: string; recommendation_en: string;
    }>;
}

export interface IndexPredictionData {
    timestamp: string;
    predictions: Record<string, {
        current_price: number; bullish_probability: number; bearish_probability: number;
        predicted_return_pct: number; target_range: { low: number; mid: number; high: number };
        confidence_level: string;
        key_drivers: Array<{ feature: string; impact: number; value: number; direction: string }>;
    }>;
    model_info: { algorithm: string; training_accuracy: number; training_samples: number; last_trained: string };
    historical_performance?: { total_predictions: number; direction_accuracy: number };
    disclaimer_ko?: string;
    disclaimer_en?: string;
}

export interface MarketRegimeData {
    timestamp: string;
    regime: 'risk_on' | 'neutral' | 'risk_off' | 'crisis';
    confidence: number;
    weighted_score: number;
    signals: {
        vix: { vix_current: number; vix_ma20: number; vix_trend: string; vix_regime: string };
        trend: { trend_regime: string; spy_above_50: boolean; spy_above_200: boolean; sma200_slope: number };
        breadth: { breadth_pct: number | null; breadth_regime: string };
        yield_curve: { yield_spread: number | null; yield_regime: string };
    };
}

export interface BacktestData {
    period: { start: string; end: string; trading_days: number; years: number };
    portfolio: { stocks: string[]; num_stocks: number; strategy: string };
    returns: {
        total_return: number; annualized_return: number; volatility: number;
        sharpe_ratio: number; max_drawdown: number; win_rate: number;
        best_day: number; worst_day: number;
    };
    benchmarks: Record<string, { total_return: number; alpha: number }>;
}

export interface DecisionSignalData {
    action: 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'CAUTIOUS' | 'DEFENSIVE';
    score: number;
    components: {
        market_gate: { score: number; contribution: number };
        regime: { regime: string; contribution: number };
        prediction: { spy_bullish: number; contribution: number };
        risk: { level: string; contribution: number };
        sector_phase: { phase: string; contribution: number };
    };
    top_picks: Array<{ ticker: string; name: string; final_score: number; grade: string; ai_recommendation: string; target_upside: number }>;
    timing: string;
    warnings: string[];
}

export interface TopPicksReportData {
    generated_at: string;
    total_analyzed: number;
    top_picks: Array<{
        ticker: string; name: string; rank: number; grade: string; rsi: number;
        // Live API fields (final_top10_report.json)
        final_score?: number; quant_score?: number; ai_bonus?: number;
        ai_recommendation?: string; current_price?: number; target_upside?: number;
        sd_stage?: string; inst_pct?: number; ai_summary?: string;
        // Legacy snapshot fields (top_picks.json)
        price?: number; composite_score?: number; signal?: string; sector?: string;
    }>;
}

export interface CumulativePerformanceSummary {
    total_picks: number;
    unique_tickers: number;
    win_rate: number;
    avg_return: number;
    avg_alpha: number;
    max_gain: { pct: number; ticker: string };
    max_loss: { pct: number; ticker: string };
    num_snapshots?: number;
}

export interface BriefingMarketData {
    name: string;
    price: number;
    change: number;
    prev_close?: number;
    high_52w?: number;
    low_52w?: number;
    pct_from_high?: number;
}

export interface BriefingFearGreed {
    score: number;
    level: string;
    color: string;
    components: { [key: string]: { value?: number; score: number } };
}

export interface BriefingSmartMoneyPick {
    rank: number;
    ticker: string;
    name: string;
    final_score: number;
    ai_recommendation: string;
    target_upside: number;
    sd_stage: string;
}

export interface BriefingData {
    timestamp: string;
    version: string;
    market_data: {
        indices: { [key: string]: BriefingMarketData };
        futures: { [key: string]: BriefingMarketData };
        bonds: { [key: string]: BriefingMarketData };
        currencies: { [key: string]: BriefingMarketData };
        commodities: { [key: string]: BriefingMarketData };
        korean_indices: { [key: string]: BriefingMarketData };
    };
    vix: { value: number; change: number; level: string; color: string };
    fear_greed: BriefingFearGreed;
    ai_analysis?: { content: string; citations: string[] };
    sector_rotation?: { content: string; citations: string[] };
    smart_money?: { top_picks?: { timestamp: string; picks: BriefingSmartMoneyPick[] }; performance?: any };
}

export interface CumulativePerformancePick {
    ticker: string;
    name: string;
    rec_date: string;
    entry_price: number;
    current_price: number;
    return_pct: number;
    final_score: number;
    recommendation: string;
}

export interface CumulativePerformanceByDate {
    date: string;
    avg_return: number;
    spy_return: number;
    alpha: number;
    win_rate: number;
    num_picks: number;
}

export interface CumulativePerformanceData {
    summary: CumulativePerformanceSummary;
    chart_data?: Array<{ date: string; avg_return: number; spy_return: number }>;
    picks: CumulativePerformancePick[];
    by_date?: CumulativePerformanceByDate[];
    snapshots?: any[];
    by_grade?: Record<string, any>;
    by_sector?: Record<string, any>;
}

// US Market API functions
export const usAPI = {
    getPortfolio: () => fetchAPI<{ market_indices: (USMarketIndex | PortfolioIndex)[]; timestamp: string }>('/api/us/portfolio'),
    getMarketGate: () => fetchAPI<USMarketGate>('/api/us/market-gate'),
    getSmartMoney: () => fetchAPI<{ picks: SmartMoneyStock[]; count: number; updated_at?: string }>('/api/us/smart-money'),
    getSmartMoneyDetail: (ticker: string) => fetchAPI<SmartMoneyDetail>(`/api/us/smart-money/${ticker}/detail`),
    getSectorRotation: () => fetchAPI<SectorRotationData>('/api/us/sector-rotation'),
    getRiskAlerts: () => fetchAPI<RiskAlertData>('/api/us/risk-alerts'),
    getEarningsImpact: () => fetchAPI<EarningsImpactData>('/api/us/earnings-impact'),
    getIndexPrediction: () => fetchAPI<IndexPredictionData>('/api/us/index-prediction'),
    getMarketBriefing: () => fetchAPI<BriefingData>('/api/us/market-briefing'),
    getMarketRegime: () => fetchAPI<MarketRegimeData>('/api/us/market-regime'),
    getBacktest: () => fetchAPI<BacktestData>('/api/us/backtest'),
    getDecisionSignal: () => fetchAPI<DecisionSignalData>('/api/us/decision-signal'),
    getTopPicksReport: () => fetchAPI<TopPicksReportData>('/api/us/top-picks-report'),
    getCumulativePerformance: () => fetchAPI<{ summary: CumulativePerformanceSummary; picks: any[]; snapshots: any[] }>('/api/us/cumulative-performance'),
    getEtfFlowAnalysis: () => fetchAPI<any>('/api/us/etf-flows'),
    getSuperPerformance: () => fetchAPI<any>('/api/us/super-performance'),
    getVCPEnhanced: () => fetchAPI<any>('/api/us/vcp-enhanced'),
};

// Crypto API Types
export interface CryptoAsset {
    name: string;
    ticker: string;
    price: number;
    change: number;
    change_pct: number;
    volume_24h: number;
}

export interface CryptoDominance {
    btc_price: number;
    eth_price: number;
    btc_rsi: number;
    btc_30d_change: number;
    sentiment: string;
}

export const cryptoAPI = {
    getOverview: () => fetchAPI<{ cryptos: CryptoAsset[]; timestamp: string }>('/api/crypto/overview'),
    getDominance: () => fetchAPI<CryptoDominance>('/api/crypto/dominance'),
    getMarketGate: () => fetchAPI<CryptoMarketGate>('/api/crypto/market-gate'),
    getGateHistory: () => fetchAPI<{ history: Array<{ date: string; gate: string; score: number }> }>('/api/crypto/gate-history'),
    getVCPSignals: (limit = 50) => fetchAPI<{ signals: CryptoSignal[]; count: number }>(`/api/crypto/vcp-signals?limit=${limit}`),
    getBriefing: () => fetchAPI<CryptoBriefingData>('/api/crypto/briefing'),
    getPrediction: () => fetchAPI<CryptoPredictionData>('/api/crypto/prediction'),
    getPredictionHistory: () => fetchAPI<{ history: Array<{ date: string; bullish_probability: number; btc_price: number }> }>('/api/crypto/prediction-history'),
    getRisk: () => fetchAPI<CryptoRiskData>('/api/crypto/risk'),
    getLeadLag: () => fetchAPI<CryptoLeadLagData>('/api/crypto/lead-lag'),
    getLeadLagChartList: () => fetchAPI<{ charts: string[] }>('/api/crypto/lead-lag/charts/list'),
    getVCPEnhanced: () => fetchAPI<any>('/api/crypto/vcp-enhanced'),
    getBacktestSummary: () => fetchAPI<CryptoBacktestResult>('/api/crypto/backtest-summary'),
    getBacktestResults: () => fetchAPI<CryptoBacktestResult>('/api/crypto/backtest-results'),
    getDataStatus: () => fetchAPI<CryptoDataStatus>('/api/crypto/data-status'),
    getTaskStatus: () => fetchAPI<Record<string, boolean>>('/api/crypto/task-status'),
    runScan: () => postAPI<TaskTriggerResponse>('/api/crypto/run-scan'),
    runGate: () => postAPI<TaskTriggerResponse>('/api/crypto/gate-scan'),
    runPrediction: () => postAPI<TaskTriggerResponse>('/api/crypto/run-prediction'),
    runRisk: () => postAPI<TaskTriggerResponse>('/api/crypto/run-risk'),
    runBriefing: () => postAPI<TaskTriggerResponse>('/api/crypto/run-briefing'),
    runLeadLag: () => postAPI<TaskTriggerResponse>('/api/crypto/run-leadlag'),
};

// CryptoAnalytics 확장 타입
export interface CryptoMarketGate {
    status: string; gate: string; score: number;
    price?: number; ma200?: number; reasons?: string[];
    metrics?: Record<string, any>; generated_at?: string;
}
export interface CryptoSignal {
    symbol: string; exchange: string; signal_type: string; score: number;
    timeframe: string; pivot_high: number; vol_ratio: number;
    ml_win_prob?: number | null; created_at: string;
}
export interface CryptoBriefingData {
    timestamp: string;
    market_summary: { total_market_cap: number; total_market_cap_change_24h: number; btc_dominance: number; btc_dominance_change_24h: number; total_volume_24h: number; active_cryptocurrencies: number };
    major_coins: Record<string, { price: number; change_24h: number; change_7d: number; volume_24h: number; market_cap: number }>;
    top_movers: { gainers: Array<{ symbol: string; name: string; change_24h: number; price: number }>; losers: Array<{ symbol: string; name: string; change_24h: number; price: number }> };
    fear_greed: { score: number; level: string; previous: number; change: number };
    funding_rates: Record<string, { rate: number; rate_pct: number; annualized_pct: number; sentiment: string }>;
    macro_correlations: { btc_pairs: Record<string, number> };
    market_gate: { gate: string; score: number; reasons: string[] } | null;
    sentiment_summary: { overall: string; factors: string[] };
    btc_price_history?: Array<{ date: string; price: number }>;
}
export interface CryptoPredictionData {
    timestamp: string;
    predictions: Record<string, { current_price: number; bullish_probability: number; bearish_probability: number; confidence_level: string; key_drivers: Array<{ feature: string; impact: number; value: number; direction: string }> }>;
    model_info: { algorithm: string; training_accuracy: number; training_samples: number; last_trained: string; ensemble_models?: Array<{ name: string; accuracy: number; bullish: number }> };
}
export interface CryptoRiskData {
    timestamp: string;
    portfolio_summary: { total_coins: number; portfolio_var_95_1d: number; portfolio_cvar_95_1d: number; risk_level: string };
    correlation_matrix: { coins: string[]; values: number[][] };
    individual_risk: Record<string, { var_95_1d: number; max_dd_30d: number; volatility_30d: number }>;
    concentration: { btc_weight_pct: number; top3_weight_pct: number; warnings: string[] };
    alerts: Array<{ severity: string; message: string; coin: string }>;
}
export interface CryptoLeadLagData {
    metadata: { target: string; generated_at: string };
    lead_lag: Array<{ var1: string; var2: string; optimal_lag: number; optimal_correlation: number; interpretation: string; p_value?: number; all_lags?: Record<string, number> }>;
    granger: Array<{ cause: string; effect: string; best_lag: number; best_p_value: number; is_significant: boolean }>;
    data_summary?: { date_range?: { start: string; end: string; periods: number }; columns?: string[] };
}

// Backtest Types
export interface CryptoBacktestResult {
    config?: Record<string, any>;
    performance?: { total_trades: number; win_rate: number; profit_factor: number; avg_r_multiple: number; max_consecutive_losses: number; max_drawdown_pct: number; sharpe_ratio: number; total_pnl_net: number; total_fees: number };
    regime_breakdown?: Record<string, { trades: number; win_rate: number; avg_pnl: number }>;
    trades_summary?: { winners: number; losers: number; gross_pnl: number };
    trades?: Array<{ symbol: string; entry_time: number; entry_price: number; entry_type: string; exit_price: number; exit_reason: string; return_pct: number; r_multiple: number; is_winner: boolean; score: number; grade: string; market_regime: string }>;
}
export interface CryptoDataStatusFile {
    name: string; file: string; exists: boolean; size_bytes: number; size_human: string;
    last_modified: string; staleness_hours: number; freshness: 'fresh' | 'stale' | 'old' | 'missing';
}
export interface CryptoDataStatus { files: CryptoDataStatusFile[]; timestamp: string }
export interface TaskTriggerResponse { status: 'started' | 'already_running' | 'completed' | 'error'; task: string; message?: string }

// Admin API Types
export interface AdminUser {
    id: number;
    email: string;
    name: string;
    role: string;
    tier: string;
    subscription_status: string;
    stripe_customer_id: string | null;
    created_at: string;
    approved_at: string | null;
    last_login_at: string | null;
}

export interface AdminDashboard {
    total_users: number;
    pro_users: number;
    free_users: number;
    admin_users: number;
    pending_subscriptions: number;
}

export interface SubscriptionRequest {
    id: number;
    user_id: number;
    user_email: string;
    user_name: string;
    request_type: string;
    from_tier: string;
    to_tier: string;
    status: string;
    payment_id: string | null;
    admin_note: string | null;
    created_at: string;
    processed_at: string | null;
}

// ── Authenticated API helpers (Bearer token 포함) ──

function _handle401(status: number) {
    if (status === 401) {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user');
        if (window.location.pathname !== '/login') {
            window.location.href = '/login';
        }
    }
}

async function _authFetch(url: string, options: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(timeoutId);
        if (!response.ok) {
            _handle401(response.status);
            const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
            throw new Error(err.error || `API Error: ${url} (${response.status})`);
        }
        return response;
    } catch (error) {
        clearTimeout(timeoutId);
        console.error(`[authFetch Error] ${url}:`, error);
        throw error;
    }
}

export async function fetchAuthAPI<T>(endpoint: string, apiToken?: string): Promise<T> {
    const headers: Record<string, string> = { ...API_HEADERS };
    if (apiToken) headers['Authorization'] = `Bearer ${apiToken}`;
    const response = await _authFetch(`${API_BASE}${endpoint}`, { headers });
    return response.json();
}

export async function putAuthAPI<T>(endpoint: string, body?: any, apiToken?: string): Promise<T> {
    const headers: Record<string, string> = { ...API_HEADERS, 'Content-Type': 'application/json' };
    if (apiToken) headers['Authorization'] = `Bearer ${apiToken}`;
    const response = await _authFetch(`${API_BASE}${endpoint}`, {
        method: 'PUT', headers,
        body: body ? JSON.stringify(body) : undefined,
    });
    return response.json();
}

export async function postAuthAPI<T>(endpoint: string, body?: any, apiToken?: string): Promise<T> {
    const headers: Record<string, string> = { ...API_HEADERS, 'Content-Type': 'application/json' };
    if (apiToken) headers['Authorization'] = `Bearer ${apiToken}`;
    const response = await _authFetch(`${API_BASE}${endpoint}`, {
        method: 'POST', headers,
        body: body ? JSON.stringify(body) : undefined,
    });
    return response.json();
}

export async function deleteAuthAPI<T>(endpoint: string, apiToken?: string): Promise<T> {
    const headers: Record<string, string> = { ...API_HEADERS };
    if (apiToken) headers['Authorization'] = `Bearer ${apiToken}`;
    const response = await _authFetch(`${API_BASE}${endpoint}`, { method: 'DELETE', headers });
    return response.json();
}

export async function putAPI<T>(endpoint: string, body?: any): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'PUT',
            headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
            body: body ? JSON.stringify(body) : undefined,
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!response.ok) throw new Error(`API Error: ${response.status}`);
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        throw error;
    }
}

// ── Admin API (Bearer token 기반) ──
export const adminAPI = {
    getDashboard: (token?: string) => fetchAuthAPI<AdminDashboard>('/api/admin/dashboard', token),
    getUsers: (token?: string) => fetchAuthAPI<{ users: AdminUser[] }>('/api/admin/users', token),
    getUser: (id: number, token?: string) => fetchAuthAPI<AdminUser>(`/api/admin/users/${id}`, token),
    setUserRole: (id: number, role: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/role`, { role }, token),
    setUserTier: (id: number, tier: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/tier`, { tier }, token),
    setUserStatus: (id: number, status: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/status`, { status }, token),
    resetPassword: (id: number, password: string, token?: string) => putAuthAPI<{ message: string; user: AdminUser }>(`/api/admin/users/${id}/reset-password`, { password }, token),
    deleteUser: (id: number, token?: string) => deleteAuthAPI<{ message: string }>(`/api/admin/users/${id}`, token),
    getSubscriptions: (token?: string) => fetchAuthAPI<{ requests: SubscriptionRequest[] }>('/api/admin/subscriptions', token),
    approveSubscription: (id: number, token?: string) => putAuthAPI<{ request: SubscriptionRequest }>(`/api/admin/subscriptions/${id}/approve`, undefined, token),
    rejectSubscription: (id: number, note?: string, token?: string) => putAuthAPI<{ request: SubscriptionRequest }>(`/api/admin/subscriptions/${id}/reject`, { note }, token),
};

// ── Wave Pattern API ──
export interface WaveDashboardData {
    summary: {
        total_signals: number;
        active: number;
        wins: number;
        losses: number;
        win_rate: number;
    };
    active_signals: Array<{
        id: number;
        ticker: string;
        name: string;
        pattern_class: string;
        wave_type: string;
        wave_label: string;
        confidence: number;
        signal_price: number;
        neckline_price: number;
        status: string;
        signal_date: string;
    }>;
    recent_closed: Array<any>;
    pattern_stats: Array<any>;
}

export const waveAPI = {
    getDashboard: () => fetchAPI<WaveDashboardData>('/api/wave/dashboard'),
    getScreenerLatest: () => fetchAPI<any>('/api/wave/screener/latest'),
    getDetect: (ticker: string, market = 'KR') => fetchAPI<any>(`/api/wave/detect/${ticker}?market=${market}`),
    getPatternTypes: () => fetchAPI<any>('/api/wave/pattern-types'),
    getSignals: (params?: string) => fetchAPI<any>(`/api/wave/signals${params ? `?${params}` : ''}`),
    getStats: () => fetchAPI<any>('/api/wave/stats'),
};

// ── User Subscription API (Bearer token 기반) ──
export const subscriptionAPI = {
    requestUpgrade: (toTier: string, token?: string) => postAuthAPI<{ request: SubscriptionRequest }>('/api/auth/subscription/request', { to_tier: toTier }, token),
    getStatus: (token?: string) => fetchAuthAPI<{ user: AdminUser; requests: SubscriptionRequest[] }>('/api/auth/subscription/status', token),
    updateProfile: (name: string, token?: string) => putAuthAPI<{ user: AdminUser }>('/api/auth/profile', { name }, token),
};

// ── Stripe API (requires auth token) ──
export const stripeAPI = {
    createCheckout: (apiToken: string) => postAuthAPI<{ url: string }>('/api/stripe/create-checkout', undefined, apiToken),
    getPortal: (apiToken: string) => postAuthAPI<{ url: string }>('/api/stripe/portal', undefined, apiToken),
};
