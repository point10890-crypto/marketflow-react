import { hasActiveBaseSubscription, hasActiveKongmingSubscription, isBaseSubscriptionExpired, subscriptionExpiryTime, subscriptionFunnelTarget, type AuthUserData } from './auth';
import { aiBundleOffer, PLAN_PAYMENT_META, planToQuery, type BillingPlan } from './billingInfo';

export const SUBSCRIPTION_REMINDER_MS = 30 * 60 * 1000;
export type SubscriptionJourney = {
    kind: 'subscribe' | 'base-expired' | 'aibain-expired' | 'kongming-expired' | 'expiring';
    title: string; message: string; cta: string; destination: string;
    plan: BillingPlan; payment: string; fingerprint: string;
    expiresAt?: string; amount?: string;
};

/** Paid access remains usable. D-1 is the inclusive final 24 hours, never a rounded local date. */
export function subscriptionExpiryReminder(user: AuthUserData | null, now = Date.now()): SubscriptionJourney | null {
    if (!user || user.role === 'admin' || !['approved', 'expired'].includes(user.status)) return null;
    const due: { service: string; at: number; base: boolean }[] = [];
    const baseExpiry = subscriptionExpiryTime(user.pro_effective_expires_at || user.pro_expires_at);
    const aiExpiry = subscriptionExpiryTime(user.aibain_expires_at);
    const kongmingExpiry = subscriptionExpiryTime(user.kongming_expires_at);
    const add = (service: string, at: number, base = false) => {
        if (at > now && at - now <= 86_400_000) due.push({ service, at, base });
    };
    if (hasActiveBaseSubscription(user, now) && user.tier === 'pro' && !user.is_pro_paused) add('PRO', baseExpiry, true);
    if (user.is_aibain_active && aiExpiry > now) {
        add(hasActiveKongmingSubscription(user, now) && aiExpiry === kongmingExpiry ? 'AI 브레인 + 제갈공명' : 'AI 브레인', aiExpiry);
    }
    if (hasActiveKongmingSubscription(user, now)) add('제갈공명', kongmingExpiry);
    const first = due.sort((a, b) => a.at - b.at)[0];
    if (!first) return null;
    const offer = first.base ? { plan: 'pro' as const, amount: PLAN_PAYMENT_META.pro.amount, payment: '/payment-request?plan=pro&renew=1' } : aiBundleOffer(user, now);
    const expiresAt = new Date(first.at).toISOString();
    return {
        kind: 'expiring', title: `${first.service} 구독 만료까지 하루 이내로 남았습니다`,
        message: `만료 전까지 계속 이용할 수 있습니다. ${offer.amount} 재구독 신청 후 관리자 승인 시 이용기간을 연장합니다.`,
        cta: '재구독 신청하기', destination: offer.payment, plan: offer.plan, payment: offer.payment,
        expiresAt, amount: offer.amount, fingerprint: `${user.id}:expiring:${first.service}:${expiresAt}:${offer.plan}:${offer.amount}`,
    };
}

export function subscriptionJourney(user: AuthUserData | null, now = Date.now()): SubscriptionJourney | null {
    if (!user || user.role === 'admin' || ['unknown', 'suspended', 'rejected'].includes(user.status)) return null;
    const upcoming = subscriptionExpiryReminder(user, now);
    if (upcoming) return upcoming;
    if (hasActiveKongmingSubscription(user, now)) return null;
    const expired = isBaseSubscriptionExpired(user, now);
    const activeBase = hasActiveBaseSubscription(user, now);
    const kongmingExpiry = subscriptionExpiryTime(user.kongming_expires_at);
    if (!expired && ['approved', 'expired'].includes(user.status) && Number.isFinite(kongmingExpiry) && kongmingExpiry <= now) {
        const { plan, label, amount, payment } = aiBundleOffer(user);
        return {
            kind: 'kongming-expired',
            title: `${label}이 만료되었습니다`,
            message: `${label} ${amount} 신청으로 서비스를 다시 이용할 수 있습니다.`,
            cta: '재구독 신청하기',
            destination: payment,
            plan, payment,
            fingerprint: `${user.id}:kongming-expired:${user.kongming_expires_at}`,
        };
    }
    const addonExpiry = subscriptionExpiryTime(user.aibain_expires_at);
    const aibainExpired = activeBase && (!!user.is_aibain_expired || Number.isFinite(addonExpiry) && addonExpiry <= now);
    if (!expired && !aibainExpired && !subscriptionFunnelTarget(user, now)) return null;
    const preferred = !expired && (user.tier === 'premium' || (!user.tier && user.requested_tier === 'premium'));
    const plan: BillingPlan = aibainExpired ? (preferred ? 'premium_aibain' : 'pro_aibain') : preferred ? 'premium' : 'pro';
    const kind = aibainExpired ? 'aibain-expired' : expired ? 'base-expired' : 'subscribe';
    return {
        kind, plan,
        title: aibainExpired ? 'AI Brain·제갈공명이 만료되었습니다' : expired ? '구독이 만료되었습니다' : '아직 이용 중인 구독이 없습니다',
        message: aibainExpired ? `${preferred ? 'Ultra PRO는 계속 이용합니다.' : 'PRO 잔여기간이 다시 차감됩니다.'} AI Brain·제갈공명은 5만 원으로 30일 재구독할 수 있습니다.` : expired ? '계정은 유지됩니다. PRO 5만 원 또는 PRO+AI Brain·제갈공명 10만 원으로 다시 신청하세요.' : '플랜 선택 → 입금 후 신청 → 관리자 승인 후 이용',
        cta: aibainExpired ? 'AI·제갈공명 재구독하기' : expired ? '재구독 신청하기' : '구독 신청하기',
        destination: aibainExpired ? `/payment-request?${planToQuery(plan)}` : expired ? '/plan-select?resubscribe=1&from=expired' : '/plan-select',
        payment: `/payment-request?${planToQuery(plan)}${expired ? '&resubscribe=1' : ''}`,
        fingerprint: `${user.id}:${kind}:${aibainExpired ? user.aibain_expires_at || '' : expired ? user.pro_expires_at || '' : user.requested_tier || ''}`,
    };
}

export function reminderDue(lastDismissal: string | null, now: number): boolean {
    if (!lastDismissal) return true;
    const at = Number(lastDismissal);
    return !Number.isFinite(at) || now < at || now - at >= SUBSCRIPTION_REMINDER_MS;
}
