interface VerifiedItem {
    symbol: string | null;
    name: string | null;
    entry_date: string | null;
    forward_return_pct: number | null;
    hit: boolean | null;
    status: string;
}

interface PerformanceCardProps {
    data: {
        window_days: number;
        hit_rate_pct: number | null;
        avg_forward_return_pct: number | null;
        false_positive_pct: number | null;
        evaluated_count: number;
        verified: VerifiedItem[];
    };
}

export default function PerformanceCard({ data }: PerformanceCardProps) {
    const verified = data?.verified ?? [];
    const windowDays = data?.window_days ?? 30;

    return (
        <section className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <h2 className="text-white font-bold text-base flex items-center gap-2 mb-4">
                <i className="fas fa-chart-line text-cyan-400" />
                성과 검증 (최근 {windowDays}일)
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                <KpiTile label="적중률" value={fmtPct(data?.hit_rate_pct)} />
                <KpiTile label="평균 수익" value={fmtPct(data?.avg_forward_return_pct)} />
                <KpiTile label="평가 표본" value={`${data?.evaluated_count ?? 0}`} />
            </div>

            {(data?.evaluated_count ?? 0) === 0 ? (
                <p className="text-sm text-gray-400">성과 검증 데이터를 누적 중입니다</p>
            ) : (
                <div className="space-y-2">
                    {verified.map((item, idx) => {
                        const ret = item.forward_return_pct;
                        const isPositive = ret != null ? ret >= 0 : null;
                        return (
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
                                <div className="flex items-center gap-2">
                                    {ret != null && (
                                        <span
                                            className={`inline-flex items-center gap-1 text-sm font-bold ${
                                                isPositive ? 'text-emerald-400' : 'text-red-400'
                                            }`}
                                        >
                                            {isPositive ? '▲' : '▼'}
                                            {ret.toFixed(2)}%
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

function fmtPct(value: number | null | undefined): string {
    if (value == null) return '—%';
    return `${value}%`;
}

function KpiTile({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-center">
            <p className="text-2xl font-black text-white">{value}</p>
            <p className="text-[11px] text-gray-500 mt-1">{label}</p>
        </div>
    );
}
