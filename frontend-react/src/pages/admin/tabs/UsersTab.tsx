import { useEffect, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { adminAPI, AdminUser, fetchAuthAPI } from '@/lib/api';

const TIER_STYLES: Record<string, { label: string; cls: string }> = {
    none: { label: 'No Tier', cls: 'bg-gray-500/20 text-gray-400' },
    pro: { label: 'Pro', cls: 'bg-amber-500/20 text-amber-400' },
    premium: { label: 'Ultra Pro', cls: 'bg-purple-500/20 text-purple-400' },
};

export function UsersTab({ apiToken, currentUserId }: { apiToken?: string; currentUserId?: number | string }) {
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    const [filterTier, setFilterTier] = useState('all');
    const [filterStatus, setFilterStatus] = useState('all');
    const [search, setSearch] = useState('');
    const [searchDebounced, setSearchDebounced] = useState('');
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [totalPages, setTotalPages] = useState(1);
    const loadSequence = useRef(0);
    const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
    const [newPassword, setNewPassword] = useState('');
    const [resetNote, setResetNote] = useState('');
    const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
    const [expiryTarget, setExpiryTarget] = useState<AdminUser | null>(null);
    const [expiryValue, setExpiryValue] = useState('');
    const [detailUser, setDetailUser] = useState<any | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [duplicates, setDuplicates] = useState<Array<{ reason: string; key: string; accounts: Array<{ id: number; email: string; name: string; tier: string | null; status: string; created_at: string | null; last_login_at: string | null }> }>>([]);
    const [showDuplicates, setShowDuplicates] = useState(false);
    const [mobileMenuId, setMobileMenuId] = useState<number | null>(null);

    // Search debounce (300ms)
    useEffect(() => {
        const timer = setTimeout(() => {
            setSearchDebounced(search.trim());
            setPage(1);
        }, 300);
        return () => clearTimeout(timer);
    }, [search]);

    const loadDuplicates = async () => {
        try {
            const res = await adminAPI.getDuplicates(apiToken);
            setDuplicates(res.groups || []);
        } catch { /* */ }
    };

    const openUserDetail = async (userId: number) => {
        setDetailLoading(true);
        try {
            const data = await fetchAuthAPI<any>(`/api/admin/users/${userId}`, apiToken);
            setDetailUser(data);
        } catch { /* */ }
        setDetailLoading(false);
    };

    const loadUsers = useCallback(async () => {
        const sequence = ++loadSequence.current;
        setLoading(true);
        try {
            const res = await adminAPI.getUsers(apiToken, {
                q: searchDebounced || undefined,
                tier: filterTier === 'all' ? undefined : filterTier,
                status: filterStatus === 'all' ? undefined : filterStatus,
                page,
                per_page: 50,
            });
            if (sequence === loadSequence.current) {
                setUsers(res.users || []);
                setTotal(res.total ?? res.users?.length ?? 0);
                setTotalPages(Math.max(1, res.total_pages ?? 1));
            }
        } catch { /* */ }
        if (sequence === loadSequence.current) setLoading(false);
    }, [apiToken, filterStatus, filterTier, page, searchDebounced]);

    useEffect(() => { void loadUsers(); }, [loadUsers]);
    useEffect(() => { void loadDuplicates(); }, [apiToken]);
    useEffect(() => { setSelectedIds(new Set()); }, [filterStatus, filterTier, page, searchDebounced]);

    const showAction = (msg: string, isError = false) => {
        setActionMsg(isError ? `error:${msg}` : `ok:${msg}`);
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

    // 가입 시 요청한 플랜으로 원클릭 승인 — tier 부여 + status=approved + 만료일 세팅 일괄 처리.
    // setUserTier 는 백엔드에서 상기 3개를 원자적으로 처리한다 (admin.py:267).
    const handleApproveWithRequestedTier = async (user: AdminUser) => {
        const tier = user.requested_tier;
        if (!tier) return;
        const tierLabel = tier === 'pro' ? 'Pro (30일)' : 'Ultra Pro (무기한)';
        if (!confirm(`${user.name} (${user.email}) 을 ${tierLabel} 로 승인하시겠습니까?\n입금 확인 후 클릭하세요.`)) return;
        try {
            const res = await adminAPI.setUserTier(user.id, tier, apiToken);
            setUsers(prev => prev.map(u => u.id === user.id ? res.user : u));
            showAction(`${user.name} → ${tierLabel} 승인 완료`);
        } catch (err: any) { showAction(err.message, true); }
    };

    // 중복 그룹 — user_id → 그룹 사유/키 매핑 (렌더링 시 O(1) 조회용)
    const duplicateMap = new Map<number, { reason: string; key: string; count: number }>();
    for (const group of duplicates) {
        for (const acc of group.accounts) {
            duplicateMap.set(acc.id, { reason: group.reason, key: group.key, count: group.accounts.length });
        }
    }

    const handleResetPassword = async () => {
        if (!resetTarget || !newPassword) return;
        if (newPassword.length < 8 || !/[A-Za-z]/.test(newPassword) || !/\d/.test(newPassword)) return;
        if (!resetNote.trim()) return;
        try {
            await adminAPI.resetPassword(resetTarget.id, newPassword, apiToken, resetNote.trim());
            showAction(`${resetTarget.name} 비밀번호 변경 완료`);
            setResetTarget(null);
            setNewPassword('');
            setResetNote('');
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await adminAPI.deleteUser(deleteTarget.id, apiToken);
            setUsers(prev => prev.filter(u => u.id !== deleteTarget.id));
            setDuplicates(prev => prev
                .map(g => ({ ...g, accounts: g.accounts.filter(a => a.id !== deleteTarget.id) }))
                .filter(g => g.accounts.length >= 2));
            showAction(`${deleteTarget.name} 삭제 완료`);
            setDeleteTarget(null);
        } catch (err: any) { showAction(err.message, true); }
    };

    // 중복 그룹 일괄 삭제 (주 계정/본인 제외)
    const handleDeleteDuplicates = async (ids: number[], groupKey: string) => {
        if (ids.length === 0) return;
        if (!confirm(`"${groupKey}" 그룹의 중복 계정 ${ids.length}개를 일괄 삭제합니다.\n이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`)) return;
        let ok = 0, fail = 0;
        for (const id of ids) {
            try {
                await adminAPI.deleteUser(id, apiToken);
                ok++;
            } catch { fail++; }
        }
        setUsers(prev => prev.filter(u => !ids.includes(u.id)));
        setDuplicates(prev => prev
            .map(g => ({ ...g, accounts: g.accounts.filter(a => !ids.includes(a.id)) }))
            .filter(g => g.accounts.length >= 2));
        showAction(fail === 0 ? `${ok}개 중복 계정 삭제 완료` : `삭제 ${ok}건, 실패 ${fail}건`, fail > 0);
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

    // Bulk actions
    const handleBulkApprove = async () => {
        const ids = Array.from(selectedIds);
        if (ids.length === 0) return;
        try {
            await adminAPI.bulkApprove(ids, apiToken);
            setUsers(prev => prev.map(u => ids.includes(u.id) ? { ...u, status: 'approved' } : u));
            showAction(`${ids.length}명 일괄 승인 완료`);
            setSelectedIds(new Set());
        } catch (err: any) { showAction(err.message, true); }
    };

    const handleBulkTier = async (tier: string) => {
        const ids = Array.from(selectedIds);
        if (ids.length === 0) return;
        try {
            await adminAPI.bulkTier(ids, tier, apiToken);
            setUsers(prev => prev.map(u => ids.includes(u.id) ? { ...u, tier } : u));
            showAction(`${ids.length}명 일괄 ${TIER_STYLES[tier]?.label || tier} 부여`);
            setSelectedIds(new Set());
        } catch (err: any) { showAction(err.message, true); }
    };

    const toggleSelect = (id: number) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const toggleSelectAll = () => {
        const selectable = filtered.filter(u => u.role !== 'admin');
        if (selectedIds.size === selectable.length && selectable.length > 0) {
            setSelectedIds(new Set());
        } else {
            setSelectedIds(new Set(selectable.map(u => u.id)));
        }
    };

    // 검색/필터는 전체 회원 DB를 대상으로 서버에서 수행한다. 현재 배열은 현재 페이지 결과다.
    const filtered = users;

    const tierCount = (t: string) => users.filter(u => (u.tier || 'none') === t).length;
    const statusCount = (s: string) => users.filter(u => u.status === s).length;
    const aibainActiveCount = users.filter(u => u.is_aibain_active).length;
    const aibainExpiringSoonCount = users.filter(u =>
        u.is_aibain_active && typeof u.aibain_days_remaining === 'number' && u.aibain_days_remaining <= 3
    ).length;

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

    const daysSince = (iso: string | null): string => {
        if (!iso) return '-';
        const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
        return `${days}일째`;
    };

    // Password strength
    const pwStrength = (pw: string): { level: number; label: string; cls: string } => {
        if (!pw) return { level: 0, label: '', cls: '' };
        const hasLetter = /[A-Za-z]/.test(pw);
        const hasDigit = /\d/.test(pw);
        const hasSpecial = /[^A-Za-z0-9]/.test(pw);
        const long = pw.length >= 12;
        if (pw.length < 8 || !hasLetter || !hasDigit) return { level: 1, label: '약함', cls: 'bg-red-500' };
        if (long && hasSpecial) return { level: 3, label: '강함', cls: 'bg-emerald-500' };
        return { level: 2, label: '보통', cls: 'bg-amber-500' };
    };

    const pwValid = newPassword.length >= 8 && /[A-Za-z]/.test(newPassword) && /\d/.test(newPassword);

    if (loading && users.length === 0) return <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" /></div>;

    return (
        <>
            {/* 요약 바 */}
            <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
                <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                    <span className="text-white font-semibold">{total}명 검색됨</span>
                    <span>현재 페이지 {users.length}명</span>
                    <span className="text-amber-400">{tierCount('pro')} Pro</span>
                    <span className="text-purple-400">{tierCount('premium')} Ultra</span>
                    <span>{tierCount('none')} No Tier</span>
                    {aibainActiveCount > 0 && (
                        <span
                            className="text-cyan-300"
                            title={aibainExpiringSoonCount > 0 ? `D-3 이내 만료 임박 ${aibainExpiringSoonCount}명` : 'AI Brain 활성 구독자'}
                        >
                            <i className="fas fa-robot text-[10px] mr-1" />
                            {aibainActiveCount} AI Brain
                            {aibainExpiringSoonCount > 0 && (
                                <span className="ml-1 text-rose-300 font-bold">(D-3↓ {aibainExpiringSoonCount})</span>
                            )}
                        </span>
                    )}
                    {statusCount('pending') > 0 && (
                        <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 font-bold">
                            승인 대기 {statusCount('pending')}
                        </span>
                    )}
                    {duplicates.length > 0 && (
                        <button onClick={() => setShowDuplicates(!showDuplicates)}
                            className="px-2 py-0.5 rounded bg-red-500/15 text-red-400 font-bold hover:bg-red-500/25 transition-colors">
                            중복 의심 {duplicates.length}
                        </button>
                    )}
                </div>
            </div>

            {actionMsg && (
                <div className={`p-3 rounded-lg text-sm font-medium ${actionMsg.startsWith('error:') ? 'bg-red-500/10 border border-red-500/20 text-red-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'}`}>
                    {actionMsg.replace(/^(error:|ok:)/, '')}
                </div>
            )}

            {/* 중복 계정 경고 패널 */}
            {showDuplicates && duplicates.length > 0 && (
                <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 space-y-3">
                    <div className="flex items-center justify-between">
                        <h3 className="text-sm font-bold text-red-400">
                            <i className="fas fa-exclamation-triangle mr-1.5" />중복 계정 탐지 ({duplicates.length}그룹)
                        </h3>
                        <button onClick={() => setShowDuplicates(false)} className="text-gray-500 hover:text-white text-xs">
                            <i className="fas fa-times" />
                        </button>
                    </div>
                    <p className="text-[10px] text-gray-500">
                        <i className="fas fa-shield-alt mr-1 text-emerald-400" />최근 로그인 계정 = 주 계정 (보호). 나머지 = 중복 의심 (삭제 가능).
                    </p>
                    <div className="space-y-2 max-h-72 overflow-y-auto">
                        {duplicates.map((group, gi) => {
                            // 주 계정 판별 우선순위:
                            // 1) 유료 tier (pro/premium) 중 가장 최근 로그인 (로그인 없으면 가장 오래된 가입일)
                            // 2) 무료 계정이라도 로그인 기록 있는 계정 중 가장 최근
                            // 3) 로그인 기록 없으면 가장 먼저 가입한 계정
                            const score = (a: typeof group.accounts[0]): string => {
                                const tierScore = a.tier === 'premium' ? '3' : a.tier === 'pro' ? '2' : '1';
                                const loginScore = a.last_login_at ? '1' : '0';
                                // 로그인 있으면 최근순, 없으면 오래된 가입순(invert created_at)
                                const timeScore = a.last_login_at
                                    ? a.last_login_at
                                    : '~' + (a.created_at || '');  // '~' > 모든 ISO → 로그인 있는게 우선
                                return `${tierScore}|${loginScore}|${timeScore}`;
                            };
                            const primaryId = group.accounts.reduce((bestId, acc) => {
                                const best = group.accounts.find(a => a.id === bestId);
                                if (!best) return acc.id;
                                // 로그인 기록 없는 경우: 가입일이 빠른 것이 주 계정
                                if (!best.last_login_at && !acc.last_login_at) {
                                    const bestTier = best.tier === 'premium' ? 3 : best.tier === 'pro' ? 2 : 1;
                                    const accTier = acc.tier === 'premium' ? 3 : acc.tier === 'pro' ? 2 : 1;
                                    if (accTier !== bestTier) return accTier > bestTier ? acc.id : bestId;
                                    return (acc.created_at || '') < (best.created_at || '') ? acc.id : bestId;
                                }
                                return score(acc) > score(best) ? acc.id : bestId;
                            }, group.accounts[0]?.id);

                            // 삭제 대상: 주 계정 + 본인 제외
                            const deletableIds = group.accounts
                                .filter(a => a.id !== primaryId && String(a.id) !== String(currentUserId))
                                .map(a => a.id);

                            return (
                                <div key={gi} className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
                                    <div className="flex items-center justify-between mb-2 gap-2">
                                        <div className="text-xs text-gray-400 min-w-0">
                                            <span className="text-red-400 font-bold">{group.reason === 'same_name' ? '동일 이름' : '유사 이메일'}</span>
                                            <span className="ml-1.5 text-white font-medium">{group.key}</span>
                                            <span className="ml-2 text-gray-600">({group.accounts.length}개)</span>
                                        </div>
                                        {deletableIds.length >= 2 && (
                                            <button onClick={() => handleDeleteDuplicates(deletableIds, group.key)}
                                                className="shrink-0 px-2 py-1 rounded text-[10px] font-bold bg-red-500/15 text-red-400 hover:bg-red-500/30 border border-red-500/30 transition-colors"
                                                title="주 계정 제외한 중복 계정 모두 삭제">
                                                <i className="fas fa-trash-alt mr-1" />중복 {deletableIds.length}개 일괄 삭제
                                            </button>
                                        )}
                                    </div>
                                    <div className="space-y-1">
                                        {group.accounts.map(acc => {
                                            const isPrimary = acc.id === primaryId;
                                            const isCurrentAdmin = currentUserId != null && String(acc.id) === String(currentUserId);
                                            const isProtected = isPrimary || isCurrentAdmin;

                                            return (
                                                <div key={acc.id} className={`flex items-center justify-between text-xs px-2 py-1.5 rounded ${isPrimary ? 'bg-emerald-500/5 border border-emerald-500/15' : 'bg-white/[0.02]'}`}>
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        {isPrimary ? (
                                                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-400 shrink-0">주 계정</span>
                                                        ) : (
                                                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red-500/15 text-red-400 shrink-0">중복</span>
                                                        )}
                                                        {isCurrentAdmin && (
                                                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-500/20 text-blue-400 shrink-0">나</span>
                                                        )}
                                                        <span className="text-white font-medium truncate">{acc.email}</span>
                                                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${TIER_STYLES[acc.tier || 'none']?.cls || 'bg-gray-500/20 text-gray-400'}`}>
                                                            {TIER_STYLES[acc.tier || 'none']?.label || 'No Tier'}
                                                        </span>
                                                        <span className={`text-[10px] ${acc.status === 'approved' ? 'text-emerald-400' : acc.status === 'suspended' ? 'text-red-400' : 'text-amber-400'}`}>
                                                            {acc.status === 'approved' ? '활성' : acc.status === 'suspended' ? '정지' : '대기'}
                                                        </span>
                                                        <span className="text-[10px] text-gray-600 hidden sm:inline">
                                                            {acc.last_login_at ? `로그인 ${new Date(acc.last_login_at).toLocaleDateString('ko-KR')}` : '미접속'}
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-1 shrink-0">
                                                        <button onClick={() => openUserDetail(acc.id)}
                                                            className="p-1 rounded text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors" title="상세">
                                                            <i className="fas fa-eye text-[10px]" />
                                                        </button>
                                                        {!isProtected && (
                                                            <button onClick={() => setDeleteTarget({ id: acc.id, name: acc.name, email: acc.email } as AdminUser)}
                                                                className="p-1 rounded text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors" title="삭제">
                                                                <i className="fas fa-trash-alt text-[10px]" />
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* 벌크 액션 바 */}
            {selectedIds.size > 0 && (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
                    <span className="text-sm text-amber-400 font-bold">{selectedIds.size}명 선택</span>
                    <div className="flex gap-1.5">
                        <button onClick={handleBulkApprove}
                            className="px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 text-xs font-bold hover:bg-emerald-500/25 transition-colors">
                            일괄 승인
                        </button>
                        <button onClick={() => handleBulkTier('pro')}
                            className="px-3 py-1.5 rounded-lg bg-amber-500/15 text-amber-400 text-xs font-bold hover:bg-amber-500/25 transition-colors">
                            일괄 Pro
                        </button>
                        <button onClick={() => handleBulkTier('premium')}
                            className="px-3 py-1.5 rounded-lg bg-purple-500/15 text-purple-400 text-xs font-bold hover:bg-purple-500/25 transition-colors">
                            일괄 Ultra
                        </button>
                    </div>
                    <button onClick={() => setSelectedIds(new Set())}
                        className="ml-auto text-xs text-gray-500 hover:text-white transition-colors">선택 해제</button>
                </div>
            )}

            {/* 필터 + 검색 */}
            <div className="flex items-center gap-3 flex-wrap">
                <div className="relative flex-1 min-w-[200px]">
                    <input
                        type="search" value={search} onChange={e => setSearch(e.target.value)}
                        placeholder="회원 ID, 이름 또는 이메일 검색..."
                        className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
                    />
                    {search && (
                        <button onClick={() => setSearch('')}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white text-xs">
                            <i className="fas fa-times" />
                        </button>
                    )}
                </div>
                <div className="flex gap-1">
                    {[{ key: 'all', label: '전체' }, { key: 'premium', label: 'Ultra Pro' }, { key: 'pro', label: 'Pro' }, { key: 'aibain', label: 'AI Brain' }, { key: 'aibain_expired', label: 'AI 만료' }, { key: 'none', label: 'No Tier' }].map(tab => (
                        <button key={tab.key} onClick={() => { setFilterTier(tab.key); setPage(1); }}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                                filterTier === tab.key
                                    ? (tab.key === 'aibain' ? 'bg-cyan-500/15 text-cyan-300' : 'bg-white/10 text-white')
                                    : (tab.key === 'aibain' ? 'text-cyan-300/70 hover:text-cyan-300 hover:bg-cyan-500/10' : 'text-gray-500 hover:text-white hover:bg-white/5')
                            }`}>
                            {tab.key === 'aibain' && <i className="fas fa-robot text-[10px] mr-1" />}
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
                        <button key={tab.key} onClick={() => { setFilterStatus(tab.key); setPage(1); }}
                            className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${filterStatus === tab.key ? `bg-white/10 ${tab.cls}` : `${tab.cls} hover:text-white hover:bg-white/5`}`}>
                            {tab.label}
                        </button>
                    ))}
                </div>
                {(filterTier !== 'all' || filterStatus !== 'all' || search) && (
                    <button onClick={() => { setFilterTier('all'); setFilterStatus('all'); setSearch(''); setPage(1); }}
                        className="px-3 py-2 rounded-lg text-xs font-medium text-gray-500 hover:text-white hover:bg-white/5 transition-colors">
                        <i className="fas fa-undo mr-1" />초기화
                    </button>
                )}
            </div>

            {/* 테이블 */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <table className="w-full">
                    <thead>
                        <tr className="bg-white/[0.03]">
                            <th className="w-10 px-3 py-3">
                                <input type="checkbox"
                                    checked={filtered.filter(u => u.role !== 'admin').length > 0 && selectedIds.size === filtered.filter(u => u.role !== 'admin').length}
                                    onChange={toggleSelectAll}
                                    className="rounded border-gray-600 bg-white/5 text-amber-500 focus:ring-amber-500/50 cursor-pointer" />
                            </th>
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
                            const dupInfo = duplicateMap.get(user.id);
                            const canOneClickApprove = user.status === 'pending' && !!user.requested_tier && !isAdmin;
                            return (
                                <tr key={user.id} className={`border-t border-white/[0.04] hover:bg-white/[0.02] transition-colors ${isSuspended ? 'opacity-50' : ''}`}>
                                    <td className="w-10 px-3 py-3">
                                        {!isAdmin ? (
                                            <input type="checkbox" checked={selectedIds.has(user.id)} onChange={() => toggleSelect(user.id)}
                                                className="rounded border-gray-600 bg-white/5 text-amber-500 focus:ring-amber-500/50 cursor-pointer" />
                                        ) : <div className="w-4" />}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 ${isAdmin ? 'bg-red-500' : 'bg-white/10'}`}>
                                                {user.name.charAt(0).toUpperCase()}
                                            </div>
                                            <div className="min-w-0">
                                                <div className="flex items-center gap-1.5 flex-wrap">
                                                    <button onClick={() => openUserDetail(user.id)} className="text-sm font-medium text-white truncate hover:text-amber-400 transition-colors text-left">{user.name}</button>
                                                    {isAdmin && <span className="text-[9px] px-1 py-0.5 bg-red-500/20 text-red-400 rounded shrink-0">관리자</span>}
                                                    {isSuspended && <span className="text-[9px] px-1 py-0.5 bg-red-500/20 text-red-400 rounded shrink-0">정지</span>}
                                                    {user.status === 'pending' && <span className="text-[9px] px-1 py-0.5 bg-amber-500/20 text-amber-400 rounded shrink-0">대기</span>}
                                                    {/* 중복 의심 경고 배지 — 승인 전 눈에 띄게 */}
                                                    {dupInfo && (
                                                        <span
                                                            className="text-[9px] px-1 py-0.5 bg-rose-500/20 text-rose-300 rounded shrink-0 cursor-help"
                                                            title={`${dupInfo.reason === 'same_name' ? '동명이인' : '유사 이메일'} — 그룹 "${dupInfo.key}" 총 ${dupInfo.count}개 계정`}
                                                        >
                                                            <i className="fas fa-exclamation-triangle mr-0.5" />
                                                            중복{dupInfo.count}
                                                        </span>
                                                    )}
                                                    {/* 가입 시 요청 플랜 칩 — pending 유저만 표시 */}
                                                    {user.status === 'pending' && user.requested_tier === 'pro' && (
                                                        <span className="text-[9px] px-1 py-0.5 bg-amber-500/15 text-amber-300 rounded shrink-0">
                                                            📋 Pro 요청
                                                        </span>
                                                    )}
                                                    {user.status === 'pending' && user.requested_tier === 'premium' && (
                                                        <span className="text-[9px] px-1 py-0.5 bg-purple-500/15 text-purple-300 rounded shrink-0">
                                                            📋 Ultra Pro 요청
                                                        </span>
                                                    )}
                                                    {/* AI Brain 활성 상태 배지 — 백엔드 is_aibain_active=true */}
                                                    {user.is_aibain_active && (
                                                        <span
                                                            className="text-[9px] px-1 py-0.5 bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 rounded shrink-0 font-bold"
                                                            title={user.aibain_days_remaining != null
                                                                ? `AI Brain 활성 — D-${user.aibain_days_remaining} 만료`
                                                                : 'AI Brain 활성'}
                                                        >
                                                            🤖 AI Brain{user.aibain_days_remaining != null && user.aibain_days_remaining <= 3 ? ` D-${user.aibain_days_remaining}` : ''}
                                                        </span>
                                                    )}
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
                                        {/* Desktop: inline buttons */}
                                        <div className="hidden md:flex items-center justify-end gap-1">
                                            {/* 요청 플랜 원클릭 승인 — pending + requested_tier 있을 때만 */}
                                            {canOneClickApprove && (
                                                <button
                                                    onClick={() => handleApproveWithRequestedTier(user)}
                                                    className={`px-2 py-1 rounded-lg text-[10px] font-bold transition-colors ${
                                                        user.requested_tier === 'premium'
                                                            ? 'bg-purple-500/20 text-purple-300 hover:bg-purple-500/30'
                                                            : 'bg-amber-500/20 text-amber-300 hover:bg-amber-500/30'
                                                    }`}
                                                    title={`입금 확인 후 클릭 → ${user.requested_tier === 'pro' ? 'Pro 30일' : 'Ultra Pro 무기한'} 승인`}
                                                >
                                                    <i className="fas fa-check-double mr-1" />
                                                    {user.requested_tier === 'pro' ? 'Pro 승인' : 'Ultra 승인'}
                                                </button>
                                            )}
                                            {user.status === 'pending' && !isAdmin && !canOneClickApprove && (
                                                <button onClick={() => handleApprove(user)}
                                                    className="p-1.5 rounded-lg text-amber-400 hover:bg-amber-500/10 text-xs transition-colors" title="승인">
                                                    <i className="fas fa-check" />
                                                </button>
                                            )}
                                            {user.tier === 'pro' && !isAdmin && (
                                                <button onClick={() => handleExtend(user, 30)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/10 text-xs transition-colors" title="+30일 연장">
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
                                            <button onClick={() => { setResetTarget(user); setNewPassword(''); setResetNote(''); }}
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
                                        {/* Mobile: dropdown menu */}
                                        <div className="md:hidden relative flex justify-end">
                                            <button onClick={() => setMobileMenuId(mobileMenuId === user.id ? null : user.id)}
                                                className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/10 text-xs transition-colors">
                                                <i className="fas fa-ellipsis-v" />
                                            </button>
                                            {mobileMenuId === user.id && (
                                                <div className="absolute right-0 top-8 z-50 bg-[#1c1c1e] border border-white/10 rounded-xl shadow-xl py-1 min-w-[140px]"
                                                    onClick={() => setMobileMenuId(null)}>
                                                    <button onClick={() => openUserDetail(user.id)}
                                                        className="w-full px-4 py-2.5 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white">
                                                        <i className="fas fa-eye mr-2 text-amber-400" />상세 보기
                                                    </button>
                                                    {canOneClickApprove && (
                                                        <button onClick={() => handleApproveWithRequestedTier(user)}
                                                            className={`w-full px-4 py-2.5 text-left text-xs hover:bg-white/5 ${user.requested_tier === 'premium' ? 'text-purple-300' : 'text-amber-300'}`}>
                                                            <i className="fas fa-check-double mr-2" />{user.requested_tier === 'pro' ? 'Pro 승인 (30일)' : 'Ultra Pro 승인'}
                                                        </button>
                                                    )}
                                                    {user.status === 'pending' && !isAdmin && !canOneClickApprove && (
                                                        <button onClick={() => handleApprove(user)}
                                                            className="w-full px-4 py-2.5 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white">
                                                            <i className="fas fa-check mr-2 text-emerald-400" />승인
                                                        </button>
                                                    )}
                                                    {!isAdmin && (
                                                        <button onClick={() => handleSuspend(user.id, user.name, user.status)}
                                                            className="w-full px-4 py-2.5 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white">
                                                            <i className={`fas ${isSuspended ? 'fa-undo' : 'fa-ban'} mr-2 ${isSuspended ? 'text-emerald-400' : 'text-red-400'}`} />
                                                            {isSuspended ? '복원' : '정지'}
                                                        </button>
                                                    )}
                                                    <button onClick={() => { setResetTarget(user); setNewPassword(''); setResetNote(''); }}
                                                        className="w-full px-4 py-2.5 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white">
                                                        <i className="fas fa-key mr-2 text-amber-400" />비밀번호 리셋
                                                    </button>
                                                    {!isAdmin && (
                                                        <button onClick={() => setDeleteTarget(user)}
                                                            className="w-full px-4 py-2.5 text-left text-xs text-gray-300 hover:bg-white/5 hover:text-white">
                                                            <i className="fas fa-trash-alt mr-2 text-red-400" />삭제
                                                        </button>
                                                    )}
                                                </div>
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

            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 pt-1">
                    <button
                        type="button"
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page <= 1 || loading}
                        className="px-3 py-2 rounded-lg bg-white/5 text-gray-300 text-xs hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                        <i className="fas fa-chevron-left mr-1" />이전
                    </button>
                    <span className="text-xs text-gray-400">{page} / {totalPages} 페이지</span>
                    <button
                        type="button"
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        disabled={page >= totalPages || loading}
                        className="px-3 py-2 rounded-lg bg-white/5 text-gray-300 text-xs hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                        다음<i className="fas fa-chevron-right ml-1" />
                    </button>
                </div>
            )}

            {/* 비밀번호 리셋 모달 */}
            {resetTarget && createPortal(
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60" style={{ backdropFilter: 'blur(4px)' }} onClick={() => setResetTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">비밀번호 리셋</h3>
                        <p className="text-sm text-gray-400 mb-4">{resetTarget.name} ({resetTarget.email})</p>
                        <input type="text" value={newPassword} onChange={e => setNewPassword(e.target.value)}
                            placeholder="새 비밀번호 (8자 이상, 영문+숫자)"
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-amber-500/50 mb-2" autoFocus />
                        {/* 비밀번호 강도 인디케이터 */}
                        {newPassword && (
                            <div className="mb-3">
                                <div className="flex gap-1 mb-1">
                                    {[1, 2, 3].map(i => (
                                        <div key={i} className={`h-1 flex-1 rounded-full ${i <= pwStrength(newPassword).level ? pwStrength(newPassword).cls : 'bg-white/10'}`} />
                                    ))}
                                </div>
                                <div className="flex justify-between text-[10px]">
                                    <span className={pwStrength(newPassword).level >= 1 ? 'text-gray-400' : 'text-gray-600'}>
                                        {pwStrength(newPassword).label}
                                    </span>
                                    {!pwValid && <span className="text-red-400">8자 이상, 영문+숫자 필수</span>}
                                </div>
                            </div>
                        )}
                        <input type="text" value={resetNote} onChange={e => setResetNote(e.target.value)}
                            placeholder="리셋 사유 (필수)"
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-amber-500/50 mb-4" />
                        <div className="flex gap-2">
                            <button onClick={() => setResetTarget(null)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors">취소</button>
                            <button onClick={handleResetPassword} disabled={!pwValid || !resetNote.trim()}
                                className="flex-1 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-black text-sm font-bold transition-colors disabled:opacity-30">변경</button>
                        </div>
                    </div>
                </div>,
            document.getElementById('modal-root') || document.body)}

            {/* 만료일 변경 모달 */}
            {expiryTarget && createPortal(
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60" style={{ backdropFilter: 'blur(4px)' }} onClick={() => setExpiryTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
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
                </div>,
            document.getElementById('modal-root') || document.body)}

            {/* 삭제 확인 모달 */}
            {deleteTarget && createPortal(
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60" style={{ backdropFilter: 'blur(4px)' }} onClick={() => setDeleteTarget(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-1">회원 삭제</h3>
                        <p className="text-sm text-gray-400 mb-2"><span className="text-white font-bold">{deleteTarget.name}</span> ({deleteTarget.email})</p>
                        <p className="text-sm text-red-400 mb-4">삭제하면 복구할 수 없습니다.</p>
                        <div className="flex gap-2">
                            <button onClick={() => setDeleteTarget(null)} className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 text-sm font-medium transition-colors">취소</button>
                            <button onClick={handleDelete} className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-white text-sm font-bold transition-colors">삭제</button>
                        </div>
                    </div>
                </div>,
            document.getElementById('modal-root') || document.body)}

            {/* 회원 상세 정보 모달 */}
            {(detailUser || detailLoading) && createPortal(
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60" style={{ backdropFilter: 'blur(4px)' }} onClick={() => setDetailUser(null)}>
                    <div className="bg-[#1c1c1e] border border-white/10 rounded-2xl p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto mx-4" onClick={e => e.stopPropagation()}>
                        {detailLoading && !detailUser ? (
                            <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" /></div>
                        ) : detailUser ? (
                            <>
                                <div className="flex items-center justify-between mb-4">
                                    <div>
                                        <h3 className="text-lg font-bold text-white">회원 상세 정보</h3>
                                        {detailUser.created_at && (
                                            <span className="text-xs text-gray-500">가입 {daysSince(detailUser.created_at)}</span>
                                        )}
                                    </div>
                                    <button onClick={() => setDetailUser(null)} className="text-gray-500 hover:text-white transition-colors">
                                        <i className="fas fa-times" />
                                    </button>
                                </div>

                                {/* 중복 계정 경고 */}
                                {duplicates.some(g => g.accounts.some(a => a.id === detailUser.id)) && (
                                    <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20">
                                        <div className="flex items-center gap-2 text-xs text-red-400 font-bold">
                                            <i className="fas fa-exclamation-triangle" />
                                            같은 이름으로 다른 계정이 존재합니다
                                        </div>
                                    </div>
                                )}

                                {/* 기본 정보 */}
                                <div className="grid grid-cols-2 gap-3 mb-4">
                                    {[
                                        { label: '이름', value: detailUser.name },
                                        { label: '이메일', value: detailUser.email },
                                        { label: '가입일', value: detailUser.created_at ? new Date(detailUser.created_at).toLocaleString('ko-KR') : '-' },
                                        { label: '마지막 로그인', value: detailUser.last_login_at ? new Date(detailUser.last_login_at).toLocaleString('ko-KR') : '없음' },
                                        { label: '플랜', value: detailUser.tier === 'premium' ? 'Ultra Pro' : detailUser.tier === 'pro' ? 'Pro' : '없음' },
                                        { label: '상태', value: detailUser.status === 'approved' ? '승인' : detailUser.status === 'pending' ? '대기' : detailUser.status === 'suspended' ? '정지' : detailUser.status },
                                        { label: '역할', value: detailUser.role === 'admin' ? '관리자' : '일반 사용자' },
                                        { label: 'Pro 만료일', value: detailUser.pro_expires_at ? new Date(detailUser.pro_expires_at).toLocaleDateString('ko-KR') : '—' },
                                    ].map(item => (
                                        <div key={item.label} className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">{item.label}</span>
                                            <p className="text-white text-sm font-medium mt-0.5 truncate">{item.value}</p>
                                        </div>
                                    ))}
                                </div>

                                {/* 모달 내 빠른 액션 */}
                                {detailUser.role !== 'admin' && (
                                    <div className="flex gap-2 mb-4">
                                        <button onClick={() => { setResetTarget(detailUser); setNewPassword(''); setResetNote(''); }}
                                            className="flex-1 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-amber-400 text-xs font-bold transition-colors">
                                            <i className="fas fa-key mr-1.5" />비번 리셋
                                        </button>
                                        <button onClick={() => handleSuspend(detailUser.id, detailUser.name, detailUser.status)}
                                            className={`flex-1 py-2 rounded-xl text-xs font-bold transition-colors ${detailUser.status === 'suspended' ? 'bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400' : 'bg-red-500/10 hover:bg-red-500/20 text-red-400'}`}>
                                            <i className={`fas ${detailUser.status === 'suspended' ? 'fa-undo' : 'fa-ban'} mr-1.5`} />
                                            {detailUser.status === 'suspended' ? '복원' : '정지'}
                                        </button>
                                        {detailUser.status === 'pending' && (
                                            <button onClick={() => { handleApprove(detailUser); setDetailUser({ ...detailUser, status: 'approved' }); }}
                                                className="flex-1 py-2 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-xs font-bold transition-colors">
                                                <i className="fas fa-check mr-1.5" />승인
                                            </button>
                                        )}
                                    </div>
                                )}

                                {/* 구독 이력 */}
                                {detailUser.subscription_history?.length > 0 && (
                                    <div className="mb-4">
                                        <h4 className="text-sm font-bold text-white mb-2">
                                            <i className="fas fa-credit-card mr-1.5 text-purple-400" />구독 이력
                                        </h4>
                                        <div className="space-y-1.5">
                                            {detailUser.subscription_history.map((s: any) => (
                                                <div key={s.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/[0.03] text-xs">
                                                    <span className="text-gray-400">{s.from_tier || 'none'} → {s.to_tier}</span>
                                                    <div className="flex items-center gap-2">
                                                        <span className={`px-1.5 py-0.5 rounded ${s.status === 'approved' ? 'bg-emerald-500/10 text-emerald-400' : s.status === 'pending' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-red-500/10 text-red-400'}`}>
                                                            {s.status === 'approved' ? '승인' : s.status === 'pending' ? '대기' : '거절'}
                                                        </span>
                                                        <span className="text-gray-600">{new Date(s.created_at).toLocaleDateString('ko-KR')}</span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* 감사 로그 */}
                                {detailUser.audit_logs?.length > 0 && (
                                    <div>
                                        <h4 className="text-sm font-bold text-white mb-2">
                                            <i className="fas fa-history mr-1.5 text-amber-400" />관리 이력
                                        </h4>
                                        <div className="space-y-1.5 max-h-48 overflow-y-auto">
                                            {detailUser.audit_logs.map((log: any) => (
                                                <div key={log.id} className="px-3 py-2 rounded-lg bg-white/[0.03] text-xs">
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-amber-400 font-medium">{log.action}</span>
                                                        <span className="text-gray-600">{new Date(log.created_at).toLocaleString('ko-KR')}</span>
                                                    </div>
                                                    {log.note && <p className="text-gray-500 mt-0.5">{log.note}</p>}
                                                    {log.admin_email && <p className="text-gray-600 mt-0.5">by {log.admin_email}</p>}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </>
                        ) : null}
                    </div>
                </div>,
            document.getElementById('modal-root') || document.body)}
        </>
    );
}

