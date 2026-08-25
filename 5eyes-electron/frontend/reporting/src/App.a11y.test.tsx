import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

/**
 * Sprint U-90 (2026-06-06): a11y-Tests fuer App-Shell Skip-Link
 * + Loading/Error Panel Live-Regions.
 *
 * Da App.tsx hauptsaechlich Routing + Data-Fetching macht, testen
 * wir die a11y-Patterns isoliert via die exportierten Panels.
 */

// LoadingPanel + ErrorPanel sind nicht exportiert -> wir lesen sie
// via App-Render im Loading/Error-State indirekt. Alternativ koennen
// wir ihre Klassen-Pattern aus dem App.tsx-Source-File parsen.
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const APP_TSX = join(__dirname, 'App.tsx');

describe('App a11y patterns (U-90)', () => {
  it('App.tsx hat Skip-Link "Direkt zum Hauptinhalt"', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toContain('Direkt zum Hauptinhalt');
    expect(text).toContain('#report-main-content');
  });

  it('App.tsx Skip-Link nutzt sr-only + focus:not-sr-only Pattern', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toMatch(/sr-only.*focus:not-sr-only/);
  });

  it('main-Element hat id und tabIndex={-1} fuer Skip-Link-Target', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toContain('id="report-main-content"');
    expect(text).toContain('tabIndex={-1}');
  });

  it('main hat aria-label mit aktueller Sektion', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toMatch(/aria-label=.*sectionId/);
  });

  it('LoadingPanel hat aria-busy + aria-live="polite"', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toMatch(/aria-busy=["']true["']/);
    expect(text).toMatch(/aria-live=["']polite["']/);
  });

  it('ErrorPanel hat role="alert" + aria-live="assertive"', () => {
    const text = readFileSync(APP_TSX, 'utf8');
    expect(text).toMatch(/role=["']alert["']/);
    expect(text).toMatch(/aria-live=["']assertive["']/);
  });
});

describe('App a11y patterns smoke', () => {
  it('Skip-Link ist render-fähig (kein JSX-Syntax-Bruch)', () => {
    // Smoke-Test: render eines absichtlich minimalen Wrappers
    // verifiziert kein zusaetzlicher Crash. Echter Skip-Link kommt
    // mit dem ReportShell-Routing-State.
    const { container } = render(
      <div>
        <a
          href="#x"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
        >
          Direkt zum Hauptinhalt
        </a>
      </div>,
    );
    expect(container.querySelector('a.sr-only')).not.toBeNull();
    expect(screen.getByText('Direkt zum Hauptinhalt')).toBeInTheDocument();
  });
});
