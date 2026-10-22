/**
 * Sprint U-12 — Tests fuer MonteCarloPathsChart SVG-Komponente.
 *
 * Pruefen ULTRA-genau:
 * - SVG-Struktur (band + p50 + goal marker)
 * - a11y (title, desc, role)
 * - Defensive (mal-aligned -> null)
 * - Goal-Marker pro Status-Farbe
 * - Legende
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { GoalEntry, MonteCarloPaths } from '@/api/types';
import {
  GOAL_SCALE_CAP,
  MonteCarloPathsChart,
  computeYScale,
  makeYTickFormatter,
  niceStep,
} from './MonteCarloPathsChart';

function makeMc(overrides: Partial<MonteCarloPaths> = {}): MonteCarloPaths {
  const time_axis = Array.from({ length: 11 }, (_, i) => `${2026 + i}`);
  const start = 2_700_000_00;
  return {
    data_pending: false,
    time_axis,
    p5: time_axis.map((_, t) => Math.round(start * Math.pow(1.03, t))),
    p50: time_axis.map((_, t) => Math.round(start * Math.pow(1.05, t))),
    p75: time_axis.map((_, t) => Math.round(start * Math.pow(1.07, t))),
    n_paths: 1000,
    seed: 42,
    horizon_years: 10,
    initial_wealth_rappen: start,
    ...overrides,
  };
}

function makeGoal(overrides: Partial<GoalEntry> = {}): GoalEntry {
  return {
    goal_id: overrides.goal_id ?? 'g1',
    label: overrides.label ?? 'Pension 60',
    goal_type: overrides.goal_type ?? 'Vermoegen',
    target_amount_rappen: overrides.target_amount_rappen ?? 3_500_000_00,
    target_date: overrides.target_date ?? '2035-01-01',
    hardness: overrides.hardness ?? 'Primaer',
    probability_bps: overrides.probability_bps ?? null,
    status: overrides.status ?? '',
    outside_simulation_horizon:
      overrides.outside_simulation_horizon ?? false,
    evaluation_scope: overrides.evaluation_scope ?? 'priority_funded',
    funding_rank: overrides.funding_rank ?? null,
    failure_event_id: overrides.failure_event_id ?? null,
  };
}

describe('MonteCarloPathsChart — Happy Path', () => {
  it('rendert SVG mit Band + p50-Linie', () => {
    render(<MonteCarloPathsChart paths={makeMc()} goals={[]} />);
    expect(screen.getByTestId('mc-paths-chart')).toBeInTheDocument();
    expect(screen.getByTestId('mc-paths-band')).toBeInTheDocument();
    expect(screen.getByTestId('mc-paths-p50')).toBeInTheDocument();
  });

  it('SVG hat role="img" und aria-label', () => {
    const { container } = render(
      <MonteCarloPathsChart paths={makeMc()} goals={[]} />,
    );
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg!.getAttribute('role')).toBe('img');
    // figure hat aria-label
    expect(
      screen.getByLabelText(/Monte-Carlo-Pfade.*Quantile/i),
    ).toBeInTheDocument();
  });

  it('SVG enthaelt title und desc fuer screen reader', () => {
    const { container } = render(
      <MonteCarloPathsChart paths={makeMc()} goals={[]} />,
    );
    const title = container.querySelector('svg > title');
    const desc = container.querySelector('svg > desc');
    expect(title?.textContent).toMatch(/Monte-Carlo Wealth-Pfade/);
    expect(desc?.textContent).toMatch(/simulierte Pfade/);
  });
});

describe('MonteCarloPathsChart — Defensive', () => {
  it('rendert null wenn time_axis < 2 Eintraege', () => {
    const mc = makeMc({
      time_axis: ['2026'],
      p5: [100],
      p50: [100],
      p75: [100],
    });
    const { container } = render(
      <MonteCarloPathsChart paths={mc} goals={[]} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });

  it('charts-2: rendert null bei nicht-finitem Wert (NaN/Infinity) in den Pfaden', () => {
    const base = makeMc();
    const p50 = [...base.p50!];
    p50[3] = Number.NaN; // z.B. Backend serialisiert NaN
    const { container } = render(
      <MonteCarloPathsChart paths={makeMc({ p50 })} goals={[]} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });

  it('rendert null wenn p5-Laenge != time_axis-Laenge', () => {
    const mc = makeMc();
    mc.p5 = mc.p5!.slice(0, 5);
    const { container } = render(
      <MonteCarloPathsChart paths={mc} goals={[]} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });

  it('rendert null wenn p50 fehlt', () => {
    const mc = makeMc();
    delete mc.p50;
    const { container } = render(
      <MonteCarloPathsChart paths={mc} goals={[]} />,
    );
    expect(container.querySelector('svg')).toBeNull();
  });
});

describe('MonteCarloPathsChart — Goal-Marker', () => {
  it('rendert Marker fuer Goal innerhalb der Zeitachse', () => {
    const goal = makeGoal({
      goal_id: 'pension',
      label: 'Pension mit 60',
      target_date: '2035-01-01',
      target_amount_rappen: 3_500_000_00,
    });
    render(<MonteCarloPathsChart paths={makeMc()} goals={[goal]} />);
    const marker = screen.getByTestId('goal-marker-pension');
    expect(marker).toBeInTheDocument();
    expect(marker.getAttribute('data-status')).toBe('erreichbar');
  });

  it('Marker-Farbe matched Status', () => {
    const goals: GoalEntry[] = [
      makeGoal({
        goal_id: 'easy',
        target_date: '2030-01-01',
        target_amount_rappen: 100_000_00,
      }),
      makeGoal({
        goal_id: 'hard',
        target_date: '2035-01-01',
        target_amount_rappen: 50_000_000_00, // unrealistic
      }),
    ];
    render(<MonteCarloPathsChart paths={makeMc()} goals={goals} />);
    expect(screen.getByTestId('goal-marker-easy').getAttribute('data-status')).toBe(
      'erreichbar',
    );
    expect(screen.getByTestId('goal-marker-hard').getAttribute('data-status')).toBe(
      'nicht_erreichbar',
    );
  });

  it('rendert KEINEN Marker fuer Goal jenseits des Horizonts', () => {
    const goal = makeGoal({
      goal_id: 'future',
      target_date: '2099-01-01',
    });
    render(<MonteCarloPathsChart paths={makeMc()} goals={[goal]} />);
    expect(screen.queryByTestId('goal-marker-future')).not.toBeInTheDocument();
  });

  it('rendert KEINEN Marker fuer Goal ohne valides target_date', () => {
    const goal = makeGoal({ goal_id: 'bad', target_date: '' });
    render(<MonteCarloPathsChart paths={makeMc()} goals={[goal]} />);
    expect(screen.queryByTestId('goal-marker-bad')).not.toBeInTheDocument();
  });

  it('rendert Goal-Label-Text neben dem Marker', () => {
    const goal = makeGoal({
      goal_id: 'pension',
      label: 'GOAL-LABEL-VISIBLE',
      target_date: '2030-01-01',
    });
    render(<MonteCarloPathsChart paths={makeMc()} goals={[goal]} />);
    expect(screen.getByText('GOAL-LABEL-VISIBLE')).toBeInTheDocument();
  });
});

describe('MonteCarloPathsChart — Legende', () => {
  it('Legacy-Payload (nur p5/p50/p75): Band ehrlich als 70 %, asymmetrisch', () => {
    render(<MonteCarloPathsChart paths={makeMc()} goals={[]} />);
    const legend = screen.getByTestId('mc-paths-legend');
    expect(legend).toHaveTextContent('Bandbreite P5–P75 (70 % der Verläufe, asymmetrisch)');
    expect(legend).toHaveTextContent(/Median \(P50\)/);
    expect(legend).toHaveTextContent(/erreichbar/);
    expect(legend).toHaveTextContent(/Knapp/);
    expect(legend).toHaveTextContent(/Schwierig/);
    // Die fruehere, falsche Angabe "90%" fuer p5–p75 darf nie mehr erscheinen
    expect(legend.textContent).not.toMatch(/90\s?%/);
    expect(screen.queryByTestId('mc-paths-legend-inner')).toBeNull();
    expect(screen.getByLabelText(/Quantilen P5, P50 und P75/)).toBeInTheDocument();
  });

  it('Fan-Payload: symmetrische Baender P10–P90 (80 %) und P25–P75 (50 %)', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[]} />);
    expect(screen.getByTestId('mc-paths-legend-outer')).toHaveTextContent(
      'Bandbreite P10–P90 (8 von 10 Verläufen)',
    );
    expect(screen.getByTestId('mc-paths-legend-inner')).toHaveTextContent(
      'Kernbereich P25–P75 (5 von 10 Verläufen)',
    );
    expect(screen.getByTestId('mc-paths-legend')).not.toHaveTextContent(/P5–/);
    expect(screen.getByLabelText(/Quantilen P10, P25, P50, P75 und P90/)).toBeInTheDocument();
  });
});

/** Fixture mit allen sechs Quantilen (wie das Backend ab REPORT-FAN-CHART-BANDS-001). */
function makeMcFan(overrides: Partial<MonteCarloPaths> = {}): MonteCarloPaths {
  const time_axis = Array.from({ length: 11 }, (_, i) => `${2026 + i}`);
  const start = 2_700_000_00;
  const g = (r: number) => time_axis.map((_, t) => Math.round(start * Math.pow(r, t)));
  return makeMc({
    time_axis,
    p5: g(1.02),
    p10: g(1.03),
    p25: g(1.04),
    p50: g(1.05),
    p75: g(1.06),
    p90: g(1.075),
    ...overrides,
  });
}

function parsePoints(attr: string | null): Array<[number, number]> {
  return (attr ?? '')
    .trim()
    .split(/\s+/)
    .map((pt) => pt.split(',').map(Number) as [number, number]);
}

describe('MonteCarloPathsChart — Faecher-Baender exakt', () => {
  it('aeusseres Band = p90 oben / p10 unten, inneres = p75 / p25 (gleiche y-Abbildung wie Median)', () => {
    const mc = makeMcFan();
    render(<MonteCarloPathsChart paths={mc} goals={[]} />);
    const n = mc.time_axis!.length;
    // Lineare y-Abbildung y = a - b*v aus zwei Median-Punkten rekonstruieren
    const med = parsePoints(screen.getByTestId('mc-paths-p50').getAttribute('points'));
    const b = (med[0]![1] - med[n - 1]![1]) / (mc.p50![n - 1]! - mc.p50![0]!);
    const a = med[0]![1] + b * mc.p50![0]!;
    const yOf = (v: number) => a - b * v;

    const outer = parsePoints(screen.getByTestId('mc-paths-band').getAttribute('points'));
    const inner = parsePoints(screen.getByTestId('mc-paths-band-inner').getAttribute('points'));
    expect(outer).toHaveLength(2 * n);
    expect(inner).toHaveLength(2 * n);
    for (let i = 0; i < n; i++) {
      // obere Kante vorwaerts, untere rueckwaerts
      expect(outer[i]![1]).toBeCloseTo(yOf(mc.p90![i]!), 6);
      expect(outer[2 * n - 1 - i]![1]).toBeCloseTo(yOf(mc.p10![i]!), 6);
      expect(inner[i]![1]).toBeCloseTo(yOf(mc.p75![i]!), 6);
      expect(inner[2 * n - 1 - i]![1]).toBeCloseTo(yOf(mc.p25![i]!), 6);
      // gleiche x-Koordinaten wie der Median
      expect(outer[i]![0]).toBeCloseTo(med[i]![0], 6);
    }
  });

  it('Legacy: genau ein Band p5–p75, kein inneres Band', () => {
    render(<MonteCarloPathsChart paths={makeMc()} goals={[]} />);
    const mc = makeMc();
    const n = mc.time_axis!.length;
    const med = parsePoints(screen.getByTestId('mc-paths-p50').getAttribute('points'));
    const b = (med[0]![1] - med[n - 1]![1]) / (mc.p50![n - 1]! - mc.p50![0]!);
    const a = med[0]![1] + b * mc.p50![0]!;
    const band = parsePoints(screen.getByTestId('mc-paths-band').getAttribute('points'));
    expect(band[n - 1]![1]).toBeCloseTo(a - b * mc.p75![n - 1]!, 6);
    expect(band[n]![1]).toBeCloseTo(a - b * mc.p5![n - 1]!, 6);
    expect(screen.queryByTestId('mc-paths-band-inner')).toBeNull();
  });

  it('teilweise gelieferte Faecher-Quantile (p90 fehlt) -> kein Chart statt falschem Band', () => {
    const mc = makeMcFan();
    delete mc.p90;
    const { container } = render(<MonteCarloPathsChart paths={mc} goals={[]} />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('nicht-finiter Wert in p10 -> kein Chart', () => {
    const mc = makeMcFan();
    mc.p10![4] = Number.POSITIVE_INFINITY;
    const { container } = render(<MonteCarloPathsChart paths={mc} goals={[]} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});

describe('MonteCarloPathsChart — Zielmarker ausserhalb der Skala', () => {
  it('Ziel weit ueber der Skala: Pfeil + exakter Wert statt still geklemmtem Punkt', () => {
    const goal = makeGoal({
      goal_id: 'hard',
      label: 'Stiftung',
      target_date: '2035-01-01',
      target_amount_rappen: 50_000_000_00,
    });
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[goal]} />);
    const marker = screen.getByTestId('goal-marker-hard');
    expect(marker.getAttribute('data-above-scale')).toBe('true');
    expect(marker.querySelector('circle')).toBeNull();
    expect(screen.getByTestId('goal-marker-arrow-hard')).toBeInTheDocument();
    expect(screen.getByTestId('goal-marker-value-hard')).toHaveTextContent(
      '▲ CHF 50.00 Mio. über Skala',
    );
    expect(screen.getByTestId('mc-paths-legend-above-scale')).toBeInTheDocument();
  });

  it('Ziel knapp ueber dem Faecher (< Cap): Skala waechst mit, Punkt liegt im Plot', () => {
    const mc = makeMcFan();
    const fanMax = Math.max(...mc.p90!);
    const target = Math.round(fanMax * 1.6);
    const goal = makeGoal({ goal_id: 'stretch', target_date: '2034-01-01', target_amount_rappen: target });
    render(<MonteCarloPathsChart paths={mc} goals={[goal]} />);
    const marker = screen.getByTestId('goal-marker-stretch');
    expect(marker.getAttribute('data-above-scale')).toBe('false');
    expect(screen.queryByTestId('goal-marker-arrow-stretch')).toBeNull();
    expect(screen.queryByTestId('mc-paths-legend-above-scale')).toBeNull();
    // Punkt liegt NICHT auf der obersten Gitterlinie (= war frueher geklemmt)
    const cy = Number(marker.querySelector('circle')!.getAttribute('cy'));
    const tickYs = Array.from(screen.getAllByTestId('mc-paths-y-tick')).map((t) =>
      Number(t.getAttribute('y')),
    );
    expect(cy).toBeGreaterThan(Math.min(...tickYs));
  });
});

describe('computeYScale / niceStep / makeYTickFormatter', () => {
  it('niceStep waehlt den kleinsten Schritt aus 1/2/2.5/5 x 10^k', () => {
    expect(niceStep(1)).toBe(1);
    expect(niceStep(1.2)).toBe(2);
    expect(niceStep(2.1)).toBe(2.5);
    expect(niceStep(2.6)).toBe(5);
    expect(niceStep(5.01)).toBe(10);
    expect(niceStep(26.25)).toBe(50);
    expect(niceStep(0.3)).toBeCloseTo(0.5, 12);
  });

  it('Skala deckt 105 % des Faechers mit hoechstens 4 runden Intervallen', () => {
    expect(computeYScale(100, [])).toEqual({ maxValue: 150, step: 50 });
    // 4.2 Mio. CHF (Rappen): top 4.41 Mio, Rohschritt 1.1025 Mio -> 2 Mio, Obergrenze 6 Mio
    const r = computeYScale(4_200_000_00, []);
    expect(r.step).toBe(2_000_000_00);
    expect(r.maxValue).toBe(6_000_000_00);
    expect(r.maxValue / r.step).toBeLessThanOrEqual(4);
  });

  it(`Ziele bis ${GOAL_SCALE_CAP}x Faecher-Max erweitern die Skala, hoehere nicht`, () => {
    expect(computeYScale(100, [180]).maxValue).toBeGreaterThanOrEqual(180 * 1.05);
    expect(computeYScale(100, [200]).maxValue).toBeGreaterThanOrEqual(210);
    expect(computeYScale(100, [201])).toEqual(computeYScale(100, []));
  });

  it('Achsenbeschriftung: feste Nachkommastellen je Achse, CH-Format', () => {
    const mio = (chf: number) => chf * 100;
    const f1 = makeYTickFormatter(mio(1_000_000), mio(250_000));
    expect(f1(0)).toBe('CHF 0');
    expect(f1(mio(500_000))).toBe('CHF 0.50 Mio.');
    expect(f1(mio(1_000_000))).toBe('CHF 1.00 Mio.');
    const f2 = makeYTickFormatter(mio(6_000_000), mio(2_000_000));
    expect(f2(mio(4_000_000))).toBe('CHF 4 Mio.');
    const f3 = makeYTickFormatter(mio(7_500_000), mio(2_500_000));
    expect(f3(mio(5_000_000))).toBe('CHF 5.0 Mio.');
    const f4 = makeYTickFormatter(mio(750_000), mio(250_000));
    expect(f4(mio(250_000))).toBe("CHF 250'000");
  });

  it('gerenderte y-Ticks haben eine einheitliche Nachkommastellenzahl und tabular-nums', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[]} />);
    const ticks = screen.getAllByTestId('mc-paths-y-tick').slice(1); // ohne 0
    const decimals = new Set(
      ticks.map((t) => (t.textContent!.match(/\.(\d+) Mio\./)?.[1] ?? '').length),
    );
    expect(decimals.size).toBe(1);
    for (const t of ticks) expect(t.textContent).toMatch(/^CHF \d+(\.\d+)? Mio\.$/);
    for (const t of ticks) {
      expect(t.getAttribute('style')).toMatch(/font-variant-numeric:\s*tabular-nums/);
    }
  });
});

describe('MonteCarloPathsChart — X-Achse Beschriftung', () => {
  it('beschriftet maximal 6 X-Ticks auch bei langem Horizont', () => {
    // 30-Jahres-Horizont -> 31 datapoints
    const time_axis = Array.from({ length: 31 }, (_, i) => `${2026 + i}`);
    const start = 1_000_000;
    const mc = makeMc({
      time_axis,
      p5: time_axis.map((_, t) => start * (1.02 ** t)),
      p50: time_axis.map((_, t) => start * (1.05 ** t)),
      p75: time_axis.map((_, t) => start * (1.08 ** t)),
      horizon_years: 30,
    });
    const { container } = render(
      <MonteCarloPathsChart paths={mc} goals={[]} />,
    );
    // X-Achsen-Labels sind <text> mit textAnchor="middle" auf der unteren Linie
    const allTexts = container.querySelectorAll('svg > text');
    // Wir wissen: 5 Y-Labels + max 6 X-Labels = max 11 isolated <text>
    // (plus Goal-Labels, aber keine Goals -> 0)
    const xLikeLabels = Array.from(allTexts).filter((t) =>
      /^\d{4}$/.test(t.textContent ?? ''),
    );
    expect(xLikeLabels.length).toBeLessThanOrEqual(6);
    expect(xLikeLabels.length).toBeGreaterThan(0);
  });
});
