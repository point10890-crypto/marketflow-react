import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { adminAPI, AdminUser } from '@/lib/api';

const TIER_STYLES: Record<string, { label: string; cls: string }> = {
    none: { label: 'No Tier', cls: 'bg-gray-500/20 text-gray-400' },
    pro: { label: 'Pro', cls: 'bg-amber-500/20 text-amber-400' },
    premium: { label: 'Ultra Pro', cls: 'bg-purple-500/20 text-purple-400' },
};

export default function AdminUsersPage() {
    const { token } = useAuth();
    const apiToken = token ?? undefined;
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    const [filterTier, setFilterTier] = useState<string>('all');
    const [filterStatus, setFilterStatus] = useState<string>('all');
    const [search, setSearch] = useState('');

    // 모달
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
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const showAction = (msg: string, isError = false) => {
        setActionMsg(isError ? `❌ ${msg}` : `✅ ${msg}`);
        setTimeout(() => setActionMsg(''), 3000);
    };

    const handleTierChange = async (userId: number, name: string, newTier: string) => {
        try {
            await adminAPI.setUserTier(userId, newTier, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, tier: newTier } : u));
            showAction(`${name} → ${TIER_STYLES[newTier]?.label || newTier}`);
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    const handleSuspend = async (userId: number, name: string, currentStatus: string) => {
        const newStatus = currentStatus === 'suspended' ? 'approved' : 'suspended';
        try {
            await adminAPI.setUserStatus(userId, newStatus, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, status: newStatus } : u));
            showAction(`${name} ${newStatus === 'suspended' ? '정지' : '복원'} 완료`);
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    const handleResetPassword = async () => {
        if (!resetTarget || !newPassword || newPassword.length < 6) return;
        try {
            await adminAPI.resetPassword(resetTarget.id, newPassword, apiToken);
            showAction(`${resetTarget.name} 비밀번호 변경 완료`);
            setResetTarget(null);
            setNewPassword('');
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await adminAPI.deleteUser(deleteTarget.id, apiToken);
            setUsers(prev => prev.filter(u => u.id !== deleteTarget.id));
            showAction(`${deleteTarget.name} 삭제 완료`);
            setDeleteTarget(null);
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    const handleExtend = async (user: AdminUser, days: number) => {
        try {
            const res = await adminAPI.extendPro(user.id, days, apiToken);
            setUsers(prev => prev.map(u => u.id === user.id ? res.user : u));
            showAction(`${user.name} +${days}일 연장`);
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    const handleSetExpiry = async () => {
        if (!expiryTarget || !expiryValue) return;
        try {
            const res = await adminAPI.setExpiry(expiryTarget.id, expiryValue, apiToken);
            setUsers(prev => prev.map(u => u.id === expiryTarget.id ? res.user : u));
            showAction(`${expiryTarget.name} 만료일 변경`);
            setExpiryTarget(null);
            setExpiryValue('');
        } catch (err: any) {
            showAction(err.message, true);
        }
    };

    // 필터링
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

    // 만료일 표시 + D-N 계산
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

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
            </div>
        );
    }

    return (
        <div className="space-y-5">
            {/* 헤더 */}
            <div className="flex items-center justify-between flex-wrap gap-2">
                <h1 className="text-2xl font-bold text-white">회원 관리</h1>
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

            {/* 토스트 */}
            {actionMsg && (
                <div className={`p-3 rounded-lg text-sm font-medium ${actionMsg.startsWith('❌') ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'}`}>
                    {actionMsg}
                </div>
            )}

            {/* 검색 + 필터 */}
            <div className="flex items-center gap-3 flex-wrap">
                <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="이름 또는 이메일 검색..."
                    className="flex-1 min-w-[200px] px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
                />
                <div className="flex gap-1">
                    {[
                        { key: 'all', label: '전체' },
                        { key: 'premium', label: 'Ultra Pro' },
                        { key: 'pro', label: 'Pro' },
                        { key: 'none', label: 'No Tier' },
                    ].map(tab => (
                        <button
                            key={tab.key}
                            onClick={() => setFilterTier(tab.key)}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                                filterTier === tab.key ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white hover:bg-white/5'
                            }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
                <div className="flex gap-1">
                    {[
                        { key: 'all', label: '상태 전체' },
                        { key: 'pending', label: '대기', cls: 'text-amber-400' },
                        { key: 'approved', label: '승인', cls: 'text-emerald-400' },
                        { key: 'suspended', label: '정지', cls: 'text-red-400' },
                    ].map(tab => (
                        <button
                            key={tab.key}
                            onClick={() => setFilterStatus(tab.key)}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                                filterStatus === tab.key
                                    ? `bg-white/10 ${(tab as any).cls || 'text-white'}`
                                    : `${(tab as any).cls || 'text-gray-500'} hover:text-white hover:bg-white/5`
                            }`}
                        >
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
                                    {/* 회원 정보 */}
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 ${
                                                isAdmin ? 'bg-red-500' : 'bg-white/10'
                                            }`}>
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
                                    {/* 가입일 */}
                                    <td className="px-4 py-3 hidden md:table-cell">
                                        <span className="text-xs text-gray-600">
                                            {user.created_at ? new Date(user.created_at).toLocaleDateString('ko-KR') : '-'}
                                        </span>
                                    </td>
                                    {/* 플랜 */}
                                    <td className="px-4 py-3 text-center">
                                        {isAdmin ? (
                                            <span className="text-[10px] px-2 py-1 rounded bg-red-500/20 text-red-400 font-bold">Admin</span>
                                        ) : (
                                            <select
                                                value={user.tier || ''}
                                                onChange={e => handleTierChange(user.id, user.name, e.target.value)}
                                                className={`text-[11px] px-2 py-1 rounded font-bold border-0 cursor-pointer focus:outline-none focus:ring-1 focus:ring-amber-500/50 ${tier.cls}`}
                                                style={{ background: 'transparent' }}
                                            >
                                                <option value="" disabled className="bg-[#1c1c1e] text-gray-300">No Tier</option>
                                                <option value="pro" className="bg-[#1c1c1e] text-amber-400">Pro</option>
                                                <option value="premium" className="bg-[#1c1c1e] text-purple-400">Ultra Pro</option>
                                            </select>
                                        )}
                                    </td>
                                    {/* 만료일 */}
                                    <td className="px-4 py-3 hidden lg:table-cell">
                                        {user.tier === 'premium' ? (
                                            <span className="text-xs text-purple-400">무기한</span>
                                        ) : user.tier === 'pro' ? (
                                            <button
                                                onClick={() => {
                                                    setExpiryTarget(user);
                                                    setExpiryValue(user.pro_expires_at ? user.pro_expires_at.slice(0, 10) : '');
                                                }}
                                                className={`text-xs ${formatExpiry(user.pro_expires_at).cls} hover:underline`}
                                                title="만료일 변경"
                                            >
                                                {formatExpiry(user.pro_expires_at).label}
                                            </button>
                                        ) : (
                                            <span className="text-xs text-gray-700">—</span>
                                        )}
                                    </td>
                                    {/* 관리 */}
                                    <td className="px-4 py-3">
                                        <div className="flex items-center justify-end gap-1">
                                            {user.tier === 'pro' && !isAdmin && (
                                                <button
                                                    onClick={() => handleExtend(user, 30)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/10 text-xs transition-colors"
                                                    title="+30일 연장"
                                                >
                                                    <i className="fas fa-plus" />
                                                </button>
                                            )}
                                            {!isAdmin && (
                                                <button
                                                    onClick={() => handleSuspend(user.id, user.name, user.status)}
                                                    className={`p-1.5 rounded-lg text-xs transition-colors ${
                                                        isSuspended
                                                            ? 'text-emerald-400 hover:bg-emerald-500/10'
                                                            : 'text-gray-500 hover:text-red-400 hover:bg-red-500/10'
                                                    }`}
                                                    title={isSuspended ? '복원' : '정지'}
                                                >
                                                    <i className={`fas ${isSuspended ? 'fa-undo' : 'fa-ban'}`} />
                                                </button>
                                            )}
                                            <button
                                                onClick={() => { setResetTarget(user); setNewPassword(''); }}
                                                className="p-1.5 rounded-lg text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 text-xs transition-colors"
                                                title="비밀번호 리셋"
                                            >
                                                <i className="fas fa-key" />
                                            </button>
                                            {!isAdmin && (
                                                <button
                                                    onClick={() => setDeleteTarget(user)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-500/10 text-xs transition-colors"
                                                    title="삭제"
                                                >
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
                {filtered.length === 0 && (
                    <div className="text-center py-12 text-gray-500 text-sm">검색 결과가 없습니다</div>
                )}
            </div>

            {/* 비밀번호 리셋 모달 */}
            {resetTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setResetTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">비밀번호 리셋</h3>
                        <p className="text-sm text-gray-400 mb-4">{resetTarget.name} ({resetTarget.email})</p>
                        <input
                            type="text"
                            value={newPassword}
                            onChange={e => setNewPassword(e.target.value)}
                            placeholder="새 비밀번호 (6자 이상)"
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-amber-500/50 mb-4"
                            autoFocus
                        />
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
                        <input
                            type="date"
                            value={expiryValue}
                            onChange={e => setExpiryValue(e.target.value)}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-amber-500/50 mb-4"
                            autoFocus
                        />
                        <div className="flex gap-2 mb-3">
                            {[7, 30, 90, 365].map(d => (
                                <button
                                    key={d}
                                    onClick={() => handleExtend(expiryTarget, d).then(() => setExpiryTarget(null))}
                                    className="flex-1 py-2 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-emerald-400 text-xs font-bold transition-colors"
                                >
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
        </div>
    );
}
