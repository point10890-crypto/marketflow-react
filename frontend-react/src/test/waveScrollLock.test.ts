/**
 * Wave page scroll-lock regression guard.
 *
 * Background: the /dashboard/wave page must use its OWN inner scroll
 * container (`h-full overflow-y-auto` on the page) and the outer
 * DashboardLayout main scroll area must be locked (`overflow-hidden`).
 * Otherwise mobile Safari hits a scroll boundary lock at the top of
 * the wave chart and the user cannot scroll back down.
 *
 * This test asserts those two contracts at the source level so any
 * future refactor that drops the wave-page branch fails CI.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = resolve(__dirname, '..');
const layoutSrc = readFileSync(resolve(SRC, 'components/layout/DashboardLayout.tsx'), 'utf-8');
const wavePageSrc = readFileSync(resolve(SRC, 'pages/dashboard/wave/WaveOverviewPage.tsx'), 'utf-8');

describe('wave page scroll-lock contract', () => {
  it('DashboardLayout detects wave page via pathname', () => {
    expect(layoutSrc).toMatch(/isWavePage\s*=\s*location\.pathname\.startsWith\(['"]\/dashboard\/wave['"]\)/);
  });

  it('DashboardLayout outer scroll container is locked on wave page', () => {
    // The conditional must produce overflow-hidden when isWavePage is true.
    expect(layoutSrc).toMatch(/isWavePage\s*\?\s*['"]overflow-hidden p-0['"]/);
  });

  it('WaveOverviewPage is its own scroll container', () => {
    // The page root must be h-full + overflow-y-auto so it scrolls
    // independently of the (locked) outer container.
    expect(wavePageSrc).toMatch(/h-full/);
    expect(wavePageSrc).toMatch(/overflow-y-auto/);
  });
});
