/**
 * Sprint U-12 — Unit-Tests fuer Goal-Klassifikation gegen MC-Pfade.
 *
 * Wir testen ULTRA-genau jeden Edge-Case, weil diese Logik direkt
 * bestimmt welcher Goal-Pill (Erreichbar/Knapp/Schwierig) im Bericht
 * angezeigt wird — Berater entscheidet danach.
 */
import { describe, expect, it } from 'vitest';

import type { GoalEntry, MonteCarloPaths } from '@/api/types';
import { classifyGoals } from './goalClassification';

function makeGoal(overrides: Partial<GoalEntry> = {}): GoalEntry {
  return {
    goal_id: overrides.goal_id ?? 'g1',
    label: overrides.label ?? 'Pension',
    goal_type: overrides.goal_type ?? 'Vermoegen',
    target_amount_rappen: overrides.target_amount_rappen ?? 3_000_000_00,
    target_date: overrides.target_date ?? '2035-01-01',
    hardness: overrides.hardness ?? 'Primaer',
    probability_bps: overrides.probability_bps ?? null,
    status: overrides.status ?? '',
  };
}

function makeMc(overrides: Partial<MonteCarloPaths> = {}): MonteCarloPaths {
  // 11 Jahre: 2026..2036, monoton steigender Wealth
  // p5  startet  2_700_000_00 und wächst ~3% p.a.
  // p50 startet  2_700_000_00 und wächst ~5% p.a.
  // p75 startet  2_700_000_00 und wächst ~7% p.a.
  const time_axis = Array.from({ length: 11 }, (_, i) => `${2026 + i}`);
  const start = 2_700_000_00;
  const p5 = time_axis.map((_, t) => Math.round(start * Math.pow(1.03, t)));
  const p50 = time_axis.map((_, t) => Math.round(start * Math.pow(1.05, t)));
  const p75 = time_axis.map((_, t) => Math.round(start * Math.pow(1.07, t)));
  return {
    data_pending: false,
    time_axis,
    p5,
    p50,
    p75,
    n_paths: 1000,
    seed: 42,
    horizon_years: 10,
    initial_wealth_rappen: start,
    ...overrides,
  };
}

describe('classifyGoals — data_pending fallback', () => {
  it('returns all unknown when data_pending=true', () => {
    const mc: MonteCarloPaths = { data_pending: true, note: '...' };
    const out = classifyGoals([makeGoal(), makeGoal({ goal_id: 'g2' })], mc);
    expect(out).toHaveLength(2);
    expect(out.every((c) => c.status === 'unknown')).toBe(true);
    expect(out.every((c) => c.t_index === null)).toBe(true);
  });

  it('returns all unknown when mc is null', () => {
    const out = classifyGoals([makeGoal()], null);
    expect(out[0].status).toBe('unknown');
  });

  it('returns all unknown when mc is undefined', () => {
    const out = classifyGoals([makeGoal()], undefined);
    expect(out[0].status).toBe('unknown');
  });
});

describe('classifyGoals — mal-aligned paths', () => {
  it('returns unknown when time_axis empty', () => {
    const mc = makeMc({ time_axis: [], p5: [], p50: [], p75: [] });
    expect(classifyGoals([makeGoal()], mc)[0].status).toBe('unknown');
  });

  it('returns unknown when p5 length != time_axis length', () => {
    const mc = makeMc();
    mc.p5 = (mc.p5 ?? []).slice(0, 5); // verkuerzt
    expect(classifyGoals([makeGoal()], mc)[0].status).toBe('unknown');
  });

  it('returns unknown when p50 length != p5 length', () => {
    const mc = makeMc();
    mc.p50 = (mc.p50 ?? []).slice(0, 3);
    expect(classifyGoals([makeGoal()], mc)[0].status).toBe('unknown');
  });

  it('returns unknown when time_axis contains non-numeric start year', () => {
    const mc = makeMc({ time_axis: ['abcd', '2027'] });
    expect(classifyGoals([makeGoal()], mc)[0].status).toBe('unknown');
  });
});

describe('classifyGoals — temporal edges', () => {
  it("returns 'past' when target_date is before time_axis start", () => {
    const mc = makeMc();
    const goal = makeGoal({ target_date: '2024-01-01' });
    expect(classifyGoals([goal], mc)[0].status).toBe('past');
  });

  it("returns 'beyond_horizon' when target_date is after time_axis end", () => {
    const mc = makeMc(); // ends 2036
    const goal = makeGoal({ target_date: '2050-01-01' });
    expect(classifyGoals([goal], mc)[0].status).toBe('beyond_horizon');
  });

  it("returns 'unknown' for invalid target_date format", () => {
    const mc = makeMc();
    const goal = makeGoal({ target_date: 'not-a-date' });
    expect(classifyGoals([goal], mc)[0].status).toBe('unknown');
  });

  it("returns 'unknown' for empty target_date", () => {
    const mc = makeMc();
    const goal = makeGoal({ target_date: '' });
    expect(classifyGoals([goal], mc)[0].status).toBe('unknown');
  });
});

describe('classifyGoals — target_amount edges', () => {
  it("returns 'unknown' when target_amount <= 0", () => {
    const mc = makeMc();
    const goal = makeGoal({ target_amount_rappen: 0 });
    expect(classifyGoals([goal], mc)[0].status).toBe('unknown');
  });

  it("returns 'unknown' for negative target_amount", () => {
    const mc = makeMc();
    const goal = makeGoal({ target_amount_rappen: -100 });
    expect(classifyGoals([goal], mc)[0].status).toBe('unknown');
  });
});

describe('classifyGoals — Status-Klassifikation', () => {
  it("klassifiziert als 'erreichbar' wenn p50 >= target", () => {
    const mc = makeMc();
    // p50 at t=9 (2035) = 2.7M * 1.05^9 = ~4.18M
    const goal = makeGoal({
      target_date: '2035-01-01',
      target_amount_rappen: 3_500_000_00, // < p50
    });
    const c = classifyGoals([goal], mc)[0];
    expect(c.status).toBe('erreichbar');
    expect(c.t_index).toBe(9);
    expect(c.p50_at_target).toBeGreaterThan(0);
  });

  it("klassifiziert als 'knapp' wenn p75 >= target > p50", () => {
    const mc = makeMc();
    // p50 at t=9 = ~4.18M, p75 at t=9 = 2.7M * 1.07^9 = ~4.97M
    const goal = makeGoal({
      target_date: '2035-01-01',
      target_amount_rappen: 4_500_000_00,
    });
    const c = classifyGoals([goal], mc)[0];
    expect(c.status).toBe('knapp');
  });

  it("klassifiziert als 'nicht_erreichbar' wenn p75 < target", () => {
    const mc = makeMc();
    const goal = makeGoal({
      target_date: '2035-01-01',
      target_amount_rappen: 10_000_000_00, // way too high
    });
    const c = classifyGoals([goal], mc)[0];
    expect(c.status).toBe('nicht_erreichbar');
    // Beweis: p75 < target
    expect(c.p75_at_target).not.toBeNull();
    expect(c.p75_at_target!).toBeLessThan(10_000_000_00);
  });

  it("trifft die Grenze p50 = target genau richtig (>= statt >)", () => {
    const mc = makeMc();
    // p50 bei t=5: 2.7M * 1.05^5 = exakt diesen Wert nehmen
    const exact_p50 = mc.p50![5];
    const goal = makeGoal({
      target_date: '2031-01-01',
      target_amount_rappen: exact_p50,
    });
    expect(classifyGoals([goal], mc)[0].status).toBe('erreichbar');
  });
});

describe('classifyGoals — Multi-Goal-Roundtrip', () => {
  it('klassifiziert mehrere Goals unabhaengig', () => {
    const mc = makeMc();
    const goals: GoalEntry[] = [
      makeGoal({ goal_id: 'a', target_date: '2030-01-01', target_amount_rappen: 100_000_00 }),
      makeGoal({ goal_id: 'b', target_date: '2036-01-01', target_amount_rappen: 5_000_000_00 }),
      makeGoal({ goal_id: 'c', target_date: '2099-01-01', target_amount_rappen: 1_000_000_00 }),
      makeGoal({ goal_id: 'd', target_date: '', target_amount_rappen: 1_000_000_00 }),
    ];
    const out = classifyGoals(goals, mc);
    expect(out.map((c) => c.goal_id)).toEqual(['a', 'b', 'c', 'd']);
    expect(out[0].status).toBe('erreichbar'); // trivial
    // out[1] kann erreichbar oder knapp sein je nach Wachstum
    expect(['erreichbar', 'knapp']).toContain(out[1].status);
    expect(out[2].status).toBe('beyond_horizon');
    expect(out[3].status).toBe('unknown');
  });

  it('returns empty array fuer empty goals input', () => {
    expect(classifyGoals([], makeMc())).toEqual([]);
  });
});

describe('classifyGoals — Determinismus', () => {
  it('liefert identisches Output bei identischem Input (Audit)', () => {
    const mc = makeMc();
    const goals = [makeGoal()];
    const a = classifyGoals(goals, mc);
    const b = classifyGoals(goals, mc);
    expect(a).toEqual(b);
  });
});
