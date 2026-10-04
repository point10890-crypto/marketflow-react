import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePWAInstall } from '@/hooks/usePWAInstall';

type InstallOutcome = 'accepted' | 'dismissed';

function setDisplayModeStandalone(matches: boolean) {
    Object.defineProperty(window, 'matchMedia', {
        configurable: true,
        value: vi.fn().mockReturnValue({
            matches,
            media: '(display-mode: standalone)',
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        }),
    });
}

function dispatchInstallPrompt(outcome: InstallOutcome, promptError?: Error) {
    const event = new Event('beforeinstallprompt') as Event & {
        prompt: ReturnType<typeof vi.fn>;
        userChoice: Promise<{ outcome: InstallOutcome }>;
    };
    event.prompt = promptError
        ? vi.fn().mockRejectedValue(promptError)
        : vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome });
    window.dispatchEvent(event);
    return event;
}

describe('PWA installation state', () => {
    beforeEach(() => {
        setDisplayModeStandalone(false);
        Object.defineProperty(navigator, 'standalone', {
            configurable: true,
            value: false,
        });
        window.dispatchEvent(new Event('appinstalled'));
    });

    it('consumes a dismissed browser prompt so it cannot be reused', async () => {
        const { result } = renderHook(() => usePWAInstall());

        let event: ReturnType<typeof dispatchInstallPrompt>;
        act(() => {
            event = dispatchInstallPrompt('dismissed');
        });
        expect(result.current.canInstall).toBe(true);

        await act(async () => {
            await expect(result.current.install()).resolves.toBe('dismissed');
        });

        expect(event!.prompt).toHaveBeenCalledTimes(1);
        expect(result.current.canInstall).toBe(false);
        await expect(result.current.install()).resolves.toBe('manual');
        expect(event!.prompt).toHaveBeenCalledTimes(1);
    });

    it('hides install UI in the source tab as soon as installation completes', () => {
        const { result } = renderHook(() => usePWAInstall());

        act(() => {
            dispatchInstallPrompt('accepted');
        });
        expect(result.current.canInstall).toBe(true);

        act(() => {
            window.dispatchEvent(new Event('appinstalled'));
        });

        expect(result.current.isInstalled).toBe(true);
        expect(result.current.canInstall).toBe(false);
    });

    it('consumes a failed native prompt and falls back to manual guidance', async () => {
        const { result } = renderHook(() => usePWAInstall());

        act(() => {
            dispatchInstallPrompt('dismissed', new Error('prompt unavailable'));
        });

        await act(async () => {
            await expect(result.current.install()).resolves.toBe('manual');
        });

        expect(result.current.canInstall).toBe(false);
    });

    it('treats iOS home-screen mode as already installed', () => {
        Object.defineProperty(navigator, 'standalone', {
            configurable: true,
            value: true,
        });
        act(() => {
            dispatchInstallPrompt('dismissed');
        });

        const { result } = renderHook(() => usePWAInstall());

        expect(result.current.isInstalled).toBe(true);
        expect(result.current.canInstall).toBe(false);
    });
});
