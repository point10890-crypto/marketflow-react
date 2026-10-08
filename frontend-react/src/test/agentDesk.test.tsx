import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import AgentDesk from '@/components/aibain/AgentDesk';
import { validateAlphaLabStatus } from '@/lib/alphaLabApi';
import { validAccountInput, validateAccountPlan, validateAgentDesk } from '@/lib/agentDeskApi';
import { accountResult, deskBoard, deskContract, deskNow, deskStatus } from './agentDeskFixtures';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(deskNow); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
function fillAccount() {
    for (const [label, value] of [['총자산 (원)', '10000000'], ['주문 가능 현금 (원)', '8000000'], ['오늘 손익 (원)', '0'], ['이번 주 손익 (원)', '0']]) {
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByLabelText('현재 보유 종목이 없습니다'));
}
async function openForm() {
    api.fetchAuthAPI.mockResolvedValue(deskStatus());
    render(<AlphaLabPanel token="member" desk />); await act(async () => {});
    fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고'));
}
describe('agent desk boundary', () => {
    it('preserves older-server research when the optional contract is absent', () => {
        const value = deskStatus(); delete value.agent_desk;
        expect(validateAlphaLabStatus(value).opportunity_engine?.candidates[0].name).toBe('삼성전자');
    });
    it.each(['상승 확률 80%', 'calibrated probability 95%'])('rejects fabricated forecast claims in role details: %s', claim => {
        const desk = deskContract(); desk.roles[0].detail = claim;
        expect(() => validateAgentDesk(desk, deskBoard())).toThrow(/응답 형식/);
    });
    it('rejects a ready account plan whose deadline outlives current quote evidence', () => {
        const plan = accountResult(); plan.valid_until = '2026-10-05T06:30:00Z';
        const account = { equity: 10000000, available_cash: 8000000, daily_pnl: 0, weekly_pnl: 0, positions_confirmed: true as const, positions: [] };
        expect(() => validateAccountPlan(plan, deskBoard(), deskContract(), account)).toThrow(/응답 형식/);
    });
    it('accepts a desk deadline tightened to independent evidence expiry', () => {
        const desk = deskContract(); desk.candidates[0].invalidation.valid_until = '2026-10-05T01:01:00Z';
        expect(validateAgentDesk(desk, deskBoard()).candidates[0].invalidation.valid_until).toBe('2026-10-05T01:01:00Z');
    });
    it('rejects a passed audit with unresolved reasons', () => {
        const desk = deskContract(); desk.candidates[0].audit.reasons = ['fx_and_flow_missing'];
        expect(() => validateAgentDesk(desk, deskBoard())).toThrow(/응답 형식/);
    });
    it('rejects ready account quantity with both flow and FX missing', () => {
        const desk = deskContract(); desk.candidates[0].missing = ['flow', 'fx_liquidity'];
        const account = { equity: 10000000, available_cash: 8000000, daily_pnl: 0, weekly_pnl: 0, positions_confirmed: true as const, positions: [] };
        expect(() => validateAccountPlan(accountResult(), deskBoard(), desk, account)).toThrow(/응답 형식/);
    });
    it('downgrades passed audit and roles when independent evidence expires despite fresh prices', () => {
        const desk = deskContract(); desk.candidates[0].invalidation.valid_until = '2026-10-05T01:00:00Z';
        desk.roles.find(role => role.id === 'auditor')!.status = 'passed';
        render(<AgentDesk desk={desk} board={deskBoard()} now={deskNow} blocked={false} />);
        const region = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(within(region).getByText(/출처 감사 갱신 대기/)).toBeVisible();
        expect(within(region).queryByText(/조건부 연구 계획|출처 감사 통과/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByText('12개 역할 · 자료 검사 펼치기'));
        expect(within(region).getByText('출처 감사 · 갱신 대기')).toBeVisible();
    });
    it('expires source audit on the shared clock without another GET', async () => {
        const status = deskStatus(); status.agent_desk!.candidates[0].invalidation.valid_until = '2026-10-05T01:01:00Z';
        api.fetchAuthAPI.mockResolvedValue(status); render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        expect(screen.getByRole('region', { name: '계좌·출처 검사' })).toHaveTextContent('출처 감사 통과');
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(screen.getByRole('region', { name: '계좌·출처 검사' })).toHaveTextContent('출처 감사 갱신 대기');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('expires the global desk inspection even with newly refreshed prices', () => {
        const desk = deskContract(); desk.generated_at = '2026-10-05T00:53:00Z';
        render(<AgentDesk desk={desk} board={deskBoard()} now={deskNow} blocked={false} />);
        expect(screen.getByRole('region', { name: '계좌·출처 검사' })).toHaveTextContent('출처 감사 갱신 대기');
    });
    it.each(['missing', 'boolean', 'NaN', 'empty holdings', 'duplicate holdings'])('withholds account facts on %s inputs', kind => {
        const account: Record<string, unknown> = { equity: 10000000, available_cash: 8000000, daily_pnl: 0, weekly_pnl: 0, positions_confirmed: true, positions: [] };
        if (kind === 'missing') delete account.weekly_pnl;
        if (kind === 'boolean') account.equity = true;
        if (kind === 'NaN') account.daily_pnl = NaN;
        if (kind === 'empty holdings') account.positions_confirmed = false;
        if (kind === 'duplicate holdings') account.positions = [{ symbol: '005930', theme: '반도체', market_value: 1000 }, { symbol: '005930', theme: '반도체', market_value: 1000 }];
        expect(validAccountInput(account)).toBe(false);
    });
    it.each(['probability', 'identity', 'unknown field', 'duplicate role', 'threshold', 'future clock'])('rejects an unsafe optional contract: %s', kind => {
        const value = deskStatus(); const desk = value.agent_desk!;
        if (kind === 'probability') Object.assign(desk.candidates[0].probability, { kind: 'calibrated', bull: .8 });
        if (kind === 'identity') desk.candidates[0].opportunity_id = 'f'.repeat(64);
        if (kind === 'unknown field') Object.assign(desk.candidates[0], { forecast_profit: .5 });
        if (kind === 'duplicate role') desk.roles[1].id = desk.roles[0].id;
        if (kind === 'threshold') desk.candidates[0].invalidation.price_below = 58000;
        if (kind === 'future clock') desk.generated_at = '2026-10-06T01:00:00Z';
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
});
describe('request-only account form', () => {
    it('requires explicit balances, PnL and holdings without defaulting facts to zero', async () => {
        await openForm();
        const submit = screen.getByRole('button', { name: '계좌 한도 계산' });
        expect(submit).toBeDisabled();
        expect(screen.getByLabelText('오늘 손익 (원)')).toHaveValue(null);
        fillAccount(); expect(submit).toBeEnabled();
        fireEvent.click(screen.getByLabelText('현재 보유 종목이 없습니다')); expect(submit).toBeDisabled();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('sends only the explicit account and displayed IDs using existing auth', async () => {
        await openForm(); fillAccount(); api.postAuthAPI.mockResolvedValue(accountResult());
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(screen.getByLabelText('삼성전자 계좌 참고 수량')).toHaveTextContent('6주');
        expect(api.postAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab/account-plan', {
            account: { equity: 10000000, available_cash: 8000000, daily_pnl: 0, weekly_pnl: 0, positions_confirmed: true, positions: [] },
            opportunity_ids: ['d'.repeat(64)],
        }, 'member');
        expect(screen.getByText(/갭 하락/)).toBeVisible();
    });
    it('includes edited holdings and requires confirming the full list', async () => {
        await openForm(); fillAccount(); fireEvent.click(screen.getByLabelText('보유 종목을 입력합니다'));
        fireEvent.click(screen.getByRole('button', { name: '보유 종목 추가' }));
        fireEvent.change(screen.getByLabelText('보유 1 종목 코드'), { target: { value: '000660' } });
        fireEvent.change(screen.getByLabelText('보유 1 테마'), { target: { value: '반도체' } });
        fireEvent.change(screen.getByLabelText('보유 1 평가금액 (원)'), { target: { value: '1000000' } });
        expect(screen.getByRole('button', { name: '계좌 한도 계산' })).toBeDisabled();
        fireEvent.click(screen.getByLabelText('모든 보유 종목과 평가금액을 확인했습니다'));
        api.postAuthAPI.mockResolvedValue({ ...accountResult(), status: 'held', valid_until: null, reasons: ['theme_unavailable'], plans: [] });
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(api.postAuthAPI.mock.calls[0][1].account.positions).toEqual([{ symbol: '000660', theme: '반도체', market_value: 1000000 }]);
    });
    it.each(['edit', 'refresh', 'expiry', 'quote expiry', 'logout'])('clears visible quantities after %s', async kind => {
        api.fetchAuthAPI.mockResolvedValue(deskStatus()); api.postAuthAPI.mockResolvedValue(accountResult());
        const view = render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고')); fillAccount();
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(screen.getByLabelText('삼성전자 계좌 참고 수량')).toHaveTextContent('6주');
        if (kind === 'edit') fireEvent.change(screen.getByLabelText('총자산 (원)'), { target: { value: '9000000' } });
        if (kind === 'refresh') { api.fetchAuthAPI.mockReturnValue(new Promise(() => {})); fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' })); }
        if (kind === 'expiry') await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
        if (kind === 'quote expiry') { vi.setSystemTime(deskNow + 420000); fireEvent.focus(window); }
        if (kind === 'logout') view.rerender(<AlphaLabPanel token="" desk />);
        expect(screen.queryByLabelText('삼성전자 계좌 참고 수량')).not.toBeInTheDocument();
    });
    it.each(['edit', 'identity', 'poll failure'])('discards an in-flight response after %s', async kind => {
        let resolve!: (value: ReturnType<typeof accountResult>) => void;
        const pending = new Promise<ReturnType<typeof accountResult>>(done => { resolve = done; });
        api.fetchAuthAPI.mockResolvedValue(deskStatus()); api.postAuthAPI.mockReturnValue(pending);
        const view = render(<AlphaLabPanel token="member" />); await act(async () => {});
        fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고')); fillAccount();
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' }));
        if (kind === 'edit') fireEvent.change(screen.getByLabelText('오늘 손익 (원)'), { target: { value: '-1000' } });
        if (kind === 'identity') view.rerender(<AlphaLabPanel token="different-account" />);
        if (kind === 'poll failure') { api.fetchAuthAPI.mockRejectedValue(new Error('private failure')); await act(async () => { await vi.advanceTimersByTimeAsync(30000); }); }
        await act(async () => { resolve(accountResult()); });
        expect(screen.queryByLabelText('삼성전자 계좌 참고 수량')).not.toBeInTheDocument();
    });
    it('discards a held in-flight response when quote evidence expires', async () => {
        let resolve!: (value: ReturnType<typeof accountResult>) => void;
        api.fetchAuthAPI.mockResolvedValue(deskStatus()); api.postAuthAPI.mockReturnValue(new Promise(done => { resolve = done; }));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고')); fillAccount();
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' }));
        await act(async () => { await vi.advanceTimersByTimeAsync(390000); });
        await act(async () => { resolve({ ...accountResult(), status: 'held', valid_until: null, reasons: ['quote_stale'], plans: [] }); });
        expect(screen.queryByRole('region', { name: '계좌 한도 계산 결과' })).not.toBeInTheDocument();
    });
    it('discards an in-flight response at an earlier desk evidence deadline', async () => {
        let resolve!: (value: ReturnType<typeof accountResult>) => void;
        const status = deskStatus(); status.agent_desk!.candidates[0].invalidation.valid_until = '2026-10-05T01:01:00Z';
        api.fetchAuthAPI.mockResolvedValue(status); api.postAuthAPI.mockReturnValue(new Promise(done => { resolve = done; }));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고')); fillAccount();
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' }));
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        await act(async () => { resolve({ ...accountResult(), status: 'held', valid_until: null, reasons: ['source_stale'], plans: [] }); });
        expect(screen.queryByRole('region', { name: '계좌 한도 계산 결과' })).not.toBeInTheDocument();
    });
    it('suppresses expired or foreign server plans', async () => {
        await openForm(); fillAccount();
        const expired = accountResult(); expired.valid_until = '2026-10-05T01:00:00Z';
        api.postAuthAPI.mockResolvedValue(expired); fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(screen.queryByLabelText('삼성전자 계좌 참고 수량')).not.toBeInTheDocument();
        expect(screen.getByRole('alert')).toHaveTextContent('계좌 한도 계산을 확인하지 못했습니다');
        const foreign = accountResult(); foreign.plans[0].opportunity_id = 'f'.repeat(64);
        api.postAuthAPI.mockResolvedValue(foreign); fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(screen.queryByLabelText('삼성전자 계좌 참고 수량')).not.toBeInTheDocument();
    });
    it('keeps essential prices and invalidation visible, with native role disclosures', async () => {
        await openForm();
        const stock = screen.getByRole('article', { name: /삼성전자/ });
        expect(within(stock).getByText('참고 손절')).toBeVisible();
        expect(within(stock).getByText('무효 조건')).toBeVisible();
        const summary = screen.getByText('12개 역할 · 자료 검사 펼치기');
        expect(summary.tagName).toBe('SUMMARY');
        expect(summary.closest('details')).not.toHaveAttribute('open');
        fireEvent.click(summary); expect(summary.closest('details')).toHaveAttribute('open');
        expect(screen.getByText(/12번의 모델 호출/)).toBeVisible();
    });
    it('shows a concise Korean hold action and translates missing source codes in disclosures', async () => {
        const status = deskStatus(); const row = status.agent_desk!.candidates[0]; row.state = 'Watch'; row.audit.status = 'held'; row.audit.independent_sources = 0;
        row.audit.reasons = ['direction_independent_sources_missing', 'risk_independent_sources_missing', 'fx_and_flow_missing', 'entry_not_current', 'unknown_safe_reason'];
        row.missing = ['regime', 'flow', 'fx_liquidity', 'calibrated_probability'];
        api.fetchAuthAPI.mockResolvedValue(status); render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const desk = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(within(desk).getByText('외국인 수급·환율 자료 확인 전에는 계좌 수량을 제공하지 않습니다.')).toBeVisible();
        expect(within(desk).queryByText(/direction_independent|unknown_safe_reason|calibrated_probability/)).not.toBeInTheDocument();
        fireEvent.click(within(desk).getByText('삼성전자 출처·확률 제한'));
        expect(within(desk).getByText(/방향 판단의 독립 출처 두 계통 확인 필요/)).toBeVisible();
    });
});
