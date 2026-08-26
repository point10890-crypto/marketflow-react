import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import {
    PLAN_PAYMENT_META,
    planFromQuery,
    planToQuery,
} from '@/lib/billingInfo';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

const FLOW_STEPS = ['계정 생성', '플랜 선택', '입금 정보', '승인 대기'];

const CORE_PROMISES = [
    {
        icon: 'fa-eye',
        title: '시장 변화를 계속 관측',
        text: '장중 Claw와 일간 분석 레인이 서로 다른 시간축의 변화를 기록합니다.',
    },
    {
        icon: 'fa-file-shield',
        title: '근거와 데이터 공백을 함께 표시',
        text: '확인된 사실, 오래된 데이터, 확인되지 않은 항목을 같은 의미로 섞지 않습니다.',
    },
    {
        icon: 'fa-chart-simple',
        title: '검출 이후 결과까지 검증',
        text: '과거 시점 입력과 사후 성과를 남겨 재현 가능한 규칙만 개선에 사용합니다.',
    },
];

export default function SignupPage() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { user, loading: authLoading, setSession } = useAuth();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const selectedPlan = planFromQuery(searchParams.get('plan'), searchParams.get('aibain'));
    const selectedMeta = selectedPlan ? PLAN_PAYMENT_META[selectedPlan] : null;
    const selectedQuery = selectedPlan ? planToQuery(selectedPlan) : '';
    const planSelectPath = selectedQuery ? `/plan-select?${selectedQuery}` : '/plan-select';
    const loginPath = selectedQuery
        ? `/login?next=${encodeURIComponent(`/plan-select?change=1&${selectedQuery}`)}`
        : '/login';

    useEffect(() => {
        if (authLoading || !user) return;
        if (user.role === 'admin') {
            navigate('/admin', { replace: true });
            return;
        }
        if (user.status === 'expired' || user.is_pro_expired) {
            navigate('/plan-select?resubscribe=1&from=expired', { replace: true });
            return;
        }
        if (!user.tier) {
            navigate(planSelectPath, { replace: true });
            return;
        }
        if (user.status !== 'approved') {
            navigate('/pending-approval', { replace: true });
            return;
        }
        navigate('/dashboard', { replace: true });
    }, [user, authLoading, navigate, planSelectPath]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
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
            }
            navigate(planSelectPath, { replace: true });
        } catch {
            setError('서버 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.');
            setLoading(false);
        }
    };

    return (
        <div className="relative min-h-screen min-h-[100dvh] overflow-x-clip bg-[#07090d] text-white">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_16%_18%,rgba(255,107,87,0.13),transparent_35%),radial-gradient(circle_at_82%_12%,rgba(16,185,129,0.09),transparent_30%)]" />
            <main className="relative mx-auto grid min-h-screen min-h-[100dvh] w-full max-w-6xl items-center gap-10 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1.08fr)_minmax(390px,0.82fr)] lg:gap-16 lg:py-12">
                <section className="pt-2 lg:py-8">
                    <Link to="/" className="inline-flex items-baseline gap-2" aria-label="MarketFlow 홈">
                        <span className="text-xl font-black tracking-tight text-white">
                            Market<span className="text-[#ff6b57]">Flow</span>
                        </span>
                        <span className="font-mono text-[9px] font-black uppercase tracking-[0.18em] text-gray-600">Analysis Core</span>
                    </Link>

                    <div className="mt-10 inline-flex items-center gap-2 rounded-full border border-[#ff6b57]/25 bg-[#ff6b57]/[0.08] px-3 py-1.5 font-mono text-[10px] font-black uppercase tracking-[0.16em] text-[#ff9b89] lg:mt-14">
                        <span className="h-1.5 w-1.5 rounded-full bg-[#ff6b57]" />
                        Evidence-first market intelligence
                    </div>
                    <h1 className="mt-5 max-w-2xl text-4xl font-black leading-[1.08] tracking-[-0.045em] text-white sm:text-5xl lg:text-6xl">
                        신호를 보는 데서 끝나지 않고
                        <span className="block bg-gradient-to-r from-[#ff8a76] via-amber-300 to-emerald-300 bg-clip-text text-transparent">
                            판단의 근거까지 확인하세요.
                        </span>
                    </h1>
                    <p className="mt-5 max-w-xl text-sm leading-7 text-gray-400 sm:text-base">
                        MarketFlow는 종목을 많이 나열하는 앱이 아닙니다. 무엇을 관측했고, 무엇이 비었으며,
                        검출 이후 결과가 어땠는지 한 흐름으로 연결하는 분석 서비스입니다.
                    </p>

                    {selectedMeta && (
                        <div className="mt-6 max-w-xl rounded-2xl border border-cyan-400/20 bg-cyan-500/[0.06] p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div className="font-mono text-[9px] font-black uppercase tracking-[0.16em] text-cyan-300">Selected plan</div>
                                    <div className="mt-1 text-lg font-black text-white">{selectedMeta.label}</div>
                                    <p className="mt-0.5 text-xs text-gray-500">{selectedMeta.period}</p>
                                </div>
                                <div className="text-right">
                                    <div className="text-xl font-black text-white">{selectedMeta.amount}</div>
                                    <Link to="/pricing" className="text-[11px] font-bold text-cyan-300 hover:text-cyan-200">
                                        다른 플랜 비교
                                    </Link>
                                </div>
                            </div>
                        </div>
                    )}

                    <div className="mt-7 grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
                        {CORE_PROMISES.map((item) => (
                            <article key={item.title} className="flex gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] p-3.5 lg:max-w-xl">
                                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-emerald-500/[0.10] text-emerald-300">
                                    <i className={`fas ${item.icon}`} />
                                </div>
                                <div>
                                    <h2 className="text-xs font-black text-gray-100">{item.title}</h2>
                                    <p className="mt-1 text-[11px] leading-5 text-gray-500">{item.text}</p>
                                </div>
                            </article>
                        ))}
                    </div>

                    <p className="mt-5 max-w-xl font-mono text-[9px] leading-5 text-gray-600">
                        READ-ONLY ANALYSIS · 자동 주문 없음 · 수익률 보장 없음
                    </p>
                </section>

                <section className="pb-2 lg:py-8">
                    <div className="mb-4 grid grid-cols-4 gap-1.5">
                        {FLOW_STEPS.map((step, index) => (
                            <div
                                key={step}
                                className={`rounded-lg border px-1.5 py-2 text-center text-[9px] font-bold ${
                                    index === 0
                                        ? 'border-emerald-400/35 bg-emerald-500/[0.12] text-emerald-200'
                                        : 'border-white/[0.07] bg-white/[0.025] text-gray-600'
                                }`}
                            >
                                <span className="mr-1 font-mono">{index + 1}</span>{step}
                            </div>
                        ))}
                    </div>

                    <form onSubmit={handleSubmit} className="rounded-3xl border border-white/[0.09] bg-[#11141b]/95 p-5 shadow-[0_28px_100px_rgba(0,0,0,0.42)] sm:p-8">
                        <div className="mb-7">
                            <div className="font-mono text-[9px] font-black uppercase tracking-[0.18em] text-[#ff8a76]">Step 01 · Create account</div>
                            <h2 className="mt-2 text-2xl font-black tracking-tight text-white">분석을 시작할 계정 만들기</h2>
                            <p className="mt-2 text-xs leading-5 text-gray-500">
                                계정 생성에는 비용이 없으며, 다음 단계에서 플랜과 입금 정보를 다시 확인합니다.
                            </p>
                        </div>

                        {error && (
                            <div role="alert" className="mb-5 rounded-xl border border-red-400/20 bg-red-500/[0.08] p-3 text-sm text-red-200">
                                {error}
                            </div>
                        )}

                        <div className="space-y-4">
                            <div>
                                <label htmlFor="signup-name" className="mb-2 block text-xs font-bold text-gray-400">이름</label>
                                <input
                                    id="signup-name"
                                    name="name"
                                    type="text"
                                    autoComplete="name"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    required
                                    maxLength={100}
                                    className="min-h-[48px] w-full rounded-xl border border-white/[0.09] bg-black/25 px-4 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-[#ff6b57]/70"
                                    placeholder="입금자명과 같은 이름"
                                />
                            </div>
                            <div>
                                <label htmlFor="signup-email" className="mb-2 block text-xs font-bold text-gray-400">이메일</label>
                                <input
                                    id="signup-email"
                                    name="email"
                                    type="email"
                                    autoComplete="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    maxLength={254}
                                    className="min-h-[48px] w-full rounded-xl border border-white/[0.09] bg-black/25 px-4 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-[#ff6b57]/70"
                                    placeholder="you@example.com"
                                />
                            </div>
                            <div>
                                <label htmlFor="signup-password" className="mb-2 block text-xs font-bold text-gray-400">비밀번호</label>
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
                                    className="min-h-[48px] w-full rounded-xl border border-white/[0.09] bg-black/25 px-4 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-[#ff6b57]/70"
                                    placeholder="영문+숫자 포함 8자 이상"
                                />
                            </div>
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="mt-6 min-h-[50px] w-full rounded-xl bg-[#ff6b57] px-4 text-sm font-black text-[#190704] transition-colors hover:bg-[#ff8a76] disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            {loading ? (
                                <><i className="fas fa-spinner fa-spin mr-2" />계정 생성 중...</>
                            ) : (
                                <>계정 만들고 플랜 확인<i className="fas fa-arrow-right ml-2 text-xs" /></>
                            )}
                        </button>

                        <p className="mt-4 text-center text-[11px] leading-5 text-gray-600">
                            가입을 진행하면 <Link to="/terms" className="text-gray-400 hover:text-white">이용약관</Link> 및{' '}
                            <Link to="/privacy" className="text-gray-400 hover:text-white">개인정보처리방침</Link>에 동의한 것으로 간주합니다.
                        </p>
                        <p className="mt-4 text-center text-sm text-gray-500">
                            이미 계정이 있으신가요?{' '}
                            <Link to={loginPath} className="font-bold text-[#ff8a76] hover:text-[#ffab9b]">로그인</Link>
                        </p>
                    </form>
                    <KakaoSupportLink className="mt-3" />
                </section>
            </main>
        </div>
    );
}
