/**
 * ClawBrandBar 스크롤 동작 — 배너는 일반 흐름, 접힌 바는 overlay 토글(히스테리시스).
 * 레이아웃 속성 전환/backdrop blur 가 다시 들어오지 않도록 CSS 도 함께 고정한다.
 */
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { ClawBrandBar } from '@/components/claw/ClawHero';

beforeAll(() => {
  // jsdom: ResizeObserver 없음(ASCII 캔버스), rAF 는 즉시 실행으로
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
  vi.stubGlobal('cancelAnimationFrame', () => {});
});

function setup() {
  const utils = render(
    <MemoryRouter>
      <div className="dashboard-shell-scroll" data-testid="scroller">
        <ClawBrandBar data={null} />
        <div style={{ height: 2000 }} />
      </div>
    </MemoryRouter>,
  );
  const scroller = screen.getByTestId('scroller');
  const banner = screen.getByTestId('claw-brand-banner');
  // jsdom 은 레이아웃이 없으므로 배너 위치/높이를 고정값으로 흉내낸다 (offsetTop 10, 높이 186 → 하단 196)
  Object.defineProperty(banner, 'offsetTop', { value: 10, configurable: true });
  Object.defineProperty(banner, 'offsetHeight', { value: 186, configurable: true });
  const scrollTo = (y: number) => {
    Object.defineProperty(scroller, 'scrollTop', { value: y, configurable: true });
    act(() => { scroller.dispatchEvent(new Event('scroll')); });
  };
  return { ...utils, scroller, scrollTo };
}

describe('ClawBrandBar', () => {
  it('starts expanded: compact overlay hidden, banner in normal flow', () => {
    setup();
    const compact = screen.getByTestId('claw-brand-compact');
    expect(compact.className).not.toContain('is-on');
    expect(compact.getAttribute('tabindex')).toBe('-1');
    expect(screen.getByTestId('claw-brand-banner').className).not.toContain('sticky');
  });

  it('shows the compact bar only after the banner has scrolled out, with hysteresis', () => {
    const { scrollTo } = setup();
    const compact = screen.getByTestId('claw-brand-compact');

    scrollTo(100);                       // 배너 아직 보임 → 펼침 유지
    expect(compact.className).not.toContain('is-on');

    scrollTo(195);                       // 배너 하단(196) - 8 초과 → 접힘
    expect(compact.className).toContain('is-on');
    expect(compact.getAttribute('tabindex')).toBe('0');

    scrollTo(160);                       // 접힘 유지 구간(196-56=140 초과) → 진동 없음
    expect(compact.className).toContain('is-on');

    scrollTo(100);                       // 140 미만 → 펼침
    expect(compact.className).not.toContain('is-on');
  });

  it('CSS: compact bar animates only transform/opacity and the banner has no blur or layout transitions', () => {
    const css = readFileSync(resolve(__dirname, '../index.css'), 'utf-8');
    const section = css.slice(css.indexOf('/* 5) 타이틀 배너'), css.indexOf('/* 6) 모바일 세로'));
    expect(section).toContain('.claw-brand-sticky { position: sticky; top: 0; height: 0;');
    expect(section).not.toMatch(/backdrop-filter/);
    expect(section).not.toMatch(/transition:[^;]*(min-height|width|height|padding)/);
    expect(section).toMatch(/\.claw-brand-compact \{[\s\S]*transition: opacity [^;]*, transform/);
  });
});
