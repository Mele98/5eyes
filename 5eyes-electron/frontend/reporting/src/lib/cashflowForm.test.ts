/**
 * Unit-Tests für die Cashflow-Form-Logik (Track #68).
 */
import { describe, expect, it } from 'vitest';
import {
  buildCashflowPayload,
  validateCashflow,
  type CashflowFormInput,
} from './cashflowForm';

function base(overrides: Partial<CashflowFormInput> = {}): CashflowFormInput {
  return {
    cashflow_type: 'Expense',
    label: 'Lebenshaltung',
    amountChf: '36000',
    frequency: 'jährlich',
    nature: 'wiederkehrend',
    ...overrides,
  };
}

describe('validateCashflow', () => {
  it('akzeptiert einen gültigen Cashflow', () => {
    expect(validateCashflow(base())).toEqual([]);
  });

  it('meldet fehlende Bezeichnung', () => {
    expect(validateCashflow(base({ label: '  ' }))).toContain('Bezeichnung ist erforderlich.');
  });

  it('meldet Betrag <= 0', () => {
    expect(validateCashflow(base({ amountChf: '0' }))).toContain('Betrag muss grösser als 0 sein.');
  });

  it('meldet nicht-numerischen Betrag', () => {
    expect(validateCashflow(base({ amountChf: 'abc' }))).toContain('Betrag muss eine Zahl sein.');
  });

  it('akzeptiert valid_until == valid_from (inklusiv)', () => {
    expect(validateCashflow(base({ valid_from: '2030-01-01', valid_until: '2030-01-01' }))).toEqual([]);
  });

  it('meldet valid_until vor valid_from', () => {
    const errs = validateCashflow(base({ valid_from: '2030-01-01', valid_until: '2029-12-31' }));
    expect(errs.some((e) => e.includes('valid_until darf nicht vor valid_from'))).toBe(true);
  });
});

describe('buildCashflowPayload', () => {
  it('konvertiert CHF → Rappen und setzt Defaults', () => {
    const payload = buildCashflowPayload(base({ amountChf: '1234.56' }));
    expect(payload.amount_rappen).toBe(123456);
    expect(payload.currency).toBe('CHF');
    expect(payload.nature).toBe('wiederkehrend');
    expect(payload.data_classification).toBe('synthetic');
    expect(payload.is_inflation_linked).toBe(false);
  });

  it('übernimmt Datumsspanne und Teuerungsindexierung', () => {
    const payload = buildCashflowPayload(
      base({ valid_from: '2030-01-01', valid_until: '2045-12-31', is_inflation_linked: true }),
    );
    expect(payload.valid_from).toBe('2030-01-01');
    expect(payload.valid_until).toBe('2045-12-31');
    expect(payload.is_inflation_linked).toBe(true);
  });
});
