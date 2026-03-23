import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

export default function LoginPage() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await login(email, password);
            // pending 유저는 승인 대기 페이지로
            const stored = localStorage.getItem('auth_user');
            if (stored) {
                const parsed = JSON.parse(stored);
                if (parsed.status && parsed.status !== 'approved' && parsed.role !== 'admin') {
                    navigate('/pending-approval');
                    return;
                }
            }
            navigate('/dashboard');
        } catch (err) {
            setError((err as Error).message || 'Invalid email or password');
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
                    <button type="submit" disabled={loading}
                        className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all disabled:opacity-50">
                        {loading ? 'Signing in...' : 'Sign In'}
                    </button>
                    <p className="text-center text-sm text-gray-500">
                        Don&apos;t have an account?{' '}
                        <Link to="/signup" className="text-[#2997ff] hover:underline">Sign Up</Link>
                    </p>
                </form>
            </div>
        </div>
    );
}
