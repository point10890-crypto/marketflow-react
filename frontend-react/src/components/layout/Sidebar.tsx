import { Link, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';

interface NavItem {
    name: string;
    href: string;
    icon: string;
    color: string;
    children?: { name: string; href: string; color: string }[];
}

interface SidebarProps {
    mobile?: boolean;
    isOpen?: boolean;
    onClose?: () => void;
}

const navigation: NavItem[] = [
    {
        name: 'Summary',
        href: '/dashboard',
        icon: 'fa-tachometer-alt',
        color: 'text-purple-400',
    },
    {
        name: 'VCP Enhanced',
        href: '/dashboard/vcp-enhanced',
        icon: 'fa-bolt',
        color: 'text-yellow-400',
    },
    {
        name: 'KR Market',
        href: '/dashboard/kr',
        icon: 'fa-chart-line',
        color: 'text-blue-400',
        children: [
            { name: 'Overview', href: '/dashboard/kr', color: 'bg-blue-500' },
            { name: 'VCP Signals', href: '/dashboard/kr/vcp', color: 'bg-rose-500' },
            { name: '종가베팅', href: '/dashboard/kr/closing-bet', color: 'bg-violet-500' },
            { name: '성과 히스토리', href: '/dashboard/kr/closing-bet/history', color: 'bg-fuchsia-500' },
            { name: 'Track Record', href: '/dashboard/kr/track-record', color: 'bg-yellow-500' },
        ],
    },
    {
        name: 'US Market',
        href: '/dashboard/us',
        icon: 'fa-globe-americas',
        color: 'text-green-400',
        children: [
            { name: 'Overview', href: '/dashboard/us', color: 'bg-green-500' },
            { name: 'VCP Signals', href: '/dashboard/us/vcp', color: 'bg-rose-500' },
            { name: 'ETF Flows', href: '/dashboard/us/etf', color: 'bg-blue-600' },
        ],
    },
    {
        name: 'Crypto',
        href: '/dashboard/crypto',
        icon: 'fa-bitcoin',
        color: 'text-yellow-500',
        children: [
            { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
            { name: 'VCP Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
        ],

    },
    {
        name: 'ProPicks',
        href: '/dashboard/stock-analyzer',
        icon: 'fa-crosshairs',
        color: 'text-orange-400',
    },
];

const adminNavigation: NavItem[] = [
    {
        name: 'Admin Dashboard',
        href: '/admin',
        icon: 'fa-shield-alt',
        color: 'text-red-400',
    },
    {
        name: 'Users',
        href: '/admin/users',
        icon: 'fa-users-cog',
        color: 'text-red-400',
    },
    {
        name: 'Subscriptions',
        href: '/admin/subscriptions',
        icon: 'fa-credit-card',
        color: 'text-red-400',
    },
    {
        name: 'System',
        href: '/admin/system',
        icon: 'fa-server',
        color: 'text-red-400',
    },
];

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const { user, logout } = useAuth();

    const userName = user?.name || 'Guest';
    const userTier = user?.tier || 'free';
    const userRole = user?.role || 'user';
    const isLoggedIn = !!user;

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
            <nav className="flex-1 px-3.5 py-5 space-y-1 overflow-y-scroll sidebar-scroll">
                <div className="px-3 mb-3 text-[11px] font-semibold uppercase tracking-[0.2em]">
                    <span className="bg-gradient-to-r from-amber-400/70 to-yellow-500/50 bg-clip-text text-transparent">Market</span>
                    <span className="text-gray-500 ml-0.5">Flow</span>
                </div>

                {navigation.map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                    const hasChildren = item.children && item.children.length > 0;
                    const isExpanded = hasChildren && pathname.startsWith(item.href);

                    return (
                        <div key={item.name}>
                            <Link
                                to={item.href}
                                onClick={!hasChildren ? onNavigate : undefined}
                                className={`flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-[15px] font-medium transition-all ${isActive
                                    ? 'text-white bg-white/5 border border-white/5'
                                    : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                                    }`}
                            >
                                <i className={`fas ${item.icon} w-5 text-center text-base ${item.color}`}></i>
                                <span>{item.name}</span>
                                {hasChildren && (
                                    <i
                                        className={`fas fa-chevron-down text-xs ml-auto transition-transform ${isExpanded ? 'rotate-180' : ''
                                            }`}
                                    ></i>
                                )}
                            </Link>

                            {/* Submenu */}
                            {hasChildren && isExpanded && (
                                <div className="pl-4 space-y-0.5 mt-1">
                                    {item.children!.map((child) => (
                                        <Link
                                            key={child.href}
                                            to={child.href}
                                            onClick={onNavigate}
                                            className={`block px-3.5 py-2 text-[13px] rounded-lg transition-colors ${pathname === child.href
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

                {/* Divider */}
                <div className="my-3 mx-2 border-t border-white/[0.06]" />

                {/* User Account Section */}
                {isLoggedIn && (
                    <>
                        <div className="px-3 mt-6 mb-3 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                            Account
                        </div>
                        <Link
                            to="/account"
                            onClick={onNavigate}
                            className={`flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-[15px] font-medium transition-all ${pathname === '/account'
                                ? 'text-white bg-white/5 border border-white/5'
                                : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                                }`}
                        >
                            <i className="fas fa-user-circle w-5 text-center text-base text-blue-400"></i>
                            <span>My Account</span>
                        </Link>
                        {userTier === 'free' && (
                            <Link
                                to="/pricing"
                                onClick={onNavigate}
                                className="flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-[15px] font-medium text-yellow-400 hover:text-white hover:bg-yellow-500/10 border border-transparent transition-all"
                            >
                                <i className="fas fa-crown w-5 text-center text-base"></i>
                                <span>Upgrade to Pro</span>
                            </Link>
                        )}
                    </>
                )}

                {/* Admin Section */}
                {userRole === 'admin' && (
                    <>
                        <div className="px-3 mt-6 mb-3 text-[11px] font-semibold text-red-500 uppercase tracking-wider">
                            Admin
                        </div>
                        {adminNavigation.map((item) => {
                            const isActive = pathname === item.href;
                            return (
                                <Link
                                    key={item.name}
                                    to={item.href}
                                    onClick={onNavigate}
                                    className={`flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-[15px] font-medium transition-all ${isActive
                                        ? 'text-white bg-red-500/10 border border-red-500/20'
                                        : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                                        }`}
                                >
                                    <i className={`fas ${item.icon} w-5 text-center text-base ${item.color}`}></i>
                                    <span>{item.name}</span>
                                </Link>
                            );
                        })}
                    </>
                )}
            </nav>

            {/* Data Status - bottom pinned */}
            <div className="px-3.5 pb-2">
                <Link
                    to="/dashboard/data-status"
                    onClick={onNavigate}
                    className={`flex items-center gap-3.5 px-3.5 py-2.5 rounded-xl text-[13px] font-medium transition-all ${
                        pathname === '/dashboard/data-status'
                            ? 'text-white bg-white/5 border border-white/5'
                            : 'text-gray-500 hover:text-gray-300 hover:bg-white/5 border border-transparent'
                    }`}
                >
                    <i className="fas fa-database w-5 text-center text-sm text-gray-500"></i>
                    <span>Data Status</span>
                </Link>
            </div>

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
                                {userTier === 'pro' ? 'Pro Plan' : userTier === 'premium' ? 'Premium' : 'Free Plan'}
                            </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            {userTier !== 'free' && (
                                <span className="text-[11px] px-2.5 py-1 rounded-md bg-purple-500/10 text-purple-400 font-bold">
                                    {userTier === 'pro' ? 'Pro' : 'Premium'}
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
