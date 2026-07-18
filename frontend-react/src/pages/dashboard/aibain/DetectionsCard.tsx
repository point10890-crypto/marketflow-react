interface TradingAgentsVerdict {
    verdict: string | null;
    confidence: number | null;
    strong_buy: boolean | null;
}

interface DetectionItem {
    symbol: string | null;
    name: string | null;
    action: string | null;
    alpha_score: number | null;
    risk_score: number | null;
    rs_rating: number | null;
    entry_date: string | null;
    tradingagents?: TradingAgentsVerdict | null;
}

function tradingAgentsBadge(ta: TradingAgentsVerdict | null | undefined): { label: string; tone: string } | null {
    // TradingAgents 다중 에이전트 딥 검증 판정 — 매수 유력 종목 강조
    if (!ta || !ta.verdict) return null;
    const conf = Number.isFinite(ta.confidence as number) ? Math.round(ta.confidence as number) : null;
    const suffix = conf != null ? ` ${conf}%` : '';
    if (ta.strong_buy || ta.verdict === 'STRONG_BUY') {
        return {
            label: `🔥 매수 유력${suffix}`,
            tone: 'border-orange-400/50 bg-gradient-to-r from-orange-500/20 to-rose-500/20 text-orange-200 shadow-[0_0_12px_-2px_rgba(251,146,60,0.5)]',
        };
    }
    if (ta.verdict === 'BUY') {
        return { label: `AI 매수${suffix}`, tone: 'border-teal-400/40 bg-teal-500/10 text-teal-300' };
    }
    return null;
}

function rsBadge(rating: number | null | undefined): { label: string; tone: string } | null {
    // O'Neil 상대강도 (1~99 백분위) — 시장 주도주/후행주 구분
    if (rating == null || !Number.isFinite(rating) || rating < 1 || rating > 99) return null;
    if (rating >= 85) return { label: `RS ${rating} 주도주`, tone: 'border-yellow-400/40 bg-yellow-500/10 text-yellow-300' };
    if (rating >= 70) return { label: `RS ${rating} 강세`, tone: 'border-sky-400/30 bg-sky-500/10 text-sky-300' };
    if (rating <= 30) return { label: `RS ${rating} 후행`, tone: 'border-rose-400/30 bg-rose-500/10 text-rose-300' };
    return { label: `RS ${rating}`, tone: 'border-white/15 bg-white/[0.06] text-gray-300' };
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
                                {(() => {
                                    const ta = tradingAgentsBadge(item.tradingagents);
                                    return ta ? (
                                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold ${ta.tone}`}>
                                            {ta.label}
                                        </span>
                                    ) : null;
                                })()}
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
                                {(() => {
                                    const rs = rsBadge(item.rs_rating);
                                    return rs ? (
                                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold ${rs.tone}`}>
                                            {rs.label}
                                        </span>
                                    ) : null;
                                })()}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}
