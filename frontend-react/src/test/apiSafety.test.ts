import { describe, expect, it, vi, afterEach } from 'vitest';
import { ApiTimeoutError, fetchWithTimeout, safeLocalRedirect } from '@/lib/api';

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe('API transport safety', () => {
    it('rejects unsafe redirect targets', () => {
        const fallback = '/plan-select';
        expect(safeLocalRedirect('/dashboard?tab=kr', fallback)).toBe('/dashboard?tab=kr');
        expect(safeLocalRedirect('//evil.example/path', fallback)).toBe(fallback);
        expect(safeLocalRedirect('/\\evil.example/path', fallback)).toBe(fallback);
        expect(safeLocalRedirect('https://evil.example/path', fallback)).toBe(fallback);
    });

    it('turns only deadline aborts into ApiTimeoutError', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
            new Promise<Response>((_resolve, reject) => {
                init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
            })
        )));

        const request = fetchWithTimeout('/api/slow', {}, 1000);
        const assertion = expect(request).rejects.toBeInstanceOf(ApiTimeoutError);
        await vi.advanceTimersByTimeAsync(1000);
        await assertion;
    });

    it('preserves caller cancellation as AbortError', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
            new Promise<Response>((_resolve, reject) => {
                init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
            })
        )));

        const controller = new AbortController();
        const request = fetchWithTimeout('/api/cancelled', { signal: controller.signal }, 1000);
        const assertion = expect(request).rejects.toMatchObject({ name: 'AbortError' });
        controller.abort();
        await assertion;
    });
});
