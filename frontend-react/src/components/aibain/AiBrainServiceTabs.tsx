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
        <nav aria-label="AI Brain 서비스" className="hidden max-w-3xl grid-cols-2 gap-3 md:grid">
            {services.map((service) => {
                const selected = service.id === active;
                return (
                    <a
                        key={service.id}
                        href={service.href}
                        aria-current={selected ? 'page' : undefined}
                        className={`group flex min-h-24 items-center gap-4 rounded-2xl border px-5 py-4 transition-all ${
                            selected
                                ? service.activeClass
                                : 'border-white/10 bg-white/[0.035] text-gray-300 hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/[0.065]'
                        }`}
                    >
                        <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-xl ${service.iconClass}`}>
                            <i className={`fas ${service.icon} text-lg`} />
                        </span>
                        <span className="min-w-0 text-left">
                            <span className="block text-[10px] font-black tracking-[0.18em] text-gray-500">{service.eyebrow}</span>
                            <span className="mt-0.5 block text-lg font-black tracking-tight text-current">{service.title}</span>
                            <span className="mt-1 block text-xs font-medium text-gray-500">{service.description}</span>
                        </span>
                    </a>
                );
            })}
        </nav>
    );
}
