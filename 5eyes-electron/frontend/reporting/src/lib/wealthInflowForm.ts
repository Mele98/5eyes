/**
 * Reine Logik für den Vermögenszuflüsse-Editor (Roadmap #54).
 *
 * Spiegelt schemas/wealth.py WealthInflowCreate (264-283), insbesondere den
 * _validate_recurring-Validator: is_recurring=1 erfordert frequency
 * 'jaehrlich'|'monatlich' (nicht 'einmalig') UND duration_years.
 */
import type {
  WealthInflowCreatePayload,
  WealthInflowFrequency,
  WealthInflowSourceType,
} from '@/api/types';

export const WEALTH_INFLOW_SOURCE_TYPES: readonly WealthInflowSourceType[] = [
  'Erbschaft',
  'Bonus',
  'Saeule3b',
  'Verkaufserloes',
  'Andere',
] as const;

export const WEALTH_INFLOW_FREQUENCIES: readonly WealthInflowFrequency[] = [
  'einmalig',
  'jaehrlich',
  'monatlich',
] as const;

const YEAR_MIN = 1900;
const YEAR_MAX = 2200;

export interface WealthInflowFormInput {
  label: string;
  source_type: WealthInflowSourceType;
  amountChf: string;
  expected_year: string;
  is_recurring: boolean;
  frequency: WealthInflowFrequency;
  duration_years: string;
  value_mode: 'nominal' | 'real';
  notes: string;
}

function parseAmount(value: string): number | null {
  const t = (value ?? '').trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function parseInt10(value: string): number | null {
  const t = (value ?? '').trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isInteger(n) ? n : NaN;
}

/** Liefert Fehler-Liste (leer = gültig). */
export function validateWealthInflow(input: WealthInflowFormInput): string[] {
  const errors: string[] = [];
  const label = input.label.trim();
  if (!label) {
    errors.push('Bezeichnung ist erforderlich.');
  } else if (label.length > 200) {
    errors.push('Bezeichnung darf höchstens 200 Zeichen haben.');
  }
  const amount = parseAmount(input.amountChf);
  if (amount === null) {
    errors.push('Betrag muss eine Zahl sein.');
  } else if (amount <= 0) {
    errors.push('Betrag muss grösser als 0 sein.');
  }
  const year = parseInt10(input.expected_year);
  if (year === null || Number.isNaN(year) || year < YEAR_MIN || year > YEAR_MAX) {
    errors.push(`Erwartetes Jahr muss zwischen ${YEAR_MIN} und ${YEAR_MAX} liegen.`);
  }
  if (input.is_recurring) {
    if (!input.frequency || input.frequency === 'einmalig') {
      errors.push("Wiederkehrend erfordert Frequenz 'jaehrlich' oder 'monatlich'.");
    }
    const dur = parseInt10(input.duration_years);
    if (dur === null || Number.isNaN(dur) || dur < 1 || dur > 99) {
      errors.push('Wiederkehrend erfordert eine Dauer (1–99 Jahre).');
    }
  }
  return errors;
}

/** Baut den WealthInflowCreate-Payload; CHF → Rappen, is_recurring → int 0/1. */
export function buildWealthInflowPayload(input: WealthInflowFormInput): WealthInflowCreatePayload {
  const amount = parseAmount(input.amountChf) ?? 0;
  const recurring = input.is_recurring;
  const duration = parseInt10(input.duration_years);
  return {
    label: input.label.trim(),
    source_type: input.source_type,
    amount_rappen: Math.round(amount * 100),
    expected_year: parseInt10(input.expected_year) ?? 0,
    is_recurring: recurring ? 1 : 0,
    frequency: recurring ? input.frequency : 'einmalig',
    duration_years: recurring ? (typeof duration === 'number' && !Number.isNaN(duration) ? duration : null) : null,
    value_mode: input.value_mode,
    notes: input.notes.trim() || null,
  };
}

/** CHF-Anzeige aus Rappen. */
export function rappenToChf(rappen: number): string {
  return `CHF ${Math.round(rappen / 100).toLocaleString('de-CH')}`;
}
