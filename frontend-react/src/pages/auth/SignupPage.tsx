import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import KakaoSupportLink from '@/components/ui/KakaoSupportLink';

/**
 * 가입 폼 — 기본 정보(이름/이메일/비번)만 받는다.
 * 플랜 선택은 가입 완료 후 /plan-select 에서 진행.
 *
 * 플로우:
 *   /          (랜딩)
 *     → /signup (이 페이지)
 *     → /plan-select
 *     → /payment-request?plan=X
 *     → /pending-approval
 *     → /dashboard
 */
export default function SignupPage() {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { setSession } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/api/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, password }),
            });

            const data = await res.json();

            if (!res.ok) {
                setError(data.error || '가입에 실패했습니다.');
                setLoading(false);
                return;
            }

            // register 응답의 token + user 로 바로 세션 수립 (login API 재호출 금지).
            // pending 상태 유저는 login API 에서 401 을 받아 세션이 수립되지 않으므로
            // 가입 직후 플랜 선택 페이지로 유도하려면 register 토큰을 직접 써야 한다.
            if (data.token && data.user) {
                setSession(data.token, data.user, true);
            }
            // 플랜 선택 페이지로
            navigate('/plan-select', { replace: true });
        } catch {
            setError('네트워크 오류입니다. 잠시 후 다시 시도해 주세요.');
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
                    <p className="text-gray-500">계정을 만들어 구독을 시작하세요</p>
                    <p className="text-gray-600 text-xs mt-1">가입 → 플랜 선택 → 입금 안내 순서로 진행됩니다</p>
                </div>
                <form onSubmit={handleSubmit} className="p-8 rounded-2xl bg-[#1c1c1e] border border-white/10 space-y-5">
                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">{error}</div>
                    )}
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">이름</label>
                        <input type="text" value={name} onChange={(e) => setName(e.target.value)} required
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="이름 (입금자명과 동일하게)" />
                    </div>
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">이메일</label>
                        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="you@example.com" />
                    </div>
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-2">비밀번호</label>
                        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8}
                            className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-[#2997ff] transition-colors"
                            placeholder="영문+숫자 8자 이상" />
                    </div>

                    <button type="submit" disabled={loading}
                        className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed">
                        {loading ? '계정 생성 중…' : '계정 만들기'}
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
