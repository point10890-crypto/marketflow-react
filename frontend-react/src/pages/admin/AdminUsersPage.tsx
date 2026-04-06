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
    const [search, setSearch] = useState('');

    // 모달
    const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
    const [newPassword, setNewPassword] = useState('');
    const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

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

    // 필터링
    const filtered = users.filter(u => {
        if (filterTier !== 'all') {
            const tierKey = u.tier || 'none';
            if (tierKey !== filterTier) return false;
        }
        if (search) {
            const q = search.toLowerCase();
            return u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
        }
        return true;
    });

    const tierCount = (t: string) => users.filter(u => (u.tier || 'none') === t).length;

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
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">회원 관리</h1>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>{users.length}명</span>
                    <span className="text-amber-400">{tierCount('pro')} Pro</span>
                    <span className="text-purple-400">{tierCount('premium')} Ultra</span>
                    <span>{tierCount('none')} No Tier</span>
                </div>
            </div>

            {/* 토스트 */}
            {actionMsg && (
                <div className={`p-3 rounded-lg text-sm font-medium ${actionMsg.startsWith('❌') ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'}`}>
                    {actionMsg}
                </div>
            )}

            {/* 검색 + 필터 */}
            <div className="flex items-center gap-3">
                <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="이름 또는 이메일 검색..."
                    className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
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
            </div>

            {/* 테이블 */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-white/[0.03]">
                            <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">회원</th>
                            <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">가입일</th>
                            <th className="text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">플랜</th>
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
                                    {/* 관리 */}
                                    <td className="px-4 py-3">
                                        <div className="flex items-center justify-end gap-1">
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
