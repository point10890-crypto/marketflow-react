import { MouseEvent, ReactNode } from 'react';
import { Link } from 'react-router-dom';

/**
 * 종목 허브 딥링크 — 리스트 행(종가베팅·주도주·VCP·Claw·이력)의 종목명을 허브로 잇는다.
 *
 * 행 자체에 onClick(펼치기 등)이 걸린 경우가 많아 클릭 전파를 막는다.
 * 시장 파라미터는 라우트 `/dashboard/stock/:market/:code` 의 첫 세그먼트로,
 * KOSPI/KOSDAQ/KR 은 전부 KR 로 접는다 (허브는 국내 종목 전용).
 */

export type HubMarket = 'KR' | 'US';

export function hubMarket(market?: string | null): HubMarket {
    return String(market || '').toUpperCase() === 'US' ? 'US' : 'KR';
}

export function stockHubPath(code: string, market?: string | null): string {
    return `/dashboard/stock/${hubMarket(market)}/${encodeURIComponent(String(code || '').trim())}`;
}

interface Props {
    code: string;
    market?: string | null;
    children: ReactNode;
    className?: string;
    title?: string;
}

export default function StockLink({ code, market, children, className = '', title }: Props) {
    const stop = (e: MouseEvent) => { e.stopPropagation(); };
    if (!code) return <span className={className}>{children}</span>;
    return (
        <Link
            to={stockHubPath(code, market)}
            onClick={stop}
            title={title ?? '종목 허브 열기'}
            className={`rounded-sm underline-offset-4 transition-colors hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-white/40 ${className}`}
        >
            {children}
        </Link>
    );
}
