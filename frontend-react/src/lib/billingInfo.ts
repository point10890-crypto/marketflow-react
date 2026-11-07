import { hasActiveBaseSubscription, subscriptionExpiryTime, type AuthUserData } from './auth';

/**
 * 청구/구독 메타데이터.
 *
 * 백엔드 tier 차원 (BillingPlanTier) 과 UI 플랜 차원 (BillingPlan) 을 분리:
 *  - BillingPlanTier: 백엔드가 인식하는 tier = 'pro' | 'premium'
 *  - BillingPlan:     기본 플랜과 AI 구독을 포함한 신청 옵션
 *
 * AI Brain 은 별도 30일 갱신 구독제. tier 만료와는 별도 차원.
 */

export type BillingPlanTier = 'pro' | 'premium';

export type BillingPlan = 'pro' | 'pro_aibain' | 'premium' | 'premium_aibain' | 'aibain_kongming';

export const AI_BUNDLE_CONVERSION = {
    plan: 'aibain_kongming_conversion',
    payment: '/payment-request?plan=aibain_kongming_conversion',
    label: '제갈공명 전환',
    amount: '10,000원',
    amountNumber: 10_000,
} as const;

export function aiBundleConversionExpiry(
    user: Pick<AuthUserData, 'ai_bundle_conversion' | 'role' | 'status'> | null | undefined,
    now = Date.now(),
): string | null {
    const quote = user?.ai_bundle_conversion;
    if (!user || user.role === 'admin' || !['approved', 'expired'].includes(user.status)
        || quote?.eligible !== true || quote.amount !== AI_BUNDLE_CONVERSION.amountNumber
        || typeof quote.expires_at !== 'string' || !(subscriptionExpiryTime(quote.expires_at) > now)) return null;
    return quote.expires_at;
}

export function formatConversionExpiry(value?: string | null): string {
    const expiry = subscriptionExpiryTime(value);
    return Number.isFinite(expiry) ? new Intl.DateTimeFormat('ko-KR', {
        dateStyle: 'long', timeStyle: 'short', timeZone: 'Asia/Seoul',
    }).format(expiry) + ' (한국시간)' : '확인 필요';
}

export function conversionApprovalDetails(expiry?: string | null): string {
    return `제갈공명 전환 ${AI_BUNDLE_CONVERSION.amount} 입금을 확인했나요?\n제갈공명 이용 종료 ${formatConversionExpiry(expiry)}\n기존 AI Brain과 기본 구독 기간은 유지됩니다.`;
}

export const BANK_ACCOUNT = {
    bank: '국민은행',
    account: '2259-02-04-057670',
    holder: '이종민',
};

export interface PlanMeta {
    label: string;
    tier: BillingPlanTier | 'aibain_kongming'; // 구독 신청 대상
    includesAibain: boolean;     // AI Brain 포함 여부
    amount: string;              // 표시용 (예: "100,000원")
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
        amount: '100,000원',
        amountNumber: 100_000,
        color: 'cyan',
        period: 'AI·제갈공명 30일 + 보존되는 Pro 30일',
        baseAmount: 'Pro 50,000원',
        aibainAmount: 'AI Brain·제갈공명 50,000원',
        description: 'Pro 5만 원 + AI·제갈공명 5만 원 · AI 이용 중 Pro 기간 일시정지',
        features: [
            'Pro 전체 기능 포함',
            'AI Brain 알파 스캐너 관찰 후보',
            'MCP TOP 3 관찰 알림',
            '제갈공명 뉴스·공시·시세 검증 포함',
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
        amount: '1,250,000원',
        amountNumber: 1_250_000,
        color: 'fuchsia',
        period: 'Ultra Pro 평생 + AI Brain 30일 갱신',
        baseAmount: 'Ultra Pro 1,200,000원 (평생)',
        aibainAmount: 'AI Brain·제갈공명 50,000원/30일',
        description: 'Ultra Pro 평생 + AI Brain 30일 갱신',
        features: [
            'Ultra Pro 평생 이용',
            'AI Brain 알파 스캐너 관찰 후보',
            'MCP TOP 3 관찰 알림',
            '제갈공명 뉴스·공시·시세 검증 포함',
            'AI Brain 만료 시 자동 회귀',
        ],
    },
    aibain_kongming: {
        label: 'AI 브레인 + 제갈공명',
        tier: 'aibain_kongming',
        includesAibain: true,
        amount: '50,000원',
        amountNumber: 50_000,
        color: 'cyan',
        period: '30일 이용권',
        description: '기존 단독 이용권 내역 · 신규 신청은 기본 등급에 맞춰 안내',
        features: [
            'AI 브레인 알파 스캐너와 Goodrich TOP 3',
            'AI 종목 판단과 차트 유사 사례',
            '제갈공명 뉴스·공시 근거 대조',
            '재료 판정과 검증 이력',
        ],
    },
};

/**
 * AI Brain 애드온 단독 요금 — 활성 Pro/Ultra Pro 회원이 AI Brain 만 추가할 때.
 * 기존 구독에 추가하는 옵션이므로 PLAN_PAYMENT_META와 별도로 노출한다.
 * (실제 금액 계산은 백엔드 aibain_addon/aibain_renewal 경로가 50,000원으로 고정)
 */
export const AIBAIN_ADDON_META = {
    label: 'AI Brain + 제갈공명',
    amount: '50,000원',
    amountNumber: 50_000,
    period: '30일 갱신 · 베이스 플랜 유지',
    description: 'Pro·Ultra Pro 회원은 5만 원에 AI Brain과 제갈공명을 30일 추가합니다. Pro 잔여기간은 일시정지됩니다.',
    features: [
        'AI Brain 알파 스캐너 관찰 후보',
        'GraphRAG 분석 + TOP 3',
        '제갈공명 뉴스·공시·시세 검증',
        '스캔 성과·품질 확인 화면',
        '만료 시 베이스 플랜으로 자동 회귀',
    ],
} as const;

/** URL 쿼리 (plan + aibain) → BillingPlan */
export function planFromQuery(
    rawPlan: string | null | undefined,
    rawAibain: string | null | undefined,
): BillingPlan | null {
    const aibain = rawAibain === '1' || rawAibain === 'true';
    if (rawPlan === 'pro') return aibain ? 'pro_aibain' : 'pro';
    if (rawPlan === 'premium') return aibain ? 'premium_aibain' : 'premium';
    if (rawPlan === 'aibain_kongming') return 'aibain_kongming';
    return null;
}

/** BillingPlan → URL 쿼리 fragment */
export function planToQuery(plan: BillingPlan): string {
    if (plan === 'aibain_kongming') return 'plan=aibain_kongming';
    const meta = PLAN_PAYMENT_META[plan];
    const base = `plan=${meta.tier}`;
    return meta.includesAibain ? `${base}&aibain=1` : base;
}

export function isKongmingSubscriptionRequest(type?: string | null): boolean {
    return type === 'aibain_kongming' || type === 'aibain_kongming_renewal';
}

/** 하위호환 — 기존 'pro' / 'premium' 만 받던 normalize (PaymentRequestPage 기존 호출) */
export function normalizeBillingPlan(value: unknown): BillingPlanTier | null {
    return value === 'pro' || value === 'premium' ? value : null;
}

/** Retired standalone URLs are resolved before any deposit instructions are shown. */
export function aiBundleOffer(user: Parameters<typeof hasActiveBaseSubscription>[0]) {
    const activeBase = hasActiveBaseSubscription(user);
    const plan: BillingPlan = activeBase && user?.tier === 'premium' ? 'premium_aibain' : 'pro_aibain';
    return {
        plan,
        label: activeBase ? AIBAIN_ADDON_META.label : 'Pro + AI Brain + 제갈공명',
        amount: activeBase ? AIBAIN_ADDON_META.amount : PLAN_PAYMENT_META.pro_aibain.amount,
        payment: `/payment-request?${planToQuery(plan)}`,
    };
}

export function resolveBillingPlan(plan: BillingPlan | null, user: Parameters<typeof hasActiveBaseSubscription>[0]): BillingPlan | null {
    return plan === 'aibain_kongming' ? aiBundleOffer(user).plan : plan;
}

export function isAiBundleRequest(request: { admin_note?: string | null } | null | undefined): boolean {
    return !!request?.admin_note?.includes('[ai_bundle_v2]');
}

export function subscriptionNote(note: string | null | undefined): string {
    return (note || '').replace('[ai_bundle_v2] ', '');
}
