import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { adminAPI } from '@/lib/api';
import { UsersTab } from '@/pages/admin/AdminPage';

describe('admin user search', () => {
  beforeEach(() => {
    vi.spyOn(adminAPI, 'getDuplicates').mockResolvedValue({ groups: [], total_groups: 0 });
    vi.spyOn(adminAPI, 'getUsers').mockResolvedValue({
      users: [{
        id: 7,
        email: 'alpha@example.com',
        name: '김알파',
        role: 'user',
        tier: 'pro',
        status: 'approved',
        pro_expires_at: '2026-08-01T00:00:00',
        created_at: '2026-01-01T00:00:00',
        approved_at: '2026-01-01T00:00:00',
        last_login_at: null,
      }],
      total: 1,
      page: 1,
      per_page: 50,
      total_pages: 1,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('debounces ID/name/email input and queries the server with pagination', async () => {
    render(<UsersTab apiToken="admin-token" currentUserId={99} />);

    const search = await screen.findByPlaceholderText('회원 ID, 이름 또는 이메일 검색...');
    fireEvent.change(search, { target: { value: 'alpha@example.com' } });

    await waitFor(() => {
      expect(adminAPI.getUsers).toHaveBeenCalledWith('admin-token', expect.objectContaining({
        q: 'alpha@example.com',
        page: 1,
        per_page: 50,
      }));
    });
    expect(screen.getByText('김알파')).toBeInTheDocument();
    expect(screen.getByText('1명 검색됨')).toBeInTheDocument();
  });

  it('requests the expired AI Brain server filter', async () => {
    render(<UsersTab apiToken="admin-token" currentUserId={99} />);

    const expiredFilter = await screen.findByRole('button', { name: 'AI 만료' });
    fireEvent.click(expiredFilter);

    await waitFor(() => {
      expect(adminAPI.getUsers).toHaveBeenCalledWith('admin-token', expect.objectContaining({
        tier: 'aibain_expired',
        page: 1,
      }));
    });
  });
});
