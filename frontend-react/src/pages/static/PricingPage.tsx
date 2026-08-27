import { useNavigate } from 'react-router-dom';
import { PublicShell } from '@/components/public/PublicShell';
import { useSeo } from '@/lib/seo';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { useAuth } from '@/contexts/AuthContext';
import {
    PLAN_PAYMENT_META,
    planToQuery,
    type BillingPlan,
} from '@/lib/billingInfo';

const PLAN_ORDER: BillingPlan[] = ['pro', 'pro_aibain', 'premium', 'premium_aibain'];

const PLAN_STYLE: Record<BillingPlan, {
    badge: string;
    icon: string;
    accent: string;
    border: string;
    surface: string;
    button: string;
}> = {
    pro: {
        badge: '기본 분석',
        icon: 'fa-chart-line',
        accent: 'text-amber-300',
        border: 'border-amber-400/25',
        surface: 'from-amber-500/[0.10] via-white/[0.025] to-transparent',
        button: 'bg-amber-400 text-slate-950 hover:bg-amber-300',
    },
    pro_aibain: {
        badge: '분석 확장',
        icon: 'fa-robot',
        accent: 'text-cyan-300',
        border: 'border-cyan-400/40',
        surface: 'from-cyan-500/[0.14] via-sky-500/[0.035] to-transparent',
        button: 'bg-cyan-300 text-slate-950 hover:bg-cyan-200',
    },
    premium: {
        badge: '평생 이용',
        icon: 'fa-infinity',
        accent: 'text-violet-300',
        border: 'border-violet-400/30',
        surface: 'from-violet-500/[0.12] via-white/[0.025] to-transparent',
        button: 'bg-violet-400 text-white hover:bg-violet-300',
    },
    premium_aibain: {
        badge: '평생 + 분석 코어',
        icon: 'fa-gem',
        accent: 'text-fuchsia-300',
        border: 'border-fuchsia-400/35',
        surface: 'from-fuchsia-500/[0.13] via-cyan-500/[0.035] to-transparent',
        button: 'bg-fuchsia-400 text-white hover:bg-fuchsia-300',
    },
};

const CORE_STAGES = [
    {
        index: '01',
        title: '관측',
        text: '장중 Claw와 일간 스캐너가 시장 변화, 데이터 시각, 결측 상태를 함께 기록합니다.',
        icon: 'fa-eye',
    },
    {
        index: '02',
        title: '검증',
        text: '근거 품질과 무효화 조건을 확인하고, 재현되지 않은 주장은 운영 판단에서 분리합니다.',
        icon: 'fa-shield-halved',
    },
    {
        index: '03',
        title: '학습',
        text: '검출 이후의 결과를 같은 기준으로 추적하고, 검증을 통과한 규칙만 제한적으로 반영합니다.',
        icon: 'fa-rotate',
    },
];

function nextPath(plan: BillingPlan, signedIn: boolean): string {
    const query = planToQuery(plan);
    return signedIn
        ? `/plan-select?change=1&${query}`
        : `/signup?${query}`;
}

export default function PricingPage() {
    const { user } = useAuth();
    const navigate = useNavigate();

    useSeo({
        title: '요금제 — Pro · Ultra Pro · AI Brain | MarketFlow',
        description: 'MarketFlow 구독 요금제 안내 — Pro(30일), Ultra Pro(무기한), AI Brain 애드온의 기능과 가격, 계좌이체 결제·승인 절차를 확인하세요.',
        path: '/pricing',
    });

    return (
        <PublicShell section="plans">
            <section className="mx-auto w-full max-w-6xl px-4 pb-8 pt-14 sm:px-6 sm:pt-20">
                <div className="mx-auto max-w-3xl text-center">
                    <div className="inline-flex items-center gap-2 rounded-full border border-[#ff6b57]/25 bg-[#ff6b57]/[0.08] px-3 py-1.5 font-mono text-[10px] font-black uppercase tracking-[0.18em] text-[#ff9b89]">
                        <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b57]" />
                        Observe · Verify · Learn
                    </div>
                    <h1 className="mt-6 text-4xl font-black tracking-[-0.04em] text-white sm:text-6xl">
                        더 많은 신호보다
                        <span className="block bg-gradient-to-r from-[#ff8a76] via-amber-300 to-emerald-300 bg-clip-text text-transparent">
                            더 검증된 판단
                        </span>
                    </h1>
                    <p className="mx-auto mt-5 max-w-2xl text-sm leading-7 text-gray-400 sm:text-base">
                        MarketFlow는 시장을 관측하고, 근거와 공백을 함께 보여주며, 검출 이후의 결과까지 추적합니다.
                        자동 주문이나 수익을 약속하지 않고 투자 판단에 필요한 분석 맥락을 제공합니다.
                    </p>
                    <div className="mt-6 flex flex-wrap justify-center gap-2 text-[11px] font-bold text-gray-400">
                        {['장중 변화 감시', '근거 품질 표시', '무효화 조건 추적', '사후 성과 검증'].map((label) => (
                            <span key={label} className="rounded-full border border-white/[0.08] bg-white/[0.035] px-3 py-1.5">
                                <i className="fas fa-check mr-1.5 text-emerald-300" />{label}
                            </span>
                        ))}
                    </div>
                </div>

                <div className="mt-12 grid grid-cols-1 gap-4 lg:grid-cols-2">
                    {PLAN_ORDER.map((plan) => (
                        <PlanCard
                            key={plan}
                            plan={plan}
                            signedIn={!!user}
                            onSelect={() => navigate(nextPath(plan, !!user))}
                        />
                    ))}
                </div>

                <div className="mt-8 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5 sm:p-6">
                    <div className="grid gap-5 md:grid-cols-3">
                        {CORE_STAGES.map((stage) => (
                            <article key={stage.index} className="flex gap-4">
                                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/[0.08] bg-black/25 text-emerald-300">
                                    <i className={`fas ${stage.icon}`} />
                                </div>
                                <div>
                                    <div className="font-mono text-[9px] font-black tracking-[0.18em] text-gray-600">CORE {stage.index}</div>
                                    <h2 className="mt-1 text-sm font-black text-white">{stage.title}</h2>
                                    <p className="mt-1.5 text-xs leading-5 text-gray-500">{stage.text}</p>
                                </div>
                            </article>
                        ))}
                    </div>
                </div>

                <div className="mt-8 grid gap-4 rounded-2xl border border-amber-400/15 bg-gradient-to-r from-amber-500/[0.06] to-transparent p-5 sm:grid-cols-[1fr_auto] sm:items-center sm:p-6">
                    <div>
                        <div className="text-sm font-black text-white">가입부터 활성화까지 네 단계면 충분합니다.</div>
                        <p className="mt-1.5 text-xs leading-5 text-gray-500">
                            계정 생성 → 플랜 선택 → 입금 정보 확인 → 관리자 승인. 승인 시점부터 이용 기간이 시작됩니다.
                        </p>
                    </div>
                    <KakaoSupportLink className="sm:w-auto sm:min-w-44" label="플랜 문의" />
                </div>
            </section>
        </PublicShell>
    );
}

function PlanCard({
    plan,
    signedIn,
    onSelect,
}: {
    plan: BillingPlan;
    signedIn: boolean;
    onSelect: () => void;
}) {
    const meta = PLAN_PAYMENT_META[plan];
    const style = PLAN_STYLE[plan];
    const recommended = plan === 'pro_aibain';

    return (
        <article className={`relative overflow-hidden rounded-2xl border ${style.border} bg-gradient-to-br ${style.surface} p-5 shadow-[0_20px_70px_rgba(0,0,0,0.2)] sm:p-7`}>
            {recommended && (
                <div className="absolute right-4 top-4 rounded-full bg-cyan-300 px-2.5 py-1 text-[9px] font-black uppercase tracking-wider text-slate-950">
                    AI 확장
                </div>
            )}
            <div className={`inline-flex items-center gap-2 text-[11px] font-black ${style.accent}`}>
                <i className={`fas ${style.icon}`} />
                {style.badge}
            </div>
            <h2 className="mt-3 text-2xl font-black text-white">{meta.label}</h2>
            <p className="mt-1 min-h-5 text-xs font-semibold text-gray-500">{meta.description}</p>

            <div className="mt-5 flex flex-wrap items-end gap-x-2 gap-y-1">
                <span className="text-3xl font-black tracking-tight text-white sm:text-4xl">{meta.amount}</span>
                <span className={`pb-1 text-[11px] font-bold ${style.accent}`}>{meta.period}</span>
            </div>

            {meta.includesAibain && meta.baseAmount && meta.aibainAmount && (
                <div className="mt-3 flex flex-wrap gap-2 font-mono text-[10px] text-gray-500">
                    <span className="rounded-md border border-white/[0.07] bg-black/20 px-2 py-1">{meta.baseAmount}</span>
                    <span className="rounded-md border border-white/[0.07] bg-black/20 px-2 py-1">{meta.aibainAmount}</span>
                </div>
            )}

            <ul className="mt-6 grid gap-2 sm:grid-cols-2">
                {meta.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-xs leading-5 text-gray-300">
                        <i className={`fas fa-check mt-1 text-[10px] ${style.accent}`} />
                        <span>{feature}</span>
                    </li>
                ))}
            </ul>

            <button
                type="button"
                onClick={onSelect}
                className={`mt-7 min-h-[48px] w-full rounded-xl px-4 text-sm font-black transition-colors ${style.button}`}
            >
                {signedIn ? `${meta.label} 선택 계속하기` : `${meta.label} 선택하기`}
                <i className="fas fa-arrow-right ml-2 text-xs" />
            </button>
        </article>
    );
}
