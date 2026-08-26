import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import NotificationToast from '@/components/ui/NotificationToast';

const notificationMock = vi.hoisted(() => ({
    notifications: [] as any[],
    dismiss: vi.fn(),
    markRead: vi.fn(),
}));

vi.mock('@/contexts/NotificationContext', () => ({
    useNotification: () => notificationMock,
}));

function notice(id: string, title: string, timestamp: number) {
    return {
        id,
        type: 'info',
        title,
        message: `${title} message`,
        timestamp,
        read: false,
    };
}

describe('NotificationToast mobile behavior', () => {
    beforeEach(() => {
        notificationMock.notifications = [];
        notificationMock.dismiss.mockReset();
        notificationMock.markRead.mockReset();
    });

    it('does not replay stored unread notifications and only shows runtime arrivals', () => {
        const stored = notice('stored', 'Stored alert', Date.now() - 1000);
        notificationMock.notifications = [stored];

        const view = render(
            <MemoryRouter>
                <NotificationToast />
            </MemoryRouter>,
        );
        expect(screen.queryByText('Stored alert')).not.toBeInTheDocument();

        const runtime = notice('runtime', 'Runtime alert', Date.now());
        notificationMock.notifications = [runtime, stored];
        view.rerender(
            <MemoryRouter>
                <NotificationToast />
            </MemoryRouter>,
        );

        expect(screen.getByText('Runtime alert')).toBeInTheDocument();
        expect(screen.queryByText('Stored alert')).not.toBeInTheDocument();
    });

    it('fits between mobile gutters and marks a clicked toast read', () => {
        const view = render(
            <MemoryRouter>
                <NotificationToast />
            </MemoryRouter>,
        );
        notificationMock.notifications = [notice('runtime', 'Runtime alert', Date.now())];
        view.rerender(
            <MemoryRouter>
                <NotificationToast />
            </MemoryRouter>,
        );

        const stack = screen.getByText('Runtime alert').closest('.notification-toast-stack');
        expect(stack).toHaveClass('left-3', 'right-3');

        fireEvent.click(screen.getByText('Runtime alert'));
        expect(notificationMock.markRead).toHaveBeenCalledWith('runtime');
        expect(screen.queryByText('Runtime alert')).not.toBeInTheDocument();
    });
});
