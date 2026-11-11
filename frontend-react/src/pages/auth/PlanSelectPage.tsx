import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { hasActiveBaseSubscription, isBaseSubscriptionExpired, subscriptionFunnelTarget } from '@/lib/auth';
import SubscriptionFlow from '@/components/subscription/SubscriptionFlow';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { useSeo } from '@/lib/seo';
import {
    PLAN_PAYMENT_META,
    AIBAIN_ADDON_META,
    resolveBillingPlan,
    planFromQuery,
    planToQuery,
    type BillingPlan,
} from '@/lib/billingInfo';


export default function PlanSelectPage() {
    useSeo({ title: '플랜 선택 | MarketFlow', noindex: true });
    const { user, token, loading, logout, refreshUser } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const isResubscribe = searchParams.get('resubscribe') === '1' || searchParams.get('from') === 'expired';
    const allowChange = searchParams.get('change') === '1';
    const preferredPlan = resolveBillingPlan(planFromQuery(searchParams.get('plan'), searchParams.get('aibain')), user);
    const preferredQuery = preferredPlan ? planToQuery(preferredPlan) : '';
    const signupPath = preferredQuery ? `/signup?${preferredQuery}` : '/signup';
    const [now, setNow] = useState(Date.now);

    // 이 페이지에 머무는 동안 관리자가 tier 를 직접 부여하면 (CLAUDE.md §12-A) stale user 로
    // 계속 플랜 선택에 갇힌다 → 마운트 + 창 포커스 시 /api/auth/me 재조회로 즉시 반영.
    // (refreshUser 는 AuthContext 재렌더마다 새 참조라 deps 에 넣으면 무한 루프 — 마운트 1회 고정)
    useEffect(() => {
        refreshUser().catch(() => {});
        const tick = () => { if (document.visibilityState !== 'hidden') setNow(Date.now()); };
        const onFocus = () => { tick(); refreshUser().catch(() => {}); };
        const timer = window.setInterval(tick, 60_000);
        window.addEventListener('focus', onFocus);
        return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); };
    }, []);

    useEffect(() => {
        if (loading) return;
        if (!user || !token) {
            navigate(signupPath, { replace: true });
            return;
        }
        if (user.role === 'admin') {
            navigate('/dashboard', { replace: true });
            return;
        }
        const isActive = hasActiveBaseSubscription(user, now);
        if (isActive && !allowChange && !preferredPlan) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, token, loading, navigate, allowChange, signupPath, preferredPlan, now]);

    if (loading) {
        return (
            <div className="grid min-h-screen min-h-[100dvh] place-items-center bg-[#09090b] text-gray-400">
                플랜 정보를 불러오는 중...
            </div>
        );
    }

    const isExpired = isBaseSubscriptionExpired(user, now) || isResubscribe;
    const isPending = user?.status === 'pending';
    const hasActiveBase = hasActiveBaseSubscription(user, now);
    const isUpgrade = allowChange && hasActiveBase;
    const effectiveExpiry = user?.pro_effective_expires_at || user?.pro_expires_at;
    const expiredAt = effectiveExpiry ? new Date(effectiveExpiry) : null;

    const select = (plan: BillingPlan) => {
        navigate(`/payment-request?${planToQuery(plan)}${isExpired ? '&resubscribe=1' : ''}`);
    };

    return <SubscriptionFlow step={1} wide
        title={isExpired ? '재구독 플랜 선택' : isUpgrade ? (user?.tier === 'premium' ? '플랜 · AI Brain 관리' : '등급 업그레이드') : '플랜을 선택해 주세요'}
        intro={isExpired ? '기존 계정 그대로 다시 시작하세요. 플랜을 고르면 입금 안내로 이동합니다.'
            : isUpgrade ? '기존 등급은 유지됩니다. 필요한 서비스만 추가하거나 이용기간을 연장하세요.'
            : isPending ? '가입이 완료되었습니다. 이용할 서비스를 고르고 다음 단계로 이동하세요.' : '이번에 이용할 서비스를 선택하세요.'}>
        <section className="subscription-status-box" aria-label="현재 구독 상태">
            <strong>{isExpired ? '현재 상태: 구독 만료' : hasActiveBase ? `현재 이용: ${user?.tier === 'premium' ? 'Ultra Pro' : 'Pro'}` : '현재 상태: 구독 전'}</strong>
            <p>{isExpired ? '계정과 이용 기록은 유지됩니다.' : hasActiveBase
                ? user?.is_aibain_active ? 'AI 브레인 이용 중 · 50,000원으로 AI 브레인과 제갈공명을 30일 함께 연장할 수 있습니다.' : 'AI 브레인 추가 구독은 50,000원 / 30일이며, 제갈공명이 포함됩니다.'
                : 'PRO만 이용하거나, AI 브레인·제갈공명을 함께 선택할 수 있습니다.'}</p>
            {isExpired && expiredAt && !Number.isNaN(expiredAt.getTime()) && <p>만료일 {expiredAt.toLocaleDateString('ko-KR')}</p>}
        </section>
        <div className="subscription-plan-grid">
            {(!hasActiveBase || user?.tier === 'pro') && <>
                <PlanCard plan="pro" onSelect={select} hasActiveBase={hasActiveBase} currentTier={user?.tier}
                    isPrevious={isExpired && user?.tier === 'pro'} isPreferred={preferredPlan === 'pro'} />
                <PlanCard plan="pro_aibain" onSelect={select} hasActiveBase={hasActiveBase} currentTier={user?.tier}
                    isPreferred={preferredPlan === 'pro_aibain'} isAiBrainActive={!!user?.is_aibain_active} />
            </>}
            {hasActiveBase && user?.tier === 'premium' && <>
                <PlanCard plan="premium" onSelect={select} hasActiveBase currentTier={user.tier} />
                <PlanCard plan="premium_aibain" onSelect={select} hasActiveBase currentTier={user.tier}
                    isPreferred={preferredPlan === 'premium_aibain'} isAiBrainActive={!!user.is_aibain_active} />
            </>}
        </div>
        <aside className="subscription-note">
            <strong>AI를 이용하는 동안 PRO 기간은 줄어들지 않아요.</strong>
            <p>AI 브레인·제갈공명을 30일 함께 이용합니다. AI 이용 중에도 PRO 전체 서비스를 계속 이용하며, 남은 PRO 기간은 보존되어 AI 종료 후 다시 시작됩니다. Ultra PRO 평생 이용권은 그대로 유지됩니다.</p>
            {!hasActiveBase && <p>PRO + AI 브레인·제갈공명 결합 플랜은 100,000원입니다. PRO 50,000원 + AI·제갈공명 50,000원이며, 승인 후 AI 30일을 이용하는 동안 PRO 30일은 보관됩니다.</p>}
        </aside>
        {hasActiveBase && user?.tier === 'pro' && <button className="subscription-button-secondary w-full" onClick={() => navigate('/payment-request?plan=pro&renew=1')}>AI 추가 없이 PRO 30일 연장 · 50,000원</button>}
        {user?.tier !== 'premium' && <details className="subscription-details" open={preferredPlan === 'premium' || preferredPlan === 'premium_aibain' ? true : undefined}>
            <summary>Ultra Pro 평생 이용 플랜 보기</summary>
            <div className="subscription-plan-grid"><PlanCard plan="premium" onSelect={select} isPreferred={preferredPlan === 'premium'} />
                <PlanCard plan="premium_aibain" onSelect={select} isPreferred={preferredPlan === 'premium_aibain'} /></div>
        </details>}
        <p className="subscription-help">플랜을 눌러도 결제되지 않습니다. 다음 화면에서 금액과 입금 계좌를 확인합니다.</p>
        <KakaoSupportLink />
        <footer className="subscription-flow-footer">
            {(!user || !subscriptionFunnelTarget(user)) && <button onClick={() => navigate('/dashboard')}>이용 화면으로 돌아가기</button>}
            {user && <button onClick={() => { logout(); navigate('/login', { replace: true }); }}>로그아웃</button>}
        </footer>
    </SubscriptionFlow>;
}

function PlanCard({ plan, onSelect, isPrevious, isPreferred, hasActiveBase, currentTier, isAiBrainActive }: {
    plan: BillingPlan; onSelect: (plan: BillingPlan) => void; isPrevious?: boolean; isPreferred?: boolean;
    hasActiveBase?: boolean; currentTier?: string | null; isAiBrainActive?: boolean;
}) {
    const meta = PLAN_PAYMENT_META[plan];
    const sameBase = !!hasActiveBase && meta.tier === currentTier;
    const addon = sameBase && meta.includesAibain;
    const current = sameBase && !meta.includesAibain;
    const amount = addon ? AIBAIN_ADDON_META.amount : meta.amount;
    const title = addon ? AIBAIN_ADDON_META.label : meta.label;
    const features = meta.includesAibain
        ? [...(addon ? [] : [meta.tier === 'premium' ? 'Ultra PRO 평생 이용 포함' : 'PRO 전체 서비스 포함']), 'AI 브레인 종목 분석·검출', '제갈공명 뉴스·공시 검증']
        : ['국내·해외 주식·코인 정보', '커뮤니티와 기본 분석 서비스'];
    return <button type="button" className="subscription-plan" disabled={current} onClick={() => onSelect(plan)}
        aria-pressed={isPreferred || undefined} aria-current={current ? 'true' : undefined} data-featured={meta.includesAibain}>
        <span className="subscription-plan-badge">{current ? '현재 구독' : addon ? '기존 회원 추가 이용' : meta.includesAibain ? '기본 + AI 분석' : '기본 서비스'}
            {isPrevious && <em>이전 플랜</em>}{isPreferred && <em>선택한 플랜</em>}</span>
        <div className="subscription-plan-heading"><h3>{title}</h3>
            {!current && <span className="subscription-plan-price"><span className="subscription-price-label">이번 입금</span><span className="subscription-price">{amount}</span></span>}
        </div>
        {current ? <p className="subscription-plan-summary">{meta.tier === 'premium' ? '평생 이용권을 보유하고 있습니다.' : '현재 PRO 이용권을 유지합니다.'}</p> : <>
            <p className="subscription-plan-summary">{addon ? 'AI 브레인 + 제갈공명 · 30일'
                : meta.includesAibain ? meta.tier === 'premium' ? '평생 이용 + AI·제갈공명 30일' : 'AI·제갈공명 30일 + 보관되는 PRO 30일'
                : meta.tier === 'premium' ? '한 번 결제 · 평생 이용' : '승인 후 30일'}</p>
            <ul>{features.map(feature => <li key={feature}>{feature}</li>)}</ul>
        </>}
        <span className="subscription-plan-cta">{current ? '현재 이용 중' : addon ? `AI Brain·제갈공명 50,000원으로 ${isAiBrainActive ? '연장' : '추가'}`
            : `${meta.label} ${isPrevious ? '다시 시작하기' : '선택'}`}</span>
    </button>;
}
