import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchTop3Advisor } from '@/lib/top3Advisor';
import { advisorFixture } from './fixtures/top3AdvisorFixture';

afterEach(() => { vi.unstubAllGlobals(); });
describe('advisor HTTP transport', () => {
    it.each([401, 403, 503])('retains HTTP %s so the panel can stop unauthorized polling', async status => {
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'private detail' }), { status }));
        vi.stubGlobal('fetch', fetch);
        await expect(fetchTop3Advisor('test-only')).rejects.toMatchObject({ status });
    });
    it('reads only saved GET with a bounded request and existing bearer', async () => {
        const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(advisorFixture()), { status: 200 }));
        vi.stubGlobal('fetch', fetch);
        expect((await fetchTop3Advisor('test-only')).top3).toHaveLength(3);
        expect(fetch.mock.calls[0][0]).toContain('/api/admin/mirofish/alpha-lab/top3-advisor');
        expect(fetch.mock.calls[0][1]).toMatchObject({ headers: { Authorization: 'Bearer test-only' } });
        expect(fetch.mock.calls[0][1].method ?? 'GET').toBe('GET');
        expect(fetch).toHaveBeenCalledTimes(1);
    });
});
