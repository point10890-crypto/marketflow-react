import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * 플랜 선택 페이지 — 신규 가입자 및 만료 재구독 공용.
 *
 * 진입 경로:
 *   - /signup 완료 직후
 *   - /pending-approval 의 "플랜 신청" 버튼
 *   - ApprovedGuard: is_pro_expired=true 인 유저 (만료 재구독)
 *   - /dashboard 상단 재구독 배너
 *
 * 선택 시 /payment-request?plan=X 로 이동.
 * 로그인 안 된 상태로 들어오면 /signup 으로 유도.
 */
export default function PlanSelectPage() {
    const { user, token, loading } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const isResubscribe = searchParams.get('resubscribe') === '1' || searchParams.get('from') === 'expired';

    // 가드 — loading 끝난 뒤에만 판정 (AuthContext 초기화 중 user=null 찰나 보호)
    useEffect(() => {
        if (loading) return;
        // 비인증 유저는 /signup 으로
        if (!user || !token) {
            navigate('/signup', { replace: true });
            return;
        }
        // admin 은 대시보드 (플랜 UI 노출 방지)
        if (user.role === 'admin') {
            navigate('/dashboard', { replace: true });
            return;
        }
        // 활성 구독 유저는 대시보드
        const isActive = (user.tier === 'pro' || user.tier === 'premium')
            && user.status === 'approved'
            && !user.is_pro_expired;
        if (isActive) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, token, loading, navigate]);

    const isExpired = !!user?.is_pro_expired || user?.status === 'expired' || isResubscribe;
    const isPending = user?.status === 'pending';
    // 만료된 user 의 expired_at 표시용
    const expiredAt = user?.pro_expires_at ? new Date(user.pro_expires_at) : null;

    const select = (plan: 'pro' | 'premium') => {
        navigate(`/payment-request?plan=${plan}`);
    };

    return (
        <div className="fixed inset-0 bg-[#09090b] flex flex-col items-center overflow-y-auto p-6 sm:p-8">
            {/* 만료 = 계정 정지 안내 (강조 배너) */}
            {isExpired && (
                <div className="w-full max-w-4xl mt-4 mb-6 rounded-2xl border-2 border-rose-500/40 bg-gradient-to-br from-rose-500/[0.12] via-amber-500/[0.05] to-slate-950/60 p-5 sm:p-6 backdrop-blur-md shadow-[0_8px_40px_rgba(244,63,94,0.18)]">
                    <div className="flex items-start gap-3">
                        <div className="grid h-10 w-10 sm:h-12 sm:w-12 shrink-0 place-items-center rounded-full bg-rose-500/20 text-rose-300 text-xl">
                            ⚠️
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                                <h2 className="text-lg sm:text-xl font-black text-rose-200">
                                    Pro 구독 만료 — 계정이 정지되었습니다
                                </h2>
                                <span className="inline-flex items-center rounded-full border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-[10px] font-black text-rose-200 uppercase tracking-wider">
                                    EXPIRED
                                </span>
                            </div>
                            <p className="mt-2 text-sm text-rose-100/80 leading-relaxed">
                                구독이 만료되어 데이터 페이지 접근이 차단되었습니다. 아래 플랜을 다시 선택해 재구독 신청해 주세요.
                            </p>
                            {expiredAt && (
                                <p className="mt-1 text-xs text-rose-200/60 tabular-nums">
                                    만료일: {expiredAt.toLocaleDateString('ko-KR')} {expiredAt.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <div className="text-center mt-2 sm:mt-6 mb-10">
                <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight mb-4">
                    {isExpired ? '재구독 플랜' : '플랜을 선택해 주세요'}
                </h1>
                <p className="text-gray-400 text-base sm:text-lg max-w-md mx-auto">
                    {isExpired
                        ? '서비스 재개를 위해 플랜을 다시 신청해 주세요.'
                        : isPending
                        ? '계정이 생성되었습니다. 구독 플랜을 선택하세요.'
                        : '원하시는 구독 플랜을 선택하세요.'}
                </p>
                {user && (
                    <p className="text-gray-600 text-xs mt-2">
                        로그인: <span className="text-gray-400">{user.email}</span>
                    </p>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 max-w-4xl w-full">
                {/* Pro */}
                <button
                    type="button"
                    onClick={() => select('pro')}
                    className="p-6 rounded-2xl border border-amber-500/30 bg-[#1c1c1e] ring-1 ring-amber-500/20 hover:ring-2 hover:ring-amber-500/50 transition-all text-left relative"
                >
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-amber-500/10 text-amber-400 text-xs font-bold mb-3">
                        <i className="fas fa-crown" /> 추천
                    </div>
                    <h3 className="text-xl font-bold text-white mb-1">Pro</h3>
                    <div className="flex items-baseline gap-1 mb-1">
                        <span className="text-3xl font-black text-white">50,000</span>
                        <span className="text-gray-400">원/30일</span>
                    </div>
                    <p className="text-amber-400/70 text-xs font-semibold mb-5">월 갱신 · 30일 이용</p>
                    <ul className="space-y-2 mb-6 text-sm text-gray-300">
                        <li className="flex items-start gap-2"><i className="fas fa-check text-amber-400 text-xs mt-1" />모든 기능 풀 접근</li>
                        <li className="flex items-start gap-2"><i className="fas fa-check text-amber-400 text-xs mt-1" />KR / US / Crypto 시그널</li>
                        <li className="flex items-start gap-2"><i className="fas fa-check text-amber-400 text-xs mt-1" />AI 챗봇 + 차트 분석</li>
                        <li className="flex items-start gap-2"><i className="fas fa-check text-amber-400 text-xs mt-1" />텔레그램 실시간 알림</li>
                    </ul>
                    <div className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-black font-bold text-center text-sm">
                        Pro 선택 →
                    </div>
                </button>

                {/* Ultra Pro */}
                <button
                    type="button"
                    onClick={() => select('premium')}
                    className="p-6 rounded-2xl border border-purple-500/30 bg-[#1c1c1e] ring-1 ring-purple-500/20 hover:ring-2 hover:ring-purple-500/50 transition-all text-left relative overflow-hidden"
                >
                    <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-bl from-purple-500/10 to-transparent rounded-bl-full pointer-events-none" />
                    <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 text-xs font-bold mb-3">
                        <i className="fas fa-gem" /> 평생 이용
                    </div>
                    <h3 className="text-xl font-bold text-white mb-1">Ultra Pro</h3>
                    <div className="flex items-baseline gap-1 mb-1">
                        <span className="text-3xl font-black text-white">1,200,000</span>
                        <span className="text-gray-400">원</span>
                    </div>
                    <p className="text-purple-400/70 text-xs font-semibold mb-5">1회 결제 · 무기한 이용</p>
                    <ul className="space-y-2 mb-6 text-sm text-gray-300">
                        <li className="flex items-start gap-2"><i className="fas fa-check text-purple-400 text-xs mt-1" />Pro 전체 기능 포함</li>
                        <li className="flex items-start gap-2"><i className="fas fa-infinity text-purple-400 text-xs mt-1" />평생 무기한 이용</li>
                        <li className="flex items-start gap-2"><i className="fas fa-sync text-purple-400 text-xs mt-1" />향후 업데이트 전부 포함</li>
                        <li className="flex items-start gap-2"><i className="fas fa-headset text-purple-400 text-xs mt-1" />우선 고객 지원</li>
                    </ul>
                    <div className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-500 to-fuchsia-500 text-white font-bold text-center text-sm">
                        Ultra Pro 선택 →
                    </div>
                </button>
            </div>

            <p className="text-gray-500 text-xs mt-8 text-center max-w-md">
                선택 후 국민은행 계좌로 입금 → 관리자 확인 후 활성화 (최대 24시간).<br />
                Ultra Pro 는 24개월 이상 이용 시 Pro 대비 절반 이하 비용입니다.
            </p>

            <div className="mt-6 flex items-center gap-4 text-xs">
                <a href="/" className="text-gray-500 hover:text-white transition-colors">
                    <i className="fas fa-arrow-left mr-1" />홈으로
                </a>
                {user && (
                    <button
                        type="button"
                        onClick={() => {
                            localStorage.removeItem('auth_token');
                            sessionStorage.removeItem('auth_token');
                            localStorage.removeItem('auth_user');
                            sessionStorage.removeItem('auth_user');
                            navigate('/login', { replace: true });
                        }}
                        className="text-gray-500 hover:text-red-400 transition-colors"
                    >
                        <i className="fas fa-sign-out-alt mr-1" />로그아웃
                    </button>
                )}
            </div>
        </div>
    );
}
