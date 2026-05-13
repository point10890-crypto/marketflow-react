/**
 * 🪣 줍줍이 컨텍스트 배너 — 페이지 상단 안내 + 통계.
 */
import { JubjubResponse } from '@/lib/jubjubApi';

interface JubjubBannerProps {
    data: JubjubResponse | null;
    minScore: number;
    onMinScoreChange: (v: number) => void;
    loading?: boolean;
}

export default function JubjubBanner({ data, minScore, onMinScoreChange, loading }: JubjubBannerProps) {
    const stats = data?.stats;
    return (
        <section className="mb-4 overflow-hidden rounded-2xl border border-amber-500/15 bg-black/60 p-4 backdrop-blur-md sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className="text-2xl">🪣</span>
                        <h2 className="text-xl font-black text-white sm:text-2xl">
                            줍줍이
                        </h2>
                        <span className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-2 py-0.5 text-[10px] font-black uppercase tracking-wider text-emerald-200">
                            저점 매수
                        </span>
                    </div>
                    <p className="mt-1.5 text-xs font-bold leading-relaxed text-neutral-400 sm:text-sm">
                        W 패턴 + 거래량 확인 + 외인 매수 + 넥라인 근접 = 줍줍 시그널.
                        진입가/목표가/손절가 자동 산출.
                    </p>
                </div>
                {loading ? (
                    <div className="text-[10px] font-bold uppercase text-neutral-500">loading...</div>
                ) : null}
            </div>

            {/* 통계 + 점수 필터 */}
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat
                    label="줍줍 후보"
                    value={data?.jubjub_count ?? 0}
                    suffix="개"
                    tone="emerald"
                />
                <Stat
                    label="🎯 진입 임박"
                    value={stats?.imminent ?? 0}
                    suffix="개"
                    tone="amber"
                />
                <Stat
                    label="🔥 매수 타이밍"
                    value={stats?.buy_now ?? 0}
                    suffix="개"
                    tone="rose"
                />
                <Stat
                    label="🚀 막 돌파"
                    value={stats?.breakout ?? 0}
                    suffix="개"
                    tone="emerald"
                />
            </div>

            {/* 최고 점수 + 점수 필터 슬라이더 */}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                {stats?.top_score && stats?.top_name ? (
                    <div className="text-[11px] font-bold text-neutral-400">
                        최고 점수:{' '}
                        <span className="font-mono tabular-nums text-amber-300 font-black">
                            {Math.round(stats.top_score)}
                        </span>
                        <span className="mx-1 text-neutral-600">·</span>
                        <span className="text-white">{stats.top_name}</span>
                    </div>
                ) : (
                    <div className="text-[11px] font-bold text-neutral-500">표본 없음</div>
                )}
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-black uppercase tracking-wider text-neutral-500">
                        최소 점수
                    </span>
                    <div className="inline-flex overflow-hidden rounded-md border border-white/10 bg-black/30">
                        {[60, 70, 80, 90].map((s) => (
                            <button
                                key={s}
                                type="button"
                                onClick={() => onMinScoreChange(s)}
                                className={`min-h-[28px] px-2.5 py-1 text-[10px] font-black transition-colors ${
                                    minScore === s
                                        ? 'bg-amber-300/20 text-amber-200'
                                        : 'text-neutral-500 hover:bg-white/5 hover:text-neutral-300 active:bg-white/10'
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

function Stat({ label, value, suffix, tone }: { label: string; value: number; suffix?: string; tone: 'emerald' | 'amber' | 'rose' }) {
    const toneClasses = {
        emerald: 'text-emerald-300',
        amber: 'text-amber-300',
        rose: 'text-rose-300',
    }[tone];
    return (
        <div className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 backdrop-blur-md">
            <div className="text-[9px] font-black uppercase tracking-wider text-neutral-500 truncate">
                {label}
            </div>
            <div className={`mt-1 text-xl font-black tabular-nums sm:text-2xl ${toneClasses}`}>
                {value}
                {suffix && <span className="ml-0.5 text-[10px] font-bold opacity-70">{suffix}</span>}
            </div>
        </div>
    );
}
