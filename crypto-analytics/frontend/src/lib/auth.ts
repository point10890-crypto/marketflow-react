import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';

const FLASK_URL = process.env.FLASK_URL || 'http://localhost:5001';

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

                const res = await fetch(`${FLASK_URL}/api/auth/login`, {
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
                token.tier = (user as unknown as Record<string, unknown>).tier as string;
                token.apiToken = (user as unknown as Record<string, unknown>).apiToken as string;
            }
            return token;
        },
        async session({ session, token }) {
            if (session.user) {
                (session.user as unknown as Record<string, unknown>).id = token.id;
                (session.user as unknown as Record<string, unknown>).tier = token.tier;
                (session.user as unknown as Record<string, unknown>).apiToken = token.apiToken;
            }
            return session;
        },
    },
    session: {
        strategy: 'jwt',
    },
    secret: process.env.NEXTAUTH_SECRET || 'marketflow-nextauth-secret',
});
