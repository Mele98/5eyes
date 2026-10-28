/**
 * GOAL-RECURRING-EDITOR-CONTRACT-001 (Frontend-Teil): der Wizard erzwingt
 * denselben Strom-Vertrag wie die API (services/goal_semantics.py,
 * routers/wealth.py:_normalize_goal_payload) und ordnet 422-Fehler feldgenau zu.
 */
import { describe, expect, it } from 'vitest';
import {
  MAX_GOAL_RAPPEN,
  buildGoalPayload,
  goalFieldErrorsFromApi,
  validateGoalFormFields,
  type GoalFormInput,
} from './goalForm';

const finiteStream: GoalFormInput = {
  goal_type: 'Wiederkehrende_Ausgabe',
  label: 'Lebenshaltung',
  rank: 2,
  hardness: 'Primär',
  frequency: 'jaehrlich',
  target_amount_rappen: 48_000_00,
  start_date: '2030-01-01',
  target_date: '2040-01-01',
  is_ongoing: false,
};

const fieldsOf = (input: GoalFormInput) => validateGoalFormFields(input).map((e) => e.field);

describe('validateGoalFormFields: Strom-Vertrag', () => {
  it('akzeptiert einen vollständigen endlichen Strom', () => {
    expect(validateGoalFormFields(finiteStream)).toEqual([]);
  });

  it('akzeptiert einen laufenden Pensionsstrom ohne Enddatum', () => {
    expect(
      validateGoalFormFields({
        ...finiteStream,
        goal_type: 'Pensionsausgabe',
        target_date: null,
        is_ongoing: true,
        pension_pillar: 'BVG',
      }),
    ).toEqual([]);
  });

  it('laufend + Enddatum ist ein Fehler am Enddatum', () => {
    expect(fieldsOf({ ...finiteStream, is_ongoing: true })).toEqual(['target_date']);
  });

  it('endlich ohne Enddatum ist ein Fehler am Enddatum (kein Default-Horizont)', () => {
    expect(fieldsOf({ ...finiteStream, target_date: null, horizon_years: 10 })).toEqual([
      'target_date',
    ]);
  });

  it('Enddatum vor Startdatum ist ein Fehler am Enddatum', () => {
    expect(fieldsOf({ ...finiteStream, target_date: '2029-12-31' })).toEqual(['target_date']);
  });

  it('fehlendes Startdatum ist ein Fehler am Startdatum, auch mit Horizont', () => {
    expect(fieldsOf({ ...finiteStream, start_date: null, horizon_years: 10 })).toEqual([
      'start_date',
    ]);
  });

  it.each([
    ['null', null],
    ['0', 0],
    ['negativ', -100],
    ['NaN (keine Zahl)', Number.NaN],
    ['Bruchteil eines Rappens', 100.5],
  ])('Betrag %s ist ein Fehler am Betrag', (_label, amount) => {
    expect(fieldsOf({ ...finiteStream, target_amount_rappen: amount })).toEqual([
      'target_amount_rappen',
    ]);
  });

  it('Betrag über der Obergrenze ist ein Fehler, an der Grenze nicht', () => {
    expect(fieldsOf({ ...finiteStream, target_amount_rappen: MAX_GOAL_RAPPEN })).toEqual([]);
    expect(fieldsOf({ ...finiteStream, target_amount_rappen: 2 ** 63 })).toEqual([
      'target_amount_rappen',
    ]);
  });

  it('Obergrenze gilt auch für Zielvermögen und einmalige Ausgaben', () => {
    expect(
      fieldsOf({
        goal_type: 'Vermögensziel',
        label: 'Vorsorge',
        rank: 1,
        hardness: 'Hart',
        target_wealth_rappen: 2 ** 63,
        target_date: '2035-01-01',
      }),
    ).toEqual(['target_wealth_rappen']);
    expect(
      fieldsOf({
        goal_type: 'Einmalige_Ausgabe',
        label: 'Haus',
        rank: 1,
        hardness: 'Hart',
        target_amount_rappen: 2 ** 63,
        target_date: '2035-01-01',
      }),
    ).toEqual(['target_amount_rappen']);
  });

  it('einmalig ist keine wiederkehrende Frequenz', () => {
    expect(fieldsOf({ ...finiteStream, frequency: 'einmalig' })).toEqual(['frequency']);
  });

  it.each(['monatlich', 'quartalsweise', 'halbjaehrlich', 'halbjährlich', 'jährlich'])(
    'Frequenz %s ist gültig',
    (frequency) => {
      expect(validateGoalFormFields({ ...finiteStream, frequency })).toEqual([]);
    },
  );
});

describe('buildGoalPayload: Rang/Härte getrennt, Strom-Normalisierung', () => {
  it('leitet die Härte nie aus dem Rang ab (Default Primär wie das Backend)', () => {
    const { hardness: _omit, ...withoutHardness } = finiteStream;
    expect(buildGoalPayload({ ...withoutHardness, rank: 1 }).hardness).toBe('Primär');
    expect(buildGoalPayload({ ...finiteStream, rank: 3, hardness: 'Hart' }).hardness).toBe('Hart');
  });

  it('sendet für Nicht-Ströme nie is_ongoing=true', () => {
    expect(
      buildGoalPayload({
        goal_type: 'Einmalige_Ausgabe',
        label: 'Haus',
        rank: 1,
        target_amount_rappen: 100,
        target_date: '2035-01-01',
        is_ongoing: true,
      }).is_ongoing,
    ).toBe(false);
  });

  it('Renditeziel bleibt nominal, auch wenn real übergeben wird', () => {
    expect(
      buildGoalPayload({
        goal_type: 'Renditeziel',
        label: 'Wachstum',
        rank: 2,
        target_return_bps: 450,
        value_mode: 'real',
      }).value_mode,
    ).toBe('nominal');
  });
});

describe('goalFieldErrorsFromApi', () => {
  it('ordnet Pydantic-Fehler über loc dem Feld zu', () => {
    expect(
      goalFieldErrorsFromApi([
        { loc: ['body', 'rank'], msg: 'ensure this value is >= 1' },
        { loc: ['body'], msg: 'irgendwas' },
      ]),
    ).toEqual([
      { field: 'rank', message: 'ensure this value is >= 1' },
      { field: null, message: 'irgendwas' },
    ]);
  });

  it.each([
    [
      'Ein laufendes wiederkehrendes Ziel darf kein Enddatum haben; entweder laufend ohne Enddatum oder endlich mit Enddatum.',
      'target_date',
    ],
    ['Zieldatum darf nicht vor dem Startdatum liegen', 'target_date'],
    [
      'Wiederkehrende und Pensions-Ziele benoetigen eine unterstuetzte wiederkehrende Frequenz.',
      'frequency',
    ],
    ["Ziel 'X': positiver Zielbetrag fehlt.", 'target_amount_rappen'],
    ["Ziel 'X': target_amount_rappen ist zu gross.", 'target_amount_rappen'],
    [
      "Ziel 'X': ein endliches wiederkehrendes Ziel benoetigt target_date; ohne Enddatum muss is_ongoing=1 sein.",
      'target_date',
    ],
    ["Renditeziel darf nicht als 'hart' definiert werden.", 'hardness'],
    ['Zeithorizont muss mindestens 1 Jahr betragen', 'horizon_years'],
  ])('Meldung "%s" -> %s', (detail, field) => {
    expect(goalFieldErrorsFromApi(detail)).toEqual([{ field, message: detail }]);
  });

  it('nicht zuordenbare Meldung bleibt allgemein', () => {
    expect(goalFieldErrorsFromApi('Mandat gesperrt')).toEqual([
      { field: null, message: 'Mandat gesperrt' },
    ]);
  });

  it('strukturierte Fehler werden über den zentralen Formatter gelesen', () => {
    expect(
      goalFieldErrorsFromApi({ reason_code: 'X', message: 'Startdatum fehlt' }),
    ).toEqual([{ field: 'start_date', message: 'Startdatum fehlt [X]' }]);
  });
});
