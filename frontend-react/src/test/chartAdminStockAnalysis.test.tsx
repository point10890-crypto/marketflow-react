import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnaloguePage from '@/pages/dashboard/aibain/ChartAnaloguePage';
import { stockAnalysis } from './adminStockAnalysisFixtures';

const auth = vi.hoisted(() => ({ role: 'admin', token: 'admin-token' as string | null, status: 'approved', loading: false, addon: false }));
const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn(), chart: vi.fn() }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: auth.role, status: auth.status, tier: 'pro', is_aibain_active: auth.addon, aibain_enabled: auth.addon }, token: auth.token, loading: auth.loading }) }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: api.fetchAuthAPI, postAuthAPI: api.postAuthAPI }));
vi.mock('@/lib/chartAnalogueApi', async importActual => ({ ...await importActual<typeof import('@/lib/chartAnalogueApi')>(), fetchChartAnalogue: api.chart }));
vi.mock('@/components/aibain/ChartAnalogueKellyPanel', () => ({ default: () => null }));
vi.mock('@/components/aibain/ChartAnalogueTop3Panel', () => ({ default: () => null }));
vi.mock('@/components/aibain/ChartAnalogueEvaluationPanel', () => ({ default: () => null }));
function Path() { const location = useLocation(); return <output aria-label="경로">{location.pathname}{location.search}{location.hash}</output>; }
function renderPage() { return render(<MemoryRouter initialEntries={['/dashboard/ai-bain/chart-predict?code=003690&adminCode=042700&view=evidence#keep']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ChartAnaloguePage /><Path /></MemoryRouter>); }

describe('administrator stock search inside the agent proposals', () => {
    beforeEach(() => {
        auth.role = 'admin'; auth.token = 'admin-token'; auth.status = 'approved'; auth.loading = false; auth.addon = false;
        api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); api.chart.mockReset();
        api.chart.mockImplementation(() => new Promise(() => {}));
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.endsWith('/alpha-lab')
            ? { schema_version: 1, state: 'missing', generated_at: null, report: null, error: null }
            : path.endsWith('/005930') ? stockAnalysis('005930', '삼성전자') : stockAnalysis()));
    });

    it('places the private subsection inside the existing agent panel and isolates selected symbols from chart/query/hash', async () => {
        renderPage(); const heading = screen.getByRole('heading', { name: '에이전트 매매 제안' });
        const region = heading.closest('section')!;
        const privateHeading = within(region).getByRole('heading', { level: 3, name: '관리자 전용 종목 검색 분석' });
        expect(privateHeading.closest('#admin-stock-analysis')).toBeInTheDocument();
        await within(region).findByRole('article', { name: /한미반도체/ });
        const publicInput = screen.getAllByRole('combobox', { name: '종목명 또는 코드' }).find(input => input.id === 'analogue-code')!;
        const privateInput = within(region).getByRole('combobox', { name: '종목명 또는 코드' });
        expect(publicInput).toHaveValue('003690');
        await userEvent.clear(privateInput); await userEvent.type(privateInput, '005930{Enter}');
        await within(region).findByRole('article', { name: /삼성전자/ });
        expect(screen.getByLabelText('경로')).toHaveTextContent('?code=003690&adminCode=005930&view=evidence#keep');
        expect(publicInput).toHaveValue('003690'); expect(api.chart).toHaveBeenCalledOnce();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('keeps the private target and unrelated query when selecting a public chart symbol', async () => {
        renderPage(); await screen.findByRole('article', { name: /한미반도체/ });
        const publicInput = screen.getAllByRole('combobox', { name: '종목명 또는 코드' }).find(input => input.id === 'analogue-code')!;
        await userEvent.clear(publicInput); await userEvent.type(publicInput, '000660{Enter}');
        expect(screen.getByLabelText('경로')).toHaveTextContent('code=000660&adminCode=042700&view=evidence');
        expect(screen.getByRole('article', { name: /한미반도체/ })).toBeInTheDocument();
        expect(api.fetchAuthAPI.mock.calls.filter(([path]) => path.includes('/stock-analysis'))).toHaveLength(1);
        expect(api.chart).toHaveBeenLastCalledWith('000660', 'admin-token');
    });

    it.each([{ label: 'regular Pro member', addon: false }, { label: 'AI Brain member', addon: true }])('retains public proposals and makes no private calls for $label', async ({ addon }) => {
        auth.role = 'user'; auth.addon = addon; auth.token = 'member-token'; renderPage(); await act(async () => {});
        expect(screen.getByRole('heading', { name: '에이전트 매매 제안' })).toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: '관리자 전용 종목 검색 분석' })).not.toBeInTheDocument();
        expect(api.fetchAuthAPI.mock.calls.some(([path]) => path.includes('/stock-analysis'))).toBe(false);
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab', 'member-token');
    });

    it.each(['suspended', 'rejected'])('never mounts private analysis or calls its API for a %s admin', async status => {
        auth.status = status; renderPage(); await act(async () => {});
        expect(screen.queryByRole('heading', { name: '관리자 전용 종목 검색 분석' })).not.toBeInTheDocument();
        expect(api.fetchAuthAPI.mock.calls.some(([path]) => path.includes('/stock-analysis'))).toBe(false);
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
});
