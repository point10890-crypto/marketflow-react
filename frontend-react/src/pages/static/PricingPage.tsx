import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI } from '@/lib/api';

export default function PricingPage() {
    const { user, token } = useAuth();
    const navigate = useNavigate();
    const userTier = user?.tier || 'free';
    const [requesting, setRequesting] = useState(false);
    const [showBank, setShowBank] = useState(false);
    const [requestSent, setRequestSent] = useState(false);

    const handleUpgrade = async () => {
        if (!user || !token) {
            navigate('/signup');
            return;
        }
        if (userTier === 'pro' || userTier === 'premium') return;

        setRequesting(true);
        try {
            await subscriptionAPI.requestUpgrade('pro', token);
            setRequestSent(true);
            setShowBank(true);
        } catch (err: any) {
            const msg = err?.message || '';
            if (msg.includes('pending')) {
                setShowBank(true);
            } else {
                alert('구독 신청 중 오류가 발생했습니다.');
            }
        } finally {
            setRequesting(false);
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
        '텔레그램 실시간 알림',
        '관심종목 분석 챗봇',
    ];

    return (
        <div className="min-h-screen bg-[#09090b] flex flex-col items-center p-6 sm:p-8">
            {/* Header */}
            <div className="text-center mt-8 sm:mt-16 mb-10 sm:mb-14">
                <Link to="/" className="inline-flex items-center gap-2 mb-6 text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-arrow-left" />
                    홈으로
                </Link>
                <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight mb-4">
                    요금 <span className="bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">플랜</span>
                </h1>
                <p className="text-gray-400 text-base sm:text-lg max-w-md mx-auto">
                    AI 기반 마켓 인사이트로 투자 의사결정을 업그레이드하세요
                </p>
            </div>

            {/* Plans Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl w-full">
                {/* Free Plan */}
                <div className="p-6 sm:p-8 rounded-2xl border border-white/10 bg-[#1c1c1e]">
                    <h3 className="text-2xl font-bold text-white mb-1">Free</h3>
                    <div className="flex items-baseline gap-1 mb-6">
                        <span className="text-4xl font-black text-white">무료</span>
                    </div>
                    <ul className="space-y-3 mb-8">
                        {freeFeatures.map((f) => (
                            <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                                <i className="fas fa-check text-green-400 text-xs mt-1 shrink-0" />
                                {f}
                            </li>
                        ))}
                        {proFeatures.slice(1).map((m) => (
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
                <div className="p-6 sm:p-8 rounded-2xl border border-amber-500/30 bg-[#1c1c1e] ring-1 ring-amber-500/20 relative">
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 text-xs font-bold mb-4">
                        <i className="fas fa-crown" /> 추천
                    </div>
                    <h3 className="text-2xl font-bold text-white mb-1">Pro</h3>
                    <div className="flex items-baseline gap-1 mb-6">
                        <span className="text-4xl font-black text-white">50,000</span>
                        <span className="text-gray-400 text-lg">원/월</span>
                    </div>
                    <ul className="space-y-3 mb-8">
                        {proFeatures.map((f) => (
                            <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                                <i className="fas fa-check text-amber-400 text-xs mt-1 shrink-0" />
                                {f}
                            </li>
                        ))}
                    </ul>

                    {userTier === 'pro' || userTier === 'premium' ? (
                        <div className="w-full py-3 rounded-xl bg-amber-500/10 text-amber-400 font-bold text-center text-sm">
                            <i className="fas fa-check-circle mr-2" />현재 플랜
                        </div>
                    ) : (
                        <button
                            onClick={handleUpgrade}
                            disabled={requesting}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting ? '처리 중...' : requestSent ? '신청 완료!' : 'Pro 구독 신청'}
                        </button>
                    )}
                </div>
            </div>

            {/* Bank Transfer Info */}
            {showBank && (
                <div className="mt-8 max-w-4xl w-full p-6 rounded-2xl border border-amber-500/20 bg-[#1c1c1e] animate-in fade-in duration-300">
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
                            <p className="text-white font-bold mt-1">카카오뱅크</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                            <p className="text-white font-bold mt-1 font-mono">3333-00-1234567</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                            <p className="text-white font-bold mt-1">BitMan</p>
                        </div>
                        <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">금액</span>
                            <p className="text-amber-400 font-bold mt-1">50,000원 / 월</p>
                        </div>
                    </div>
                    <p className="text-gray-500 text-xs mt-4">
                        <i className="fas fa-info-circle mr-1" />
                        입금자명을 가입 시 사용한 이름과 동일하게 입력해 주세요. 확인 후 관리자가 Pro 플랜을 활성화합니다.
                    </p>
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
            <div className="mt-12 flex items-center gap-6">
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
