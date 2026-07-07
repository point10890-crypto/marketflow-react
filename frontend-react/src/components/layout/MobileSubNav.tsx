import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';

interface SubNavItem {
    name: string;
    href: string;
    color: string;
}

const sectionChildren: Record<string, SubNavItem[]> = {
    '/dashboard/kr': [
        { name: 'Overview', href: '/dashboard/kr', color: 'bg-blue-500' },
        { name: '주도주 LIVE', href: '/dashboard/kr/leading-stocks', color: 'bg-orange-500' },
        { name: 'VCP Signals', href: '/dashboard/kr/vcp', color: 'bg-rose-500' },
        { name: '종가베팅', href: '/dashboard/kr/closing-bet', color: 'bg-violet-500' },
        { name: '성과 History', href: '/dashboard/kr/closing-bet/history', color: 'bg-indigo-500' },
        { name: 'Track Record', href: '/dashboard/kr/track-record', color: 'bg-yellow-500' },
        { name: 'AI Chart', href: '/dashboard/kr/ai-chart', color: 'bg-cyan-500' },
    ],
    '/dashboard/us': [
        { name: 'Overview', href: '/dashboard/us', color: 'bg-green-500' },
        { name: 'VCP Signals', href: '/dashboard/us/vcp', color: 'bg-rose-500' },
        { name: 'ETF Flows', href: '/dashboard/us/etf', color: 'bg-blue-600' },
        { name: 'AI Chart', href: '/dashboard/us/ai-chart', color: 'bg-cyan-500' },
    ],
    '/dashboard/crypto': [
        { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
        { name: 'VCP Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
    ],
};

const sectionActiveColors: Record<string, string> = {
    '/dashboard/kr': 'text-blue-300 border-blue-300',
    '/dashboard/us': 'text-green-300 border-green-300',
    '/dashboard/crypto': 'text-yellow-300 border-yellow-300',
};

function isActivePath(pathname: string, href: string) {
    return pathname === href;
}

export default function MobileSubNav() {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const scrollRef = useRef<HTMLDivElement>(null);

    const sectionKey = Object.keys(sectionChildren).find(
        (key) => pathname === key || pathname.startsWith(key + '/'),
    );

    useEffect(() => {
        if (!scrollRef.current || !sectionKey) return;
        const activeEl = scrollRef.current.querySelector('[data-active="true"]');
        activeEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }, [pathname, sectionKey]);

    if (!sectionKey) return null;

    const activeColor = sectionActiveColors[sectionKey] || 'text-white border-white';

    return (
        <div className="md:hidden shrink-0 border-b border-white/5 bg-[#0d0d0f] z-30">
            <div
                ref={scrollRef}
                className="mobile-sub-nav-scroll flex items-center gap-1.5 overflow-x-auto px-2.5 py-2"
                style={{ scrollbarWidth: 'none', msOverflowStyle: 'none', WebkitOverflowScrolling: 'touch' } as React.CSSProperties}
            >
                {sectionChildren[sectionKey].map((item) => {
                    const isActive = isActivePath(pathname, item.href);
                    return (
                        <Link
                            key={item.href}
                            to={item.href}
                            data-active={isActive}
                            className={`inline-flex min-h-9 shrink-0 items-center rounded-full border px-3 py-1.5 text-xs font-bold transition-all ${
                                isActive
                                    ? `${activeColor} bg-white/10 border-current`
                                    : 'text-slate-500 border-transparent hover:text-slate-300 hover:bg-white/5'
                            }`}
                        >
                            <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${item.color} ${item.name.includes('LIVE') ? 'animate-pulse' : ''}`} />
                            {item.name}
                        </Link>
                    );
                })}
            </div>
        </div>
    );
}
