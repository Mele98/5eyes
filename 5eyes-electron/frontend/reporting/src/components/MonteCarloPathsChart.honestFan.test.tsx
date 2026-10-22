/**
 * AA-UX-HONEST-FAN-001 (UX-Audit „Signature-Verbesserungen", Punkt 1):
 * Endwerte am rechten Rand, Ziel-Pille mit Erfolgswahrscheinlichkeit,
 * Klartext-Satz aus P10/P90 des Endjahres, Ziel ueber Skala -- und nichts
 * davon, wenn das Projection-Gate Projektionen ausblendet.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type {
  GoalBasedInvestingData,
  GoalEntry,
  MonteCarloPaths,
  ProjectionGateData,
} from '@/api/types';
import { Goals } from '@/pages/Goals';
import { MonteCarloPathsChart } from './MonteCarloPathsChart';

const NBSP = ' ';

function makeMcFan(overrides: Partial<MonteCarloPaths> = {}): MonteCarloPaths {
  const time_axis = Array.from({ length: 25 }, (_, i) => `${2026 + i}`);
  // Endwerte exakt setzen: P10 1.6 Mio., P50 2.41 Mio., P90 3.4 Mio. (Rappen)
  const lin = (end: number) => time_axis.map((_, t) => Math.round(200_000_000 + ((end - 200_000_000) * t) / 24));
  return {
    data_pending: false,
    time_axis,
    p5: lin(140_000_000),
    p10: lin(160_000_000),
    p25: lin(200_000_000),
    p50: lin(241_000_000),
    p75: lin(290_000_000),
    p90: lin(340_000_000),
    n_paths: 1000,
    seed: 42,
    horizon_years: 24,
    initial_wealth_rappen: 200_000_000,
    ...overrides,
  };
}

function makeGoal(overrides: Partial<GoalEntry> = {}): GoalEntry {
  return {
    goal_id: 'g1',
    label: 'Ruhestand',
    goal_type: 'Vermoegen',
    target_amount_rappen: 220_000_000,
    target_date: '2040-01-01',
    hardness: 'Primaer',
    probability_bps: 8200,
    status: 'erreichbar',
    outside_simulation_horizon: false,
    evaluation_scope: 'priority_funded',
    funding_rank: 1,
    failure_event_id: null,
    ...overrides,
  };
}

describe('Ehrlicher Faecher — Endwerte am rechten Rand', () => {
  it('beschriftet P90, Median und P10 des Endjahres direkt am Rand', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[]} />);
    expect(screen.getByTestId('mc-paths-end-label-p50')).toHaveTextContent('2.41 Mio. · Median');
    expect(screen.getByTestId('mc-paths-end-label-p90')).toHaveTextContent('3.40 Mio. · P90');
    expect(screen.getByTestId('mc-paths-end-label-p10')).toHaveTextContent('1.60 Mio. · P10');
  });

  it('Endwerte liegen rechts vom Plot und ueberlappen nicht (>= 12px Abstand)', () => {
    // enger Faecher: Endwerte nahe beieinander
    const mc = makeMcFan({
      p10: makeMcFan().p50!.map((v) => v - 1_000_000),
      p25: makeMcFan().p50!.map((v) => v - 500_000),
      p75: makeMcFan().p50!.map((v) => v + 500_000),
      p90: makeMcFan().p50!.map((v) => v + 1_000_000),
    });
    render(<MonteCarloPathsChart paths={mc} goals={[]} />);
    const ys = (['p90', 'p50', 'p10'] as const).map((k) =>
      Number(screen.getByTestId(`mc-paths-end-label-${k}`).getAttribute('y')),
    );
    expect(ys[1] - ys[0]).toBeGreaterThanOrEqual(12);
    expect(ys[2] - ys[1]).toBeGreaterThanOrEqual(12);
    const p50Points = screen.getByTestId('mc-paths-p50').getAttribute('points')!.split(' ');
    const lastX = Number(p50Points[p50Points.length - 1].split(',')[0]);
    const labelX = Number(screen.getByTestId('mc-paths-end-label-p50').getAttribute('x'));
    expect(labelX).toBeGreaterThan(lastX);
  });

  it('Median-Linie ist die dominante Linie (2.5px)', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[]} />);
    expect(screen.getByTestId('mc-paths-p50').getAttribute('stroke-width')).toBe('2.5');
  });

  it('Legacy-Payload (p5–p75): nur Median beschriftet, kein P10/P90-Satz', () => {
    const legacy = makeMcFan({ p10: undefined, p25: undefined, p90: undefined });
    render(<MonteCarloPathsChart paths={legacy} goals={[]} />);
    expect(screen.getByTestId('mc-paths-end-label-p50')).toBeInTheDocument();
    expect(screen.queryByTestId('mc-paths-end-label-p90')).toBeNull();
    expect(screen.queryByTestId('mc-paths-end-label-p10')).toBeNull();
    expect(screen.queryByTestId('mc-paths-range-sentence')).toBeNull();
  });
});

describe('Ehrlicher Faecher — Klartext-Satz', () => {
  it('Satz aus P10/P90 des Endjahres', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[]} />);
    expect(screen.getByTestId('mc-paths-range-sentence')).toHaveTextContent(
      'In 8 von 10 Verläufen liegt Ihr Vermögen 2050 zwischen CHF 1.60 und 3.40 Mio.',
    );
    expect(screen.getByTestId('mc-paths-range-sentence').textContent).not.toMatch(/garant/i);
  });
});

describe('Ehrlicher Faecher — Ziel-Pille', () => {
  it('Pille zeigt Label und Erfolgswahrscheinlichkeit', () => {
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[makeGoal()]} />);
    expect(screen.getByTestId('goal-marker-pill-g1').textContent).toBe(`Ruhestand · 82${NBSP}%`);
  });

  it('ohne belastbare Wahrscheinlichkeit nur das Label (keine erfundene Zahl)', () => {
    const goals = [
      makeGoal({ goal_id: 'a', probability_bps: null }),
      makeGoal({ goal_id: 'b', evaluation_scope: 'legacy_aggregate_unknown' }),
      makeGoal({ goal_id: 'c', outside_simulation_horizon: true }),
    ];
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={goals} />);
    for (const id of ['a', 'b', 'c']) {
      expect(screen.getByTestId(`goal-marker-pill-${id}`).textContent).toBe('Ruhestand');
    }
  });

  it('Ziel ueber der Skala: „▲ Zielwert über Skala"', () => {
    const goal = makeGoal({ goal_id: 'hi', target_amount_rappen: 5_000_000_000 });
    render(<MonteCarloPathsChart paths={makeMcFan()} goals={[goal]} />);
    expect(screen.getByTestId('goal-marker-value-hi')).toHaveTextContent('▲ CHF 50.00 Mio. über Skala');
    expect(screen.getByTestId('goal-marker-pill-hi').textContent).toBe(`Ruhestand · 82${NBSP}%`);
  });
});

describe('Ehrlicher Faecher — Projection-Gate', () => {
  it('projectionsHidden: kein Chart, keine Endwerte, keine Pille, kein Satz', () => {
    const { container } = render(
      <MonteCarloPathsChart paths={makeMcFan()} goals={[makeGoal()]} projectionsHidden />,
    );
    expect(container.innerHTML).toBe('');
  });

  it.each(['stale', 'blocked'] as const)(
    'projection_status=%s: keine Beschriftung, keine Pille, kein Satz',
    (status) => {
      render(
        <MonteCarloPathsChart
          paths={makeMcFan({ projection_status: status })}
          goals={[makeGoal()]}
        />,
      );
      expect(screen.queryByTestId('mc-paths-end-label-p50')).toBeNull();
      expect(screen.queryByTestId('mc-paths-range-sentence')).toBeNull();
      expect(screen.queryByTestId('goal-marker-pill-g1')).toBeNull();
    },
  );
});

describe('Ehrlicher Faecher — Goals-Seite respektiert das Report-Projection-Gate', () => {
  const gate = (hidden: boolean): ProjectionGateData => ({
    status: hidden ? 'blocked' : 'current',
    reason_code: null,
    projections_hidden: hidden,
    hinweis: null,
    note: null,
    hidden_channels: [],
    historical_ist_channels: [],
  });
  const data = (): GoalBasedInvestingData => ({
    goals: [makeGoal()],
    goal_achievement_score_bps: 8200,
    plan_solvency: null,
    monte_carlo_paths: makeMcFan(),
  });

  it('projections_hidden: kein Faecher, kein Satz, keine Pille', () => {
    render(<Goals data={data()} projectionGate={gate(true)} />);
    expect(screen.queryByTestId('mc-paths-chart')).toBeNull();
    expect(screen.queryByTestId('mc-paths-range-sentence')).toBeNull();
    expect(screen.queryByTestId('goal-marker-pill-g1')).toBeNull();
  });

  it('Positivkontrolle: Gate offen -> Faecher mit Satz und Pille', () => {
    render(<Goals data={data()} projectionGate={gate(false)} />);
    expect(screen.getByTestId('mc-paths-chart')).toBeInTheDocument();
    expect(screen.getByTestId('mc-paths-range-sentence')).toBeInTheDocument();
    expect(screen.getByTestId('goal-marker-pill-g1')).toBeInTheDocument();
  });
});
