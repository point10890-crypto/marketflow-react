import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import {
    getToken,
    setToken,
    clearToken,
    getUser,
    saveUser,
    isAuthenticated,
    isAdmin as checkIsAdmin,
    type AuthUserData,
} from '@/lib/auth';
import { postAPI, API_BASE } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// 핵심 원칙 (재부팅·백엔드 다운 시 유저 차단 금지)
//
// 1) 로컬 토큰이 유효하면 무조건 유저 상태를 만든다 (캐시 → 합성 순).
// 2) /api/auth/me 검증은 백그라운드 best-effort. 실패해도 user 를 절대 null 로
//    되돌리지 않는다 (네트워크 오류로 로그아웃 금지).
// 3) /api/auth/me 가 성공하면 진짜 값으로 덮어쓰고 캐시도 갱신.
// 4) logout() 은 사용자 명시적 액션에서만 호출.
// ─────────────────────────────────────────────────────────────────────────────

interface AuthUser {
    id: number | string;
    email: string;
    name: string;
    // null = no active subscription. Access is gated by (status==='approved' && tier in {pro, premium}).
    tier: string | null;
    role: string;
    status: string;
    pro_expires_at?: string | null;
}

interface AuthContextType {
    user: AuthUser | null;
    token: string | null;
    loading: boolean;
    login: (email: string, password: string, remember?: boolean) => Promise<void>;
    logout: () => void;
    isAdmin: () => boolean;
    refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    token: null,
    loading: true,
    login: async () => {},
    logout: () => {},
    isAdmin: () => false,
    refreshUser: async () => {},
});

function toAuthUser(d: AuthUserData): AuthUser {
    return {
        id: d.id,
        email: d.email,
        name: d.name,
        tier: d.tier,
        role: d.role,
        status: d.status || 'approved',
        pro_expires_at: d.pro_expires_at || null,
    };
}

/**
 * 캐시는 비었지만 토큰은 유효한 상태를 위한 폴백 유저.
 * (예: localStorage 일부 손상 + 백엔드 다운 동시 발생)
 *
 * 토큰 포맷 `user_id:expiry:sig` — 서버 HMAC 으로 한 번 발급된 사실 자체를
 * 신뢰해 임시로 통과시킨다. 다음 /api/auth/me 성공 시 실제 값으로 덮어써진다.
 */
function synthesizeUserFromToken(token: string): AuthUser | null {
    const parts = token.split(':');
    if (parts.length !== 3) return null;
    const id = parts[0];
    if (!id) return null;
    return {
        id,
        email: '(offline)',
        name: '사용자',
        tier: 'pro',
        role: 'user',
        status: 'approved',
        pro_expires_at: null,
    };
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [token, setTokenState] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!isAuthenticated()) {
            setLoading(false);
            return;
        }

        const storedToken = getToken();
        if (!storedToken) {
            setLoading(false);
            return;
        }
        setTokenState(storedToken);

        // (1) 캐시된 유저 → 없으면 토큰 기반 합성 유저로 즉시 진입 보장
        const cached = getUser();
        const initial = cached ? toAuthUser(cached) : synthesizeUserFromToken(storedToken);
        if (initial) setUser(initial);

        // (2) 백그라운드 검증 — 실패해도 user 보존
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);
        fetch(`${API_BASE}/api/auth/me`, {
            headers: { Authorization: `Bearer ${storedToken}` },
            signal: controller.signal,
        })
            .then((r) => {
                clearTimeout(timeoutId);
                return r.ok ? r.json() : null;
            })
            .then((data) => {
                if (data?.user) {
                    setUser(toAuthUser(data.user));
                    saveUser(data.user);
                }
            })
            .catch((err) => {
                console.warn('[Auth] background /me failed (offline-tolerant):', err?.message || err);
            })
            .finally(() => setLoading(false));
    }, []);

    const login = async (email: string, password: string, remember?: boolean): Promise<void> => {
        const data = await postAPI<{ token: string; user?: AuthUserData }>('/api/auth/login', { email, password });
        if (!data.token) throw new Error('No token received from server');

        setToken(data.token, remember);
        setTokenState(data.token);

        if (data.user) {
            setUser(toAuthUser(data.user));
            saveUser(data.user);
        }
    };

    const logout = () => {
        clearToken();
        setTokenState(null);
        setUser(null);
    };

    const refreshUser = async () => {
        const currentToken = getToken();
        if (!currentToken) return;
        try {
            const res = await fetch(`${API_BASE}/api/auth/me`, {
                headers: { Authorization: `Bearer ${currentToken}` },
            });
            if (res.ok) {
                const data = await res.json();
                if (data.user) {
                    setUser(toAuthUser(data.user));
                    saveUser(data.user);
                }
            }
        } catch {
            /* 오프라인 — 캐시 유지 */
        }
    };

    const isAdminFn = () => checkIsAdmin() || user?.role === 'admin';

    return (
        <AuthContext.Provider value={{ user, token, loading, login, logout, isAdmin: isAdminFn, refreshUser }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}
