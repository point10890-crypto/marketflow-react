import { useState, useRef, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import BottomTabBar from './BottomTabBar';
import MobileSubNav from './MobileSubNav';
import MobileDashboardRail from './MobileDashboardRail';
import { PullToRefreshProvider, PullIndicator } from './PullToRefreshProvider';
import InstallPrompt from './InstallPrompt';
import NotificationToast from '@/components/ui/NotificationToast';
import { usePullToRefresh } from '@/hooks/usePullToRefresh';
import { useSwipeNavigation } from '@/hooks/useSwipeNavigation';
import { useSmartRefresh } from '@/hooks/useAutoRefresh';
import { useNotification } from '@/contexts/NotificationContext';
import { PageErrorBoundary } from '@/components/PageErrorBoundary';
import { ClawBrandBar } from '@/components/claw/ClawHero';
import { useClawState } from '@/hooks/useClawState';
import { useAuth } from '@/contexts/AuthContext';

const SWIPE_TABS = [
    { href: '/dashboard' },
    { href: '/dashboard/vcp-enhanced' },
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
    const { token } = useAuth();
    const claw = useClawState(token);
    // 메인 타이틀(브랜드 바)은 모든 대시보드 페이지에 고정. Claw LIVE 페이지는 자체 풀 히어로, W Pattern은 전체화면 캔버스라 제외
    const showBrandBar = pathname !== '/dashboard/kr/claw' && !pathname.startsWith('/dashboard/wave');

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
    const isWavePage = location.pathname.startsWith('/dashboard/wave');
    const isSwipeTabPage = SWIPE_TABS.some((tab) => pathname === tab.href);
    useSwipeNavigation(scrollRef, SWIPE_TABS, isWavePage || !isSwipeTabPage);

    return (
        <PullToRefreshProvider onRefreshRef={refreshFnRef}>
            <div className="claw-theme flex h-screen w-full bg-black overflow-hidden">
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
                <main className="claw-shell-bg flex-1 min-w-0 flex flex-col h-full overflow-hidden relative">
                    <Header
                        onMenuClick={() => setSidebarOpen(true)}
                    />
                    <MobileDashboardRail />
                    <MobileSubNav />
                    <div
                        ref={scrollRef}
                        className={`dashboard-shell-scroll flex-1 min-w-0 ${isWavePage ? 'overflow-hidden p-0' : 'overflow-x-hidden overflow-y-auto px-2.5 pt-2.5 pb-32 sm:p-3 md:p-6 md:pb-6'} scroll-smooth overscroll-contain relative`}
                    >
                        <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
                        <div
                            className={isWavePage ? 'h-full' : ''}
                            style={pullDistance > 0
                                ? { transform: `translateY(${pullDistance}px)`, transition: 'none' }
                                : { transition: 'transform 0.3s ease' }}
                        >
                            {showBrandBar && <ClawBrandBar data={claw} />}
                            <PageErrorBoundary resetKey={pathname}>
                                <div key={pathname} className={`page-enter dashboard-mobile-page ${isWavePage ? 'h-full' : ''}`}>
                                    <Outlet />
                                </div>
                            </PageErrorBoundary>
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
