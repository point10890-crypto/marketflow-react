/**
 * AutoRunnerCard — MCP Stage 2 자동 실행기 콘솔.
 *
 * 표시:
 *  - 현재 phase (IDLE/CHECKING/TRIGGERED/ANALYZING/NOTIFYING/COOLDOWN/CIRCUIT_OPEN/PAUSED)
 *  - 오늘 카운터 (checks/triggers/successes/failures, est cost)
 *  - 다음 체크 시각 + 쿨다운/서킷 만료
 *  - 최근 실패 사유 (skip_reasons)
 *
 * 액션:
 *  - ⏸ Pause / ▶ Resume
 *  - ♻ Reset Circuit (서킷 브레이커 + 실패 카운터 리셋)
 *  - 🚀 Force Trigger (쿨다운/new-events 게이트 우회, 시장/freshness는 유지)
 *
 * 폴링: 15초 (자동 실행기 상태는 빠르게 변하므로)
 */
import { useEffect, useState } from 'react';
import { MiroFishAutoRunnerStatus, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 15_000;

type ActionState = 'idle' | 'running' | 'ok' | 'failed';

function phaseTone(phase: string): { tone: string; emoji: string } {
    switch (phase) {
        case 'IDLE':
            return { tone: 'border-slate-300/20 bg-slate-300/10 text-slate-200', emoji: '⚪' };
        case 'CHECKING':
            return { tone: 'border-cyan-300/30 bg-cyan-300/10 text-cyan-200', emoji: '🔍' };
        case 'TRIGGERED':
        case 'ANALYZING':
            return { tone: 'border-anthropic-orange/40 bg-anthropic-orange/15 text-anthropic-orange', emoji: '⚙️' };
        case 'NOTIFYING':
            return { tone: 'border-blue-300/30 bg-blue-300/10 text-blue-200', emoji: '📤' };
        case 'COOLDOWN':
            return { tone: 'border-amber-300/30 bg-amber-300/10 text-amber-200', emoji: '⏳' };
        case 'CIRCUIT_OPEN':
            return { tone: 'border-rose-300/40 bg-rose-300/15 text-rose-200', emoji: '⛔' };
        case 'PAUSED':
            return { tone: 'border-slate-300/30 bg-slate-300/10 text-slate-400', emoji: '⏸️' };
        default:
            return { tone: 'border-white/10 bg-white/5 text-slate-300', emoji: '•' };
    }
}

function formatTime(iso?: string | null): string {
    if (!iso) return '--';
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '--';
        const now = new Date();
        const diffSec = (d.getTime() - now.getTime()) / 1000;
        // 미래 (남은 시간)
        if (diffSec > 0 && diffSec < 3600) {
            const mins = Math.floor(diffSec / 60);
            const secs = Math.floor(diffSec % 60);
            return `${mins}m ${secs}s 후`;
        }
        // 과거 (경과 시간)
        if (diffSec < 0 && diffSec > -3600) {
            const ago = Math.floor(-diffSec / 60);
            return `${ago}분 전`;
        }
        return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Seoul' });
    } catch {
        return '--';
    }
}

export default function AutoRunnerCard() {
    const [status, setStatus] = useState<MiroFishAutoRunnerStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [actionStates, setActionStates] = useState<Record<string, ActionState>>({});
    const [actionMessage, setActionMessage] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const data = await mirofishApi.getAutoRunnerStatus();
                if (cancelled) return;
                setStatus(data);
                setError(null);
            } catch (err) {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : 'load failed');
            }
        }
        load();
        const id = setInterval(load, POLL_INTERVAL_MS);
        return () => {
            cancelled = true;
            clearInterval(id);
        };
    }, []);

    async function runAction(key: string, fn: () => Promise<MiroFishAutoRunnerStatus | any>, label: string) {
        if (actionStates[key] === 'running') return;
        setActionStates((prev) => ({ ...prev, [key]: 'running' }));
        setActionMessage(null);
        try {
            const result = await fn();
            if (result && typeof result === 'object' && 'phase' in result) {
                setStatus(result as MiroFishAutoRunnerStatus);
            }
            setActionStates((prev) => ({ ...prev, [key]: 'ok' }));
            setActionMessage(`${label} 완료`);
            setTimeout(() => {
                setActionStates((prev) => ({ ...prev, [key]: 'idle' }));
                setActionMessage(null);
            }, 3000);
        } catch (err) {
            setActionStates((prev) => ({ ...prev, [key]: 'failed' }));
            const msg = err instanceof Error ? err.message : '실패';
            setActionMessage(`${label} 실패: ${msg}`);
        }
    }

    const phase = status?.phase || 'IDLE';
    const phaseInfo = phaseTone(phase);
    const today = status?.today;
    const tuning = status?.tuning;

    const costRatio = today && tuning ? Math.min(1, Number(today.est_cost_usd || 0) / Number(tuning.daily_cap_usd || 1)) : 0;

    const topSkipReasons = today?.skip_reasons
        ? Object.entries(today.skip_reasons).sort((a, b) => b[1] - a[1]).slice(0, 2)
        : [];

    return (
        <section className="rounded-xl border border-anthropic-orange/30 bg-gradient-to-b from-anthropic-orange/[0.08] to-slate-950/60 p-3 shadow-[0_18px_70px_rgba(204,120,92,0.10)] sm:p-4">
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-anthropic-orange sm:text-[11px] sm:tracking-[0.22em]">
                        <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                            status?.worker_running ? 'animate-pulse bg-anthropic-orange' : 'bg-slate-500'
                        }`} />
                        <span className="truncate">Auto Runner</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">🤖 자동 검출 실행기</h3>
                </div>
                <span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-black whitespace-nowrap ${phaseInfo.tone}`}>
                    {phaseInfo.emoji} {phase}
                </span>
            </header>

            {error && (
                <div className="mt-3 rounded-lg border border-rose-300/20 bg-rose-300/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {error}
                </div>
            )}

            {/* 오늘 카운터 그리드 */}
            <div className="mt-3 grid grid-cols-4 gap-1.5">
                {[
                    { label: '체크', value: today?.checks ?? 0, color: 'text-slate-200' },
                    { label: '발사', value: today?.triggers ?? 0, color: 'text-anthropic-orange' },
                    { label: '성공', value: today?.successes ?? 0, color: 'text-emerald-300' },
                    { label: '실패', value: today?.failures ?? 0, color: 'text-rose-300' },
                ].map((c) => (
                    <div key={c.label} className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-center">
                        <div className="text-[9px] font-black uppercase tracking-wider text-slate-500">{c.label}</div>
                        <div className={`mt-0.5 text-base font-black tabular-nums ${c.color}`}>{c.value}</div>
                    </div>
                ))}
            </div>

            {/* 비용 게이지 */}
            {today && tuning && (
                <div className="mt-2 rounded-md border border-white/10 bg-black/30 p-2">
                    <div className="flex items-center justify-between text-[10px] font-bold">
                        <span className="text-slate-500">오늘 LLM 비용</span>
                        <span className="font-mono tabular-nums text-slate-200">
                            ${Number(today.est_cost_usd || 0).toFixed(2)} / ${Number(tuning.daily_cap_usd).toFixed(2)}
                        </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-sm bg-white/5">
                        <div
                            className={`h-1.5 rounded-sm transition-all ${
                                costRatio > 0.8 ? 'bg-rose-400' : costRatio > 0.5 ? 'bg-amber-400' : 'bg-emerald-400'
                            }`}
                            style={{ width: `${Math.max(2, Math.min(100, costRatio * 100))}%` }}
                        />
                    </div>
                </div>
            )}

            {/* 다음 체크 / 쿨다운 / 서킷 */}
            <div className="mt-2 space-y-1 text-[10px] font-bold">
                {status?.cooldown_until && new Date(status.cooldown_until) > new Date() && (
                    <div className="flex items-center justify-between rounded-md border border-amber-300/20 bg-amber-300/[0.05] px-2 py-1.5 text-amber-200">
                        <span>⏳ 쿨다운</span>
                        <span className="font-mono tabular-nums">{formatTime(status.cooldown_until)}</span>
                    </div>
                )}
                {phase === 'CIRCUIT_OPEN' && status?.circuit_release_at && (
                    <div className="flex items-center justify-between rounded-md border border-rose-300/30 bg-rose-300/[0.05] px-2 py-1.5 text-rose-200">
                        <span>⛔ 서킷 브레이커 ({status.consecutive_failures}회 연속 실패)</span>
                        <span className="font-mono tabular-nums">{formatTime(status.circuit_release_at)}</span>
                    </div>
                )}
                {status?.last_check_reason && phase !== 'CIRCUIT_OPEN' && (
                    <div className="rounded-md border border-white/5 bg-white/[0.02] px-2 py-1.5 text-slate-400 leading-snug">
                        <span className="text-slate-500">최근 체크:</span>{' '}
                        <span className="break-words">{status.last_check_reason}</span>
                    </div>
                )}
                {topSkipReasons.length > 0 && (
                    <div className="rounded-md border border-white/5 bg-white/[0.02] px-2 py-1.5">
                        <div className="text-[9px] font-black uppercase tracking-wider text-slate-500">오늘 스킵 사유 TOP {topSkipReasons.length}</div>
                        {topSkipReasons.map(([reason, count]) => (
                            <div key={reason} className="mt-0.5 flex items-center justify-between text-slate-400">
                                <span className="truncate pr-2">{reason.split(':')[0]}</span>
                                <span className="font-mono tabular-nums text-slate-300">×{count}</span>
                            </div>
                        ))}
                    </div>
                )}
                {status?.last_success_at && (
                    <div className="flex items-center justify-between rounded-md border border-emerald-300/20 bg-emerald-300/[0.05] px-2 py-1.5 text-emerald-200">
                        <span>✅ 최근 성공 (TOP {status.last_top3_count})</span>
                        <span className="font-mono tabular-nums">{formatTime(status.last_success_at)}</span>
                    </div>
                )}
            </div>

            {/* 액션 버튼 */}
            <div className="mt-3 grid grid-cols-2 gap-1.5">
                {/* Pause / Resume */}
                <button
                    type="button"
                    disabled={actionStates['pause'] === 'running' || !status}
                    onClick={() => runAction(
                        'pause',
                        () => mirofishApi.pauseAutoRunner(!status?.paused),
                        status?.paused ? '재개' : '일시정지',
                    )}
                    className={`min-h-[40px] rounded-lg border px-2 py-1.5 text-[11px] font-black transition-colors disabled:cursor-wait ${
                        status?.paused
                            ? 'border-emerald-300/30 bg-emerald-300/10 text-emerald-200 hover:bg-emerald-300/15'
                            : 'border-white/10 bg-black/30 text-slate-200 hover:border-amber-300/30 hover:bg-amber-300/[0.08]'
                    }`}
                >
                    {status?.paused ? '▶ 재개' : '⏸ 일시정지'}
                </button>

                {/* Force Trigger */}
                <button
                    type="button"
                    disabled={actionStates['trigger'] === 'running' || phase === 'ANALYZING' || phase === 'CIRCUIT_OPEN'}
                    onClick={() => runAction(
                        'trigger',
                        () => mirofishApi.triggerAutoRunner(),
                        '강제 트리거',
                    )}
                    className="min-h-[40px] rounded-lg border border-anthropic-orange/30 bg-anthropic-orange/10 px-2 py-1.5 text-[11px] font-black text-anthropic-orange transition-colors hover:bg-anthropic-orange/15 active:bg-anthropic-orange/20 disabled:cursor-wait disabled:opacity-50"
                >
                    {actionStates['trigger'] === 'running' ? '실행중...' : '🚀 강제 발사'}
                </button>

                {/* Reset Circuit */}
                <button
                    type="button"
                    disabled={actionStates['reset'] === 'running'}
                    onClick={() => runAction(
                        'reset',
                        () => mirofishApi.resetAutoRunner('circuit'),
                        '서킷 리셋',
                    )}
                    className="min-h-[40px] rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11px] font-black text-slate-200 transition-colors hover:border-cyan-300/30 hover:bg-cyan-300/[0.08]"
                >
                    ♻ 서킷 리셋
                </button>

                {/* Reset Today */}
                <button
                    type="button"
                    disabled={actionStates['resetToday'] === 'running'}
                    onClick={() => runAction(
                        'resetToday',
                        () => mirofishApi.resetAutoRunner('today'),
                        '카운터 리셋',
                    )}
                    className="min-h-[40px] rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-[11px] font-black text-slate-200 transition-colors hover:border-violet-300/30 hover:bg-violet-300/[0.08]"
                >
                    🔄 카운터 리셋
                </button>
            </div>

            {actionMessage && (
                <div className="mt-2 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[10px] font-bold text-slate-300">
                    {actionMessage}
                </div>
            )}

            {/* 설정 요약 (작게) */}
            {tuning && (
                <div className="mt-2 flex flex-wrap gap-1 text-[9px] font-bold text-slate-500">
                    <span>쿨다운 {tuning.cooldown_minutes}분</span>
                    <span>·</span>
                    <span>신규 ≥{tuning.min_new_events}</span>
                    <span>·</span>
                    <span>α≥{tuning.min_alpha}/risk≤{tuning.max_risk}</span>
                    <span>·</span>
                    <span>일일 ${tuning.daily_cap_usd}</span>
                    {tuning.dry_run && <span className="text-amber-400">· DRY-RUN</span>}
                </div>
            )}
        </section>
    );
}
