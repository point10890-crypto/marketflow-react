import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { BANK_ACCOUNT } from '@/lib/billingInfo';
import { subscriptionAPI, type SubscriptionRequest } from '@/lib/api';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

const FLOW_STEPS = ['계정 생성', '플랜 선택', '입금 정보', '승인 대기'];

/**
 * 승인 대기 페이지 — 모든 sub_req (신규 가입 + AI Brain 애드온 + 업그레이드) 공통.
 *
 * 동작:
 * - 마운트 + 30s 폴링: subscriptionAPI.getStatus() 로 최신 sub_req fetch
 * - 실제 sub_req.amount + admin_note (AI Brain 마커) 표시
 * - 활성 회원 (Pro/Premium) 도 pending sub_req 가 있으면 페이지 유지 (예: AI Brain 애드온 신청)
 * - sub_req 가 approved 되거나 없어지면 대시보드로 자동 이동
 */
export default function PendingApprovalPage() {
    const { user, token, logout, refreshUser } = useAuth();
    const navigate = useNavigate();
    const [checking, setChecking] = useState(false);
    const [message, setMessage] = useState('');
    const [pendingSubReq, setPendingSubReq] = useState<SubscriptionRequest | null>(null);
    const [subReqLoaded, setSubReqLoaded] = useState(false);
    const pollRef = useRef<number | null>(null);

    const fetchSubReq = useCallback(async () => {
        if (!token) return null;
        try {
            const resp = await subscriptionAPI.getStatus(token);
            const pending = (resp.requests || []).find((r) => r.status === 'pending') || null;
            setPendingSubReq(pending);
            return pending;
        } catch {
            return null;
        } finally {
            setSubReqLoaded(true);
        }
    }, [token]);

    // 초기 1회 sub_req fetch
    useEffect(() => {
        fetchSubReq();
    }, [fetchSubReq]);

    // 자동 리다이렉트 — admin / 활성 회원 + pending sub_req 없을 때만 이동
    useEffect(() => {
        if (!user || !subReqLoaded) return;
        if (user.role === 'admin') {
            navigate('/admin', { replace: true });
            return;
        }
        const isActive = user.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium');
        if (isActive && !pendingSubReq) {
            // 활성 회원인데 pending sub_req 가 없음 → 대시보드로
            navigate('/dashboard', { replace: true });
        }
    }, [user, navigate, pendingSubReq, subReqLoaded]);

    // 30초 폴링 — user 상태 + sub_req 둘 다 refresh
    useEffect(() => {
        const tick = () => {
            refreshUser().catch(() => {});
            fetchSubReq();
        };
        pollRef.current = window.setInterval(tick, 30000);
        return () => {
            if (pollRef.current) window.clearInterval(pollRef.current);
        };
    }, [refreshUser, fetchSubReq]);

    const handleCheckStatus = async () => {
        setChecking(true);
        setMessage('');
        try {
            await refreshUser();
            const sr = await fetchSubReq();
            setTimeout(() => {
                const stored = localStorage.getItem('auth_user') || sessionStorage.getItem('auth_user');
                if (stored) {
                    const parsed = JSON.parse(stored);
                    const hasAccess = parsed.status === 'approved' && (parsed.tier === 'pro' || parsed.tier === 'premium');
                    // 활성 + sub_req 없음 = 승인 완료
                    if ((hasAccess && !sr) || parsed.role === 'admin') {
                        setMessage('승인되었습니다! 대시보드로 이동합니다.');
                        setTimeout(() => navigate('/dashboard'), 1000);
                        return;
                    }
                }
                setMessage('아직 승인 대기 중입니다.');
                setChecking(false);
            }, 500);
        } catch {
            setMessage('서버 연결에 실패했습니다.');
            setChecking(false);
        }
    };

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // sub_req 로부터 표시 정보 도출
    const isAibainAddon = pendingSubReq?.request_type === 'aibain_addon';
    const includesAibain = !!pendingSubReq?.admin_note?.includes('AI Brain');
    const subReqAmount = pendingSubReq?.amount || null;

    // 색상 테마 — AI Brain 포함이면 cyan, 아니면 amber
    const themeColor = includesAibain
        ? { border: 'border-cyan-500/30', bg: 'bg-cyan-500/10', text: 'text-cyan-300', accentBg: 'bg-cyan-500/[0.06]', accentBorder: 'border-cyan-500/20' }
        : { border: 'border-amber-500/20', bg: 'bg-amber-500/10', text: 'text-amber-400', accentBg: 'bg-amber-500/[0.06]', accentBorder: 'border-amber-500/20' };

    // 헤더 / 안내 문구 분기
    const isUpgradeFromActive = user?.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium');
    let headerTitle = '승인 대기 중';
    let headerSubtitle = '구독 신청이 접수되었습니다. 입금 확인 후 관리자가 서비스를 활성화합니다.';
    if (!pendingSubReq && !isUpgradeFromActive) {
        headerTitle = '플랜 선택이 필요합니다';
        headerSubtitle = '계정은 만들어졌지만 아직 구독 신청이 접수되지 않았습니다. 플랜을 선택하면 입금 안내와 승인 신청이 이어집니다.';
    }
    if (isAibainAddon) {
        headerTitle = 'AI Brain 활성화 대기 중';
        headerSubtitle = '입금 확인 후 관리자가 AI Brain 알파 스캐너 서비스를 활성화합니다. 그 동안 기존 구독은 그대로 이용 가능합니다.';
    } else if (isUpgradeFromActive) {
        headerTitle = '업그레이드 대기 중';
        headerSubtitle = '입금 확인 후 관리자가 새 플랜으로 업그레이드합니다.';
    }

    return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4">
            <div className="w-full max-w-lg text-center">
                <div className="mb-4 grid grid-cols-4 gap-2">
                    {FLOW_STEPS.map((step, index) => (
                        <div
                            key={step}
                            className={`rounded-xl border px-2 py-2 text-center text-[10px] font-bold ${
                                index === 3
                                    ? 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200'
                                    : 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'
                            }`}
                        >
                            <div className="mb-1 text-[11px]">{index + 1}</div>
                            {step}
                        </div>
                    ))}
                </div>
                <div className={`p-8 rounded-2xl bg-[#1c1c1e] border ${themeColor.border}`}>
                    <div className={`w-16 h-16 mx-auto mb-6 ${themeColor.bg} rounded-full flex items-center justify-center`}>
                        <i className={`${!pendingSubReq && !isUpgradeFromActive ? 'fas fa-credit-card' : isAibainAddon ? 'fas fa-robot' : 'fas fa-hourglass-half'} text-2xl ${themeColor.text}`}></i>
                    </div>

                    <h1 className="text-2xl font-bold text-white mb-2">{headerTitle}</h1>
                    <p className="text-gray-400 text-sm mb-6 leading-relaxed">{headerSubtitle}</p>
                    <p className="text-gray-600 text-[11px] mb-4">
                        30초마다 자동으로 승인 상태를 확인합니다.
                    </p>

                    {user && (
                        <div className="p-3 rounded-lg bg-white/5 mb-6 text-left">
                            <div className="text-[10px] text-gray-500 mb-1">가입 정보</div>
                            <div className="text-sm text-white">{user.name}</div>
                            <div className="text-xs text-gray-400 mb-2">{user.email}</div>
                            {pendingSubReq && (
                                <div className="mt-2 pt-2 border-t border-white/5 space-y-1.5">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-[10px] text-gray-500">요청:</span>
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${themeColor.bg} ${themeColor.text}`}>
                                            <i className={`${isAibainAddon ? 'fas fa-robot' : pendingSubReq.to_tier === 'premium' ? 'fas fa-gem' : 'fas fa-crown'} mr-1`} />
                                            {isAibainAddon
                                                ? `${pendingSubReq.from_tier === 'premium' ? 'Ultra Pro' : 'Pro'} → +AI Brain 애드온`
                                                : includesAibain
                                                ? `${pendingSubReq.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'} + AI Brain`
                                                : pendingSubReq.to_tier === 'premium' ? 'Ultra Pro' : 'Pro'}
                                        </span>
                                    </div>
                                    {pendingSubReq.admin_note && (
                                        <p className="text-[11px] text-gray-400 leading-relaxed pl-1">
                                            <i className="fas fa-info-circle mr-1 text-cyan-400/70" />
                                            {pendingSubReq.admin_note}
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    <div className={`p-4 rounded-xl ${themeColor.accentBg} border ${themeColor.accentBorder} mb-6 text-left`}>
                        <div className="flex items-start gap-3 mb-4">
                            <div className={`w-10 h-10 rounded-xl ${themeColor.bg} flex items-center justify-center shrink-0`}>
                                <i className={`fas fa-university ${themeColor.text}`} />
                            </div>
                            <div>
                                <h2 className="text-white font-bold text-sm">입금 계좌 정보</h2>
                                <p className="text-gray-400 text-xs mt-0.5">
                                    {isAibainAddon
                                        ? '입금 확인 후 AI Brain 알파 스캐너가 30일간 활성화됩니다.'
                                        : '입금 확인 후 관리자가 구독을 활성화합니다.'}
                                </p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                                <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.bank}</p>
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                                <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.holder}</p>
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06] sm:col-span-2">
                                <div className="flex items-center justify-between gap-3">
                                    <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                                    <button
                                        type="button"
                                        onClick={() => navigator.clipboard?.writeText(BANK_ACCOUNT.account.replace(/-/g, ''))}
                                        className="text-[10px] text-gray-400 hover:text-white transition-colors"
                                    >
                                        <i className="fas fa-copy mr-1" />복사
                                    </button>
                                </div>
                                <p className="text-white font-bold mt-1 font-mono text-lg tracking-wider">{BANK_ACCOUNT.account}</p>
                            </div>
                            <div className={`p-3 rounded-lg ${themeColor.accentBg} border ${themeColor.accentBorder}`}>
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">입금 금액</span>
                                <p className={`font-bold mt-1 text-base ${themeColor.text}`}>
                                    {subReqAmount || '플랜 선택 후 확정'}
                                </p>
                                {isAibainAddon && (
                                    <p className="text-[10px] text-gray-500 mt-0.5">AI Brain 30일 갱신</p>
                                )}
                            </div>
                            <div className="p-3 rounded-lg bg-black/20 border border-white/[0.06]">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">입금자명</span>
                                <p className="text-white font-bold mt-1 text-sm">
                                    {pendingSubReq?.depositor_name || user?.name || '가입 시 이름'}
                                </p>
                            </div>
                        </div>

                        <p className="mt-3 text-[11px] leading-relaxed text-gray-400">
                            입금자명은 가입 이름과 동일하게 보내 주세요.
                            {isAibainAddon
                                ? ' AI Brain 만료 시 별도 갱신 없으면 자동으로 기존 베이스 플랜으로 회귀합니다.'
                                : pendingSubReq && includesAibain
                                ? ' AI Brain 알파 스캐너 알림이 30일간 활성화됩니다.'
                                : !pendingSubReq
                                ? ' 아직 플랜을 선택하지 않았다면 아래 버튼에서 먼저 플랜을 선택해 주세요.'
                                : ''}
                        </p>
                    </div>

                    {message && (
                        <div className={`p-3 rounded-lg mb-4 text-sm ${message.includes('승인되었습니다') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-gray-400'}`}>
                            {message}
                        </div>
                    )}

                    <div className="space-y-3">
                        {!pendingSubReq && !isUpgradeFromActive && (
                            <button
                                onClick={() => navigate('/plan-select')}
                                className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all flex items-center justify-center gap-2"
                            >
                                <i className="fas fa-credit-card" />
                                플랜 선택하기
                            </button>
                        )}
                        {isUpgradeFromActive && (
                            <button
                                onClick={() => navigate('/dashboard')}
                                className="w-full py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-medium transition-all"
                            >
                                <i className="fas fa-arrow-left mr-2" />
                                대시보드로 돌아가기
                            </button>
                        )}
                        <button
                            onClick={handleCheckStatus}
                            disabled={checking}
                            className="w-full py-3 rounded-xl bg-white/10 hover:bg-white/15 text-white font-medium transition-all disabled:opacity-50"
                        >
                            {checking ? '확인 중...' : '승인 상태 확인'}
                        </button>
                        {!isUpgradeFromActive && (
                            <button
                                onClick={handleLogout}
                                className="w-full py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 font-medium transition-all"
                            >
                                로그아웃
                            </button>
                        )}
                        <KakaoSupportLink />
                    </div>
                </div>
            </div>
        </div>
    );
}
