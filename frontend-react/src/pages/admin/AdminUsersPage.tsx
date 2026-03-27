import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { adminAPI, AdminUser } from '@/lib/api';

export default function AdminUsersPage() {
    const { token } = useAuth();
    const apiToken = token ?? undefined;
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    const [filterStatus, setFilterStatus] = useState<string>('all');

    // 비밀번호 리셋 모달
    const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
    const [newPassword, setNewPassword] = useState('');

    // 삭제 확인 모달
    const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

    useEffect(() => { loadUsers(); }, [apiToken]);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const res = await adminAPI.getUsers(apiToken);
            setUsers(res.users || []);
        } catch (err) {
            console.error('Failed to load users:', err);
        } finally {
            setLoading(false);
        }
    };

    const showAction = (msg: string) => {
        setActionMsg(msg);
        setTimeout(() => setActionMsg(''), 3000);
    };

    const handleApprove = async (userId: number, userName: string) => {
        try {
            await adminAPI.setUserStatus(userId, 'approved', apiToken);
            await adminAPI.setUserTier(userId, 'pro', apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, subscription_status: 'approved', tier: 'pro' } : u));
            showAction(`${userName} 승인 완료`);
        } catch (err: any) {
            showAction(`오류: ${err.message}`);
        }
    };

    const handleSuspend = async (userId: number, userName: string) => {
        try {
            await adminAPI.setUserStatus(userId, 'suspended', apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, subscription_status: 'suspended' } : u));
            showAction(`${userName} 해제 완료`);
        } catch (err: any) {
            showAction(`오류: ${err.message}`);
        }
    };

    const handleResetPassword = async () => {
        if (!resetTarget || !newPassword || newPassword.length < 6) return;
        try {
            await adminAPI.resetPassword(resetTarget.id, newPassword, apiToken);
            showAction(`${resetTarget.name} 비밀번호 리셋 완료`);
            setResetTarget(null);
            setNewPassword('');
        } catch (err: any) {
            showAction(`오류: ${err.message}`);
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
            showAction(`오류: ${err.message}`);
        }
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'approved': return { text: '승인됨', cls: 'bg-emerald-500/20 text-emerald-400' };
            case 'pending': return { text: '대기중', cls: 'bg-amber-500/20 text-amber-400' };
            case 'suspended': return { text: '해제됨', cls: 'bg-red-500/20 text-red-400' };
            case 'rejected': return { text: '거부됨', cls: 'bg-gray-500/20 text-gray-400' };
            default: return { text: status, cls: 'bg-gray-500/20 text-gray-400' };
        }
    };

    const filtered = users.filter(u => {
        if (filterStatus === 'all') return true;
        return u.subscription_status === filterStatus;
    });

    const pendingCount = users.filter(u => u.subscription_status === 'pending').length;

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">사용자 관리</h1>
                <span className="text-sm text-gray-400">총 {users.length}명</span>
            </div>

            {pendingCount > 0 && (
                <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center gap-3">
                    <i className="fas fa-user-clock text-amber-400 text-lg"></i>
                    <span className="text-amber-400 font-bold">{pendingCount}명의 승인 대기자가 있습니다</span>
                </div>
            )}

            {actionMsg && (
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm">
                    <i className="fas fa-check-circle mr-2"></i>{actionMsg}
                </div>
            )}

            {/* 필터 탭 */}
            <div className="flex gap-2">
                {[
                    { key: 'all', label: '전체' },
                    { key: 'pending', label: '대기중' },
                    { key: 'approved', label: '승인됨' },
                    { key: 'suspended', label: '해제됨' },
                ].map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setFilterStatus(tab.key)}
                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                            filterStatus === tab.key
                                ? 'bg-white/10 text-white'
                                : 'text-gray-500 hover:text-white hover:bg-white/5'
                        }`}
                    >
                        {tab.label}
                        {tab.key === 'pending' && pendingCount > 0 && (
                            <span className="ml-1.5 px-1.5 py-0.5 text-[10px] bg-amber-500 text-black rounded-full font-bold">{pendingCount}</span>
                        )}
                    </button>
                ))}
            </div>

            {/* 사용자 목록 */}
            <div className="space-y-3">
                {filtered.map((user) => {
                    const badge = getStatusBadge(user.subscription_status);
                    const isAdmin = user.role === 'admin';
                    const isPending = user.subscription_status === 'pending';
                    const isApproved = user.subscription_status === 'approved';
                    const isSuspended = user.subscription_status === 'suspended' || user.subscription_status === 'rejected';

                    return (
                        <div key={user.id} className={`p-4 rounded-xl border transition-colors ${
                            isPending ? 'bg-amber-500/5 border-amber-500/20' : 'bg-[#1c1c1e] border-white/10'
                        }`}>
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white ${
                                        isAdmin ? 'bg-red-500' : isApproved ? 'bg-emerald-500' : isPending ? 'bg-amber-500' : 'bg-gray-600'
                                    }`}>
                                        {user.name.charAt(0).toUpperCase()}
                                    </div>
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-bold text-white">{user.name}</span>
                                            {isAdmin && <span className="text-[10px] px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">관리자</span>}
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${badge.cls}`}>{badge.text}</span>
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">{user.tier}</span>
                                        </div>
                                        <div className="text-xs text-gray-500">{user.email}</div>
                                        <div className="text-[10px] text-gray-600 mt-0.5">
                                            가입: {user.created_at ? new Date(user.created_at).toLocaleDateString('ko-KR') : '-'}
                                            {user.last_login_at && <> · 최근 로그인: {new Date(user.last_login_at).toLocaleDateString('ko-KR')}</>}
                                        </div>
                                    </div>
                                </div>

                                {/* 액션 버튼 */}
                                <div className="flex items-center gap-2">
                                    {!isAdmin && (
                                        <>
                                            {(isPending || isSuspended) && (
                                                <button
                                                    onClick={() => handleApprove(user.id, user.name)}
                                                    className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-white text-xs font-bold transition-colors active:scale-95"
                                                >
                                                    승인
                                                </button>
                                            )}
                                            {isApproved && (
                                                <button
                                                    onClick={() => handleSuspend(user.id, user.name)}
                                                    className="px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-400 text-xs font-medium transition-colors active:scale-95"
                                                >
                                                    해제
                                                </button>
                                            )}
                                        </>
                                    )}
                                    <button
                                        onClick={() => { setResetTarget(user); setNewPassword(''); }}
                                        className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white text-xs font-medium transition-colors active:scale-95"
                                        title="비밀번호 리셋"
                                    >
                                        <i className="fas fa-key mr-1"></i>비번 리셋
                                    </button>
                                    {!isAdmin && (
                                        <button
                                            onClick={() => setDeleteTarget(user)}
                                            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-red-500/20 text-gray-500 hover:text-red-400 text-xs font-medium transition-colors active:scale-95"
                                            title="사용자 삭제"
                                        >
                                            <i className="fas fa-trash-alt"></i>
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
                {filtered.length === 0 && (
                    <div className="text-center py-12 text-gray-500 text-sm">
                        <i className="fas fa-users text-2xl mb-3 block"></i>
                        해당하는 사용자가 없습니다
                    </div>
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
                            <button
                                onClick={() => setResetTarget(null)}
                                className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors"
                            >
                                취소
                            </button>
                            <button
                                onClick={handleResetPassword}
                                disabled={!newPassword || newPassword.length < 6}
                                className="flex-1 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-sm font-bold transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                            >
                                리셋
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* 삭제 확인 모달 */}
            {deleteTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setDeleteTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">사용자 삭제</h3>
                        <p className="text-sm text-gray-400 mb-2">
                            <span className="text-white font-bold">{deleteTarget.name}</span> ({deleteTarget.email})
                        </p>
                        <p className="text-sm text-red-400 mb-4">삭제하면 복구할 수 없습니다.</p>
                        <div className="flex gap-2">
                            <button
                                onClick={() => setDeleteTarget(null)}
                                className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors"
                            >
                                취소
                            </button>
                            <button
                                onClick={handleDelete}
                                className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-white text-sm font-bold transition-colors"
                            >
                                삭제
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
