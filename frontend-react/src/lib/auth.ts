// localStorage-based JWT auth (no NextAuth)

const TOKEN_KEY = 'auth_token';

export function getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
    localStorage.removeItem(TOKEN_KEY);
}

interface JWTPayload {
    id: number | string;
    email: string;
    name: string;
    tier: string;
    role: string;
    exp?: number;
    iat?: number;
}

export function getUser(): JWTPayload | null {
    const token = getToken();
    if (!token) return null;

    try {
        const parts = token.split('.');
        if (parts.length !== 3) return null;

        // Decode the payload (middle part)
        const payload = parts[1];
        // Add padding if needed
        const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
        const decoded = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
        return JSON.parse(decoded) as JWTPayload;
    } catch {
        return null;
    }
}

export function isAuthenticated(): boolean {
    const user = getUser();
    if (!user) return false;

    // Check token expiry if present
    if (user.exp && user.exp * 1000 < Date.now()) {
        clearToken();
        return false;
    }

    return true;
}

export function isAdmin(): boolean {
    return getUser()?.role === 'admin';
}
