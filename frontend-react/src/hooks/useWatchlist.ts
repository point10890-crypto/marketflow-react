import { useState, useCallback } from 'react';

export interface WatchItem {
    code: string;
    name: string;
    grade: string;
    scoreTotal: number;
    entryPrice: number;
    stopPrice: number;
    targetPrice: number;
    changePct: number;
    market: string;
    addedAt: string;
}

const STORAGE_KEY = 'bitman_watchlist_v1';

function loadFromStorage(): WatchItem[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch {
        return [];
    }
}

function saveToStorage(items: WatchItem[]): void {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch { /* storage full or unavailable */ }
}

export function useWatchlist() {
    const [watchlist, setWatchlist] = useState<WatchItem[]>(loadFromStorage);

    const add = useCallback((item: Omit<WatchItem, 'addedAt'>) => {
        setWatchlist(prev => {
            const filtered = prev.filter(w => w.code !== item.code);
            const next = [{ ...item, addedAt: new Date().toISOString() }, ...filtered];
            saveToStorage(next);
            return next;
        });
    }, []);

    const remove = useCallback((code: string) => {
        setWatchlist(prev => {
            const next = prev.filter(w => w.code !== code);
            saveToStorage(next);
            return next;
        });
    }, []);

    const toggle = useCallback((item: Omit<WatchItem, 'addedAt'>) => {
        setWatchlist(prev => {
            const exists = prev.some(w => w.code === item.code);
            const next = exists
                ? prev.filter(w => w.code !== item.code)
                : [{ ...item, addedAt: new Date().toISOString() }, ...prev];
            saveToStorage(next);
            return next;
        });
    }, []);

    const isWatched = useCallback((code: string): boolean => {
        return watchlist.some(w => w.code === code);
    }, [watchlist]);

    const clear = useCallback(() => {
        setWatchlist([]);
        saveToStorage([]);
    }, []);

    return { watchlist, add, remove, toggle, isWatched, clear };
}
