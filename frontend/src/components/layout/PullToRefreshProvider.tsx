'use client';

import { createContext, useContext, useCallback, useRef, useEffect, type ReactNode } from 'react';

interface PullToRefreshContextType {
    registerRefresh: (fn: () => Promise<void>) => void;
}

const PullToRefreshContext = createContext<PullToRefreshContextType>({
    registerRefresh: () => {},
});

export function PullToRefreshProvider({
    children,
    onRefreshRef,
}: {
    children: ReactNode;
    onRefreshRef: React.MutableRefObject<(() => Promise<void>) | null>;
}) {
    const registerRefresh = useCallback(
        (fn: () => Promise<void>) => {
            onRefreshRef.current = fn;
        },
        [onRefreshRef]
    );

    return (
        <PullToRefreshContext.Provider value={{ registerRefresh }}>
            {children}
        </PullToRefreshContext.Provider>
    );
}

export function usePullToRefreshRegister(fn: () => Promise<void>) {
    const { registerRefresh } = useContext(PullToRefreshContext);
    const stableFn = useRef(fn);
    stableFn.current = fn;

    useEffect(() => {
        registerRefresh(() => stableFn.current());
    }, [registerRefresh]);
}

// Pull indicator component
export function PullIndicator({
    pullDistance,
    isRefreshing,
    threshold = 80,
}: {
    pullDistance: number;
    isRefreshing: boolean;
    threshold?: number;
}) {
    if (pullDistance <= 0 && !isRefreshing) return null;

    const progress = Math.min(pullDistance / threshold, 1);
    const rotation = pullDistance * 3;

    return (
        <div
            className="absolute left-1/2 -translate-x-1/2 z-50 pointer-events-none md:hidden"
            style={{
                top: Math.max(pullDistance - 36, 4),
                opacity: isRefreshing ? 1 : progress,
                transition: isRefreshing ? 'none' : 'opacity 0.15s ease',
            }}
        >
            <div
                className={`w-8 h-8 rounded-full border-2 border-white/20 border-t-white/60 ${isRefreshing ? 'animate-spin' : ''}`}
                style={{
                    transform: isRefreshing ? undefined : `rotate(${rotation}deg)`,
                }}
            />
        </div>
    );
}
