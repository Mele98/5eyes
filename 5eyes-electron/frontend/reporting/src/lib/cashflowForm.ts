/**
 * Reine Logik für den Cashflow-Editor (Track #68).
 *
 * Backend-Vertrag: schemas/wealth.py CashflowCreate (171-185). Das Backend
 * erzwingt nur die Literals (cashflow_type, nature); die fachliche
 * Plausibilität (Betrag, Datumsspanne) prüfen wir clientseitig.
 *
 * Konvention (Memory project_5eyes_cashflow_konventionen): valid_until ist
 * INKLUSIV — der letzte Gültigkeitstag zählt noch dazu.
 */
import type {
  CashflowCreatePayload,
  CashflowNature,
  CashflowType,
} from '@/api/types';

export const CASHFLOW_FREQUENCIES = ['jährlich', 'monatlich', 'einmalig'] as const;

export interface CashflowFormInput {
  cashflow_type: CashflowType;
  label: string;
  amountChf: string;
  currency?: string;
  frequency?: string;
  nature?: CashflowNature;
  valid_from?: string | null;
  valid_until?: string | null;
  is_inflation_linked?: boolean;
  notes?: string | null;
}

function parseChf(value: string): number | null {
  const trimmed = (value ?? '').trim();
  if (trimmed === '') return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** Liefert Fehler-Liste (leer = gültig). valid_until INKLUSIV → darf == valid_from sein. */
export function validateCashflow(input: CashflowFormInput): string[] {
  const errors: string[] = [];
  if (!input.label || !input.label.trim()) {
    errors.push('Bezeichnung ist erforderlich.');
  }
  const amount = parseChf(input.amountChf);
  if (amount === null) {
    errors.push('Betrag muss eine Zahl sein.');
  } else if (amount <= 0) {
    errors.push('Betrag muss grösser als 0 sein.');
  }
  if (input.cashflow_type !== 'Income' && input.cashflow_type !== 'Expense') {
    errors.push("cashflow_type muss 'Income' oder 'Expense' sein.");
  }
  if (input.valid_from && input.valid_until && input.valid_until < input.valid_from) {
    errors.push('valid_until darf nicht vor valid_from liegen (valid_until ist inklusiv).');
  }
  return errors;
}

/** Baut den CashflowCreate-Payload; CHF → Rappen (×100), data_classification synthetic. */
export function buildCashflowPayload(input: CashflowFormInput): CashflowCreatePayload {
  const amount = parseChf(input.amountChf) ?? 0;
  return {
    cashflow_type: input.cashflow_type,
    label: input.label.trim(),
    amount_rappen: Math.round(amount * 100),
    currency: input.currency ?? 'CHF',
    frequency: input.frequency ?? 'jährlich',
    nature: input.nature ?? 'wiederkehrend',
    valid_from: input.valid_from || null,
    valid_until: input.valid_until || null,
    is_inflation_linked: input.is_inflation_linked ?? false,
    notes: input.notes || null,
    data_classification: 'synthetic',
  };
}

/** CHF-Anzeige aus Rappen (1234500 → "CHF 12'345"). */
export function rappenToChf(rappen: number): string {
  return `CHF ${Math.round(rappen / 100).toLocaleString('de-CH')}`;
}
