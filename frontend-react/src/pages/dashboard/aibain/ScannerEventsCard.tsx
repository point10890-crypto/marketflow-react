import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchAuthAPI } from '@/lib/api';

/**
 * 알파 스캐너 신규 이벤트 위젯.
 * 텔레그램으로 전송되는 MiroFish 알파 스캐너 신규 매수 후보를 대시보드에 그대로 노출한다.
 * 구독자(admin_or_aibain) 접근 가능한 두 엔드포인트를 직접 조회 — 백엔드 변경 없음.
 *  - /scanner/monitor/status : 최종 후보 수 / 신규 수 / 최근 점검 시각
 *  - /scanner/alerts/state   : 최근 신규 이벤트 종목 목록(recent_sent_events)
 */

interface ScannerEvent {
    event_key?: string;
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
    price?: { current_price?: number | null; change_rate?: number | null; date?: string | null };
    sent_at?: string | null;
    generated_at?: string | null;
    run_id?: string | null;
}

interface MonitorState {
    last_candidate_count?: number | null;
    last_new_event_count?: number | null;
    last_run_id?: string | null;
    last_checked_at?: string | null;
    last_status?: string | null;
    last_error?: string | null;
}

interface AlertState {
    recent_sent_events?: ScannerEvent[];
    sent_event_count?: number | null;
    last_sent_at?: string | null;
}

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

function fmtPrice(n?: number | null) {
    if (n == null || !Number.isFinite(n)) return '—';
    return `₩${Math.round(n).toLocaleString('ko-KR')}`;
}

function fmtPct(n?: number | null) {
    if (n == null || !Number.isFinite(n)) return null;
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}%`;
}

function fmtKST(iso?: string | null) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

export default function ScannerEventsCard({ token }: { token?: string }) {
    const [monitor, setMonitor] = useState<MonitorState | null>(null);
    const [alerts, setAlerts] = useState<AlertState | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');

    const load = useCallback(async (opts?: { silent?: boolean }) => {
        if (opts?.silent) setRefreshing(true);
        else setLoading(true);
        try {
            const [m, a] = await Promise.all([
                fetchAuthAPI<MonitorState>('/api/admin/mirofish/scanner/monitor/status', token),
                fetchAuthAPI<AlertState>('/api/admin/mirofish/scanner/alerts/state', token),
            ]);
            setMonitor(m);
            setAlerts(a);
            setError('');
        } catch {
            setError('스캐너 데이터를 불러오지 못했습니다.');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [token]);

    useEffect(() => {
        load();
        const id = window.setInterval(() => load({ silent: true }), 60000);
        return () => window.clearInterval(id);
    }, [load]);

    const events = useMemo(() => {
        const list = alerts?.recent_sent_events ?? [];
        return [...list]
            .sort((x, y) => String(y.sent_at ?? '').localeCompare(String(x.sent_at ?? '')))
            .slice(0, 12);
    }, [alerts]);

    const candidateCount = monitor?.last_candidate_count ?? null;
    const newCount = monitor?.last_new_event_count ?? 0;
    const hasNew = (newCount ?? 0) > 0;

    return (
        <section className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <h2 className="text-white font-bold text-base flex items-center gap-2">
                    <i className="fas fa-satellite-dish text-cyan-400" />
                    알파 스캐너 신규 이벤트
                    {hasNew && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-black text-emerald-300 animate-pulse">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                            신규 {newCount}건
                        </span>
                    )}
                </h2>
                <div className="flex items-center gap-2">
                    <span className="text-[11px] text-gray-500">점검 {fmtKST(monitor?.last_checked_at)}</span>
                    <button
                        type="button"
                        onClick={() => load({ silent: true })}
                        className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-medium text-gray-300 hover:bg-white/10 transition-all"
                        title="새로고침"
                    >
                        <i className={`fas fa-rotate-right text-[10px] ${refreshing ? 'fa-spin' : ''}`} />
                    </button>
                </div>
            </div>

            {/* Summary chips */}
            <div className="mb-4 flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-bold text-gray-200">
                    최종 후보 <span className="text-white tabular-nums">{candidateCount ?? '—'}</span>개
                </span>
                <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${hasNew ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300' : 'border-white/10 bg-white/[0.04] text-gray-300'}`}>
                    신규 <span className="tabular-nums">{newCount ?? 0}</span>건
                </span>
                {monitor?.last_status && (
                    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-bold ${statusTone(monitor.last_status)}`}>
                        {STATUS_LABELS[monitor.last_status] || monitor.last_status}
                    </span>
                )}
            </div>

            {loading ? (
                <div className="flex items-center justify-center py-8 text-gray-400">
                    <i className="fas fa-spinner fa-spin text-cyan-400 mr-2" />
                    <span className="text-sm">불러오는 중...</span>
                </div>
            ) : error ? (
                <div className="rounded-xl border border-rose-400/20 bg-rose-500/5 p-4 text-center text-sm text-rose-300">
                    {error}
                </div>
            ) : events.length === 0 ? (
                <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] p-6 text-center text-sm text-gray-400">
                    아직 전송된 신규 이벤트 종목이 없습니다. 조건 충족 후보가 나오면 이 목록에 실시간으로 표시됩니다.
                </div>
            ) : (
                <>
                    <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-gray-500">
                        최근 신규 이벤트 종목
                    </div>
                    <div className="space-y-2.5">
                        {events.map((ev, idx) => {
                            const pct = fmtPct(ev.price?.change_rate);
                            const up = (ev.price?.change_rate ?? 0) >= 0;
                            return (
                                <div
                                    key={ev.event_key ?? `${ev.symbol ?? 'unknown'}-${idx}`}
                                    className="rounded-xl border border-white/10 bg-white/[0.03] p-3"
                                >
                                    <div className="flex items-start justify-between gap-3 flex-wrap">
                                        <div className="min-w-0">
                                            <p className="text-sm font-bold text-white truncate">
                                                {ev.rank != null && <span className="mr-1.5 text-gray-500">#{ev.rank}</span>}
                                                {ev.display_name ?? ev.symbol ?? '—'}
                                                {ev.symbol && (
                                                    <span className="ml-1.5 font-mono text-xs text-gray-500">{ev.symbol}</span>
                                                )}
                                                {ev.market && (
                                                    <span className="ml-1.5 text-[10px] font-bold uppercase tracking-widest text-gray-600">{ev.market}</span>
                                                )}
                                            </p>
                                            <p className="mt-1 flex items-center gap-2 text-xs">
                                                <span className="font-bold text-gray-200 tabular-nums">{fmtPrice(ev.price?.current_price)}</span>
                                                {pct && (
                                                    <span className={`font-bold tabular-nums ${up ? 'text-rose-400' : 'text-sky-400'}`}>{pct}</span>
                                                )}
                                                <span className="text-gray-600">·</span>
                                                <span className="text-gray-500">{fmtKST(ev.sent_at)}</span>
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-1.5 flex-wrap justify-end">
                                            {ev.action && (
                                                <span className="inline-flex items-center rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-bold text-cyan-300">
                                                    {actionLabel(ev.action)}
                                                </span>
                                            )}
                                            {ev.alpha_score != null && (
                                                <span className="inline-flex items-center rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                                                    알파 {ev.alpha_score}
                                                </span>
                                            )}
                                            {ev.risk_score != null && (
                                                <span className="inline-flex items-center rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                                                    리스크 {ev.risk_score}
                                                </span>
                                            )}
                                            {ev.ranking_score != null && (
                                                <span className="inline-flex items-center rounded-full border border-white/15 bg-white/[0.06] px-2 py-0.5 text-[10px] font-bold text-gray-300">
                                                    랭킹 {ev.ranking_score}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    {(ev.strategy_tags?.length ?? 0) > 0 && (
                                        <div className="mt-2 flex flex-wrap gap-1">
                                            {ev.strategy_tags!.slice(0, 5).map((tag) => (
                                                <span key={tag} className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-gray-400">
                                                    {tag}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                    <p className="mt-3 text-[11px] text-gray-600">
                        텔레그램으로 전송되는 알파 스캐너 신규 매수 후보와 동일한 피드입니다. 30초 주기 실시간 점검.
                    </p>
                </>
            )}
        </section>
    );
}
