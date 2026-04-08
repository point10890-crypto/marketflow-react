import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

export default function PendingApprovalPage() {
    const { user, logout, refreshUser } = useAuth();
    const navigate = useNavigate();
    const [checking, setChecking] = useState(false);
    const [message, setMessage] = useState('');
    const pollRef = useRef<number | null>(null);

    // user 가 승인 + tier 부여 상태가 되면 즉시 대시보드로
    useEffect(() => {
        if (!user) return;
        if (user.role === 'admin') {
            navigate('/admin', { replace: true });
            return;
        }
        if (user.status === 'approved' && (user.tier === 'pro' || user.tier === 'premium')) {
            navigate('/dashboard', { replace: true });
        }
    }, [user, navigate]);

    // 30초마다 자동 폴링 — 관리자가 승인하면 자동으로 대시보드 진입
    useEffect(() => {
        const tick = () => { refreshUser().catch(() => {}); };
        pollRef.current = window.setInterval(tick, 30000);
        return () => {
            if (pollRef.current) window.clearInterval(pollRef.current);
        };
    }, [refreshUser]);

    const handleCheckStatus = async () => {
        setChecking(true);
        setMessage('');
        try {
            await refreshUser();
            setTimeout(() => {
                const stored = localStorage.getItem('auth_user') || sessionStorage.getItem('auth_user');
                if (stored) {
                    const parsed = JSON.parse(stored);
                    const hasAccess = parsed.status === 'approved' && (parsed.tier === 'pro' || parsed.tier === 'premium');
                    if (hasAccess || parsed.role === 'admin') {
                        setMessage('승인되었습니다! 대시보드로 이동합니다.');
                        setTimeout(() => navigate('/dashboard'), 1000);
                        return;
                    }
                }
                setMessage('아직 승인 대기 중입니다. (Pro 이상 등급 부여 필요)');
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

    return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4">
            <div className="w-full max-w-md text-center">
                <div className="p-8 rounded-2xl bg-[#1c1c1e] border border-white/10">
                    <div className="w-16 h-16 mx-auto mb-6 bg-amber-500/10 rounded-full flex items-center justify-center">
                        <i className="fas fa-hourglass-half text-2xl text-amber-400"></i>
                    </div>

                    <h1 className="text-2xl font-bold text-white mb-2">승인 대기 중</h1>
                    <p className="text-gray-400 text-sm mb-6">
                        회원가입이 완료되었습니다.<br />
                        관리자가 Pro 또는 Ultra Pro 등급을 부여하면 서비스를 이용하실 수 있습니다.
                    </p>
                    <p className="text-gray-600 text-[11px] mb-4">
                        30초마다 자동으로 승인 상태를 확인합니다.
                    </p>

                    {user && (
                        <div className="p-3 rounded-lg bg-white/5 mb-6 text-left">
                            <div className="text-[10px] text-gray-500 mb-1">가입 정보</div>
                            <div className="text-sm text-white">{user.name}</div>
                            <div className="text-xs text-gray-400">{user.email}</div>
                        </div>
                    )}

                    {message && (
                        <div className={`p-3 rounded-lg mb-4 text-sm ${message.includes('승인되었습니다') ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-gray-400'}`}>
                            {message}
                        </div>
                    )}

                    <div className="space-y-3">
                        <button
                            onClick={handleCheckStatus}
                            disabled={checking}
                            className="w-full py-3 rounded-xl bg-amber-500 hover:bg-amber-400 text-black font-bold transition-all disabled:opacity-50"
                        >
                            {checking ? '확인 중...' : '승인 상태 확인'}
                        </button>
                        <button
                            onClick={handleLogout}
                            className="w-full py-3 rounded-xl bg-white/5 hover:bg-white/10 text-gray-400 font-medium transition-all"
                        >
                            로그아웃
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
