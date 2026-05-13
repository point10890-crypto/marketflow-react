import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import { BANK_ACCOUNT, PLAN_PAYMENT_META, normalizeBillingPlan, type BillingPlanTier } from '@/lib/billingInfo';

/**
 * 입금 안내 + 승인 신청 페이지.
 *
 * 진입: /payment-request?plan=pro|premium
 *
 * 동작:
 *   1. 선택 플랜 + 계좌 정보 + 금액 자동 표시
 *   2. 입금자명 입력 (가입 이름 프리필)
 *   3. "승인 신청" 클릭 → subscriptionAPI.requestUpgrade
 *   4. 성공 → /pending-approval 로 이동
 *   5. 이미 같은 플랜 pending 요청 존재 시 바로 /pending-approval
 */
export default function PaymentRequestPage() {
    const { user, token, loading } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const rawPlan = searchParams.get('plan');
    const plan: BillingPlanTier | null = normalizeBillingPlan(rawPlan);

    const [depositorName, setDepositorName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');

    // 인증/플랜 가드 + 활성 유저 차단 — loading 끝난 뒤에만 판정 (초기화 찰나 보호)
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
        if (isActive) {
            navigate('/dashboard', { replace: true });
            return;
        }
        if (!plan) {
            navigate('/plan-select', { replace: true });
            return;
        }
    }, [user, token, plan, loading, navigate]);

    // 입금자명 프리필 = 가입 이름
    useEffect(() => {
        if (user?.name && !depositorName) {
            setDepositorName(user.name);
        }
    }, [user?.name]); // eslint-disable-line react-hooks/exhaustive-deps

    if (!user || !token || !plan) {
        return null;
    }

    const meta = PLAN_PAYMENT_META[plan];

    const colorMap = {
        amber:  { ring: 'ring-amber-500/30',  bg: 'bg-amber-500/10',  text: 'text-amber-400',  btn: 'from-amber-500 to-orange-500', btnText: 'text-black' },
        purple: { ring: 'ring-purple-500/30', bg: 'bg-purple-500/10', text: 'text-purple-400', btn: 'from-purple-500 to-fuchsia-500', btnText: 'text-white' },
    }[meta.color as 'amber' | 'purple'];

    const handleSubmit = async () => {
        setError('');
        if (!depositorName.trim()) {
            setError('입금자명을 입력해 주세요.');
            return;
        }
        setSubmitting(true);
        try {
            await subscriptionAPI.requestUpgrade(plan, token, depositorName.trim());
            navigate('/pending-approval', { replace: true });
        } catch (err: any) {
            const msg = err?.message || '';
            // 이미 pending 요청이 있는 경우도 성공으로 간주 → 승인 대기 페이지로
            if (msg.toLowerCase().includes('pending')) {
                navigate('/pending-approval', { replace: true });
                return;
            }
            setError('승인 신청 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.');
            setSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-[#09090b] flex flex-col items-center overflow-y-auto p-4 sm:p-8">
            <div className="w-full max-w-md mt-4 sm:mt-12">
                {/* Header */}
                <div className="text-center mb-6">
                    <div className={`inline-flex items-center gap-2 px-4 py-1.5 rounded-full ${colorMap.bg} ${colorMap.text} text-xs font-bold mb-3`}>
                        <i className={plan === 'premium' ? 'fas fa-gem' : 'fas fa-crown'} />
                        선택한 플랜: {meta.label}
                    </div>
                    <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight mb-2">
                        입금 안내
                    </h1>
                    <p className="text-gray-500 text-sm">
                        아래 계좌로 <span className={`font-bold ${colorMap.text}`}>{meta.amount}</span> 입금 후<br />
                        승인 신청 버튼을 눌러주세요.
                    </p>
                </div>

                {/* 계좌 박스 */}
                <div className={`p-5 rounded-2xl bg-[#1c1c1e] ring-1 ${colorMap.ring} mb-4 space-y-3`}>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded-lg bg-white/[0.03]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                            <p className="text-white font-bold mt-0.5">{BANK_ACCOUNT.bank}</p>
                        </div>
                        <div className="p-3 rounded-lg bg-white/[0.03]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                            <p className="text-white font-bold mt-0.5">{BANK_ACCOUNT.holder}</p>
                        </div>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.03]">
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                            <button
                                type="button"
                                onClick={() => {
                                    navigator.clipboard?.writeText(BANK_ACCOUNT.account.replace(/-/g, ''));
                                }}
                                className="text-[10px] text-gray-400 hover:text-white"
                            >
                                <i className="fas fa-copy mr-1" />복사
                            </button>
                        </div>
                        <p className="text-white font-bold mt-0.5 font-mono text-lg tracking-wider">{BANK_ACCOUNT.account}</p>
                    </div>
                    <div className={`p-3 rounded-lg ${colorMap.bg}`}>
                        <span className="text-[10px] text-gray-500 uppercase tracking-wider">입금 금액</span>
                        <div className="flex items-baseline justify-between mt-0.5">
                            <p className={`font-black text-2xl ${colorMap.text}`}>{meta.amount}</p>
                            <span className="text-xs text-gray-500">{meta.period}</span>
                        </div>
                    </div>
                </div>

                {/* 입금자명 */}
                <div className="p-5 rounded-2xl bg-[#1c1c1e] border border-white/10 mb-4">
                    <label className="block text-xs font-medium text-gray-400 mb-2">입금자명 *</label>
                    <input
                        type="text"
                        value={depositorName}
                        onChange={(e) => setDepositorName(e.target.value)}
                        placeholder="입금자명 (가입 이름과 동일)"
                        className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff]"
                    />
                    <p className="text-[11px] text-gray-500 mt-2">
                        <i className="fas fa-info-circle mr-1" />
                        입금자명이 가입 이름과 다르면 관리자 확인이 지연될 수 있습니다.
                    </p>
                </div>

                {error && (
                    <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm mb-4">
                        {error}
                    </div>
                )}

                {/* 승인 신청 버튼 */}
                <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={submitting || !depositorName.trim()}
                    className={`w-full py-4 rounded-xl bg-gradient-to-r ${colorMap.btn} ${colorMap.btnText} font-bold text-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2`}
                >
                    {submitting ? (
                        <><i className="fas fa-spinner fa-spin" />처리 중...</>
                    ) : (
                        <><i className="fas fa-paper-plane" />{meta.label} 승인 신청</>
                    )}
                </button>

                <button
                    type="button"
                    onClick={() => navigate('/plan-select')}
                    className="w-full mt-3 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 font-medium text-sm transition-all"
                >
                    다른 플랜 선택
                </button>

                {/* 카카오톡 문의 */}
                <a
                    href="https://open.kakao.com/o/sJVLbWUe"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-[#FEE500]/10 hover:bg-[#FEE500]/20 text-[#FEE500] font-bold text-sm transition-all border border-[#FEE500]/20"
                >
                    <i className="fas fa-comment" />카카오톡 문의
                </a>

                <p className="text-gray-600 text-[11px] text-center mt-4">
                    승인 신청 후 관리자 확인까지 최대 24시간 소요됩니다.
                </p>
            </div>
        </div>
    );
}
