import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { BANK_ACCOUNT, PLAN_PAYMENT_META } from '@/lib/billingInfo';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

type LoginUser = {
    role?: string;
    status?: string;
    tier?: string | null;
    is_pro_expired?: boolean;
};

function safeNextPath(value: string | null): string | null {
    if (!value) return null;
    try {
        const decoded = decodeURIComponent(value);
        if (!decoded.startsWith('/') || decoded.startsWith('//')) return null;
        return decoded;
    } catch {
        return null;
    }
}

function nextPathForUser(user: LoginUser, nextPath: string | null): string {
    if (user.role === 'admin') {
        return nextPath?.startsWith('/admin') ? nextPath : '/admin';
    }
    if (user.status === 'expired' || user.is_pro_expired) {
        return '/plan-select?resubscribe=1&from=expired';
    }
    if (!user.tier) {
        return '/plan-select';
    }
    if (user.status !== 'approved') {
        return '/pending-approval';
    }
    if (user.tier !== 'pro' && user.tier !== 'premium') {
        return '/plan-select';
    }
    return nextPath?.startsWith('/dashboard') ? nextPath : '/dashboard';
}

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [remember, setRemember] = useState(true);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login, user, loading: authLoading } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const nextPath = safeNextPath(searchParams.get('next'));

    useEffect(() => {
        if (authLoading || !user || user.status === 'unknown') return;
        navigate(nextPathForUser(user, nextPath), { replace: true });
    }, [user, authLoading, navigate, nextPath]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await login(email, password, remember);
            const stored = localStorage.getItem('auth_user') || sessionStorage.getItem('auth_user');
            if (stored) {
                try {
                    navigate(nextPathForUser(JSON.parse(stored), nextPath), { replace: true });
                    return;
                } catch {
                    // corrupted storage: fall through to dashboard
                }
            }
            navigate(nextPath?.startsWith('/dashboard') ? nextPath : '/dashboard', { replace: true });
        } catch (err) {
            setError((err as Error).message || '이메일 또는 비밀번호를 확인해 주세요.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4 py-8">
            <div className="w-full max-w-md">
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-bold text-white tracking-tighter mb-2">
                        Market<span className="text-[#2997ff]">Flow</span>
                    </h1>
                    <p className="text-gray-400 font-semibold">로그인 후 상태에 맞는 다음 단계로 이동합니다.</p>
                    <p className="text-gray-600 text-xs mt-1">승인 대기, 구독 만료, 재구독 신청도 같은 계정으로 이어집니다.</p>
                </div>

                <form onSubmit={handleSubmit} className="p-8 rounded-2xl bg-[#1c1c1e] border border-white/10 space-y-5">
                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm">{error}</div>
                    )}
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">이메일</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="you@example.com"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">비밀번호</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            minLength={6}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="비밀번호"
                        />
                    </div>
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                        <input
                            type="checkbox"
                            checked={remember}
                            onChange={(e) => setRemember(e.target.checked)}
                            className="w-4 h-4 rounded border-white/20 bg-white/5 text-[#2997ff] focus:ring-[#2997ff] focus:ring-offset-0 accent-[#2997ff]"
                        />
                        <span className="text-sm text-gray-400">로그인 유지</span>
                    </label>
                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all disabled:opacity-50"
                    >
                        {loading ? '로그인 중...' : '로그인'}
                    </button>
                    <p className="text-center text-sm text-gray-500">
                        처음 오셨나요?{' '}
                        <Link to="/signup" className="text-[#2997ff] hover:underline">가입하고 구독 시작</Link>
                    </p>
                </form>

                <div className="mt-4 p-4 rounded-2xl bg-[#13151f] border border-amber-500/20">
                    <div className="flex items-center gap-3 mb-3">
                        <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center">
                            <i className="fas fa-university text-amber-400" />
                        </div>
                        <div>
                            <h2 className="text-white font-bold text-sm">결제 계좌 정보</h2>
                            <p className="text-gray-500 text-xs">가입, 구독 신청, 재구독 입금 확인용</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <InfoBox label="은행" value={BANK_ACCOUNT.bank} />
                        <InfoBox label="예금주" value={BANK_ACCOUNT.holder} />
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] col-span-2">
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
                        <InfoBox label="Pro" value={PLAN_PAYMENT_META.pro.amount} sub={PLAN_PAYMENT_META.pro.period} valueClass="text-amber-400" />
                        <InfoBox label="Pro + AI Brain" value={PLAN_PAYMENT_META.pro_aibain.amount} sub="Pro + AI Brain 30일" valueClass="text-cyan-300" />
                        <InfoBox label="Ultra Pro" value={PLAN_PAYMENT_META.premium.amount} sub={PLAN_PAYMENT_META.premium.period} valueClass="text-purple-300" />
                        <InfoBox label="Ultra + AI Brain" value={PLAN_PAYMENT_META.premium_aibain.amount} sub="평생 + AI Brain 30일" valueClass="text-fuchsia-300" />
                    </div>
                </div>
                <KakaoSupportLink className="mt-3" />
            </div>
        </div>
    );
}

function InfoBox({
    label,
    value,
    sub,
    valueClass = 'text-white',
}: {
    label: string;
    value: string;
    sub?: string;
    valueClass?: string;
}) {
    return (
        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
            <p className={`${valueClass} font-bold mt-1 text-sm`}>{value}</p>
            {sub && <p className="text-gray-500 text-[10px] mt-0.5">{sub}</p>}
        </div>
    );
}
