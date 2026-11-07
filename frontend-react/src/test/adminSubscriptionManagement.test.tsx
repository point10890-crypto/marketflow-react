import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UsersTab } from '@/pages/admin/tabs/UsersTab';
import SubscriptionsTab from '@/pages/admin/tabs/SubscriptionsTab';
import ProExpiryTab from '@/pages/admin/ProExpiryTab';

const api = vi.hoisted(() => ({ getUsers: vi.fn(), getDuplicates: vi.fn(), getSubscriptions: vi.fn(),
    getUser: vi.fn(), expireSubscription: vi.fn(), setUserTier: vi.fn(), extendPro: vi.fn(),
    enableAibain: vi.fn(), extendAibain: vi.fn(), revokeAibain: vi.fn(),
    approveSubscription: vi.fn(), rejectSubscription: vi.fn(), withdrawSubscription: vi.fn(), deleteSubscription: vi.fn(), manageAiBundle: vi.fn(), deleteUser: vi.fn(), setUserStatus: vi.fn(), fetchAuthAPI: vi.fn(), bulkTier: vi.fn(), bulkApprove: vi.fn() }));
vi.mock('@/lib/api', () => ({ adminAPI: api, fetchAuthAPI: api.fetchAuthAPI }));
const member = { id: 7, name: '관리대상', email: 'member@example.test', role: 'user', tier: 'pro', status: 'approved', pro_expires_at: '2026-12-05T00:00:00Z', created_at: '2026-01-01', approved_at: '2026-01-01', last_login_at: null, is_aibain_active: true };
const pending = { id: 77, user_id: 7, user_name: '관리대상', user_email: member.email, request_type: 'renewal', from_tier: 'pro', to_tier: 'pro', status: 'pending', payment_id: null, admin_note: null, depositor_name: '입금자', amount: '50,000원', created_at: '2026-11-05', processed_at: null };
const expired = { ...member, status: 'expired', is_pro_expired: true, is_aibain_active: false };
beforeEach(() => {
    vi.resetAllMocks();
    api.getUsers.mockResolvedValue({ users: [member], total: 1, total_pages: 1 });
    api.getDuplicates.mockResolvedValue({ groups: [], total_groups: 0 });
    api.getSubscriptions.mockResolvedValue({ requests: [], pending_signups: [], expired_members: [] });
    api.getUser.mockResolvedValue(member);
    api.fetchAuthAPI.mockResolvedValue({ ...member, subscription_history: [], audit_logs: [] });
    api.expireSubscription.mockResolvedValue({ user: expired, message: '전체 구독 만료' });
    api.setUserTier.mockResolvedValue({ user: member });
    api.extendPro.mockResolvedValue({ user: member });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(window, 'prompt').mockReturnValue('');
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function openManagement() {
    render(<UsersTab apiToken="admin-token" currentUserId={99} />);
    fireEvent.click(await screen.findByRole('button', { name: '관리대상 구독 관리' }));
    return screen.findByRole('region', { name: '관리대상 구독 관리' });
}

describe('admin member subscription management', () => {
    it('confirms the 10,000 won conversion and displays the captured expiry in history', async () => {
        const conversion = { ...pending, request_type: 'aibain_kongming_conversion',
            amount: '10,000원', conversion_expires_at: '2026-12-12T07:00:00Z' };
        api.getSubscriptions.mockResolvedValue({ requests: [conversion] });
        api.approveSubscription.mockResolvedValue({ request: { ...conversion, status: 'approved' } });
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);
        const approve = await screen.findByRole('button', { name: '제갈공명 전환 승인' });
        expect(screen.getByText('10,000원')).toBeInTheDocument();
        expect(screen.getByText(/제갈공명 이용 종료 .*12월 12일/)).toBeInTheDocument();
        vi.mocked(window.confirm).mockReturnValueOnce(false);
        fireEvent.click(approve);
        expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/10,000원[\s\S]*제갈공명 이용 종료.*12월 12일/));
        expect(api.approveSubscription).not.toHaveBeenCalled();
        fireEvent.click(approve);
        expect(await screen.findByText('제갈공명 전환 · 10,000원')).toBeInTheDocument();
        expect(api.approveSubscription).toHaveBeenCalledOnce();
        expect(api.approveSubscription).toHaveBeenCalledWith(77, 'admin-token');
    });
    it('revokes AI and Kongming together while keeping the base membership', async () => {
        api.manageAiBundle.mockResolvedValue({ user: { ...member, is_aibain_active: false, is_kongming_active: false } });
        const panel = await openManagement();
        fireEvent.click(await within(panel).findByRole('button', { name: 'AI·제갈공명 철회' }));
        await waitFor(() => expect(api.manageAiBundle).toHaveBeenCalledWith(7, 'revoke', undefined, 'admin-token'));
        expect(api.expireSubscription).not.toHaveBeenCalled();
    });
    it('withdraws a pending application without revoking existing access', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        api.withdrawSubscription.mockResolvedValue({ request: { ...pending, status: 'withdrawn' } });
        const panel = await openManagement();
        fireEvent.click(await within(panel).findByRole('button', { name: '신청 철회' }));
        await waitFor(() => expect(api.withdrawSubscription).toHaveBeenCalledWith(77, undefined, 'admin-token'));
        expect(await within(panel).findByText('대기 신청 철회 완료 · 재신청 가능')).toBeInTheDocument();
        expect(api.expireSubscription).not.toHaveBeenCalled();
    });
    it('manages expired members and verifies email before account deletion inside the subscription tab', async () => {
        api.getUsers.mockResolvedValue({ users: [expired], total: 1, total_pages: 1 });
        api.deleteUser.mockResolvedValue({ message: 'deleted' });
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);
        fireEvent.change(await screen.findByLabelText('구독 상태 필터'), { target: { value: 'expired' } });
        await waitFor(() => expect(api.getUsers).toHaveBeenLastCalledWith('admin-token', expect.objectContaining({ subscription_state: 'expired' })));
        fireEvent.click(await screen.findByRole('button', { name: '관리대상 직권 처리' }));
        const panel = await screen.findByRole('region', { name: '관리대상 구독 관리' });
        await within(panel).findByRole('button', { name: /선택 플랜.*부여/ });
        fireEvent.click(within(panel).getByRole('button', { name: '회원 계정 삭제' }));
        expect(api.deleteUser).not.toHaveBeenCalled();
        vi.mocked(window.prompt).mockReturnValueOnce(member.email);
        api.getUsers.mockResolvedValue({ users: [], total: 0, total_pages: 0 });
        fireEvent.click(within(panel).getByRole('button', { name: '회원 계정 삭제' }));
        await waitFor(() => expect(api.deleteUser).toHaveBeenCalledWith(7, 'admin-token'));
    });
    it('removes approved history without ending the paid entitlement', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [{ ...pending, status: 'approved' }] });
        api.deleteSubscription.mockResolvedValue({ request: { ...pending, status: 'approved', archived_at: '2026-11-07T00:00:00Z' } });
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);
        fireEvent.click(await screen.findByRole('button', { name: '내역 삭제' }));
        await waitFor(() => expect(api.deleteSubscription).toHaveBeenCalledWith(77, 'admin-token'));
        expect(api.expireSubscription).not.toHaveBeenCalled();
        expect(screen.queryByText('approved')).not.toBeInTheDocument();
    });
    it('does not offer grant or expiry actions for a rejected member without pending requests', async () => {
        api.getUsers.mockResolvedValue({ users: [{ ...member, status: 'rejected' }], total: 1 });
        const panel = await openManagement();
        expect(within(panel).queryByRole('button', { name: '전체 구독 만료' })).not.toBeInTheDocument();
        expect(await within(panel).findByText(/구독은 변경할 수 없습니다/)).toBeInTheDocument();
        expect(within(panel).queryByRole('button', { name: /선택 플랜.*부여/ })).not.toBeInTheDocument();
        expect(api.expireSubscription).not.toHaveBeenCalled();
        expect(api.setUserTier).not.toHaveBeenCalled();
    });
    it('exposes a direct subscription management control and selected plan grants', async () => {
        const panel = await openManagement();
        expect(await within(panel).findByRole('button', { name: /선택 플랜.*부여/ })).toBeEnabled();
        fireEvent.change(within(panel).getByLabelText('부여할 플랜'), { target: { value: 'premium' } });
        fireEvent.click(within(panel).getByRole('button', { name: /선택 플랜.*부여/ }));
        await waitFor(() => expect(api.setUserTier).toHaveBeenCalledWith(7, 'premium', 'admin-token'));
    });
    it('confirms all-subscription expiry for the named member, records an optional reason and updates the row', async () => {
        const panel = await openManagement();
        fireEvent.click(within(panel).getByRole('button', { name: '전체 구독 만료' }));
        const confirm = within(panel).getByRole('dialog', { name: '전체 구독 만료 확인' });
        expect(confirm).toHaveTextContent('관리대상');
        expect(confirm).toHaveTextContent(/Pro.*Ultra Pro.*AI Brain/);
        fireEvent.change(within(confirm).getByLabelText('만료 사유 (선택)'), { target: { value: '운영 확인' } });
        fireEvent.click(within(confirm).getByRole('button', { name: '전체 구독 만료 확정' }));
        await waitFor(() => expect(api.expireSubscription).toHaveBeenCalledWith(7, '운영 확인', 'admin-token'));
        expect(await screen.findByText('만료', { selector: 'span' })).toBeInTheDocument();
    });
    it('reloads pending requests after expiry interrupts the initial lookup and ignores that older response', async () => {
        let finishInitial!: (data: { requests: typeof pending[] }) => void;
        api.getSubscriptions.mockReturnValueOnce(new Promise(resolve => { finishInitial = resolve; }));
        const panel = await openManagement();
        expect(within(panel).getByText('대기 구독 요청 확인 중...')).toBeInTheDocument();
        fireEvent.click(within(panel).getByRole('button', { name: '전체 구독 만료' }));
        fireEvent.click(within(panel).getByRole('button', { name: '전체 구독 만료 확정' }));
        expect(await within(panel).findByRole('button', { name: /선택 플랜.*부여/ })).toBeEnabled();
        await act(async () => finishInitial({ requests: [pending] }));
        expect(within(panel).getByRole('button', { name: /선택 플랜.*부여/ })).toBeEnabled();
        expect(within(panel).queryByText('대기 구독 요청 확인 중...')).not.toBeInTheDocument();
        expect(within(panel).queryByRole('button', { name: /재구독.*77.*승인/ })).not.toBeInTheDocument();
    });
    it('keeps active membership on failed expiry and prevents repeat requests while busy', async () => {
        let reject!: (error: Error) => void;
        api.expireSubscription.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
        const panel = await openManagement();
        fireEvent.click(within(panel).getByRole('button', { name: '전체 구독 만료' }));
        const button = within(panel).getByRole('button', { name: '전체 구독 만료 확정' });
        fireEvent.click(button); fireEvent.click(button);
        expect(button).toBeDisabled();
        expect(api.expireSubscription).toHaveBeenCalledTimes(1);
        await act(async () => reject(new Error('만료 실패')));
        expect(within(panel).getByRole('alert')).toHaveTextContent('만료 실패');
        expect(screen.queryByText('만료', { selector: 'span' })).not.toBeInTheDocument();
    });
    it('approves the existing exact pending renewal instead of blindly extending or granting', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [{ ...pending, id: 78, user_id: 8 }, pending] });
        api.approveSubscription.mockResolvedValue({ request: { ...pending, status: 'approved' } });
        const panel = await openManagement();
        fireEvent.click(await within(panel).findByRole('button', { name: /재구독.*77.*승인/ }));
        await waitFor(() => expect(api.approveSubscription).toHaveBeenCalledWith(77, 'admin-token'));
        expect(api.setUserTier).not.toHaveBeenCalled();
        expect(api.extendPro).not.toHaveBeenCalled();
    });
    it('does not grant when pending-request lookup fails', async () => {
        api.getSubscriptions.mockRejectedValue(new Error('HTTP 503'));
        const panel = await openManagement();
        expect(await within(panel).findByRole('alert')).toHaveTextContent(/대기.*확인/);
        expect(within(panel).queryByRole('button', { name: /선택 플랜.*부여/ })).not.toBeInTheDocument();
    });
    it('rechecks pending requests before a grant so a newly submitted renewal cannot be bypassed', async () => {
        const panel = await openManagement();
        const grant = await within(panel).findByRole('button', { name: /선택 플랜.*부여/ });
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        fireEvent.click(grant);
        expect(await within(panel).findByRole('button', { name: /재구독.*77.*승인/ })).toBeInTheDocument();
        expect(api.setUserTier).not.toHaveBeenCalled();
    });
    it('retries member-state refresh after a confirmed approval without submitting the approval twice', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        api.approveSubscription.mockResolvedValue({ request: { ...pending, status: 'approved' } });
        api.getUser.mockRejectedValueOnce(new Error('HTTP 503'));
        const panel = await openManagement();
        fireEvent.click(await within(panel).findByRole('button', { name: /재구독.*77.*승인/ }));
        expect(await within(panel).findByRole('alert')).toHaveTextContent(/승인.*완료.*회원.*조회/);
        fireEvent.click(within(panel).getByRole('button', { name: '회원 상태 다시 조회' }));
        await waitFor(() => expect(within(panel).queryByRole('alert')).not.toBeInTheDocument());
        expect(api.approveSubscription).toHaveBeenCalledTimes(1);
    });
    it('preserves an active Pro period through its explicit extension action', async () => {
        api.extendPro.mockResolvedValue({ user: member });
        const panel = await openManagement();
        fireEvent.click(await within(panel).findByRole('button', { name: 'Pro +30일 연장' }));
        await waitFor(() => expect(api.extendPro).toHaveBeenCalledWith(7, 30, 'admin-token'));
        expect(api.setUserTier).not.toHaveBeenCalled();
    });
    it('does not bypass pending requests through bulk tier assignment', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        render(<UsersTab apiToken="admin-token" />);
        await screen.findByRole('button', { name: '관리대상' });
        fireEvent.click(screen.getAllByRole('checkbox')[1]);
        fireEvent.click(screen.getByRole('button', { name: '일괄 Pro' }));
        expect(await screen.findByRole('alert')).toHaveTextContent(/대기.*요청.*승인/);
        expect(api.bulkTier).not.toHaveBeenCalled();
    });
    it('shows failed user loading as unavailable and retries without claiming no matching members', async () => {
        api.getUsers.mockRejectedValueOnce(new Error('HTTP 503'));
        render(<UsersTab apiToken="admin-token" />);
        expect(await screen.findByRole('alert')).toHaveTextContent(/회원.*불러오지 못/);
        expect(screen.queryByText('검색 결과가 없습니다')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }));
        expect(await screen.findByRole('button', { name: '관리대상' })).toBeInTheDocument();
    });
    it('retains last-good users when a filter refresh fails', async () => {
        render(<UsersTab apiToken="admin-token" />);
        expect(await screen.findByRole('button', { name: '관리대상' })).toBeInTheDocument();
        api.getUsers.mockRejectedValueOnce(new Error('HTTP 503'));
        fireEvent.click(screen.getByRole('button', { name: '만료' }));
        expect(await screen.findByRole('alert')).toHaveTextContent(/이전.*표시/);
        expect(screen.getByRole('button', { name: '관리대상' })).toBeInTheDocument();
    });
    it('binds detail responses to the most recently opened member', async () => {
        let finishFirst!: (data: typeof member) => void;
        const other = { ...member, id: 8, name: '다른회원', email: 'other@example.test' };
        api.getUsers.mockResolvedValue({ users: [member, other], total: 2 });
        api.fetchAuthAPI.mockReturnValueOnce(new Promise(resolve => { finishFirst = resolve; })).mockResolvedValueOnce(other);
        render(<UsersTab apiToken="admin-token" />);
        fireEvent.click(await screen.findByRole('button', { name: '관리대상' }));
        fireEvent.click(screen.getByRole('button', { name: '다른회원' }));
        const dialog = await screen.findByRole('dialog', { name: '회원 상세 정보' });
        await waitFor(() => expect(within(dialog).getByText('다른회원', { selector: 'p' })).toBeInTheDocument());
        await act(async () => finishFirst(member));
        expect(within(dialog).getByText('다른회원', { selector: 'p' })).toBeInTheDocument();
        expect(within(dialog).queryByText('관리대상', { selector: 'p' })).not.toBeInTheDocument();
    });
    it('retains a member when deletion fails and locks repeated delete clicks', async () => {
        let reject!: (error: Error) => void;
        api.deleteUser.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
        render(<UsersTab apiToken="admin-token" currentUserId={99} />);
        fireEvent.click((await screen.findAllByTitle('삭제'))[0]);
        const dialog = screen.getByRole('dialog', { name: '회원 삭제 확인' });
        expect(dialog).toHaveTextContent(/게시글.*댓글.*구매.*구독 요청/);
        expect(dialog).toHaveTextContent(/관리자 감사.*보존/);
        const remove = within(dialog).getByRole('button', { name: '회원 영구 삭제' });
        fireEvent.click(remove); fireEvent.click(remove);
        expect(remove).toBeDisabled();
        expect(api.deleteUser).toHaveBeenCalledTimes(1);
        await act(async () => reject(new Error('삭제 실패')));
        expect(await within(dialog).findByRole('alert')).toHaveTextContent('삭제 실패');
        expect(screen.getByRole('button', { name: '관리대상' })).toBeInTheDocument();
        expect(dialog).toBeInTheDocument();
    });
    it('removes only successfully deleted duplicate accounts', async () => {
        const users = [member, { ...member, id: 8, name: '삭제성공', email: 'ok@example.test', tier: '' }, { ...member, id: 9, name: '삭제실패', email: 'fail@example.test', tier: '' }];
        api.getUsers.mockResolvedValue({ users, total: 3 });
        api.getDuplicates.mockResolvedValue({ groups: [{ reason: 'same_name', key: '중복그룹', accounts: users }], total_groups: 1 });
        api.deleteUser.mockImplementation((id: number) => id === 8 ? Promise.resolve({}) : Promise.reject(new Error('삭제 실패')));
        render(<UsersTab apiToken="admin-token" currentUserId={99} />);
        fireEvent.click(await screen.findByRole('button', { name: '중복 의심 1' }));
        fireEvent.click(screen.getByRole('button', { name: /중복 2개 일괄 삭제/ }));
        expect(await screen.findByText('삭제 1건, 실패 1건')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: '삭제성공' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: '삭제실패' })).toBeInTheDocument();
    });
    it('keeps detail status pending when activation fails', async () => {
        api.getUsers.mockResolvedValue({ users: [{ ...member, status: 'pending' }], total: 1 });
        api.fetchAuthAPI.mockResolvedValue({ ...member, status: 'pending' });
        api.setUserStatus.mockRejectedValue(new Error('승인 실패'));
        render(<UsersTab apiToken="admin-token" currentUserId={99} />);
        fireEvent.click(await screen.findByRole('button', { name: '관리대상' }));
        const dialog = await screen.findByRole('dialog', { name: '회원 상세 정보' });
        fireEvent.click(within(dialog).getByRole('button', { name: '승인' }));
        expect(await screen.findByText('승인 실패')).toBeInTheDocument();
        expect(within(dialog).getByText('대기', { selector: 'p' })).toBeInTheDocument();
    });
});

describe('Pro expiry management', () => {
    it('shows unavailable Pro data with a retry instead of an empty member result', async () => {
        api.getUsers.mockRejectedValueOnce(new Error('HTTP 503'));
        render(<ProExpiryTab apiToken="admin-token" />);
        expect(await screen.findByRole('alert')).toHaveTextContent(/회원.*불러오지 못/);
        expect(screen.queryByText('Pro 구독자가 없습니다')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
        await waitFor(() => expect(screen.getAllByText('관리대상').length).toBeGreaterThan(0));
    });
    it('routes extension into exact pending-request approval when a renewal is waiting', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        render(<ProExpiryTab apiToken="admin-token" />);
        fireEvent.click((await screen.findAllByRole('button', { name: '+30일' }))[0]);
        expect(await screen.findByRole('button', { name: /재구독.*77.*승인/ })).toBeInTheDocument();
        expect(api.extendPro).not.toHaveBeenCalled();
    });
});

describe('subscription request mutations', () => {
    it('does not allow an earlier GET to undo a successfully approved renewal', async () => {
        let finishRefresh!: (value: { requests: typeof pending[] }) => void;
        api.getSubscriptions.mockResolvedValueOnce({ requests: [pending] }).mockReturnValueOnce(new Promise(resolve => { finishRefresh = resolve; }));
        api.approveSubscription.mockResolvedValue({ request: { ...pending, status: 'approved' } });
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);
        fireEvent.click(await screen.findByRole('button', { name: /새로고침/ }));
        fireEvent.click(screen.getByRole('button', { name: /Pro 재구독 승인/ }));
        await waitFor(() => expect(screen.getByText('approved')).toBeInTheDocument());
        await act(async () => finishRefresh({ requests: [pending] }));
        expect(screen.queryByRole('button', { name: /Pro 재구독 승인/ })).not.toBeInTheDocument();
        expect(screen.getByText('approved')).toBeInTheDocument();
    });
    it('cancels rejection when the optional-reason prompt is cancelled', async () => {
        api.getSubscriptions.mockResolvedValue({ requests: [pending] });
        vi.mocked(window.prompt).mockReturnValue(null);
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);
        fireEvent.click(await screen.findByRole('button', { name: '거절' }));
        expect(api.rejectSubscription).not.toHaveBeenCalled();
        expect(screen.getByRole('button', { name: /Pro 재구독 승인/ })).toBeInTheDocument();
    });

    it('shows a combined plan renewal and approves that request by ID', async () => {
        const combined = { ...pending, request_type: 'aibain_kongming_renewal', to_tier: 'aibain_kongming', amount: '50,000원' };
        api.getSubscriptions.mockResolvedValue({ requests: [combined] });
        api.approveSubscription.mockResolvedValue({ request: { ...combined, status: 'approved' } });
        render(<SubscriptionsTab apiToken="admin-token" onCountChange={() => {}} />);

        expect(await screen.findByText('50,000원')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'AI 브레인 + 제갈공명 갱신 승인' }));
        await waitFor(() => expect(api.approveSubscription).toHaveBeenCalledWith(combined.id, 'admin-token'));
        expect(await screen.findByText('AI 브레인 + 제갈공명 갱신')).toBeInTheDocument();
    });
});
