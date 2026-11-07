import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { BankTransferDetails } from '@/components/subscription/SubscriptionFlow';
import { BANK_ACCOUNT } from '@/lib/billingInfo';
afterEach(() => vi.unstubAllGlobals());
it('confirms account copying only after clipboard succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    render(<BankTransferDetails />);
    fireEvent.click(screen.getByRole('button', { name: '계좌 복사' }));
    expect(await screen.findByText('계좌번호를 복사했습니다.')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(BANK_ACCOUNT.account.replace(/-/g, ''));
});
it('keeps the account readable and explains manual copying when clipboard is denied', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    render(<BankTransferDetails />);
    fireEvent.click(screen.getByRole('button', { name: '계좌 복사' }));
    expect(await screen.findByText(/복사하지 못했습니다/)).toBeInTheDocument();
    expect(screen.getByText(BANK_ACCOUNT.account)).toBeVisible();
    expect(screen.queryByText('계좌번호를 복사했습니다.')).not.toBeInTheDocument();
});
