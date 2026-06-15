import { useEffect, useMemo, useRef, useState, type CompositionEvent as ReactCompositionEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { MiroFishAlphaCandidate, MiroFishAlphaEndpointBlueprint, MiroFishAnalyst, MiroFishAutonomousActionResult, MiroFishAutonomousLearningFeedback, MiroFishAutonomousStatus, MiroFishDeepSeekStatus, MiroFishDeepSeekSummaryResult, MiroFishGraphRAGEntityMatch, MiroFishLayer, MiroFishLog, MiroFishMcpResourceSnapshot, MiroFishNode, MiroFishRun, MiroFishScannerRun, MiroFishScannerStatus, MiroFishStatus, MiroFishTargetSnapshot, MiroFishTradingViewStatus, MiroFishWorkflow, mirofishApi } from '@/lib/mirofishApi';
import { shareToKakao } from '@/lib/kakaoShare';
import MirofishChatPanel from '@/components/admin/MirofishChatPanel';
import TodaysPipelineCard from '@/components/admin/TodaysPipelineCard';
import RecentOutcomesBoard from '@/components/admin/RecentOutcomesBoard';
import QuickActionsFooter from '@/components/admin/QuickActionsFooter';
import AutoRunnerCard from '@/components/admin/AutoRunnerCard';
import Top3TradingViewCharts from '@/components/admin/Top3TradingViewCharts';
import GraphRAGStatusCard from '@/components/admin/GraphRAGStatusCard';
import GraphRAGEntityResolverCard from '@/components/admin/GraphRAGEntityResolverCard';
import ScanPerformanceCard from '@/components/admin/ScanPerformanceCard';
import ScanHistoryCard from '@/components/admin/ScanHistoryCard';
import SourceFreshnessMatrix from '@/components/admin/SourceFreshnessMatrix';

const agentCounts = [3, 7, 10, 15];
const defaultTarget = '삼성전자';

const layerColors: Record<string, string> = {
    TARGET: 'bg-red-500',
    'CAUSAL HISTORY': 'bg-blue-500',
    'AI ANALYSTS': 'bg-violet-500',
    PREDICTIONS: 'bg-orange-400',
    VERDICT: 'bg-emerald-400',
};

function createEmptyRun(target = defaultTarget): MiroFishRun {
    return {
        target,
        display_name: target,
        status: 'idle',
        layers: [],
        logs: [],
        analysts: [],
        graph_nodes: [],
        prediction_nodes: [],
    };
}

const impactSteps = [
    { no: '01', ko: '대상 입력', en: 'TARGET', icon: 'fa-search' },
    { no: '02', ko: 'Brain 13D', en: 'BRAIN', icon: 'fa-brain' },
    { no: '03', ko: '그래프 추출', en: 'GRAPHRAG', icon: 'fa-link' },
    { no: '04', ko: '에이전트 토론', en: 'DEBATE', icon: 'fa-users' },
    { no: '05', ko: 'CIO 판정', en: 'VERDICT', icon: 'fa-gavel' },
];

const runSteps = ['입력', 'Brain 13D', 'GraphRAG', '에이전트', '리포트'];
const runStepEndpoints: EndpointKey[] = ['resolve', 'runDetail', 'graph', 'events', 'report'];
const phaseNumberById: Record<string, number> = {
    intake: 1,
    brain_snapshot: 2,
    graph_build: 3,
    analyst_mesh: 4,
    verdict: 5,
    report: 5,
};
type ApiState = 'checking' | 'ready' | 'error' | 'running';
type AlphaScannerState = 'idle' | 'loading' | 'running' | 'ready' | 'error';
type DeepSeekPanelState = 'idle' | 'checking' | 'summarizing' | 'ready' | 'sending' | 'sent' | 'error';
type WorkflowPanelState = 'idle' | 'running' | 'completed' | 'no_new_events' | 'blocked' | 'error';
type AutonomousPanelState = 'idle' | 'checking' | 'running' | 'ready' | 'sending' | 'sent' | 'error';
type EndpointKey = 'status' | 'dataSources' | 'resolve' | 'history' | 'createRun' | 'runDetail' | 'graph' | 'events' | 'report' | 'deepseek' | 'tradingview' | 'kalman' | 'workflow' | 'autonomous' | 'mcpResources' | 'alphaEndpoints';
type EndpointStatus = 'idle' | 'loading' | 'ok' | 'error';
type TargetCandidate = NonNullable<MiroFishTargetSnapshot['candidates']>[number];

const endpointDefinitions: Array<{ key: EndpointKey; method: string; path: string; title: string; icon: string; color: string }> = [
    { key: 'status', method: 'GET', path: '/api/admin/mirofish/status', title: 'Service Status', icon: 'fa-satellite-dish', color: 'text-anthropic-darkText' },
    { key: 'dataSources', method: 'GET', path: '/api/admin/mirofish/data-sources', title: 'Data Sources', icon: 'fa-database', color: 'text-anthropic-darkText' },
    { key: 'resolve', method: 'GET', path: '/api/admin/mirofish/targets/resolve', title: 'Target Resolve', icon: 'fa-crosshairs', color: 'text-anthropic-darkText' },
    { key: 'history', method: 'GET', path: '/api/admin/mirofish/runs', title: 'Run History', icon: 'fa-clock-rotate-left', color: 'text-anthropic-darkText' },
    { key: 'createRun', method: 'POST', path: '/api/admin/mirofish/runs', title: 'Create Run', icon: 'fa-play', color: 'text-anthropic-orange' },
    { key: 'runDetail', method: 'GET', path: '/api/admin/mirofish/runs/{id}', title: 'Run Detail', icon: 'fa-file-code', color: 'text-anthropic-darkText' },
    { key: 'graph', method: 'GET', path: '/api/admin/mirofish/runs/{id}/graph', title: 'Graph Artifact', icon: 'fa-project-diagram', color: 'text-anthropic-darkText' },
    { key: 'events', method: 'GET', path: '/api/admin/mirofish/runs/{id}/events', title: 'Event Feed', icon: 'fa-stream', color: 'text-anthropic-darkText' },
    { key: 'report', method: 'GET', path: '/api/admin/mirofish/runs/{id}/report', title: 'Report', icon: 'fa-scroll', color: 'text-anthropic-darkText' },
    { key: 'deepseek', method: 'POST', path: '/api/admin/mirofish/deepseek/scanner-summary', title: 'DeepSeek V2', icon: 'fa-wand-magic-sparkles', color: 'text-anthropic-orange' },
    { key: 'tradingview', method: 'GET', path: '/api/admin/mirofish/tradingview/status', title: 'TradingView MCP', icon: 'fa-chart-simple', color: 'text-anthropic-darkText' },
    { key: 'kalman', method: 'POST', path: '/api/admin/mirofish/kalman/runs', title: 'Dual Kalman Gate', icon: 'fa-wave-square', color: 'text-cyan-200' },
    { key: 'workflow', method: 'POST', path: '/api/admin/mirofish/workflow/scan-analyze', title: 'MCP Top 3', icon: 'fa-network-wired', color: 'text-anthropic-orange' },
    { key: 'autonomous', method: 'POST', path: '/api/admin/mirofish/autonomous/*', title: 'Autonomous MCP', icon: 'fa-robot', color: 'text-anthropic-orange' },
    { key: 'mcpResources', method: 'GET', path: '/api/admin/mirofish/mcp/resources', title: 'MCP Resources', icon: 'fa-plug-circle-check', color: 'text-cyan-200' },
    { key: 'alphaEndpoints', method: 'GET', path: '/api/admin/mirofish/mcp/alpha-endpoints', title: 'Alpha Evidence Gates', icon: 'fa-shield-halved', color: 'text-emerald-200' },
];

function clampCount(value: unknown, fallback: number) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
}

function verdictTone(verdict?: string) {
    const upper = (verdict || '').toUpperCase();
    if (upper.includes('BULL') || upper === 'BUY') return 'border-emerald-400 bg-emerald-500/10 text-emerald-500';
    if (upper.includes('BEAR') || upper === 'SELL') return 'border-rose-400 bg-rose-500/10 text-rose-500';
    return 'border-amber-400 bg-amber-500/10 text-amber-500';
}

function endpointStatusTone(state: EndpointStatus) {
    // Anthropic style: 단일 액센트 + 의미적 색상 최소화
    if (state === 'ok') return 'border-green-500/30 bg-green-500/[0.08] text-green-400';
    if (state === 'loading') return 'border-anthropic-orange/30 bg-anthropic-orange/[0.10] text-anthropic-orange';
    if (state === 'error') return 'border-red-500/30 bg-red-500/[0.08] text-red-400';
    return 'border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkMuted';
}

function targetCandidateLabel(candidate?: TargetCandidate | null): string {
    return String(candidate?.display_name || candidate?.name || candidate?.symbol || '').trim();
}

function targetCandidateStartValue(candidate?: TargetCandidate | null): string {
    const label = targetCandidateLabel(candidate);
    const symbol = String(candidate?.symbol || candidate?.yahoo_ticker || '').trim();
    const market = String(candidate?.market || '').trim();
    const parts = [label, symbol, market].filter(Boolean);
    return Array.from(new Set(parts)).join(' ').trim();
}

function graphragMatchToTargetCandidate(match: MiroFishGraphRAGEntityMatch): TargetCandidate {
    const symbol = String(match.symbol || match.ids?.ticker_kr || '').trim();
    const displayName = String(match.name_ko || match.name || match.name_en || symbol || match.entity_id).trim();
    return {
        symbol: symbol || null,
        name: displayName,
        display_name: displayName,
        market: match.market || match.exchange || undefined,
        yahoo_ticker: match.ids?.yahoo_ticker || undefined,
        asset_type: match.type || 'equity',
        score: Math.round((Number(match.confidence) || 0) * 100),
        match_type: `graphrag_${match.match_reason || 'entity'}`,
    };
}

function targetCandidateMatchLabel(candidate?: TargetCandidate | null): string {
    const matchType = String(candidate?.match_type || '');
    if (matchType.startsWith('graphrag')) return 'GraphRAG';
    if (matchType.includes('initial')) return '초성';
    if (matchType.includes('exact')) return '정확';
    if (matchType.includes('prefix')) return '시작';
    if (matchType.includes('symbol')) return '코드';
    if (matchType.includes('alias')) return '별칭';
    return '관련';
}

function phaseFromRunState(run: MiroFishRun): number {
    if (run.status === 'completed') return 5;
    const phaseId = run.progress?.current_phase || run.events?.[run.events.length - 1]?.phase;
    if (phaseId && phaseNumberById[phaseId]) return phaseNumberById[phaseId];
    const percent = Number(run.progress?.percent || 0);
    if (percent >= 82) return 5;
    if (percent >= 62) return 4;
    if (percent >= 40) return 3;
    if (percent >= 20) return 2;
    return 1;
}

function isTerminalRun(run: MiroFishRun): boolean {
    return run.status === 'completed' || run.status === 'failed';
}

function formatElapsed(ms?: number) {
    const seconds = Math.max(0, Math.round((ms || 0) / 100) / 10);
    return `${seconds.toFixed(1)}s`;
}

function formatDateTime(value?: string | null): string {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

function scannerRunTimestamp(run?: MiroFishScannerRun | null): number {
    const raw = run?.generated_at || run?.updated_at || run?.created_at || run?.last_run_at;
    if (!raw) return 0;
    const value = new Date(raw).getTime();
    return Number.isNaN(value) ? 0 : value;
}

function formatPrice(value: unknown): string {
    const numeric = typeof value === 'number'
        ? value
        : typeof value === 'string'
            ? Number(value.replace(/,/g, ''))
            : NaN;
    return Number.isFinite(numeric) ? numeric.toLocaleString('ko-KR') : '--';
}

function formatSignedPct(value: unknown): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '--';
    return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`;
}

function formatMetricNumber(value: unknown, digits = 1): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '--';
    return numeric.toFixed(digits);
}

function formatSubscriberPolicy(policy?: MiroFishRun['subscriber_policy'] | null): string {
    if (!policy) {
        return 'AI Brain 구독자 분석은 일일 횟수 제한, 동시 실행 제한, 최근 동일 분석 재사용 캐시가 적용됩니다.';
    }
    const used = Number(policy.used_today ?? 0);
    const daily = Number(policy.daily_limit ?? 0);
    const active = Number(policy.active_count ?? 0);
    const concurrent = Number(policy.concurrent_limit ?? 0);
    const cacheMinutes = Number(policy.cache_minutes ?? 0);
    const prefix = policy.reused_cached_run ? '최근 동일 분석 run을 재사용했습니다.' : '구독자 분석 run이 생성되었습니다.';
    return `${prefix} 오늘 ${used}/${daily}회 사용, 실행 중 ${active}/${concurrent}개, 캐시 ${cacheMinutes}분.`;
}

function workflowOutcomeSummary(workflow?: MiroFishWorkflow | null): Record<string, any> {
    const direct = workflow?.outcome_summary;
    if (direct && typeof direct === 'object') return direct as Record<string, any>;
    const nested = workflow?.summary?.outcome;
    if (nested && typeof nested === 'object') return nested as Record<string, any>;
    const outcomes = workflow?.outcomes;
    if (outcomes?.summary && typeof outcomes.summary === 'object') return outcomes.summary as Record<string, any>;
    return {};
}

function outcomeTone(status?: string, hit?: boolean | null): string {
    if (hit === true) return 'border-emerald-300/25 bg-emerald-300/12 text-emerald-100';
    if (hit === false) return 'border-rose-300/25 bg-rose-300/12 text-rose-100';
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'partial') return 'border-cyan-300/25 bg-cyan-300/12 text-cyan-100';
    if (normalized === 'pending') return 'border-amber-300/25 bg-amber-300/12 text-amber-100';
    return 'border-white/10 bg-white/8 text-slate-300';
}

function visibleLayers(run: MiroFishRun, phase: number): MiroFishLayer[] {
    const base = run.layers?.length
        ? run.layers
        : [
            { label: 'TARGET', count: run.target ? 1 : 0 },
            { label: 'CAUSAL HISTORY', count: run.graph_nodes?.length || 0 },
            { label: 'AI ANALYSTS', count: run.analysts?.length || 0 },
            { label: 'PREDICTIONS', count: run.prediction_nodes?.length || 0 },
            { label: 'VERDICT', count: run.verdict ? 1 : 0 },
        ];
    return base.map((layer) => {
        const label = layer.label.toUpperCase();
        const count = phase < 3 && label !== 'TARGET'
            ? 0
            : phase < 4 && label === 'PREDICTIONS'
                ? 0
                : phase < 5 && label === 'VERDICT'
                    ? 0
                    : layer.count;
        return { ...layer, label, count, color: layer.color || layerColors[label] || 'bg-slate-400' };
    });
}

function visibleLogs(run: MiroFishRun, phase: number): MiroFishLog[] {
    const logs = run.logs?.length ? run.logs : [];
    return logs.filter((log) => (log.phase || 1) <= phase);
}

function feedToneClass(tone?: string): string {
    if (!tone) return 'text-blue-800';
    if (tone.includes('cyan')) return 'text-cyan-800';
    if (tone.includes('teal')) return 'text-teal-800';
    if (tone.includes('violet')) return 'text-violet-800';
    if (tone.includes('emerald')) return 'text-emerald-800';
    if (tone.includes('rose') || tone.includes('red')) return 'text-rose-800';
    if (tone.includes('amber') || tone.includes('yellow')) return 'text-amber-800';
    if (tone.includes('blue')) return 'text-blue-800';
    return 'text-slate-800';
}

function alphaActionTone(action?: string) {
    const upper = String(action || '').toUpperCase();
    if (upper.includes('BUY')) return 'border-emerald-300/25 bg-emerald-300/12 text-emerald-100';
    if (upper.includes('AVOID') || upper.includes('SELL')) return 'border-rose-300/25 bg-rose-300/12 text-rose-100';
    if (upper.includes('PULLBACK') || upper.includes('WAIT')) return 'border-amber-300/25 bg-amber-300/12 text-amber-100';
    return 'border-cyan-300/20 bg-cyan-300/10 text-cyan-100';
}

function formatCompactNumber(value: unknown) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return '--';
    if (numeric >= 100000000) return `${Math.round(numeric / 100000000).toLocaleString('ko-KR')}억`;
    if (numeric >= 10000) return `${Math.round(numeric / 10000).toLocaleString('ko-KR')}만`;
    return numeric.toLocaleString('ko-KR');
}

function formatAlphaEvidence(candidate: MiroFishAlphaCandidate): string {
    const evidence = candidate.evidence?.[0];
    if (evidence) {
        const source = evidence.source || 'artifact';
        const field = evidence.field || 'signal';
        const score = evidence.score === undefined ? '' : ` ${Math.round(evidence.score)}`;
        return `${source} / ${field}${score}`;
    }
    return `trading value ${formatCompactNumber(candidate.trading_value)}`;
}

function formatAlphaAnalysis(candidate: MiroFishAlphaCandidate): string {
    const profile = candidate.analysis_profile || {};
    const sourceCount = Number(profile.source_count || 0);
    const trend20 = Number(profile.trend_20d_pct || 0);
    const volumeRatio = Number(profile.volume_ratio || 0);
    const quality = candidate.signal_quality || 'quality';
    const trendText = Number.isFinite(trend20) ? `${trend20 >= 0 ? '+' : ''}${trend20.toFixed(1)}%` : '--';
    const volumeText = Number.isFinite(volumeRatio) && volumeRatio > 0 ? `${volumeRatio.toFixed(1)}x` : '--';
    return `${quality} · src ${sourceCount || '--'} · T20 ${trendText} · Vol ${volumeText}`;
}

function tradingViewSignal(candidate: MiroFishAlphaCandidate): Record<string, any> {
    const direct = candidate.tradingview && typeof candidate.tradingview === 'object'
        ? candidate.tradingview
        : {};
    if (Object.keys(direct).length) return direct;
    const profileSignal = candidate.analysis_profile?.tradingview_adjustment;
    return profileSignal && typeof profileSignal === 'object'
        ? profileSignal as Record<string, any>
        : {};
}

function formatTradingViewSignal(candidate: MiroFishAlphaCandidate): string | null {
    const signal = tradingViewSignal(candidate);
    if (!signal.available && !signal.applied) return null;
    const recommendation = String(signal.recommendation || 'UNKNOWN').replace(/_/g, ' ');
    const alphaDelta = Number(signal.alpha_delta ?? 0);
    const alphaText = Number.isFinite(alphaDelta)
        ? `${alphaDelta >= 0 ? '+' : ''}${alphaDelta.toFixed(1)}`
        : '--';
    const freshness = signal.freshness && typeof signal.freshness === 'object'
        ? String(signal.freshness.status || '')
        : '';
    const source = String(signal.source || '');
    const suffix = freshness && freshness !== 'unknown'
        ? ` - ${freshness}`
        : source
            ? ` - ${source}`
            : '';
    return `TradingView ${recommendation} ${alphaText}${suffix}`;
}

function tradingViewSignalTone(candidate: MiroFishAlphaCandidate): string {
    const signal = tradingViewSignal(candidate);
    const recommendation = String(signal.recommendation || '').toUpperCase();
    const alphaDelta = Number(signal.alpha_delta ?? 0);
    const freshness = signal.freshness && typeof signal.freshness === 'object'
        ? String(signal.freshness.status || '').toLowerCase()
        : '';
    if (freshness === 'stale') return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
    if (recommendation.includes('SELL') || alphaDelta < 0) return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    if (recommendation.includes('BUY') || alphaDelta > 0) return 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100';
    return 'border-slate-300/20 bg-slate-300/10 text-slate-200';
}

function deepSeekStateTone(state: DeepSeekPanelState, configured?: boolean) {
    if (!configured) return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
    if (state === 'error') return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    if (state === 'summarizing' || state === 'sending' || state === 'checking') return 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100';
    if (state === 'ready' || state === 'sent') return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    return 'border-white/10 bg-white/8 text-slate-300';
}

function freshnessTone(status?: string) {
    const value = String(status || '').toLowerCase();
    if (value === 'fresh') return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (value === 'stale') return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
    if (value === 'unknown') return 'border-slate-300/20 bg-slate-300/10 text-slate-200';
    return 'border-white/10 bg-white/8 text-slate-300';
}

function providerStatus(record?: Record<string, any>, key?: string): Record<string, any> {
    if (!record || typeof record !== 'object' || !key) return {};
    const value = record[key];
    return value && typeof value === 'object' ? value as Record<string, any> : {};
}

function AlphaBoardPanel({
    candidates,
    scannerRun,
    scannerStatus,
    state,
    errorText,
    deepSeekStatus,
    deepSeekState,
    deepSeekSummary,
    deepSeekErrorText,
    workflow,
    workflowState,
    workflowErrorText,
    autonomousStatus,
    onScan,
    onWorkflow,
    onForceWorkflow,
    onDeepSeekSummary,
    onSendDeepSeekTelegram,
    onSelect,
    onDeepDive,
    subscriberMode = false,
}: {
    candidates: MiroFishAlphaCandidate[];
    scannerRun: MiroFishScannerRun | null;
    scannerStatus: MiroFishScannerStatus | null;
    state: AlphaScannerState;
    errorText?: string | null;
    deepSeekStatus?: MiroFishDeepSeekStatus | null;
    deepSeekState: DeepSeekPanelState;
    deepSeekSummary?: MiroFishDeepSeekSummaryResult | null;
    deepSeekErrorText?: string | null;
    workflow?: MiroFishWorkflow | null;
    workflowState: WorkflowPanelState;
    workflowErrorText?: string | null;
    autonomousStatus?: MiroFishAutonomousStatus | null;
    onScan: () => void;
    onWorkflow: () => void;
    onForceWorkflow: () => void;
    onDeepSeekSummary: () => void;
    onSendDeepSeekTelegram: () => void;
    onSelect: (candidate: MiroFishAlphaCandidate) => void;
    onDeepDive: (candidate: MiroFishAlphaCandidate) => void;
    subscriberMode?: boolean;
}) {
    const topCandidates = candidates.slice(0, 5);
    const scannerBusy = state === 'loading' || state === 'running';
    const deepSeekBusy = deepSeekState === 'checking' || deepSeekState === 'summarizing' || deepSeekState === 'sending';
    const deepSeekConfigured = Boolean(deepSeekStatus?.configured);
    const summaryCandidates = deepSeekSummary?.summary?.candidates || [];
    const workflowBusy = workflowState === 'running';
    const topWorkflow = workflow?.top3 || [];
    const workflowProgress = workflow?.progress || {};
    const workflowPercent = Math.max(0, Math.min(100, Number(workflowProgress.percent || (workflowState === 'completed' ? 100 : 0))));
    const workflowCompleted = Number(workflowProgress.completed || workflow?.analyzed_count || 0);
    const workflowTotal = Number(workflowProgress.total || workflow?.event_count || 0);
    const workflowStageTone = workflowState === 'completed'
        ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
        : workflowState === 'error' || workflowState === 'blocked'
            ? 'border-rose-300/25 bg-rose-300/10 text-rose-100'
            : workflowBusy
                ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100'
                : 'border-white/10 bg-white/8 text-slate-300';
    const lastRunAt = scannerRun?.generated_at || scannerRun?.updated_at || scannerRun?.created_at || scannerStatus?.last_run_at;
    const nextRunAt = scannerStatus?.next_scheduled_at || scannerRun?.next_scheduled_at;
    const freshnessStatus = scannerStatus?.freshness_status || String(scannerStatus?.freshness?.status || scannerRun?.freshness_status || scannerRun?.freshness?.status || scannerRun?.source_files?.[0]?.freshness || 'unknown');
    const workflowFreshness = String(workflow?.scanner_freshness?.status || freshnessStatus || 'unknown');
    const scannerPoolCount = workflow?.scanner_candidate_count ?? scannerRun?.candidate_count ?? candidates.length;
    const outcomeSummary = workflowOutcomeSummary(workflow);
    const outcomeHitRate = outcomeSummary.top3_hit_rate_pct ?? outcomeSummary.hit_rate_pct;
    const outcomeAvgReturn = outcomeSummary.average_forward_return_pct;
    const outcomeEvaluated = Number(outcomeSummary.top3_evaluated_count ?? outcomeSummary.evaluated_count ?? 0);
    const outcomePending = Number(outcomeSummary.pending_count ?? 0);
    const outcomeStatus = String(outcomeSummary.status || workflow?.outcome_status || '').toLowerCase();
    const replayGuardValue = outcomeSummary.lookahead_safe && !['failed', 'not_evaluated'].includes(outcomeStatus)
        ? 'ON'
        : (workflow?.outcome_status || outcomeStatus || '--');
    const mcpServer = autonomousStatus?.runtime?.mcp_server;
    const startupTask = autonomousStatus?.runtime?.startup_task;
    const watchdogTask = autonomousStatus?.runtime?.watchdog_task;
    const mcpHealthy = Boolean(mcpServer?.healthy);
    const startupRegistered = Boolean(startupTask?.registered);
    const watchdogRegistered = Boolean(watchdogTask?.registered);
    const mcpRuntimeTone = mcpHealthy
        ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
        : 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    const taskRuntimeTone = startupRegistered && watchdogRegistered
        ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
        : 'border-amber-300/25 bg-amber-300/10 text-amber-100';
    const runTradingViewProvider = providerStatus(scannerRun?.providers, 'tradingview');
    const statusTradingViewProvider = providerStatus(scannerStatus?.providers, 'tradingview');
    const tradingViewProvider = Object.keys(runTradingViewProvider).length ? runTradingViewProvider : statusTradingViewProvider;
    const tradingViewEnabled = Boolean(tradingViewProvider.enabled);
    const tradingViewConfigured = Boolean(tradingViewProvider.configured || tradingViewProvider.cache_available || tradingViewProvider.mcp_url_configured);
    const tradingViewMode = String(tradingViewProvider.mode || (tradingViewConfigured ? 'cache' : 'off'));
    const tradingViewTone = tradingViewEnabled
        ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100'
        : tradingViewConfigured
            ? 'border-amber-300/25 bg-amber-300/10 text-amber-100'
            : 'border-white/10 bg-white/8 text-slate-300';
    const tradingViewLabel = tradingViewEnabled
        ? `TradingView ${tradingViewMode}`
        : tradingViewConfigured
            ? 'TradingView cache only'
            : 'TradingView off';
    const scannerAdvisory = scannerRun?.performance_advisory || {};
    const advisoryHitRaw = Number(scannerAdvisory.hit_rate_recent);
    const advisoryHitRate = Number.isFinite(advisoryHitRaw)
        ? `${(advisoryHitRaw <= 1 ? advisoryHitRaw * 100 : advisoryHitRaw).toFixed(1)}%`
        : '--';
    const topEvidenceGrade = String(candidates[0]?.analysis_profile?.evidence_quality?.grade || '--');
    const topConfidenceCap = Number(candidates[0]?.analysis_profile?.confidence_cap);
    const analysisArtifactsReady = Boolean(scannerRun?.analysis_artifacts?.feature_vectors && scannerRun?.analysis_artifacts?.evidence_ledger);

    // 카카오톡 공유 핸들러 (list template + buttons 포함)
    async function handleShareTop3(workflowId: string) {
        try {
            const payload = await mirofishApi.getSharePayload(workflowId);
            const result = await shareToKakao({
                title: payload.title,
                description: payload.description,
                image_url: payload.image_url,
                link_url: payload.link_url,
                list_contents: payload.list_contents,
                kakao_buttons: payload.kakao_buttons,
            });
            if (result === 'clipboard') {
                window.alert('TOP 3 분석 내용 + 링크를 클립보드에 복사했습니다.');
            } else if (result === 'failed') {
                window.alert('공유에 실패했습니다. 카카오 SDK 키를 확인해 주세요.');
            }
        } catch (err) {
            console.error('[Share TOP 3] failed', err);
            window.alert('공유 정보를 가져오지 못했습니다.');
        }
    }

    async function handleShareRank(workflowId: string, rank: number) {
        try {
            const payload = await mirofishApi.getSharePayload(workflowId, rank);
            const result = await shareToKakao({
                title: payload.title,
                description: payload.description,
                image_url: payload.image_url,
                link_url: payload.link_url,
                kakao_buttons: payload.kakao_buttons,
            });
            if (result === 'clipboard') {
                window.alert(`TOP ${rank} 분석 내용 + 링크를 클립보드에 복사했습니다.`);
            } else if (result === 'failed') {
                window.alert('공유에 실패했습니다.');
            }
        } catch (err) {
            console.error(`[Share TOP ${rank}] failed`, err);
            window.alert('공유 정보를 가져오지 못했습니다.');
        }
    }

    return (
        <section className="rounded-xl border border-white/10 bg-[#10151f]/90 p-4 shadow-[0_18px_70px_rgba(0,0,0,0.22)] backdrop-blur">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-emerald-200/70">
                        <i className="fas fa-radar text-emerald-300" />
                        Alpha Board
                    </div>
                    <h2 className="mt-1 text-2xl font-black text-white">Top3 수익 후보 검출</h2>
                    <p className="mt-1 text-sm font-semibold text-slate-400">
                        스캔된 후보를 수급·리스크·GraphRAG·사후성과 기준으로 압축합니다.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${state === 'error' ? 'border-rose-300/20 bg-rose-300/10 text-rose-100' : state === 'ready' ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-white/15 bg-white/8 text-slate-200'}`}>
                        {state === 'idle' ? 'IDLE' : state.toUpperCase()}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/8 px-3 py-1.5 text-xs font-bold text-slate-300">
                        {scannerRun?.candidate_count ?? candidates.length} candidates
                    </span>
                    <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1.5 text-xs font-bold text-cyan-100">
                        Last {formatDateTime(lastRunAt)}
                    </span>
                    <span className="rounded-full border border-violet-300/20 bg-violet-300/10 px-3 py-1.5 text-xs font-bold text-violet-100">
                        Next {formatDateTime(nextRunAt)}
                    </span>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${freshnessTone(freshnessStatus)}`}>
                        Fresh {freshnessStatus}
                    </span>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${deepSeekStateTone(deepSeekState, deepSeekConfigured)}`}>
                        DeepSeek {deepSeekConfigured ? (deepSeekStatus?.default_model || 'ready') : 'not set'}
                    </span>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${tradingViewTone}`}>
                        {tradingViewLabel}
                    </span>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${mcpRuntimeTone}`}>
                        MCP HTTP {mcpHealthy ? 'online' : 'offline'}
                    </span>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${taskRuntimeTone}`}>
                        Watchdog {watchdogRegistered ? '5m on' : 'missing'}
                    </span>
                    <button
                        type="button"
                        onClick={onScan}
                        disabled={scannerBusy}
                        aria-label="Run scanner"
                        className="rounded-lg bg-emerald-400 px-4 py-2 text-xs font-black text-slate-950 shadow-lg shadow-emerald-500/20 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-70"
                    >
                        {scannerBusy ? '스캔 중...' : '스캐너 실행'}
                    </button>
                </div>
            </div>

            {(errorText || deepSeekErrorText || workflowErrorText) && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100">
                    {errorText || deepSeekErrorText || workflowErrorText}
                </div>
            )}

            <div className="mt-4 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] p-3">
                <div>
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                            <div className="text-[11px] font-black uppercase tracking-[0.18em] text-cyan-200/80">Top3 자동 분석 흐름</div>
                            <div className="mt-1 text-sm font-bold text-slate-200">
                                자동 스캔 → 신규 후보 5종 선별 → 다중 GraphRAG 분석 → 최종 Top3 랭킹과 알림 생성.
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2">
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${workflowStageTone}`}>
                                    MCP {workflowState}
                                </span>
                                <span className="rounded-full border border-white/10 bg-white/8 px-2.5 py-1 text-[11px] font-bold text-slate-300">
                                    {workflowCompleted}/{workflowTotal || 0} analyzed
                                </span>
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${freshnessTone(workflowFreshness)}`}>
                                    source {workflowFreshness}
                                </span>
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${mcpRuntimeTone}`}>
                                    MCP server {mcpHealthy ? 'online' : 'offline'}
                                </span>
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${taskRuntimeTone}`}>
                                    Scheduler watchdog {watchdogRegistered ? 'active' : 'missing'}
                                </span>
                                <span className="rounded-full border border-white/10 bg-white/8 px-2.5 py-1 text-[11px] font-bold text-slate-300">
                                    Scheduler last {formatDateTime(scannerStatus?.scheduler_last_run_at)}
                                </span>
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${tradingViewTone}`}>
                                    TV technical {tradingViewConfigured ? tradingViewMode : 'not configured'}
                                </span>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <button
                                type="button"
                                onClick={onWorkflow}
                                disabled={workflowBusy}
                                className="rounded-lg border border-cyan-300/25 bg-cyan-300/12 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-300/18 disabled:cursor-wait disabled:opacity-60"
                            >
                                {workflowBusy ? 'Top3 분석 중...' : '신규 이벤트 Top3'}
                            </button>
                            {!subscriberMode && (
                                <button
                                    type="button"
                                    onClick={onForceWorkflow}
                                    disabled={workflowBusy}
                                    aria-label="Run MCP Top 3 Force refresh"
                                    className="rounded-lg border border-amber-300/25 bg-amber-300/12 px-3 py-2 text-xs font-black text-amber-100 transition hover:bg-amber-300/18 disabled:cursor-wait disabled:opacity-60"
                                >
                                    강제 MCP Top3 갱신
                                </button>
                            )}
                        </div>
                    </div>

                    <div className="mt-4 grid gap-2 md:grid-cols-4">
                        {[
                            ['Scanner', scannerPoolCount, 'candidate pool'],
                            ['Batch 5', workflow?.event_count ?? 0, 'new candidates'],
                            ['GraphRAG', workflowCompleted, workflowBusy ? 'running' : 'uploaded runs'],
                            ['Top 3', topWorkflow.length, workflowState === 'completed' ? 'ready for alert' : 'ranking'],
                        ].map(([label, value, caption], index) => (
                            <div key={String(label)} className="rounded-lg border border-white/10 bg-black/20 p-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">{String(label)}</span>
                                    <span className={`h-2.5 w-2.5 rounded-full ${workflowBusy && index <= 2 ? 'animate-pulse bg-cyan-300' : index === 3 && topWorkflow.length ? 'bg-emerald-300' : 'bg-white/25'}`} />
                                </div>
                                <div className="mt-2 text-xl font-black text-white">{String(value)}</div>
                                <div className="mt-1 text-[11px] font-bold text-slate-500">{String(caption)}</div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-3">
                        {[
                            ['MCP HTTP', mcpHealthy ? 'online' : 'offline', mcpServer?.server_version || mcpServer?.url || '127.0.0.1:8765'],
                            ['Startup Task', startupRegistered ? 'registered' : 'missing', startupTask?.last_result || startupTask?.state || '--'],
                            ['Watchdog', watchdogRegistered ? 'active' : 'missing', watchdogTask?.next_run_time || watchdogTask?.last_run_time || 'every 5m'],
                        ].map(([label, value, caption]) => (
                            <div key={String(label)} className="rounded-lg border border-white/10 bg-black/20 p-3">
                                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">{String(label)}</div>
                                <div className={`mt-1 text-lg font-black ${String(value) === 'online' || String(value) === 'registered' || String(value) === 'active' ? 'text-emerald-100' : 'text-amber-100'}`}>
                                    {String(value)}
                                </div>
                                <div className="mt-1 truncate text-[11px] font-bold text-slate-500">{String(caption)}</div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-black/30">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-cyan-300 via-violet-400 to-emerald-300 transition-all duration-500"
                            style={{ width: `${workflowPercent}%` }}
                        />
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-4">
                        {[
                            ['Forward Return', outcomeAvgReturn === undefined || outcomeAvgReturn === null ? '--' : formatSignedPct(outcomeAvgReturn), 'avg verified return'],
                            ['Hit Rate', outcomeHitRate === undefined || outcomeHitRate === null ? '--' : `${Number(outcomeHitRate).toFixed(1)}%`, 'forward hit/miss'],
                            ['Verified', outcomeEvaluated, `${outcomePending} pending`],
                            ['Replay Guard', replayGuardValue, 'no look-ahead'],
                        ].map(([label, value, caption]) => (
                            <div key={String(label)} className="rounded-lg border border-emerald-300/12 bg-emerald-300/[0.04] p-3">
                                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-emerald-200/60">{String(label)}</div>
                                <div className="mt-1 text-lg font-black text-white">{String(value)}</div>
                                <div className="mt-1 text-[11px] font-bold text-slate-500">{String(caption)}</div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-4">
                        {[
                            ['Evidence Grade', topEvidenceGrade, 'top candidate quality'],
                            ['Confidence Cap', Number.isFinite(topConfidenceCap) ? `${Math.round(topConfidenceCap * 100)}%` : '--', 'source/freshness bound'],
                            ['Reject Ledger', scannerRun?.rejected_candidate_count ?? 0, `${scannerRun?.screened_count ?? scannerPoolCount} screened`],
                            ['Outcome Advisory', advisoryHitRate, `${scannerAdvisory.evaluated_count ?? 0} evaluated · ${analysisArtifactsReady ? 'artifacts ready' : 'artifacts pending'}`],
                        ].map(([label, value, caption]) => (
                            <div key={String(label)} className="rounded-lg border border-cyan-300/12 bg-cyan-300/[0.04] p-3">
                                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-cyan-200/60">{String(label)}</div>
                                <div className="mt-1 text-lg font-black text-white">{String(value)}</div>
                                <div className="mt-1 truncate text-[11px] font-bold text-slate-500">{String(caption)}</div>
                            </div>
                        ))}
                    </div>

                    {(workflow?.graphrag || workflow?.source_freshness) && (
                        <div className="mt-3">
                            <SourceFreshnessMatrix
                                sourceFreshness={workflow.source_freshness}
                                graphrag={workflow.graphrag}
                            />
                        </div>
                    )}

                    {topWorkflow.length > 0 && (
                        <div className="mt-3 space-y-2">
                            {/* TOP 3 일괄 공유 버튼 */}
                            {workflow?.id && (
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-[10px] font-medium uppercase tracking-wider text-anthropic-darkMuted">
                                        TOP 3 결과
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => handleShareTop3(workflow.id!)}
                                        className="inline-flex items-center gap-1.5 rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 px-3 py-1.5 text-[11px] font-medium text-anthropic-darkText transition-colors hover:border-yellow-400/40 hover:text-yellow-300"
                                        title="카카오톡으로 TOP 3 공유"
                                    >
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M12 3C6.48 3 2 6.48 2 10.8c0 2.78 1.83 5.22 4.6 6.62l-1.12 4.05c-.1.36.31.65.62.45L11 19.2c.33.03.66.05 1 .05 5.52 0 10-3.48 10-7.8S17.52 3 12 3z"/>
                                        </svg>
                                        TOP 3 공유
                                    </button>
                                </div>
                            )}
                            <div className="grid gap-2 md:grid-cols-3">
                                {topWorkflow.map((item, index) => (
                                    <div key={`${item.symbol}-${item.run_id}-${index}`} className="rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 p-3">
                                        <div className="flex items-center justify-between">
                                            <div className="text-[10px] font-medium uppercase tracking-wider text-anthropic-orange">TOP {index + 1}</div>
                                            {workflow?.id && (
                                                <button
                                                    type="button"
                                                    onClick={() => handleShareRank(workflow.id!, index + 1)}
                                                    className="inline-flex h-6 w-6 items-center justify-center rounded text-anthropic-darkMuted transition-colors hover:bg-yellow-400/10 hover:text-yellow-300"
                                                    title={`카카오톡으로 TOP ${index + 1} 공유`}
                                                    aria-label={`Share TOP ${index + 1} to KakaoTalk`}
                                                >
                                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                                        <path d="M12 3C6.48 3 2 6.48 2 10.8c0 2.78 1.83 5.22 4.6 6.62l-1.12 4.05c-.1.36.31.65.62.45L11 19.2c.33.03.66.05 1 .05 5.52 0 10-3.48 10-7.8S17.52 3 12 3z"/>
                                                    </svg>
                                                </button>
                                            )}
                                        </div>
                                        <div className="mt-1 truncate text-sm font-medium text-anthropic-cream">
                                            {item.verdict?.target_display || item.target || item.candidate?.display_name || item.symbol}
                                        </div>
                                        <div className="mt-1 font-mono text-[11px] text-anthropic-darkMuted">
                                            {item.verdict?.symbol || item.symbol || item.candidate?.symbol}
                                            {item.verdict?.market && <span className="ml-1 text-anthropic-darkMuted/80">· {item.verdict.market}</span>}
                                            <span className="ml-1">· score {Math.round(Number(item.final_score || 0))}</span>
                                        </div>
                                        {item.verdict?.reference_date && (
                                            <div className="mt-0.5 font-mono text-[10px] text-anthropic-darkMuted/70">
                                                ref {String(item.verdict.reference_date).slice(0, 10)}
                                            </div>
                                        )}
                                        <div className="mt-2 inline-flex rounded-full border border-anthropic-darkLine bg-anthropic-dark px-2 py-1 text-[10px] font-medium text-anthropic-cream">
                                            {item.verdict?.action || 'HOLD'} {item.verdict?.confidence_pct || 0}%
                                        </div>
                                        {item.graphrag && (
                                            <div className="mt-2 flex flex-wrap gap-1 text-[9px] font-bold text-anthropic-darkMuted">
                                                <span className="rounded border border-amber-400/15 bg-amber-400/[0.06] px-1.5 py-0.5 text-amber-200/80">
                                                    L {item.graphrag.links ?? 0}
                                                </span>
                                                <span className="rounded border border-amber-400/15 bg-amber-400/[0.06] px-1.5 py-0.5 text-amber-200/80">
                                                    E {item.graphrag.entities ?? 0}
                                                </span>
                                                <span className="rounded border border-amber-400/15 bg-amber-400/[0.06] px-1.5 py-0.5 text-amber-200/80">
                                                    R {item.graphrag.relations ?? 0}
                                                </span>
                                            </div>
                                        )}
                                        <div className={`mt-2 inline-flex rounded-full border px-2 py-1 text-[10px] font-medium ${outcomeTone(item.outcome?.status, item.outcome?.hit)}`}>
                                            {item.outcome?.forward_return_pct === undefined || item.outcome?.forward_return_pct === null
                                                ? String(item.outcome?.status || 'pending')
                                                : `T${item.outcome.primary_horizon_days || '?'} ${formatSignedPct(item.outcome.forward_return_pct)}`}
                                            {' '}
                                            {item.outcome?.hit === true ? 'HIT' : item.outcome?.hit === false ? 'MISS' : 'PENDING'}
                                        </div>
                                        {item.outcome?.lookahead_safe && (
                                            <div className="mt-2 text-[10px] font-medium uppercase tracking-wider text-anthropic-darkMuted">
                                                replay-safe after {item.outcome.entry_date}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                            <Top3TradingViewCharts items={topWorkflow} />
                        </div>
                    )}
                    {workflow?.status === 'no_new_events' && (
                        <div className="mt-2 text-xs font-bold text-slate-400">No new scanner events for the MCP workflow.</div>
                    )}
                </div>
            </div>

            <div className="mt-4 grid gap-3 rounded-lg border border-white/10 bg-black/20 p-3 md:grid-cols-[1fr_auto]">
                <div>
                    <div className="text-[11px] font-black uppercase tracking-[0.18em] text-emerald-200/70">DeepSeek V2 Harness</div>
                    <div className="mt-1 text-sm font-bold text-slate-200">
                        스캐너 숫자는 그대로 두고 DeepSeek가 한글 근거 요약만 생성합니다.
                    </div>
                    {deepSeekSummary?.summary?.summary_title_ko && (
                        <div className="mt-2 rounded-lg border border-emerald-300/15 bg-emerald-300/8 p-3">
                            <div className="text-sm font-black text-emerald-100">{deepSeekSummary.summary.summary_title_ko}</div>
                            <p className="mt-1 text-xs font-semibold text-slate-300">{deepSeekSummary.summary.portfolio_note_ko}</p>
                            <div className="mt-2 flex flex-wrap gap-2">
                                {summaryCandidates.slice(0, 3).map((item) => (
                                    <span key={`${item.symbol}-${item.rank}`} className="rounded-full border border-white/10 bg-white/8 px-2.5 py-1 text-[11px] font-bold text-slate-200">
                                        {item.symbol} {item.action_ko || '요약'}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
                <div className="flex flex-wrap items-start gap-2 md:justify-end">
                    <button
                        type="button"
                        onClick={onDeepSeekSummary}
                        disabled={deepSeekBusy || (!scannerRun?.id && scannerBusy)}
                        className="rounded-lg border border-emerald-300/25 bg-emerald-300/12 px-3 py-2 text-xs font-black text-emerald-100 transition hover:bg-emerald-300/18 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {deepSeekState === 'summarizing' ? '요약 중...' : 'DeepSeek 요약'}
                    </button>
                    <button
                        type="button"
                        onClick={onSendDeepSeekTelegram}
                        disabled={deepSeekBusy || !scannerRun?.id}
                        className="rounded-lg border border-cyan-300/25 bg-cyan-300/12 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-300/18 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {deepSeekState === 'sending' ? '전송 중...' : deepSeekState === 'sent' ? '전송 완료' : '텔레그램 전송'}
                    </button>
                </div>
            </div>

            <div className="mt-4 grid gap-2">
                {topCandidates.length ? topCandidates.map((candidate) => (
                    <button
                        key={`${candidate.rank}-${candidate.symbol}-${candidate.display_name}`}
                        type="button"
                        onClick={() => onSelect(candidate)}
                        onDoubleClick={() => onDeepDive(candidate)}
                        className="grid gap-3 rounded-lg border border-white/10 bg-white/[0.06] p-3 text-left transition hover:border-emerald-300/30 hover:bg-white/[0.09] md:grid-cols-[44px_1.4fr_0.8fr_0.8fr_1fr_auto]"
                    >
                        <span className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-300/12 text-sm font-black text-emerald-100">
                            #{candidate.rank}
                        </span>
                        <span className="min-w-0">
                            <span className="block truncate text-base font-black text-white">{candidate.display_name}</span>
                            <span className="mt-0.5 block font-mono text-[11px] font-bold text-slate-400">{candidate.symbol} · {candidate.market || 'KR'} · {candidate.horizon}</span>
                        </span>
                        <span>
                            <span className="block text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">Alpha</span>
                            <span className="text-2xl font-black text-emerald-200">{Math.round(candidate.alpha_score)}</span>
                        </span>
                        <span>
                            <span className="block text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">Risk</span>
                            <span className="text-2xl font-black text-amber-200">{Math.round(candidate.risk_score)}</span>
                        </span>
                        <span className="min-w-0">
                            <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-black ${alphaActionTone(candidate.action)}`}>
                                {candidate.action}
                            </span>
                            <span className="mt-1 block truncate text-xs font-semibold text-slate-400">
                                {candidate.strategy_tags.slice(0, 3).join(' · ') || 'multi-signal'}
                            </span>
                            <span className="mt-1 block truncate text-xs font-semibold text-slate-500">
                                {formatAlphaEvidence(candidate)}
                            </span>
                            <span className="mt-1 block truncate font-mono text-[11px] font-black text-emerald-200/80">
                                {formatAlphaAnalysis(candidate)}
                            </span>
                            {formatTradingViewSignal(candidate) && (
                                <span className={`mt-1 inline-flex max-w-full rounded-full border px-2 py-0.5 text-[10px] font-black ${tradingViewSignalTone(candidate)}`}>
                                    <span className="truncate">{formatTradingViewSignal(candidate)}</span>
                                </span>
                            )}
                        </span>
                        <span className="flex items-center gap-2 md:justify-end">
                            <span className="font-mono text-xs font-black text-slate-300">{formatPrice(candidate.price)}</span>
                            <span
                                role="button"
                                tabIndex={0}
                                onClick={(event) => {
                                    event.stopPropagation();
                                    onDeepDive(candidate);
                                }}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                        event.preventDefault();
                                        event.stopPropagation();
                                        onDeepDive(candidate);
                                    }
                                }}
                                className="rounded-lg border border-cyan-300/25 bg-cyan-300/10 px-3 py-2 text-xs font-black text-cyan-100"
                            >
                                Deep Dive
                            </span>
                        </span>
                    </button>
                )) : (
                    <div className="rounded-lg border border-dashed border-white/12 bg-white/[0.04] px-4 py-6 text-sm font-bold text-slate-400">
                        아직 검출된 후보가 없습니다. Run scanner로 KR 시장 후보를 먼저 산출하세요.
                    </div>
                )}
            </div>
        </section>
    );
}

function alphaEndpointTone(status?: string): string {
    const value = String(status || '').toLowerCase();
    if (value === 'ready' || value === 'optional_ready') return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (value === 'limited' || value === 'optional_limited') return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
    if (value === 'blocked') return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    return 'border-cyan-300/20 bg-cyan-300/10 text-cyan-100';
}

function AlphaEndpointBlueprintCard({ blueprint, resourceSnapshot }: {
    blueprint: MiroFishAlphaEndpointBlueprint | null;
    resourceSnapshot: MiroFishMcpResourceSnapshot | null;
}) {
    const readiness = blueprint?.source_readiness || {};
    const endpoints = (blueprint?.endpoints || []).filter((endpoint) => ['P0', 'P1'].includes(String(endpoint.priority))).slice(0, 5);
    const nextActions = (blueprint?.next_actions || []).slice(0, 3);
    const covered = Number(readiness.required_covered || 0);
    const total = Number(readiness.required_total || 0);
    const status = String(readiness.status || 'unknown');
    const statusTone = alphaEndpointTone(status === 'ready' ? 'ready' : status === 'limited' ? 'limited' : status === 'blocked' ? 'blocked' : 'planned');

    return (
        <section className="rounded-xl border border-cyan-300/15 bg-slate-950/55 p-4 shadow-[0_18px_60px_rgba(14,165,233,0.08)]">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-cyan-200/75">
                        <i className="fas fa-shield-halved text-cyan-200" />
                        Alpha Evidence
                    </div>
                    <h2 className="mt-1 text-lg font-black text-white">Top3 검출 데이터 게이트</h2>
                    <p className="mt-1 text-xs font-semibold leading-5 text-slate-400">
                        수급, 공시, 공매도/신용, 레짐, 성과메모리 엔드포인트가 Top3 판단에 붙을 준비 상태입니다.
                    </p>
                </div>
                <span className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-black ${statusTone}`}>
                    {status.toUpperCase()} {total ? `${covered}/${total}` : ''}
                </span>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2">
                {[
                    ['P0', blueprint?.p0_count ?? 0, 'core gates'],
                    ['Resources', resourceSnapshot?.catalog_count ?? '--', 'catalog'],
                    ['Missing', readiness.required_missing ?? '--', 'required'],
                ].map(([label, value, caption]) => (
                    <div key={String(label)} className="rounded-lg border border-white/10 bg-black/20 p-3">
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">{String(label)}</div>
                        <div className="mt-1 text-xl font-black text-white">{String(value)}</div>
                        <div className="mt-1 text-[11px] font-bold text-slate-500">{String(caption)}</div>
                    </div>
                ))}
            </div>

            <div className="mt-3 space-y-2">
                {endpoints.length ? endpoints.map((endpoint) => (
                    <div key={endpoint.id} className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
                        <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-0.5 text-[10px] font-black text-cyan-100">{endpoint.priority}</span>
                                    <span className="truncate text-sm font-black text-white">{endpoint.name}</span>
                                </div>
                                <div className="mt-1 truncate font-mono text-[10px] font-semibold text-slate-500">
                                    {endpoint.mcp_tool || endpoint.internal_path}
                                </div>
                            </div>
                            <span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-black ${alphaEndpointTone(endpoint.current_status)}`}>
                                {String(endpoint.current_status || 'planned').toUpperCase()}
                            </span>
                        </div>
                        <p className="mt-2 text-[11px] font-semibold leading-4 text-slate-400">{endpoint.alpha_impact}</p>
                    </div>
                )) : (
                    <div className="rounded-lg border border-dashed border-white/12 bg-white/[0.04] px-3 py-4 text-xs font-bold text-slate-400">
                        Alpha endpoint blueprint 대기 중입니다.
                    </div>
                )}
            </div>

            {nextActions.length > 0 && (
                <div className="mt-3 rounded-lg border border-amber-300/15 bg-amber-300/8 p-3">
                    <div className="text-[10px] font-black uppercase tracking-[0.16em] text-amber-100/80">Next Attach</div>
                    <div className="mt-2 space-y-1">
                        {nextActions.map((action) => (
                            <div key={String(action.id)} className="truncate text-[11px] font-bold text-amber-50/90">
                                {String(action.priority || '')} {String(action.name || action.id || '')}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </section>
    );
}

function AutonomousMcpPanel({
    status,
    state,
    result,
    learning,
    errorText,
    confirmation,
    sharedSecret,
    onConfirmationChange,
    onSharedSecretChange,
    onRefresh,
    onDetectionDryRun,
    onAnalysisDryRun,
    onLearningPreview,
    onSendLatestTelegram,
}: {
    status: MiroFishAutonomousStatus | null;
    state: AutonomousPanelState;
    result?: MiroFishAutonomousActionResult | null;
    learning?: MiroFishAutonomousLearningFeedback | null;
    errorText?: string | null;
    confirmation: string;
    sharedSecret: string;
    onConfirmationChange: (value: string) => void;
    onSharedSecretChange: (value: string) => void;
    onRefresh: () => void;
    onDetectionDryRun: () => void;
    onAnalysisDryRun: () => void;
    onLearningPreview: () => void;
    onSendLatestTelegram: () => void;
}) {
    const busy = state === 'checking' || state === 'running' || state === 'sending';
    const mutationEnabled = Boolean(status?.mutation_enabled);
    const secretRequired = Boolean(status?.shared_secret_configured);
    const phrase = status?.send_confirmation_phrase || 'SEND_MIROFISH_AUTONOMOUS_ALERT';
    const canSend = mutationEnabled && confirmation === phrase && (!secretRequired || sharedSecret.trim().length > 0) && !busy;
    const learningView = learning || status?.learning || null;
    const alphaMemory = learningView?.alpha_memory;
    const strongestMemory = alphaMemory?.strongest_positive || null;
    const weakestMemory = alphaMemory?.weakest_negative || null;
    const memorySampleCount = Number(alphaMemory?.sample_count || 0);
    const scoreProfile = alphaMemory?.score_profile || {};
    const strategyCohorts = Array.isArray(alphaMemory?.cohorts?.strategy_tags) ? alphaMemory.cohorts.strategy_tags : [];
    const signalCohorts = Array.isArray(alphaMemory?.cohorts?.signal_quality) ? alphaMemory.cohorts.signal_quality : [];
    const visibleCohorts = (strategyCohorts.length ? strategyCohorts : signalCohorts).slice(0, 5);
    const eventItems = result?.events || [];
    const topSymbols = result?.top_symbols || [];
    const statusTone = state === 'error'
        ? 'border-rose-300/25 bg-rose-300/10 text-rose-100'
        : state === 'ready' || state === 'sent'
            ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
            : busy
                ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100'
                : 'border-white/10 bg-white/8 text-slate-300';
    const mcpServer = status?.runtime?.mcp_server;
    const startupTask = status?.runtime?.startup_task;
    const watchdogTask = status?.runtime?.watchdog_task;
    const mcpHealthy = Boolean(mcpServer?.healthy);
    const startupRegistered = Boolean(startupTask?.registered);
    const watchdogRegistered = Boolean(watchdogTask?.registered);

    return (
        <section className="rounded-lg border border-cyan-300/10 bg-slate-950/45 p-3">
            <div className="flex flex-col gap-3">
                <div>
                    <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-cyan-200/70">
                        <i className="fas fa-robot text-cyan-200" />
                        Autonomous MCP Control
                    </div>
                    <h2 className="mt-1 text-base font-black text-white">Admin pre-service test harness</h2>
                    <p className="mt-1 text-xs font-semibold leading-relaxed text-slate-400">
                        Dry-run first: detect candidates, preview scan-analysis, inspect learning feedback, then gated Telegram send for the latest workflow.
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${statusTone}`}>
                        {state === 'idle' ? 'IDLE' : state.toUpperCase()}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${mutationEnabled ? 'border-amber-300/25 bg-amber-300/10 text-amber-100' : 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'}`}>
                        {mutationEnabled ? 'mutation on' : 'dry-run locked'}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${status?.telegram?.personal_configured ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-white/10 bg-white/8 text-slate-300'}`}>
                        personal Telegram {status?.telegram?.personal_configured ? 'ready' : 'off'}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold ${secretRequired ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100' : 'border-white/10 bg-white/8 text-slate-300'}`}>
                        shared secret {secretRequired ? 'required' : 'not set'}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${mcpHealthy ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-rose-300/25 bg-rose-300/10 text-rose-100'}`}>
                        MCP HTTP {mcpHealthy ? 'online' : 'offline'}
                    </span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${watchdogRegistered ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-amber-300/25 bg-amber-300/10 text-amber-100'}`}>
                        Watchdog {watchdogRegistered ? '5m on' : 'missing'}
                    </span>
                </div>
            </div>

            {errorText && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100">
                    {errorText}
                </div>
            )}

            <div className="mt-4 grid gap-2 md:grid-cols-5">
                {[
                    ['Tools', status?.tools?.length ?? 0, 'MCP exposed actions'],
                    ['Resources', status?.resources?.length ?? 0, 'status and artifacts'],
                    ['Hit Rate', learningView?.hit_rate_pct === undefined || learningView?.hit_rate_pct === null ? '--' : `${Number(learningView.hit_rate_pct).toFixed(1)}%`, `${learningView?.evaluated_count ?? 0} evaluated`],
                    ['Avg Return', learningView?.average_forward_return_pct === undefined || learningView?.average_forward_return_pct === null ? '--' : formatSignedPct(learningView.average_forward_return_pct), 'advisory only'],
                    ['Alpha Memory', alphaMemory?.available ? memorySampleCount : '--', strongestMemory?.key ? `best ${String(strongestMemory.key)}` : 'waiting outcomes'],
                ].map(([label, value, caption]) => (
                    <div key={String(label)} className="rounded-lg border border-white/10 bg-black/20 p-3">
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">{String(label)}</div>
                        <div className="mt-1 text-xl font-black text-white">{String(value)}</div>
                        <div className="mt-1 text-[11px] font-bold text-slate-500">{String(caption)}</div>
                    </div>
                ))}
            </div>

            <div className="mt-3 grid gap-2 md:grid-cols-3">
                {[
                    ['MCP HTTP', mcpHealthy ? 'online' : 'offline', mcpServer?.server_version || mcpServer?.url || 'local probe'],
                    ['Startup Task', startupRegistered ? 'registered' : 'missing', startupTask?.last_result || startupTask?.state || startupTask?.error || '--'],
                    ['Watchdog Task', watchdogRegistered ? 'active' : 'missing', watchdogTask?.next_run_time || watchdogTask?.last_run_time || watchdogTask?.error || '--'],
                ].map(([label, value, caption]) => (
                    <div key={String(label)} className="rounded-lg border border-cyan-300/12 bg-cyan-300/[0.04] p-3">
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-cyan-200/60">{String(label)}</div>
                        <div className={`mt-1 text-lg font-black ${String(value) === 'online' || String(value) === 'registered' || String(value) === 'active' ? 'text-emerald-100' : 'text-amber-100'}`}>
                            {String(value)}
                        </div>
                        <div className="mt-1 truncate text-[11px] font-bold text-slate-500">{String(caption)}</div>
                    </div>
                ))}
            </div>

            {alphaMemory?.available && (
                <div className="mt-3 rounded-lg border border-emerald-300/15 bg-emerald-300/[0.05] p-3">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div>
                            <div className="text-[11px] font-black uppercase tracking-[0.18em] text-emerald-100/80">Alpha Memory</div>
                            <div className="mt-1 text-sm font-bold text-slate-200">
                                Forward outcomes are tied back to the original alpha/risk/tag/CIO feature snapshot.
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-[11px] font-black text-emerald-100">
                                samples {memorySampleCount}
                            </span>
                            {strongestMemory?.key && (
                                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-[11px] font-black text-cyan-100">
                                    best {String(strongestMemory.key)} {strongestMemory.hit_rate_pct ?? '--'}%
                                </span>
                            )}
                            {weakestMemory?.key && (
                                <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-2.5 py-1 text-[11px] font-black text-amber-100">
                                    weak {String(weakestMemory.key)} {weakestMemory.average_forward_return_pct ?? '--'}%
                                </span>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <div className="mt-3 rounded-lg border border-amber-300/15 bg-amber-300/[0.055] p-3">
                <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                        <div className="text-[11px] font-black uppercase tracking-[0.18em] text-amber-100/85">성과검증 보드</div>
                        <div className="mt-1 text-sm font-black text-white">Top 3 추천이 실제 이후 수익으로 이어졌는지 검증합니다.</div>
                        <div className="mt-1 text-xs font-semibold text-amber-100/70">
                            검증 기준: 추천일 이후 가격 데이터만 사용, 미래 데이터 누수 없이 hit rate / 평균 수익률 / 실패 신호를 분리합니다.
                        </div>
                    </div>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${alphaMemory?.available ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-amber-300/25 bg-amber-300/10 text-amber-100'}`}>
                        {alphaMemory?.available ? '검증 샘플 연결됨' : '검증 샘플 대기'}
                    </span>
                </div>
                <div className="mt-3 grid gap-2 md:grid-cols-4">
                    {[
                        ['검증 대상', alphaMemory?.available ? `${memorySampleCount}건` : '--', `${learningView?.evaluated_count ?? 0} evaluated`],
                        ['승률', learningView?.hit_rate_pct === undefined || learningView?.hit_rate_pct === null ? '--' : `${Number(learningView.hit_rate_pct).toFixed(1)}%`, 'BUY/HOLD 결과 hit'],
                        ['평균 수익률', learningView?.average_forward_return_pct === undefined || learningView?.average_forward_return_pct === null ? '--' : formatSignedPct(learningView.average_forward_return_pct), 'forward return'],
                        ['Look-ahead', learningView?.lookahead_safe === true ? 'safe' : learningView?.lookahead_safe === false ? '주의' : 'pending', 'entry 이후 데이터만'],
                    ].map(([label, value, caption]) => (
                        <div key={String(label)} className="rounded-lg border border-white/10 bg-black/25 p-3">
                            <div className="text-[10px] font-black uppercase tracking-[0.14em] text-amber-100/55">{String(label)}</div>
                            <div className="mt-1 text-xl font-black text-white">{String(value)}</div>
                            <div className="mt-1 text-[11px] font-bold text-slate-400">{String(caption)}</div>
                        </div>
                    ))}
                </div>
                {alphaMemory?.available ? (
                    <div className="mt-3 grid gap-3 lg:grid-cols-[1.05fr_1.25fr]">
                        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">Hit vs Miss Score Profile</div>
                            <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                {[
                                    ['Alpha', scoreProfile.hit_avg_alpha, scoreProfile.miss_avg_alpha],
                                    ['Risk', scoreProfile.hit_avg_risk, scoreProfile.miss_avg_risk],
                                    ['Final', scoreProfile.hit_avg_final_score, scoreProfile.miss_avg_final_score],
                                ].map(([label, hit, miss]) => (
                                    <div key={String(label)} className="rounded-lg border border-white/10 bg-white/[0.04] p-2">
                                        <div className="text-[10px] font-black uppercase tracking-[0.12em] text-slate-500">{String(label)}</div>
                                        <div className="mt-1 flex items-baseline justify-between gap-2">
                                            <span className="text-sm font-black text-emerald-100">H {formatMetricNumber(hit)}</span>
                                            <span className="text-sm font-black text-rose-100">M {formatMetricNumber(miss)}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                            <div className="flex items-center justify-between gap-2">
                                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">Signal Cohorts</div>
                                {strongestMemory?.key && (
                                    <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-0.5 text-[10px] font-black text-emerald-100">
                                        strongest {String(strongestMemory.key)}
                                    </span>
                                )}
                            </div>
                            <div className="mt-2 space-y-2">
                                {visibleCohorts.length ? visibleCohorts.map((cohort) => (
                                    <div key={String(cohort.key)} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2">
                                        <div className="truncate text-xs font-black text-slate-100">{String(cohort.key)}</div>
                                        <div className="text-[11px] font-black text-emerald-100">{cohort.hit_rate_pct ?? '--'}%</div>
                                        <div className={`text-[11px] font-black ${Number(cohort.average_forward_return_pct) >= 0 ? 'text-cyan-100' : 'text-rose-100'}`}>
                                            {formatSignedPct(cohort.average_forward_return_pct)}
                                        </div>
                                    </div>
                                )) : (
                                    <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-bold text-slate-400">
                                        아직 코호트별 성과 샘플이 부족합니다.
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="mt-3 rounded-lg border border-dashed border-amber-300/20 bg-black/20 px-3 py-2 text-xs font-bold text-amber-100/75">
                        워크플로우 Top 3가 생성되고 이후 가격 데이터가 쌓이면 이 영역에 실제 성과 검증이 표시됩니다.
                    </div>
                )}
            </div>

            <details className="group mt-3 rounded-lg border border-white/10 bg-white/[0.03]">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-black text-slate-200 [&::-webkit-details-marker]:hidden">
                    <span>전송/실행 제어</span>
                    <span className="text-[10px] uppercase tracking-wider text-slate-500 transition-transform group-open:rotate-180">▼</span>
                </summary>
                <div className="grid gap-3 border-t border-white/10 p-3 lg:grid-cols-2">
                    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">Mutation gate</div>
                        <input
                            value={confirmation}
                            onChange={(event) => onConfirmationChange(event.target.value)}
                            placeholder={phrase}
                            className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 font-mono text-xs font-bold text-slate-100 outline-none focus:border-cyan-300/40"
                        />
                        <div className="mt-1 text-[11px] font-bold text-slate-500">Required only for real Telegram send.</div>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">Shared secret</div>
                        <input
                            type="password"
                            value={sharedSecret}
                            onChange={(event) => onSharedSecretChange(event.target.value)}
                            disabled={!secretRequired}
                            placeholder={secretRequired ? 'required by server' : 'not required'}
                            className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 font-mono text-xs font-bold text-slate-100 outline-none focus:border-cyan-300/40 disabled:opacity-50"
                        />
                        <div className="mt-1 text-[11px] font-bold text-slate-500">Never stored; posted only with the send request.</div>
                    </div>
                    <div className="flex flex-wrap items-start gap-2 lg:col-span-2">
                        <button type="button" onClick={onRefresh} disabled={busy} className="rounded-lg border border-white/10 bg-white/8 px-3 py-2 text-xs font-black text-slate-200 transition hover:bg-white/12 disabled:cursor-wait disabled:opacity-60">
                            Refresh status
                        </button>
                        <button type="button" onClick={onDetectionDryRun} disabled={busy} className="rounded-lg border border-emerald-300/25 bg-emerald-300/12 px-3 py-2 text-xs font-black text-emerald-100 transition hover:bg-emerald-300/18 disabled:cursor-wait disabled:opacity-60">
                            Detection dry-run
                        </button>
                        <button type="button" onClick={onAnalysisDryRun} disabled={busy} className="rounded-lg border border-cyan-300/25 bg-cyan-300/12 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-300/18 disabled:cursor-wait disabled:opacity-60">
                            Analysis dry-run
                        </button>
                        <button type="button" onClick={onLearningPreview} disabled={busy} className="rounded-lg border border-violet-300/25 bg-violet-300/12 px-3 py-2 text-xs font-black text-violet-100 transition hover:bg-violet-300/18 disabled:cursor-wait disabled:opacity-60">
                            Learning preview
                        </button>
                        <button type="button" onClick={onSendLatestTelegram} disabled={!canSend} className="rounded-lg border border-amber-300/25 bg-amber-300/12 px-3 py-2 text-xs font-black text-amber-100 transition hover:bg-amber-300/18 disabled:cursor-not-allowed disabled:opacity-45">
                            {state === 'sending' ? 'Sending...' : 'Send latest Telegram'}
                        </button>
                    </div>
                </div>
            </details>

            {(result || learningView?.recommendations?.length) && (
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                    {result && (
                        <div className="rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] p-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="text-[11px] font-black uppercase tracking-[0.18em] text-cyan-100/80">Last action result</div>
                                <span className="rounded-full border border-white/10 bg-white/8 px-2.5 py-1 text-[11px] font-black text-slate-200">
                                    {result.status || (result.ok ? 'ok' : 'unknown')}
                                </span>
                            </div>
                            <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                <div><div className="text-[10px] font-black uppercase text-slate-500">Run</div><div className="truncate font-mono text-xs font-bold text-slate-200">{result.run_id || result.workflow_id || '--'}</div></div>
                                <div><div className="text-[10px] font-black uppercase text-slate-500">Events</div><div className="text-sm font-black text-white">{result.new_event_count ?? result.event_count ?? 0}</div></div>
                                <div><div className="text-[10px] font-black uppercase text-slate-500">Telegram</div><div className="text-sm font-black text-white">{result.telegram_sent ? 'sent' : result.telegram_skipped_reason || 'not sent'}</div></div>
                            </div>
                            {(eventItems.length > 0 || topSymbols.length > 0) && (
                                <div className="mt-3 flex flex-wrap gap-2">
                                    {eventItems.slice(0, 5).map((event) => (
                                        <span key={event.key || event.symbol} className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-[11px] font-bold text-emerald-100">
                                            {event.symbol} alpha {Math.round(Number(event.alpha_score || 0))}
                                        </span>
                                    ))}
                                    {topSymbols.slice(0, 5).map((symbol, index) => (
                                        <span key={`${symbol}-${index}`} className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2.5 py-1 text-[11px] font-bold text-cyan-100">
                                            TOP {index + 1} {symbol}
                                        </span>
                                    ))}
                                </div>
                            )}
                            {result.resource_links && (
                                <div className="mt-3 flex flex-wrap gap-2">
                                    {Object.entries(result.resource_links).map(([key, value]) => (
                                        <span key={key} className="rounded-full border border-white/10 bg-white/8 px-2.5 py-1 font-mono text-[10px] font-bold text-slate-400">
                                            {key}: {value}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                    {learningView?.recommendations?.length ? (
                        <div className="rounded-lg border border-violet-300/15 bg-violet-300/[0.06] p-3">
                            <div className="text-[11px] font-black uppercase tracking-[0.18em] text-violet-100/80">Learning feedback</div>
                            <div className="mt-2 space-y-2">
                                {learningView.recommendations.slice(0, 4).map((item, index) => (
                                    <div key={`${item.type}-${index}`} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
                                        <div className="text-xs font-black text-violet-100">{String(item.action || item.type || 'recommendation')}</div>
                                        <div className="mt-1 text-xs font-semibold text-slate-400">{String(item.reason || item.suggested_change || '')}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                </div>
            )}

            <div className="mt-3 text-[11px] font-bold text-slate-500">
                Checked {formatDateTime(status?.checked_at)} · learning is advisory and does not mutate production scoring weights.
            </div>
        </section>
    );
}

function analystPositions(analysts: MiroFishAnalyst[]): MiroFishNode[] {
    const xs = [31, 43, 55, 67, 76, 83, 89, 24, 50, 71];
    return analysts.map((analyst, index) => ({
        label: analyst.name,
        x: xs[index] ?? 50,
        y: index > 6 ? 82 : 75 + (index % 2),
    }));
}

function Stepper({ phase }: { phase: number }) {
    return (
        <section className="rounded-xl border border-anthropic-darkLine bg-anthropic-dark p-4 sm:p-5">
            {/* 모바일: 가로 스크롤 — 데스크탑: 5열 grid */}
            <div className="-mx-4 sm:mx-0 overflow-x-auto sm:overflow-visible px-4 sm:px-0 snap-x snap-mandatory sm:snap-none">
                <div className="relative flex gap-4 min-w-max sm:min-w-0 sm:grid sm:grid-cols-5 sm:gap-3">
                    <div className="absolute left-[10%] right-[10%] top-9 sm:top-12 hidden h-px bg-anthropic-darkLine sm:block" />
                    {impactSteps.map((step, index) => {
                        const active = index + 1 <= phase;
                        return (
                            <div key={step.no} className="relative flex flex-col items-center text-center w-20 sm:w-auto shrink-0 sm:shrink snap-start">
                                <div className={`grid h-14 w-14 sm:h-[72px] sm:w-[72px] place-items-center rounded-xl border text-sm font-medium transition-colors ${active ? 'border-anthropic-orange bg-anthropic-orange text-white' : 'border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkMuted'}`}>
                                    {active ? <i className={`fas ${step.icon} text-base sm:text-lg`} /> : step.no}
                                </div>
                                <div className={`mt-2 sm:mt-3 text-[11px] sm:text-xs font-medium ${active ? 'text-anthropic-cream' : 'text-anthropic-darkMuted'}`}>{step.ko}</div>
                                <div className={`mt-0.5 text-[9px] sm:text-[10px] font-medium tracking-wider ${active ? 'text-anthropic-orange' : 'text-anthropic-darkMuted'}`}>{step.en}</div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </section>
    );
}

function TargetCard({ run }: { run: MiroFishRun }) {
    const change = Number(run.change_pct ?? 0);
    const price = formatPrice(run.price);
    const market = String(run.market || '').toUpperCase();
    const currency = market.includes('NASDAQ') || market.includes('NYSE') || market.includes('AMEX') || market.includes('US')
        ? 'USD'
        : 'KRW';
    return (
        <section className="rounded-xl border border-white/30 bg-white/[0.88] p-6 text-slate-900 shadow-[0_22px_80px_rgba(14,165,233,0.12)]">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-slate-400">
                        분석 대상
                        <span className="h-2 w-2 rounded-full bg-violet-600" />
                        <span className="text-violet-600">실시간 스트리밍</span>
                        <i className="fas fa-signal text-violet-500" />
                    </div>
                    <h2 className="mt-2 break-words text-4xl font-black tracking-tight">{run.display_name || run.target}</h2>
                    <div className="mt-5 h-1.5 w-72 max-w-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400" />
                </div>
                <div className="text-left md:text-right">
                    <div className="text-5xl font-black tracking-tight">{price}<span className="ml-2 text-lg font-bold text-slate-400">{currency}</span></div>
                    <div className={`mt-2 inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-black ${change >= 0 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'}`}>
                        <i className={`fas ${change >= 0 ? 'fa-caret-up' : 'fa-caret-down'}`} />
                        {change.toFixed(2)}%
                    </div>
                </div>
            </div>
        </section>
    );
}

function KnowledgeGraph({ phase, run }: { phase: number; run: MiroFishRun }) {
    const isGraphReady = phase >= 3;
    const isPredictionReady = phase >= 4;
    const isVerdictReady = phase >= 5;
    const layers = visibleLayers(run, phase);
    const graphNodes = run.graph_nodes?.length ? run.graph_nodes : [];
    const analysts = run.analysts?.length ? run.analysts : [];
    const analystNodes = analystPositions(analysts);
    const predictionNodes = run.prediction_nodes?.length ? run.prediction_nodes : [];
    const verdict = run.verdict;
    const progressPercent = Math.max(0, Math.min(100, Number(run.progress?.percent || (isVerdictReady ? 100 : phase * 18))));
    const elapsedMs = run.progress?.elapsed_ms || run.performance?.elapsed_ms || 0;
    const elapsedSeconds = Math.max(1, elapsedMs / 1000);
    const eventCount = run.events?.length || run.logs?.length || run.performance?.events_count || 0;
    const edgeCount = run.graph_artifact?.edges?.length || run.performance?.graph_edges || 0;
    const streamRate = Math.max(1, Math.round((graphNodes.length + predictionNodes.length + analysts.length + edgeCount) / elapsedSeconds));
    const confidence = verdict?.confidence ?? (isVerdictReady ? 64 : Math.min(88, 42 + progressPercent));
    const activePhase = run.progress?.current_label || (phase >= 5 ? 'Final Verdict' : phase >= 4 ? 'Agent Debate' : phase >= 3 ? 'GraphRAG' : 'Target Intake');
    const graphLoad = Math.min(100, Math.round(((graphNodes.length + edgeCount) / Math.max(1, graphNodes.length + edgeCount + 8)) * 100));

    return (
        <section className="relative min-h-[500px] overflow-hidden rounded-xl border border-white/30 bg-[radial-gradient(circle_at_58%_70%,rgba(16,185,129,0.16),transparent_22%),radial-gradient(circle_at_28%_26%,rgba(99,102,241,0.16),transparent_24%),linear-gradient(180deg,rgba(248,250,252,0.96),rgba(226,232,240,0.94))] p-5 text-slate-900 shadow-[0_26px_90px_rgba(15,23,42,0.18)]">
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.13)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.11)_1px,transparent_1px)] bg-[size:44px_44px]" />
            <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/65 to-transparent" />
            {isGraphReady && (
                <div
                    className="pointer-events-none absolute left-0 right-0 z-[1] h-px bg-gradient-to-r from-transparent via-blue-500/70 to-transparent shadow-[0_0_28px_rgba(59,130,246,0.75)] transition-all duration-700"
                    style={{ top: `${Math.min(88, Math.max(15, progressPercent))}%` }}
                />
            )}
            <div className="absolute left-5 top-5 z-20 w-48 rounded-xl bg-white/80 p-4 shadow-xl shadow-slate-300/30">
                <div className="mb-3 text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">레이어</div>
                <div className="space-y-3">
                    {layers.map((layer) => (
                        <div key={layer.label} className="flex items-center gap-3 text-xs font-black">
                            <span className={`h-3 w-3 rounded-full ${layer.color} shadow`} />
                            <span className="flex-1">{layer.label}</span>
                            <span className="text-slate-500">{layer.count}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="absolute left-1/2 top-6 z-20 -translate-x-1/2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-500 shadow">
                지식 그래프 <span className="ml-2 inline-block h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div className="absolute right-5 top-20 z-30 w-56 rounded-2xl border border-slate-200/80 bg-white/88 p-4 shadow-2xl shadow-slate-400/20 backdrop-blur">
                <div className="flex items-center justify-between">
                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-slate-400">Live Compute</div>
                    <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-black text-emerald-700">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                        STREAM
                    </span>
                </div>
                <div className="mt-3 text-sm font-black text-slate-900">{activePhase}</div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400 transition-all duration-500" style={{ width: `${progressPercent}%` }} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] font-black">
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">PROGRESS</div><div className="text-blue-700">{progressPercent}%</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">RATE</div><div className="text-violet-700">{streamRate}/s</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">GRAPH</div><div className="text-emerald-700">{graphNodes.length}/{edgeCount}</div></div>
                    <div className="rounded-lg bg-slate-100 px-2 py-2"><div className="text-slate-400">CONF</div><div className="text-amber-700">{Math.round(confidence)}%</div></div>
                </div>
            </div>
            {isPredictionReady && (
                <div className="absolute right-40 top-6 z-20 hidden items-center gap-2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.12em] text-slate-500 shadow lg:flex">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    <span>강세 <b className="text-emerald-500">{verdict?.bullish ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-amber-400" />
                    <span>중립 <b className="text-amber-500">{verdict?.neutral ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-rose-500" />
                    <span>약세 <b className="text-rose-500">{verdict?.bearish ?? 0}</b></span>
                </div>
            )}

            {isGraphReady ? (
                <>
                    <svg className="absolute inset-0 z-[2] h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                        {graphNodes.map((node, index) => (
                            <line key={`${node.label}-${index}`} x1="30" y1="31" x2={node.x ?? 50} y2={node.y ?? 50} stroke="rgba(99,102,241,0.42)" strokeWidth="0.34" strokeDasharray="1.1 1.4">
                                <animate attributeName="stroke-dashoffset" from="0" to="-8" dur={`${2.1 + (index % 5) * 0.18}s`} repeatCount="indefinite" />
                            </line>
                        ))}
                        {isPredictionReady && predictionNodes.map((node, index) => {
                            const source = analystNodes[index] ?? analystNodes[0];
                            return (
                                <line key={`pred-${node.label}`} x1={source.x} y1={source.y} x2={node.x ?? 50} y2={node.y ?? 65} stroke="rgba(245,158,11,0.48)" strokeWidth="0.42" strokeDasharray="1.3 1.6">
                                    <animate attributeName="stroke-dashoffset" from="0" to="-9" dur={`${1.7 + (index % 4) * 0.16}s`} repeatCount="indefinite" />
                                </line>
                            );
                        })}
                        {isVerdictReady && predictionNodes.map((node) => (
                            <line key={`verdict-${node.label}`} x1={node.x ?? 50} y1={node.y ?? 65} x2="58" y2="92" stroke="rgba(16,185,129,0.52)" strokeWidth="0.48" strokeDasharray="1.4 1.2">
                                <animate attributeName="stroke-dashoffset" from="0" to="-10" dur="1.65s" repeatCount="indefinite" />
                            </line>
                        ))}
                    </svg>

                    <div className="absolute left-[30%] top-[31%] z-10 -translate-x-1/2 -translate-y-1/2 text-center">
                        <div className="absolute left-1/2 top-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 animate-ping rounded-full border border-red-400/35" />
                        <div className="relative grid h-16 w-16 place-items-center rounded-full border-2 border-red-400 bg-red-500/15 text-red-500 shadow-[0_0_0_8px_rgba(248,113,113,0.13),0_0_36px_rgba(248,113,113,0.30)]">
                            <i className="fas fa-warning" />
                        </div>
                        <div className="-mt-1 max-w-[140px] truncate rounded border border-red-300 bg-white px-2 py-0.5 text-[10px] font-black">{run.display_name || run.target}</div>
                    </div>

                    {graphNodes.map((node, index) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 50}%` }}>
                            <div className="mx-auto h-5 w-5 animate-pulse rounded-full border-2 border-indigo-400 bg-indigo-300/45 shadow-[0_0_18px_rgba(99,102,241,0.28)]" style={{ animationDelay: `${(index % 6) * 120}ms` }} />
                            <div className="-mt-0.5 max-w-[78px] truncate rounded border border-indigo-200 bg-white px-1.5 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {analystNodes.map((node, index) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x}%`, top: `${node.y}%` }}>
                            <div className="mx-auto h-8 w-8 animate-pulse rounded-full border-2 border-violet-400 bg-violet-300/45 shadow-[0_0_22px_rgba(139,92,246,0.26)]" style={{ animationDelay: `${(index % 5) * 150}ms` }} />
                            <div className="-mt-0.5 max-w-[84px] truncate rounded border border-violet-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isPredictionReady && predictionNodes.map((node) => (
                        <div key={node.label} className="absolute z-20 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 65}%` }}>
                            <div className={`mx-auto h-7 w-7 rounded-full border-2 ${node.verdict === 'bull' ? 'border-emerald-400 bg-emerald-300/40' : node.verdict === 'bear' ? 'border-rose-400 bg-rose-300/40' : 'border-amber-400 bg-amber-300/40'}`} />
                            <div className="max-w-[96px] truncate rounded border border-orange-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isVerdictReady && (
                        <div className="absolute left-[58%] top-[92%] z-30 -translate-x-1/2 -translate-y-1/2 text-center">
                            <div className="mx-auto h-20 w-20 rounded-full border-4 border-emerald-400 bg-emerald-300/45 shadow-[0_0_0_10px_rgba(16,185,129,0.12),0_0_42px_rgba(16,185,129,0.38)]" />
                            <div className="-mt-1 rounded border border-emerald-300 bg-white px-3 py-1 text-sm font-black text-emerald-600">{verdict?.label || 'HOLD'}</div>
                        </div>
                    )}
                    <div className="absolute bottom-5 left-5 right-5 z-30 grid gap-2 rounded-2xl border border-white/60 bg-white/80 p-3 shadow-xl shadow-slate-400/20 backdrop-blur md:grid-cols-4">
                        {[
                            { label: 'GRAPH LOAD', value: `${graphLoad}%`, bar: graphLoad, color: 'from-blue-500 to-indigo-500' },
                            { label: 'EVENTS', value: eventCount, bar: Math.min(100, eventCount * 8), color: 'from-cyan-500 to-teal-400' },
                            { label: 'ANALYST MESH', value: analysts.length, bar: Math.min(100, analysts.length * 10), color: 'from-violet-500 to-fuchsia-500' },
                            { label: 'VERDICT CONF', value: `${Math.round(confidence)}%`, bar: Math.round(confidence), color: 'from-emerald-500 to-lime-400' },
                        ].map((metric) => (
                            <div key={metric.label} className="min-w-0">
                                <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-[0.16em] text-slate-500">
                                    <span>{metric.label}</span>
                                    <span className="text-slate-900">{metric.value}</span>
                                </div>
                                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
                                    <div className={`h-full rounded-full bg-gradient-to-r ${metric.color} transition-all duration-700`} style={{ width: `${metric.bar}%` }} />
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            ) : (
                <>
                    <div className="absolute inset-x-12 bottom-8 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
                    <div className="absolute bottom-5 right-5 text-xs font-bold text-slate-300">Waiting for graph nodes</div>
                </>
            )}
        </section>
    );
}

function FeedPanel({ phase, run }: { phase: number; run: MiroFishRun }) {
    const logs = visibleLogs(run, phase);
    return (
        <section className="min-h-[430px] rounded-xl border border-slate-300/70 bg-white/[0.94] p-5 text-slate-950 shadow-[0_18px_70px_rgba(15,23,42,0.12)]">
            <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-red-400" />
                    <span className="h-3 w-3 rounded-full bg-yellow-400" />
                    <span className="h-3 w-3 rounded-full bg-emerald-400" />
                    <span className="ml-2 text-[11px] font-black uppercase tracking-[0.2em] text-slate-600">Feed</span>
                </div>
                <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs font-black text-white">{logs.length}</span>
            </div>
            <div className="space-y-4 font-mono text-sm leading-6">
                {logs.map((log, index) => (
                    <div key={`${log.time || index}-${log.text}`} className="flex gap-3">
                        <span className="shrink-0 font-bold text-slate-500">{log.time || 'live'}</span>
                        <span className={`font-black ${feedToneClass(log.tone)}`}>{log.text}</span>
                    </div>
                ))}
                {phase < 5 && <div className="h-5 w-1.5 animate-pulse rounded bg-blue-500" />}
            </div>
        </section>
    );
}

function ProgressPerformancePanel({ run, apiState }: { run: MiroFishRun; apiState: ApiState }) {
    const percent = Math.max(0, Math.min(100, Number(run.progress?.percent || (apiState === 'running' ? 2 : 0))));
    const elapsed = run.progress?.elapsed_ms || run.performance?.elapsed_ms || 0;
    const eventCount = run.events?.length || run.logs?.length || run.performance?.events_count || 0;
    const graphNodes = run.graph_artifact?.nodes?.length || run.performance?.graph_nodes || run.graph_nodes?.length || 0;
    const graphEdges = run.graph_artifact?.edges?.length || run.performance?.graph_edges || 0;
    const currentLabel = run.progress?.current_label || run.progress?.current_phase || run.status || 'waiting';
    const phaseDurations = run.performance?.phase_durations_ms || {};

    return (
        <section className="rounded-xl border border-white/20 bg-white/[0.88] p-4 text-slate-900 shadow-[0_18px_70px_rgba(59,130,246,0.14)]">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                    <div className="text-[11px] font-black uppercase tracking-[0.22em] text-slate-400">Live Pipeline Performance</div>
                    <div className="mt-1 text-xl font-black text-slate-900">{currentLabel}</div>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs font-black">
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">진행</div><div className="text-blue-600">{percent}%</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">경과</div><div className="text-violet-600">{formatElapsed(elapsed)}</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">그래프</div><div className="text-emerald-600">{graphNodes}/{graphEdges}</div></div>
                    <div className="rounded-lg bg-slate-100 px-3 py-2"><div className="text-slate-400">이벤트</div><div className="text-amber-600">{eventCount}</div></div>
                </div>
            </div>
            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400 transition-all duration-500" style={{ width: `${percent}%` }} />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-6">
                {impactSteps.map((step) => {
                    const phaseId = Object.keys(phaseNumberById).find((key) => phaseNumberById[key] === Number(step.no));
                    const duration = phaseId ? phaseDurations[phaseId] : undefined;
                    const active = phaseFromRunState(run) >= Number(step.no);
                    return (
                        <div key={step.no} className={`rounded-lg border px-3 py-2 text-[11px] font-black ${active ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white/60 text-slate-400'}`}>
                            <div>{step.ko}</div>
                            <div className="mt-1 font-mono text-[10px] opacity-70">{duration === undefined ? '--' : formatElapsed(duration)}</div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function SignalSummaryCard({ run }: { run: MiroFishRun }) {
    const score = run.brain?.score;
    const scoreValue = clampCount(score, 0);
    return (
        <section className="max-w-3xl rounded-xl border border-white/30 bg-white/90 p-4 text-slate-900 shadow-[0_18px_70px_rgba(124,58,237,0.16)]">
            <div className="flex items-center gap-5">
                <div className="grid h-24 w-24 shrink-0 place-items-center rounded-full border-4 border-blue-200 bg-blue-50 text-center shadow-inner">
                    <div>
                        <div className="text-2xl font-black text-blue-600">{score === undefined ? '--' : scoreValue}</div>
                        <div className="text-[10px] font-bold text-slate-400">/100</div>
                    </div>
                </div>
                <div className="min-w-0 flex-1">
                    <div className="text-lg font-black text-blue-700">Brain 시그널 요약</div>
                    <div className="mt-3 grid grid-cols-2 gap-4 text-xs font-bold text-slate-400 sm:grid-cols-4">
                        <span>체제</span>
                        <span className="text-slate-700">{run.brain?.regime || 'neutral'}</span>
                        <span>위기 단계</span>
                        <span className="text-slate-700">{run.brain?.crisis || 'Lv.2'}</span>
                    </div>
                    <div className="mt-5 h-2 rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-gradient-to-r from-blue-400 via-violet-400 to-emerald-300" style={{ width: `${Math.min(100, Math.max(0, scoreValue))}%` }} />
                    </div>
                </div>
            </div>
        </section>
    );
}

function FinalVerdictPanel({ run }: { run: MiroFishRun }) {
    const verdict = run.verdict;
    const targetName = String(run.display_name || verdict?.target || run.target || '분석 대상').trim();
    const targetMeta = [run.symbol, run.market]
        .map((part) => String(part || '').trim())
        .filter(Boolean)
        .join(' · ');
    const rawSummary = verdict?.summary || 'MiroFish 실데이터 판정이 도착했습니다.';
    const scopedSummary = targetName && rawSummary.includes(targetName)
        ? rawSummary
        : `${targetName} 단일 분석 기준: ${rawSummary}`;

    return (
        <section className="relative overflow-hidden rounded-xl border border-emerald-200/20 bg-emerald-700 p-8 text-white shadow-[0_26px_90px_rgba(16,185,129,0.22)] md:p-12">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_36%,rgba(255,255,255,0.22),rgba(255,255,255,0)_24%),linear-gradient(135deg,rgba(6,95,70,0.9),rgba(5,150,105,0.95))]" />
            <div className="relative mx-auto flex min-h-[430px] max-w-5xl flex-col items-center justify-center text-center">
                <div className="mb-6 flex items-center gap-4 text-[11px] font-black uppercase tracking-[0.45em] text-emerald-100/50">
                    <span>최종 판정</span>
                    <span className="h-px w-12 bg-emerald-100/30" />
                </div>
                <div className="mb-6 flex max-w-full flex-wrap items-center justify-center gap-2 rounded-full border border-white/20 bg-white/[0.12] px-4 py-2 text-xs font-black text-emerald-50 shadow-[0_14px_45px_rgba(0,0,0,0.14)] backdrop-blur">
                    <span className="uppercase tracking-[0.2em] text-emerald-100/60">단일 분석 대상 최종판결</span>
                    <span className="max-w-[min(72vw,520px)] truncate text-base text-white md:text-xl">{targetName}</span>
                    <span className="rounded-full bg-white/15 px-2.5 py-1 font-mono text-[11px] text-emerald-50/80">{targetMeta || 'single target'}</span>
                </div>
                <h2 className="text-[76px] font-black leading-none tracking-tight text-white md:text-[152px]">{verdict?.label || 'HOLD'}</h2>
                <p className="mt-7 max-w-4xl text-base font-bold text-emerald-50/75 md:text-lg">{scopedSummary}</p>
                <p className="mt-3 text-xs font-black uppercase tracking-[0.2em] text-emerald-50/45">
                    전체 종목 판정이 아니라 현재 선택한 대상 1건의 최종판결입니다.
                </p>
                <div className="mt-10 grid h-36 w-36 place-items-center rounded-full border-[7px] border-white/90 bg-white/5 shadow-[0_0_60px_rgba(255,255,255,0.16)]">
                    <div>
                        <div className="text-[11px] font-black uppercase tracking-[0.28em] text-emerald-50/45">확신도</div>
                        <div className="text-4xl font-black text-white">{verdict?.confidence ?? 64}%</div>
                    </div>
                </div>
                <div className="mt-10 grid w-full max-w-3xl grid-cols-2 gap-3 md:grid-cols-4">
                    {[
                        { label: '강세', value: verdict?.bullish ?? 0, color: 'text-emerald-100' },
                        { label: '약세', value: verdict?.bearish ?? 0, color: 'text-rose-200' },
                        { label: '중립', value: verdict?.neutral ?? 0, color: 'text-white' },
                        { label: '시계열', value: verdict?.horizon || '1M', color: 'text-white' },
                    ].map((stat) => (
                        <div key={stat.label} className="rounded-xl border border-white/15 bg-white/10 px-5 py-4 backdrop-blur">
                            <div className="text-[10px] font-black uppercase tracking-[0.25em] text-emerald-50/35">{stat.label}</div>
                            <div className={`mt-2 text-3xl font-black ${stat.color}`}>{stat.value}</div>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}

function ImpactPanel({ phase, run, apiState }: { phase: number; run: MiroFishRun; apiState: ApiState }) {
    const analysts = run.analysts?.length ? run.analysts : [];
    const verdict = run.verdict;
    return (
        <div className="space-y-4">
            <ProgressPerformancePanel run={run} apiState={apiState} />
            <Stepper phase={phase} />
            <TargetCard run={run} />
            {phase >= 5 && <SignalSummaryCard run={run} />}
            <div className="grid gap-4 lg:grid-cols-[1fr_0.64fr]">
                <KnowledgeGraph phase={phase} run={run} />
                <FeedPanel phase={phase} run={run} />
            </div>
            {phase >= 4 && (
                <section className="space-y-3">
                    <div className="flex items-center justify-between px-1">
                        <h2 className="text-sm font-black uppercase tracking-[0.18em] text-white/35">애널리스트 ({analysts.length})</h2>
                        <div className="text-xs font-black uppercase tracking-[0.16em]">
                            <span className="text-emerald-400">강세 {verdict?.bullish ?? 0}</span>
                            <span className="mx-3 text-white/25">|</span>
                            <span className="text-red-400">약세 {verdict?.bearish ?? 0}</span>
                        </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                        {analysts.map((card) => (
                            <div key={card.name} className={`rounded-xl border border-white/20 bg-white/90 p-4 text-slate-900 shadow-xl shadow-black/10 border-t-4 ${verdictTone(card.verdict).split(' ')[0]}`}>
                                <div className="flex items-center gap-3">
                                    <div className="grid h-12 w-12 place-items-center rounded-full bg-slate-100 ring-1 ring-slate-200">
                                        <i className={`fas ${card.icon || 'fa-user-tie'} text-slate-500`} />
                                    </div>
                                    <div className="min-w-0">
                                        <div className="font-black text-slate-900">{card.name}</div>
                                        <div className="truncate text-xs font-bold text-slate-400">{card.role || 'MiroFish analyst'}</div>
                                    </div>
                                </div>
                                <div className={`mt-4 inline-flex rounded-full px-2.5 py-1 text-[10px] font-black ${verdictTone(card.verdict).replace('border-emerald-400 ', '').replace('border-rose-400 ', '').replace('border-amber-400 ', '')}`}>
                                    {card.verdict || 'NEUTRAL'} {card.confidence ? `${card.confidence}%` : ''}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
            {phase >= 5 && <FinalVerdictPanel run={run} />}
        </div>
    );
}

interface AdminEndpointsPageProps {
    /**
     * Pro + AI Brain 구독자 모드 — admin 전용 컨트롤 (AutoRunner / QuickActions) 숨김
     * + 헤더 라벨 "구독자 콘솔" 로 변경.
     * 동일한 데이터/렌더 로직을 구독자에게 노출하기 위한 토글.
     */
    subscriberMode?: boolean;
}

export default function AdminEndpointsPage({ subscriberMode = false }: AdminEndpointsPageProps = {}) {
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [phase, setPhase] = useState(1);
    const [target, setTarget] = useState(defaultTarget);
    const [agentCount, setAgentCount] = useState(10);
    const [run, setRun] = useState<MiroFishRun>(() => createEmptyRun());
    const [status, setStatus] = useState<MiroFishStatus | null>(null);
    const [targetSnapshot, setTargetSnapshot] = useState<MiroFishTargetSnapshot | null>(null);
    const [suggestionTarget, setSuggestionTarget] = useState('');
    const [suggestionCandidates, setSuggestionCandidates] = useState<TargetCandidate[]>([]);
    const [activeCandidateIndex, setActiveCandidateIndex] = useState(0);
    const [recentRuns, setRecentRuns] = useState<MiroFishRun[]>([]);
    const [dataSourceCount, setDataSourceCount] = useState(0);
    const [alphaScannerState, setAlphaScannerState] = useState<AlphaScannerState>('idle');
    const [alphaScannerRun, setAlphaScannerRun] = useState<MiroFishScannerRun | null>(null);
    const alphaScannerRunRef = useRef<MiroFishScannerRun | null>(null);
    const [alphaScannerStatus, setAlphaScannerStatus] = useState<MiroFishScannerStatus | null>(null);
    const [alphaCandidates, setAlphaCandidates] = useState<MiroFishAlphaCandidate[]>([]);
    const [alphaErrorText, setAlphaErrorText] = useState<string | null>(null);
    const [deepSeekStatus, setDeepSeekStatus] = useState<MiroFishDeepSeekStatus | null>(null);
    const [tradingViewStatus, setTradingViewStatus] = useState<MiroFishTradingViewStatus | null>(null);
    const [dualKalmanStatus, setDualKalmanStatus] = useState<Record<string, any> | null>(null);
    const [deepSeekState, setDeepSeekState] = useState<DeepSeekPanelState>('idle');
    const [deepSeekSummary, setDeepSeekSummary] = useState<MiroFishDeepSeekSummaryResult | null>(null);
    const [deepSeekErrorText, setDeepSeekErrorText] = useState<string | null>(null);
    const [workflowState, setWorkflowState] = useState<WorkflowPanelState>('idle');
    const [workflow, setWorkflow] = useState<MiroFishWorkflow | null>(null);
    const [workflowErrorText, setWorkflowErrorText] = useState<string | null>(null);
    const [autonomousStatus, setAutonomousStatus] = useState<MiroFishAutonomousStatus | null>(null);
    const [autonomousState, setAutonomousState] = useState<AutonomousPanelState>('idle');
    const [autonomousResult, setAutonomousResult] = useState<MiroFishAutonomousActionResult | null>(null);
    const [autonomousLearning, setAutonomousLearning] = useState<MiroFishAutonomousLearningFeedback | null>(null);
    const [autonomousErrorText, setAutonomousErrorText] = useState<string | null>(null);
    const [mcpResourceSnapshot, setMcpResourceSnapshot] = useState<MiroFishMcpResourceSnapshot | null>(null);
    const [alphaEndpointBlueprint, setAlphaEndpointBlueprint] = useState<MiroFishAlphaEndpointBlueprint | null>(null);
    const [autonomousConfirmation, setAutonomousConfirmation] = useState('');
    const [autonomousSharedSecret, setAutonomousSharedSecret] = useState('');
    const [opsLaneRefreshKey, setOpsLaneRefreshKey] = useState(0);
    const [opsLaneState, setOpsLaneState] = useState<'idle' | 'refreshing'>('idle');
    const [endpointState, setEndpointState] = useState<Record<EndpointKey, EndpointStatus>>(() => Object.fromEntries(endpointDefinitions.map((item) => [item.key, 'idle'])) as Record<EndpointKey, EndpointStatus>);
    const [apiState, setApiState] = useState<ApiState>('checking');
    const [errorText, setErrorText] = useState<string | null>(null);
    const [subscriberPolicy, setSubscriberPolicy] = useState<MiroFishRun['subscriber_policy'] | null>(null);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);
    const lastStartAtRef = useRef(0);
    const targetValueRef = useRef(defaultTarget);
    const suggestRequestRef = useRef(0);
    const resolveRequestRef = useRef(0);
    const pendingCompositionStartRef = useRef(false);

    function markEndpoint(key: EndpointKey, state: EndpointStatus) {
        setEndpointState((current) => ({ ...current, [key]: state }));
    }

    useEffect(() => {
        let alive = true;
        async function boot() {
            markEndpoint('status', 'loading');
            markEndpoint('history', 'loading');
            markEndpoint('dataSources', 'loading');
            markEndpoint('deepseek', 'loading');
            markEndpoint('tradingview', 'loading');
            markEndpoint('kalman', 'loading');
            markEndpoint('workflow', 'loading');
            markEndpoint('autonomous', 'loading');
            markEndpoint('mcpResources', 'loading');
            markEndpoint('alphaEndpoints', 'loading');
            try {
                const [statusResult, historyResult, sourcesResult, deepSeekResult, tradingViewResult, kalmanResult, workflowResult, autonomousResult, mcpResourcesResult, alphaEndpointsResult] = await Promise.allSettled([
                    mirofishApi.getStatus(),
                    mirofishApi.listRuns(),
                    mirofishApi.getDataSources(),
                    mirofishApi.getDeepSeekStatus(),
                    mirofishApi.getTradingViewStatus(),
                    mirofishApi.getDualKalmanStatus(),
                    mirofishApi.getWorkflowStatus(),
                    mirofishApi.getAutonomousStatus(),
                    mirofishApi.getMcpResources(),
                    mirofishApi.getAlphaEndpointBlueprint(),
                ]);
                if (!alive) return;
                const failures: string[] = [];
                const noteFailure = (key: EndpointKey, label: string, reason: unknown) => {
                    markEndpoint(key, 'error');
                    const detail = reason instanceof Error ? reason.message : String(reason || 'failed');
                    failures.push(`${label}: ${detail}`);
                };

                if (statusResult.status === 'fulfilled') {
                    const statusData = statusResult.value as MiroFishStatus;
                    setStatus(statusData);
                    setRun((current) => ({ ...current, brain: statusData.brain || current.brain, pipeline: statusData.pipeline || current.pipeline }));
                    markEndpoint('status', 'ok');
                } else {
                    setStatus({ ready: false, source: 'api unavailable', pipeline: { status: 'unavailable' } });
                    noteFailure('status', 'Service Status', statusResult.reason);
                }

                if (historyResult.status === 'fulfilled') {
                    const historyData = historyResult.value as { runs?: MiroFishRun[] };
                    setRecentRuns(Array.isArray(historyData.runs) ? historyData.runs : []);
                    markEndpoint('history', 'ok');
                } else {
                    noteFailure('history', 'Run History', historyResult.reason);
                }

                if (sourcesResult.status === 'fulfilled') {
                    const sourcesData = sourcesResult.value as { files?: Array<{ exists?: boolean }> };
                    setDataSourceCount(Array.isArray(sourcesData?.files) ? sourcesData.files.filter((file) => file.exists).length : 0);
                    markEndpoint('dataSources', 'ok');
                } else {
                    setDataSourceCount(0);
                    noteFailure('dataSources', 'Data Sources', sourcesResult.reason);
                }

                if (deepSeekResult.status === 'fulfilled') {
                    const deepSeekData = deepSeekResult.value as MiroFishDeepSeekStatus;
                    setDeepSeekStatus(deepSeekData);
                    setDeepSeekState(deepSeekData.configured ? 'ready' : 'idle');
                    markEndpoint('deepseek', deepSeekData.configured ? 'ok' : 'idle');
                } else {
                    setDeepSeekState('error');
                    noteFailure('deepseek', 'DeepSeek V2', deepSeekResult.reason);
                }

                if (tradingViewResult.status === 'fulfilled') {
                    const tradingViewData = tradingViewResult.value as MiroFishTradingViewStatus;
                    setTradingViewStatus(tradingViewData);
                    markEndpoint('tradingview', tradingViewData.enabled || tradingViewData.cache_available || tradingViewData.mcp_url_configured ? 'ok' : 'idle');
                } else {
                    noteFailure('tradingview', 'TradingView MCP', tradingViewResult.reason);
                }

                if (kalmanResult.status === 'fulfilled') {
                    const kalmanData = kalmanResult.value as Record<string, any>;
                    setDualKalmanStatus(kalmanData);
                    markEndpoint('kalman', kalmanData?.ready ? 'ok' : 'idle');
                } else {
                    noteFailure('kalman', 'Dual Kalman Gate', kalmanResult.reason);
                }

                if (workflowResult.status === 'fulfilled') {
                    const workflowData = workflowResult.value as { latest_workflow?: MiroFishWorkflow };
                    if (workflowData?.latest_workflow) {
                        setWorkflow(workflowData.latest_workflow);
                        setWorkflowState(workflowData.latest_workflow.status === 'completed' ? 'completed' : 'idle');
                    }
                    markEndpoint('workflow', workflowData ? 'ok' : 'idle');
                } else {
                    setWorkflowState('error');
                    noteFailure('workflow', 'MCP Top 3', workflowResult.reason);
                }

                if (autonomousResult.status === 'fulfilled') {
                    const autonomousData = autonomousResult.value as MiroFishAutonomousStatus;
                    setAutonomousStatus(autonomousData);
                    setAutonomousLearning(autonomousData.learning?.available ? autonomousData.learning : null);
                    setAutonomousState('ready');
                    markEndpoint('autonomous', 'ok');
                } else {
                    setAutonomousState('error');
                    noteFailure('autonomous', 'Autonomous MCP', autonomousResult.reason);
                }

                if (mcpResourcesResult.status === 'fulfilled') {
                    const resourceData = mcpResourcesResult.value as MiroFishMcpResourceSnapshot;
                    setMcpResourceSnapshot(resourceData);
                    markEndpoint('mcpResources', 'ok');
                    if (resourceData.alpha_endpoint_blueprint) {
                        setAlphaEndpointBlueprint(resourceData.alpha_endpoint_blueprint);
                    }
                } else {
                    noteFailure('mcpResources', 'MCP Resources', mcpResourcesResult.reason);
                }

                if (alphaEndpointsResult.status === 'fulfilled') {
                    const endpointData = alphaEndpointsResult.value as MiroFishAlphaEndpointBlueprint;
                    setAlphaEndpointBlueprint(endpointData);
                    markEndpoint('alphaEndpoints', endpointData.endpoints?.length ? 'ok' : 'idle');
                } else {
                    noteFailure('alphaEndpoints', 'Alpha Evidence Gates', alphaEndpointsResult.reason);
                }

                const hasCoreData = statusResult.status === 'fulfilled' || historyResult.status === 'fulfilled' || sourcesResult.status === 'fulfilled';
                setApiState(hasCoreData ? 'ready' : 'error');
                setErrorText(failures.length ? `Partial endpoint check failed: ${failures.map((item) => item.split(':')[0]).join(', ')}` : null);
            } catch (error) {
                if (!alive) return;
                setApiState('error');
                setStatus({ ready: false, source: 'api unavailable', pipeline: { status: 'unavailable' } });
                markEndpoint('status', 'error');
                markEndpoint('history', 'error');
                markEndpoint('dataSources', 'error');
                markEndpoint('deepseek', 'error');
                markEndpoint('tradingview', 'error');
                markEndpoint('kalman', 'error');
                markEndpoint('workflow', 'error');
                markEndpoint('autonomous', 'error');
                markEndpoint('mcpResources', 'error');
                markEndpoint('alphaEndpoints', 'error');
                setErrorText(error instanceof Error ? error.message : 'MiroFish API 연결 실패');
            }
        }
        boot();
        return () => {
            alive = false;
        };
    }, []);

    useEffect(() => {
        if (!activeRunId || !isAnalyzing) return;
        let alive = true;
        const runId = activeRunId;

        async function refreshRun() {
            try {
                const hydrated = await mirofishApi.hydrateRun(runId);
                if (!alive) return;
                setRun(hydrated);
                setPhase(phaseFromRunState(hydrated));
                markEndpoint('runDetail', 'ok');
                markEndpoint('graph', 'ok');
                markEndpoint('events', 'ok');
                if (hydrated.report?.markdown) markEndpoint('report', 'ok');

                if (hydrated.status === 'failed') {
                    setApiState('error');
                    setErrorText(hydrated.progress?.error || 'MiroFish run failed.');
                    setActiveRunId(null);
                    markEndpoint('createRun', 'error');
                    return;
                }

                if (hydrated.status === 'completed') {
                    setApiState('ready');
                    setActiveRunId(null);
                    setPhase(5);
                    mirofishApi.listRuns()
                        .then((data) => {
                            setRecentRuns(data.runs);
                            markEndpoint('history', 'ok');
                        })
                        .catch(() => markEndpoint('history', 'error'));
                }
            } catch (error) {
                if (!alive) return;
                setApiState('error');
                setErrorText(error instanceof Error ? error.message : 'MiroFish run polling failed.');
                markEndpoint('runDetail', 'error');
            }
        }

        refreshRun();
        const timer = window.setInterval(refreshRun, 1000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [activeRunId, isAnalyzing]);

    useEffect(() => {
        alphaScannerRunRef.current = alphaScannerRun;
    }, [alphaScannerRun]);

    useEffect(() => {
        if (alphaScannerState === 'loading' || alphaScannerState === 'running') return;
        let alive = true;

        async function refreshLatestScanner() {
            try {
                const scannerStatus = await mirofishApi.getScannerStatus();
                if (!alive) return;
                setAlphaScannerStatus(scannerStatus);
                try {
                    const latest = await mirofishApi.getLatestScannerRun();
                    if (!alive || !latest.id) return;
                    const currentRun = alphaScannerRunRef.current;
                    const currentTime = scannerRunTimestamp(currentRun);
                    const latestTime = scannerRunTimestamp(latest);
                    if (currentRun?.id && currentRun.id !== latest.id && currentTime > 0 && currentTime >= latestTime) return;
                    setAlphaScannerRun(latest);
                    setAlphaCandidates(latest.candidates || []);
                    setAlphaScannerState(latest.status === 'failed' ? 'error' : latest.status === 'running' ? 'running' : 'ready');
                    if (latest.status !== 'failed') setAlphaErrorText(null);
                } catch {
                    if (!scannerStatus.last_run_id && alphaScannerState === 'idle') {
                        setAlphaScannerRun(null);
                        setAlphaCandidates([]);
                    }
                }
            } catch (error) {
                if (!alive || alphaScannerState !== 'idle') return;
                setAlphaScannerState('error');
                setAlphaErrorText(error instanceof Error ? error.message : 'Alpha scanner status unavailable.');
            }
        }

        refreshLatestScanner();
        const timer = window.setInterval(refreshLatestScanner, 45000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [alphaScannerState]);

    useEffect(() => {
        if (!alphaScannerRun?.id || alphaScannerState !== 'running') return;
        let alive = true;
        const scannerRunId = alphaScannerRun.id;

        async function refreshScannerRun() {
            try {
                const [scannerRun, candidatePayload] = await Promise.all([
                    mirofishApi.getScannerRun(scannerRunId),
                    mirofishApi.getScannerCandidates(scannerRunId),
                ]);
                if (!alive) return;
                setAlphaScannerRun(scannerRun);
                setAlphaCandidates(candidatePayload.candidates);
                if (scannerRun.status === 'completed') {
                    setAlphaScannerState('ready');
                    mirofishApi.getScannerStatus().then(setAlphaScannerStatus).catch(() => undefined);
                } else if (scannerRun.status === 'failed') {
                    setAlphaScannerState('error');
                    setAlphaErrorText(scannerRun.error || 'Alpha scanner failed.');
                }
            } catch (error) {
                if (!alive) return;
                setAlphaScannerState('error');
                setAlphaErrorText(error instanceof Error ? error.message : 'Alpha scanner polling failed.');
            }
        }

        refreshScannerRun();
        const timer = window.setInterval(refreshScannerRun, 1200);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [alphaScannerRun?.id, alphaScannerState]);

    useEffect(() => {
        const nextTarget = target.trim();
        if (!nextTarget || apiState === 'running') {
            setSuggestionTarget('');
            setSuggestionCandidates([]);
            setActiveCandidateIndex(0);
            return;
        }
        let alive = true;
        const requestId = suggestRequestRef.current + 1;
        suggestRequestRef.current = requestId;
        markEndpoint('resolve', 'loading');
        const timer = window.setTimeout(() => {
            (async () => {
                try {
                    const [graphragResult, legacyResult] = await Promise.allSettled([
                        mirofishApi.graphrag?.resolveEntity
                            ? mirofishApi.graphrag.resolveEntity(nextTarget, { limit: 16 })
                            : Promise.reject(new Error('GraphRAG resolver unavailable')),
                        mirofishApi.searchTargets(nextTarget, 16),
                    ]);
                    if (!alive || suggestRequestRef.current !== requestId) return;
                    const graphCandidates = graphragResult.status === 'fulfilled'
                        ? ((graphragResult.value as any)?.matches || []).map(graphragMatchToTargetCandidate)
                        : [];
                    const legacyCandidates = legacyResult.status === 'fulfilled'
                        ? (legacyResult.value as any)?.candidates || []
                        : [];
                    const seen = new Set<string>();
                    const candidates = [...graphCandidates, ...legacyCandidates].filter((candidate) => {
                        const key = `${candidate.symbol || ''}|${candidate.yahoo_ticker || ''}|${targetCandidateLabel(candidate)}`.toLowerCase();
                        if (seen.has(key)) return false;
                        seen.add(key);
                        return true;
                    }).slice(0, 16);
                    setSuggestionTarget(nextTarget);
                    setSuggestionCandidates(candidates);
                    setActiveCandidateIndex(0);
                    markEndpoint('resolve', candidates.length || graphragResult.status === 'fulfilled' || legacyResult.status === 'fulfilled' ? 'ok' : 'error');
                } catch {
                    if (!alive || suggestRequestRef.current !== requestId) return;
                    setSuggestionTarget(nextTarget);
                    setSuggestionCandidates([]);
                    setActiveCandidateIndex(0);
                    markEndpoint('resolve', 'error');
                }
            })();
        }, 80);
        return () => {
            alive = false;
            window.clearTimeout(timer);
        };
    }, [target, apiState]);

    useEffect(() => {
        const nextTarget = target.trim();
        if (!nextTarget || apiState === 'running') return;
        let alive = true;
        const requestId = resolveRequestRef.current + 1;
        resolveRequestRef.current = requestId;
        const timer = window.setTimeout(() => {
            mirofishApi.resolveTarget(nextTarget)
                .then((snapshot) => {
                    if (!alive || resolveRequestRef.current !== requestId) return;
                    setTargetSnapshot(snapshot);
                })
                .catch(() => {
                    if (!alive || resolveRequestRef.current !== requestId) return;
                    setTargetSnapshot(null);
                });
        }, 520);
        return () => {
            alive = false;
            window.clearTimeout(timer);
        };
    }, [target, apiState]);

    const brainSignals = useMemo(() => {
        const brain = status?.brain || run.brain;
        return [
            { label: 'BRAIN', value: brain?.score === undefined ? '--' : String(brain.score), tone: 'text-violet-300' },
            { label: 'REGIME', value: brain?.regime || '--', tone: 'text-slate-200' },
            { label: 'CRISIS', value: brain?.crisis || '--', tone: 'text-amber-300' },
        ];
    }, [run.brain, status]);

    const endpointMetrics = useMemo<Record<EndpointKey, string>>(() => ({
        status: status?.pipeline?.status || 'not loaded',
        dataSources: `${dataSourceCount} files`,
        resolve: targetSnapshot?.resolved?.symbol || targetSnapshot?.resolved?.asset_type || 'waiting',
        history: `${recentRuns.length} runs`,
        createRun: run.id ? String(run.status || 'created') : 'idle',
        runDetail: run.id ? String(run.id).slice(0, 24) : '{id}',
        graph: `${run.graph_artifact?.nodes?.length || 0} nodes / ${run.graph_artifact?.edges?.length || 0} edges`,
        events: `${run.events?.length || 0} events`,
        report: run.report?.markdown ? `${run.report.markdown.length} chars` : 'waiting',
        deepseek: deepSeekStatus?.configured ? (deepSeekSummary?.model || deepSeekStatus.default_model || 'ready') : 'not configured',
        workflow: workflow?.id ? `${workflow.status || 'running'} · top ${workflow.top3?.length || 0}` : workflowState,
        tradingview: tradingViewStatus
            ? `${tradingViewStatus.enabled ? tradingViewStatus.mode || 'enabled' : 'off'} / ${tradingViewStatus.cache_available ? 'cache' : tradingViewStatus.mcp_url_configured ? 'mcp url' : 'no source'}`
            : 'not loaded',
        kalman: dualKalmanStatus
            ? `${dualKalmanStatus.mode || 'shadow'} / ${dualKalmanStatus.latest_run_id ? 'latest' : 'ready'}`
            : 'not loaded',
        autonomous: autonomousStatus ? `${autonomousStatus.mutation_enabled ? 'mutation on' : 'dry-run'} / ${autonomousStatus.telegram?.personal_configured ? 'telegram ok' : 'telegram off'}` : autonomousState,
        mcpResources: mcpResourceSnapshot
            ? `${mcpResourceSnapshot.catalog_count || 0} resources`
            : 'not loaded',
        alphaEndpoints: alphaEndpointBlueprint
            ? `${alphaEndpointBlueprint.source_readiness?.status || 'unknown'} / P0 ${alphaEndpointBlueprint.p0_count || 0}`
            : 'not loaded',
    }), [alphaEndpointBlueprint, autonomousState, autonomousStatus, dataSourceCount, deepSeekStatus, deepSeekSummary, dualKalmanStatus, mcpResourceSnapshot, recentRuns.length, run, status, targetSnapshot, tradingViewStatus, workflow, workflowState]);

    const targetCandidates = useMemo<TargetCandidate[]>(() => {
        const query = target.trim();
        if (!query || suggestionTarget !== query) return [];
        return suggestionCandidates.filter((candidate) => targetCandidateStartValue(candidate));
    }, [target, suggestionCandidates, suggestionTarget]);

    const activeCandidate = targetCandidates[activeCandidateIndex] || targetCandidates[0] || null;

    function getStartTarget(inputValue?: string) {
        const typedTarget = (inputValue ?? targetValueRef.current ?? target).trim();
        if (activeCandidate) return targetCandidateStartValue(activeCandidate) || typedTarget || defaultTarget;
        return typedTarget || defaultTarget;
    }

    function selectTargetCandidate(candidate: TargetCandidate, shouldStart = false) {
        const nextTarget = targetCandidateStartValue(candidate);
        if (!nextTarget) return;
        targetValueRef.current = nextTarget;
        setTarget(nextTarget);
        setTargetSnapshot(null);
        setSuggestionTarget('');
        setSuggestionCandidates([]);
        setActiveCandidateIndex(0);
        markEndpoint('resolve', 'loading');
        if (shouldStart) requestStart(nextTarget);
    }

    function handleTargetKeyNavigation(event: ReactKeyboardEvent<HTMLInputElement>) {
        if (!targetCandidates.length) return;
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveCandidateIndex((index) => (index + 1) % targetCandidates.length);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveCandidateIndex((index) => (index - 1 + targetCandidates.length) % targetCandidates.length);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            setTargetSnapshot(null);
            setActiveCandidateIndex(0);
        }
    }

    async function handleStart(targetOverride?: string) {
        if (apiState === 'running') return;
        const nextTarget = (targetOverride ?? targetValueRef.current ?? target).trim() || defaultTarget;
        setErrorText(null);
        setSubscriberPolicy(null);
        setIsAnalyzing(true);
        setApiState('running');
        setActiveRunId(null);
        setPhase(1);
        setRun({ ...createEmptyRun(nextTarget), status: 'running', progress: { percent: 1, current_phase: 'intake', current_label: 'Target Intake', elapsed_ms: 0 } });
        markEndpoint('createRun', 'loading');
        markEndpoint('runDetail', 'idle');
        markEndpoint('graph', 'idle');
        markEndpoint('events', 'idle');
        markEndpoint('report', 'idle');
        try {
            const data = await mirofishApi.startRun({ target: nextTarget, agent_count: agentCount, mode: 'full', async: true });
            const baseRun = { ...data, target: data.target || nextTarget, display_name: data.display_name || data.target || nextTarget };
            setSubscriberPolicy(baseRun.subscriber_policy || null);
            setRun(baseRun);
            setPhase(phaseFromRunState(baseRun));
            markEndpoint('createRun', 'ok');
            markEndpoint('runDetail', 'loading');
            markEndpoint('graph', 'loading');
            markEndpoint('events', 'loading');
            markEndpoint('report', 'loading');
            const runId = String(baseRun.id || '');
            if (!runId) throw new Error('MiroFish run id was not returned.');
            setActiveRunId(runId);
        } catch (error) {
            setIsAnalyzing(false);
            setActiveRunId(null);
            setRun((current) => ({ ...current, status: 'api_error' }));
            setApiState('error');
            markEndpoint('createRun', 'error');
            markEndpoint('runDetail', 'error');
            markEndpoint('graph', 'error');
            markEndpoint('events', 'error');
            markEndpoint('report', 'error');
            setErrorText(error instanceof Error ? error.message : 'MiroFish API unavailable. Live data was not loaded.');
        }
    }

    async function handleAlphaScan() {
        setAlphaScannerState('loading');
        setAlphaErrorText(null);
        setDeepSeekSummary(null);
        setDeepSeekErrorText(null);
        try {
            const scannerRun = await mirofishApi.startScannerRun({
                market: 'KR',
                horizon: '20D',
                strategy: 'multi_signal',
                risk_profile: 'balanced',
                limit: 20,
            });
            setAlphaScannerRun(scannerRun);
            setAlphaCandidates(scannerRun.candidates || []);
            setAlphaScannerState(scannerRun.status === 'completed' ? 'ready' : 'running');
            mirofishApi.getScannerStatus().then(setAlphaScannerStatus).catch(() => undefined);
            if (scannerRun.status === 'failed') {
                setAlphaScannerState('error');
                setAlphaErrorText(scannerRun.error || 'Alpha scanner failed.');
            }
        } catch (error) {
            setAlphaScannerState('error');
            setAlphaErrorText(error instanceof Error ? error.message : 'Alpha scanner API unavailable.');
        }
    }

    async function handleMcpWorkflow(force = false) {
        setWorkflowState('running');
        setWorkflowErrorText(null);
        markEndpoint('workflow', 'loading');
        try {
            const result = await mirofishApi.startWorkflowScanAnalyze({
                market: 'KR',
                horizon: '20D',
                strategy: 'multi_signal',
                risk_profile: 'balanced',
                limit: 20,
                min_alpha: 50,
                max_risk: 65,
                actions: ['BUY_CANDIDATE', 'WATCH'],
                max_events: 5,
                agent_count: agentCount,
                top_n: 3,
                max_parallel: 3,
                quality_gate: 'dual_kalman',
                kalman_profile: 'linear_dkf_shadow_v1',
                min_kalman_confidence: 0.55,
                block_high_innovation: true,
                allow_stale_sources: false,
                mode: 'full',
                force,
            });
            setWorkflow(result);
            if (result.status === 'blocked') {
                setWorkflowState('blocked');
                setWorkflowErrorText(result.blocked_reason || 'MCP workflow blocked.');
                markEndpoint('workflow', 'error');
                return;
            }
            if (result.status === 'no_new_events') {
                setWorkflowState('no_new_events');
                markEndpoint('workflow', 'ok');
                return;
            }
            if (result.status === 'completed' || result.top3?.length) {
                setWorkflowState('completed');
                markEndpoint('workflow', 'ok');
                return;
            }
            setWorkflowState('running');
            markEndpoint('workflow', 'ok');
            const workflowId = String(result.id || '');
            if (workflowId) {
                for (let attempt = 0; attempt < 60; attempt += 1) {
                    await new Promise((resolve) => window.setTimeout(resolve, 2500));
                    const latest = await mirofishApi.getWorkflow(workflowId);
                    setWorkflow(latest);
                    if (latest.status === 'completed') {
                        setWorkflowState('completed');
                        return;
                    }
                    if (latest.status === 'failed') {
                        setWorkflowState('error');
                        setWorkflowErrorText('MCP workflow failed.');
                        markEndpoint('workflow', 'error');
                        return;
                    }
                }
            }
        } catch (error) {
            setWorkflowState('error');
            markEndpoint('workflow', 'error');
            setWorkflowErrorText(error instanceof Error ? error.message : 'MCP workflow failed.');
        }
    }

    async function refreshAutonomousStatus() {
        setAutonomousState('checking');
        setAutonomousErrorText(null);
        markEndpoint('autonomous', 'loading');
        try {
            const nextStatus = await mirofishApi.getAutonomousStatus();
            setAutonomousStatus(nextStatus);
            setAutonomousLearning(nextStatus.learning?.available ? nextStatus.learning : null);
            setAutonomousState('ready');
            markEndpoint('autonomous', 'ok');
        } catch (error) {
            setAutonomousState('error');
            markEndpoint('autonomous', 'error');
            setAutonomousErrorText(error instanceof Error ? error.message : 'Autonomous MCP status failed.');
        }
    }

    async function refreshOpsLane() {
        if (opsLaneState === 'refreshing') return;
        setOpsLaneState('refreshing');
        setOpsLaneRefreshKey((key) => key + 1);
        markEndpoint('workflow', 'loading');
        try {
            const [workflowResult, scannerStatusResult] = await Promise.allSettled([
                mirofishApi.getWorkflowStatus(),
                mirofishApi.getScannerStatus(),
                refreshAutonomousStatus(),
            ]);

            if (workflowResult.status === 'fulfilled') {
                const workflowData = workflowResult.value as { latest_workflow?: MiroFishWorkflow };
                if (workflowData?.latest_workflow) {
                    setWorkflow(workflowData.latest_workflow);
                    setWorkflowState(workflowData.latest_workflow.status === 'completed' ? 'completed' : 'idle');
                }
                markEndpoint('workflow', 'ok');
            } else {
                setWorkflowState('error');
                markEndpoint('workflow', 'error');
                setWorkflowErrorText(workflowResult.reason instanceof Error ? workflowResult.reason.message : 'Workflow status refresh failed.');
            }

            if (scannerStatusResult.status === 'fulfilled') {
                setAlphaScannerStatus(scannerStatusResult.value as MiroFishScannerStatus);
            }
        } finally {
            setOpsLaneState('idle');
        }
    }

    async function handleAutonomousDetectionDryRun() {
        setAutonomousState('running');
        setAutonomousErrorText(null);
        markEndpoint('autonomous', 'loading');
        try {
            const result = await mirofishApi.runAutonomousCandidateAlert({
                dry_run: true,
                send_telegram: false,
                limit: 20,
                min_alpha: 70,
                max_risk: 45,
                max_events: 8,
                allow_stale_sources: false,
            });
            setAutonomousResult(result);
            setAutonomousState('ready');
            markEndpoint('autonomous', 'ok');
            void refreshAutonomousStatus();
        } catch (error) {
            setAutonomousState('error');
            markEndpoint('autonomous', 'error');
            setAutonomousErrorText(error instanceof Error ? error.message : 'Autonomous detection dry-run failed.');
        }
    }

    async function handleAutonomousAnalysisDryRun() {
        setAutonomousState('running');
        setAutonomousErrorText(null);
        markEndpoint('autonomous', 'loading');
        try {
            const result = await mirofishApi.runAutonomousScanAnalysis({
                dry_run: true,
                sync: true,
                send_telegram: false,
                commit_event_state: false,
                market: 'KR',
                horizon: '20D',
                strategy: 'multi_signal',
                risk_profile: 'balanced',
                limit: 20,
                min_alpha: 50,
                max_risk: 65,
                actions: ['BUY_CANDIDATE', 'WATCH'],
                max_events: 5,
                top_n: 3,
                max_parallel: 3,
                agent_count: agentCount,
                allow_stale_sources: false,
                mode: 'full',
                force: true,
            });
            setAutonomousResult(result);
            setAutonomousState('ready');
            markEndpoint('autonomous', 'ok');
            void refreshAutonomousStatus();
        } catch (error) {
            setAutonomousState('error');
            markEndpoint('autonomous', 'error');
            setAutonomousErrorText(error instanceof Error ? error.message : 'Autonomous analysis dry-run failed.');
        }
    }

    async function handleAutonomousLearningPreview() {
        setAutonomousState('running');
        setAutonomousErrorText(null);
        markEndpoint('autonomous', 'loading');
        try {
            const feedback = await mirofishApi.refreshAutonomousLearning({
                commit: false,
                limit: 20,
            });
            setAutonomousLearning({ available: true, ...feedback });
            setAutonomousState('ready');
            markEndpoint('autonomous', 'ok');
        } catch (error) {
            setAutonomousState('error');
            markEndpoint('autonomous', 'error');
            setAutonomousErrorText(error instanceof Error ? error.message : 'Autonomous learning preview failed.');
        }
    }

    async function handleSendLatestAutonomousTelegram() {
        setAutonomousState('sending');
        setAutonomousErrorText(null);
        markEndpoint('autonomous', 'loading');
        try {
            const result = await mirofishApi.sendLatestAutonomousWorkflowTelegram({
                confirmation: autonomousConfirmation,
                shared_secret: autonomousSharedSecret || undefined,
                channel: false,
                commit_event_state: false,
            });
            setAutonomousResult(result);
            setAutonomousState(result.ok ? 'sent' : 'error');
            markEndpoint('autonomous', result.ok ? 'ok' : 'error');
        } catch (error) {
            setAutonomousState('error');
            markEndpoint('autonomous', 'error');
            setAutonomousErrorText(error instanceof Error ? error.message : 'Latest workflow Telegram send failed.');
        }
    }

    async function handleDeepSeekSummary() {
        setDeepSeekState('summarizing');
        setDeepSeekErrorText(null);
        try {
            if (alphaScannerRun?.id) {
                const summary = await mirofishApi.summarizeScannerRunWithDeepSeek(alphaScannerRun.id, {
                    limit: 5,
                    model: deepSeekStatus?.default_model,
                    thinking: false,
                });
                setDeepSeekSummary(summary);
                setDeepSeekState('ready');
                markEndpoint('deepseek', 'ok');
                return;
            }
            const payload = await mirofishApi.createDeepSeekScannerSummary({
                market: 'KR',
                horizon: '20D',
                strategy: 'multi_signal',
                risk_profile: 'balanced',
                limit: 20,
                summary_limit: 5,
                model: deepSeekStatus?.default_model,
                thinking: false,
            });
            setAlphaScannerRun(payload.run);
            setAlphaCandidates(payload.run.candidates || []);
            setAlphaScannerState(payload.run.status === 'completed' ? 'ready' : 'running');
            setDeepSeekSummary(payload.summary);
            setDeepSeekState('ready');
            markEndpoint('deepseek', 'ok');
        } catch (error) {
            setDeepSeekState('error');
            markEndpoint('deepseek', 'error');
            setDeepSeekErrorText(error instanceof Error ? error.message : 'DeepSeek summary failed.');
        }
    }

    async function handleSendDeepSeekTelegram() {
        if (!alphaScannerRun?.id) {
            setDeepSeekState('error');
            setDeepSeekErrorText('먼저 scanner run을 생성하세요.');
            return;
        }
        setDeepSeekState('sending');
        setDeepSeekErrorText(null);
        try {
            const result = await mirofishApi.sendScannerDeepSeekSummaryTelegram(alphaScannerRun.id, {
                summary: deepSeekSummary || undefined,
                limit: 5,
                model: deepSeekStatus?.default_model,
                thinking: false,
                channel: false,
            });
            if (!result.ok) throw new Error('Telegram send failed.');
            if (result.summary) setDeepSeekSummary(result.summary);
            setDeepSeekState('sent');
            markEndpoint('deepseek', 'ok');
        } catch (error) {
            setDeepSeekState('error');
            markEndpoint('deepseek', 'error');
            setDeepSeekErrorText(error instanceof Error ? error.message : 'DeepSeek Telegram send failed.');
        }
    }

    function selectAlphaCandidate(candidate: MiroFishAlphaCandidate) {
        const nextTarget = targetCandidateStartValue(candidate as TargetCandidate) || candidate.display_name || candidate.symbol;
        targetValueRef.current = nextTarget;
        setTarget(nextTarget);
        setTargetSnapshot({
            target: nextTarget,
            source: candidate.source || 'alpha_scanner',
            resolved: {
                symbol: candidate.symbol,
                display_name: candidate.display_name,
                market: candidate.market || 'KR',
            },
            signal_count: candidate.strategy_tags.length,
            source_files: [candidate.source || 'alpha_scanner'],
        });
    }

    function deepDiveAlphaCandidate(candidate: MiroFishAlphaCandidate) {
        const nextTarget = targetCandidateStartValue(candidate as TargetCandidate) || candidate.display_name || candidate.symbol;
        selectAlphaCandidate(candidate);
        requestStart(nextTarget);
    }

    function submitAnalysisForm(form: HTMLFormElement) {
        const formTarget = new FormData(form).get('target');
        requestStart(getStartTarget(typeof formTarget === 'string' ? formTarget : targetValueRef.current));
    }

    function requestStart(targetOverride?: string) {
        const now = Date.now();
        if (apiState === 'running' || now - lastStartAtRef.current < 600) return;
        lastStartAtRef.current = now;
        void handleStart(targetOverride);
    }

    function isEnterKey(event: ReactKeyboardEvent<HTMLElement>) {
        const native = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
        return event.key === 'Enter' || event.code === 'Enter' || event.key === 'NumpadEnter' || native.keyCode === 13;
    }

    function isComposing(event: ReactKeyboardEvent<HTMLElement> | ReactCompositionEvent<HTMLInputElement>) {
        const native = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
        return Boolean(native.isComposing || native.keyCode === 229);
    }

    const analysisSearchPanel = (
        <div className={subscriberMode ? 'mt-5 max-w-5xl' : 'mt-6 sm:mt-8 max-w-4xl'}>
            <form
                className="rounded-lg border border-white/10 bg-white/[0.035] p-1"
                onSubmit={(event) => {
                    event.preventDefault();
                    submitAnalysisForm(event.currentTarget);
                }}
                onKeyDownCapture={(event) => {
                    if (!isEnterKey(event)) return;
                    if (isComposing(event)) {
                        pendingCompositionStartRef.current = true;
                        return;
                    }
                    event.preventDefault();
                    event.stopPropagation();
                    event.currentTarget.requestSubmit();
                }}
            >
                <div className="flex flex-col gap-2 sm:flex-row">
                    <label className="flex min-h-12 flex-1 items-center gap-3 rounded-lg px-3 text-anthropic-darkMuted">
                        <i className="fas fa-search text-base" />
                        <input
                            name="target"
                            className="w-full bg-transparent text-base font-medium text-anthropic-cream outline-none placeholder:text-anthropic-darkMuted"
                            placeholder="삼성전자, 두산, SK, NVDA 등 분석 대상 입력"
                            value={target}
                            onChange={(event) => {
                                const nextTarget = event.target.value;
                                targetValueRef.current = nextTarget;
                                setTarget(nextTarget);
                                setTargetSnapshot(null);
                                setSuggestionTarget('');
                                setSuggestionCandidates([]);
                                setActiveCandidateIndex(0);
                                markEndpoint('resolve', 'idle');
                            }}
                            onKeyDown={(event) => {
                                handleTargetKeyNavigation(event);
                            }}
                            onCompositionEnd={(event) => {
                                const shouldStart = pendingCompositionStartRef.current;
                                pendingCompositionStartRef.current = false;
                                const composedTarget = event.currentTarget.value;
                                targetValueRef.current = composedTarget;
                                if (shouldStart) window.setTimeout(() => requestStart(composedTarget), 0);
                            }}
                        />
                    </label>
                    <button
                        type="submit"
                        aria-label="Run GraphRAG analysis"
                        disabled={apiState === 'running'}
                        className="min-h-12 rounded-md bg-cyan-400 px-6 text-sm font-black text-slate-950 transition hover:bg-cyan-300 disabled:cursor-wait disabled:opacity-50"
                    >
                        {apiState === 'running' ? '분석 중...' : '분석 시작'}
                    </button>
                </div>
            </form>

            {subscriberMode && (
                <div className="mt-2 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.07] px-4 py-2 text-xs font-bold text-cyan-50">
                    {formatSubscriberPolicy(subscriberPolicy)}
                </div>
            )}

            {targetCandidates.length > 0 && (
                <div className="mt-2 overflow-hidden rounded-lg border border-white/15 bg-slate-950/95 text-sm">
                    <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-400">
                        <span>Autocomplete</span>
                        <span>{targetCandidates.length} candidates</span>
                    </div>
                    <div className="max-h-72 overflow-y-auto p-1">
                        {targetCandidates.map((candidate, index) => {
                            const active = index === activeCandidateIndex;
                            const label = targetCandidateLabel(candidate);
                            return (
                                <button
                                    key={`${candidate.symbol}-${candidate.display_name}-${index}`}
                                    type="button"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => selectTargetCandidate(candidate)}
                                    onDoubleClick={() => selectTargetCandidate(candidate, true)}
                                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition ${active ? 'bg-cyan-400/[0.14] text-white ring-1 ring-cyan-300/35' : 'text-slate-200 hover:bg-white/[0.08]'}`}
                                >
                                    <span className={`grid h-8 w-8 place-items-center rounded-lg ${active ? 'bg-cyan-300 text-slate-950' : 'bg-white/10 text-cyan-200'}`}>
                                        <i className="fas fa-magnifying-glass-chart text-xs" />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate font-black">{label}</span>
                                        <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-400">
                                            {candidate.symbol || 'keyword'} · {candidate.market || 'KR'} · {candidate.yahoo_ticker || 'ticker pending'}
                                        </span>
                                    </span>
                                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-black ${active ? 'border-cyan-200/60 bg-cyan-200/[0.18] text-cyan-50' : 'border-white/10 bg-white/5 text-slate-400'}`}>
                                        {targetCandidateMatchLabel(candidate)}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {errorText && <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-xs font-bold text-amber-100">{errorText}</div>}

            {targetSnapshot && (
                <div className="mt-3 flex flex-wrap gap-2 text-xs font-bold">
                    <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1.5 text-cyan-100">
                        {targetSnapshot.resolved?.display_name || targetSnapshot.target}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1.5 text-slate-200">
                        {targetSnapshot.resolved?.symbol || 'keyword'} · {targetSnapshot.resolved?.market || 'UNKNOWN'}
                    </span>
                    <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1.5 text-emerald-100">
                        source files {targetSnapshot.source_files?.length || 0}
                    </span>
                    <span className="rounded-full border border-violet-300/20 bg-violet-300/10 px-3 py-1.5 text-violet-100">
                        signals {targetSnapshot.signal_count || 0}
                    </span>
                    {targetSnapshot.kis?.enabled && (
                        <span className={`rounded-full border px-3 py-1.5 ${targetSnapshot.kis.found ? 'border-cyan-300/20 bg-cyan-300/10 text-cyan-100' : 'border-slate-300/20 bg-white/10 text-slate-200'}`}>
                            {targetSnapshot.kis.found ? 'KIS live' : 'KIS standby'}
                        </span>
                    )}
                </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-slate-400">
                    <span>에이전트</span>
                    <button type="button" onClick={() => setAgentCount((value) => Math.max(1, value - 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-black/25 text-slate-200 hover:text-white">-</button>
                    <span className="text-xl font-black text-cyan-300 font-mono">{agentCount}</span>
                    <button type="button" onClick={() => setAgentCount((value) => Math.min(15, value + 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-black/25 text-slate-200 hover:text-white">+</button>
                </div>
                <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] p-1">
                    {agentCounts.map((count) => (
                        <button key={count} type="button" onClick={() => setAgentCount(count)} className={`h-8 min-w-8 rounded-lg px-2 text-xs font-bold transition-colors ${count === agentCount ? 'bg-cyan-400 text-slate-950' : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'}`}>
                            {count}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );

    return (
        <div className="space-y-5">
            <section className={`border-b ${
                subscriberMode
                    ? 'border-cyan-300/15 bg-[#0d1320]/80'
                    : 'border-anthropic-darkLine bg-transparent'
            }`}>
                <div className="px-4 py-5 sm:px-5 sm:py-7 md:px-8 md:py-10">
                    <div className="flex flex-wrap items-center justify-between gap-2 sm:gap-3">
                        <div className={`inline-flex items-center gap-1.5 sm:gap-2 rounded-full border px-2.5 sm:px-3 py-1 sm:py-1.5 text-[11px] sm:text-xs font-medium ${
                            subscriberMode
                                ? 'border-cyan-500/30 bg-cyan-500/[0.06] text-cyan-300'
                                : 'border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkText'
                        }`}>
                            <i className={`fas ${subscriberMode ? 'fa-robot text-cyan-400' : 'fa-lock text-anthropic-orange'}`} />
                            {subscriberMode ? 'Pro + AI Brain 구독자 콘솔' : '관리자 전용 리서치 콘솔'}
                        </div>
                        <div className={`inline-flex items-center gap-1.5 sm:gap-2 rounded-full border px-2.5 sm:px-3 py-1 sm:py-1.5 text-[11px] sm:text-xs font-medium ${
                            apiState === 'error'
                                ? 'border-red-500/30 bg-red-500/[0.08] text-red-300'
                                : apiState === 'running'
                                    ? 'border-anthropic-orange/30 bg-anthropic-orange/[0.10] text-anthropic-orange'
                                    : 'border-anthropic-darkLine bg-anthropic-dark2 text-anthropic-darkMuted'
                        }`}>
                            <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                                apiState === 'error' ? 'bg-red-400' :
                                apiState === 'running' ? 'bg-anthropic-orange animate-pulse' :
                                'bg-anthropic-darkMuted'
                            }`} />
                            {apiState === 'checking' ? 'MiroFish 점검 중' : apiState === 'running' ? '분석 실행 중' : apiState === 'error' ? 'API 오류' : 'MiroFish 준비됨'}
                        </div>
                    </div>

                    <div className="mt-4 max-w-4xl">
                        <h1 className={`${subscriberMode ? 'text-2xl sm:text-3xl' : 'font-serif text-[26px] sm:text-[34px] md:text-[42px] font-medium'} leading-[1.15] tracking-tight text-anthropic-cream`}>
                            {subscriberMode ? 'AI Brain 검출 대시보드' : (
                                <>MiroFish <span className="italic">Market Brain</span></>
                            )}
                        </h1>
                        <p className="mt-2 max-w-3xl text-sm font-medium leading-6 text-anthropic-darkMuted">
                            {subscriberMode
                                ? '오늘의 검출 · 성과 검증 · 학습 피드백을 한 화면에서.'
                                : '검출 · 분석 · 성과 검증 · 운영을 단일 콘솔에서.'}
                        </p>
                    </div>

                    {brainSignals.length > 0 && (
                        <div className="mt-4 flex flex-wrap gap-1.5 sm:gap-2">
                            {brainSignals.map((signal) => (
                                <span key={signal.label} className="inline-flex items-center gap-2 rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 px-3 py-1.5 text-[11px] font-medium text-anthropic-darkMuted">
                                    <span className="tracking-wide">{signal.label}</span>
                                    <span className="text-anthropic-cream font-mono text-xs">{signal.value}</span>
                                </span>
                            ))}
                        </div>
                    )}

                    {analysisSearchPanel}

                    <div className="mt-5 grid gap-5 2xl:grid-cols-[minmax(0,1.65fr)_minmax(400px,0.72fr)] 2xl:items-start">
                        <section className="min-w-0 rounded-2xl border border-cyan-300/15 bg-cyan-300/[0.035] p-3 shadow-[0_18px_70px_rgba(8,145,178,0.10)]">
                            <div className="mb-3 flex flex-col gap-3 rounded-xl border border-cyan-300/12 bg-black/20 px-4 py-3 md:flex-row md:items-center md:justify-between">
                                <div>
                                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-cyan-200/75">Left Format</div>
                                    <h2 className="mt-1 text-lg font-black text-white">검출·분석 실행 레인</h2>
                                    <p className="mt-1 text-xs font-semibold text-slate-400">
                                        스캐너 실행, 신규 이벤트 Top3, DeepSeek 요약은 이 레인에서 독립 실행합니다.
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        type="button"
                                        onClick={handleAlphaScan}
                                        disabled={alphaScannerState === 'loading' || alphaScannerState === 'running'}
                                        className="rounded-lg border border-emerald-300/25 bg-emerald-300/12 px-3 py-2 text-xs font-black text-emerald-100 transition hover:bg-emerald-300/18 disabled:cursor-wait disabled:opacity-60"
                                    >
                                        {alphaScannerState === 'loading' || alphaScannerState === 'running' ? '스캔 중...' : '스캐너 실행'}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleMcpWorkflow(false)}
                                        disabled={workflowState === 'running'}
                                        className="rounded-lg border border-cyan-300/25 bg-cyan-300/12 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-300/18 disabled:cursor-wait disabled:opacity-60"
                                    >
                                        {workflowState === 'running' ? 'Top3 분석 중...' : 'MCP Top3 실행'}
                                    </button>
                                </div>
                            </div>
                            <div id="alpha-board" className="scroll-mt-4">
                                <AlphaBoardPanel
                                    candidates={alphaCandidates}
                                    scannerRun={alphaScannerRun}
                                    scannerStatus={alphaScannerStatus}
                                    state={alphaScannerState}
                                    errorText={alphaErrorText}
                                    deepSeekStatus={deepSeekStatus}
                                    deepSeekState={deepSeekState}
                                    deepSeekSummary={deepSeekSummary}
                                    deepSeekErrorText={deepSeekErrorText}
                                    workflow={workflow}
                                    workflowState={workflowState}
                                    workflowErrorText={workflowErrorText}
                                    autonomousStatus={autonomousStatus}
                                    onScan={handleAlphaScan}
                                    onWorkflow={() => handleMcpWorkflow(false)}
                                    onForceWorkflow={() => handleMcpWorkflow(true)}
                                    onDeepSeekSummary={handleDeepSeekSummary}
                                    onSendDeepSeekTelegram={handleSendDeepSeekTelegram}
                                    onSelect={selectAlphaCandidate}
                                    onDeepDive={deepDiveAlphaCandidate}
                                    subscriberMode={subscriberMode}
                                />
                            </div>
                            <div className="mt-4">
                                <MirofishChatPanel variant="inline" />
                            </div>
                        </section>
                        <aside className="min-w-0 2xl:sticky 2xl:top-4">
                            <section className="rounded-2xl border border-amber-300/18 bg-amber-300/[0.035] p-3 shadow-[0_18px_70px_rgba(245,158,11,0.09)]">
                                <div className="mb-3 rounded-xl border border-amber-300/12 bg-black/25 px-4 py-3">
                                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                        <div>
                                            <div className="text-[10px] font-black uppercase tracking-[0.22em] text-amber-200/75">Right Format</div>
                                            <h2 className="mt-1 text-lg font-black text-white">운영·성과 모니터 레인</h2>
                                            <p className="mt-1 text-xs font-semibold text-slate-400">
                                                파이프라인, 성과검증, 히스토리, 운영 진단을 별도 갱신합니다.
                                            </p>
                                        </div>
                                        <div className="flex flex-wrap gap-2">
                                            <button
                                                type="button"
                                                onClick={refreshOpsLane}
                                                disabled={opsLaneState === 'refreshing'}
                                                className="rounded-lg border border-amber-300/25 bg-amber-300/12 px-3 py-2 text-xs font-black text-amber-100 transition hover:bg-amber-300/18 disabled:cursor-wait disabled:opacity-60"
                                            >
                                                {opsLaneState === 'refreshing' ? '갱신 중...' : '운영 현황 새로고침'}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => handleMcpWorkflow(false)}
                                                disabled={workflowState === 'running'}
                                                className="rounded-lg border border-cyan-300/25 bg-cyan-300/12 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-300/18 disabled:cursor-wait disabled:opacity-60"
                                            >
                                                {workflowState === 'running' ? '실행 중...' : '우측 Top3 실행'}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                <div key={`ops-lane-${opsLaneRefreshKey}`} className="flex flex-col gap-3">
                                    <TodaysPipelineCard />
                                    <ScanPerformanceCard />
                                    <ScanHistoryCard />
                                    <RecentOutcomesBoard />
                                    {!subscriberMode && (
                                        <details className="group rounded-xl border border-white/10 bg-white/[0.03]">
                                            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-black text-slate-200 [&::-webkit-details-marker]:hidden">
                                                <span>운영 진단</span>
                                                <span className="text-[10px] uppercase tracking-wider text-slate-500 transition-transform group-open:rotate-180">▼</span>
                                            </summary>
                                            <div className="flex flex-col gap-3 border-t border-white/10 p-3">
                                                <AutoRunnerCard />
                                                <AutonomousMcpPanel
                                                    status={autonomousStatus}
                                                    state={autonomousState}
                                                    result={autonomousResult}
                                                    learning={autonomousLearning}
                                                    errorText={autonomousErrorText}
                                                    confirmation={autonomousConfirmation}
                                                    sharedSecret={autonomousSharedSecret}
                                                    onConfirmationChange={setAutonomousConfirmation}
                                                    onSharedSecretChange={setAutonomousSharedSecret}
                                                    onRefresh={refreshAutonomousStatus}
                                                    onDetectionDryRun={handleAutonomousDetectionDryRun}
                                                    onAnalysisDryRun={handleAutonomousAnalysisDryRun}
                                                    onLearningPreview={handleAutonomousLearningPreview}
                                                    onSendLatestTelegram={handleSendLatestAutonomousTelegram}
                                                />
                                                <AlphaEndpointBlueprintCard
                                                    blueprint={alphaEndpointBlueprint}
                                                    resourceSnapshot={mcpResourceSnapshot}
                                                />
                                                <GraphRAGStatusCard />
                                                <GraphRAGEntityResolverCard />
                                                <QuickActionsFooter />
                                            </div>
                                        </details>
                                    )}
                                </div>
                            </section>
                        </aside>
                    </div>

                </div>
            </section>

            {isAnalyzing && <ImpactPanel phase={phase} run={run} apiState={apiState} />}

            {/* API endpoint health grid — collapsible, default hidden. Polling/state still active for downstream UI. */}
            <details className="group rounded-xl border border-amber-500/15 bg-black/60 overflow-hidden">
                <summary className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 list-none [&::-webkit-details-marker]:hidden hover:bg-white/[0.02]">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[10px] font-black uppercase tracking-[0.18em] text-neutral-500">API Endpoints</span>
                        <span className="text-[10px] font-bold text-neutral-600">·</span>
                        <span className="text-[11px] font-bold text-neutral-400 truncate">
                            {(() => {
                                const states = Object.values(endpointState);
                                const ok = states.filter((s) => s === 'ok').length;
                                const err = states.filter((s) => s === 'error').length;
                                const loading = states.filter((s) => s === 'loading').length;
                                return `${ok}/${states.length} OK${err ? ` · ${err} error` : ''}${loading ? ` · ${loading} checking` : ''}`;
                            })()}
                        </span>
                    </div>
                    <span className="shrink-0 text-[10px] font-black uppercase tracking-wider text-neutral-500 transition-transform group-open:rotate-180">
                        ▼
                    </span>
                </summary>
                <div className="border-t border-amber-500/10 p-3 sm:p-4">
                    <div className="grid gap-2 sm:gap-3 grid-cols-2 lg:grid-cols-3">
                        {endpointDefinitions.map((endpoint) => {
                            const state = endpointState[endpoint.key];
                            return (
                                <section key={endpoint.key} className="rounded-xl border border-anthropic-darkLine bg-anthropic-dark p-3 sm:p-5 transition-colors hover:border-anthropic-orange/30 min-w-0">
                                    <div className="flex items-start justify-between gap-1.5 sm:gap-2">
                                        <span className="grid h-8 w-8 sm:h-10 sm:w-10 shrink-0 place-items-center rounded-lg border border-anthropic-darkLine bg-anthropic-dark2">
                                            <i className={`fas ${endpoint.icon} ${endpoint.color} text-xs sm:text-base`} />
                                        </span>
                                        <span className={`rounded-full border px-1.5 sm:px-2 py-0.5 sm:py-1 text-[9px] sm:text-[11px] font-medium tracking-wide ${endpointStatusTone(state)}`}>
                                            {state.toUpperCase()}
                                        </span>
                                    </div>
                                    <h2 className="mt-2 sm:mt-4 font-serif text-sm sm:text-lg font-medium text-anthropic-cream truncate">{endpoint.title}</h2>
                                    <div className="mt-1 sm:mt-2 flex items-center gap-1 sm:gap-1.5 font-mono text-[9px] sm:text-[11px] text-anthropic-darkMuted min-w-0">
                                        <span className="rounded border border-anthropic-darkLine bg-anthropic-dark2 px-1 sm:px-1.5 py-0.5 text-anthropic-orange shrink-0">{endpoint.method}</span>
                                        <span className="truncate">{endpoint.path}</span>
                                    </div>
                                    <p className="mt-1.5 sm:mt-3 truncate text-[11px] sm:text-sm text-anthropic-darkText">{endpointMetrics[endpoint.key]}</p>
                                </section>
                            );
                        })}
                    </div>
                </div>
            </details>

            <details className="group rounded-xl border border-anthropic-darkLine bg-anthropic-dark/70">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
                    <div className="min-w-0">
                        <h2 className="text-sm font-black text-anthropic-cream">파이프라인 상태</h2>
                        <p className="mt-0.5 truncate text-xs text-anthropic-darkMuted">
                            {status?.pipeline?.status || '/api/admin/mirofish/status 응답 대기 중'}
                        </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                            apiState === 'error'
                                ? 'border-red-500/30 bg-red-500/[0.08] text-red-400'
                                : 'border-green-500/30 bg-green-500/[0.08] text-green-400'
                        }`}>
                            {apiState === 'error' ? 'API 오류' : 'API 연결'}
                        </span>
                        <span className="text-[10px] uppercase tracking-wider text-anthropic-darkMuted transition-transform group-open:rotate-180">▼</span>
                    </div>
                </summary>
                <div className="border-t border-anthropic-darkLine p-4">
                    <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:overflow-visible sm:px-0">
                        <div className="flex min-w-max gap-2 sm:grid sm:min-w-0 sm:grid-cols-5">
                            {runSteps.map((step, index) => {
                                const linkedState = endpointState[runStepEndpoints[index]];
                                const ready = linkedState === 'ok' && (!isAnalyzing || index + 1 <= phase);
                                return (
                                    <div key={step} className="w-36 shrink-0 rounded-lg border border-anthropic-darkLine bg-anthropic-dark2 p-3 sm:w-auto sm:shrink">
                                        <div className="flex items-center justify-between">
                                            <span className="text-[10px] font-medium uppercase tracking-wider text-anthropic-darkMuted">단계 {index + 1}</span>
                                            <span className={`h-1.5 w-1.5 rounded-full ${
                                                ready ? 'bg-green-400' :
                                                linkedState === 'error' ? 'bg-red-400' :
                                                linkedState === 'loading' ? 'bg-anthropic-orange animate-pulse' :
                                                'bg-anthropic-darkMuted'
                                            }`} />
                                        </div>
                                        <div className="mt-2 text-sm font-medium text-anthropic-cream">{step}</div>
                                        <div className="mt-0.5 text-xs text-anthropic-darkMuted">
                                            {ready ? '엔드포인트 확인' : linkedState === 'error' ? '오류' : linkedState === 'loading' ? '로딩 중' : '대기 중'}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            </details>
        </div>
    );
}
