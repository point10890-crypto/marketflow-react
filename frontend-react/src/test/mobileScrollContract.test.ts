/**
 * Shared scrolling contract.
 *
 * Public/auth pages use native document scrolling. Dashboard routes use one
 * bounded inner scroller (Wave intentionally owns its separate nested scroller,
 * covered by waveScrollLock.test.ts).
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = resolve(__dirname, '..');
const css = readFileSync(resolve(SRC, 'index.css'), 'utf-8');
const app = readFileSync(resolve(SRC, 'App.tsx'), 'utf-8');
const layout = readFileSync(resolve(SRC, 'components/layout/DashboardLayout.tsx'), 'utf-8');
const header = readFileSync(resolve(SRC, 'components/layout/Header.tsx'), 'utf-8');
const bottomTabs = readFileSync(resolve(SRC, 'components/layout/BottomTabBar.tsx'), 'utf-8');
const installPrompt = readFileSync(resolve(SRC, 'components/layout/InstallPrompt.tsx'), 'utf-8');
const notificationToast = readFileSync(resolve(SRC, 'components/ui/NotificationToast.tsx'), 'utf-8');

describe('shared mobile scroll contract', () => {
  it('keeps the document scrollable for public and auth routes', () => {
    const rootRules = css.slice(0, css.indexOf('/* Mobile safe area'));
    expect(rootRules).not.toMatch(/overflow\s*:\s*hidden/);
    expect(rootRules).not.toMatch(/overscroll-behavior\s*:\s*none/);
    expect(rootRules).toMatch(/body\s*\{[\s\S]*min-height:\s*100dvh/);
    expect(app).toContain('<DocumentScrollReset />');
  });

  it('uses one dynamic-viewport dashboard scroller without forced smooth scrolling', () => {
    expect(layout).toContain('h-[100dvh]');
    expect(layout).toContain('dashboard-shell-scroll flex-1 min-w-0 min-h-0');
    expect(layout).not.toContain('scroll-smooth');
    expect(layout).not.toContain('overscroll-contain');
    expect(layout).toMatch(/useLayoutEffect\([\s\S]*scrollTop\s*=\s*0[\s\S]*\[pathname\]/);
  });

  it('does not intercept page-wide mobile touch gestures', () => {
    expect(layout).not.toContain('usePullToRefresh(');
    expect(layout).not.toContain('useSwipeNavigation(');
    expect(layout).not.toContain('pullDistance');
  });

  it('drops long-lived mobile transform and fixed blur layers', () => {
    expect(css).toMatch(/\.page-enter\s*\{[\s\S]*backwards/);
    expect(css).toMatch(/@media \(max-width: 767px\), \(prefers-reduced-motion: reduce\)[\s\S]*\.page-enter \{ animation: none; \}/);
    expect(header).toContain('md:backdrop-blur-md');
    expect(bottomTabs).not.toContain('backdrop-blur');
  });

  it('keeps transient overlays inside mobile safe areas and clears visible banners', () => {
    expect(css).toMatch(/\.dashboard-install-prompt-visible \.dashboard-standard-scroll[\s\S]*padding-bottom:\s*calc\(16rem \+ env\(safe-area-inset-bottom/);
    expect(css).toMatch(/\.install-prompt-banner[\s\S]*safe-area-inset-bottom/);
    expect(css).toMatch(/\.mobile-safe-top-header[\s\S]*safe-area-inset-top/);
    expect(installPrompt).toContain('isInstalled || !canInstall');
    expect(layout).toContain('dashboard-install-prompt-visible');
    expect(notificationToast).toContain('left-3 right-3');
  });
});
