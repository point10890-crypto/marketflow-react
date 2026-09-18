import StockLink from '@/components/stock/StockLink';
import { useState } from 'react';
import { ClawOverview, eventChip, fmtPct, hhmm } from '@/lib/claw';

const FILTERS: { key: string; label: string }[] = [
    { key: 'ALL', label: '전체' }, { key: 'LEADER_NEW', label: 'NEW' }, { key: 'LEADER_UPGRADE', label: 'UP' },
    { key: 'LEADER_DROP', label: 'DROP' }, { key: 'VOLUME_SURGE', label: 'VOL' }, { key: 'NEW_HIGH_BREAK', label: 'HIGH' },
];

/** 이벤트 타임라인 (5col) — 최신이 위, 유형 필터, 발송 ✓ */
export default function ClawEventsCard({ data }: { data: ClawOverview }) {
    const [filter, setFilter] = useState('ALL');
    const items = data.events.items.slice().reverse().filter(e => filter === 'ALL' || e.type === filter);

    return (
        <section className="claw-card-in rounded-2xl border border-white/[0.06] bg-[#13151f] p-4 sm:rounded-3xl sm:p-5 lg:col-span-5">
            <h2 className="mb-3 flex items-center gap-2 text-[15px] font-bold text-white">
                <i className="fas fa-bolt text-[13px] text-teal-400" />
                이벤트 타임라인
                <span className="ml-auto text-[11px] font-medium text-gray-500">
                    {data.loop.market_open ? '실시간' : <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-bold text-gray-300">전 세션 이벤트</span>}
                </span>
            </h2>
            <div className="mb-2.5 flex flex-wrap gap-1.5">
                {FILTERS.map(f => (
                    <button key={f.key} type="button" onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
                            className={`min-h-9 rounded-full border px-2.5 py-1 text-[11.5px] font-bold transition-colors ${filter === f.key ? 'border-white/15 bg-white/10 text-white' : 'border-white/10 text-gray-400 hover:text-gray-200'}`}>
                        {f.label}{f.key !== 'ALL' && data.events.counts[f.key] ? <span className="ml-1 text-gray-500">{data.events.counts[f.key]}</span> : null}
                    </button>
                ))}
            </div>
            {items.length === 0 ? (
                <p className="py-5 text-center text-[13px] text-gray-500">
                    {data.events.items.length ? '이 유형의 이벤트 없음' : data.leaders.rows.length ? '아직 조용해요 — 등급이 바뀌면 바로 여기 올라옵니다' : '첫 이벤트를 기다리는 중이에요'}
                </p>
            ) : (
                <ul className="divide-y divide-white/[0.06]">
                    {items.map((e, i) => {
                        const chip = eventChip(e.type);
                        const halt = e.type.startsWith('HALT');
                        const tr = e.grade_from || e.grade_to ? `${e.grade_from || '–'}→${e.grade_to || '–'}` : '';
                        return (
                            <li key={`${e.ts}-${e.type}-${e.code}-${i}`} className={`grid grid-cols-[42px_44px_minmax(0,1fr)_16px] items-center gap-2 py-2.5 text-[13px] sm:grid-cols-[44px_46px_minmax(0,1fr)_auto_16px] ${halt ? 'rounded-lg bg-amber-500/[0.06] px-1.5' : ''}`}>
                                <span className="font-mono text-[12px] tabular-nums text-gray-500">{hhmm(e.ts)}</span>
                                <span className={`rounded px-1.5 py-0.5 text-center text-[10px] font-bold ${chip.cls}`}>{chip.label}</span>
                                <span className="min-w-0 truncate text-gray-100">
                                    {e.code ? <StockLink code={e.code} market="KR" className="text-gray-100">{e.name}</StockLink> : e.name}
                                    {e.code && <span className="ml-1.5 font-mono text-[11px] text-gray-500">{e.code}</span>}
                                </span>
                                <span className="hidden whitespace-nowrap font-mono text-[11.5px] text-gray-400 sm:block">{tr}{e.chg != null && e.score != null ? ` · ${fmtPct(e.chg)}` : ''}</span>
                                <span className={`text-right text-[11px] ${e.reported_at ? 'text-teal-300' : 'text-gray-600'}`} title={e.reported_at ? `발송 ${hhmm(e.reported_at)}` : '미발송'}>
                                    <i className={`fas ${e.reported_at ? 'fa-check' : 'fa-minus'}`} />
                                </span>
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}
