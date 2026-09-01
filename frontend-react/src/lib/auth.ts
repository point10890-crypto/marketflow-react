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

/**
 * AI Brain 섹션 노출 여부 — 관리자 또는 활성 AI Brain 애드온 구독자만 true.
 * 내비/Summary 카드/라우트 가드가 전부 이 한 곳을 본다 (백엔드 admin_or_aibain_required 와 동일 기준).
 * 만료·미구독 Pro 유저는 false → 섹션 자체가 보이지 않고, Summary 의 업그레이드 배너만 남는다.
 */
export function canAccessAiBain(user: { role?: string | null; is_aibain_active?: boolean | null } | null | undefined): boolean {
    if (!user) return false;
    return user.role === 'admin' || !!user.is_aibain_active;
}

/** subscriptionFunnelTarget 이 판정에 쓰는 최소 유저 형태 (AuthContext.AuthUser 부분집합). */
export interface FunnelUser {
    role?: string | null;
    status?: string | null;
    tier?: string | null;
    is_pro_expired?: boolean | null;
}

/**
 * 로그인한 회원이 "구독 퍼널의 어느 단계로 보내져야 하는가"의 단일 기준.
 *
 * 반환값:
 *  - null                              : 리다이렉트 불필요 (비로그인 방문자 / 로딩 중 unknown / admin / 활성 구독자)
 *  - '/plan-select?resubscribe=…'      : 만료 회원 → 재구독
 *  - '/plan-select'                    : tier 미선택 (노티어) → 플랜 선택
 *  - '/pending-approval'               : 플랜 신청 후 승인 대기
 *
 * ApprovedGuard/ProGuard(보호 라우트), FunnelGate(공개 라우트), 404 CTA 가 전부
 * 이 한 함수를 본다 — 분기 기준이 갈라지면 "비구독 회원이 머무는 페이지"가 생긴다.
 */
export function subscriptionFunnelTarget(user: FunnelUser | null | undefined): string | null {
    if (!user) return null;
    // 'unknown' = 토큰만 있고 /api/auth/me 응답 전 합성 유저 — 판정 보류 (가드가 별도 처리)
    if (user.status === 'unknown') return null;
    if (user.role === 'admin') return null;
    if (user.status === 'expired' || user.is_pro_expired) return '/plan-select?resubscribe=1&from=expired';
    if (!user.tier) return '/plan-select';
    if (user.status !== 'approved') return '/pending-approval';
    if (user.tier !== 'pro' && user.tier !== 'premium') return '/pending-approval';
    return null;
}
