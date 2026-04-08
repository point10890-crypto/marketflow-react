import { useRef, useState, useEffect, useCallback, type RefObject } from 'react';

interface PullToRefreshResult {
    pullDistance: number;
    isRefreshing: boolean;
}

export function usePullToRefresh(
    scrollRef: RefObject<HTMLDivElement | null>,
    onRefresh: (() => Promise<void>) | null,
    threshold: number = 80
): PullToRefreshResult {
    const [pullDistance, setPullDistance] = useState(0);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const startY = useRef(0);
    const pulling = useRef(false);
    const pullDistanceRef = useRef(0);
    const isRefreshingRef = useRef(false);
    const onRefreshRef = useRef(onRefresh);

    onRefreshRef.current = onRefresh;
    isRefreshingRef.current = isRefreshing;

    const handleRefresh = useCallback(async () => {
        const fn = onRefreshRef.current;
        if (!fn || isRefreshingRef.current) return;
        setIsRefreshing(true);
        try {
            await fn();
        } finally {
            setIsRefreshing(false);
            pullDistanceRef.current = 0;
            setPullDistance(0);
        }
    }, []);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        // Only enable on mobile
        if (window.innerWidth >= 768) return;

        const onTouchMove = (e: TouchEvent) => {
            if (!pulling.current || isRefreshingRef.current) return;
            const deltaY = e.touches[0].clientY - startY.current;
            if (deltaY <= 0 || el.scrollTop > 0) {
                // No longer pulling — detach touchmove so browser owns the scroll.
                pulling.current = false;
                el.removeEventListener('touchmove', onTouchMove);
                return;
            }
            const dampened = Math.min(deltaY * 0.4, threshold * 1.5);
            pullDistanceRef.current = dampened;
            setPullDistance(dampened);
            if (dampened > 10) {
                e.preventDefault();
            }
        };

        const onTouchStart = (e: TouchEvent) => {
            // Only arm pull-to-refresh when starting at the very top.
            // Attaching touchmove dynamically (only when armed) lets the browser
            // handle scroll natively the rest of the time — no iOS boundary lock.
            if (el.scrollTop <= 0 && !isRefreshingRef.current && onRefreshRef.current) {
                startY.current = e.touches[0].clientY;
                pulling.current = true;
                el.addEventListener('touchmove', onTouchMove, { passive: false });
            }
        };

        const onTouchEnd = () => {
            el.removeEventListener('touchmove', onTouchMove);
            if (!pulling.current) return;
            pulling.current = false;
            if (pullDistanceRef.current >= threshold) {
                handleRefresh();
            } else if (pullDistanceRef.current !== 0) {
                pullDistanceRef.current = 0;
                setPullDistance(0);
            }
        };

        el.addEventListener('touchstart', onTouchStart, { passive: true });
        el.addEventListener('touchend', onTouchEnd, { passive: true });
        el.addEventListener('touchcancel', onTouchEnd, { passive: true });

        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('touchmove', onTouchMove);
            el.removeEventListener('touchend', onTouchEnd);
            el.removeEventListener('touchcancel', onTouchEnd);
        };
    }, [scrollRef, threshold, handleRefresh]);

    return { pullDistance, isRefreshing };
}
