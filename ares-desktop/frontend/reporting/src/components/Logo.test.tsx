import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Logo } from './Logo';

/**
 * Sprint U-16 (2026-06-06): Tests fuer SVG-Wordmark-Logo.
 */

describe('Logo', () => {
  it('rendert als img-Rolle mit data-testid', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-5eyes');
    expect(logo.tagName).toBe('svg');
    expect(logo.getAttribute('role')).toBe('img');
  });

  it('default aria-label nennt 5eyes + WealthArchitekten', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-5eyes');
    const aria = logo.getAttribute('aria-label');
    expect(aria).toMatch(/5eyes/);
    expect(aria).toMatch(/WealthArchitekten/);
  });

  it('custom ariaLabel ueberschreibt Default', () => {
    render(<Logo ariaLabel="Mein Custom Logo" />);
    const logo = screen.getByTestId('logo-5eyes');
    expect(logo.getAttribute('aria-label')).toBe('Mein Custom Logo');
  });

  it('default width=96', () => {
    render(<Logo />);
    const logo = screen.getByTestId('logo-5eyes');
    expect(logo.getAttribute('width')).toBe('96');
  });

  it('custom width skaliert Hoehe proportional', () => {
    render(<Logo width={240} />);
    const logo = screen.getByTestId('logo-5eyes');
    expect(logo.getAttribute('width')).toBe('240');
    // viewBox: 240/80 = 3:1 -> height = width/3
    expect(logo.getAttribute('height')).toBe('80');
  });

  it('rendert SVG-text-Elemente fuer "5" und "eyes"', () => {
    const { container } = render(<Logo />);
    const texts = container.querySelectorAll('text');
    expect(texts.length).toBe(2);
    expect(texts[0].textContent).toBe('5');
    expect(texts[1].textContent).toBe('eyes');
  });

  it('nutzt Cormorant Garamond fuer "5"', () => {
    const { container } = render(<Logo />);
    const fiveText = container.querySelectorAll('text')[0];
    expect(fiveText.getAttribute('font-family')).toMatch(/Cormorant/);
  });

  it('nutzt Inter fuer "eyes"', () => {
    const { container } = render(<Logo />);
    const eyesText = container.querySelectorAll('text')[1];
    expect(eyesText.getAttribute('font-family')).toMatch(/Inter/);
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
    expect(title?.textContent).toMatch(/5eyes/);
  });

  it('akzeptiert className-Prop', () => {
    render(<Logo className="text-accent extra-class" />);
    const logo = screen.getByTestId('logo-5eyes');
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
