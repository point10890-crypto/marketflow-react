import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';

const API_URL = process.env.API_URL || 'http://localhost:5001';

export const { handlers, signIn, signOut, auth } = NextAuth({
    providers: [
        Credentials({
            name: 'Email',
            credentials: {
                email: { label: 'Email', type: 'email' },
                password: { label: 'Password', type: 'password' },
            },
            async authorize(credentials) {
                if (!credentials?.email || !credentials?.password) return null;

                const res = await fetch(`${API_URL}/api/auth/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: credentials.email,
                        password: credentials.password,
                    }),
                });

                if (!res.ok) return null;

                const data = await res.json();
                return {
                    id: String(data.user.id),
                    email: data.user.email,
                    name: data.user.name,
                    tier: data.user.tier,
                    role: data.user.role || 'user',
                    apiToken: data.token,
                };
            },
        }),
    ],
    pages: {
        signIn: '/login',
    },
    callbacks: {
        async jwt({ token, user }) {
            if (user) {
                token.id = user.id;
                token.email = user.email;
                token.tier = (user as unknown as Record<string, unknown>).tier as string;
                token.role = (user as unknown as Record<string, unknown>).role as string;
                token.apiToken = (user as unknown as Record<string, unknown>).apiToken as string;
            }

            // API 토큰 만료 체크 및 자동 갱신 (토큰 형식: user_id:expiry:sig)
            if (token.apiToken) {
                try {
                    const parts = (token.apiToken as string).split(':');
                    if (parts.length === 3) {
                        const expiry = parseInt(parts[1], 10);
                        const now = Math.floor(Date.now() / 1000);
                        // 만료 3일 전이면 /api/auth/me로 유효성 확인 후 재로그인
                        if (expiry - now < 86400 * 3) {
                            const meRes = await fetch(`${API_URL}/api/auth/me`, {
                                headers: { Authorization: `Bearer ${token.apiToken}` },
                            });
                            if (!meRes.ok) {
                                // 토큰 만료됨 — 세션 무효화
                                return { ...token, apiToken: null, error: 'token_expired' };
                            }
                            const meData = await meRes.json();
                            // tier + role 실시간 동기화
                            token.tier = meData.user?.tier || token.tier;
                            token.role = meData.user?.role || token.role;
                        }
                    }
                } catch { /* 토큰 파싱 실패 무시 */ }
            }

            return token;
        },
        async session({ session, token }) {
            if (session.user) {
                (session.user as unknown as Record<string, unknown>).id = token.id;
                (session.user as unknown as Record<string, unknown>).tier = token.tier;
                (session.user as unknown as Record<string, unknown>).role = token.role;
                (session.user as unknown as Record<string, unknown>).apiToken = token.apiToken;
            }
            return session;
        },
    },
    session: {
        strategy: 'jwt',
        maxAge: 30 * 24 * 60 * 60, // 30 days (match Flask token expiry)
    },
    trustHost: true,
    secret: process.env.NEXTAUTH_SECRET || 'marketflow-nextauth-secret',
});
