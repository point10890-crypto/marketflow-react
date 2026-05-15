import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * Pro + AI Bain 구독자 전용 페이지 (Stage 1 placeholder).
 *
 * 향후 admin 페이지의 분석 기능을 그대로 가져와서 구독자에게 제공.
 * 현재는 entry point + 안내만 노출 — 본격 구현은 다음 단계.
 *
 * 라우트: /dashboard/ai-bain (App.tsx, ProGuard 보호)
 */
export default function AiBainPage() {
    const { user } = useAuth();
    const tier = user?.tier ?? null;
    const role = user?.role ?? 'user';
    const isAdmin = role === 'admin';
    const hasProAccess = isAdmin || tier === 'pro' || tier === 'premium';

    return (
        <div className="min-h-screen bg-[#09090b] text-white p-4 sm:p-6 lg:p-8">
            <div className="max-w-6xl mx-auto space-y-6">
                {/* Header */}
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

                {/* 구현 진행 안내 */}
                <div className="rounded-2xl border border-amber-500/25 bg-amber-500/[0.04] p-5">
                    <div className="flex items-start gap-3">
                        <i className="fas fa-hammer text-amber-400 text-xl mt-0.5" />
                        <div className="min-w-0 flex-1">
                            <h3 className="text-white font-bold text-sm">구현 진행 중 (Stage 1)</h3>
                            <p className="mt-1 text-xs text-gray-400 leading-relaxed">
                                현재 관리자 전용으로 운영 중인 알파 스캐너 / MCP TOP 3 / 그래프RAG 기능을
                                Pro + AI Bain 구독자에게 단계적으로 공개합니다. 본 페이지에 실시간 결과가 곧 표시됩니다.
                            </p>
                        </div>
                    </div>
                </div>

                {/* 기능 미리보기 카드 4종 */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
                        <div className="flex items-center gap-2 mb-2">
                            <i className="fas fa-bolt text-cyan-400" />
                            <h3 className="text-white font-bold text-sm">알파 스캐너</h3>
                        </div>
                        <p className="text-gray-400 text-xs leading-relaxed">
                            매 시장 시각마다 신규 후보 종목 최대 5개 자동 발견 · 진입가 / 리스크 점수 포함.
                        </p>
                    </div>

                    <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
                        <div className="flex items-center gap-2 mb-2">
                            <i className="fas fa-trophy text-cyan-400" />
                            <h3 className="text-white font-bold text-sm">MCP TOP 3</h3>
                        </div>
                        <p className="text-gray-400 text-xs leading-relaxed">
                            워크플로우가 선정한 TOP 3 종목의 CIO 판정 · 외인 매수 · 공시 이벤트 즉시 알림.
                        </p>
                    </div>

                    <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
                        <div className="flex items-center gap-2 mb-2">
                            <i className="fas fa-project-diagram text-cyan-400" />
                            <h3 className="text-white font-bold text-sm">그래프RAG 분석</h3>
                        </div>
                        <p className="text-gray-400 text-xs leading-relaxed">
                            종목 간 관계 · 섹터 연결 · 이벤트 인과 관계를 그래프 기반으로 시각화.
                        </p>
                    </div>

                    <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-5">
                        <div className="flex items-center gap-2 mb-2">
                            <i className="fas fa-history text-cyan-400" />
                            <h3 className="text-white font-bold text-sm">스캔 성과 히스토리</h3>
                        </div>
                        <p className="text-gray-400 text-xs leading-relaxed">
                            과거 스캔 결과의 수익률 추적 · 적중률 / 평균 수익 통계 자동 집계.
                        </p>
                    </div>
                </div>

                {/* 구독 안내 / 업그레이드 */}
                {!hasProAccess ? (
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
                ) : tier === 'pro' || tier === 'premium' ? (
                    <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/[0.04] to-[#13151f] p-6">
                        <h3 className="text-lg font-bold text-white mb-2">
                            <i className="fas fa-arrow-up text-cyan-400 mr-2" />
                            업그레이드 — AI Bain 추가
                        </h3>
                        <p className="text-sm text-gray-300 mb-4">
                            현재 <span className="text-cyan-300 font-bold">{tier === 'pro' ? 'Pro' : 'Ultra Pro'}</span> 구독을 이용 중입니다.
                            기존 구독에 AI Bain 알파 스캐너를 추가해 실시간 시그널 서비스를 받으세요.
                            카카오 채널로 입금자명 + "AI Bain 추가" 문의 시 운영자가 활성화합니다.
                        </p>
                        <div className="flex flex-wrap gap-2">
                            <Link
                                to="/pricing"
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-cyan-400/30 bg-cyan-500/10 text-cyan-300 font-bold text-sm hover:bg-cyan-500/15 transition-all"
                            >
                                <i className="fas fa-info-circle" />
                                요금 보기
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
                ) : (
                    <div className="rounded-2xl border border-red-500/30 bg-red-500/[0.04] p-5">
                        <p className="text-sm text-red-300">
                            <i className="fas fa-shield-halved mr-2" />
                            관리자 권한으로 접근 중 — 정식 출시 후 구독자에게 본 페이지가 공개됩니다.
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}
