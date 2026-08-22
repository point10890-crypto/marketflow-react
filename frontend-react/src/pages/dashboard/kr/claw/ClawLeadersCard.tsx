import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ClawOverview, GRADE_BAR, GRADE_CHIP, chgClass, eventChip, fmtEok, fmtHeld, fmtPct, hhmm } from '@/lib/claw';

interface Props { data: ClawOverview; }

/** 주도주 카드 (7col) — S/A 펼침, B 접힘. 행 클릭 → 주도주LIVE 상세. */
export default function ClawLeadersCard({ data }: Props) {
    const [showB, setShowB] = useState(false);
    const halted = data.loop.state === 'halt';
    const rows = data.leaders.rows;
    const lead = rows.filter(r => r.grade === 'S' || r.grade === 'A');
    const bs = rows.filter(r => r.grade === 'B');
    const bg = data.leaders.by_grade;

    const Row = ({ r }: { r: ClawOverview['leaders']['rows'][number] }) => {
        const held = data.loop.market_open ? fmtHeld(r.since_ts, data.leaders.snapshot_ts) : null;
        const ev = r.today_event ? eventChip(r.today_event.type) : null;
        return (
            <Link
                to={`/dashboard/kr/leading-stocks#${r.code}`}
                className="grid grid-cols-[34px_minmax(0,1.3fr)_minmax(120px,1fr)_72px_72px_minmax(0,1fr)] items-center gap-2.5 rounded-xl border border-transparent px-2 py-2 transition-colors hover:border-white/[0.06] hover:bg-white/[0.03] max-sm:grid-cols-[30px_minmax(0,1fr)_64px_60px]"
            >
                <span className={`grid h-6 w-[30px] place-items-center rounded-md border text-[12px] font-black ${GRADE_CHIP[r.grade] ?? GRADE_CHIP.B}`}>{r.grade}</span>
                <span className="flex min-w-0 flex-col">
                    <b className="truncate font-bold text-white">{r.name}</b>
                    <span className="font-mono text-[11px] text-gray-500">{r.code}</span>
                </span>
                <span className="flex items-center gap-2 max-sm:hidden">
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.07]"><span className={`block h-full rounded-full ${GRADE_BAR[r.grade] ?? GRADE_BAR.B}`} style={{ width: `${Math.min(100, Math.max(0, r.score))}%` }} /></span>
                    <b className="w-7 text-right font-mono text-[12px] tabular-nums text-gray-200">{r.score}</b>
                </span>
                <span className={`text-right font-mono text-[13px] font-bold tabular-nums ${chgClass(r.chg)}`}>{fmtPct(r.chg)}</span>
                <span className="text-right font-mono text-[12px] tabular-nums text-gray-400">{fmtEok(r.trval_eok)}</span>
                <span className="flex flex-wrap justify-end gap-1.5 text-[11px] text-gray-500 max-sm:hidden">
                    {ev && <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${ev.cls}`}>{ev.label} {hhmm(r.today_event!.ts)}</span>}
                    {held && <span>유지 {held}</span>}
                </span>
            </Link>
        );
    };

    return (
        <section className="relative rounded-2xl border border-white/[0.06] bg-[#13151f] p-5 lg:col-span-7">
            <h2 className="mb-3 flex items-center gap-2 text-[15px] font-bold text-white">
                <i className="fas fa-crown text-[13px] text-teal-400" />
                주도주
                <span className="ml-auto text-[11px] font-medium text-gray-500">
                    {!data.loop.market_open && <span className="mr-2 rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-bold text-gray-300">전 세션 기준</span>}
                    스냅샷 {hhmm(data.leaders.snapshot_ts)} · S{bg.S ?? 0} A{bg.A ?? 0} B{bg.B ?? 0}
                </span>
            </h2>
            <div className="mb-1 grid grid-cols-[34px_minmax(0,1.3fr)_minmax(120px,1fr)_72px_72px_minmax(0,1fr)] gap-2.5 border-b border-white/[0.06] px-2 pb-1.5 text-[10.5px] uppercase tracking-wider text-gray-500 max-sm:grid-cols-[30px_minmax(0,1fr)_64px_60px]">
                <span /><span>종목</span><span className="max-sm:hidden">점수</span><span className="text-right">등락</span><span className="text-right">거래대금</span><span className="text-right max-sm:hidden">오늘</span>
            </div>
            <div className={halted ? 'opacity-40' : ''}>
                {lead.length === 0 ? (
                    <p className="py-5 text-center text-[13px] text-gray-500">{rows.length ? `현재 S/A 주도주 없음 — 마지막 스냅샷 ${hhmm(data.leaders.snapshot_ts)}` : '아직 스냅샷 없음 — 루프가 첫 틱을 저장하면 여기 표시됩니다'}</p>
                ) : lead.map(r => <Row key={r.code} r={r} />)}
                {bs.length > 0 && (
                    <div className="mt-2 border-t border-white/[0.06] pt-2">
                        <button type="button" onClick={() => setShowB(v => !v)} aria-expanded={showB}
                                className="rounded-lg px-2 py-1 text-[12px] font-bold text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-200">
                            <i className={`fas fa-chevron-${showB ? 'up' : 'down'} mr-1.5 text-[10px]`} />B등급 {bs.length}종목 {showB ? '접기' : '보기'}
                        </button>
                        {showB && bs.map(r => <Row key={r.code} r={r} />)}
                    </div>
                )}
            </div>
            {halted && (
                <div className="absolute inset-0 grid place-items-center rounded-2xl bg-[#09090b]/70 p-5 text-center backdrop-blur-[2px]">
                    <div className="rounded-xl border border-amber-400/45 bg-amber-500/10 px-4 py-3 text-[13px] font-bold text-amber-300">
                        <i className="fas fa-pause mr-1.5" />검출 보류 중 — 방향성 판단 없음
                        <div className="mt-1 text-[12px] font-medium text-amber-200/80">{data.regime.reasons.join(' · ')}</div>
                    </div>
                </div>
            )}
        </section>
    );
}
