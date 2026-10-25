/**
 * Sprint U-49 (Roadmap-Punkt 49, 2026-06-04): Positionen-Filter Tests.
 *
 * Pure-Function-Tests, kein React-Render.
 */
import { describe, it, expect } from 'vitest';
import type { PositionEntry, PositionGroup } from '@/api/types';
import {
  filterByBuckets,
  filterPositions,
  matchesQuery,
} from './filterPositions';


function pos(overrides: Partial<PositionEntry> = {}): PositionEntry {
  return {
    product_name: 'iShares MSCI World',
    isin: 'IE00B4L5Y983',
    provider: 'BlackRock',
    currency: 'USD',
    share_bps: 5000,
    market_value_rappen: 1000000_00,
    product_id: 'p-1',
    ...overrides,
  } as PositionEntry;
}


function group(overrides: Partial<PositionGroup> = {}): PositionGroup {
  return {
    key: 'equities',
    label: 'Aktien',
    share_bps: 6000,
    total_rappen: 6000000_00,
    positions: [pos()],
    ...overrides,
  } as PositionGroup;
}


// ---------------------------------------------------------------------------
// matchesQuery
// ---------------------------------------------------------------------------

describe('U-49 matchesQuery', () => {
  it('returns true for empty query', () => {
    expect(matchesQuery(pos(), '')).toBe(true);
  });

  it('returns true for whitespace-only query', () => {
    expect(matchesQuery(pos(), '   ')).toBe(true);
  });

  it('matches product_name case-insensitive', () => {
    expect(matchesQuery(pos({ product_name: 'iShares MSCI World' }), 'ishares')).toBe(true);
    expect(matchesQuery(pos({ product_name: 'iShares MSCI World' }), 'WORLD')).toBe(true);
  });

  it('matches isin', () => {
    expect(matchesQuery(pos({ isin: 'CH0012345678' }), 'ch001234')).toBe(true);
  });

  it('matches provider', () => {
    expect(matchesQuery(pos({ provider: 'Vanguard' }), 'vang')).toBe(true);
  });

  it('matches currency', () => {
    expect(matchesQuery(pos({ currency: 'EUR' }), 'eur')).toBe(true);
  });

  it('returns false when nothing matches', () => {
    expect(matchesQuery(pos({ product_name: 'Apple Inc' }), 'tesla')).toBe(false);
  });

  it('handles null/undefined fields gracefully', () => {
    const p = pos({
      product_name: undefined,
      isin: undefined,
      provider: undefined,
      currency: undefined,
    });
    expect(matchesQuery(p, 'anything')).toBe(false);
    expect(matchesQuery(p, '')).toBe(true);
  });

  it('matches partial strings', () => {
    expect(matchesQuery(pos({ product_name: 'Nestle SA' }), 'nes')).toBe(true);
  });
});


// ---------------------------------------------------------------------------
// filterPositions
// ---------------------------------------------------------------------------

describe('U-49 filterPositions', () => {
  it('returns all groups when query empty', () => {
    const groups = [group(), group({ key: 'bonds', label: 'Anleihen' })];
    const result = filterPositions(groups, '');
    expect(result.groups).toEqual(groups);
    expect(result.stats.groups_after).toBe(2);
  });

  it('filters positions by query in single group', () => {
    const groups = [
      group({
        key: 'equities',
        positions: [
          pos({ product_name: 'Apple Inc' }),
          pos({ product_name: 'Microsoft Corp' }),
          pos({ product_name: 'Tesla Inc' }),
        ],
      }),
    ];
    const result = filterPositions(groups, 'apple');
    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].positions).toHaveLength(1);
    expect(result.groups[0].positions[0].product_name).toBe('Apple Inc');
  });

  it('hides completely empty groups when filter active', () => {
    const groups = [
      group({
        key: 'equities',
        positions: [pos({ product_name: 'Apple' })],
      }),
      group({
        key: 'bonds',
        positions: [pos({ product_name: 'CH-Bond' })],
      }),
    ];
    const result = filterPositions(groups, 'apple');
    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].key).toBe('equities');
  });

  it('keeps multiple groups when each has matches', () => {
    const groups = [
      group({
        key: 'equities',
        positions: [pos({ product_name: 'Apple' })],
      }),
      group({
        key: 'bonds',
        positions: [pos({ product_name: 'Apple-Bond' })],
      }),
    ];
    const result = filterPositions(groups, 'apple');
    expect(result.groups).toHaveLength(2);
  });

  it('stats counts positions correctly', () => {
    const groups = [
      group({
        positions: [
          pos({ product_name: 'Apple' }),
          pos({ product_name: 'Microsoft' }),
        ],
      }),
      group({
        key: 'bonds',
        positions: [pos({ product_name: 'CH-Bond' })],
      }),
    ];
    const result = filterPositions(groups, 'apple');
    expect(result.stats.total_positions_before).toBe(3);
    expect(result.stats.total_positions_after).toBe(1);
    expect(result.stats.groups_before).toBe(2);
    expect(result.stats.groups_after).toBe(1);
  });

  it('returns empty groups when nothing matches', () => {
    const groups = [
      group({ positions: [pos({ product_name: 'Apple' })] }),
    ];
    const result = filterPositions(groups, 'tesla');
    expect(result.groups).toEqual([]);
    expect(result.stats.total_positions_after).toBe(0);
  });

  it('does NOT mutate input groups', () => {
    const positions = [pos({ product_name: 'Apple' }), pos({ product_name: 'Tesla' })];
    const groups = [group({ positions })];
    filterPositions(groups, 'apple');
    expect(groups[0].positions).toHaveLength(2);
  });

  it('handles empty positions array', () => {
    const groups = [group({ positions: [] })];
    const result = filterPositions(groups, 'anything');
    expect(result.groups).toEqual([]);
    expect(result.stats.total_positions_before).toBe(0);
  });

  it('matches isin across multiple positions', () => {
    const groups = [
      group({
        positions: [
          pos({ product_name: 'A', isin: 'CH001' }),
          pos({ product_name: 'B', isin: 'CH002' }),
          pos({ product_name: 'C', isin: 'DE001' }),
        ],
      }),
    ];
    const result = filterPositions(groups, 'CH00');
    expect(result.groups[0].positions).toHaveLength(2);
  });
});


// ---------------------------------------------------------------------------
// filterByBuckets
// ---------------------------------------------------------------------------

describe('U-49 filterByBuckets', () => {
  it('returns all groups when allowed set is empty', () => {
    const groups = [group(), group({ key: 'bonds' })];
    expect(filterByBuckets(groups, new Set())).toEqual(groups);
  });

  it('filters by allowed keys', () => {
    const groups = [
      group({ key: 'equities' }),
      group({ key: 'bonds' }),
      group({ key: 'real_estate' }),
    ];
    const result = filterByBuckets(groups, new Set(['equities', 'real_estate']));
    expect(result).toHaveLength(2);
    expect(result.map((g) => g.key)).toEqual(['equities', 'real_estate']);
  });
});
