/**
 * Claw LIVE — AI Brain 대시보드용 압축 카드.
 *
 * 기존 가상 매매/검출 카드와 같은 문법(rounded-2xl · #13151f · 헤더 아이콘)으로
 * "지금 주도주 S/A 상위 5 + 최근 이벤트 4 + 루프/레짐 상태"만 보여주고,
 * 전체 화면은 /dashboard/kr/claw 로 보낸다. 자체 폴링(장중 5s / 장외 60s).
 * 응답 형태가 계약과 다르면(구 백엔드·모킹) 조용히 '준비 중' 한 줄만 렌더한다.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import ClawMascot from '@/components/claw/ClawMascot';
import {
    CLAW_OVERVIEW_ENDPOINT, ClawOverview, GRADE_CHIP, LOOP_LABEL, REGIME_LABEL,
    chgClass, eventChip, fmtEok, fmtHeld, fmtPct, hhmm, isClawOverview,
} from '@/lib/claw';

export default function ClawLiveCard() {
    const { token } = useAuth();
    const [data, setData] = useState<ClawOverview | null>(null);
    const [failed, setFailed] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await fetchAuthAPI<unknown>(CLAW_OVERVIEW_ENDPOINT, token ?? undefined);
            if (isClawOverview(res)) { setData(res); setFailed(false); } else { setFailed(true); }
        } catch {
            setFailed(true);
        }
    }, [token]);

    // 최초 1회 로드, 이후 폴링(장중 5s / 장외 60s). 보이는 탭에서만 재호출.
    useEffect(() => { void load(); }, [load]);
    const marketOpen = data?.loop.market_open ?? false;
    useEffect(() => {
        const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, marketOpen ? 5000 : 60000);
        return () => clearInterval(timer);
    }, [load, marketOpen]);

    if (!data) {
        return (
            <section className="rounded-2xl border border-teal-400/15 bg-[#13151f] p-5">
                <Header state={null} />
                <p className="text-sm text-gray-500">{failed ? 'Claw LIVE 데이터가 아직 없습니다 (백엔드 준비 중)' : '불러오는 중...'}</p>
            </section>
        );
    }

    const loop = LOOP_LABEL[data.loop.state] ?? LOOP_LABEL.idle;
    const reg = REGIME_LABEL[data.regime.regime] ?? REGIME_LABEL.UNKNOWN;
    const leaders = data.leaders.rows.filter(r => r.grade === 'S' || r.grade === 'A').slice(0, 5);
    const events = data.events.items.slice(-4).reverse();
    const halted = data.loop.state === 'halt';
    const evCount = data.events.items.length;

    return (
        <section className={`rounded-2xl border bg-[#13151f] p-5 ${halted ? 'border-amber-400/40' : 'border-teal-400/15'}`}>
            <Header state={data.loop.state} />

            {/* 상태 한 줄: 루프 · 레짐 · 이벤트 · 발송 */}
            <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-gray-400">
                <span className="inline-flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${loop.dot}`} />
                    <b className={`font-bold ${halted ? 'text-amber-300' : 'text-gray-200'}`}>{loop.label}</b>
                    <span className="text-gray-500">{data.loop.state === 'running' ? `틱 ${hhmm(data.loop.last_tick_ts)}` : loop.sub}</span>
                </span>
                <span>레짐 <b className={`font-bold ${reg.cls}`}>{reg.label}</b>{data.regime.gate_score != null && <span className="text-gray-500"> · gate {data.regime.gate_score}</span>}</span>
                <span>이벤트 <b className="font-bold text-gray-200">{evCount}</b>건</span>
                <span>발송 <b className="font-bold text-gray-200">{data.system.briefs_delivered_today}/{data.system.briefs_today}</b>{!data.system.delivery.enabled && <span className="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">dry-run</span>}</span>
            </div>

            {halted && (
                <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-500/[0.06] px-3.5 py-2.5 text-[12px] text-amber-200">
                    <i className="fas fa-pause mr-1.5 text-[10px]" />검출 보류 중 — 방향성 판단 없음
                    {data.regime.reasons.length > 0 && <span className="ml-2 text-amber-300/70">{data.regime.reasons[0]}</span>}
                </div>
            )}

            <div className="grid gap-4 md:grid-cols-5">
                {/* 주도주 S/A */}
                <div className={`md:col-span-3 ${halted ? 'opacity-50' : ''}`}>
                    <div className="mb-2 flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        <span>주도주 S/A</span>
                        <span className="font-medium normal-case tracking-normal">{data.loop.market_open ? '실시간' : '전 세션 기준'} · {hhmm(data.leaders.snapshot_ts)}</span>
                    </div>
                    {leaders.length === 0 ? (
                        <p className="py-3 text-sm text-gray-500">{data.leaders.rows.length ? '현재 S/A 주도주 없음' : '아직 스냅샷 없음'}</p>
                    ) : (
                        <ul className="space-y-1">
                            {leaders.map(r => {
                                const held = data.loop.market_open ? fmtHeld(r.since_ts, data.leaders.snapshot_ts) : null;
                                return (
                                    <li key={r.code} className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-white/[0.03]">
                                        <span className={`grid h-6 w-7 shrink-0 place-items-center rounded-md border text-[11px] font-black ${GRADE_CHIP[r.grade] ?? GRADE_CHIP.B}`}>{r.grade}</span>
                                        <span className="min-w-0 flex-1 truncate">
                                            <b className="font-bold text-white">{r.name}</b>
                                            <span className="ml-1.5 font-mono text-[11px] text-gray-500">{r.code}</span>
                                            {r.today_event && <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-bold ${eventChip(r.today_event.type).cls}`}>{eventChip(r.today_event.type).label} {hhmm(r.today_event.ts)}</span>}
                                        </span>
                                        {held && <span className="hidden text-[11px] text-gray-500 sm:inline">유지 {held}</span>}
                                        <span className={`w-16 text-right font-mono text-[13px] font-bold tabular-nums ${chgClass(r.chg)}`}>{fmtPct(r.chg)}</span>
                                        <span className="hidden w-16 text-right font-mono text-[11px] tabular-nums text-gray-500 sm:inline">{fmtEok(r.trval_eok)}</span>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>

                {/* 최근 이벤트 */}
                <div className="md:col-span-2">
                    <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">최근 이벤트</div>
                    {events.length === 0 ? (
                        <p className="py-3 text-sm text-gray-500">오늘 전이 없음</p>
                    ) : (
                        <ul className="space-y-1">
                            {events.map((e, i) => {
                                const chip = eventChip(e.type);
                                return (
                                    <li key={`${e.ts}-${e.type}-${e.code}-${i}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[12.5px]">
                                        <span className="font-mono text-[11px] tabular-nums text-gray-500">{hhmm(e.ts)}</span>
                                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${chip.cls}`}>{chip.label}</span>
                                        <span className="min-w-0 flex-1 truncate text-gray-200">{e.name}</span>
                                        {(e.grade_from || e.grade_to) && <span className="font-mono text-[11px] text-gray-500">{e.grade_from || '–'}→{e.grade_to || '–'}</span>}
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3 text-[11px] text-gray-500">
                <span>틱 {data.system.snapshots_today.toLocaleString('ko-KR')} · KIS 직접호출 {data.system.kis_calls_today} · DROP {data.system.drop_confirm_ticks}틱 확정</span>
                <Link to="/dashboard/kr/claw" className="font-bold text-teal-300 transition-colors hover:text-teal-200">
                    전체 보기 <i className="fas fa-arrow-right ml-1 text-[10px]" />
                </Link>
            </div>
        </section>
    );
}

function Header({ state }: { state: ClawOverview['loop']['state'] | null }) {
    const label = state === 'running' ? 'LIVE' : state === 'halt' ? 'HOLD' : state === 'dead' ? 'OFFLINE' : 'REST';
    return (
        <h2 className="mb-3 flex items-center gap-2.5 text-base font-bold text-white">
            <ClawMascot state={state} size={34} className="-my-1 shrink-0" />
            <span className="claw-title-gradient">Claw LIVE</span>
            <span className="rounded-full border border-teal-400/25 bg-teal-500/10 px-2 py-0.5 text-[10px] font-bold text-teal-300">{label}</span>
            <span className="text-[11px] font-medium text-gray-500">장중 주도주 전이 감시</span>
        </h2>
    );
}
