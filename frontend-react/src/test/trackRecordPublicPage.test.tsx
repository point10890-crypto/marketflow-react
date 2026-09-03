import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TrackRecordPublicPage from '@/pages/public/TrackRecordPublicPage';

const mockApi = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('@/lib/api', () => ({ publicTrackRecordAPI: { get: mockApi.get } }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: null, loading: false }) }));

const payload = {
  schema_version: 'marketflow.public_track_record.v1',
  generated_at: '2026-09-03T00:00:00',
  as_of: '2026-09-02',
  date_range: { from: '2026-08-25', to: '2026-09-02' },
  days_count: 3,
  window_trading_days: 60,
  sample_size: 3,
  masked_count: 1,
  by_grade: { S: 1, A: 2 },
  verification: { evaluated: 1, pending: 2, closed: 1, open: 0, wins: 1, losses: 0, win_rate: 100, avg_roi_pct: 5, avg_hold_roi_pct: 6.4 },
  grade_stats: {},
  days: [],
  signals: [
    { date: '2026-09-02', grade: 'A', market: 'KOSPI', masked: true, stock_name: 'SK**', stock_code: null,
      change_pct: 3.2, score_total: 9, forward_return: null, verification: 'pending', forward: null },
    { date: '2026-08-27', grade: 'S', market: 'KOSPI', masked: false, stock_name: '씨에스윈드', stock_code: '112610',
      change_pct: 18.5, score_total: 11, forward_return: null, verification: 'pending', forward: null },
    { date: '2026-08-25', grade: 'A', market: 'KOSPI', masked: false, stock_name: '삼성전기', stock_code: '009150',
      change_pct: 9.2, score_total: 8, forward_return: 5, verification: 'closed',
      forward: { outcome: 'TARGET_HIT', outcome_date: '2026-08-28', roi_pct: 5, hold_roi_pct: 6.4, max_high_pct: 7.1, days_held: 3 } },
  ],
  methodology: { delay: '신호는 발생일 이후 거래일 1일이 지난 뒤 공개됩니다.', masking: '5일 미만 마스킹' },
  disclaimer: '성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다.',
};

function renderPage() {
  return render(<MemoryRouter initialEntries={['/track-record']}><TrackRecordPublicPage /></MemoryRouter>);
}

describe('TrackRecordPublicPage', () => {
  beforeEach(() => { mockApi.get.mockReset(); });

  it('공개 API 로 기록을 읽어 마스킹된 행과 실명 행을 함께 보여준다', async () => {
    mockApi.get.mockResolvedValue(payload);
    renderPage();
    await waitFor(() => expect(mockApi.get).toHaveBeenCalledTimes(1));
    // 표본·검증 대기 수는 항상 노출
    expect(await screen.findByText('3건')).toBeInTheDocument();
    expect(screen.getByText('검증 대기 2건')).toBeInTheDocument();
    // 마스킹 행: 이름 앞 두 글자만, 코드 없음 (데스크톱 표 + 모바일 카드 둘 다 렌더)
    expect(screen.getAllByText('SK**').length).toBeGreaterThan(0);
    expect(screen.queryByText('SK하이닉스')).not.toBeInTheDocument();
    expect(screen.getAllByText('공개 전').length).toBeGreaterThan(0);
    // 실명 행: 이름 + 코드
    expect(screen.getAllByText('씨에스윈드').length).toBeGreaterThan(0);
    expect(screen.getAllByText('112610').length).toBeGreaterThan(0);
    // 사후 결과는 추적 파일에 있을 때만
    expect(screen.getAllByText('목표 도달').length).toBeGreaterThan(0);
    expect(screen.getAllByText('검증 대기').length).toBeGreaterThanOrEqual(2);
  });

  it('면책 문구와 요금제 CTA 가 있다', async () => {
    mockApi.get.mockResolvedValue(payload);
    renderPage();
    expect(await screen.findByText(/성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다/)).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /요금제 보기/ });
    expect(cta).toHaveAttribute('href', '/pricing');
    expect(screen.getByText(/거래일 1일 지연/)).toBeInTheDocument();
  });

  it('종결 표본이 없으면 적중률 대신 "검증 대기" 를 보여준다', async () => {
    mockApi.get.mockResolvedValue({
      ...payload,
      verification: { ...payload.verification, evaluated: 0, pending: 3, closed: 0, wins: 0, win_rate: null, avg_roi_pct: null, avg_hold_roi_pct: null },
      signals: payload.signals.map((s) => ({ ...s, forward: null, forward_return: null, verification: 'pending' })),
    });
    renderPage();
    expect(await screen.findByText('종결된 표본이 아직 없습니다')).toBeInTheDocument();
    expect(screen.queryByText('100.0%')).not.toBeInTheDocument();
  });

  it('API 실패는 오류 배너로만 알리고 CTA 는 남긴다', async () => {
    mockApi.get.mockRejectedValue(new Error('down'));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('기록을 불러오지 못했습니다');
    expect(screen.getByRole('link', { name: /요금제 보기/ })).toBeInTheDocument();
  });
});
