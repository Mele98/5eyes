/**
 * Unit-Tests für die WealthInflow-Form-Logik (Roadmap #54).
 */
import { describe, expect, it } from 'vitest';
import {
  buildWealthInflowPayload,
  validateWealthInflow,
  type WealthInflowFormInput,
} from './wealthInflowForm';

function base(overrides: Partial<WealthInflowFormInput> = {}): WealthInflowFormInput {
  return {
    label: 'Erbschaft Tante',
    source_type: 'Erbschaft',
    amountChf: '250000',
    expected_year: '2032',
    is_recurring: false,
    frequency: 'jaehrlich',
    duration_years: '',
    value_mode: 'nominal',
    notes: '',
    ...overrides,
  };
}

describe('validateWealthInflow', () => {
  it('akzeptiert einen gültigen einmaligen Zufluss', () => {
    expect(validateWealthInflow(base())).toEqual([]);
  });

  it('akzeptiert einen gültigen wiederkehrenden Zufluss', () => {
    expect(validateWealthInflow(base({ is_recurring: true, frequency: 'jaehrlich', duration_years: '10' }))).toEqual([]);
  });

  it('meldet fehlende Bezeichnung', () => {
    expect(validateWealthInflow(base({ label: ' ' }))).toContain('Bezeichnung ist erforderlich.');
  });

  it('meldet Betrag <= 0', () => {
    expect(validateWealthInflow(base({ amountChf: '0' }))).toContain('Betrag muss grösser als 0 sein.');
  });

  it('meldet Jahr ausserhalb [1900,2200]', () => {
    expect(validateWealthInflow(base({ expected_year: '1850' }))).toContain(
      'Erwartetes Jahr muss zwischen 1900 und 2200 liegen.',
    );
  });

  it('verlangt Frequenz != einmalig bei Wiederkehrend', () => {
    const errs = validateWealthInflow(base({ is_recurring: true, frequency: 'einmalig', duration_years: '5' }));
    expect(errs.some((e) => e.includes("'jaehrlich' oder 'monatlich'"))).toBe(true);
  });

  it('verlangt Dauer bei Wiederkehrend', () => {
    const errs = validateWealthInflow(base({ is_recurring: true, frequency: 'jaehrlich', duration_years: '' }));
    expect(errs.some((e) => e.includes('Dauer'))).toBe(true);
  });
});

describe('buildWealthInflowPayload', () => {
  it('konvertiert CHF→Rappen und einmalig → is_recurring 0 + duration null', () => {
    const p = buildWealthInflowPayload(base({ amountChf: '250000' }));
    expect(p.amount_rappen).toBe(25_000_000);
    expect(p.is_recurring).toBe(0);
    expect(p.frequency).toBe('einmalig');
    expect(p.duration_years).toBeNull();
    expect(p.expected_year).toBe(2032);
  });

  it('setzt is_recurring 1 + Frequenz + Dauer bei wiederkehrend', () => {
    const p = buildWealthInflowPayload(base({ is_recurring: true, frequency: 'monatlich', duration_years: '8' }));
    expect(p.is_recurring).toBe(1);
    expect(p.frequency).toBe('monatlich');
    expect(p.duration_years).toBe(8);
  });
});
