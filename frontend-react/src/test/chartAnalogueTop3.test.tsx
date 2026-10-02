import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnalogueTop3Panel from '@/components/aibain/ChartAnalogueTop3Panel';
import { fetchChartAnalogueTop3, startChartAnalogueTop3 } from '@/lib/chartAnalogueApi';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);

const none = { state: 'none', processed: 0, total: 0, started_at: null, error: null, freshness: 'missing', report: null };
const report = {
    schema_version: 1, rule_version: 'chart-top3-risk20-v1', mode: 'research', status: 'ready',
    as_of: '2026-10-02T08:00:00Z', generated_at: '2026-10-02T08:01:00Z',
    source: { name: 'closed_daily', source_id: 'naver_closed_daily', price_basis: 'provider_adjusted',
        latest_session: '2026-10-02', captured_at: '2026-10-02T07:00:00Z', built_at: '2026-10-02T07:10:00Z' },
    universe: { indexed: 100, processed: 100, eligible: 8, rejected: { insufficient_samples: 92 } },
    criteria: { horizon_sessions: 20, min_samples: 20, min_up_frequency_pct: 60, min_p10_return_pct: -12,
        min_median_similarity: 0.8, min_distinct_symbols: 5, cost_bps: 33, downside_weight: 0.5 },
    candidates: [
        { rank: 1, symbol: '003690', target: '코리안리', market: 'KR', score: 3.67, sample_count: 30,
            distinct_symbols: 8, median_similarity: 0.9, latest_session: '2026-10-02', query_captured_at: '2026-10-02T07:00:00Z', close: 10000,
            horizon: { sessions: 20, median_return_pct: 6, p10_return_pct: -4, p90_return_pct: 15, up_frequency_pct: 70 }, reasons: ['eligible'] },
        { rank: 2, symbol: '005930', target: '삼성전자', market: 'KR', score: 2.67, sample_count: 25,
            distinct_symbols: 7, median_similarity: 0.85, latest_session: '2026-10-02', query_captured_at: '2026-10-02T07:00:00Z', close: 60000,
            horizon: { sessions: 20, median_return_pct: 5, p10_return_pct: -4, p90_return_pct: 13, up_frequency_pct: 65 }, reasons: ['eligible'] },
        { rank: 3, symbol: '000660', target: 'SK하이닉스', market: 'KR', score: 1.67, sample_count: 20,
            distinct_symbols: 5, median_similarity: 0.8, latest_session: '2026-10-02', query_captured_at: '2026-10-02T07:00:00Z', close: 150000,
            horizon: { sessions: 20, median_return_pct: 4, p10_return_pct: -4, p90_return_pct: 10, up_frequency_pct: 60 }, reasons: ['eligible'] },
    ], warnings: ['research_only'],
};
const done = { ...none, state: 'done', processed: 100, total: 100, freshness: 'current', report };
const running = { ...none, state: 'running', processed: 1, total: 100, started_at: '2026-10-02T08:00:00Z' };

describe('automatic chart analogue TOP3', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
    afterEach(() => { vi.useRealTimers(); });

    it('reads saved candidates without automatically starting another scan', async () => {
        api.fetchAuthAPI.mockResolvedValue(done);
        render(<ChartAnalogueTop3Panel token="member-token" />);
        const cards = await screen.findAllByRole('article', { name: /자동 TOP3/ });
        expect(cards).toHaveLength(3);
        expect(cards[0]).toHaveTextContent('코리안리');
        expect(cards[0]).toHaveTextContent('3.67');
        expect(cards[0]).toHaveTextContent('70.0%');
        expect(cards[0]).toHaveTextContent('30개');
        expect(cards[0]).toHaveTextContent('8종목');
        expect(cards[0]).toHaveTextContent('자료 수집 2026-10-02 07:00:00 UTC');
        expect(screen.getByText(/자료 closed_daily/)).toHaveTextContent('공급자 수정주가');
        expect(within(cards[0]).getByRole('link', { name: /상세 차트/ })).toHaveAttribute('href', '/dashboard/ai-bain/chart-predict?code=003690');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/top3', 'member-token');
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('shows an empty saved state without invented candidates', async () => {
        api.fetchAuthAPI.mockResolvedValue(none);
        render(<ChartAnalogueTop3Panel token="member-token" />);
        expect(await screen.findByText('저장된 자동 TOP3 결과가 없습니다')).toBeInTheDocument();
        expect(screen.queryByRole('article')).toBeNull();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('starts only on button action and polls running progress every four seconds', async () => {
        vi.useFakeTimers();
        api.fetchAuthAPI.mockResolvedValueOnce(none).mockResolvedValueOnce({ ...running, processed: 50 }).mockResolvedValueOnce(done);
        api.postAuthAPI.mockResolvedValue(running);
        const view = render(<ChartAnalogueTop3Panel token="member-token" />);
        await act(async () => {});
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: '자동 TOP3 검출' })); });
        expect(api.postAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/top3', {}, 'member-token');
        expect(screen.getByRole('button', { name: '자동 TOP3 검출' })).toBeDisabled();
        expect(screen.getByRole('status')).toHaveTextContent('1 / 100');
        await act(async () => { await vi.advanceTimersByTimeAsync(3999); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(1); });
        expect(screen.getByRole('status')).toHaveTextContent('50 / 100');
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(screen.getAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(3);
        view.unmount();
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(3);
    });

    it('cancels the pending polling timer when the panel is removed', async () => {
        vi.useFakeTimers();
        api.fetchAuthAPI.mockResolvedValue(running);
        const view = render(<ChartAnalogueTop3Panel token="member-token" />);
        await act(async () => {});
        expect(screen.getByRole('status')).toHaveTextContent('1 / 100');
        view.unmount();
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });

    it('keeps the previous candidates visible while a new scan is running', async () => {
        api.fetchAuthAPI.mockResolvedValue(done);
        api.postAuthAPI.mockResolvedValue({ ...running, freshness: 'outdated' });
        render(<ChartAnalogueTop3Panel token="member-token" />);
        await screen.findAllByRole('article', { name: /자동 TOP3/ });
        await userEvent.click(screen.getByRole('button', { name: '자동 TOP3 검출' }));
        expect(screen.getAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(3);
        expect(screen.getByText(/이전 결과/)).toBeInTheDocument();
    });

    it('marks outdated saved data visibly instead of treating it as current', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...done, freshness: 'outdated' });
        render(<ChartAnalogueTop3Panel token="member-token" />);
        expect(await screen.findByText(/저장된 결과가 최신 가격 색인과 다릅니다/)).toBeInTheDocument();
        expect(screen.getAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(3);
    });

    it('shows only actual partial candidates without padding TOP3', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...done, report: { ...report, status: 'insufficient_candidates', candidates: report.candidates.slice(0, 1) } });
        render(<ChartAnalogueTop3Panel token="member-token" />);
        expect(await screen.findByText(/기준을 충족한 후보가 1개뿐입니다/)).toBeInTheDocument();
        expect(screen.getAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(1);
        expect(screen.queryByText('삼성전자')).toBeNull();
    });

    it.each(['missing_index', 'invalid_index', 'stale_data', 'failed'])('shows %s without fictional cards or server errors', async status => {
        api.fetchAuthAPI.mockResolvedValue({ ...done, state: 'error', error: 'private/path exception', report: { ...report, status, candidates: [] } });
        render(<ChartAnalogueTop3Panel token="member-token" />);
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(screen.queryByRole('article')).toBeNull();
        expect(screen.queryByText(/private\/path/)).toBeNull();
    });

    it('allows retry through the scan button after a request failure', async () => {
        api.fetchAuthAPI.mockRejectedValueOnce(new Error('internal exception'));
        api.postAuthAPI.mockResolvedValue(done);
        render(<ChartAnalogueTop3Panel token="member-token" />);
        expect(await screen.findByRole('alert')).toHaveTextContent('불러오지 못했습니다');
        expect(screen.queryByText(/internal exception/)).toBeNull();
        await userEvent.click(screen.getByRole('button', { name: '자동 TOP3 검출' }));
        expect(await screen.findAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(3);
    });

    it('ignores the previous authentication request after its token changes', async () => {
        let resolveOld!: (value: typeof none) => void;
        api.fetchAuthAPI.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; })).mockResolvedValueOnce(done);
        const view = render(<ChartAnalogueTop3Panel token="old" />);
        view.rerender(<ChartAnalogueTop3Panel token="new" />);
        await screen.findAllByRole('article', { name: /자동 TOP3/ });
        await act(async () => { resolveOld(none); });
        expect(screen.getAllByRole('article', { name: /자동 TOP3/ })).toHaveLength(3);
    });
});

describe('TOP3 API contract', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });

    it('allows source collection summaries and unrelated provider metadata', async () => {
        const response = { ...done, report: { ...report, source: { ...report.source,
            collection_summary: { refreshed: 2900, cache_preserved: 0 }, origin: { provider: 'naver' } } } };
        api.fetchAuthAPI.mockResolvedValue(response);
        await expect(fetchChartAnalogueTop3('member-token')).resolves.toEqual(response);
    });

    it.each([
        { ...done, processed: NaN },
        { ...done, total: -1 },
        { ...done, freshness: 'fresh' },
        { ...done, report: { ...report, candidates: report.candidates.slice(0, 2) } },
        { ...done, report: { ...report, candidates: [report.candidates[0], report.candidates[0], report.candidates[2]] } },
        { ...done, report: { ...report, candidates: [{ ...report.candidates[0], score: 999 }, ...report.candidates.slice(1)] } },
        { ...done, report: { ...report, candidates: [{ ...report.candidates[0], close: Infinity }, ...report.candidates.slice(1)] } },
        { ...done, report: { ...report, candidates: [{ ...report.candidates[0], symbol: 'BAD' }, ...report.candidates.slice(1)] } },
        { ...done, report: { ...report, criteria: { ...report.criteria, min_samples: 5 } } },
        { ...done, report: { ...report, generated_at: '2026-10-02 08:01:00' } },
        { ...done, report: { ...report, source: { ...report.source, collection_summary: { refreshed: Infinity } } } },
    ])('rejects malformed, duplicated or unvalidated results %#', async response => {
        api.fetchAuthAPI.mockResolvedValue(response);
        await expect(fetchChartAnalogueTop3('member-token')).rejects.toThrow('자동 TOP3 응답 형식');
    });

    it('validates POST results as strictly as saved GET results', async () => {
        api.postAuthAPI.mockResolvedValue({ ...done, report: { ...report, candidates: [] } });
        await expect(startChartAnalogueTop3('member-token')).rejects.toThrow('자동 TOP3 응답 형식');
    });
});
