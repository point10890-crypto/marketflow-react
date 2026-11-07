import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import SignupPage from '@/pages/auth/SignupPage';
import PaymentRequestPage from '@/pages/auth/PaymentRequestPage';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import { nextPathForUser, safeNextPath } from '@/pages/auth/LoginPage';
import PricingPage from '@/pages/static/PricingPage';

const mocks = vi.hoisted(() => ({
    auth: {
        user: null as any,
        token: null as string | null,
        loading: false,
        setSession: vi.fn(),
        logout: vi.fn(),
        refreshUser: vi.fn(async () => {}),
    },
    fetch: vi.fn(),
    getStatus: vi.fn(async () => ({ requests: [] as any[] })),
    requestUpgrade: vi.fn(async () => ({})),
    requestConversion: vi.fn(async () => ({})),
    requestKongming: vi.fn(async () => ({})),
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => mocks.auth,
}));

vi.mock('@/lib/api', () => ({
    API_BASE: 'https://api.test',
    subscriptionAPI: {
        getStatus: mocks.getStatus,
        requestUpgrade: mocks.requestUpgrade,
        requestKongming: mocks.requestKongming,
        requestConversion: mocks.requestConversion,
    },
}));

function LocationProbe() {
    const location = useLocation();
    return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderAt(path: string, page: React.ReactElement, route: string) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path={route} element={page} />
                <Route path="*" element={<LocationProbe />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('subscription acquisition funnel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.auth.user = null;
        mocks.auth.token = null;
        mocks.auth.loading = false;
        mocks.getStatus.mockResolvedValue({ requests: [] });
        mocks.requestUpgrade.mockResolvedValue({});
        vi.stubGlobal('fetch', mocks.fetch);
    });

    const conversionPath = '/payment-request?plan=aibain_kongming_conversion';
    const conversionUser = {
        id: 135, name: '기존회원', email: 'legacy@example.test', role: 'user', tier: 'pro',
        status: 'approved', is_pro_expired: false, is_aibain_active: true,
    };
    const conversionQuote = () => ({
        eligible: true, amount: 10000, expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(), reason: '',
    });

    it('shows a separate 10,000 won offer next to the regular 50,000 won renewal', async () => {
        mocks.auth.user = { ...conversionUser, ai_bundle_conversion: conversionQuote() };
        mocks.auth.token = 'conversion-token';
        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');
        expect(screen.getByRole('link', { name: /제갈공명 전환 신청/ })).toHaveAttribute('href', conversionPath);
        expect(screen.getByText('10,000원')).toBeInTheDocument();
        expect(within(screen.getByRole('button', { name: /AI Brain \+ 제갈공명/ })).getByText('50,000원')).toBeInTheDocument();
    });

    it.each(['ineligible', 'missing user', 'different member', 'expired quote'])('keeps bank details hidden for a %s fresh status', async condition => {
        const quote = conversionQuote();
        mocks.auth.user = { ...conversionUser, ai_bundle_conversion: quote };
        mocks.auth.token = 'conversion-token';
        const latest = condition === 'missing user' ? undefined : {
            ...conversionUser,
            id: condition === 'different member' ? 136 : conversionUser.id,
            ai_bundle_conversion: { ...quote, eligible: condition !== 'ineligible',
                expires_at: condition === 'expired quote' ? '2020-01-01T00:00:00Z' : quote.expires_at },
        };
        mocks.getStatus.mockResolvedValue({ requests: [], user: latest } as any);
        renderAt(conversionPath, <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByText(/전환 신청 자격을 확인할 수 없습니다/)).toBeInTheDocument();
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();
        expect(mocks.requestConversion).not.toHaveBeenCalled();
    });

    it('quotes conversion from the current server even if cached eligibility is absent', async () => {
        mocks.auth.user = conversionUser;
        mocks.auth.token = 'conversion-token';
        mocks.getStatus.mockResolvedValue({ requests: [], user: { ...conversionUser, ai_bundle_conversion: conversionQuote() } } as any);
        renderAt(conversionPath, <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByText('10,000원')).toBeInTheDocument();
        expect(screen.getByText(/제갈공명 이용 종료/)).toBeInTheDocument();
        expect(screen.getByText('국민은행')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /승인 신청/ }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');
        expect(mocks.requestConversion).toHaveBeenCalledWith('conversion-token', '기존회원');
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('keeps a pending conversion in the existing queue and shows its captured expiry', async () => {
        mocks.auth.user = conversionUser;
        mocks.auth.token = 'conversion-token';
        mocks.getStatus.mockResolvedValue({ requests: [{
            id: 10, status: 'pending', request_type: 'aibain_kongming_conversion',
            amount: '10,000원', conversion_expires_at: conversionQuote().expires_at,
        }] });
        const payment = renderAt(conversionPath, <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();
        payment.unmount();
        renderAt('/pending-approval', <PendingApprovalPage />, '/pending-approval');
        expect(await screen.findByRole('heading', { name: '제갈공명 전환 승인 대기 중' })).toBeInTheDocument();
        expect(screen.getByText('10,000원')).toBeInTheDocument();
        expect(screen.getByText('제갈공명 이용 종료')).toBeInTheDocument();
        expect(screen.queryByText(/30일 이용합니다/)).not.toBeInTheDocument();
    });

    it.each(['current', 'inactive AI', 'changed expiry', 'prior Kongming', 'missing user'])(
        'only displays pending transfer instructions with current AI terms: %s', async condition => {
            const expiry = conversionQuote().expires_at;
            mocks.auth.user = conversionUser;
            mocks.auth.token = 'conversion-token';
            const latest = condition === 'missing user' ? undefined : {
                ...conversionUser,
                is_aibain_active: condition !== 'inactive AI',
                aibain_expires_at: condition === 'changed expiry' ? new Date(Date.now() + 86_400_000).toISOString() : expiry,
                kongming_expires_at: condition === 'prior Kongming' ? '2020-01-01T00:00:00Z' : null,
            };
            mocks.getStatus.mockResolvedValue({ user: latest, requests: [{
                id: 10, status: 'pending', request_type: 'aibain_kongming_conversion',
                amount: '10,000원', conversion_expires_at: expiry,
            }] } as any);
            renderAt('/pending-approval', <PendingApprovalPage />, '/pending-approval');
            expect(await screen.findByRole('heading', { name: '제갈공명 전환 승인 대기 중' })).toBeInTheDocument();
            if (condition === 'current') {
                expect(screen.getByText('입금 계좌를 다시 확인하려면')).toBeInTheDocument();
            } else {
                expect(screen.getByText(/추가 입금 전에 관리자에게 문의/)).toBeInTheDocument();
                expect(screen.queryByText('입금 계좌를 다시 확인하려면')).not.toBeInTheDocument();
                expect(screen.queryByText('국민은행')).not.toBeInTheDocument();
            }
        },
    );

    it('refreshes current auth before opening AI Brain after conversion approval', async () => {
        mocks.auth.user = conversionUser;
        mocks.auth.token = 'conversion-token';
        const approved = {
            ...conversionUser, is_kongming_active: true, kongming_expires_at: conversionQuote().expires_at,
        };
        mocks.getStatus.mockResolvedValue({ user: approved, requests: [
            { id: 10, status: 'approved', request_type: 'aibain_kongming_conversion' },
        ] } as any);
        const page = <MemoryRouter initialEntries={['/pending-approval']}>
            <Routes>
                <Route path="/pending-approval" element={<PendingApprovalPage />} />
                <Route path="*" element={<LocationProbe />} />
            </Routes>
        </MemoryRouter>;
        const view = render(page);
        expect(await screen.findByRole('heading', { name: '승인이 확인되었습니다' })).toBeInTheDocument();
        expect(mocks.auth.refreshUser).toHaveBeenCalled();
        expect(screen.queryByTestId('location')).not.toBeInTheDocument();
        mocks.auth.user = approved;
        view.rerender(<MemoryRouter initialEntries={['/pending-approval']}>
            <Routes>
                <Route path="/pending-approval" element={<PendingApprovalPage />} />
                <Route path="*" element={<LocationProbe />} />
            </Routes>
        </MemoryRouter>);
        expect(await screen.findByTestId('location')).toHaveTextContent('/dashboard/ai-bain');
    });

    it('returns the existing member to the conversion link after login', () => {
        expect(nextPathForUser(conversionUser, conversionPath)).toBe(conversionPath);
        expect(nextPathForUser({ ...conversionUser, has_pending_subscription: true }, conversionPath)).toBe('/pending-approval');
    });

    it('routes an expired member with an existing request away from bank details', async () => {
        mocks.auth.user = {id: 55, name: '재구독', role: 'user', tier: 'pro', status: 'expired', is_pro_expired: true};
        mocks.auth.token = 'test-token';
        mocks.getStatus.mockResolvedValue({requests: [{status: 'pending'}]});
        renderAt('/payment-request?plan=pro&resubscribe=1', <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('returns an active member to plan comparison instead of bouncing to the dashboard', async () => {
        mocks.auth.user = { id: 91, name: '기존 회원', role: 'user', tier: 'pro', status: 'approved' };
        mocks.auth.token = 'active-token';
        renderAt('/payment-request?plan=pro&aibain=1', <PaymentRequestPage />, '/payment-request');
        fireEvent.click(await screen.findByRole('button', { name: '다른 플랜 선택' }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?change=1&plan=pro&aibain=1');
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('offers a base-only renewal without adding AI or submitting a request on plan selection', async () => {
        mocks.auth.user = { id: 91, name: '기존 회원', role: 'user', tier: 'pro', status: 'approved' };
        mocks.auth.token = 'active-token';
        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');
        fireEvent.click(screen.getByRole('button', { name: 'AI 추가 없이 PRO 30일 연장 · 50,000원' }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=pro&renew=1');
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it.each(['rejected', 'withdrawn'])('keeps a %s Ultra application visible and offers its previous plan directly', async status => {
        mocks.auth.user={id:294,name:'취소회원',email:'cancel@example.test',role:'user',status:'pending',tier:null,requested_tier:'premium',has_pending_subscription:false};
        mocks.auth.token='cancel-token';
        mocks.getStatus.mockResolvedValue({requests:[{id:301,status,to_tier:'premium'}]});
        renderAt('/pending-approval',<PendingApprovalPage />,'/pending-approval');
        expect(await screen.findByRole('heading', { name: status === 'rejected' ? '구독 신청이 거절되었습니다' : '구독 신청이 취소되었습니다' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '다시 신청' })).toHaveAttribute('href', '/payment-request?plan=premium');
        expect(nextPathForUser(mocks.auth.user,null)).toBe('/plan-select');
    });

    it('keeps a pending request outside recent history in approval and blocks another deposit', async () => {
        mocks.auth.user={id:1,name:'회원',role:'user',tier:'pro',status:'expired',is_pro_expired:true};mocks.auth.token='token';
        mocks.getStatus.mockResolvedValue({requests:Array.from({length:10},()=>({status:'rejected'})),pending_request:{id:2,status:'pending',request_type:'resubscription',to_tier:'pro',amount:'50,000원'}} as any);
        const payment=renderAt('/payment-request?plan=pro',<PaymentRequestPage />,'/payment-request');
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');payment.unmount();
        renderAt('/pending-approval',<PendingApprovalPage />,'/pending-approval');
        expect(await screen.findByText('50,000원')).toBeInTheDocument();
        expect(screen.getByRole('heading',{name:'승인 대기 중'})).toBeInTheDocument();expect(screen.queryByTestId('location')).not.toBeInTheDocument();
    });

    it('shows the base and AI Brain plans and preserves the legacy plan query', async () => {
        renderAt('/pricing', <PricingPage />, '/pricing');

        expect(screen.getByRole('heading', { name: 'Pro' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Pro + AI Brain' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Ultra Pro' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Ultra Pro + AI Brain' })).toBeInTheDocument();
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /^Pro \+ AI Brain 선택하기/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/signup?plan=pro&aibain=1');
        expect(mocks.fetch).not.toHaveBeenCalled();
    });

    it('lists the Pro and AI bundle at 100,000 won and carries it to signup', async () => {
        renderAt('/pricing', <PricingPage />, '/pricing');
        const card = screen.getByRole('heading', { name: 'Pro + AI Brain' }).closest('article')!;
        expect(within(card).getByText('100,000원')).toBeInTheDocument();
        expect(within(card).getByText('AI·제갈공명 30일 + 보존되는 Pro 30일')).toBeInTheDocument();
        fireEvent.click(within(card).getByRole('button', { name: /선택하기/ }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/signup?plan=pro&aibain=1');
        expect(mocks.requestKongming).not.toHaveBeenCalled();
    });

    it('lets a member without Pro select the combined plan', async () => {
        mocks.auth.user = { id: 54, name: '신규 회원', role: 'user', tier: null, status: 'pending' };
        mocks.auth.token = 'combined-token';
        renderAt('/plan-select?plan=aibain_kongming', <PlanSelectPage />, '/plan-select');
        fireEvent.click(screen.getByRole('heading', { name: 'Pro + AI Brain' }).closest('button')!);
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=pro&aibain=1');
    });

    it('resolves a retired standalone link to the 50,000 won active Pro bundle', async () => {
        mocks.auth.user = {
            id: 54, name: '기존 회원', role: 'user', tier: 'pro', status: 'approved', is_aibain_active: true,
        };
        mocks.auth.token = 'combined-token';
        renderAt('/payment-request?plan=aibain_kongming', <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByText('선택한 플랜: AI Brain + 제갈공명')).toBeInTheDocument();
        expect(screen.getAllByText('50,000원').length).toBeGreaterThan(0);
        expect(screen.queryByText('40,000원')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /승인 신청/ }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');
        expect(mocks.requestUpgrade).toHaveBeenCalledWith('pro', 'combined-token', '기존 회원', true, 50000);
        expect(mocks.requestKongming).not.toHaveBeenCalled();
    });

    it.each([
        [null, 'pending', 'pro', '100,000원'],
        ['pro', 'expired', 'pro', '100,000원'],
        ['pro', 'approved', 'pro', '50,000원'],
        ['premium', 'approved', 'premium', '50,000원'],
    ])('quotes the retired bundle link from current membership: %s %s', async (tier, status, target, price) => {
        mocks.auth.user = { id: 80, name: '금액 검증', role: 'user', tier, status };
        mocks.auth.token = 'quote-token';
        renderAt('/payment-request?plan=aibain_kongming', <PaymentRequestPage />, '/payment-request');
        expect((await screen.findAllByText(price)).length).toBeGreaterThan(0);
        expect(screen.getByText(/PRO 잔여기간이 줄어들지|Ultra PRO 평생 이용권/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /승인 신청/ }));
        await waitFor(() => expect(mocks.requestUpgrade).toHaveBeenCalledWith(target, 'quote-token', '금액 검증', true, Number(price.replace(/[^0-9]/g, ''))));
        expect(mocks.requestKongming).not.toHaveBeenCalled();
    });

    it('sends a signed-in visitor to change mode without submitting a subscription', async () => {
        mocks.auth.user = {
            id: 11,
            email: 'member@example.test',
            name: '회원',
            role: 'user',
            status: 'approved',
            tier: 'pro',
        };
        mocks.auth.token = 'member-token';

        renderAt('/pricing', <PricingPage />, '/pricing');
        fireEvent.click(screen.getByRole('button', { name: /Ultra Pro \+ AI Brain 선택 계속하기/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?change=1&plan=premium&aibain=1');
        expect(mocks.fetch).not.toHaveBeenCalled();
    });

    it('preserves the chosen plan through account creation and records the base requested tier', async () => {
        mocks.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({
                token: 'new-token',
                user: {
                    id: 21,
                    email: 'new@example.test',
                    name: '신규회원',
                    role: 'user',
                    status: 'pending',
                    tier: null,
                },
            }),
        } as Response);

        renderAt('/signup?plan=pro&aibain=1', <SignupPage />, '/signup');
        expect(screen.getByText('Pro + AI Brain', { selector: 'div' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute(
            'href',
            '/login?next=%2Fplan-select%3Fchange%3D1%26plan%3Dpro%26aibain%3D1',
        );

        fireEvent.change(screen.getByLabelText('이름'), { target: { value: '신규회원' } });
        fireEvent.change(screen.getByLabelText('이메일'), { target: { value: 'new@example.test' } });
        fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'Pass1234!' } });
        fireEvent.click(screen.getByRole('button', { name: /계정 만들고 플랜 확인/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?plan=pro&aibain=1');
        expect(mocks.auth.setSession).toHaveBeenCalledWith('new-token', expect.objectContaining({ id: 21 }), true);
        const request = mocks.fetch.mock.calls[0][1] as RequestInit;
        expect(JSON.parse(String(request.body))).toEqual({
            name: '신규회원',
            email: 'new@example.test',
            password: 'Pass1234!',
            requested_tier: 'pro',
        });
    });

    it('preserves a preferred plan when an existing no-tier member visits signup', async () => {
        mocks.auth.user = {
            id: 31,
            email: 'pending@example.test',
            name: '대기회원',
            role: 'user',
            status: 'pending',
            tier: null,
        };
        mocks.auth.token = 'pending-token';

        renderAt('/signup?plan=premium&aibain=1', <SignupPage />, '/signup');

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?plan=premium&aibain=1');
    });

    it('marks the preferred plan and keeps the lifetime base period honest', async () => {
        mocks.auth.user = {
            id: 41,
            email: 'pending@example.test',
            name: '대기회원',
            role: 'user',
            status: 'pending',
            tier: null,
            is_pro_expired: false,
        };
        mocks.auth.token = 'pending-token';

        renderAt('/plan-select?plan=premium&aibain=1', <PlanSelectPage />, '/plan-select');

        const preferred = screen.getByRole('button', { name: /Ultra Pro \+ AI Brain/ });
        expect(preferred).toHaveAttribute('aria-pressed', 'true');
        expect(within(preferred).getAllByText('평생 이용 + AI·제갈공명 30일').length).toBeGreaterThan(0);
        expect(within(preferred).queryByText('원 / 30일')).not.toBeInTheDocument();

        fireEvent.click(preferred);
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=premium&aibain=1');
    });

    it('shows an active Pro member the actual 50,000 won AI Brain add-on amount', async () => {
        mocks.auth.user = {
            id: 51,
            email: 'active-pro@example.test',
            name: '활성회원',
            role: 'user',
            status: 'approved',
            tier: 'pro',
            is_pro_expired: false,
            is_aibain_active: false,
        };
        mocks.auth.token = 'active-token';

        renderAt('/plan-select?change=1&plan=pro&aibain=1', <PlanSelectPage />, '/plan-select');

        const addon = screen.getByRole('button', { name: /AI Brain \+ 제갈공명/ });
        expect(within(addon).getByText('50,000원')).toBeInTheDocument();
        expect(within(addon).queryByText('100,000원')).not.toBeInTheDocument();
        expect(within(addon).getByText('AI Brain·제갈공명 50,000원으로 추가')).toBeInTheDocument();

        const currentPro = screen.getByRole('heading', { name: 'Pro' }).closest('button');
        expect(currentPro).toBeDisabled();

        fireEvent.click(addon);
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=pro&aibain=1');
    });

    it('blocks an active Ultra Pro downgrade and prices its AI Brain add-on separately', () => {
        mocks.auth.user = {
            id: 61,
            email: 'active-ultra@example.test',
            name: '울트라회원',
            role: 'user',
            status: 'approved',
            tier: 'premium',
            is_pro_expired: false,
            is_aibain_active: false,
        };
        mocks.auth.token = 'ultra-token';

        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');

        expect(screen.queryByRole('heading', { name: 'Pro' })).not.toBeInTheDocument();
        const ultraCard = screen.getByRole('heading', { name: 'Ultra Pro' }).closest('button');
        const addon = screen.getByRole('button', { name: /AI Brain \+ 제갈공명/ });

        expect(ultraCard).toBeDisabled();
        expect(within(addon).getByText('50,000원')).toBeInTheDocument();
        expect(addon).toBeEnabled();
    });

    it("hides the dead '처음으로' escape for funneled members but keeps it in change mode", () => {
        // 노티어 회원: / 는 FunnelGate 가 곧장 /plan-select 로 되돌리므로 버튼 숨김 (로그아웃만 남음)
        mocks.auth.user = {
            id: 71, email: 'parked@example.test', name: '대기', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'parked-token';
        const { unmount } = renderAt('/plan-select', <PlanSelectPage />, '/plan-select');
        expect(screen.queryByRole('button', { name: /이용 화면으로 돌아가기/ })).toBeNull();
        expect(screen.getByRole('button', { name: /로그아웃/ })).toBeInTheDocument();
        unmount();

        // 활성 구독자(change=1): FunnelGate 통과 대상이므로 랜딩 이동 버튼 유지
        mocks.auth.user = {
            id: 72, email: 'active@example.test', name: '활성', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: false,
        };
        mocks.auth.token = 'active-token';
        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');
        expect(screen.getByRole('button', { name: /이용 화면으로 돌아가기/ })).toBeInTheDocument();
    });

    it('refreshes auth state on mount and window focus so an admin tier grant unparks the user', () => {
        mocks.auth.user = {
            id: 81, email: 'granted@example.test', name: '부여대상', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'granted-token';
        const { unmount } = renderAt('/plan-select', <PlanSelectPage />, '/plan-select');
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(1);
        fireEvent(window, new Event('focus'));
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(2);
        unmount();

        mocks.auth.refreshUser.mockClear();
        renderAt('/payment-request?plan=pro', <PaymentRequestPage />, '/payment-request');
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(1);
        fireEvent(window, new Event('focus'));
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(2);
    });

    it('lets an active Pro through the payment guard with renew=1 and submits an early renewal', async () => {
        mocks.auth.user = {
            id: 84, email: 'active@example.test', name: '활성회원', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: false,
            pro_expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
        };
        mocks.auth.token = 'active-token';

        renderAt('/payment-request?plan=pro&renew=1', <PaymentRequestPage />, '/payment-request');

        // 가드에 튕기지 않고 갱신 라벨이 보인다
        expect((await screen.findAllByText(/Pro 갱신 \(만료 전\)/)).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/승인 시 기존 만료일부터 \+30일/).length).toBeGreaterThan(0);
        expect(screen.queryByTestId('location')).toBeNull();

        fireEvent.click(await screen.findByRole('button', { name: /승인 신청/ }));
        expect(await screen.findByTestId('location')).toHaveTextContent('/pending-approval');
        expect(mocks.requestUpgrade).toHaveBeenCalledWith('pro', 'active-token', '활성회원', false, 50000);
    });

    it('still bounces an active Pro from the payment page without renew=1', async () => {
        mocks.auth.user = {
            id: 85, email: 'active2@example.test', name: '활성회원2', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: false,
        };
        mocks.auth.token = 'active-token';

        renderAt('/payment-request?plan=pro', <PaymentRequestPage />, '/payment-request');
        expect(await screen.findByTestId('location')).toHaveTextContent('/dashboard');
    });

    it("maps the stale 'Already on ... tier' 400 to a refresh + dashboard instead of a dead-end error", async () => {
        mocks.auth.user = {
            id: 82, email: 'granted@example.test', name: '부여됨', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'granted-token';
        mocks.requestUpgrade.mockRejectedValue(new Error('Already on pro tier'));

        renderAt('/payment-request?plan=pro', <PaymentRequestPage />, '/payment-request');
        fireEvent.click(await screen.findByRole('button', { name: /승인 신청/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/dashboard');
        expect(mocks.auth.refreshUser).toHaveBeenCalled();
    });

    it('treats an expired-Pro renewal wait as pending, not an active upgrade', async () => {
        mocks.auth.user = {
            id: 91, email: 'expired@example.test', name: '만료회원', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: true,
        };
        mocks.auth.token = 'expired-token';
        mocks.getStatus.mockResolvedValue({
            requests: [{
                id: 1, status: 'pending', from_tier: 'pro', to_tier: 'pro',
                request_type: 'renewal', amount: '110,000원', depositor_name: '만료회원',
            }],
        });

        renderAt('/pending-approval', <PendingApprovalPage />, '/pending-approval');

        expect(await screen.findByRole('heading', { name: '승인 대기 중' })).toBeInTheDocument();
        expect(screen.queryByText('업그레이드 대기 중')).toBeNull();
        // 만료 재구독자는 대시보드 버튼(ApprovedGuard 가 다시 plan-select 로 튕김) 대신 로그아웃 노출
        expect(screen.queryByRole('button', { name: /대시보드로 돌아가기/ })).toBeNull();
        expect(screen.getByRole('button', { name: '로그아웃' })).toBeInTheDocument();
        expect(screen.getByText('110,000원')).toBeInTheDocument();
    });

    it('restores a safely selected plan after login for no-tier, active, and expired members', () => {
        const planned = '/plan-select?change=1&plan=premium&aibain=1';

        expect(nextPathForUser({ status: 'pending', tier: null }, planned)).toBe(planned);
        expect(nextPathForUser({ status: 'approved', tier: 'pro' }, planned)).toBe(planned);
        // 구독 신청 제출(requested_tier 기록) 회원은 재입금 안내 대신 승인 대기로
        expect(nextPathForUser({ status: 'pending', tier: null, requested_tier: 'pro' }, null))
            .toBe('/pending-approval');
        expect(nextPathForUser({ status: 'pending', tier: null }, null)).toBe('/plan-select');
        expect(nextPathForUser({ status: 'expired', tier: 'pro', is_pro_expired: true }, planned)).toBe(
            '/plan-select?plan=premium&aibain=1&resubscribe=1&from=expired',
        );
        expect(safeNextPath('https://evil.example/plan-select')).toBeNull();
        expect(safeNextPath('//evil.example/plan-select')).toBeNull();
    });

    it('keeps promotional pricing mutation-free and auth pages on document scrolling', () => {
        const src = resolve(__dirname, '..');
        const pricing = readFileSync(resolve(src, 'pages/static/PricingPage.tsx'), 'utf8');
        const signup = readFileSync(resolve(src, 'pages/auth/SignupPage.tsx'), 'utf8');
        const planSelect = readFileSync(resolve(src, 'pages/auth/PlanSelectPage.tsx'), 'utf8');

        expect(pricing).toContain('PLAN_PAYMENT_META');
        expect(pricing).toContain('planToQuery');
        expect(pricing).not.toMatch(/subscriptionAPI|requestUpgrade|BANK_ACCOUNT/);
        expect(signup).toContain('min-h-[100dvh]');
        expect(planSelect).toContain('min-h-[100dvh]');
        expect(planSelect).not.toContain('fixed inset-0');
    });
});
