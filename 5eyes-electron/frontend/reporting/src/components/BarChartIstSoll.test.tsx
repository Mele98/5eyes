import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { chartPalette, colors } from '@/design/tokens';
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
    expect(screen.getByText('-10.0 %')).toBeInTheDocument();
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
  it('IST = Ink, SOLL = Akzent (chartPalette.ist / chartPalette.soll)', () => {
    // Token-Vertrag: IST ist Ink, SOLL ist Akzent
    expect(chartPalette.ist).toBe(colors.ink.DEFAULT);
    expect(chartPalette.soll).toBe(colors.accent.DEFAULT);
    render(<BarChartIstSoll items={[AKTIEN]} />);
    const ist = screen.getByTestId('bar-ist-fill');
    const soll = screen.getByTestId('bar-soll-fill');
    expect(ist.className.split(/\s+/)).toContain('bg-ink');
    expect(ist.className.split(/\s+/)).not.toContain('bg-accent');
    expect(soll.className.split(/\s+/)).toContain('bg-accent');
    expect(soll.className.split(/\s+/)).not.toContain('bg-accent-subtle');
  });

  it('Zahlen in tabellarischen Ziffern, Drift mit fester Nachkommastelle', () => {
    render(<BarChartIstSoll items={[
      { label: 'A', ist_bps: 1200, soll_bps: 2000, drift_bps: -800 },
      { label: 'B', ist_bps: 1234, soll_bps: 1000, drift_bps: 234 },
    ]} />);
    const drifts = screen.getAllByTestId('bar-drift');
    expect(drifts.map((d) => d.textContent)).toEqual(['-8.0 %', '+2.3 %']);
    for (const d of drifts) expect(d.closest('.tabular-nums')).not.toBeNull();
    expect(screen.getByText('IST 12.0 %', { normalizer: (t) => t.replace(/\s+/g, ' ') }).className).toMatch(/tabular-nums/);
  });
});
