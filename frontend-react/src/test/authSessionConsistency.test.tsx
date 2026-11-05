import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { getToken, getUser, saveUser, setToken, type AuthUserData } from '@/lib/auth';

const api = vi.hoisted(() => ({ fetch: vi.fn(), post: vi.fn() }));
vi.mock('@/lib/api', () => ({ API_BASE: 'https://api.example.test', fetchWithTimeout: api.fetch, postAPI: api.post }));

const member: AuthUserData = { id: 11, email: 'member@example.test', name: '기존 회원', role: 'user', status: 'expired', tier: 'pro', is_pro_expired: true };
const renewed: AuthUserData = { ...member, status: 'approved', is_pro_expired: false, pro_expires_at: '2099-01-01T00:00:00Z' };
const another: AuthUserData = { ...renewed, id: 22, email: 'another@example.test', name: '다른 회원' };
const token = (id: number) => `${id}:${Math.floor(Date.now() / 1000) + 86400}:test-signature`;
const response = (user = member, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => ({ user }) });
function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(done => { resolve = done; });
    return { promise, resolve };
}
function Probe() {
    const auth = useAuth();
    return <>
        <output data-testid="session">{auth.user ? `${auth.user.name}:${auth.user.status}` : '로그아웃'}</output>
        <button onClick={() => { void auth.refreshUser(); }}>갱신</button>
        <button onClick={auth.logout}>로그아웃</button>
        <button onClick={() => auth.setSession(token(22), another)}>계정 변경</button>
    </>;
}
function show() { return render(<AuthProvider><Probe /></AuthProvider>); }
beforeEach(() => {
    localStorage.clear(); sessionStorage.clear(); vi.resetAllMocks();
    setToken(token(11)); saveUser(member);
});
afterEach(cleanup);

it('cannot restore an expired session when its bootstrap response arrives after logout', async () => {
    const pending = deferred<ReturnType<typeof response>>();
    api.fetch.mockReturnValue(pending.promise);
    show();
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '로그아웃' }));
    await act(async () => { pending.resolve(response(member)); });
    expect(screen.getByTestId('session')).toHaveTextContent('로그아웃');
    expect(getToken()).toBeNull();
    expect(getUser()).toBeNull();
});

it('keeps an approved renewal when an older expiry refresh resolves last', async () => {
    api.fetch.mockResolvedValueOnce(response(member));
    show();
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    await act(async () => {});
    const older = deferred<ReturnType<typeof response>>();
    const newer = deferred<ReturnType<typeof response>>();
    api.fetch.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    fireEvent.click(screen.getByRole('button', { name: '갱신' }));
    fireEvent.click(screen.getByRole('button', { name: '갱신' }));
    await act(async () => { newer.resolve(response(renewed)); });
    expect(screen.getByTestId('session')).toHaveTextContent('기존 회원:approved');
    await act(async () => { older.resolve(response(member)); });
    expect(screen.getByTestId('session')).toHaveTextContent('기존 회원:approved');
    expect(getUser()?.status).toBe('approved');
});

it('ignores a bootstrap 401 from the previous account after session replacement', async () => {
    const old = deferred<ReturnType<typeof response>>();
    api.fetch.mockReturnValue(old.promise);
    show();
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '계정 변경' }));
    await act(async () => { old.resolve(response(member, 401)); });
    expect(screen.getByTestId('session')).toHaveTextContent('다른 회원:approved');
    expect(getToken()).toBe(token(22));
    expect(getUser()?.id).toBe(22);
});

it('clears a currently rejected authentication token while retaining sessions on transport errors', async () => {
    api.fetch.mockResolvedValueOnce(response(renewed));
    show();
    await waitFor(() => expect(screen.getByTestId('session')).toHaveTextContent('approved'));
    api.fetch.mockRejectedValueOnce(new Error('network'));
    fireEvent.click(screen.getByRole('button', { name: '갱신' }));
    await act(async () => {});
    expect(getToken()).not.toBeNull();
    expect(screen.getByTestId('session')).toHaveTextContent('approved');
    api.fetch.mockResolvedValueOnce(response(member, 401));
    fireEvent.click(screen.getByRole('button', { name: '갱신' }));
    await waitFor(() => expect(screen.getByTestId('session')).toHaveTextContent('로그아웃'));
    expect(getToken()).toBeNull();
});
