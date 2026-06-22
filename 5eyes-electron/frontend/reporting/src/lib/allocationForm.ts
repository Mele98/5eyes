/**
 * Reine Logik für den Asset-Allocation-Editor (Track #67).
 *
 * Spiegelt die Backend-Invarianten aus schemas/allocation.py
 * `TargetAllocationCreate.validate_alloc` (26-48):
 *  - Summe der 5 Ziel-Quoten == 10000 bps
 *  - je Klasse: min <= max und min <= target <= max
 *
 * bps = Basispunkte (10000 = 100%). Editierbar pro Klasse: target/min/max.
 */
import type {
  AllocationBucketKey,
  TargetAllocationCreatePayload,
  TargetAllocationRecord,
} from '@/api/types';

export const ALLOCATION_BUCKETS: ReadonlyArray<{
  key: AllocationBucketKey;
  label: string;
}> = [
  { key: 'equities', label: 'Aktien' },
  { key: 'bonds', label: 'Obligationen' },
  { key: 'real_estate', label: 'Immobilien' },
  { key: 'alternatives', label: 'Alternative' },
  { key: 'liquidity', label: 'Liquidität' },
] as const;

export interface BucketBand {
  target: number;
  min: number;
  max: number;
}

export type AllocationDraft = Record<AllocationBucketKey, BucketBand>;

/** Summe der 5 Ziel-Quoten in bps (muss 10000 ergeben). */
export function totalTargetBps(draft: AllocationDraft): number {
  return ALLOCATION_BUCKETS.reduce((sum, b) => sum + (draft[b.key]?.target ?? 0), 0);
}

/**
 * Clientseitige Validierung, 1:1 zur Backend-validate_alloc. Liefert eine
 * Liste menschenlesbarer Fehler (leer = gültig).
 */
export function validateAllocation(draft: AllocationDraft): string[] {
  const errors: string[] = [];
  const total = totalTargetBps(draft);
  if (total !== 10000) {
    errors.push(`Allokation muss 10000 BP (100%) ergeben — aktuell ${total} BP.`);
  }
  for (const { key, label } of ALLOCATION_BUCKETS) {
    const band = draft[key];
    if (!band) continue;
    if (band.min > band.max) {
      errors.push(`${label}: Bandbreite ungültig — Min ${band.min} BP ist grösser als Max ${band.max} BP.`);
      continue;
    }
    if (!(band.min <= band.target && band.target <= band.max)) {
      errors.push(`${label}: Ziel ${band.target} muss zwischen Min ${band.min} und Max ${band.max} liegen.`);
    }
  }
  return errors;
}

/** Baut den TargetAllocationCreate-Payload aus dem Draft. */
export function buildTargetAllocationPayload(
  draft: AllocationDraft,
  policyId: string,
  extra: { risky_fraction_bps?: number | null; based_on_assessment_id?: string | null } = {},
): TargetAllocationCreatePayload {
  return {
    target_equities_bps: draft.equities.target,
    target_bonds_bps: draft.bonds.target,
    target_real_estate_bps: draft.real_estate.target,
    target_alternatives_bps: draft.alternatives.target,
    target_liquidity_bps: draft.liquidity.target,
    band_equities_min_bps: draft.equities.min,
    band_equities_max_bps: draft.equities.max,
    band_bonds_min_bps: draft.bonds.min,
    band_bonds_max_bps: draft.bonds.max,
    band_real_estate_min_bps: draft.real_estate.min,
    band_real_estate_max_bps: draft.real_estate.max,
    band_alternatives_min_bps: draft.alternatives.min,
    band_alternatives_max_bps: draft.alternatives.max,
    band_liquidity_min_bps: draft.liquidity.min,
    band_liquidity_max_bps: draft.liquidity.max,
    risky_fraction_bps: extra.risky_fraction_bps ?? null,
    based_on_assessment_id: extra.based_on_assessment_id ?? null,
    policy_id: policyId,
  };
}

/** Liest einen Draft aus einem bestehenden TargetAllocationRecord. */
export function draftFromRecord(rec: TargetAllocationRecord): AllocationDraft {
  return {
    equities: {
      target: rec.target_equities_bps,
      min: rec.band_equities_min_bps,
      max: rec.band_equities_max_bps,
    },
    bonds: {
      target: rec.target_bonds_bps,
      min: rec.band_bonds_min_bps,
      max: rec.band_bonds_max_bps,
    },
    real_estate: {
      target: rec.target_real_estate_bps,
      min: rec.band_real_estate_min_bps,
      max: rec.band_real_estate_max_bps,
    },
    alternatives: {
      target: rec.target_alternatives_bps,
      min: rec.band_alternatives_min_bps,
      max: rec.band_alternatives_max_bps,
    },
    liquidity: {
      target: rec.target_liquidity_bps,
      min: rec.band_liquidity_min_bps,
      max: rec.band_liquidity_max_bps,
    },
  };
}

/** Formatiert bps als Prozent-String (450 → "4.50 %"). */
export function bpsToPct(bps: number): string {
  return `${(bps / 100).toFixed(2)} %`;
}
