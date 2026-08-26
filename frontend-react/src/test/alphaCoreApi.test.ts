import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));

vi.mock('@/lib/api', () => ({
    fetchAuthAPI: apiMock.fetchAuthAPI,
}));

import { ALPHA_CORE_ENDPOINTS, fetchAlphaCoreSnapshot } from '@/lib/alphaCore';

describe('Alpha Core GET client', () => {
    beforeEach(() => {
        apiMock.fetchAuthAPI.mockReset();
    });

    it('reads only the five operations endpoints and retains partial results', async () => {
        apiMock.fetchAuthAPI
            .mockResolvedValueOnce({ mode: 'PAPER' })
            .mockResolvedValueOnce({ cash_krw: 100 })
            .mockRejectedValueOnce(new Error('not ready'))
            .mockResolvedValueOnce({ data: { items: [] } })
            .mockResolvedValueOnce({ summary: { pending: 0 } });

        const result = await fetchAlphaCoreSnapshot('token');

        expect(apiMock.fetchAuthAPI.mock.calls).toEqual([
            [ALPHA_CORE_ENDPOINTS.status, 'token'],
            [ALPHA_CORE_ENDPOINTS.portfolio, 'token'],
            [ALPHA_CORE_ENDPOINTS.riskDecisions, 'token'],
            [ALPHA_CORE_ENDPOINTS.hypotheses, 'token'],
            [ALPHA_CORE_ENDPOINTS.ledger, 'token'],
        ]);
        expect(result.status?.mode).toBe('PAPER');
        expect(result.hypotheses?.items).toEqual([]);
        expect(result.riskDecisions).toBeNull();
        expect(result.unavailable).toEqual(['riskDecisions']);
    });
});

