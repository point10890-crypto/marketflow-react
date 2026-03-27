// localStorage-based auth (HMAC token + user object)

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';

export function getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

export interface AuthUserData {
    id: number | string;
    email: string;
    name: string;
    tier: string;
    role: string;
    status: string;
}

export function saveUser(user: AuthUserData): void {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): AuthUserData | null {
    try {
        const raw = localStorage.getItem(USER_KEY);
        if (!raw) return null;
        return JSON.parse(raw) as AuthUserData;
    } catch {
        localStorage.removeItem(USER_KEY);
        return null;
    }
}

export function isAuthenticated(): boolean {
    const token = getToken();
    if (!token) return false;

    // Token format: "user_id:expiry:sig"
    const parts = token.split(':');
    if (parts.length !== 3) return false;

    const expiry = parseInt(parts[1], 10);
    if (isNaN(expiry) || expiry * 1000 < Date.now()) {
        clearToken();
        return false;
    }

    return true;
}

export function isAdmin(): boolean {
    return getUser()?.role === 'admin';
}
