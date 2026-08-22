import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ClawMascot from '@/components/claw/ClawMascot';

describe('ClawMascot', () => {
  it('maps each loop state to its own animation class and badge', () => {
    const { container: run } = render(<ClawMascot state="running" />);
    expect(run.querySelector('svg')).toHaveClass('claw-anim-run');
    expect(run.querySelector('.claw-candles')).not.toBeNull();

    const { container: idle } = render(<ClawMascot state="idle" />);
    expect(idle.querySelector('svg')).toHaveClass('claw-anim-idle');
    expect(idle.querySelector('.claw-zz')).not.toBeNull();

    const { container: halt } = render(<ClawMascot state="halt" />);
    expect(halt.querySelector('svg')).toHaveClass('claw-anim-halt');
    expect(halt.querySelector('.claw-badge')?.textContent).toBe('!');

    const { container: dead } = render(<ClawMascot state="dead" />);
    expect(dead.querySelector('svg')).toHaveClass('claw-anim-dead');
    expect(dead.textContent).toContain('?');
  });

  it('falls back to idle when state is unknown and exposes an accessible label', () => {
    const { container } = render(<ClawMascot state={null} size={40} />);
    const svg = container.querySelector('svg')!;
    expect(svg).toHaveClass('claw-anim-idle');
    expect(svg.getAttribute('aria-label')).toBe('Claw 마스코트');
    expect(svg.getAttribute('width')).toBe('40');
  });
});
