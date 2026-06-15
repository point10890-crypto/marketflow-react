interface ComboStat {
    combo: string;
    n: number;
    hit_rate: number;
    expectancy_pct: number;
}

interface LearningCardProps {
    data: {
        regime_distribution: Record<string, number>;
        top_positive: ComboStat[];
        top_negative: ComboStat[];
        updated_at: string | null;
    };
}

export default function LearningCard({ data }: LearningCardProps) {
    const topPositive = data?.top_positive ?? [];
    const topNegative = data?.top_negative ?? [];
    const regimeDistribution = data?.regime_distribution ?? {};
    const regimeEntries = Object.entries(regimeDistribution);

    const isEmpty = topPositive.length === 0 && topNegative.length === 0 && regimeEntries.length === 0;

    return (
        <section className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <h2 className="text-white font-bold text-base flex items-center gap-2 mb-4">
                <i className="fas fa-brain text-cyan-400" />
                AI 학습 피드백
            </h2>

            {isEmpty ? (
                <p className="text-sm text-gray-400">학습 데이터를 누적 중입니다</p>
            ) : (
                <>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                        <ComboGroup title="잘 맞은 패턴" items={topPositive} tone="positive" />
                        <ComboGroup title="주의할 패턴" items={topNegative} tone="negative" />
                    </div>

                    {regimeEntries.length > 0 && (
                        <p className="text-[11px] text-gray-500">
                            시장 레짐 분포: {regimeEntries.map(([regime, count]) => `${regime} ${count}`).join(' · ')}
                        </p>
                    )}
                </>
            )}
        </section>
    );
}

function ComboGroup({ title, items, tone }: { title: string; items: ComboStat[]; tone: 'positive' | 'negative' }) {
    const toneClasses =
        tone === 'positive'
            ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300'
            : 'border-red-400/30 bg-red-500/10 text-red-300';

    return (
        <div>
            <h3 className="text-xs font-bold text-gray-400 mb-2">{title}</h3>
            {items.length === 0 ? (
                <p className="text-xs text-gray-500">데이터 없음</p>
            ) : (
                <div className="flex flex-col gap-2">
                    {items.map((item, idx) => (
                        <div
                            key={`${item.combo}-${idx}`}
                            className={`rounded-lg border px-3 py-2 text-xs ${toneClasses}`}
                        >
                            <p className="font-bold text-white truncate">{item.combo}</p>
                            <p className="mt-0.5 text-[11px] opacity-90">
                                적중 {Math.round(item.hit_rate * 100)}% · 기대 {item.expectancy_pct}% · n={item.n}
                            </p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
