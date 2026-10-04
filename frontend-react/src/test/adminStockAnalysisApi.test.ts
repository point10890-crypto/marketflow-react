import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchAdminStockAnalysis, searchAdminStockCandidates, startAdminStockAnalysis, validateAdminStockAnalysis, effectiveAdminStockProposal } from '@/lib/adminStockAnalysisApi';
import { analysisNow, stockAnalysis } from './adminStockAnalysisFixtures';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);

describe('admin named-stock analysis boundary', () => {
    beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(analysisNow)); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
    afterEach(() => vi.useRealTimers());

    it('uses only the new admin search, encoded names/chosung and strict KR candidates', async () => {
        api.fetchAuthAPI.mockResolvedValue({ candidates: [
            { symbol: '005930', name: '삼성전자', market: 'KR' }, { symbol: '005930', name: '중복', market: 'KR' },
            { symbol: 'AAPL', name: 'Apple', market: 'US' }, { symbol: '000660', name: 'SK하이닉스', market: 'KR' },
        ] });
        expect(await searchAdminStockCandidates(' ㅅㅅㅈㅈ ', 'admin-token')).toEqual([
            { symbol: '005930', name: '삼성전자' }, { symbol: '000660', name: 'SK하이닉스' },
        ]);
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/stock-analysis/search?q=%E3%85%85%E3%85%85%E3%85%88%E3%85%88&limit=8', 'admin-token', 8000);
        await searchAdminStockCandidates('A&B', 'admin-token');
        expect(api.fetchAuthAPI.mock.calls[1][0]).toContain('q=A%26B&limit=8');
    });

    it('reads saved data and starts only the selected symbol with an exact body', async () => {
        api.fetchAuthAPI.mockResolvedValue(stockAnalysis()); api.postAuthAPI.mockResolvedValue(stockAnalysis());
        expect((await fetchAdminStockAnalysis('042700', 'admin-token')).target.symbol).toBe('042700');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/stock-analysis/042700', 'admin-token', 15000);
        await startAdminStockAnalysis('042700', 'admin-token');
        expect(api.postAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/stock-analysis', { symbol: '042700' }, 'admin-token', 30000);
    });

    it('accepts a requested symbol outside the global top three without a fabricated cohort report', () => {
        expect(validateAdminStockAnalysis(stockAnalysis(), '042700').result?.candidate.symbol).toBe('042700');
    });

    it.each(['identity', 'nonfinite', 'weight', 'plan', 'fingerprint', 'source_future', 'proposal_missing', 'session', 'evidence_missing', 'quarter_kelly'])('rejects corrupt %s response', fault => {
        const value = stockAnalysis(); const result = value.result!;
        if (fault === 'identity') result.candidate.symbol = '005930';
        if (fault === 'nonfinite') result.candidate.plan!.stop_price = NaN;
        if (fault === 'weight') result.candidate.proposal!.proposed_weight = .06;
        if (fault === 'plan') result.candidate.plan!.target_price = 170000;
        if (fault === 'fingerprint') result.input_fingerprint = 'hash';
        if (fault === 'source_future') result.source.captured_at = '2027-01-01T00:00:00Z';
        if (fault === 'proposal_missing') Reflect.deleteProperty(result.candidate, 'proposal');
        if (fault === 'session') result.candidate.proposal!.input_session = '2026-09-30';
        if (fault === 'evidence_missing') delete result.candidate.evidence;
        if (fault === 'quarter_kelly') result.candidate.risk.quarter_kelly_fraction = .2;
        expect(() => validateAdminStockAnalysis(value, '042700')).toThrow(/응답/);
    });

    it('accepts GET presentation timing after the original analysis without moving the input snapshot', () => {
        const value = stockAnalysis(); value.result!.analyzed_at = '2026-10-01T09:01:00Z';
        expect(validateAdminStockAnalysis(value, '042700').result!.analyzed_at).toBe('2026-10-01T09:01:00Z');
    });

    it.each(['manual_allocation', 'calibration_compounded', 'calibration_stress_compounded', 'confirmation_compounded',
        'confirmation_stress_compounded', 'calibration_exit_before_start', 'confirmation_exit_before_start'])('rejects a BUY violating the backend contract: %s', fault => {
        const value = stockAnalysis(); const candidate = value.result!.candidate; const evidence = candidate.evidence!;
        if (fault === 'manual_allocation') candidate.risk.weight = .01;
        if (fault === 'calibration_compounded') evidence.calibration.compounded_trade_return = 0;
        if (fault === 'calibration_stress_compounded') evidence.calibration.stress_compounded_trade_return = 0;
        if (fault === 'confirmation_compounded') evidence.confirmation.compounded_trade_return = 0;
        if (fault === 'confirmation_stress_compounded') evidence.confirmation.stress_compounded_trade_return = 0;
        if (fault === 'calibration_exit_before_start') evidence.calibration.last_exit_session = '2020-12-31';
        if (fault === 'confirmation_exit_before_start') evidence.confirmation.last_exit_session = '2025-09-30';
        expect(() => validateAdminStockAnalysis(value, '042700')).toThrow(/응답/);
    });

    it('accepts an honest zero-sample diagnostic with unavailable rates', () => {
        const value = stockAnalysis();
        value.result!.diagnostics.push({ strategy_id: 'momentum', setup_active: false, reasons: ['insufficient_samples'],
            calibration: { samples: 0, wins: 0, losses: 0, zeros: 0, win_rate: null, mean_net_return: null,
                stress_mean_net_return: null, compounded_trade_return: 0, stress_compounded_trade_return: 0,
                start: '2021-01-04', end: '2025-09-30', last_exit_session: null, t_stat: null }, confirmation: null });
        expect(validateAdminStockAnalysis(value, '042700').result!.diagnostics).toHaveLength(1);
    });

    it.each(['running', 'failed', 'held', 'blocked', 'expired', 'stale', 'missing_deadline'])('turns an unsafe %s BUY into WAIT with zero weight without losing reference prices', reason => {
        const value = stockAnalysis();
        if (reason === 'running' || reason === 'failed' || reason === 'held') value.state = reason;
        if (reason === 'blocked') value.result!.quality.status = 'blocked';
        if (reason === 'expired') value.result!.candidate.proposal!.valid_until = '2026-10-01T09:59:59Z';
        if (reason === 'stale') value.result!.source.captured_at = '2026-09-20T09:00:00Z';
        if (reason === 'missing_deadline') value.result!.candidate.proposal!.valid_until = null;
        const validated = validateAdminStockAnalysis(value, '042700');
        const proposal = effectiveAdminStockProposal(validated, false, Date.now());
        expect(proposal?.action).toBe('wait'); expect(proposal?.proposed_weight).toBe(0);
        expect(validated.result?.candidate.plan?.entry_price).toBe(100000);
    });

    it('sanitizes transport diagnostics and rejects bad symbols before any request', async () => {
        await expect(startAdminStockAnalysis('../invalid')).rejects.toThrow(/종목/);
        expect(api.postAuthAPI).not.toHaveBeenCalled();
        api.fetchAuthAPI.mockRejectedValue(new Error('SECRET transport traceback'));
        await expect(fetchAdminStockAnalysis('042700')).rejects.toThrow('저장 분석 결과를 불러오지 못했습니다.');
    });
});
