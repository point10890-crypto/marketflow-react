import { useEffect, useState } from 'react';
import { BRIEF_KIND_LABEL, ClawOverview, hhmm, renderTelegramText } from '@/lib/claw';

/** 브리핑 (8col) — 탭: 종류·시각·발송 여부. 본문은 <b> 만 허용해 렌더. 재발송 버튼 없음. */
export default function ClawBriefsCard({ data }: { data: ClawOverview }) {
    const list = data.briefs.items.slice().sort((a, b) => a.ts.localeCompare(b.ts));
    const [tab, setTab] = useState(0);
    useEffect(() => { if (tab >= list.length) setTab(Math.max(0, list.length - 1)); }, [list.length, tab]);
    const cur = list[tab];

    return (
        <section className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-5 lg:col-span-8">
            <h2 className="mb-3 flex items-center gap-2 text-[15px] font-bold text-white">
                <i className="fab fa-telegram text-[13px] text-teal-400" />
                브리핑
                <span className="ml-auto text-[11px] font-medium text-gray-500">{list.length ? `${list.length}건` : ''}</span>
            </h2>
            {list.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5" role="tablist">
                    {list.map((b, i) => (
                        <button key={b.digest || i} type="button" role="tab" aria-selected={i === tab} onClick={() => setTab(i)}
                                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px] font-bold transition-colors ${i === tab ? 'border-white/15 bg-white/[0.08] text-white' : 'border-white/10 text-gray-400 hover:text-gray-200'}`}>
                            {BRIEF_KIND_LABEL[b.kind] ?? b.kind} {hhmm(b.ts)}
                            <span className={b.delivered ? 'text-teal-300' : 'text-amber-300'}>
                                <i className={`fas ${b.delivered ? 'fa-check' : 'fa-flask'} text-[10px]`} /> {b.delivered ? '발송' : 'dry-run'}
                            </span>
                        </button>
                    ))}
                </div>
            )}
            <div className="max-h-72 overflow-auto whitespace-pre-wrap break-keep rounded-xl rounded-bl-[4px] border border-white/[0.06] bg-[#181b27] px-3.5 py-3 text-[13px] leading-relaxed text-gray-200">
                {cur ? renderTelegramText(cur.text) : <span className="text-gray-500">아직 브리핑 없음 — 08:20 조간 브리핑부터 쌓입니다</span>}
            </div>
        </section>
    );
}
