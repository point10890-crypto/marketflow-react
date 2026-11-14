import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { getUser } from '@/lib/auth';
import { nextPathForUser, safeNextPath, signupPathForPlan } from '@/lib/authNavigation';
import { useSeo } from '@/lib/seo';

export { nextPathForUser, safeNextPath } from '@/lib/authNavigation';

export default function LoginPage() {
    useSeo({ title: '로그인 | BitMan', noindex: true });
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
            const storedUser = getUser();
            if (storedUser) {
                navigate(nextPathForUser(storedUser, nextPath), { replace: true });
                return;
            }
            navigate(nextPath?.startsWith('/dashboard') ? nextPath : '/dashboard', { replace: true });
        } catch (err) {
            setError((err as Error).message || '이메일 또는 비밀번호를 확인해 주세요.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <main className="min-h-screen min-h-[100dvh] bg-[#09090b] px-4 py-8 text-gray-300 sm:px-6">
            <div className="mx-auto grid min-h-[calc(100dvh-4rem)] w-full max-w-5xl items-center gap-10 lg:grid-cols-[1fr_28rem]">
                <section className="hidden lg:block">
                    <Link to="/" className="inline-flex min-h-11 items-center gap-2 text-lg font-extrabold tracking-tight text-white" aria-label="BitMan 홈">
                        <span className="grid size-8 place-items-center rounded-md bg-[#ffa786] text-[#211511]" aria-hidden="true">B</span> BitMan
                    </Link>
                    <p className="mt-8 font-mono text-[11px] font-bold uppercase tracking-[0.22em] text-[#ff8067]">Welcome back</p>
                    <h1 className="mt-4 max-w-xl text-4xl font-black leading-[1.15] tracking-[-0.04em] text-white">
                        감시는 계속되고,<br />판단의 근거는 남습니다.
                    </h1>
                    <p className="mt-5 max-w-lg text-[15px] leading-7 text-gray-400">
                        로그인하면 계정 상태에 따라 운영 대시보드, 승인 현황 또는 재구독 단계로 안전하게 이어집니다.
                    </p>
                    <div className="mt-8 grid max-w-lg grid-cols-3 gap-3">
                        {['원천 시각 확인', '품질 부족 시 HOLD', '실주문 기능 없음'].map((item) => (
                            <div key={item} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4 text-xs font-semibold text-gray-400">
                                <span className="mb-3 block h-1.5 w-1.5 rounded-full bg-[#ff6b4a]" />{item}
                            </div>
                        ))}
                    </div>
                </section>

                <section className="w-full">
                    <div className="mb-7 lg:hidden">
                        <Link to="/" className="inline-flex min-h-11 items-center gap-2 text-lg font-extrabold tracking-tight text-white" aria-label="BitMan 홈">
                            <span className="grid size-8 place-items-center rounded-md bg-[#ffa786] text-[#211511]" aria-hidden="true">B</span> BitMan
                        </Link>
                    </div>
                    <div className="rounded-[1.75rem] border border-white/[0.08] bg-[#111216] p-6 shadow-2xl shadow-black/30 sm:p-8">
                        <p className="font-mono text-[10px] font-bold uppercase tracking-[0.22em] text-[#ff8067]">Account access</p>
                        <h2 className="mt-3 text-2xl font-black tracking-tight text-white">다시 시작하기</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-500">기존 계정으로 로그인하세요.</p>

                        <form onSubmit={handleSubmit} className="mt-7 space-y-5">
                            {error && (
                                <div role="alert" className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>
                            )}
                            <div>
                                <label htmlFor="login-email" className="mb-2 block text-xs font-semibold text-gray-400">이메일</label>
                                <input id="login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email"
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white placeholder-gray-600 transition-colors focus:border-[#ff6b4a] focus:outline-none focus:ring-2 focus:ring-[#ff6b4a]/25"
                                    placeholder="you@example.com" />
                            </div>
                            <div>
                                <label htmlFor="login-password" className="mb-2 block text-xs font-semibold text-gray-400">비밀번호</label>
                                <input id="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} autoComplete="current-password"
                                    className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white placeholder-gray-600 transition-colors focus:border-[#ff6b4a] focus:outline-none focus:ring-2 focus:ring-[#ff6b4a]/25"
                                    placeholder="비밀번호" />
                            </div>
                            <label className="flex min-h-[44px] cursor-pointer select-none items-center gap-2">
                                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
                                    className="h-4 w-4 accent-[#ff6b4a] focus:ring-[#ff6b4a]" />
                                <span className="text-sm text-gray-400">로그인 유지</span>
                            </label>
                            <button type="submit" disabled={loading}
                                className="min-h-[48px] w-full rounded-xl bg-[#ff6b4a] px-5 font-black text-[#160805] transition-colors hover:bg-[#ff846b] disabled:cursor-not-allowed disabled:opacity-50">
                                {loading ? '로그인 중...' : '로그인'}
                            </button>
                        </form>

                        <div className="mt-6 border-t border-white/[0.06] pt-5 text-center text-sm text-gray-500">
                            처음 오셨나요? <Link to={signupPathForPlan(nextPath)} className="font-bold text-[#ff8067] hover:text-[#ff9b86]">계정 만들기</Link>
                        </div>
                    </div>
                    <KakaoSupportLink className="mt-3" />
                </section>
            </div>
        </main>
    );
}
