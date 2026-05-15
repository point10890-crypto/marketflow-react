import { useState, useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

export default function PricingPage() {
    const { user, token } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const userTier = user?.tier ?? null;
    const [requesting, setRequesting] = useState<string | null>(null);
    const [showBank, setShowBank] = useState(false);
    const [selectedPlan, setSelectedPlan] = useState<'pro' | 'premium' | null>(null);
    const [depositorName, setDepositorName] = useState('');

    const [requestSent, setRequestSent] = useState(false);

    const handleSelectPlan = (tier: 'pro' | 'premium') => {
        if (!user || !token) {
            navigate('/signup');
            return;
        }
        if (userTier === tier || userTier === 'premium') return;
        setSelectedPlan(tier);
        setShowBank(true);
        setRequestSent(false);
    };

    // 가입 직후 /pricing 에 도착하면 요청 플랜으로 계좌 정보 자동 펼치기.
    // 우선순위: URL ?plan= > user.requested_tier.
    // 유저가 이미 해당 plan 이거나 premium(상위) 이면 자동펼침 생략.
    useEffect(() => {
        if (!user || !token) return;
        if (showBank) return; // 이미 수동 선택으로 펼쳐져 있으면 유지
        const qPlan = searchParams.get('plan');
        const target: 'pro' | 'premium' | null =
            qPlan === 'pro' || qPlan === 'premium'
                ? qPlan
                : (user.requested_tier === 'pro' || user.requested_tier === 'premium'
                    ? user.requested_tier
                    : null);
        if (!target) return;
        if (userTier === target || userTier === 'premium') return;
        setSelectedPlan(target);
        setShowBank(true);
        // 기본 입금자명 = 가입 시 이름 (수정 가능)
        if (!depositorName) setDepositorName(user.name || '');
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user, token]);

    const handleSubmitRequest = async () => {
        if (!user || !token || !selectedPlan) return;
        if (!depositorName.trim()) {
            alert('입금자명을 입력해 주세요.');
            return;
        }

        setRequesting(selectedPlan);
        try {
            await subscriptionAPI.requestUpgrade(selectedPlan, token, depositorName.trim());
            setRequestSent(true);
        } catch (err: any) {
            const msg = err?.message || '';
            if (msg.includes('pending')) {
                setRequestSent(true);
            } else {
                alert('구독 신청 중 오류가 발생했습니다.');
            }
        } finally {
            setRequesting(null);
        }
    };

    const proFeatures = [
        'Summary 대시보드 + 전체 기능',
        'KR Market (종가베팅, 주도주LIVE, VCP, AI Chart, Track Record)',
        'US Market (Overview, VCP, ETF Flows, AI Chart)',
        'Crypto (Overview, VCP Signals)',
        'VCP Enhanced Scanner (전 시장)',
        'W Pattern AI (M&W 차트 패턴)',
        'ProPicks (Investing.com 분석)',
        'AI Briefing Portal',
        '관심종목 분석 챗봇',
    ];

    const isPro = userTier === 'pro';
    const isPremium = userTier === 'premium';
    const isProOrAbove = isPro || isPremium;

    const bankAmount = selectedPlan === 'premium' ? '1,200,000원 (1회)' : '50,000원 / 30일';

    // 구독 만료일 (서버에서 받은 실제 값 또는 신규 30일)
    const getExpiryDate = () => {
        if (user?.pro_expires_at) {
            return new Date(user.pro_expires_at).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
        }
        const now = new Date();
        now.setDate(now.getDate() + 30);
        return now.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
    };

    return (
        <div className="fixed inset-0 bg-[#09090b] flex flex-col items-center overflow-y-auto p-6 sm:p-8">
            {/* Header */}
            <div className="text-center mt-8 sm:mt-16 mb-10 sm:mb-14">
                <Link to="/" className="inline-flex items-center gap-2 mb-6 text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-arrow-left" />
                    홈으로
                </Link>
                <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight mb-4">
                    마크 미너비니 <span className="bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">앱 구독</span>
                </h1>
                <p className="text-gray-400 text-base sm:text-lg max-w-md mx-auto">
                    AI 기반 마켓 인사이트로 투자 의사결정을 업그레이드하세요
                </p>
            </div>

            {/* Plans Grid — 3 columns (Pro / Pro + AI Bain / Ultra Pro) */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5 max-w-6xl w-full">
                {/* Pro Plan */}
                <div className="p-6 rounded-2xl border border-amber-500/30 bg-[#1c1c1e] ring-1 ring-amber-500/20 relative">
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 text-xs font-bold mb-3">
                        <i className="fas fa-crown" /> 기본
                    </div>
                    <h3 className="text-xl font-bold text-white mb-1">Pro</h3>
                    <div className="flex items-baseline gap-1 mb-1">
                        <span className="text-3xl font-black text-white">50,000</span>
                        <span className="text-gray-400">원/30일</span>
                    </div>
                    <p className="text-amber-400/70 text-xs font-semibold mb-5">
                        구독 만료일: {getExpiryDate()}까지
                    </p>
                    <ul className="space-y-2.5 mb-6">
                        {proFeatures.map((f) => (
                            <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                                <i className="fas fa-check text-amber-400 text-xs mt-1 shrink-0" />
                                {f}
                            </li>
                        ))}
                    </ul>

                    {isProOrAbove ? (
                        <div className="w-full py-3 rounded-xl bg-amber-500/10 text-amber-400 font-bold text-center text-sm">
                            <i className="fas fa-check-circle mr-2" />{isPremium ? '포함됨' : '현재 플랜'}
                        </div>
                    ) : (
                        <button
                            onClick={() => handleSelectPlan('pro')}
                            disabled={requesting !== null}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting === 'pro' ? '처리 중...' : 'Pro 구독 신청'}
                        </button>
                    )}
                </div>

                {/* Pro + AI Bain Plan (신규) */}
                <div className="p-6 rounded-2xl border border-cyan-500/30 bg-[#1c1c1e] ring-1 ring-cyan-500/20 relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl from-cyan-500/10 to-transparent rounded-bl-full pointer-events-none" />
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-cyan-500/10 text-cyan-400 text-xs font-bold mb-3">
                        <i className="fas fa-robot" /> 추천
                    </div>
                    <h3 className="text-xl font-bold text-white mb-1">
                        Pro + AI Bain
                    </h3>
                    <div className="flex items-baseline gap-1 mb-1">
                        <span className="text-3xl font-black text-white">90,000</span>
                        <span className="text-gray-400">원/30일</span>
                    </div>
                    <p className="text-cyan-400/70 text-xs font-semibold mb-1">
                        Pro 50,000원 + AI Bain 40,000원
                    </p>
                    <p className="text-gray-500 text-[11px] mb-5">
                        구독 만료일: {getExpiryDate()}까지
                    </p>
                    <ul className="space-y-2.5 mb-6">
                        <li className="flex items-start gap-2 text-sm text-gray-300">
                            <i className="fas fa-check text-cyan-400 text-xs mt-1 shrink-0" />
                            Pro 전체 기능 포함
                        </li>
                        <li className="flex items-start gap-2 text-sm text-cyan-200 font-semibold">
                            <i className="fas fa-bolt text-cyan-400 text-xs mt-1 shrink-0" />
                            AI Bain 알파 스캐너 — 신규 5종 자동 알림
                        </li>
                        <li className="flex items-start gap-2 text-sm text-gray-300">
                            <i className="fas fa-trophy text-cyan-400 text-xs mt-1 shrink-0" />
                            TOP 3 신규 이벤트 즉시 알림
                        </li>
                        <li className="flex items-start gap-2 text-sm text-gray-300">
                            <i className="fas fa-shield-halved text-cyan-400 text-xs mt-1 shrink-0" />
                            개인봇 사일로 (다른 채널과 분리)
                        </li>
                    </ul>

                    {isProOrAbove ? (
                        <div className="w-full py-3 rounded-xl bg-cyan-500/10 text-cyan-400 font-bold text-center text-sm">
                            <i className="fas fa-info-circle mr-2" />AI Bain 추가는 카카오 문의
                        </div>
                    ) : (
                        <button
                            onClick={() => handleSelectPlan('pro')}
                            disabled={requesting !== null}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 hover:from-cyan-400 hover:to-sky-400 text-black font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting === 'pro' ? '처리 중...' : 'Pro + AI Bain 신청'}
                        </button>
                    )}
                </div>

                {/* Ultra Pro Plan */}
                <div className="p-6 rounded-2xl border border-purple-500/30 bg-[#1c1c1e] ring-1 ring-purple-500/20 relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl from-purple-500/10 to-transparent rounded-bl-full" />
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 text-xs font-bold mb-3">
                        <i className="fas fa-gem" /> 평생 이용
                    </div>
                    <h3 className="text-xl font-bold text-white mb-1">Ultra Pro</h3>
                    <div className="flex items-baseline gap-1 mb-1">
                        <span className="text-3xl font-black text-white">1,200,000</span>
                        <span className="text-gray-400">원</span>
                    </div>
                    <p className="text-purple-400/70 text-xs font-semibold mb-5">1회 결제 · 무기한 이용</p>
                    <ul className="space-y-2.5 mb-6">
                        {proFeatures.map((f) => (
                            <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                                <i className="fas fa-check text-purple-400 text-xs mt-1 shrink-0" />
                                {f}
                            </li>
                        ))}
                        <li className="flex items-start gap-2 text-sm text-purple-300 font-semibold">
                            <i className="fas fa-infinity text-purple-400 text-xs mt-1 shrink-0" />
                            평생 무료 업데이트
                        </li>
                        <li className="flex items-start gap-2 text-sm text-purple-300 font-semibold">
                            <i className="fas fa-headset text-purple-400 text-xs mt-1 shrink-0" />
                            우선 고객 지원
                        </li>
                    </ul>

                    {isPremium ? (
                        <div className="w-full py-3 rounded-xl bg-purple-500/10 text-purple-400 font-bold text-center text-sm">
                            <i className="fas fa-gem mr-2" />현재 플랜
                        </div>
                    ) : (
                        <button
                            onClick={() => handleSelectPlan('premium')}
                            disabled={requesting !== null}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-500 to-fuchsia-500 hover:from-purple-400 hover:to-fuchsia-400 text-white font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting === 'premium' ? '처리 중...' : 'Ultra Pro 구매'}
                        </button>
                    )}
                </div>
            </div>

            {/* AI Bain 상세 설명 섹션 */}
            <section className="mt-12 max-w-5xl w-full">
                <div className="rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-cyan-500/[0.04] via-[#13151f] to-[#1c1c1e] p-6 sm:p-8 relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-cyan-500/10 to-transparent rounded-bl-full pointer-events-none" />

                    <div className="relative flex items-start gap-4 mb-6">
                        <div className="grid h-12 w-12 sm:h-14 sm:w-14 shrink-0 place-items-center rounded-2xl bg-cyan-500/15 text-cyan-300 text-2xl">
                            <i className="fas fa-robot" />
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                                <h2 className="text-2xl sm:text-3xl font-black text-white">AI Bain 이란?</h2>
                                <span className="inline-flex items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-black text-cyan-300 uppercase tracking-wider">
                                    <i className="fas fa-bolt text-[10px]" />
                                    ALPHA SCAN
                                </span>
                            </div>
                            <p className="mt-2 text-sm sm:text-base text-gray-300 leading-relaxed">
                                <strong className="text-cyan-300">AI Bain 알파 스캐너</strong> 전용 실시간 시그널 서비스.
                                Pro 구독에 추가하면 마켓 신호를 <strong className="text-white">실시간 자동 푸시</strong>로 받습니다.
                                기존 시스템과 독립된 사일로로 운영되어 다른 알림과 섞이지 않습니다.
                            </p>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
                        <div className="rounded-xl border border-cyan-400/15 bg-black/30 p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-bolt text-cyan-400" />
                                <h3 className="text-white font-bold text-sm">신규 5종 스캐너 알림</h3>
                            </div>
                            <p className="text-gray-400 text-xs leading-relaxed">
                                매 시장 시각마다 알파 스캐너가 발견한 <strong className="text-cyan-300">신규 후보 종목 최대 5개</strong>를
                                즉시 푸시. 진입가/리스크 점수 포함. 시장 흐름이 빨라도 놓치지 않습니다.
                            </p>
                        </div>

                        <div className="rounded-xl border border-cyan-400/15 bg-black/30 p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-trophy text-cyan-400" />
                                <h3 className="text-white font-bold text-sm">TOP 3 신규 이벤트 알림</h3>
                            </div>
                            <p className="text-gray-400 text-xs leading-relaxed">
                                MCP 워크플로우가 선정한 <strong className="text-cyan-300">TOP 3 종목</strong>의
                                CIO 판정 변동·외인 매수·공시 등 핵심 이벤트를 즉시 전송.
                                각 이벤트는 종목명·코드·시장·기준일 포함 (정직한 식별 정책).
                            </p>
                        </div>

                        <div className="rounded-xl border border-cyan-400/15 bg-black/30 p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-shield-halved text-cyan-400" />
                                <h3 className="text-white font-bold text-sm">독립 사일로</h3>
                            </div>
                            <p className="text-gray-400 text-xs leading-relaxed">
                                개인봇 / 채널봇과 분리된 별도 봇. 다른 알림 흐름과 섞이지 않고
                                <strong className="text-cyan-300"> AI Bain 만의 시그널</strong>만 한 곳에서 받습니다.
                            </p>
                        </div>

                        <div className="rounded-xl border border-cyan-400/15 bg-black/30 p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-clock text-cyan-400" />
                                <h3 className="text-white font-bold text-sm">즉시 푸시 · 지연 없음</h3>
                            </div>
                            <p className="text-gray-400 text-xs leading-relaxed">
                                알파 스캐너 워크플로우가 신호를 발견하는 즉시
                                <strong className="text-cyan-300"> 자동 푸시</strong>. 별도 로그인이나 대시보드 확인 없이
                                바로 시그널을 받아 진입 타이밍을 놓치지 않습니다.
                            </p>
                        </div>
                    </div>

                    <div className="rounded-xl bg-cyan-500/[0.06] border border-cyan-400/15 p-4">
                        <h3 className="text-cyan-300 font-bold text-sm mb-2 flex items-center gap-2">
                            <i className="fas fa-receipt" />
                            요금 안내
                        </h3>
                        <div className="text-sm text-gray-300 space-y-1">
                            <div className="flex justify-between">
                                <span>Pro 구독 (30일)</span>
                                <span className="font-mono">50,000원</span>
                            </div>
                            <div className="flex justify-between">
                                <span>AI Bain 알림 (30일)</span>
                                <span className="font-mono">40,000원</span>
                            </div>
                            <div className="h-px bg-cyan-400/20 my-2" />
                            <div className="flex justify-between font-bold text-white">
                                <span>합계 / 30일</span>
                                <span className="font-mono text-cyan-300">90,000원</span>
                            </div>
                        </div>
                        <p className="mt-3 text-[11px] text-gray-500">
                            <i className="fas fa-info-circle mr-1" />
                            Pro 구독 결제 후 카카오 채널로 입금자명 + "AI Bain 추가" 문의 시 운영자가 AI Bain 알파 스캐너를 활성화합니다.
                        </p>
                    </div>
                </div>
            </section>

            <div className="mt-5 w-full max-w-md">
                <KakaoSupportLink />
            </div>

            {/* Bank Transfer Info */}
            {showBank && (
                <div className="mt-8 max-w-5xl w-full p-6 rounded-2xl border border-amber-500/20 bg-[#1c1c1e]">
                    <div className="flex items-center gap-3 mb-4">
                        <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                            <i className="fas fa-university text-amber-400" />
                        </div>
                        <div>
                            <h4 className="text-white font-bold">계좌이체 안내</h4>
                            <p className="text-gray-500 text-xs">아래 계좌로 입금 후 승인까지 최대 24시간 소요됩니다</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                            <p className="text-white font-bold mt-1">국민은행</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                            <p className="text-white font-bold mt-1 font-mono">2259-02-04-057670</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                            <p className="text-white font-bold mt-1">이종민</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">금액</span>
                            <p className={`font-bold mt-1 ${selectedPlan === 'premium' ? 'text-purple-400' : 'text-amber-400'}`}>{bankAmount}</p>
                        </div>
                    </div>

                    {/* 입금자명 입력 */}
                    <div className="mt-4">
                        <label className="text-[10px] text-gray-500 uppercase tracking-wider block mb-2">입금자명</label>
                        <input
                            type="text"
                            value={depositorName}
                            onChange={(e) => setDepositorName(e.target.value)}
                            placeholder="입금자명을 입력하세요"
                            className="w-full px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06] text-white placeholder-gray-600 text-sm focus:outline-none focus:border-amber-500/50 transition-colors"
                        />
                    </div>

                    {/* 구독 기간 안내 */}
                    <div className="mt-4 p-4 rounded-xl bg-amber-500/5 border border-amber-500/10">
                        <div className="flex items-center gap-2 text-sm">
                            <i className="fas fa-calendar-alt text-amber-400 text-xs" />
                            <span className="text-gray-400">구독 기간:</span>
                            {selectedPlan === 'premium' ? (
                                <span className="text-purple-400 font-bold">무기한 (평생 이용)</span>
                            ) : (
                                <span className="text-amber-400 font-bold">
                                    {new Date().toLocaleDateString('ko-KR')} ~ {getExpiryDate()} (30일)
                                </span>
                            )}
                        </div>
                    </div>

                    <p className="text-gray-500 text-xs mt-4">
                        <i className="fas fa-info-circle mr-1" />
                        입금자명을 가입 시 사용한 이름과 동일하게 입력해 주세요. 확인 후 관리자가 플랜을 활성화합니다.
                    </p>

                    {/* 승인요청 버튼 */}
                    {requestSent ? (
                        <div className="mt-4 w-full py-4 rounded-xl bg-green-500/10 border border-green-500/20 text-center">
                            <i className="fas fa-check-circle text-green-400 text-lg" />
                            <p className="text-green-400 font-bold mt-1">승인 요청이 완료되었습니다</p>
                            <p className="text-gray-500 text-xs mt-1">관리자 확인 후 플랜이 활성화됩니다 (최대 24시간)</p>
                        </div>
                    ) : (
                        <button
                            onClick={handleSubmitRequest}
                            disabled={requesting !== null || !depositorName.trim()}
                            className={`mt-4 w-full py-4 rounded-xl font-bold text-sm transition-all flex items-center justify-center gap-2 ${
                                selectedPlan === 'premium'
                                    ? 'bg-gradient-to-r from-purple-500 to-fuchsia-500 hover:from-purple-400 hover:to-fuchsia-400 text-white'
                                    : 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black'
                            } disabled:opacity-40 disabled:cursor-not-allowed`}
                        >
                            {requesting ? (
                                <>
                                    <i className="fas fa-spinner fa-spin" />
                                    처리 중...
                                </>
                            ) : (
                                <>
                                    <i className="fas fa-paper-plane" />
                                    {selectedPlan === 'premium' ? 'Ultra Pro' : 'Pro'} 승인 요청
                                </>
                            )}
                        </button>
                    )}

                </div>
            )}

            {/* Footer */}
            <div className="mt-12 mb-8 flex items-center gap-6">
                <Link to="/dashboard" className="text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-arrow-left mr-2" />대시보드
                </Link>
                {user && (
                    <Link to="/dashboard/account" className="text-gray-500 hover:text-white transition-colors text-sm">
                        <i className="fas fa-user mr-2" />내 계정
                    </Link>
                )}
            </div>
        </div>
    );
}
