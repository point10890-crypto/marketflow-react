import { Link, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { InstallGuide } from './InstallPrompt';

interface NavItem {
    name: string;
    href: string;
    icon: string;
    color: string;
    bg?: string;
    glow?: boolean;
    dividerBefore?: string;
    badge?: string;
    children?: { name: string; href: string; color: string }[];
}

interface SidebarProps {
    mobile?: boolean;
    isOpen?: boolean;
    onClose?: () => void;
}

// 상단 글로벌 도구
const globalTools: NavItem[] = [
    { name: 'Summary', href: '/dashboard', icon: 'fa-tachometer-alt', color: 'text-purple-400', bg: 'from-purple-500/15 to-purple-600/5' },
    { name: 'Briefing', href: '/dashboard/briefing', icon: 'fa-newspaper', color: 'text-amber-400', bg: 'from-amber-500/15 to-amber-600/5' },
    { name: 'VCP Enhanced', href: '/dashboard/vcp-enhanced', icon: 'fa-bolt', color: 'text-yellow-400', bg: 'from-yellow-500/15 to-yellow-600/5' },
    { name: 'W Pattern', href: '/dashboard/wave', icon: 'fa-wave-square', color: 'text-pink-400', bg: 'from-pink-500/15 to-pink-600/5', glow: true, badge: 'AI' },
];

// 시장별 카드
const marketCards: NavItem[] = [
    {
        name: 'KR', href: '/dashboard/kr', icon: 'fa-chart-line', color: 'text-blue-400', bg: 'from-blue-500/20 to-blue-600/5',
        children: [
            { name: 'Overview', href: '/dashboard/kr', color: 'bg-blue-500' },
            { name: 'VCP Signals', href: '/dashboard/kr/vcp', color: 'bg-rose-500' },
            { name: '주도주LIVE', href: '/dashboard/kr/leading-stocks', color: 'bg-orange-500' },
            { name: '종가베팅', href: '/dashboard/kr/closing-bet', color: 'bg-violet-500' },
            { name: '성과 히스토리', href: '/dashboard/kr/closing-bet/history', color: 'bg-fuchsia-500' },
            { name: 'Track Record', href: '/dashboard/kr/track-record', color: 'bg-yellow-500' },
            { name: 'AI Chart', href: '/dashboard/kr/ai-chart', color: 'bg-cyan-500' },
        ],
    },
    {
        name: 'US', href: '/dashboard/us', icon: 'fa-globe-americas', color: 'text-green-400', bg: 'from-green-500/20 to-green-600/5',
        children: [
            { name: 'Overview', href: '/dashboard/us', color: 'bg-green-500' },
            { name: 'VCP Signals', href: '/dashboard/us/vcp', color: 'bg-rose-500' },
            { name: 'ETF Flows', href: '/dashboard/us/etf', color: 'bg-blue-600' },
            { name: 'AI Chart', href: '/dashboard/us/ai-chart', color: 'bg-cyan-500' },
        ],
    },
    {
        name: 'Crypto', href: '/dashboard/crypto', icon: 'fa-bitcoin', color: 'text-amber-400', bg: 'from-amber-500/20 to-amber-600/5',
        children: [
            { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
            { name: 'VCP Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
        ],
    },
];

// 하단 도구
const toolItems: NavItem[] = [
    { name: 'ProPicks', href: '/dashboard/stock-analyzer', icon: 'fa-crosshairs', color: 'text-orange-400', bg: 'from-orange-500/15 to-orange-600/5' },
];

// 전체 navigation (하위 호환용)
const navigation = [...globalTools, ...marketCards, ...toolItems];

const adminNavigation: NavItem[] = [
    {
        name: '관리자',
        href: '/admin',
        icon: 'fa-shield-alt',
        color: 'text-red-400',
    },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const { user, logout } = useAuth();
    const { canInstall, isInstalled, isIOS, install } = usePWAInstall();
    const [showGuide, setShowGuide] = useState(false);

    const userName = user?.name || 'Guest';
    const userTier = user?.tier ?? null;
    // Guards ensure only pro/premium/admin reach the dashboard, so tier-lock UI is vestigial.
    const isLocked = false;
    const userRole = user?.role || 'user';
    const isLoggedIn = !!user;

    const handleSidebarInstall = async () => {
        const result = await install();
        if (result === 'manual') setShowGuide(true);
    };

    return (
        <>
            {/* Brand */}
            <Link to="/dashboard" className="h-[72px] flex items-center px-5 border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer">
                <div className="relative w-10 h-10 bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600 rounded-xl flex items-center justify-center text-white font-extrabold text-2xl shadow-lg shadow-amber-500/30 mr-3.5 ring-1 ring-amber-400/20 drop-shadow-sm">
                    <div className="absolute inset-0.5 rounded-[10px] ring-1 ring-white/10" />
                    <span className="relative">B</span>
                </div>
                <div className="flex flex-col leading-none">
                    <span className="text-[24px] font-extrabold tracking-tight">
                        <span className="bg-gradient-to-r from-yellow-300 via-amber-400 to-yellow-500 bg-clip-text text-transparent">Bit</span><span className="bg-gradient-to-r from-amber-400 to-yellow-300 bg-clip-text text-transparent">Man</span>
                    </span>
                    <div className="w-full h-px bg-gradient-to-r from-amber-500/50 via-amber-400/20 to-transparent mt-1 mb-[3px]" />
                    <span className="text-[13px] font-semibold tracking-[0.18em] bg-gradient-to-r from-gray-300 via-slate-400 to-gray-500 bg-clip-text text-transparent">MarketFlow</span>
                </div>
            </Link>

            {/* Navigation */}
            <nav className="flex-1 px-3.5 py-4 pb-8 overflow-y-scroll sidebar-scroll">
                {/* ── Global Tools ── */}
                <div className="px-2 mb-2.5 text-[10px] font-semibold uppercase tracking-[0.2em]">
                    <span className="bg-gradient-to-r from-amber-400/70 to-yellow-500/50 bg-clip-text text-transparent">Market</span>
                    <span className="text-gray-500 ml-0.5">Flow</span>
                </div>
                <div className="space-y-1 mb-1">
                    {globalTools.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link key={item.name} to={item.href} onClick={onNavigate}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] font-medium transition-all border ${
                                    isActive
                                        ? `bg-gradient-to-r ${item.bg} text-white border-white/10`
                                        : 'text-gray-400 hover:text-white hover:bg-white/[0.03] border-transparent'
                                }`}
                            >
                                {item.glow ? (
                                    <span className="relative w-8 h-8 rounded-lg bg-pink-500/10 flex items-center justify-center shrink-0">
                                        <i className={`fas ${item.icon} text-sm ${item.color} drop-shadow-[0_0_6px_rgba(236,72,153,0.5)]`}></i>
                                    </span>
                                ) : (
                                    <span className={`w-8 h-8 rounded-lg bg-gradient-to-br ${item.bg} flex items-center justify-center shrink-0`}>
                                        <i className={`fas ${item.icon} text-sm ${item.color}`}></i>
                                    </span>
                                )}
                                <span>{item.name}</span>
                                {item.badge && (
                                    <span className="ml-auto text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-pink-500/15 text-pink-400 border border-pink-500/20 animate-pulse" style={{ animationDuration: '2s' }}>
                                        {item.badge}
                                    </span>
                                )}
                                {isLocked && item.href !== '/dashboard' && !item.glow && (
                                    <i className="fas fa-lock text-[10px] text-gray-600 ml-auto" />
                                )}
                            </Link>
                        );
                    })}
                </div>

                {/* ── Markets Section ── */}
                <div className="flex items-center gap-2 px-2 pt-4 pb-2">
                    <div className="flex-1 h-px bg-white/[0.06]" />
                    <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-gray-600">Markets</span>
                    <div className="flex-1 h-px bg-white/[0.06]" />
                </div>

                <div className="space-y-1">
                    {marketCards.map((item) => {
                        const isActive = pathname.startsWith(item.href);
                        const isExpanded = isActive && item.children;
                        return (
                            <div key={item.name}>
                                <Link to={item.href} onClick={onNavigate}
                                    className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] font-medium transition-all border ${
                                        isActive
                                            ? `bg-gradient-to-r ${item.bg} text-white border-white/10`
                                            : 'text-gray-400 hover:text-white hover:bg-white/[0.03] border-transparent'
                                    }`}
                                >
                                    <span className={`w-8 h-8 rounded-lg bg-gradient-to-br ${item.bg} flex items-center justify-center shrink-0`}>
                                        <i className={`fas ${item.icon} text-sm ${item.color}`}></i>
                                    </span>
                                    <span>{item.name}</span>
                                    {item.children && (
                                        <i className={`fas fa-chevron-down text-xs ml-auto transition-transform ${isExpanded ? 'rotate-180' : ''}`}></i>
                                    )}
                                </Link>
                                {isExpanded && item.children && (
                                    <div className="space-y-0.5 mt-1 ml-2 p-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                                        {item.children.map((child) => (
                                            <Link key={child.href} to={child.href} onClick={onNavigate}
                                                className={`block px-3 py-2 text-[13px] rounded-lg transition-colors ${
                                                    pathname === child.href
                                                        ? 'text-white bg-white/10'
                                                        : 'text-gray-400 hover:text-white hover:bg-white/5'
                                                }`}
                                            >
                                                <span className={`inline-block w-1.5 h-1.5 rounded-full ${child.color} mr-2.5`}></span>
                                                {child.name}
                                            </Link>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* ── Tools Section ── */}
                <div className="flex items-center gap-2 px-2 pt-3 pb-2">
                    <div className="flex-1 h-px bg-white/[0.06]" />
                    <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-gray-600">Tools</span>
                    <div className="flex-1 h-px bg-white/[0.06]" />
                </div>
                <div className="space-y-1 mb-1">
                    {toolItems.map((item) => {
                        const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                        return (
                            <Link key={item.name} to={item.href} onClick={onNavigate}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] font-medium transition-all border ${
                                    isActive
                                        ? `bg-gradient-to-r ${item.bg} text-white border-white/10`
                                        : 'text-gray-400 hover:text-white hover:bg-white/[0.03] border-transparent'
                                }`}
                            >
                                <span className={`w-8 h-8 rounded-lg bg-gradient-to-br ${item.bg} flex items-center justify-center shrink-0`}>
                                    <i className={`fas ${item.icon} text-sm ${item.color}`}></i>
                                </span>
                                <span>{item.name}</span>
                            </Link>
                        );
                    })}
                </div>

                {/* Divider */}
                <div className="my-2 mx-2 border-t border-white/[0.06]" />

                {/* User Account Section */}
                {isLoggedIn && (
                    <>
                        <div className="flex items-center gap-2 px-2 pt-3 pb-2">
                            <div className="flex-1 h-px bg-white/[0.06]" />
                            <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-gray-600">Account</span>
                            <div className="flex-1 h-px bg-white/[0.06]" />
                        </div>
                        <Link
                            to="/dashboard/account"
                            onClick={onNavigate}
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-[14px] font-medium transition-all border ${pathname === '/dashboard/account'
                                ? 'text-white bg-white/5 border-white/5'
                                : 'text-gray-400 hover:text-white hover:bg-white/[0.03] border-transparent'
                                }`}
                        >
                            <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/15 to-blue-600/5 flex items-center justify-center shrink-0">
                                <i className="fas fa-user-circle text-sm text-blue-400"></i>
                            </span>
                            <span>내 계정</span>
                        </Link>
                    </>
                )}

                {/* Admin Section */}
                {userRole === 'admin' && (
                    <div className="space-y-1 mt-2">
                        <Link to="/admin/data-status" onClick={onNavigate}
                            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-[13px] font-medium transition-all border ${
                                pathname === '/admin/data-status'
                                    ? 'text-white bg-white/5 border-white/5'
                                    : 'text-gray-500 hover:text-gray-300 hover:bg-white/5 border-transparent'
                            }`}
                        >
                            <i className="fas fa-database w-5 text-center text-sm text-gray-500"></i>
                            <span>Data Status</span>
                        </Link>
                        <Link to="/admin" onClick={onNavigate}
                            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-[13px] font-medium transition-all border ${
                                pathname.startsWith('/admin') && pathname !== '/admin/data-status'
                                    ? 'text-red-400 bg-red-500/10 border-red-500/20'
                                    : 'text-gray-500 hover:text-red-400 hover:bg-red-500/5 border-transparent'
                            }`}
                        >
                            <i className="fas fa-shield-alt w-5 text-center text-sm text-red-400/60"></i>
                            <span>관리자</span>
                        </Link>
                    </div>
                )}

                {/* Community — inside scroll area */}
                <Link to="/dashboard/community" onClick={onNavigate}
                    className={`mt-4 flex items-center gap-2.5 p-3 rounded-xl text-[13px] font-bold transition-all border ${
                        pathname.startsWith('/dashboard/community')
                            ? 'text-yellow-400 bg-gradient-to-r from-yellow-500/15 to-amber-500/10 border-yellow-500/20'
                            : 'text-yellow-400/80 hover:text-yellow-400 bg-gradient-to-r from-yellow-500/10 to-amber-500/5 border-yellow-500/10 hover:border-yellow-500/20'
                    }`}
                >
                    <i className="fas fa-comments w-5 text-center"></i>
                    <span>커뮤니티</span>
                </Link>

                {/* App Install — inside scroll area */}
                {!isInstalled && (
                    <button
                        onClick={handleSidebarInstall}
                        className="mt-2 w-full flex items-center gap-2.5 p-3 rounded-xl bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border border-blue-500/20 text-[13px] font-bold text-blue-400 hover:text-blue-300 transition-colors"
                    >
                        <i className="fas fa-mobile-screen-button w-5 text-center"></i>
                        <span>앱 다운로드</span>
                        <i className="fas fa-download text-[10px] ml-auto opacity-50"></i>
                    </button>
                )}
            </nav>
            {showGuide && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}

            {/* Profile */}
            <div className="p-4 border-t border-white/5">
                {isLoggedIn ? (
                    <div className="flex items-center gap-3 p-2.5 rounded-xl">
                        <div className={`w-9 h-9 rounded-full ring-2 ring-white/10 flex items-center justify-center text-white text-sm font-bold ${userTier === 'pro' || userTier === 'premium' ? 'bg-gradient-to-tr from-indigo-500 to-purple-500' : 'bg-gradient-to-tr from-gray-600 to-gray-500'}`}>
                            {userName.charAt(0).toUpperCase()}
                        </div>
                        <div className="flex flex-col flex-1 min-w-0">
                            <span className="text-sm font-bold text-white truncate">{userName}</span>
                            <span className={`text-[11px] ${userTier === 'pro' || userTier === 'premium' ? 'text-purple-400' : 'text-gray-500'}`}>
                                {userTier === 'pro' ? 'Pro Plan' : userTier === 'premium' ? 'Ultra Pro' : 'Admin'}
                            </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            {(userTier === 'pro' || userTier === 'premium') && (
                                <span className="text-[11px] px-2.5 py-1 rounded-md bg-purple-500/10 text-purple-400 font-bold">
                                    {userTier === 'pro' ? 'Pro' : 'Ultra Pro'}
                                </span>
                            )}
                            <button
                                onClick={() => logout()}
                                className="text-[11px] px-2.5 py-1.5 rounded-md bg-white/5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                                title="Sign Out"
                            >
                                <i className="fas fa-sign-out-alt"></i>
                            </button>
                        </div>
                    </div>
                ) : (
                    <Link
                        to="/login"
                        className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-white/5 transition-colors"
                    >
                        <div className="w-9 h-9 rounded-full bg-gray-700 flex items-center justify-center">
                            <i className="fas fa-sign-in-alt text-gray-400 text-sm"></i>
                        </div>
                        <span className="text-[15px] text-gray-400">Sign In</span>
                    </Link>
                )}
            </div>
        </>
    );
}

export default function Sidebar({ mobile = false, isOpen = false, onClose }: SidebarProps) {
    // Lock body scroll when mobile sidebar is open
    useEffect(() => {
        if (mobile && isOpen) {
            document.body.style.overflow = 'hidden';
            return () => { document.body.style.overflow = ''; };
        }
    }, [mobile, isOpen]);

    // Desktop sidebar
    if (!mobile) {
        return (
            <aside className="w-72 apple-glass flex flex-col shrink-0 z-50">
                <SidebarContent />
            </aside>
        );
    }

    // Mobile overlay sidebar
    return (
        <div
            className={`fixed inset-0 z-[60] transition-opacity duration-300 ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        >
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                onClick={onClose}
            />
            {/* Sidebar panel */}
            <aside
                className={`absolute top-0 left-0 h-full w-80 apple-glass flex flex-col shadow-2xl shadow-black/50 transition-transform duration-300 ease-out ${
                    isOpen ? 'translate-x-0' : '-translate-x-full'
                }`}
            >
                {/* Close button */}
                <button
                    onClick={onClose}
                    className="absolute top-5 right-4 w-8 h-8 flex items-center justify-center rounded-full bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition-colors z-10"
                >
                    <i className="fas fa-times text-sm"></i>
                </button>
                <SidebarContent onNavigate={onClose} />
            </aside>
        </div>
    );
}
