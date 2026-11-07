import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { isAiBundleRequest, subscriptionNote, isKongmingSubscriptionRequest, PLAN_PAYMENT_META, planToQuery } from '@/lib/billingInfo';
import { subscriptionAPI, type SubscriptionRequest } from '@/lib/api';
import SubscriptionFlow, { BankTransferDetails } from '@/components/subscription/SubscriptionFlow';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { hasActiveBaseSubscription, hasActiveKongmingSubscription, isBaseSubscriptionExpired, subscriptionFunnelTarget, type AuthUserData } from '@/lib/auth';
import { hasPendingSubscription, pendingSubscriptionRequest } from '@/lib/subscriptionStatus';
import { useSeo } from '@/lib/seo';

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
    const cancelled = ['cancelled', 'canceled', 'withdrawn'].includes(rejectedSubReq?.status || '');
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
            const declined = !pendingExists && ['rejected', 'cancelled', 'canceled', 'withdrawn'].includes(reqs[0]?.status) ? reqs[0] : null;
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

    if (!subReqLoaded && !statusError && !hasPending) {
        headerTitle = '신청 상태 확인 중';
        headerSubtitle = '접수된 신청과 현재 이용권을 확인하고 있습니다.';
    } else if (statusError && !hasPending && !blockedAccount) {
        headerTitle = '잠시 후 다시 확인해 주세요';
        headerSubtitle = '연결 문제로 현재 상태를 확인하지 못했습니다. 다시 신청하거나 입금하지 않아도 됩니다.';
    }
    const requestedLabel = isKongming ? kongmingLabel : isAibainAddon ? aiBundle ? 'AI 브레인 + 제갈공명' : 'AI Brain'
        : `${pendingSubReq?.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}${includesAibain ? ' + AI 브레인·제갈공명' : ''}`;

    return <SubscriptionFlow step={3} title={headerTitle} intro={headerSubtitle}>
        {hasPending && !blockedAccount && <section className="subscription-status-box" aria-label="신청 접수 안내">
            <strong>신청 접수 완료 · 입금 확인을 기다리고 있어요</strong>
            <p>이미 입금했다면 다시 입금하거나 신청하지 마세요. 승인되면 이용 화면으로 자동 이동합니다.</p>
        </section>}
        {(subReqLoaded || statusError) && <p className="subscription-help">30초마다 자동으로 승인 상태를 확인합니다.</p>}
        {rejectedSubReq && !hasPending && <section className="subscription-error">
            <strong>{cancelled ? '취소된 신청' : '거절된 신청'}</strong>
            <p className="mt-2">{rejectedSubReq.admin_note ? `사유: ${subscriptionNote(rejectedSubReq.admin_note)}` : '사유가 기재되지 않았습니다. 카카오톡으로 문의해 주세요.'}</p>
            <p className="mt-2">이미 입금했다면 다시 보내기 전에 고객지원에 확인해 주세요.</p>
        </section>}
        {pendingSubReq && !blockedAccount && <section className="subscription-order" aria-label="접수한 신청">
            <h2 className="text-base font-semibold mb-4">접수한 신청</h2>
            <dl className="subscription-receipt">
                <dt>신청 서비스</dt><dd>{requestedLabel}</dd>
                <dt>신청 금액</dt><dd>{subReqAmount || '확인 중'}</dd>
                <dt>입금자명</dt><dd>{pendingSubReq.depositor_name || user?.name || '가입 시 이름'}</dd>
                {user?.email && <><dt>회원 계정</dt><dd>{user.email}</dd></>}
            </dl>
            {(isKongming || aiBundle) && <p className="mt-4">승인 후 AI 브레인·제갈공명을 30일 이용합니다. PRO 기간은 AI 이용 중 보관됩니다.</p>}
        </section>}
        {message && <p role={statusError ? 'alert' : 'status'} className={statusError ? 'subscription-error' : 'subscription-note'}>{message}</p>}
        <div className="subscription-actions">
            {rejectedSubReq && !hasPending && !statusError && !blockedAccount && !awaitingAuth &&
                <Link to={reapplyPath} className="subscription-button-primary">{reapplyRenewal ? '재구독 신청' : '다시 신청'}</Link>}
            {!hasPending && !hasExistingAccess && !rejectedSubReq && subReqLoaded && !blockedAccount && !awaitingAuth &&
                <button onClick={() => navigate('/plan-select')} className="subscription-button-primary">플랜 선택하기</button>}
            <button onClick={handleCheckStatus} disabled={checking} className="subscription-button-secondary">{checking ? '확인 중...' : '승인 상태 확인'}</button>
            {hasExistingAccess && !awaitingAuth && !blockedAccount && <>
                <button onClick={() => navigate(dashboardPath)} className="subscription-button-secondary">대시보드로 돌아가기</button>
                <p className="subscription-help !m-0 text-center">대기하는 동안 기존 구독은 계속 이용할 수 있습니다.</p>
            </>}
        </div>
        {hasPending && !blockedAccount && <details className="subscription-details">
            <summary>입금 계좌를 다시 확인하려면</summary>
            <p className="subscription-help">아직 이체하지 않은 경우에만 확인하세요. 이미 입금했다면 추가 입금은 필요 없습니다.</p>
            <BankTransferDetails />
        </details>}
        <div className="mt-5"><KakaoSupportLink label="입금·승인 문의" /></div>
        {!hasExistingAccess && <footer className="subscription-flow-footer"><button onClick={handleLogout}>로그아웃</button></footer>}
    </SubscriptionFlow>;
}
