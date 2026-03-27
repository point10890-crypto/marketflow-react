import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { NotificationProvider } from '@/contexts/NotificationContext';
import DashboardLayout from '@/components/layout/DashboardLayout';
import LoginPage from '@/pages/auth/LoginPage';
import SignupPage from '@/pages/auth/SignupPage';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import PricingPage from '@/pages/static/PricingPage';
import LandingPage from '@/pages/LandingPage';

// Dashboard pages - lazy loaded
import { lazy, Suspense, Component, type ReactNode } from 'react';

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
    constructor(props: { children: ReactNode }) {
        super(props);
        this.state = { hasError: false };
    }
    static getDerivedStateFromError() { return { hasError: true }; }
    componentDidCatch(error: Error) { console.error('[ErrorBoundary]', error); }
    render() {
        if (this.state.hasError) {
            return (
                <div className="flex items-center justify-center h-full min-h-[400px]">
                    <div className="text-center p-8">
                        <i className="fas fa-exclamation-triangle text-amber-400 text-3xl mb-4 block"></i>
                        <h2 className="text-white text-lg font-bold mb-2">오류가 발생했습니다</h2>
                        <p className="text-gray-400 text-sm mb-4">페이지를 새로고침 해주세요</p>
                        <button onClick={() => window.location.reload()} className="px-4 py-2 bg-amber-500 text-black rounded-lg font-bold text-sm">새로고침</button>
                    </div>
                </div>
            );
        }
        return this.props.children;
    }
}
const SummaryPage = lazy(() => import('@/pages/dashboard/SummaryPage'));
const VcpEnhancedPage = lazy(() => import('@/pages/dashboard/VcpEnhancedPage'));
const KrOverviewPage = lazy(() => import('@/pages/dashboard/kr/KrOverviewPage'));
const KrVcpPage = lazy(() => import('@/pages/dashboard/kr/KrVcpPage'));
const KrClosingBetPage = lazy(() => import('@/pages/dashboard/kr/KrClosingBetPage'));
const KrChatbotPage = lazy(() => import('@/pages/dashboard/kr/KrChatbotPage'));
const KrTrackRecordPage = lazy(() => import('@/pages/dashboard/kr/TrackRecordPage'));
const KrClosingBetHistoryPage = lazy(() => import('@/pages/dashboard/kr/ClosingBetHistoryPage'));
const KrLeadingStocksPage = lazy(() => import('@/pages/dashboard/kr/KrLeadingStocksPage'));
const UsOverviewPage = lazy(() => import('@/pages/dashboard/us/UsOverviewPage'));
const UsVcpPage = lazy(() => import('@/pages/dashboard/us/UsVcpPage'));
const UsEtfPage = lazy(() => import('@/pages/dashboard/us/UsEtfPage'));
const CryptoOverviewPage = lazy(() => import('@/pages/dashboard/crypto/CryptoOverviewPage'));
const CryptoSignalsPage = lazy(() => import('@/pages/dashboard/crypto/CryptoSignalsPage'));
const StockAnalyzerPage = lazy(() => import('@/pages/dashboard/StockAnalyzerPage'));
const WaveOverviewPage = lazy(() => import('@/pages/dashboard/wave/WaveOverviewPage'));
const DataStatusPage = lazy(() => import('@/pages/dashboard/DataStatusPage'));
const AdminPage = lazy(() => import('@/pages/admin/AdminPage'));
const AdminUsersPage = lazy(() => import('@/pages/admin/AdminUsersPage'));
const AdminSubscriptionsPage = lazy(() => import('@/pages/admin/AdminSubscriptionsPage'));
const AdminSystemPage = lazy(() => import('@/pages/admin/AdminSystemPage'));

function ApprovedGuard({ children }: { children: React.ReactNode }) {
    const { user } = useAuth();
    // No user (not logged in) → allow access (auth may be disabled / public mode)
    if (!user) return <>{children}</>;
    // Admin always passes
    if (user.role === 'admin') return <>{children}</>;
    // Pending/rejected/suspended → redirect to approval page
    if (user.status !== 'approved') return <Navigate to="/pending-approval" replace />;
    return <>{children}</>;
}

function AdminGuard({ children }: { children: React.ReactNode }) {
    const { user } = useAuth();
    // Initial render: user state not yet hydrated from localStorage
    // Check localStorage directly to avoid flash redirect
    if (!user) {
        try {
            const stored = localStorage.getItem('auth_user');
            if (stored) {
                const parsed = JSON.parse(stored);
                if (parsed.role === 'admin') return <>{children}</>;
            }
        } catch { /* ignore */ }
        return <Navigate to="/dashboard" replace />;
    }
    if (user.role !== 'admin') return <Navigate to="/dashboard" replace />;
    return <>{children}</>;
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
                    <Route path="/pricing" element={<PricingPage />} />
                    <Route path="/pending-approval" element={<PendingApprovalPage />} />

                    {/* Dashboard routes (ApprovedGuard blocks pending users) */}
                    <Route path="/dashboard" element={<ErrorBoundary><ApprovedGuard><DashboardLayout /></ApprovedGuard></ErrorBoundary>}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><SummaryPage /></Suspense>} />
                        <Route path="vcp-enhanced" element={<Suspense fallback={<LoadingFallback />}><VcpEnhancedPage /></Suspense>} />
                        <Route path="kr" element={<Suspense fallback={<LoadingFallback />}><KrOverviewPage /></Suspense>} />
                        <Route path="kr/vcp" element={<Suspense fallback={<LoadingFallback />}><KrVcpPage /></Suspense>} />
                        <Route path="kr/closing-bet" element={<Suspense fallback={<LoadingFallback />}><KrClosingBetPage /></Suspense>} />
                        <Route path="kr/closing-bet/history" element={<Suspense fallback={<LoadingFallback />}><KrClosingBetHistoryPage /></Suspense>} />
                        <Route path="kr/leading-stocks" element={<Suspense fallback={<LoadingFallback />}><KrLeadingStocksPage /></Suspense>} />
                        <Route path="kr/chatbot" element={<Suspense fallback={<LoadingFallback />}><KrChatbotPage /></Suspense>} />
                        <Route path="kr/track-record" element={<Suspense fallback={<LoadingFallback />}><KrTrackRecordPage /></Suspense>} />
                        <Route path="us" element={<Suspense fallback={<LoadingFallback />}><UsOverviewPage /></Suspense>} />
                        <Route path="us/vcp" element={<Suspense fallback={<LoadingFallback />}><UsVcpPage /></Suspense>} />
                        <Route path="us/etf" element={<Suspense fallback={<LoadingFallback />}><UsEtfPage /></Suspense>} />
                        <Route path="crypto" element={<Suspense fallback={<LoadingFallback />}><CryptoOverviewPage /></Suspense>} />
                        <Route path="crypto/signals" element={<Suspense fallback={<LoadingFallback />}><CryptoSignalsPage /></Suspense>} />
                        <Route path="stock-analyzer" element={<Suspense fallback={<LoadingFallback />}><StockAnalyzerPage /></Suspense>} />
                        <Route path="wave" element={<Suspense fallback={<LoadingFallback />}><WaveOverviewPage /></Suspense>} />
                    </Route>

                    {/* Admin routes */}
                    <Route path="/admin" element={<AdminGuard><DashboardLayout /></AdminGuard>}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><AdminPage /></Suspense>} />
                        <Route path="data-status" element={<Suspense fallback={<LoadingFallback />}><DataStatusPage /></Suspense>} />
                        <Route path="users" element={<Suspense fallback={<LoadingFallback />}><AdminUsersPage /></Suspense>} />
                        <Route path="subscriptions" element={<Suspense fallback={<LoadingFallback />}><AdminSubscriptionsPage /></Suspense>} />
                        <Route path="system" element={<Suspense fallback={<LoadingFallback />}><AdminSystemPage /></Suspense>} />
                    </Route>

                    {/* 404 Not Found */}
                    <Route path="*" element={
                        <div className="flex items-center justify-center min-h-screen bg-[#09090b] text-white">
                            <div className="text-center px-6">
                                <div className="text-6xl font-black text-amber-500 mb-4">404</div>
                                <h1 className="text-xl font-bold mb-2">페이지를 찾을 수 없습니다</h1>
                                <p className="text-gray-500 text-sm mb-6">요청하신 페이지가 존재하지 않거나 이동되었습니다.</p>
                                <a href="/dashboard" className="inline-block px-6 py-3 bg-amber-500 text-black font-bold rounded-xl hover:bg-amber-400 transition-colors">
                                    대시보드로 이동
                                </a>
                            </div>
                        </div>
                    } />
                </Routes>
            </NotificationProvider>
            </AuthProvider>
        </BrowserRouter>
    );
}
