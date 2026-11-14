import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ArrowRight, AudioLines, BrainCircuit, ChartCandlestick, CircleDollarSign, Globe2, ScanSearch, ShieldCheck } from 'lucide-react';
import { InstallGuide } from '@/components/layout/InstallPrompt';
import { PublicShell, getPublicAccountAction, type PublicAccountAction } from '@/components/public/PublicShell';
import { useAuth } from '@/contexts/AuthContext';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { canAccessAiBain, hasActiveBaseSubscription, isBaseSubscriptionExpired } from '@/lib/auth';
import { AIBAIN_ADDON_META, PLAN_PAYMENT_META, planToQuery, type BillingPlan } from '@/lib/billingInfo';
import { useSeo } from '@/lib/seo';
import orbitImage from '@/assets/public-market-orbit.webp';
import kongmingImage from '@/assets/kongming-banner.webp';
import './LandingPage.css';

const MARKETS = [
    { title: '국내주식', label: 'KR', icon: ChartCandlestick, description: '장중 주도주 변화, 종목별 수급과 차트' },
    { title: '미국주식', label: 'US', icon: Globe2, description: '시장 브리핑, 업종별 흐름과 ETF 자금' },
    { title: '가상자산', label: 'CRYPTO', icon: CircleDollarSign, description: '코인 시그널, 비트코인 점유율과 시장 흐름' },
] as const;

const BRAIN_FEATURES = [
    { icon: ScanSearch, title: '알파 스캐너 · Goodrich TOP 3', description: '시장과 종목을 살펴볼 후보를 좁혀, 어디부터 확인할지 정리합니다.' },
    { icon: AudioLines, title: '종목 판단 · 차트 유사 사례', description: '수급과 차트, 20거래일 매물대, 과거 유사 구간을 살펴보고 에이전트의 합의와 이견을 확인합니다.' },
    { icon: ShieldCheck, title: '제갈공명 뉴스·재료 검증', description: '급등 배경을 추적하고 기사·공시·시세를 대조해 확인된 근거와 추가 확인이 필요한 재료를 구분합니다.' },
] as const;

const SIGNUP_STEPS = [
    { title: '무료 계정 만들기', description: '회원가입을 완료하면 플랜 선택으로 이동합니다.' },
    { title: '플랜 선택', description: '요금과 포함 기능을 확인한 뒤 구독할 플랜을 선택합니다.' },
    { title: '입금 후 신청', description: '화면에 나온 계좌로 입금한 뒤 입금 확인을 신청합니다.' },
    { title: '승인 후 이용', description: '관리자 승인 후 선택한 서비스가 계정에서 열립니다.' },
];

const FAQS = [
    { question: '계정만 먼저 만들 수 있나요?', answer: '네. 가입은 무료입니다. 유료 기능은 플랜을 선택하고 구독 승인이 완료되면 열립니다.' },
    { question: '기존 Pro·Ultra Pro 회원도 AI 브레인을 추가할 수 있나요?', answer: '네. 활성 Pro·Ultra Pro 회원은 50,000원에 AI 브레인과 제갈공명을 30일 추가할 수 있습니다. AI 이용 중 Pro 서비스는 유지되고, 보존된 Pro 잔여기간은 AI 이용 종료 후 다시 시작됩니다.' },
    { question: '에이전트가 주문도 실행하나요?', answer: 'BitMan은 시장 관찰과 분석을 자동화합니다. 매매 여부와 주문은 투자자가 결정합니다.' },
];

const AVAILABLE_PLANS = ['pro', 'pro_aibain', 'premium', 'premium_aibain'] as const;

function StartLink({ action }: { action: PublicAccountAction }) {
    if (action.disabled) {
        return <span className="bm-button bm-button--muted" aria-disabled="true">{action.label}</span>;
    }
    return <Link className="bm-button bm-button--primary" to={action.to}>{action.label}<ArrowRight size={17} aria-hidden /></Link>;
}

export default function LandingPage() {
    const { user, loading } = useAuth();
    const action = getPublicAccountAction(user, loading);
    const { canInstall, isInstalled, isIOS, install } = usePWAInstall();
    const [showGuide, setShowGuide] = useState(false);
    const isActiveMember = user?.role !== 'admin' && hasActiveBaseSubscription(user);
    const canOpenBrain = canAccessAiBain(user);
    const chosenAddon = user?.tier === 'premium' ? 'premium_aibain' : 'pro_aibain';
    const plans = isActiveMember && user?.tier === 'premium'
        ? AVAILABLE_PLANS.filter((plan) => PLAN_PAYMENT_META[plan].tier === 'premium')
        : AVAILABLE_PLANS;

    useEffect(() => {
        if (isInstalled) setShowGuide(false);
    }, [isInstalled]);

    useSeo({
        title: 'BitMan AI 주식분석 에이전트 | AI 브레인',
        description: '여러 AI 에이전트가 국내주식·미국주식·가상자산 시장을 자동 분석합니다. AI 브레인과 제갈공명에서 종목 후보, 차트 유사 사례, 뉴스·공시 근거를 확인하세요.',
        path: '/',
        jsonLd: [{
            '@context': 'https://schema.org',
            '@type': 'FAQPage',
            mainEntity: FAQS.map(({ question, answer }) => ({
                '@type': 'Question',
                name: question,
                acceptedAnswer: { '@type': 'Answer', text: answer },
            })),
        }],
    });

    function planHref(plan: BillingPlan) {
        const query = planToQuery(plan);
        if (!user || user.status === 'unknown') return `/signup?${query}`;
        if (user.role === 'admin') return '/admin';
        if (user.has_pending_subscription === true || action.to === '/pending-approval') return '/pending-approval';
        if (isBaseSubscriptionExpired(user)) return `/plan-select?resubscribe=1&from=expired&${query}`;
        return `/plan-select?${isActiveMember ? 'change=1&' : ''}${query}`;
    }

    const aiHref = canOpenBrain ? '/dashboard/ai-bain' : planHref(chosenAddon);
    const pending = user?.has_pending_subscription === true || action.to === '/pending-approval';
    const addonHref = user
        ? planHref(chosenAddon)
        : `/login?next=${encodeURIComponent(`/plan-select?change=1&${planToQuery('pro_aibain')}`)}`;

    return (
        <PublicShell landing>
            <div className="bitman-landing">
                <div className="bm-wrap">
                    <section className="bm-hero" aria-labelledby="bitman-title">
                        <div className="bm-hero-copy">
                            <p className="bm-kicker"><span />멀티 AI 에이전트 주식분석 자동화</p>
                            <h1 id="bitman-title">세 시장을 살피고,<br /><em>종목의 근거를 찾다.</em></h1>
                            <p className="bm-lead">국내주식부터 미국주식, 가상자산까지. BitMan이 시장을 살피고, <strong>AI 브레인</strong>이 관심 종목의 근거를 교차 검토합니다.</p>
                            <div className="bm-actions">
                                <StartLink action={action} />
                                <a className="bm-button" href="#ai-brain">AI 브레인 알아보기<ArrowDown size={16} aria-hidden /></a>
                            </div>
                            <p className="bm-cta-note">{action.hint}</p>
                        </div>

                        <figure className="bm-orbit">
                            <img src={orbitImage} alt="" width="1160" height="870" fetchPriority="high" />
                            <figcaption>
                                <Globe2 size={17} aria-hidden />
                                <span>국내주식 <b>·</b> 미국주식 <b>·</b> 가상자산</span>
                            </figcaption>
                        </figure>
                    </section>

                    <section id="automation" className="bm-market-grid" aria-label="자동 분석 대상 시장">
                        {MARKETS.map(({ title, label, icon: Icon, description }) => (
                            <article className="bm-market" key={label}>
                                <Icon size={22} strokeWidth={1.6} aria-hidden />
                                <div>
                                    <h2>{title} <span aria-hidden>{label}</span></h2>
                                    <p>{description}</p>
                                </div>
                            </article>
                        ))}
                    </section>

                    <section id="ai-brain" className="bm-section" aria-labelledby="brain-title">
                        <div className="bm-brain">
                            <img src={kongmingImage} alt="" loading="lazy" decoding="async" />
                            <div className="bm-brain-copy">
                                <p className="bm-kicker"><BrainCircuit size={18} aria-hidden />AI 브레인</p>
                                <h2 id="brain-title">어떤 종목을 볼지,<br />왜 봐야 할지.</h2>
                                <p>알파 스캐너에서 종목 후보를 찾고, 제갈공명에서 뉴스와 공시를 대조하세요. 차트와 수급까지 함께 보며 관심 종목을 판단할 수 있습니다.</p>
                                {action.disabled ? <StartLink action={action} /> : (
                                    <Link className="bm-button bm-button--primary" to={aiHref}>
                                        {canOpenBrain ? 'AI 브레인 열기' : pending ? '승인 상태' : 'AI 브레인으로 시작'}
                                        <ArrowRight size={17} aria-hidden />
                                    </Link>
                                )}
                            </div>
                        </div>
                        <div className="bm-feature-grid">
                            {BRAIN_FEATURES.map(({ icon: Icon, title, description }) => (
                                <article key={title}>
                                    <Icon size={22} strokeWidth={1.6} aria-hidden />
                                    <h3>{title}</h3>
                                    <p>{description}</p>
                                </article>
                            ))}
                        </div>
                        <div className="bm-evidence">
                            <Link to="/guide/signal-verification-worked-example">공개 분석 예제<ArrowRight size={14} aria-hidden /></Link>
                            <Link to="/track-record">검출 이후 결과 보기<ArrowRight size={14} aria-hidden /></Link>
                            <Link to="/community">커뮤니티 둘러보기<ArrowRight size={14} aria-hidden /></Link>
                        </div>
                    </section>

                    <section id="pricing" className="bm-section" aria-labelledby="plans-title">
                        <div className="bm-section-title">
                            <div>
                                <h2 id="plans-title">내게 맞는 플랜</h2>
                                <p>세 시장의 대시보드부터 AI 브레인과 제갈공명까지.</p>
                            </div>
                            <Link className="bm-text-link" to="/pricing">전체 요금제 비교<ArrowRight size={16} aria-hidden /></Link>
                        </div>
                        <div className="bm-prices">
                            {plans.map((plan) => {
                                const meta = PLAN_PAYMENT_META[plan];
                                const sameTier = isActiveMember && user?.tier === meta.tier;
                                const addon = sameTier && meta.includesAibain;
                                const current = sameTier && !meta.includesAibain;
                                const featured = plan === 'pro_aibain' || addon;
                                return (
                                    <article className={`bm-price${featured ? ' bm-price--featured' : ''}`} key={plan} aria-label={addon ? AIBAIN_ADDON_META.label : meta.label}>
                                        <h3>{addon ? 'AI 브레인 추가·연장' : meta.label}</h3>
                                        <p className="bm-amount">{current ? '이용 중' : addon ? AIBAIN_ADDON_META.amount : meta.amount}</p>
                                        <p className="bm-period">{addon ? AIBAIN_ADDON_META.period : meta.period}</p>
                                        <p>{meta.includesAibain ? 'AI 브레인과 제갈공명 뉴스·재료 검증 포함' : '국내·미국·가상자산 분석 대시보드'}</p>
                                        {action.disabled ? <StartLink action={action} /> : !current && (
                                            <Link
                                                aria-label={pending ? '승인 상태' : user?.role === 'admin' ? '관리 콘솔' : addon ? 'AI 브레인 추가·연장' : `${meta.label} 선택`}
                                                className={`bm-button${featured ? ' bm-button--primary' : ''}`}
                                                to={planHref(plan)}
                                            >
                                                {pending ? '승인 상태' : user?.role === 'admin' ? '관리 콘솔' : addon ? '추가·연장' : '플랜 선택'}<ArrowRight size={16} aria-hidden />
                                            </Link>
                                        )}
                                    </article>
                                );
                            })}
                        </div>
                        <div className="bm-addon">
                            <div>
                                <h3>{AIBAIN_ADDON_META.label}</h3>
                                <p>기존 Pro·Ultra Pro 회원은 <strong>{AIBAIN_ADDON_META.amount} / 30일</strong>에 추가할 수 있습니다.</p>
                            </div>
                            {canOpenBrain && user?.role !== 'admin' ? <span className="bm-addon-status">이용 중</span> : !action.disabled && (!user || isActiveMember) && (
                                <Link className="bm-text-link" to={addonHref}>{pending ? '승인 상태' : isActiveMember ? 'AI 브레인 추가' : '로그인 후 추가'}<ArrowRight size={16} aria-hidden /></Link>
                            )}
                        </div>
                        {isActiveMember && !action.disabled && (
                            <Link className="bm-text-link bm-change-plan" to="/plan-select?change=1">플랜 변경 · AI Brain 추가<ArrowRight size={16} aria-hidden /></Link>
                        )}
                    </section>

                    <section id="how-it-works" className="bm-section" aria-labelledby="start-title">
                        <div className="bm-section-title"><h2 id="start-title">가입부터 이용까지</h2></div>
                        <ol className="bm-steps">
                            {SIGNUP_STEPS.map(({ title, description }, index) => (
                                <li key={title}>
                                    <span className="bm-step-number" aria-hidden>{index + 1}</span>
                                    <h3>{title}</h3>
                                    <p>{description}</p>
                                </li>
                            ))}
                        </ol>
                    </section>

                    <section className="bm-section bm-faq" aria-labelledby="faq-title">
                        <h2 id="faq-title">자주 묻는 질문</h2>
                        <div>
                            {FAQS.map(({ question, answer }) => (
                                <details key={question}>
                                    <summary>{question}</summary>
                                    <p>{answer}</p>
                                </details>
                            ))}
                        </div>
                    </section>

                    <section className="bm-final" aria-labelledby="next-title">
                        <div>
                            <h2 id="next-title">BitMan 시작하기</h2>
                            <p>{action.hint}</p>
                        </div>
                        <div className="bm-actions">
                            <StartLink action={action} />
                            {!isInstalled && canInstall && (
                                <button className="bm-button" type="button" onClick={async () => {
                                    if (await install() === 'manual') setShowGuide(true);
                                }}>
                                    {isIOS ? '설치 방법 보기' : '앱으로 설치'}
                                </button>
                            )}
                        </div>
                    </section>
                </div>
            </div>

            {showGuide && !isInstalled && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}
        </PublicShell>
    );
}
