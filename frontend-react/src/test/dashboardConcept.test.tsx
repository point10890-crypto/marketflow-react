import { render, screen, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { DashboardConceptPanel } from '@/pages/dashboard/DashboardClient';

const dashboardSource = readFileSync(
  resolve(__dirname, '../pages/dashboard/DashboardClient.tsx'),
  'utf-8',
);

describe('dashboard operating concept', () => {
  it('introduces the four operating axes in a desktop-only top panel', () => {
    render(<DashboardConceptPanel />);

    const panel = screen.getByRole('region', {
      name: '시장 판단을 기록하는 운영 대시보드',
    });
    expect(panel).toHaveClass('hidden', 'md:block');
    expect(within(panel).getByRole('heading', {
      level: 1,
      name: '시장 판단을 기록하는 운영 대시보드',
    })).toBeInTheDocument();

    ['데이터', '품질', '리스크', '결과 추적'].forEach((axis) => {
      expect(within(panel).getByText(axis)).toBeInTheDocument();
    });

    const panelUse = dashboardSource.indexOf('<DashboardConceptPanel />');
    const desktopHeader = dashboardSource.indexOf('Header + Scrolling Market Ticker');
    expect(panelUse).toBeGreaterThan(-1);
    expect(panelUse).toBeLessThan(desktopHeader);
  });

  it('uses observation and risk language instead of trade recommendations', () => {
    expect(dashboardSource).not.toContain("label: '적극매수'");
    expect(dashboardSource).not.toContain("label: '매수'");
    expect(dashboardSource).not.toContain("label: '매도'");
    expect(dashboardSource).not.toContain("label: '적극매도'");
    expect(dashboardSource).not.toContain('>매수</span>');
    expect(dashboardSource).not.toContain('>매도</span>');

    ['관찰 최우선', '관찰 강화', '균형 관찰', '리스크 주의', '리스크 경계'].forEach((label) => {
      expect(dashboardSource).toContain(label);
    });
    expect(dashboardSource).toContain("s.signal === 'BUY'");
    expect(dashboardSource).toContain('by_signal?.SELL');
  });

  it('does not restore the TopSignal breathe animation', () => {
    expect(dashboardSource).not.toContain('@keyframes breathe');
    expect(dashboardSource).not.toMatch(/animation:\s*['\"]breathe/);
  });
});
