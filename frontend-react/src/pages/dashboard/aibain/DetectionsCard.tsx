interface DetectionItem {
    symbol: string | null;
    name: string | null;
    action: string | null;
    alpha_score: number | null;
    risk_score: number | null;
    entry_date: string | null;
}

interface DetectionsCardProps {
    data: {
        as_of: string | null;
        items: DetectionItem[];
    };
}

export default function DetectionsCard({ data }: DetectionsCardProps) {
    const items = data?.items ?? [];

    return (
        <section className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <h2 className="text-white font-bold text-base flex items-center gap-2">
                    <i className="fas fa-bullseye text-cyan-400" />
                    오늘의 검출 (Top 3)
                </h2>
                {data?.as_of && (
                    <span className="text-[11px] text-gray-500">기준일: {data.as_of}</span>
                )}
            </div>

            {items.length === 0 ? (
                <p className="text-sm text-gray-400">오늘 신규 검출이 없습니다</p>
            ) : (
                <div className="space-y-3">
                    {items.map((item, idx) => (
                        <div
                            key={`${item.symbol ?? 'unknown'}-${idx}`}
                            className="rounded-xl border border-white/10 bg-white/[0.03] p-3 flex items-center justify-between gap-3 flex-wrap"
                        >
                            <div className="min-w-0">
                                <p className="text-sm font-bold text-white truncate">
                                    {item.name ?? item.symbol ?? '—'}
                                    {item.symbol && item.name && (
                                        <span className="ml-1.5 text-xs text-gray-500 font-mono">{item.symbol}</span>
                                    )}
                                </p>
                                {item.entry_date && (
                                    <p className="text-[11px] text-gray-500 mt-0.5">진입일: {item.entry_date}</p>
                                )}
                            </div>
                            <div className="flex items-center gap-2 flex-wrap">
                                {item.action && (
                                    <span className="inline-flex items-center rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-bold text-cyan-300 uppercase">
                                        {item.action}
                                    </span>
                                )}
                                {item.alpha_score != null && (
                                    <span className="inline-flex items-center rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                                        Alpha {item.alpha_score}
                                    </span>
                                )}
                                {item.risk_score != null && (
                                    <span className="inline-flex items-center rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                                        Risk {item.risk_score}
                                    </span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}
