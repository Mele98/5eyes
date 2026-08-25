/**
 * Unit-Tests für die Client-Form-Logik (Track #66).
 */
import { describe, expect, it } from 'vitest';
import {
  buildClientUpdatePayload,
  clientDisplayName,
  validateClient,
  type ClientFormInput,
} from './clientForm';
import type { ClientRecord } from '@/api/types';

function base(overrides: Partial<ClientFormInput> = {}): ClientFormInput {
  return {
    salutation: 'Herr',
    first_name: 'Max',
    last_name: 'Muster',
    date_of_birth: '1975-06-01',
    investment_horizon_start: '',
    investment_horizon_end: '',
    country_of_residence: 'CH',
    canton: 'ZH',
    civil_status: 'verheiratet',
    profession: 'Ingenieur',
    employer: 'ACME',
    language: 'DE',
    household_type: 'Paar',
    client_classification: 'Privatkunde',
    is_qualified_investor: false,
    is_professional_opt_out: false,
    partner_salutation: '',
    partner_first_name: '',
    partner_last_name: '',
    partner_date_of_birth: '',
    partner_profession: '',
    notes: '',
    ...overrides,
  };
}

describe('validateClient', () => {
  it('akzeptiert gültige Stammdaten', () => {
    expect(validateClient(base())).toEqual([]);
  });
  it('meldet fehlenden Vornamen', () => {
    expect(validateClient(base({ first_name: ' ' }))).toContain('Vorname ist erforderlich.');
  });
  it('meldet fehlenden Nachnamen', () => {
    expect(validateClient(base({ last_name: '' }))).toContain('Nachname ist erforderlich.');
  });
  it('meldet ungültiges Geburtsdatum-Format', () => {
    expect(validateClient(base({ date_of_birth: '01.06.1975' }))).toContain('Geburtsdatum muss im Format JJJJ-MM-TT sein.');
  });
  it('akzeptiert leeres Geburtsdatum', () => {
    expect(validateClient(base({ date_of_birth: '' }))).toEqual([]);
  });
});

describe('buildClientUpdatePayload', () => {
  it('wandelt leere optionale Felder in null und trimmt', () => {
    const payload = buildClientUpdatePayload(base({ canton: '  ', salutation: '', notes: '  ', first_name: ' Max ' }));
    expect(payload.canton).toBeNull();
    expect(payload.salutation).toBeNull();
    expect(payload.notes).toBeNull();
    expect(payload.first_name).toBe('Max');
    expect(payload.country_of_residence).toBe('CH');
  });
  it('default Wohnsitzland CH bei leer', () => {
    expect(buildClientUpdatePayload(base({ country_of_residence: '' })).country_of_residence).toBe('CH');
  });
});

describe('clientDisplayName', () => {
  it('formatiert "Nachname, Vorname"', () => {
    expect(clientDisplayName({ first_name: 'Max', last_name: 'Muster' } as ClientRecord)).toBe('Muster, Max');
  });
});

describe('crm-2: Partner-Felder + Anlagehorizont', () => {
  it('übernimmt Partner-Daten + Anlagehorizont in den Payload', () => {
    const p = buildClientUpdatePayload(base({
      partner_salutation: 'Frau',
      partner_first_name: 'Anna',
      partner_last_name: 'Muster',
      partner_date_of_birth: '1978-03-04',
      partner_profession: 'Ärztin',
      investment_horizon_start: '2026-01-01',
      investment_horizon_end: '2046-01-01',
    }));
    expect(p.partner_salutation).toBe('Frau');
    expect(p.partner_first_name).toBe('Anna');
    expect(p.partner_date_of_birth).toBe('1978-03-04');
    expect(p.investment_horizon_start).toBe('2026-01-01');
    expect(p.investment_horizon_end).toBe('2046-01-01');
  });
  it('leere Partner-Felder → null', () => {
    const p = buildClientUpdatePayload(base());
    expect(p.partner_salutation).toBeNull();
    expect(p.partner_first_name).toBeNull();
    expect(p.investment_horizon_start).toBeNull();
  });
  it('meldet ungültiges Partner-Geburtsdatum', () => {
    expect(validateClient(base({ partner_date_of_birth: '04.03.1978' }))).toContain('Partner-Geburtsdatum muss im Format JJJJ-MM-TT sein.');
  });
  it('meldet Anlagehorizont-Ende vor Start', () => {
    const errs = validateClient(base({ investment_horizon_start: '2046-01-01', investment_horizon_end: '2026-01-01' }));
    expect(errs).toContain('Anlagehorizont-Ende darf nicht vor dem Start liegen.');
  });
});
