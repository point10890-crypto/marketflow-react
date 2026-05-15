import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { InstallGuide } from '@/components/layout/InstallPrompt';
import { useAuth } from '@/contexts/AuthContext';

const features = [
    { icon: 'fa-flag', title: 'KR Market', desc: '종가베팅, 주도주LIVE, VCP, AI Chart, Track Record', color: 'from-blue-500 to-indigo-600' },
    { icon: 'fa-globe-americas', title: 'US Market', desc: 'S&P500 Overview, VCP Signals, ETF Flows, AI Chart', color: 'from-green-500 to-emerald-600' },
    { icon: 'fa-bitcoin', title: 'Crypto', desc: '시가총액, 도미넌스, VCP Signals 실시간 분석', color: 'from-yellow-500 to-orange-600' },
    { icon: 'fa-chart-bar', title: 'VCP Enhanced', desc: 'KR/US/Crypto 전 시장 Volume Contraction 스캐너', color: 'from-rose-500 to-pink-600' },
    { icon: 'fa-wave-square', title: 'W Pattern AI', desc: 'M&W 차트 패턴 자동 감지 + 승률 추적', color: 'from-pink-500 to-fuchsia-600' },
    { icon: 'fa-newspaper', title: 'AI Briefing', desc: 'Gemini 기반 조간/마감 AI 시장 브리핑', color: 'from-purple-500 to-violet-600' },
];

const minerviniStats = [
    { value: '220%', label: '연평균 수익률', sub: '5년 연속 (1994–1999)' },
    { value: '33,500%', label: '5년 누적 수익률', sub: '복리 기준' },
    { value: '#1', label: 'US Investing Champion', sub: '1997년 우승' },
    { value: '0.33%', label: '최대 손실 (월)', sub: '리스크 관리의 정수' },
];

const sepaElements = [
    { num: '1', title: 'Trend', desc: '주도주는 반드시 상승 추세 — 30주 이평선 위, 200일선 우상향' },
    { num: '2', title: 'Fundamentals', desc: 'EPS·매출 가속, 분기별 어닝 서프라이즈, 마진 개선' },
    { num: '3', title: 'Catalyst', desc: '신제품·실적 발표·산업 변화 등 주가를 폭발시킬 트리거' },
    { num: '4', title: 'Entry Point', desc: 'VCP 완성 후 거래량 동반 돌파 — 정확한 매수 타이밍' },
    { num: '5', title: 'Exit', desc: '손절선 7~8% 엄수, 이익 실현은 추세 종료 신호 시' },
];

const usageSteps = [
    { step: '01', title: '회원가입 & Pro 구독', desc: '이메일로 가입 후 Pro 또는 Ultra Pro 플랜 결제', icon: 'fa-user-plus' },
    { step: '02', title: 'Summary로 시장 점검', desc: 'KR·US·Crypto 시장 게이지로 RISK_ON/OFF 즉시 확인', icon: 'fa-gauge-high' },
    { step: '03', title: 'VCP·종가베팅 시그널 확인', desc: 'AI가 점수 매긴 S/A등급 종목 + 진입가·손절가 자동 계산', icon: 'fa-chart-line' },
    { step: '04', title: 'AI 챗봇으로 심층 분석', desc: '관심 종목을 챗봇에 입력하면 DART 공시·뉴스·차트 종합 분석', icon: 'fa-robot' },
];

export default function LandingPage() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [animState, setAnimState] = useState<'idle' | 'ripple' | 'exit'>('idle');
    const [mounted, setMounted] = useState(false);
    const [showGuide, setShowGuide] = useState(false);
    const { isInstalled, isIOS, install } = usePWAInstall();

    // 로그인 + 승인된 Pro/Ultra Pro 유저는 랜딩 페이지 스킵 → 대시보드로
    useEffect(() => {
        if (user && user.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium')) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, navigate]);

    useEffect(() => {
        const t = setTimeout(() => setMounted(true), 50);
        return () => clearTimeout(t);
    }, []);

    const handleInstallApp = async () => {
        const result = await install();
        if (result === 'manual') setShowGuide(true);
    };

    const handleEnter = () => {
        if (animState !== 'idle') return;
        setAnimState('ripple');
        setTimeout(() => setAnimState('exit'), 400);
        // 미인증 방문자는 /signup 으로, 인증 유저는 /dashboard 로 분기.
        // (가드가 다시 튕기는 순환 방지 + 비가입자 가입 유도)
        const target = user ? '/dashboard' : '/signup';
        setTimeout(() => navigate(target), 900);
    };

    return (
        <div className={`landing-root ${mounted ? 'landing-in' : ''} ${animState === 'exit' ? 'landing-exit' : ''}`}>
            {/* Ambient grid */}
            <div className="landing-grid" aria-hidden />
            <div className="landing-orb landing-orb-1" aria-hidden />
            <div className="landing-orb landing-orb-2" aria-hidden />

            {/* Scrollable content */}
            <div className="relative z-10 min-h-screen flex flex-col items-center">
                {/* ============ HERO ============ */}
                <div className="landing-content">
                    <div className="landing-logo">
                        <div className="landing-logo-icon"><span>B</span></div>
                        <span className="landing-logo-text">BitMan</span>
                    </div>

                    <div className="landing-headline">
                        <div className="inline-block px-3 py-1 mb-4 rounded-full border border-amber-500/30 bg-amber-500/10 text-[10px] sm:text-xs font-bold tracking-wider text-amber-400 uppercase">
                            Mark Minervini Project
                        </div>
                        <h1>마크 미너비니<br /><span className="landing-headline-accent">전략 자동화</span></h1>
                        <p className="landing-subtitle">VCP · SEPA · Trend Template<br />AI가 24시간 KR · US · Crypto를 스캔합니다</p>
                    </div>

                    <div className="landing-stats">
                        {[
                            { label: 'KR VCP', value: 'LIVE' },
                            { label: 'US Market', value: 'LIVE' },
                            { label: 'Crypto', value: 'LIVE' },
                        ].map((s) => (
                            <div key={s.label} className="landing-stat">
                                <span className="landing-stat-dot" />
                                <span className="landing-stat-label">{s.label}</span>
                            </div>
                        ))}
                    </div>

                    <button
                        className={`landing-cta ${animState === 'ripple' ? 'landing-cta-ripple' : ''}`}
                        onClick={handleEnter}
                        aria-label={user ? '대시보드 열기' : '가입하고 시작'}
                    >
                        <span className="landing-cta-text">{user ? '대시보드 보기' : '가입하고 시작'}</span>
                        <span className="landing-cta-arrow"><i className="fas fa-arrow-right" /></span>
                        <span className="landing-cta-ripple-bg" />
                    </button>

                    <p className="landing-hint">마켓 서머리 · VCP · 종가베팅 · AI 챗봇</p>
                </div>

                {/* ============ 마크 미너비니 인물 탐구 ============ */}
                <section className="w-full max-w-5xl px-6 pt-8 pb-16">
                    <div className="text-center mb-10">
                        <div className="text-[11px] tracking-[0.2em] text-amber-400/80 font-bold mb-3">WHO IS</div>
                        <h2 className="text-3xl sm:text-4xl font-black text-white mb-3">
                            <span className="bg-gradient-to-r from-amber-300 via-amber-500 to-orange-500 bg-clip-text text-transparent">Mark Minervini</span>
                        </h2>
                        <p className="text-gray-400 text-sm sm:text-base max-w-2xl mx-auto leading-relaxed">
                            세계에서 가장 성공한 트레이더 중 한 명. 1997년 US Investing Championship 우승자.
                            5년 연속 평균 220%의 경이적인 수익률로 33,500%의 누적 수익을 기록했습니다.
                        </p>
                    </div>

                    {/* Mock "프로필 카드" — 사진 대신 이니셜 + 이모지로 시각 표현 */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                        <div className="md:col-span-1 relative overflow-hidden rounded-2xl border border-amber-500/20 bg-gradient-to-br from-[#1a1410] via-[#13151f] to-[#0f0f12] p-6 text-center">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-amber-500/10 blur-3xl rounded-full" />
                            <div className="relative w-28 h-28 mx-auto mb-4 rounded-2xl overflow-hidden ring-2 ring-amber-500/40 shadow-2xl shadow-amber-500/20">
                                <img
                                    src="/landing/minervini.png"
                                    alt="Mark Minervini"
                                    className="w-full h-full object-cover"
                                    loading="lazy"
                                />
                            </div>
                            <div className="text-white font-bold text-base">Mark Minervini</div>
                            <div className="text-amber-400/70 text-[11px] mt-1">US Investing Champion · 334% Annual Return</div>
                            <div className="flex justify-center gap-1 mt-3">
                                <span className="px-2 py-0.5 text-[9px] rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">SEPA</span>
                                <span className="px-2 py-0.5 text-[9px] rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">VCP</span>
                                <span className="px-2 py-0.5 text-[9px] rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">Trend</span>
                            </div>
                        </div>
                        <div className="md:col-span-2 grid grid-cols-2 gap-3">
                            {minerviniStats.map((s) => (
                                <div key={s.label} className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 sm:p-5">
                                    <div className="text-2xl sm:text-3xl font-black bg-gradient-to-r from-amber-300 to-orange-500 bg-clip-text text-transparent">{s.value}</div>
                                    <div className="text-white text-xs sm:text-sm font-bold mt-1">{s.label}</div>
                                    <div className="text-gray-500 text-[10px] sm:text-[11px] mt-1">{s.sub}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <blockquote className="border-l-2 border-amber-500/50 pl-4 py-2 text-gray-400 text-sm sm:text-base italic max-w-3xl mx-auto">
                        “리스크 관리는 모든 것의 시작이다. 큰 손실을 피해라 — 그러면 큰 수익은 자연스럽게 따라온다.”
                        <div className="text-[10px] text-gray-600 not-italic mt-2">— Mark Minervini</div>
                    </blockquote>
                </section>

                {/* ============ VCP 전략 ============ */}
                <section className="w-full max-w-5xl px-6 pb-16">
                    <div className="text-center mb-8">
                        <div className="text-[11px] tracking-[0.2em] text-blue-400/80 font-bold mb-3">STRATEGY 01</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-2">VCP — Volume Contraction Pattern</h2>
                        <p className="text-gray-400 text-sm max-w-2xl mx-auto">
                            거래량이 단계적으로 줄어들면서 가격 변동폭도 좁혀지는 패턴.
                            매도 압력이 소진된 후 거래량 폭발과 함께 돌파하는 순간이 최적의 진입 시점입니다.
                        </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
                        {/* CSS 차트 mockup */}
                        <div className="rounded-2xl border border-white/[0.07] bg-[#0d0e14] p-5 relative overflow-hidden">
                            <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                    <span className="text-white text-xs font-bold">VCP Pattern</span>
                                    <span className="px-1.5 py-0.5 rounded text-[9px] bg-emerald-500/20 text-emerald-400 font-bold">BREAKOUT</span>
                                </div>
                                <span className="text-emerald-400 text-xs font-bold">+12.4%</span>
                            </div>
                            <svg viewBox="0 0 300 120" className="w-full h-32">
                                <defs>
                                    <linearGradient id="vcpGrad" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor="rgba(16,185,129,0.4)" />
                                        <stop offset="100%" stopColor="rgba(16,185,129,0)" />
                                    </linearGradient>
                                </defs>
                                {/* 가격 라인 — 수축 → 돌파 */}
                                <path
                                    d="M 0,80 L 30,40 L 50,75 L 70,50 L 90,72 L 110,55 L 130,68 L 150,58 L 170,65 L 190,60 L 210,63 L 230,61 L 250,30 L 280,15 L 300,10"
                                    stroke="rgb(16,185,129)"
                                    strokeWidth="2"
                                    fill="none"
                                />
                                <path
                                    d="M 0,80 L 30,40 L 50,75 L 70,50 L 90,72 L 110,55 L 130,68 L 150,58 L 170,65 L 190,60 L 210,63 L 230,61 L 250,30 L 280,15 L 300,10 L 300,120 L 0,120 Z"
                                    fill="url(#vcpGrad)"
                                />
                                {/* 수축 영역 표시 */}
                                <line x1="240" y1="0" x2="240" y2="120" stroke="rgba(245,158,11,0.4)" strokeWidth="1" strokeDasharray="3,3" />
                                <text x="245" y="15" fill="rgb(245,158,11)" fontSize="9" fontWeight="bold">BUY</text>
                            </svg>
                            <div className="grid grid-cols-3 gap-2 mt-3">
                                <div className="text-center p-2 rounded bg-white/5">
                                    <div className="text-[9px] text-gray-500">진입가</div>
                                    <div className="text-xs font-bold text-white">$142.50</div>
                                </div>
                                <div className="text-center p-2 rounded bg-white/5">
                                    <div className="text-[9px] text-gray-500">손절가</div>
                                    <div className="text-xs font-bold text-red-400">$131.10</div>
                                </div>
                                <div className="text-center p-2 rounded bg-white/5">
                                    <div className="text-[9px] text-gray-500">목표가</div>
                                    <div className="text-xs font-bold text-emerald-400">$165.20</div>
                                </div>
                            </div>
                        </div>

                        <div className="space-y-3">
                            {[
                                { num: '1', text: '주가가 큰 상승 후 횡보 또는 완만한 조정' },
                                { num: '2', text: '거래량이 단계적으로 감소 (보통 3~5단계)' },
                                { num: '3', text: '변동폭이 점점 좁아지는 압축 구간' },
                                { num: '4', text: '거래량 폭발과 함께 박스 상단 돌파' },
                                { num: '5', text: '신고가 갱신 — 진입 신호 발동' },
                            ].map((item) => (
                                <div key={item.num} className="flex items-start gap-3 p-3 rounded-xl bg-[#13151f] border border-white/[0.05]">
                                    <div className="w-6 h-6 shrink-0 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-600 flex items-center justify-center text-white text-[11px] font-black">{item.num}</div>
                                    <div className="text-gray-300 text-xs sm:text-sm leading-relaxed pt-0.5">{item.text}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </section>

                {/* ============ SEPA 시스템 ============ */}
                <section className="w-full max-w-5xl px-6 pb-16">
                    <div className="text-center mb-10">
                        <div className="text-[11px] tracking-[0.2em] text-purple-400/80 font-bold mb-3">STRATEGY 02</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-2">SEPA — Specific Entry Point Analysis</h2>
                        <p className="text-gray-400 text-sm max-w-2xl mx-auto">
                            미너비니가 정립한 5단계 종목 선정·매매 시스템.
                            BitMan은 이 5가지 요소를 모두 자동 점수화하여 S/A/B/C 등급으로 분류합니다.
                        </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                        {sepaElements.map((el) => (
                            <div key={el.num} className="relative rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 hover:border-purple-500/30 transition-all">
                                <div className="text-5xl font-black bg-gradient-to-br from-purple-500/30 to-purple-500/0 bg-clip-text text-transparent leading-none mb-2">{el.num}</div>
                                <div className="text-white font-bold text-sm mb-1">{el.title}</div>
                                <div className="text-gray-500 text-[11px] leading-relaxed">{el.desc}</div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-6 p-4 sm:p-5 rounded-2xl border border-purple-500/20 bg-gradient-to-r from-purple-500/5 via-transparent to-transparent">
                        <div className="flex items-start gap-3">
                            <i className="fas fa-lightbulb text-purple-400 mt-0.5" />
                            <div>
                                <div className="text-white text-sm font-bold mb-1">BitMan의 17점 자동 점수 시스템</div>
                                <div className="text-gray-400 text-xs leading-relaxed">
                                    뉴스·재료(3) + 거래대금(3) + 차트패턴(2) + 캔들(1) + 기간조정(1) + 수급(2) + 공시(2) + 애널리스트(3) = 17점.
                                    9점 이상은 S등급, 7점 이상은 A등급으로 자동 분류되어 텔레그램으로 발송됩니다.
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                {/* ============ 앱 화면 미리보기 (CSS Mockups) ============ */}
                <section className="w-full max-w-6xl px-6 pb-16">
                    <div className="text-center mb-10">
                        <div className="text-[11px] tracking-[0.2em] text-emerald-400/80 font-bold mb-3">INSIDE THE APP</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-2">한눈에 보는 BitMan 대시보드</h2>
                        <p className="text-gray-400 text-sm max-w-2xl mx-auto">AI가 미너비니 전략을 자동 적용한 결과를 실시간으로 확인하세요</p>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                        {/* Mock 1: Summary */}
                        <div className="rounded-2xl border border-white/[0.07] bg-[#0d0e14] p-4 hover:border-amber-500/30 transition-all">
                            <div className="flex items-center justify-between mb-3">
                                <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Summary</span>
                                <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-500/20 text-emerald-400">RISK_ON</span>
                            </div>
                            <div className="text-white text-sm font-bold mb-3">시장 게이지</div>
                            <div className="space-y-2">
                                {[
                                    { label: 'KR Market', val: 78, color: 'bg-emerald-500' },
                                    { label: 'US Market', val: 65, color: 'bg-blue-500' },
                                    { label: 'Crypto', val: 52, color: 'bg-amber-500' },
                                ].map((m) => (
                                    <div key={m.label}>
                                        <div className="flex justify-between text-[10px] mb-1">
                                            <span className="text-gray-400">{m.label}</span>
                                            <span className="text-white font-bold">{m.val}</span>
                                        </div>
                                        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                                            <div className={`h-full ${m.color}`} style={{ width: `${m.val}%` }} />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Mock 2: 종가베팅 */}
                        <div className="rounded-2xl border border-white/[0.07] bg-[#0d0e14] p-4 hover:border-amber-500/30 transition-all">
                            <div className="flex items-center justify-between mb-3">
                                <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">KR · 종가베팅 V2</span>
                                <span className="text-[10px] text-amber-400">17점 만점</span>
                            </div>
                            <div className="space-y-2">
                                {[
                                    { grade: 'S', name: '삼성전자', score: 14, change: '+3.2%', color: 'bg-amber-500/20 text-amber-400' },
                                    { grade: 'S', name: 'LG에너지솔루션', score: 12, change: '+2.8%', color: 'bg-amber-500/20 text-amber-400' },
                                    { grade: 'A', name: '현대차', score: 9, change: '+1.9%', color: 'bg-blue-500/20 text-blue-400' },
                                    { grade: 'A', name: 'NAVER', score: 8, change: '+1.5%', color: 'bg-blue-500/20 text-blue-400' },
                                ].map((s) => (
                                    <div key={s.name} className="flex items-center gap-2 p-2 rounded-lg bg-white/[0.02]">
                                        <span className={`w-5 h-5 rounded text-[10px] font-black flex items-center justify-center ${s.color}`}>{s.grade}</span>
                                        <span className="text-white text-xs font-medium flex-1 truncate">{s.name}</span>
                                        <span className="text-[10px] text-gray-500">{s.score}/17</span>
                                        <span className="text-[10px] text-emerald-400 font-bold">{s.change}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Mock 3: VCP Scanner */}
                        <div className="rounded-2xl border border-white/[0.07] bg-[#0d0e14] p-4 hover:border-amber-500/30 transition-all">
                            <div className="flex items-center justify-between mb-3">
                                <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">US VCP Scanner</span>
                                <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-500/20 text-emerald-400">12 LIVE</span>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                {[
                                    { t: 'NVDA', s: 92 },
                                    { t: 'AAPL', s: 88 },
                                    { t: 'MSFT', s: 85 },
                                    { t: 'AVGO', s: 81 },
                                ].map((v) => (
                                    <div key={v.t} className="p-2 rounded-lg bg-white/[0.02] border border-white/5">
                                        <div className="flex items-center justify-between mb-1">
                                            <span className="text-white text-xs font-bold">{v.t}</span>
                                            <span className="text-[9px] text-emerald-400 font-bold">{v.s}</span>
                                        </div>
                                        <svg viewBox="0 0 60 20" className="w-full h-4">
                                            <polyline
                                                points="0,15 10,12 20,14 30,10 40,12 50,5 60,2"
                                                stroke="rgb(16,185,129)"
                                                strokeWidth="1.5"
                                                fill="none"
                                            />
                                        </svg>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </section>

                {/* ============ Pro Plan Features ============ */}
                <section className="w-full max-w-5xl px-6 pb-16">
                    <div className="text-center mb-10">
                        <div className="text-[11px] tracking-[0.2em] text-amber-400/80 font-bold mb-3">FEATURES</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-3">
                            <span className="bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">Pro</span> 플랜 전체 기능
                        </h2>
                        <p className="text-gray-500 text-sm">AI 기반 실시간 분석 도구로 투자 의사결정을 지원합니다</p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {features.map((f) => (
                            <div key={f.title} className="group p-5 rounded-2xl border border-white/[0.07] bg-[#13151f] hover:border-white/[0.15] transition-all">
                                <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${f.color} flex items-center justify-center mb-3 shadow-lg`}>
                                    <i className={`fas ${f.icon} text-white text-sm`} />
                                </div>
                                <h3 className="text-white font-bold text-sm mb-1">{f.title}</h3>
                                <p className="text-gray-500 text-xs leading-relaxed">{f.desc}</p>
                            </div>
                        ))}
                    </div>
                </section>

                {/* ============ 사용법 4 STEP ============ */}
                <section className="w-full max-w-5xl px-6 pb-16">
                    <div className="text-center mb-10">
                        <div className="text-[11px] tracking-[0.2em] text-cyan-400/80 font-bold mb-3">HOW TO USE</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-2">4단계로 시작하는 미너비니 전략</h2>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        {usageSteps.map((s) => (
                            <div key={s.step} className="relative p-5 rounded-2xl border border-white/[0.07] bg-[#13151f]">
                                <div className="absolute top-3 right-3 text-3xl font-black text-white/[0.05]">{s.step}</div>
                                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center mb-3 shadow-lg">
                                    <i className={`fas ${s.icon} text-white text-sm`} />
                                </div>
                                <h3 className="text-white font-bold text-sm mb-1">{s.title}</h3>
                                <p className="text-gray-500 text-[11px] leading-relaxed">{s.desc}</p>
                            </div>
                        ))}
                    </div>
                </section>

                {/* ============ Pricing ============ */}
                <section className="w-full max-w-5xl px-6 pb-16">
                    <div className="text-center">
                        <div className="text-[11px] tracking-[0.2em] text-amber-400/80 font-bold mb-3">PRICING</div>
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-8">지금 시작하세요</h2>
                        <div className="inline-flex flex-col sm:flex-row items-center gap-4 sm:gap-6 p-6 sm:p-8 rounded-2xl border border-amber-500/20 bg-[#13151f]">
                            <div>
                                <div className="text-amber-400 text-xs mb-1 font-bold">Pro <i className="fas fa-crown text-[10px]" /></div>
                                <div className="text-2xl font-black text-white">50,000<span className="text-base text-gray-400">원/30일</span></div>
                                <div className="text-gray-600 text-xs mt-1">전체 기능 이용</div>
                            </div>
                            <div className="hidden sm:block w-px h-16 bg-white/10" />
                            <div className="sm:hidden w-24 h-px bg-white/10" />
                            <div>
                                <div className="text-cyan-400 text-xs mb-1 font-bold">Pro + AI Bain <i className="fas fa-robot text-[10px]" /></div>
                                <div className="text-2xl font-black text-white">90,000<span className="text-base text-gray-400">원/30일</span></div>
                                <div className="text-gray-600 text-xs mt-1">Pro + AI Bain 알파 스캐너</div>
                            </div>
                            <div className="hidden sm:block w-px h-16 bg-white/10" />
                            <div className="sm:hidden w-24 h-px bg-white/10" />
                            <div>
                                <div className="text-purple-400 text-xs mb-1 font-bold">Ultra Pro <i className="fas fa-gem text-[10px]" /></div>
                                <div className="text-2xl font-black text-white">1,200,000<span className="text-base text-gray-400">원</span></div>
                                <div className="text-gray-600 text-xs mt-1">평생 무기한 이용</div>
                            </div>
                        </div>

                        <div className="flex items-center justify-center gap-4 mt-8">
                            <Link
                                to="/signup"
                                className="px-8 py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold text-sm transition-all"
                            >
                                가입하고 시작
                            </Link>
                            <Link
                                to="/pricing"
                                className="px-8 py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-bold text-sm transition-all border border-white/10"
                            >
                                요금 상세
                            </Link>
                        </div>

                        <p className="text-gray-400 text-base sm:text-lg mt-6">
                            이미 계정이 있으신가요? <Link to="/login" className="text-amber-400 hover:text-amber-300 font-semibold">로그인</Link>
                        </p>
                    </div>
                </section>

                {/* ============ App Download ============ */}
                {!isInstalled && (
                    <section className="w-full max-w-5xl px-6 pb-16">
                        <div className="p-6 rounded-2xl border border-blue-500/20 bg-[#13151f] text-center">
                            <div className="w-14 h-14 mx-auto mb-4 bg-gradient-to-br from-blue-500/20 to-cyan-500/20 rounded-2xl flex items-center justify-center border border-blue-500/20">
                                <i className="fas fa-mobile-screen-button text-blue-400 text-2xl" />
                            </div>
                            <h3 className="text-white font-bold text-lg mb-1">앱으로 더 빠르게</h3>
                            <p className="text-gray-500 text-sm mb-4">홈 화면에 추가하고 네이티브 앱처럼 사용하세요</p>
                            <div className="flex flex-wrap items-center justify-center gap-3 mb-4">
                                <span className="flex items-center gap-1.5 text-xs text-gray-400">
                                    <i className="fas fa-bolt text-amber-400 text-[10px]" /> 빠른 실행
                                </span>
                                <span className="flex items-center gap-1.5 text-xs text-gray-400">
                                    <i className="fas fa-bell text-amber-400 text-[10px]" /> 푸시 알림
                                </span>
                                <span className="flex items-center gap-1.5 text-xs text-gray-400">
                                    <i className="fas fa-expand text-amber-400 text-[10px]" /> 전체 화면
                                </span>
                            </div>
                            <button
                                onClick={handleInstallApp}
                                className="inline-flex items-center gap-2 px-8 py-3 rounded-xl bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-400 hover:to-cyan-400 text-white font-bold text-sm transition-all"
                            >
                                <i className="fas fa-download" />
                                앱 다운로드
                            </button>
                        </div>
                    </section>
                )}

                {/* ============ Footer ============ */}
                <footer className="w-full max-w-5xl px-6 pb-10 text-center">
                    <div className="text-gray-700 text-[10px]">
                        © {new Date().getFullYear()} BitMan · Mark Minervini Project · 본 서비스는 마크 미너비니의 매매 전략을 학습 목적으로 자동화한 도구이며, 투자 권유가 아닙니다.
                    </div>
                </footer>
            </div>

            {showGuide && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}

            {/* Exit overlay */}
            <div className={`landing-exit-overlay ${animState === 'exit' ? 'landing-exit-overlay-active' : ''}`} aria-hidden />
        </div>
    );
}
