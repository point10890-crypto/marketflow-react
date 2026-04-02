import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { getToken, setToken, clearToken, getUser, saveUser, isAuthenticated, isAdmin as checkIsAdmin, type AuthUserData } from '@/lib/auth';
import { postAPI, API_BASE, API_HEADERS } from '@/lib/api';

interface AuthUser {
    id: number | string;
    email: string;
    name: string;
    tier: string;
    role: string;
    status: string;
}

interface AuthContextType {
    user: AuthUser | null;
    token: string | null;
    loading: boolean;
    login: (email: string, password: string) => Promise<void>;
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

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [token, setTokenState] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    // Initialize from localStorage on mount, then always refresh from server
    useEffect(() => {
        if (isAuthenticated()) {
            const storedToken = getToken();
            if (storedToken) {
                setTokenState(storedToken);
                const storedUser = getUser();
                if (storedUser && storedUser.tier) {
                    setUser({
                        id: storedUser.id,
                        email: storedUser.email,
                        name: storedUser.name,
                        tier: storedUser.tier,
                        role: storedUser.role,
                        status: storedUser.status || 'approved',
                    });
                }
                // Always refresh from server to get latest tier/status
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 10000);
                fetch(`${API_BASE}/api/auth/me`, {
                    headers: { ...API_HEADERS, 'Authorization': `Bearer ${storedToken}` },
                    signal: controller.signal,
                }).then(r => { clearTimeout(timeout); return r.ok ? r.json() : null; }).then(data => {
                    if (data?.user) {
                        setUserFromData(data.user);
                    }
                }).catch((err) => {
                    console.warn('[Auth] Session check failed:', err.message || err);
                }).finally(() => {
                    setLoading(false);
                });
            } else {
                setLoading(false);
            }
        } else {
            setLoading(false);
        }
    }, []);

    const setUserFromData = (data: AuthUserData) => {
        const authUser: AuthUser = {
            id: data.id,
            email: data.email,
            name: data.name,
            tier: data.tier,
            role: data.role,
            status: data.status || 'approved',
        };
        setUser(authUser);
        saveUser(data);
    };

    const login = async (email: string, password: string): Promise<void> => {
        const data = await postAPI<{ token: string; user?: AuthUserData }>('/api/auth/login', { email, password });

        if (!data.token) {
            throw new Error('No token received from server');
        }

        setToken(data.token);
        setTokenState(data.token);

        if (data.user) {
            setUserFromData(data.user);
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
                headers: { ...API_HEADERS, 'Authorization': `Bearer ${currentToken}` },
            });
            if (res.ok) {
                const data = await res.json();
                if (data.user) {
                    setUserFromData(data.user);
                }
            }
        } catch { /* ignore */ }
    };

    const isAdminFn = () => {
        return checkIsAdmin() || user?.role === 'admin';
    };

    return (
        <AuthContext.Provider value={{ user, token, loading, login, logout, isAdmin: isAdminFn, refreshUser }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}
