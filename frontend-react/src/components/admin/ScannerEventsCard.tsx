import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    MiroFishScannerAlertEvent,
    MiroFishScannerAlertState,
    MiroFishScannerMonitorState,
    MiroFishScannerTradingAgentsHistoryRecord,
    mirofishApi,
} from '@/lib/mirofishApi';

const ACTION_LABELS: Record<string, string> = {
    BUY_CANDIDATE: '매수 후보',
    BUY: '매수',
    WATCH: '관찰',
    AVOID: '회피',
};

const STATUS_LABELS: Record<string, string> = {
    sent: '신규 전송됨',
    no_new_events: '신규 없음',
    unchanged: '변동 없음',
    blocked: '알림 차단',
    send_failed: '전송 실패',
    pending_send: '전송 대기',
    retry_wait: '재시도 대기',
};

const TA_VERDICT_STYLE: Record<string, string> = {
    STRONG_BUY: 'border-emerald-300/40 bg-emerald-300/10 text-emerald-200',
    BUY: 'border-sky-300/40 bg-sky-300/10 text-sky-200',
    HOLD: 'border-white/15 bg-white/[0.06] text-slate-300',
    SELL: 'border-rose-300/40 bg-rose-300/10 text-rose-200',
};

const TA_VERDICT_LABEL: Record<string, string> = {
    STRONG_BUY: '강력 매수',
    BUY: '매수',
    HOLD: '관망',
    SELL: '매도/회피',
};

const POLL_INTERVAL_MS = 30000;
const CACHE_KEY = 'marketflow.mirofish.scanner-events.v1';

interface ScannerEventsCache {
    monitor: MiroFishScannerMonitorState | null;
    alerts: MiroFishScannerAlertState | null;
    cachedAt: string;
}

function alertEvents(alerts?: MiroFishScannerAlertState | null) {
    return Array.isArray(alerts?.feed_events)
        ? alerts.feed_events
        : alerts?.recent_sent_events ?? [];
}

function eventTimestamp(event?: MiroFishScannerAlertEvent | null) {
    const parsed = Date.parse(String(event?.sent_at || ''));
    return Number.isFinite(parsed) ? parsed : 0;
}

function readCache(): ScannerEventsCache | null {
    try {
        const raw = window.localStorage.getItem(CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw) as ScannerEventsCache;
        return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
        return null;
    }
}

function preserveLatestEvents(previous: MiroFishScannerAlertState | null, next: MiroFishScannerAlertState) {
    const previousEvents = alertEvents(previous);
    const nextEvents = alertEvents(next);
    const previousLatest = Math.max(0, ...previousEvents.map(eventTimestamp));
    const nextLatest = Math.max(0, ...nextEvents.map(eventTimestamp));
    if (previousEvents.length > 0 && (nextEvents.length === 0 || nextLatest < previousLatest)) {
        return {
            ...next,
            feed_events: previousEvents,
            feed_event_count: previousEvents.length,
        };
    }
    return next;
}

function enrichWithDeepSeekBriefs(
    state: MiroFishScannerAlertState,
    fallbackEvents: MiroFishScannerAlertEvent[],
) {
    const briefs = new Map(
        fallbackEvents
            .filter((event) => event?.symbol && event.deepseek_brief)
            .map((event) => [String(event.symbol), String(event.deepseek_brief)]),
    );
    if (briefs.size === 0) return state;
    const enrich = (events?: MiroFishScannerAlertEvent[]) => events?.map((event) => {
        if (!event || event.deepseek_brief) return event;
        const brief = briefs.get(String(event.symbol || ''));
        return brief ? { ...event, deepseek_brief: brief } : event;
    });
    return {
        ...state,
        feed_events: enrich(state.feed_events),
        recent_sent_events: enrich(state.recent_sent_events),
    };
}

function enrichWithTradingAgentsHistory(
    state: MiroFishScannerAlertState,
    records: MiroFishScannerTradingAgentsHistoryRecord[],
) {
    const history = new Map(records.map((record) => [record.event_key, record]));
    const latestBySymbol = new Map<string, MiroFishScannerTradingAgentsHistoryRecord>();
    records.forEach((record) => {
        const symbol = String(record.symbol || '').trim();
        if (symbol && !latestBySymbol.has(symbol)) latestBySymbol.set(symbol, record);
    });
    if (history.size === 0) return state;
    const enrich = (events?: MiroFishScannerAlertEvent[]) => events?.map((event) => {
        if (!event || event.tradingagents) return event;
        const exact = event.event_key ? history.get(event.event_key) : undefined;
        const symbolMatch = latestBySymbol.get(String(event.symbol || '').trim());
        const eventDate = String(event.sent_at || '').slice(0, 10);
        const detectedDate = String(symbolMatch?.detected_at || '').slice(0, 10);
        const record = exact || (eventDate && detectedDate === eventDate ? symbolMatch : undefined);
        if (!record?.verdict) return event;
        return {
            ...event,
            tradingagents: {
                verdict: record.verdict,
                confidence: Number(record.confidence ?? 0),
                strong_buy: Boolean(record.strong_buy),
                regime: record.regime ?? undefined,
                regime_adjustment: record.regime_adjustment ?? undefined,
                method: record.method ?? undefined,
                verified_at: record.verified_at ?? undefined,
            },
        };
    });
    return {
        ...state,
        feed_events: enrich(state.feed_events),
        recent_sent_events: enrich(state.recent_sent_events),
    };
}

function actionLabel(action?: string | null) {
    if (!action) return '';
    return ACTION_LABELS[action] || action;
}

function statusTone(status?: string | null) {
    if (status === 'sent') return 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300';
    if (status === 'blocked' || status === 'send_failed') return 'border-rose-400/30 bg-rose-500/10 text-rose-300';
    if (status === 'no_new_events' || status === 'unchanged') return 'border-white/15 bg-white/[0.06] text-gray-400';
    return 'border-cyan-400/30 bg-cyan-500/10 text-cyan-300';
}

function qualityLabel(value?: string | null) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const upper = raw.toUpperCase();
    if (/^[A-D][+-]?$/.test(upper)) return upper;
    if (upper === 'HIGH_CONVICTION') return 'A';
    if (upper === 'ACTIONABLE') return 'B';
    if (upper === 'WATCH') return 'C';
    return upper.replace(/_/g, ' ');
}

function fmtPrice(value?: number | string | null) {
    const numeric = typeof value === 'number'
        ? value
        : typeof value === 'string'
            ? Number(value.replace(/,/g, ''))
            : NaN;
    if (!Number.isFinite(numeric)) return '@--';
    return `@${Math.round(numeric).toLocaleString('ko-KR')}`;
}

function fmtPct(value?: number | null) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return null;
    const sign = numeric > 0 ? '+' : '';
    return `${sign}${numeric.toFixed(2)}%`;
}

function fmtKST(iso?: string | null) {
    if (!iso) return '--';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '--';
    return date.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

interface ScannerEventsCardProps {
    className?: string;
    compact?: boolean;
    maxEvents?: number;
    token?: string;
    fallbackEvents?: MiroFishScannerAlertEvent[];
}

export default function ScannerEventsCard({ className = '', compact = false, maxEvents = 8, fallbackEvents = [] }: ScannerEventsCardProps) {
    const cached = useMemo(readCache, []);
    const [monitor, setMonitor] = useState<MiroFishScannerMonitorState | null>(cached?.monitor ?? null);
    const [alerts, setAlerts] = useState<MiroFishScannerAlertState | null>(cached?.alerts ?? null);
    const [loading, setLoading] = useState(!cached?.alerts);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');
    const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(cached?.cachedAt ?? null);
    const inFlightRef = useRef(false);
    const monitorRef = useRef(monitor);

    const load = useCallback(async (opts?: { silent?: boolean }) => {
        if (inFlightRef.current) return;
        inFlightRef.current = true;
        if (opts?.silent) setRefreshing(true);
        else setLoading(true);
        try {
            const [monitorResult, alertResult, historyResult] = await Promise.allSettled([
                mirofishApi.getScannerMonitorStatus(true),
                mirofishApi.getScannerAlertState(true),
                mirofishApi.getScannerTradingAgentsHistory(maxEvents * 4),
            ]);
            if (monitorResult.status === 'rejected' && alertResult.status === 'rejected') {
                throw new Error('scanner feed unavailable');
            }
            const updatedAt = new Date().toISOString();
            const monitorState = monitorResult.status === 'fulfilled' ? monitorResult.value : monitorRef.current;
            const alertState = alertResult.status === 'fulfilled' ? alertResult.value : {
                feed_events: fallbackEvents,
                feed_event_count: fallbackEvents.length,
            };
            if (monitorResult.status === 'fulfilled') {
                monitorRef.current = monitorState;
                setMonitor(monitorState);
            }
            setAlerts((previous) => {
                const next = enrichWithTradingAgentsHistory(
                    enrichWithDeepSeekBriefs(
                        preserveLatestEvents(previous, alertState),
                        fallbackEvents,
                    ),
                    historyResult.status === 'fulfilled' ? historyResult.value.records : [],
                );
                try {
                    window.localStorage.setItem(CACHE_KEY, JSON.stringify({
                        monitor: monitorState,
                        alerts: next,
                        cachedAt: updatedAt,
                    } satisfies ScannerEventsCache));
                } catch { /* private mode / quota */ }
                return next;
            });
            setLastUpdatedAt(updatedAt);
            setError(monitorResult.status === 'rejected' || alertResult.status === 'rejected'
                ? '일부 스캐너 상태를 불러오지 못해 마지막 정상 캐시를 유지합니다.'
                : '');
        } catch {
            setError('스캐너 이벤트를 불러오지 못했습니다.');
        } finally {
            setLoading(false);
            setRefreshing(false);
            inFlightRef.current = false;
        }
    }, [fallbackEvents, maxEvents]);

    useEffect(() => {
        if (fallbackEvents.length === 0) return;
        const updatedAt = new Date().toISOString();
        setAlerts((previous) => {
            const next = enrichWithDeepSeekBriefs(preserveLatestEvents(previous, {
                feed_events: fallbackEvents,
                feed_event_count: fallbackEvents.length,
            }), fallbackEvents);
            try {
                window.localStorage.setItem(CACHE_KEY, JSON.stringify({
                    monitor: monitorRef.current,
                    alerts: next,
                    cachedAt: updatedAt,
                } satisfies ScannerEventsCache));
            } catch { /* private mode / quota */ }
            return next;
        });
        setLastUpdatedAt(updatedAt);
    }, [fallbackEvents]);

    useEffect(() => {
        void load();
        const refresh = () => void load({ silent: true });
        const handleVisibilityChange = () => {
            if (!document.hidden) refresh();
        };
        const id = window.setInterval(refresh, POLL_INTERVAL_MS);
        window.addEventListener('focus', refresh);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        return () => {
            window.clearInterval(id);
            window.removeEventListener('focus', refresh);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
        };
    }, [load]);

    const events = useMemo(() => {
        // feed_events is the server-filtered, delivered BUY event feed. Only use
        // recent_sent_events for older API payloads that do not expose feed_events.
        const list = alertEvents(alerts);
        return [...list]
            .sort((left, right) => String(right.sent_at ?? '').localeCompare(String(left.sent_at ?? '')))
            .slice(0, maxEvents);
    }, [alerts, maxEvents]);

    const eventTime = events[0]?.sent_at || alerts?.latest_run_at || monitor?.last_checked_at || alerts?.last_sent_at || null;
    const candidateCount = alerts?.last_candidate_count ?? monitor?.last_candidate_count ?? alerts?.latest_candidate_count ?? null;
    const newCount = alerts?.last_new_event_count ?? alerts?.latest_new_event_count ?? monitor?.last_new_event_count ?? 0;
    const hasNew = Number(newCount) > 0;

    return (
        <section className={`w-full min-w-0 overflow-hidden rounded-2xl border border-cyan-300/18 bg-[#0d1824] ${compact ? 'p-3' : 'p-4'} shadow-[0_18px_70px_rgba(8,145,178,0.09)] ${className}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.22em] text-cyan-200/75">Alpha Scanner Feed</div>
                    <h2 className={`mt-1 flex flex-wrap items-center gap-2 font-black text-white ${compact ? 'text-base' : 'text-lg'}`}>
                        <i className="fas fa-satellite-dish text-cyan-300" />
                        알파 스캐너 신규 이벤트
                        {hasNew && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-300/35 bg-emerald-300/12 px-2 py-0.5 text-[10px] font-black text-emerald-200">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                                신규 {newCount}건
                            </span>
                        )}
                    </h2>
                </div>
                <button
                    type="button"
                    onClick={() => void load({ silent: true })}
                    className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-slate-300 transition hover:bg-white/[0.09] hover:text-white"
                    title="새로고침"
                >
                    <i className={`fas fa-rotate-right text-xs ${refreshing ? 'fa-spin' : ''}`} />
                </button>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                <span className="col-span-2 min-w-0 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-bold text-slate-200 sm:col-span-1">
                    시각 <span className="font-mono text-white">{fmtKST(eventTime)}</span>
                </span>
                <span className="min-w-0 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-bold text-slate-200">
                    최종 후보 <span className="font-mono text-white">{candidateCount ?? '--'}</span>개
                </span>
                <span className={`min-w-0 rounded-full border px-3 py-1 text-xs font-bold ${hasNew ? 'border-emerald-300/30 bg-emerald-300/12 text-emerald-200' : 'border-white/10 bg-white/[0.04] text-slate-300'}`}>
                    신규 <span className="font-mono">{newCount ?? 0}</span>개
                </span>
                {monitor?.last_status && (
                    <span className={`col-span-2 min-w-0 rounded-full border px-3 py-1 text-xs font-bold sm:col-span-1 ${statusTone(monitor.last_status)}`}>
                        {STATUS_LABELS[monitor.last_status] || monitor.last_status}
                    </span>
                )}
                {lastUpdatedAt && (
                    <span className="col-span-2 min-w-0 rounded-full border border-cyan-300/15 bg-cyan-300/[0.06] px-3 py-1 text-xs font-bold text-cyan-100 sm:col-span-1">
                        갱신 <span className="font-mono">{fmtKST(lastUpdatedAt)}</span>
                    </span>
                )}
            </div>

            {error && (
                <div className="mt-4 rounded-xl border border-amber-300/20 bg-amber-300/[0.06] px-3 py-2 text-xs font-bold text-amber-100">
                    {events.length > 0 ? '새 이벤트 확인에 실패해 마지막 정상 캐시를 유지합니다.' : error}
                </div>
            )}

            {loading && events.length === 0 ? (
                <div className="mt-4 flex items-center justify-center rounded-xl border border-white/10 bg-black/20 py-6 text-sm font-bold text-slate-400">
                    <i className="fas fa-spinner fa-spin mr-2 text-cyan-300" />
                    불러오는 중...
                </div>
            ) : events.length === 0 ? (
                <div className="mt-4 rounded-xl border border-dashed border-white/12 bg-white/[0.02] p-5 text-sm font-semibold text-slate-400">
                    아직 전송된 신규 이벤트 종목이 없습니다. 조건 충족 후보가 나오면 이 위젯에 자동 표시됩니다.
                </div>
            ) : (
                <div className={`mt-4 grid gap-2 ${compact ? '' : 'md:grid-cols-2'}`}>
                    {events.map((event, index) => (
                        <ScannerEventRow key={event.event_key ?? `${event.symbol ?? 'unknown'}-${index}`} event={event} compact={compact} />
                    ))}
                </div>
            )}

            <p className="mt-3 text-[11px] font-semibold text-slate-500">
                텔레그램으로 전송되는 알파 스캐너 신규 후보와 같은 피드입니다. 30초마다 자동 갱신하며, 탭 복귀 시 즉시 다시 확인합니다.
            </p>
        </section>
    );
}

function ScannerEventRow({ event, compact = false }: { event: MiroFishScannerAlertEvent; compact?: boolean }) {
    const pct = fmtPct(event.price?.change_rate);
    const up = Number(event.price?.change_rate ?? 0) >= 0;
    const quality = qualityLabel(event.signal_quality);

    return (
        <article className={`min-w-0 rounded-xl border border-white/10 bg-white/[0.035] ${compact ? 'p-2.5' : 'p-3'}`}>
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="font-mono text-xs font-black text-cyan-200">{event.symbol || '--'}</span>
                        <span className="min-w-0 max-w-full flex-1 truncate text-sm font-black text-white">{event.display_name || event.symbol || '이름 없음'}</span>
                        {event.market && <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">{event.market}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs font-bold">
                        <span className="font-mono text-slate-200">{fmtPrice(event.price?.current_price)}</span>
                        {pct && <span className={`font-mono ${up ? 'text-rose-300' : 'text-sky-300'}`}>{pct}</span>}
                        <span className="text-slate-600">·</span>
                        <span className="font-mono text-slate-500">{fmtKST(event.sent_at)}</span>
                    </div>
                </div>
                {event.rank != null && (
                    <span className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 font-mono text-xs font-black text-slate-300">
                        #{event.rank}
                    </span>
                )}
            </div>

            <div className="mt-2 flex flex-wrap gap-1.5">
                {event.action && (
                    <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[10px] font-black text-cyan-200">
                        {actionLabel(event.action)}
                    </span>
                )}
                {quality && (
                    <span className="rounded-full border border-violet-300/30 bg-violet-300/10 px-2 py-0.5 text-[10px] font-black text-violet-200">
                        등급 {quality}
                    </span>
                )}
                {event.risk_score != null && (
                    <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2 py-0.5 text-[10px] font-black text-amber-200">
                        리스크 {event.risk_score}
                    </span>
                )}
                {event.alpha_score != null && (
                    <span className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-2 py-0.5 text-[10px] font-black text-emerald-200">
                        알파 {event.alpha_score}
                    </span>
                )}
            </div>

            {event.tradingagents && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.04] px-2.5 py-2">
                    <i className="fas fa-shield-halved text-[10px] text-cyan-300" aria-hidden="true" />
                    <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-black ${TA_VERDICT_STYLE[event.tradingagents.verdict] || TA_VERDICT_STYLE.HOLD}`}>
                        13D 딥검증 · 매매의견 {TA_VERDICT_LABEL[event.tradingagents.verdict] || event.tradingagents.verdict}
                    </span>
                    <span className="text-[10px] font-bold text-slate-400">확신 {Math.round(event.tradingagents.confidence)}%</span>
                    {event.tradingagents.strong_buy && <span className="text-[10px] font-black text-orange-300">🔥 매수유력</span>}
                    {event.tradingagents.regime && (
                        <span className="text-[10px] font-semibold text-slate-500">
                            레짐 {event.tradingagents.regime}
                            {event.tradingagents.regime_adjustment?.applied
                                ? ` · 보정 ${event.tradingagents.regime_adjustment.applied > 0 ? '+' : ''}${event.tradingagents.regime_adjustment.applied}`
                                : ''}
                        </span>
                    )}
                    <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-cyan-300/70">TradingAgents</span>
                </div>
            )}

            {!event.tradingagents && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-white/[0.025] px-2.5 py-2 text-[10px] font-bold text-slate-500">
                    <i className="fas fa-shield-halved text-[10px]" aria-hidden="true" />
                    <span>13D 딥검증 · 매매의견 검증 대기</span>
                </div>
            )}

            {event.deepseek_brief && (
                <div className="mt-2 flex min-w-0 items-start gap-2 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.055] px-2.5 py-2">
                    <i className="fas fa-wand-magic-sparkles mt-0.5 shrink-0 text-[10px] text-cyan-300" aria-hidden="true" />
                    <p className="line-clamp-2 min-w-0 text-[11px] font-semibold leading-[1.45] text-slate-300">
                        <span className="mr-1 font-black text-cyan-200">DeepSeek</span>
                        {event.deepseek_brief}
                    </p>
                </div>
            )}
        </article>
    );
}
