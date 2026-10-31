import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { assetClassKey, chartPalette, colors, soll as sollToken } from '@/design/tokens';
import { BarChartIstSoll, bandStatus } from './BarChartIstSoll';

describe('BarChartIstSoll', () => {
  const items = [
    {
      label: 'Aktien',
      ist_bps: 2500,
      soll_bps: 3500,
      drift_bps: -1000,
      band_min_bps: 3000,
      band_max_bps: 4000,
    },
    {
      label: 'Obligationen',
      ist_bps: 6000,
      soll_bps: 5000,
      drift_bps: 1000,
    },
  ];

  it('rendert alle Item-Labels', () => {
    render(<BarChartIstSoll items={items} />);
    expect(screen.getByText('Aktien')).toBeInTheDocument();
    expect(screen.getByText('Obligationen')).toBeInTheDocument();
  });

  it('rendert IST- und SOLL-Prozente', () => {
    render(<BarChartIstSoll items={items} />);
    // IST 25.0 % und SOLL 35.0 % für Aktien
    expect(screen.getByText(/IST.*25\.0 %/)).toBeInTheDocument();
    expect(screen.getByText(/SOLL.*35\.0 %/)).toBeInTheDocument();
  });

  it('rendert Drift mit Vorzeichen', () => {
    render(<BarChartIstSoll items={items} />);
    // AA-UX-FORMAT-001: Minus ist U+2212, nie Bindestrich.
    expect(screen.getByText('\u221210.0 %')).toBeInTheDocument();
    expect(screen.queryByText('-10.0 %')).toBeNull();
    expect(screen.getByText('+10.0 %')).toBeInTheDocument();
  });

  it('färbt grossen Drift rot ein (>= 15 %)', () => {
    const { container } = render(<BarChartIstSoll items={[
      { label: 'X', ist_bps: 5000, soll_bps: 2000, drift_bps: 3000 },
    ]} />);
    const drift = container.querySelector('.text-status-rot');
    expect(drift).not.toBeNull();
  });

  it('färbt kleinen Drift grün ein (< threshold/2)', () => {
    const { container } = render(<BarChartIstSoll items={[
      { label: 'X', ist_bps: 3000, soll_bps: 3000, drift_bps: 0 },
    ]} />);
    const drift = container.querySelector('.text-status-gruen');
    expect(drift).not.toBeNull();
  });

  it('rendert leere Liste mit Hinweis', () => {
    render(<BarChartIstSoll items={[]} />);
    expect(screen.getByText(/Keine Datenpunkte/)).toBeInTheDocument();
  });

  it('zeigt Toleranzband nur bei showBands=true', () => {
    const { container, rerender } = render(<BarChartIstSoll items={items} showBands />);
    const bandsOn = container.querySelectorAll('.bg-gold-subtle\\/40');
    expect(bandsOn.length).toBeGreaterThan(0);

    rerender(<BarChartIstSoll items={items} showBands={false} />);
    const bandsOff = document.querySelectorAll('.bg-gold-subtle\\/40');
    expect(bandsOff.length).toBe(0);
  });
});

const AKTIEN = {
  label: 'Aktien',
  ist_bps: 2500,
  soll_bps: 3500,
  drift_bps: -1000,
  band_min_bps: 3000,
  band_max_bps: 4000,
};

describe('BarChartIstSoll — Drift-Farbe nach Bandbreite (REPORT-DRIFT-BAND-COLOR-001)', () => {
  it('Liquiditaet Band 0–10 %, IST 18 % (Drift +8 pp): ausserhalb -> Warnfarbe + Klartext', () => {
    render(<BarChartIstSoll showBands items={[
      { label: 'Liquidität', ist_bps: 1800, soll_bps: 1000, drift_bps: 800, band_min_bps: 0, band_max_bps: 1000 },
    ]} />);
    const row = screen.getByTestId('bar-row-Liquidität');
    expect(row.getAttribute('data-band-status')).toBe('outside');
    expect(screen.getByTestId('bar-drift').closest('.text-status-rot')).not.toBeNull();
    expect(row).toHaveTextContent('ausserhalb Band');
  });

  it('grosser Drift INNERHALB einer breiten Bandbreite: neutral, nicht rot', () => {
    render(<BarChartIstSoll showBands items={[
      { label: 'Aktien', ist_bps: 5800, soll_bps: 3000, drift_bps: 2800, band_min_bps: 2000, band_max_bps: 6000 },
    ]} />);
    const row = screen.getByTestId('bar-row-Aktien');
    expect(row.getAttribute('data-band-status')).toBe('inside');
    expect(row.querySelector('.text-status-rot')).toBeNull();
    expect(row.querySelector('.text-status-gruen')).toBeNull();
    expect(screen.getByTestId('bar-drift').closest('.text-ink-muted')).not.toBeNull();
    expect(row).not.toHaveTextContent('ausserhalb Band');
  });

  it('Bandgrenzen sind inklusive (wie services/depot_check.py)', () => {
    expect(bandStatus({ label: 'x', ist_bps: 4000, soll_bps: 3500, drift_bps: 500, band_min_bps: 3000, band_max_bps: 4000 })).toBe('inside');
    expect(bandStatus({ label: 'x', ist_bps: 3000, soll_bps: 3500, drift_bps: -500, band_min_bps: 3000, band_max_bps: 4000 })).toBe('inside');
    expect(bandStatus({ label: 'x', ist_bps: 4001, soll_bps: 3500, drift_bps: 501, band_min_bps: 3000, band_max_bps: 4000 })).toBe('outside');
    expect(bandStatus({ label: 'x', ist_bps: 2999, soll_bps: 3500, drift_bps: -501, band_min_bps: 3000, band_max_bps: 4000 })).toBe('outside');
  });

  it('Backend-Flag in_band hat Vorrang vor der eigenen Rechnung', () => {
    expect(bandStatus({ label: 'x', ist_bps: 3500, soll_bps: 3500, drift_bps: 0, band_min_bps: 3000, band_max_bps: 4000, in_band: false })).toBe('outside');
    expect(bandStatus({ label: 'x', ist_bps: 9000, soll_bps: 3500, drift_bps: 5500, band_min_bps: 3000, band_max_bps: 4000, in_band: true })).toBe('inside');
  });

  it('ohne Bandbreite (fehlend, null oder 0/0) -> kein Bandstatus, Schwellen-Fallback', () => {
    expect(bandStatus({ label: 'x', ist_bps: 5000, soll_bps: 2000, drift_bps: 3000 })).toBeNull();
    expect(bandStatus({ label: 'x', ist_bps: 5000, soll_bps: 2000, drift_bps: 3000, band_min_bps: null, band_max_bps: null, in_band: null })).toBeNull();
    expect(bandStatus({ label: 'x', ist_bps: 5000, soll_bps: 2000, drift_bps: 3000, band_min_bps: 0, band_max_bps: 0 })).toBeNull();
    const { container } = render(<BarChartIstSoll items={[
      { label: 'USD', ist_bps: 5000, soll_bps: 2000, drift_bps: 3000, band_min_bps: 0, band_max_bps: 0 },
    ]} />);
    expect(container.querySelector('[data-band-status="none"] .text-status-rot')).not.toBeNull();
  });

  it('SOLL-Label nennt die Bandbreite im Report-Format (nur mit showBands)', () => {
    const { rerender } = render(<BarChartIstSoll showBands items={[AKTIEN]} />);
    expect(screen.getByText('SOLL 35.0 % · Band 30.0 % – 40.0 %')).toBeInTheDocument();
    rerender(<BarChartIstSoll items={[AKTIEN]} />);
    expect(screen.queryByText(/Band 30\.0 %/)).toBeNull();
  });
});

describe('BarChartIstSoll — Design-Tokens und Zahlenformat', () => {
  it('IST = Ink, SOLL = Brand-Gold (chartPalette.ist / chartPalette.soll)', () => {
    // AA-UX-COLORS-001: SOLL traegt den Brand-Akzent Gold wie in der App,
    // nicht mehr Petrol (gruenlich) -- Gruen bleibt "besser als IST".
    expect(chartPalette.ist).toBe(colors.ink.DEFAULT);
    expect(chartPalette.soll).toBe(sollToken.DEFAULT);
    expect(sollToken.DEFAULT).toBe('#8A6A1F');
    render(<BarChartIstSoll items={[AKTIEN]} />);
    const ist = screen.getByTestId('bar-ist-fill');
    const soll = screen.getByTestId('bar-soll-fill');
    expect(ist.className.split(/\s+/)).toContain('bg-ink');
    expect(ist.className.split(/\s+/)).not.toContain('bg-accent');
    expect(soll.className.split(/\s+/)).toContain('bg-soll');
    expect(soll.className.split(/\s+/)).toContain('dark:bg-soll-dark');
    expect(soll.className).not.toMatch(/bg-accent/);
  });

  it('Zahlen in tabellarischen Ziffern, Drift mit fester Nachkommastelle', () => {
    render(<BarChartIstSoll items={[
      { label: 'A', ist_bps: 1200, soll_bps: 2000, drift_bps: -800 },
      { label: 'B', ist_bps: 1234, soll_bps: 1000, drift_bps: 234 },
    ]} />);
    const drifts = screen.getAllByTestId('bar-drift');
    expect(drifts.map((d) => d.textContent)).toEqual(['\u22128.0\u00a0%', '+2.3\u00a0%']);
    for (const d of drifts) expect(d.closest('.tabular-nums')).not.toBeNull();
    expect(screen.getByText('IST 12.0 %', { normalizer: (t) => t.replace(/\s+/g, ' ') }).className).toMatch(/tabular-nums/);
  });
});

describe('BarChartIstSoll — Anlageklassen-Farbmarke (AA-UX-COLORS-001)', () => {
  it('Asset Allocation (showBands): jede Zeile traegt die Klassenfarbe aus den Tokens', () => {
    render(<BarChartIstSoll showBands items={[
      { label: 'Aktien', ist_bps: 3000, soll_bps: 3000, drift_bps: 0 },
      { label: 'Obligationen', ist_bps: 3000, soll_bps: 3000, drift_bps: 0 },
      { label: 'Immobilien', ist_bps: 1000, soll_bps: 1000, drift_bps: 0 },
      { label: 'Alternative', ist_bps: 1000, soll_bps: 1000, drift_bps: 0 },
      { label: 'Liquidität', ist_bps: 2000, soll_bps: 2000, drift_bps: 0 },
    ]} />);
    const swatches = screen.getAllByTestId('bar-swatch');
    expect(swatches.map((s) => s.getAttribute('data-asset-class'))).toEqual(['eq', 'bd', 're', 'alt', 'liq']);
    expect(swatches[0]!.className).toContain('bg-ac-eq');
    expect(swatches[0]!.className).toContain('dark:bg-ac-eq-dark');
  });

  it('FX/Branchen (ohne showBands): keine Klassenfarbe', () => {
    render(<BarChartIstSoll items={[{ label: 'USD', ist_bps: 1000, soll_bps: 1000, drift_bps: 0 }]} />);
    expect(screen.queryByTestId('bar-swatch')).toBeNull();
  });

  it('assetClassKey: Private Equity ist Alternative, nicht Aktien', () => {
    expect(assetClassKey('Private Equity')).toBe('alt');
    expect(assetClassKey('equities')).toBe('eq');
    expect(assetClassKey('Alternative / Gold')).toBe('alt');
    expect(assetClassKey('Liquiditaet')).toBe('liq');
    expect(assetClassKey('Externe Mandate')).toBe('oth');
  });
});
