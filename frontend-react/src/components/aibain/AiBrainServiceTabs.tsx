type AiBrainService = 'scanner' | 'goodrich' | 'decision';

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
];

export default function AiBrainServiceTabs({ active }: AiBrainServiceTabsProps) {
    return (
        <nav aria-label="AI Brain 서비스" className="grid w-full grid-cols-3 gap-2 sm:gap-3 md:max-w-5xl">
            {services.map((service) => {
                const selected = service.id === active;
                return (
                    <a
                        key={service.id}
                        href={service.href}
                        aria-current={selected ? 'page' : undefined}
                        className={`group flex min-h-[76px] flex-col justify-center items-center gap-1.5 rounded-xl border px-2 py-2.5 transition-colors sm:flex-row sm:justify-start sm:min-h-24 sm:gap-3 sm:px-4 sm:py-4 ${
                            selected
                                ? 'border-[#365372] bg-[#1b2c40] text-[#acd3ff]'
                                : 'border-[#30363f] bg-[#15191e] text-gray-300 hover:border-[#526a83] hover:bg-[#1d232b]'
                        }`}
                    >
                        <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg sm:h-10 sm:w-10 ${service.iconClass}`}>
                            <i className={`fas ${service.icon} text-base sm:text-lg`} />
                        </span>
                        <span className="min-w-0 text-center sm:text-left">
                            <span className="hidden sm:block text-[11px] font-medium tracking-[0.06em] text-gray-400">{service.eyebrow}</span>
                            <span className="mt-0.5 block text-xs font-semibold tracking-tight text-current sm:text-base">{service.title}</span>
                            <span className="mt-0.5 hidden sm:block font-medium text-gray-400 sm:mt-1 sm:text-xs">{service.description}</span>
                        </span>
                    </a>
                );
            })}
        </nav>
    );
}
