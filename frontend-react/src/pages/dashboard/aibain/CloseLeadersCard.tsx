/**
 * 마감 주도주 — AI Brain 대시보드 카드 (마스터 플랜 P3).
 *
 * 마감 기준(세션 마지막 정상 스냅샷)의 주도주 전체를 등급순으로 보여주고,
 * 종목별 당일 전이 타임라인(NEW/UP/HIGH/VOL/DROP)과 마감 브리핑 발송 여부를 병기한다.
 * 마감 데이터라 폴링하지 않는다(최초 1회 로드, 10분 재검). ClawLiveCard 와 동일 문법.
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import {
    CLAW_CLOSE_LEADERS_ENDPOINT, ClawCloseLeaders, GRADE_CHIP,
    chgClass, eventChip, fmtDay, fmtEok, fmtPct, hhmm, isClawCloseLeaders,
} from '@/lib/claw';

const MAX_ROWS = 12;

export default function CloseLeadersCard() {
    const { token } = useAuth();
    const [data, setData] = useState<ClawCloseLeaders | null>(null);
    const [failed, setFailed] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await fetchAuthAPI<unknown>(CLAW_CLOSE_LEADERS_ENDPOINT, token ?? undefined);
            if (isClawCloseLeaders(res)) { setData(res); setFailed(false); } else { setFailed(true); }
        } catch {
            setFailed(true);
        }
    }, [token]);

    useEffect(() => { void load(); }, [load]);
    useEffect(() => {
        const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 600000);
        return () => clearInterval(timer);
    }, [load]);

    if (!data || data.error === 'no_snapshot') {
        return (
            <section className="rounded-2xl border border-teal-400/15 bg-[#13151f] p-5">
                <Header day={null} />
                <p className="text-sm text-gray-500">
                    {failed ? '마감 주도주 데이터가 아직 없습니다 (백엔드 준비 중)'
                        : data ? '아직 마감 스냅샷이 없습니다' : '불러오는 중...'}
                </p>
            </section>
        );
    }

    const rows = data.rows.filter(r => r.grade === 'S' || r.grade === 'A');
    const bCount = data.rows.length - rows.length;
    const shown = rows.slice(0, MAX_ROWS);

    return (
        <section className="rounded-2xl border border-teal-400/15 bg-[#13151f] p-5">
            <Header day={data.day} />

            <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-gray-400">
                <span>확정 <b className="font-bold text-gray-200">{hhmm(data.snapshot_ts)}</b> 스냅샷</span>
                <span>S/A <b className="font-bold text-gray-200">{rows.length}</b>{bCount > 0 && <span className="text-gray-500"> · B {bCount}</span>}</span>
                <span>전이 <b className="font-bold text-gray-200">{data.events_count}</b>건</span>
                {data.close_brief && (
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${data.close_brief.delivered ? 'bg-teal-500/15 text-teal-300' : 'bg-amber-500/15 text-amber-300'}`}>
                        마감 브리핑 {data.close_brief.delivered ? '발송됨' : '미발송'} {hhmm(data.close_brief.ts)}
                    </span>
                )}
            </div>

            {shown.length === 0 ? (
                <p className="py-3 text-sm text-gray-500">이 세션에는 S/A 주도주가 없었습니다</p>
            ) : (
                <ul className="space-y-1">
                    {shown.map(r => (
                        <li key={r.code} className="rounded-lg px-2 py-1.5 hover:bg-white/[0.03]">
                            <div className="flex items-center gap-2.5">
                                <span className={`grid h-6 w-7 shrink-0 place-items-center rounded-md border text-[11px] font-black ${GRADE_CHIP[r.grade] ?? GRADE_CHIP.B}`}>{r.grade}</span>
                                <span className="min-w-0 flex-1 truncate">
                                    <b className="font-bold text-white">{r.name}</b>
                                    <span className="ml-1.5 font-mono text-[11px] text-gray-500">{r.code}</span>
                                    {r.score != null && <span className="ml-2 font-mono text-[11px] text-gray-500">{r.score}점</span>}
                                </span>
                                <span className={`w-16 text-right font-mono text-[13px] font-bold tabular-nums ${chgClass(r.chg)}`}>{fmtPct(r.chg)}</span>
                                <span className="hidden w-16 text-right font-mono text-[11px] tabular-nums text-gray-500 sm:inline">{fmtEok(r.trval_eok)}</span>
                            </div>
                            {r.events.length > 0 && (
                                <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-[38px]">
                                    {r.events.map((e, i) => {
                                        const chip = eventChip(e.type);
                                        return (
                                            <span key={`${e.ts}-${e.type}-${i}`} className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${chip.cls}`}>
                                                {chip.label} {hhmm(e.ts)}
                                                {(e.grade_from || e.grade_to) && <span className="ml-1 font-mono font-medium opacity-70">{e.grade_from || '–'}→{e.grade_to || '–'}</span>}
                                            </span>
                                        );
                                    })}
                                </div>
                            )}
                        </li>
                    ))}
                </ul>
            )}

            {rows.length > MAX_ROWS && (
                <p className="mt-2 text-right text-[11px] text-gray-500">외 {rows.length - MAX_ROWS}종목</p>
            )}
        </section>
    );
}

function Header({ day }: { day: string | null }) {
    return (
        <h2 className="mb-3 flex items-center gap-2.5 text-base font-bold text-white">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-teal-400/20 bg-teal-500/10">
                <i className="fas fa-flag-checkered text-[13px] text-teal-300" />
            </span>
            <span className="claw-title-gradient">마감 주도주</span>
            <span className="rounded-full border border-teal-400/25 bg-teal-500/10 px-2 py-0.5 text-[10px] font-bold text-teal-300">CLOSE</span>
            <span className="text-[11px] font-medium text-gray-500">마감 기준 {fmtDay(day)} 세션</span>
        </h2>
    );
}
