import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ThemeToggle } from './ThemeToggle';

/**
 * Sprint U-50 (2026-06-06): Tests fuer Dark-Mode-Toggle-Button.
 */

describe('ThemeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('dark');
  });

  afterEach(() => {
    document.documentElement.classList.remove('dark');
  });

  it('rendert als Button mit data-testid', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    expect(button.tagName).toBe('BUTTON');
    expect(button.getAttribute('type')).toBe('button');
  });

  it('zeigt initial "Dunkel" Label im Light-Mode', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    expect(button.textContent).toContain('Dunkel');
    expect(button.getAttribute('aria-pressed')).toBe('false');
  });

  it('toggled zu Dark-Mode bei Click', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    fireEvent.click(button);
    expect(button.textContent).toContain('Hell');
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('persistiert Theme in localStorage', () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByTestId('theme-toggle'));
    expect(window.localStorage.getItem('theme')).toBe('dark');
  });

  it('toggled zurueck zu Light-Mode bei zweitem Click', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    fireEvent.click(button);
    fireEvent.click(button);
    expect(button.textContent).toContain('Dunkel');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(window.localStorage.getItem('theme')).toBe('light');
  });

  it('aria-label wechselt mit Theme', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    expect(button.getAttribute('aria-label')).toMatch(/Dunkles/);
    fireEvent.click(button);
    expect(button.getAttribute('aria-label')).toMatch(/Helles/);
  });

  it('Icon ist aria-hidden (dekorativ)', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    const icon = button.querySelector('[aria-hidden="true"]');
    expect(icon).not.toBeNull();
  });

  it('hat focus-visible Ring-Klassen fuer Keyboard-Nutzer', () => {
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    expect(button.className).toMatch(/focus-visible:ring/);
  });

  it('liest localStorage beim Mount', () => {
    window.localStorage.setItem('theme', 'dark');
    render(<ThemeToggle />);
    const button = screen.getByTestId('theme-toggle');
    expect(button.textContent).toContain('Hell');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});
