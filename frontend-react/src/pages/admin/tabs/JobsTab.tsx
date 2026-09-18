import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchAuthAPI, postAuthAPI } from '@/lib/api';

/**
 * 잡 상태 보드 — scheduler.py 데몬(~30잡)의 heartbeat/마지막 실행/수동 재실행 결과.
 * 데이터는 /api/scheduler/status 의 `daemon` (Flask 가 data/scheduler_*.json 을 읽어 병합).
 * "재실행" 은 POST /api/scheduler/trigger/<job_key> → 파일 큐 → 데몬이 30초 내 소비.
 */

export interface DaemonTrigger {
    id: string | null;
    ok: boolean | null;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
    requested_by?: string | null;
}

export interface DaemonJob {
    key: string;
    label: string;
    schedule: string | null;
    market: 'KR' | 'US' | 'Crypto' | 'System' | string;
    record_key?: string | null;
    last_run: string | null;
    age_minutes: number | null;
    queued: boolean;
    running: boolean;
    last_trigger: DaemonTrigger | null;
}

export interface TriggerResult {
    id: string;
    job_key: string;
    started_at: string | null;
    finished_at: string | null;
    ok: boolean | null;
    error: string | null;
    requested_by?: string | null;
}

export interface SchedulerStatus {
    running?: boolean;
    kst_now?: string;
    daemon?: {
        alive: boolean | null;
        stale_seconds: number | null;
        jobs?: DaemonJob[];
        trigger_results?: TriggerResult[];
        pending_triggers?: number;
        jobs_generated_at?: string | null;
    };
}

const MARKET_ORDER = ['KR', 'US', 'Crypto', 'System'];
const MARKET_LABEL: Record<string, string> = { KR: '🇰🇷 KR', US: '🇺🇸 US', Crypto: '🪙 Crypto', System: '⚙️ System' };
const POLL_MS = 30_000;
const FAST_POLL_MS = 5_000;

export function formatRelative(ageMinutes: number | null): string {
    if (ageMinutes === null || ageMinutes === undefined || Number.isNaN(ageMinutes)) return '기록 없음';
    if (ageMinutes < 1) return '방금';
    if (ageMinutes < 60) return `${Math.round(ageMinutes)}분 전`;
    if (ageMinutes < 60 * 48) return `${Math.round(ageMinutes / 60)}시간 전`;
    return `${Math.round(ageMinutes / 60 / 24)}일 전`;
}

/** 경과 색: <24h 녹색, <48h 황색, 그 외/없음 적색 */
export function ageTone(ageMinutes: number | null): 'green' | 'amber' | 'red' {
    if (ageMinutes === null || ageMinutes === undefined) return 'red';
    if (ageMinutes < 24 * 60) return 'green';
    if (ageMinutes < 48 * 60) return 'amber';
    return 'red';
}

const TONE_CLASS = {
    green: 'text-green-400',
    amber: 'text-amber-400',
    red: 'text-red-400',
} as const;

const DOT_CLASS = {
    green: 'bg-green-400',
    amber: 'bg-amber-400',
    red: 'bg-red-400',
} as const;

function shortTime(iso: string | null | undefined): string {
    if (!iso) return '-';
    const m = /T(\d{2}:\d{2})/.exec(iso);
    return m ? m[1] : iso;
}

function TriggerBadge({ job }: { job: DaemonJob }) {
    if (job.queued) {
        return <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300">대기중</span>;
    }
    if (job.running) {
        return (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-300">
                <i className="fas fa-spinner fa-spin mr-1" />실행중
            </span>
        );
    }
    const t = job.last_trigger;
    if (!t || t.ok === null) return <span className="text-[10px] text-gray-600">-</span>;
    if (t.ok) {
        return (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-300" title={`수동 ${shortTime(t.finished_at)} 완료`}>
                성공 {shortTime(t.finished_at)}
            </span>
        );
    }
    return (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-300" title={t.error || ''}>
            실패 {shortTime(t.finished_at)}
        </span>
    );
}

export default function JobsTab({ token }: { token: string | null }) {
    const [status, setStatus] = useState<SchedulerStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [triggering, setTriggering] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    // 재실행 직후 status 파일이 아직 갱신되기 전에도 "대기중" 을 즉시 보여준다.
    const [localQueued, setLocalQueued] = useState<Record<string, string>>({});
    const mounted = useRef(true);

    const load = useCallback(async () => {
        try {
            const data = await fetchAuthAPI<SchedulerStatus>('/api/scheduler/status', token || undefined);
            if (!mounted.current) return;
            setStatus(data);
            setError(null);
            // 서버가 큐/실행/결과를 반영하면 로컬 대기 표시는 지운다
            setLocalQueued(prev => {
                const next = { ...prev };
                for (const j of data?.daemon?.jobs ?? []) {
                    if (next[j.key] && (j.queued || j.running || j.last_trigger?.id === next[j.key])) delete next[j.key];
                }
                return next;
            });
        } catch (e) {
            if (!mounted.current) return;
            setError(e instanceof Error ? e.message : '상태 조회 실패');
        } finally {
            if (mounted.current) setLoading(false);
        }
    }, [token]);

    const jobs = useMemo(() => status?.daemon?.jobs ?? [], [status]);
    const busy = useMemo(
        () => jobs.some(j => j.queued || j.running) || Object.keys(localQueued).length > 0,
        [jobs, localQueued],
    );

    useEffect(() => {
        mounted.current = true;
        load();
        return () => { mounted.current = false; };
    }, [load]);

    useEffect(() => {
        const timer = setInterval(() => {
            if (document.visibilityState === 'visible') load();
        }, busy ? FAST_POLL_MS : POLL_MS);
        return () => clearInterval(timer);
    }, [load, busy]);

    const handleTrigger = async (job: DaemonJob) => {
        setTriggering(job.key);
        setMessage(null);
        try {
            const res = await postAuthAPI<{ status: string; id?: string; job_key?: string; error?: string }>(
                `/api/scheduler/trigger/${encodeURIComponent(job.key)}`, undefined, token || undefined);
            if (res?.status === 'queued') {
                setLocalQueued(prev => ({ ...prev, [job.key]: res.id || '' }));
                setMessage(`${job.label} 재실행 요청 접수 (id ${res.id}) — 데몬이 30초 내 실행합니다.`);
            } else {
                setMessage(`${job.label}: ${res?.error || res?.status || '응답 없음'}`);
            }
        } catch (e) {
            setMessage(`${job.label} 재실행 실패: ${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setTriggering(null);
            load();
        }
    };

    const daemon = status?.daemon;
    const alive = daemon?.alive ?? null;
    const grouped = useMemo(() => {
        const map = new Map<string, DaemonJob[]>();
        for (const j of jobs) {
            const m = MARKET_ORDER.includes(j.market) ? j.market : 'System';
            if (!map.has(m)) map.set(m, []);
            map.get(m)!.push(j);
        }
        return MARKET_ORDER.filter(m => map.has(m)).map(m => [m, map.get(m)!] as const);
    }, [jobs]);
    const results = daemon?.trigger_results ?? [];

    if (loading && !status) {
        return <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500" /></div>;
    }

    return (
        <>
            {/* 데몬 상태 */}
            <div className="apple-glass rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        <i className="fas fa-clock text-cyan-400 mr-2" />스케줄러 데몬
                    </h2>
                    <button onClick={load} className="text-xs text-gray-400 hover:text-white px-3 py-1 rounded bg-white/5 hover:bg-white/10 transition-colors" aria-label="잡 상태 새로고침">
                        <i className="fas fa-sync-alt mr-1" /> 새로고침
                    </button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Daemon</div>
                        <div className={`text-lg font-bold flex items-center gap-2 ${alive ? 'text-green-400' : 'text-red-400'}`}>
                            <span className={`w-2.5 h-2.5 rounded-full ${alive ? 'bg-green-400' : 'bg-red-400'}`} />
                            {alive === null ? '알 수 없음' : alive ? 'ALIVE' : 'DEAD'}
                        </div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Heartbeat 경과</div>
                        <div className="text-lg font-bold text-white">
                            {daemon?.stale_seconds === null || daemon?.stale_seconds === undefined ? '-' : `${Math.round(daemon.stale_seconds)}s`}
                        </div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">등록 잡</div>
                        <div className="text-lg font-bold text-white">{jobs.length}</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">대기 요청</div>
                        <div className="text-lg font-bold text-blue-300">{daemon?.pending_triggers ?? 0}</div>
                    </div>
                </div>
                <div className="mt-3 text-xs text-gray-500">
                    KST {status?.kst_now || '-'}
                    {daemon?.jobs_generated_at && <> · 잡 목록 기록 {daemon.jobs_generated_at}</>}
                    {alive === false && <span className="text-red-300 ml-2">데몬 미응답 — 재실행 요청은 데몬 재기동 후 처리됩니다.</span>}
                </div>
                {error && <div className="mt-2 text-xs text-red-300">{error}</div>}
                {message && <div className="mt-2 text-xs text-cyan-200" role="status">{message}</div>}
            </div>

            {/* 잡 테이블 (마켓별) */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-list-check text-purple-400 mr-2" />잡 상태 보드
                </h2>
                {jobs.length === 0 ? (
                    <div className="text-sm text-gray-500">
                        잡 목록이 없습니다 — 데몬이 기동하면 <code className="text-gray-400">data/scheduler_jobs.json</code> 을 기록합니다.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-gray-500 border-b border-white/10">
                                    <th className="text-left py-2 pr-2 font-medium">잡</th>
                                    <th className="text-left py-2 pr-2 font-medium">스케줄 (KST)</th>
                                    <th className="text-left py-2 pr-2 font-medium">마지막 실행</th>
                                    <th className="text-left py-2 pr-2 font-medium">수동 실행</th>
                                    <th className="text-right py-2 font-medium" />
                                </tr>
                            </thead>
                            <tbody>
                                {grouped.map(([market, rows]) => (
                                    <GroupRows key={market} market={market} rows={rows}
                                        localQueued={localQueued} triggering={triggering} onTrigger={handleTrigger} />
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* 최근 수동 재실행 결과 */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-history text-amber-400 mr-2" />최근 재실행 결과
                </h2>
                {results.length === 0 ? (
                    <div className="text-sm text-gray-500">아직 수동 재실행 기록이 없습니다.</div>
                ) : (
                    <div className="space-y-1">
                        {results.map(r => (
                            <div key={r.id} className="flex items-center justify-between gap-3 p-2 bg-white/[0.02] rounded text-xs">
                                <div className="flex items-center gap-2 min-w-0">
                                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${r.finished_at === null ? 'bg-yellow-400 animate-pulse' : r.ok ? 'bg-green-400' : 'bg-red-400'}`} />
                                    <span className="text-white font-medium">{r.job_key}</span>
                                    <span className="text-gray-500 truncate">{r.requested_by || ''}</span>
                                </div>
                                <div className="text-gray-400 flex-shrink-0">
                                    {r.started_at?.replace('T', ' ') || '-'} → {r.finished_at === null ? '실행중' : (r.finished_at?.replace('T', ' ') || '-')}
                                    {r.error && <span className="text-red-300 ml-2" title={r.error}>{r.error.slice(0, 60)}</span>}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </>
    );
}

function GroupRows({ market, rows, localQueued, triggering, onTrigger }: {
    market: string;
    rows: DaemonJob[];
    localQueued: Record<string, string>;
    triggering: string | null;
    onTrigger: (job: DaemonJob) => void;
}) {
    return (
        <>
            <tr className="bg-white/[0.03]">
                <td colSpan={5} className="py-1.5 px-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wide">
                    {MARKET_LABEL[market] || market} <span className="text-gray-600 font-normal">({rows.length})</span>
                </td>
            </tr>
            {rows.map(job => {
                const tone = ageTone(job.age_minutes);
                const effective: DaemonJob = localQueued[job.key] ? { ...job, queued: true } : job;
                const disabled = triggering === job.key || effective.queued || effective.running;
                return (
                    <tr key={job.key} className="border-b border-white/[0.04] hover:bg-white/[0.03]">
                        <td className="py-1.5 pr-2">
                            <div className="text-white font-medium">{job.label}</div>
                            <div className="text-gray-600 font-mono text-[10px]">{job.key}</div>
                        </td>
                        <td className="py-1.5 pr-2 text-gray-400 whitespace-nowrap">{job.schedule || '-'}</td>
                        <td className={`py-1.5 pr-2 whitespace-nowrap ${TONE_CLASS[tone]}`}>
                            <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${DOT_CLASS[tone]}`} />
                            {formatRelative(job.age_minutes)}
                            {job.last_run && <span className="text-gray-600 ml-1 text-[10px]">{job.last_run.replace('T', ' ')}</span>}
                        </td>
                        <td className="py-1.5 pr-2"><TriggerBadge job={effective} /></td>
                        <td className="py-1.5 text-right">
                            <button
                                onClick={() => onTrigger(job)}
                                disabled={disabled}
                                aria-label={`${job.label} 재실행`}
                                className="text-[11px] px-2.5 py-1 rounded bg-white/5 text-gray-300 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                            >
                                {triggering === job.key ? <><i className="fas fa-spinner fa-spin mr-1" />요청중</> : <><i className="fas fa-redo mr-1" />재실행</>}
                            </button>
                        </td>
                    </tr>
                );
            })}
        </>
    );
}
