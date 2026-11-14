import { hasActiveBaseSubscription, isBaseSubscriptionExpired, isKongmingOnlyUser, subscriptionFunnelTarget, type FunnelUser } from './auth';
import { AI_BUNDLE_CONVERSION, planFromQuery, planToQuery } from './billingInfo';

export function safeNextPath(value: string | null): string | null {
    if (!value) return null;
    try {
        const decoded = decodeURIComponent(value);
        if (!decoded.startsWith('/') || decoded.startsWith('//') || decoded.includes('\\')) return null;
        return decoded;
    } catch {
        return null;
    }
}

function planSelectNext(nextPath: string | null): string | null {
    return nextPath === '/plan-select' || nextPath?.startsWith('/plan-select?') ? nextPath : null;
}

/** Only a recognized subscription selection is carried back into account creation. */
export function signupPathForPlan(nextPath: string | null): string {
    const planned = planSelectNext(nextPath);
    const query = new URLSearchParams(planned?.split('?')[1] || '');
    const plan = planFromQuery(query.get('plan'), query.get('aibain'));
    return plan ? `/signup?${planToQuery(plan)}` : '/signup';
}

export function nextPathForUser(user: FunnelUser, nextPath: string | null): string {
    const planned = planSelectNext(nextPath);
    if (user.role === 'admin') {
        return nextPath?.startsWith('/admin') ? nextPath : '/admin';
    }
    if (nextPath === AI_BUNDLE_CONVERSION.payment && ['approved', 'expired'].includes(user.status || '')) {
        return user.has_pending_subscription ? '/pending-approval' : '/plan-select?change=1';
    }
    if (planned && user.has_pending_subscription) return '/pending-approval';
    if (isKongmingOnlyUser(user)) {
        if (planned) return planned;
        if (nextPath === '/pending-approval' || nextPath?.startsWith('/dashboard/')) return nextPath;
        return '/dashboard/ai-bain';
    }
    const funnel = subscriptionFunnelTarget(user);
    if (funnel === '/pending-approval') return funnel;
    if (funnel?.includes('plan=aibain_kongming')) return funnel;

    const query = new URLSearchParams(planned?.split('?')[1] || '');
    if (isBaseSubscriptionExpired(user)) {
        query.delete('change');
        query.set('resubscribe', '1');
        query.set('from', 'expired');
        return `/plan-select?${query.toString()}`;
    }
    if (!user.tier) return planned || funnel || '/plan-select';
    if (user.status !== 'approved') return '/pending-approval';
    if (!hasActiveBaseSubscription(user)) return planned || '/plan-select';

    if (planned && query.get('change') === '1') {
        // A Pro + AI offer opened by a returning Ultra Pro member is an AI add-on.
        if (user.tier === 'premium' && planFromQuery(query.get('plan'), query.get('aibain')) === 'pro_aibain') {
            query.set('plan', 'premium');
            return `/plan-select?${query.toString()}`;
        }
        return planned;
    }
    return nextPath?.startsWith('/dashboard') ? nextPath : '/dashboard';
}
