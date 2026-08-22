import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

const tabs = [
    { name: 'Summary', href: '/dashboard', icon: 'fas fa-tachometer-alt', color: 'purple' },
    { name: 'AI Brain', href: '/dashboard/ai-bain', icon: 'fa-robot', color: 'cyan' },
    { name: 'KR', href: '/dashboard/kr', icon: 'fa-chart-line', color: 'rose' },
    { name: 'US', href: '/dashboard/us', icon: 'fa-globe-americas', color: 'green' },
    { name: 'Crypto', href: '/dashboard/crypto', icon: 'fab fa-bitcoin', color: 'yellow' },
    { name: 'AI 분석', href: '/dashboard/manual-stock-analysis', icon: 'fa-table-list', color: 'orange' },
    { name: 'Briefing', href: '/dashboard/briefing', icon: 'fa-newspaper', color: 'blue' },
    { name: '커뮤니티', href: '/dashboard/community', icon: 'fa-comments', color: 'cyan' },
];

const activeColors: Record<string, string> = {
    purple: 'text-purple-300',
    rose: 'text-rose-300',
    green: 'text-green-300',
    yellow: 'text-yellow-300',
    cyan: 'text-cyan-300',
    orange: 'text-orange-300',
    blue: 'text-blue-300',
};

const activeDots: Record<string, string> = {
    purple: 'bg-purple-300',
    rose: 'bg-rose-300',
    green: 'bg-green-300',
    yellow: 'bg-yellow-300',
    cyan: 'bg-cyan-300',
    orange: 'bg-orange-300',
    blue: 'bg-blue-300',
};

function isActive(pathname: string, href: string) {
    if (href === '/dashboard') return pathname === '/dashboard';
    return pathname === href || pathname.startsWith(href + '/');
}

function iconClass(icon: string) {
    return icon.includes(' ') ? icon : `fas ${icon}`;
}

export default function BottomTabBar() {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    const { user } = useAuth();
    const isLocked = !!user && user.tier !== 'pro' && user.tier !== 'premium' && user.role !== 'admin';

    return (
        <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 mobile-safe-bottom">
            <div className="border-t border-white/5 bg-[#0a0a0a]/92 backdrop-blur-xl">
                <div className="mobile-bottom-tabs flex items-center gap-1 overflow-x-auto px-2 py-1.5">
                    {tabs.map((tab) => {
                        const selected = isActive(pathname, tab.href);
                        return (
                            <Link
                                key={tab.href}
                                to={tab.href}
                                className={`relative flex min-h-[58px] min-w-[64px] shrink-0 flex-col items-center justify-center gap-0.5 rounded-xl px-2 transition-all active:scale-95 ${
                                    selected
                                        ? `claw-tab-active ${activeColors[tab.color]} bg-white/[0.06]`
                                        : 'text-zinc-600'
                                }`}
                            >
                                <span className="relative">
                                    <i className={`${iconClass(tab.icon)} text-base`} />
                                    {isLocked && tab.href !== '/dashboard' && (
                                        <i className="fas fa-lock absolute -right-2 -top-1 text-[7px] text-slate-600" />
                                    )}
                                </span>
                                <span className="max-w-[58px] truncate text-[9px] font-black tracking-wide">{tab.name}</span>
                                {selected && (
                                    <span className={`mt-0.5 h-1 w-1 rounded-full ${activeDots[tab.color]}`} />
                                )}
                            </Link>
                        );
                    })}
                </div>
            </div>
        </nav>
    );
}
