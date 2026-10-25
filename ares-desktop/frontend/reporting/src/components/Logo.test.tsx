import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Logo } from './Logo';

/**
 * Sprint U-16 (2026-06-06): Tests fuer SVG-Wordmark-Logo.
 */

describe('Logo', () => {
  it('rendert als img-Rolle mit data-testid', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-ares');
    expect(logo.tagName).toBe('svg');
    expect(logo.getAttribute('role')).toBe('img');
  });

  it('default aria-label ist "Logo Ares"', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-ares');
    expect(logo.getAttribute('aria-label')).toBe('Logo Ares');
  });

  it('custom ariaLabel ueberschreibt Default', () => {
    render(<Logo ariaLabel="Mein Custom Logo" />);
    const logo = screen.getByTestId('logo-ares');
    expect(logo.getAttribute('aria-label')).toBe('Mein Custom Logo');
  });

  it('default width=96', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-ares');
    expect(logo.getAttribute('width')).toBe('96');
  });

  it('custom width skaliert Hoehe proportional', () => {
    render(<Logo width={240} />);
    const logo = screen.getByTestId('logo-ares');
    expect(logo.getAttribute('width')).toBe('240');
    // viewBox: 240/80 = 3:1 -> height = width/3
    expect(logo.getAttribute('height')).toBe('80');
  });

  it('rendert genau ein SVG-text-Element mit dem Schriftzug "Ares"', () => {
    const { container } = render(<Logo />);
    const texts = container.querySelectorAll('text');
    expect(texts.length).toBe(1);
    expect(texts[0].textContent?.trim()).toBe('Ares');
  });

  it('nutzt Cormorant Garamond fuer den Schriftzug', () => {
    const { container } = render(<Logo />);
    const wordmark = container.querySelectorAll('text')[0];
    expect(wordmark.getAttribute('font-family')).toMatch(/Cormorant/);
  });

  it('sichtbarer SVG-Text ist exakt der Produktname (keine geteilte Wortmarke)', () => {
    const { container } = render(<Logo />);
    const visible = Array.from(container.querySelectorAll('text'))
      .map((t) => t.textContent ?? '')
      .join('')
      .trim();
    expect(visible).toBe('Ares');
  });

  it('SVG nutzt currentColor (Theme-aware)', () => {
    const { container } = render(<Logo />);
    const texts = container.querySelectorAll('text');
    for (const t of texts) {
      expect(t.getAttribute('fill')).toBe('currentColor');
    }
  });

  it('hat title-Element fuer Screen-Reader-Tooltips', () => {
    const { container } = render(<Logo />);
    const title = container.querySelector('title');
    expect(title).not.toBeNull();
    expect(title?.textContent).toBe('Logo Ares');
  });

  it('akzeptiert className-Prop', () => {
    render(<Logo className="text-accent extra-class" />);
    const logo = screen.getByTestId('logo-ares');
    const cls = logo.getAttribute('class') ?? '';
    expect(cls).toContain('text-accent');
    expect(cls).toContain('extra-class');
  });

  it('hat dezente Akzent-Linie als Unterzeichnung', () => {
    const { container } = render(<Logo />);
    const line = container.querySelector('line');
    expect(line).not.toBeNull();
    expect(line?.getAttribute('stroke-opacity')).toBe('0.25');
  });
});
