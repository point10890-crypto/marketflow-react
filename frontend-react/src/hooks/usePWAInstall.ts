import { useState, useEffect, useCallback } from 'react';

interface BeforeInstallPromptEvent extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let _deferredPrompt: BeforeInstallPromptEvent | null = null;
let _installedThisSession = false;
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
        _installedThisSession = false;
        _deferredPrompt = e as BeforeInstallPromptEvent;
        notifyAll();
    });
    window.addEventListener('appinstalled', () => {
        _deferredPrompt = null;
        _installedThisSession = true;
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

    const isStandaloneDisplay = typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(display-mode: standalone)').matches;
    const isIOSStandalone = typeof navigator !== 'undefined' &&
        Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
    const isInstalled = _installedThisSession || isStandaloneDisplay || isIOSStandalone;

    const isIOS = typeof navigator !== 'undefined' &&
        (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1));

    const canInstall = !isInstalled && (_deferredPrompt !== null || isIOS);

    const install = useCallback(async (): Promise<'accepted' | 'dismissed' | 'manual'> => {
        const prompt = _deferredPrompt;
        if (prompt) {
            // beforeinstallprompt events are single-use, regardless of outcome.
            _deferredPrompt = null;
            notifyAll();
            try {
                await prompt.prompt();
                const { outcome } = await prompt.userChoice;
                if (outcome === 'accepted') _installedThisSession = true;
                notifyAll();
                return outcome;
            } catch {
                return 'manual';
            }
        }
        return 'manual'; // show manual guide
    }, []);

    return { canInstall, isInstalled, isIOS, install };
}
