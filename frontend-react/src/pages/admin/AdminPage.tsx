import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { adminAPI, AdminDashboard } from '@/lib/api';
import DashboardTab from './tabs/DashboardTab';
import { UsersTab } from './tabs/UsersTab';
import SubscriptionsTab from './tabs/SubscriptionsTab';
import SystemTab from './tabs/SystemTab';
import ProExpiryTab from './ProExpiryTab';

/**
 * 관리자 페이지 셸 — 탭 네비게이션만 담당한다.
 * 각 탭의 구현은 ./tabs/ 아래 파일로 분리 (2026-08-11 간소화 리팩터링).
 */

type AdminTab = 'dashboard' | 'users' | 'subscriptions' | 'pro' | 'system';

const TABS: { key: AdminTab; label: string; icon: string }[] = [
    { key: 'dashboard', label: '대시보드', icon: 'fa-shield-alt' },
    { key: 'users', label: '사용자', icon: 'fa-users-cog' },
    { key: 'subscriptions', label: '구독', icon: 'fa-credit-card' },
    { key: 'pro', label: 'Pro 관리', icon: 'fa-hourglass-half' },
    { key: 'system', label: '시스템', icon: 'fa-server' },
];

export default function AdminPage() {
    const { token, user: authUser } = useAuth();
    const apiToken = token ?? undefined;
    const [activeTab, setActiveTab] = useState<AdminTab>('dashboard');
    const [dashData, setDashData] = useState<AdminDashboard | null>(null);
    const [pendingCount, setPendingCount] = useState(0);

    // 대시보드 카운트는 승인/입금이 실시간으로 들어오므로 60초 주기 + 탭 복귀 시 갱신.
    // 백그라운드 탭에서는 폴링을 멈춰 불필요한 요청을 막는다.
    useEffect(() => {
        let cancelled = false;
        const load = () => {
            adminAPI.getDashboard(apiToken).then(d => {
                if (cancelled) return;
                setDashData(d);
                setPendingCount(d?.pending_subscriptions || 0);
            }).catch(() => {});
        };
        load();
        const timer = setInterval(() => {
            if (document.visibilityState === 'visible') load();
        }, 60_000);
        const onVisible = () => { if (document.visibilityState === 'visible') load(); };
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            cancelled = true;
            clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [apiToken]);

    return (
        <div className="space-y-5">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">관리자 대시보드</h1>
                <span className="text-xs text-red-400 bg-red-500/10 px-3 py-1 rounded-full font-semibold">
                    <i className="fas fa-shield-alt mr-1" /> 관리자 전용
                </span>
            </div>

            {/* Tab Navigation */}
            <div className="grid grid-cols-5 gap-1 bg-white/[0.03] rounded-xl p-1 border border-white/[0.06]">
                {TABS.map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`flex items-center justify-center gap-1.5 px-2 py-2.5 rounded-lg text-xs sm:text-sm font-medium transition-all whitespace-nowrap ${
                            activeTab === tab.key
                                ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                                : 'text-gray-500 hover:text-white hover:bg-white/5 border border-transparent'
                        }`}
                    >
                        <i className={`fas ${tab.icon} text-xs`} />
                        <span>{tab.label}</span>
                        {tab.key === 'subscriptions' && pendingCount > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400 text-[10px] font-bold">
                                {pendingCount}
                            </span>
                        )}
                        {tab.key === 'subscriptions' && (dashData?.expired_users ?? 0) > 0 && (
                            <span title={`만료 · 재구독 대기 ${dashData?.expired_users}명`}
                                  className="px-1.5 py-0.5 rounded-full bg-orange-500/20 text-orange-400 text-[10px] font-bold">
                                {dashData?.expired_users}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === 'dashboard' && <DashboardTab data={dashData} onNavigate={setActiveTab} apiToken={apiToken} />}
            {activeTab === 'users' && <UsersTab apiToken={apiToken} currentUserId={authUser?.id} />}
            {activeTab === 'subscriptions' && <SubscriptionsTab apiToken={apiToken} onCountChange={setPendingCount} />}
            {activeTab === 'pro' && <ProExpiryTab apiToken={apiToken} />}
            {activeTab === 'system' && <SystemTab token={token} />}
        </div>
    );
}
