import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
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
import { postAPI, API_BASE, fetchWithTimeout } from '@/lib/api';

// ─────────────────────────────────────────────────────────────────────────────
// 핵심 원칙 (재부팅·백엔드 다운 시 유저 차단 금지)
//
// 1) 로컬 토큰이 유효하면 무조건 유저 상태를 만든다 (캐시 → 합성 순).
// 2) /api/auth/me 검증은 백그라운드 best-effort. 실패해도 user 를 절대 null 로
//    되돌리지 않는다 (네트워크 오류로 로그아웃 금지).
// 3) /api/auth/me 가 성공하면 진짜 값으로 덮어쓰고 캐시도 갱신.
// 4) 현재 세션의 확정된 401 또는 명시적 로그아웃만 세션을 종료한다.
//    이전 계정/이전 조회 응답은 현재 구독 상태를 덮어쓰지 않는다.
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
    // 서버 만료 판정. 공유 구독 helper가 열린 화면의 Pro 만료 시각도 보완한다.
    is_pro_expired?: boolean;
    // 가입 시 유저가 선택한 플랜. pending 유저 안내용.
    requested_tier?: 'pro' | 'premium' | null;
    has_pending_subscription?: boolean;
    pending_subscription_request?: AuthUserData['pending_subscription_request'];
    // ── AI Brain 알파 스캐너 애드온 (별도 30일 갱신 구독) ───────────────────
    aibain_enabled?: boolean;
    aibain_expires_at?: string | null;
    is_aibain_active?: boolean;        // backend 계산값 (만료 체크 포함)
    is_aibain_expired?: boolean;
    aibain_days_remaining?: number | null;
    kongming_expires_at?: string | null;
    is_kongming_active?: boolean;
    // Pro 만료 카운터 일시정지 (AI Brain 활성 중)
    pro_paused_at?: string | null;
    is_pro_paused?: boolean;
    // 회원 본인 텔레그램 알림 연결 여부 (/account 연결 카드가 본다)
    telegram_linked?: boolean;
    telegram_linked_at?: string | null;
}

interface AuthContextType {
    user: AuthUser | null;
    token: string | null;
    loading: boolean;
    login: (email: string, password: string, remember?: boolean) => Promise<void>;
    logout: () => void;
    isAdmin: () => boolean;
    refreshUser: () => Promise<void>;
    // register() 응답 등으로 이미 발급된 토큰+유저를 직접 세션에 심을 때 사용.
    // pending 유저는 login API 에서 401 이 나므로, 가입 직후 대시보드/플랜 페이지로
    // 바로 진입시키기 위해 이 경로가 필요하다.
    setSession: (token: string, userData: AuthUserData, remember?: boolean) => void;
}

const AuthContext = createContext<AuthContextType>({
    user: null,
    token: null,
    loading: true,
    login: async () => {},
    logout: () => {},
    isAdmin: () => false,
    refreshUser: async () => {},
    setSession: () => {},
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
        is_pro_expired: d.is_pro_expired ?? false,
        requested_tier: d.requested_tier ?? null,
        has_pending_subscription: d.has_pending_subscription,
        pending_subscription_request: d.pending_subscription_request,
        // AI Brain 알파 스캐너 (애드온) — 빠뜨리면 Summary 배너 숨김 / AiBainPage 풀 콘솔 조건이
        // React 상태에서 항상 false 로 보임 (백엔드는 정상 반환하지만 frontend 가 strip).
        aibain_enabled: d.aibain_enabled ?? false,
        aibain_expires_at: d.aibain_expires_at ?? null,
        is_aibain_active: d.is_aibain_active ?? false,
        is_aibain_expired: d.is_aibain_expired ?? false,
        aibain_days_remaining: d.aibain_days_remaining ?? null,
        kongming_expires_at: d.kongming_expires_at ?? null,
        is_kongming_active: d.is_kongming_active ?? false,
        // Pro 일시정지 (AI Brain 활성 중)
        pro_paused_at: d.pro_paused_at ?? null,
        is_pro_paused: d.is_pro_paused ?? false,
        // 텔레그램 연결 상태 — strip 되면 /account 카드가 영원히 '미연결' 로 보인다
        telegram_linked: d.telegram_linked ?? false,
        telegram_linked_at: d.telegram_linked_at ?? null,
    };
}

/**
 * 캐시는 비었지만 토큰은 유효한 상태를 위한 폴백 유저.
 *
 * 절대 가짜 권한(`tier='pro'`, `status='approved'`)을 부여하지 않는다.
 * 가드를 우회시켜 pending/free 유저가 dashboard 에 잠시라도 들어가는 사고를
 * 막기 위함. tier=null + status='unknown' 으로 발급해 ApprovedGuard 가
 * `/api/auth/me` 응답을 기다리게 한다.
 */
function synthesizeUserFromToken(token: string): AuthUser | null {
    const parts = token.split(':');
    if (parts.length !== 3) return null;
    const id = parts[0];
    if (!id) return null;
    return {
        id,
        email: '(loading)',
        name: '...',
        tier: null,
        role: 'user',
        status: 'unknown',
        pro_expires_at: null,
        is_pro_expired: false,
        requested_tier: null,
    };
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [token, setTokenState] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const sessionEpoch = useRef(0);
    const readSequence = useRef(0);
    const mounted = useRef(true);

    const logout = useCallback(() => {
        sessionEpoch.current++;
        readSequence.current++;
        clearToken();
        setTokenState(null);
        setUser(null);
        setLoading(false);
        // 방문 이력은 유지하므로 재방문 시 로그인으로 연결한다.
    }, []);

    const readUser = useCallback(async (currentToken: string, signal?: AbortSignal) => {
        const epoch = sessionEpoch.current;
        const sequence = ++readSequence.current;
        const current = () => mounted.current && !signal?.aborted
            && epoch === sessionEpoch.current && sequence === readSequence.current
            && getToken() === currentToken;
        try {
            const res = await fetchWithTimeout(`${API_BASE}/api/auth/me`, {
                headers: { Authorization: `Bearer ${currentToken}` }, signal,
            }, 10000);
            if (!current()) return;
            if (res.status === 401) {
                logout();
                return;
            }
            if (!res.ok) return;
            const data = await res.json();
            if (current() && data?.user) {
                setUser(toAuthUser(data.user));
                saveUser(data.user);
            }
        } catch {
            // 연결 장애는 마지막 확인 세션을 유지한다. 401과 구분한다.
        }
    }, [logout]);

    useEffect(() => {
        mounted.current = true;
        if (!isAuthenticated()) {
            setLoading(false);
            return () => { mounted.current = false; };
        }

        const storedToken = getToken();
        if (!storedToken) {
            setLoading(false);
            return () => { mounted.current = false; };
        }
        setTokenState(storedToken);

        // (1) 캐시된 유저 → 없으면 토큰 기반 합성 유저로 즉시 진입 보장
        const cached = getUser();
        const initial = cached ? toAuthUser(cached) : synthesizeUserFromToken(storedToken);
        if (initial) setUser(initial);

        // (2) 백그라운드 검증 — 실패해도 user 보존
        const controller = new AbortController();
        void readUser(storedToken, controller.signal).finally(() => {
            if (mounted.current && !controller.signal.aborted) setLoading(false);
        });
        return () => { mounted.current = false; controller.abort(); };
    }, [readUser]);

    // "이 기기에서 한번이라도 로그인/가입한 적 있음" 영구 플래그.
    // logout 에서는 지우지 않는다 → 방문 이력 있는 기기는 로그아웃 후 재접속 시
    // /login 으로, 없는 기기는 랜딩(/) 으로 분기해 비가입자에게 가입 유도.
    const markHasLoggedInBefore = useCallback(() => {
        try { localStorage.setItem('auth_has_logged_in_before', 'true'); } catch { /* quota/private mode */ }
    }, []);

    const setSession = useCallback((tok: string, userData: AuthUserData, remember?: boolean) => {
        if (!tok) return;
        sessionEpoch.current++;
        readSequence.current++;
        setToken(tok, remember);
        setTokenState(tok);
        setUser(toAuthUser(userData));
        saveUser(userData);
        setLoading(false);
        markHasLoggedInBefore();
    }, [markHasLoggedInBefore]);

    const login = useCallback(async (email: string, password: string, remember?: boolean): Promise<void> => {
        const epoch = ++sessionEpoch.current;
        readSequence.current++;
        const data = await postAPI<{ token: string; user?: AuthUserData }>('/api/auth/login', { email, password });
        if (!mounted.current || epoch !== sessionEpoch.current) throw new Error('로그인 요청이 변경되었습니다. 다시 확인해 주세요.');
        if (!data.token) throw new Error('No token received from server');
        if (data.user) {
            setSession(data.token, data.user, remember);
        } else {
            setToken(data.token, remember);
            setTokenState(data.token);
            setUser(synthesizeUserFromToken(data.token));
            setLoading(false);
            markHasLoggedInBefore();
        }
    }, [setSession, markHasLoggedInBefore]);

    const refreshUser = useCallback(async () => {
        const currentToken = getToken();
        if (!currentToken) return;
        await readUser(currentToken);
    }, [readUser]);

    const isAdminFn = () => checkIsAdmin() || user?.role === 'admin';

    return (
        <AuthContext.Provider value={{ user, token, loading, login, logout, isAdmin: isAdminFn, refreshUser, setSession }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}
