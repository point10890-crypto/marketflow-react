import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { adminAPI, AdminDashboard, AdminUser, SubscriptionRequest, fetchAuthAPI, API_BASE } from '@/lib/api';

type AdminTab = 'dashboard' | 'users' | 'subscriptions' | 'system';

const TABS: { key: AdminTab; label: string; icon: string }[] = [
    { key: 'dashboard', label: '대시보드', icon: 'fa-shield-alt' },
    { key: 'users', label: '사용자', icon: 'fa-users-cog' },
    { key: 'subscriptions', label: '구독', icon: 'fa-credit-card' },
    { key: 'system', label: '시스템', icon: 'fa-server' },
];

// ── Main Admin Page ──────────────────────────────────────────────────────────

export default function AdminPage() {
    const { token } = useAuth();
    const apiToken = token ?? undefined;
    const [activeTab, setActiveTab] = useState<AdminTab>('dashboard');
    const [dashData, setDashData] = useState<AdminDashboard | null>(null);
    const [pendingCount, setPendingCount] = useState(0);

    useEffect(() => {
        adminAPI.getDashboard(apiToken).then(d => {
            setDashData(d);
            setPendingCount(d?.pending_subscriptions || 0);
        }).catch(() => {});
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
            <div className="grid grid-cols-4 gap-1 bg-white/[0.03] rounded-xl p-1 border border-white/[0.06]">
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
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === 'dashboard' && <DashboardTab data={dashData} onNavigate={setActiveTab} />}
            {activeTab === 'users' && <UsersTab apiToken={apiToken} />}
            {activeTab === 'subscriptions' && <SubscriptionsTab apiToken={apiToken} onCountChange={setPendingCount} />}
            {activeTab === 'system' && <SystemTab token={token} />}
        </div>
    );
}

// ── Dashboard Tab ────────────────────────────────────────────────────────────

function DashboardTab({ data, onNavigate }: { data: AdminDashboard | null; onNavigate: (tab: AdminTab) => void }) {
    const navigate = useNavigate();
    const stats = [
        { label: 'Total Users', value: data?.total_users || 0, icon: 'fa-users', color: 'text-blue-400', bg: 'bg-blue-500/10', tab: 'users' as AdminTab },
        { label: 'Pro Users', value: data?.pro_users || 0, icon: 'fa-crown', color: 'text-yellow-400', bg: 'bg-yellow-500/10', tab: 'users' as AdminTab },
        { label: 'Ultra Pro', value: data?.premium_users || 0, icon: 'fa-gem', color: 'text-purple-400', bg: 'bg-purple-500/10', tab: 'users' as AdminTab },
        { label: 'No Tier', value: data?.no_tier_users || 0, icon: 'fa-user-clock', color: 'text-gray-400', bg: 'bg-gray-500/10', tab: 'users' as AdminTab },
        { label: 'Pending Subs', value: data?.pending_subscriptions || 0, icon: 'fa-clock', color: 'text-orange-400', bg: 'bg-orange-500/10', tab: 'subscriptions' as AdminTab },
        { label: '구매 승인', value: '—', icon: 'fa-receipt', color: 'text-yellow-400', bg: 'bg-yellow-500/10', tab: null as any, route: '/dashboard/community/formula-market/purchases' },
    ];

    const links = [
        { tab: 'users' as AdminTab, icon: 'fa-users-cog', label: '사용자 관리', desc: '역할, 등급, 권한 관리' },
        { tab: 'subscriptions' as AdminTab, icon: 'fa-credit-card', label: '구독 관리', desc: data?.pending_subscriptions ? `${data.pending_subscriptions}건 승인 대기` : '대기 중인 요청 없음' },
        { tab: 'system' as AdminTab, icon: 'fa-server', label: '시스템 모니터', desc: '서버 상태, 데이터 현황' },
    ];

    return (
        <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                {stats.map(s => (
                    <button
                        key={s.label}
                        onClick={() => s.route ? navigate(s.route) : onNavigate(s.tab)}
                        className="apple-glass rounded-xl p-4 text-left hover:bg-white/5 hover:border-white/10 transition-all group cursor-pointer"
                    >
                        <div className={`w-10 h-10 ${s.bg} rounded-lg flex items-center justify-center mb-3 group-hover:scale-110 transition-transform`}>
                            <i className={`fas ${s.icon} ${s.color}`} />
                        </div>
                        <div className="text-2xl font-bold text-white">{s.value}</div>
                        <div className="text-xs text-gray-400 mt-1 group-hover:text-white transition-colors">{s.label}</div>
                    </button>
                ))}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {links.map(l => (
                    <button
                        key={l.tab}
                        onClick={() => onNavigate(l.tab)}
                        className="apple-glass rounded-xl p-4 md:p-6 hover:bg-white/5 transition-colors group text-left"
                    >
                        <div className="flex items-center gap-2 md:gap-3">
                            <i className={`fas ${l.icon} text-red-400 text-lg md:text-xl`} />
                            <div className="flex-1 min-w-0">
                                <div className="text-sm md:text-base text-white font-semibold group-hover:text-red-400 transition-colors truncate">{l.label}</div>
                                <div className="text-[10px] md:text-xs text-gray-500 truncate">{l.desc}</div>
                            </div>
                            <i className="fas fa-chevron-right text-gray-600 group-hover:text-red-400 transition-colors text-xs" />
                        </div>
                    </button>
                ))}
                <button
                    onClick={() => navigate('/dashboard/community/formula-market/purchases')}
                    className="apple-glass rounded-xl p-4 md:p-6 hover:bg-white/5 transition-colors group text-left"
                >
                    <div className="flex items-center gap-2 md:gap-3">
                        <i className="fas fa-receipt text-yellow-400 text-lg md:text-xl" />
                        <div className="flex-1 min-w-0">
                            <div className="text-sm md:text-base text-white font-semibold group-hover:text-yellow-400 transition-colors truncate">구매 관리</div>
                            <div className="text-[10px] md:text-xs text-gray-500 truncate">구매 승인/해제</div>
                        </div>
                        <i className="fas fa-chevron-right text-gray-600 group-hover:text-yellow-400 transition-colors text-xs" />
                    </div>
                </button>
            </div>
        </>
    );
}

// ── Users Tab ────────────────────────────────────────────────────────────────

const TIER_STYLES: Record<string, { label: string; cls: string }> = {
    none: { label: 'No Tier', cls: 'bg-gray-500/20 text-gray-400' },
    pro: { label: 'Pro', cls: 'bg-amber-500/20 text-amber-400' },
    premium: { label: 'Ultra Pro', cls: 'bg-purple-500/20 text-purple-400' },
};

function UsersTab({ apiToken }: { apiToken?: string }) {
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    const [filterTier, setFilterTier] = useState('all');
    const [filterStatus, setFilterStatus] = useState('all');
    const [search, setSearch] = useState('');
    const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
    const [newPassword, setNewPassword] = useState('');
    const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
    const [expiryTarget, setExpiryTarget] = useState<AdminUser | null>(null);
    const [expiryValue, setExpiryValue] = useState('');

    useEffect(() => { loadUsers(); }, [apiToken]);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const res = await adminAPI.getUsers(apiToken);
            setUsers(res.users || []);
        } catch { /* */ }
        setLoading(false);
    };

    const showAction = (msg: string, isError = false) => {
        setActionMsg(isError ? `❌ ${msg}` : `✅ ${msg}`);
        setTimeout(() => setActionMsg(''), 3000);
    };

    const handleTierChange = async (userId: number, name: string, newTier: string) => {
        try {
            const res = await adminAPI.setUserTier(userId, newTier, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? res.user : u));
            showAction(`${name} → ${TIER_STYLES[newTier]?.label || newTier}`);
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleSuspend = async (userId: number, name: string, currentStatus: string) => {
        const newStatus = currentStatus === 'suspended' ? 'approved' : 'suspended';
        try {
            await adminAPI.setUserStatus(userId, newStatus, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, status: newStatus } : u));
            showAction(`${name} ${newStatus === 'suspended' ? '정지' : '복원'} 완료`);
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleApprove = async (user: AdminUser) => {
        try {
            await adminAPI.setUserStatus(user.id, 'approved', apiToken);
            setUsers(prev => prev.map(u => u.id === user.id ? { ...u, status: 'approved' } : u));
            showAction(`${user.name} 승인 완료`);
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleResetPassword = async () => {
        if (!resetTarget || !newPassword || newPassword.length < 6) return;
        try {
            await adminAPI.resetPassword(resetTarget.id, newPassword, apiToken);
            showAction(`${resetTarget.name} 비밀번호 변경 완료`);
            setResetTarget(null);
            setNewPassword('');
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await adminAPI.deleteUser(deleteTarget.id, apiToken);
            setUsers(prev => prev.filter(u => u.id !== deleteTarget.id));
            showAction(`${deleteTarget.name} 삭제 완료`);
            setDeleteTarget(null);
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleExtend = async (user: AdminUser, days: number) => {
        try {
            const res = await adminAPI.extendPro(user.id, days, apiToken);
            setUsers(prev => prev.map(u => u.id === user.id ? res.user : u));
            showAction(`${user.name} +${days}일 연장`);
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleSetExpiry = async () => {
        if (!expiryTarget || !expiryValue) return;
        try {
            const res = await adminAPI.setExpiry(expiryTarget.id, expiryValue, apiToken);
            setUsers(prev => prev.map(u => u.id === expiryTarget.id ? res.user : u));
            showAction(`${expiryTarget.name} 만료일 변경`);
            setExpiryTarget(null);
            setExpiryValue('');
        } catch (err: any) { showAction(err.message, true); }
    };

    const filtered = users.filter(u => {
        if (filterTier !== 'all') {
            const tierKey = u.tier || 'none';
            if (tierKey !== filterTier) return false;
        }
        if (filterStatus !== 'all' && u.status !== filterStatus) return false;
        if (search) {
            const q = search.toLowerCase();
            return u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
        }
        return true;
    });

    const tierCount = (t: string) => users.filter(u => (u.tier || 'none') === t).length;
    const statusCount = (s: string) => users.filter(u => u.status === s).length;

    const formatExpiry = (iso: string | null): { label: string; cls: string } => {
        if (!iso) return { label: '—', cls: 'text-gray-600' };
        const d = new Date(iso);
        const now = new Date();
        const days = Math.ceil((d.getTime() - now.getTime()) / 86400000);
        const dateStr = d.toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' });
        if (days < 0) return { label: `만료 (${dateStr})`, cls: 'text-red-400' };
        if (days <= 1) return { label: `D-${days} (${dateStr})`, cls: 'text-red-400' };
        if (days <= 3) return { label: `D-${days} (${dateStr})`, cls: 'text-amber-400' };
        return { label: `${dateStr} (${days}일)`, cls: 'text-gray-500' };
    };

    if (loading) return <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" /></div>;

    return (
        <>
            {/* 요약 */}
            <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
                <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                    <span>{users.length}명</span>
                    <span className="text-amber-400">{tierCount('pro')} Pro</span>
                    <span className="text-purple-400">{tierCount('premium')} Ultra</span>
                    <span>{tierCount('none')} No Tier</span>
                    {statusCount('pending') > 0 && (
                        <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 font-bold">
                            승인 대기 {statusCount('pending')}
                        </span>
                    )}
                </div>
            </div>

            {actionMsg && (
                <div className={`p-3 rounded-lg text-sm font-medium ${actionMsg.startsWith('❌') ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'}`}>
                    {actionMsg}
                </div>
            )}

            <div className="flex items-center gap-3 flex-wrap">
                <input
                    type="text" value={search} onChange={e => setSearch(e.target.value)}
                    placeholder="이름 또는 이메일 검색..."
                    className="flex-1 min-w-[200px] px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
                />
                <div className="flex gap-1">
                    {[{ key: 'all', label: '전체' }, { key: 'premium', label: 'Ultra Pro' }, { key: 'pro', label: 'Pro' }, { key: 'none', label: 'No Tier' }].map(tab => (
                        <button key={tab.key} onClick={() => setFilterTier(tab.key)}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${filterTier === tab.key ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white hover:bg-white/5'}`}>
                            {tab.label}
                        </button>
                    ))}
                </div>
                <div className="flex gap-1">
                    {[
                        { key: 'all', label: '상태 전체', cls: 'text-gray-500' },
                        { key: 'pending', label: '대기', cls: 'text-amber-400' },
                        { key: 'approved', label: '승인', cls: 'text-emerald-400' },
                        { key: 'suspended', label: '정지', cls: 'text-red-400' },
                    ].map(tab => (
                        <button key={tab.key} onClick={() => setFilterStatus(tab.key)}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${filterStatus === tab.key ? `bg-white/10 ${tab.cls}` : `${tab.cls} hover:text-white hover:bg-white/5`}`}>
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* 테이블 */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-white/[0.03]">
                            <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">회원</th>
                            <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">가입일</th>
                            <th className="text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">플랜</th>
                            <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">만료일</th>
                            <th className="text-right text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map(user => {
                            const isAdmin = user.role === 'admin';
                            const isSuspended = user.status === 'suspended';
                            const tier = TIER_STYLES[user.tier || 'none'] || TIER_STYLES.none;
                            return (
                                <tr key={user.id} className={`border-t border-white/[0.04] hover:bg-white/[0.02] transition-colors ${isSuspended ? 'opacity-50' : ''}`}>
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 ${isAdmin ? 'bg-red-500' : 'bg-white/10'}`}>
                                                {user.name.charAt(0).toUpperCase()}
                                            </div>
                                            <div className="min-w-0">
                                                <div className="flex items-center gap-1.5">
                                                    <span className="text-sm font-medium text-white truncate">{user.name}</span>
                                                    {isAdmin && <span className="text-[9px] px-1 py-0.5 bg-red-500/20 text-red-400 rounded shrink-0">관리자</span>}
                                                    {isSuspended && <span className="text-[9px] px-1 py-0.5 bg-red-500/20 text-red-400 rounded shrink-0">정지</span>}
                                                </div>
                                                <div className="text-xs text-gray-500 truncate">{user.email}</div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 hidden md:table-cell">
                                        <span className="text-xs text-gray-600">{user.created_at ? new Date(user.created_at).toLocaleDateString('ko-KR') : '-'}</span>
                                    </td>
                                    <td className="px-4 py-3 text-center">
                                        {isAdmin ? (
                                            <span className="text-[10px] px-2 py-1 rounded bg-red-500/20 text-red-400 font-bold">Admin</span>
                                        ) : (
                                            <select value={user.tier || ''} onChange={e => handleTierChange(user.id, user.name, e.target.value)}
                                                className={`text-[11px] px-2 py-1 rounded font-bold border-0 cursor-pointer focus:outline-none focus:ring-1 focus:ring-amber-500/50 ${tier.cls}`}
                                                style={{ background: 'transparent' }}>
                                                <option value="" disabled className="bg-[#1c1c1e] text-gray-300">No Tier</option>
                                                <option value="pro" className="bg-[#1c1c1e] text-amber-400">Pro</option>
                                                <option value="premium" className="bg-[#1c1c1e] text-purple-400">Ultra Pro</option>
                                            </select>
                                        )}
                                        {user.status === 'pending' && (
                                            <div className="text-[9px] text-amber-400 font-bold mt-1">승인 대기</div>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 hidden lg:table-cell">
                                        {user.tier === 'premium' ? (
                                            <span className="text-xs text-purple-400">무기한</span>
                                        ) : user.tier === 'pro' ? (
                                            <button
                                                onClick={() => { setExpiryTarget(user); setExpiryValue(user.pro_expires_at ? user.pro_expires_at.slice(0, 10) : ''); }}
                                                className={`text-xs ${formatExpiry(user.pro_expires_at).cls} hover:underline`}
                                                title="만료일 변경">
                                                {formatExpiry(user.pro_expires_at).label}
                                            </button>
                                        ) : (
                                            <span className="text-xs text-gray-700">—</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex items-center justify-end gap-1">
                                            {user.status === 'pending' && !isAdmin && (
                                                <button onClick={() => handleApprove(user)}
                                                    className="p-1.5 rounded-lg text-amber-400 hover:bg-amber-500/10 text-xs transition-colors"
                                                    title="승인">
                                                    <i className="fas fa-check" />
                                                </button>
                                            )}
                                            {user.tier === 'pro' && !isAdmin && (
                                                <button onClick={() => handleExtend(user, 30)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/10 text-xs transition-colors"
                                                    title="+30일 연장">
                                                    <i className="fas fa-plus" />
                                                </button>
                                            )}
                                            {!isAdmin && (
                                                <button onClick={() => handleSuspend(user.id, user.name, user.status)}
                                                    className={`p-1.5 rounded-lg text-xs transition-colors ${isSuspended ? 'text-emerald-400 hover:bg-emerald-500/10' : 'text-gray-500 hover:text-red-400 hover:bg-red-500/10'}`}
                                                    title={isSuspended ? '복원' : '정지'}>
                                                    <i className={`fas ${isSuspended ? 'fa-undo' : 'fa-ban'}`} />
                                                </button>
                                            )}
                                            <button onClick={() => { setResetTarget(user); setNewPassword(''); }}
                                                className="p-1.5 rounded-lg text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 text-xs transition-colors" title="비밀번호 리셋">
                                                <i className="fas fa-key" />
                                            </button>
                                            {!isAdmin && (
                                                <button onClick={() => setDeleteTarget(user)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-500/10 text-xs transition-colors" title="삭제">
                                                    <i className="fas fa-trash-alt" />
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
                {filtered.length === 0 && <div className="text-center py-12 text-gray-500 text-sm">검색 결과가 없습니다</div>}
            </div>

            {/* 비밀번호 리셋 모달 */}
            {resetTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setResetTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">비밀번호 리셋</h3>
                        <p className="text-sm text-gray-400 mb-4">{resetTarget.name} ({resetTarget.email})</p>
                        <input type="text" value={newPassword} onChange={e => setNewPassword(e.target.value)}
                            placeholder="새 비밀번호 (6자 이상)"
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-amber-500/50 mb-4" autoFocus />
                        <div className="flex gap-2">
                            <button onClick={() => setResetTarget(null)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors">취소</button>
                            <button onClick={handleResetPassword} disabled={!newPassword || newPassword.length < 6} className="flex-1 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-sm font-bold transition-colors disabled:opacity-30">변경</button>
                        </div>
                    </div>
                </div>
            )}

            {/* 만료일 변경 모달 */}
            {expiryTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setExpiryTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">Pro 만료일 변경</h3>
                        <p className="text-sm text-gray-400 mb-4">{expiryTarget.name} ({expiryTarget.email})</p>
                        <input type="date" value={expiryValue} onChange={e => setExpiryValue(e.target.value)}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-amber-500/50 mb-4" autoFocus />
                        <div className="flex gap-2 mb-3">
                            {[7, 30, 90, 365].map(d => (
                                <button key={d}
                                    onClick={async () => { await handleExtend(expiryTarget, d); setExpiryTarget(null); }}
                                    className="flex-1 py-2 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-emerald-400 text-xs font-bold transition-colors">
                                    +{d}일
                                </button>
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <button onClick={() => setExpiryTarget(null)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors">취소</button>
                            <button onClick={handleSetExpiry} disabled={!expiryValue} className="flex-1 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-sm font-bold transition-colors disabled:opacity-30">날짜 적용</button>
                        </div>
                    </div>
                </div>
            )}

            {/* 삭제 확인 모달 */}
            {deleteTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setDeleteTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">회원 삭제</h3>
                        <p className="text-sm text-gray-400 mb-2"><span className="text-white font-bold">{deleteTarget.name}</span> ({deleteTarget.email})</p>
                        <p className="text-sm text-red-400 mb-4">삭제하면 복구할 수 없습니다.</p>
                        <div className="flex gap-2">
                            <button onClick={() => setDeleteTarget(null)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors">취소</button>
                            <button onClick={handleDelete} className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-white text-sm font-bold transition-colors">삭제</button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

// ── Subscriptions Tab ────────────────────────────────────────────────────────

function SubscriptionsTab({ apiToken, onCountChange }: { apiToken?: string; onCountChange: (n: number) => void }) {
    const [requests, setRequests] = useState<SubscriptionRequest[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    // 처리 중인 request id 추적 — 같은 row 더블클릭 방지 + 이미 처리된 row 보호
    const [processing, setProcessing] = useState<Set<number>>(new Set());

    // silent=true 이면 스피너를 띄우지 않음 (refresh 버튼용 기본은 스피너 O)
    const loadRequests = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const res = await adminAPI.getSubscriptions(apiToken);
            const reqs = res.requests || [];
            setRequests(reqs);
            onCountChange(reqs.filter((r: SubscriptionRequest) => r.status === 'pending').length);
        } catch { /* */ }
        if (!silent) setLoading(false);
    }, [apiToken, onCountChange]);

    useEffect(() => { loadRequests(); }, [loadRequests]);

    const showAction = (msg: string) => { setActionMsg(msg); setTimeout(() => setActionMsg(''), 3000); };

    const handleApprove = async (id: number) => {
        // 이미 처리 중이거나 pending 이 아닌 row 는 무시 (중복 클릭 차단)
        if (processing.has(id)) return;
        const current = requests.find(r => r.id === id);
        if (!current || current.status !== 'pending') return;

        setProcessing(prev => { const n = new Set(prev); n.add(id); return n; });
        // 1) Optimistic UI: 즉시 approved 로 전환
        setRequests(prev => {
            const next = prev.map(r => r.id === id ? { ...r, status: 'approved' as const, processed_at: new Date().toISOString() } : r);
            onCountChange(next.filter(r => r.status === 'pending').length);
            return next;
        });
        showAction('✅ 구독 승인 완료');
        try {
            // 2) 서버 확정. 응답의 request 객체로 로컬 상태 merge (loadRequests 호출 X → 스피너 X)
            const res = await adminAPI.approveSubscription(id, apiToken);
            if (res?.request) {
                setRequests(prev => prev.map(r => r.id === id ? res.request : r));
            }
        } catch (err: any) {
            // 실패 시에만 롤백
            setRequests(prev => {
                const next = prev.map(r => r.id === id ? { ...r, status: 'pending' as const, processed_at: null } : r);
                onCountChange(next.filter(r => r.status === 'pending').length);
                return next;
            });
            showAction(`❌ ${err.message}`);
        } finally {
            setProcessing(prev => { const n = new Set(prev); n.delete(id); return n; });
        }
    };

    const handleReject = async (id: number) => {
        if (processing.has(id)) return;
        const current = requests.find(r => r.id === id);
        if (!current || current.status !== 'pending') return;

        const note = prompt('거절 사유 (선택):');
        setProcessing(prev => { const n = new Set(prev); n.add(id); return n; });
        // Optimistic UI
        setRequests(prev => {
            const next = prev.map(r => r.id === id ? { ...r, status: 'rejected' as const, admin_note: note || '', processed_at: new Date().toISOString() } : r);
            onCountChange(next.filter(r => r.status === 'pending').length);
            return next;
        });
        showAction('구독 요청 거절됨');
        try {
            const res = await adminAPI.rejectSubscription(id, note || undefined, apiToken);
            if (res?.request) {
                setRequests(prev => prev.map(r => r.id === id ? res.request : r));
            }
        } catch (err: any) {
            setRequests(prev => {
                const next = prev.map(r => r.id === id ? { ...r, status: 'pending' as const, processed_at: null, admin_note: null } : r);
                onCountChange(next.filter(r => r.status === 'pending').length);
                return next;
            });
            showAction(`❌ ${err.message}`);
        } finally {
            setProcessing(prev => { const n = new Set(prev); n.delete(id); return n; });
        }
    };

    if (loading) return <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500" /></div>;

    const pending = requests.filter(r => r.status === 'pending');
    const processed = requests.filter(r => r.status !== 'pending');

    return (
        <>
            {actionMsg && (
                <div className={`p-3 rounded-lg text-sm font-medium ${actionMsg.startsWith('❌') ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'}`}>
                    {actionMsg}
                </div>
            )}

            {/* Pending */}
            <div>
                <div className="flex items-center justify-between mb-3">
                    <h2 className="text-lg font-semibold text-yellow-400">
                        <i className="fas fa-clock mr-2" />대기 중 ({pending.length})
                    </h2>
                    <button onClick={() => loadRequests()} className="text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 transition-colors">
                        <i className="fas fa-sync-alt mr-1" /> 새로고침
                    </button>
                </div>
                {pending.length === 0 ? (
                    <div className="apple-glass rounded-xl p-8 text-center text-gray-500">
                        <i className="fas fa-check-circle text-3xl mb-3 text-green-500/50" />
                        <div>대기 중인 구독 요청이 없습니다</div>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {pending.map(req => (
                            <div key={req.id} className="apple-glass rounded-xl p-4 border border-yellow-500/20">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-yellow-500/10 rounded-full flex items-center justify-center">
                                            <i className="fas fa-arrow-up text-yellow-400" />
                                        </div>
                                        <div>
                                            <div className="text-white font-medium">{req.user_name || `User #${req.user_id}`}</div>
                                            <div className="text-xs text-gray-400">{req.user_email || ''}</div>
                                            <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-1">
                                                <span className={`px-1.5 py-0.5 rounded ${req.from_tier === 'none' ? 'bg-gray-500/20 text-gray-400' : 'bg-amber-500/20 text-amber-400'}`}>{req.from_tier}</span>
                                                <span className="mx-1">&rarr;</span>
                                                <span className={`px-1.5 py-0.5 rounded font-bold ${req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400' : 'bg-amber-500/20 text-amber-400'}`}>
                                                    {req.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                                </span>
                                                {req.depositor_name && (
                                                    <span className="ml-2 px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                                                        <i className="fas fa-user text-[10px] mr-1" />{req.depositor_name}
                                                    </span>
                                                )}
                                                {req.amount && <span className="px-1.5 py-0.5 rounded bg-green-500/10 text-green-400">{req.amount}</span>}
                                                <span className="ml-2 text-gray-600">{new Date(req.created_at).toLocaleString()}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={() => handleApprove(req.id)}
                                            disabled={processing.has(req.id)}
                                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                                                req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30' : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                                            }`}>
                                            <i className={`fas ${processing.has(req.id) ? 'fa-spinner fa-spin' : (req.to_tier === 'premium' ? 'fa-gem' : 'fa-crown')} mr-1`} />
                                            {req.to_tier === 'premium' ? 'Ultra Pro 승인' : 'Pro 승인'}
                                        </button>
                                        <button onClick={() => handleReject(req.id)}
                                            disabled={processing.has(req.id)}
                                            className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg text-sm font-medium hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                            <i className="fas fa-times mr-1" /> 거절
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* History */}
            {processed.length > 0 && (
                <div>
                    <h2 className="text-lg font-semibold text-gray-400 mb-3">
                        <i className="fas fa-history mr-2" />처리 이력 ({processed.length})
                    </h2>
                    <div className="apple-glass rounded-xl overflow-hidden">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-white/5">
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">회원</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">변경</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">상태</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">날짜</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">메모</th>
                                </tr>
                            </thead>
                            <tbody>
                                {processed.map(req => (
                                    <tr key={req.id} className="border-b border-white/5">
                                        <td className="px-4 py-3 text-sm text-white">{req.user_name || `#${req.user_id}`}</td>
                                        <td className="px-4 py-3 text-xs text-gray-400">{req.from_tier} &rarr; {req.to_tier}</td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs px-2 py-1 rounded ${req.status === 'approved' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{req.status}</span>
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-500">{req.processed_at ? new Date(req.processed_at).toLocaleDateString() : '-'}</td>
                                        <td className="px-4 py-3 text-xs text-gray-500">{req.admin_note || '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </>
    );
}

// ── System Tab ───────────────────────────────────────────────────────────────

interface DataFileStatus {
    exists: boolean;
    size: number;
    last_modified: string;
}

function SystemTab({ token }: { token: string | null }) {
    const [health, setHealth] = useState<any>(null);
    const [dataStatus, setDataStatus] = useState<Record<string, DataFileStatus>>({});
    const [loading, setLoading] = useState(true);
    const [updating, setUpdating] = useState<string | null>(null);

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const [healthRes, statusRes] = await Promise.allSettled([
                fetchAuthAPI<any>('/api/health', token || undefined),
                fetchAuthAPI<Record<string, DataFileStatus>>('/api/system/data-status', token || undefined),
            ]);
            if (healthRes.status === 'fulfilled') setHealth(healthRes.value);
            if (statusRes.status === 'fulfilled') setDataStatus(statusRes.value);
        } catch { /* */ }
        setLoading(false);
    }, [token]);

    useEffect(() => { loadData(); }, [loadData]);

    const handleUpdate = async (type: string) => {
        setUpdating(type);
        try {
            const tokenParam = token ? `&token=${encodeURIComponent(token)}` : '';
            const eventSource = new EventSource(`${API_BASE}/api/system/update-single?type=${encodeURIComponent(type)}${tokenParam}`);
            eventSource.addEventListener('status', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    if (data.status === 'completed') { eventSource.close(); setUpdating(null); loadData(); }
                } catch { eventSource.close(); setUpdating(null); }
            });
            eventSource.onerror = () => { eventSource.close(); setUpdating(null); };
        } catch { setUpdating(null); }
    };

    if (loading) return <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500" /></div>;

    return (
        <>
            {/* Server Health */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-heartbeat text-green-400 mr-2" />Server Health
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Status</div>
                        <div className="text-lg font-bold text-green-400">{health?.status === 'ok' ? 'Online' : 'Unknown'}</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Backend</div>
                        <div className="text-lg font-bold text-blue-400">Flask</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Port</div>
                        <div className="text-lg font-bold text-white">5001</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Database</div>
                        <div className="text-lg font-bold text-purple-400">SQLite</div>
                    </div>
                </div>
            </div>

            {/* Data Files */}
            <div className="apple-glass rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        <i className="fas fa-database text-cyan-400 mr-2" />Data Files
                    </h2>
                    <button onClick={loadData} className="text-xs text-gray-400 hover:text-white px-3 py-1 rounded bg-white/5 hover:bg-white/10 transition-colors">
                        <i className="fas fa-sync-alt mr-1" /> Refresh
                    </button>
                </div>
                <div className="space-y-2">
                    {Object.entries(dataStatus).map(([key, status]) => (
                        <div key={key} className="flex items-center justify-between p-3 bg-white/[0.02] rounded-lg hover:bg-white/[0.04] transition-colors">
                            <div className="flex items-center gap-3">
                                <div className={`w-2 h-2 rounded-full ${status.exists ? 'bg-green-400' : 'bg-red-400'}`} />
                                <div>
                                    <div className="text-sm text-white font-medium">{key}</div>
                                    <div className="text-xs text-gray-500">
                                        {status.exists ? `${(status.size / 1024).toFixed(1)} KB | ${status.last_modified ? new Date(status.last_modified).toLocaleString() : 'Unknown'}` : 'File not found'}
                                    </div>
                                </div>
                            </div>
                            <button onClick={() => handleUpdate(key)} disabled={updating === key}
                                className="text-xs px-3 py-1 rounded bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50">
                                {updating === key ? <><i className="fas fa-spinner fa-spin mr-1" /> Updating</> : <><i className="fas fa-redo mr-1" /> Update</>}
                            </button>
                        </div>
                    ))}
                </div>
            </div>
        </>
    );
}
