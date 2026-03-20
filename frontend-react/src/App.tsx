import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from '@/contexts/AuthContext';
import DashboardLayout from '@/components/layout/DashboardLayout';
import LoginPage from '@/pages/auth/LoginPage';
import SignupPage from '@/pages/auth/SignupPage';
import PricingPage from '@/pages/static/PricingPage';
import LandingPage from '@/pages/LandingPage';

// Dashboard pages - lazy loaded
import { lazy, Suspense } from 'react';
const SummaryPage = lazy(() => import('@/pages/dashboard/SummaryPage'));
const VcpEnhancedPage = lazy(() => import('@/pages/dashboard/VcpEnhancedPage'));
const KrOverviewPage = lazy(() => import('@/pages/dashboard/kr/KrOverviewPage'));
const KrVcpPage = lazy(() => import('@/pages/dashboard/kr/KrVcpPage'));
const KrClosingBetPage = lazy(() => import('@/pages/dashboard/kr/KrClosingBetPage'));
const KrChatbotPage = lazy(() => import('@/pages/dashboard/kr/KrChatbotPage'));
const KrTrackRecordPage = lazy(() => import('@/pages/dashboard/kr/TrackRecordPage'));
const KrClosingBetHistoryPage = lazy(() => import('@/pages/dashboard/kr/ClosingBetHistoryPage'));
const UsOverviewPage = lazy(() => import('@/pages/dashboard/us/UsOverviewPage'));
const UsVcpPage = lazy(() => import('@/pages/dashboard/us/UsVcpPage'));
const UsEtfPage = lazy(() => import('@/pages/dashboard/us/UsEtfPage'));
const CryptoOverviewPage = lazy(() => import('@/pages/dashboard/crypto/CryptoOverviewPage'));
const CryptoSignalsPage = lazy(() => import('@/pages/dashboard/crypto/CryptoSignalsPage'));
const StockAnalyzerPage = lazy(() => import('@/pages/dashboard/StockAnalyzerPage'));
const DataStatusPage = lazy(() => import('@/pages/dashboard/DataStatusPage'));
const AdminPage = lazy(() => import('@/pages/admin/AdminPage'));
const AdminUsersPage = lazy(() => import('@/pages/admin/AdminUsersPage'));
const AdminSubscriptionsPage = lazy(() => import('@/pages/admin/AdminSubscriptionsPage'));
const AdminSystemPage = lazy(() => import('@/pages/admin/AdminSystemPage'));

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
                <Routes>
                    {/* Public routes */}
                    <Route path="/" element={<LandingPage />} />
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/signup" element={<SignupPage />} />
                    <Route path="/pricing" element={<PricingPage />} />

                    {/* Dashboard routes */}
                    <Route path="/dashboard" element={<DashboardLayout />}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><SummaryPage /></Suspense>} />
                        <Route path="vcp-enhanced" element={<Suspense fallback={<LoadingFallback />}><VcpEnhancedPage /></Suspense>} />
                        <Route path="kr" element={<Suspense fallback={<LoadingFallback />}><KrOverviewPage /></Suspense>} />
                        <Route path="kr/vcp" element={<Suspense fallback={<LoadingFallback />}><KrVcpPage /></Suspense>} />
                        <Route path="kr/closing-bet" element={<Suspense fallback={<LoadingFallback />}><KrClosingBetPage /></Suspense>} />
                        <Route path="kr/closing-bet/history" element={<Suspense fallback={<LoadingFallback />}><KrClosingBetHistoryPage /></Suspense>} />
                        <Route path="kr/chatbot" element={<Suspense fallback={<LoadingFallback />}><KrChatbotPage /></Suspense>} />
                        <Route path="kr/track-record" element={<Suspense fallback={<LoadingFallback />}><KrTrackRecordPage /></Suspense>} />
                        <Route path="us" element={<Suspense fallback={<LoadingFallback />}><UsOverviewPage /></Suspense>} />
                        <Route path="us/vcp" element={<Suspense fallback={<LoadingFallback />}><UsVcpPage /></Suspense>} />
                        <Route path="us/etf" element={<Suspense fallback={<LoadingFallback />}><UsEtfPage /></Suspense>} />
                        <Route path="crypto" element={<Suspense fallback={<LoadingFallback />}><CryptoOverviewPage /></Suspense>} />
                        <Route path="crypto/signals" element={<Suspense fallback={<LoadingFallback />}><CryptoSignalsPage /></Suspense>} />
                        <Route path="stock-analyzer" element={<Suspense fallback={<LoadingFallback />}><StockAnalyzerPage /></Suspense>} />
                        <Route path="data-status" element={<Suspense fallback={<LoadingFallback />}><DataStatusPage /></Suspense>} />
                    </Route>

                    {/* Admin routes */}
                    <Route path="/admin" element={<DashboardLayout />}>
                        <Route index element={<Suspense fallback={<LoadingFallback />}><AdminPage /></Suspense>} />
                        <Route path="users" element={<Suspense fallback={<LoadingFallback />}><AdminUsersPage /></Suspense>} />
                        <Route path="subscriptions" element={<Suspense fallback={<LoadingFallback />}><AdminSubscriptionsPage /></Suspense>} />
                        <Route path="system" element={<Suspense fallback={<LoadingFallback />}><AdminSystemPage /></Suspense>} />
                    </Route>

                    {/* Fallback */}
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
            </AuthProvider>
        </BrowserRouter>
    );
}
