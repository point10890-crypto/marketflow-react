import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAutoRefresh, useSmartRefresh } from '@/hooks/useAutoRefresh';

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe('refresh polling', () => {
    it('does not overlap auto-refresh requests', async () => {
        vi.useFakeTimers();
        let finish!: () => void;
        const firstRequest = new Promise<void>((resolve) => { finish = resolve; });
        const refresh = vi.fn()
            .mockImplementationOnce(() => firstRequest)
            .mockResolvedValue(undefined);

        renderHook(() => useAutoRefresh(refresh, 1000));

        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
        expect(refresh).toHaveBeenCalledTimes(1);

        await act(async () => { finish(); await firstRequest; });
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(refresh).toHaveBeenCalledTimes(2);
    });

    it('keeps one smart-refresh interval when an equivalent inline array is rerendered', async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ versions: {} }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        }));
        vi.stubGlobal('fetch', fetchMock);
        const refresh = vi.fn();

        const { rerender } = renderHook(
            ({ generation }) => {
                void generation;
                useSmartRefresh(refresh, ['vcp_kr_latest.json'], 60000);
            },
            { initialProps: { generation: 1 } },
        );

        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        rerender({ generation: 2 });
        await Promise.resolve();
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
});
