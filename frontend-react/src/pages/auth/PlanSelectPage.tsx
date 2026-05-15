import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { PLAN_PAYMENT_META, planToQuery, type BillingPlan } from '@/lib/billingInfo';

/**
 * 플랜 선택 페이지 — 신규 가입자 및 만료 재구독 공용.
 *
 * 진입 경로:
 *   - /signup 완료 직후
 *   - /pending-approval 의 "플랜 신청" 버튼
 *   - ApprovedGuard: is_pro_expired=true 인 유저 (만료 재구독)
 *   - /dashboard 상단 재구독 배너
 *
 * 선택 시 /payment-request?plan=X 로 이동.
 * 로그인 안 된 상태로 들어오면 /signup 으로 유도.
 */
export default function PlanSelectPage() {
    const { user, token, loading } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const isResubscribe = searchParams.get('resubscribe') === '1' || searchParams.get('from') === 'expired';

    // 가드 — loading 끝난 뒤에만 판정 (AuthContext 초기화 중 user=null 찰나 보호)
    useEffect(() => {
        if (loading) return;
        // 비인증 유저는 /signup 으로
        if (!user || !token) {
            navigate('/signup', { replace: true });
            return;
        }
        // admin 은 대시보드 (플랜 UI 노출 방지)
        if (user.role === 'admin') {
            navigate('/dashboard', { replace: true });
            return;
        }
        // 활성 구독 유저는 대시보드
        const isActive = (user.tier === 'pro' || user.tier === 'premium')
            && user.status === 'approved'
            && !user.is_pro_expired;
        if (isActive) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, token, loading, navigate]);

    const isExpired = !!user?.is_pro_expired || user?.status === 'expired' || isResubscribe;
    const isPending = user?.status === 'pending';
    // 만료된 user 의 expired_at 표시용
    const expiredAt = user?.pro_expires_at ? new Date(user.pro_expires_at) : null;

    const select = (plan: BillingPlan) => {
        navigate(`/payment-request?${planToQuery(plan)}`);
    };

    return (
        <div className="fixed inset-0 bg-[#09090b] flex flex-col items-center overflow-y-auto p-6 sm:p-8">
            {/* 만료 = 계정 정지 안내 (강조 배너) */}
            {isExpired && (
                <div className="w-full max-w-4xl mt-4 mb-6 rounded-2xl border-2 border-rose-500/40 bg-gradient-to-br from-rose-500/[0.12] via-amber-500/[0.05] to-slate-950/60 p-5 sm:p-6 backdrop-blur-md shadow-[0_8px_40px_rgba(244,63,94,0.18)]">
                    <div className="flex items-start gap-3">
                        <div className="grid h-10 w-10 sm:h-12 sm:w-12 shrink-0 place-items-center rounded-full bg-rose-500/20 text-rose-300 text-xl">
                            ⚠️
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                                <h2 className="text-lg sm:text-xl font-black text-rose-200">
                                    Pro 구독 만료 — 계정이 정지되었습니다
                                </h2>
                                <span className="inline-flex items-center rounded-full border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-[10px] font-black text-rose-200 uppercase tracking-wider">
                                    EXPIRED
                                </span>
                            </div>
                            <p className="mt-2 text-sm text-rose-100/80 leading-relaxed">
                                구독이 만료되어 데이터 페이지 접근이 차단되었습니다. 아래 플랜을 다시 선택해 재구독 신청해 주세요.
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

            <div className="text-center mt-2 sm:mt-6 mb-10">
                <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight mb-4">
                    {isExpired ? '재구독 플랜' : '플랜을 선택해 주세요'}
                </h1>
                <p className="text-gray-400 text-base sm:text-lg max-w-md mx-auto">
                    {isExpired
                        ? '서비스 재개를 위해 플랜을 다시 신청해 주세요.'
                        : isPending
                        ? '계정이 생성되었습니다. 구독 플랜을 선택하세요.'
                        : '원하시는 구독 플랜을 선택하세요.'}
                </p>
                {user && (
                    <p className="text-gray-600 text-xs mt-2">
                        로그인: <span className="text-gray-400">{user.email}</span>
                    </p>
                )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 max-w-4xl w-full">
                <PlanCard plan="pro" onSelect={select} badgeIcon="fa-crown" badgeText="기본" />
                <PlanCard plan="pro_aibain" onSelect={select} badgeIcon="fa-robot" badgeText="추천" highlighted />
                <PlanCard plan="premium" onSelect={select} badgeIcon="fa-gem" badgeText="평생 이용" />
                <PlanCard plan="premium_aibain" onSelect={select} badgeIcon="fa-crown" badgeText="평생 + AI Bain" />
            </div>

            <p className="text-gray-500 text-xs mt-8 text-center max-w-md">
                선택 후 국민은행 계좌로 입금 → 관리자 확인 후 활성화 (최대 24시간).<br />
                Ultra Pro 는 24개월 이상 이용 시 Pro 대비 절반 이하 비용입니다.
            </p>

            <div className="mt-5 w-full max-w-md">
                <KakaoSupportLink />
            </div>

            <div className="mt-6 flex items-center gap-4 text-xs">
                <a href="/" className="text-gray-500 hover:text-white transition-colors">
                    <i className="fas fa-arrow-left mr-1" />홈으로
                </a>
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
    );
}

// ── PlanCard component ─────────────────────────────────────────────────────

interface PlanCardProps {
    plan: BillingPlan;
    onSelect: (plan: BillingPlan) => void;
    badgeIcon: string;
    badgeText: string;
    highlighted?: boolean;
}

const COLOR_STYLES: Record<NonNullable<PlanCardProps['plan']>, {
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

    // 가격 표시 분리: AI Bain 포함 시 베이스/AI Bain 분리 표기
    const priceMajor = meta.amountNumber.toLocaleString();
    const priceUnit = plan === 'premium' ? '원' : '원/30일';

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
                <p className={`${c.accent}/70 text-xs font-semibold mb-5`}>{meta.description}</p>
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
                {meta.label} 선택 →
            </div>
        </button>
    );
}
