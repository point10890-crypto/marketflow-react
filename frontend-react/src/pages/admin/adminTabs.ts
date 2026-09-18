export type AdminTab = 'dashboard' | 'users' | 'subscriptions' | 'purchases' | 'pro' | 'system' | 'jobs';

export const ADMIN_TABS: { key: AdminTab; label: string; icon: string }[] = [
    { key: 'dashboard', label: '대시보드', icon: 'fa-shield-alt' },
    { key: 'users', label: '사용자', icon: 'fa-users-cog' },
    { key: 'subscriptions', label: '구독', icon: 'fa-credit-card' },
    { key: 'purchases', label: '구매', icon: 'fa-receipt' },
    { key: 'pro', label: 'Pro 관리', icon: 'fa-hourglass-half' },
    { key: 'system', label: '시스템', icon: 'fa-server' },
    { key: 'jobs', label: '잡 상태', icon: 'fa-clock' },
];
