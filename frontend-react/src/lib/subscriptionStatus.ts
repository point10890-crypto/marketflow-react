import type { SubscriptionRequest } from './api';

type Status = {
    requests: SubscriptionRequest[];
    pending_request?: SubscriptionRequest | null;
    user?: { has_pending_subscription?: boolean };
};

/** Recent history is display-only; the server checks all pending requests. */
export function pendingSubscriptionRequest(status: Status): SubscriptionRequest | null {
    return status.pending_request?.status === 'pending' ? status.pending_request
        : status.requests.find(request => request.status === 'pending') || null;
}

export function hasPendingSubscription(status: Status): boolean {
    return status.user?.has_pending_subscription === true || !!pendingSubscriptionRequest(status);
}
