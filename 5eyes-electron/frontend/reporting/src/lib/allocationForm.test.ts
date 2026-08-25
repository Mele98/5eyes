/**
 * Unit-Tests für die Allocation-Form-Logik (Track #67).
 *
 * Spiegelt die Backend-Validierung TargetAllocationCreate.validate_alloc.
 */
import { describe, expect, it } from 'vitest';
import {
  buildTargetAllocationPayload,
  draftFromRecord,
  totalTargetBps,
  validateAllocation,
  type AllocationDraft,
} from './allocationForm';
import type { TargetAllocationRecord } from '@/api/types';

function balancedDraft(): AllocationDraft {
  return {
    equities: { target: 4000, min: 3000, max: 5000 },
    bonds: { target: 3000, min: 2000, max: 4000 },
    real_estate: { target: 1000, min: 0, max: 2000 },
    alternatives: { target: 1000, min: 0, max: 2000 },
    liquidity: { target: 1000, min: 0, max: 2000 },
  };
}

describe('ALLOC-1: Integer-/Finite-Validierung', () => {
  it('meldet einen Float-Wert (Backend-Felder sind int)', () => {
    const d = balancedDraft();
    d.equities.target = 4000.5;
    d.bonds.target = 2999.5; // Summe bleibt 10000, aber Floats
    const errs = validateAllocation(d);
    expect(errs.some((e) => e.includes('ganze Zahl in BP'))).toBe(true);
  });
  it('meldet ein NaN-Feld (Finite-Guard)', () => {
    const d = balancedDraft();
    d.liquidity.target = Number.NaN;
    const errs = validateAllocation(d);
    expect(errs.some((e) => e.includes('ganze Zahl in BP'))).toBe(true);
  });
});

describe('totalTargetBps', () => {
  it('summiert die 5 Ziel-Quoten', () => {
    expect(totalTargetBps(balancedDraft())).toBe(10000);
  });
});

describe('validateAllocation', () => {
  it('akzeptiert eine ausgewogene 10000-bps-Allokation', () => {
    expect(validateAllocation(balancedDraft())).toEqual([]);
  });

  it('meldet eine Summe ungleich 10000', () => {
    const d = balancedDraft();
    d.equities.target = 4500; // Summe 10500
    const errs = validateAllocation(d);
    expect(errs.some((e) => e.includes('10000 BP'))).toBe(true);
  });

  it('meldet min > max', () => {
    const d = balancedDraft();
    d.equities.min = 6000;
    d.equities.max = 5000;
    const errs = validateAllocation(d);
    expect(errs.some((e) => e.includes('Bandbreite ungültig'))).toBe(true);
  });

  it('meldet ein Ziel ausserhalb des Bandes', () => {
    const d = balancedDraft();
    d.equities.min = 1000;
    d.equities.max = 3000; // target 4000 liegt darüber
    const errs = validateAllocation(d);
    expect(errs.some((e) => e.includes('zwischen Min'))).toBe(true);
  });
});

describe('buildTargetAllocationPayload', () => {
  it('mappt Draft + policy_id auf die 15 bps-Felder', () => {
    const payload = buildTargetAllocationPayload(balancedDraft(), 'pol-1', {
      based_on_assessment_id: 'ra-1',
    });
    expect(payload.target_equities_bps).toBe(4000);
    expect(payload.band_liquidity_max_bps).toBe(2000);
    expect(payload.policy_id).toBe('pol-1');
    expect(payload.based_on_assessment_id).toBe('ra-1');
    expect(payload.risky_fraction_bps).toBeNull();
  });
});

describe('draftFromRecord', () => {
  it('liest target/min/max je Klasse aus dem Record', () => {
    const rec = {
      target_equities_bps: 4200,
      band_equities_min_bps: 3500,
      band_equities_max_bps: 5500,
      target_bonds_bps: 2800,
      band_bonds_min_bps: 2000,
      band_bonds_max_bps: 4000,
      target_real_estate_bps: 1000,
      band_real_estate_min_bps: 0,
      band_real_estate_max_bps: 2000,
      target_alternatives_bps: 1000,
      band_alternatives_min_bps: 0,
      band_alternatives_max_bps: 2000,
      target_liquidity_bps: 1000,
      band_liquidity_min_bps: 0,
      band_liquidity_max_bps: 2000,
    } as TargetAllocationRecord;
    const draft = draftFromRecord(rec);
    expect(draft.equities).toEqual({ target: 4200, min: 3500, max: 5500 });
    expect(draft.bonds.target).toBe(2800);
  });
});
