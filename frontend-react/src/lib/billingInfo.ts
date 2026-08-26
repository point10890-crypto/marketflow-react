/**
 * 청구/구독 메타데이터.
 *
 * 백엔드 tier 차원 (BillingPlanTier) 과 UI 플랜 차원 (BillingPlan) 을 분리:
 *  - BillingPlanTier: 백엔드가 인식하는 tier = 'pro' | 'premium'
 *  - BillingPlan:     UI 가 노출하는 4종 옵션 (베이스 × AI Brain on/off)
 *
 * AI Brain 은 별도 30일 갱신 구독제. tier 만료와는 별도 차원.
 */

export type BillingPlanTier = 'pro' | 'premium';

/** UI 플랜 키 — 4종 (베이스 × AI Brain 토글) */
export type BillingPlan = 'pro' | 'pro_aibain' | 'premium' | 'premium_aibain';

export const BANK_ACCOUNT = {
    bank: '국민은행',
    account: '2259-02-04-057670',
    holder: '이종민',
};

export interface PlanMeta {
    label: string;
    tier: BillingPlanTier;       // 백엔드로 전송할 tier
    includesAibain: boolean;     // AI Brain 포함 여부
    amount: string;              // 표시용 (예: "90,000원")
    amountNumber: number;        // 비교/계산용 (예: 90000)
    color: 'amber' | 'cyan' | 'purple' | 'fuchsia';
    period: string;
    baseAmount?: string;         // 베이스 분리 표시 (Pro+AI Brain 등)
    aibainAmount?: string;       // AI Brain 분리 표시
    description: string;
    features: string[];
}

export const PLAN_PAYMENT_META: Record<BillingPlan, PlanMeta> = {
    pro: {
        label: 'Pro',
        tier: 'pro',
        includesAibain: false,
        amount: '50,000원',
        amountNumber: 50_000,
        color: 'amber',
        period: '30일 이용권',
        description: '월 갱신 · 30일 이용',
        features: [
            '기본 대시보드 전체 접근',
            'KR / US / Crypto 시그널',
            'AI 챗봇 + 차트 분석',
            '텔레그램 관찰 이벤트 알림',
        ],
    },
    pro_aibain: {
        label: 'Pro + AI Brain',
        tier: 'pro',
        includesAibain: true,
        amount: '90,000원',
        amountNumber: 90_000,
        color: 'cyan',
        period: '30일 이용권 (Pro 30일 + AI Brain 30일)',
        baseAmount: 'Pro 50,000원',
        aibainAmount: 'AI Brain 40,000원',
        description: 'Pro 50,000원 + AI Brain 40,000원 (30일 갱신)',
        features: [
            'Pro 전체 기능 포함',
            'AI Brain 알파 스캐너 관찰 후보',
            'MCP TOP 3 관찰 알림',
            '그래프RAG 분석 + 스캔 성과',
        ],
    },
    premium: {
        label: 'Ultra Pro',
        tier: 'premium',
        includesAibain: false,
        amount: '1,200,000원',
        amountNumber: 1_200_000,
        color: 'purple',
        period: '평생 무기한 이용',
        description: '1회 결제 · 무기한 이용',
        features: [
            'Pro 전체 기능 포함',
            '평생 무기한 이용',
            '향후 업데이트 전부 포함',
            '우선 고객 지원',
        ],
    },
    premium_aibain: {
        label: 'Ultra Pro + AI Brain',
        tier: 'premium',
        includesAibain: true,
        amount: '1,240,000원',
        amountNumber: 1_240_000,
        color: 'fuchsia',
        period: 'Ultra Pro 평생 + AI Brain 30일 갱신',
        baseAmount: 'Ultra Pro 1,200,000원 (평생)',
        aibainAmount: 'AI Brain 40,000원/30일',
        description: 'Ultra Pro 평생 + AI Brain 30일 갱신',
        features: [
            'Ultra Pro 평생 이용',
            'AI Brain 알파 스캐너 관찰 후보',
            'MCP TOP 3 관찰 알림',
            'AI Brain 만료 시 자동 회귀',
        ],
    },
};

/** URL 쿼리 (plan + aibain) → BillingPlan */
export function planFromQuery(
    rawPlan: string | null | undefined,
    rawAibain: string | null | undefined,
): BillingPlan | null {
    const aibain = rawAibain === '1' || rawAibain === 'true';
    if (rawPlan === 'pro') return aibain ? 'pro_aibain' : 'pro';
    if (rawPlan === 'premium') return aibain ? 'premium_aibain' : 'premium';
    return null;
}

/** BillingPlan → URL 쿼리 fragment */
export function planToQuery(plan: BillingPlan): string {
    const meta = PLAN_PAYMENT_META[plan];
    const base = `plan=${meta.tier}`;
    return meta.includesAibain ? `${base}&aibain=1` : base;
}

/** 하위호환 — 기존 'pro' / 'premium' 만 받던 normalize (PaymentRequestPage 기존 호출) */
export function normalizeBillingPlan(value: unknown): BillingPlanTier | null {
    return value === 'pro' || value === 'premium' ? value : null;
}
