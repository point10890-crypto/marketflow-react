import { Link, useLocation } from 'react-router-dom';

const primaryItems = [
    { name: 'Summary', href: '/dashboard', icon: 'fas fa-tachometer-alt' },
    { name: 'Briefing', href: '/dashboard/briefing', icon: 'fa-newspaper' },
    { name: 'AI Brain', href: '/dashboard/ai-bain', icon: 'fa-robot' },
    { name: 'Goodrich TOP 3', href: '/dashboard/ai-bain/goodrich', icon: 'fa-ranking-star' },
    { name: 'KR', href: '/dashboard/kr', icon: 'fa-chart-line' },
    { name: 'US', href: '/dashboard/us', icon: 'fa-globe-americas' },
    { name: 'Crypto', href: '/dashboard/crypto', icon: 'fab fa-bitcoin' },
    { name: 'AI 분석', href: '/dashboard/manual-stock-analysis', icon: 'fa-table-list' },
    { name: '커뮤니티', href: '/dashboard/community', icon: 'fa-comments' },
];

const pageTitles: Array<[RegExp, string, string]> = [
    [/^\/dashboard$/, 'Summary', '시장 요약'],
    [/^\/dashboard\/briefing/, 'Briefing', 'AI 브리핑'],
    [/^\/dashboard\/ai-bain\/goodrich/, 'Goodrich TOP 3', 'AI 펀드매니저'],
    [/^\/dashboard\/ai-bain/, 'AI Brain', 'GraphRAG'],
    [/^\/dashboard\/manual-stock-analysis/, 'AI 분석 목록', '루프 스크래퍼'],
    [/^\/dashboard\/vcp-enhanced/, 'VCP Enhanced', '거래량 수축'],
    [/^\/dashboard\/stock-analyzer/, 'ProPicks', '분석 도구'],
    [/^\/dashboard\/wave/, 'W Pattern', '패턴 감지'],
    [/^\/dashboard\/kr\/leading-stocks/, '주도주 LIVE', 'KR 실시간'],
    [/^\/dashboard\/kr\/closing-bet\/history/, '종가베팅 기록', '성과 검증'],
    [/^\/dashboard\/kr\/closing-bet/, '종가베팅', 'S/A 후보'],
    [/^\/dashboard\/kr\/track-record/, 'Track Record', '사후 성과'],
    [/^\/dashboard\/kr\/ai-chart/, 'KR AI Chart', '차트 분석'],
    [/^\/dashboard\/kr\/vcp/, 'KR VCP', '수축 신호'],
    [/^\/dashboard\/kr/, 'KR Market', '국내 시장'],
    [/^\/dashboard\/us\/etf/, 'US ETF', '패시브 플로우'],
    [/^\/dashboard\/us\/ai-chart/, 'US AI Chart', '차트 분석'],
    [/^\/dashboard\/us\/vcp/, 'US VCP', '수축 신호'],
    [/^\/dashboard\/us/, 'US Market', '미국 시장'],
    [/^\/dashboard\/crypto\/signals/, 'Crypto Signals', 'VCP 신호'],
    [/^\/dashboard\/crypto/, 'Crypto', '디지털 자산'],
    [/^\/dashboard\/community/, 'Community', '게시판'],
    [/^\/dashboard\/account/, '내 계정', '구독 정보'],
];

function activeFor(pathname: string, href: string) {
    if (href === '/dashboard') return pathname === '/dashboard';
    if (href === '/dashboard/ai-bain') return pathname === href;
    return pathname === href || pathname.startsWith(href + '/');
}

function iconClass(icon: string) {
    return icon.includes(' ') ? icon : `fas ${icon}`;
}

export default function MobileDashboardRail() {
    const location = useLocation();
    const pathname = location.pathname ?? '';
    if (!pathname.startsWith('/dashboard')) return null;

    const current = pageTitles.find(([pattern]) => pattern.test(pathname));
    const title = current?.[1] ?? 'Dashboard';
    const subtitle = current?.[2] ?? 'MarketFlow';

    return (
        <section className="md:hidden shrink-0 border-b border-white/5 bg-[#09090b]/96 px-2.5 py-2">
            <div className="mb-2 flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="text-[9px] font-black uppercase tracking-[0.22em] text-slate-600">Mobile Dashboard</div>
                    <div className="mt-0.5 flex items-baseline gap-2">
                        <h1 className="truncate text-base font-black leading-none text-white">{title}</h1>
                        <span className="shrink-0 text-[10px] font-bold text-slate-500">{subtitle}</span>
                    </div>
                </div>
                <Link
                    to="/dashboard/ai-bain"
                    className="shrink-0 rounded-full border border-cyan-400/25 bg-cyan-400/10 px-2.5 py-1.5 text-[10px] font-black text-cyan-200"
                >
                    AI Brain
                </Link>
            </div>
            <nav className="mobile-dashboard-rail-scroll flex gap-1.5 overflow-x-auto pb-0.5">
                {primaryItems.map((item) => {
                    const isActive = activeFor(pathname, item.href);
                    return (
                        <Link
                            key={item.href}
                            to={item.href}
                            className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-black transition-colors ${
                                isActive
                                    ? 'border-cyan-300/45 bg-cyan-400/15 text-cyan-100'
                                    : 'border-white/[0.07] bg-white/[0.035] text-slate-400'
                            }`}
                        >
                            <i className={`${iconClass(item.icon)} text-[11px]`} />
                            {item.name}
                        </Link>
                    );
                })}
            </nav>
        </section>
    );
}
