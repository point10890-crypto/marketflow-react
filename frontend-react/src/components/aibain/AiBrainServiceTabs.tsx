type AiBrainService = 'scanner' | 'goodrich';

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
        activeClass: 'border-cyan-300/60 bg-cyan-500/15 text-cyan-100 shadow-[0_0_30px_rgba(34,211,238,0.12)]',
        iconClass: 'bg-cyan-400/15 text-cyan-300',
    },
    {
        id: 'goodrich' as const,
        href: '/dashboard/ai-bain/goodrich',
        icon: 'fa-ranking-star',
        eyebrow: 'KIS + OPENAI',
        title: 'Goodrich TOP 3',
        description: 'AI 펀드매니저 실전 리서치',
        activeClass: 'border-emerald-300/60 bg-emerald-500/15 text-emerald-100 shadow-[0_0_30px_rgba(52,211,153,0.12)]',
        iconClass: 'bg-emerald-400/15 text-emerald-300',
    },
];

export default function AiBrainServiceTabs({ active }: AiBrainServiceTabsProps) {
    return (
        <nav aria-label="AI Brain 서비스" className="grid w-full grid-cols-1 gap-2.5 sm:gap-3 md:max-w-3xl md:grid-cols-2">
            {services.map((service) => {
                const selected = service.id === active;
                return (
                    <a
                        key={service.id}
                        href={service.href}
                        aria-current={selected ? 'page' : undefined}
                        className={`group flex min-h-20 items-center gap-3.5 rounded-2xl border px-4 py-3.5 transition-all sm:min-h-24 sm:gap-4 sm:px-5 sm:py-4 ${
                            selected
                                ? service.activeClass
                                : 'border-white/10 bg-white/[0.035] text-gray-300 hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/[0.065]'
                        }`}
                    >
                        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl sm:h-12 sm:w-12 ${service.iconClass}`}>
                            <i className={`fas ${service.icon} text-base sm:text-lg`} />
                        </span>
                        <span className="min-w-0 text-left">
                            <span className="block text-[10px] font-black tracking-[0.18em] text-gray-500">{service.eyebrow}</span>
                            <span className="mt-0.5 block text-base font-black tracking-tight text-current sm:text-lg">{service.title}</span>
                            <span className="mt-0.5 block text-[11px] font-medium text-gray-500 sm:mt-1 sm:text-xs">{service.description}</span>
                        </span>
                    </a>
                );
            })}
        </nav>
    );
}
