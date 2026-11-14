import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import { hasActiveBaseSubscription } from '@/lib/auth';
import { nextPathForUser } from '@/lib/authNavigation';
import {
    PLAN_PAYMENT_META,
    planFromQuery,
    planToQuery,
    resolveBillingPlan,
} from '@/lib/billingInfo';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';
import { useSeo } from '@/lib/seo';

const FIELD_CLASS = 'min-h-12 w-full rounded-xl border border-[#35473e] bg-[#111815] px-4 text-base text-[#f2f4ea] placeholder:text-[#8b9a91] focus:border-[#ffa786] focus:outline-2 focus:outline-offset-2 focus:outline-[#ffa786]';

export default function SignupPage() {
    useSeo({ title: '회원가입 | BitMan', noindex: true });
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { user, loading: authLoading, setSession } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const selectedPlan = resolveBillingPlan(planFromQuery(searchParams.get('plan'), searchParams.get('aibain')), user);
    const selectedMeta = selectedPlan ? PLAN_PAYMENT_META[selectedPlan] : null;
    const selectedQuery = selectedPlan ? planToQuery(selectedPlan) : '';
    const planSelectPath = selectedQuery ? `/plan-select?${selectedQuery}` : '/plan-select';
    const loginPath = selectedQuery
        ? `/login?next=${encodeURIComponent(`/plan-select?change=1&${selectedQuery}`)}`
        : '/login';

    useEffect(() => {
        if (authLoading || !user || user.status === 'unknown') return;
        const next = selectedQuery
            ? hasActiveBaseSubscription(user) ? `/plan-select?change=1&${selectedQuery}` : planSelectPath
            : null;
        navigate(nextPathForUser(user, next), { replace: true });
    }, [user, authLoading, navigate, planSelectPath, selectedQuery]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (loading || authLoading || user) return;
        setError('');
        setLoading(true);

        try {
            const payload = {
                name: name.trim(),
                email: email.trim(),
                password,
                ...(selectedMeta ? { requested_tier: selectedMeta.tier } : {}),
            };
            const res = await fetch(`${API_BASE}/api/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await res.json();

            if (!res.ok) {
                setError(data.error || '가입에 실패했습니다. 입력 정보를 확인해 주세요.');
                setLoading(false);
                return;
            }

            if (data.token && data.user) {
                setSession(data.token, data.user, true);
                navigate(planSelectPath, { replace: true });
            } else {
                navigate(loginPath, { replace: true });
            }
        } catch {
            setError('서버 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.');
            setLoading(false);
        }
    };

    return (
        <main className="min-h-[100dvh] bg-[#0d1411] px-4 py-5 text-[#f2f4ea] sm:py-10">
            <div className="mx-auto max-w-lg">
                <header className="mb-4 flex items-center justify-between gap-3">
                    <Link to="/" className="inline-flex min-h-11 items-center gap-2 text-lg font-extrabold" aria-label="BitMan 홈">
                        <span className="grid size-8 place-items-center rounded-md bg-[#ffa786] text-[#211511]" aria-hidden="true">B</span> BitMan
                    </Link>
                    <Link to={loginPath} className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-bold text-[#ffa786] hover:bg-white/5">
                        로그인
                    </Link>
                </header>
                <form onSubmit={handleSubmit} aria-busy={loading} className="rounded-2xl border border-[#2d3b36] bg-[#151f1c] p-5 sm:p-8">
                    <div className="mb-5">
                        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">무료 계정 만들기</h1>
                        <p className="mt-1 text-sm leading-6 text-[#adb9b1]">
                            가입 후 이용할 플랜과 금액을 확인할 수 있어요.
                        </p>
                    </div>
                    {selectedMeta && (
                        <section aria-label="선택한 플랜" className="mb-5 rounded-xl border border-[#35473e] bg-[#111815] p-3">
                            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                                <div className="text-sm font-extrabold">{selectedMeta.label}</div>
                                <strong className="text-base text-[#ffa786]">{selectedMeta.amount}</strong>
                            </div>
                            <p className="mt-1 text-xs leading-5 text-[#adb9b1]">{selectedMeta.period}</p>
                        </section>
                    )}
                    {error && (
                        <div role="alert" className="mb-5 rounded-xl border border-red-400/20 bg-red-500/[0.08] p-3 text-sm text-red-200">
                            {error}
                        </div>
                    )}

                    <div className="space-y-3">
                        <div>
                            <label htmlFor="signup-name" className="mb-1.5 block text-sm font-semibold">이름</label>
                            <input
                                id="signup-name"
                                name="name"
                                type="text"
                                autoComplete="name"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                required
                                maxLength={100}
                                className={FIELD_CLASS}
                            />
                        </div>
                        <div>
                            <label htmlFor="signup-email" className="mb-1.5 block text-sm font-semibold">이메일</label>
                            <input
                                id="signup-email"
                                name="email"
                                type="email"
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                maxLength={254}
                                className={FIELD_CLASS}
                            />
                        </div>
                        <div>
                            <label htmlFor="signup-password" className="mb-1.5 block text-sm font-semibold">비밀번호</label>
                            <input
                                id="signup-password"
                                name="password"
                                type="password"
                                autoComplete="new-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                minLength={8}
                                maxLength={128}
                                className={FIELD_CLASS}
                                aria-describedby="signup-password-hint"
                            />
                            <p id="signup-password-hint" className="mt-1 text-xs text-[#adb9b1]">영문과 숫자를 포함해 8자 이상</p>
                        </div>
                    </div>

                    <button
                        type="submit"
                        disabled={loading || authLoading || !!user}
                        className="mt-5 min-h-[48px] w-full rounded-xl bg-[#ffa786] px-4 text-sm font-extrabold text-[#211511] transition-colors hover:bg-[#ffba9f] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {loading ? (
                            <><i className="fas fa-spinner fa-spin mr-2" />계정 생성 중...</>
                        ) : (
                            <>계정 만들고 플랜 확인<i className="fas fa-arrow-right ml-2 text-xs" aria-hidden="true" /></>
                        )}
                    </button>

                    <p className="mt-3 text-center text-xs leading-5 text-[#adb9b1]">
                        가입하면 <Link to="/terms" className="font-semibold underline underline-offset-2">이용약관</Link> 및{' '}
                        <Link to="/privacy" className="font-semibold underline underline-offset-2">개인정보처리방침</Link>에 동의하게 됩니다.
                    </p>
                </form>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                    <Link to="/pricing" className="inline-flex min-h-11 items-center rounded-lg px-2 text-sm font-medium text-[#adb9b1] hover:text-white">플랜 비교</Link>
                    <KakaoSupportLink className="!w-auto" label="가입 문의" />
                </div>
            </div>
        </main>
    );
}
