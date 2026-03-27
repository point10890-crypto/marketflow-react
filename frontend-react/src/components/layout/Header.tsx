import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import CommandPalette from './CommandPalette';
import { useNotification } from '@/contexts/NotificationContext';

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
    '/dashboard/kr/track-record': 'Track Record',
    '/dashboard/us': 'US Market',
    '/dashboard/us/etf': 'ETF Flows',
    '/dashboard/us/vcp': 'US VCP',
    '/dashboard/crypto': 'Crypto',
    '/dashboard/crypto/signals': 'Crypto VCP Signals',
    '/dashboard/stock-analyzer': 'ProPicks Analyzer',
    '/dashboard/wave': 'W Pattern',
    '/admin/data-status': 'Data Status',
};

function getPageTitle(pathname: string): string {
    if (PAGE_NAMES[pathname]) return PAGE_NAMES[pathname];
    const segments = pathname.split('/').filter(Boolean);
    const last = segments[segments.length - 1] || 'Dashboard';
    return last.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function timeAgo(ts: number): string {
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

export default function Header({ onMenuClick }: HeaderProps) {
    const location = useLocation();
    const navigate = useNavigate();
    const pathname = location.pathname ?? '';
    const [paletteOpen, setPaletteOpen] = useState(false);
    const [bellOpen, setBellOpen] = useState(false);
    const bellRef = useRef<HTMLDivElement>(null);
    const pageTitle = getPageTitle(pathname);
    const { notifications, unreadCount, markAllRead, clearAll, dismiss } = useNotification();

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

    // 외부 클릭 시 벨 닫기 (지연 등록으로 토글 클릭 충돌 방지)
    useEffect(() => {
        if (!bellOpen) return;
        const handleClick = (e: MouseEvent) => {
            if (bellRef.current && !bellRef.current.contains(e.target as Node)) {
                setBellOpen(false);
            }
        };
        const timer = setTimeout(() => document.addEventListener('mousedown', handleClick), 10);
        return () => { clearTimeout(timer); document.removeEventListener('mousedown', handleClick); };
    }, [bellOpen]);

    const handleBellClick = () => {
        setBellOpen(prev => !prev);
        if (!bellOpen && unreadCount > 0) markAllRead();
    };

    const typeIcon: Record<string, string> = {
        alert: 'fas fa-bolt text-amber-400',
        success: 'fas fa-check-circle text-emerald-400',
        info: 'fas fa-info-circle text-blue-400',
    };

    return (
        <>
            <header className="h-14 md:h-16 flex items-center justify-between px-4 md:px-6 border-b border-white/10 md:border-white/5 bg-[#111113] md:bg-[#09090b]/80 backdrop-blur-md shrink-0 z-40">
                {/* Left: Hamburger (mobile) + Page Title */}
                <div className="flex items-center gap-3">
                    <button
                        onClick={onMenuClick}
                        className="md:hidden w-10 h-10 flex items-center justify-center rounded-xl bg-white/10 text-white hover:bg-white/20 transition-colors active:scale-95"
                    >
                        <i className="fas fa-bars text-base"></i>
                    </button>

                    <button
                        onClick={() => {
                            if (pathname !== '/dashboard') navigate('/dashboard');
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
                    <button
                        onClick={() => setPaletteOpen(true)}
                        className="md:hidden p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors active:scale-95"
                    >
                        <i className="fas fa-search text-sm"></i>
                    </button>

                    {/* Refresh Button */}
                    <button
                        onClick={() => window.location.reload()}
                        className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors active:scale-95"
                        title="Refresh"
                    >
                        <i className="fas fa-sync-alt text-sm"></i>
                    </button>

                    {/* Bell - Notification Center */}
                    <div ref={bellRef} className="relative">
                        <button
                            onClick={handleBellClick}
                            className={`p-2 hover:text-white hover:bg-white/10 rounded-full transition-colors relative active:scale-95 ${unreadCount > 0 ? 'text-amber-400 animate-[bell-ring_1s_ease-in-out_infinite]' : 'text-gray-400'}`}
                        >
                            <i className="far fa-bell text-sm"></i>
                            {unreadCount > 0 && (
                                <span className="absolute top-1 right-1 min-w-[14px] h-[14px] flex items-center justify-center px-0.5 text-[9px] font-bold bg-red-500 text-white rounded-full border border-black animate-pulse">
                                    {unreadCount > 9 ? '9+' : unreadCount}
                                </span>
                            )}
                        </button>

                        {/* Dropdown */}
                        {bellOpen && (
                            <div className="absolute right-0 top-full mt-2 w-80 max-h-[400px] bg-[#1c1c1e] border border-white/10 rounded-2xl shadow-2xl overflow-hidden z-50">
                                <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
                                    <span className="text-xs font-bold text-white">Notifications</span>
                                    {notifications.length > 0 && (
                                        <button onClick={clearAll} className="text-[10px] text-gray-500 hover:text-red-400 transition-colors">
                                            Clear all
                                        </button>
                                    )}
                                </div>
                                <div className="overflow-y-auto max-h-[340px]">
                                    {notifications.length === 0 ? (
                                        <div className="p-6 text-center text-gray-500 text-xs">
                                            <i className="far fa-bell-slash text-lg mb-2 block"></i>
                                            No notifications yet
                                        </div>
                                    ) : (
                                        notifications.slice(0, 15).map(n => (
                                            <div
                                                key={n.id}
                                                className={`flex items-start gap-3 px-4 py-3 hover:bg-white/5 cursor-pointer transition-colors border-b border-white/5 ${!n.read ? 'bg-white/[0.02]' : ''}`}
                                                onClick={() => {
                                                    if (n.link) {
                                                        navigate(n.link);
                                                        setBellOpen(false);
                                                    }
                                                }}
                                            >
                                                <i className={`${typeIcon[n.type] || typeIcon.info} text-xs mt-1`}></i>
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-[11px] font-semibold text-white truncate">{n.title}</div>
                                                    <div className="text-[10px] text-gray-500 mt-0.5 line-clamp-2">{n.message}</div>
                                                    <div className="text-[9px] text-gray-600 mt-1">{timeAgo(n.timestamp)}</div>
                                                </div>
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); dismiss(n.id); }}
                                                    className="text-gray-600 hover:text-gray-400 text-[10px] p-1 shrink-0"
                                                >
                                                    <i className="fas fa-times"></i>
                                                </button>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </header>

            <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        </>
    );
}
