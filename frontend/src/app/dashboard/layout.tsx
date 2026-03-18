'use client';

import { useState, useRef } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import BottomTabBar from '@/components/layout/BottomTabBar';
import MobileSubNav from '@/components/layout/MobileSubNav';
import { PullToRefreshProvider, PullIndicator } from '@/components/layout/PullToRefreshProvider';
import InstallPrompt from '@/components/layout/InstallPrompt';
import { usePullToRefresh } from '@/hooks/usePullToRefresh';
import { useSwipeNavigation } from '@/hooks/useSwipeNavigation';

const SWIPE_TABS = [
    { href: '/dashboard' },
    { href: '/dashboard/kr' },
    { href: '/dashboard/us' },
    { href: '/dashboard/crypto' },
    { href: '/dashboard/stock-analyzer' },
];

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const refreshFnRef = useRef<(() => Promise<void>) | null>(null);
    const pathname = usePathname() ?? '';

    const { pullDistance, isRefreshing } = usePullToRefresh(scrollRef, refreshFnRef.current);
    useSwipeNavigation(scrollRef, SWIPE_TABS);

    return (
        <PullToRefreshProvider onRefreshRef={refreshFnRef}>
            <div className="flex h-screen w-full bg-black overflow-hidden">
                {/* Desktop Sidebar */}
                <div className="hidden md:flex">
                    <Sidebar />
                </div>

                {/* Mobile Overlay Sidebar */}
                <Sidebar
                    mobile
                    isOpen={sidebarOpen}
                    onClose={() => setSidebarOpen(false)}
                />

                {/* Main Content */}
                <main className="flex-1 flex flex-col h-full overflow-hidden bg-[#09090b] relative">
                    <Header
                        onMenuClick={() => setSidebarOpen(true)}
                    />
                    <MobileSubNav />
                    <div
                        ref={scrollRef}
                        className="flex-1 overflow-y-auto p-3 md:p-6 pb-20 md:pb-6 scroll-smooth overscroll-contain relative"
                        style={pullDistance > 0 ? { transform: `translateY(${pullDistance}px)`, transition: 'none' } : { transition: 'transform 0.3s ease' }}
                    >
                        <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
                        <div key={pathname} className="page-enter">
                            {children}
                        </div>
                    </div>
                </main>

                {/* Mobile Bottom Tab Bar */}
                <BottomTabBar />
                <InstallPrompt />
            </div>
        </PullToRefreshProvider>
    );
}
