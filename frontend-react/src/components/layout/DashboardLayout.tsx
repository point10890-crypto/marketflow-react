import { useState, useRef, useCallback, useLayoutEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import BottomTabBar from './BottomTabBar';
import MobileSubNav from './MobileSubNav';
import MobileDashboardRail from './MobileDashboardRail';
import { PullToRefreshProvider } from './PullToRefreshProvider';
import InstallPrompt from './InstallPrompt';
import NotificationToast from '@/components/ui/NotificationToast';
import { useSmartRefresh } from '@/hooks/useAutoRefresh';
import { useNotification } from '@/contexts/NotificationContext';
import { PageErrorBoundary } from '@/components/PageErrorBoundary';
import { ClawBrandBar } from '@/components/claw/ClawHero';
import RenewalBanner from './RenewalBanner';
import { useClawState } from '@/hooks/useClawState';
import { useAuth } from '@/contexts/AuthContext';

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
    const [installPromptVisible, setInstallPromptVisible] = useState(false);
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

    const isWavePage = location.pathname.startsWith('/dashboard/wave');

    // DashboardLayout stays mounted while child routes change. Reset the shared
    // scroller before paint so a new page never inherits the previous page's
    // vertical or horizontal position.
    useLayoutEffect(() => {
        const scroller = scrollRef.current;
        if (!scroller) return;
        scroller.scrollTop = 0;
        scroller.scrollLeft = 0;
    }, [pathname]);

    return (
        <PullToRefreshProvider onRefreshRef={refreshFnRef}>
            <div className={`claw-theme flex h-[100dvh] min-h-0 w-full bg-black overflow-hidden ${installPromptVisible ? 'dashboard-install-prompt-visible' : ''}`}>
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
                <main className="claw-shell-bg flex-1 min-w-0 min-h-0 flex flex-col h-full overflow-hidden relative">
                    <Header
                        onMenuClick={() => setSidebarOpen(true)}
                    />
                    <MobileDashboardRail />
                    <MobileSubNav />
                    <div
                        ref={scrollRef}
                        className={`dashboard-shell-scroll flex-1 min-w-0 min-h-0 ${isWavePage ? 'dashboard-wave-scroll overflow-hidden p-0' : 'dashboard-standard-scroll overflow-x-hidden overflow-y-auto px-2.5 pt-2.5 pb-32 sm:p-3 md:p-6 md:pb-6'} relative`}
                    >
                        <div className={isWavePage ? 'h-full min-h-0' : ''}>
                            {!isWavePage && <RenewalBanner />}
                            {showBrandBar && <ClawBrandBar key={pathname} data={claw} />}
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
                <InstallPrompt onVisibilityChange={setInstallPromptVisible} />
                <NotificationToast />
            </div>
        </PullToRefreshProvider>
    );
}
