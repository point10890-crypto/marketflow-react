import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { adminAPI, AdminDashboard, fetchAuthAPI } from '@/lib/api';
import DashboardTab from './tabs/DashboardTab';
import { UsersTab } from './tabs/UsersTab';
import SubscriptionsTab from './tabs/SubscriptionsTab';
import SystemTab from './tabs/SystemTab';
import JobsTab from './tabs/JobsTab';
import ProExpiryTab from './ProExpiryTab';
import PurchaseAdminPage from '../community/PurchaseAdminPage';
import { ADMIN_TABS, type AdminTab } from './adminTabs';

/**
 * 관리자 페이지 셸 — 탭 네비게이션만 담당한다.
 * 각 탭의 구현은 ./tabs/ 아래 파일로 분리 (2026-08-11 간소화 리팩터링).
 */

export default function AdminPage() {
    const { token, user: authUser } = useAuth();
    const apiToken = token ?? undefined;
    const [activeTab, setActiveTab] = useState<AdminTab>('dashboard');
    const [dashData, setDashData] = useState<AdminDashboard | null>(null);
    const [pendingCount, setPendingCount] = useState(0);
    const [dashLoading, setDashLoading] = useState(true);
    const [dashError, setDashError] = useState('');
    const dashRequest = useRef(0);
    const [purchasePendingCount, setPurchasePendingCount] = useState<number | null>(null);
    const [purchaseCountError, setPurchaseCountError] = useState(false);
    const purchaseRequest = useRef(0);
    const purchaseToken = useRef(apiToken);
    purchaseToken.current = apiToken;

    const loadPurchaseCount = useCallback(async () => {
        if (apiToken !== purchaseToken.current) return;
        const requestId = ++purchaseRequest.current;
        try {
            const data = await fetchAuthAPI<{ pending_count: number }>('/api/community/purchases/summary', apiToken);
            if (!Number.isSafeInteger(data?.pending_count) || data.pending_count < 0) throw new Error('Invalid purchase count');
            if (requestId !== purchaseRequest.current || apiToken !== purchaseToken.current) return;
            setPurchasePendingCount(data.pending_count);
            setPurchaseCountError(false);
        } catch {
            if (requestId === purchaseRequest.current && apiToken === purchaseToken.current) setPurchaseCountError(true);
        }
    }, [apiToken]);

    useEffect(() => {
        setPurchasePendingCount(null);
        setPurchaseCountError(false);
        loadPurchaseCount();
        const onVisible = () => { if (document.visibilityState === 'visible') loadPurchaseCount(); };
        const timer = setInterval(onVisible, 60_000);
        document.addEventListener('visibilitychange', onVisible);
        window.addEventListener('focus', onVisible);
        return () => {
            purchaseRequest.current++;
            clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
            window.removeEventListener('focus', onVisible);
        };
    }, [loadPurchaseCount]);

    const purchaseBadgeLabel = purchasePendingCount === null
        ? `구매 승인 대기 ${purchaseCountError ? '확인 실패 · 구매 탭에서 다시 확인' : '확인 중'}`
        : `구매 승인 대기 ${purchasePendingCount}건${purchaseCountError ? ' · 갱신 실패, 이전 조회 결과' : ''}`;

    const loadDashboard = useCallback(async () => {
        const requestId = ++dashRequest.current;
        setDashLoading(true);
        try {
            const data = await adminAPI.getDashboard(apiToken);
            const requiredCounts = ['total_users', 'pro_users', 'premium_users', 'no_tier_users',
                'admin_users', 'pending_users', 'approved_users', 'suspended_users', 'pending_subscriptions'] as const;
            if (!data || !requiredCounts.every(key => Number.isFinite(data[key]) && data[key] >= 0)) {
                throw new Error('Invalid dashboard response');
            }
            if (requestId !== dashRequest.current) return;
            setDashData(data);
            setPendingCount(data.pending_subscriptions);
            setDashError('');
        } catch {
            if (requestId === dashRequest.current) setDashError('대시보드 데이터를 불러오지 못했습니다.');
        } finally {
            if (requestId === dashRequest.current) setDashLoading(false);
        }
    }, [apiToken]);

    // 대시보드 카운트는 승인/입금이 실시간으로 들어오므로 60초 주기 + 탭 복귀 시 갱신.
    // 백그라운드 탭에서는 폴링을 멈춰 불필요한 요청을 막는다.
    useEffect(() => {
        setDashData(null);
        setPendingCount(0);
        setDashError('');
        loadDashboard();
        const timer = setInterval(() => {
            if (document.visibilityState === 'visible') loadDashboard();
        }, 60_000);
        const onVisible = () => { if (document.visibilityState === 'visible') loadDashboard(); };
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            dashRequest.current++;
            clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [loadDashboard]);

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
            <div className="grid grid-cols-3 lg:grid-cols-7 gap-1 bg-white/[0.03] rounded-xl p-1 border border-white/[0.06]">
                {ADMIN_TABS.map(tab => (
                    <button
                        key={tab.key}
                        aria-pressed={activeTab === tab.key}
                        onClick={() => { setActiveTab(tab.key); if (tab.key === 'purchases') loadPurchaseCount(); }}
                        className={`flex items-center justify-center gap-1.5 px-2 py-2.5 rounded-lg text-xs sm:text-sm font-medium transition-all whitespace-nowrap ${
                            activeTab === tab.key
                                ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                                : 'text-gray-500 hover:text-white hover:bg-white/5 border border-transparent'
                        }`}
                    >
                        <i className={`fas ${tab.icon} text-xs`} />
                        <span>{tab.label}</span>
                        {tab.key === 'purchases' && (
                            <span role="status" aria-live="polite" aria-label={purchaseBadgeLabel} title={purchaseBadgeLabel}
                                className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${purchaseCountError
                                    ? 'bg-orange-500/20 text-orange-400'
                                    : purchasePendingCount === 0 ? 'bg-white/10 text-gray-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                                {purchasePendingCount ?? (purchaseCountError ? '?' : '…')}
                            </span>
                        )}
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
            {activeTab === 'dashboard' && <DashboardTab data={dashData} loading={dashLoading} error={dashError} onRetry={loadDashboard} onNavigate={setActiveTab} apiToken={apiToken} />}
            {activeTab === 'users' && <UsersTab apiToken={apiToken} currentUserId={authUser?.id} />}
            {activeTab === 'subscriptions' && <SubscriptionsTab apiToken={apiToken} onCountChange={setPendingCount} />}
            {activeTab === 'purchases' && <PurchaseAdminPage onBack={() => setActiveTab('dashboard')} onPurchasesChanged={loadPurchaseCount} />}
            {activeTab === 'pro' && <ProExpiryTab apiToken={apiToken} />}
            {activeTab === 'system' && <SystemTab token={token} />}
            {activeTab === 'jobs' && <JobsTab token={token} />}
        </div>
    );
}
