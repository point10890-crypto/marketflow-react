import { useState } from 'react';
import { Link } from 'react-router-dom';
import ClawMascot from '@/components/claw/ClawMascot';
import { InstallGuide } from '@/components/layout/InstallPrompt';
import { PublicShell, getPublicAccountAction, type PublicAccountAction } from '@/components/public/PublicShell';
import { useAuth } from '@/contexts/AuthContext';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { AIBAIN_ADDON_META, PLAN_PAYMENT_META, planToQuery, type BillingPlan } from '@/lib/billingInfo';
import { useSeo, SITE_ORIGIN, DEFAULT_OG_IMAGE } from '@/lib/seo';

/**
 * 랜딩 — 에이전트 주식 분석 자동화 + AI Brain 을 전면에 세운 전환 퍼널 입구.
 *
 * 디자인 언어: "친근하지만 전문적인" — 따뜻한 딥 톤 배경, 큰 라운드, 마스코트
 * 중심의 스토리텔링. 기계적인 mono 라벨 대신 부드러운 pill 배지를 쓰되,
 * 스케줄·채점·검증 같은 전문 구조는 그대로 보여준다.
 * 모든 플랜 CTA 는 플랜 사전선택 쿼리(planToQuery)를 실어 가입 → 플랜 → 입금
 * 흐름에 끊김 없이 연결한다. 수익 보장·투자 권유로 읽힐 표현은 쓰지 않는다.
 */

const AGENT_SCHEDULE = [
    {
        time: '04:00',
        market: '미국 시장',
        title: '미국 시장 전체 갱신',
        description: 'VIX·공포탐욕·섹터 로테이션 데이터를 수집하고 AI 매크로 브리핑과 Smart Money Top Picks 를 새로 작성해요.',
        icon: 'fa-earth-americas',
        tone: 'text-sky-300',
        chip: 'border-sky-400/25 bg-sky-400/10',
    },
    {
        time: '09:00 – 15:30',
        market: '국내 장중',
        title: 'Claw 장중 관찰 루프',
        description: '국내 장중 주도주 흐름을 초 단위로 관찰하고, 신규 진입·등급 변화·이탈을 검증해 텔레그램으로 알려드려요.',
        icon: 'fa-bolt',
        tone: 'text-[#ffab8f]',
        chip: 'border-[#ff8f6d]/25 bg-[#ff8f6d]/10',
    },
    {
        time: '14:50',
        market: '국내 마감 전',
        title: '종가베팅 V2 스크리너',
        description: '상승률 상위 종목을 뉴스·수급·공시·차트 17점 체계로 채점하고 Multi-AI 교차 검증으로 등급을 확정해요.',
        icon: 'fa-list-check',
        tone: 'text-amber-300',
        chip: 'border-amber-400/25 bg-amber-400/10',
    },
    {
        time: '16:00',
        market: '국내 마감 후',
        title: '마감 후 심화 분석',
        description: '가격·수급·VCP 신호와 리포트를 갱신하고, 당일 검출 결과를 사후 검증 대기열에 등록해요.',
        icon: 'fa-magnifying-glass-chart',
        tone: 'text-emerald-300',
        chip: 'border-emerald-400/25 bg-emerald-400/10',
    },
    {
        time: '연중무휴 · 4시간 주기',
        market: '암호화폐',
        title: '암호화폐 파이프라인',
        description: '크립토 시장은 쉬지 않으니까요. 4시간 주기로 시그널·브리핑 전체 파이프라인을 반복 실행해요.',
        icon: 'fa-coins',
        tone: 'text-violet-300',
        chip: 'border-violet-400/25 bg-violet-400/10',
    },
];

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

const AIBRAIN_CYCLE = [
    {
        phase: 'SENSE',
        title: '감지',
        icon: 'fa-satellite-dish',
        description: '시장 폭·수급·검출 이벤트와 과거 평가 결과를 한 관측 화면으로 모읍니다.',
    },
    {
        phase: 'THINK',
        title: '추론',
        icon: 'fa-brain',
        description: 'GraphRAG 근거 그래프와 레짐(RISK_ON/OFF)·조합 패턴 증거로 후보를 교차 검토합니다.',
    },
    {
        phase: 'ACT',
        title: '실행',
        icon: 'fa-bolt',
        description: '검증 게이트를 통과한 관찰 후보만 TOP 3 로 정리해 대시보드와 알림으로 전달합니다.',
    },
    {
        phase: 'LEARN',
        title: '학습',
        icon: 'fa-arrows-rotate',
        description: '검출 이후 D+1·D+5 결과를 다시 채점해 잘 맞은 패턴과 주의 패턴을 갱신합니다.',
    },
];

const AIBRAIN_FEATURES = [
    {
        icon: 'fa-crosshairs',
        title: '알파 스캐너',
        description: '전 종목을 자동 스캔해 통계 게이트를 통과한 관찰 후보만 남깁니다. 사람이 종목을 고르는 단계가 없습니다.',
    },
    {
        icon: 'fa-diagram-project',
        title: 'GraphRAG 근거 분석',
        description: '뉴스·공시·수급·테마를 근거 그래프로 연결해, 왜 이 후보가 남았는지 추적 가능한 형태로 보여줍니다.',
    },
    {
        icon: 'fa-square-poll-vertical',
        title: '성과 검증 대시보드',
        description: '적중률·평균 수익·평가 표본을 숨기지 않고 공개합니다. 검증된 픽과 실패한 픽을 같은 화면에서 확인합니다.',
    },
    {
        icon: 'fa-chart-line',
        title: '레짐 인식 · 패턴 학습',
        description: '시장 국면(RISK_ON/NEUTRAL/RISK_OFF)별로 어떤 조합이 잘 작동했는지 상호작용 맵으로 축적합니다.',
    },
];

const TRUST_PRINCIPLES = [
    { icon: 'fa-eye', title: '관찰 전용', description: '브로커 주문·정정·취소를 실행하지 않습니다. 판단과 실행은 사용자에게 남습니다.' },
    { icon: 'fa-hand', title: '불확실하면 HOLD', description: '데이터가 오래됐거나 필수 입력이 빠지면 긍정 신호보다 보류 상태를 우선합니다.' },
    { icon: 'fa-fingerprint', title: '원천과 시각 표시', description: '데이터가 언제 관찰됐고 어떤 출처를 거쳤는지 확인할 수 있게 구성합니다.' },
    { icon: 'fa-chart-column', title: '결과까지 기록', description: '과거 화면을 성과처럼 꾸미지 않고 비교 가능한 관찰만 사후 지표로 집계합니다.' },
];

const FAQS = [
    {
        question: '자동으로 주식을 주문하나요?',
        answer: '아니요. MarketFlow는 분석과 관찰을 자동화하는 서비스이며 실제 계좌 주문을 실행하지 않습니다. 판단과 실행은 항상 사용자에게 있습니다.',
    },
    {
        question: '에이전트는 정확히 무엇을 자동화하나요?',
        answer: '데이터 수집(US 04:00, KR 장중·마감, Crypto 4시간 주기), 후보 스크리닝과 채점, Multi-AI 교차 검증, 변화 검출과 알림, 검출 이후 성과 기록까지의 분석 파이프라인 전체를 자동화합니다.',
    },
    {
        question: 'AI Brain은 기본 Pro와 무엇이 다른가요?',
        answer: 'Pro는 자동화된 대시보드와 시그널 열람이 중심입니다. AI Brain은 그 위에서 알파 스캐너가 후보를 직접 발굴하고, GraphRAG 근거 분석·TOP 3·성과 검증·레짐 학습을 제공하는 별도 30일 갱신 애드온입니다.',
    },
    {
        question: '가입하면 바로 무료로 대시보드를 쓸 수 있나요?',
        answer: '계정 생성은 무료입니다. 전체 대시보드 이용은 플랜을 선택하고 입금 확인과 관리자 승인이 끝난 뒤 시작됩니다.',
    },
    {
        question: '표시된 등급이나 과거 결과가 수익을 보장하나요?',
        answer: '아니요. 등급과 성과 지표는 관찰 우선순위와 사후 검증을 위한 분석 결과이며 투자 권유가 아닙니다. 과거 결과도 미래 수익을 보장하지 않습니다.',
    },
];

const PRICING_PLANS: BillingPlan[] = ['pro', 'pro_aibain', 'premium', 'premium_aibain'];

function AccountActionLink({ action, className = '' }: { action: PublicAccountAction; className?: string }) {
    if (action.disabled) {
        return (
            <span
                aria-disabled="true"
                className={`inline-flex min-h-[50px] items-center justify-center rounded-full border border-white/10 bg-white/[0.04] px-7 text-sm font-black text-gray-500 ${className}`}
            >
                {action.label}
            </span>
        );
    }
    return (
        <Link
            to={action.to}
            className={`inline-flex min-h-[50px] items-center justify-center rounded-full bg-gradient-to-r from-[#ff8a5c] to-[#ff6b57] px-7 text-sm font-black text-[#241008] shadow-[0_10px_30px_rgba(255,122,90,0.28)] transition-all hover:-translate-y-0.5 hover:shadow-[0_14px_36px_rgba(255,122,90,0.36)] ${className}`}
        >
            {action.label}<i className="fas fa-arrow-right ml-2 text-[11px]" aria-hidden />
        </Link>
    );
}

/** 부드러운 pill 배지 + 헤딩 — mono 라벨을 대체하는 친근한 섹션 머리 */
function SectionHeading({ badgeIcon, badge, title, description, tone = 'coral' }: {
    badgeIcon: string; badge: string; title: string; description: string; tone?: 'coral' | 'cyan';
}) {
    const pill = tone === 'cyan'
        ? 'border-cyan-400/25 bg-cyan-400/10 text-cyan-200'
        : 'border-[#ff8f6d]/25 bg-[#ff8f6d]/10 text-[#ffab8f]';
    return (
        <div className="mx-auto mb-9 max-w-2xl text-center sm:mb-12">
            <span className={`inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-[12px] font-bold ${pill}`}>
                <i className={`fas ${badgeIcon} text-[11px]`} aria-hidden />{badge}
            </span>
            <h2 className="mt-4 break-keep text-2xl font-black leading-snug tracking-tight text-white sm:text-4xl">{title}</h2>
            <p className="mt-3 break-keep text-sm leading-relaxed text-gray-400 sm:text-base">{description}</p>
        </div>
    );
}

/** 히어로 우측 — 에이전트 자동화 콘솔 데모 (화면 예시). 마스코트 말풍선으로 친근하게. */
function AgentConsolePreview() {
    return (
        <div className="relative mx-auto w-full max-w-[540px]">
            {/* 마스코트 + 말풍선 */}
            <div className="relative z-10 mb-[-14px] flex items-end gap-3 pl-4">
                <ClawMascot state="running" size={64} title="분석 중인 에이전트" />
                <div className="relative mb-5 rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.06] px-4 py-2.5 text-[12.5px] font-semibold text-gray-200 backdrop-blur-sm">
                    지금도 시장을 지켜보고 있어요!
                </div>
            </div>

            <div className="relative rounded-[28px] border border-[#ff8f6d]/20 bg-[#171219] p-3 shadow-[0_32px_90px_rgba(255,122,90,0.14)] sm:p-4">
                <div className="pointer-events-none absolute inset-0 rounded-[28px] bg-[radial-gradient(70%_70%_at_50%_0%,rgba(255,140,100,.10),transparent_70%)]" aria-hidden />
                <div className="relative rounded-3xl border border-white/[0.07] bg-[#100d13]/95 p-4 sm:p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
                        <div className="text-sm font-black text-white">에이전트 분석 콘솔</div>
                        <span className="rounded-full border border-amber-400/25 bg-amber-400/10 px-2.5 py-1 text-[10px] font-bold text-amber-200">
                            화면 예시 · 실제 종목 아님
                        </span>
                    </div>

                    <div className="mt-4 grid grid-cols-3 gap-2">
                        {[
                            ['파이프라인', '작동 중', 'text-emerald-300', 'fa-circle-play'],
                            ['AI Brain', '학습 중', 'text-cyan-300', 'fa-brain'],
                            ['자동 주문', '없음', 'text-gray-300', 'fa-hand'],
                        ].map(([label, value, toneCls, icon]) => (
                            <div key={label} className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3 text-center">
                                <i className={`fas ${icon} text-[11px] ${toneCls}`} aria-hidden />
                                <div className={`mt-1 text-[12px] font-black ${toneCls}`}>{value}</div>
                                <div className="mt-0.5 text-[9.5px] text-gray-600">{label}</div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-3 space-y-2">
                        {[
                            { time: '04:00', label: 'AI 매크로 브리핑 발행 완료', icon: 'fa-earth-americas', toneCls: 'text-sky-300' },
                            { time: '09:12', label: '관찰 후보 A · 등급 상승 감지', icon: 'fa-arrow-trend-up', toneCls: 'text-[#ffab8f]' },
                            { time: '14:50', label: '종가베팅 17점 채점 완료', icon: 'fa-list-check', toneCls: 'text-amber-300' },
                            { time: '15:40', label: 'AI Brain TOP 3 갱신', icon: 'fa-brain', toneCls: 'text-cyan-300' },
                        ].map((event) => (
                            <div key={event.time} className="flex items-center gap-3 rounded-2xl border border-white/[0.05] bg-black/20 px-3.5 py-3">
                                <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-white/[0.05] ${event.toneCls}`}>
                                    <i className={`fas ${event.icon} text-[11px]`} aria-hidden />
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-gray-300">{event.label}</span>
                                <span className="font-mono text-[10px] tabular-nums text-gray-600">{event.time}</span>
                            </div>
                        ))}
                    </div>

                    <p className="mt-3 text-center text-[10px] text-gray-600">모든 기록에 원천 시각과 근거가 함께 남아요</p>
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

    useSeo({
        title: 'MarketFlow — 에이전트 주식 분석 자동화 · AI Brain',
        description:
            '잠들지 않는 AI 에이전트가 한국·미국·암호화폐 시장을 시장 일정에 맞춰 자동 분석합니다. 장중 주도주 관찰, 종가베팅 스크리너, 그리고 스스로 학습하는 AI Brain — 근거와 사후 검증까지 한 대시보드에서.',
        path: '/',
        // WebSite 스키마는 index.html 의 정적 JSON-LD 가 이미 제공 — 여기선 나머지만.
        jsonLd: [
            {
                '@context': 'https://schema.org',
                '@type': 'Organization',
                name: 'MarketFlow',
                url: SITE_ORIGIN,
                logo: DEFAULT_OG_IMAGE,
                email: 'point10890@gmail.com',
            },
            {
                '@context': 'https://schema.org',
                '@type': 'FAQPage',
                mainEntity: FAQS.map((f) => ({
                    '@type': 'Question',
                    name: f.question,
                    acceptedAnswer: { '@type': 'Answer', text: f.answer },
                })),
            },
        ],
    });

    const handleInstall = async () => {
        const result = await install();
        if (result === 'manual') setShowGuide(true);
    };

    // 플랜 카드 → 퍼널 진입 링크. 비로그인은 가입부터, 로그인 상태는 플랜 선택으로 직행.
    // PlanSelectPage 가 활성/만료/애드온 분기를 모두 처리하므로 여기선 사전선택만 전달한다.
    const planHref = (plan: BillingPlan) => {
        const q = planToQuery(plan);
        if (!user || user.status === 'unknown') return `/signup?${q}`;
        if (user.role === 'admin') return '/admin';
        if (user.status === 'expired' || user.is_pro_expired) return `/plan-select?resubscribe=1&from=expired&${q}`;
        return `/plan-select?change=1&${q}`;
    };
    const aiBrainHref = planHref('pro_aibain');
    // 활성 구독 회원에게는 대시보드 링크 대신 플랜 변경/애드온 추가 CTA 를 보여준다.
    const isActiveMember = !!user && user.role !== 'admin'
        && user.status === 'approved'
        && (user.tier === 'pro' || user.tier === 'premium')
        && !user.is_pro_expired;
    // AI Brain 애드온(40,000원/30일) 스트립 — 활성 회원은 자기 tier 에 맞는
    // 애드온 사전선택으로, 비로그인은 로그인 후 같은 경로로 이어진다.
    const addonPlanQuery = planToQuery(user?.tier === 'premium' ? 'premium_aibain' : 'pro_aibain');
    const addonHref = isActiveMember
        ? `/plan-select?change=1&${addonPlanQuery}`
        : `/login?next=${encodeURIComponent(`/plan-select?change=1&${addonPlanQuery}`)}`;
    const aibainAlreadyActive = !!user?.is_aibain_active;

    return (
        <PublicShell section="claw">
            {/* ── HERO — 따뜻한 그라디언트 위 에이전트 스토리 ─────────── */}
            <section className="relative overflow-hidden border-b border-white/[0.05]">
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_55%_at_18%_10%,rgba(255,138,100,.14),transparent_70%),radial-gradient(45%_45%_at_88%_20%,rgba(56,189,248,.08),transparent_70%)]" aria-hidden />
                <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[1.02fr_.98fr] lg:py-24">
                    <div className="max-w-2xl">
                        <span className="inline-flex items-center gap-2 rounded-full border border-[#ff8f6d]/25 bg-[#ff8f6d]/10 px-4 py-1.5 text-[12px] font-bold text-[#ffab8f]">
                            <i className="fas fa-robot text-[11px]" aria-hidden />
                            자율 분석 에이전트
                        </span>
                        <h1 className="mt-5 break-keep text-[34px] font-black leading-[1.14] tracking-[-0.03em] text-white sm:text-[56px]">
                            사람이 잠든 시간에도,
                            <span className="mt-1 block bg-gradient-to-r from-[#ff9a76] via-[#ffb47a] to-amber-300 bg-clip-text text-transparent">
                                에이전트는 시장을 분석합니다.
                            </span>
                        </h1>
                        <p className="mt-5 max-w-xl break-keep text-[15px] leading-7 text-gray-400 sm:text-lg sm:leading-8">
                            복잡한 시장 관찰은 에이전트에게 맡기세요. 새벽 미국 시장 갱신부터 장중 주도주
                            관찰, 마감 종가베팅 스크리닝까지 알아서 돌아갑니다. 그 위에서{' '}
                            <a href="#ai-brain" className="font-bold text-cyan-300 underline decoration-cyan-400/40 underline-offset-4 hover:text-cyan-200">AI Brain</a>이
                            결과를 다시 학습해 다음 관찰을 더 정확하게 만들어요.
                        </p>

                        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                            <AccountActionLink action={action} className="w-full sm:w-auto" />
                            <a
                                href="#ai-brain"
                                className="inline-flex min-h-[50px] w-full items-center justify-center rounded-full border border-cyan-400/25 bg-cyan-400/[0.07] px-7 text-sm font-bold text-cyan-200 transition-colors hover:bg-cyan-400/[0.14] sm:w-auto"
                            >
                                <i className="fas fa-brain mr-2 text-[12px]" aria-hidden />AI Brain 알아보기
                            </a>
                        </div>
                        <p className="mt-3 text-[11px] leading-relaxed text-gray-600">{action.hint}</p>

                        <ul className="mt-8 flex max-w-xl flex-wrap gap-2 text-[12px] font-semibold text-gray-300">
                            {['시장 일정 자동 분석', '장중 실시간 관찰', '자율 학습 사이클', '관찰 전용 · 주문 없음'].map((item) => (
                                <li key={item} className="flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-3.5 py-2">
                                    <i className="fas fa-check text-[9px] text-emerald-300" aria-hidden />{item}
                                </li>
                            ))}
                        </ul>
                    </div>
                    <AgentConsolePreview />
                </div>
            </section>

            {/* ── 자동화 스케줄 — 에이전트의 하루 ─────────────────────── */}
            <section id="automation" className="scroll-mt-20 px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-4xl">
                    <SectionHeading
                        badgeIcon="fa-clock"
                        badge="에이전트의 하루"
                        title="분석은 스케줄이 대신합니다"
                        description="사용자가 할 일은 결과와 근거를 확인하는 것뿐이에요. 수집·채점·검증·기록은 시장별 일정에 맞춰 자동으로 반복됩니다."
                    />
                    <ol className="relative space-y-3 sm:before:absolute sm:before:bottom-6 sm:before:left-[27px] sm:before:top-6 sm:before:w-px sm:before:bg-gradient-to-b sm:before:from-[#ff8f6d]/30 sm:before:via-white/10 sm:before:to-violet-400/30">
                        {AGENT_SCHEDULE.map((item) => (
                            <li key={item.title} className="relative flex gap-4 rounded-[24px] border border-white/[0.07] bg-white/[0.025] p-5 transition-colors hover:border-white/[0.14] sm:items-center sm:gap-5">
                                <span className={`relative z-10 grid h-[54px] w-[54px] shrink-0 place-items-center rounded-2xl border ${item.chip} ${item.tone}`}>
                                    <i className={`fas ${item.icon} text-lg`} aria-hidden />
                                </span>
                                <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                                        <span className={`font-mono text-[12.5px] font-black tabular-nums ${item.tone}`}>{item.time}</span>
                                        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-bold text-gray-400">{item.market}</span>
                                    </div>
                                    <h3 className="mt-1.5 text-[15px] font-black text-white">{item.title}</h3>
                                    <p className="mt-1 break-keep text-[12.5px] leading-6 text-gray-500">{item.description}</p>
                                </div>
                            </li>
                        ))}
                    </ol>
                </div>
            </section>

            {/* ── HOW IT WORKS ────────────────────────────────────────── */}
            <section id="how-it-works" className="scroll-mt-20 border-y border-white/[0.05] bg-white/[0.015] px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        badgeIcon="fa-magnifying-glass"
                        badge="이렇게 일해요"
                        title="점수보다 먼저, 관찰의 품질을 확인합니다"
                        description="단순히 종목 목록을 만드는 것이 아니라 무엇을 봤고 무엇을 모르는지 남기는 흐름입니다."
                    />
                    <ol className="grid gap-3 md:grid-cols-5">
                        {OBSERVATION_STEPS.map((item) => (
                            <li key={item.step} className="rounded-[22px] border border-white/[0.07] bg-[#14111a] p-5 transition-colors hover:border-[#ff8f6d]/25">
                                <div className="flex items-center justify-between">
                                    <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[#ff8f6d]/10 text-[#ffab8f]">
                                        <i className={`fas ${item.icon} text-sm`} aria-hidden />
                                    </span>
                                    <span className="text-[11px] font-black text-gray-700">{item.step}</span>
                                </div>
                                <h3 className="mt-4 text-sm font-black text-white">{item.title}</h3>
                                <p className="mt-2 break-keep text-[12px] leading-6 text-gray-500">{item.description}</p>
                            </li>
                        ))}
                    </ol>
                </div>
            </section>

            {/* ── AI BRAIN — 플래그십 ─────────────────────────────────── */}
            <section id="ai-brain" className="relative scroll-mt-20 overflow-hidden px-4 py-16 sm:px-6 sm:py-28">
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_0%,rgba(34,211,238,.09),transparent_70%),radial-gradient(40%_40%_at_15%_80%,rgba(167,139,250,.06),transparent_70%)]" aria-hidden />
                <div className="relative mx-auto max-w-6xl">
                    <div className="mx-auto mb-10 max-w-2xl text-center sm:mb-14">
                        <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/25 bg-cyan-400/10 px-4 py-1.5 text-[12px] font-bold text-cyan-200">
                            <i className="fas fa-brain text-[11px]" aria-hidden />
                            AI Brain — 대표 기능
                        </span>
                        <h2 className="mt-4 break-keep text-3xl font-black leading-snug tracking-tight text-white sm:text-5xl">
                            스스로 배우는 분석 두뇌,
                            <span className="block bg-gradient-to-r from-cyan-300 via-sky-300 to-violet-300 bg-clip-text text-transparent">AI Brain</span>
                        </h2>
                        <p className="mt-4 break-keep text-sm leading-7 text-gray-400 sm:text-base">
                            대부분의 분석 도구는 신호를 내보내는 데서 끝나요. AI Brain은 자신이 낸 관찰 후보의
                            이후 결과를 다시 채점하고, 잘 맞은 패턴과 주의 패턴을 학습해 다음 분석에 반영하는
                            <strong className="text-white"> 자율 학습 사이클</strong>로 돌아갑니다.
                        </p>
                    </div>

                    {/* Sense → Think → Act → Learn */}
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        {AIBRAIN_CYCLE.map((item, index) => (
                            <article key={item.phase} className="relative rounded-[24px] border border-cyan-400/15 bg-gradient-to-b from-cyan-400/[0.05] to-transparent p-5 transition-colors hover:border-cyan-400/35">
                                {index < AIBRAIN_CYCLE.length - 1 && (
                                    <i className="fas fa-arrow-right-long absolute -right-2.5 top-9 z-10 hidden text-[11px] text-cyan-400/50 lg:block" aria-hidden />
                                )}
                                <div className="flex items-center justify-between">
                                    <span className="grid h-11 w-11 place-items-center rounded-2xl border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
                                        <i className={`fas ${item.icon}`} aria-hidden />
                                    </span>
                                    <span className="text-[10px] font-black tracking-[0.15em] text-cyan-400/60">{item.phase}</span>
                                </div>
                                <h3 className="mt-4 font-black text-white">{item.title}</h3>
                                <p className="mt-2 break-keep text-[12px] leading-6 text-gray-500">{item.description}</p>
                            </article>
                        ))}
                    </div>

                    {/* 기능 그리드 */}
                    <div className="mt-8 grid gap-4 sm:grid-cols-2">
                        {AIBRAIN_FEATURES.map((item) => (
                            <article key={item.title} className="flex items-start gap-4 rounded-[24px] border border-white/[0.07] bg-[#101420] p-5 transition-colors hover:border-cyan-400/25 sm:p-6">
                                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-cyan-400/10 text-cyan-300">
                                    <i className={`fas ${item.icon}`} aria-hidden />
                                </span>
                                <div>
                                    <h3 className="text-base font-black text-white">{item.title}</h3>
                                    <p className="mt-1.5 break-keep text-[13px] leading-6 text-gray-400">{item.description}</p>
                                </div>
                            </article>
                        ))}
                    </div>

                    <div className="mt-10 flex flex-col items-center gap-3 text-center">
                        <Link
                            to={aiBrainHref}
                            className="inline-flex min-h-[52px] items-center justify-center rounded-full bg-gradient-to-r from-cyan-400 to-sky-500 px-9 text-sm font-black text-[#06222c] shadow-[0_10px_30px_rgba(34,211,238,0.25)] transition-all hover:-translate-y-0.5 hover:shadow-[0_14px_36px_rgba(34,211,238,0.35)]"
                        >
                            <i className="fas fa-brain mr-2 text-[12px]" aria-hidden />
                            AI Brain 포함 플랜으로 시작하기
                        </Link>
                        <p className="max-w-md break-keep text-[11px] leading-5 text-gray-600">
                            AI Brain은 Pro / Ultra Pro 베이스 플랜에 추가하는 30일 갱신 애드온입니다.
                            성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다.
                        </p>
                    </div>
                </div>
            </section>

            {/* ── TRUST ───────────────────────────────────────────────── */}
            <section className="border-y border-white/[0.05] bg-white/[0.015] px-4 py-16 sm:px-6 sm:py-20">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        badgeIcon="fa-handshake"
                        badge="지키는 약속"
                        title="더 많이 말하는 것보다 잘못 말하지 않는 것"
                        description="자동화가 빨라질수록 원칙이 중요하니까요. MarketFlow가 지키는 네 가지 약속입니다."
                    />
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        {TRUST_PRINCIPLES.map((item) => (
                            <article key={item.title} className="rounded-[22px] border border-white/[0.07] bg-[#14111a] p-5 transition-colors hover:border-emerald-400/25">
                                <span className="grid h-11 w-11 place-items-center rounded-2xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
                                    <i className={`fas ${item.icon}`} aria-hidden />
                                </span>
                                <h3 className="mt-4 font-black text-white">{item.title}</h3>
                                <p className="mt-2 break-keep text-[12px] leading-6 text-gray-500">{item.description}</p>
                            </article>
                        ))}
                    </div>
                </div>
            </section>

            {/* ── PRICING — 퍼널 직결 ─────────────────────────────────── */}
            <section id="pricing" className="scroll-mt-20 px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-6xl">
                    <SectionHeading
                        badgeIcon="fa-tags"
                        badge="요금 안내"
                        title="플랜을 고르면 바로 시작 단계로 이어져요"
                        description="카드를 선택하면 계정 생성 → 플랜 확인 → 입금 안내 → 승인 대기까지 한 흐름으로 연결됩니다."
                    />
                    <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
                        {PRICING_PLANS.map((plan) => {
                            const meta = PLAN_PAYMENT_META[plan];
                            const highlighted = plan === 'pro_aibain';
                            return (
                                <Link
                                    key={plan}
                                    to={planHref(plan)}
                                    className={`group relative flex flex-col rounded-[26px] border p-5 pt-6 transition-all hover:-translate-y-1 ${
                                        meta.includesAibain
                                            ? 'border-cyan-400/25 bg-gradient-to-b from-cyan-400/[0.06] to-transparent hover:border-cyan-300/50 hover:shadow-[0_18px_44px_rgba(34,211,238,0.14)]'
                                            : 'border-white/[0.08] bg-[#14111a] hover:border-white/20 hover:shadow-[0_18px_44px_rgba(0,0,0,0.4)]'
                                    } ${highlighted ? 'ring-1 ring-cyan-400/40' : ''}`}
                                >
                                    {highlighted && (
                                        <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-cyan-300/40 bg-[#0c141f] px-3 py-1 text-[10px] font-black text-cyan-200">
                                            <i className="fas fa-star mr-1 text-[8px]" aria-hidden />가장 많이 선택해요
                                        </span>
                                    )}
                                    <div className={`text-[11px] font-bold ${meta.includesAibain ? 'text-cyan-300' : 'text-[#ffab8f]'}`}>
                                        {meta.includesAibain ? 'AI Brain 포함' : '베이스 플랜'}
                                    </div>
                                    <h3 className="mt-1.5 text-base font-black text-white">{meta.label}</h3>
                                    <div className="mt-3 text-2xl font-black tracking-tight text-white">{meta.amount}</div>
                                    <p className="mt-1 min-h-[36px] text-[11px] leading-5 text-gray-500">{meta.period}</p>
                                    {meta.baseAmount && meta.aibainAmount && (
                                        <p className="mt-3 border-t border-white/[0.06] pt-3 text-[10px] leading-5 text-gray-600">
                                            {meta.baseAmount}<br />+ {meta.aibainAmount}
                                        </p>
                                    )}
                                    <span className={`mt-4 inline-flex min-h-[42px] items-center justify-center rounded-full text-[12px] font-black transition-colors ${
                                        meta.includesAibain
                                            ? 'bg-cyan-400/15 text-cyan-100 group-hover:bg-cyan-400/25'
                                            : 'bg-white/[0.06] text-gray-200 group-hover:bg-white/[0.12]'
                                    }`}>
                                        {meta.label}로 시작<i className="fas fa-arrow-right ml-1.5 text-[10px]" aria-hidden />
                                    </span>
                                </Link>
                            );
                        })}
                    </div>
                    {/* AI Brain 애드온 단독 요금 — 기존 구독자용 40,000원/30일 */}
                    <div className="mt-4 flex flex-col gap-4 rounded-[26px] border border-cyan-400/20 bg-gradient-to-r from-cyan-400/[0.06] via-transparent to-transparent p-5 sm:flex-row sm:items-center sm:p-6">
                        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-cyan-400/10 text-cyan-300">
                            <i className="fas fa-puzzle-piece" aria-hidden />
                        </span>
                        <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                <h3 className="text-[15px] font-black text-white">{AIBAIN_ADDON_META.label}</h3>
                                <span className="text-lg font-black text-cyan-200">{AIBAIN_ADDON_META.amount}</span>
                                <span className="text-[11px] font-bold text-gray-500">/ {AIBAIN_ADDON_META.period}</span>
                            </div>
                            <p className="mt-1 break-keep text-[12.5px] leading-6 text-gray-400">
                                이미 Pro / Ultra Pro 를 이용 중이라면 베이스 플랜은 그대로 두고
                                AI Brain 만 40,000원에 추가할 수 있어요. 만료되면 베이스 플랜으로 자동 회귀합니다.
                            </p>
                        </div>
                        {aibainAlreadyActive ? (
                            <span className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-full border border-cyan-400/25 bg-cyan-400/10 px-6 text-[12px] font-black text-cyan-200">
                                <i className="fas fa-check mr-1.5 text-[10px]" aria-hidden />이용 중
                            </span>
                        ) : (
                            <Link
                                to={addonHref}
                                className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-full bg-cyan-400/15 px-6 text-[12px] font-black text-cyan-100 transition-colors hover:bg-cyan-400/25"
                            >
                                {isActiveMember ? 'AI Brain 추가하기' : '로그인 후 추가하기'}
                                <i className="fas fa-arrow-right ml-1.5 text-[10px]" aria-hidden />
                            </Link>
                        )}
                    </div>

                    <div className="mt-8 flex flex-col items-center gap-3 text-center">
                        {isActiveMember && (
                            <Link
                                to="/plan-select?change=1"
                                className="inline-flex min-h-[50px] items-center justify-center rounded-full bg-gradient-to-r from-[#ff8a5c] to-[#ff6b57] px-8 text-sm font-black text-[#241008] shadow-[0_10px_30px_rgba(255,122,90,0.28)] transition-all hover:-translate-y-0.5"
                            >
                                플랜 변경 · AI Brain 추가<i className="fas fa-arrow-right ml-2 text-[11px]" aria-hidden />
                            </Link>
                        )}
                        <Link to="/pricing" className="text-[12px] font-bold text-gray-500 underline decoration-white/15 underline-offset-4 transition-colors hover:text-white">
                            기능·기간·결제 절차 자세히 보기
                        </Link>
                    </div>
                </div>
            </section>

            {/* ── FAQ ─────────────────────────────────────────────────── */}
            <section className="border-t border-white/[0.05] bg-white/[0.015] px-4 py-16 sm:px-6 sm:py-24">
                <div className="mx-auto max-w-3xl">
                    <SectionHeading
                        badgeIcon="fa-circle-question"
                        badge="자주 묻는 질문"
                        title="시작하기 전에 확인하세요"
                        description="자동화 범위와 구독 흐름을 오해 없이 안내해 드릴게요."
                    />
                    <div className="space-y-2.5">
                        {FAQS.map((item) => (
                            <details key={item.question} className="group rounded-[20px] border border-white/[0.07] bg-[#14111a] p-4 transition-colors open:border-[#ff8f6d]/30 sm:p-5">
                                <summary className="flex min-h-[32px] cursor-pointer list-none items-center gap-3 text-sm font-black text-white">
                                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#ff8f6d]/10 text-[11px] font-black text-[#ffab8f]">Q</span>
                                    <span className="flex-1 break-keep">{item.question}</span>
                                    <i className="fas fa-chevron-down shrink-0 text-[11px] text-gray-600 transition-transform group-open:rotate-180" aria-hidden />
                                </summary>
                                <p className="mt-3 border-t border-white/[0.05] pt-3 break-keep pl-10 text-[13px] leading-6 text-gray-400">{item.answer}</p>
                            </details>
                        ))}
                    </div>
                </div>
            </section>

            {!isInstalled && canInstall && (
                <section className="px-4 pb-8 pt-8 sm:px-6">
                    <div className="mx-auto flex max-w-3xl flex-col items-start justify-between gap-4 rounded-[24px] border border-white/[0.07] bg-white/[0.025] p-5 sm:flex-row sm:items-center sm:p-6">
                        <div>
                            <h2 className="text-base font-black text-white">홈 화면에서 더 빠르게 열기</h2>
                            <p className="mt-1 text-[12px] leading-5 text-gray-500">지원되는 브라우저에서 MarketFlow를 홈 화면 앱으로 추가할 수 있어요.</p>
                        </div>
                        <button
                            type="button"
                            onClick={handleInstall}
                            className="inline-flex min-h-[44px] shrink-0 items-center rounded-full border border-white/10 bg-white/[0.05] px-5 text-[12px] font-bold text-gray-200 transition-colors hover:bg-white/[0.09]"
                        >
                            <i className="fas fa-download mr-2 text-[10px]" aria-hidden />앱으로 추가
                        </button>
                    </div>
                </section>
            )}

            {/* ── FINAL CTA ───────────────────────────────────────────── */}
            <section className="px-4 pb-8 pt-10 sm:px-6 sm:pt-16">
                <div className="relative mx-auto max-w-5xl overflow-hidden rounded-[32px] border border-[#ff8f6d]/20 bg-gradient-to-b from-[#1c1420] to-[#131017] p-8 text-center sm:p-12">
                    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_50%_0%,rgba(255,140,100,.10),transparent_70%)]" aria-hidden />
                    <div className="relative">
                        <ClawMascot state="idle" size={84} className="mx-auto" title="기다리는 에이전트" />
                        <h2 className="mt-4 break-keep text-2xl font-black tracking-tight text-white sm:text-4xl">
                            분석은 에이전트에게, 판단은 당신에게
                        </h2>
                        <p className="mx-auto mt-3 max-w-2xl break-keep text-sm leading-7 text-gray-400">
                            계정을 만들고 플랜을 선택하면 입금 안내와 승인 절차가 이어져요.
                            승인 완료 즉시 자동화 대시보드와 AI Brain(선택 시)이 열립니다.
                        </p>
                        <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
                            <AccountActionLink action={action} className="w-full sm:w-auto" />
                            <Link
                                to="/community"
                                className="inline-flex min-h-[50px] w-full items-center justify-center rounded-full border border-white/10 bg-white/[0.04] px-7 text-sm font-bold text-gray-200 transition-colors hover:bg-white/[0.08] sm:w-auto"
                            >
                                공개 분석 먼저 보기
                            </Link>
                        </div>
                    </div>
                </div>
            </section>

            {showGuide && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}
        </PublicShell>
    );
}
