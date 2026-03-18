'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
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
    ],
    '/dashboard/us': [
        { name: 'Overview', href: '/dashboard/us', color: 'bg-green-500' },
        { name: 'Briefing', href: '/dashboard/us/briefing', color: 'bg-amber-500' },
        { name: 'Top Picks', href: '/dashboard/us/top-picks', color: 'bg-indigo-500' },
        { name: 'Smart Money', href: '/dashboard/us/smart-money', color: 'bg-blue-500' },
        { name: 'Risk', href: '/dashboard/us/risk', color: 'bg-orange-500' },
        { name: 'Earnings', href: '/dashboard/us/earnings', color: 'bg-pink-500' },
        { name: 'Sectors', href: '/dashboard/us/sectors', color: 'bg-teal-500' },
        { name: 'Signals', href: '/dashboard/us/signals', color: 'bg-emerald-500' },
        { name: 'Calendar', href: '/dashboard/us/calendar', color: 'bg-lime-500' },
        { name: 'Prediction', href: '/dashboard/us/prediction', color: 'bg-red-500' },
        { name: 'Regime', href: '/dashboard/us/regime', color: 'bg-cyan-500' },
        { name: 'ETF', href: '/dashboard/us/etf', color: 'bg-blue-600' },
        { name: 'Heatmap', href: '/dashboard/us/heatmap', color: 'bg-violet-500' },
        { name: 'Cumulative', href: '/dashboard/us/cumulative-performance', color: 'bg-purple-500' },
        { name: 'VCP', href: '/dashboard/us/vcp', color: 'bg-rose-500' },
        { name: 'Options', href: '/dashboard/us/options', color: 'bg-yellow-500' },
        { name: '13F', href: '/dashboard/us/13f', color: 'bg-slate-500' },
        { name: 'Insider', href: '/dashboard/us/insider', color: 'bg-fuchsia-500' },
        { name: 'News', href: '/dashboard/us/news', color: 'bg-sky-500' },
        { name: 'Rotation', href: '/dashboard/us/sector-rotation', color: 'bg-emerald-600' },
    ],
    '/dashboard/crypto': [
        { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
        { name: 'Briefing', href: '/dashboard/crypto/briefing', color: 'bg-amber-500' },
        { name: 'VCP Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
        { name: 'Prediction', href: '/dashboard/crypto/prediction', color: 'bg-red-500' },
        { name: 'Risk', href: '/dashboard/crypto/risk', color: 'bg-rose-500' },
        { name: 'Lead-Lag', href: '/dashboard/crypto/leadlag', color: 'bg-cyan-500' },
        { name: 'Backtest', href: '/dashboard/crypto/backtest', color: 'bg-indigo-500' },
    ],
};

// Map section color dot classes for active state
const sectionActiveColors: Record<string, string> = {
    '/dashboard/kr': 'text-blue-400 border-blue-400',
    '/dashboard/us': 'text-green-400 border-green-400',
    '/dashboard/crypto': 'text-yellow-400 border-yellow-400',
};

export default function MobileSubNav() {
    const pathname = usePathname() ?? '';
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
                style={{ scrollbarWidth: 'none', msOverflowStyle: 'none', WebkitOverflowScrolling: 'touch' }}
            >
                {children.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
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
