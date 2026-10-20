/**
 * Reine Logik für den Asset-Allocation-Editor (Track #67).
 *
 * Spiegelt die Backend-Invarianten aus schemas/allocation.py
 * `TargetAllocationCreate.validate_alloc` (26-48):
 *  - Summe der 5 Ziel-Quoten == 10000 bps
 *  - je Klasse: min <= max und min <= target <= max
 *
 * Intern bps (10000 = 100%); im Editor wird in Prozent eingegeben
 * (pctInputToBps / bpsToPctInput). Editierbar pro Klasse: target/min/max.
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

export type BandField = 'target' | 'min' | 'max';

const FIELD_LABELS: Record<BandField, string> = { target: 'Ziel', min: 'Minimum', max: 'Maximum' };

/** bps → Prozent-Text für Meldungen (1 Nachkommastelle, 4500 → "45.0 %"). */
function pct1(bps: number): string {
  return `${(bps / 100).toFixed(1)} %`;
}

/** Prozent-Eingabe (z. B. "12.5" oder "12,5") → bps; leer/ungültig → NaN. */
export function pctInputToBps(raw: string): number {
  const cleaned = String(raw ?? '').replace('%', '').replace(',', '.').trim();
  if (cleaned === '') return Number.NaN;
  const value = Number(cleaned);
  return Number.isFinite(value) ? Math.round(value * 100) : Number.NaN;
}

/** bps → Wert für das Prozent-Eingabefeld (1 Nachkommastelle). */
export function bpsToPctInput(bps: number): string {
  return Number.isFinite(bps) ? (bps / 100).toFixed(1) : '';
}

/**
 * Feldgenaue Validierung, 1:1 zur Backend-validate_alloc
 * (schemas/allocation.py TargetAllocationCreate: je Feld int 0..10000,
 * min <= max, min <= target <= max). Die Summe prüft validateAllocation.
 */
export function fieldErrors(
  draft: AllocationDraft,
): Partial<Record<AllocationBucketKey, Partial<Record<BandField, string>>>> {
  const out: Partial<Record<AllocationBucketKey, Partial<Record<BandField, string>>>> = {};
  const put = (key: AllocationBucketKey, field: BandField, msg: string) => {
    out[key] = { ...(out[key] ?? {}), [field]: msg };
  };
  for (const { key, label } of ALLOCATION_BUCKETS) {
    const band = draft[key];
    if (!band) continue;
    let numeric = true;
    for (const field of ['target', 'min', 'max'] as BandField[]) {
      const value = band[field];
      if (!Number.isFinite(value) || !Number.isInteger(value)) {
        put(key, field, `${label} ${FIELD_LABELS[field]}: bitte einen Prozentwert eingeben.`);
        numeric = false;
      } else if (value < 0 || value > 10000) {
        put(key, field, `${label} ${FIELD_LABELS[field]}: Wert muss zwischen 0 % und 100 % liegen.`);
        numeric = false;
      }
    }
    if (!numeric) continue;
    if (band.min > band.max) {
      const msg = `${label}: Bandbreite ungültig — Minimum ${pct1(band.min)} liegt über dem Maximum ${pct1(band.max)}.`;
      put(key, 'min', msg);
      put(key, 'max', msg);
      continue;
    }
    if (!(band.min <= band.target && band.target <= band.max)) {
      put(
        key,
        'target',
        `${label}: Ziel ${pct1(band.target)} muss zwischen Minimum ${pct1(band.min)} und Maximum ${pct1(band.max)} liegen.`,
      );
    }
  }
  return out;
}

/**
 * Clientseitige Validierung, 1:1 zur Backend-validate_alloc. Liefert eine
 * Liste menschenlesbarer Fehler (leer = gültig). Meldungen in Prozent.
 */
export function validateAllocation(draft: AllocationDraft): string[] {
  const perField = fieldErrors(draft);
  const errors: string[] = [];
  for (const { key } of ALLOCATION_BUCKETS) {
    for (const msg of Object.values(perField[key] ?? {})) {
      if (msg && !errors.includes(msg)) errors.push(msg);
    }
  }
  const allNumeric = ALLOCATION_BUCKETS.every(({ key }) =>
    (['target', 'min', 'max'] as BandField[]).every((f) => Number.isInteger(draft[key]?.[f])),
  );
  if (!allNumeric) return errors;
  const total = totalTargetBps(draft);
  if (total !== 10000) {
    errors.unshift(`Die Ziel-Quoten müssen zusammen 100 % ergeben — aktuell ${pct1(total)}.`);
  }
  return errors;
}

/** Baut den TargetAllocationCreate-Payload aus dem Draft. */
export function buildTargetAllocationPayload(
  draft: AllocationDraft,
  policyId: string,
  extra: {
    risky_fraction_bps?: number | null;
    based_on_assessment_id?: string | null;
    override_reason?: string | null;
  } = {},
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
    override_reason: extra.override_reason ?? null,
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
