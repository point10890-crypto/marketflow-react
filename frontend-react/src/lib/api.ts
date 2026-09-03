// API utility functions
//
// Architecture:
//   Dev:  Vite proxy /api/* → Flask 5001 (vite.config.ts)
//   Prod: VITE_API_BASE_URL → Cloudflare Tunnel → Flask 5001

import { getToken } from './auth';

export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// 모든 API 호출에 사용할 인증 헤더.
// localStorage/sessionStorage 에서 토큰을 읽어 Bearer 헤더를 생성.
// 토큰이 없으면 빈 객체 반환 → public 엔드포인트도 호출 가능.
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
    const token = getToken();
    const headers: Record<string, string> = extra ? { ...extra } : {};
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
}

/** Restrict backend-provided redirects to an absolute path on this origin. */
export function safeLocalRedirect(value: unknown, fallback: string): string {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
        return fallback;
    }
    try {
        const base = typeof window !== 'undefined' ? window.location.origin : 'https://local.invalid';
        const parsed = new URL(value, base);
        if (parsed.origin !== base) return fallback;
        return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
        return fallback;
    }
}

/** 만료/계정정지 응답 자동 처리 — 모든 fetchAPI / postAPI 공통 사용 */
async function _handleAuthGate(response: Response, url: string): Promise<void> {
    if (response.status !== 401 && response.status !== 403) return;
    let body: any = null;
    try {
        body = await response.clone().json();
    } catch {
        return;
    }
    if (!body || typeof body !== 'object') return;
    // 만료/계정정지 시 자동 redirect (data 페이지에서 발생 시)
    if (body.expired || body.status === 'expired') {
        try {
            // 무한 루프 방지: 이미 /plan-select 에 있으면 skip
            if (typeof window !== 'undefined' && !window.location.pathname.includes('/plan-select')) {
                console.warn('[fetchAPI] subscription expired — redirect to plan-select', url);
                window.location.replace(safeLocalRedirect(
                    body.redirect_to,
                    '/plan-select?resubscribe=1&from=expired',
                ));
            }
        } catch { /* ignore */ }
    }
}


/** fetchAPI 가 throw 하는 Error — status 속성으로 호출자가 분기 가능 */
export class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
    }
}

export class ApiTimeoutError extends Error {
    readonly url: string;
    readonly timeoutMs: number;

    constructor(url: string, timeoutMs: number) {
        super(`API timeout: ${url}`);
        this.name = 'ApiTimeoutError';
        this.url = url;
        this.timeoutMs = timeoutMs;
    }
}

/** Fetch with a deadline while preserving a caller-provided abort signal. */
export async function fetchWithTimeout(
    input: RequestInfo | URL,
    init: RequestInit = {},
    timeoutMs = 15000,
): Promise<Response> {
    const controller = new AbortController();
    const callerSignal = init.signal;
    let timedOut = false;
    const abortFromCaller = () => controller.abort();

    if (callerSignal?.aborted) controller.abort();
    else callerSignal?.addEventListener('abort', abortFromCaller, { once: true });

    const timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, timeoutMs);

    try {
        return await fetch(input, { ...init, signal: controller.signal });
    } catch (error) {
        if (timedOut && error instanceof DOMException && error.name === 'AbortError') {
            throw new ApiTimeoutError(String(input), timeoutMs);
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
        callerSignal?.removeEventListener('abort', abortFromCaller);
    }
}

export async function fetchAPI<T>(endpoint: string, timeoutMs = 10000): Promise<T> {
    const url = `${API_BASE}${endpoint}`;

    try {
        const response = await fetchWithTimeout(url, {
            headers: authHeaders(),
        }, timeoutMs);
        if (!response.ok) {
            await _handleAuthGate(response, url);
            throw new ApiError(`API Error: ${endpoint} (${response.status})`, response.status);
        }
        return await response.json();
    } catch (error) {
        console.error(`[fetchAPI Error] ${url}:`, error);
        throw error;
    }
}

export async function postAPI<T>(endpoint: string, body?: any, timeoutMs = 15000): Promise<T> {
    const url = `${API_BASE}${endpoint}`;

    try {
        const response = await fetchWithTimeout(url, {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: body ? JSON.stringify(body) : undefined,
        }, timeoutMs);
        if (!response.ok) {
            await _handleAuthGate(response, url);
            const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
            throw new ApiError(err.error || `API Error: ${endpoint} (${response.status})`, response.status);
        }
        return await response.json();
    } catch (error) {
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
    getAIChartAnalysis: () => fetchAPI<KRAIChartAnalysisResponse>('/api/kr/ai-chart-analysis'),
};

export interface KRAIChartSignal {
    stock_code: string;
    stock_name: string;
    market: string;
    signal: 'BUY' | 'HOLD' | 'SELL';
    confidence: number;
    ma_status: string;
    rsi_zone: string;
    volume_trend: string;
    reasons: string[];
}

export interface KRAIChartAnalysisResponse {
    signals: KRAIChartSignal[];
    summary: {
        total: number;
        by_signal: Record<string, number>;
        by_market: Record<string, number>;
        avg_confidence: number;
    };
    updated_at: string | null;
}

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

export interface DevilAdvocateFlag {
    category: string;
    severity: 'HIGH' | 'MEDIUM' | 'LOW';
    evidence: string;
}

export interface JonggaV2AIPick {
    stock_code: string;
    stock_name: string;
    rank: number;
    confidence: 'HIGH' | 'MEDIUM' | 'LOW';
    reason: string;
    reasons?: { gemini?: string; openai?: string; grok?: string };
    risk: string;
    expected_return?: string;
    source?: string;
    gemini_rank?: number;
    openai_rank?: number;
    grok_rank?: number;
    devil_advocate_flags?: DevilAdvocateFlag[];
    review_verdict?: 'PASS' | 'WARN' | 'BLOCK';
    review_reasoning?: string;
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
        strong_count?: number;
        market_view?: string;
        top_themes?: string[];
        generated_at?: string;
        consensus_method?: string;
        models?: string[];
        models_attempted?: string[];
        models_succeeded?: string[];
        total_cost_usd?: number;
        devil_advocate_enabled?: boolean;
        devil_advocate_model?: string;
        devil_advocate_flagged_count?: number;
        devil_advocate_cost_usd?: number;
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
    getAIChartAnalysis: () => fetchAPI<USAIChartAnalysisResponse>('/api/us/ai-chart-analysis'),
};

export interface USAIChartSignal {
    ticker: string;
    name: string;
    sector: string;
    signal: 'BUY' | 'HOLD' | 'SELL';
    confidence: number;
    ma_status: string;
    rsi_zone: string;
    volume_trend: string;
    reasons: string[];
}

export interface USAIChartAnalysisResponse {
    signals: USAIChartSignal[];
    summary: {
        total: number;
        by_signal: Record<string, number>;
        by_sector: Record<string, number>;
        avg_confidence: number;
    };
    updated_at: string | null;
}

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

// ── Market Indices ──
export interface MarketIndexItem {
    name: string;
    price: string;
    change: string;
    change_pct: number;
    color: string;
}

export const commonAPI = {
    getMarketIndices: () => fetchAPI<{ indices: MarketIndexItem[]; updated_at: number }>('/api/market-indices'),
};

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
    status: string;
    pro_expires_at: string | null;
    is_pro_expired?: boolean;
    requested_tier?: 'pro' | 'premium' | null;
    created_at: string;
    approved_at: string | null;
    last_login_at: string | null;
    // AI Brain 알파 스캐너 (애드온)
    aibain_enabled?: boolean;
    aibain_expires_at?: string | null;
    is_aibain_active?: boolean;
    is_aibain_expired?: boolean;
    aibain_days_remaining?: number | null;
    // 회원 본인 텔레그램 알림 연결 여부
    telegram_linked?: boolean;
    telegram_linked_at?: string | null;
}

export interface AdminAuditLogEntry {
    id: number;
    admin_id: number | null;
    admin_email: string | null;
    action: string;
    target_user_id: number | null;
    target_email: string | null;
    before: any;
    after: any;
    note: string | null;
    created_at: string;
}

export interface AdminNotification {
    id: number;
    type: 'purchase_request' | 'subscription_request' | 'new_signup';
    title: string;
    message: string;
    is_read: boolean;
    related_id: number | null;
    created_at: string;
}

export interface AdminDashboard {
    total_users: number;
    pro_users: number;
    premium_users: number;
    no_tier_users: number;
    admin_users: number;
    pending_users: number;
    approved_users: number;
    suspended_users: number;
    expired_users?: number;           // 만료 · 재구독 대기
    churn?: {
        expiring_d3: number;              // 만료 임박 (D-3 이내)
        expired_unrenewed: number;        // 만료 후 미재구독
        resubscribed_this_month: number;  // 이번 달 재구독 승인
    };
    pending_subscriptions: number;
    pending_signups?: number;         // 가입만 완료 · 플랜 미선택 (팔로업 대상)
    pro_expiring_soon?: number;       // Pro 베이스 D-3 이내 만료 임박
    // AI Brain 알파 스캐너 (애드온) 통계
    aibain_active_users?: number;
    aibain_expiring_soon?: number;   // D-3 이내 만료 임박
    pending_aibain_subs?: number;     // AI Brain 최초/재구독 pending 카운트
}

export interface SubscriptionRequest {
    id: number;
    user_id: number;
    user_email: string;
    user_name: string;
    request_type: string;
    from_tier: string;  // 'none' | 'pro' | 'premium'
    to_tier: string;    // 'pro' | 'premium'
    status: string;
    payment_id: string | null;
    admin_note: string | null;
    depositor_name: string | null;
    amount: string | null;
    created_at: string;
    processed_at: string | null;
}

export interface AibainSubscriptionStatus {
    state: 'active' | 'expired' | 'available' | 'unavailable' | 'activation_pending' | 'renewal_pending';
    is_active: boolean;
    is_expired: boolean;
    renewal_eligible: boolean;
    expires_at: string | null;
    pending_request: SubscriptionRequest | null;
    has_other_pending_request: boolean;
}

export interface PendingSignup {
    id: number;
    email: string;
    name: string;
    created_at: string | null;
    requested_tier: string | null;
}

/** 만료 · 재구독 대기 회원 (사각지대 제로 원칙의 만료 확장) */
export interface ExpiredMember {
    id: number;
    email: string;
    name: string;
    tier: string | null;
    pro_expires_at: string | null;
    days_since_expiry: number | null;
    last_login_at: string | null;
}

// ── Authenticated API helpers (Bearer token 포함) ──

function _handle401(status: number) {
    // 단일 API 401에 즉시 로그아웃·리다이렉트하지 않음 (사용자 세션 보존).
    // 진짜 만료 토큰은 isAuthenticated() / AuthContext의 /api/auth/me 체크에서 처리됨.
    // 페이지는 throw된 에러로 빈 상태/에러 UI를 보여주고, 새로고침 시 자연 복구.
    void status;
}

async function _authFetch(url: string, options: RequestInit, timeoutMs: number = 15000): Promise<Response> {
    // Auto-inject auth token if not already present
    const headers = new Headers(options.headers as HeadersInit);
    if (!headers.has('Authorization')) {
        const token = getToken();
        if (token) headers.set('Authorization', `Bearer ${token}`);
    }
    try {
        const response = await fetchWithTimeout(url, { ...options, headers }, timeoutMs);
        if (!response.ok) {
            _handle401(response.status);
            await _handleAuthGate(response, url);
            const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
            throw new Error(err.error || `API Error: ${url} (${response.status})`);
        }
        return response;
    } catch (error) {
        console.error(`[authFetch Error] ${url}:`, error);
        throw error;
    }
}

// apiToken 인자가 주어지면 해당 토큰 사용, 아니면 localStorage 토큰 자동 주입.
function withToken(extra: Record<string, string> | undefined, apiToken?: string): Record<string, string> {
    if (apiToken) return { ...(extra || {}), Authorization: `Bearer ${apiToken}` };
    return authHeaders(extra);
}

export async function fetchAuthAPI<T>(endpoint: string, apiToken?: string, timeoutMs?: number): Promise<T> {
    const response = await _authFetch(
        `${API_BASE}${endpoint}`,
        { headers: withToken(undefined, apiToken) },
        timeoutMs,
    );
    return response.json();
}

export async function putAuthAPI<T>(endpoint: string, body?: any, apiToken?: string): Promise<T> {
    const response = await _authFetch(`${API_BASE}${endpoint}`, {
        method: 'PUT',
        headers: withToken({ 'Content-Type': 'application/json' }, apiToken),
        body: body ? JSON.stringify(body) : undefined,
    });
    return response.json();
}

export async function postAuthAPI<T>(endpoint: string, body?: any, apiToken?: string, timeoutMs?: number): Promise<T> {
    const response = await _authFetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: withToken({ 'Content-Type': 'application/json' }, apiToken),
        body: body ? JSON.stringify(body) : undefined,
    }, timeoutMs ?? 15000);
    return response.json();
}

export async function deleteAuthAPI<T>(endpoint: string, apiToken?: string): Promise<T> {
    const response = await _authFetch(`${API_BASE}${endpoint}`, {
        method: 'DELETE',
        headers: withToken(undefined, apiToken),
    });
    return response.json();
}

export async function putAPI<T>(endpoint: string, body?: any): Promise<T> {
    try {
        const response = await fetchWithTimeout(`${API_BASE}${endpoint}`, {
            method: 'PUT',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: body ? JSON.stringify(body) : undefined,
        }, 15000);
        if (!response.ok) throw new Error(`API Error: ${response.status}`);
        return await response.json();
    } catch (error) {
        throw error;
    }
}

// ── Admin API (Bearer token 기반) ──
// ── 전환 퍼널 요약 (GET /api/admin/funnel/summary) ──
export interface FunnelSummary {
    days: number;
    since: string;
    counts: Record<string, number>;   // register / subscription_request / approve / reject / tier_grant
    users: { registered: number; requested: number; approved: number };
    conversion: {
        register_to_request: number | null;
        request_to_approve: number | null;
        register_to_approve: number | null;
    };
    median_request_to_approve_hours: number | null;
    approved_requests_sampled: number;
}

export const adminAPI = {
    getDashboard: (token?: string) => fetchAuthAPI<AdminDashboard>('/api/admin/dashboard', token),
    getFunnelSummary: (days = 30, token?: string) => fetchAuthAPI<FunnelSummary>(`/api/admin/funnel/summary?days=${days}`, token),
    getUsers: (token?: string, params?: { status?: string; tier?: string; q?: string; page?: number; per_page?: number }) => {
        const qs = new URLSearchParams();
        if (params?.status) qs.set('status', params.status);
        if (params?.tier) qs.set('tier', params.tier);
        if (params?.q) qs.set('q', params.q);
        if (params?.page) qs.set('page', String(params.page));
        if (params?.per_page) qs.set('per_page', String(params.per_page));
        const suffix = qs.toString();
        return fetchAuthAPI<{ users: AdminUser[]; total?: number; page?: number; per_page?: number; total_pages?: number }>(
            `/api/admin/users${suffix ? '?' + suffix : ''}`,
            token,
        );
    },
    getUser: (id: number, token?: string) => fetchAuthAPI<AdminUser>(`/api/admin/users/${id}`, token),
    setUserRole: (id: number, role: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/role`, { role }, token),
    setUserTier: (id: number, tier: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/tier`, { tier }, token),
    setUserStatus: (id: number, status: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/status`, { status }, token),
    extendPro: (id: number, days: number, token?: string) => postAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/extend`, { days }, token),
    setExpiry: (id: number, pro_expires_at: string, token?: string) => putAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/expiry`, { pro_expires_at }, token),
    revokeSubscription: (id: number, note: string | undefined, token?: string) => postAuthAPI<{ user: AdminUser }>(`/api/admin/users/${id}/revoke`, { note: note || '' }, token),
    // AI Brain 알파 스캐너 애드온 관리 (별도 30일 갱신 구독)
    enableAibain: (id: number, days?: number, note?: string, token?: string) =>
        postAuthAPI<{ user: AdminUser; message: string }>(`/api/admin/users/${id}/aibain/enable`, { days: days ?? 30, note }, token),
    extendAibain: (id: number, days?: number, note?: string, token?: string) =>
        postAuthAPI<{ user: AdminUser; message: string }>(`/api/admin/users/${id}/aibain/extend`, { days: days ?? 30, note }, token),
    revokeAibain: (id: number, note?: string, token?: string) =>
        postAuthAPI<{ user: AdminUser; message: string }>(`/api/admin/users/${id}/aibain/revoke`, { note }, token),
    bulkTier: (user_ids: number[], tier: string, token?: string) => postAuthAPI<{ count: number }>(`/api/admin/users/bulk-tier`, { user_ids, tier }, token),
    bulkApprove: (user_ids: number[], token?: string) => postAuthAPI<{ count: number }>(`/api/admin/users/bulk-approve`, { user_ids }, token),
    resetPassword: (id: number, password: string, token?: string, note?: string) => putAuthAPI<{ message: string; user: AdminUser }>(`/api/admin/users/${id}/reset-password`, { password, note }, token),
    deleteUser: (id: number, token?: string) => deleteAuthAPI<{ message: string }>(`/api/admin/users/${id}`, token),
    getDuplicates: (token?: string) => fetchAuthAPI<{ groups: Array<{ reason: string; key: string; accounts: Array<{ id: number; email: string; name: string; tier: string | null; status: string; created_at: string | null; last_login_at: string | null }> }>; total_groups: number }>('/api/admin/users/duplicates', token),
    getSubscriptions: (token?: string) => fetchAuthAPI<{ requests: SubscriptionRequest[]; pending_signups?: PendingSignup[]; expired_members?: ExpiredMember[] }>('/api/admin/subscriptions', token),
    approveSubscription: (id: number, token?: string) => putAuthAPI<{ request: SubscriptionRequest }>(`/api/admin/subscriptions/${id}/approve`, undefined, token),
    rejectSubscription: (id: number, note?: string, token?: string) => putAuthAPI<{ request: SubscriptionRequest }>(`/api/admin/subscriptions/${id}/reject`, { note }, token),
    getNotifications: (token?: string, page = 1) => fetchAuthAPI<{ notifications: AdminNotification[]; total: number; page: number; total_pages: number }>(`/api/admin/notifications?page=${page}`, token),
    getUnreadCount: (token?: string) => fetchAuthAPI<{ unread_count: number }>('/api/admin/notifications/unread-count', token),
    markRead: (id: number, token?: string) => putAuthAPI<AdminNotification>(`/api/admin/notifications/${id}/read`, undefined, token),
    markAllRead: (token?: string) => putAuthAPI<{ message: string }>('/api/admin/notifications/read-all', undefined, token),
    getAuditLog: (token?: string, params?: { limit?: number; action?: string; target_user_id?: number }) => {
        const qs = new URLSearchParams();
        if (params?.limit) qs.set('limit', String(params.limit));
        if (params?.action) qs.set('action', params.action);
        if (params?.target_user_id) qs.set('target_user_id', String(params.target_user_id));
        const suffix = qs.toString();
        return fetchAuthAPI<{ logs: AdminAuditLogEntry[]; count: number }>(`/api/admin/audit-log${suffix ? '?' + suffix : ''}`, token);
    },
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
    requestUpgrade: (toTier: string, token?: string, depositorName?: string, includesAibain?: boolean) =>
        postAuthAPI<{ request: SubscriptionRequest }>('/api/auth/subscription/request', {
            to_tier: toTier,
            depositor_name: depositorName,
            includes_aibain: !!includesAibain,
        }, token),
    requestAibain: (tier: string, token?: string, depositorName?: string) =>
        postAuthAPI<{ request: SubscriptionRequest }>('/api/auth/subscription/request', {
            to_tier: tier,
            depositor_name: depositorName,
            includes_aibain: true,
        }, token),
    getStatus: (token?: string) => fetchAuthAPI<{
        user: AdminUser;
        requests: SubscriptionRequest[];
        aibain_subscription?: AibainSubscriptionStatus;
    }>('/api/auth/subscription/status', token),
    updateProfile: (name: string, token?: string) => putAuthAPI<{ user: AdminUser }>('/api/auth/profile', { name }, token),
    changePassword: (currentPassword: string, newPassword: string, token?: string) => putAuthAPI<{ message: string; token?: string }>('/api/auth/change-password', { current_password: currentPassword, new_password: newPassword }, token),
};

// ── 회원 텔레그램 알림 연결 (승인/만료 안내를 본인에게) ──
export interface TelegramLinkInfo {
    code: string;
    deep_link: string | null;       // https://t.me/<bot>?start=<code> (봇 username 미설정 시 null)
    bot_username: string | null;
    expires_at: string;
    ttl_minutes: number;
    telegram_linked: boolean;
    instructions?: string;
    error?: string;
}

export const telegramAPI = {
    getLinkCode: (token?: string) => postAuthAPI<TelegramLinkInfo>('/api/auth/telegram/link-code', undefined, token),
    unlink: (token?: string) => postAuthAPI<{ message: string; user: AdminUser; error?: string }>('/api/auth/telegram/unlink', undefined, token),
};

// ── AI Briefing API (조간/마감 브리핑) ──
export interface AIBriefingSection {
    heading: string;
    content: string;
}

export interface AIBriefing {
    type: 'morning' | 'closing';
    date: string;
    title: string;
    summary: string;
    sections: AIBriefingSection[];
    market_sentiment: 'BULLISH' | 'NEUTRAL' | 'BEARISH';
    confidence: number;
    key_events: string[];
    sources: string[];
    generated_at: string;
}

export interface BriefingDatesResponse {
    dates: Array<{ date: string; types: string[] }>;
}

export const briefingAPI = {
    getLatest: () => fetchAPI<AIBriefing>('/api/briefing/latest'),
    getMorning: (date?: string) => fetchAPI<AIBriefing>(`/api/briefing/morning${date ? `/${date}` : ''}`),
    getClosing: (date?: string) => fetchAPI<AIBriefing>(`/api/briefing/closing${date ? `/${date}` : ''}`),
    getDates: () => fetchAPI<BriefingDatesResponse>('/api/briefing/dates'),
};

// ── Stripe API (requires auth token) ──
export const stripeAPI = {
    createCheckout: (apiToken: string) => postAuthAPI<{ url: string }>('/api/stripe/create-checkout', undefined, apiToken),
    getPortal: (apiToken: string) => postAuthAPI<{ url: string }>('/api/stripe/portal', undefined, apiToken),
};

// ── Community API ──

export interface CommunityBoard {
    id: number;
    slug: string;
    name: string;
    description: string;
    icon: string;
    sort_order: number;
    min_tier: string;
    write_tier: string;
    is_active: boolean;
    post_count: number;
    latest_post_id?: number | null;
    latest_post_title?: string | null;
    latest_post_at?: string | null;
    can_read?: boolean;
    can_write?: boolean;
    created_at: string;
}

export interface PostAuthor {
    id: number;
    name: string;
    tier: string;
}

export interface CommunityPost {
    id: number;
    board_id: number;
    author: PostAuthor;
    title: string;
    content?: string;
    images?: PostImage[];
    is_notice: boolean;
    view_count: number;
    comment_count: number;
    like_count: number;
    created_at: string;
    updated_at: string;
    is_mine?: boolean;
    board?: { id: number; slug: string; name: string };
    // Formula market fields
    price?: string;
    file_url?: string;
    file_name?: string;
    is_public?: boolean;
    purchase_status?: string | null; // null=미구매, pending, approved, rejected
    purchase_id?: number;
}

export interface PostImage {
    id: number;
    filename: string;
    original_name: string;
    file_size: number;
    url: string;
}

export interface CommunityComment {
    id: number;
    post_id: number;
    author: PostAuthor;
    parent_id: number | null;
    content: string;
    is_hidden: boolean;
    like_count: number;
    created_at: string;
    updated_at: string;
}

export interface PostListResponse {
    posts: CommunityPost[];
    notices: CommunityPost[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
}

export const communityAPI = {
    // Boards
    getBoards: () => fetchAuthAPI<CommunityBoard[]>('/api/community/boards'),
    createBoard: (data: Partial<CommunityBoard>) => postAuthAPI<CommunityBoard>('/api/community/boards', data),

    // Posts
    getPosts: (boardSlug: string, page = 1, perPage = 20) =>
        fetchAuthAPI<PostListResponse>(`/api/community/boards/${boardSlug}/posts?page=${page}&per_page=${perPage}`),
    getPost: (postId: number) => fetchAuthAPI<{ post: CommunityPost }>(`/api/community/posts/${postId}`),
    createPost: (boardSlug: string, data: { title: string; content: string; image_filenames?: string[] }) =>
        postAuthAPI<CommunityPost>(`/api/community/boards/${boardSlug}/posts`, data),
    updatePost: (postId: number, data: { title?: string; content?: string; price?: string; file_url?: string | null; file_name?: string | null; is_public?: boolean }) =>
        putAuthAPI<CommunityPost>(`/api/community/posts/${postId}`, data),
    deletePost: (postId: number) =>
        deleteAuthAPI<{ ok: boolean }>(`/api/community/posts/${postId}`),
    toggleNotice: (postId: number) =>
        putAuthAPI<{ is_notice: boolean }>(`/api/community/posts/${postId}/notice`),

    // Comments
    getComments: (postId: number) =>
        fetchAuthAPI<CommunityComment[]>(`/api/community/posts/${postId}/comments`),
    createComment: (postId: number, data: { content: string; parent_id?: number }) =>
        postAuthAPI<CommunityComment>(`/api/community/posts/${postId}/comments`, data),
    updateComment: (commentId: number, data: { content: string }) =>
        putAuthAPI<CommunityComment>(`/api/community/comments/${commentId}`, data),
    deleteComment: (commentId: number) =>
        deleteAuthAPI<{ ok: boolean }>(`/api/community/comments/${commentId}`),

    // Image Upload
    uploadImage: async (file: File): Promise<{ url: string; filename: string }> => {
        const formData = new FormData();
        formData.append('file', file);
        const { getToken } = await import('./auth');
        const token = getToken();
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}/api/community/upload`, {
            method: 'POST',
            headers,
            body: formData,
        });
        if (!res.ok) throw new Error('Upload failed');
        return res.json();
    },

    // Video upload
    uploadVideo: async (file: File): Promise<{ url: string; filename: string; original_name: string }> => {
        const formData = new FormData();
        formData.append('file', file);
        const { getToken } = await import('./auth');
        const token = getToken();
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}/api/community/upload-video`, {
            method: 'POST',
            headers,
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || 'Video upload failed');
        }
        return res.json();
    },

    // Formula file upload
    uploadFile: async (file: File): Promise<{ url: string; filename: string; original_name: string }> => {
        const formData = new FormData();
        formData.append('file', file);
        const { getToken } = await import('./auth');
        const token = getToken();
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}/api/community/upload-file`, {
            method: 'POST',
            headers,
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || 'Upload failed');
        }
        return res.json();
    },

    // Purchase
    createPurchase: (postId: number, buyerName: string) =>
        postAuthAPI<{ id: number; status: string }>(`/api/community/posts/${postId}/purchase`, { buyer_name: buyerName }),
    getMyPurchases: (status?: 'pending' | 'approved' | 'rejected') =>
        fetchAuthAPI<{ purchases: Array<{
            id: number;
            post_id: number;
            post_title?: string;
            post_price?: string;
            buyer_name: string;
            status: string;
            created_at?: string;
            approved_at?: string;
        }>; total: number }>(`/api/community/purchases/mine${status ? `?status=${status}` : ''}`),

    // Search
    search: (q: string, board?: string, page = 1) => {
        const params = new URLSearchParams({ q, page: String(page) });
        if (board) params.set('board', board);
        return fetchAuthAPI<PostListResponse>(`/api/community/search?${params}`);
    },

    // Summary (public, no auth)
    getSummary: () => fetchAPI<CommunitySummary>('/api/community/summary'),
};

export interface CommunitySummary {
    total_posts: number;
    total_comments: number;
    today_posts: number;
    recent_posts: Array<{ id: number; title: string; board_name: string; created_at: string; comment_count: number }>;
    formula_count: number;
    pending_purchases: number;
}

// ═══════════════════════════════════════════════════════
//  Public Community (비로그인 공개 읽기 — AdSense 심사 콘텐츠)
// ═══════════════════════════════════════════════════════

export interface PublicBoard {
    slug: string;
    name: string;
    description?: string | null;
    post_count: number;
}

export interface PublicPostSummary {
    id: number;
    title: string;
    author_name: string;
    is_notice: boolean;
    view_count: number;
    comment_count: number;
    created_at: string | null;
}

export interface PublicPostDetail extends PublicPostSummary {
    content: string;
    board: { slug: string; name: string };
}

export interface PublicComment {
    id: number;
    author_name: string;
    content: string;
    created_at: string | null;
}

export const publicCommunityAPI = {
    getBoards: () => fetchAPI<{ boards: PublicBoard[] }>('/api/public/community/boards'),
    getPosts: (slug: string, page = 1) =>
        fetchAPI<{
            board: { slug: string; name: string };
            posts: PublicPostSummary[];
            notices: PublicPostSummary[];
            total: number; page: number; per_page: number; total_pages: number;
        }>(`/api/public/community/boards/${slug}/posts?page=${page}`),
    getPost: (id: number) =>
        fetchAPI<{ post: PublicPostDetail; comments: PublicComment[] }>(`/api/public/community/posts/${id}`),
};

// ── Public Track Record (지연·마스킹, 비로그인) ───────────────────────────────
export interface PublicTrackForward {
    outcome: 'TARGET_HIT' | 'STOP_HIT' | 'OPEN' | string;
    outcome_date: string | null;
    roi_pct: number | null;
    hold_roi_pct: number | null;
    max_high_pct: number | null;
    days_held: number;
}

export interface PublicTrackSignal {
    date: string;
    grade: string;
    market: string | null;
    masked: boolean;
    stock_name: string;
    stock_code: string | null;
    change_pct: number | null;
    score_total: number | null;
    forward_return: number | null;
    verification: 'pending' | 'open' | 'closed' | string;
    forward: PublicTrackForward | null;
}

export interface PublicTrackRecord {
    schema_version: string;
    generated_at: string;
    as_of: string | null;
    date_range: { from: string | null; to: string | null };
    days_count: number;
    window_trading_days: number;
    sample_size: number;
    masked_count: number;
    by_grade: Record<string, number>;
    verification: {
        evaluated: number; pending: number; closed: number; open: number;
        wins: number; losses: number;
        win_rate: number | null; avg_roi_pct: number | null; avg_hold_roi_pct: number | null;
    };
    grade_stats: Record<string, { count: number; closed: number; wins: number; win_rate: number | null; avg_roi_pct: number | null }>;
    days: { date: string; count: number; by_grade: Record<string, number>; masked: boolean }[];
    signals: PublicTrackSignal[];
    methodology: Record<string, string>;
    disclaimer: string;
}

export const publicTrackRecordAPI = {
    get: () => fetchAPI<PublicTrackRecord>('/api/public/track-record'),
};

// ── Stock Hub (Pro) ─────────────────────────────────────────────────────────
export interface StockHubPrice {
    close: number; prev_close: number | null; change_pct: number | null;
    date: string; bars: number; source: string;
}

export interface StockHubHistoryEntry {
    date: string; grade: string | null; score_total: number | null; change_pct: number | null;
    entry_price: number | null; stop_price: number | null; target_price: number | null;
    outcome: string | null; roi_pct: number | null; hold_roi_pct: number | null; days_held: number | null;
}

export interface StockHubNews {
    title: string | null; link: string | null; source: string | null; grade: string | null;
    score: number | null; published_ts: string | null; summary: string | null;
}

export interface StockHub {
    schema_version: string;
    generated_at: string;
    code: string;
    name: string | null;
    market: string | null;
    sector: string | null;
    price: StockHubPrice | null;
    chart: { date: string; close: number; high: number | null; low: number | null; volume: number | null }[];
    sources: {
        jongga: Record<string, any> | null;
        leading: Record<string, any> | null;
        vcp: Record<string, any> | null;
        wave: Record<string, any> | null;
        claw: Record<string, any> | null;
    };
    present: string[];
    history: StockHubHistoryEntry[];
    news: StockHubNews[];
    errors: Record<string, string>;
    disclaimer: string;
}

export const stockHubAPI = {
    get: (code: string) => fetchAPI<StockHub>(`/api/kr/stock/${encodeURIComponent(code)}/hub`, 20000),
};
