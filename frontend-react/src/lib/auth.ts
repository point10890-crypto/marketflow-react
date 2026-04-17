// Auth storage (HMAC token + user object)
// "로그인 유지" 체크 시 localStorage (브라우저 닫아도 유지)
// 미체크 시 sessionStorage (탭 닫으면 소멸)

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';
const REMEMBER_KEY = 'auth_remember';

function getStorage(): Storage {
    return localStorage.getItem(REMEMBER_KEY) === '1' ? localStorage : sessionStorage;
}

export function getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, remember?: boolean): void {
    if (remember !== undefined) {
        if (remember) {
            localStorage.setItem(REMEMBER_KEY, '1');
        } else {
            localStorage.removeItem(REMEMBER_KEY);
        }
    }
    const storage = getStorage();
    storage.setItem(TOKEN_KEY, token);
    // 다른 storage에서 제거 (중복 방지)
    const other = storage === localStorage ? sessionStorage : localStorage;
    other.removeItem(TOKEN_KEY);
    other.removeItem(USER_KEY);
}

export function clearToken(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(REMEMBER_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
}

export interface AuthUserData {
    id: number | string;
    email: string;
    name: string;
    tier: string | null;
    role: string;
    status: string;
    pro_expires_at?: string | null;
    is_pro_expired?: boolean;
    requested_tier?: 'pro' | 'premium' | null;
}

export function saveUser(user: AuthUserData): void {
    getStorage().setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): AuthUserData | null {
    try {
        const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
        if (!raw) return null;
        return JSON.parse(raw) as AuthUserData;
    } catch {
        localStorage.removeItem(USER_KEY);
        sessionStorage.removeItem(USER_KEY);
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
