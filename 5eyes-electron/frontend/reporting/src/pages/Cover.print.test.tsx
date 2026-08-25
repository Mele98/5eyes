/**
 * Sprint U-52 (Roadmap-Punkt 52, 2026-06-02): Cover-Animation print-aware.
 *
 * Hintergrund
 * -----------
 * Cover.tsx nutzt framer-motion mit initial={{ opacity: 0, y: 12 }}.
 * Wenn der PDF-Snapshot vor Animation-Ende ausgeloest wird (z.B.
 * Headless-Chromium), waeren Cover-Titel + Subtitle UNSICHTBAR oder
 * verschoben.
 *
 * Fix-Strategy (Belt-and-Suspenders)
 * ----------------------------------
 * 1. CSS @media print: alle Animationen sofort beenden, opacity 1
 *    und transform none erzwingen (globals.css U-52-Block).
 * 2. Cover.tsx: useReducedMotion() — bei reduce=true wird
 *    initial=false gesetzt, KEINE Fade-Animation gerendert.
 * 3. prefers-reduced-motion CSS-Media-Query als a11y-Bonus.
 *
 * Diese Test-Suite verifiziert Schicht 1+2.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { Cover } from './Cover';
import type { CoverData } from '@/api/types';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS_PATH = resolve(__dirname, '../styles/globals.css');

const COVER_DATA: CoverData = {
  title: 'Test Advisory Report',
  subtitle: 'Print-Awareness Audit',
  client_name: 'Max Muster',
  mandate_number: 'MX-TEST-01',
  advisor_name: 'Anna Berater',
  report_date: '2026-06-02',
};

// ---------------------------------------------------------------------------
// Schicht 1: CSS-Audit (parse globals.css)
// ---------------------------------------------------------------------------

describe('U-52 CSS print-awareness', () => {
  const css = readFileSync(GLOBALS_CSS_PATH, 'utf-8');

  it('kills animations under @media print', () => {
    const printBlockMatch = css.match(/@media print\s*\{([\s\S]*?)\n\}/);
    expect(printBlockMatch, 'Kein @media print Block gefunden').toBeTruthy();
    const printBlock = printBlockMatch![1];
    expect(printBlock).toMatch(/animation-duration:\s*0s/);
    expect(printBlock).toMatch(/transition-duration:\s*0s/);
  });

  it('forces opacity 1 + transform none for testid elements in print', () => {
    const printBlockMatch = css.match(/@media print\s*\{([\s\S]*?)\n\}/);
    const printBlock = printBlockMatch![1];
    expect(printBlock).toMatch(/\[data-testid\][\s\S]*?opacity:\s*1\s*!important/);
    expect(printBlock).toMatch(/\[data-testid\][\s\S]*?transform:\s*none\s*!important/);
  });

  it('respects prefers-reduced-motion (a11y bonus)', () => {
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    const reducedMatch = css.match(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/,
    );
    expect(reducedMatch).toBeTruthy();
    const reducedBlock = reducedMatch![1];
    expect(reducedBlock).toMatch(/animation-duration/);
    expect(reducedBlock).toMatch(/transition-duration/);
  });
});

// ---------------------------------------------------------------------------
// Schicht 2: Cover-Component respektiert useReducedMotion
// ---------------------------------------------------------------------------

describe('U-52 Cover useReducedMotion', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query.includes('prefers-reduced-motion: reduce'),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders cover title even with prefers-reduced-motion', () => {
    render(<Cover data={COVER_DATA} />);
    expect(screen.getByTestId('cover-title')).toHaveTextContent(
      'Test Advisory Report',
    );
  });

  it('renders all key cover fields (regression smoke)', () => {
    render(<Cover data={COVER_DATA} />);
    expect(screen.getByTestId('cover-title')).toBeInTheDocument();
    expect(screen.getByTestId('cover-client-name')).toHaveTextContent(
      'Max Muster',
    );
    expect(screen.getByTestId('cover-advisor-name')).toHaveTextContent(
      'Anna Berater',
    );
    expect(screen.getByTestId('cover-report-date')).toHaveTextContent(
      '02.06.2026',
    );
  });

  it('main section has data-testid cover-main-section (CSS-target)', () => {
    render(<Cover data={COVER_DATA} />);
    expect(
      screen.getByTestId('cover-main-section'),
    ).toBeInTheDocument();
  });
});
