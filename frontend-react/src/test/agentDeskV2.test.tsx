import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AgentDesk from '@/components/aibain/AgentDesk';
import { validateAccountPlan, validateAgentDesk } from '@/lib/agentDeskApi';
import { accountResult, deskBoard, deskContract, deskNow } from './agentDeskFixtures';

const api = vi.hoisted(() => ({ postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(deskNow); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

function v2Desk() {
    return Object.assign(deskContract(), { contract: {
        schema_version: 1 as const, policy_version: 'desk-evidence-v2' as const, policy_hash: 'e'.repeat(64),
        decision_id: 'a'.repeat(64) as string | null, evidence_snapshot_id: 'f'.repeat(64) as string | null,
        evidence_status: 'ready' as 'ready' | 'missing' | 'held',
        market_checks: [{ symbol: '005930', opportunity_id: 'd'.repeat(64), status: 'passed' as 'passed' | 'held',
            reasons: [] as string[], valid_until: '2026-10-05T01:01:00Z' as string | null }],
    } });
}
const account = { equity: 10000000, available_cash: 8000000, daily_pnl: 0, weekly_pnl: 0,
    positions_confirmed: true as const, positions: [] };

describe('optional desk v2 boundary', () => {
    it('accepts decision-bound market checks without changing legacy promotion or forecast', () => {
        const value = validateAgentDesk(v2Desk(), deskBoard(), deskNow);
        expect(value).toHaveProperty('contract.evidence_status', 'ready');
        expect(value.promotion.stage).toBe('M0');
        expect(value.order_allowed).toBe(false);
        expect(value.candidates[0].probability.bull).toBeNull();
    });
    it('continues to accept the exact legacy contract', () => {
        const value = validateAgentDesk(deskContract(), deskBoard(), deskNow);
        expect(value).not.toHaveProperty('contract');
    });
    it.each(['null', 'extra field', 'bad version', 'bad hash', 'foreign decision', 'missing decision',
        'bad snapshot', 'missing ready snapshot', 'bad status', 'missing check', 'duplicate check', 'foreign symbol', 'foreign opportunity',
        'check extra field', 'passed with reasons', 'passed without deadline', 'deadline exceeds board',
        'naive deadline', 'too many reasons'])('rejects unsafe v2 data: %s', kind => {
        const desk = v2Desk(); const contract = desk.contract; const check = contract.market_checks[0];
        if (kind === 'null') Object.assign(desk, { contract: null });
        if (kind === 'extra field') Object.assign(contract, { source_url: 'https://example.test' });
        if (kind === 'bad version') Object.assign(contract, { policy_version: 'other-policy' });
        if (kind === 'bad hash') contract.policy_hash = 'unverified';
        if (kind === 'foreign decision') contract.decision_id = '0'.repeat(64);
        if (kind === 'missing decision') contract.decision_id = null;
        if (kind === 'bad snapshot') contract.evidence_snapshot_id = 'unknown';
        if (kind === 'missing ready snapshot') contract.evidence_snapshot_id = null;
        if (kind === 'bad status') Object.assign(contract, { evidence_status: 'approved' });
        if (kind === 'missing check') contract.market_checks = [];
        if (kind === 'duplicate check') contract.market_checks.push({ ...check });
        if (kind === 'foreign symbol') check.symbol = '000660';
        if (kind === 'foreign opportunity') check.opportunity_id = '0'.repeat(64);
        if (kind === 'check extra field') Object.assign(check, { order_allowed: true });
        if (kind === 'passed with reasons') check.reasons = ['market_vi_active'];
        if (kind === 'passed without deadline') check.valid_until = null;
        if (kind === 'deadline exceeds board') check.valid_until = '2026-10-05T06:30:01Z';
        if (kind === 'naive deadline') check.valid_until = '2026-10-05T01:01:00';
        if (kind === 'too many reasons') { check.status = 'held'; check.reasons = Array(101).fill('market_state_missing'); }
        expect(() => validateAgentDesk(desk, deskBoard(), deskNow)).toThrow(/응답 형식/);
    });
    it('rejects market checks reordered against their displayed candidates', () => {
        const board = deskBoard(); const desk = v2Desk();
        board.candidates.push({ ...board.candidates[0], rank: 2, symbol: '000660', name: 'SK하이닉스', opportunity_id: '0'.repeat(64) });
        desk.candidates.push({ ...desk.candidates[0], symbol: '000660', name: 'SK하이닉스', opportunity_id: '0'.repeat(64) });
        desk.contract.market_checks.push({ ...desk.contract.market_checks[0], symbol: '000660', opportunity_id: '0'.repeat(64) });
        expect(() => validateAgentDesk(desk, board, deskNow)).not.toThrow();
        desk.contract.market_checks.reverse();
        expect(() => validateAgentDesk(desk, board, deskNow)).toThrow(/응답 형식/);
    });
    it('allows a missing evidence receipt for an empty desk without a board', () => {
        const desk = v2Desk(); desk.candidates = []; desk.contract.market_checks = [];
        desk.contract.decision_id = null; desk.contract.evidence_snapshot_id = null; desk.contract.evidence_status = 'missing';
        expect(() => validateAgentDesk(desk, undefined, deskNow)).not.toThrow();
    });
});

describe('v2 account allocation guard', () => {
    it('rejects ready quantity when the legacy desk has no saved evidence contract', () => {
        expect(() => validateAccountPlan(accountResult(), deskBoard(), deskContract(), account, deskNow)).toThrow(/응답 형식/);
    });
    it('accepts a held response without quantities when the legacy desk has no saved evidence contract', () => {
        const plan = accountResult(); plan.status = 'held'; plan.valid_until = null; plan.reasons = ['desk_evidence_missing'];
        Object.assign(plan.plans[0], { status: 'held', reasons: ['desk_evidence_missing'], quantity: null, weight: 0, budget: 0, planned_loss: 0 });
        expect(validateAccountPlan(plan, deskBoard(), deskContract(), account, deskNow).plans[0].quantity).toBeNull();
    });
    it.each(['missing evidence', 'held evidence', 'held market', 'expired market', 'overlong plan'])('rejects ready quantity with %s', kind => {
        const desk = v2Desk(); const plan = accountResult();
        plan.valid_until = '2026-10-05T01:01:00Z';
        if (kind === 'missing evidence') desk.contract.evidence_status = 'missing';
        if (kind === 'held evidence') desk.contract.evidence_status = 'held';
        if (kind === 'held market') { desk.contract.market_checks[0].status = 'held'; desk.contract.market_checks[0].reasons = ['market_vi_active']; }
        if (kind === 'expired market') desk.contract.market_checks[0].valid_until = '2026-10-05T01:00:00Z';
        if (kind === 'overlong plan') plan.valid_until = '2026-10-05T01:02:00Z';
        expect(() => validateAccountPlan(plan, deskBoard(), desk, account, deskNow)).toThrow(/응답 형식/);
    });
    it('accepts a reference allocation only until its passed market guard deadline', () => {
        const plan = accountResult(); plan.valid_until = '2026-10-05T01:01:00Z';
        expect(validateAccountPlan(plan, deskBoard(), v2Desk(), account, deskNow).plans[0].quantity).toBe(6);
    });
});

describe('v2 market guard display', () => {
    it('shows a server policy receipt and distinct source and market checks', () => {
        render(<AgentDesk desk={v2Desk()} board={deskBoard()} now={deskNow} blocked={false} />);
        const region = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(within(region).getByText(/desk-evidence-v2/)).toBeVisible();
        expect(within(region).getByText(/eeeeeeeeeeee/)).toBeVisible();
        expect(region).toHaveTextContent('근거 묶음 저장됨');
        expect(region).toHaveTextContent('출처 감사 통과');
        expect(region).toHaveTextContent('현재 시장 가드 통과');
        expect(region).not.toHaveTextContent(/해시 검증 완료|원본 URL/);
    });
    it('expires only the market guard while a fresh source audit remains distinct', () => {
        render(<AgentDesk desk={v2Desk()} board={deskBoard()} now={deskNow + 60000} blocked={false} />);
        const region = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(region).toHaveTextContent('출처 감사 통과');
        expect(region).toHaveTextContent('현재 시장 가드 갱신 대기');
        expect(region).not.toHaveTextContent('현재 시장 가드 통과');
    });
    it.each([['missing', '근거 묶음 없음'], ['held', '근거 묶음 확인 보류']] as const)('shows %s evidence without hiding source audit', (state, label) => {
        const desk = v2Desk(); desk.contract.evidence_status = state;
        render(<AgentDesk desk={desk} board={deskBoard()} now={deskNow} blocked={false} />);
        expect(screen.getByRole('region', { name: '계좌·출처 검사' })).toHaveTextContent(label);
    });
    it('translates market and semantic holds without exposing raw reason codes', () => {
        const desk = v2Desk(); const check = desk.contract.market_checks[0];
        check.status = 'held'; check.valid_until = null; check.reasons = ['market_vi_active', 'market_sidecar_cooldown', 'evidence_direction_conflict'];
        render(<AgentDesk desk={desk} board={deskBoard()} now={deskNow} blocked={false} />);
        const region = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(region).toHaveTextContent('변동성 완화장치 발동');
        expect(region).toHaveTextContent('사이드카 해제 후 대기');
        expect(region).toHaveTextContent('같은 판단 근거의 방향 충돌');
        expect(region).not.toHaveTextContent(/market_vi_active|market_sidecar_cooldown|evidence_direction_conflict/);
    });
    it('explains backend evidence, policy and entry-window holds in Korean', () => {
        const desk = v2Desk(); const check = desk.contract.market_checks[0];
        check.status = 'held'; check.valid_until = null;
        check.reasons = ['desk_evidence_missing', 'desk_evidence_integrity', 'desk_policy_changed', 'directional_semantics_missing',
            'flow_required_for_plan', 'disclosure_required_for_plan', 'desk_market_guard_invalid', 'market_entry_window_expired', 'market_vi_release_after_capture'];
        render(<AgentDesk desk={desk} board={deskBoard()} now={deskNow} blocked={false} />);
        const region = screen.getByRole('region', { name: '계좌·출처 검사' });
        expect(region).toHaveTextContent('저장 근거 묶음 없음');
        expect(region).toHaveTextContent('저장 근거 묶음 무결성 확인 필요');
        expect(region).toHaveTextContent('저장 정책 식별자 변경');
        expect(region).toHaveTextContent('외국인 수급 확인 후 계좌 계획 계산');
        expect(region).toHaveTextContent('공시 자료 확인 후 계좌 계획 계산');
        expect(region).toHaveTextContent('현재 시장 가드 형식 확인 필요');
        expect(region).toHaveTextContent('신규 진입 유효기간 종료');
        expect(region).toHaveTextContent('변동성 완화장치 해제 시각 확인 필요');
        expect(region).not.toHaveTextContent(/desk_evidence|desk_policy|directional_semantics|market_entry_window/);
    });
    it('removes accepted account quantities at the earlier market guard deadline', async () => {
        const plan = accountResult(); plan.valid_until = '2026-10-05T01:01:00Z'; api.postAuthAPI.mockResolvedValue(plan);
        const view = render(<AgentDesk desk={v2Desk()} board={deskBoard()} now={deskNow} blocked={false} token="member" />);
        fireEvent.click(screen.getByText('계좌 한도 계산 · 연구 참고'));
        for (const [label, value] of [['총자산 (원)', '10000000'], ['주문 가능 현금 (원)', '8000000'], ['오늘 손익 (원)', '0'], ['이번 주 손익 (원)', '0']]) {
            fireEvent.change(screen.getByLabelText(label), { target: { value } });
        }
        fireEvent.click(screen.getByLabelText('현재 보유 종목이 없습니다'));
        fireEvent.click(screen.getByRole('button', { name: '계좌 한도 계산' })); await act(async () => {});
        expect(screen.getByLabelText('삼성전자 계좌 참고 수량')).toHaveTextContent('6주');
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        view.rerender(<AgentDesk desk={v2Desk()} board={deskBoard()} now={deskNow + 60000} blocked={false} token="member" />);
        expect(screen.queryByLabelText('삼성전자 계좌 참고 수량')).not.toBeInTheDocument();
    });
});
