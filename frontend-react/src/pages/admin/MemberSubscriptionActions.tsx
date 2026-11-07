import { useCallback, useEffect, useRef, useState } from 'react';
import { adminAPI, type AdminUser, type SubscriptionRequest } from '@/lib/api';
import { AI_BUNDLE_CONVERSION, conversionApprovalDetails, formatConversionExpiry, isKongmingSubscriptionRequest, PLAN_PAYMENT_META } from '@/lib/billingInfo';

const kongmingPlanLabel = PLAN_PAYMENT_META.aibain_kongming.label;

export default function MemberSubscriptionActions({ user, apiToken, onUpdated, onMutationStart, onBusyChange, onDeleted }: {
    user: AdminUser;
    apiToken?: string;
    onUpdated: (user: AdminUser) => void;
    onMutationStart?: () => void;
    onBusyChange?: (busy: boolean) => void;
    onDeleted?: (id: number) => void;
}) {
    const [requests, setRequests] = useState<SubscriptionRequest[] | null>(null);
    const [lookupError, setLookupError] = useState('');
    const [tier, setTier] = useState<'pro' | 'premium'>(user.tier === 'premium' ? 'premium' : 'pro');
    const [busy, setBusy] = useState(false);
    const busyRef = useRef(false);
    const lookupSequence = useRef(0);
    const scopeSequence = useRef(0);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [refreshNeeded, setRefreshNeeded] = useState(false);
    const [confirmExpiry, setConfirmExpiry] = useState(false);
    const [note, setNote] = useState('');
    const blocked = user.role === 'admin' || ['suspended', 'blocked', 'rejected'].includes(user.status);
    const statusLabel = user.status === 'approved'
        ? user.is_pro_expired ? '구독 만료' : '이용 중'
        : ({ expired: '구독 만료', pending: '승인 대기', suspended: '이용 정지', blocked: '이용 정지', rejected: '가입 거절' } as Record<string, string>)[user.status] || '상태 확인 필요';
    const buttonClass = 'px-3 py-2 rounded-lg text-xs font-semibold bg-white/5 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed';

    const loadPending = useCallback(async () => {
        const sequence = ++lookupSequence.current;
        setLookupError('');
        try {
            const response = await adminAPI.getSubscriptions(apiToken);
            if (!Array.isArray(response?.requests)) throw new Error('Invalid subscription response');
            if (sequence === lookupSequence.current) setRequests(response.requests.filter(request => request.user_id === user.id && request.status === 'pending'));
        } catch {
            if (sequence === lookupSequence.current) setLookupError('대기 중인 구독 요청을 확인하지 못했습니다. 확인 후 다시 시도하세요.');
        }
    }, [apiToken, user.id]);
    useEffect(() => {
        scopeSequence.current++;
        setRequests(null);
        void loadPending();
        return () => { scopeSequence.current++; lookupSequence.current++; };
    }, [loadPending]);

    const run = async (operation: () => Promise<void>) => {
        if (busyRef.current || blocked) return;
        const scope = scopeSequence.current;
        const interruptedLookup = requests === null;
        busyRef.current = true;
        lookupSequence.current++;
        setBusy(true);
        onBusyChange?.(true);
        onMutationStart?.();
        setError(''); setMessage('');
        try { await operation(); }
        catch (err) { if (scope === scopeSequence.current) setError(err instanceof Error ? err.message : '구독 처리에 실패했습니다.'); }
        finally {
            // 전체 만료는 최초 조회 중에도 가능하다. 무효화한 조회를 새로 시작해
            // 같은 회원의 패널이 영구 로딩 상태로 남지 않도록 한다.
            if (scope === scopeSequence.current) {
                if (interruptedLookup) void loadPending();
                busyRef.current = false; setBusy(false); onBusyChange?.(false);
            }
        }
    };
    const updateUser = (next: AdminUser) => {
        if (!next || next.id !== user.id) throw new Error('회원 상태 응답을 확인할 수 없습니다. 다시 조회해 주세요.');
        onUpdated(next);
    };
    const verifyNoPending = async () => {
        const response = await adminAPI.getSubscriptions(apiToken);
        if (!Array.isArray(response?.requests)) throw new Error('대기 구독 요청을 확인할 수 없습니다. 다시 확인해 주세요.');
        const pending = response.requests.filter(request => request.user_id === user.id && request.status === 'pending');
        setRequests(pending);
        if (pending.length) throw new Error('새 대기 요청이 있습니다. 해당 구독 요청을 먼저 승인해 주세요.');
    };
    const approve = (request: SubscriptionRequest) => {
        const isConversion = request.request_type === AI_BUNDLE_CONVERSION.plan;
        const detail = isConversion ? conversionApprovalDetails(request.conversion_expires_at) : '입금을 확인하고 승인하시겠습니까?';
        if (!window.confirm(`${user.name} (${user.email})\n요청 #${request.id}\n${detail}`)) return;
        void run(async () => {
            const response = await adminAPI.approveSubscription(request.id, apiToken);
            if (response?.request?.id !== request.id || response.request.status !== 'approved') throw new Error('승인 결과를 확인할 수 없습니다. 다시 조회해 주세요.');
            setRequests(previous => previous?.filter(item => item.id !== request.id) ?? null);
            setMessage(`요청 #${request.id} 승인 완료`);
            try { updateUser(await adminAPI.getUser(user.id, apiToken)); }
            catch { setRefreshNeeded(true); setError('승인은 완료됐지만 최신 회원 상태를 조회하지 못했습니다. 회원 상태를 다시 조회해 주세요.'); }
        });
    };
    const grant = () => {
        if (requests === null || requests.length || lookupError) return;
        if (!window.confirm(`${user.name} (${user.email})\n${tier === 'pro' ? 'Pro 30일' : 'Ultra Pro 무기한'} 구독을 부여하시겠습니까?`)) return;
        void run(async () => {
            await verifyNoPending();
            updateUser((await adminAPI.setUserTier(user.id, tier, apiToken)).user);
            setMessage('선택 플랜 부여 완료');
        });
    };
    const extend = () => {
        if (requests === null || requests.length || lookupError) return;
        if (!window.confirm(`${user.name} (${user.email})\n현재 Pro 만료일 기준으로 30일을 연장하시겠습니까?`)) return;
        void run(async () => {
            await verifyNoPending();
            updateUser((await adminAPI.extendPro(user.id, 30, apiToken)).user);
            setMessage('Pro 30일 연장 완료');
        });
    };
    const aiAction = (action: 'enable' | 'extend' | 'revoke') => {
        const detail = action === 'revoke' ? 'AI Brain과 제갈공명 이용권을 함께 철회합니다. PRO 잔여기간은 다시 차감되고 Ultra PRO는 유지됩니다.' : 'AI Brain과 제갈공명을 함께 30일 부여·연장합니다. PRO 잔여기간은 일시정지됩니다.';
        if (!window.confirm(`${user.name} (${user.email})\n${detail}`)) return;
        const reason = window.prompt('AI·제갈공명 처리 사유 (선택):', '');
        if (reason === null) return;
        void run(async () => {
            await verifyNoPending();
            const response = await adminAPI.manageAiBundle(user.id, action === 'revoke' ? 'revoke' : 'grant', reason || undefined, apiToken);
            updateUser(response.user);
            setMessage('AI Brain·제갈공명 구독 처리 완료');
        });
    };

    return <section aria-label={`${user.name} 구독 관리`} className="rounded-xl border border-white/10 p-3 space-y-3 text-gray-300">
        <div className="text-sm font-semibold text-white">구독 관리 · {user.name}</div>
        <p className="text-xs text-gray-400 break-all">{user.email} · 회원 #{user.id}</p>
        <p className="text-xs text-gray-400">{user.tier === 'premium' ? 'Ultra Pro (무기한)' : user.tier === 'pro' ? 'Pro' : 'No Tier'} · {statusLabel} · AI Brain {user.is_aibain_active ? '활성' : '비활성'}</p>
        {user.subscription_lifecycle && <p className="text-sm text-amber-300">{user.subscription_lifecycle.label}</p>}
        {user.tier === 'pro' && <p className="text-xs text-gray-400">PRO {user.is_pro_paused ? '잔여기간 보존 중 · AI 종료 후 재개' : `만료일 ${(user.pro_effective_expires_at || user.pro_expires_at) ? new Date(user.pro_effective_expires_at || user.pro_expires_at!).toLocaleString('ko-KR') : '미설정'}`}</p>}
        {user.kongming_expires_at && <p className="text-xs text-cyan-300">{kongmingPlanLabel} · {user.is_kongming_active ? '이용 중' : '만료'} · {new Date(user.kongming_expires_at).toLocaleDateString('ko-KR')}</p>}
        {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
        {refreshNeeded && <button disabled={busy} onClick={() => void run(async () => { updateUser(await adminAPI.getUser(user.id, apiToken)); setRefreshNeeded(false); })} className={buttonClass}>회원 상태 다시 조회</button>}
        {message && <p role="status" className="text-xs text-emerald-400">{message}</p>}
        {busy && <p role="status" className="text-xs text-amber-400">처리 중...</p>}
        {blocked ? <p className="text-xs text-amber-400">관리자 또는 정지·거절된 회원의 구독은 변경할 수 없습니다.</p> : !refreshNeeded && <>
            {lookupError ? <div role="alert" className="text-xs text-red-400">{lookupError} <button onClick={() => { setRequests(null); void loadPending(); }} className={buttonClass}>다시 확인</button></div>
                : requests === null ? <p role="status" className="text-xs text-gray-400">대기 구독 요청 확인 중...</p>
                    : requests.length ? <div className="space-y-2">
                        <p className="text-xs text-amber-300">대기 요청을 승인하면 해당 요청과 구독 상태가 함께 처리됩니다.</p>
                        {requests.map(request => <div key={request.id} className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => approve(request)} className={`${buttonClass} flex-1 text-left text-amber-300`}>
                            {request.request_type === AI_BUNDLE_CONVERSION.plan ? <>
                                제갈공명 전환 승인 · {request.amount || AI_BUNDLE_CONVERSION.amount}
                                <span className="block">제갈공명 이용 종료 {formatConversionExpiry(request.conversion_expires_at)}</span>
                            </> : <>
                                {request.request_type.includes('renewal') ? '재구독' : '구독'} 요청 #{request.id} 승인 · {isKongmingSubscriptionRequest(request.request_type) ? kongmingPlanLabel : request.request_type.startsWith('aibain') ? 'AI Brain' : request.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                            </>}
                        </button><button disabled={busy} className={`${buttonClass} text-red-300`} onClick={() => {
                            if (!window.confirm(`대기 요청 #${request.id}을 철회합니까? 기존 이용권은 유지되며 회원은 다시 신청할 수 있습니다.`)) return;
                            void run(async () => {
                                const result = await adminAPI.withdrawSubscription(request.id, undefined, apiToken);
                                if (result.request?.status !== 'withdrawn') throw new Error('철회 결과를 확인하지 못했습니다.');
                                setRequests(items => items?.filter(item => item.id !== request.id) ?? []);
                                setMessage('대기 신청 철회 완료 · 재신청 가능');
                                updateUser(await adminAPI.getUser(user.id, apiToken));
                            });
                        }}>신청 철회</button></div>)}
                    </div> : <div className="flex flex-wrap gap-2 items-center">
                        <label className="sr-only" htmlFor={`grant-tier-${user.id}`}>부여할 플랜</label>
                        <select id={`grant-tier-${user.id}`} value={tier} disabled={busy} onChange={event => setTier(event.target.value as 'pro' | 'premium')} className="bg-[#242426] border border-white/10 rounded-lg px-2 py-2 text-xs">
                            <option value="pro">Pro 30일</option><option value="premium">Ultra Pro 무기한</option>
                        </select>
                        <button disabled={busy} onClick={grant} className={`${buttonClass} text-emerald-300`}>선택 플랜 부여 / 재활성화</button>
                    </div>}
            {requests !== null && !requests.length && !lookupError && <div className="flex flex-wrap gap-2">
                {user.tier === 'pro' && <button disabled={busy} onClick={extend} className={`${buttonClass} text-emerald-300`}>Pro +30일 연장</button>}
                <button disabled={busy || !['pro', 'premium'].includes(user.tier) || user.status !== 'approved' || !!user.is_pro_expired} onClick={() => aiAction(user.is_aibain_active ? 'extend' : 'enable')} className={`${buttonClass} text-cyan-300`}>AI Brain·제갈공명 {user.is_aibain_active || user.is_kongming_active ? '+30일 연장' : '30일 활성화'}</button>
                {(user.is_aibain_active || user.aibain_enabled || user.is_kongming_active) && <button disabled={busy} onClick={() => aiAction('revoke')} className={`${buttonClass} text-red-300`}>AI·제갈공명 철회</button>}
            </div>}
            <button disabled={busy} onClick={() => setConfirmExpiry(true)} className={`${buttonClass} text-red-400 border border-red-500/20`}>전체 구독 만료</button>
            {onDeleted && <button disabled={busy} className={`${buttonClass} text-red-400`} onClick={() => {
                const email = window.prompt(`${user.name}의 회원 계정과 작성 글·댓글·구매 및 구독 신청을 삭제합니다. 감사 이력은 보존됩니다. 삭제하려면 회원 이메일을 정확히 입력하세요.`);
                if (email !== user.email) return;
                void run(async () => { await adminAPI.deleteUser(user.id, apiToken); onDeleted(user.id); });
            }}>회원 계정 삭제</button>}
            {confirmExpiry && <div role="dialog" aria-label="전체 구독 만료 확인" className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 space-y-3">
                <p className="text-xs text-red-300">{user.name} ({user.email})의 Pro · Ultra Pro · AI Brain · 제갈공명 구독을 모두 즉시 만료합니다. 회원 계정, 구매·구독 요청 및 관리자 감사 이력은 보존됩니다.</p>
                <label className="block text-xs">만료 사유 (선택)<textarea aria-label="만료 사유 (선택)" value={note} disabled={busy} onChange={event => setNote(event.target.value)} className="mt-1 block w-full bg-black/20 border border-white/10 rounded-lg p-2" /></label>
                <div className="flex flex-wrap gap-2">
                    <button disabled={busy} onClick={() => setConfirmExpiry(false)} className={buttonClass}>취소</button>
                    <button disabled={busy} onClick={() => void run(async () => {
                        updateUser((await adminAPI.expireSubscription(user.id, note.trim() || undefined, apiToken)).user);
                        setConfirmExpiry(false); setNote(''); setMessage('전체 구독 만료 완료');
                    })} className={`${buttonClass} bg-red-500/20 text-red-300`}>전체 구독 만료 확정</button>
                </div>
            </div>}
        </>}
    </section>;
}
