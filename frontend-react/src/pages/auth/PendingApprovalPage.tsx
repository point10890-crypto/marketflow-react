import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { BANK_ACCOUNT, isAiBundleRequest, subscriptionNote, isKongmingSubscriptionRequest, PLAN_PAYMENT_META, planToQuery } from '@/lib/billingInfo';
import { subscriptionAPI, type SubscriptionRequest } from '@/lib/api';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { hasActiveBaseSubscription, hasActiveKongmingSubscription, isBaseSubscriptionExpired, subscriptionFunnelTarget, type AuthUserData } from '@/lib/auth';
import { hasPendingSubscription, pendingSubscriptionRequest } from '@/lib/subscriptionStatus';
import { useSeo } from '@/lib/seo';

const FLOW_STEPS = ['계정 생성', '플랜 선택', '입금 정보', '승인 대기'];
const KONGMING_PLAN = 'aibain_kongming';

/** Legacy status responses may omit user facts; only a complete same-member user can confirm access. */
function confirmedStatusUser(raw: unknown, memberId: number | string | undefined): AuthUserData | null {
    if (raw == null) return null;
    if (typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid subscription user');
    const value = raw as Record<string, unknown>;
    if (!['id', 'status', 'tier'].some(key => key in value)) return null;
    if (memberId == null || String(value.id) !== String(memberId)
        || typeof value.name !== 'string' || typeof value.email !== 'string'
        || typeof value.role !== 'string' || typeof value.status !== 'string'
        || !(value.tier === null || typeof value.tier === 'string')
        || typeof value.is_pro_expired !== 'boolean') throw new Error('Invalid subscription user');
    return value as unknown as AuthUserData;
}

/**
 * 승인 대기 페이지 — 모든 sub_req (신규 가입 + AI Brain 애드온 + 업그레이드) 공통.
 *
 * 동작:
 * - 마운트 + 30s 폴링: subscriptionAPI.getStatus() 로 최신 sub_req fetch
 * - 실제 sub_req.amount + admin_note (AI Brain 마커) 표시
 * - 활성 회원 (Pro/Premium) 도 pending sub_req 가 있으면 페이지 유지 (예: AI Brain 애드온 신청)
 * - sub_req 가 approved 되거나 없어지면 대시보드로 자동 이동
 */
export default function PendingApprovalPage() {
    useSeo({ title: '승인 대기 | MarketFlow', noindex: true });
    const { user, token, logout, refreshUser } = useAuth();
    const navigate = useNavigate();
    const [checking, setChecking] = useState(false);
    const [message, setMessage] = useState('');
    const [statusError, setStatusError] = useState(false);
    const pendingSignature = `${user?.has_pending_subscription ?? 'unknown'}:${user?.pending_subscription_request?.id ?? ''}:${user?.pending_subscription_request?.status ?? ''}:${user?.pending_subscription_request?.request_type ?? ''}`;
    const identity = `${user?.id ?? ''}:${token ?? ''}:${pendingSignature}`;
    const identityRef = useRef(identity);
    identityRef.current = identity;
    const requestSequence = useRef(0);
    const refreshRef = useRef(refreshUser);
    refreshRef.current = refreshUser;
    const refreshedStatus = useRef('');
    const [now, setNow] = useState(Date.now);
    const [snapshot, setSnapshot] = useState<{ identity: string; pending: SubscriptionRequest | null;
        hasPending: boolean; declined: SubscriptionRequest | null; confirmedUser: AuthUserData | null } | null>(null);
    const currentSnapshot = snapshot?.identity === identity ? snapshot : null;
    const pendingSubReq = currentSnapshot?.pending ?? null;
    const rejectedSubReq = currentSnapshot?.declined ?? null;
    const hasPending = currentSnapshot?.hasPending
        ?? (user?.has_pending_subscription === true || user?.pending_subscription_request?.status === 'pending');
    const subReqLoaded = currentSnapshot !== null;
    const cancelled = ['cancelled', 'canceled'].includes(rejectedSubReq?.status || '');
    const confirmedUser = currentSnapshot?.confirmedUser ?? null;
    const decisionUser = confirmedUser ?? user;
    const blockedAccount = !!confirmedUser && ['suspended', 'rejected'].includes(confirmedUser.status);
    const awaitingAuth = !!confirmedUser && (
        (hasActiveBaseSubscription(confirmedUser, now) && !hasActiveBaseSubscription(user, now))
        || (hasActiveKongmingSubscription(confirmedUser, now) && !hasActiveKongmingSubscription(user, now))
    );

    const fetchSubReq = useCallback(async () => {
        if (!token) return undefined;
        const sequence = ++requestSequence.current;
        try {
            const resp = await subscriptionAPI.getStatus(token);
            if (!Array.isArray(resp?.requests)) throw new Error('Invalid subscription status');
            if (sequence !== requestSequence.current || identityRef.current !== identity) return undefined;
            const confirmed = confirmedStatusUser(resp.user, user?.id);
            const reqs = resp.requests;
            const pending = pendingSubscriptionRequest(resp);
            const pendingExists = hasPendingSubscription(resp);
            const declined = !pendingExists && ['rejected', 'cancelled', 'canceled'].includes(reqs[0]?.status) ? reqs[0] : null;
            setSnapshot({ identity, pending, hasPending: pendingExists, declined, confirmedUser: confirmed });
            setMessage(''); setStatusError(false);
            if (confirmed && (hasActiveBaseSubscription(confirmed) || hasActiveKongmingSubscription(confirmed)
                || ['suspended', 'rejected'].includes(confirmed.status))) {
                const fingerprint = `${identity}:${confirmed.status}:${confirmed.tier}:${confirmed.pro_expires_at}:${confirmed.aibain_expires_at}:${confirmed.kongming_expires_at}`;
                if (refreshedStatus.current !== fingerprint) {
                    refreshedStatus.current = fingerprint;
                    refreshRef.current().catch(() => {});
                }
            }
            return pending;
        } catch {
            if (sequence === requestSequence.current && identityRef.current === identity) {
                setMessage('신청 상태를 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.');
                setStatusError(true);
            }
            return undefined;
        }
    }, [token, identity, user?.id]);

    // 초기 1회 sub_req fetch
    useEffect(() => {
        setSnapshot(null); setMessage(''); setChecking(false); setStatusError(false);
        void fetchSubReq();
        return () => { requestSequence.current++; };
    }, [fetchSubReq]);

    // 자동 리다이렉트 — admin / 활성 회원 + pending sub_req 없을 때만 이동
    useEffect(() => {
        if (!user || !subReqLoaded) return;
        if (blockedAccount || awaitingAuth) return;
        if (user.role === 'admin') {
            navigate('/admin', { replace: true });
            return;
        }
        // 만료 Pro 재구독 신청자는 status='approved'/tier 유지 + is_pro_expired=true —
        // 활성으로 오인하면 대시보드로 튕겨 ApprovedGuard 가 다시 plan-select 로 되돌린다.
        const isActive = hasActiveBaseSubscription(decisionUser, now);
        if (!hasPending && !rejectedSubReq) {
            if (isActive) navigate('/dashboard', { replace: true });
            else if (hasActiveKongmingSubscription(decisionUser, now)) navigate('/dashboard/ai-bain', { replace: true });
            else {
                const funnel = subscriptionFunnelTarget(decisionUser, now);
                if (funnel?.startsWith(`/plan-select?${planToQuery(KONGMING_PLAN)}`)) {
                    navigate(funnel, { replace: true });
                    return;
                }
                const expired = isBaseSubscriptionExpired(decisionUser, now);
                const tier = user.requested_tier || user.tier;
                const query = new URLSearchParams();
                if (tier === 'pro' || tier === 'premium') query.set('plan', tier);
                if (expired) { query.set('resubscribe', '1'); query.set('from', 'expired'); }
                navigate(`/plan-select${query.size ? '?' + query.toString() : ''}`, { replace: true });
            }
        }
    }, [user, decisionUser, navigate, hasPending, subReqLoaded, rejectedSubReq, now, blockedAccount, awaitingAuth]);

    // 30초 폴링 — user 상태 + sub_req 둘 다 refresh
    useEffect(() => {
        const tick = () => {
            if (document.visibilityState === 'hidden') return;
            setNow(Date.now());
            refreshRef.current().catch(() => {});
            void fetchSubReq();
        };
        const timer = window.setInterval(tick, 30000);
        window.addEventListener('focus', tick);
        return () => {
            window.clearInterval(timer);
            window.removeEventListener('focus', tick);
        };
    }, [fetchSubReq]);

    const handleCheckStatus = async () => {
        setChecking(true);
        setMessage('');
        const checkingIdentity = identity;
        try {
            await refreshRef.current();
            if (identityRef.current !== checkingIdentity) return;
            const sr = await fetchSubReq();
            if (identityRef.current === checkingIdentity && sr) setMessage('아직 승인 대기 중입니다.');
        } catch {
            if (identityRef.current === checkingIdentity) setMessage('서버 연결에 실패했습니다.');
        } finally {
            if (identityRef.current === checkingIdentity) setChecking(false);
        }
    };

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // sub_req 로부터 표시 정보 도출
    const isAibainRenewal = pendingSubReq?.request_type === 'aibain_renewal';
    const isAibainAddon = pendingSubReq?.request_type === 'aibain_addon' || isAibainRenewal;
    const isKongming = isKongmingSubscriptionRequest(pendingSubReq?.request_type);
    const isKongmingRenewal = pendingSubReq?.request_type === 'aibain_kongming_renewal';
    const rejectedKongming = isKongmingSubscriptionRequest(rejectedSubReq?.request_type);
    const kongmingLabel = PLAN_PAYMENT_META[KONGMING_PLAN].label;
    const includesAibain = !!pendingSubReq?.admin_note?.includes('AI Brain');
    const aiBundle = isAiBundleRequest(pendingSubReq);
    const subReqAmount = pendingSubReq?.amount || null;

    // 색상 테마 — AI Brain 포함이면 cyan, 아니면 amber
    const themeColor = isKongming || includesAibain
        ? { border: 'border-cyan-500/30', bg: 'bg-cyan-500/10', text: 'text-cyan-300', accentBg: 'bg-cyan-500/[0.06]', accentBorder: 'border-cyan-500/20' }
        : { border: 'border-amber-500/20', bg: 'bg-amber-500/10', text: 'text-amber-400', accentBg: 'bg-amber-500/[0.06]', accentBorder: 'border-amber-500/20' };

    // 헤더 / 안내 문구 분기 — 만료 Pro 재구독은 "활성 업그레이드"가 아니다 (is_pro_expired 체크)
    const isUpgradeFromActive = hasActiveBaseSubscription(decisionUser, now);
    const hasExistingAccess = isUpgradeFromActive || hasActiveKongmingSubscription(decisionUser, now);
    const dashboardPath = isUpgradeFromActive ? '/dashboard' : '/dashboard/ai-bain';
    const expired = isBaseSubscriptionExpired(decisionUser, now);
    const reapplyTier = rejectedSubReq?.to_tier === 'premium' || (!rejectedSubReq && (user?.tier === 'premium' || user?.requested_tier === 'premium')) ? 'premium' : 'pro';
    const reapplyAibain = ['aibain_addon', 'aibain_renewal'].includes(rejectedSubReq?.request_type || '')
        || !!rejectedSubReq?.admin_note?.includes('AI Brain');
    const reapplyRenewal = rejectedKongming ? rejectedSubReq?.request_type === 'aibain_kongming_renewal' : expired;
    const reapplyQuery = rejectedKongming ? planToQuery(KONGMING_PLAN) : `plan=${reapplyTier}${reapplyAibain ? '&aibain=1' : ''}`;
    const reapplyPath = `/payment-request?${reapplyQuery}${reapplyRenewal ? '&resubscribe=1' : ''}`;
    let headerTitle = '승인 대기 중';
    let headerSubtitle = '구독 신청이 접수되었습니다. 입금 확인 후 관리자가 서비스를 활성화합니다.';
    if (!hasPending && (!hasExistingAccess || rejectedSubReq)) {
        if (rejectedSubReq) {
            headerTitle = cancelled ? '구독 신청이 취소되었습니다' : '구독 신청이 거절되었습니다';
            headerSubtitle = '아래 사유를 확인한 뒤 다시 신청하거나 카카오톡으로 문의해 주세요.';
        } else {
            headerTitle = '플랜 선택이 필요합니다';
            headerSubtitle = '계정은 만들어졌지만 아직 구독 신청이 접수되지 않았습니다. 플랜을 선택하면 입금 안내와 승인 신청이 이어집니다.';
        }
    }
    if (isKongming) {
        headerTitle = `${kongmingLabel}${isKongmingRenewal ? ' 재구독' : ''} 승인 대기 중`;
        headerSubtitle = '입금 확인 후 관리자가 30일 이용권을 승인합니다.';
    } else if (isAibainAddon) {
        headerTitle = isAibainRenewal ? 'AI Brain 재구독 승인 대기 중' : 'AI Brain 활성화 대기 중';
        headerSubtitle = `입금 확인 후 관리자가 AI Brain 알파 스캐너를 ${isAibainRenewal ? '30일 재활성화' : '활성화'}합니다. 그 동안 기존 구독은 그대로 이용 가능합니다.`;
    } else if (isUpgradeFromActive && !rejectedSubReq) {
        headerTitle = '업그레이드 대기 중';
        headerSubtitle = '입금 확인 후 관리자가 새 플랜으로 업그레이드합니다.';
    }
    if (awaitingAuth && !hasPending) {
        headerTitle = '승인이 확인되었습니다';
        headerSubtitle = '회원 이용 상태를 갱신하고 있습니다. 추가 신청이나 입금이 필요하지 않습니다.';
    }
    if (blockedAccount) {
        headerTitle = '계정 상태 확인이 필요합니다';
        headerSubtitle = '현재 계정은 새 구독 신청을 진행할 수 없습니다. 고객지원으로 문의해 주세요.';
    }

    return (
        <div className="min-h-[100dvh] bg-black flex items-center justify-center p-4">
            <div className="w-full max-w-lg text-center">
                <div className="mb-4 grid grid-cols-4 gap-2">
                    {FLOW_STEPS.map((step, index) => (
                        <div
                            key={step}
                            className={`rounded-xl border px-2 py-2 text-center text-[10px] font-bold ${
                                index === 3
                                    ? 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200'
                                    : 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'
                            }`}
                        >
                            <div className="mb-1 text-[11px]">{index + 1}</div>
                            {step}
                        </div>
                    ))}
                </div>
                <div className={`p-8 rounded-2xl bg-[#1c1c1e] border ${themeColor.border}`}>
                    <div className={`w-16 h-16 mx-auto mb-6 ${themeColor.bg} rounded-full flex items-center justify-center`}>
                        <i className={`${!pendingSubReq && !hasExistingAccess ? 'fas fa-credit-card' : isKongming || isAibainAddon ? 'fas fa-robot' : 'fas fa-hourglass-half'} text-2xl ${themeColor.text}`}></i>
                    </div>

                    <h1 className="text-2xl font-bold text-white mb-2">{headerTitle}</h1>
                    <p className="text-gray-400 text-sm mb-6 leading-relaxed">{headerSubtitle}</p>

                    {rejectedSubReq && !hasPending && (
                        <div className="p-4 rounded-xl bg-red-500/[0.07] border border-red-500/25 mb-6 text-left">
                            <div className="flex items-center gap-2 mb-1.5">
                                <i className="fas fa-circle-xmark text-red-400 text-sm" />
                                <span className="text-red-300 font-bold text-sm">{cancelled ? '취소된 신청' : '거절된 신청'}</span>
                                <span className="text-[10px] text-gray-500">
                                    {rejectedSubReq.processed_at || rejectedSubReq.created_at ? new Date(rejectedSubReq.processed_at || rejectedSubReq.created_at).toLocaleDateString('ko-KR') : ''}
                                </span>
                            </div>
                            <div className="text-xs text-gray-400">
                                요청 플랜: {rejectedKongming ? kongmingLabel : rejectedSubReq.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                            </div>
                            <p className="text-xs text-gray-300 mt-1.5 leading-relaxed">
                                {rejectedSubReq.admin_note
                                    ? <>사유: {subscriptionNote(rejectedSubReq.admin_note)}</>
                                    : '사유가 기재되지 않았습니다. 카카오톡으로 문의해 주세요.'}
                            </p>
                        </div>
                    )}
                    <p className="text-gray-600 text-[11px] mb-4">
                        30초마다 자동으로 승인 상태를 확인합니다.
                    </p>

                    {user && (
                        <div className="p-3 rounded-lg bg-white/5 mb-6 text-left">
                            <div className="text-[10px] text-gray-500 mb-1">가입 정보</div>
                            <div className="text-sm text-white">{user.name}</div>
                            <div className="text-xs text-gray-400 mb-2">{user.email}</div>
                            {pendingSubReq && (
                                <div className="mt-2 pt-2 border-t border-white/5 space-y-1.5">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-[10px] text-gray-500">요청:</span>
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${themeColor.bg} ${themeColor.text}`}>
                                            <i className={`${isKongming || isAibainAddon ? 'fas fa-robot' : pendingSubReq.to_tier === 'premium' ? 'fas fa-gem' : 'fas fa-crown'} mr-1`} />
                                            {isKongming ? kongmingLabel : isAibainAddon
                                                ? `${pendingSubReq.from_tier === 'premium' ? 'Ultra Pro' : 'Pro'} → ${isAibainRenewal ? 'AI Brain 재구독' : '+AI Brain 애드온'}`
                                                : includesAibain
                                                ? `${pendingSubReq.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'} + AI Brain`
                                                : pendingSubReq.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                        </span>
                                    </div>
                                    {pendingSubReq.admin_note && (
                                        <p className="text-[11px] text-gray-400 leading-relaxed pl-1">
                                            <i className="fas fa-info-circle mr-1 text-cyan-400/70" />
                                            {subscriptionNote(pendingSubReq.admin_note)}
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {hasPending && !blockedAccount && <div className={`p-4 rounded-xl ${themeColor.accentBg} border ${themeColor.accentBorder} mb-6 text-left`}>
                        <div className="flex items-start gap-3 mb-4">
                            <div className={`w-10 h-10 rounded-xl ${themeColor.bg} flex items-center justify-center shrink-0`}>
                                <i className={`fas fa-university ${themeColor.text}`} />
                            </div>
                            <div>
                                <h2 className="text-white font-bold text-sm">입금 계좌 정보</h2>
                                <p className="text-gray-400 text-xs mt-0.5">
                                    {isKongming || aiBundle ? '입금 확인 후 AI Brain과 제갈공명을 30일 함께 이용합니다. PRO 잔여기간은 AI 이용 중 일시정지됩니다.' : isAibainAddon
                                        ? '입금 확인 후 AI Brain 알파 스캐너가 30일간 활성화됩니다.'
                                        : '입금 확인 후 관리자가 구독을 활성화합니다.'}
                                </p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                                <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.bank}</p>
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                                <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.holder}</p>
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06] sm:col-span-2">
                                <div className="flex items-center justify-between gap-3">
                                    <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                                    <button
                                        type="button"
                                        onClick={() => navigator.clipboard?.writeText(BANK_ACCOUNT.account.replace(/-/g, ''))}
                                        className="text-[10px] text-gray-400 hover:text-white transition-colors"
                                    >
                                        <i className="fas fa-copy mr-1" />복사
                                    </button>
                                </div>
                                <p className="text-white font-bold mt-1 font-mono text-lg tracking-wider">{BANK_ACCOUNT.account}</p>
                            </div>
                            <div className={`p-3 rounded-lg ${themeColor.accentBg} border ${themeColor.accentBorder}`}>
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">입금 금액</span>
                                <p className={`font-bold mt-1 text-base ${themeColor.text}`}>
                                    {subReqAmount || '플랜 선택 후 확정'}
                                </p>
                                {(isKongming || isAibainAddon) && (
                                    <p className="text-[10px] text-gray-500 mt-0.5">{isKongming ? '30일 이용권' : 'AI Brain 30일 갱신'}</p>
                                )}
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">입금자명</span>
                                <p className="text-white font-bold mt-1 text-sm">
                                    {pendingSubReq?.depositor_name || user?.name || '가입 시 이름'}
                                </p>
                            </div>
                        </div>

                        <p className="mt-3 text-[11px] leading-relaxed text-gray-400">
                            입금자명은 가입 이름과 동일하게 보내 주세요.
                            {isKongming ? '' : isAibainAddon
                                ? ' AI Brain 만료 시 별도 갱신 없으면 자동으로 기존 베이스 플랜으로 회귀합니다.'
                                : pendingSubReq && includesAibain
                                ? ' AI Brain 알파 스캐너 알림이 30일간 활성화됩니다.'
                                : !pendingSubReq
                                ? ' 아직 플랜을 선택하지 않았다면 아래 버튼에서 먼저 플랜을 선택해 주세요.'
                                : ''}
                        </p>
                    </div>}

                    {message && (
                        <div className={`p-3 rounded-lg mb-4 text-sm ${message.includes('승인되었습니다') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-gray-400'}`}>
                            {message}
                        </div>
                    )}

                    <div className="space-y-3">
                        {rejectedSubReq && !hasPending && !statusError && !blockedAccount && !awaitingAuth && <Link to={reapplyPath} className="block w-full py-3 rounded-xl bg-amber-400 text-black font-bold">
                            {reapplyRenewal ? '재구독 신청' : '다시 신청'}
                        </Link>}
                        {!hasPending && !hasExistingAccess && !rejectedSubReq && subReqLoaded && !blockedAccount && !awaitingAuth && (
                            <button
                                onClick={() => navigate('/plan-select')}
                                className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all flex items-center justify-center gap-2"
                            >
                                <i className="fas fa-credit-card" />
                                플랜 선택하기
                            </button>
                        )}
                        {hasExistingAccess && !awaitingAuth && !blockedAccount && (
                            <button
                                onClick={() => navigate(dashboardPath)}
                                className="w-full py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-medium transition-all"
                            >
                                <i className="fas fa-arrow-left mr-2" />
                                대시보드로 돌아가기
                            </button>
                        )}
                        <button
                            onClick={handleCheckStatus}
                            disabled={checking}
                            className="w-full py-3 rounded-xl bg-white/10 hover:bg-white/15 text-white font-medium transition-all disabled:opacity-50"
                        >
                            {checking ? '확인 중...' : '승인 상태 확인'}
                        </button>
                        {!hasExistingAccess && (
                            <button
                                onClick={handleLogout}
                                className="w-full py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 font-medium transition-all"
                            >
                                로그아웃
                            </button>
                        )}
                        <KakaoSupportLink />
                    </div>
                </div>
            </div>
        </div>
    );
}
