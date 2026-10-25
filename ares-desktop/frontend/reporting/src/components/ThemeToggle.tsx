import { useEffect, useState } from 'react';
import {
  applyThemeToDom,
  persistTheme,
  resolveInitialTheme,
  toggleTheme,
  type Theme,
} from '@/lib/theme';

/**
 * Sprint U-50 (2026-06-06): Dark-Mode-Toggle als kleiner Button.
 *
 * Pattern: state-loses Button — Theme lebt in <html>-Klasse + localStorage.
 * Beim Mount wird der initiale Theme aus localStorage oder
 * System-Preference resolved und angewandt.
 *
 * a11y: aria-label wechselt mit aktuellem Theme, role=button (Default).
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('light');

  useEffect(() => {
    const initial = resolveInitialTheme();
    setTheme(initial);
    applyThemeToDom(initial);
  }, []);

  const handleToggle = () => {
    const next = toggleTheme(theme);
    setTheme(next);
    applyThemeToDom(next);
    persistTheme(next);
  };

  const isDark = theme === 'dark';
  return (
    <button
      type="button"
      data-testid="theme-toggle"
      onClick={handleToggle}
      aria-label={isDark ? 'Helles Theme aktivieren' : 'Dunkles Theme aktivieren'}
      aria-pressed={isDark}
      className="inline-flex items-center gap-2 rounded border border-rule bg-canvas-panel px-3 py-1.5 text-micro uppercase tracking-widest text-ink-subtle hover:border-rule-strong hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 dark:border-ink-muted dark:bg-canvas-subtle"
    >
      <span aria-hidden="true" className="text-caption">
        {isDark ? '☼' : '☽'}
      </span>
      <span>{isDark ? 'Hell' : 'Dunkel'}</span>
    </button>
  );
}
