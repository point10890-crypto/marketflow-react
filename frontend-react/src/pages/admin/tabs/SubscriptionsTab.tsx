import { useEffect, useState, useCallback } from 'react';
import { adminAPI, SubscriptionRequest, PendingSignup } from '@/lib/api';

export default function SubscriptionsTab({ apiToken, onCountChange }: { apiToken?: string; onCountChange: (n: number) => void }) {
    const [requests, setRequests] = useState<SubscriptionRequest[]>([]);
    const [pendingSignups, setPendingSignups] = useState<PendingSignup[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');
    // 처리 중인 request id 추적 — 같은 row 더블클릭 방지 + 이미 처리된 row 보호
    const [processing, setProcessing] = useState<Set<number>>(new Set());
    const [grantingUser, setGrantingUser] = useState<Set<number>>(new Set());

    // silent=true 이면 스피너를 띄우지 않음 (refresh 버튼용 기본은 스피너 O)
    const loadRequests = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const res = await adminAPI.getSubscriptions(apiToken);
            const reqs = res.requests || [];
            setRequests(reqs);
            setPendingSignups(res.pending_signups || []);
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

    // 플랜 미선택 pending 가입자 — tier 부여 (status=approved 자동 승격)
    const handleGrantTier = async (userId: number, tier: 'pro' | 'premium') => {
        if (grantingUser.has(userId)) return;
        setGrantingUser(prev => { const n = new Set(prev); n.add(userId); return n; });
        try {
            await adminAPI.setUserTier(userId, tier, apiToken);
            setPendingSignups(prev => prev.filter(u => u.id !== userId));
            showAction(`✅ ${tier === 'premium' ? 'Ultra Pro' : 'Pro'} 부여 완료`);
        } catch (err: any) {
            showAction(`❌ ${err.message}`);
        } finally {
            setGrantingUser(prev => { const n = new Set(prev); n.delete(userId); return n; });
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
                        {pending.map(req => {
                            const isAibainRenewal = req.request_type === 'aibain_renewal';
                            const isAibainOnly = req.request_type === 'aibain_addon' || isAibainRenewal;
                            const includesAibain = isAibainOnly || !!(req.admin_note && req.admin_note.includes('AI Brain'));
                            const cardBorder = isAibainOnly ? 'border-cyan-500/30' : 'border-yellow-500/20';
                            const iconBg = isAibainOnly ? 'bg-cyan-500/15' : 'bg-yellow-500/10';
                            const iconColor = isAibainOnly ? 'text-cyan-300' : 'text-yellow-400';
                            const iconClass = isAibainOnly ? 'fa-robot' : 'fa-arrow-up';
                            // 승인 버튼 색상/라벨 분기
                            let btnLabel = req.to_tier === 'premium' ? 'Ultra Pro 승인' : 'Pro 승인';
                            let btnIcon = req.to_tier === 'premium' ? 'fa-gem' : 'fa-crown';
                            let btnColor = req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30' : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30';
                            if (isAibainOnly) {
                                btnLabel = isAibainRenewal ? 'AI Brain 재구독 승인' : 'AI Brain 활성화';
                                btnIcon = 'fa-bolt';
                                btnColor = 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30';
                            } else if (includesAibain) {
                                btnLabel = req.to_tier === 'premium' ? 'Ultra Pro + AI Brain 승인' : 'Pro + AI Brain 승인';
                                btnIcon = 'fa-robot';
                                btnColor = 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30';
                            }
                            return (
                                <div key={req.id} className={`apple-glass rounded-xl p-4 border ${cardBorder}`}>
                                    <div className="flex items-center justify-between flex-wrap gap-3">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-10 h-10 ${iconBg} rounded-full flex items-center justify-center`}>
                                                <i className={`fas ${iconClass} ${iconColor}`} />
                                            </div>
                                            <div>
                                                <div className="text-white font-medium flex items-center gap-2 flex-wrap">
                                                    {req.user_name || `User #${req.user_id}`}
                                                    {isAibainOnly && (
                                                        <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 uppercase">
                                                            <i className="fas fa-robot text-[8px] mr-0.5" />
                                                            {isAibainRenewal ? 'AI BRAIN RENEWAL' : 'AI BRAIN ADDON'}
                                                        </span>
                                                    )}
                                                    {!isAibainOnly && includesAibain && (
                                                        <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 uppercase">
                                                            <i className="fas fa-robot text-[8px] mr-0.5" />
                                                            +AI BAIN
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="text-xs text-gray-400">{req.user_email || ''}</div>
                                                <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-1">
                                                    <span className={`px-1.5 py-0.5 rounded ${req.from_tier === 'none' ? 'bg-gray-500/20 text-gray-400' : 'bg-amber-500/20 text-amber-400'}`}>{req.from_tier}</span>
                                                    <span className="mx-1">&rarr;</span>
                                                    <span className={`px-1.5 py-0.5 rounded font-bold ${isAibainOnly ? 'bg-cyan-500/20 text-cyan-300' : req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400' : 'bg-amber-500/20 text-amber-400'}`}>
                                                        {isAibainOnly ? (isAibainRenewal ? 'AI Brain 재구독' : '+AI Brain') : req.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                                    </span>
                                                    {req.depositor_name && (
                                                        <span className="ml-2 px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                                                            <i className="fas fa-user text-[10px] mr-1" />{req.depositor_name}
                                                        </span>
                                                    )}
                                                    {req.amount && (
                                                        <span className={`px-1.5 py-0.5 rounded font-bold ${isAibainOnly ? 'bg-cyan-500/15 text-cyan-300' : 'bg-green-500/10 text-green-400'}`}>
                                                            {req.amount}
                                                        </span>
                                                    )}
                                                    <span className="ml-2 text-gray-600">{new Date(req.created_at).toLocaleString()}</span>
                                                </div>
                                                {req.admin_note && (
                                                    <p className="text-[11px] text-cyan-300/80 mt-1.5 leading-relaxed">
                                                        <i className="fas fa-info-circle text-cyan-400/70 mr-1" />
                                                        {req.admin_note}
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                        <div className="flex gap-2">
                                            <button onClick={() => handleApprove(req.id)}
                                                disabled={processing.has(req.id)}
                                                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${btnColor}`}>
                                                <i className={`fas ${processing.has(req.id) ? 'fa-spinner fa-spin' : btnIcon} mr-1`} />
                                                {btnLabel}
                                            </button>
                                            <button onClick={() => handleReject(req.id)}
                                                disabled={processing.has(req.id)}
                                                className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg text-sm font-medium hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                                <i className="fas fa-times mr-1" /> 거절
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* 플랜 미선택 — 가입만 한 pending 유저 (승인요청 제출 전/이탈) */}
            {pendingSignups.length > 0 && (
                <div>
                    <h2 className="text-lg font-semibold text-orange-400 mb-3">
                        <i className="fas fa-user-clock mr-2" />가입만 완료 · 플랜 미선택 ({pendingSignups.length})
                    </h2>
                    <div className="space-y-3">
                        {pendingSignups.map(u => (
                            <div key={u.id} className="apple-glass rounded-xl p-4 border border-orange-500/20">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-orange-500/10 rounded-full flex items-center justify-center">
                                            <i className="fas fa-user-clock text-orange-400" />
                                        </div>
                                        <div>
                                            <div className="text-white font-medium">{u.name || `User #${u.id}`}</div>
                                            <div className="text-xs text-gray-400">{u.email}</div>
                                            <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-1">
                                                <span className="px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400">승인요청 미제출</span>
                                                {u.requested_tier && (
                                                    <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                                                        희망: {u.requested_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                                    </span>
                                                )}
                                                {u.created_at && <span className="ml-2 text-gray-600">{new Date(u.created_at).toLocaleString()}</span>}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={() => handleGrantTier(u.id, 'pro')}
                                            disabled={grantingUser.has(u.id)}
                                            className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                            <i className={`fas ${grantingUser.has(u.id) ? 'fa-spinner fa-spin' : 'fa-crown'} mr-1`} />
                                            Pro 부여
                                        </button>
                                        <button onClick={() => handleGrantTier(u.id, 'premium')}
                                            disabled={grantingUser.has(u.id)}
                                            className="px-4 py-2 rounded-lg text-sm font-medium bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                            <i className={`fas ${grantingUser.has(u.id) ? 'fa-spinner fa-spin' : 'fa-gem'} mr-1`} />
                                            Ultra Pro 부여
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

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

