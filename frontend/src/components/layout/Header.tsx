'use client';

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import CommandPalette from './CommandPalette';

interface HeaderProps {
    title?: string;
    onMenuClick?: () => void;
}

const PAGE_NAMES: Record<string, string> = {
    '/dashboard': 'Summary',
    '/dashboard/vcp-enhanced': 'VCP Enhanced',
    '/dashboard/kr': 'KR Market',
    '/dashboard/kr/vcp': 'KR VCP Signals',
    '/dashboard/kr/closing-bet': '\uc885\uac00\ubca0\ud305',
    '/dashboard/kr/closing-bet/history': '\uc885\uac00\ubca0\ud305 History',
    '/dashboard/kr/chatbot': 'KR Chatbot',
    '/dashboard/us': 'US Market',
    '/dashboard/us/etf': 'ETF Flows',
    '/dashboard/us/vcp': 'US VCP',
    '/dashboard/crypto': 'Crypto',
    '/dashboard/crypto/signals': 'Crypto VCP Signals',
    '/dashboard/stock-analyzer': 'ProPicks Analyzer',
    '/dashboard/data-status': 'Data Status',
};

function getPageTitle(pathname: string): string {
    if (PAGE_NAMES[pathname]) return PAGE_NAMES[pathname];
    const segments = pathname.split('/').filter(Boolean);
    const last = segments[segments.length - 1] || 'Dashboard';
    return last.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export default function Header({ onMenuClick }: HeaderProps) {
    const pathname = usePathname() ?? '';
    const [paletteOpen, setPaletteOpen] = useState(false);
    const pageTitle = getPageTitle(pathname);

    useEffect(() => {
        const handleKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                setPaletteOpen(prev => !prev);
            }
        };
        window.addEventListener('keydown', handleKey);
        return () => window.removeEventListener('keydown', handleKey);
    }, []);

    return (
        <>
            <header className="h-14 md:h-16 flex items-center justify-between px-4 md:px-6 border-b border-white/10 md:border-white/5 bg-[#111113] md:bg-[#09090b]/80 backdrop-blur-md shrink-0 z-40">
                {/* Left: Hamburger (mobile) + Page Title */}
                <div className="flex items-center gap-3">
                    {/* Hamburger - mobile only */}
                    <button
                        onClick={onMenuClick}
                        className="md:hidden w-10 h-10 flex items-center justify-center rounded-xl bg-white/10 text-white hover:bg-white/20 transition-colors active:scale-95"
                    >
                        <i className="fas fa-bars text-base"></i>
                    </button>

                    {/* Brand - mobile only, clickable → Summary dashboard */}
                    <button
                        onClick={() => {
                            if (pathname !== '/dashboard') {
                                window.location.href = '/dashboard';
                            }
                        }}
                        className="md:hidden flex items-center gap-2 active:scale-95 transition-transform duration-150"
                    >
                        <div className="relative w-7 h-7 bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600 rounded-lg flex items-center justify-center text-white font-extrabold text-sm shadow-lg shadow-amber-500/20 ring-1 ring-amber-400/20">
                            <span className="relative">B</span>
                        </div>
                        <span className="text-[15px] font-extrabold tracking-tight">
                            <span className="bg-gradient-to-r from-yellow-300 via-amber-400 to-yellow-500 bg-clip-text text-transparent">Bit</span><span className="bg-gradient-to-r from-amber-400 to-yellow-300 bg-clip-text text-transparent">Man</span>
                        </span>
                    </button>

                    {/* Page Title - desktop only */}
                    <div className="hidden md:block">
                        <h1 className="text-lg font-semibold text-white">{pageTitle}</h1>
                    </div>
                </div>

                {/* Search - desktop only */}
                <div className="hidden md:block max-w-md w-full mx-4">
                    <button
                        onClick={() => setPaletteOpen(true)}
                        className="relative group w-full"
                    >
                        <i className="fas fa-search absolute left-3.5 top-2.5 text-gray-500"></i>
                        <div className="block w-full pl-10 pr-12 py-2.5 bg-[#18181b] border border-white/10 rounded-full text-sm text-gray-500 text-left cursor-pointer hover:border-white/20 transition-all">
                            Search markets, tickers, or commands...
                        </div>
                        <div className="absolute inset-y-0 right-0 pr-3.5 flex items-center">
                            <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-[10px] font-mono text-gray-500 bg-white/5 rounded border border-gray-600">
                                ⌘K
                            </kbd>
                        </div>
                    </button>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                    {/* Search - mobile only */}
                    <button
                        onClick={() => setPaletteOpen(true)}
                        className="md:hidden p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors active:scale-95"
                    >
                        <i className="fas fa-search text-sm"></i>
                    </button>
                    <button className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors relative active:scale-95">
                        <i className="far fa-bell text-sm"></i>
                        <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-red-500 rounded-full border border-black"></span>
                    </button>
                </div>
            </header>

            <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        </>
    );
}
