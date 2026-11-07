"""Subscription offers. Existing requests keep the terms recorded at submission."""

AI_BUNDLE_POLICY_MARKER = '[ai_bundle_v2]'
AI_BUNDLE_AMOUNT = 50_000
BASE_PLAN_AMOUNTS = {'pro': 50_000, 'premium': 1_200_000}


def is_ai_bundle_request(subscription_request):
    return AI_BUNDLE_POLICY_MARKER in (subscription_request.admin_note or '')
