import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { PLAN_PAYMENT_META, planToQuery, type BillingPlan } from '@/lib/billingInfo';

const FLOW_STEPS = ['계정 생성', '플랜 선택', '입금 정보', '승인 대기'];

export default function PlanSelectPage() {
    const { user, token, loading } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const isResubscribe = searchParams.get('resubscribe') === '1' || searchParams.get('from') === 'expired';
    const allowChange = searchParams.get('change') === '1';

    useEffect(() => {
        if (loading) return;
        if (!user || !token) {
            navigate('/signup', { replace: true });
            return;
        }
        if (user.role === 'admin') {
            navigate('/dashboard', { replace: true });
            return;
        }
        const isActive = (user.tier === 'pro' || user.tier === 'premium')
            && user.status === 'approved'
            && !user.is_pro_expired;
        if (isActive && !allowChange) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, token, loading, navigate, allowChange]);

    if (loading) {
        return (
            <div className="fixed inset-0 bg-[#09090b] grid place-items-center text-gray-400">
                플랜 정보를 불러오는 중...
            </div>
        );
    }

    const isExpired = !!user?.is_pro_expired || user?.status === 'expired' || isResubscribe;
    const isPending = user?.status === 'pending';
    const expiredAt = user?.pro_expires_at ? new Date(user.pro_expires_at) : null;

    const select = (plan: BillingPlan) => {
        navigate(`/payment-request?${planToQuery(plan)}${isExpired ? '&resubscribe=1' : ''}`);
    };

    return (
        <div className="fixed inset-0 bg-[#09090b] flex flex-col items-center overflow-y-auto p-6 sm:p-8">
            <div className="w-full max-w-5xl">
                {isExpired && (
                    <div className="mb-6 rounded-2xl border-2 border-rose-500/40 bg-gradient-to-br from-rose-500/[0.12] via-amber-500/[0.05] to-slate-950/60 p-5 sm:p-6 shadow-[0_8px_40px_rgba(244,63,94,0.18)]">
                        <div className="flex items-start gap-3">
                            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-rose-500/20 text-rose-200">
                                <i className="fas fa-rotate-right" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <h2 className="text-lg sm:text-xl font-black text-rose-100">구독이 만료되었습니다. 재구독 신청을 진행하세요.</h2>
                                    <span className="inline-flex items-center rounded-full border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-[10px] font-black text-rose-100 uppercase tracking-wider">
                                        재구독
                                    </span>
                                </div>
                                <p className="mt-2 text-sm text-rose-100/75 leading-relaxed">
                                    기존 계정은 유지됩니다. 원하는 플랜을 선택하고 입금자명만 확인하면 승인 대기 단계로 넘어갑니다.
                                </p>
                                {expiredAt && (
                                    <p className="mt-1 text-xs text-rose-200/60 tabular-nums">
                                        만료일: {expiredAt.toLocaleDateString('ko-KR')} {expiredAt.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                <div className="mb-5 grid grid-cols-4 gap-2">
                    {FLOW_STEPS.map((step, index) => (
                        <div
                            key={step}
                            className={`rounded-xl border px-2 py-2 text-center text-[10px] font-bold ${
                                index === 1
                                    ? 'border-amber-400/40 bg-amber-500/15 text-amber-200'
                                    : index < 1
                                    ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200'
                                    : 'border-white/10 bg-white/[0.03] text-gray-500'
                            }`}
                        >
                            <div className="mb-1 text-[11px]">{index + 1}</div>
                            {step}
                        </div>
                    ))}
                </div>

                <div className="text-center mb-8">
                    <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight mb-4">
                        {isExpired ? '재구독 플랜 선택' : '플랜을 선택해 주세요'}
                    </h1>
                    <p className="text-gray-400 text-base sm:text-lg max-w-xl mx-auto">
                        {isExpired
                            ? '서비스 재개를 위해 다시 이용할 플랜을 선택하세요.'
                            : isPending
                            ? '계정 생성이 끝났습니다. 이제 이용할 플랜을 선택하면 됩니다.'
                            : '구독 신청을 진행할 플랜을 선택하세요.'}
                    </p>
                    {user && (
                        <p className="text-gray-600 text-xs mt-2">
                            로그인 계정: <span className="text-gray-400">{user.email}</span>
                        </p>
                    )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                    <PlanCard plan="pro" onSelect={select} badgeIcon="fa-crown" badgeText="기본" />
                    <PlanCard plan="pro_aibain" onSelect={select} badgeIcon="fa-robot" badgeText="추천" highlighted />
                    <PlanCard plan="premium" onSelect={select} badgeIcon="fa-gem" badgeText="평생 이용" />
                    <PlanCard plan="premium_aibain" onSelect={select} badgeIcon="fa-crown" badgeText="평생 + AI Brain" />
                </div>

                <div className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-gray-400 leading-relaxed">
                    <div className="flex items-start gap-3">
                        <i className="fas fa-circle-info text-amber-400 mt-1" />
                        <p>
                            플랜 선택 후 계좌번호와 입금 금액이 자동으로 표시됩니다. 입금자명은 가입 이름과 같게 입력하면 승인 확인이 빨라집니다.
                        </p>
                    </div>
                </div>

                <div className="mt-5 w-full max-w-md mx-auto">
                    <KakaoSupportLink />
                </div>

                <div className="mt-6 flex items-center justify-center gap-4 text-xs">
                    <button type="button" onClick={() => navigate('/')} className="text-gray-500 hover:text-white transition-colors">
                        <i className="fas fa-arrow-left mr-1" />처음으로
                    </button>
                    {user && (
                        <button
                            type="button"
                            onClick={() => {
                                localStorage.removeItem('auth_token');
                                sessionStorage.removeItem('auth_token');
                                localStorage.removeItem('auth_user');
                                sessionStorage.removeItem('auth_user');
                                navigate('/login', { replace: true });
                            }}
                            className="text-gray-500 hover:text-red-400 transition-colors"
                        >
                            <i className="fas fa-sign-out-alt mr-1" />로그아웃
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

interface PlanCardProps {
    plan: BillingPlan;
    onSelect: (plan: BillingPlan) => void;
    badgeIcon: string;
    badgeText: string;
    highlighted?: boolean;
}

const COLOR_STYLES: Record<BillingPlan, {
    border: string;
    ring: string;
    hoverRing: string;
    badgeBg: string;
    badgeText: string;
    accent: string;
    btn: string;
    btnText: string;
    bgOverlay: string;
}> = {
    pro: {
        border: 'border-amber-500/30',
        ring: 'ring-amber-500/20',
        hoverRing: 'hover:ring-amber-500/50',
        badgeBg: 'bg-amber-500/10',
        badgeText: 'text-amber-400',
        accent: 'text-amber-400',
        btn: 'from-amber-500 to-orange-500',
        btnText: 'text-black',
        bgOverlay: 'from-amber-500/10 to-transparent',
    },
    pro_aibain: {
        border: 'border-cyan-500/40',
        ring: 'ring-cyan-500/25',
        hoverRing: 'hover:ring-cyan-500/60',
        badgeBg: 'bg-cyan-500/10',
        badgeText: 'text-cyan-300',
        accent: 'text-cyan-300',
        btn: 'from-cyan-500 to-sky-500',
        btnText: 'text-black',
        bgOverlay: 'from-cyan-500/10 to-transparent',
    },
    premium: {
        border: 'border-purple-500/30',
        ring: 'ring-purple-500/20',
        hoverRing: 'hover:ring-purple-500/50',
        badgeBg: 'bg-purple-500/10',
        badgeText: 'text-purple-400',
        accent: 'text-purple-400',
        btn: 'from-purple-500 to-fuchsia-500',
        btnText: 'text-white',
        bgOverlay: 'from-purple-500/10 to-transparent',
    },
    premium_aibain: {
        border: 'border-fuchsia-500/40',
        ring: 'ring-fuchsia-500/25',
        hoverRing: 'hover:ring-fuchsia-500/60',
        badgeBg: 'bg-fuchsia-500/10',
        badgeText: 'text-fuchsia-300',
        accent: 'text-fuchsia-300',
        btn: 'from-fuchsia-500 via-purple-500 to-cyan-500',
        btnText: 'text-white',
        bgOverlay: 'from-fuchsia-500/10 to-transparent',
    },
};

function PlanCard({ plan, onSelect, badgeIcon, badgeText, highlighted }: PlanCardProps) {
    const meta = PLAN_PAYMENT_META[plan];
    const c = COLOR_STYLES[plan];
    const priceMajor = meta.amountNumber.toLocaleString();
    const priceUnit = plan === 'premium' ? '원' : '원 / 30일';

    return (
        <button
            type="button"
            onClick={() => onSelect(plan)}
            className={`p-6 rounded-2xl border ${c.border} bg-[#1c1c1e] ring-1 ${c.ring} hover:ring-2 ${c.hoverRing} transition-all text-left relative overflow-hidden ${highlighted ? 'sm:scale-[1.02]' : ''}`}
        >
            <div className={`absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl ${c.bgOverlay} rounded-bl-full pointer-events-none`} />
            <div className={`inline-flex items-center gap-1 px-3 py-1 rounded-full ${c.badgeBg} ${c.badgeText} text-xs font-bold mb-3`}>
                <i className={`fas ${badgeIcon}`} /> {badgeText}
            </div>
            <h3 className="text-xl font-bold text-white mb-1">{meta.label}</h3>
            <div className="flex items-baseline gap-1 mb-1">
                <span className="text-3xl font-black text-white">{priceMajor}</span>
                <span className="text-gray-400">{priceUnit}</span>
            </div>
            {meta.includesAibain && meta.baseAmount && meta.aibainAmount ? (
                <p className={`${c.accent} text-[11px] font-semibold mb-5 leading-tight`}>
                    {meta.baseAmount} + <strong className="text-white">{meta.aibainAmount}</strong>
                </p>
            ) : (
                <p className={`${c.accent} text-xs font-semibold mb-5`}>{meta.description}</p>
            )}
            <ul className="space-y-2 mb-6 text-sm text-gray-300">
                {meta.features.map((feature, i) => (
                    <li key={i} className="flex items-start gap-2">
                        <i className={`fas fa-check ${c.accent} text-xs mt-1`} />
                        {feature}
                    </li>
                ))}
            </ul>
            <div className={`w-full py-3 rounded-xl bg-gradient-to-r ${c.btn} ${c.btnText} font-bold text-center text-sm`}>
                {meta.label} 선택
            </div>
        </button>
    );
}
