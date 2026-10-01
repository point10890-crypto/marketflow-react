import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import { subscriptionFunnelTarget } from '@/lib/auth';
import { PLAN_PAYMENT_META, planToQuery, type BillingPlan } from '@/lib/billingInfo';
import { safeGetItem, safeSetItem } from '@/lib/safeStorage';
import './subscription-entry.css';

/** Entry guidance only. Existing server payment/approval and access gates remain authoritative. */
export default function SubscriptionEntry() {
    const { user, token, loading } = useAuth();
    const { pathname } = useLocation();
    const target = subscriptionFunnelTarget(user);
    const eligible = !loading && !!user && !!token && !!target
        && !['/payment-request', '/pending-approval', '/login', '/signup'].includes(pathname);
    const expired = !!user?.is_pro_expired || user?.status === 'expired';
    const key = `subscription-entry:v1:${user?.id}:${expired ? user?.pro_expires_at || 'expired' : 'new'}`;
    const [lookup, setLookup] = useState<{ key: string; state: 'ready' | 'pending' | 'error' } | null>(null);
    const [retry, setRetry] = useState(0);
    const [dismissed, setDismissed] = useState('');
    const dialog = useRef<HTMLDialogElement>(null);
    const lookupKey = `${key}:${token}:${pathname}`;
    useEffect(() => {
        if (!eligible || !token) return;
        let current = true;
        subscriptionAPI.getStatus(token).then(data => {
            if (current) setLookup({ key: lookupKey, state: data.requests.some(r => r.status === 'pending') ? 'pending' : 'ready' });
        }).catch(() => { if (current) setLookup({ key: lookupKey, state: 'error' }); });
        return () => { current = false; };
    }, [eligible, token, lookupKey, retry]);
    const state = lookup?.key === lookupKey ? lookup.state : null;
    const open = eligible && state === 'ready' && dismissed !== key && safeGetItem('session', key) !== '1';
    const close = () => { safeSetItem('session', key, '1'); setDismissed(key); };
    useEffect(() => {
        if (!open || !dialog.current) return;
        const element = dialog.current;
        const previous = document.activeElement as HTMLElement | null;
        if (element.showModal) element.showModal();
        else element.setAttribute('open', '');
        return () => { element.close?.(); previous?.focus(); };
    }, [open]);
    if (!eligible) return null;
    const plan: BillingPlan = expired && user?.tier === 'premium' ? 'premium' : 'pro';
    const meta = PLAN_PAYMENT_META[plan];
    const payment = `/payment-request?${planToQuery(plan)}${expired ? '&resubscribe=1' : ''}`;
    const destination = expired ? '/plan-select?resubscribe=1&from=expired' : '/plan-select';
    return <>
        <aside className="subscription-entry" aria-label="구독 안내">
            <div><strong>{state === 'pending' ? '구독 신청을 확인하고 있습니다' : expired ? '구독이 만료되었습니다' : '아직 이용 중인 구독이 없습니다'}</strong>
                <p>{state === 'pending' ? '추가 입금 없이 신청 상태를 확인하세요.' : state === 'error' ? '신청 내역을 불러오지 못했습니다. 다시 확인해 주세요.' : '플랜 선택 → 입금 후 신청 → 관리자 승인 후 이용'}</p></div>
            {state === 'error' ? <button onClick={() => setRetry(v => v + 1)}>다시 확인</button>
                : state ? <Link to={state === 'pending' ? '/pending-approval' : destination}>{state === 'pending' ? '신청 상태 확인' : expired ? '재구독 신청하기' : '구독 신청하기'}</Link>
                : <span role="status">신청 내역 확인 중…</span>}
        </aside>
        {open && <dialog ref={dialog} className="subscription-entry-dialog" aria-labelledby="subscription-entry-title" onCancel={close}>
            <div className="subscription-entry-body">
                <p className="subscription-entry-eyebrow">{expired ? '다시 시작하기' : '회원 가입 완료 · 다음 단계'}</p>
                <h2 id="subscription-entry-title">{expired ? '기존 계정으로 바로 재구독하세요' : '구독을 시작해 보세요'}</h2>
                <p>{expired ? '계정과 이용 기록은 그대로 유지됩니다. 이용할 플랜을 선택해 다시 신청해 주세요.' : '어디서 신청할지 찾지 않아도 됩니다. 아래에서 플랜을 고르면 입금 안내로 바로 연결됩니다.'}</p>
                <ol><li>플랜 선택</li><li>입금 후 신청</li><li>승인 후 이용</li></ol>
                <Link className="subscription-entry-primary" to={payment} onClick={close}>
                    <span>{meta.label} {expired ? '재구독' : '구독 신청'}</span><span>{meta.amount} · {meta.period}</span>
                </Link>
                <p className="subscription-entry-note">버튼을 눌러도 결제되지 않습니다. 다음 화면에서 금액·계좌·입금자명을 확인한 뒤 신청합니다.</p>
                <Link className="subscription-entry-secondary" to={destination} onClick={close}>다른 플랜·AI Brain 함께 보기</Link>
                <button className="subscription-entry-dismiss" onClick={close}>플랜 화면에서 살펴보기</button>
            </div>
        </dialog>}
    </>;
}
