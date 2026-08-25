import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  applyThemeToDom,
  detectSystemPreference,
  persistTheme,
  readStoredTheme,
  resolveInitialTheme,
  toggleTheme,
} from './theme';

/**
 * Sprint U-50 (2026-06-06): Tests fuer Theme-Helper.
 *
 * Bewusst pure-Helper-Tests ohne React-Komponente — der Toggle-Button
 * hat seinen eigenen Test in components/ThemeToggle.test.tsx.
 */

describe('toggleTheme', () => {
  it('light -> dark', () => {
    expect(toggleTheme('light')).toBe('dark');
  });

  it('dark -> light', () => {
    expect(toggleTheme('dark')).toBe('light');
  });
});


describe('readStoredTheme', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('liefert null bei leerem Storage', () => {
    expect(readStoredTheme()).toBeNull();
  });

  it('liefert "light" wenn gespeichert', () => {
    window.localStorage.setItem('theme', 'light');
    expect(readStoredTheme()).toBe('light');
  });

  it('liefert "dark" wenn gespeichert', () => {
    window.localStorage.setItem('theme', 'dark');
    expect(readStoredTheme()).toBe('dark');
  });

  it('liefert null bei ungueltigem Wert', () => {
    window.localStorage.setItem('theme', 'rainbow');
    expect(readStoredTheme()).toBeNull();
  });
});


describe('persistTheme', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('schreibt "dark" in localStorage', () => {
    persistTheme('dark');
    expect(window.localStorage.getItem('theme')).toBe('dark');
  });

  it('schreibt "light" in localStorage', () => {
    persistTheme('light');
    expect(window.localStorage.getItem('theme')).toBe('light');
  });
});


describe('detectSystemPreference', () => {
  it('liefert "dark" wenn matchMedia(prefers-color-scheme: dark) matched', () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    expect(detectSystemPreference()).toBe('dark');
    window.matchMedia = original;
  });

  it('liefert "light" wenn nicht matched', () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    expect(detectSystemPreference()).toBe('light');
    window.matchMedia = original;
  });
});


describe('resolveInitialTheme', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('localStorage hat Vorrang vor System-Preference', () => {
    window.localStorage.setItem('theme', 'light');
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    expect(resolveInitialTheme()).toBe('light');
    window.matchMedia = original;
  });

  it('faellt auf System-Preference zurueck wenn kein storage', () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    expect(resolveInitialTheme()).toBe('dark');
    window.matchMedia = original;
  });
});


describe('applyThemeToDom', () => {
  afterEach(() => {
    document.documentElement.classList.remove('dark');
    delete document.documentElement.dataset.theme;
  });

  it('fuegt "dark"-Klasse hinzu bei dark-Theme', () => {
    applyThemeToDom('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('entfernt "dark"-Klasse bei light-Theme', () => {
    document.documentElement.classList.add('dark');
    applyThemeToDom('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.documentElement.dataset.theme).toBe('light');
  });
});
