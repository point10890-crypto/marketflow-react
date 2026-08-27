import { ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * Public pages share one native document scroller and one truthful account CTA.
 * The dashboard keeps its own bounded scroller; public pages must not introduce
 * a second fixed, overflow-y container.
 */

const NAV_LINKS = [
    { to: '/#automation', label: '자동화' },
    { to: '/#ai-brain', label: 'AI Brain' },
    { to: '/guide', label: '가이드' },
    { to: '/pricing', label: '요금제' },
    { to: '/community', label: '커뮤니티' },
];

export interface PublicActionUser {
    role?: string | null;
    status?: string | null;
    tier?: string | null;
    requested_tier?: string | null;
    is_pro_expired?: boolean | null;
}

export interface PublicAccountAction {
    to: string;
    label: string;
    hint: string;
    disabled?: boolean;
}

/** Keep this routing aligned with App.tsx's auth guards. */
export function getPublicAccountAction(
    user: PublicActionUser | null | undefined,
    loading = false,
): PublicAccountAction {
    if (loading || user?.status === 'unknown') {
        return { to: '/login', label: '계정 확인 중', hint: '로그인 상태를 확인하고 있습니다.', disabled: true };
    }
    if (!user) {
        return { to: '/signup', label: '무료 계정 만들기', hint: '계정 생성은 무료이며 이용은 플랜 승인 후 시작됩니다.' };
    }
    if (user.role === 'admin') {
        return { to: '/admin', label: '관리 콘솔', hint: '관리자 화면으로 이동합니다.' };
    }
    if (user.status === 'expired' || user.is_pro_expired) {
        return { to: '/plan-select?resubscribe=1&from=expired', label: '재구독', hint: '기존 계정과 기록은 유지됩니다.' };
    }
    if (user.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium')) {
        return { to: '/dashboard', label: '대시보드', hint: '현재 구독으로 대시보드를 엽니다.' };
    }
    if (user.status === 'pending' && user.requested_tier) {
        return { to: '/pending-approval', label: '승인 상태', hint: '입금 확인과 승인 상태를 확인합니다.' };
    }
    if (!user.tier) {
        return { to: '/plan-select', label: '플랜 선택', hint: '이용할 플랜을 선택합니다.' };
    }
    return { to: '/pending-approval', label: '승인 상태', hint: '구독 승인 상태를 확인합니다.' };
}

export function PublicShell({ children, section }: { children: ReactNode; section?: string }) {
    return (
        <div className="pub-root flex min-h-[100dvh] flex-col bg-[#09090b] text-gray-300">
            <a
                href="#main-content"
                className="fixed left-3 top-3 z-50 -translate-y-24 rounded-lg bg-white px-4 py-2 text-sm font-bold text-black transition-transform focus:translate-y-0"
            >
                본문으로 건너뛰기
            </a>
            <div className="pub-glow" aria-hidden />
            <PublicHeader section={section} />
            <main id="main-content" tabIndex={-1} className="relative z-[1] w-full flex-1 outline-none">
                {children}
            </main>
            <PublicFooter />
        </div>
    );
}

export function PublicHeader({ section }: { section?: string }) {
    const { user, loading } = useAuth();
    const [menuOpen, setMenuOpen] = useState(false);
    const action = getPublicAccountAction(user, loading);

    return (
        <header className="pub-header sticky top-0 z-20 border-b border-white/[0.06] bg-[#09090b] sm:bg-[#09090b]/90 sm:backdrop-blur-md">
            <div className="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
                <Link to="/" className="flex min-w-0 items-baseline gap-2" aria-label="MarketFlow 홈">
                    <span className="text-[18px] font-black tracking-tight text-white">
                        Market<span className="text-[#ff6b57]">Flow</span>
                    </span>
                    {section && (
                        <span className="hidden font-mono text-[10px] uppercase tracking-[0.18em] text-gray-600 sm:inline">
                            //{section}
                        </span>
                    )}
                </Link>

                <nav className="hidden items-center gap-6 md:flex" aria-label="공개 페이지">
                    {NAV_LINKS.map((item) => (
                        <a
                            key={item.to}
                            href={item.to}
                            className="text-[13px] font-medium text-gray-400 transition-colors hover:text-white"
                        >
                            {item.label}
                        </a>
                    ))}
                </nav>

                <div className="flex shrink-0 items-center gap-2">
                    {!user && !loading && (
                        <Link
                            to="/login"
                            className="hidden min-h-[44px] items-center rounded-lg px-3 text-[12px] font-semibold text-gray-400 transition-colors hover:text-white sm:inline-flex"
                        >
                            로그인
                        </Link>
                    )}
                    {action.disabled ? (
                        <span
                            aria-disabled="true"
                            className="inline-flex min-h-[44px] items-center rounded-lg border border-white/10 bg-white/[0.04] px-3.5 text-[12px] font-bold text-gray-500"
                        >
                            {action.label}
                        </span>
                    ) : (
                        <Link
                            to={action.to}
                            className="inline-flex min-h-[44px] items-center rounded-lg bg-[#ff6b57] px-3.5 text-[12px] font-black text-[#190704] transition-colors hover:bg-[#ff8a76]"
                        >
                            {action.label}
                        </Link>
                    )}
                    <button
                        type="button"
                        aria-label="메뉴 열기"
                        aria-expanded={menuOpen}
                        aria-controls="public-mobile-menu"
                        onClick={() => setMenuOpen((open) => !open)}
                        className="grid min-h-[44px] min-w-[44px] place-items-center rounded-lg border border-white/10 text-gray-300 md:hidden"
                    >
                        <i className={`fas ${menuOpen ? 'fa-xmark' : 'fa-bars'}`} aria-hidden />
                    </button>
                </div>
            </div>

            {menuOpen && (
                <nav id="public-mobile-menu" aria-label="모바일 공개 페이지" className="border-t border-white/[0.06] px-4 py-3 md:hidden">
                    <div className="mx-auto grid max-w-6xl grid-cols-2 gap-2">
                        {NAV_LINKS.map((item) => (
                            <a
                                key={item.to}
                                href={item.to}
                                onClick={() => setMenuOpen(false)}
                                className="flex min-h-[44px] items-center rounded-lg border border-white/[0.06] bg-white/[0.025] px-3 text-[13px] font-semibold text-gray-300"
                            >
                                {item.label}
                            </a>
                        ))}
                    </div>
                </nav>
            )}
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
                            Market<span className="text-[#ff6b57]">Flow</span>
                        </div>
                        <p className="mt-2 max-w-[34ch] text-[12px] leading-relaxed text-gray-500">
                            시장 데이터를 관찰하고 의미 있는 변화를 검출해 근거·품질·사후 기록과 함께 보여주는 AI 분석 서비스.
                        </p>
                    </div>
                    <div>
                        <div className="pub-label">서비스</div>
                        <ul className="mt-3 space-y-2 text-[12px]">
                            <li><a className="text-gray-500 transition-colors hover:text-[#ff9b89]" href="/#automation">자동화 파이프라인</a></li>
                            <li><a className="text-gray-500 transition-colors hover:text-[#ff9b89]" href="/#ai-brain">AI Brain</a></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/guide">인사이트 가이드</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/pricing">요금제</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/community">커뮤니티</Link></li>
                        </ul>
                    </div>
                    <div>
                        <div className="pub-label">정책 · 문의</div>
                        <ul className="mt-3 space-y-2 text-[12px]">
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/about">서비스 소개</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/privacy">개인정보처리방침</Link></li>
                            <li><Link className="text-gray-500 transition-colors hover:text-[#ff9b89]" to="/terms">이용약관</Link></li>
                            <li>
                                <a className="text-gray-500 transition-colors hover:text-[#ff9b89]" href="mailto:point10890@gmail.com">
                                    point10890@gmail.com
                                </a>
                            </li>
                        </ul>
                    </div>
                </div>
                <div className="mt-8 border-t border-white/[0.05] pt-5">
                    <p className="font-mono text-[10px] leading-relaxed text-gray-600">
                        DISCLOSURE — MarketFlow는 관찰·분석 정보를 제공하며 자동 주문이나 투자 자문을 수행하지 않습니다.
                        데이터 제공처와 네트워크 상황에 따라 갱신이 지연되거나 일부 기능이 일시 중단될 수 있습니다.
                        모든 정보는 투자 판단을 위한 참고 자료이며, 최종 결정과 책임은 투자자 본인에게 있습니다.
                        과거의 결과는 미래 수익을 보장하지 않습니다.
                    </p>
                    <p className="mt-3 text-[11px] text-gray-600">© {year} MarketFlow</p>
                </div>
            </div>
        </footer>
    );
}

/**
 * AdSense manual slot for public editorial/community pages. The conversion
 * landing intentionally does not render ads.
 */
export function AdSlot({ slot, className = '' }: { slot: string; className?: string }) {
    useEffect(() => {
        try {
            ((window as any).adsbygoogle = (window as any).adsbygoogle || []).push({});
        } catch { /* script unavailable or blocked */ }
    }, []);
    return (
        <div className={`pub-ad ${className}`} aria-label="advertisement">
            <span className="pub-ad-tag">AD</span>
            <ins
                className="adsbygoogle"
                style={{ display: 'block' }}
                data-ad-client="ca-pub-4268071335236139"
                data-ad-slot={slot}
                data-ad-format="auto"
                data-full-width-responsive="true"
            />
        </div>
    );
}
