import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AlphaCoreSnapshot } from '@/lib/alphaCore';
import AlphaCoreOpsCard from '@/pages/dashboard/aibain/AlphaCoreOpsCard';

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ token: 'read-only-token' }),
}));

const snapshot: AlphaCoreSnapshot = {
    status: {
        schema_version: 'marketflow.alpha_core.status.v1',
        status: 'ok',
        available: true,
        mode: 'SHADOW',
        generated_at: '2026-08-24T12:30:00+09:00',
        database: { status: 'ok' },
        counts: { hypotheses: 2 },
        risk_state: { state: 'BLOCK_NEW' },
        quality: { status: 'ok', stale: false },
    },
    portfolio: {
        status: 'ok',
        cash_krw: 40_000_000,
        nav_krw: 100_000_000,
        gross_exposure_krw: 60_000_000,
        net_exposure_krw: 60_000_000,
        drawdown_pct: -1.4,
    },
    riskDecisions: {
        items: [{
            id: 'risk-1',
            decision: 'REJECT',
            reason_codes: ['data_quality_gate'],
            created_at: '2026-08-24T12:29:00+09:00',
        }],
    },
    hypotheses: {
        items: [
            { hypothesis_id: 'h-1', title: '거래대금 확장 후속성', status: 'SHADOW' },
            { hypothesis_id: 'h-2', title: '주도주 등급 지속성', status: 'DRAFT' },
        ],
    },
    ledger: {
        pending: 2,
        reconcile_required: true,
        reconciliation: { required: true, unreconciled_count: 1 },
    },
    unavailable: [],
};

describe('AlphaCoreOpsCard', () => {
    it('shows a mobile-safe shadow operations summary without order or approval controls', async () => {
        const loader = vi.fn().mockResolvedValue(snapshot);
        render(<AlphaCoreOpsCard loadSnapshot={loader} />);

        expect(await screen.findByText('AlphaClaw Core')).toBeInTheDocument();
        expect(screen.getAllByText('SHADOW')).toHaveLength(2);
        expect(screen.getByText('관측 정상')).toBeInTheDocument();
        expect(screen.getByText('BLOCK_NEW')).toBeInTheDocument();
        expect(screen.getByText('data_quality_gate')).toBeInTheDocument();
        expect(screen.getByText('거래대금 확장 후속성')).toBeInTheDocument();
        expect(screen.getByText('대사 필요')).toBeInTheDocument();
        expect(screen.getByText(/GET-only/)).toBeInTheDocument();
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(loader).toHaveBeenCalledWith('read-only-token');
    });

    it('fails closed to an explicit unavailable state', async () => {
        render(<AlphaCoreOpsCard loadSnapshot={() => Promise.reject(new Error('offline'))} />);

        await waitFor(() => expect(screen.getByText('연결 확인 필요')).toBeInTheDocument());
        expect(screen.getByText('확인 불가')).toBeInTheDocument();
        expect(screen.getByText('최근 거절 사유 없음')).toBeInTheDocument();
        expect(screen.getByText('등록된 검증 가설 없음')).toBeInTheDocument();
    });
});
