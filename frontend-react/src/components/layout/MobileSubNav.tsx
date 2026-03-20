import { Link, useLocation } from 'react-router-dom';
import { useRef, useEffect } from 'react';

interface SubNavItem {
    name: string;
    href: string;
    color: string;
}

const sectionChildren: Record<string, SubNavItem[]> = {
    '/dashboard/kr': [
        { name: 'Overview', href: '/dashboard/kr', color: 'bg-blue-500' },
        { name: 'VCP Signals', href: '/dashboard/kr/vcp', color: 'bg-rose-500' },
        { name: '종가베팅', href: '/dashboard/kr/closing-bet', color: 'bg-violet-500' },
        { name: 'Track Record', href: '/dashboard/kr/track-record', color: 'bg-yellow-500' },
    ],
    '/dashboard/us': [
        { name: 'Overview', href: '/dashboard/us', color: 'bg-green-500' },
        { name: 'VCP Signals', href: '/dashboard/us/vcp', color: 'bg-rose-500' },
        { name: 'ETF Flows', href: '/dashboard/us/etf', color: 'bg-blue-600' },
    ],
    '/dashboard/crypto': [
        { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
        { name: 'VCP Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
    ],
};

// Map section color dot classes for active state
const sectionActiveColors: Record<string, string> = {
    '/dashboard/kr': 'text-blue-400 border-blue-400',
    '/dashboard/us': 'text-green-400 border-green-400',
    '/dashboard/crypto': 'text-yellow-400 border-yellow-400',
};

export default function MobileSubNav() {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const scrollRef = useRef<HTMLDivElement>(null);

    // Find the matching section
    const sectionKey = Object.keys(sectionChildren).find(
        (key) => pathname === key || pathname.startsWith(key + '/')
    );

    // Auto-scroll active tab into view
    useEffect(() => {
        if (!scrollRef.current || !sectionKey) return;
        const activeEl = scrollRef.current.querySelector('[data-active="true"]');
        if (activeEl) {
            activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
    }, [pathname, sectionKey]);

    if (!sectionKey) return null;

    const children = sectionChildren[sectionKey];
    const activeColor = sectionActiveColors[sectionKey] || 'text-white border-white';

    return (
        <div className="md:hidden border-b border-white/5 bg-[#0d0d0f] shrink-0 z-30">
            <div
                ref={scrollRef}
                className="flex items-center gap-1 px-3 py-2 overflow-x-auto mobile-sub-nav-scroll"
                style={{ scrollbarWidth: 'none', msOverflowStyle: 'none', WebkitOverflowScrolling: 'touch' } as React.CSSProperties}
            >
                {children.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            to={item.href}
                            data-active={isActive}
                            className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-semibold transition-all whitespace-nowrap border ${
                                isActive
                                    ? `${activeColor} bg-white/10 border-current`
                                    : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/5'
                            }`}
                        >
                            <span className={`inline-block w-1.5 h-1.5 rounded-full ${item.color} mr-1.5 align-middle`}></span>
                            {item.name}
                        </Link>
                    );
                })}
            </div>
        </div>
    );
}
