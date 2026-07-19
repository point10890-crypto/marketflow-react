import { fetchAuthAPI, postAuthAPI } from './api';

export type MiroFishVerdict = 'BUY' | 'SELL' | 'HOLD' | 'BULLISH' | 'BEARISH' | 'NEUTRAL';

export interface MiroFishLayer {
    label: string;
    count: number;
    color?: string;
}

export interface MiroFishLog {
    time?: string;
    text: string;
    tone?: string;
    phase?: number;
}

export interface MiroFishAnalyst {
    name: string;
    role?: string;
    verdict?: MiroFishVerdict | string;
    confidence?: number;
    icon?: string;
}

export interface MiroFishNode {
    label: string;
    x?: number;
    y?: number;
    kind?: 'target' | 'history' | 'analyst' | 'prediction' | 'verdict';
    verdict?: string;
}

export interface MiroFishGraphNode {
    id?: string;
    label?: string;
    type?: string;
    layer?: string;
    score?: number;
    [key: string]: any;
}

export interface MiroFishGraphEdge {
    source?: string;
    target?: string;
    label?: string;
    weight?: number;
    layer?: string;
    [key: string]: any;
}

export interface MiroFishGraphArtifact {
    run_id?: string;
    target?: string;
    source?: string;
    schema_version?: number;
    nodes: MiroFishGraphNode[];
    edges: MiroFishGraphEdge[];
    layers?: Array<Record<string, any>>;
}

export interface MiroFishReport {
    run_id?: string;
    format?: string;
    markdown: string;
}

export interface MiroFishEvent {
    ts?: string;
    level?: string;
    phase?: string;
    message?: string;
    payload?: Record<string, any>;
}

export interface MiroFishEventsResponse {
    run_id?: string;
    events: MiroFishEvent[];
    next_index?: number;
    total?: number;
    has_more?: boolean;
}

export interface MiroFishTargetSnapshot {
    target?: string;
    source?: string;
    resolved?: {
        input?: string;
        symbol?: string | null;
        name?: string;
        display_name?: string;
        market?: string;
        asset_type?: string;
    };
    candidates?: Array<{
        symbol?: string | null;
        name?: string;
        display_name?: string;
        market?: string;
        yahoo_ticker?: string;
        asset_type?: string;
        score?: number;
        match_type?: string;
    }>;
    price?: Record<string, any>;
    kis?: {
        enabled?: boolean;
        found?: boolean;
        source?: string;
        error?: string;
        quote?: Record<string, any>;
        investor?: Record<string, any>;
        sources?: string[];
    };
    signals?: Record<string, any>;
    signal_count?: number;
    briefing_count?: number;
    dart_available?: boolean;
    source_files?: string[];
    built_at?: string;
}

export interface MiroFishTargetSearchResponse {
    target?: string;
    source?: string;
    candidates: NonNullable<MiroFishTargetSnapshot['candidates']>;
}

export interface MiroFishRun {
    id?: string | number;
    target: string;
    display_name?: string;
    symbol?: string | null;
    market?: string | null;
    source?: string;
    price?: number | string;
    change_pct?: number;
    mode?: string;
    status?: string;
    layers?: MiroFishLayer[];
    logs?: MiroFishLog[];
    analysts?: MiroFishAnalyst[];
    graph_nodes?: MiroFishNode[];
    prediction_nodes?: MiroFishNode[];
    verdict?: {
        label?: MiroFishVerdict | string;
        target?: string;
        confidence?: number;
        bullish?: number;
        bearish?: number;
        neutral?: number;
        horizon?: string;
        summary?: string;
    };
    brain?: {
        score?: number;
        regime?: string;
        crisis?: string;
    };
    pipeline?: {
        graph_links?: number;
        similar_events?: number;
        agent_count?: number;
        status?: string;
        graph_method?: string;
        debate_method?: string;
        cio_method?: string;
    };
    progress?: {
        completed_phases?: number;
        total_phases?: number;
        percent?: number;
        current_phase?: string;
        current_label?: string;
        started_at?: string;
        updated_at?: string;
        elapsed_ms?: number;
        error?: string;
    };
    performance?: {
        elapsed_ms?: number;
        events_count?: number;
        graph_nodes?: number;
        graph_edges?: number;
        phase_durations_ms?: Record<string, number>;
    };
    artifacts?: Record<string, string>;
    data_context?: {
        source_files?: string[];
        signals?: Record<string, any>;
        briefing_count?: number;
        dart_available?: boolean;
        kis?: Record<string, any>;
        built_at?: string;
    };
    graph_artifact?: MiroFishGraphArtifact;
    report?: MiroFishReport;
    events?: MiroFishEvent[];
    subscriber_policy?: {
        role?: string;
        daily_limit?: number;
        used_today?: number;
        remaining_today?: number;
        concurrent_limit?: number;
        active_count?: number;
        cache_minutes?: number;
        reused_cached_run?: boolean;
        message?: string;
        date_kst?: string;
    };
}

export interface MiroFishStatus {
    ready?: boolean;
    source?: string;
    brain?: {
        score?: number;
        regime?: string;
        crisis?: string;
    };
    pipeline?: {
        graph_links?: number;
        similar_events?: number;
        agent_count?: number;
        status?: string;
    };
    updated_at?: string;
}

export interface StartMiroFishRunRequest {
    target: string;
    agent_count: number;
    mode: 'full' | string;
    async?: boolean;
}

export interface MiroFishScannerRunRequest {
    market?: 'KR' | 'US' | 'CRYPTO' | string;
    horizon?: string;
    strategy?: string;
    risk_profile?: 'conservative' | 'balanced' | 'aggressive' | string;
    limit?: number;
}

export interface MiroFishAlphaEvidence {
    source?: string;
    field?: string;
    score?: number;
    value?: unknown;
    confidence?: number;
}

export interface MiroFishScannerSourceFile {
    file?: string;
    exists?: boolean;
    generated_at?: string | null;
    modified_at?: string | null;
    freshness?: string;
}

export interface MiroFishAlphaCandidate {
    rank: number;
    symbol: string;
    name?: string;
    display_name: string;
    market?: string;
    alpha_score: number;
    risk_score: number;
    action: string;
    horizon: string;
    signal_quality?: string;
    strategy_tags: string[];
    evidence: MiroFishAlphaEvidence[];
    analysis_profile?: Record<string, any>;
    entry_plan?: Record<string, any>;
    replay_context?: Record<string, any>;
    risk_flags?: string[];
    source?: string;
    generated_at?: string;
    freshness?: Record<string, any>;
    freshness_sec?: number;
    price?: number | string;
    change_pct?: number;
    trading_value?: number;
    ranking_score?: number;
    score_breakdown?: Record<string, number>;
    tradingview?: Record<string, any>;
    crash_rebound_gate?: MiroFishCrashReboundGate | null;
    outcome?: MiroFishOutcomeItem;
}

export interface MiroFishCrashReboundSignal {
    id?: string;
    label?: string;
    state?: 'pass' | 'fail' | 'unknown' | string;
    status?: 'ok' | 'limited' | 'unknown' | string;
    weight?: number;
    detail?: string;
    source_grade?: string;
    source?: string | null;
    fetched_at?: string | null;
    freshness?: 'fresh' | 'recent' | 'stale' | 'unknown' | string;
    confidence?: 'high' | 'medium' | 'low' | string;
}

export interface MiroFishCrashReboundGate {
    schema_version?: string;
    generated_at?: string;
    status?: 'recovery_confirmed' | 'rebound_confirmed' | 'rebound_watch' | 'neutral' | 'caution' | 'risk_off' | 'crash_risk' | 'unknown' | string;
    label?: string;
    score?: number | null;
    confidence?: 'high' | 'medium' | 'low' | string;
    data_coverage_pct?: number | null;
    summary?: string;
    signals?: MiroFishCrashReboundSignal[];
    counts?: Record<string, number>;
    scanner_policy?: {
        mode?: string;
        alpha_multiplier?: number;
        risk_multiplier?: number;
        confidence_cap_pct?: number;
        telegram_level?: string;
        reason?: string;
    };
    source_packet?: Record<string, any>;
    non_goals?: string[];
}

export interface MiroFishFearIndexComponent {
    id?: string;
    label?: string;
    score?: number | null;
    weight?: number;
    status?: 'ok' | 'limited' | 'unknown' | string;
    detail?: string;
    source?: string | null;
    source_grade?: string;
    fetched_at?: string | null;
    freshness?: 'fresh' | 'recent' | 'stale' | 'unknown' | string;
    confidence?: 'high' | 'medium' | 'low' | string;
}

export interface MiroFishFearIndex {
    schema_version?: string;
    generated_at?: string;
    score?: number | null;
    level?: 'extreme_fear' | 'fear' | 'neutral' | 'low_fear' | 'complacent' | 'unknown' | string;
    level_label?: string;
    tone?: 'danger' | 'warning' | 'neutral' | 'calm' | 'risk' | 'unknown' | string;
    confidence?: 'high' | 'medium' | 'low' | string;
    coverage_pct?: number | null;
    summary?: string;
    components?: MiroFishFearIndexComponent[];
    dashboard?: {
        display_score?: string;
        display_label?: string;
        color?: string;
        primary_driver?: string | null;
        primary_detail?: string | null;
    };
    source_packet?: Record<string, any>;
    non_goals?: string[];
}

export interface MiroFishOutcomeHorizon {
    horizon_days?: number;
    exit_date?: string;
    exit_price?: number;
    return_pct?: number;
}

export interface MiroFishOutcomeItem {
    symbol?: string;
    name?: string;
    rank?: number;
    status?: string;
    reason?: string;
    entry_date?: string;
    entry_price?: number;
    available_future_days?: number;
    primary_horizon_days?: number;
    forward_return_pct?: number | null;
    max_forward_return_pct?: number;
    max_drawdown_pct?: number;
    hit?: boolean | null;
    stopped?: boolean;
    lookahead_safe?: boolean;
    horizons?: Record<string, MiroFishOutcomeHorizon>;
}

export interface MiroFishOutcomeSummary {
    status?: string;
    evaluated_count?: number;
    pending_count?: number;
    hit_count?: number;
    miss_count?: number;
    hit_rate_pct?: number | null;
    top3_evaluated_count?: number;
    top3_hit_count?: number;
    top3_hit_rate_pct?: number | null;
    average_forward_return_pct?: number | null;
    best_symbol?: string | null;
    best_return_pct?: number | null;
    worst_symbol?: string | null;
    worst_return_pct?: number | null;
    lookahead_safe?: boolean;
}

export interface MiroFishWorkflowOutcomes {
    workflow_id?: string;
    status?: string;
    generated_at?: string;
    lookahead_safe?: boolean;
    method?: string;
    horizons?: number[];
    target_return_pct?: number;
    stop_loss_pct?: number;
    price_history?: Record<string, any>;
    items?: MiroFishOutcomeItem[];
    summary?: MiroFishOutcomeSummary;
}

export interface MiroFishScannerRun {
    id: string;
    status: string;
    market?: string;
    horizon?: string;
    strategy?: string;
    risk_profile?: string;
    limit?: number;
    created_at?: string;
    generated_at?: string;
    updated_at?: string;
    last_run_at?: string;
    next_scheduled_at?: string;
    freshness_status?: string;
    candidate_count?: number;
    screened_count?: number;
    rejected_candidate_count?: number;
    source_files?: MiroFishScannerSourceFile[];
    freshness?: Record<string, any>;
    scoring_schema?: Record<string, any>;
    providers?: Record<string, any>;
    candidates?: MiroFishAlphaCandidate[];
    analysis_artifacts?: Record<string, string>;
    performance_advisory?: {
        available?: boolean;
        applied_to_scoring?: boolean;
        source?: string;
        lookahead_safe?: boolean;
        evaluated_count?: number;
        workflow_count_scanned?: number;
        hit_rate_recent?: number | null;
        horizon_days?: number | null;
        recommendations?: Record<string, any>;
        asof?: string;
        note?: string;
        error?: string;
    };
    summary?: Record<string, any>;
    error?: string;
}

export interface MiroFishScannerStatus {
    enabled?: boolean;
    timezone?: string;
    scheduled_times?: string[];
    next_scheduled_times?: string[];
    next_scheduled_at?: string | null;
    last_run_id?: string | null;
    last_run_at?: string | null;
    scheduler_last_run_at?: string | null;
    freshness?: Record<string, any>;
    freshness_status?: string;
    source_files?: MiroFishScannerSourceFile[];
    candidate_count?: number;
    checked_at?: string;
    providers?: Record<string, any>;
}

export interface MiroFishScannerDiagnostics {
    ok?: boolean;
    health?: 'ok' | 'warning' | 'error' | string;
    checked_at?: string;
    schedule?: MiroFishScannerStatus;
    source?: Record<string, any>;
    monitor?: Record<string, any>;
    alert?: Record<string, any>;
    latest_run?: Partial<MiroFishScannerRun> | null;
    telegram?: Record<string, any>;
    deepseek?: Record<string, any>;
    issues?: Array<{ severity?: string; code?: string; message?: string }>;
}

export interface MiroFishScannerCandidatesResponse {
    run_id?: string;
    status?: string;
    candidates: MiroFishAlphaCandidate[];
}

export interface MiroFishDeepSeekStatus {
    provider?: string;
    configured?: boolean;
    base_url?: string;
    default_model?: string;
    recommended_models?: string[];
    supported_endpoints?: Record<string, string>;
    project_usage?: Record<string, string>;
    models?: { data?: Array<{ id?: string; owned_by?: string }> };
    balance?: { is_available?: boolean; balance_infos?: Array<Record<string, unknown>> };
    checked_at?: string;
}

export interface MiroFishTradingViewStatus {
    provider?: string;
    mode?: string;
    enabled?: boolean;
    configured?: boolean;
    mcp_url_configured?: boolean;
    credentials_present?: boolean;
    cache_path?: string;
    cache_available?: boolean;
    cache_ttl_sec?: number;
    score_weight?: number;
    live_checked?: boolean;
    healthy?: boolean | null;
    error?: string;
    checked_at?: string;
}

export interface MiroFishDeepSeekSummaryCandidate {
    rank?: number;
    symbol?: string;
    display_name?: string;
    market?: string;
    action_ko?: string;
    thesis_ko?: string;
    risk_ko?: string;
    next_check_ko?: string;
}

export interface MiroFishDeepSeekSummaryResult {
    provider?: string;
    model?: string;
    run_id?: string;
    candidate_count?: number;
    thinking?: boolean;
    summary?: {
        summary_title_ko?: string;
        portfolio_note_ko?: string;
        candidates?: MiroFishDeepSeekSummaryCandidate[];
    };
    usage?: Record<string, unknown>;
    finish_reason?: string;
    created_at?: string;
}

export interface MiroFishDeepSeekScannerSummaryResponse {
    run: MiroFishScannerRun;
    summary: MiroFishDeepSeekSummaryResult;
    links?: Record<string, string>;
}

export interface MiroFishDeepSeekTelegramResponse {
    ok?: boolean;
    run_id?: string;
    provider?: string;
    message_source?: string;
    fallback_reason?: string | null;
    message_chars?: number;
    summary?: MiroFishDeepSeekSummaryResult;
}

export interface MiroFishWorkflowAnalysisResult {
    candidate?: Partial<MiroFishAlphaCandidate>;
    status?: string;
    run_id?: string;
    target?: string;
    symbol?: string;
    market?: string;
    verdict?: {
        action?: string;
        confidence_pct?: number;
        bullish?: number;
        neutral?: number;
        bearish?: number;
        target?: string;
        summary?: string;
        // ── Phase C (P0 #4): 종목 식별 + 분석 기준일 ──
        symbol?: string;
        market?: string;
        reference_date?: string | null;
        target_display?: string;
    };
    graph?: Record<string, any>;
    brain?: Record<string, any>;
    // ── Phase C: per-top3 GraphRAG mini-dict ──
    graphrag?: {
        links?: number;
        entities?: number;
        relations?: number;
        method?: string;
    };
    final_score?: number;
    score_formula_version?: string;
    score_breakdown?: {
        version?: string;
        score?: number;
        inputs?: Record<string, any>;
        weights?: Record<string, number>;
        components?: Record<string, number>;
    };
    forward_return_pct?: number | null;
    outcome_status?: string;
    hit?: boolean | null;
    outcome?: MiroFishOutcomeItem;
    reason?: string;
    artifacts?: Record<string, string>;
    tradingagents?: {
        verdict?: string | null;
        confidence?: number | null;
        bull_case?: string | null;
        bear_case?: string | null;
        risk_summary?: string | null;
        method?: string | null;
        provider_usage?: {
            providers?: Record<string, { calls?: number; successes?: number }>;
        } | null;
    } | null;
}

// ── Phase C: workflow-level GraphRAG summary ──
export interface MiroFishWorkflowGraphRAG {
    mode?: string;
    entity_count?: number;
    edge_count?: number;
    source_coverage?: {
        scanner?: string;
        kis?: string;
        tradingview?: string;
        dart?: string;
        news?: string;
        deepseek?: string;
        [key: string]: string | undefined;
    };
    source_details?: Record<string, {
        status?: string;
        freshness?: string;
        required_for_alpha?: boolean;
        [key: string]: any;
    }>;
}

export interface MiroFishWorkflowSourceFreshness {
    status?: 'fresh' | 'partial' | 'stale' | string;
    last_update?: string | null;
    data_age_hours?: number | null;
    sources?: {
        scanner_freshness?: string;
        stale_files?: string[] | number;
        available_files?: string[] | number;
        missing_required_files?: string[] | number;
        kis_freshness?: string;
        tradingview_freshness?: string;
        dart_freshness?: string;
        news_freshness?: string;
        deepseek_freshness?: string;
        [key: string]: any;
    };
}

export interface MiroFishWorkflow {
    ok?: boolean;
    id?: string;
    status?: string;
    type?: string;
    created_at?: string;
    completed_at?: string;
    scanner_run_id?: string;
    scanner_freshness?: Record<string, any>;
    scanner_candidate_count?: number;
    event_count?: number;
    candidate_count?: number;
    analyzed_count?: number;
    candidates?: Partial<MiroFishAlphaCandidate>[];
    analysis_runs?: MiroFishWorkflowAnalysisResult[];
    top3?: MiroFishWorkflowAnalysisResult[];
    summary?: Record<string, any>;
    outcome_status?: string;
    outcome_summary?: MiroFishOutcomeSummary;
    outcomes?: MiroFishWorkflowOutcomes;
    progress?: Record<string, any>;
    filters?: Record<string, any>;
    blocked_reason?: string | null;
    alert_blocked?: boolean;
    links?: Record<string, string>;
    // ── Phase C: workflow-level GraphRAG + source freshness ──
    graphrag?: MiroFishWorkflowGraphRAG;
    source_freshness?: MiroFishWorkflowSourceFreshness;
}

export interface MiroFishWorkflowStatus {
    service?: string;
    ready?: boolean;
    mode?: string;
    latest_workflow?: MiroFishWorkflow | null;
    checked_at?: string;
}

// ── Phase A/B/D: GraphRAG subsystem ──────────────────────────────────

export interface MiroFishGraphRAGPhase {
    A_skeleton?: boolean;
    B_resolver?: boolean;
    C_workflow_enrichment?: boolean;
    D_ui?: boolean;
    E_mcp?: boolean;
    F_eval?: boolean;
}

export interface MiroFishGraphRAGEndpointsLive {
    status?: boolean;
    entities_resolve?: boolean;
    entities_get?: boolean;
    [key: string]: boolean | undefined;
}

export interface MiroFishGraphRAGStoragePath {
    path?: string;
    exists?: boolean;
    is_dir?: boolean;
    size_bytes?: number;
}

export interface MiroFishGraphRAGEntities {
    present?: boolean;
    entity_count?: number;
    alias_count?: number;
    external_id_count?: number;
    error?: string;
}

export interface MiroFishGraphRAGFlags {
    shadow_mode?: boolean;
    devil_advocate_enabled?: boolean;
    multi_ai_include_grok?: boolean;
    gdelt_enabled?: boolean;
    cache_ttl_sec?: number;
    vector_backend?: string;
    embedding_model?: string;
    keys_present?: Record<string, boolean>;
}

export interface MiroFishGraphRAGStatus {
    service?: string;
    state: 'not_initialized' | 'degraded' | 'ready' | 'error' | string;
    ready: boolean;
    phase: MiroFishGraphRAGPhase;
    endpoints_live: MiroFishGraphRAGEndpointsLive;
    storage: Record<string, MiroFishGraphRAGStoragePath>;
    entities: MiroFishGraphRAGEntities;
    flags: MiroFishGraphRAGFlags;
    mcp?: {
        state?: string;
        module_available?: boolean;
        registered?: boolean;
        tool_count?: number;
        error?: string | null;
        recorded_at?: string;
    };
    base_dir?: string;
    data_dir?: string;
    asof?: string;
    error?: string;
}

export type MiroFishGraphRAGMatchReason =
    | 'ticker_direct'
    | 'yahoo_ticker'
    | 'corp_code_reverse'
    | 'exact_alias'
    | 'exact_name'
    | 'chosung_exact'
    | 'chosung_prefix'
    | 'prefix_name'
    | 'fuzzy'
    | string;

export interface MiroFishGraphRAGEntityIds {
    ticker_kr?: string | null;
    yahoo_ticker?: string | null;
    corp_code?: string | null;
    figi?: string | null;
    isin?: string | null;
    [key: string]: string | null | undefined;
}

export interface MiroFishGraphRAGEntityMatch {
    entity_id: string;
    type?: string;
    name: string;
    name_ko?: string | null;
    name_en?: string | null;
    symbol: string | null;
    market: string | null;
    exchange?: string | null;
    country?: string | null;
    confidence: number;
    match_reason: MiroFishGraphRAGMatchReason;
    ids?: MiroFishGraphRAGEntityIds;
}

export interface MiroFishGraphRAGResolveResponse {
    query: string;
    normalized?: string;
    matches: MiroFishGraphRAGEntityMatch[];
    asof?: string;
    source?: string;
    error?: string;
}

export interface MiroFishGraphRAGEntityDetail extends MiroFishGraphRAGEntityMatch {
    aliases?: Array<{
        alias: string;
        lang?: string;
        source?: string;
        confidence?: number;
    }>;
    [key: string]: any;
}

// ── Phase G: scan history + performance ─────────────────────────────

export interface MiroFishScanHistoryOutcome {
    hit_count: number;
    miss_count: number;
    pending_count: number;
    neutral_count: number;
    evaluated_count: number;
    hit_rate: number | null;
    avg_forward_return_pct: number | null;
    best_return_pct: number | null;
    worst_return_pct: number | null;
}

export interface MiroFishScanHistoryItem {
    symbol: string;
    display_name: string;
    market: string;
    scan_count: number;
    scan_first_date: string;
    scan_last_date: string;
    alpha_avg: number;
    alpha_max: number;
    alpha_min: number;
    risk_avg: number;
    strategy_tags: string[];
    workflow_count: number;
    verdict_actions: Record<string, number>;
    outcome: MiroFishScanHistoryOutcome;
    last_target_display?: string | null;
}

export interface MiroFishScanHistorySummary {
    evaluated_count: number;
    hit_count: number;
    miss_count: number;
    hit_rate: number | null;
    avg_return_pct: number | null;
}

export interface MiroFishScanHistoryResponse {
    window_days: number;
    min_alpha: number;
    generated_at: string;
    total_unique_symbols: number;
    total_scans: number;
    total_workflows: number;
    returned_items: number;
    items: MiroFishScanHistoryItem[];
    summary: MiroFishScanHistorySummary;
    lookahead_safe?: boolean;
}

export interface MiroFishScanHistoryScanEntry {
    date: string;
    scanner_run_id: string;
    run_date?: string;
    rank?: number | null;
    symbol: string;
    display_name: string;
    market: string;
    alpha_score: number;
    risk_score: number;
    ranking_score: number;
    action: string;
    signal_quality?: string;
    strategy_tags: string[];
}

export interface MiroFishScanHistoryWorkflowOutcome {
    status: string;
    hit: boolean | null;
    forward_return_pct: number | null;
    entry_date?: string | null;
    primary_horizon_days?: number | null;
    max_forward_return_pct?: number | null;
    max_drawdown_pct?: number | null;
    stopped?: boolean | null;
}

export interface MiroFishScanHistoryWorkflowEntry {
    date: string;
    workflow_id: string;
    symbol: string;
    display_name: string;
    market: string;
    rank?: number | null;
    final_score: number;
    verdict: {
        action: string;
        confidence_pct: number;
        target_display: string;
    };
    outcome: MiroFishScanHistoryWorkflowOutcome;
}

export interface MiroFishSymbolHistoryResponse {
    symbol: string;
    display_name: string;
    market: string;
    window_days: number;
    scans: MiroFishScanHistoryScanEntry[];
    workflows: MiroFishScanHistoryWorkflowEntry[];
    aggregate: {
        total_scans: number;
        total_workflows: number;
        evaluated_count: number;
        hit_count: number;
        outcome_hit_rate: number | null;
        avg_forward_return_pct: number | null;
    };
    generated_at: string;
    lookahead_safe?: boolean;
    error?: string;
}

export interface MiroFishScanPerformanceGroupStat {
    n: number;
    hit_rate: number | null;
    avg_return_pct: number | null;
}

export interface MiroFishScanPerformanceTopPerformer {
    symbol: string;
    display_name: string;
    market: string;
    n: number;
    hit_rate: number;
    avg_return_pct: number;
}

export interface MiroFishScanPerformanceResponse {
    service?: string;
    window_days: number;
    generated_at: string;
    total_signals: number;
    evaluated: number;
    pending: number;
    hit_count: number;
    miss_count: number;
    hit_rate: number | null;
    avg_return_pct: number | null;
    ic_signal_to_return: number | null;
    workflow_count_scanned: number;
    scanner_runs_scanned: number;
    by_market: Record<string, MiroFishScanPerformanceGroupStat>;
    by_strategy_tag: Record<string, MiroFishScanPerformanceGroupStat>;
    by_verdict_action: Record<string, MiroFishScanPerformanceGroupStat>;
    by_alpha_bucket: Record<string, MiroFishScanPerformanceGroupStat>;
    top_performers: MiroFishScanPerformanceTopPerformer[];
    lookahead_safe?: boolean;
}

export interface MiroFishPriceChartPoint {
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
    change_rate?: number;
    update_time?: string;
}

export interface MiroFishPriceChartResponse {
    symbol: string;
    target?: string;
    source?: string;
    count: number;
    limit?: number;
    chart: MiroFishPriceChartPoint[];
    latest?: MiroFishPriceChartPoint | null;
}

export interface MiroFishAutonomousLearningFeedback {
    available?: boolean;
    service?: string;
    generated_at?: string;
    mode?: string;
    production_weights_mutated?: boolean;
    lookahead_safe?: boolean;
    workflow_count?: number;
    item_count?: number;
    evaluated_count?: number;
    hit_count?: number;
    miss_count?: number;
    hit_rate_pct?: number | null;
    average_forward_return_pct?: number | null;
    recommendation_count?: number;
    alpha_memory?: {
        available?: boolean;
        sample_count?: number;
        strongest_positive?: Record<string, any> | null;
        weakest_negative?: Record<string, any> | null;
        score_profile?: Record<string, any>;
        cohorts?: Record<string, any[]>;
        guidance?: Array<Record<string, any>>;
    };
    recommendations?: Array<Record<string, any>>;
    errors?: Array<Record<string, any>>;
}

export interface MiroFishLearningReadiness {
    schema_version?: string;
    service?: string;
    generated_at?: string;
    ready?: boolean;
    learning_active?: boolean;
    status?: string;
    mode?: string;
    primary_objective?: string;
    lookahead_safe?: boolean;
    production_weights_mutated?: boolean;
    blockers?: string[];
    outcome_memory?: Record<string, any>;
    backtest_gate?: Record<string, any>;
    score_control?: Record<string, any>;
    learning_guard?: Record<string, any>;
    top3_metrics?: Record<string, any>;
    links?: Record<string, string>;
}

export interface MiroFishAutonomousStatus {
    service?: string;
    ready?: boolean;
    mode?: string;
    mutation_enabled?: boolean;
    shared_secret_configured?: boolean;
    send_confirmation_phrase?: string;
    telegram?: {
        personal_configured?: boolean;
        channel_configured?: boolean;
        personal_chat_present?: boolean;
        channel_chat_present?: boolean;
    };
    scanner?: Record<string, any>;
    workflow?: MiroFishWorkflowStatus | Record<string, any>;
    learning?: MiroFishAutonomousLearningFeedback;
    runtime?: {
        mcp_server?: {
            url?: string;
            healthy?: boolean;
            status_code?: number | null;
            server_name?: string | null;
            server_version?: string | null;
            error?: string | null;
            checked_at?: string;
        };
        startup_task?: {
            task_name?: string;
            registered?: boolean;
            query_ok?: boolean;
            platform?: string;
            state?: string | null;
            next_run_time?: string | null;
            last_run_time?: string | null;
            last_result?: string | null;
            error?: string | null;
            checked_at?: string;
        };
        watchdog_task?: {
            task_name?: string;
            registered?: boolean;
            query_ok?: boolean;
            platform?: string;
            state?: string | null;
            next_run_time?: string | null;
            last_run_time?: string | null;
            last_result?: string | null;
            error?: string | null;
            checked_at?: string;
        };
    };
    tools?: string[];
    resources?: string[];
    checked_at?: string;
}

export interface MiroFishAutonomousActionResult {
    ok?: boolean;
    status?: string;
    dry_run?: boolean;
    run_id?: string;
    workflow_id?: string;
    scanner_run_id?: string;
    candidate_count?: number;
    new_event_count?: number;
    event_count?: number;
    analysis_count?: number;
    top_count?: number;
    top_symbols?: string[];
    top_names?: string[];
    telegram_sent?: boolean;
    telegram_sent_at?: string | null;
    telegram_skipped_reason?: string;
    state_committed?: boolean;
    event_state_committed?: boolean;
    alert_blocked?: boolean;
    blocked_reason?: string | null;
    message_chars?: number;
    outcome_status?: string;
    learning_feedback?: MiroFishAutonomousLearningFeedback;
    resource_links?: Record<string, string>;
    events?: Array<{
        key?: string;
        symbol?: string;
        name?: string;
        market?: string;
        alpha_score?: number;
        risk_score?: number;
        action?: string;
    }>;
}

export interface MiroFishMcpRequirementStatus {
    id?: string;
    label?: string;
    required_for_top3?: boolean;
    status?: string;
    evidence_hits?: string[];
    recommended_resource_ids?: string[];
}

export interface MiroFishAlphaEndpointContract {
    id: string;
    priority: 'P0' | 'P1' | 'P2' | 'P3' | string;
    name: string;
    http_method?: string;
    internal_path?: string;
    mcp_tool?: string;
    current_status?: string;
    source_grade?: string;
    alpha_impact?: string;
    pipeline_position?: string;
    requirements?: MiroFishMcpRequirementStatus[];
    resources?: Array<Record<string, any>>;
    risk_controls?: string[];
    read_only_required?: boolean;
    orders_blocked?: boolean;
}

export interface MiroFishAlphaEndpointBlueprint {
    schema_version?: string;
    objective?: string;
    generated_at?: string;
    scanner_run_id?: string | null;
    workflow_id?: string | null;
    source_readiness?: {
        status?: string;
        required_total?: number;
        required_covered?: number;
        required_partial?: number;
        required_missing?: number;
        summary?: string;
    };
    endpoint_count?: number;
    p0_count?: number;
    endpoints: MiroFishAlphaEndpointContract[];
    next_actions?: Array<Record<string, any>>;
    non_goals?: string[];
}

export interface MiroFishMcpResourceSnapshot {
    schema_version?: string;
    mode?: string;
    generated_at?: string;
    catalog_count?: number;
    catalog?: Array<Record<string, any>>;
    source_gaps?: Record<string, any>;
    adoption_plan?: Record<string, any>;
    alpha_endpoint_blueprint?: MiroFishAlphaEndpointBlueprint;
    rules?: Record<string, any>;
}

export interface RunTradingAgentsResult {
    id: string;
    method?: string;
    verdict: {
        verdict: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | string;
        confidence: number;
        strong_buy: boolean;
        regime?: string;
        regime_adjustment?: { direction: string; alignment: number | null; applied: number };
        bull_case?: string;
        bear_case?: string;
        risk_summary?: string;
    };
}

type RawObject = Record<string, any>;

const phaseByName: Record<string, number> = {
    intake: 1,
    brain_snapshot: 2,
    graph_build: 3,
    analyst_mesh: 4,
    verdict: 5,
    report: 5,
};

const toneByPhase: Record<number, string> = {
    1: 'text-blue-300',
    2: 'text-cyan-300',
    3: 'text-teal-400',
    4: 'text-violet-400',
    5: 'text-emerald-400',
};

const analystIcons = [
    'fa-compass',
    'fa-water',
    'fa-shield-halved',
    'fa-bolt',
    'fa-globe-asia',
    'fa-chart-line',
    'fa-coins',
    'fa-link',
    'fa-clipboard-check',
    'fa-clock',
];

function asObject(value: unknown): RawObject {
    return value && typeof value === 'object' ? value as RawObject : {};
}

function asNumber(value: unknown, fallback = 0): number {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
}

function asPercent(value: unknown, fallback = 0): number {
    const numberValue = asNumber(value, fallback);
    if (numberValue > 0 && numberValue <= 1) return Math.round(numberValue * 100);
    return Math.round(numberValue);
}

function asStringArray(value: unknown): string[] {
    if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
    if (typeof value === 'string' && value.trim()) return [value.trim()];
    return [];
}

function normalizeAlphaEvidence(rawValue: unknown): MiroFishAlphaEvidence[] {
    if (Array.isArray(rawValue)) {
        return rawValue.map((item) => {
            if (typeof item === 'string') {
                return { source: 'alpha_scanner', field: item };
            }
            const raw = asObject(item);
            return {
                source: raw.source === undefined ? undefined : String(raw.source),
                field: raw.field === undefined ? undefined : String(raw.field),
                score: raw.score === undefined ? undefined : asNumber(raw.score, 0),
                value: raw.value,
                confidence: raw.confidence === undefined ? undefined : asNumber(raw.confidence, 0),
            };
        });
    }
    if (typeof rawValue === 'string' && rawValue.trim()) {
        return [{ source: 'alpha_scanner', field: rawValue.trim() }];
    }
    return [];
}

function normalizeScannerSourceFiles(rawValue: unknown): MiroFishScannerSourceFile[] {
    if (!Array.isArray(rawValue)) return [];
    return rawValue.map((item) => {
        if (typeof item === 'string') return { file: item, exists: true };
        const raw = asObject(item);
        return {
            file: raw.file === undefined ? undefined : String(raw.file),
            exists: raw.exists === undefined ? undefined : Boolean(raw.exists),
            generated_at: raw.generated_at === undefined ? undefined : raw.generated_at === null ? null : String(raw.generated_at),
            modified_at: raw.modified_at === undefined ? undefined : raw.modified_at === null ? null : String(raw.modified_at),
            freshness: raw.freshness === undefined ? undefined : String(raw.freshness),
        };
    });
}

function normalizePhase(value: unknown, fallback = 1): number {
    if (typeof value === 'number') return value;
    const key = String(value || '').toLowerCase();
    return phaseByName[key] ?? fallback;
}

function normalizeBrain(rawValue: unknown): MiroFishRun['brain'] {
    const raw = asObject(rawValue);
    return {
        score: asPercent(raw.score ?? raw.alignment_score, 50),
        regime: String(raw.regime ?? 'neutral').replace(/_/g, ' '),
        crisis: String(raw.crisis ?? raw.crisis_level ?? 'Lv.2'),
    };
}

function normalizePipeline(rawValue: unknown, statusValue?: unknown): MiroFishStatus['pipeline'] {
    const raw = asObject(rawValue);
    return {
        graph_links: asNumber(raw.graph_links ?? raw.links, 0),
        similar_events: asNumber(raw.similar_events ?? raw.events, 0),
        agent_count: asNumber(raw.agent_count ?? raw.max_agent_count, 0),
        status: String(raw.status ?? statusValue ?? 'ready'),
    };
}

function normalizeAnalyst(rawValue: unknown, index: number): MiroFishAnalyst {
    const raw = asObject(rawValue);
    const stance = String(raw.verdict ?? raw.stance ?? 'NEUTRAL').toUpperCase();
    const verdict: MiroFishVerdict = stance === 'BUY'
        ? 'BULLISH'
        : stance === 'SELL'
            ? 'BEARISH'
            : stance === 'HOLD'
                ? 'NEUTRAL'
                : stance as MiroFishVerdict;

    return {
        name: String(raw.name ?? raw.id ?? `Agent ${index + 1}`),
        role: String(raw.role ?? raw.note ?? 'MiroFish analyst'),
        verdict,
        confidence: asPercent(raw.confidence, 60),
        icon: String(raw.icon ?? analystIcons[index % analystIcons.length] ?? 'fa-user-tie'),
    };
}

function normalizeAnalysts(rawValue: unknown): MiroFishAnalyst[] {
    return Array.isArray(rawValue) ? rawValue.map(normalizeAnalyst) : [];
}

function normalizeLog(rawValue: unknown, index: number): MiroFishLog {
    const raw = asObject(rawValue);
    const phase = normalizePhase(raw.phase, Math.min(5, index + 1));
    return {
        phase,
        time: String(raw.time ?? raw.timestamp ?? raw.created_at ?? 'live'),
        text: String(raw.text ?? raw.message ?? raw.event ?? 'MiroFish event'),
        tone: String(raw.tone ?? toneByPhase[phase] ?? 'text-blue-300'),
    };
}

function normalizeLogs(rawValue: unknown): MiroFishLog[] {
    return Array.isArray(rawValue) ? rawValue.map(normalizeLog) : [];
}

function normalizeNode(rawValue: unknown): MiroFishNode {
    const raw = asObject(rawValue);
    return {
        label: String(raw.label ?? raw.name ?? raw.id ?? 'node'),
        x: raw.x === undefined ? undefined : asNumber(raw.x),
        y: raw.y === undefined ? undefined : asNumber(raw.y),
        kind: raw.kind,
        verdict: raw.verdict,
    };
}

function normalizeNodes(rawValue: unknown): MiroFishNode[] | undefined {
    if (!Array.isArray(rawValue)) return undefined;
    return rawValue.map(normalizeNode);
}

function normalizeVerdict(rawValue: unknown, analysts: MiroFishAnalyst[]): MiroFishRun['verdict'] {
    const raw = asObject(rawValue);
    if (Object.keys(raw).length === 0 && analysts.length === 0) return undefined;
    const label = String(raw.label ?? raw.action ?? 'HOLD').toUpperCase() as MiroFishVerdict;
    const bullish = raw.bullish ?? analysts.filter((analyst) => String(analyst.verdict).includes('BULL')).length;
    const bearish = raw.bearish ?? analysts.filter((analyst) => String(analyst.verdict).includes('BEAR')).length;
    const neutral = raw.neutral ?? analysts.filter((analyst) => String(analyst.verdict).includes('NEUT') || analyst.verdict === 'HOLD').length;

    return {
        label,
        target: raw.target === undefined ? undefined : String(raw.target),
        confidence: asPercent(raw.confidence ?? raw.confidence_pct, 50),
        bullish: asNumber(bullish, 3),
        bearish: asNumber(bearish, 0),
        neutral: asNumber(neutral, 4),
        horizon: String(raw.horizon ?? raw.time_horizon ?? '1M').toUpperCase(),
        summary: String(raw.summary ?? `${bullish} analysts bullish, ${bearish} bearish, ${neutral} neutral.`),
    };
}

function normalizeLayers(
    rawValue: unknown,
    analysts: MiroFishAnalyst[],
    verdict?: MiroFishRun['verdict'],
    graphNodeCount = 0,
    predictionNodeCount = 0,
): MiroFishLayer[] {
    if (Array.isArray(rawValue) && rawValue.length > 0) {
        return rawValue.map((layer) => {
            const raw = asObject(layer);
            return {
                label: String(raw.label ?? raw.name ?? 'LAYER').toUpperCase(),
                count: asNumber(raw.count, 0),
                color: raw.color,
            };
        });
    }

    return [
        { label: 'TARGET', count: 1 },
        { label: 'CAUSAL HISTORY', count: graphNodeCount },
        { label: 'AI ANALYSTS', count: analysts.length },
        { label: 'PREDICTIONS', count: predictionNodeCount },
        { label: 'VERDICT', count: verdict ? 1 : 0 },
    ];
}

function normalizePredictionNodes(rawValue: unknown, analysts: MiroFishAnalyst[]): MiroFishNode[] | undefined {
    const nodes = normalizeNodes(rawValue);
    if (nodes?.length) return nodes;
    if (!analysts.length) return undefined;

    const xs = [40, 35, 43, 56, 70, 75, 81, 30, 50, 67];
    return analysts.slice(0, 10).map((analyst, index) => {
        const verdict = String(analyst.verdict || '').toLowerCase();
        return {
            label: `${analyst.name} ${analyst.verdict || 'NEUTRAL'}`,
            x: xs[index] ?? 50,
            y: 65 + ((index % 4) * 3),
            verdict: verdict.includes('bull') ? 'bull' : verdict.includes('bear') ? 'bear' : 'neutral',
        };
    });
}

const graphCoords = [
    [35, 42], [42, 38], [50, 40], [58, 37], [66, 43], [72, 48],
    [62, 54], [53, 57], [44, 55], [36, 59], [29, 50], [77, 56],
    [69, 62], [48, 64], [40, 68], [57, 48], [73, 38], [31, 66],
];

function normalizeGraph(payload: any): MiroFishGraphArtifact {
    const raw = asObject(payload);
    return {
        ...raw,
        run_id: raw.run_id,
        target: raw.target,
        source: raw.source,
        schema_version: asNumber(raw.schema_version, 1),
        nodes: Array.isArray(raw.nodes) ? raw.nodes.map((node) => asObject(node) as MiroFishGraphNode) : [],
        edges: Array.isArray(raw.edges) ? raw.edges.map((edge) => asObject(edge) as MiroFishGraphEdge) : [],
        layers: Array.isArray(raw.layers) ? raw.layers.map((layer) => asObject(layer)) : [],
    };
}

function nodesFromGraphArtifact(graph?: MiroFishGraphArtifact): MiroFishNode[] {
    if (!graph?.nodes?.length) return [];
    return graph.nodes
        .filter((node) => {
            const type = String(node.type || '').toLowerCase();
            return !['target', 'brain', 'verdict', 'analyst'].includes(type);
        })
        .slice(0, 24)
        .map((node, index) => {
            const coord = graphCoords[index % graphCoords.length] ?? [50, 50];
            const yOffset = index >= graphCoords.length ? 8 : 0;
            return {
                label: String(node.label || node.id || 'node'),
                x: coord[0],
                y: Math.min(74, coord[1] + yOffset),
                kind: 'history',
            };
        });
}

function normalizeReport(payload: any): MiroFishReport {
    const raw = asObject(payload);
    return {
        run_id: raw.run_id,
        format: String(raw.format || 'markdown'),
        markdown: String(raw.markdown || ''),
    };
}

function normalizeEvent(rawValue: unknown): MiroFishEvent {
    const raw = asObject(rawValue);
    return {
        ts: raw.ts ? String(raw.ts) : undefined,
        level: raw.level ? String(raw.level) : undefined,
        phase: raw.phase ? String(raw.phase) : undefined,
        message: raw.message ? String(raw.message) : undefined,
        payload: asObject(raw.payload),
    };
}

function normalizeEvents(payload: any): MiroFishEventsResponse {
    const raw = asObject(payload);
    return {
        run_id: raw.run_id,
        events: Array.isArray(raw.events) ? raw.events.map(normalizeEvent) : [],
        next_index: asNumber(raw.next_index, 0),
        total: asNumber(raw.total, 0),
        has_more: Boolean(raw.has_more),
    };
}

function timeFromEvent(event: MiroFishEvent): string {
    const payloadTime = event.payload?.time;
    if (payloadTime) return String(payloadTime);
    if (!event.ts) return 'live';
    const parsed = new Date(event.ts);
    return Number.isNaN(parsed.getTime()) ? String(event.ts) : parsed.toLocaleTimeString('ko-KR', { hour12: false });
}

function logFromEvent(event: MiroFishEvent, index: number): MiroFishLog {
    const phase = normalizePhase(event.phase, Math.min(5, index + 1));
    return {
        phase,
        time: timeFromEvent(event),
        text: String(event.payload?.text || event.message || 'MiroFish event'),
        tone: toneByPhase[phase] || 'text-blue-300',
    };
}

export function attachMiroFishArtifacts(
    run: MiroFishRun,
    graph?: MiroFishGraphArtifact,
    report?: MiroFishReport,
    events?: MiroFishEventsResponse,
): MiroFishRun {
    const graphNodes = nodesFromGraphArtifact(graph);
    const eventLogs = events?.events?.length ? events.events.map(logFromEvent) : undefined;
    return {
        ...run,
        graph_artifact: graph || run.graph_artifact,
        report: report || run.report,
        events: events?.events || run.events,
        graph_nodes: graphNodes.length ? graphNodes : run.graph_nodes,
        logs: eventLogs?.length ? eventLogs : run.logs,
    };
}

function normalizeStatus(payload: any): MiroFishStatus {
    const raw = asObject(payload);
    const limits = asObject(raw.limits);
    const pipeline = normalizePipeline(raw.pipeline ?? {
        graph_links: raw.graph_links,
        similar_events: raw.similar_events,
        agent_count: limits.max_agent_count,
        status: raw.mode ?? raw.service,
    }, raw.mode ?? raw.service);

    return {
        ready: Boolean(raw.ready),
        source: String(raw.source ?? raw.service ?? raw.mode ?? 'mirofish'),
        brain: normalizeBrain(raw.brain ?? raw.brain_summary),
        pipeline,
        updated_at: raw.updated_at,
    };
}

function unwrapRun(payload: any, target: string): MiroFishRun {
    const run = payload?.run ?? payload?.data ?? payload?.result ?? payload;
    const normalizedTarget = run?.target ?? run?.ticker ?? run?.symbol ?? target;
    const analysts = normalizeAnalysts(run?.analysts);
    const verdict = normalizeVerdict(run?.verdict, analysts);
    const pipeline = normalizePipeline(run?.pipeline, run?.status);
    const graphNodes = normalizeNodes(run?.graph_nodes);
    const predictionNodes = normalizePredictionNodes(run?.prediction_nodes, analysts);

    return {
        ...run,
        target: String(normalizedTarget),
        display_name: String(run?.display_name ?? run?.name ?? run?.target_name ?? normalizedTarget),
        price: run?.price ?? run?.current_price,
        change_pct: asNumber(run?.change_pct ?? run?.change_percent, 0),
        layers: normalizeLayers(run?.layers, analysts, verdict, graphNodes?.length ?? 0, predictionNodes?.length ?? 0),
        logs: normalizeLogs(run?.logs),
        analysts,
        graph_nodes: graphNodes,
        prediction_nodes: predictionNodes,
        verdict,
        brain: normalizeBrain(run?.brain ?? run?.brain_summary),
        pipeline,
    };
}

function normalizeAlphaCandidate(rawValue: unknown, index = 0): MiroFishAlphaCandidate {
    const raw = asObject(rawValue);
    const symbol = String(raw.symbol ?? raw.code ?? raw.ticker ?? '');
    const displayNameSource = raw.display_name ?? raw.name ?? raw.stock_name ?? symbol;
    const displayName = String(displayNameSource || 'Unknown');
    return {
        ...raw,
        rank: asNumber(raw.rank, index + 1),
        symbol,
        display_name: displayName,
        market: raw.market === undefined ? undefined : String(raw.market),
        alpha_score: asNumber(raw.alpha_score ?? raw.score ?? raw.total_score, 0),
        risk_score: asNumber(raw.risk_score ?? raw.risk ?? raw.risk_penalty, 0),
        ranking_score: asNumber(raw.ranking_score, 0),
        action: String(raw.action ?? raw.verdict ?? 'WATCH').toUpperCase(),
        horizon: String(raw.horizon ?? raw.expected_horizon ?? '20D').toUpperCase(),
        signal_quality: raw.signal_quality === undefined ? undefined : String(raw.signal_quality),
        strategy_tags: asStringArray(raw.strategy_tags ?? raw.strategies ?? raw.tags),
        evidence: normalizeAlphaEvidence(raw.evidence ?? raw.reasons ?? raw.reason),
        analysis_profile: asObject(raw.analysis_profile),
        entry_plan: asObject(raw.entry_plan),
        replay_context: asObject(raw.replay_context),
        risk_flags: asStringArray(raw.risk_flags ?? raw.risks),
        source: raw.source === undefined ? undefined : String(raw.source),
        generated_at: raw.generated_at === undefined ? undefined : String(raw.generated_at),
        freshness: asObject(raw.freshness),
        freshness_sec: raw.freshness_sec === undefined ? undefined : asNumber(raw.freshness_sec, 0),
        price: asObject(raw.price).current_price ?? raw.price ?? raw.current_price,
        change_pct: raw.change_pct === undefined
            ? asObject(raw.price).change_rate === undefined ? undefined : asNumber(asObject(raw.price).change_rate, 0)
            : asNumber(raw.change_pct, 0),
        trading_value: raw.trading_value === undefined
            ? asObject(raw.price).trading_value === undefined ? undefined : asNumber(asObject(raw.price).trading_value, 0)
            : asNumber(raw.trading_value, 0),
        score_breakdown: asObject(raw.score_breakdown ?? raw.breakdown),
        tradingview: asObject(raw.tradingview),
        crash_rebound_gate: asObject(raw.crash_rebound_gate) as MiroFishCrashReboundGate,
    };
}

function normalizeScannerRun(payload: any): MiroFishScannerRun {
    const raw = asObject(payload?.run ?? payload?.data ?? payload?.result ?? payload);
    const rawCandidates = Array.isArray(raw.candidates) ? raw.candidates : [];
    return {
        ...raw,
        id: String(raw.id ?? raw.run_id ?? ''),
        status: String(raw.status ?? 'completed'),
        market: raw.market === undefined ? undefined : String(raw.market),
        horizon: raw.horizon === undefined ? undefined : String(raw.horizon).toUpperCase(),
        strategy: raw.strategy === undefined ? undefined : String(raw.strategy),
        risk_profile: raw.risk_profile === undefined ? undefined : String(raw.risk_profile),
        limit: raw.limit === undefined ? undefined : asNumber(raw.limit, 20),
        created_at: raw.created_at === undefined ? undefined : String(raw.created_at),
        generated_at: raw.generated_at === undefined ? undefined : String(raw.generated_at),
        updated_at: raw.updated_at === undefined ? undefined : String(raw.updated_at),
        last_run_at: raw.last_run_at === undefined ? undefined : String(raw.last_run_at),
        next_scheduled_at: raw.next_scheduled_at === undefined ? undefined : String(raw.next_scheduled_at),
        freshness_status: raw.freshness_status === undefined ? asObject(raw.freshness).status : String(raw.freshness_status),
        candidate_count: asNumber(raw.candidate_count ?? rawCandidates.length, rawCandidates.length),
        screened_count: raw.screened_count === undefined ? undefined : asNumber(raw.screened_count, 0),
        rejected_candidate_count: raw.rejected_candidate_count === undefined ? undefined : asNumber(raw.rejected_candidate_count, 0),
        source_files: normalizeScannerSourceFiles(raw.source_files),
        freshness: asObject(raw.freshness),
        scoring_schema: asObject(raw.scoring_schema),
        providers: asObject(raw.providers),
        candidates: rawCandidates.map(normalizeAlphaCandidate),
        analysis_artifacts: asObject(raw.analysis_artifacts),
        performance_advisory: asObject(raw.performance_advisory) as MiroFishScannerRun['performance_advisory'],
        summary: asObject(raw.summary),
        error: raw.error === undefined ? undefined : String(raw.error),
    };
}

function normalizeScannerStatus(payload: any): MiroFishScannerStatus {
    const raw = asObject(payload);
    return {
        ...raw,
        enabled: raw.enabled === undefined ? undefined : Boolean(raw.enabled),
        timezone: raw.timezone === undefined ? undefined : String(raw.timezone),
        scheduled_times: asStringArray(raw.scheduled_times),
        next_scheduled_times: asStringArray(raw.next_scheduled_times),
        next_scheduled_at: raw.next_scheduled_at === undefined || raw.next_scheduled_at === null ? null : String(raw.next_scheduled_at),
        last_run_id: raw.last_run_id === undefined || raw.last_run_id === null ? null : String(raw.last_run_id),
        last_run_at: raw.last_run_at === undefined || raw.last_run_at === null ? null : String(raw.last_run_at),
        scheduler_last_run_at: raw.scheduler_last_run_at === undefined || raw.scheduler_last_run_at === null ? null : String(raw.scheduler_last_run_at),
        freshness: asObject(raw.freshness),
        freshness_status: raw.freshness_status === undefined ? asObject(raw.freshness).status : String(raw.freshness_status),
        source_files: normalizeScannerSourceFiles(raw.source_files),
        candidate_count: raw.candidate_count === undefined ? undefined : asNumber(raw.candidate_count, 0),
        checked_at: raw.checked_at === undefined ? undefined : String(raw.checked_at),
        providers: asObject(raw.providers),
    };
}

function normalizeScannerCandidates(payload: any): MiroFishScannerCandidatesResponse {
    const raw = asObject(payload);
    const rawCandidates = Array.isArray(raw.candidates)
        ? raw.candidates
        : Array.isArray(raw.results)
            ? raw.results
            : [];
    return {
        run_id: raw.run_id === undefined ? undefined : String(raw.run_id),
        status: raw.status === undefined ? undefined : String(raw.status),
        candidates: rawCandidates.map(normalizeAlphaCandidate),
    };
}

export const mirofishApi = {
    getStatus: async () => normalizeStatus(await fetchAuthAPI<any>('/api/admin/mirofish/status')),
    getDataSources: async () => fetchAuthAPI<any>('/api/admin/mirofish/data-sources'),
    searchTargets: async (target: string, limit = 16) => fetchAuthAPI<MiroFishTargetSearchResponse>(`/api/admin/mirofish/targets/search?target=${encodeURIComponent(target)}&limit=${limit}`),
    resolveTarget: async (target: string) => fetchAuthAPI<MiroFishTargetSnapshot>(`/api/admin/mirofish/targets/resolve?target=${encodeURIComponent(target)}`),
    listRuns: async () => {
        const payload = await fetchAuthAPI<any>('/api/admin/mirofish/runs');
        const runs = Array.isArray(payload?.runs) ? payload.runs.map((run: unknown) => unwrapRun(run, '')) : [];
        return { runs };
    },
    getRun: async (runId: string) => unwrapRun(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}`), ''),
    getGraph: async (runId: string) => normalizeGraph(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/graph`)),
    getReport: async (runId: string) => normalizeReport(await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/report`)),
    getEvents: async (runId: string, since = 0, limit = 200) => normalizeEvents(
        await fetchAuthAPI<any>(`/api/admin/mirofish/runs/${runId}/events?since=${since}&limit=${limit}`),
    ),
    runTradingAgentsForRun: async (runId: string) => postAuthAPI<RunTradingAgentsResult>(
        `/api/admin/mirofish/runs/${encodeURIComponent(runId)}/tradingagents`,
        {},
        undefined,
        120000,
    ),
    hydrateRun: async (runId: string, baseRun?: MiroFishRun) => {
        const [detail, graph, report, events] = await Promise.all([
            baseRun ? Promise.resolve(baseRun) : mirofishApi.getRun(runId),
            mirofishApi.getGraph(runId),
            mirofishApi.getReport(runId),
            mirofishApi.getEvents(runId),
        ]);
        return attachMiroFishArtifacts(detail, graph, report, events);
    },
    startRun: async (request: StartMiroFishRunRequest) => {
        // LLM 모드 create_run 은 백엔드에서 60-120초 소요 (Gemini 호출 + 파이프라인).
        // fast/rule 모드는 3초 내 완료. 양쪽 다 안전하게 180초 timeout.
        const payload = await postAuthAPI<any>('/api/admin/mirofish/runs', request, undefined, 180000);
        return unwrapRun(payload, request.target);
    },
    startScannerRun: async (request: MiroFishScannerRunRequest = {}) => normalizeScannerRun(
        await postAuthAPI<any>('/api/admin/mirofish/scanner/runs', request, undefined, 180000),
    ),
    getScannerStatus: async () => normalizeScannerStatus(
        await fetchAuthAPI<any>('/api/admin/mirofish/scanner/status'),
    ),
    getScannerDiagnostics: async () => fetchAuthAPI<MiroFishScannerDiagnostics>(
        '/api/admin/mirofish/scanner/diagnostics',
    ),
    getScannerAlertState: async (fresh = false) => fetchAuthAPI<MiroFishScannerAlertState>(
        `/api/admin/mirofish/scanner/alerts/state${fresh ? `?t=${Date.now()}` : ''}`,
    ),
    getScannerMonitorStatus: async (fresh = false) => fetchAuthAPI<MiroFishScannerMonitorState>(
        `/api/admin/mirofish/scanner/monitor/status${fresh ? `?t=${Date.now()}` : ''}`,
    ),
    getLatestScannerRun: async () => normalizeScannerRun(
        await fetchAuthAPI<any>('/api/admin/mirofish/scanner/runs/latest'),
    ),
    getScannerRun: async (runId: string) => normalizeScannerRun(
        await fetchAuthAPI<any>(`/api/admin/mirofish/scanner/runs/${runId}`),
    ),
    getScannerCandidates: async (runId: string) => normalizeScannerCandidates(
        await fetchAuthAPI<any>(`/api/admin/mirofish/scanner/runs/${runId}/candidates`),
    ),
    getScannerFeatureVectors: async (runId: string) => fetchAuthAPI<Record<string, any>>(
        `/api/admin/mirofish/scanner/runs/${encodeURIComponent(runId)}/feature-vectors`,
    ),
    getScannerEvidenceLedger: async (runId: string) => fetchAuthAPI<Record<string, any>>(
        `/api/admin/mirofish/scanner/runs/${encodeURIComponent(runId)}/evidence`,
    ),
    getScannerRejectedCandidates: async (runId: string) => fetchAuthAPI<Record<string, any>>(
        `/api/admin/mirofish/scanner/runs/${encodeURIComponent(runId)}/rejects`,
    ),
    getDeepSeekStatus: async (live = false) => fetchAuthAPI<MiroFishDeepSeekStatus>(
        `/api/admin/mirofish/deepseek/status${live ? '?live=1' : ''}`,
    ),
    getTradingViewStatus: async (live = false) => fetchAuthAPI<MiroFishTradingViewStatus>(
        `/api/admin/mirofish/tradingview/status${live ? '?live=1' : ''}`,
    ),
    getDualKalmanStatus: async () => fetchAuthAPI<Record<string, any>>(
        '/api/admin/mirofish/kalman/status',
    ),
    getPriceChart: async (symbol: string, limit = 120) => fetchAuthAPI<MiroFishPriceChartResponse>(
        `/api/admin/mirofish/price-chart/${encodeURIComponent(symbol)}?limit=${limit}`,
    ),
    createDeepSeekScannerSummary: async (request: MiroFishScannerRunRequest & { summary_limit?: number; model?: string; thinking?: boolean } = {}) => {
        const payload = await postAuthAPI<any>('/api/admin/mirofish/deepseek/scanner-summary', request, undefined, 120000);
        return {
            ...payload,
            run: normalizeScannerRun(payload?.run),
            summary: payload?.summary as MiroFishDeepSeekSummaryResult,
        } as MiroFishDeepSeekScannerSummaryResponse;
    },
    summarizeScannerRunWithDeepSeek: async (runId: string, request: { limit?: number; model?: string; thinking?: boolean } = {}) => postAuthAPI<MiroFishDeepSeekSummaryResult>(
        `/api/admin/mirofish/scanner/runs/${encodeURIComponent(runId)}/deepseek-summary`,
        request,
        undefined,
        120000,
    ),
    sendScannerDeepSeekSummaryTelegram: async (runId: string, request: { limit?: number; model?: string; thinking?: boolean; channel?: boolean; summary?: MiroFishDeepSeekSummaryResult } = {}) => postAuthAPI<MiroFishDeepSeekTelegramResponse>(
        `/api/admin/mirofish/scanner/runs/${encodeURIComponent(runId)}/deepseek-summary/telegram`,
        request,
        undefined,
        120000,
    ),
    getWorkflowStatus: async () => fetchAuthAPI<MiroFishWorkflowStatus>('/api/admin/mirofish/workflow/status'),
    getLatestWorkflow: async () => fetchAuthAPI<MiroFishWorkflow>('/api/admin/mirofish/workflows/latest'),
    getWorkflow: async (workflowId: string) => fetchAuthAPI<MiroFishWorkflow>(
        `/api/admin/mirofish/workflows/${encodeURIComponent(workflowId)}`,
    ),
    getWorkflowOutcomes: async (workflowId: string) => fetchAuthAPI<MiroFishWorkflowOutcomes>(
        `/api/admin/mirofish/workflows/${encodeURIComponent(workflowId)}/outcomes`,
    ),
    refreshWorkflowOutcomes: async (workflowId: string, request: { horizons?: number[] } = {}) => postAuthAPI<MiroFishWorkflowOutcomes>(
        `/api/admin/mirofish/workflows/${encodeURIComponent(workflowId)}/outcomes/refresh`,
        request,
        undefined,
        120000,
    ),
    startWorkflowScanAnalyze: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishWorkflow>(
        '/api/admin/mirofish/workflow/scan-analyze',
        request,
        undefined,
        300000,
    ),
    /** 자연어 채팅 — Gemini function calling 으로 안전한 read-only MCP 도구 호출 */
    chat: async (
        message: string,
        history: Array<{ role: 'user' | 'assistant'; content: string }> = [],
    ) => postAuthAPI<MiroFishChatResponse>(
        '/api/admin/mirofish/chat',
        { message, history },
        undefined,
        90000,
    ),
    /** 채팅 응답을 텔레그램(개인봇)으로 공유 */
    sendChatToTelegram: async (
        content: string,
        options: { question?: string; channel?: boolean } = {},
    ) => postAuthAPI<MiroFishChatTelegramResponse>(
        '/api/admin/mirofish/chat/telegram',
        {
            content,
            question: options.question || '',
            channel: options.channel ?? false,
        },
        undefined,
        30000,
    ),
    getAutonomousStatus: async () => fetchAuthAPI<MiroFishAutonomousStatus>(
        '/api/admin/mirofish/autonomous/status',
    ),
    getMcpResources: async () => fetchAuthAPI<MiroFishMcpResourceSnapshot>(
        '/api/admin/mirofish/mcp/resources',
        undefined,
        60000,
    ),
    getAlphaEndpointBlueprint: async () => fetchAuthAPI<MiroFishAlphaEndpointBlueprint>(
        '/api/admin/mirofish/mcp/alpha-endpoints',
        undefined,
        60000,
    ),
    getAutonomousLearning: async () => fetchAuthAPI<MiroFishAutonomousLearningFeedback>(
        '/api/admin/mirofish/autonomous/learning',
    ),
    getLearningReadiness: async () => fetchAuthAPI<MiroFishLearningReadiness>(
        '/api/admin/mirofish/learning/readiness',
    ),
    runAutonomousCandidateAlert: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishAutonomousActionResult>(
        '/api/admin/mirofish/autonomous/candidate-alert',
        request,
        undefined,
        180000,
    ),
    runAutonomousScanAnalysis: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishAutonomousActionResult>(
        '/api/admin/mirofish/autonomous/scan-analysis',
        request,
        undefined,
        300000,
    ),
    refreshAutonomousLearning: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishAutonomousLearningFeedback>(
        '/api/admin/mirofish/autonomous/learning/refresh',
        request,
        undefined,
        180000,
    ),
    sendLatestAutonomousWorkflowTelegram: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishAutonomousActionResult>(
        '/api/admin/mirofish/autonomous/telegram/latest',
        request,
        undefined,
        120000,
    ),
    /** 오늘의 검출 파이프라인 + 시장 컨텍스트 스냅샷 */
    // 백엔드 cold 첫 호출 60s 이상 가능 (워크플로우 + scanner 통합 집계).
    // 60s timeout 부여, 추후 백엔드 캐시 추가 시 단축.
    getPipelineToday: async () => fetchAuthAPI<MiroFishPipelineToday>(
        '/api/admin/mirofish/pipeline/today',
        undefined,
        90000,
    ),
    getCrashReboundGate: async () => fetchAuthAPI<MiroFishCrashReboundGate>(
        '/api/admin/mirofish/market/crash-rebound/latest',
        undefined,
        30000,
    ),
    runCrashReboundGate: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishCrashReboundGate>(
        '/api/admin/mirofish/market/crash-rebound/run',
        request,
        undefined,
        60000,
    ),
    getCrashReboundGateSchema: async () => fetchAuthAPI<Record<string, any>>(
        '/api/admin/mirofish/market/crash-rebound/schema',
        undefined,
        30000,
    ),
    getFearIndex: async () => fetchAuthAPI<MiroFishFearIndex>(
        '/api/admin/mirofish/market/fear-index/latest',
        undefined,
        30000,
    ),
    runFearIndex: async (request: Record<string, any> = {}) => postAuthAPI<MiroFishFearIndex>(
        '/api/admin/mirofish/market/fear-index/run',
        request,
        undefined,
        60000,
    ),
    getFearIndexSchema: async () => fetchAuthAPI<Record<string, any>>(
        '/api/admin/mirofish/market/fear-index/schema',
        undefined,
        30000,
    ),
    /** Auto-runner (Stage 2 자동 실행기) 상태 */
    // 백엔드 21s+ — recent_cycles 등 무거운 응답. 45s timeout.
    getAutoRunnerStatus: async () => fetchAuthAPI<MiroFishAutoRunnerStatus>(
        '/api/admin/mirofish/auto-runner/status',
        undefined,
        45000,
    ),
    pauseAutoRunner: async (paused: boolean) => postAuthAPI<MiroFishAutoRunnerStatus>(
        '/api/admin/mirofish/auto-runner/pause',
        { paused },
    ),
    resetAutoRunner: async (scope: 'circuit' | 'today' | 'all' = 'circuit') => postAuthAPI<MiroFishAutoRunnerStatus>(
        '/api/admin/mirofish/auto-runner/reset',
        { scope },
    ),
    triggerAutoRunner: async () => postAuthAPI<{ fired: boolean; success?: boolean; reason?: string; gates?: any }>(
        '/api/admin/mirofish/auto-runner/trigger',
        {},
        undefined,
        300000,
    ),
    tuneAutoRunner: async (windowDays: number = 14, apply: boolean = false) => postAuthAPI<MiroFishAutoRunnerTuneResult>(
        '/api/admin/mirofish/auto-runner/tune',
        { window_days: windowDays, apply },
        undefined,
        90000,
    ),
    applyAutoRunnerTune: async (rec: Partial<MiroFishAutoRunnerThresholds>) => postAuthAPI<MiroFishAutoRunnerApplyResult>(
        '/api/admin/mirofish/auto-runner/apply-tune',
        rec,
        undefined,
        30000,
    ),
    /** 최근 N일 추천 종목 outcomes 보드 — 64 워크플로우 + outcome 통합으로 cold 30s+ */
    getOutcomesBoard: async (params: { days?: number; limit?: number } = {}) => {
        const search = new URLSearchParams();
        if (params.days !== undefined) search.set('days', String(params.days));
        if (params.limit !== undefined) search.set('limit', String(params.limit));
        const qs = search.toString();
        return fetchAuthAPI<MiroFishOutcomesBoard>(
            `/api/admin/mirofish/outcomes/board${qs ? `?${qs}` : ''}`,
            undefined,
            60000,
        );
    },
    /** 카카오톡 공유 payload — workflow의 TOP 3 또는 단일 rank. */
    getSharePayload: async (workflowId: string, rank?: number) => {
        const path = rank
            ? `/api/admin/mirofish/workflows/${encodeURIComponent(workflowId)}/share?rank=${rank}`
            : `/api/admin/mirofish/workflows/${encodeURIComponent(workflowId)}/share`;
        return fetchAuthAPI<MiroFishSharePayload>(path);
    },
    /** Phase A–D: GraphRAG subsystem control plane.
     *
     * Backend prefix: `/api/admin/mirofish/graphrag`.
     * - status: subsystem state + phase + flags + entities + endpoints_live
     * - resolveEntity: 한글/티커/초성/yahoo/corp_code 입력을 표준 entity 로 변환
     * - getEntity: 단일 entity 상세 (entity_id 예: `kr:005930`)
     */
    graphrag: {
        getStatus: async () => fetchAuthAPI<MiroFishGraphRAGStatus>(
            '/api/admin/mirofish/graphrag/status',
        ),
        resolveEntity: async (
            q: string,
            options: { hint_market?: string; limit?: number } = {},
        ) => {
            const search = new URLSearchParams({ q });
            if (options.hint_market) search.set('hint_market', options.hint_market);
            if (options.limit !== undefined) search.set('limit', String(options.limit));
            return fetchAuthAPI<MiroFishGraphRAGResolveResponse>(
                `/api/admin/mirofish/graphrag/entities/resolve?${search.toString()}`,
            );
        },
        getEntity: async (entityId: string) => fetchAuthAPI<MiroFishGraphRAGEntityDetail>(
            `/api/admin/mirofish/graphrag/entities/${encodeURIComponent(entityId)}`,
        ),
        /** Phase G: 전체 종목 스캔 히스토리 + outcome 집계. cold 9-15s (캐시 후 < 1s). */
        getScanHistory: async (options: { days?: number; limit?: number; min_alpha?: number } = {}) => {
            const search = new URLSearchParams();
            if (options.days !== undefined) search.set('days', String(options.days));
            if (options.limit !== undefined) search.set('limit', String(options.limit));
            if (options.min_alpha !== undefined) search.set('min_alpha', String(options.min_alpha));
            const qs = search.toString();
            return fetchAuthAPI<MiroFishScanHistoryResponse>(
                qs
                    ? `/api/admin/mirofish/graphrag/scan-history?${qs}`
                    : '/api/admin/mirofish/graphrag/scan-history',
                undefined,
                90000,
            );
        },
        /** Phase G: 단일 종목의 모든 scan 등장 + workflow 진입 상세. cold 20s. */
        getSymbolHistory: async (symbol: string, days?: number) => {
            const qs = days !== undefined ? `?days=${days}` : '';
            return fetchAuthAPI<MiroFishSymbolHistoryResponse>(
                `/api/admin/mirofish/graphrag/scan-history/${encodeURIComponent(symbol)}${qs}`,
                undefined,
                60000,
            );
        },
        /** Phase G: 전체 성과 통계 (KPI/IC/by_market/by_tag/top_performers). cold 8-15s. */
        getScanPerformance: async (days?: number) => {
            const qs = days !== undefined ? `?days=${days}` : '';
            return fetchAuthAPI<MiroFishScanPerformanceResponse>(
                `/api/admin/mirofish/graphrag/scan-history-performance${qs}`,
                undefined,
                60000,
            );
        },
    },
};

export interface MiroFishChatToolCall {
    name: string;
    args: Record<string, any>;
    result_preview: string;
}

export interface MiroFishChatResponse {
    reply: string;
    tool_calls: MiroFishChatToolCall[];
    iterations: number;
    method: 'llm' | 'fallback' | 'llm_error';
    prompt_version?: string;
    prompt_hash?: string;
    error?: string;
}

export interface MiroFishChatTelegramResponse {
    ok: boolean;
    telegram_sent?: boolean;
    message_chars?: number;
    telegram_config?: {
        personal_configured?: boolean;
        channel_configured?: boolean;
        personal_chat_present?: boolean;
        channel_chat_present?: boolean;
    };
    error?: string;
}

export interface MiroFishPipelineMarketKr {
    phase?: 'pre_open' | 'regular_session' | 'after_close' | 'closed_weekend' | string;
    is_regular_session?: boolean;
    gate_label?: string | null;
    gate_score?: number | null;
    kospi_change_pct?: number | null;
    kosdaq_change_pct?: number | null;
    updated_at?: string | null;
}

export interface MiroFishPipelineMarketUs {
    vix?: number | null;
    vix_level?: 'low' | 'moderate' | 'elevated' | 'high' | null;
    fear_greed_score?: number | null;
    fear_greed_label?: string | null;
    timestamp?: string | null;
}

export interface MiroFishPipelineKpi {
    window_days: number;
    sample_size: number;
    hit_rate_pct: number | null;
    avg_return_pct: number | null;
    pending_count: number;
}

export interface MiroFishOperatingStage {
    id: 'scanner' | 'batch' | 'graphrag' | 'top3' | 'telegram' | 'outcomes' | string;
    label: string;
    objective: string;
    status: 'complete' | 'running' | 'ready' | 'waiting' | 'attention' | string;
    progress_pct: number;
    count: number;
    total?: number | null;
    artifact_id?: string | null;
    updated_at?: string | null;
    requires?: string[];
}

export interface MiroFishOperatingWorkflow {
    schema_version: string;
    generated_at: string;
    date_kst: string;
    workflow_id?: string | null;
    workflow_status?: string | null;
    current_stage_id?: string | null;
    overall_status: 'complete' | 'running' | 'ready' | 'waiting' | 'attention' | string;
    overall_progress_pct: number;
    stages: MiroFishOperatingStage[];
    links?: Record<string, string>;
}

export interface MiroFishPipelineToday {
    generated_at: string;
    date_kst: string;
    market: {
        kr: MiroFishPipelineMarketKr;
        us: MiroFishPipelineMarketUs;
    };
    crash_rebound_gate?: MiroFishCrashReboundGate | null;
    fear_index?: MiroFishFearIndex | null;
    funnel: {
        scanner_pool: number;
        scanner_runs_today: number;
        batch_new_candidates: number;
        graphrag_uploaded: number;
        top3_ready: number;
        latest_workflow_id?: string | null;
        latest_workflow_status?: string | null;
        latest_workflow_at?: string | null;
        latest_scanner_run_at?: string | null;
        freshness_status?: string | null;
    };
    operating_workflow?: MiroFishOperatingWorkflow;
    kpi_7d: MiroFishPipelineKpi;
    kpi_30d: MiroFishPipelineKpi;
    next: {
        next_scheduled_scan_at?: string | null;
        next_scheduled_scans?: string[];
        scanner_enabled?: boolean;
    };
    alerts_today: {
        scanner_alerts_today: number;
        scanner_last_alert_at?: string | null;
        recent_scanner_alerts?: MiroFishScannerAlertEvent[];
    };
}

export interface MiroFishScannerAlertEvent {
    event_key?: string;
    sent_at?: string | null;
    run_id?: string | null;
    rank?: number | null;
    symbol?: string | null;
    display_name?: string | null;
    market?: string | null;
    action?: string | null;
    horizon?: string | null;
    alpha_score?: number | null;
    risk_score?: number | null;
    ranking_score?: number | null;
    signal_quality?: string | null;
    strategy_tags?: string[];
    price?: {
        current_price?: number | string | null;
        change_rate?: number | null;
        date?: string | null;
    } | null;
    source?: string | null;
    deepseek_brief?: string | null;
    tradingagents?: {
        verdict: string;
        confidence: number;
        strong_buy: boolean;
        regime?: string;
        regime_adjustment?: { direction?: string; alignment?: number | null; applied?: number };
        method?: string;
        verified_at?: string;
    };
}

export interface MiroFishScannerAlertState {
    state_path?: string;
    version?: number;
    last_checked_at?: string | null;
    last_sent_at?: string | null;
    last_run_id?: string | null;
    last_candidate_count?: number | null;
    last_new_event_count?: number | null;
    sent_event_count?: number | null;
    recent_sent_events?: MiroFishScannerAlertEvent[];
    latest_run_id?: string | null;
    latest_run_at?: string | null;
    latest_candidate_count?: number | null;
    latest_candidate_events?: MiroFishScannerAlertEvent[];
    latest_new_event_count?: number | null;
    latest_new_events?: MiroFishScannerAlertEvent[];
    feed_event_count?: number | null;
    feed_events?: MiroFishScannerAlertEvent[];
}

export interface MiroFishScannerMonitorState {
    state_path?: string;
    version?: number;
    last_checked_at?: string | null;
    last_processed_at?: string | null;
    last_status?: string | null;
    last_run_id?: string | null;
    last_candidate_count?: number | null;
    last_new_event_count?: number | null;
    last_telegram_sent?: boolean | null;
    last_error?: string | null;
    last_source_fingerprint?: string | null;
    last_failed_source_fingerprint?: string | null;
    last_failed_at?: string | null;
    current_source_fingerprint?: string | null;
    source_changed?: boolean | null;
    source?: Record<string, any>;
}

export interface MiroFishBoardItem {
    workflow_id: string;
    symbol: string;
    name: string;
    rank?: number | null;
    entry_date?: string | null;
    entry_price?: number | null;
    status: 'evaluated' | 'partial' | 'pending' | 'missing_entry' | string;
    hit?: boolean | null;
    stopped?: boolean | null;
    forward_return_pct?: number | null;
    max_forward_return_pct?: number | null;
    max_drawdown_pct?: number | null;
    primary_horizon_days?: number | null;
    available_future_days?: number | null;
    /** 백엔드에서 horizon 별 return_pct(number) 만 flatten 해서 보냄. null=평가전. */
    horizons?: Record<string, number | null>;
    feature_snapshot?: Record<string, any> | null;
}

export interface MiroFishAutoRunnerGate {
    name: string;
    ok: boolean;
    detail?: any;
}

export interface MiroFishAutoRunnerThresholds {
    min_alpha?: number;
    max_risk?: number;
    min_new_events?: number;
    cooldown_minutes?: number;
    force_after_hours?: number;
}

export interface MiroFishAutoRunnerTuneResult {
    ok: boolean;
    error?: string;
    generated_at?: string;
    window_days?: number;
    current_thresholds?: MiroFishAutoRunnerThresholds;
    recent_kpi?: Record<string, any>;
    recommendation?: MiroFishAutoRunnerThresholds & {
        reasoning?: string;
        confidence?: 'low' | 'medium' | 'high' | string;
    };
    diff?: Array<{
        field: string;
        current: number | null;
        recommended: number | null;
        delta: number | null;
    }>;
    duration_s?: number;
    apply_note?: string;
    applied?: MiroFishAutoRunnerApplyResult;
    raw_preview?: string;
}

export interface MiroFishAutoRunnerApplyResult {
    ok: boolean;
    applied?: Record<string, number>;
    effective_tunables?: Record<string, any>;
    note?: string;
}

export interface MiroFishAutoRunnerStatus {
    service: string;
    phase: 'IDLE' | 'CHECKING' | 'TRIGGERED' | 'ANALYZING' | 'NOTIFYING' | 'COOLDOWN' | 'CIRCUIT_OPEN' | 'PAUSED' | string;
    paused: boolean;
    enabled: boolean;
    dry_run: boolean;
    worker_running: boolean;
    next_eligible_check_at?: string | null;
    last_check_at?: string | null;
    last_check_reason?: string | null;
    last_trigger_at?: string | null;
    last_success_at?: string | null;
    last_failure_at?: string | null;
    last_workflow_id?: string | null;
    last_top3_count: number;
    consecutive_failures: number;
    circuit_opened_at?: string | null;
    circuit_release_at?: string | null;
    cooldown_until?: string | null;
    today: {
        date_kst: string;
        checks: number;
        triggers: number;
        successes: number;
        failures: number;
        telegram_sent: number;
        est_cost_usd: number;
        skip_reasons?: Record<string, number>;
    };
    recent_cycles?: Array<{
        at: string;
        outcome: string;
        reason?: string;
        top3?: number;
        duration_s?: number;
    }>;
    tuning: {
        enabled: boolean;
        poll_seconds: number;
        cooldown_minutes: number;
        min_new_events: number;
        min_alpha: number;
        max_risk: number;
        daily_cap_usd: number;
        monthly_cap_usd?: number;
        circuit_breaker_failures: number;
        circuit_open_minutes: number;
        est_cost_per_trigger_usd: number;
        dry_run: boolean;
        allow_outside_market_hours?: boolean;
    };
    checked_at?: string;
}

export interface MiroFishOutcomesBoard {
    window_days: number;
    generated_at: string;
    sample_size: number;
    workflow_count: number;
    summary: {
        evaluated_count: number;
        pending_count: number;
        hit_count: number;
        miss_count: number;
        stopped_count: number;
        hit_rate_pct: number | null;
        avg_forward_return_pct: number | null;
        false_positive_pct: number | null;
        best_return_pct: number | null;
        worst_return_pct: number | null;
        targets: {
            hit_rate_pct: number;
            avg_return_pct: number;
            false_positive_pct: number;
        };
    };
    items: MiroFishBoardItem[];
    items_truncated: boolean;
    total_items: number;
}

export interface MiroFishShareItem {
    rank: number;
    symbol: string;
    name: string;
    market: string;
    score: number;
    action: 'BUY' | 'HOLD' | 'SELL' | string;
    confidence_pct: number;
    outcome_status: string;
    outcome_hit?: boolean | null;
    outcome_forward_return_pct?: number | null;
    outcome_horizon_days?: number | null;
    replay_safe_after?: string | null;
    analyst_quote?: string;
    cio_reasoning?: string;
    cio_opposing?: string;
    cio_allocation_pct?: number | null;
    run_id?: string;
}

export interface MiroFishShareListContent {
    title: string;
    description: string;
    image_url: string;
    link_url: string;
}

export interface MiroFishShareButton {
    title: string;
    link_url: string;
}

export interface MiroFishSharePayload {
    title: string;
    description: string;
    image_url: string;
    link_url: string;
    rank: number | null;
    top_items: MiroFishShareItem[];
    list_contents?: MiroFishShareListContent[];
    kakao_buttons?: MiroFishShareButton[];
    analyst_quote?: string;
    cio_reasoning?: string;
    cio_opposing?: string;
    workflow_id: string;
    completed_at?: string;
}
