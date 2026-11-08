import { useId } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { canAccessKongming } from '@/lib/auth';
import kongmingBanner from '@/assets/kongming-banner.webp';
import './AiBrainServiceTabs.css';

type AiBrainService = 'scanner' | 'goodrich' | 'decision' | 'chart-predict' | 'kongming';

interface AiBrainServiceTabsProps {
    active: AiBrainService;
}

const services = [
    {
        id: 'scanner' as const,
        href: '/dashboard/ai-bain',
        icon: 'fa-satellite-dish',
        eyebrow: 'MIROFISH',
        title: '알파 스캐너',
        description: 'GraphRAG 검출·검증 대시보드',
        iconClass: 'bg-cyan-400/15 text-cyan-300',
    },
    {
        id: 'goodrich' as const,
        href: '/dashboard/ai-bain/goodrich',
        icon: 'fa-ranking-star',
        eyebrow: 'KIS + OPENAI',
        title: 'Goodrich TOP 3',
        description: 'AI 펀드매니저 실전 리서치',
        iconClass: 'bg-emerald-400/15 text-emerald-300',
    },
    {
        id: 'decision' as const,
        href: '/dashboard/ai-bain/decision',
        icon: 'fa-scale-balanced',
        eyebrow: '근거 대조',
        title: '종목 판단',
        description: '독립 근거 7종 합의·이견 비교',
        iconClass: 'bg-teal-400/15 text-teal-300',
    },
    {
        id: 'chart-predict' as const,
        href: '/dashboard/ai-bain/chart-predict?code=003690',
        icon: 'fa-chart-line',
        eyebrow: '과거 사례 · SHADOW',
        title: '차트 유사 사례',
        description: '닮은 과거 구간의 이후 결과',
        iconClass: 'bg-sky-400/15 text-sky-300',
    },
    {
        id: 'kongming' as const,
        href: '/dashboard/ai-bain/catalyst-validation',
        icon: 'fa-newspaper',
        eyebrow: '제갈공명',
        title: '뉴스·재료 검증',
        description: '기사와 공식 근거 대조',
        iconClass: 'bg-amber-400/15 text-amber-300',
    },
];

export default function AiBrainServiceTabs({ active }: AiBrainServiceTabsProps) {
    const { user } = useAuth();
    const showKongming = canAccessKongming(user);
    const availableServices = showKongming ? services : services.filter(service => service.id !== 'kongming');
    const titleId = useId();
    const Title = active === 'kongming' ? 'h1' : 'h2';

    return (
        <section aria-labelledby={titleId} className="ai-brain-menu relative isolate w-full overflow-hidden rounded-2xl border border-[#365372] bg-[#0a1420] p-3 sm:p-5">
            <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
                <img src={kongmingBanner} alt="" className="h-full w-full object-cover object-[65%_top] sm:object-[center_20%]" />
                <div className="absolute inset-0 bg-gradient-to-r from-[#07121e]/90 via-[#07121e]/35 to-transparent" />
                <div className="absolute inset-0 bg-gradient-to-t from-[#07121e]/95 via-[#07121e]/20 to-transparent" />
            </div>
            <header className="flex min-h-28 flex-col justify-center px-2 pb-3 sm:min-h-36 sm:px-3 sm:pb-5">
                <p className="text-[11px] font-semibold tracking-[0.16em] text-sky-200 sm:text-xs">AI BRAIN</p>
                <Title id={titleId} className="mt-1 text-2xl font-bold tracking-tight text-white sm:text-4xl">제갈공명</Title>
                <p className="mt-2 text-xs text-slate-200">분석 메뉴를 선택하세요</p>
            </header>
            <nav aria-label="AI Brain 서비스" className={`ai-brain-menu__grid grid w-full gap-2 sm:gap-3 ${showKongming ? 'ai-brain-menu__grid--full' : ''}`} >
            {availableServices.map((service) => {
                const selected = service.id === active;
                return (
                    <a
                        key={service.id}
                        href={service.href}
                        aria-current={selected ? 'page' : undefined}
                        className={`group flex min-h-[76px] min-w-0 flex-col items-center justify-center gap-1.5 rounded-xl border px-2 py-2.5 transition-colors
                            sm:min-h-24 sm:gap-2 sm:px-3 sm:py-3 ${service.id === 'kongming' ? 'ai-brain-menu__last' : ''} ${
                            selected
                                ? 'border-[#80bbde] bg-[#19344b]/95 text-[#c8eaff]'
                                : 'border-[#52758d]/60 bg-[#101f2d]/90 text-slate-100 hover:border-[#8ebad5] hover:bg-[#1a3347]'
                        }`}
                    >
                        <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg sm:h-8 sm:w-8 ${service.iconClass}`}>
                            <i className={`fas ${service.icon} text-base sm:text-lg`} aria-hidden="true" />
                        </span>
                        <span className="min-w-0 text-center">
                            <span className="ai-brain-menu__detail text-[11px] font-medium tracking-[0.06em] text-slate-300">{service.eyebrow}</span>
                            <span className="mt-0.5 block text-xs font-semibold tracking-tight text-current sm:text-base">{service.title}</span>
                            <span className="ai-brain-menu__detail mt-1 text-xs font-medium text-slate-300">{service.description}</span>
                        </span>
                    </a>
                );
            })}
            </nav>
        </section>
    );
}
