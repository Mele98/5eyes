/**
 * Unit-Tests für die Mandate-Form-Logik (Track #65).
 */
import { describe, expect, it } from 'vitest';
import {
  buildMandateUpdatePayload,
  validateMandate,
  type MandateFormInput,
} from './mandateForm';

function base(overrides: Partial<MandateFormInput> = {}): MandateFormInput {
  return {
    mandate_type: 'Anlageberatung',
    status: 'Aktiv',
    base_currency: 'CHF',
    advisory_language: 'DE',
    depot_bank: '',
    depot_account_number: '',
    retirement_year: '',
    life_expectancy_year: '',
    investment_universe: 'Standard',
    client_birth_year: '',
    client_sex: '',
    use_mortality_simulation: false,
    tax_jurisdiction: '',
    ...overrides,
  };
}

describe('validateMandate', () => {
  it('akzeptiert ein minimal gültiges Mandat', () => {
    expect(validateMandate(base())).toEqual([]);
  });

  it('meldet ein Jahr ausserhalb [1900,2200]', () => {
    const errs = validateMandate(base({ retirement_year: '1800' }));
    expect(errs.some((e) => e.includes('Pensionierungsjahr'))).toBe(true);
  });

  it('meldet Lebenserwartung <= Pensionierungsjahr', () => {
    const errs = validateMandate(base({ retirement_year: '2040', life_expectancy_year: '2035' }));
    expect(errs).toContain('Lebenserwartung muss nach dem Pensionierungsjahr liegen.');
  });

  it('akzeptiert Lebenserwartung nach Pensionierung', () => {
    expect(validateMandate(base({ retirement_year: '2040', life_expectancy_year: '2065' }))).toEqual([]);
  });

  it('meldet fehlende Basiswährung', () => {
    expect(validateMandate(base({ base_currency: '  ' }))).toContain('Basiswährung ist erforderlich.');
  });
});

describe('buildMandateUpdatePayload', () => {
  it('wandelt leere Strings in null und Jahre in Zahlen', () => {
    const payload = buildMandateUpdatePayload(base({
      depot_bank: '',
      retirement_year: '2040',
      client_sex: '',
      tax_jurisdiction: '  ',
    }));
    expect(payload.depot_bank).toBeNull();
    expect(payload.retirement_year).toBe(2040);
    expect(payload.client_sex).toBeNull();
    expect(payload.tax_jurisdiction).toBeNull();
    expect(payload.base_currency).toBe('CHF');
  });

  it('übernimmt gesetzte Werte', () => {
    const payload = buildMandateUpdatePayload(base({
      depot_bank: 'UBS',
      client_sex: 'F',
      tax_jurisdiction: 'CH-ZH',
      use_mortality_simulation: true,
    }));
    expect(payload.depot_bank).toBe('UBS');
    expect(payload.client_sex).toBe('F');
    expect(payload.tax_jurisdiction).toBe('CH-ZH');
    expect(payload.use_mortality_simulation).toBe(true);
  });
});
