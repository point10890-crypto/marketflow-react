import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { subscriptionAPI, type SubscriptionRequest } from '@/lib/api';

export default function AccountPage() {
    const { user, token, refreshUser } = useAuth();
    const [requests, setRequests] = useState<SubscriptionRequest[]>([]);
    const [loading, setLoading] = useState(true);
    const [requesting, setRequesting] = useState(false);
    const [showBank, setShowBank] = useState(false);

    const isPro = user?.tier === 'pro' || user?.tier === 'premium';
    const hasPending = requests.some(r => r.status === 'pending');

    useEffect(() => {
        if (!token) return;
        (async () => {
            try {
                const data = await subscriptionAPI.getStatus(token);
                setRequests(data.requests || []);
            } catch { /* ignore */ }
            setLoading(false);
        })();
    }, [token]);

    const handleRequest = async () => {
        if (!token || isPro || hasPending) return;
        setRequesting(true);
        try {
            await subscriptionAPI.requestUpgrade('pro', token);
            setShowBank(true);
            // Refresh status
            const data = await subscriptionAPI.getStatus(token);
            setRequests(data.requests || []);
        } catch {
            alert('구독 신청 중 오류가 발생했습니다.');
        }
        setRequesting(false);
    };

    const handleRefresh = async () => {
        if (!token) return;
        await refreshUser();
        const data = await subscriptionAPI.getStatus(token);
        setRequests(data.requests || []);
    };

    const statusBadge = (status: string) => {
        const styles: Record<string, string> = {
            pending: 'bg-yellow-500/10 text-yellow-400',
            approved: 'bg-green-500/10 text-green-400',
            rejected: 'bg-red-500/10 text-red-400',
        };
        const labels: Record<string, string> = {
            pending: '대기 중',
            approved: '승인됨',
            rejected: '거절됨',
        };
        return (
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${styles[status] || 'bg-gray-500/10 text-gray-400'}`}>
                {labels[status] || status}
            </span>
        );
    };

    if (!user) {
        return (
            <div className="flex items-center justify-center h-full min-h-[400px]">
                <div className="text-center">
                    <p className="text-gray-400 mb-4">로그인이 필요합니다</p>
                    <Link to="/login" className="px-6 py-3 bg-amber-500 text-black font-bold rounded-xl">로그인</Link>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-2xl mx-auto space-y-6">
            <h1 className="text-2xl font-black text-white">내 계정</h1>

            {/* Profile Card */}
            <div className="p-6 rounded-2xl border border-white/[0.07] bg-[#13151f]">
                <div className="flex items-center gap-4 mb-6">
                    <div className="w-14 h-14 rounded-full bg-gradient-to-br from-amber-500 to-orange-500 flex items-center justify-center text-black text-xl font-black">
                        {user.name?.charAt(0)?.toUpperCase() || 'U'}
                    </div>
                    <div>
                        <h2 className="text-lg font-bold text-white">{user.name}</h2>
                        <p className="text-gray-500 text-sm">{user.email}</p>
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                        <span className="text-[10px] text-gray-500 uppercase tracking-wider">플랜</span>
                        <div className="flex items-center gap-2 mt-1">
                            {isPro ? (
                                <span className="text-amber-400 font-bold flex items-center gap-1.5">
                                    <i className="fas fa-crown text-xs" /> Pro
                                </span>
                            ) : (
                                <span className="text-gray-400 font-bold">Free</span>
                            )}
                        </div>
                    </div>
                    <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                        <span className="text-[10px] text-gray-500 uppercase tracking-wider">상태</span>
                        <p className="text-green-400 font-bold mt-1 flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-green-400" />
                            {user.status === 'approved' ? '활성' : user.status}
                        </p>
                    </div>
                </div>
            </div>

            {/* Subscription Action */}
            {!isPro && (
                <div className="p-6 rounded-2xl border border-amber-500/20 bg-[#13151f]">
                    <div className="flex items-center gap-3 mb-4">
                        <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                            <i className="fas fa-crown text-amber-400" />
                        </div>
                        <div>
                            <h3 className="text-white font-bold">Pro 플랜으로 업그레이드</h3>
                            <p className="text-gray-500 text-xs">월 50,000원 · 계좌이체</p>
                        </div>
                    </div>

                    <p className="text-gray-400 text-sm mb-4">
                        KR/US/Crypto 전체 대시보드, VCP Enhanced, W Pattern AI, ProPicks, AI Briefing 등 모든 기능을 이용할 수 있습니다.
                    </p>

                    {hasPending ? (
                        <div className="flex items-center gap-3">
                            <div className="flex-1 py-3 rounded-xl bg-yellow-500/10 text-yellow-400 font-bold text-center text-sm">
                                <i className="fas fa-clock mr-2" />구독 신청 대기 중
                            </div>
                            <button onClick={handleRefresh} className="px-4 py-3 rounded-xl bg-white/5 text-gray-400 hover:text-white transition-colors text-sm">
                                <i className="fas fa-sync-alt" />
                            </button>
                        </div>
                    ) : (
                        <button
                            onClick={handleRequest}
                            disabled={requesting}
                            className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black font-bold transition-all text-sm disabled:opacity-50"
                        >
                            {requesting ? '처리 중...' : 'Pro 구독 신청하기'}
                        </button>
                    )}
                </div>
            )}

            {/* Bank Transfer Info */}
            {!isPro && (showBank || hasPending) && (
                <div className="p-6 rounded-2xl border border-white/[0.07] bg-[#13151f]">
                    <div className="flex items-center gap-3 mb-4">
                        <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center">
                            <i className="fas fa-university text-blue-400" />
                        </div>
                        <div>
                            <h3 className="text-white font-bold">계좌이체 안내</h3>
                            <p className="text-gray-500 text-xs">아래 계좌로 입금해 주세요</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                            <p className="text-white font-bold mt-1 text-sm">카카오뱅크</p>
                        </div>
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">계좌번호</span>
                            <p className="text-white font-bold mt-1 text-sm font-mono">3333-00-1234567</p>
                        </div>
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                            <p className="text-white font-bold mt-1 text-sm">BitMan</p>
                        </div>
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">금액</span>
                            <p className="text-amber-400 font-bold mt-1 text-sm">50,000원 / 월</p>
                        </div>
                    </div>
                    <p className="text-gray-500 text-xs mt-3">
                        <i className="fas fa-info-circle mr-1" />
                        입금자명을 가입 시 이름과 동일하게 입력해 주세요. 확인 후 24시간 내 Pro 플랜이 활성화됩니다.
                    </p>
                </div>
            )}

            {/* Request History */}
            {!loading && requests.length > 0 && (
                <div className="p-6 rounded-2xl border border-white/[0.07] bg-[#13151f]">
                    <h3 className="text-white font-bold mb-4">구독 신청 이력</h3>
                    <div className="space-y-3">
                        {requests.map(r => (
                            <div key={r.id} className="flex items-center justify-between p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                                <div className="flex items-center gap-3">
                                    {statusBadge(r.status)}
                                    <span className="text-gray-400 text-sm">
                                        {r.from_tier} → {r.to_tier}
                                    </span>
                                </div>
                                <span className="text-gray-600 text-xs">
                                    {new Date(r.created_at).toLocaleDateString('ko-KR')}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Pro Status */}
            {isPro && (
                <div className="p-6 rounded-2xl border border-green-500/20 bg-[#13151f]">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-green-500/10 flex items-center justify-center">
                            <i className="fas fa-check-circle text-green-400" />
                        </div>
                        <div>
                            <h3 className="text-white font-bold">Pro 플랜 이용 중</h3>
                            <p className="text-gray-500 text-xs">모든 대시보드 기능을 이용하실 수 있습니다</p>
                        </div>
                    </div>
                </div>
            )}

            {/* Links */}
            <div className="flex items-center gap-4 pt-2">
                <Link to="/dashboard" className="text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-arrow-left mr-2" />대시보드
                </Link>
                <Link to="/pricing" className="text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-tag mr-2" />요금 안내
                </Link>
            </div>
        </div>
    );
}
