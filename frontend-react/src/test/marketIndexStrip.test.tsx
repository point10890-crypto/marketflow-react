import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MarketIndexStrip, {
  changeBarPct,
  formatPrice,
  parsePrice,
} from '@/pages/dashboard/MarketIndexStrip';
import type { MarketIndexItem } from '@/lib/api';

const item = (name: string, price: string, change_pct: number): MarketIndexItem => ({
  name, price, change: '', change_pct, color: '',
});

const BASE = [
  item('Dow Jones', '52,002.41', -0.34),
  item('VIX', '19.99', 21.45),
  item('10Y Treasury', '5.10', 0.18),
];

function setReducedMotion(reduce: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: reduce && query.includes('prefers-reduced-motion'),
      media: query, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

describe('가격 문자열 처리', () => {
  it('천단위 쉼표와 소수 자릿수를 읽는다', () => {
    expect(parsePrice('52,002.41')).toEqual({ value: 52002.41, decimals: 2 });
    expect(parsePrice('5.10')).toEqual({ value: 5.1, decimals: 2 });
    expect(parsePrice('1,329')).toEqual({ value: 1329, decimals: 0 });
  });

  it('숫자가 아니면 null — 원문을 그대로 보여주기 위함', () => {
    expect(parsePrice('N/A')).toBeNull();
    expect(parsePrice('')).toBeNull();
  });

  it('원래 형식(쉼표·자릿수)을 유지해 다시 쓴다', () => {
    expect(formatPrice(52002.41, 2)).toBe('52,002.41');
    expect(formatPrice(5.1, 2)).toBe('5.10');
    expect(formatPrice(1329, 0)).toBe('1,329');
  });
});

describe('등락 게이지', () => {
  it('등락폭에 비례하고 상한에서 멈춘다', () => {
    expect(changeBarPct(1.5)).toBeCloseTo(50);
    expect(changeBarPct(-1.5)).toBeCloseTo(50);
    expect(changeBarPct(21.45)).toBe(100);
  });

  it('0% 여도 흔적은 남긴다', () => {
    expect(changeBarPct(0)).toBeGreaterThan(0);
  });
});

describe('MarketIndexStrip', () => {
  beforeEach(() => setReducedMotion(true));
  afterEach(() => vi.useRealTimers());

  it('모든 지수와 가격·등락률을 보여준다', () => {
    render(<MarketIndexStrip indices={BASE} />);
    expect(screen.getByText('Dow Jones')).toBeInTheDocument();
    expect(screen.getByText('52,002.41')).toBeInTheDocument();
    expect(screen.getByText(/\+21\.45%/)).toBeInTheDocument();
    expect(screen.getByText(/-0\.34%/)).toBeInTheDocument();
  });

  it('살아있는 데이터임을 알리는 LIVE 표시가 있다', () => {
    render(<MarketIndexStrip indices={BASE} />);
    expect(screen.getByText('LIVE')).toBeInTheDocument();
  });

  it('지수가 없으면 그리드를 그리지 않는다', () => {
    const { container } = render(<MarketIndexStrip indices={[]} />);
    expect(container.querySelector('.summary-index-grid')).toBeNull();
  });

  it('타일마다 순차 진입 순서를 부여한다', () => {
    render(<MarketIndexStrip indices={BASE} />);
    const tiles = screen.getAllByTestId('market-index-tile');
    expect(tiles.map((t) => t.style.getPropertyValue('--i'))).toEqual(['0', '1', '2']);
  });

  it('가격이 오르면 상승 틱, 내리면 하락 틱을 표시한다', () => {
    const { rerender } = render(<MarketIndexStrip indices={BASE} />);
    rerender(<MarketIndexStrip indices={[
      item('Dow Jones', '52,100.00', -0.15),
      item('VIX', '18.50', 12.0),
      item('10Y Treasury', '5.10', 0.18),
    ]} />);
    const [dow, vix, tsy] = screen.getAllByTestId('market-index-tile');
    expect(dow).toHaveAttribute('data-tick', 'up');
    expect(vix).toHaveAttribute('data-tick', 'down');
    expect(tsy).not.toHaveAttribute('data-tick');
  });

  it('첫 렌더에는 틱을 표시하지 않는다 — 변화가 아니므로', () => {
    render(<MarketIndexStrip indices={BASE} />);
    screen.getAllByTestId('market-index-tile').forEach((t) => {
      expect(t).not.toHaveAttribute('data-tick');
    });
  });

  it('틱 표시는 잠시 뒤 사라진다', () => {
    vi.useFakeTimers();
    const { rerender } = render(<MarketIndexStrip indices={BASE} />);
    rerender(<MarketIndexStrip indices={[item('Dow Jones', '52,100.00', -0.15), BASE[1], BASE[2]]} />);
    expect(screen.getAllByTestId('market-index-tile')[0]).toHaveAttribute('data-tick', 'up');
    act(() => { vi.advanceTimersByTime(2000); });
    expect(screen.getAllByTestId('market-index-tile')[0]).not.toHaveAttribute('data-tick');
  });

  it('등락 게이지 폭을 타일에 반영한다', () => {
    render(<MarketIndexStrip indices={BASE} />);
    const bars = screen.getAllByTestId('market-index-bar');
    expect(bars[1].style.width).toBe('100%');
  });

  it('숫자가 아닌 가격은 원문 그대로 보여준다', () => {
    render(<MarketIndexStrip indices={[item('Odd', 'N/A', 0)]} />);
    expect(screen.getByText('N/A')).toBeInTheDocument();
  });

  it('모션 축소 설정이면 카운트업 없이 최종 값을 바로 보여준다', () => {
    const { rerender } = render(<MarketIndexStrip indices={BASE} />);
    rerender(<MarketIndexStrip indices={[item('Dow Jones', '53,000.00', 1.6), BASE[1], BASE[2]]} />);
    expect(screen.getByText('53,000.00')).toBeInTheDocument();
  });

  it('모션이 켜져 있으면 카운트업 후 최종 값에 도달한다', async () => {
    setReducedMotion(false);
    vi.useFakeTimers();
    const { rerender } = render(<MarketIndexStrip indices={BASE} />);
    rerender(<MarketIndexStrip indices={[item('Dow Jones', '53,000.00', 1.6), BASE[1], BASE[2]]} />);
    await act(async () => { vi.advanceTimersByTime(1500); });
    expect(screen.getByText('53,000.00')).toBeInTheDocument();
  });
});
