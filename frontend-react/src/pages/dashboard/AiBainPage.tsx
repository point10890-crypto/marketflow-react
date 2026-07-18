import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import AdminEndpointsPage from '@/pages/admin/AdminEndpointsPage';

/**
 * Pro + AI Brain 구독자 전용 페이지.
 *
 * 라우트: /dashboard/ai-bain (ProGuard 보호)
 *
 * 가시성 분기:
 *  - admin (또는 활성 AI Brain) → 구독자 콘솔 (AdminEndpointsPage subscriberMode, 전체 기능)
 *  - 활성 Pro/Ultra Pro 비AI Brain → "AI Brain 구독 업그레이드" 안내 (+40,000원/30일)
 *  - 그 외 → "구독 신청" CTA → /pricing
 *
 * 구독자 콘솔은 admin 페이지(/admin/endpoints)의 분석 기능(MiroFish 어시스턴트, Alpha Board,
 * Brain Signal, Verdict, GraphRAG, Scan History, Recent Outcomes 등)을 모두 노출하되
 * 운영자 전용 컨트롤만 제외한다.
 */
export default function AiBainPage() {
    const { user } = useAuth();
    const tier = user?.tier ?? null;
    const role = user?.role ?? 'user';
    const isAdmin = role === 'admin';
    const hasProBase = tier === 'pro' || tier === 'premium';
    const isAibainActive = !!user?.is_aibain_active;
    // admin 또는 AI Brain 활성 구독자 → 풀 콘솔
    const showFullDashboard = isAdmin || isAibainActive;
    // Pro/Premium 인데 AI Brain 미활성 → 업그레이드 신청 폼
    const showUpgradeFlow = !isAdmin && hasProBase && !isAibainActive;

    // ── admin (또는 활성 AI Brain) → 구독자 콘솔 (전체 기능 유지) ──────────────────
    if (showFullDashboard) {
        return <AdminEndpointsPage subscriberMode />;
    }

    // ── 활성 Pro / Ultra Pro → 업그레이드 안내 ─────────────────────────────────
    if (showUpgradeFlow) {
        return <UpgradePrompt tier={tier} />;
    }

    // ── 미가입 / 비구독 → 구독 신청 CTA ────────────────────────────────────────
    return <SubscribePrompt />;
}

// ── Helpers ────────────────────────────────────────────────────────────────

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
                                <h1 className="text-2xl sm:text-3xl font-black tracking-tight">AI Brain 알파 스캐너</h1>
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
    const { user, token } = useAuth();
    const navigate = useNavigate();
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [depositorName, setDepositorName] = useState(user?.name || '');
    const [pendingRequest, setPendingRequest] = useState<Awaited<ReturnType<typeof subscriptionAPI.getStatus>>['requests'][number] | null>(null);
    const [checkingStatus, setCheckingStatus] = useState(true);

    const tierLabel = tier === 'pro' ? 'Pro' : 'Ultra Pro';
    const isRenewal = !!user?.is_aibain_expired || (!!user?.aibain_expires_at && !user?.is_aibain_active);
    const pendingIsAibain = pendingRequest?.request_type === 'aibain_addon' || pendingRequest?.request_type === 'aibain_renewal';

    useEffect(() => {
        let active = true;
        if (!token) {
            setCheckingStatus(false);
            return () => { active = false; };
        }
        subscriptionAPI.getStatus(token)
            .then(data => {
                if (!active) return;
                setPendingRequest(data.requests.find(req => req.status === 'pending') || null);
            })
            .catch(() => {})
            .finally(() => { if (active) setCheckingStatus(false); });
        return () => { active = false; };
    }, [token]);

    const handleSubmit = async () => {
        setError('');
        if (!tier || !token) {
            setError('로그인 정보를 확인할 수 없습니다.');
            return;
        }
        if (!depositorName.trim()) {
            setError('입금자명을 입력해 주세요.');
            return;
        }
        setSubmitting(true);
        try {
            // 서버가 이용 이력에 따라 최초 추가(aibain_addon)와 만료 재구독(aibain_renewal)을 분류한다.
            await subscriptionAPI.requestAibain(tier, token, depositorName.trim());
            navigate('/pending-approval', { replace: true });
        } catch (err: any) {
            const msg = err?.message || '';
            if (msg.toLowerCase().includes('pending')) {
                navigate('/pending-approval', { replace: true });
                return;
            }
            setError(msg || 'AI Brain 신청 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.');
            setSubmitting(false);
        }
    };

    if (checkingStatus) {
        return (
            <PageShell>
                <div className="rounded-2xl border border-cyan-500/25 bg-[#13151f] p-10 text-center text-cyan-300">
                    <i className="fas fa-spinner fa-spin mr-2" />구독 상태를 확인하고 있습니다
                </div>
            </PageShell>
        );
    }

    if (pendingRequest) {
        const renewalPending = pendingRequest.request_type === 'aibain_renewal';
        return (
            <PageShell>
                <div className="rounded-2xl border border-yellow-500/25 bg-gradient-to-br from-yellow-500/[0.07] to-[#13151f] p-6 sm:p-8 text-center">
                    <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-yellow-500/10 text-yellow-300 text-2xl">
                        <i className="fas fa-hourglass-half" />
                    </div>
                    <h3 className="text-xl sm:text-2xl font-black text-white">
                        {pendingIsAibain ? (renewalPending ? 'AI Brain 재구독 승인 대기 중' : 'AI Brain 활성화 승인 대기 중') : '다른 구독 신청 승인 대기 중'}
                    </h3>
                    <p className="mt-2 text-sm text-gray-300">
                        입금 확인 후 관리자가 처리합니다. 중복 신청 없이 현재 요청 상태를 바로 확인할 수 있습니다.
                    </p>
                    <div className="mt-4 inline-flex items-center gap-2 rounded-xl bg-white/5 px-4 py-2 text-sm text-gray-300">
                        <span>{pendingRequest.amount || '입금액 확인 중'}</span>
                        <span className="text-gray-600">·</span>
                        <span>{pendingRequest.depositor_name || user?.name}</span>
                    </div>
                    <Link
                        to="/pending-approval"
                        className="mt-5 w-full py-3 rounded-xl bg-yellow-500/15 hover:bg-yellow-500/25 text-yellow-300 font-bold text-sm transition-all flex items-center justify-center gap-2"
                    >
                        <i className="fas fa-search" />승인 상태 확인
                    </Link>
                </div>
            </PageShell>
        );
    }

    return (
        <PageShell>
            {/* 메인 업그레이드 신청 카드 */}
            <div className="rounded-2xl border border-cyan-500/40 bg-gradient-to-br from-cyan-500/[0.08] via-[#13151f] to-[#1c1c1e] p-6 sm:p-8 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-cyan-500/15 to-transparent rounded-bl-full pointer-events-none" />

                <div className="relative">
                    <div className="flex items-start gap-3 mb-4">
                        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-cyan-500/15 text-cyan-300 text-2xl">
                            <i className={`fas ${isRenewal ? 'fa-redo' : 'fa-arrow-up'}`} />
                        </div>
                        <div className="min-w-0 flex-1">
                            <h3 className="text-xl sm:text-2xl font-black text-white">AI Brain {isRenewal ? '재구독' : '구독 업그레이드'} 신청</h3>
                            <p className="mt-1 text-sm text-gray-300">
                                {isRenewal ? (
                                    <>만료된 AI Brain을 30일 다시 활성화합니다.</>
                                ) : (
                                    <>현재 <span className="text-cyan-300 font-bold">{tierLabel}</span> 구독에 AI Brain 알파 스캐너만 추가합니다.</>
                                )}
                                {' '}
                                기존 베이스 구독은 그대로 유지됩니다.
                            </p>
                            {isRenewal && user?.aibain_expires_at && (
                                <p className="mt-2 text-xs text-rose-300">
                                    이전 이용 만료일: {new Date(user.aibain_expires_at).toLocaleDateString('ko-KR')}
                                </p>
                            )}
                            {isRenewal && tier === 'premium' && (
                                <p className="mt-2 text-xs text-purple-300">
                                    <i className="fas fa-gem mr-1" />AI Brain만 만료되었으며 Ultra Pro 무기한 이용권은 계속 유지됩니다.
                                </p>
                            )}
                            {isRenewal && tier === 'pro' && (
                                <p className="mt-2 text-xs text-amber-300">
                                    <i className="fas fa-crown mr-1" />AI Brain만 만료되었으며 Pro 잔여기간 카운터는 자동으로 재개됩니다.
                                </p>
                            )}
                        </div>
                    </div>

                    {/* 가격 요약 박스 */}
                    <div className="rounded-xl border border-cyan-400/20 bg-cyan-500/[0.06] p-4 mb-5">
                        <h4 className="text-cyan-300 font-bold text-xs mb-2 flex items-center gap-1.5">
                            <i className="fas fa-receipt" />
                            요금 안내
                        </h4>
                        <div className="text-sm text-gray-300 space-y-1">
                            <div className="flex justify-between">
                                <span>현재 {tierLabel} 구독</span>
                                <span className="text-gray-500">유지</span>
                            </div>
                            <div className="flex justify-between">
                                <span>AI Brain 알파 스캐너 (30일)</span>
                                <span className="font-mono text-white">+40,000원</span>
                            </div>
                            <div className="h-px bg-cyan-400/20 my-2" />
                            <div className="flex justify-between font-bold text-white">
                                <span>이번 입금 금액</span>
                                <span className="font-mono text-cyan-300 text-base">40,000원</span>
                            </div>
                        </div>
                        <p className="mt-2 text-[10px] text-gray-500">
                            <i className="fas fa-info-circle mr-1" />
                            30일 후 자동 만료 — 별도 갱신 없으면 기존 {tierLabel} 버전으로 자동 회귀.
                        </p>
                    </div>

                    {/* 입금자명 입력 */}
                    <div className="mb-4">
                        <label className="block text-xs font-medium text-gray-400 mb-2">입금자명 *</label>
                        <input
                            type="text"
                            value={depositorName}
                            onChange={(e) => setDepositorName(e.target.value)}
                            placeholder="입금자명 (가입 이름과 동일하게)"
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-cyan-400/50"
                        />
                    </div>

                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm mb-4">
                            {error}
                        </div>
                    )}

                    {/* 신청 버튼 */}
                    <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={submitting || !depositorName.trim()}
                        className="w-full py-4 rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 text-black font-bold text-sm hover:from-cyan-400 hover:to-sky-400 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                    >
                        {submitting ? (
                            <><i className="fas fa-spinner fa-spin" />처리 중...</>
                        ) : (
                            <><i className={`fas ${isRenewal ? 'fa-redo' : 'fa-paper-plane'}`} />AI Brain {isRenewal ? '재구독' : '구독'} 신청 (+40,000원/30일)</>
                        )}
                    </button>

                    <p className="text-gray-600 text-[11px] text-center mt-3">
                        신청 후 입금 → 관리자 확인 (최대 24시간) → AI Brain 활성화
                    </p>
                </div>
            </div>

            {/* 보조 링크 */}
            <div className="flex flex-wrap gap-2 justify-center">
                <Link
                    to="/pricing"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-gray-300 font-medium text-xs hover:bg-white/10 transition-all"
                >
                    <i className="fas fa-info-circle" />
                    가격 페이지
                </Link>
                <Link
                    to="/dashboard/account"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-gray-300 font-medium text-xs hover:bg-white/10 transition-all"
                >
                    <i className="fas fa-user-circle" />
                    내 구독 보기
                </Link>
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
                    Pro + AI Brain 구독자만 이용 가능합니다. 가격 페이지에서 구독을 신청해 주세요.
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
