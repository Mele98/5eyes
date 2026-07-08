/**
 * Reine Logik für den CRM/Stammdaten-Editor (Track #66).
 *
 * Backend-Vertrag schemas/clients.py ClientUpdate (36-60). Pflichtfelder im
 * Edit: Vor-/Nachname. Datumsfelder optional (ISO YYYY-MM-DD).
 */
import type {
  ClientClassification,
  ClientLanguage,
  ClientRecord,
  ClientUpdatePayload,
  HouseholdType,
  Salutation,
} from '@/api/types';

export const SALUTATIONS: readonly Salutation[] = ['Herr', 'Frau', 'Divers'] as const;
export const HOUSEHOLD_TYPES: readonly HouseholdType[] = ['Einzelperson', 'Paar', 'Familie'] as const;
export const CLIENT_CLASSIFICATIONS: readonly ClientClassification[] = [
  'Privatkunde',
  'Professioneller Kunde',
  'Institutioneller Kunde',
] as const;
export const CLIENT_LANGUAGES: readonly ClientLanguage[] = ['DE', 'FR', 'IT', 'EN'] as const;

export interface ClientFormInput {
  salutation: '' | Salutation;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  investment_horizon_start: string;
  investment_horizon_end: string;
  country_of_residence: string;
  canton: string;
  civil_status: string;
  profession: string;
  employer: string;
  language: ClientLanguage;
  household_type: HouseholdType;
  client_classification: ClientClassification;
  is_qualified_investor: boolean;
  is_professional_opt_out: boolean;
  // crm-2: Partner-Stammdaten (relevant bei household_type 'Paar'/'Familie').
  partner_salutation: '' | Salutation;
  partner_first_name: string;
  partner_last_name: string;
  partner_date_of_birth: string;
  partner_profession: string;
  notes: string;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Liefert Fehler-Liste (leer = gültig). */
export function validateClient(input: ClientFormInput): string[] {
  const errors: string[] = [];
  if (!input.first_name.trim()) errors.push('Vorname ist erforderlich.');
  if (!input.last_name.trim()) errors.push('Nachname ist erforderlich.');
  const dateFields: Array<[string, string]> = [
    ['Geburtsdatum', input.date_of_birth],
    ['Partner-Geburtsdatum', input.partner_date_of_birth],
    ['Anlagehorizont-Start', input.investment_horizon_start],
    ['Anlagehorizont-Ende', input.investment_horizon_end],
  ];
  for (const [label, v] of dateFields) {
    if (v.trim() && !ISO_DATE.test(v.trim())) {
      errors.push(`${label} muss im Format JJJJ-MM-TT sein.`);
    }
  }
  if (
    input.investment_horizon_start.trim() &&
    input.investment_horizon_end.trim() &&
    input.investment_horizon_end < input.investment_horizon_start
  ) {
    errors.push('Anlagehorizont-Ende darf nicht vor dem Start liegen.');
  }
  return errors;
}

/** Baut den ClientUpdate-Payload; leere optionale Strings → null. */
export function buildClientUpdatePayload(input: ClientFormInput): ClientUpdatePayload {
  const orNull = (v: string): string | null => (v.trim() === '' ? null : v.trim());
  return {
    salutation: input.salutation === '' ? null : input.salutation,
    first_name: input.first_name.trim(),
    last_name: input.last_name.trim(),
    date_of_birth: orNull(input.date_of_birth),
    investment_horizon_start: orNull(input.investment_horizon_start),
    investment_horizon_end: orNull(input.investment_horizon_end),
    country_of_residence: input.country_of_residence.trim() || 'CH',
    canton: orNull(input.canton),
    civil_status: orNull(input.civil_status),
    profession: orNull(input.profession),
    employer: orNull(input.employer),
    language: input.language,
    household_type: input.household_type,
    client_classification: input.client_classification,
    is_qualified_investor: input.is_qualified_investor,
    is_professional_opt_out: input.is_professional_opt_out,
    partner_salutation: input.partner_salutation === '' ? null : input.partner_salutation,
    partner_first_name: orNull(input.partner_first_name),
    partner_last_name: orNull(input.partner_last_name),
    partner_date_of_birth: orNull(input.partner_date_of_birth),
    partner_profession: orNull(input.partner_profession),
    notes: orNull(input.notes),
  };
}

/** Anzeigename für die Trefferliste. */
export function clientDisplayName(c: ClientRecord): string {
  return `${c.last_name}, ${c.first_name}`;
}
