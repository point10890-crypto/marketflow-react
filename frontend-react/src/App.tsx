import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
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
import { lazy, Suspense } from 'react';

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
const KrAIChartAnalysisPage = lazy(() => import('@/pages/dashboard/kr/AIChartAnalysisPage'));
const UsOverviewPage = lazy(() => import('@/pages/dashboard/us/UsOverviewPage'));
const UsVcpPage = lazy(() => import('@/pages/dashboard/us/UsVcpPage'));
const UsEtfPage = lazy(() => import('@/pages/dashboard/us/UsEtfPage'));
const UsAIChartPage = lazy(() => import('@/pages/dashboard/us/UsAIChartPage'));
const CryptoOverviewPage = lazy(() => import('@/pages/dashboard/crypto/CryptoOverviewPage'));
const CryptoSignalsPage = lazy(() => import('@/pages/dashboard/crypto/CryptoSignalsPage'));
const StockAnalyzerPage = lazy(() => import('@/pages/dashboard/StockAnalyzerPage'));
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

function ApprovedGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    if (loading) return <LoadingFallback />;
    if (!user) return <Navigate to={unauthRedirect()} replace />;
    if (user.status === 'unknown') return <LoadingFallback />;
    if (user.role === 'admin') return <>{children}</>;
    // Pro 만료 → 계정 정지 상태. 재구독 페이지로 안내.
    if (user.status === 'expired' || user.is_pro_expired) {
        return <Navigate to="/plan-select?resubscribe=1&from=expired" replace />;
    }
    if (user.status !== 'approved') return <Navigate to="/pending-approval" replace />;
    if (user.tier !== 'pro' && user.tier !== 'premium') return <Navigate to="/pending-approval" replace />;
    return <>{children}</>;
}

function ProGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    if (loading) return <LoadingFallback />;
    if (!user) return <Navigate to={unauthRedirect()} replace />;
    if (user.status === 'unknown') return <LoadingFallback />;
    if (user.role === 'admin') return <>{children}</>;
    // 만료 우선 — 계정 정지 상태로 간주 → 재구독
    if (user.status === 'expired' || user.is_pro_expired) {
        return <Navigate to="/plan-select?resubscribe=1&from=expired" replace />;
    }
    if (user.tier === 'pro' || user.tier === 'premium') {
        return <>{children}</>;
    }
    // 미구독 pending 유저는 플랜 선택 페이지로
    return <Navigate to="/plan-select" replace />;
}

function AdminGuard({ children }: { children: React.ReactNode }) {
    const { user, loading } = useAuth();
    if (loading) return <LoadingFallback />;
    if (!user) return <Navigate to={unauthRedirect()} replace />;
    if (user.status === 'unknown') return <LoadingFallback />;
    if (user.role !== 'admin') return <Navigate to="/dashboard" replace />;
    return <>{children}</>;
}

// 404 — 미인증 방문자는 랜딩/로그인으로, 인증 유저는 대시보드로 CTA 차별화.
// 비가입자가 아무 URL 이나 쳐도 가입 플로우로 자연스럽게 흐르게 하기 위함.
function NotFoundPage() {
    const { user } = useAuth();
    const target = user ? '/dashboard' : unauthRedirect();
    const label = user
        ? '대시보드로 이동'
        : (target === '/login' ? '로그인' : '앱 소개 · 가입');
    return (
        <div className="flex items-center justify-center min-h-screen bg-[#09090b] text-white">
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
            <AuthProvider>
            <NotificationProvider>
                <Routes>
                    {/* Public routes */}
                    <Route path="/" element={<LandingPage />} />
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/signup" element={<SignupPage />} />
                    {/* 구독 신청 3단계 플로우 — 신규 가입 + 만료 재구독 공용 */}
                    <Route path="/plan-select" element={<PlanSelectPage />} />
                    <Route path="/payment-request" element={<PaymentRequestPage />} />
                    <Route path="/pricing" element={<PricingPage />} />
                    <Route path="/pending-approval" element={<PendingApprovalPage />} />

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
                        <Route path="kr/chatbot" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrChatbotPage /></Suspense></ProGuard>} />
                        <Route path="kr/track-record" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrTrackRecordPage /></Suspense></ProGuard>} />
                        <Route path="kr/ai-chart" element={<ProGuard><Suspense fallback={<LoadingFallback />}><KrAIChartAnalysisPage /></Suspense></ProGuard>} />
                        <Route path="us" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsOverviewPage /></Suspense></ProGuard>} />
                        <Route path="us/vcp" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsVcpPage /></Suspense></ProGuard>} />
                        <Route path="us/etf" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsEtfPage /></Suspense></ProGuard>} />
                        <Route path="us/ai-chart" element={<ProGuard><Suspense fallback={<LoadingFallback />}><UsAIChartPage /></Suspense></ProGuard>} />
                        <Route path="crypto" element={<ProGuard><Suspense fallback={<LoadingFallback />}><CryptoOverviewPage /></Suspense></ProGuard>} />
                        <Route path="crypto/signals" element={<ProGuard><Suspense fallback={<LoadingFallback />}><CryptoSignalsPage /></Suspense></ProGuard>} />
                        <Route path="stock-analyzer" element={<ProGuard><Suspense fallback={<LoadingFallback />}><StockAnalyzerPage /></Suspense></ProGuard>} />
                        <Route path="wave" element={<ProGuard><Suspense fallback={<LoadingFallback />}><WaveOverviewPage /></Suspense></ProGuard>} />
                        <Route path="briefing" element={<ProGuard><Suspense fallback={<LoadingFallback />}><BriefingPortalPage /></Suspense></ProGuard>} />
                        <Route path="community" element={<Suspense fallback={<LoadingFallback />}><CommunityPage /></Suspense>} />
                        <Route path="community/:boardSlug" element={<Suspense fallback={<LoadingFallback />}><BoardPage /></Suspense>} />
                        <Route path="community/formula-market" element={<Suspense fallback={<LoadingFallback />}><FormulaListPage /></Suspense>} />
                        <Route path="community/formula-market/purchases" element={<Suspense fallback={<LoadingFallback />}><PurchaseAdminPage /></Suspense>} />
                        <Route path="community/formula-market/write" element={<Suspense fallback={<LoadingFallback />}><FormulaWritePage /></Suspense>} />
                        <Route path="community/:boardSlug/write" element={<Suspense fallback={<LoadingFallback />}><PostWritePage /></Suspense>} />
                        <Route path="community/post/:postId" element={<Suspense fallback={<LoadingFallback />}><PostDetailPage /></Suspense>} />
                        <Route path="community/post/:postId/edit" element={<Suspense fallback={<LoadingFallback />}><PostWritePage /></Suspense>} />
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
