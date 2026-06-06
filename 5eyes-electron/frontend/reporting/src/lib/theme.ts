/**
 * Sprint U-50 (2026-06-06): Theme-Verwaltung fuer Sub-App Dark-Mode.
 *
 * Auswahl-Logik (in dieser Reihenfolge):
 *   1. localStorage 'theme' (User-Override)
 *   2. window.matchMedia('(prefers-color-scheme: dark)') (System-Preference)
 *   3. 'light' (Editorial-Default)
 *
 * Branding-Disziplin: Dark-Mode ist EINE RUHIGE Variante mit Navy-
 * Hintergrund + Offwhite-Text, KEIN knalliger 'Hacker-Modus'. Bleibt
 * Swiss-Private-Banking-Aesthetik treu.
 */
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

export function readStoredTheme(): Theme | null {
  if (typeof window === 'undefined' || !window.localStorage) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark') return raw;
    return null;
  } catch {
    return null;
  }
}

export function detectSystemPreference(): Theme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    return mq.matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function resolveInitialTheme(): Theme {
  const stored = readStoredTheme();
  if (stored) return stored;
  return detectSystemPreference();
}

export function applyThemeToDom(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
  root.dataset.theme = theme;
}

export function persistTheme(theme: Theme): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Quota oder Disabled-Storage: bewusst ignorieren — Toggle ist
    // session-local Fallback.
  }
}

export function toggleTheme(current: Theme): Theme {
  return current === 'dark' ? 'light' : 'dark';
}
