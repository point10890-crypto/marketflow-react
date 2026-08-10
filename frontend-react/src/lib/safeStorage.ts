export type StorageArea = 'local' | 'session';

const memoryFallback: Record<StorageArea, Map<string, string>> = {
    local: new Map<string, string>(),
    session: new Map<string, string>(),
};

function getBrowserStorage(area: StorageArea): Storage | null {
    if (typeof window === 'undefined') return null;

    try {
        return area === 'local' ? window.localStorage : window.sessionStorage;
    } catch {
        // Safari privacy settings and some in-app WebViews can throw while
        // merely reading the storage property.
        return null;
    }
}

export function safeGetItem(area: StorageArea, key: string): string | null {
    const fallback = memoryFallback[area];
    if (fallback.has(key)) return fallback.get(key) ?? null;

    const storage = getBrowserStorage(area);
    if (!storage) return null;

    try {
        return storage.getItem(key);
    } catch {
        return null;
    }
}

/**
 * Store a value without throwing.
 *
 * The return value reports whether browser storage persisted the value. When
 * it is false, the value remains available from an in-memory fallback for the
 * lifetime of the current page.
 */
export function safeSetItem(area: StorageArea, key: string, value: string): boolean {
    const fallback = memoryFallback[area];
    const storage = getBrowserStorage(area);

    if (storage) {
        try {
            storage.setItem(key, value);
            fallback.delete(key);
            return true;
        } catch {
            // QuotaExceededError / SecurityError: retain a page-lifetime copy.
        }
    }

    fallback.set(key, value);
    return false;
}

export function safeRemoveItem(area: StorageArea, key: string): boolean {
    memoryFallback[area].delete(key);
    const storage = getBrowserStorage(area);
    if (!storage) return false;

    try {
        storage.removeItem(key);
        return true;
    } catch {
        return false;
    }
}
