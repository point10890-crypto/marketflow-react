import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminAPI, AdminDashboard, AdminNotification } from '@/lib/api';

/**
 * 관리자 대시보드 탭 — "오늘 처리할 일" 중심의 간소화 레이아웃.
 *
 * 구성 (위 → 아래):
 *  1. 처리 대기 큐 — 액션이 필요한 항목만. 전부 0이면 "모두 처리 완료" 한 줄.
 *  2. 회원 현황 스트립 — 숫자 5개 한 줄 요약.
 *  3. 바로가기 — 사용자/구독/구매/시스템.
 *  4. 최근 알림.
 */

type AdminTabKey = 'dashboard' | 'users' | 'subscriptions' | 'pro' | 'system';

function notiIcon(type: string) {
    if (type === 'purchase_request') return 'fa-receipt text-yellow-400';
    if (type === 'subscription_request') return 'fa-credit-card text-purple-400';
    return 'fa-user-plus text-blue-400';
}

function notiTimeAgo(dateStr: string) {
    const diff = Date.now() - new Date(dateStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return '방금';
    if (m < 60) return `${m}분 전`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}시간 전`;
    const d = Math.floor(h / 24);
    return `${d}일 전`;
}

export default function DashboardTab({ data, onNavigate, apiToken }: {
    data: AdminDashboard | null;
    onNavigate: (tab: AdminTabKey) => void;
    apiToken?: string;
}) {
    const navigate = useNavigate();
    const [notifications, setNotifications] = useState<AdminNotification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [notiLoading, setNotiLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [listRes, countRes] = await Promise.all([
                    adminAPI.getNotifications(apiToken),
                    adminAPI.getUnreadCount(apiToken),
                ]);
                if (cancelled) return;
                setNotifications(listRes.notifications || []);
                setUnreadCount(countRes.unread_count || 0);
            } catch { /* */ }
            if (!cancelled) setNotiLoading(false);
        })();
        return () => { cancelled = true; };
    }, [apiToken]);

    const handleMarkRead = async (id: number) => {
        try {
            await adminAPI.markRead(id, apiToken);
            setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
            setUnreadCount(prev => Math.max(0, prev - 1));
        } catch { /* */ }
    };

    const handleMarkAllRead = async () => {
        try {
            await adminAPI.markAllRead(apiToken);
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
            setUnreadCount(0);
        } catch { /* */ }
    };

    // ── 1. 처리 대기 큐 ──────────────────────────────────────────────
    const actionItems = [
        {
            count: data?.pending_subscriptions || 0,
            label: '구독 승인 대기',
            sub: '입금 확인 후 승인 처리',
            icon: 'fa-credit-card', color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/25',
            tab: 'subscriptions' as AdminTabKey,
        },
        {
            count: data?.pending_signups || 0,
            label: '가입만 완료 · 플랜 미선택',
            sub: '이탈 가입자 팔로업 (카톡 안내)',
            icon: 'fa-user-clock', color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/25',
            tab: 'subscriptions' as AdminTabKey,
        },
        {
            count: data?.pro_expiring_soon || 0,
            label: 'Pro 만료 임박 (D-3)',
            sub: '갱신 안내 필요',
            icon: 'fa-hourglass-half', color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/25',
            tab: 'pro' as AdminTabKey,
        },
        {
            count: data?.churn?.expired_unrenewed ?? data?.expired_users ?? 0,
            label: '만료 · 재구독 대기',
            sub: '재구독 유도 팔로업 (원클릭 재활성화)',
            icon: 'fa-hourglass-end', color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/25',
            tab: 'subscriptions' as AdminTabKey,
        },
        {
            count: data?.aibain_expiring_soon || 0,
            label: 'AI Brain 만료 임박 (D-3)',
            sub: '애드온 갱신 안내',
            icon: 'fa-robot', color: 'text-cyan-300', bg: 'bg-cyan-500/10', border: 'border-cyan-500/25',
            tab: 'users' as AdminTabKey,
        },
    ].filter(item => item.count > 0);

    // ── 1b. 구독 매출 추정 — 현재 활성 구독 기준 클라이언트 계산 (표시 전용) ──
    // Pro 50,000원/30일 + AI Brain 40,000원/30일 반복, Ultra Pro 1,200,000원 1회.
    // 결제 원장이 아닌 회원 수 기반 추정치이므로 라벨에 '추정'을 명시한다.
    const proUsers = data?.pro_users || 0;
    const premiumUsers = data?.premium_users || 0;
    const aibainUsers = data?.aibain_active_users || 0;
    const recurringMonthly = proUsers * 50_000 + aibainUsers * 40_000;
    const lifetimeTotal = premiumUsers * 1_200_000;
    const revenueStats = [
        { label: '월 반복 매출 (추정)', value: `${recurringMonthly.toLocaleString()}원`, sub: `Pro ${proUsers} · AI Brain ${aibainUsers}`, color: 'text-emerald-300', icon: 'fa-arrows-rotate' },
        { label: 'Ultra Pro 누적 (추정)', value: `${lifetimeTotal.toLocaleString()}원`, sub: `Ultra Pro ${premiumUsers}명 × 120만원`, color: 'text-purple-300', icon: 'fa-gem' },
        { label: '갱신 위험 노출', value: `${((data?.churn?.expiring_d3 ?? 0) * 50_000 + (data?.aibain_expiring_soon ?? 0) * 40_000).toLocaleString()}원`, sub: `D-3 만료 임박 기준`, color: 'text-amber-300', icon: 'fa-triangle-exclamation' },
    ];

    // ── 2. 회원 현황 스트립 ───────────────────────────────────────────
    const memberStats = [
        { label: '전체', value: data?.total_users || 0, color: 'text-white' },
        { label: 'Pro', value: data?.pro_users || 0, color: 'text-amber-400' },
        { label: 'Ultra Pro', value: data?.premium_users || 0, color: 'text-purple-400' },
        { label: 'AI Brain', value: data?.aibain_active_users || 0, color: 'text-cyan-300' },
        { label: 'No Tier', value: data?.no_tier_users || 0, color: 'text-gray-400' },
    ];

    // ── 3. 바로가기 ──────────────────────────────────────────────────
    const shortcuts = [
        { label: '사용자 관리', icon: 'fa-users-cog', onClick: () => onNavigate('users') },
        { label: '구독 관리', icon: 'fa-credit-card', onClick: () => onNavigate('subscriptions') },
        { label: '구매 관리', icon: 'fa-receipt', onClick: () => navigate('/dashboard/community/formula-market/purchases') },
        { label: '시스템', icon: 'fa-server', onClick: () => onNavigate('system') },
    ];

    return (
        <>
            {/* 1. 처리 대기 큐 */}
            <div className="apple-glass rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.06]">
                    <i className="fas fa-inbox text-amber-400" />
                    <span className="text-sm font-semibold text-white">오늘 처리할 일</span>
                    {actionItems.length > 0 && (
                        <span className="px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold">
                            {actionItems.reduce((s, i) => s + i.count, 0)}
                        </span>
                    )}
                </div>
                {actionItems.length === 0 ? (
                    <div className="flex items-center gap-3 px-4 py-5">
                        <i className="fas fa-check-circle text-emerald-400 text-lg" />
                        <div>
                            <div className="text-sm text-white font-medium">모두 처리 완료</div>
                            <div className="text-xs text-gray-500">대기 중인 승인/팔로업이 없습니다</div>
                        </div>
                    </div>
                ) : (
                    <div className="divide-y divide-white/[0.04]">
                        {actionItems.map(item => (
                            <button
                                key={item.label}
                                onClick={() => onNavigate(item.tab)}
                                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.04] transition-colors text-left"
                            >
                                <div className={`w-9 h-9 ${item.bg} rounded-lg flex items-center justify-center shrink-0`}>
                                    <i className={`fas ${item.icon} ${item.color} text-sm`} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm text-white font-medium truncate">{item.label}</div>
                                    <div className="text-[11px] text-gray-500 truncate">{item.sub}</div>
                                </div>
                                <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${item.bg} ${item.color} border ${item.border}`}>
                                    {item.count}
                                </span>
                                <i className="fas fa-chevron-right text-gray-600 text-xs" />
                            </button>
                        ))}
                    </div>
                )}
            </div>

            {/* 1b. 구독 매출 추정 스트립 */}
            <div className="apple-glass rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/[0.06]">
                    <i className="fas fa-coins text-emerald-400 text-xs" />
                    <span className="text-xs font-semibold text-white">구독 매출 현황</span>
                    <span className="text-[9px] text-gray-600">활성 구독 수 기반 추정치</span>
                </div>
                <div className="grid grid-cols-3 divide-x divide-white/[0.06]">
                    {revenueStats.map(s => (
                        <div key={s.label} className="px-3 py-3 text-center">
                            <div className={`text-sm sm:text-base font-bold tabular-nums ${s.color}`}>
                                <i className={`fas ${s.icon} text-[10px] mr-1.5 opacity-70`} />
                                {s.value}
                            </div>
                            <div className="text-[10px] text-gray-500 mt-0.5">{s.label}</div>
                            <div className="text-[9px] text-gray-600 mt-0.5">{s.sub}</div>
                        </div>
                    ))}
                </div>
            </div>

            {/* 2. 회원 현황 스트립 */}
            <div className="apple-glass rounded-xl px-4 py-3">
                <div className="grid grid-cols-5 divide-x divide-white/[0.06]">
                    {memberStats.map(s => (
                        <button
                            key={s.label}
                            onClick={() => onNavigate('users')}
                            className="text-center py-1 hover:bg-white/[0.03] rounded-lg transition-colors"
                        >
                            <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
                            <div className="text-[10px] text-gray-500 mt-0.5">{s.label}</div>
                        </button>
                    ))}
                </div>
            </div>

            {/* 2b. 이탈(churn) 지표 — 만료→재구독 퍼널 */}
            <div className="apple-glass rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/[0.06]">
                    <i className="fas fa-arrows-rotate text-orange-400 text-xs" />
                    <span className="text-xs font-semibold text-white">구독 유지 · 재구독</span>
                </div>
                <div className="grid grid-cols-3 divide-x divide-white/[0.06]">
                    {[
                        { label: '만료 임박 D-3', value: data?.churn?.expiring_d3 ?? 0, color: 'text-red-400', icon: 'fa-hourglass-half', tab: 'pro' as AdminTabKey },
                        { label: '만료 후 미재구독', value: data?.churn?.expired_unrenewed ?? 0, color: 'text-orange-400', icon: 'fa-user-clock', tab: 'subscriptions' as AdminTabKey },
                        { label: '이번 달 재구독', value: data?.churn?.resubscribed_this_month ?? 0, color: 'text-emerald-400', icon: 'fa-rotate-right', tab: 'subscriptions' as AdminTabKey },
                    ].map(s => (
                        <button
                            key={s.label}
                            onClick={() => onNavigate(s.tab)}
                            className="text-center py-3 hover:bg-white/[0.03] transition-colors"
                        >
                            <div className={`text-lg font-bold ${s.color}`}>
                                <i className={`fas ${s.icon} text-[10px] mr-1.5 opacity-70`} />
                                {s.value}
                            </div>
                            <div className="text-[10px] text-gray-500 mt-0.5">{s.label}</div>
                        </button>
                    ))}
                </div>
            </div>

            {/* 3. 바로가기 */}
            <div className="grid grid-cols-4 gap-2">
                {shortcuts.map(s => (
                    <button
                        key={s.label}
                        onClick={s.onClick}
                        className="apple-glass rounded-xl py-3 px-2 hover:bg-white/5 hover:border-white/10 transition-colors text-center"
                    >
                        <i className={`fas ${s.icon} text-gray-400 text-sm mb-1.5 block`} />
                        <span className="text-[11px] text-gray-300 font-medium">{s.label}</span>
                    </button>
                ))}
            </div>

            {/* 4. 최근 알림 */}
            <div className="apple-glass rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
                    <div className="flex items-center gap-2">
                        <i className="fas fa-bell text-red-400" />
                        <span className="text-sm font-semibold text-white">최근 알림</span>
                        {unreadCount > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 text-[10px] font-bold">
                                {unreadCount}
                            </span>
                        )}
                    </div>
                    {unreadCount > 0 && (
                        <button
                            onClick={handleMarkAllRead}
                            className="text-[11px] text-gray-500 hover:text-white transition-colors"
                        >
                            모두 읽음
                        </button>
                    )}
                </div>

                {notiLoading ? (
                    <div className="p-6 text-center text-gray-500 text-sm">
                        <i className="fas fa-spinner fa-spin mr-1" /> 로딩 중...
                    </div>
                ) : notifications.length === 0 ? (
                    <div className="p-6 text-center text-gray-600 text-sm">
                        <i className="fas fa-bell-slash mr-1" /> 알림이 없습니다
                    </div>
                ) : (
                    <div className="divide-y divide-white/[0.04]">
                        {notifications.slice(0, 10).map(n => (
                            <div
                                key={n.id}
                                className={`flex items-start gap-3 px-4 py-3 transition-colors ${
                                    n.is_read ? 'opacity-60' : 'bg-white/[0.02]'
                                }`}
                            >
                                <div className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center flex-shrink-0 mt-0.5">
                                    <i className={`fas ${notiIcon(n.type)} text-xs`} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm text-white font-medium truncate">{n.title}</div>
                                    <div className="text-xs text-gray-400 truncate mt-0.5">{n.message}</div>
                                    <div className="text-[10px] text-gray-600 mt-1">{notiTimeAgo(n.created_at)}</div>
                                </div>
                                {!n.is_read && (
                                    <button
                                        onClick={() => handleMarkRead(n.id)}
                                        className="text-[10px] text-gray-500 hover:text-white transition-colors flex-shrink-0 mt-1"
                                        title="읽음 처리"
                                    >
                                        <i className="fas fa-check" />
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </>
    );
}
