export type BillingPlanTier = 'pro' | 'premium';

export const BANK_ACCOUNT = {
    bank: '국민은행',
    account: '2259-02-04-057670',
    holder: '이종민',
};

export const PLAN_PAYMENT_META: Record<BillingPlanTier, {
    label: string;
    amount: string;
    color: 'amber' | 'purple';
    period: string;
}> = {
    pro: {
        label: 'Pro',
        amount: '50,000원',
        color: 'amber',
        period: '30일 이용권',
    },
    premium: {
        label: 'Ultra Pro',
        amount: '1,200,000원',
        color: 'purple',
        period: '평생 무기한',
    },
};

export function normalizeBillingPlan(value: unknown): BillingPlanTier | null {
    return value === 'pro' || value === 'premium' ? value : null;
}

