/**
 * Unit-Tests für die Goal-Form-Logik (Track #64).
 *
 * Sichert die Spiegelung der Backend-Invarianten aus schemas/wealth.py:
 * Family-Ableitung, Härte-Mapping, Feld-Isolation und Payload-Bau.
 */
import { describe, expect, it } from 'vitest';
import {
  buildGoalPayload,
  familyForType,
  formatGoalError,
  hardnessForRank,
  validateGoalForm,
  type GoalFormInput,
} from './goalForm';
import type { GoalType } from '@/api/types';

describe('familyForType', () => {
  const cases: Array<[GoalType, string]> = [
    ['Kapitalerhalt', 'Vermögen'],
    ['Vermögensziel', 'Vermögen'],
    ['Vermoegensziel', 'Vermögen'],
    ['Einmalige_Ausgabe', 'Cashflow'],
    ['Wiederkehrende_Ausgabe', 'Cashflow'],
    ['Pensionsausgabe', 'Cashflow'],
    ['Renditeziel', 'Rendite'],
    ['Maximierung', 'Maximierung'],
  ];
  it.each(cases)('%s → %s', (type, family) => {
    expect(familyForType(type)).toBe(family);
  });
});

describe('hardnessForRank', () => {
  it('mappt Rang 1/2/3 auf Hart/Primär/Opportunistisch', () => {
    expect(hardnessForRank(1)).toBe('Hart');
    expect(hardnessForRank(2)).toBe('Primär');
    expect(hardnessForRank(3)).toBe('Opportunistisch');
  });
  it('fällt für unbekannte Ränge auf Primär zurück', () => {
    expect(hardnessForRank(99)).toBe('Primär');
  });
});

describe('validateGoalForm', () => {
  const base: GoalFormInput = {
    goal_type: 'Renditeziel',
    label: 'Wachstum',
    rank: 2,
    hardness: 'Primär',
  };

  it('akzeptiert ein gültiges Renditeziel', () => {
    expect(validateGoalForm({ ...base, target_return_bps: 450 })).toEqual([]);
  });

  it('verlangt target_return_bps für Renditeziel', () => {
    const errs = validateGoalForm({ ...base });
    expect(errs).toContain('Renditeziel benötigt target_return_bps');
  });

  it('verbietet ein "hartes" Renditeziel', () => {
    const errs = validateGoalForm({ ...base, hardness: 'Hart', target_return_bps: 450 });
    expect(errs.some((e) => e.includes("nicht als 'hart'"))).toBe(true);
  });

  it('verlangt Datum oder Horizont für Einmalige_Ausgabe', () => {
    const errs = validateGoalForm({
      goal_type: 'Einmalige_Ausgabe',
      label: 'Auto',
      rank: 1,
      hardness: 'Primär',
      target_amount_rappen: 5_000_00,
    });
    expect(errs).toContain('Einmalige_Ausgabe benötigt target_date oder horizon_years');
  });

  it('verlangt target_wealth_rappen für Vermögensziel', () => {
    const errs = validateGoalForm({
      goal_type: 'Vermögensziel',
      label: 'Vorsorge',
      rank: 1,
      hardness: 'Hart',
      target_date: '2035-01-01',
    });
    expect(errs).toContain('Vermögensziel benötigt target_wealth_rappen');
  });

  it('meldet ein fehlendes Label', () => {
    const errs = validateGoalForm({ ...base, label: '   ', target_return_bps: 450 });
    expect(errs).toContain('Bezeichnung ist erforderlich.');
  });

  it('verbietet ein für den Typ unzulässiges Feld', () => {
    const errs = validateGoalForm({
      ...base,
      target_return_bps: 450,
      frequency: 'jaehrlich',
    });
    expect(errs.some((e) => e.includes("Feld 'frequency'"))).toBe(true);
  });
});

describe('buildGoalPayload', () => {
  it('setzt für Renditeziel nur target_return_bps', () => {
    const payload = buildGoalPayload({
      goal_type: 'Renditeziel',
      label: 'Wachstum',
      rank: 2,
      hardness: 'Primär',
      target_return_bps: 450,
    });
    expect(payload.goal_family).toBe('Rendite');
    expect(payload.target_return_bps).toBe(450);
    expect(payload.target_amount_rappen).toBeNull();
    expect(payload.target_wealth_rappen).toBeNull();
    expect(payload.frequency).toBeNull();
    expect(payload.value_mode).toBe('nominal');
    expect(payload.data_classification).toBe('synthetic');
  });

  it('übernimmt value_mode nur bei Vermögenszielen', () => {
    const payload = buildGoalPayload({
      goal_type: 'Vermögensziel',
      label: 'Vorsorge',
      rank: 1,
      hardness: 'Hart',
      value_mode: 'real',
      target_wealth_rappen: 1_000_000_00,
      target_date: '2035-01-01',
    });
    expect(payload.goal_family).toBe('Vermögen');
    expect(payload.target_wealth_rappen).toBe(1_000_000_00);
    expect(payload.value_mode).toBe('real');
    expect(payload.target_return_bps).toBeNull();
    expect(payload.target_amount_rappen).toBeNull();
  });
});

describe('formatGoalError', () => {
  it('gibt einen String unverändert zurück', () => {
    expect(formatGoalError('Kaputt')).toBe('Kaputt');
  });
  it('flacht ein FastAPI-422-Array über .msg', () => {
    const detail = [
      { loc: ['body', 'rank'], msg: 'ensure this value is >= 1' },
      { loc: ['body', 'label'], msg: 'field required' },
    ];
    expect(formatGoalError(detail)).toBe('ensure this value is >= 1; field required');
  });
  it('liest .msg aus einem Objekt', () => {
    expect(formatGoalError({ msg: 'Einzelfehler' })).toBe('Einzelfehler');
  });
  it('fällt auf eine Default-Meldung zurück', () => {
    expect(formatGoalError(null)).toContain('Unbekannter Fehler');
  });
});
