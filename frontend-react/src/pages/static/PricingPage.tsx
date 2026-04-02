import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';

export default function PricingPage() {
    const { user, token } = useAuth();
    const navigate = useNavigate();
    const userTier = user?.tier || 'free';
    const [requesting, setRequesting] = useState<string | null>(null);
    const [showBank, setShowBank] = useState(false);
    const [selectedPlan, setSelectedPlan] = useState<'pro' | 'premium' | null>(null);
    const [depositorName, setDepositorName] = useState('');

    const handleUpgrade = async (tier: 'pro' | 'premium') => {
        if (!user || !token) {
            navigate('/signup');
            return;
        }
        if (userTier === tier || userTier === 'premium') return;

        setRequesting(tier);
        try {
            await subscriptionAPI.requestUpgrade(tier, token, depositorName || undefined);
            setSelectedPlan(tier);
            setShowBank(true);
        } catch (err: any) {
            const msg = err?.message || '';
            if (msg.includes('pending')) {
                setSelectedPlan(tier);
                setShowBank(true);
            } else {
                alert('구독 신청 중 오류가 발생했습니다.');
            }
        } finally {
            setRequesting(null);
        }
    };

    const freeFeatures = [
        'Summary 대시보드',
        '글로벌 시장 지수 실시간',
        '조간/마감 브리핑 요약',
    ];

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

    // 구독 만료일 자동 산출
    const getExpiryDate = () => {
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

            {/* Plans Grid — 3 columns */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5 max-w-5xl w-full">
                {/* Free Plan */}
                <div className="p-6 rounded-2xl border border-white/10 bg-[#1c1c1e]">
                    <h3 className="text-xl font-bold text-white mb-1">Free</h3>
                    <div className="flex items-baseline gap-1 mb-5">
                        <span className="text-3xl font-black text-white">무료</span>
                    </div>
                    <ul className="space-y-2.5 mb-6">
                        {freeFeatures.map((f) => (
                            <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                                <i className="fas fa-check text-green-400 text-xs mt-1 shrink-0" />
                                {f}
                            </li>
                        ))}
                        {proFeatures.slice(1, 5).map((m) => (
                            <li key={m} className="flex items-start gap-2 text-sm text-gray-600">
                                <i className="fas fa-lock text-gray-700 text-xs mt-1 shrink-0" />
                                {m}
                            </li>
                        ))}
                    </ul>
                    <div className="w-full py-3 rounded-xl bg-white/5 text-gray-500 font-bold text-center text-sm">
                        {userTier === 'free' ? '현재 플랜' : '기본 플랜'}
                    </div>
                </div>

                {/* Pro Plan */}
                <div className="p-6 rounded-2xl border border-amber-500/30 bg-[#1c1c1e] ring-1 ring-amber-500/20 relative">
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 text-xs font-bold mb-3">
                        <i className="fas fa-crown" /> 추천
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
                            onClick={() => handleUpgrade('pro')}
                            disabled={requesting !== null}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting === 'pro' ? '처리 중...' : 'Pro 구독 신청'}
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
                            onClick={() => handleUpgrade('premium')}
                            disabled={requesting !== null}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-500 to-fuchsia-500 hover:from-purple-400 hover:to-fuchsia-400 text-white font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting === 'premium' ? '처리 중...' : 'Ultra Pro 구매'}
                        </button>
                    )}
                </div>
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

                    {/* 카카오톡 문의 */}
                    <a
                        href="https://open.kakao.com/o/sJVLbWUe"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-4 flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-[#FEE500]/10 hover:bg-[#FEE500]/20 text-[#FEE500] font-bold text-sm transition-all border border-[#FEE500]/20"
                    >
                        <i className="fas fa-comment" />
                        카카오톡 문의하기
                    </a>
                </div>
            )}

            {!showBank && userTier === 'free' && user && (
                <button
                    onClick={() => setShowBank(true)}
                    className="mt-6 text-amber-400/70 hover:text-amber-400 transition-colors text-sm"
                >
                    <i className="fas fa-university mr-2" />계좌 정보 보기
                </button>
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
