import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import { hasPendingSubscription } from '@/lib/subscriptionStatus';
import { PLAN_PAYMENT_META, AIBAIN_ADDON_META, AI_BUNDLE_CONVERSION, resolveBillingPlan, planFromQuery, planToQuery, type BillingPlan } from '@/lib/billingInfo';
import SubscriptionFlow, { BankTransferDetails } from '@/components/subscription/SubscriptionFlow';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { hasActiveBaseSubscription } from '@/lib/auth';
import { useSeo } from '@/lib/seo';

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
    useSeo({ title: '결제 안내 | MarketFlow', noindex: true });
    const { user, token, loading, refreshUser } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const rawPlan = searchParams.get('plan');
    const isConversion = rawPlan === AI_BUNDLE_CONVERSION.plan;
    const rawAibain = searchParams.get('aibain');
    // renew=1: 활성 Pro 의 만료 전 갱신 (RenewalBanner 경로) — 백엔드 early_renewal 접수
    const isRenewal = searchParams.get('renew') === '1';
    const plan: BillingPlan | null = resolveBillingPlan(planFromQuery(rawPlan, rawAibain), user);
    const selectedMeta = plan ? PLAN_PAYMENT_META[plan] : null;
    const isKongmingPlan = plan === 'aibain_kongming';
    const selectedQuery = plan ? planToQuery(plan) : '';

    const [depositorName, setDepositorName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [checkResult, setCheckResult] = useState<{
        identity: string; state: 'ready' | 'error';
    } | null>(null);
    const [checkAttempt, setCheckAttempt] = useState(0);
    const userId = user?.id;
    const checkIdentity = JSON.stringify([token, userId, isConversion, checkAttempt]);
    const checked = !loading && checkResult?.identity === checkIdentity ? checkResult : null;
    useEffect(() => {
        if (!token || loading || userId == null) return;
        let current = true;
        subscriptionAPI.getStatus(token).then(data => {
            if (!current) return;
            if (!Array.isArray(data?.requests)) throw new Error('Invalid subscription status');
            if (hasPendingSubscription(data)) {
                navigate('/pending-approval', { replace: true });
                return;
            }
            setCheckResult({ identity: checkIdentity, state: 'ready' });
        }).catch(() => { if (current) setCheckResult({ identity: checkIdentity, state: 'error' }); });
        return () => { current = false; };
    }, [token, userId, loading, navigate, checkIdentity, isConversion]);

    // 이 페이지에 머무는 동안 관리자가 tier 를 직접 부여하면 (CLAUDE.md §12-A) stale user 로
    // 400 루프에 빠진다 → 마운트 + 창 포커스 시 /api/auth/me 재조회, 아래 가드가 대시보드로 보낸다.
    // (refreshUser 는 AuthContext 재렌더마다 새 참조라 deps 에 넣으면 무한 루프 — 마운트 1회 고정)
    useEffect(() => {
        refreshUser().catch(() => {});
        const onFocus = () => {
            refreshUser().catch(() => {});
            if (isConversion) setCheckAttempt(v => v + 1);
        };
        window.addEventListener('focus', onFocus);
        return () => window.removeEventListener('focus', onFocus);
    }, [isConversion]);

    // 인증/플랜 가드 + 활성 유저 차단 — loading 끝난 뒤에만 판정 (초기화 찰나 보호)
    useEffect(() => {
        if (loading) return;
        if (!user || !token) {
            const signup = selectedQuery ? `/signup?${selectedQuery}` : '/signup';
            const target = isConversion ? '/login?next=' + encodeURIComponent(AI_BUNDLE_CONVERSION.payment) : signup;
            navigate(target, { replace: true });
            return;
        }
        if (user.role === 'admin') {
            navigate('/dashboard', { replace: true });
            return;
        }
        if (isConversion) return;
        if (!plan) {
            navigate('/plan-select', { replace: true });
            return;
        }
        const meta = PLAN_PAYMENT_META[plan];
        const isActive = hasActiveBaseSubscription(user);
        if (isActive && !isKongmingPlan) {
            const sameBaseTier = meta.tier === user.tier;
            const aiBrainAddonOnly = sameBaseTier && meta.includesAibain;
            const tierUpgrade = user.tier === 'pro' && meta.tier === 'premium';
            // 만료 전 갱신: 활성 Pro + 같은 tier + renew=1 (premium 은 무기한이라 해당 없음)
            const earlyRenewal = isRenewal && sameBaseTier && meta.tier === 'pro' && !meta.includesAibain;
            if (!aiBrainAddonOnly && !tierUpgrade && !earlyRenewal) {
                navigate('/dashboard', { replace: true });
            }
        }
    }, [user, token, plan, loading, navigate, isRenewal, isKongmingPlan, selectedQuery, isConversion]);

    // 입금자명 프리필 = 가입 이름
    useEffect(() => {
        if (user?.name && !depositorName) {
            setDepositorName(user.name);
        }
    }, [user?.name]);

    if (!user || !token || user.role === 'admin' || (!selectedMeta && !isConversion)) {
        return null;
    }

    if (checked?.state !== 'ready') {
        return <main className="min-h-[100dvh] bg-[#09090b] text-white grid place-items-center px-6">
            <div role="status" className="text-center space-y-4">
                <p>{checked?.state === 'error' ? '신청 내역을 확인하지 못했습니다. 중복 입금을 막기 위해 다시 확인해 주세요.' : '기존 구독 신청을 확인하고 있습니다…'}</p>
                {checked?.state === 'error' && <button className="rounded-xl bg-amber-400 px-5 py-3 font-bold text-black" onClick={() => setCheckAttempt(v => v + 1)}>다시 확인</button>}
            </div>
        </main>;
    }
    if (isConversion) {
        return <SubscriptionFlow step={2} title="구독 상품 변경 안내" intro="제갈공명 전환 상품의 신규 신청이 종료되었습니다.">
            <aside className="subscription-note">
                <p>기존 PRO·Ultra PRO 회원의 AI 브레인 추가 구독은 50,000원 / 30일이며, 제갈공명이 포함됩니다.</p>
                <p>PRO + AI 브레인·제갈공명 신규 결합 플랜은 100,000원입니다.</p>
                <p>AI 이용 중에도 PRO 전체 서비스를 계속 이용하며, PRO 잔여기간은 보존되어 AI 종료 후 다시 시작됩니다.</p>
            </aside>
            <div className="subscription-actions">
                <Link className="subscription-button-primary" to="/plan-select?change=1">현재 플랜 선택</Link>
            </div>
            <KakaoSupportLink label="구독 문의" />
        </SubscriptionFlow>;
    }

    const meta = selectedMeta;
    const isAiBrainAddonOnly = !isKongmingPlan && hasActiveBaseSubscription(user)
        && meta?.includesAibain
        && meta.tier === user.tier;
    const isEarlyRenewal = isRenewal
        && user.status === 'approved'
        && !user.is_pro_expired
        && meta?.tier === user.tier
        && meta?.tier === 'pro'
        && !meta.includesAibain;
    const displayLabel = isAiBrainAddonOnly ? AIBAIN_ADDON_META.label
        : isEarlyRenewal ? 'Pro 갱신 (만료 전)' : meta?.label;
    const displayAmount = isAiBrainAddonOnly ? AIBAIN_ADDON_META.amount : meta?.amount;
    const displayPeriod = isAiBrainAddonOnly ? 'AI Brain·제갈공명 30일 · 기존 이용 중이면 만료일부터 연장'
        : isEarlyRenewal || (isKongmingPlan && user.is_kongming_active) ? '승인 시 기존 만료일부터 +30일' : meta?.period;

    const handleSubmit = async () => {
        if (submitting) return;
        setError('');
        if (!depositorName.trim()) {
            setError('입금자명을 입력해 주세요.');
            return;
        }
        setSubmitting(true);
        try {
            if (isKongmingPlan) {
                await subscriptionAPI.requestKongming(token, depositorName.trim());
            } else if (meta) {
                await subscriptionAPI.requestUpgrade(meta.tier, token, depositorName.trim(), meta.includesAibain, isAiBrainAddonOnly ? AIBAIN_ADDON_META.amountNumber : meta.amountNumber);
            }
            navigate('/pending-approval', { replace: true });
        } catch (err: any) {
            const msg = err?.message || '';
            // 이미 pending 요청이 있는 경우도 성공으로 간주 → 승인 대기 페이지로
            if (msg.toLowerCase().includes('pending')) {
                navigate('/pending-approval', { replace: true });
                return;
            }
            // "Already on pro tier" = 관리자가 이미 같은 tier 를 부여한 상태 (stale user) →
            // 최신 유저로 갱신하고 대시보드로. 400 에러 루프에 가두지 않는다.
            if (msg.toLowerCase().includes('already on')) {
                refreshUser().catch(() => {});
                navigate('/dashboard', { replace: true });
                return;
            }
            setError(msg || '승인 신청 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.');
            setSubmitting(false);
        }
    };

    return <SubscriptionFlow step={2} title="입금 안내" intro="금액을 확인해 직접 이체한 뒤, 입금자명으로 승인 신청을 마쳐 주세요.">
        <section className="subscription-order" aria-label="이번 신청 내용">
            <p>선택한 플랜: {displayLabel}</p>
            <div className="subscription-price">{displayAmount}</div>
            <p>{displayPeriod}</p>
            {isAiBrainAddonOnly ? <p>기존 {user.tier === 'premium' ? 'Ultra Pro' : 'Pro'} 구독은 유지합니다.</p>
                : meta?.includesAibain && meta.baseAmount && <p>{meta.baseAmount} + {meta.aibainAmount}</p>}
        </section>
        <form onSubmit={event => { event.preventDefault(); void handleSubmit(); }}>
            <h2 className="text-base font-semibold mb-3">1. 아래 계좌로 입금해 주세요</h2>
            <BankTransferDetails />
            <label className="subscription-field">2. 입금자명을 확인해 주세요
                <input type="text" aria-label="입금자명" value={depositorName} disabled={submitting}
                    onChange={event => setDepositorName(event.target.value)} placeholder="이체할 때 사용한 입금자명"
                    autoComplete="name" required />
            </label>
            <p className="subscription-help">은행 이체 화면의 입금자명과 같게 입력하세요. 가입 이름과 달라도 실제 입금자명을 쓰면 됩니다.</p>
            {meta?.includesAibain && <aside className="subscription-note">
                <strong>승인 후 어떻게 이용하나요?</strong>
                <p>AI 브레인과 제갈공명을 30일 함께 이용합니다.
                    {meta.tier === 'premium' ? ' Ultra PRO 평생 이용권은 유지됩니다.' : ' AI 이용 중에도 PRO 전체 서비스를 계속 이용합니다. PRO 잔여기간이 줄어들지 않고, AI 이용이 끝나면 다시 시작됩니다.'}</p>
                {(isAiBrainAddonOnly && user.is_aibain_active) && <p>이용 중인 AI 기간이 남아 있으면 기존 만료일부터 30일을 더합니다.</p>}
            </aside>}
            {error && <p role="alert" className="subscription-error">{error}</p>}
            <div className="subscription-actions">
                <button type="submit" className="subscription-button-primary" disabled={submitting || !depositorName.trim()}>
                    {submitting ? '신청을 보내고 있습니다…' : '입금했어요 · 승인 신청'}
                </button>
                <p className="subscription-help !m-0 text-center">이 버튼으로 자동 결제되지는 않습니다. 관리자 입금 확인 후 이용할 수 있습니다.</p>
                <button type="button" className="subscription-button-secondary" disabled={submitting}
                    onClick={() => navigate(`/plan-select?${hasActiveBaseSubscription(user) ? 'change=1&' : ''}${selectedQuery}`)}>
                    다른 플랜 선택
                </button>
            </div>
        </form>
        <div className="mt-5"><KakaoSupportLink label="입금·신청 문의" /></div>
    </SubscriptionFlow>;
}
