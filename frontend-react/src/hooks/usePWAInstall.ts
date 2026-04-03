import { useState, useEffect, useCallback } from 'react';

interface BeforeInstallPromptEvent extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let _deferredPrompt: BeforeInstallPromptEvent | null = null;
const _listeners = new Set<() => void>();

function notifyAll() {
    _listeners.forEach((fn) => fn());
}

// Capture the global prompt from index.html
if (typeof window !== 'undefined') {
    const captured = (window as any).__pwaInstallPrompt;
    if (captured) {
        _deferredPrompt = captured as BeforeInstallPromptEvent;
        (window as any).__pwaInstallPrompt = null;
    }
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        _deferredPrompt = e as BeforeInstallPromptEvent;
        notifyAll();
    });
    window.addEventListener('appinstalled', () => {
        _deferredPrompt = null;
        notifyAll();
    });
}

export function usePWAInstall() {
    const [, setTick] = useState(0);

    useEffect(() => {
        const update = () => setTick((t) => t + 1);
        _listeners.add(update);
        return () => { _listeners.delete(update); };
    }, []);

    const isInstalled = typeof window !== 'undefined' && window.matchMedia('(display-mode: standalone)').matches;

    const isIOS = typeof navigator !== 'undefined' &&
        (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));

    const canInstall = !isInstalled && (_deferredPrompt !== null || isIOS);

    const install = useCallback(async (): Promise<'accepted' | 'dismissed' | 'manual'> => {
        if (_deferredPrompt) {
            await _deferredPrompt.prompt();
            const { outcome } = await _deferredPrompt.userChoice;
            if (outcome === 'accepted') _deferredPrompt = null;
            notifyAll();
            return outcome;
        }
        return 'manual'; // show manual guide
    }, []);

    return { canInstall, isInstalled, isIOS, install };
}
