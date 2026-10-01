import { createPortal } from 'react-dom';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import { subscriptionJourney, reminderDue } from '@/lib/subscriptionJourney';
import { hasPendingSubscription } from '@/lib/subscriptionStatus';
import { PLAN_PAYMENT_META } from '@/lib/billingInfo';
import { safeGetItem, safeSetItem } from '@/lib/safeStorage';
import './subscription-entry.css';

/** Entry guidance only. Existing server payment/approval and access gates remain authoritative. */
export default function SubscriptionEntry() {
    const { user, token, loading, refreshUser } = useAuth();
    const refresh = useRef(refreshUser);
    refresh.current = refreshUser;
    const [now, setNow] = useState(Date.now);
    const { pathname } = useLocation();
    const [bannerHost, setBannerHost] = useState<HTMLElement | null>(null);
    useLayoutEffect(() => { setBannerHost(document.getElementById('subscription-entry-dashboard')); }, [pathname, loading, user?.id]);
    const journey = subscriptionJourney(user);
    const eligible = !loading && !!user && !!token && !!journey
        && !['/payment-request', '/pending-approval', '/login', '/signup'].includes(pathname);
    const expired = journey?.kind === 'base-expired';
    const brain = journey?.kind === 'aibain-expired';
    const key = `subscription-entry:v2:${journey?.fingerprint}`;
    const [lookup, setLookup] = useState<{ key: string; state: 'ready' | 'pending' | 'error' } | null>(null);
    const [retry, setRetry] = useState(0);
    const [dismissedAt, setDismissedAt] = useState<{ key: string; at: string } | null>(null);
    const dialog = useRef<HTMLDialogElement>(null);
    const lookupKey = `${key}:${token}:${pathname}:${retry}`;
    useEffect(() => {
        if (!user || !token || loading || user.role === 'admin') return;
        const tick = () => {
            if (document.visibilityState === 'hidden') return;
            setNow(Date.now());
            // An open dialog is refreshed through /auth/me. Before reopening a
            // dismissed dialog, confirm current status rather than reusing it.
            if (!dialog.current?.open) setRetry(value => value + 1);
            refresh.current?.().catch(() => {});
        };
        const interval = window.setInterval(tick, 60_000);
        window.addEventListener('focus', tick);
        document.addEventListener('visibilitychange', tick);
        return () => {
            window.clearInterval(interval);
            window.removeEventListener('focus', tick);
            document.removeEventListener('visibilitychange', tick);
        };
    }, [user?.id, user?.role, token, loading]);
    useEffect(() => {
        if (!eligible || !token) return;
        let current = true;
        subscriptionAPI.getStatus(token).then(data => {
            if (current) setLookup({ key: lookupKey, state: hasPendingSubscription(data) ? 'pending' : 'ready' });
        }).catch(() => { if (current) setLookup({ key: lookupKey, state: 'error' }); });
        return () => { current = false; };
    }, [eligible, token, lookupKey, retry]);
    const state = user?.has_pending_subscription === true ? 'pending' : lookup?.key === lookupKey ? lookup.state : null;
    const lastDismissal = dismissedAt?.key === key ? dismissedAt.at : safeGetItem('session', key);
    const open = eligible && state === 'ready' && reminderDue(lastDismissal, now);
    const close = () => {
        const at = String(Date.now());
        safeSetItem('session', key, at);
        setNow(Date.now());
        setDismissedAt({ key, at });
    };
    useEffect(() => {
        if (!open || !dialog.current) return;
        const element = dialog.current;
        const previous = document.activeElement as HTMLElement | null;
        if (element.showModal) element.showModal();
        else element.setAttribute('open', '');
        return () => { element.close?.(); previous?.focus(); };
    }, [open]);
    if (!eligible || !journey) return null;
    const meta = PLAN_PAYMENT_META[journey.plan];
    const payment = journey.payment;
    const destination = journey.destination;
    const banner = <aside className="subscription-entry" aria-label="구독 안내">
            <div><strong>{state === 'pending' ? '구독 신청을 확인하고 있습니다' : journey.title}</strong>
                <p>{state === 'pending' ? '추가 입금 없이 신청 상태를 확인하세요.' : state === 'error' ? '신청 내역을 불러오지 못했습니다. 다시 확인해 주세요.' : journey.message}</p></div>
            {state === 'error' ? <button onClick={() => setRetry(v => v + 1)}>다시 확인</button>
                : state ? <Link to={state === 'pending' ? '/pending-approval' : destination}>{state === 'pending' ? '신청 상태 확인' : journey.cta}</Link>
                : <span role="status">신청 내역 확인 중…</span>}
        </aside>;
    return <>
        {bannerHost ? createPortal(banner, bannerHost) : banner}
        {open && <dialog ref={dialog} className="subscription-entry-dialog" aria-labelledby="subscription-entry-title" onCancel={close}>
            <div className="subscription-entry-body">
                <p className="subscription-entry-eyebrow">{brain ? 'AI Brain 재구독' : expired ? '다시 시작하기' : '구독 신청 · 다음 단계'}</p>
                <h2 id="subscription-entry-title">{brain ? 'AI Brain을 다시 이용하세요' : expired ? '기존 계정으로 바로 재구독하세요' : '구독을 시작해 보세요'}</h2>
                <p>{brain ? '기본 구독은 유지됩니다. AI Brain만 30일 재구독할 수 있습니다.' : expired ? '계정과 이용 기록은 그대로 유지됩니다. 이용할 플랜을 선택해 다시 신청해 주세요.' : '어디서 신청할지 찾지 않아도 됩니다. 아래에서 플랜을 고르면 입금 안내로 바로 연결됩니다.'}</p>
                <ol><li>플랜 선택</li><li>입금 후 신청</li><li>승인 후 이용</li></ol>
                <Link className="subscription-entry-primary" to={payment} onClick={close}>
                    <span>{brain ? 'AI Brain 재구독' : `${meta.label} ${expired ? '재구독' : '구독 신청'}`}</span><span>{brain ? '40,000원 · AI Brain 30일' : `${meta.amount} · ${meta.period}`}</span>
                </Link>
                <p className="subscription-entry-note">버튼을 눌러도 결제되지 않습니다. 다음 화면에서 금액·계좌·입금자명을 확인한 뒤 신청합니다.</p>
                <Link className="subscription-entry-secondary" to={brain ? '/plan-select?change=1' : destination} onClick={close}>다른 플랜·AI Brain 함께 보기</Link>
                <button className="subscription-entry-dismiss" onClick={close}>나중에 보기</button><p className="subscription-entry-note">신청 전까지 안내 카드는 계속 표시됩니다. 팝업은 30분 뒤 다시 알려드립니다.</p>
            </div>
        </dialog>}
    </>;
}
