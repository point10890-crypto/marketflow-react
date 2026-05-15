import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import TodaysPipelineCard from '@/components/admin/TodaysPipelineCard';
import RecentOutcomesBoard from '@/components/admin/RecentOutcomesBoard';
import ScanPerformanceCard from '@/components/admin/ScanPerformanceCard';

/**
 * Pro + AI Bain 구독자 전용 페이지 (Stage 2).
 *
 * 라우트: /dashboard/ai-bain (App.tsx, ProGuard 보호)
 *
 * 가시성 분기:
 *  - admin 권한        → 실시간 분석 대시보드 풀버전 (TodaysPipeline + RecentOutcomes + ScanPerformance)
 *  - 활성 Pro/Ultra Pro → "AI Bain 추가 신청" 업그레이드 안내 (+40,000원/30일)
 *  - 그 외             → "구독 신청" CTA → /pricing
 *
 * 관리자 페이지(/admin/endpoints) 의 핵심 분석 기능을 단순화한 레이아웃.
 * 운영 컨트롤(Run scanner, Auto Runner, LLM 튜닝, MCP HTTP/Watchdog 상태) 은 모두 제외.
 */
export default function AiBainPage() {
    const { user } = useAuth();
    const tier = user?.tier ?? null;
    const role = user?.role ?? 'user';
    const isAdmin = role === 'admin';
    const hasProBase = tier === 'pro' || tier === 'premium';
    const showAdminDashboard = isAdmin;
    const showUpgradeFlow = !isAdmin && hasProBase;
    const showSubscribeCTA = !isAdmin && !hasProBase;

    return (
        <div className="min-h-screen bg-[#09090b] text-white p-4 sm:p-6 lg:p-8">
            <div className="max-w-6xl mx-auto space-y-6">

                {/* ── 헤더 ── */}
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
                                {isAdmin && (
                                    <span className="inline-flex items-center gap-1 rounded-full border border-red-400/30 bg-red-500/10 px-2 py-0.5 text-[10px] font-black text-red-300 uppercase tracking-wider">
                                        <i className="fas fa-shield-halved text-[10px]" />
                                        ADMIN
                                    </span>
                                )}
                            </div>
                            <p className="mt-2 text-sm sm:text-base text-gray-300 leading-relaxed">
                                MCP 워크플로우 기반 실시간 시그널 서비스 — 신규 5종 스캐너, TOP 3 이벤트, 그래프RAG 분석을 한 곳에서.
                            </p>
                        </div>
                    </div>
                </div>

                {/* ── 미가입자 / 비구독자 → 구독 신청 CTA ── */}
                {showSubscribeCTA && (
                    <>
                        {/* 기능 미리보기 4종 */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                            <FeatureCard icon="fa-bolt" title="알파 스캐너" desc="매 시장 시각마다 신규 후보 종목 최대 5개 자동 발견 · 진입가 / 리스크 점수 포함." />
                            <FeatureCard icon="fa-trophy" title="MCP TOP 3" desc="워크플로우가 선정한 TOP 3 종목의 CIO 판정 · 외인 매수 · 공시 이벤트 즉시 알림." />
                            <FeatureCard icon="fa-project-diagram" title="그래프RAG 분석" desc="종목 간 관계 · 섹터 연결 · 이벤트 인과 관계를 그래프 기반으로 시각화." />
                            <FeatureCard icon="fa-history" title="스캔 성과 히스토리" desc="과거 스캔 결과의 수익률 추적 · 적중률 / 평균 수익 통계 자동 집계." />
                        </div>

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
                    </>
                )}

                {/* ── 활성 Pro / Ultra Pro → AI Bain 추가 업그레이드 안내 ── */}
                {showUpgradeFlow && (
                    <>
                        {/* 기능 미리보기 4종 */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                            <FeatureCard icon="fa-bolt" title="알파 스캐너" desc="매 시장 시각마다 신규 후보 종목 최대 5개 자동 발견 · 진입가 / 리스크 점수 포함." />
                            <FeatureCard icon="fa-trophy" title="MCP TOP 3" desc="워크플로우가 선정한 TOP 3 종목의 CIO 판정 · 외인 매수 · 공시 이벤트 즉시 알림." />
                            <FeatureCard icon="fa-project-diagram" title="그래프RAG 분석" desc="종목 간 관계 · 섹터 연결 · 이벤트 인과 관계를 그래프 기반으로 시각화." />
                            <FeatureCard icon="fa-history" title="스캔 성과 히스토리" desc="과거 스캔 결과의 수익률 추적 · 적중률 / 평균 수익 통계 자동 집계." />
                        </div>

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
                    </>
                )}

                {/* ── 관리자 / AI Bain 활성 사용자 → 실시간 분석 대시보드 ── */}
                {showAdminDashboard && (
                    <>
                        {/* 빠른 상태 칩 — 모바일 화면에서 한눈에 */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                            <StatusChip icon="fa-bolt" label="알파 스캐너" value="실시간" tone="cyan" />
                            <StatusChip icon="fa-trophy" label="MCP TOP 3" value="자동 발사" tone="amber" />
                            <StatusChip icon="fa-project-diagram" label="그래프RAG" value="활성" tone="sky" />
                            <StatusChip icon="fa-shield-halved" label="알림 사일로" value="AIbain_bot" tone="emerald" />
                        </div>

                        {/* 메인 대시보드 — admin 페이지 핵심 3개 카드 재사용 */}
                        <div className="space-y-6">
                            {/* 1. 오늘의 파이프라인 — 현재 실행 중인 분석 흐름 */}
                            <section>
                                <SectionHeader icon="fa-stream" title="오늘의 파이프라인" desc="실시간 분석 단계 · 다음 스캔 시각 · 워크플로우 상태" />
                                <TodaysPipelineCard />
                            </section>

                            {/* 2. 최근 성과 — 추천 종목의 실제 수익률 */}
                            <section>
                                <SectionHeader icon="fa-chart-line" title="최근 추천 성과" desc="지난 7/30/60일 추천 종목의 forward return · 적중률 · 평균 수익 R-multiple" />
                                <RecentOutcomesBoard />
                            </section>

                            {/* 3. 스캔 성과 통계 — KPI + 시장별 / 전략별 집계 */}
                            <section>
                                <SectionHeader icon="fa-gauge-high" title="스캔 성과 통계" desc="전체 스캔 / 평가 / 적중률 / Information Coefficient · 시장별 · 전략별 집계" />
                                <ScanPerformanceCard />
                            </section>
                        </div>

                        {/* 하단 안내 */}
                        <div className="rounded-2xl border border-cyan-500/15 bg-cyan-500/[0.03] p-5">
                            <div className="flex items-start gap-3">
                                <i className="fas fa-info-circle text-cyan-400 text-lg mt-0.5" />
                                <div className="min-w-0 flex-1">
                                    <p className="text-xs text-gray-300 leading-relaxed">
                                        본 대시보드는 관리자 전용 분석 콘솔 (<code className="text-cyan-300 bg-black/30 px-1.5 py-0.5 rounded text-[10px]">/admin/endpoints</code>) 의
                                        핵심 분석 기능을 단순화한 Pro + AI Bain 구독자 뷰입니다.
                                        실시간 데이터는 60초 간격으로 자동 갱신되며, 신규 시그널은 AIbain_bot 텔레그램으로도 발송됩니다.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

// ── helpers ─────────────────────────────────────────────────────────────────

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

function StatusChip({ icon, label, value, tone }: { icon: string; label: string; value: string; tone: 'cyan' | 'amber' | 'sky' | 'emerald' }) {
    const toneClass: Record<typeof tone, string> = {
        cyan: 'border-cyan-400/25 bg-cyan-500/[0.06] text-cyan-300',
        amber: 'border-amber-400/25 bg-amber-500/[0.06] text-amber-300',
        sky: 'border-sky-400/25 bg-sky-500/[0.06] text-sky-300',
        emerald: 'border-emerald-400/25 bg-emerald-500/[0.06] text-emerald-300',
    };
    return (
        <div className={`rounded-xl border p-3 ${toneClass[tone]}`}>
            <div className="flex items-center gap-2 mb-1">
                <i className={`fas ${icon} text-xs opacity-80`} />
                <span className="text-[10px] uppercase tracking-wider font-bold opacity-70">{label}</span>
            </div>
            <div className="text-sm font-bold">{value}</div>
        </div>
    );
}

function SectionHeader({ icon, title, desc }: { icon: string; title: string; desc: string }) {
    return (
        <div className="mb-3 px-1">
            <div className="flex items-center gap-2 mb-1">
                <i className={`fas ${icon} text-cyan-400 text-sm`} />
                <h2 className="text-base sm:text-lg font-bold text-white">{title}</h2>
            </div>
            <p className="text-[11px] sm:text-xs text-gray-500 leading-relaxed">{desc}</p>
        </div>
    );
}
