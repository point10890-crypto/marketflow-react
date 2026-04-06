import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

const tabs = [
    { name: 'Summary', href: '/dashboard', icon: 'fa-tachometer-alt', color: 'purple' },
    { name: 'KR', href: '/dashboard/kr', icon: 'fa-chart-line', color: 'rose' },
    { name: 'US', href: '/dashboard/us', icon: 'fa-globe-americas', color: 'green' },
    { name: 'Crypto', href: '/dashboard/crypto', icon: 'fa-bitcoin', color: 'yellow' },
    { name: 'ProPicks', href: '/dashboard/stock-analyzer', icon: 'fa-crosshairs', color: 'orange' },
    { name: '커뮤니티', href: '/dashboard/community', icon: 'fa-comments', color: 'cyan' },
];

const activeColors: Record<string, string> = {
    purple: 'text-purple-400',
    rose: 'text-rose-400',
    green: 'text-green-400',
    yellow: 'text-yellow-400',
    cyan: 'text-cyan-400',
    orange: 'text-orange-400',
};

const activeDots: Record<string, string> = {
    purple: 'bg-purple-400',
    rose: 'bg-rose-400',
    green: 'bg-green-400',
    yellow: 'bg-yellow-400',
    cyan: 'bg-cyan-400',
    orange: 'bg-orange-400',
};

export default function BottomTabBar() {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const { user } = useAuth();
    // Guards ensure only pro/premium/admin reach the dashboard; locked state is vestigial.
    const isLocked = !!user && user.tier !== 'pro' && user.tier !== 'premium' && user.role !== 'admin';

    return (
        <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 mobile-safe-bottom">
            <div className="bg-[#0a0a0a]/90 backdrop-blur-xl border-t border-white/5">
                <div className="flex items-center justify-around px-0.5 py-1.5">
                    {tabs.map((tab) => {
                        const isActive = tab.href === '/dashboard'
                            ? pathname === '/dashboard'
                            : pathname.startsWith(tab.href);

                        return (
                            <Link
                                key={tab.href}
                                to={tab.href}
                                className={`flex flex-col items-center justify-center gap-0.5 py-2 px-2 rounded-xl transition-all min-w-[50px] ${
                                    isActive
                                        ? `${activeColors[tab.color]}`
                                        : 'text-zinc-600'
                                }`}
                            >
                                <span className="relative">
                                    <i className={`fas ${tab.icon} text-base`}></i>
                                    {isLocked && tab.href !== '/dashboard' && (
                                        <i className="fas fa-lock absolute -top-1 -right-2 text-[7px] text-gray-600" />
                                    )}
                                </span>
                                <span className="text-[9px] font-bold tracking-wide">{tab.name}</span>
                                {isActive && (
                                    <span className={`w-1 h-1 rounded-full ${activeDots[tab.color]} mt-0.5`}></span>
                                )}
                            </Link>
                        );
                    })}
                </div>
            </div>
        </nav>
    );
}
