import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchCatalystOutcomes } from '@/lib/catalystOutcomes';
import { catalystOutcomesFixture } from './fixtures/catalystOutcomesFixture';
afterEach(() => { vi.unstubAllGlobals(); });
describe('catalyst outcomes saved GET', () => {
    it.each([401, 403, 503])('preserves HTTP %s', async status => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })));
        await expect(fetchCatalystOutcomes({}, 'test-token')).rejects.toMatchObject({ status });
    });
    it('uses explicit bearer, no-store and bounded GET with validated filters', async () => {
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(catalystOutcomesFixture())));
        vi.stubGlobal('fetch', fetch);
        await fetchCatalystOutcomes({ filter: 'all', page: 2, page_size: 10, symbol: '005930' }, 'test-token');
        expect(fetch.mock.calls[0][0]).toContain('/api/admin/mirofish/kongming/catalyst-outcomes?filter=all&page=2&page_size=10&symbol=005930');
        expect(fetch.mock.calls[0][1]).toMatchObject({ headers: { Authorization: 'Bearer test-token' }, cache: 'no-store' });
        expect(fetch.mock.calls[0][1].method ?? 'GET').toBe('GET');
        await expect(fetchCatalystOutcomes({ symbol: '005930&refresh=1' }, 'test-token')).rejects.toThrow();
        await expect(fetchCatalystOutcomes({ page: 0 }, 'test-token')).rejects.toThrow();
        expect(fetch).toHaveBeenCalledTimes(1);
    });
});
