import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { InstallGuide } from '@/components/layout/InstallPrompt';

const features = [
    { icon: 'fa-flag', title: 'KR Market', desc: '종가베팅, 주도주LIVE, VCP, AI Chart, Track Record', color: 'from-blue-500 to-indigo-600' },
    { icon: 'fa-globe-americas', title: 'US Market', desc: 'S&P500 Overview, VCP Signals, ETF Flows, AI Chart', color: 'from-green-500 to-emerald-600' },
    { icon: 'fa-bitcoin', title: 'Crypto', desc: '시가총액, 도미넌스, VCP Signals 실시간 분석', color: 'from-yellow-500 to-orange-600' },
    { icon: 'fa-chart-bar', title: 'VCP Enhanced', desc: 'KR/US/Crypto 전 시장 Volume Contraction 스캐너', color: 'from-rose-500 to-pink-600' },
    { icon: 'fa-wave-square', title: 'W Pattern AI', desc: 'M&W 차트 패턴 자동 감지 + 승률 추적', color: 'from-pink-500 to-fuchsia-600' },
    { icon: 'fa-newspaper', title: 'AI Briefing', desc: 'Gemini 기반 조간/마감 AI 시장 브리핑', color: 'from-purple-500 to-violet-600' },
];

export default function LandingPage() {
    const navigate = useNavigate();
    const [animState, setAnimState] = useState<'idle' | 'ripple' | 'exit'>('idle');
    const [mounted, setMounted] = useState(false);
    const [showGuide, setShowGuide] = useState(false);
    const { canInstall, isInstalled, isIOS, install } = usePWAInstall();

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
        setTimeout(() => navigate('/dashboard'), 900);
    };

    return (
        <div className={`landing-root ${mounted ? 'landing-in' : ''} ${animState === 'exit' ? 'landing-exit' : ''}`}>
            {/* Ambient grid */}
            <div className="landing-grid" aria-hidden />
            <div className="landing-orb landing-orb-1" aria-hidden />
            <div className="landing-orb landing-orb-2" aria-hidden />

            {/* Scrollable content */}
            <div className="relative z-10 min-h-screen flex flex-col items-center">
                {/* Hero Section */}
                <div className="landing-content">
                    <div className="landing-logo">
                        <div className="landing-logo-icon"><span>B</span></div>
                        <span className="landing-logo-text">BitMan</span>
                    </div>

                    <div className="landing-headline">
                        <h1>AI 마켓<br /><span className="landing-headline-accent">인사이트</span></h1>
                        <p className="landing-subtitle">KR · US · Crypto<br />실시간 시장 분석 대시보드</p>
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
                        aria-label="대시보드 열기"
                    >
                        <span className="landing-cta-text">대시보드 보기</span>
                        <span className="landing-cta-arrow"><i className="fas fa-arrow-right" /></span>
                        <span className="landing-cta-ripple-bg" />
                    </button>

                    <p className="landing-hint">마켓 서머리 · VCP · 종가베팅</p>
                </div>

                {/* Features Section */}
                <div className="w-full max-w-5xl px-6 pb-16 mt-4">
                    <div className="text-center mb-10">
                        <h2 className="text-2xl sm:text-3xl font-black text-white mb-3">
                            <span className="bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">Pro</span> 플랜 기능
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

                    {/* Pricing Preview */}
                    <div className="mt-14 text-center">
                        <div className="inline-flex flex-col sm:flex-row items-center gap-4 sm:gap-6 p-6 sm:p-8 rounded-2xl border border-amber-500/20 bg-[#13151f]">
                            <div>
                                <div className="text-amber-400 text-xs mb-1 font-bold">Pro <i className="fas fa-crown text-[10px]" /></div>
                                <div className="text-2xl font-black text-white">50,000<span className="text-base text-gray-400">원/30일</span></div>
                                <div className="text-gray-600 text-xs mt-1">전체 기능 이용</div>
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
                                시작하기
                            </Link>
                            <Link
                                to="/pricing"
                                className="px-8 py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-bold text-sm transition-all border border-white/10"
                            >
                                요금 상세
                            </Link>
                        </div>

                        <p className="text-gray-600 text-xs mt-6">
                            이미 계정이 있으신가요? <Link to="/login" className="text-amber-400/70 hover:text-amber-400">로그인</Link>
                        </p>
                    </div>

                    {/* App Download Section */}
                    {!isInstalled && (
                        <div className="mt-14 p-6 rounded-2xl border border-blue-500/20 bg-[#13151f] text-center">
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
                    )}
                </div>
            </div>

            {showGuide && <InstallGuide isIOS={isIOS} onClose={() => setShowGuide(false)} />}

            {/* Exit overlay */}
            <div className={`landing-exit-overlay ${animState === 'exit' ? 'landing-exit-overlay-active' : ''}`} aria-hidden />
        </div>
    );
}
