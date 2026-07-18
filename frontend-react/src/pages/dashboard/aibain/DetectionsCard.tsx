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
            tone: 'border-orange-400/50 bg-orange-500/15 text-orange-200',
        };
    }
    if (ta.verdict === 'BUY') {
        return { label: `AI 매수${suffix}`, tone: 'border-teal-400/40 bg-teal-500/10 text-teal-300' };
    }
    return null;
}

function rsLabel(rating: number | null | undefined): string | null {
    // O'Neil 상대강도 (1~99 백분위) — 색 배지 대신 무채색 텍스트로 밀도 축소
    if (rating == null || !Number.isFinite(rating) || rating < 1 || rating > 99) return null;
    if (rating >= 85) return `RS ${rating} 주도주`;
    if (rating >= 70) return `RS ${rating} 강세`;
    if (rating <= 30) return `RS ${rating} 후행`;
    return `RS ${rating}`;
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
            <h2 className="text-white font-bold text-base flex items-center gap-2 mb-4">
                <i className="fas fa-bullseye text-cyan-400" />
                오늘의 검출
                <span className="text-[11px] font-medium text-gray-500">Top 3</span>
            </h2>

            {items.length === 0 ? (
                <p className="text-sm text-gray-400">오늘 신규 검출이 없습니다</p>
            ) : (
                <div className="space-y-2.5">
                    {items.map((item, idx) => {
                        const ta = tradingAgentsBadge(item.tradingagents);
                        const isStrong = !!(item.tradingagents?.strong_buy);
                        const meta = [
                            item.alpha_score != null ? `Alpha ${item.alpha_score}` : null,
                            item.risk_score != null ? `Risk ${item.risk_score}` : null,
                            rsLabel(item.rs_rating),
                        ].filter(Boolean).join('  ·  ');

                        return (
                            <div
                                key={`${item.symbol ?? 'unknown'}-${idx}`}
                                className={`rounded-xl border p-3.5 ${
                                    isStrong ? 'border-orange-400/25 bg-orange-500/[0.04]' : 'border-white/10 bg-white/[0.03]'
                                }`}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="flex items-center gap-3 min-w-0">
                                        <span className="shrink-0 grid place-items-center h-7 w-7 rounded-lg bg-white/[0.06] text-xs font-bold text-gray-400">
                                            {idx + 1}
                                        </span>
                                        <div className="min-w-0">
                                            <p className="text-[15px] font-bold text-white truncate">
                                                {item.name ?? item.symbol ?? '—'}
                                                {item.symbol && item.name && (
                                                    <span className="ml-1.5 text-xs text-gray-500 font-mono">{item.symbol}</span>
                                                )}
                                            </p>
                                            {meta && (
                                                <p className="mt-0.5 text-[11px] font-mono text-gray-500 truncate">{meta}</p>
                                            )}
                                        </div>
                                    </div>
                                    {ta && (
                                        <span className={`shrink-0 inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-bold ${ta.tone}`}>
                                            {ta.label}
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </section>
    );
}
