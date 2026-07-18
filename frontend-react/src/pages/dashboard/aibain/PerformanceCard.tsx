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
    learningPattern?: string | null;
}

export default function PerformanceCard({ data, learningPattern }: PerformanceCardProps) {
    const verified = (data?.verified ?? []).filter((v) => v.forward_return_pct != null).slice(0, 8);
    const windowDays = data?.window_days ?? 30;
    const evaluated = data?.evaluated_count ?? 0;

    return (
        <section className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <h2 className="text-white font-bold text-base flex items-center gap-2 mb-4">
                <i className="fas fa-chart-line text-cyan-400" />
                성과 검증
                <span className="text-[11px] font-medium text-gray-500">최근 {windowDays}일</span>
            </h2>

            <div className="flex items-center gap-x-6 gap-y-2 flex-wrap mb-4">
                <Stat label="적중률" value={fmtPct(data?.hit_rate_pct)} />
                <span className="h-4 w-px bg-white/10" />
                <Stat label="평균 수익" value={fmtSignedPct(data?.avg_forward_return_pct)} signed={data?.avg_forward_return_pct} />
                <span className="h-4 w-px bg-white/10" />
                <Stat label="표본" value={`${evaluated}개`} />
            </div>

            {evaluated === 0 ? (
                <p className="text-sm text-gray-400">성과 검증 데이터를 누적 중입니다</p>
            ) : (
                <div className="flex flex-wrap gap-1.5">
                    {verified.map((item, idx) => {
                        const ret = item.forward_return_pct as number;
                        const up = ret >= 0;
                        const title = `${item.name ?? item.symbol ?? ''}${item.entry_date ? ` · ${item.entry_date}` : ''}`;
                        return (
                            <span
                                key={`${item.symbol ?? 'unknown'}-${idx}`}
                                title={title}
                                className={`inline-flex items-center gap-0.5 rounded-md border px-2 py-0.5 text-[11px] font-bold font-mono ${
                                    up ? 'border-emerald-400/25 bg-emerald-500/10 text-emerald-300' : 'border-red-400/25 bg-red-500/10 text-red-300'
                                }`}
                            >
                                {up ? '▲' : '▼'}{ret.toFixed(1)}%
                            </span>
                        );
                    })}
                </div>
            )}

            {learningPattern && (
                <p className="mt-4 pt-3 border-t border-white/[0.06] text-[11px] text-gray-500">
                    <i className="fas fa-brain mr-1.5 text-gray-600" />
                    {'AI 학습: 잘 맞은 패턴 '}
                    <span className="text-gray-400 font-medium">{learningPattern}</span>
                </p>
            )}
        </section>
    );
}

function fmtPct(value: number | null | undefined): string {
    if (value == null) return '—';
    return `${value}%`;
}

function fmtSignedPct(value: number | null | undefined): string {
    if (value == null) return '—';
    const sign = value > 0 ? '+' : '';
    return `${sign}${value}%`;
}

function Stat({ label, value, signed }: { label: string; value: string; signed?: number | null }) {
    const valueColor =
        signed == null ? 'text-white' : signed >= 0 ? 'text-emerald-400' : 'text-red-400';
    return (
        <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-gray-500">{label}</span>
            <span className={`text-lg font-black ${valueColor}`}>{value}</span>
        </div>
    );
}
