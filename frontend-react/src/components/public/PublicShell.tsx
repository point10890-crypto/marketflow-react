import { ReactNode, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * 공개 영역(비로그인) 셸 — 다크 터미널 에디토리얼.
 *
 * 대시보드와 구분되는 "읽는 공간": 사이드바 없이 상단 헤더 + 본문 컬럼 + 공용
 * 푸터. AdSense 심사 크롤러와 첫 방문자가 함께 보는 영역이므로 정책 링크와
 * 투자 면책을 푸터에 상시 노출한다.
 */

const NAV_LINKS = [
    { to: '/community', label: '커뮤니티' },
    { to: '/pricing', label: '요금제' },
    { to: '/about', label: '소개' },
];

export function PublicShell({ children, section }: { children: ReactNode; section?: string }) {
    return (
        <div className="pub-root min-h-screen bg-[#09090b] text-gray-300 flex flex-col">
            <div className="pub-glow" aria-hidden />
            <PublicHeader section={section} />
            <main className="relative z-[1] flex-1 w-full">{children}</main>
            <PublicFooter />
        </div>
    );
}

export function PublicHeader({ section }: { section?: string }) {
    const { user } = useAuth();
    const navigate = useNavigate();
    return (
        <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-[#09090b]/85 backdrop-blur-md">
            <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
                <Link to="/" className="flex min-w-0 items-baseline gap-2">
                    <span className="text-[17px] font-black tracking-tight text-white">
                        Market<span className="text-amber-400">Flow</span>
                    </span>
                    {section && (
                        <span className="hidden font-mono text-[10px] uppercase tracking-[0.18em] text-gray-600 xs:inline sm:inline">
                            //{section}
                        </span>
                    )}
                </Link>
                <nav className="hidden items-center gap-6 md:flex">
                    {NAV_LINKS.map(l => (
                        <Link key={l.to} to={l.to}
                              className="text-[13px] font-medium text-gray-400 transition-colors hover:text-white">
                            {l.label}
                        </Link>
                    ))}
                </nav>
                <div className="flex shrink-0 items-center gap-2">
                    {user ? (
                        <button onClick={() => navigate('/dashboard')}
                                className="min-h-[44px] rounded-lg bg-white/[0.06] px-3.5 text-[12px] font-bold text-gray-200 transition-colors hover:bg-white/10">
                            <i className="fas fa-gauge-high mr-1.5 text-amber-400" />대시보드
                        </button>
                    ) : (
                        <>
                            <button onClick={() => navigate('/login')}
                                    className="hidden min-h-[44px] rounded-lg px-3 text-[12px] font-semibold text-gray-400 transition-colors hover:text-white sm:block">
                                로그인
                            </button>
                            <button onClick={() => navigate('/signup')}
                                    className="min-h-[44px] rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 px-3.5 text-[12px] font-black text-black transition-transform hover:scale-[1.03]">
                                무료 가입
                            </button>
                        </>
                    )}
                </div>
            </div>
        </header>
    );
}

export function PublicFooter() {
    const year = new Date().getFullYear();
    return (
        <footer className="relative z-[1] mt-16 border-t border-white/[0.06] bg-[#0b0b0e]">
            <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
                <div className="grid grid-cols-1 gap-8 sm:grid-cols-3">
                    <div>
                        <div className="text-base font-black tracking-tight text-white">
                            Market<span className="text-amber-400">Flow</span>
                        </div>
                        <p className="mt-2 max-w-[28ch] text-[12px] leading-relaxed text-gray-500">
                            KR·US·Crypto 시장을 AI 로 분석하는 마크 미너비니 전략 기반 시장 분석 서비스.
                        </p>
                    </div>
                    <div>
                        <div className="pub-label">바로가기</div>
                        <ul className="mt-3 space-y-2 text-[12px]">
                            <li><Link className="text-gray-500 transition-colors hover:text-amber-300" to="/community">커뮤니티</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-amber-300" to="/pricing">요금제</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-amber-300" to="/about">서비스 소개</Link></li>
                        </ul>
                    </div>
                    <div>
                        <div className="pub-label">정책 · 문의</div>
                        <ul className="mt-3 space-y-2 text-[12px]">
                            <li><Link className="text-gray-500 transition-colors hover:text-amber-300" to="/privacy">개인정보처리방침</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-amber-300" to="/terms">이용약관</Link></li>
                            <li>
                                <a className="text-gray-500 transition-colors hover:text-amber-300" href="mailto:point10890@gmail.com">
                                    point10890@gmail.com
                                </a>
                            </li>
                        </ul>
                    </div>
                </div>
                <div className="mt-8 border-t border-white/[0.05] pt-5">
                    <p className="font-mono text-[10px] leading-relaxed text-gray-600">
                        DISCLOSURE — 본 서비스가 제공하는 모든 정보는 투자 판단을 위한 참고 자료이며, 투자 권유나
                        자문이 아닙니다. 투자의 최종 결정과 그에 따른 책임은 투자자 본인에게 있습니다. 과거의 수익률이
                        미래의 수익을 보장하지 않습니다.
                    </p>
                    <p className="mt-3 text-[11px] text-gray-600">
                        © {year} MarketFlow · Mark Minervini Project
                    </p>
                </div>
            </div>
        </footer>
    );
}

/**
 * AdSense 수동 광고 슬롯 — 공개 페이지 전용.
 * Auto ads 를 쓰지 않으므로 이 컴포넌트가 놓인 곳에만 광고가 실린다
 * (로그인 대시보드는 광고 프리 유지). 미승인/차단 시 빈 영역이 접히도록
 * min-height 를 강제하지 않는다.
 */
export function AdSlot({ slot, className = '' }: { slot: string; className?: string }) {
    useEffect(() => {
        try {
            ((window as any).adsbygoogle = (window as any).adsbygoogle || []).push({});
        } catch { /* 스크립트 미로드/차단 — 조용히 무시 */ }
    }, []);
    return (
        <div className={`pub-ad ${className}`} aria-label="advertisement">
            <span className="pub-ad-tag">AD</span>
            <ins className="adsbygoogle"
                 style={{ display: 'block' }}
                 data-ad-client="ca-pub-4268071335236139"
                 data-ad-slot={slot}
                 data-ad-format="auto"
                 data-full-width-responsive="true" />
        </div>
    );
}
