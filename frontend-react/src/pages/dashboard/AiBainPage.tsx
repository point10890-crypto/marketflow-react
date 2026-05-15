import { lazy, Suspense } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

// 관리자 페이지의 MiroFish Market Brain GraphRAG Analysis 콘솔을 그대로 재사용.
// AutoRunner / QuickActions 만 subscriberMode 로 자동 숨김 (admin 전용 컨트롤).
const AdminEndpointsPage = lazy(() => import('@/pages/admin/AdminEndpointsPage'));

/**
 * Pro + AI Bain 구독자 전용 페이지.
 *
 * 라우트: /dashboard/ai-bain (ProGuard 보호)
 *
 * 가시성 분기:
 *  - admin (또는 활성 AI Bain) → 관리자 콘솔의 풀 그래프RAG Analysis 렌더 (subscriberMode)
 *  - 활성 Pro/Ultra Pro 비AI Bain → "AI Bain 구독 업그레이드" 안내 (+40,000원/30일)
 *  - 그 외 → "구독 신청" CTA → /pricing
 *
 * 본 페이지는 admin 페이지(/admin/endpoints) 의 분석 컨텐츠 (Alpha Board, Brain Signal,
 * Verdict, GraphRAG, Scan History, Recent Outcomes 등) 를 모두 노출하되,
 * 운영자 전용 컨트롤 (AutoRunner: 강제 발사 / 일시정지 / 서킷 리셋 / 카운터 리셋 /
 * LLM 임계값 추천 + QuickActionsFooter) 만 제외합니다.
 */
export default function AiBainPage() {
    const { user } = useAuth();
    const tier = user?.tier ?? null;
    const role = user?.role ?? 'user';
    const isAdmin = role === 'admin';
    const hasProBase = tier === 'pro' || tier === 'premium';
    const showFullDashboard = isAdmin; // TODO Stage 5: || user.is_aibain_active
    const showUpgradeFlow = !isAdmin && hasProBase;

    // ── admin (또는 활성 AI Bain) → 풀 콘솔 ─────────────────────────────────────
    if (showFullDashboard) {
        return (
            <Suspense fallback={<DashboardLoading />}>
                <AdminEndpointsPage subscriberMode />
            </Suspense>
        );
    }

    // ── 활성 Pro / Ultra Pro → 업그레이드 안내 ─────────────────────────────────
    if (showUpgradeFlow) {
        return <UpgradePrompt tier={tier} />;
    }

    // ── 미가입 / 비구독 → 구독 신청 CTA ────────────────────────────────────────
    return <SubscribePrompt />;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function DashboardLoading() {
    return (
        <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
            <div className="text-center">
                <i className="fas fa-spinner fa-spin text-cyan-400 text-2xl mb-3" />
                <p className="text-sm text-gray-400">AI Bain 알파 스캐너 콘솔 불러오는 중...</p>
            </div>
        </div>
    );
}

function PageShell({ children }: { children: React.ReactNode }) {
    return (
        <div className="min-h-screen bg-[#09090b] text-white p-4 sm:p-6 lg:p-8">
            <div className="max-w-6xl mx-auto space-y-6">
                {/* 공통 헤더 (admin 모드일 때는 admin 페이지 자체 헤더가 표시되므로 여기는 사용 X) */}
                <div className="rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-cyan-500/[0.06] via-[#13151f] to-[#1c1c1e] p-6 sm:p-8 relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-cyan-500/10 to-transparent rounded-bl-full pointer-events-none" />
                    <div className="relative flex items-start gap-4">
                        <div className="grid h-14 w-14 sm:h-16 sm:w-16 shrink-0 place-items-center rounded-2xl bg-cyan-500/15 text-cyan-300 text-3xl">
                            <i className="fas fa-robot" />
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                                <h1 className="text-2xl sm:text-3xl font-black tracking-tight">AI Bain 알파 스캐너</h1>
                                <span className="inline-flex items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-black text-cyan-300 uppercase tracking-wider">
                                    <i className="fas fa-bolt text-[10px]" />
                                    ALPHA SCAN
                                </span>
                            </div>
                            <p className="mt-2 text-sm sm:text-base text-gray-300 leading-relaxed">
                                MCP 워크플로우 기반 실시간 시그널 서비스 — 신규 5종 스캐너, TOP 3 이벤트, 그래프RAG 분석을 한 곳에서.
                            </p>
                        </div>
                    </div>
                </div>

                {/* 기능 미리보기 4종 */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <FeatureCard icon="fa-bolt" title="알파 스캐너" desc="매 시장 시각마다 신규 후보 종목 최대 5개 자동 발견 · 진입가 / 리스크 점수 포함." />
                    <FeatureCard icon="fa-trophy" title="MCP TOP 3" desc="워크플로우가 선정한 TOP 3 종목의 CIO 판정 · 외인 매수 · 공시 이벤트 즉시 알림." />
                    <FeatureCard icon="fa-project-diagram" title="그래프RAG 분석" desc="종목 간 관계 · 섹터 연결 · 이벤트 인과 관계를 그래프 기반으로 시각화." />
                    <FeatureCard icon="fa-history" title="스캔 성과 히스토리" desc="과거 스캔 결과의 수익률 추적 · 적중률 / 평균 수익 통계 자동 집계." />
                </div>

                {children}
            </div>
        </div>
    );
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
    return (
        <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
            <div className="flex items-center gap-2 mb-2">
                <i className={`fas ${icon} text-cyan-400`} />
                <h3 className="text-white font-bold text-sm">{title}</h3>
            </div>
            <p className="text-gray-400 text-xs leading-relaxed">{desc}</p>
        </div>
    );
}

function UpgradePrompt({ tier }: { tier: string | null }) {
    return (
        <PageShell>
            <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/[0.04] to-[#13151f] p-6">
                <h3 className="text-lg font-bold text-white mb-2">
                    <i className="fas fa-arrow-up text-cyan-400 mr-2" />
                    AI Bain 구독 업그레이드
                </h3>
                <p className="text-sm text-gray-300 mb-4">
                    현재 <span className="text-cyan-300 font-bold">{tier === 'pro' ? 'Pro' : 'Ultra Pro'}</span> 구독을 이용 중입니다.
                    기존 구독은 그대로 유지하고 <span className="text-cyan-300 font-bold">+40,000원/30일</span> 만 추가하면
                    AI Bain 알파 스캐너 서비스가 활성화됩니다.
                </p>
                <p className="text-xs text-gray-500 mb-4">
                    만료 시 별도 갱신 신청 없으면 자동으로 기존 {tier === 'pro' ? 'Pro' : 'Ultra Pro'} 버전으로 회귀합니다.
                    카카오 채널로 입금자명 + "AI Bain 추가" 문의 시 운영자가 활성화합니다.
                </p>
                <div className="flex flex-wrap gap-2">
                    <Link
                        to="/pricing"
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-cyan-400/30 bg-cyan-500/10 text-cyan-300 font-bold text-sm hover:bg-cyan-500/15 transition-all"
                    >
                        <i className="fas fa-info-circle" />
                        요금 자세히
                    </Link>
                    <Link
                        to="/dashboard/account"
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-gray-300 font-bold text-sm hover:bg-white/10 transition-all"
                    >
                        <i className="fas fa-user-circle" />
                        내 구독 보기
                    </Link>
                </div>
            </div>
        </PageShell>
    );
}

function SubscribePrompt() {
    return (
        <PageShell>
            <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/[0.06] to-[#13151f] p-6">
                <h3 className="text-lg font-bold text-white mb-2">
                    <i className="fas fa-key text-cyan-400 mr-2" />
                    구독 안내
                </h3>
                <p className="text-sm text-gray-300 mb-4">
                    Pro + AI Bain 구독자만 이용 가능합니다. 가격 페이지에서 구독을 신청해 주세요.
                </p>
                <Link
                    to="/pricing"
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 text-black font-bold text-sm hover:from-cyan-400 hover:to-sky-400 transition-all"
                >
                    <i className="fas fa-receipt" />
                    구독 신청
                </Link>
            </div>
        </PageShell>
    );
}
