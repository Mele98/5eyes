/**
 * AA-UX-HONEST-FAN-001: Falltabelle fanAnnotations.contract.json gegen die
 * Report-Implementierung. Dieselbe Tabelle laeuft im Backend gegen die
 * gleichnamigen Monolith-Funktionen (test_monolith_fan_annotations_contract.py).
 */
import { describe, expect, it } from 'vitest';

import contract from './fanAnnotations.contract.json';
import {
  fanAboveScaleText,
  fanEndLabelText,
  fanGoalPillText,
  fanGoalProbability,
  fanRangeSentence,
  fanSpreadLabelYs,
  type FanCanonicalGoalProbability,
  type FanEndKey,
} from './fanAnnotations';

type C = typeof contract;

describe('fanAnnotations — gemeinsamer Vertrag App/Report', () => {
  it.each((contract as C).end_label_cases as Array<[number | null, FanEndKey, string]>)(
    'Endwert %s / %s -> %s',
    (chf, key, expected) => {
      expect(fanEndLabelText(chf, key)).toBe(expected);
    },
  );

  it.each((contract as C).goal_pill_cases as Array<[string | null, number | null, string]>)(
    'Ziel-Pille %s / %s -> %s',
    (label, prob, expected) => {
      expect(fanGoalPillText(label, prob)).toBe(expected);
    },
  );

  it.each((contract as C).above_scale_cases as Array<[number | null, string]>)(
    'Ziel ueber Skala %s -> %s',
    (chf, expected) => {
      expect(fanAboveScaleText(chf)).toBe(expected);
    },
  );

  it.each(
    (contract as C).range_sentence_cases as Array<[string | number, number | null, number | null, string]>,
  )('Satz %s / %s / %s', (year, p10, p90, expected) => {
    expect(fanRangeSentence(year, p10, p90)).toBe(expected);
  });

  it.each(
    (contract as C).spread_cases as Array<[number[], number, number, number, number[]]>,
  )('Entzerrung %j', (ys, gap, top, bottom, expected) => {
    expect(fanSpreadLabelYs(ys, gap, top, bottom)).toEqual(expected);
  });

  it('keine Garantie-/Zusicherungsformulierung im Klartext-Satz', () => {
    const s = fanRangeSentence('2050', 1_600_000, 3_400_000);
    expect(s).not.toMatch(/garant|sicher|gewiss|wird .* erreich/i);
    expect(s).toMatch(/^In 8 von 10 Verläufen/);
  });
});

describe('fanAnnotations — kanonische Quelle der Ziel-Pille (CIO-Entscheid)', () => {
  it.each(
    (contract as C).goal_pill_estimate_cases as Array<[string, number | null, boolean, string]>,
  )('Pille %s / %s / Schaetzung=%s', (label, prob, estimate, expected) => {
    expect(fanGoalPillText(label, prob, estimate)).toBe(expected);
  });

  it.each(
    (contract as C).goal_probability_cases as Array<
      [FanCanonicalGoalProbability | null, number | null, { pct: number; estimate: boolean } | null]
    >,
  )('Quelle %j / Simulation %s', (canonical, sim, expected) => {
    expect(fanGoalProbability(canonical, sim)).toEqual(expected);
  });
});
