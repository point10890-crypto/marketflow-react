import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import InstallPrompt from '@/components/layout/InstallPrompt';
import { NotificationProvider } from '@/contexts/NotificationContext';
import { clearToken, getToken, getUser, saveUser, setToken } from '@/lib/auth';
import { authHeaders } from '@/lib/api';
import { safeGetItem, safeRemoveItem, safeSetItem } from '@/lib/safeStorage';

const pwaInstallMock = vi.hoisted(() => ({
    canInstall: true,
    isInstalled: false,
    isIOS: true,
    install: vi.fn(),
}));

vi.mock('@/hooks/usePWAInstall', () => ({
    usePWAInstall: () => pwaInstallMock,
}));

const originalLocalStorage = Object.getOwnPropertyDescriptor(window, 'localStorage');
const originalSessionStorage = Object.getOwnPropertyDescriptor(window, 'sessionStorage');

function restoreStorageDescriptors() {
    if (originalLocalStorage) Object.defineProperty(window, 'localStorage', originalLocalStorage);
    if (originalSessionStorage) Object.defineProperty(window, 'sessionStorage', originalSessionStorage);
}

function blockStorageProperty(area: 'localStorage' | 'sessionStorage') {
    Object.defineProperty(window, area, {
        configurable: true,
        get() {
            throw new DOMException('Storage access denied', 'SecurityError');
        },
    });
}

function quotaStorage(): Storage {
    const values = new Map<string, string>();
    return {
        get length() { return values.size; },
        clear: () => values.clear(),
        getItem: (key) => values.get(key) ?? null,
        key: (index) => Array.from(values.keys())[index] ?? null,
        removeItem: (key) => { values.delete(key); },
        setItem: () => { throw new DOMException('Storage quota exceeded', 'QuotaExceededError'); },
    };
}

function cleanKnownKeys() {
    for (const area of ['local', 'session'] as const) {
        for (const key of [
            'safe-storage-security-test',
            'safe-storage-quota-test',
            'auth_token',
            'auth_user',
            'auth_remember',
            'bitman_notifications',
            'install-dismissed',
        ]) {
            safeRemoveItem(area, key);
        }
    }
}

describe('Safari-safe browser storage', () => {
    beforeEach(() => {
        restoreStorageDescriptors();
        cleanKnownKeys();
        pwaInstallMock.canInstall = true;
        pwaInstallMock.isInstalled = false;
        pwaInstallMock.isIOS = true;
        pwaInstallMock.install.mockReset().mockResolvedValue('manual');
    });

    afterEach(() => {
        cleanup();
        vi.useRealTimers();
        restoreStorageDescriptors();
        cleanKnownKeys();
    });

    it('does not throw when Safari blocks access to the storage property', () => {
        blockStorageProperty('localStorage');
        blockStorageProperty('sessionStorage');

        expect(() => safeGetItem('local', 'safe-storage-security-test')).not.toThrow();
        expect(safeGetItem('local', 'safe-storage-security-test')).toBeNull();
        expect(safeSetItem('local', 'safe-storage-security-test', 'memory-value')).toBe(false);
        expect(safeGetItem('local', 'safe-storage-security-test')).toBe('memory-value');
        expect(() => safeRemoveItem('local', 'safe-storage-security-test')).not.toThrow();
        expect(safeGetItem('local', 'safe-storage-security-test')).toBeNull();
        expect(() => authHeaders()).not.toThrow();
        expect(authHeaders()).toEqual({});
    });

    it('retains a page-lifetime value when a storage write exceeds quota', () => {
        Object.defineProperty(window, 'localStorage', {
            configurable: true,
            value: quotaStorage(),
        });

        expect(safeSetItem('local', 'safe-storage-quota-test', 'fallback-value')).toBe(false);
        expect(safeGetItem('local', 'safe-storage-quota-test')).toBe('fallback-value');
    });

    it('falls back to sessionStorage when remembered auth cannot write locally', () => {
        Object.defineProperty(window, 'localStorage', {
            configurable: true,
            value: quotaStorage(),
        });
        const token = `7:${Math.floor(Date.now() / 1000) + 3600}:signature`;
        const user = {
            id: 7,
            email: 'ios@example.com',
            name: 'iOS User',
            tier: 'pro',
            role: 'user',
            status: 'approved',
        };

        expect(() => setToken(token, true)).not.toThrow();
        saveUser(user);

        expect(window.sessionStorage.getItem('auth_token')).toBe(token);
        expect(getToken()).toBe(token);
        expect(getUser()).toEqual(user);
        clearToken();
    });

    it('renders notifications when localStorage reads throw SecurityError', () => {
        blockStorageProperty('localStorage');

        expect(() => render(
            <NotificationProvider>
                <div>notification child</div>
            </NotificationProvider>,
        )).not.toThrow();
        expect(screen.getByText('notification child')).toBeInTheDocument();
    });

    it('shows and dismisses the install prompt when storage is blocked', () => {
        vi.useFakeTimers();
        blockStorageProperty('localStorage');
        render(<InstallPrompt />);

        act(() => vi.advanceTimersByTime(3000));
        expect(screen.getByText('BitMan 앱 설치')).toBeInTheDocument();

        fireEvent.click(screen.getAllByRole('button')[0]);
        expect(screen.queryByText('BitMan 앱 설치')).not.toBeInTheDocument();
    });

    it('does not advertise installation when the browser cannot install the PWA', () => {
        vi.useFakeTimers();
        pwaInstallMock.canInstall = false;

        render(<InstallPrompt />);
        act(() => vi.advanceTimersByTime(3000));

        expect(screen.queryByText('BitMan 앱 설치')).not.toBeInTheDocument();
    });
});
