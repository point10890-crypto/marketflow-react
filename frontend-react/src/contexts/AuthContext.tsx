import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { getToken, setToken, clearToken, getUser, isAuthenticated, isAdmin as checkIsAdmin } from '@/lib/auth';
import { postAPI } from '@/lib/api';

interface AuthUser {
    id: number | string;
    email: string;
    name: string;
    tier: string;
    role: string;
}

interface AuthContextType {
    user: AuthUser | null;
    token: string | null;
    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
    isAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    token: null,
    login: async () => {},
    logout: () => {},
    isAdmin: () => false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [token, setTokenState] = useState<string | null>(null);

    // Initialize from localStorage on mount
    useEffect(() => {
        if (isAuthenticated()) {
            const storedToken = getToken();
            const storedUser = getUser();
            if (storedToken && storedUser) {
                setTokenState(storedToken);
                setUser({
                    id: storedUser.id,
                    email: storedUser.email,
                    name: storedUser.name,
                    tier: storedUser.tier,
                    role: storedUser.role,
                });
            }
        }
    }, []);

    const login = async (email: string, password: string): Promise<void> => {
        const data = await postAPI<{ token: string; user?: AuthUser }>('/api/auth/login', { email, password });

        if (!data.token) {
            throw new Error('No token received from server');
        }

        setToken(data.token);
        setTokenState(data.token);

        // Decode user from token or use returned user object
        const decoded = getUser();
        if (decoded) {
            setUser({
                id: decoded.id,
                email: decoded.email,
                name: decoded.name,
                tier: decoded.tier,
                role: decoded.role,
            });
        } else if (data.user) {
            setUser(data.user);
        }
    };

    const logout = () => {
        clearToken();
        setTokenState(null);
        setUser(null);
    };

    const isAdminFn = () => {
        return checkIsAdmin() || user?.role === 'admin';
    };

    return (
        <AuthContext.Provider value={{ user, token, login, logout, isAdmin: isAdminFn }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}
