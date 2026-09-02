import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { canAccessAiBain, subscriptionFunnelTarget } from '@/lib/auth';
import { useSeo } from '@/lib/seo';
import { NotificationProvider } from '@/contexts/NotificationContext';
import DashboardLayout from '@/components/layout/DashboardLayout';
import LoginPage from '@/pages/auth/LoginPage';
import SignupPage from '@/pages/auth/SignupPage';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import PaymentRequestPage from '@/pages/auth/PaymentRequestPage';
import PricingPage from '@/pages/static/PricingPage';
import LandingPage from '@/pages/LandingPage';

// Dashboard pages - lazy loaded
import { lazy, Suspense, useLayoutEffect } from 'react';

function DocumentScrollReset() {
    const { pathname } = useLocation();

    useLayoutEffect(() => {
        const scroller = document.scrollingElement ?? document.documentElement;
        scroller.scrollTop = 0;
        scroller.scrollLeft = 0;
    }, [pathname]);

    return null;
}

// 에러 경계는 DashboardLayout 안 <Outlet /> 주변(PageErrorBoundary)으로 이동.
// 이렇게 두면 한 페이지가 터져도 사이드바·네비·다른 페이지 진입은 살아 있음.
const SummaryPage = lazy(() => import('@/pages/dashboard/SummaryPage'));
const VcpEnhancedPage = lazy(() => import('@/pages/dashboard/VcpEnhancedPage'));
const KrOverviewPage = lazy(() => import('@/pages/dashboard/kr/KrOverviewPage'));
const KrVcpPage = lazy(() => import('@/pages/dashboard/kr/KrVcpPage'));
const KrClosingBetPage = lazy(() => import('@/pages/dashboard/kr/KrClosingBetPage'));
const KrChatbotPage = lazy(() => import('@/pages/dashboard/kr/KrChatbotPage'));
const KrTrackRecordPage = lazy(() => import('@/pages/dashboard/kr/TrackRecordPage'));
const KrClosingBetHistoryPage = lazy(() => import('@/pages/dashboard/kr/ClosingBetHistoryPage'));
const KrLeadingStocksPage = lazy(() => import('@/pages/dashboard/kr/KrLeadingStocksPage'));
const KrClawPage = lazy(() => import('@/pages/dashboard/kr/claw/KrClawPage'));
const KrAIChartAnalysisPage = lazy(() => import('@/pages/dashboard/kr/AIChartAnalysisPage'));
const UsOverviewPage = lazy(() => import('@/pages/dashboard/us/UsOverviewPage'));
const UsVcpPage = lazy(() => import('@/pages/dashboard/us/UsVcpPage'));
const UsEtfPage = lazy(() => import('@/pages/dashboard/us/UsEtfPage'));
const UsAIChartPage = lazy(() => import('@/pages/dashboard/us/UsAIChartPage'));
const AiBainPage = lazy(() => import('@/pages/dashboard/AiBainPage'));
const GoodrichFundManagerPage = lazy(() => import('@/pages/dashboard/aibain/GoodrichFundManagerPage'));
const DecisionBriefPage = lazy(() => import('@/pages/dashboard/aibain/DecisionBriefPage'));
const CryptoOverviewPage = lazy(() => import('@/pages/dashboard/crypto/CryptoOverviewPage'));
const CryptoSignalsPage = lazy(() => import('@/pages/dashboard/crypto/CryptoSignalsPage'));
const StockAnalyzerPage = lazy(() => import('@/pages/dashboard/StockAnalyzerPage'));
const ManualStockAnalysisPage = lazy(() => import('@/pages/dashboard/ManualStockAnalysisPage'));
const WaveOverviewPage = lazy(() => import('@/pages/dashboard/wave/WaveOverviewPage'));
const BriefingPortalPage = lazy(() => import('@/pages/dashboard/BriefingPortalPage'));
const AccountPage = lazy(() => import('@/pages/AccountPage'));
const DataStatusPage = lazy(() => import('@/pages/dashboard/DataStatusPage'));
const AdminPage = lazy(() => import('@/pages/admin/AdminPage'));
const AdminEndpointsPage = lazy(() => import('@/pages/admin/AdminEndpointsPage'));
const CommunityPage = lazy(() => import('@/pages/community/CommunityPage'));
const BoardPage = lazy(() => import('@/pages/community/BoardPage'));
const PostDetailPage = lazy(() => import('@/pages/community/PostDetailPage'));
const PostWritePage = lazy(() => import('@/pages/community/PostWritePage'));
const FormulaWritePage = lazy(() => import('@/pages/community/FormulaWritePage'));
const FormulaListPage = lazy(() => import('@/pages/community/FormulaListPage'));
const PurchaseAdminPage = lazy(() => import('@/pages/community/PurchaseAdminPage'));
// 공개(비로그인) 영역 — AdSense 심사용 공개 콘텐츠 + 정책 페이지
const PublicCommunityPage = lazy(() => import('@/pages/public/PublicCommunityPage'));
const PublicPostPage = lazy(() => import('@/pages/public/PublicPostPage'));
const GuideListPage = lazy(() => import('@/pages/public/GuidePages').then(m => ({ default: m.GuideListPage })));
const GuideArticlePage = lazy(() => import('@/pages/public/GuidePages').then(m => ({ default: m.GuideArticlePage })));
const PrivacyPage = lazy(() => import('@/pages/static/PolicyPages').then(m => ({ default: m.PrivacyPage })));
const TermsPage = lazy(() => import('@/pages/static/PolicyPages').then(m => ({ default: m.TermsPage })));
const AboutPage = lazy(() => import('@/pages/static/PolicyPages').then(m => ({ default: m.AboutPage })));

// Unified app access gate: login → approved status → pro/premium tier.
// New signups land in /pending-approval until an admin assigns them a paid tier.
//
// status='unknown' = AuthContext synthesized a placeholder from token alone;
// real user info hasn't loaded yet. Show LoadingFallback (do NOT redirect)
// so existing logged-in users never see a flicker bounce to /login or
// /pending-approval during page hydration.
// 미인증 방문자 착지 경로: 이 기기에서 로그인한 이력이 있으면 /login (재로그인 유도),
// 없으면 랜딩 / (앱 소개 + 가입 유도). 비가입자가 /dashboard 등 아무 보호 경로로
// 들어와도 가입/로그인 경로로 자연스럽게 흐르게 하는 핵심 분기.
function unauthRedirect(): string {
    try {
        return localStorage.getItem('auth_has_logged_in_before') === 'true' ? '/login' : '/';
    } catch {
        return '/';
    }
}

export function ApprovedGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    const location = useLocation();
    const next = `${location.pathname}${location.search || ''}`;
    if (loading) return <LoadingFallback />;
    if (!user) return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
    // 'unknown' = 토큰만 있고 /api/auth/me 미응답 (오프라인/백엔드 다운 포함) — 위 설계 주석대로
    // 리다이렉트하지 않고 로딩만 보여준다. 유효 토큰 유저를 /login 으로 튕기면 안 된다.
    if (user.status === 'unknown') return <LoadingFallback />;
    if (user.role === 'admin') return <>{children}</>;
    // 만료 → 재구독 / 노티어 → 플랜 선택 / 승인 대기 → pending-approval.
    // 판정 기준은 subscriptionFunnelTarget 한 곳 (FunnelGate·404 CTA 와 공유).
    const funnel = subscriptionFunnelTarget(user);
    if (funnel) return <Navigate to={funnel} replace />;
    return <>{children}</>;
}

// ProGuard 는 ApprovedGuard 와 판정이 동일해졌다 (활성 Pro/Ultra Pro 또는 admin 만 통과).
// 라우트 표기 호환을 위해 별칭으로 유지.
const ProGuard = ApprovedGuard;

// 공개 라우트용 게이트 — 랜딩/공개 커뮤니티/가이드/프라이싱에 로그인한 "비구독 회원"
// (노티어·만료·승인대기)이 들어오면 구독 퍼널로 돌려보낸다. 비로그인 방문자와
// 활성 구독자·admin 은 그대로 열람 (AdSense 크롤러는 비로그인이므로 영향 없음).
function FunnelGate({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    // 공개 페이지는 로딩 중에도 콘텐츠를 먼저 보여준다 (비로그인 방문자 지연 금지).
    const target = loading ? null : subscriptionFunnelTarget(user);
    if (target) return <Navigate to={target} replace />;
    return <>{children}</>;
}

// AI Brain 섹션 가드 — 활성 AI Brain 애드온 구독자 또는 admin 만 통과 (canAccessAiBain).
// ProGuard 안쪽에 중첩해 쓴다 (로그인/만료 판정은 ProGuard 가 먼저). 그 외 유저는
// /dashboard/ai-bain 으로 보내 AiBainPage 의 신청/재구독 안내(UpgradePrompt)를 보게 한다.
function AiBainGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    if (loading) return <LoadingFallback />;
    if (canAccessAiBain(user)) return <>{children}</>;
    return <Navigate to="/dashboard/ai-bain" replace />;
}

function AdminGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    const location = useLocation();
    const next = `${location.pathname}${location.search || ''}`;
    if (loading) return <LoadingFallback />;
    if (!user) return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
    if (user.status === 'unknown') return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
    if (user.role !== 'admin') return <Navigate to="/dashboard" replace />;
    return <>{children}</>;
}

// 404 — 미인증 방문자는 랜딩/로그인으로, 인증 유저는 대시보드로 CTA 차별화.
// 비가입자가 아무 URL 이나 쳐도 가입 플로우로 자연스럽게 흐르게 하기 위함.
function NotFoundPage() {
    useSeo({ title: '페이지를 찾을 수 없습니다 | MarketFlow', noindex: true });
    const { user } = useAuth();
    // 비구독 회원은 404 에서도 구독 퍼널로 — "아무 페이지나 들어가도 구독 신청으로" 원칙
    const funnel = user ? subscriptionFunnelTarget(user) : null;
    const target = user ? (funnel ?? '/dashboard') : unauthRedirect();
    const label = user
        ? (funnel ? '구독 신청으로 이동' : '대시보드로 이동')
        : (target === '/login' ? '로그인' : '앱 소개 · 가입');
    return (
        <div className="flex min-h-[100dvh] items-center justify-center bg-[#09090b] text-white">
            <div className="text-center px-6">
                <div className="text-6xl font-black text-amber-500 mb-4">404</div>
                <h1 className="text-xl font-bold mb-2">페이지를 찾을 수 없습니다</h1>
                <p className="text-gray-500 text-sm mb-6">요청하신 페이지가 존재하지 않거나 이동되었습니다.</p>
                <a href={target} className="inline-block px-6 py-3 bg-amber-500 text-black font-bold rounded-xl hover:bg-amber-400 transition-colors">
                    {label}
                </a>
            </div>
        </div>
    );
}

function LoadingFallback() {
    return (
        <div className="flex items-center justify-center h-full min-h-[400px]">
            <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span className="text-white/50 text-sm">Loading...</span>
            </div>
        </div>
    );
}

export default function App() {
    return (
        <BrowserRouter>
            <DocumentScrollReset />
            <AuthProvider>
            <NotificationProvider>
                <Routes>
                    {/* Public routes — FunnelGate: 로그인한 비구독 회원(노티어·만료·승인대기)은
                        공개 페이지에 머물지 않고 구독 퍼널로 리다이렉트 (비로그인·활성 구독자·admin 은 그대로) */}
                    <Route path="/" element={<FunnelGate><LandingPage /></FunnelGate>} />
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/signup" element={<SignupPage />} />
                    {/* 구독 신청 3단계 플로우 — 신규 가입 + 만료 재구독 공용 */}
                    <Route path="/plan-select" element={<PlanSelectPage />} />
                    <Route path="/payment-request" element={<PaymentRequestPage />} />
                    <Route path="/pricing" element={<FunnelGate><PricingPage /></FunnelGate>} />
                    <Route path="/pending-approval" element={<PendingApprovalPage />} />

                    {/* 공개(비로그인) 영역 — 커뮤니티 열람 + 정책 페이지.
                        정책 3종(privacy/terms/about)은 법적 고지라 FunnelGate 를 걸지 않는다. */}
                    <Route path="/community" element={<FunnelGate><Suspense fallback={<LoadingFallback />}><PublicCommunityPage /></Suspense></FunnelGate>} />
                    <Route path="/community/post/:postId" element={<FunnelGate><Suspense fallback={<LoadingFallback />}><PublicPostPage /></Suspense></FunnelGate>} />
                    <Route path="/community/:board" element={<FunnelGate><Suspense fallback={<LoadingFallback />}><PublicCommunityPage /></Suspense></FunnelGate>} />
                    <Route path="/guide" element={<FunnelGate><Suspense fallback={<LoadingFallback />}><GuideListPage /></Suspense></FunnelGate>} />
                    <Route path="/guide/:slug" element={<FunnelGate><Suspense fallback={<LoadingFallback />}><GuideArticlePage /></Suspense></FunnelGate>} />
                    <Route path="/privacy" element={<Suspense fallback={<LoadingFallback />}><PrivacyPage /></Suspense>} />
                    <Route path="/terms" element={<Suspense fallback={<LoadingFallback />}><TermsPage /></Suspense>} />
                    <Route path="/about" element={<Suspense fallback={<LoadingFallback />}><AboutPage /></Suspense>} />

                    {/* Dashboard routes (ApprovedGuard blocks pending users) */}
                    <Route path="/dashboard" element={<ApprovedGuard><DashboardLayout /></ApprovedGuard>}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><SummaryPage /></Suspense>} />
                        <Route path="account" element={<Suspense fallback={<LoadingFallback />}><AccountPage /></Suspense>} />
                        <Route path="vcp-enhanced" element={<ProGuard><Suspense fallback={<LoadingFallback />}><VcpEnhancedPage /></Suspense></ProGuard>} />
                        <Route path="kr" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrOverviewPage /></Suspense></ProGuard>} />
                        <Route path="kr/vcp" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrVcpPage /></Suspense></ProGuard>} />
                        <Route path="kr/closing-bet" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrClosingBetPage /></Suspense></ProGuard>} />
                        <Route path="kr/closing-bet/history" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrClosingBetHistoryPage /></Suspense></ProGuard>} />
                        <Route path="kr/leading-stocks" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrLeadingStocksPage /></Suspense></ProGuard>} />
                        <Route path="kr/claw" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrClawPage /></Suspense></ProGuard>} />
                        <Route path="kr/chatbot" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrChatbotPage /></Suspense></ProGuard>} />
                        <Route path="kr/track-record" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrTrackRecordPage /></Suspense></ProGuard>} />
                        <Route path="kr/ai-chart" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrAIChartAnalysisPage /></Suspense></ProGuard>} />
                        <Route path="us" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsOverviewPage /></Suspense></ProGuard>} />
                        <Route path="us/vcp" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsVcpPage /></Suspense></ProGuard>} />
                        <Route path="us/etf" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsEtfPage /></Suspense></ProGuard>} />
                        <Route path="us/ai-chart" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsAIChartPage /></Suspense></ProGuard>} />
                        <Route path="ai-bain/decision" element={<ProGuard><AiBainGuard><Suspense fallback={<LoadingFallback />}><DecisionBriefPage /></Suspense></AiBainGuard></ProGuard>} />
                        <Route path="ai-bain/goodrich" element={<ProGuard><AiBainGuard><Suspense fallback={<LoadingFallback />}><GoodrichFundManagerPage /></Suspense></AiBainGuard></ProGuard>} />
                        <Route path="ai-bain" element={<ProGuard><Suspense fallback={<LoadingFallback />}><AiBainPage /></Suspense></ProGuard>} />
                        <Route path="crypto" element={<ProGuard><Suspense fallback={<LoadingFallback />}><CryptoOverviewPage /></Suspense></ProGuard>} />
                        <Route path="crypto/signals" element={<ProGuard><Suspense fallback={<LoadingFallback />}><CryptoSignalsPage /></Suspense></ProGuard>} />
                        <Route path="stock-analyzer" element={<ProGuard><Suspense fallback={<LoadingFallback />}><StockAnalyzerPage /></Suspense></ProGuard>} />
                        <Route path="manual-stock-analysis" element={<ProGuard><Suspense fallback={<LoadingFallback />}><ManualStockAnalysisPage /></Suspense></ProGuard>} />
                        <Route path="wave" element={<ProGuard><Suspense fallback={<LoadingFallback />}><WaveOverviewPage /></Suspense></ProGuard>} />
                        <Route path="briefing" element={<ProGuard><Suspense fallback={<LoadingFallback />}><BriefingPortalPage /></Suspense></ProGuard>} />
                        <Route path="community" element={<Suspense fallback={<LoadingFallback />}><CommunityPage /></Suspense>} />
                        <Route path="community/formula-market" element={<Suspense fallback={<LoadingFallback />}><FormulaListPage /></Suspense>} />
                        <Route path="community/formula-market/purchases" element={<AdminGuard><Suspense fallback={<LoadingFallback />}><PurchaseAdminPage /></Suspense></AdminGuard>} />
                        <Route path="community/formula-market/write" element={<Suspense fallback={<LoadingFallback />}><FormulaWritePage /></Suspense>} />
                        <Route path="community/post/:postId" element={<Suspense fallback={<LoadingFallback />}><PostDetailPage /></Suspense>} />
                        <Route path="community/post/:postId/edit" element={<Suspense fallback={<LoadingFallback />}><PostWritePage /></Suspense>} />
                        <Route path="community/:boardSlug" element={<Suspense fallback={<LoadingFallback />}><BoardPage /></Suspense>} />
                        <Route path="community/:boardSlug/write" element={<Suspense fallback={<LoadingFallback />}><PostWritePage /></Suspense>} />
                    </Route>

                    {/* Admin routes */}
                    <Route path="/admin" element={<AdminGuard><DashboardLayout /></AdminGuard>}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><AdminPage /></Suspense>} />
                        <Route path="data-status" element={<Suspense fallback={<LoadingFallback />}><DataStatusPage /></Suspense>} />
                        <Route path="endpoints" element={<Suspense fallback={<LoadingFallback />}><AdminEndpointsPage /></Suspense>} />
                        <Route path="users" element={<Navigate to="/admin" replace />} />
                        <Route path="subscriptions" element={<Navigate to="/admin" replace />} />
                        <Route path="system" element={<Navigate to="/admin" replace />} />
                    </Route>

                    {/* 404 — 미인증자/인증자 분기 CTA */}
                    <Route path="*" element={<NotFoundPage />} />
                </Routes>
            </NotificationProvider>
            </AuthProvider>
        </BrowserRouter>
    );
}
