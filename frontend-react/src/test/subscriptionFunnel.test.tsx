/**
 * 비구독 회원 퍼널 단일 기준 — subscriptionFunnelTarget.
 * 어떤 페이지에 들어와도 노티어/만료/승인대기 회원은 구독 퍼널로 보내져야 한다.
 * 가드(ApprovedGuard·ProGuard)·공개 라우트(FunnelGate)·404 CTA 가 전부 이 함수를 본다.
 */
import { describe, expect, it } from 'vitest';

import { subscriptionFunnelTarget } from '@/lib/auth';

const base = { id: 1, email: 'u@example.com', name: 'U', role: 'user' };

describe('subscriptionFunnelTarget', () => {
    it('비로그인 방문자·로딩 중(unknown)·admin 은 리다이렉트하지 않는다', () => {
        expect(subscriptionFunnelTarget(null)).toBeNull();
        expect(subscriptionFunnelTarget(undefined)).toBeNull();
        expect(subscriptionFunnelTarget({ ...base, status: 'unknown', tier: null })).toBeNull();
        expect(subscriptionFunnelTarget({ ...base, role: 'admin', status: 'approved', tier: null })).toBeNull();
    });

    it('활성 Pro / Ultra Pro 구독자는 통과한다', () => {
        expect(subscriptionFunnelTarget({ ...base, status: 'approved', tier: 'pro', is_pro_expired: false })).toBeNull();
        expect(subscriptionFunnelTarget({ ...base, status: 'approved', tier: 'premium', is_pro_expired: false })).toBeNull();
    });

    it('만료 회원은 재구독 플랜 선택으로 (tier 보존 상태 포함)', () => {
        expect(subscriptionFunnelTarget({ ...base, status: 'expired', tier: 'pro' }))
            .toBe('/plan-select?resubscribe=1&from=expired');
        // status 는 approved 지만 백엔드 계산상 만료
        expect(subscriptionFunnelTarget({ ...base, status: 'approved', tier: 'pro', is_pro_expired: true }))
            .toBe('/plan-select?resubscribe=1&from=expired');
    });

    it('노티어(tier=null) + 신청 미제출 회원은 어떤 status 든 플랜 선택으로', () => {
        expect(subscriptionFunnelTarget({ ...base, status: 'pending', tier: null })).toBe('/plan-select');
        expect(subscriptionFunnelTarget({ ...base, status: 'approved', tier: null })).toBe('/plan-select');
    });

    it('구독 신청을 제출한 노티어 회원(requested_tier 기록)은 재입금 안내가 아닌 승인 대기로', () => {
        // 백엔드는 sub_req 제출 시 requested_tier 만 기록, tier 는 승인 시점에 설정 —
        // /plan-select 로 보내면 이미 입금한 회원에게 "다시 입금" 안내가 된다.
        expect(subscriptionFunnelTarget({ ...base, status: 'pending', tier: null, requested_tier: 'pro' }))
            .toBe('/pending-approval');
        expect(subscriptionFunnelTarget({ ...base, status: 'pending', tier: null, requested_tier: 'premium' }))
            .toBe('/pending-approval');
    });

    it('플랜 신청 후 승인 대기 회원은 pending-approval 로', () => {
        expect(subscriptionFunnelTarget({ ...base, status: 'pending', tier: 'pro' })).toBe('/pending-approval');
        // 알 수 없는 tier 값도 활성 구독으로 오인하지 않는다
        expect(subscriptionFunnelTarget({ ...base, status: 'approved', tier: 'free' })).toBe('/pending-approval');
    });
});
