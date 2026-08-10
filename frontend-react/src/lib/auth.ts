// Auth storage (HMAC token + user object)
// "로그인 유지" 체크 시 localStorage (브라우저 닫아도 유지)
// 미체크 시 sessionStorage (탭 닫으면 소멸)

import { safeGetItem, safeRemoveItem, safeSetItem, type StorageArea } from './safeStorage';

const TOKEN_KEY = 'auth_token';
const USER_KEY = 'auth_user';
const REMEMBER_KEY = 'auth_remember';

function getStorageArea(): StorageArea {
    return safeGetItem('local', REMEMBER_KEY) === '1' ? 'local' : 'session';
}

export function getToken(): string | null {
    return safeGetItem('local', TOKEN_KEY) || safeGetItem('session', TOKEN_KEY);
}

export function setToken(token: string, remember?: boolean): void {
    const wantsLocal = remember === true || (remember === undefined && getStorageArea() === 'local');

    if (wantsLocal) {
        const rememberPersisted = safeSetItem('local', REMEMBER_KEY, '1');
        const tokenPersisted = safeSetItem('local', TOKEN_KEY, token);
        if (rememberPersisted && tokenPersisted) {
            safeRemoveItem('session', TOKEN_KEY);
            safeRemoveItem('session', USER_KEY);
            return;
        }

        // Safari private/WebView storage can be readable but reject writes.
        // Fall back to tab-scoped session storage so login remains usable.
        safeRemoveItem('local', TOKEN_KEY);
        safeRemoveItem('local', USER_KEY);
        safeRemoveItem('local', REMEMBER_KEY);
        safeSetItem('session', TOKEN_KEY, token);
        return;
    }

    safeRemoveItem('local', TOKEN_KEY);
    safeRemoveItem('local', USER_KEY);
    safeRemoveItem('local', REMEMBER_KEY);
    safeSetItem('session', TOKEN_KEY, token);
}

export function clearToken(): void {
    safeRemoveItem('local', TOKEN_KEY);
    safeRemoveItem('local', USER_KEY);
    safeRemoveItem('local', REMEMBER_KEY);
    safeRemoveItem('session', TOKEN_KEY);
    safeRemoveItem('session', USER_KEY);
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
    // AI Brain 알파 스캐너 (애드온) — backend /api/auth/me 응답 포함
    aibain_enabled?: boolean;
    aibain_expires_at?: string | null;
    is_aibain_active?: boolean;
    is_aibain_expired?: boolean;
    aibain_days_remaining?: number | null;
    // Pro 만료 일시정지 (AI Brain 활성 중)
    pro_paused_at?: string | null;
    is_pro_paused?: boolean;
}

export function saveUser(user: AuthUserData): void {
    const serialized = JSON.stringify(user);
    const area = getStorageArea();
    if (area === 'session' || safeSetItem('local', USER_KEY, serialized)) {
        if (area === 'session') safeSetItem('session', USER_KEY, serialized);
        return;
    }

    // If localStorage filled up between token and user writes, keep the pair
    // together in sessionStorage rather than leaving a half-saved login.
    const token = safeGetItem('local', TOKEN_KEY);
    safeRemoveItem('local', TOKEN_KEY);
    safeRemoveItem('local', USER_KEY);
    safeRemoveItem('local', REMEMBER_KEY);
    if (token) safeSetItem('session', TOKEN_KEY, token);
    safeSetItem('session', USER_KEY, serialized);
}

export function getUser(): AuthUserData | null {
    for (const area of ['local', 'session'] as const) {
        const raw = safeGetItem(area, USER_KEY);
        if (!raw) continue;
        try {
            return JSON.parse(raw) as AuthUserData;
        } catch {
            safeRemoveItem(area, USER_KEY);
        }
    }
    return null;
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
