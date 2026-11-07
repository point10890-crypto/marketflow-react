import { useEffect, useState, useCallback, useRef } from 'react';
import { adminAPI, SubscriptionRequest, PendingSignup, ExpiredMember } from '@/lib/api';
import { isAiBundleRequest, subscriptionNote, isKongmingSubscriptionRequest, PLAN_PAYMENT_META } from '@/lib/billingInfo';

const kongmingPlanLabel = PLAN_PAYMENT_META.aibain_kongming.label;

export default function SubscriptionsTab({ apiToken, onCountChange }: { apiToken?: string; onCountChange: (n: number) => void }) {
    const [requests, setRequests] = useState<SubscriptionRequest[]>([]);
    const [pendingSignups, setPendingSignups] = useState<PendingSignup[]>([]);
    const [expiredMembers, setExpiredMembers] = useState<ExpiredMember[]>([]);
    const [loading, setLoading] = useState(true);
    const [hasLoaded, setHasLoaded] = useState(false);
    const [loadError, setLoadError] = useState('');
    const requestSequence = useRef(0);
    const mutationLocks = useRef(new Set<string>());
    const [actionMsg, setActionMsg] = useState('');
    // 처리 중인 request id 추적 — 같은 row 더블클릭 방지 + 이미 처리된 row 보호
    const [processing, setProcessing] = useState<Set<number>>(new Set());
    const [grantingUser, setGrantingUser] = useState<Set<number>>(new Set());

    // silent=true 이면 스피너를 띄우지 않음 (refresh 버튼용 기본은 스피너 O)
    const loadRequests = useCallback(async (silent = false) => {
        if (mutationLocks.current.size > 0) return;
        const requestId = ++requestSequence.current;
        if (!silent) setLoading(true);
        try {
            const res = await adminAPI.getSubscriptions(apiToken);
            if (!res || !Array.isArray(res.requests)
                || (res.pending_signups != null && !Array.isArray(res.pending_signups))
                || (res.expired_members != null && !Array.isArray(res.expired_members))) {
                throw new Error('Invalid subscriptions response');
            }
            if (requestId !== requestSequence.current) return;
            const reqs = res.requests;
            setRequests(reqs);
            setPendingSignups(res.pending_signups || []);
            setExpiredMembers(res.expired_members || []);
            onCountChange(reqs.filter((r: SubscriptionRequest) => r.status === 'pending').length);
            setHasLoaded(true);
            setLoadError('');
        } catch {
            if (requestId === requestSequence.current) setLoadError('구독 내역을 불러오지 못했습니다.');
        } finally {
            if (requestId === requestSequence.current) setLoading(false);
        }
    }, [apiToken, onCountChange]);

    // 승인/거절/부여 진행 중에는 자동 갱신을 미룬다 (optimistic UI 를 폴링이 덮어쓰는 것 방지)
    const busyRef = useRef(false);
    busyRef.current = processing.size > 0 || grantingUser.size > 0;

    // AdminPage 상단 배지는 60초 폴링으로 갱신되는데 목록은 수동 새로고침뿐이면
    // "배지 1 인데 목록은 비어 있는" 불일치가 생긴다 → 목록도 같은 주기로 조용히 갱신.
    useEffect(() => {
        loadRequests();
        const refresh = () => {
            if (document.visibilityState === 'visible' && !busyRef.current) loadRequests(true);
        };
        const timer = setInterval(refresh, 60_000);
        document.addEventListener('visibilitychange', refresh);
        return () => {
            requestSequence.current++;
            clearInterval(timer);
            document.removeEventListener('visibilitychange', refresh);
        };
    }, [loadRequests]);

    const showAction = (msg: string) => { setActionMsg(msg); setTimeout(() => setActionMsg(''), 3000); };

    // 입금자명 복사 — 은행 앱 입금 내역과 대조할 때 쓰는 원클릭 액션
    const copyDepositor = async (name: string) => {
        try {
            await navigator.clipboard.writeText(name);
            showAction(`📋 입금자명 "${name}" 복사됨`);
        } catch {
            showAction('❌ 클립보드 복사 실패');
        }
    };

    const handleApprove = async (id: number) => {
        // 이미 처리 중이거나 pending 이 아닌 row 는 무시 (중복 클릭 차단)
        if (mutationLocks.current.has(`request:${id}`)) return;
        const current = requests.find(r => r.id === id);
        if (!current || current.status !== 'pending') return;

        mutationLocks.current.add(`request:${id}`);
        requestSequence.current++;
        setLoading(false);
        setProcessing(prev => { const n = new Set(prev); n.add(id); return n; });
        try {
            const res = await adminAPI.approveSubscription(id, apiToken);
            if (res?.request?.id !== id || res.request.status !== 'approved') throw new Error('승인 결과를 확인할 수 없습니다.');
            setRequests(prev => {
                const next = prev.map(r => r.id === id ? res.request : r);
                onCountChange(next.filter(r => r.status === 'pending').length);
                return next;
            });
            showAction('✅ 구독 승인 완료');
        } catch (err: any) {
            showAction(`❌ ${err.message}`);
        } finally {
            mutationLocks.current.delete(`request:${id}`);
            setProcessing(prev => { const n = new Set(prev); n.delete(id); return n; });
        }
    };

    const handleReject = async (id: number) => {
        if (mutationLocks.current.has(`request:${id}`)) return;
        const current = requests.find(r => r.id === id);
        if (!current || current.status !== 'pending') return;

        const note = prompt('거절 사유 (선택):');
        if (note === null) return;
        mutationLocks.current.add(`request:${id}`);
        requestSequence.current++;
        setLoading(false);
        setProcessing(prev => { const n = new Set(prev); n.add(id); return n; });
        try {
            const res = await adminAPI.rejectSubscription(id, note || undefined, apiToken);
            if (res?.request?.id !== id || res.request.status !== 'rejected') throw new Error('거절 결과를 확인할 수 없습니다.');
            setRequests(prev => {
                const next = prev.map(r => r.id === id ? res.request : r);
                onCountChange(next.filter(r => r.status === 'pending').length);
                return next;
            });
            showAction('구독 요청 거절됨');
        } catch (err: any) {
            showAction(`❌ ${err.message}`);
        } finally {
            mutationLocks.current.delete(`request:${id}`);
            setProcessing(prev => { const n = new Set(prev); n.delete(id); return n; });
        }
    };

    // 플랜 미선택 pending 가입자 — tier 부여 (status=approved 자동 승격)
    const handleGrantTier = async (userId: number, tier: 'pro' | 'premium') => {
        if (mutationLocks.current.has(`user:${userId}`)) return;
        if (requests.some(request => request.user_id === userId && request.status === 'pending')) { showAction('❌ 대기 중인 구독 요청을 먼저 승인해 주세요.'); return; }
        mutationLocks.current.add(`user:${userId}`);
        requestSequence.current++;
        setLoading(false);
        setGrantingUser(prev => { const n = new Set(prev); n.add(userId); return n; });
        try {
            await adminAPI.setUserTier(userId, tier, apiToken);
            setPendingSignups(prev => prev.filter(u => u.id !== userId));
            showAction(`✅ ${tier === 'premium' ? 'Ultra Pro' : 'Pro'} 부여 완료`);
        } catch (err: any) {
            showAction(`❌ ${err.message}`);
        } finally {
            mutationLocks.current.delete(`user:${userId}`);
            setGrantingUser(prev => { const n = new Set(prev); n.delete(userId); return n; });
        }
    };

    // 만료 회원 — 원클릭 재활성화 (tier 재부여 = status approved 승격 + 30일)
    const handleReactivate = async (member: ExpiredMember, tier: 'pro' | 'premium') => {
        if (mutationLocks.current.has(`user:${member.id}`)) return;
        if (requests.some(request => request.user_id === member.id && request.status === 'pending')) { showAction('❌ 대기 중인 구독 요청을 먼저 승인해 주세요.'); return; }
        mutationLocks.current.add(`user:${member.id}`);
        requestSequence.current++;
        setLoading(false);
        setGrantingUser(prev => { const n = new Set(prev); n.add(member.id); return n; });
        try {
            await adminAPI.setUserTier(member.id, tier, apiToken);
            setExpiredMembers(prev => prev.filter(u => u.id !== member.id));
            showAction(`✅ ${member.name} — ${tier === 'premium' ? 'Ultra Pro' : 'Pro'} 재활성화 완료`);
        } catch (err: any) {
            showAction(`❌ ${err.message}`);
        } finally {
            mutationLocks.current.delete(`user:${member.id}`);
            setGrantingUser(prev => { const n = new Set(prev); n.delete(member.id); return n; });
        }
    };

    const errorNotice = loadError && (
        <div role="alert" className="flex items-center justify-between gap-3 p-3 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-400">
            <span>{loadError} {hasLoaded ? '이전 조회 결과를 표시하고 있습니다.' : '현재 대기 내역을 확인할 수 없습니다.'}</span>
            <button onClick={() => loadRequests()} disabled={loading} className="shrink-0 px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 disabled:opacity-50">다시 시도</button>
        </div>
    );
    if (!hasLoaded) return loadError ? errorNotice : <div role="status" className="flex justify-center gap-2 py-12 text-sm text-gray-400"><div className="animate-spin rounded-full h-5 w-5 border-b-2 border-red-500" />구독 내역을 불러오는 중...</div>;

    const pending = requests.filter(r => r.status === 'pending');
    const processed = requests.filter(r => r.status !== 'pending');

    return (
        <>
            {errorNotice}
            {loading && <div role="status" className="text-xs text-gray-400">구독 내역을 새로고침하는 중...</div>}
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
                            const isKongmingPlan = isKongmingSubscriptionRequest(req.request_type);
                            const isKongmingRenewal = req.request_type === 'aibain_kongming_renewal';
                            const isBaseRenewal = req.request_type.includes('renewal') && !isAibainRenewal && !isKongmingPlan;
                            const isAibainOnly = req.request_type === 'aibain_addon' || isAibainRenewal;
                            const isAiOnly = isAibainOnly || isKongmingPlan;
                            const includesAibain = isAibainOnly || !!(req.admin_note && req.admin_note.includes('AI Brain'));
                            const aiBundle = isAiBundleRequest(req);
                            const cardBorder = isAiOnly ? 'border-cyan-500/30' : 'border-yellow-500/20';
                            const iconBg = isAiOnly ? 'bg-cyan-500/15' : 'bg-yellow-500/10';
                            const iconColor = isAiOnly ? 'text-cyan-300' : 'text-yellow-400';
                            const iconClass = isKongmingPlan ? 'fa-newspaper' : isAibainOnly ? 'fa-robot' : 'fa-arrow-up';
                            // 승인 버튼 색상/라벨 분기
                            let btnLabel = req.to_tier === 'premium' ? 'Ultra Pro 승인' : 'Pro 승인';
                            if (isBaseRenewal) btnLabel = req.to_tier === 'premium' ? 'Ultra Pro 재구독 승인' : 'Pro 재구독 승인';
                            let btnIcon = req.to_tier === 'premium' ? 'fa-gem' : 'fa-crown';
                            let btnColor = req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400 hover:bg-purple-500/30' : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30';
                            if (isKongmingPlan) {
                                btnLabel = `${kongmingPlanLabel}${isKongmingRenewal ? ' 갱신' : ''} 승인`;
                                btnIcon = 'fa-newspaper';
                                btnColor = 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30';
                            } else if (isAibainOnly) {
                                btnLabel = isAibainRenewal ? 'AI Brain 재구독 승인' : 'AI Brain 활성화';
                                btnIcon = 'fa-bolt';
                                btnColor = 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30';
                            } else if (includesAibain) {
                                btnLabel = req.to_tier === 'premium' ? 'Ultra Pro + AI Brain 승인' : 'Pro + AI Brain 승인';
                                btnIcon = 'fa-robot';
                                btnColor = 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30';
                            }
                            if (aiBundle) btnLabel = btnLabel.replace('AI Brain', 'AI Brain·제갈공명');
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
                                                    {(isBaseRenewal || isKongmingRenewal) && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">재구독</span>}
                                                    {isAibainOnly && (
                                                        <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 uppercase">
                                                            <i className="fas fa-robot text-[8px] mr-0.5" />
                                                            {isAibainRenewal ? 'AI BRAIN RENEWAL' : 'AI BRAIN ADDON'}
                                                        </span>
                                                    )}
                                                    {!isAiOnly && includesAibain && (
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
                                                    <span className={`px-1.5 py-0.5 rounded font-bold ${isAiOnly ? 'bg-cyan-500/20 text-cyan-300' : req.to_tier === 'premium' ? 'bg-purple-500/20 text-purple-400' : 'bg-amber-500/20 text-amber-400'}`}>
                                                        {isKongmingPlan ? kongmingPlanLabel : isAibainOnly ? (isAibainRenewal ? 'AI Brain 재구독' : '+AI Brain') : req.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                                    </span>
                                                    {req.depositor_name && (
                                                        <button
                                                            type="button"
                                                            onClick={() => copyDepositor(req.depositor_name!)}
                                                            title="입금자명 복사 (은행 앱 대조용)"
                                                            className="ml-2 px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors"
                                                        >
                                                            <i className="fas fa-user text-[10px] mr-1" />{req.depositor_name}
                                                            <i className="fas fa-copy text-[9px] ml-1 opacity-60" />
                                                        </button>
                                                    )}
                                                    {req.amount && (
                                                        <span className={`px-1.5 py-0.5 rounded font-bold ${isAiOnly ? 'bg-cyan-500/15 text-cyan-300' : 'bg-green-500/10 text-green-400'}`}>
                                                            {req.amount}
                                                        </span>
                                                    )}
                                                    <span className="ml-2 text-gray-600">{new Date(req.created_at).toLocaleString()}</span>
                                                </div>
                                                {req.admin_note && (
                                                    <p className="text-[11px] text-cyan-300/80 mt-1.5 leading-relaxed">
                                                        <i className="fas fa-info-circle text-cyan-400/70 mr-1" />
                                                        {subscriptionNote(req.admin_note)}
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

            {/* 만료 · 재구독 대기 — 재구독 요청 제출 전인 만료 회원 (이탈 방지 팔로업 대상) */}
            {expiredMembers.length > 0 && (
                <div>
                    <h2 className="text-lg font-semibold text-amber-400 mb-3">
                        <i className="fas fa-hourglass-end mr-2" />만료 · 재구독 대기 ({expiredMembers.length})
                    </h2>
                    <div className="space-y-3">
                        {expiredMembers.map(m => (
                            <div key={m.id} className="apple-glass rounded-xl p-4 border border-amber-500/20">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-amber-500/10 rounded-full flex items-center justify-center">
                                            <i className="fas fa-hourglass-end text-amber-400" />
                                        </div>
                                        <div>
                                            <div className="text-white font-medium">{m.name || `User #${m.id}`}</div>
                                            <div className="text-xs text-gray-400">{m.email}</div>
                                            <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-1">
                                                <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 font-bold">
                                                    {m.tier === 'premium' ? 'Ultra Pro' : 'Pro'} 만료
                                                    {m.days_since_expiry != null && ` · ${m.days_since_expiry}일 경과`}
                                                </span>
                                                {m.pro_expires_at && (
                                                    <span className="px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400">
                                                        만료일 {new Date(m.pro_expires_at).toLocaleDateString('ko-KR')}
                                                    </span>
                                                )}
                                                {m.last_login_at && (
                                                    <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300">
                                                        <i className="fas fa-right-to-bracket text-[10px] mr-1" />
                                                        최근 로그인 {new Date(m.last_login_at).toLocaleDateString('ko-KR')}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={() => handleReactivate(m, 'pro')}
                                            disabled={grantingUser.has(m.id)}
                                            className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                            <i className={`fas ${grantingUser.has(m.id) ? 'fa-spinner fa-spin' : 'fa-rotate-right'} mr-1`} />
                                            Pro 재활성화
                                        </button>
                                        <button onClick={() => handleReactivate(m, 'premium')}
                                            disabled={grantingUser.has(m.id)}
                                            className="px-4 py-2 rounded-lg text-sm font-medium bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                            <i className={`fas ${grantingUser.has(m.id) ? 'fa-spinner fa-spin' : 'fa-gem'} mr-1`} />
                                            Ultra Pro
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

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
                    <div className="apple-glass rounded-xl overflow-hidden overflow-x-auto">
                        <table className="w-full min-w-[560px]">
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
                                        <td className="px-4 py-3 text-xs text-gray-400">
                                            {isKongmingSubscriptionRequest(req.request_type) ? (
                                                <span className="text-cyan-300"><i className="fas fa-newspaper text-[10px] mr-1" />{kongmingPlanLabel}{req.request_type === 'aibain_kongming_renewal' ? ' 갱신' : ''}</span>
                                            ) : req.request_type === 'aibain_addon' ? (
                                                <span className="text-cyan-300"><i className="fas fa-robot text-[10px] mr-1" />+AI Brain</span>
                                            ) : req.request_type === 'aibain_renewal' ? (
                                                <span className="text-cyan-300"><i className="fas fa-robot text-[10px] mr-1" />AI Brain 재구독</span>
                                            ) : (
                                                <>{req.request_type.includes('renewal') ? '재구독 · ' : ''}{req.from_tier} &rarr; {req.to_tier}</>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs px-2 py-1 rounded ${req.status === 'approved' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{req.status}</span>
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-500">{req.processed_at ? new Date(req.processed_at).toLocaleDateString() : '-'}</td>
                                        <td className="px-4 py-3 text-xs text-gray-500">{subscriptionNote(req.admin_note) || '-'}</td>
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

