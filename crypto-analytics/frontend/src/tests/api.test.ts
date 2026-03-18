import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch before importing
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('API module', () => {
    beforeEach(() => {
        mockFetch.mockReset();
    });

    it('fetchAPI throws on non-ok response', async () => {
        mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 500,
        });

        const { fetchAPI } = await import('@/lib/api');
        await expect(fetchAPI('/api/test')).rejects.toThrow('API Error: 500');
    });

    it('fetchAPI returns parsed JSON on success', async () => {
        mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ data: 'test' }),
        });

        const { fetchAPI } = await import('@/lib/api');
        const result = await fetchAPI<{ data: string }>('/api/test');
        expect(result).toEqual({ data: 'test' });
    });

    it('cryptoAPI has expected methods', async () => {
        const { cryptoAPI } = await import('@/lib/api');
        const expectedMethods = [
            'getVCPSignals', 'getMarketGate', 'getTimeline',
            'getMonthlyReport', 'getLeadLag', 'getBriefing',
            'getPrediction', 'getRisk', 'getGateHistory',
            'getPredictionHistory',
        ];
        for (const method of expectedMethods) {
            expect(typeof (cryptoAPI as Record<string, unknown>)[method]).toBe('function');
        }
    });
});
