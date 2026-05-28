import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BarChartIstSoll } from './BarChartIstSoll';

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
