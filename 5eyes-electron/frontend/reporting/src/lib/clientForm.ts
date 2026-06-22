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
  notes: string;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Liefert Fehler-Liste (leer = gültig). */
export function validateClient(input: ClientFormInput): string[] {
  const errors: string[] = [];
  if (!input.first_name.trim()) errors.push('Vorname ist erforderlich.');
  if (!input.last_name.trim()) errors.push('Nachname ist erforderlich.');
  if (input.date_of_birth.trim() && !ISO_DATE.test(input.date_of_birth.trim())) {
    errors.push('Geburtsdatum muss im Format JJJJ-MM-TT sein.');
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
    notes: orNull(input.notes),
  };
}

/** Anzeigename für die Trefferliste. */
export function clientDisplayName(c: ClientRecord): string {
  return `${c.last_name}, ${c.first_name}`;
}
