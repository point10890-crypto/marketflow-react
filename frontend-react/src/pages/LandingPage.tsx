import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import ClawMascot from '@/components/claw/ClawMascot';
import { InstallGuide } from '@/components/layout/InstallPrompt';
import { PublicShell, getPublicAccountAction, type PublicAccountAction } from '@/components/public/PublicShell';
import { useAuth } from '@/contexts/AuthContext';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { PLAN_PAYMENT_META, type BillingPlan } from '@/lib/billingInfo';

const OBSERVATION_STEPS = [
    {
        step: '01',
        icon: 'fa-satellite-dish',
        title: '시장 관찰',
        description: '시장별 일정과 원천 주기에 맞춰 가격·거래량·수급·분석 데이터를 수집합니다.',
    },
    {
        step: '02',
        icon: 'fa-shield-halved',
        title: '품질 확인',
        description: '기준 시각과 누락 입력을 먼저 검사하고, 신뢰할 수 없으면 새 판단을 보류합니다.',
    },
    {
        step: '03',
        icon: 'fa-wave-square',
        title: '변화 검출',
        description: '주도주 신규 진입·등급 변화·이탈처럼 이전 관찰과 달라진 부분을 구분합니다.',
    },
    {
        step: '04',
        icon: 'fa-receipt',
        title: '근거와 함께 기록',
        description: '종목·시각·상태·발송 결과를 남겨 같은 변화를 반복해서 알리지 않습니다.',
    },
    {
        step: '05',
        icon: 'fa-clock-rotate-left',
        title: '사후 검증',
        description: '발견 당시 알 수 있었던 정보와 이후 결과를 분리해 전략을 계속 점검합니다.',
    },
];

const TRUST_PRINCIPLES = [
    {
        icon: 'fa-eye',
        title: '관찰 전용',
        description: '브로커 주문·정정·취소를 실행하지 않습니다. 판단과 실행은 사용자에게 남습니다.',
    },
    {
        icon: 'fa-hand',
        title: '불확실하면 HOLD',
        description: '데이터가 오래됐거나 필수 입력이 빠지면 긍정 신호보다 보류 상태를 우선합니다.',
    },
    {
        icon: 'fa-fingerprint',
        title: '원천과 시각 표시',
        description: '데이터가 언제 관찰됐고 어떤 출처를 거쳤는지 확인할 수 있게 구성합니다.',
    },
    {
        icon: 'fa-chart-column',
        title: '결과까지 기록',
        description: '과거 화면을 성과처럼 꾸미지 않고 비교 가능한 관찰만 사후 지표로 집계합니다.',
    },
];

const PRODUCT_AREAS = [
    {
        icon: 'fa-bolt',
        eyebrow: 'KR INTRADAY',
        title: 'Claw LIVE',
        description: '국내 장중 주도주 흐름과 등급 변화를 관찰하고 시스템 상태·원천 시각·전달 기록을 함께 보여줍니다.',
        accent: 'border-[#ff6b57]/25 bg-[#ff6b57]/[0.06] text-[#ff9b89]',
    },
    {
        icon: 'fa-layer-group',
        eyebrow: 'MARKET CONTEXT',
        title: 'KR · US · Crypto',
        description: '시장 개요, VCP, 차트 분석과 브리핑을 시장별 갱신 주기에 맞춰 한 화면에서 확인합니다.',
        accent: 'border-amber-400/20 bg-amber-400/[0.06] text-amber-300',
    },
    {
        icon: 'fa-file-shield',
        eyebrow: 'EVIDENCE FIRST',
        title: '근거와 위험 확인',
        description: '등급만 보지 않고 데이터 품질, 기준 시각, 누락 정보와 무효화 조건을 함께 읽도록 돕습니다.',
        accent: 'border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300',
    },
    {
        icon: 'fa-brain',
        eyebrow: 'OPTIONAL ADD-ON',
        title: 'AI Brain',
        description: '알파 스캐너, GraphRAG 분석, TOP 3와 스캔 성과 화면을 제공하는 별도 30일 갱신 애드온입니다.',
        accent: 'border-cyan-400/20 bg-cyan-400/[0.06] text-cyan-300',
    },
];

const FAQS = [
    {
        question: '자동으로 주식을 주문하나요?',
        answer: '아니요. MarketFlow는 시장 관찰과 분석 정보를 제공하며 실제 계좌 주문을 실행하지 않습니다.',
    },
    {
        question: '가입하면 바로 무료로 대시보드를 쓸 수 있나요?',
        answer: '계정 생성은 무료입니다. 전체 대시보드 이용은 플랜을 선택하고 입금 확인과 관리자 승인이 끝난 뒤 시작됩니다.',
    },
    {
        question: '모든 데이터가 같은 속도로 갱신되나요?',
        answer: '아닙니다. 국내 장중 관찰, 미국 시장, 암호화폐, 일간 분석은 원천과 시장 일정에 따라 갱신 주기가 다릅니다. 화면의 기준 시각과 상태를 함께 확인해 주세요.',
    },
    {
        question: 'AI Brain은 기본 Pro에 포함되나요?',
        answer: 'AI Brain은 별도 30일 갱신 애드온입니다. Pro 또는 Ultra Pro 베이스 플랜에 추가할 수 있습니다.',
    },
    {
        question: '표시된 등급이나 과거 결과가 수익을 보장하나요?',
        answer: '아니요. 등급은 관찰 우선순위를 돕는 분석 결과이며 투자 권유가 아닙니다. 과거 결과도 미래 수익을 보장하지 않습니다.',
    },
];

const PRICING_PLANS: BillingPlan[] = ['pro', 'pro_aibain', 'premium', 'premium_aibain'];

function AccountActionLink({ action, className = '' }: { action: PublicAccountAction; className?: string }) {
    if (action.disabled) {
        return (
            <span
                aria-disabled="true"
                className={`inline-flex min-h-[48px] items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] px-6 text-sm font-black text-gray-500 ${className}`}
            >
                {action.label}
            </span>
        );
    }
    return (
        <Link
            to={action.to}
            className={`inline-flex min-h-[48px] items-center justify-center rounded-xl bg-[#ff6b57] px-6 text-sm font-black text-[#190704] transition-colors hover:bg-[#ff8a76] ${className}`}
        >
            {action.label}<i className="fas fa-arrow-right ml-2 text-[11px]" aria-hidden />
        </Link>
    );
}

function SectionHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
    return (
        <div className="mx-auto mb-8 max-w-2xl text-center sm:mb-10">
            <div className="font-mono text-[10px] font-bold uppercase tracking-[0.24em] text-[#ff8a76]">// {eyebrow}</div>
            <h2 className="mt-3 text-2xl font-black tracking-tight text-white sm:text-4xl">{title}</h2>
            <p className="mt-3 text-sm leading-relaxed text-gray-400 sm:text-base">{description}</p>
        </div>
    );
}

function ProductPreview() {
    return (
        <div className="relative mx-auto w-full max-w-[540px] rounded-3xl border border-[#ff6b57]/20 bg-[#0a0709] p-3 shadow-[0_28px_100px_rgba(255,90,60,0.12)] sm:p-5">
            <div className="pointer-events-none absolute inset-0 rounded-3xl bg-[radial-gradient(65%_80%_at_50%_0%,rgba(255,90,60,.14),transparent_72%)]" aria-hidden />
            <div className="relative rounded-2xl border border-white/[0.07] bg-[#101014]/95 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
                    <div className="flex items-center gap-2">
                        <ClawMascot state="running" size={44} title="관찰 중인 Claw" />
                        <div>
                            <div className="text-sm font-black text-white">Claw 관찰 콘솔</div>
                            <div className="font-mono text-[9px] text-gray-500">DEMONSTRATION</div>
                        </div>
                    </div>
                    <span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-2.5 py-1 text-[10px] font-bold text-amber-200">
                        화면 예시 · 실제 종목 아님
                    </span>
                </div>

                <div className="mt-4 grid grid-cols-3 gap-2">
                    {[
                        ['관찰 상태', 'OBSERVE', 'text-emerald-300'],
                        ['데이터 품질', 'CHECKED', 'text-cyan-300'],
                        ['자동 주문', 'OFF', 'text-gray-300'],
                    ].map(([label, value, tone]) => (
                        <div key={label} className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-3">
                            <div className="text-[9px] text-gray-600">{label}</div>
                            <div className={`mt-1 font-mono text-[10px] font-black sm:text-xs ${tone}`}>{value}</div>
                        </div>
                    ))}
                </div>

                <div className="mt-3 space-y-2">
                    {[
                        { time: '09:12', type: 'LEADER_UPGRADE', name: '관찰 후보 A', tone: 'text-[#ff9b89]' },
                        { time: '09:18', type: 'DATA_HOLD', name: '필수 입력 확인 중', tone: 'text-amber-300' },
                        { time: '09:26', type: 'OUTCOME_PENDING', name: '사후 관찰 예약', tone: 'text-cyan-300' },
                    ].map((event) => (
                        <div key={event.time} className="grid grid-cols-[42px_1fr] items-center gap-2 rounded-xl border border-white/[0.05] bg-black/20 p-3 sm:grid-cols-[48px_1fr_auto]">
                            <span className="font-mono text-[10px] text-gray-600">{event.time}</span>
                            <div className="min-w-0">
                                <div className={`truncate font-mono text-[10px] font-bold ${event.tone}`}>{event.type}</div>
                                <div className="mt-0.5 truncate text-[11px] text-gray-400">{event.name}</div>
                            </div>
                            <span className="hidden text-[10px] text-gray-600 sm:inline">근거 시각 기록됨</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export default function LandingPage() {
    const { user, loading } = useAuth();
    const action = getPublicAccountAction(user, loading);
    const [showGuide, setShowGuide] = useState(false);
    const { canInstall, isInstalled, isIOS, install } = usePWAInstall();

    useEffect(() => {
        document.title = 'MarketFlow Claw — 근거 중심 AI 시장 관찰';
    }, []);

    const handleInstall = async () => {
        const result = await install();
        if (result === 'manual') setShowGuide(true);
    };

    const planActionTo = user?.role === 'admin'
        ? '/admin'
        : user?.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium')
        ? '/plan-select?change=1'
        : action.to;
    const planActionLabel = user?.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium')
        ? '플랜 변경 · AI Brain 추가'
        : user
        ? action.label
        : '계정 만들고 플랜 선택';

    return (
        <PublicShell section="claw">
            <section className="relative overflow-hidden border-b border-white/[0.05]">
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(55%_55%_at_15%_15%,rgba(255,90,60,.12),transparent_75%)]" aria-hidden />
                <div className="relative mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[1.02fr_.98fr] lg:py-24">
                    <div className="max-w-2xl">
                        <div className="inline-flex items-center gap-2 rounded-full border border-[#ff6b57]/25 bg-[#ff6b57]/10 px-3 py-1.5 font-mono text-[10px] font-bold tracking-[0.15em] text-[#ff9b89]">
                            <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b57]" />
                            MARKET OBSERVATION AGENT
                        </div>
                        <h1 className="mt-5 break-keep text-[38px] font-black leading-[1.08] tracking-[-0.04em] text-white sm:text-6xl">
                            시장을 계속 관찰하고,
                            <span className="mt-1 block text-[#ff6b57]">의미 있는 변화만 검출합니다.</span>
                        </h1>
                        <p className="mt-5 max-w-xl text-[15px] leading-7 text-gray-400 sm:text-lg sm:leading-8">
                            MarketFlow Claw는 국내 장중 흐름을 반복 관찰하고 데이터 품질이 충분할 때만 변화를 기록합니다.
                            KR·US·Crypto 분석 도구와 함께 근거·위험·사후 결과를 한 대시보드에서 확인하세요.
                        </p>

                        <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:items-center">
                            <AccountActionLink action={action} className="w-full sm:w-auto" />
                            <a
                                href="#how-it-works"
                                className="inline-flex min-h-[48px] w-full items-center justify-center rounded-xl border border-white/10 bg-white/[0.035] px-6 text-sm font-bold text-gray-200 transition-colors hover:bg-white/[0.07] sm:w-auto"
                            >
                                작동 방식 보기<i className="fas fa-arrow-down ml-2 text-[11px]" aria-hidden />
                            </a>
                        </div>
                        <p className="mt-3 text-[11px] leading-relaxed text-gray-600">{action.hint}</p>

                        <ul className="mt-7 grid max-w-xl grid-cols-2 gap-2 text-[11px] text-gray-400 sm:grid-cols-4">
                            {['관찰 전용', '불확실 시 HOLD', '중복 억제', '사후 기록'].map((item) => (
                                <li key={item} className="flex items-center gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2">
                                    <i className="fas fa-check text-[9px] text-[#ff6b57]" aria-hidden />{item}
                                </li>
                            ))}
                        </ul>
                    </div>
                    <ProductPreview />
                </div>
            </section>

            <section id="how-it-works" className="scroll-mt-20 px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        eyebrow="HOW IT WORKS"
                        title="점수보다 먼저, 관찰의 품질을 확인합니다"
                        description="단순히 종목 목록을 만드는 것이 아니라 무엇을 봤고 무엇을 모르는지 남기는 흐름입니다."
                    />
                    <ol className="grid gap-3 md:grid-cols-5">
                        {OBSERVATION_STEPS.map((item, index) => (
                            <li key={item.step} className="relative rounded-2xl border border-white/[0.07] bg-[#111116] p-5">
                                {index < OBSERVATION_STEPS.length - 1 && (
                                    <i className="fas fa-chevron-right absolute -right-2.5 top-10 z-10 hidden text-[10px] text-[#ff6b57]/50 md:block" aria-hidden />
                                )}
                                <div className="flex items-center justify-between">
                                    <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#ff6b57]/10 text-[#ff8a76]">
                                        <i className={`fas ${item.icon} text-sm`} aria-hidden />
                                    </span>
                                    <span className="font-mono text-[10px] text-gray-700">{item.step}</span>
                                </div>
                                <h3 className="mt-4 text-sm font-black text-white">{item.title}</h3>
                                <p className="mt-2 text-[12px] leading-6 text-gray-500">{item.description}</p>
                            </li>
                        ))}
                    </ol>
                </div>
            </section>

            <section className="border-y border-white/[0.05] bg-white/[0.015] px-4 py-16 sm:px-6 sm:py-20">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        eyebrow="TRUST CONTRACT"
                        title="더 많이 말하는 것보다 잘못 말하지 않는 것"
                        description="MarketFlow가 사용자에게 약속하는 네 가지 운영 원칙입니다."
                    />
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        {TRUST_PRINCIPLES.map((item) => (
                            <article key={item.title} className="rounded-2xl border border-white/[0.07] bg-[#0d0d11] p-5">
                                <span className="grid h-10 w-10 place-items-center rounded-xl border border-[#ff6b57]/20 bg-[#ff6b57]/10 text-[#ff8a76]">
                                    <i className={`fas ${item.icon}`} aria-hidden />
                                </span>
                                <h3 className="mt-4 font-black text-white">{item.title}</h3>
                                <p className="mt-2 text-[12px] leading-6 text-gray-500">{item.description}</p>
                            </article>
                        ))}
                    </div>
                </div>
            </section>

            <section id="product" className="scroll-mt-20 px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        eyebrow="PRODUCT"
                        title="관찰에서 분석 확장까지"
                        description="기본 대시보드와 선택형 AI Brain 애드온의 역할을 분리해 필요한 범위만 선택합니다."
                    />
                    <div className="grid gap-4 sm:grid-cols-2">
                        {PRODUCT_AREAS.map((item) => (
                            <article key={item.title} className={`rounded-2xl border p-5 sm:p-6 ${item.accent}`}>
                                <div className="flex items-start gap-4">
                                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-black/20">
                                        <i className={`fas ${item.icon}`} aria-hidden />
                                    </span>
                                    <div>
                                        <div className="font-mono text-[9px] font-bold tracking-[0.18em] opacity-70">{item.eyebrow}</div>
                                        <h3 className="mt-1 text-lg font-black text-white">{item.title}</h3>
                                        <p className="mt-2 text-[13px] leading-6 text-gray-400">{item.description}</p>
                                    </div>
                                </div>
                            </article>
                        ))}
                    </div>

                    <div className="mt-8 grid gap-4 lg:grid-cols-2">
                        <div className="rounded-2xl border border-amber-400/20 bg-amber-400/[0.04] p-6">
                            <div className="font-mono text-[10px] font-bold tracking-[0.18em] text-amber-300">PRO</div>
                            <h3 className="mt-2 text-xl font-black text-white">시장 관찰과 분석의 기본</h3>
                            <ul className="mt-4 space-y-2 text-[13px] text-gray-400">
                                {['Claw LIVE와 국내 주도주 관찰', 'KR · US · Crypto 대시보드', 'VCP · 차트 분석 · 시장 브리핑'].map((item) => (
                                    <li key={item} className="flex gap-2"><i className="fas fa-check mt-1 text-[10px] text-amber-300" aria-hidden />{item}</li>
                                ))}
                            </ul>
                        </div>
                        <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/[0.04] p-6">
                            <div className="font-mono text-[10px] font-bold tracking-[0.18em] text-cyan-300">AI BRAIN ADD-ON</div>
                            <h3 className="mt-2 text-xl font-black text-white">근거 분석과 후보 검증 확장</h3>
                            <ul className="mt-4 space-y-2 text-[13px] text-gray-400">
                                {['AI Brain 알파 스캐너', 'GraphRAG 분석과 TOP 3', '스캔 성과·품질 확인 화면'].map((item) => (
                                    <li key={item} className="flex gap-2"><i className="fas fa-check mt-1 text-[10px] text-cyan-300" aria-hidden />{item}</li>
                                ))}
                            </ul>
                            <p className="mt-4 text-[11px] text-gray-600">베이스 플랜과 별도로 30일마다 갱신합니다.</p>
                        </div>
                    </div>
                </div>
            </section>

            <section className="border-y border-white/[0.05] bg-white/[0.015] px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        eyebrow="PRICING PREVIEW"
                        title="한 번 더 확인할 수 있는 명확한 플랜"
                        description="계정 생성 후 플랜을 선택하고 입금 정보와 기간을 다시 확인합니다. 승인은 입금 확인 후 진행됩니다."
                    />
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        {PRICING_PLANS.map((plan) => {
                            const meta = PLAN_PAYMENT_META[plan];
                            return (
                                <article key={plan} className={`rounded-2xl border p-5 ${meta.includesAibain ? 'border-cyan-400/20 bg-cyan-400/[0.035]' : 'border-white/[0.08] bg-[#101014]'}`}>
                                    <div className={`font-mono text-[9px] font-bold tracking-[0.15em] ${meta.includesAibain ? 'text-cyan-300' : 'text-[#ff8a76]'}`}>
                                        {meta.includesAibain ? 'WITH AI BRAIN' : 'BASE PLAN'}
                                    </div>
                                    <h3 className="mt-2 text-base font-black text-white">{meta.label}</h3>
                                    <div className="mt-3 text-2xl font-black tracking-tight text-white">{meta.amount}</div>
                                    <p className="mt-1 min-h-[36px] text-[11px] leading-5 text-gray-500">{meta.period}</p>
                                    {meta.baseAmount && meta.aibainAmount && (
                                        <p className="mt-3 border-t border-white/[0.06] pt-3 text-[10px] leading-5 text-gray-600">
                                            {meta.baseAmount}<br />+ {meta.aibainAmount}
                                        </p>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                    <div className="mt-7 flex flex-col items-center gap-3 text-center">
                        {!action.disabled && (
                            <Link
                                to={planActionTo}
                                className="inline-flex min-h-[48px] items-center justify-center rounded-xl bg-[#ff6b57] px-7 text-sm font-black text-[#190704] transition-colors hover:bg-[#ff8a76]"
                            >
                                {planActionLabel}<i className="fas fa-arrow-right ml-2 text-[11px]" aria-hidden />
                            </Link>
                        )}
                        <Link to="/pricing" className="text-[12px] font-bold text-gray-500 underline decoration-white/15 underline-offset-4 hover:text-white">
                            기능·기간·결제 절차 자세히 보기
                        </Link>
                    </div>
                </div>
            </section>

            <section className="px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-3xl">
                    <SectionHeading
                        eyebrow="FAQ"
                        title="시작하기 전에 확인하세요"
                        description="서비스 범위와 구독 흐름을 오해 없이 안내합니다."
                    />
                    <div className="space-y-2">
                        {FAQS.map((item) => (
                            <details key={item.question} className="group rounded-2xl border border-white/[0.07] bg-[#101014] p-4 open:border-[#ff6b57]/25 sm:p-5">
                                <summary className="flex min-h-[32px] cursor-pointer list-none items-center justify-between gap-4 text-sm font-black text-white">
                                    {item.question}
                                    <i className="fas fa-plus shrink-0 text-[11px] text-gray-600 transition-transform group-open:rotate-45" aria-hidden />
                                </summary>
                                <p className="mt-3 border-t border-white/[0.05] pt-3 text-[13px] leading-6 text-gray-400">{item.answer}</p>
                            </details>
                        ))}
                    </div>
                </div>
            </section>

            {!isInstalled && canInstall && (
                <section className="px-4 pb-8 sm:px-6">
                    <div className="mx-auto flex max-w-3xl flex-col items-start justify-between gap-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-5 sm:flex-row sm:items-center sm:p-6">
                        <div>
                            <div className="font-mono text-[9px] font-bold tracking-[0.16em] text-gray-600">OPTIONAL</div>
                            <h2 className="mt-1 text-base font-black text-white">홈 화면에서 더 빠르게 열기</h2>
                            <p className="mt-1 text-[12px] leading-5 text-gray-500">지원되는 브라우저에서 MarketFlow를 홈 화면 앱으로 추가할 수 있습니다.</p>
                        </div>
                        <button
                            type="button"
                            onClick={handleInstall}
                            className="inline-flex min-h-[44px] shrink-0 items-center rounded-xl border border-white/10 bg-white/[0.05] px-4 text-[12px] font-bold text-gray-200 hover:bg-white/[0.08]"
                        >
                            <i className="fas fa-download mr-2 text-[10px]" aria-hidden />앱으로 추가
                        </button>
                    </div>
                </section>
            )}

            <section className="px-4 pb-8 pt-10 sm:px-6 sm:pt-16">
                <div className="mx-auto max-w-5xl overflow-hidden rounded-3xl border border-[#ff6b57]/20 bg-[#0a0709] p-7 text-center sm:p-12">
                    <ClawMascot state="idle" size={72} className="mx-auto" title="기다리는 Claw" />
                    <div className="mt-3 font-mono text-[10px] font-bold tracking-[0.2em] text-[#ff8a76]">START WITH CONTEXT</div>
                    <h2 className="mt-3 text-2xl font-black tracking-tight text-white sm:text-4xl">종목보다 먼저 시장과 근거를 확인하세요</h2>
                    <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-gray-400">
                        플랜과 결제 정보를 확인한 뒤 입금하고, 승인 완료 후 대시보드 이용 기간이 시작됩니다.
                    </p>
                    <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
                        <AccountActionLink action={action} className="w-full sm:w-auto" />
                        <Link
                            to="/community"
                            className="inline-flex min-h-[48px] w-full items-center justify-center rounded-xl border border-white/10 bg-white/[0.035] px-6 text-sm font-bold text-gray-200 hover:bg-white/[0.07] sm:w-auto"
                        >
                            공개 분석 먼저 보기
                        </Link>
                    </div>
                </div>
            </section>

            {showGuide && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}
        </PublicShell>
    );
}
