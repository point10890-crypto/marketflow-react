'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useSession, signOut } from 'next-auth/react';

interface NavItem {
    name: string;
    href: string;
    icon: string;
    color: string;
    children?: { name: string; href: string; color: string }[];
}

const navigation: NavItem[] = [
    {
        name: 'Summary',
        href: '/dashboard/crypto',
        icon: 'fa-tachometer-alt',
        color: 'text-purple-400',
    },
    {
        name: 'Crypto',
        href: '/dashboard/crypto',
        icon: 'fa-bitcoin',
        color: 'text-yellow-500',
        children: [
            { name: 'Overview', href: '/dashboard/crypto', color: 'bg-yellow-500' },
            { name: 'Briefing', href: '/dashboard/crypto/briefing', color: 'bg-amber-500' },
            { name: 'Signals', href: '/dashboard/crypto/signals', color: 'bg-orange-500' },
            { name: 'Prediction', href: '/dashboard/crypto/prediction', color: 'bg-red-500' },
            { name: 'Risk', href: '/dashboard/crypto/risk', color: 'bg-rose-500' },
        ],
    },
    {
        name: 'Data Status',
        href: '/dashboard/data-status',
        icon: 'fa-database',
        color: 'text-gray-400',
    },
];

export default function Sidebar() {
    const pathname = usePathname();
    const { data: session } = useSession();

    const userName = session?.user?.name || 'Guest';
    const userTier = (session?.user as Record<string, unknown>)?.tier as string || 'free';

    return (
        <aside className="w-64 apple-glass flex flex-col shrink-0 z-50">
            {/* Brand */}
            <div className="h-16 flex items-center px-4 border-b border-white/5">
                <div className="w-8 h-8 bg-yellow-500 rounded-lg flex items-center justify-center text-white font-bold text-lg shadow-lg shadow-yellow-500/20 mr-3">
                    C
                </div>
                <span className="text-white font-bold tracking-tight text-lg">
                    Crypto<span className="text-yellow-500">Analytics</span>
                </span>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3 py-6 space-y-1 overflow-y-auto">
                <div className="px-3 mb-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Dashboard
                </div>

                {navigation.map((item) => {
                    const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                    const hasChildren = item.children && item.children.length > 0;
                    const isExpanded = hasChildren && pathname.startsWith(item.href);

                    return (
                        <div key={item.name}>
                            <Link
                                href={item.href}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${isActive
                                    ? 'text-white bg-white/5 border border-white/5'
                                    : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                                    }`}
                            >
                                <i className={`fas ${item.icon} w-5 text-center ${item.color}`}></i>
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
                                <div className="pl-3 space-y-1 mt-1">
                                    {item.children!.map((child) => (
                                        <Link
                                            key={child.href}
                                            href={child.href}
                                            className={`block px-3 py-2 text-xs rounded-md transition-colors ${pathname === child.href
                                                ? 'text-white bg-white/10'
                                                : 'text-gray-400 hover:text-white hover:bg-white/5'
                                                }`}
                                        >
                                            <span className={`inline-block w-1.5 h-1.5 rounded-full ${child.color} mr-2`}></span>
                                            {child.name}
                                        </Link>
                                    ))}
                                </div>
                            )}
                        </div>
                    );
                })}
            </nav>

            {/* Profile */}
            <div className="p-4 border-t border-white/5">
                <div className="flex items-center gap-3 p-2 rounded-lg">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-500 ring-2 ring-white/10 flex items-center justify-center text-white text-xs font-bold">
                        {userName.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex flex-col flex-1 min-w-0">
                        <span className="text-xs font-bold text-white truncate">{userName}</span>
                        <span className={`text-[10px] font-medium ${userTier === 'pro' ? 'text-yellow-500' : 'text-gray-500'}`}>
                            {userTier === 'pro' ? 'Pro Plan' : 'Free Plan'}
                        </span>
                    </div>
                    {session ? (
                        <button
                            onClick={() => signOut({ callbackUrl: '/login' })}
                            className="text-gray-500 hover:text-white transition-colors"
                            title="Sign Out"
                        >
                            <i className="fas fa-sign-out-alt text-sm"></i>
                        </button>
                    ) : (
                        <Link href="/login" className="text-gray-500 hover:text-white transition-colors">
                            <i className="fas fa-sign-in-alt text-sm"></i>
                        </Link>
                    )}
                </div>
            </div>
        </aside>
    );
}
