"""Subscription offers. Existing requests keep the terms recorded at submission."""

from app.models import db
from app.models.user import AIBAIN_KONGMING_REQUEST_TYPES, SubscriptionRequest, User
from app.services.subscription_lifecycle import utc


AI_BUNDLE_CONVERSION_AMOUNT = 10_000
AI_BUNDLE_POLICY_MARKER = '[ai_bundle_v2]'
AI_BUNDLE_AMOUNT = 50_000
BASE_PLAN_AMOUNTS = {'pro': 50_000, 'premium': 1_200_000}


def is_ai_bundle_request(subscription_request):
    return AI_BUNDLE_POLICY_MARKER in (subscription_request.admin_note or '')


def ai_bundle_conversion_reason(
    user: User, *, has_pending: bool, exclude_request_id: int | None = None,
) -> str:
    """Validate legacy pending approvals, not eligibility for a new checkout."""
    if user.is_admin or not user.is_approved:
        return 'account_ineligible'
    if not user.is_aibain_active:
        return 'aibain_inactive'
    if user.aibain_expires_at is None:
        return 'indefinite_aibain'
    if user.kongming_expires_at is not None:
        return 'kongming_previously_granted'
    if has_pending:
        return 'pending_request'

    approved = SubscriptionRequest.query.filter(
        SubscriptionRequest.user_id == user.id,
        SubscriptionRequest.status == 'approved',
        SubscriptionRequest.request_type.in_(AIBAIN_KONGMING_REQUEST_TYPES)
        | SubscriptionRequest.admin_note.contains(AI_BUNDLE_POLICY_MARKER, autoescape=True),
    )
    if exclude_request_id is not None:
        approved = approved.filter(SubscriptionRequest.id != exclude_request_id)
    if db.session.query(approved.exists()).scalar():
        return 'kongming_previously_granted'
    return 'eligible'


def ai_bundle_conversion_offer(user: User, *, has_pending: bool) -> dict:
    """Retired for new requests; retain the response shape for older clients.

    Historical pending conversions still use their captured terms at approval.
    Do not retire conversion_snapshot_is_current with this public offer.
    """
    return {
        'eligible': False,
        'amount': AI_BUNDLE_CONVERSION_AMOUNT,
        'expires_at': None,
        'reason': 'plan_retired',
    }


def conversion_snapshot_is_current(user: User, subscription_request: SubscriptionRequest) -> bool:
    """Validate the captured AI term while holding the subscription request write lock."""
    return (
        subscription_request.conversion_expires_at is not None
        and utc(subscription_request.conversion_expires_at) == utc(user.aibain_expires_at)
        and ai_bundle_conversion_reason(
            user,
            has_pending=False,
            exclude_request_id=subscription_request.id,
        ) == 'eligible'
    )
