/**
 * Vitest baseline smoke test.
 *
 * Purpose: prove the test runner + jsdom + testing-library wiring works
 * end-to-end. Real component tests are added on top of this baseline.
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

describe('vitest baseline', () => {
  it('renders a DOM node and queries it', () => {
    render(<h1>MarketFlow</h1>);
    expect(screen.getByRole('heading', { name: 'MarketFlow' })).toBeInTheDocument();
  });

  it('runs basic assertions', () => {
    expect(1 + 1).toBe(2);
  });
});
