/**
 * Sprint U-48 (Roadmap-Punkt 48, 2026-06-04): Goals-Sort Tests.
 *
 * Pure-Function-Tests, kein React-Render.
 */
import { describe, it, expect } from 'vitest';
import type { GoalEntry } from '@/api/types';
import {
  compareGoals,
  nextSortConfig,
  sortGoals,
  type SortConfig,
} from './sortGoals';


function goal(overrides: Partial<GoalEntry> = {}): GoalEntry {
  return {
    goal_id: 'g-1',
    label: 'Default',
    goal_type: 'wealth',
    target_amount_rappen: 100000_00,
    status: 'erreichbar',
    probability_bps: 8000,
    ...overrides,
  } as GoalEntry;
}


// ---------------------------------------------------------------------------
// compareGoals
// ---------------------------------------------------------------------------

describe('U-48 compareGoals', () => {
  it('sorts labels alphabetically (de-CH locale)', () => {
    const a = goal({ label: 'Auto kaufen' });
    const b = goal({ label: 'Eigenheim' });
    expect(compareGoals(a, b, 'label')).toBeLessThan(0);
    expect(compareGoals(b, a, 'label')).toBeGreaterThan(0);
  });

  it('sorts labels case-insensitive', () => {
    const a = goal({ label: 'auto' });
    const b = goal({ label: 'Auto' });
    expect(compareGoals(a, b, 'label')).toBe(0);
  });

  it('handles umlaut in label sort (de-CH)', () => {
    const a = goal({ label: 'Ausbildung' });
    const b = goal({ label: 'Übernahme' });
    // ä/ö/ü sort near base in de-CH
    expect(Math.abs(compareGoals(a, b, 'label'))).toBeGreaterThan(0);
  });

  it('sorts type alphabetically', () => {
    const a = goal({ goal_type: 'cashflow' });
    const b = goal({ goal_type: 'wealth' });
    expect(compareGoals(a, b, 'type')).toBeLessThan(0);
  });

  it('sorts target by amount asc', () => {
    const a = goal({ target_amount_rappen: 50000_00 });
    const b = goal({ target_amount_rappen: 100000_00 });
    expect(compareGoals(a, b, 'target')).toBeLessThan(0);
  });

  it('puts null target at end on asc', () => {
    const withTarget = goal({ target_amount_rappen: 50000_00 });
    const withoutTarget = goal({ target_amount_rappen: undefined });
    expect(compareGoals(withTarget, withoutTarget, 'target')).toBeLessThan(0);
  });

  it('sorts status by priority (erreichbar first asc)', () => {
    const erreichbar = goal({ status: 'erreichbar' });
    const knapp = goal({ status: 'knapp' });
    const rot = goal({ status: 'nicht_erreichbar' });
    expect(compareGoals(erreichbar, knapp, 'status')).toBeLessThan(0);
    expect(compareGoals(knapp, rot, 'status')).toBeLessThan(0);
  });

  it('puts data_pending status last in asc', () => {
    const pending = goal({ status: 'data_pending' as any });
    const rot = goal({ status: 'nicht_erreichbar' });
    expect(compareGoals(rot, pending, 'status')).toBeLessThan(0);
  });

  it('sorts probability asc (lower probability first)', () => {
    const lowProb = goal({ probability_bps: 3000 });
    const highProb = goal({ probability_bps: 9000 });
    expect(compareGoals(lowProb, highProb, 'probability')).toBeLessThan(0);
  });

  it('treats null probability as 0', () => {
    const noProb = goal({ probability_bps: undefined });
    const someProb = goal({ probability_bps: 3000 });
    expect(compareGoals(noProb, someProb, 'probability')).toBeLessThan(0);
  });
});


// ---------------------------------------------------------------------------
// sortGoals
// ---------------------------------------------------------------------------

describe('U-48 sortGoals', () => {
  it('returns same goals when config is null', () => {
    const goals = [goal({ label: 'C' }), goal({ label: 'A' })];
    const sorted = sortGoals(goals, null);
    expect(sorted).toEqual(goals);
  });

  it('does NOT mutate input array', () => {
    const goals = [goal({ label: 'C' }), goal({ label: 'A' })];
    const before = goals.map((g) => g.label);
    sortGoals(goals, { column: 'label', direction: 'asc' });
    expect(goals.map((g) => g.label)).toEqual(before);
  });

  it('sorts asc correctly', () => {
    const goals = [
      goal({ label: 'C' }),
      goal({ label: 'A' }),
      goal({ label: 'B' }),
    ];
    const sorted = sortGoals(goals, { column: 'label', direction: 'asc' });
    expect(sorted.map((g) => g.label)).toEqual(['A', 'B', 'C']);
  });

  it('sorts desc correctly', () => {
    const goals = [
      goal({ label: 'A' }),
      goal({ label: 'B' }),
      goal({ label: 'C' }),
    ];
    const sorted = sortGoals(goals, { column: 'label', direction: 'desc' });
    expect(sorted.map((g) => g.label)).toEqual(['C', 'B', 'A']);
  });

  it('sorts by target amount asc with null at end', () => {
    const goals = [
      goal({ label: 'WithoutTarget', target_amount_rappen: undefined }),
      goal({ label: 'Big', target_amount_rappen: 1000000_00 }),
      goal({ label: 'Small', target_amount_rappen: 50000_00 }),
    ];
    const sorted = sortGoals(goals, { column: 'target', direction: 'asc' });
    expect(sorted.map((g) => g.label)).toEqual(['Small', 'Big', 'WithoutTarget']);
  });
});


// ---------------------------------------------------------------------------
// nextSortConfig (Three-State Toggle)
// ---------------------------------------------------------------------------

describe('U-48 nextSortConfig three-state', () => {
  it('first click on new column -> asc', () => {
    expect(nextSortConfig(null, 'label')).toEqual({
      column: 'label', direction: 'asc',
    });
  });

  it('second click same column -> desc', () => {
    const after = nextSortConfig(
      { column: 'label', direction: 'asc' },
      'label',
    );
    expect(after).toEqual({ column: 'label', direction: 'desc' });
  });

  it('third click same column -> reset (null)', () => {
    const after = nextSortConfig(
      { column: 'label', direction: 'desc' },
      'label',
    );
    expect(after).toBeNull();
  });

  it('click on different column -> new asc (not desc)', () => {
    const after = nextSortConfig(
      { column: 'label', direction: 'desc' },
      'target',
    );
    expect(after).toEqual({ column: 'target', direction: 'asc' });
  });

  it('full cycle: null -> asc -> desc -> null', () => {
    let config: SortConfig | null = null;
    config = nextSortConfig(config, 'probability');
    expect(config).toEqual({ column: 'probability', direction: 'asc' });
    config = nextSortConfig(config, 'probability');
    expect(config).toEqual({ column: 'probability', direction: 'desc' });
    config = nextSortConfig(config, 'probability');
    expect(config).toBeNull();
  });
});
