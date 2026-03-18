'use client';

import { useEffect, useRef } from 'react';
import { useRouter, usePathname } from 'next/navigation';

interface SwipeTab {
    href: string;
}

export function useSwipeNavigation(
    scrollRef: React.RefObject<HTMLDivElement | null>,
    tabs: SwipeTab[],
    minSwipeDistance: number = 80,
    maxVerticalOffset: number = 50
) {
    const router = useRouter();
    const pathname = usePathname() ?? '';
    const startX = useRef(0);
    const startY = useRef(0);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        // Only enable on mobile
        if (window.innerWidth >= 768) return;

        const onTouchStart = (e: TouchEvent) => {
            const touch = e.touches[0];
            startX.current = touch.clientX;
            startY.current = touch.clientY;
        };

        const onTouchEnd = (e: TouchEvent) => {
            const touch = e.changedTouches[0];
            const deltaX = touch.clientX - startX.current;
            const deltaY = Math.abs(touch.clientY - startY.current);

            // Ignore vertical swipes
            if (deltaY > maxVerticalOffset) return;

            // Ignore swipes near screen edges (browser back gesture zone)
            if (startX.current < 20 || startX.current > window.innerWidth - 20) return;

            // Check minimum distance
            if (Math.abs(deltaX) < minSwipeDistance) return;

            // Find current tab index
            const currentIndex = tabs.findIndex(
                (t) => pathname === t.href || pathname.startsWith(t.href + '/')
            );
            if (currentIndex === -1) return;

            if (deltaX < 0 && currentIndex < tabs.length - 1) {
                // Swipe left → next tab
                router.push(tabs[currentIndex + 1].href);
            } else if (deltaX > 0 && currentIndex > 0) {
                // Swipe right → prev tab
                router.push(tabs[currentIndex - 1].href);
            }
        };

        el.addEventListener('touchstart', onTouchStart, { passive: true });
        el.addEventListener('touchend', onTouchEnd, { passive: true });

        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('touchend', onTouchEnd);
        };
    }, [scrollRef, tabs, pathname, router, minSwipeDistance, maxVerticalOffset]);
}
