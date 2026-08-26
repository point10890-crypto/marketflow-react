import { ClawQuality, ClawScorecards, fmtAge, fmtPct, hhmm } from '@/lib/claw';

interface Props {
    scorecards: ClawScorecards | null;
    quality: ClawQuality | null;
    loading: boolean;
}

function tone(quality: ClawQuality | null, scorecards: ClawScorecards | null): string {
    if (quality?.status === 'unavailable') return 'border-red-500/30 bg-red-500/[0.05]';
    if (quality?.status === 'degraded' || quality?.freshness.stale || scorecards?.stale) return 'border-amber-400/30 bg-amber-400/[0.04]';
    return 'border-white/[0.06] bg-[#13151f]';
}

function stateLabel(quality: ClawQuality | null, scorecards: ClawScorecards | null): { text: string; cls: string } {
    if (!quality) return { text: '준비 중', cls: 'bg-white/[0.06] text-gray-400' };
    if (quality.status === 'unavailable') return { text: '원장 확인 필요', cls: 'bg-red-500/15 text-red-300' };
    if (quality.status === 'degraded' || quality.freshness.stale || scorecards?.stale) return { text: '일부 지연', cls: 'bg-amber-500/15 text-amber-300' };
    if (scorecards?.insufficient) return { text: '표본 축적 중', cls: 'bg-blue-500/15 text-blue-300' };
    return { text: '관측 정상', cls: 'bg-teal-500/15 text-teal-300' };
}

export default function ClawObservationCard({ scorecards, quality, loading }: Props) {
    if (loading && !quality && !scorecards) {
        return <section aria-label="관측 원장 불러오는 중" className="h-[118px] animate-pulse rounded-2xl border border-white/[0.06] bg-[#13151f] lg:col-span-12" />;
    }
    if (!quality && !scorecards) return null;

    const state = stateLabel(quality, scorecards);
    const horizons = scorecards?.horizons ?? [];
    const latest = scorecards?.recent_instances?.[0];
    const complete = quality?.outcomes.complete ?? scorecards?.coverage.complete_n ?? 0;
    const pending = quality?.outcomes.pending ?? scorecards?.coverage.pending_n ?? 0;
    const missing = quality?.outcomes.missing ?? scorecards?.coverage.missing_n ?? 0;

    return (
        <section className={`claw-card-in rounded-2xl border p-4 sm:rounded-3xl sm:p-5 lg:col-span-12 ${tone(quality, scorecards)}`}>
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="flex items-center gap-2 text-[15px] font-bold text-white">
                    <i className="fas fa-clipboard-check text-[13px] text-[#ff8a6b]" />관측·검증 하네스
                </h2>
                <span className={`rounded-full px-2 py-1 text-[10px] font-extrabold ${state.cls}`}>{state.text}</span>
                <span className="ml-auto text-[11px] text-gray-500">
                    원장 {quality?.ledger.instances ?? scorecards?.coverage.instances ?? 0}건
                    {quality?.freshness.age_seconds != null && ` · ${fmtAge(quality.freshness.age_seconds)} 전`}
                </span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-[1fr_1fr_1fr_1.3fr]">
                <Metric label="완료" value={complete} detail="성숙 horizon" toneClass="text-teal-300" />
                <Metric label="대기" value={pending} detail="거래세션 대기" toneClass="text-blue-300" />
                <Metric label="결측" value={missing} detail="0% 대체 안 함" toneClass={missing ? 'text-amber-300' : 'text-gray-200'} />
                <div className="min-w-0 rounded-xl border border-white/[0.05] bg-black/15 px-3 py-2.5">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">최근 Signal</div>
                    {latest ? (
                        <div className="mt-1 min-w-0 text-[12px]">
                            <div className="flex min-w-0 items-center gap-2">
                                <b className="min-w-0 flex-1 truncate text-white">{latest.name || latest.code}</b>
                                <span className="shrink-0 font-mono text-[11px] text-gray-500">{hhmm(latest.opened_at)}</span>
                            </div>
                            <span className="mt-1 inline-flex max-w-full truncate rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-gray-400">{latest.trigger_type}</span>
                        </div>
                    ) : <p className="mt-1 text-[12px] text-gray-500">새 관측을 기다리는 중</p>}
                </div>
            </div>

            {horizons.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-white/[0.05] pt-3">
                    {horizons.map(h => (
                        <span key={h.horizon_sessions} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.025] px-2.5 text-[11px] text-gray-400">
                            <b className="text-gray-200">D{h.horizon_sessions}</b>
                            {h.status === 'observed' && h.avg_return_pct != null
                                ? <span className={h.avg_return_pct >= 0 ? 'text-red-300' : 'text-blue-300'}>{fmtPct(h.avg_return_pct)} · 양수 {h.positive_rate_pct?.toFixed(0) ?? '-'}%</span>
                                : <span>{h.complete_n}/{h.eligible_n} 완료</span>}
                        </span>
                    ))}
                    {scorecards?.insufficient && <span className="self-center text-[11px] text-gray-500">정책 미적용 · {scorecards.insufficient_reason || '표본 부족'}</span>}
                </div>
            )}
        </section>
    );
}

function Metric({ label, value, detail, toneClass }: { label: string; value: number; detail: string; toneClass: string }) {
    return (
        <div className="rounded-xl border border-white/[0.05] bg-black/15 px-3 py-2.5">
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{label}</div>
            <div className={`mt-1 font-mono text-xl font-black tabular-nums ${toneClass}`}>{value.toLocaleString('ko-KR')}</div>
            <div className="mt-0.5 text-[10px] text-gray-500">{detail}</div>
        </div>
    );
}
