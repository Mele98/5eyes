/**
 * Reine Logik für den Mandate-Editor (Track #65).
 *
 * Backend-Vertrag schemas/mandates.py MandateUpdate (32-58). Das Backend
 * validiert die Literals; die fachliche Plausibilität der Jahre prüfen wir
 * clientseitig (analog MaxPensionSpendingRequest: life_expectancy > retirement).
 */
import type {
  AdvisoryLanguage,
  ClientSex,
  InvestmentUniverse,
  MandateStatus,
  MandateType,
  MandateUpdatePayload,
} from '@/api/types';

export const MANDATE_TYPES: readonly MandateType[] = [
  'Vermögensverwaltung',
  'Anlageberatung',
  'Finanzplanung',
  'Reporting only',
] as const;
export const MANDATE_STATUSES: readonly MandateStatus[] = ['Aktiv', 'Inaktiv', 'Archiviert'] as const;
export const ADVISORY_LANGUAGES: readonly AdvisoryLanguage[] = ['DE', 'FR', 'IT', 'EN'] as const;
export const INVESTMENT_UNIVERSES: readonly InvestmentUniverse[] = ['Standard', 'Alternativ'] as const;
export const CLIENT_SEXES: readonly ClientSex[] = ['M', 'F'] as const;

const YEAR_MIN = 1900;
const YEAR_MAX = 2200;

export interface MandateFormInput {
  mandate_type: MandateType;
  status: MandateStatus;
  base_currency: string;
  advisory_language: AdvisoryLanguage;
  depot_bank: string;
  depot_account_number: string;
  retirement_year: string;
  life_expectancy_year: string;
  investment_universe: InvestmentUniverse;
  client_birth_year: string;
  client_sex: '' | ClientSex;
  use_mortality_simulation: boolean;
  tax_jurisdiction: string;
}

function parseYear(value: string): number | null {
  const t = (value ?? '').trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isInteger(n) ? n : NaN;
}

/** Liefert Fehler-Liste (leer = gültig). */
export function validateMandate(input: MandateFormInput): string[] {
  const errors: string[] = [];
  const years: Array<[string, string]> = [
    ['Pensionierungsjahr', input.retirement_year],
    ['Lebenserwartung (Jahr)', input.life_expectancy_year],
    ['Geburtsjahr', input.client_birth_year],
  ];
  for (const [label, raw] of years) {
    const y = parseYear(raw);
    if (y === null) continue;
    if (Number.isNaN(y) || y < YEAR_MIN || y > YEAR_MAX) {
      errors.push(`${label} muss eine Jahreszahl zwischen ${YEAR_MIN} und ${YEAR_MAX} sein.`);
    }
  }
  const ret = parseYear(input.retirement_year);
  const life = parseYear(input.life_expectancy_year);
  if (typeof ret === 'number' && !Number.isNaN(ret) && typeof life === 'number' && !Number.isNaN(life)) {
    if (life <= ret) {
      errors.push('Lebenserwartung muss nach dem Pensionierungsjahr liegen.');
    }
  }
  if (!input.base_currency.trim()) {
    errors.push('Basiswährung ist erforderlich.');
  }
  return errors;
}

/** Baut den MandateUpdate-Payload; leere Strings → null, Jahre → number|null. */
export function buildMandateUpdatePayload(input: MandateFormInput): MandateUpdatePayload {
  const year = (v: string): number | null => {
    const y = parseYear(v);
    return typeof y === 'number' && !Number.isNaN(y) ? y : null;
  };
  return {
    mandate_type: input.mandate_type,
    status: input.status,
    base_currency: input.base_currency.trim(),
    advisory_language: input.advisory_language,
    depot_bank: input.depot_bank.trim() || null,
    depot_account_number: input.depot_account_number.trim() || null,
    retirement_year: year(input.retirement_year),
    life_expectancy_year: year(input.life_expectancy_year),
    investment_universe: input.investment_universe,
    client_birth_year: year(input.client_birth_year),
    client_sex: input.client_sex === '' ? null : input.client_sex,
    use_mortality_simulation: input.use_mortality_simulation,
    tax_jurisdiction: input.tax_jurisdiction.trim() || null,
  };
}
