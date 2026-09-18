import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import JobsTab, { ageTone, formatRelative, type SchedulerStatus } from '@/pages/admin/tabs/JobsTab';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));

vi.mock('@/lib/api', () => ({
  fetchAuthAPI: mockApi.fetchAuthAPI,
  postAuthAPI: mockApi.postAuthAPI,
}));

const baseStatus: SchedulerStatus = {
  running: true,
  kst_now: '2026-09-03 15:00:00 KST',
  daemon: {
    alive: true,
    stale_seconds: 12.3,
    pending_triggers: 0,
    jobs: [
      {
        key: 'kr_jongga', label: '종가베팅 V2', schedule: '평일 14:50', market: 'KR',
        last_run: '2026-09-03T14:52:00', age_minutes: 8, queued: false, running: false, last_trigger: null,
      },
      {
        key: 'us_market', label: 'US 마켓 전체 갱신', schedule: '평일 04:00', market: 'US',
        last_run: '2026-09-01T04:00:00', age_minutes: 60 * 59, queued: false, running: false,
        last_trigger: { id: 'abc', ok: false, error: 'timeout', started_at: '2026-09-02T10:00:00', finished_at: '2026-09-02T10:03:00' },
      },
      {
        key: 'crypto', label: 'Crypto 파이프라인', schedule: '매 4시간', market: 'Crypto',
        last_run: null, age_minutes: null, queued: false, running: false, last_trigger: null,
      },
    ],
    trigger_results: [
      { id: 'abc', job_key: 'us_market', started_at: '2026-09-02T10:00:00', finished_at: '2026-09-02T10:03:00', ok: false, error: 'timeout', requested_by: 'ops@test' },
    ],
  },
};

describe('JobsTab helpers', () => {
  it('경과 색상: <24h 녹색, <48h 황색, 그 외/없음 적색', () => {
    expect(ageTone(30)).toBe('green');
    expect(ageTone(24 * 60 - 1)).toBe('green');
    expect(ageTone(30 * 60)).toBe('amber');
    expect(ageTone(48 * 60)).toBe('red');
    expect(ageTone(null)).toBe('red');
  });

  it('상대 시각 표기', () => {
    expect(formatRelative(null)).toBe('기록 없음');
    expect(formatRelative(0.4)).toBe('방금');
    expect(formatRelative(8)).toBe('8분 전');
    expect(formatRelative(125)).toBe('2시간 전');
    expect(formatRelative(3 * 24 * 60)).toBe('3일 전');
  });
});

describe('JobsTab', () => {
  beforeEach(() => {
    mockApi.fetchAuthAPI.mockReset();
    mockApi.postAuthAPI.mockReset();
  });

  it('데몬 alive 배지 + 마켓별 잡 행 + 마지막 실행/수동 결과를 그린다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(baseStatus);
    render(<JobsTab token="t" />);

    await waitFor(() => expect(screen.getByText('ALIVE')).toBeInTheDocument());
    expect(mockApi.fetchAuthAPI).toHaveBeenCalledWith('/api/scheduler/status', 't');
    expect(screen.getByText('12s')).toBeInTheDocument();
    expect(screen.getByText('종가베팅 V2')).toBeInTheDocument();
    expect(screen.getByText('8분 전')).toBeInTheDocument();
    expect(screen.getByText('기록 없음')).toBeInTheDocument();
    expect(screen.getByText(/🇰🇷 KR/)).toBeInTheDocument();
    expect(screen.getByText(/🪙 Crypto/)).toBeInTheDocument();
    // 마지막 수동 실행 실패 → 실패 배지 (테이블) + 결과 목록
    expect(screen.getByText(/실패 10:03/)).toBeInTheDocument();
    expect(screen.getByText('ops@test')).toBeInTheDocument();
  });

  it('데몬이 죽어 있으면 DEAD 배지와 안내를 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({
      ...baseStatus,
      daemon: { alive: false, stale_seconds: null, jobs: [], trigger_results: [] },
    });
    render(<JobsTab token="t" />);
    await waitFor(() => expect(screen.getByText('DEAD')).toBeInTheDocument());
    expect(screen.getByText(/데몬 미응답/)).toBeInTheDocument();
    expect(screen.getByText(/잡 목록이 없습니다/)).toBeInTheDocument();
  });

  it('재실행 클릭 → POST trigger → 대기중 표시 → 서버가 완료를 반영하면 성공 배지', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(baseStatus);
    mockApi.postAuthAPI.mockResolvedValue({ status: 'queued', id: 'req1', job_key: 'kr_jongga' });
    render(<JobsTab token="t" />);
    await waitFor(() => expect(screen.getByText('종가베팅 V2')).toBeInTheDocument());

    // 완료 후 status 응답 (재실행 결과 반영)
    const finished: SchedulerStatus = {
      ...baseStatus,
      daemon: {
        ...baseStatus.daemon!,
        jobs: baseStatus.daemon!.jobs!.map(j => j.key === 'kr_jongga'
          ? { ...j, age_minutes: 0.2, last_trigger: { id: 'req1', ok: true, error: null, started_at: '2026-09-03T15:00:10', finished_at: '2026-09-03T15:01:00' } }
          : j),
        trigger_results: [
          { id: 'req1', job_key: 'kr_jongga', started_at: '2026-09-03T15:00:10', finished_at: '2026-09-03T15:01:00', ok: true, error: null },
          ...baseStatus.daemon!.trigger_results!,
        ],
      },
    };
    // 트리거 직후의 reload 는 아직 큐만 반영(변화 없음) → 그 다음 폴링에서 완료
    mockApi.fetchAuthAPI.mockResolvedValueOnce(baseStatus).mockResolvedValue(finished);

    const button = screen.getByRole('button', { name: '종가베팅 V2 재실행' });
    await userEvent.click(button);

    await waitFor(() => expect(mockApi.postAuthAPI).toHaveBeenCalledWith('/api/scheduler/trigger/kr_jongga', undefined, 't'));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('req1'));
    const row = screen.getByText('종가베팅 V2').closest('tr')!;
    expect(within(row).getByText('대기중')).toBeInTheDocument();
    expect(within(row).getByRole('button')).toBeDisabled();

    // 수동 새로고침 → 완료 상태 반영
    await userEvent.click(screen.getByRole('button', { name: '잡 상태 새로고침' }));
    await waitFor(() => expect(within(screen.getByText('종가베팅 V2').closest('tr')!).getByText(/성공 15:01/)).toBeInTheDocument());
    expect(within(screen.getByText('종가베팅 V2').closest('tr')!).getByRole('button')).toBeEnabled();
  });

  it('상태 조회 실패 시 에러를 보여주되 마지막 정상 상태를 지우지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValueOnce(baseStatus).mockRejectedValueOnce(new Error('backend restarting'));
    render(<JobsTab token="t" />);
    await waitFor(() => expect(screen.getByText('ALIVE')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: '잡 상태 새로고침' }));
    await waitFor(() => expect(screen.getByText('backend restarting')).toBeInTheDocument());
    expect(screen.getByText('종가베팅 V2')).toBeInTheDocument();
  });
});
