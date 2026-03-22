import { useState, useRef, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import BottomTabBar from './BottomTabBar';
import MobileSubNav from './MobileSubNav';
import { PullToRefreshProvider, PullIndicator } from './PullToRefreshProvider';
import InstallPrompt from './InstallPrompt';
import NotificationToast from '@/components/ui/NotificationToast';
import { usePullToRefresh } from '@/hooks/usePullToRefresh';
import { useSwipeNavigation } from '@/hooks/useSwipeNavigation';
import { useSmartRefresh } from '@/hooks/useAutoRefresh';
import { useNotification } from '@/contexts/NotificationContext';

const SWIPE_TABS = [
    { href: '/dashboard' },
    { href: '/dashboard/kr' },
    { href: '/dashboard/us' },
    { href: '/dashboard/crypto' },
    { href: '/dashboard/stock-analyzer' },
];

const FILE_LABELS: Record<string, { title: string; message: string; link: string }> = {
    'jongga_v2_latest.json': { title: '종가베팅 업데이트', message: '새로운 종가베팅 시그널이 도착했습니다', link: '/dashboard/kr/closing-bet' },
    'vcp_kr_latest.json': { title: 'KR VCP 업데이트', message: 'KR VCP 시그널이 갱신되었습니다', link: '/dashboard/kr/vcp' },
    'vcp_us_latest.json': { title: 'US VCP 업데이트', message: 'US VCP 시그널이 갱신되었습니다', link: '/dashboard/us/vcp' },
    'vcp_crypto_latest.json': { title: 'Crypto VCP 업데이트', message: 'Crypto VCP 시그널이 갱신되었습니다', link: '/dashboard/crypto/signals' },
    'market_briefing.json': { title: 'US 브리핑 업데이트', message: 'AI 마켓 브리핑이 갱신되었습니다', link: '/dashboard/us' },
    'crypto_briefing.json': { title: 'Crypto 브리핑', message: '크립토 브리핑이 갱신되었습니다', link: '/dashboard/crypto' },
};

const WATCH_FILES = Object.keys(FILE_LABELS);

export default function DashboardLayout() {
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const refreshFnRef = useRef<(() => Promise<void>) | null>(null);
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const { notify } = useNotification();

    // 전역 데이터 변경 감지 → 알림 발생
    const handleDataChanged = useCallback((changedFiles: string[]) => {
        for (const file of changedFiles) {
            const label = FILE_LABELS[file];
            if (label) {
                notify({ type: 'alert', title: label.title, message: label.message, link: label.link });
            }
        }
    }, [notify]);

    useSmartRefresh(
        () => {}, // 전역 레벨에서는 refetch 안 함 (개별 페이지가 처리)
        WATCH_FILES,
        15000,
        true,
        handleDataChanged
    );

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
                        className="flex-1 overflow-y-auto p-3 md:p-6 pb-24 md:pb-6 scroll-smooth overscroll-contain relative"
                        style={pullDistance > 0 ? { transform: `translateY(${pullDistance}px)`, transition: 'none' } : { transition: 'transform 0.3s ease' }}
                    >
                        <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
                        <div key={pathname} className="page-enter">
                            <Outlet />
                        </div>
                    </div>
                </main>

                {/* Mobile Bottom Tab Bar */}
                <BottomTabBar />
                <InstallPrompt />
                <NotificationToast />
            </div>
        </PullToRefreshProvider>
    );
}
