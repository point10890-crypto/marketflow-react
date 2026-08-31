import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DecisionBriefPage from '@/pages/dashboard/aibain/DecisionBriefPage';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));

vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI, postAuthAPI: mockApi.postAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, tier: 'pro', is_aibain_active: true }, token: 't' }),
}));
vi.mock('@/components/aibain/AiBrainServiceTabs', () => ({
  default: () => <nav data-testid="tabs" />,
}));
// 지식베이스 카드는 자체 테스트가 있고 마운트 시 자기 현황을 조회한다.
// 이 파일은 판단 조회 흐름만 검증하므로 분리한다.
vi.mock('@/pages/dashboard/aibain/RagStatusCard', () => ({
  default: () => <section data-testid="rag-status" />,
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

  it('조회 전에는 안내만 보이고 판단 API 를 호출하지 않는다', () => {
    render(<DecisionBriefPage />);
    expect(mockApi.fetchAuthAPI).not.toHaveBeenCalled();
    expect(screen.getByText(/종목 코드 또는 종목명을 입력하면/)).toBeInTheDocument();
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


describe('DecisionBriefPage — 온디맨드 심층 분석', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); mockApi.postAuthAPI.mockReset(); });

  const deep = {
    symbol: '041190', name: '우리기술투자', status: 'neutral',
    analysts: [
      { role: 'technical', title: '기술적', stance: 'bullish', score: 20,
        summary: '거래량 증가', evidence: ['20일선 상회'], method: 'llm', verification: null },
    ],
    debate: {
      rounds: [{ round: 1, bull: '수급이 붙었다', bear: '실적 근거가 약하다' }],
      manager: { stance: 'neutral', thesis: '방향성 불충분', confidence: 55 },
      method: 'llm',
    },
    risk: null, verdict: { verdict: 'HOLD', confidence: 55 },
    verification: { verified: 3, unverified: 2, contradicted: 0 },
    citations: [{ kind: 'news', text: '자사주 매입 공시', grade: 'B', source: 'yonhap', link: 'https://n/1' }],
    retrieval: { news_count: 1, graph_count: 2 }, method: 'llm', error: null,
  };

  async function search() {
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '041190');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
  }

  it('조회 후 심층 분석 버튼이 보이고, 누르기 전에는 실행되지 않는다', async () => {
    await search();
    expect(screen.getByRole('button', { name: /심층 분석 실행/ })).toBeInTheDocument();
    expect(mockApi.postAuthAPI).not.toHaveBeenCalled();
  });

  it('토론 라운드와 애널리스트 근거를 보여준다', async () => {
    await search();
    mockApi.postAuthAPI.mockResolvedValue(deep);
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));

    await waitFor(() => expect(screen.getByText('수급이 붙었다')).toBeInTheDocument());
    expect(screen.getByText('실적 근거가 약하다')).toBeInTheDocument();
    expect(screen.getByText('방향성 불충분')).toBeInTheDocument();
    expect(screen.getByText('거래량 증가')).toBeInTheDocument();
  });

  it('투입된 검색 근거를 인용으로 보여준다 (변형 RAG)', async () => {
    await search();
    mockApi.postAuthAPI.mockResolvedValue(deep);
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));

    await waitFor(() => expect(screen.getByText('자사주 매입 공시')).toBeInTheDocument());
    expect(screen.getByText(/뉴스 1 · 그래프 2/)).toBeInTheDocument();
  });

  it('분석 실패는 안내로 표시하고 화면을 깨뜨리지 않는다', async () => {
    await search();
    mockApi.postAuthAPI.mockResolvedValue({ ...deep, error: 'LLM down', analysts: [], debate: null });
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));

    await waitFor(() => expect(screen.getByText(/분석을 완료하지 못했습니다/)).toBeInTheDocument());
  });
});

describe('DecisionBriefPage — 판정 시인성', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); mockApi.postAuthAPI.mockReset(); });

  const deepBase = {
    symbol: '041190', name: '우리기술투자', status: 'neutral',
    analysts: [], debate: null, risk: null,
    verdict: { verdict: 'HOLD', confidence: 55 },
    verification: null, citations: [], retrieval: null, method: 'llm', error: null,
  };

  async function searchThenDeep(verdict: Record<string, unknown>) {
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    mockApi.postAuthAPI.mockResolvedValue({ ...deepBase, verdict });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '041190');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));
  }

  it('HOLD 판정을 한글 라벨 "중립" 으로 보여준다', async () => {
    await searchThenDeep({ verdict: 'HOLD', confidence: 55 });
    await waitFor(() => expect(screen.getByTestId('deep-call')).toHaveTextContent('중립'));
  });

  it('STRONG_BUY 는 "적극매수" 로 표시한다', async () => {
    await searchThenDeep({ verdict: 'STRONG_BUY', confidence: 82 });
    await waitFor(() => expect(screen.getByTestId('deep-call')).toHaveTextContent('적극매수'));
    expect(screen.getByTestId('deep-call')).toHaveTextContent('82');
  });

  it('STRONG_SELL 은 "적극매도" 로 표시한다', async () => {
    await searchThenDeep({ verdict: 'STRONG_SELL', confidence: 71 });
    await waitFor(() => expect(screen.getByTestId('deep-call')).toHaveTextContent('적극매도'));
  });

  it('판정 옆에 매매 지시가 아님을 명시한다', async () => {
    await searchThenDeep({ verdict: 'BUY', confidence: 70 });
    await waitFor(() => expect(screen.getByTestId('deep-call')).toHaveTextContent('매수'));
    expect(screen.getByTestId('deep-call')).toHaveTextContent(/매매 지시가 아닙니다/);
  });

  it('알 수 없는 판정 값도 화면을 깨뜨리지 않는다', async () => {
    await searchThenDeep({ verdict: 'WHO_KNOWS', confidence: null });
    await waitFor(() => expect(screen.getByTestId('deep-call')).toBeInTheDocument());
  });
});

describe('DecisionBriefPage — 근거 시인성', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); });

  async function show(patch: Record<string, unknown> = {}) {
    mockApi.fetchAuthAPI.mockResolvedValue({ ...brief, ...patch });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '009150');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
  }

  it('감산 사유를 원문 대신 한글 설명으로 바꿔 보여준다', async () => {
    await show({ cap_reasons: ['data gap: claw', 'sources conflicted'] });
    expect(screen.getByText(/주도주 전이 근거 없음/)).toBeInTheDocument();
    // 충돌 힌트 문구와 겹치지 않도록 감산 사유 칩 문구를 정확히 지정한다
    expect(screen.getByText('근거들이 서로 반대 방향')).toBeInTheDocument();
    expect(screen.queryByText('· data gap: claw')).toBeNull();
  });

  it('강한 근거 부족·미검증 수치 사유도 한글로 설명한다', async () => {
    await show({
      cap_reasons: ['strong evidence < 2 (S/A 소스 부족)', 'unverified numbers: 3 (기계적 검증 미통과 수치)'],
    });
    expect(screen.getByText(/강한 근거\(S·A 등급\) 부족/)).toBeInTheDocument();
    expect(screen.getByText(/수치 3건이 원천과 대조되지 않음/)).toBeInTheDocument();
  });

  it('모르는 사유도 알 수 없는 원문이면 그대로 보여준다', async () => {
    await show({ cap_reasons: ['something new from backend'] });
    expect(screen.getByText(/something new from backend/)).toBeInTheDocument();
  });

  it('충돌 종목은 결론 한 줄에서 방향이 갈린다고 말한다', async () => {
    await show({});
    expect(screen.getByTestId('conclusion')).toHaveTextContent(/갈립니다/);
  });

  it('근거가 모자라면 결론 한 줄에서 판단 불가를 말한다', async () => {
    await show({ status: 'avoid_data_gap', strong_evidence: 0 });
    expect(screen.getByTestId('conclusion')).toHaveTextContent(/모자랍니다/);
  });

  it('일치 종목은 결론 한 줄에서 관찰 대상임을 말한다', async () => {
    await show({
      status: 'watch', strong_evidence: 3,
      agreement: { positive: 3, negative: 0, neutral: 0, absent: 0, active: 3, ratio: 1, verdict: 'aligned', direction: 'positive' },
    });
    expect(screen.getByTestId('conclusion')).toHaveTextContent(/관찰 대상/);
  });

  it('찬반 분포를 막대로 시각화한다', async () => {
    await show({});
    const bar = screen.getByTestId('stance-bar');
    expect(bar).toHaveAttribute('aria-label', expect.stringContaining('긍정 1'));
  });
});

describe('DecisionBriefPage — 일간 캐시 표시', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); mockApi.postAuthAPI.mockReset(); });

  async function show(patch: Record<string, unknown> = {}) {
    mockApi.fetchAuthAPI.mockResolvedValue({ ...brief, ...patch });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '009150');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
  }

  it('캐시본을 보고 있으면 그 사실과 시각을 알린다', async () => {
    await show({ cached: true, cached_at: '2026-08-29T05:00:00' });
    expect(screen.getByTestId('cache-badge')).toHaveTextContent(/오늘 조회한 결과/);
    expect(screen.getByTestId('cache-badge')).toHaveTextContent('05:00');
  });

  it('새로 계산한 결과에는 캐시 배지를 붙이지 않는다', async () => {
    await show({});
    expect(screen.queryByTestId('cache-badge')).toBeNull();
  });

  it('다시 조회 버튼은 force 로 캐시를 우회한다', async () => {
    await show({ cached: true, cached_at: '2026-08-29T05:00:00' });
    mockApi.fetchAuthAPI.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /다시 조회/ }));
    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());
    expect(String(mockApi.fetchAuthAPI.mock.calls[0][0])).toContain('force=1');
  });

  it('일반 조회는 force 를 붙이지 않는다', async () => {
    await show({});
    expect(String(mockApi.fetchAuthAPI.mock.calls[0][0])).not.toContain('force');
  });

  it('캐시된 심층 분석은 배지를 달고 재분석 버튼을 제공한다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '041190');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());

    mockApi.postAuthAPI.mockResolvedValue({
      symbol: '041190', name: null, status: 'neutral', analysts: [], debate: null,
      risk: null, verdict: { verdict: 'HOLD', confidence: 55 }, verification: null,
      citations: [], retrieval: null, method: 'llm', error: null,
      cached: true, cached_at: '2026-08-29T05:10:00',
    });
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));

    await waitFor(() => expect(screen.getByTestId('deep-call')).toHaveTextContent(/오늘 분석한 결과/));
    await userEvent.click(screen.getByRole('button', { name: /다시 분석/ }));
    await waitFor(() => expect(mockApi.postAuthAPI).toHaveBeenCalledTimes(2));
    expect(mockApi.postAuthAPI.mock.calls[1][1]).toEqual({ force: true });
  });

  it('첫 심층 분석 요청은 force 없이 보낸다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '041190');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());

    mockApi.postAuthAPI.mockResolvedValue({
      symbol: '041190', name: null, status: 'neutral', analysts: [], debate: null,
      risk: null, verdict: {}, verification: null, citations: [], retrieval: null,
      method: 'llm', error: null,
    });
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));
    await waitFor(() => expect(mockApi.postAuthAPI).toHaveBeenCalled());
    expect(mockApi.postAuthAPI.mock.calls[0][1]).toEqual({});
  });
});

describe('DecisionBriefPage — 종목명·초성 검색', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); mockApi.postAuthAPI.mockReset(); });

  const suggest = (candidates: unknown[]) => ({ query: 'q', candidates });

  it('모바일에서 한글을 칠 수 있도록 숫자 전용 키패드를 강제하지 않는다', () => {
    render(<DecisionBriefPage />);
    const input = screen.getByLabelText('종목 코드');
    expect(input).not.toHaveAttribute('inputMode', 'numeric');
  });

  it('입력하면 후보를 조회해 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(suggest([
      { symbol: '005930', name: '삼성전자', confidence: 0.85, reason: 'chosung_exact' },
      { symbol: '263810', name: '상신전자', confidence: 0.85, reason: 'chosung_exact' },
    ]));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), 'ㅅㅅㅈㅈ');

    await waitFor(() => expect(screen.getByRole('option', { name: /삼성전자/ })).toBeInTheDocument());
    expect(screen.getByRole('option', { name: /상신전자/ })).toBeInTheDocument();
    expect(String(mockApi.fetchAuthAPI.mock.calls[0][0])).toContain('/decision/search');
  });

  it('후보를 고르면 그 종목 코드로 판단을 조회한다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValueOnce(suggest([
      { symbol: '000660', name: 'SK하이닉스', confidence: 0.95, reason: 'exact_alias' },
    ]));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '하닉');
    await waitFor(() => expect(screen.getByRole('option', { name: /SK하이닉스/ })).toBeInTheDocument());

    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    await userEvent.click(screen.getByRole('option', { name: /SK하이닉스/ }));

    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
    const lookupCall = mockApi.fetchAuthAPI.mock.calls.find(
      (c) => !String(c[0]).includes('/search'));
    expect(String(lookupCall?.[0])).toContain('000660');
  });

  it('후보 검색이 실패해도 직접 입력한 값으로 조회할 수 있다', async () => {
    // 호출 순서가 아니라 경로로 갈라야 디바운스 타이밍에 흔들리지 않는다
    mockApi.fetchAuthAPI.mockImplementation((path: string) =>
      String(path).includes('/search')
        ? Promise.reject(new Error('search down'))
        : Promise.resolve(brief));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('후보가 없으면 목록을 띄우지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(suggest([]));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), 'zzz');
    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('한 글자로는 후보를 조회하지 않는다', async () => {
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), 'ㅅ');
    expect(mockApi.fetchAuthAPI).not.toHaveBeenCalled();
  });

  it('후보 목록에 매칭 근거를 함께 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(suggest([
      { symbol: '005930', name: '삼성전자', confidence: 0.85, reason: 'chosung_exact' },
    ]));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), 'ㅅㅅㅈㅈ');
    await waitFor(() => expect(screen.getByRole('option', { name: /초성/ })).toBeInTheDocument());
  });
});

describe('DecisionBriefPage — 첫 조회 대기', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); });

  it('첫 조회는 오래 걸릴 수 있으므로 넉넉한 타임아웃을 준다', async () => {
    // 프로덕션 실측: 캐시 미적중 조회가 6~45초로 흔들린다(백그라운드 워커 경합).
    // 30초 타임아웃이면 첫 조회가 그대로 실패한다.
    mockApi.fetchAuthAPI.mockResolvedValue(brief);
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());

    const call = mockApi.fetchAuthAPI.mock.calls.find((c) => !String(c[0]).includes('/search'));
    expect(Number(call?.[2])).toBeGreaterThanOrEqual(60000);
  });

  it('조회 중에는 첫 조회가 오래 걸릴 수 있음을 알린다', async () => {
    mockApi.fetchAuthAPI.mockReturnValue(new Promise(() => { /* 계속 대기 */ }));
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '005930');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText(/처음 조회하는 종목은/)).toBeInTheDocument());
  });
});


describe('DecisionBriefPage - job+poll 심층 분석', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); mockApi.postAuthAPI.mockReset(); });

  const deepDone = {
    symbol: '041190', name: '우리기술투자', status: 'neutral',
    analysts: [
      { role: 'technical', title: '기술적', stance: 'bullish', score: 20,
        summary: '거래량 증가', evidence: ['20일선 상회'], method: 'llm', verification: null },
    ],
    debate: { rounds: [{ round: 1, bull: '수급이 붙었다', bear: '실적 근거가 약하다' }],
              manager: { stance: 'neutral', thesis: '방향성 불충분', confidence: 55 }, method: 'llm' },
    risk: null, verdict: { verdict: 'HOLD', confidence: 55 }, verification: null,
    citations: [], retrieval: null, method: 'llm', error: null,
  };

  async function searchFirst() {
    mockApi.fetchAuthAPI.mockImplementation((path: string) => {
      if (path.includes('/analyze/status')) return Promise.resolve({ state: 'done', payload: deepDone });
      return Promise.resolve(brief);
    });
    render(<DecisionBriefPage />);
    await userEvent.type(screen.getByLabelText('종목 코드'), '041190');
    await userEvent.click(screen.getByRole('button', { name: /판단 조회/ }));
    await waitFor(() => expect(screen.getByText('삼성전기')).toBeInTheDocument());
  }

  it('202 잡 시작이면 상태를 폴링해 완료 결과를 렌더한다', async () => {
    await searchFirst();
    mockApi.postAuthAPI.mockResolvedValue({ state: 'running', job: { state: 'running' } });
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));
    await waitFor(() => expect(screen.getByText('수급이 붙었다')).toBeInTheDocument());
    expect(mockApi.fetchAuthAPI).toHaveBeenCalledWith(
      expect.stringContaining('/analyze/status'), expect.anything(), expect.anything());
  });

  it('일일 한도 초과는 사람이 읽는 안내로 보여준다', async () => {
    await searchFirst();
    mockApi.postAuthAPI.mockRejectedValue(new Error('quota_exceeded'));
    await userEvent.click(screen.getByRole('button', { name: /심층 분석 실행/ }));
    await waitFor(() => expect(screen.getByText(/일일 한도/)).toBeInTheDocument());
  });
});
