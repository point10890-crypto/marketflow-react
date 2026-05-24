import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

const FLOW_STEPS = ['계정 생성', '플랜 선택', '입금 정보', '승인 대기'];

export default function SignupPage() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { user, loading: authLoading, setSession } = useAuth();
    const navigate = useNavigate();

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
            navigate('/plan-select', { replace: true });
            return;
        }
        if (user.status !== 'approved') {
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
            const res = await fetch(`${API_BASE}/api/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name.trim(), email: email.trim(), password }),
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
            navigate('/plan-select', { replace: true });
        } catch {
            setError('서버 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.');
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-black flex items-center justify-center p-4 py-8">
            <div className="w-full max-w-md">
                <div className="text-center mb-6">
                    <h1 className="text-4xl font-bold text-white tracking-tighter mb-2">
                        Market<span className="text-[#2997ff]">Flow</span>
                    </h1>
                    <p className="text-gray-400 font-semibold">처음 오셨다면 여기서 바로 시작하세요.</p>
                    <p className="text-gray-600 text-xs mt-1">가입 후 플랜 선택과 구독 신청까지 이어집니다.</p>
                </div>

                <div className="mb-4 grid grid-cols-4 gap-2">
                    {FLOW_STEPS.map((step, index) => (
                        <div
                            key={step}
                            className={`rounded-xl border px-2 py-2 text-center text-[10px] font-bold ${
                                index === 0
                                    ? 'border-blue-400/40 bg-blue-500/15 text-blue-200'
                                    : 'border-white/10 bg-white/[0.03] text-gray-500'
                            }`}
                        >
                            <div className="mb-1 text-[11px]">{index + 1}</div>
                            {step}
                        </div>
                    ))}
                </div>

                <form onSubmit={handleSubmit} className="p-8 rounded-2xl bg-[#1c1c1e] border border-white/10 space-y-5">
                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm">{error}</div>
                    )}
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">이름</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            required
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="입금자명과 같은 이름"
                        />
                    </div>
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
                            minLength={8}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="영문+숫자 포함 8자 이상"
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        {loading ? '계정 생성 중...' : '계정 만들고 플랜 선택'}
                    </button>

                    <p className="text-center text-sm text-gray-500">
                        이미 계정이 있으신가요?{' '}
                        <Link to="/login" className="text-[#2997ff] hover:underline">로그인</Link>
                    </p>
                </form>
                <KakaoSupportLink className="mt-3" />
            </div>
        </div>
    );
}
