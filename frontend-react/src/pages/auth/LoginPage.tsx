import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { BANK_ACCOUNT, PLAN_PAYMENT_META } from '@/lib/billingInfo';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [remember, setRemember] = useState(true);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login, user, loading: authLoading } = useAuth();
    const navigate = useNavigate();

    // 이미 로그인 상태면 적절한 페이지로 리다이렉트.
    // authLoading=true 인 동안에는 hydration 중이므로 절대 리다이렉트하지 않음
    // (synthesized status='unknown' 단계에서 잘못된 위치로 튀는 것을 막는다).
    useEffect(() => {
        if (authLoading) return;
        if (!user) return;
        if (user.status === 'unknown') return;
        if (user.role === 'admin') {
            navigate('/admin', { replace: true });
            return;
        }
        if (user.status !== 'approved' || (user.tier !== 'pro' && user.tier !== 'premium')) {
            navigate('/pending-approval', { replace: true });
            return;
        }
        navigate('/dashboard', { replace: true });
    }, [user, authLoading, navigate]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await login(email, password, remember);
            // pending 유저는 승인 대기 페이지로
            const stored = localStorage.getItem('auth_user') || sessionStorage.getItem('auth_user');
            if (stored) {
                try {
                    const parsed = JSON.parse(stored);
                    if (parsed.status && parsed.status !== 'approved' && parsed.role !== 'admin') {
                        navigate('/pending-approval');
                        return;
                    }
                } catch {
                    // corrupted storage — proceed to dashboard
                }
            }
            navigate('/dashboard');
        } catch (err) {
            setError((err as Error).message || 'Invalid email or password');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-bold text-white tracking-tighter mb-2">
                        Market<span className="text-[#2997ff]">Flow</span>
                    </h1>
                    <p className="text-gray-500">Sign in to your account</p>
                </div>
                <form onSubmit={handleSubmit} className="p-8 rounded-2xl bg-[#1c1c1e] border border-white/10 space-y-5">
                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">{error}</div>
                    )}
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">Email</label>
                        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="you@example.com" />
                    </div>
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">Password</label>
                        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="Min 6 characters" />
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
                    <button type="submit" disabled={loading}
                        className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all disabled:opacity-50">
                        {loading ? 'Signing in...' : 'Sign In'}
                    </button>
                    <p className="text-center text-sm text-gray-500">
                        Don&apos;t have an account?{' '}
                        <Link to="/signup" className="text-[#2997ff] hover:underline">Sign Up</Link>
                    </p>
                </form>

                <div className="mt-4 p-4 rounded-2xl bg-[#13151f] border border-amber-500/20">
                    <div className="flex items-center gap-3 mb-3">
                        <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center">
                            <i className="fas fa-university text-amber-400" />
                        </div>
                        <div>
                            <h2 className="text-white font-bold text-sm">결제 계좌 정보</h2>
                            <p className="text-gray-500 text-xs">신규 가입·재구독 입금 확인용</p>
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">은행</span>
                            <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.bank}</p>
                        </div>
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">예금주</span>
                            <p className="text-white font-bold mt-1 text-sm">{BANK_ACCOUNT.holder}</p>
                        </div>
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
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Pro</span>
                            <p className="text-amber-400 font-bold mt-1 text-sm">{PLAN_PAYMENT_META.pro.amount}</p>
                            <p className="text-gray-500 text-[10px] mt-0.5">{PLAN_PAYMENT_META.pro.period}</p>
                        </div>
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Ultra Pro</span>
                            <p className="text-purple-400 font-bold mt-1 text-sm">{PLAN_PAYMENT_META.premium.amount}</p>
                            <p className="text-gray-500 text-[10px] mt-0.5">{PLAN_PAYMENT_META.premium.period}</p>
                        </div>
                    </div>
                </div>
                <KakaoSupportLink className="mt-3" />
            </div>
        </div>
    );
}
