/**
 * Sprint U-47 (Roadmap-Punkt 47, 2026-06-01): Tests fuer Sub-App
 * Print-CSS.
 *
 * Strategie
 * ---------
 * Vitest in jsdom kann zwar @media-print-Rules nicht echt anwenden
 * (kein print-preview-Renderer), aber wir koennen das CSS-File parsen
 * und auf die Pflicht-Inhalte verifizieren — das fängt Drift in der
 * Print-Konfiguration zuverlässig.
 *
 * Was getestet wird
 * - @page A4-Definition + 20mm Margins (gleich wie Server-PDF)
 * - .no-print -> display:none
 * - .print-only -> display:block in print
 * - .page-break-* Helper existieren
 * - print-color-adjust:exact (sonst werden Status-Farben blass)
 * - Tabellen + figures haben page-break-inside:avoid
 * - Externe Links bekommen URL-After-Pseudo
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';


// Globals-CSS einmal laden, nicht pro Test re-readen
const GLOBALS_CSS_PATH = join(__dirname, 'globals.css');
const css = readFileSync(GLOBALS_CSS_PATH, 'utf8');


// ---------------------------------------------------------------------------
// @media print Block existiert + ist nicht-trivial
// ---------------------------------------------------------------------------

describe('Print-CSS — @media print Block', () => {
  it('enthaelt einen @media print Block', () => {
    expect(css).toMatch(/@media\s+print\s*\{/);
  });

  it('hat einen substantiellen Print-Block (> 100 Zeichen)', () => {
    const match = css.match(/@media\s+print\s*\{([\s\S]+?)\n\}/);
    expect(match).not.toBeNull();
    // Letzter passender Block nach unserem U-47-Refactor
    const blocks = [...css.matchAll(/@media\s+print\s*\{([\s\S]+?)\}\s*(?=$|@|\n[a-zA-Z\.])/g)];
    const lastBlock = blocks[blocks.length - 1]?.[1] ?? '';
    expect(lastBlock.length).toBeGreaterThan(100);
  });
});


// ---------------------------------------------------------------------------
// @page A4-Konfiguration
// ---------------------------------------------------------------------------

describe('Print-CSS — @page A4-Konfiguration', () => {
  it('setzt @page size: A4', () => {
    expect(css).toMatch(/@page\s*\{[^}]*size:\s*A4/i);
  });

  it('setzt @page margin: 20mm (gleich wie Server-PDF)', () => {
    expect(css).toMatch(/@page\s*\{[^}]*margin:\s*20mm/i);
  });
});


// ---------------------------------------------------------------------------
// .no-print / .print-only / Page-Break-Helper
// ---------------------------------------------------------------------------

describe('Print-CSS — Visibility-Helper', () => {
  it('.no-print -> display:none im Print', () => {
    // Muss im @media print Block sein
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\.no-print\s*\{[^}]*display:\s*none/i);
  });

  it('.print-only -> default hidden, im Print sichtbar', () => {
    // Default (ausserhalb @media print)
    expect(css).toMatch(/\.print-only\s*\{[^}]*display:\s*none/i);
    // Im Print-Block: sichtbar
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\.print-only\s*\{[^}]*display:\s*block/i);
  });
});


describe('Print-CSS — Page-Break-Helper', () => {
  it('.page-break-before erzwingt Seitenumbruch vor Element', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\.page-break-before\s*\{[^}]*page-break-before:\s*always/i);
  });

  it('.page-break-after erzwingt Seitenumbruch nach Element', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\.page-break-after\s*\{[^}]*page-break-after:\s*always/i);
  });

  it('.page-break-avoid verhindert Seitenumbruch IM Element', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\.page-break-avoid\s*\{[^}]*page-break-inside:\s*avoid/i);
  });

  it('alle 3 Page-Break-Helper haben CSS-3 break-* aliases (Browser-Compat)', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/break-before:\s*page/i);
    expect(printBlock).toMatch(/break-after:\s*page/i);
    expect(printBlock).toMatch(/break-inside:\s*avoid/i);
  });
});


// ---------------------------------------------------------------------------
// Farb-Treue (kritisch fuer Ampel-Pills)
// ---------------------------------------------------------------------------

describe('Print-CSS — Farb-Treue', () => {
  it('-webkit-print-color-adjust: exact gesetzt', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/-webkit-print-color-adjust:\s*exact/i);
  });

  it('print-color-adjust: exact (standard) gesetzt', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(/\bprint-color-adjust:\s*exact/i);
  });
});


// ---------------------------------------------------------------------------
// Tabellen + Figures werden NICHT mitten umbrochen
// ---------------------------------------------------------------------------

describe('Print-CSS — Anti-Bruch fuer Tabellen + figures', () => {
  it('tr/figure/.status-pill haben page-break-inside:avoid', () => {
    const printBlock = _extractPrintBlock(css);
    // matcht "tr, figure, .status-pill {" mit page-break-inside:avoid drin
    expect(printBlock).toMatch(
      /tr\s*,\s*figure\s*,\s*\.status-pill\s*\{[^}]*page-break-inside:\s*avoid/i,
    );
  });
});


// ---------------------------------------------------------------------------
// Externe URLs werden im Druck ausgeschrieben (Audit-Trail)
// ---------------------------------------------------------------------------

describe('Print-CSS — URL-Audit-Trail', () => {
  it('Externe Links bekommen URL als ::after-Content', () => {
    const printBlock = _extractPrintBlock(css);
    expect(printBlock).toMatch(
      /a\[href\^="http"\]::after\s*\{[^}]*content:\s*["']\s*\(["']\s*attr\(href\)/i,
    );
  });
});


// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/**
 * Extrahiert den Inhalt des @media-print-Blocks fuer fokussierte Asserts.
 * Naive brace-matching — geht davon aus dass keine schraegen nested-{}
 * im Block sind (in unserem CSS-Style stimmt das).
 */
function _extractPrintBlock(fullCss: string): string {
  const startIdx = fullCss.search(/@media\s+print\s*\{/);
  if (startIdx === -1) return '';
  const blockStart = fullCss.indexOf('{', startIdx);
  // Walk braces
  let depth = 1;
  let i = blockStart + 1;
  while (i < fullCss.length && depth > 0) {
    const ch = fullCss[i];
    if (ch === '{') depth++;
    else if (ch === '}') depth--;
    i++;
  }
  return fullCss.slice(blockStart + 1, i - 1);
}
