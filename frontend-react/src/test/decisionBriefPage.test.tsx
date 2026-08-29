import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DecisionBriefPage from '@/pages/dashboard/aibain/DecisionBriefPage';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));

vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, tier: 'pro', is_aibain_active: true }, token: 't' }),
}));
vi.mock('@/components/aibain/AiBrainServiceTabs', () => ({
  default: () => <nav data-testid="tabs" />,
}));

const brief = {
  schema_version: 'mirofish.decision_brief.v1',
  generated_at: '2026-08-29T05:00:00+00:00',
  symbol: '009150',
  name: '삼성전기',
  status: 'neutral',
  signals: [
    { source: 'claw', stance: 'negative', grade: 'A', as_of: '2026-08-28T15:20:00', detail: {} },
    { source: 'tradingagents', stance: 'positive', grade: 'B', as_of: '2026-08-28', detail: {} },
  ],
  agreement: {
    positive: 1, negative: 1, neutral: 0, absent: 0,
    active: 2, ratio: 0.5, verdict: 'conflicted', direction: 'split',
  },
  strong_evidence: 1,
  data_gaps: ['jongga', 'paper'],
  invalidators: [{ type: 'DROP_CONFIRMED', cond: 'S/A 이탈 3틱 연속 확정', mode: 'shadow' }],
  confidence_cap: 0.25,
  cap_reasons: ['sources conflicted'],
  regime: { phase: 'uptrend_broadening', gate_status: 'RED', conflict: true },
  errors: {},
  disclaimer: '정보 제공 목적이며 투자 권유가 아닙니다.',
};

describe('DecisionBriefPage', () => {
  beforeEach(() => {
    mockApi.fetchAuthAPI.mockReset();
  });

  it('조회 전에는 안내만 보이고 API 를 호출하지 않는다', () => {
    render(<DecisionBriefPage />);
    expect(mockApi.fetchAuthAPI).not.toHaveBeenCalled();
    expect(screen.getByText(/종목 코드를 입력하면/)).toBeInTheDocument();
  });

  it('이견이 갈리는 종목은 충돌로 표시하고 공백을 숨기지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    render(<DecisionBriefPage />);

    await userEvent.type(screen.getByLabelText('종목 코드'), '009150');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
    expect(screen.getByText('의견 충돌')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();
    // 데이터 공백을 그대로 노출
    expect(screen.getByText('종가베팅 V2')).toBeInTheDocument();
    // 무효화는 관측 전용임을 명시
    expect(screen.getByText(/자동 청산 아님/)).toBeInTheDocument();
  });

  it('매수·매도 지시 문구를 렌더하지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ ...brief, status: 'watch' });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText('관찰 대상')).toBeInTheDocument());
    expect(screen.queryByText(/매수하세요|매도하세요|BUY 추천/)).toBeNull();
  });

  it('응답이 계약과 다르면 오류 안내로 폴백한다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ unexpected: true });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText(/형식이 올바르지 않습니다/)).toBeInTheDocument());
  });

  it('조회 실패 시 재시도 안내를 보여준다', async () => {
    mockApi.fetchAuthAPI.mockRejectedValue(new Error('boom'));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '999999');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText(/조회에 실패했습니다/)).toBeInTheDocument());
  });
});

describe('DecisionBriefPage — 6계층 표시', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); });

  const withExtras = {
    ...brief,
    verification: { verified: 3, unverified: 2, contradicted: 1 },
    news: {
      count: 1,
      items: [{
        title: '삼성전기 자사주 매입 공시', link: 'https://n/1', source: 'yonhap',
        grade: 'B', score: 3.0, published_ts: '2026-08-29T09:00:00+09:00',
        corroboration: 2,
      }],
    },
  };

  it('L4 기계적 검증 결과를 배지로 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(withExtras);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '009150');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText('기계적 검증')).toBeInTheDocument());
    expect(screen.getByText(/원천과 맞지 않는 항목/)).toBeInTheDocument();
  });

  it('L1 뉴스 맥락을 방향 판정과 구분해 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(withExtras);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '009150');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText('삼성전기 자사주 매입 공시')).toBeInTheDocument());
    expect(screen.getByText(/방향 판정 아님/)).toBeInTheDocument();
    expect(screen.getByText(/2개 매체/)).toBeInTheDocument();
  });

  it('검증·뉴스가 없어도 화면이 깨지지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ ...brief, verification: null, news: { count: 0, items: [] } });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));

    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
    expect(screen.queryByText('기계적 검증')).toBeNull();
  });
});
