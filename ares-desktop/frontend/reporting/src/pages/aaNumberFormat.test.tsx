/**
 * REPORT-NUMBER-FORMAT-001: Zahlenformat der AA-Sektionen (8 Asset
 * Allocation, 13 Building Blocks) und des Faechers (11).
 *
 * Vertrag (identisch zu lib/format.ts und PDF swiss_numbers.py):
 * - Prozent mit GENAU einer Nachkommastelle je Spalte und Leerzeichen
 *   vor "%" ("12.0 %", nicht "12%" neben "8.4%")
 * - Zahlenspalten mit tabellarischen Ziffern (font-variant-numeric)
 */
import { render } from '@testing-library/react';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { MemoryRouter } from 'react-router-dom';
import { fileURLToPath } from 'url';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({ role: 'advisor', canEdit: false, loading: false, error: null }),
}));
vi.mock('@/api/useReportNotes', () => ({
  useReportNotes: () => ({
    state: 'ready',
    data: null,
    error: null,
    reload: () => {},
    saving: false,
    saveError: null,
    save: async () => {},
  }),
}));

import { AssetAllocation } from './AssetAllocation';
import { BuildingBlocks } from './BuildingBlocks';
import { makeAssetAllocation, makeBuildingBlocks } from '@/test/fixtures';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, '..', 'styles', 'globals.css');

/** Alle Prozentangaben im gerenderten Text (inkl. Varianten ohne Leerzeichen). */
function percentTokens(text: string): string[] {
  return text.match(/[+\-\u2212]?\d+(?:\.\d+)?\s?%/g) ?? [];
}

describe('AA-Sektionen: einheitliches Prozentformat', () => {
  it('Sektion 8: jede Prozentzahl hat genau 1 Nachkommastelle und " %"', () => {
    const data = makeAssetAllocation();
    // Edge-Werte: ganze Prozent, kleine Drift, 0-Drift
    data.items = [
      { ...data.items[0]!, ist_bps: 1200, soll_bps: 2000, drift_bps: -800 },
      { ...data.items[1]!, ist_bps: 5840, soll_bps: 5000, drift_bps: 840 },
    ];
    const { container } = render(
      <MemoryRouter>
        <AssetAllocation data={data} mandateId="m" onReload={() => {}} />
      </MemoryRouter>,
    );
    const tokens = percentTokens(container.textContent ?? '');
    expect(tokens.length).toBeGreaterThanOrEqual(6);
    // AA-UX-FORMAT-001: geschuetztes Leerzeichen vor %, Minus U+2212.
    for (const t of tokens) expect(t).toMatch(/^[+\u2212]?\d+\.\d\u00a0%$/);
  });

  it('Sektion 13: Ziel- und Bandbreitenspalten mit 1 Nachkommastelle und " %"', () => {
    const { container } = render(
      <MemoryRouter>
        <BuildingBlocks data={makeBuildingBlocks()} />
      </MemoryRouter>,
    );
    const cells = Array.from(container.querySelectorAll('td.text-right'));
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      for (const t of percentTokens(cell.textContent ?? '')) {
        expect(t).toMatch(/^[+\u2212]?\d+\.\d\u00a0%$/);
      }
    }
  });
});

describe('Zahlenspalten: tabellarische Ziffern', () => {
  it('globals.css setzt font-variant-numeric: tabular-nums fuer font-mono und rechtsbuendige Zellen', () => {
    const css = readFileSync(GLOBALS_CSS, 'utf8');
    const rule = css.match(/\.font-mono,\s*td\.text-right,\s*th\.text-right\s*\{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });
});
