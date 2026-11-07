import { useState, type ReactNode } from 'react';
import { BANK_ACCOUNT } from '@/lib/billingInfo';
import './subscription-flow.css';

export function SubscriptionSteps({ step }: { step: 1 | 2 | 3 }) {
    return <ol className="subscription-steps" aria-label="구독 신청 단계">
        {['플랜 선택', '입금·신청', '승인 대기'].map((label, index) =>
            <li key={label} aria-current={index + 1 === step ? 'step' : undefined} data-complete={index + 1 < step}>
                <span aria-hidden="true">{index + 1 < step ? '✓' : index + 1}</span><strong>{label}</strong>
            </li>)}
    </ol>;
}

export default function SubscriptionFlow({ step, title, intro, children, wide = false }: {
    step: 1 | 2 | 3; title: string; intro: ReactNode; children: ReactNode; wide?: boolean;
}) {
    return <main className="subscription-flow min-h-[100dvh]">
        <div className={`subscription-flow-inner ${wide ? 'subscription-flow-wide' : ''}`}>
            <p className="subscription-flow-eyebrow">구독 · 신청 안내</p>
            <SubscriptionSteps step={step} />
            <header className="subscription-flow-header"><h1>{title}</h1><p>{intro}</p></header>
            {children}
        </div>
    </main>;
}

export function BankTransferDetails() {
    const [copyStatus, setCopyStatus] = useState('');
    const copyAccount = async () => {
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
            await navigator.clipboard.writeText(BANK_ACCOUNT.account.replace(/-/g, ''));
            setCopyStatus('계좌번호를 복사했습니다.');
        } catch { setCopyStatus('복사하지 못했습니다. 아래 계좌번호를 길게 누르거나 직접 선택해 주세요.'); }
    };
    return <section className="subscription-bank" aria-label="입금 계좌 정보">
        <div className="subscription-bank-owner"><strong>{BANK_ACCOUNT.bank}</strong><span>예금주 {BANK_ACCOUNT.holder}</span></div>
        <div className="subscription-bank-number"><span>{BANK_ACCOUNT.account}</span>
            <button type="button" className="subscription-button-secondary" onClick={() => void copyAccount()}>계좌 복사</button></div>
        <p role="status" className="subscription-help">{copyStatus || '이 계좌로 직접 이체한 뒤 아래에서 신청해 주세요.'}</p>
    </section>;
}
