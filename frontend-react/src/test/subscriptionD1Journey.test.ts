import { describe, expect, it } from 'vitest';
import { subscriptionJourney } from '@/lib/subscriptionJourney';

const now = Date.parse('2026-11-11T00:00:00Z');
const base = { id: 1, email: 'member@example.test', name: '회원', role: 'user', status: 'approved', tier: 'pro', is_pro_expired: false };
const expiry = '2026-11-12T00:00:00'; // API timezone-less values are UTC, not device time.

describe('D-1 subscription reminder boundary', () => {
    it('starts exactly 24 hours before PRO expiry and links to early renewal', () => {
        const member = { ...base, pro_expires_at: expiry };
        expect(subscriptionJourney(member, now - 1)).toBeNull();
        const due = subscriptionJourney(member, now);
        expect(due?.kind).toBe('expiring');
        expect(due?.payment).toBe('/payment-request?plan=pro&renew=1');
        expect(due?.amount).toBe('50,000원');
        expect(due?.expiresAt).toBe('2026-11-12T00:00:00.000Z');
        expect(subscriptionJourney(member, now + 86_400_000)?.kind).toBe('base-expired');
    });
    it('uses the effective resumed expiry instead of the old frozen date', () => {
        expect(subscriptionJourney({ ...base, pro_expires_at: '2026-11-10T00:00:00Z', pro_effective_expires_at: expiry }, now)?.kind).toBe('expiring');
        expect(subscriptionJourney({ ...base, pro_expires_at: expiry, pro_effective_expires_at: '2026-12-12T00:00:00Z' }, now)).toBeNull();
    });
    it.each(['pro', 'premium'])('renews a %s AI bundle for 50000 while base access is retained', tier => {
        const due = subscriptionJourney({ ...base, tier, is_pro_paused: true, pro_expires_at: '2026-11-10T00:00:00Z',
            is_aibain_active: true, aibain_expires_at: expiry, is_kongming_active: true, kongming_expires_at: expiry }, now);
        expect(due?.kind).toBe('expiring');
        expect(due?.title).toContain('AI 브레인 + 제갈공명');
        expect(due?.amount).toBe('50,000원');
        expect(due?.payment).toBe(`/payment-request?plan=${tier}&aibain=1`);
    });
    it('does not hide an earlier legacy AI expiry behind later Kongming access', () => {
        const due = subscriptionJourney({ ...base, is_pro_paused: true, is_aibain_active: true, aibain_expires_at: expiry,
            is_kongming_active: true, kongming_expires_at: '2026-12-01T00:00:00Z' }, now);
        expect(due?.kind).toBe('expiring');
        expect(due?.title).toContain('AI 브레인');
        expect(due?.title).not.toContain('제갈공명');
        expect(due?.expiresAt).toBe('2026-11-12T00:00:00.000Z');
    });
    it('uses the current 100000 bundle for legacy no-base Kongming subscribers', () => {
        const due = subscriptionJourney({ ...base, tier: null, is_kongming_active: true, kongming_expires_at: expiry }, now);
        expect(due?.amount).toBe('100,000원');
        expect(due?.payment).toBe('/payment-request?plan=pro&aibain=1');
    });
    it.each([
        { role: 'admin' }, { status: 'suspended' }, { status: 'rejected' },
        { tier: 'premium' }, { is_pro_paused: true }, { pro_expires_at: 'invalid' },
    ])('does not invent an expiring paid entitlement for %j', override => {
        expect(subscriptionJourney({ ...base, pro_expires_at: expiry, ...override }, now)?.kind).not.toBe('expiring');
    });
    it('keys dismissal to the entitlement cycle so an extended expiry is a new reminder', () => {
        const old = subscriptionJourney({ ...base, pro_expires_at: expiry }, now);
        const newer = subscriptionJourney({ ...base, pro_expires_at: '2026-12-12T00:00:00Z' }, Date.parse('2026-12-11T00:00:00Z'));
        expect(old?.fingerprint).toBeTruthy();
        expect(newer?.fingerprint).not.toBe(old?.fingerprint);
    });
});
