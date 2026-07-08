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
import { MonteCarloPathsChart } from './MonteCarloPathsChart';

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
  it('zeigt die 5-Eintraege-Legende', () => {
    render(<MonteCarloPathsChart paths={makeMc()} goals={[]} />);
    const legend = screen.getByTestId('mc-paths-legend');
    expect(legend).toHaveTextContent(/Band p5/);
    expect(legend).toHaveTextContent(/Median p50/);
    expect(legend).toHaveTextContent(/erreichbar/);
    expect(legend).toHaveTextContent(/Knapp/);
    expect(legend).toHaveTextContent(/Schwierig/);
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
