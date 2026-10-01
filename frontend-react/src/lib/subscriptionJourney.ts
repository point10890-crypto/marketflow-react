import { subscriptionFunnelTarget, type AuthUserData } from './auth';
import { planToQuery, type BillingPlan } from './billingInfo';

export const SUBSCRIPTION_REMINDER_MS = 30 * 60 * 1000;
export type SubscriptionJourney = {
    kind: 'subscribe' | 'base-expired' | 'aibain-expired';
    title: string; message: string; cta: string; destination: string;
    plan: BillingPlan; payment: string; fingerprint: string;
};

export function subscriptionJourney(user: AuthUserData | null): SubscriptionJourney | null {
    if (!user || user.role === 'admin' || user.status === 'unknown') return null;
    const expired = !!user.is_pro_expired || user.status === 'expired';
    const activeBase = user.status === 'approved' && ['pro', 'premium'].includes(user.tier || '') && !expired;
    const aibainExpired = activeBase && !!user.is_aibain_expired;
    if (!expired && !aibainExpired && !subscriptionFunnelTarget(user)) return null;
    const preferred = user.tier === 'premium' || (!user.tier && user.requested_tier === 'premium');
    const plan: BillingPlan = aibainExpired ? (preferred ? 'premium_aibain' : 'pro_aibain') : preferred ? 'premium' : 'pro';
    const kind = aibainExpired ? 'aibain-expired' : expired ? 'base-expired' : 'subscribe';
    return {
        kind, plan,
        title: aibainExpired ? 'AI Brain이 만료되었습니다' : expired ? '구독이 만료되었습니다' : '아직 이용 중인 구독이 없습니다',
        message: aibainExpired ? '기본 구독은 계속 이용할 수 있습니다. AI Brain을 다시 신청해 주세요.' : '플랜 선택 → 입금 후 신청 → 관리자 승인 후 이용',
        cta: aibainExpired ? 'AI Brain 재구독하기' : expired ? '재구독 신청하기' : '구독 신청하기',
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
