/**
 * 🪣 줍줍이 컨텍스트 배너 — 페이지 상단 안내 + 통계.
 */
import { JubjubBadge, JubjubResponse } from '@/lib/jubjubApi';

export type JubjubBadgeFilter = 'all' | JubjubBadge;

interface JubjubBannerProps {
    data: JubjubResponse | null;
    minScore: number;
    onMinScoreChange: (v: number) => void;
    badgeFilter?: JubjubBadgeFilter;
    onBadgeFilterChange?: (f: JubjubBadgeFilter) => void;
    loading?: boolean;
}

export default function JubjubBanner({ data, minScore, onMinScoreChange, badgeFilter = 'all', onBadgeFilterChange, loading }: JubjubBannerProps) {
    const stats = data?.stats;
    return (
        <section className="mb-4 overflow-hidden rounded-2xl border border-white/8 bg-neutral-950/80 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className="text-2xl opacity-80">🪣</span>
                        <h2 className="text-xl font-black text-neutral-100 sm:text-2xl">
                            줍줍이
                        </h2>
                        <span className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-neutral-400">
                            저점 매수
                        </span>
                    </div>
                    <p className="mt-1.5 text-xs font-medium leading-relaxed text-neutral-500 sm:text-sm">
                        W 패턴 + 거래량 확인 + 외인 매수 + 넥라인 근접 = 줍줍 시그널.
                        진입가/목표가/손절가 자동 산출.
                    </p>
                </div>
                {loading ? (
                    <div className="text-[10px] font-bold uppercase text-neutral-600">loading...</div>
                ) : null}
            </div>

            {/* 통계 + 점수 필터 (각 타일은 클릭 시 해당 카테고리로 필터 + 스크롤) */}
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat
                    label="줍줍 후보"
                    value={data?.jubjub_count ?? 0}
                    suffix="개"
                    tone="emerald"
                    active={badgeFilter === 'all'}
                    onClick={onBadgeFilterChange ? () => onBadgeFilterChange('all') : undefined}
                />
                <Stat
                    label="🎯 진입 임박"
                    value={stats?.imminent ?? 0}
                    suffix="개"
                    tone="amber"
                    active={badgeFilter === 'imminent'}
                    onClick={onBadgeFilterChange ? () => onBadgeFilterChange('imminent') : undefined}
                />
                <Stat
                    label="🔥 매수 타이밍"
                    value={stats?.buy_now ?? 0}
                    suffix="개"
                    tone="rose"
                    active={badgeFilter === 'buy_now'}
                    onClick={onBadgeFilterChange ? () => onBadgeFilterChange('buy_now') : undefined}
                />
                <Stat
                    label="🚀 막 돌파"
                    value={stats?.breakout ?? 0}
                    suffix="개"
                    tone="emerald"
                    active={badgeFilter === 'breakout'}
                    onClick={onBadgeFilterChange ? () => onBadgeFilterChange('breakout') : undefined}
                />
            </div>

            {/* 최고 점수 + 점수 필터 슬라이더 */}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                {stats?.top_score && stats?.top_name ? (
                    <div className="text-[11px] font-medium text-neutral-500">
                        최고 점수:{' '}
                        <span className="font-mono tabular-nums text-neutral-200 font-bold">
                            {Math.round(stats.top_score)}
                        </span>
                        <span className="mx-1 text-neutral-700">·</span>
                        <span className="text-neutral-300">{stats.top_name}</span>
                    </div>
                ) : (
                    <div className="text-[11px] font-medium text-neutral-600">표본 없음</div>
                )}
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-neutral-600">
                        최소 점수
                    </span>
                    <div className="inline-flex overflow-hidden rounded-md border border-white/8 bg-black/40">
                        {[60, 70, 80, 90].map((s) => (
                            <button
                                key={s}
                                type="button"
                                onClick={() => onMinScoreChange(s)}
                                className={`min-h-[28px] px-2.5 py-1 text-[10px] font-bold transition-colors ${
                                    minScore === s
                                        ? 'bg-white/[0.06] text-neutral-200'
                                        : 'text-neutral-600 hover:bg-white/[0.03] hover:text-neutral-400'
                                }`}
                            >
                                ≥{s}
                            </button>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    );
}

function Stat({ label, value, suffix, tone, active, onClick }: {
    label: string;
    value: number;
    suffix?: string;
    tone: 'emerald' | 'amber' | 'rose';
    active?: boolean;
    onClick?: () => void;
}) {
    // 톤 표시는 좌측 미세한 dot 으로만 — 숫자는 통일된 뉴트럴 (Bloomberg 스타일)
    const toneDot = {
        emerald: 'bg-emerald-400/50',
        amber: 'bg-amber-400/50',
        rose: 'bg-rose-400/50',
    }[tone];
    const activeRing = active
        ? 'border-white/20 bg-white/[0.04]'
        : 'border-white/8 bg-black/30 hover:border-white/15 hover:bg-white/[0.02]';
    const interactive = onClick
        ? `cursor-pointer transition-colors text-left w-full ${activeRing}`
        : 'border-white/8 bg-black/30';
    const content = (
        <>
            <div className="flex items-center gap-1.5">
                <span className={`inline-block h-1 w-1 rounded-full ${toneDot}`} aria-hidden />
                <div className="text-[9px] font-bold uppercase tracking-wider text-neutral-500 truncate">
                    {label}
                </div>
                {active && (
                    <span className="ml-auto shrink-0 text-[8px] font-bold uppercase tracking-wider text-neutral-400">ON</span>
                )}
            </div>
            <div className="mt-1 text-xl font-black tabular-nums text-neutral-100 sm:text-2xl">
                {value}
                {suffix && <span className="ml-0.5 text-[10px] font-medium text-neutral-500">{suffix}</span>}
            </div>
        </>
    );
    if (onClick) {
        return (
            <button
                type="button"
                onClick={onClick}
                aria-pressed={active}
                className={`rounded-xl border px-3 py-2 ${interactive}`}
            >
                {content}
            </button>
        );
    }
    return (
        <div className={`rounded-xl border px-3 py-2 ${interactive}`}>
            {content}
        </div>
    );
}
