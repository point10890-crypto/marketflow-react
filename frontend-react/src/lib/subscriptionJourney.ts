import { hasActiveBaseSubscription, hasActiveKongmingSubscription, isBaseSubscriptionExpired, subscriptionExpiryTime, subscriptionFunnelTarget, type AuthUserData } from './auth';
import { aiBundleOffer, planToQuery, type BillingPlan } from './billingInfo';

export const SUBSCRIPTION_REMINDER_MS = 30 * 60 * 1000;
export type SubscriptionJourney = {
    kind: 'subscribe' | 'base-expired' | 'aibain-expired' | 'kongming-expired';
    title: string; message: string; cta: string; destination: string;
    plan: BillingPlan; payment: string; fingerprint: string;
};

export function subscriptionJourney(user: AuthUserData | null, now = Date.now()): SubscriptionJourney | null {
    if (!user || user.role === 'admin' || ['unknown', 'suspended', 'rejected'].includes(user.status)) return null;
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
