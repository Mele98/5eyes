/**
 * Round 38 red test — GOAL-RECURRING-EDITOR-CONTRACT-001, Pflichttest 6+7
 * (docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
 *  Ares-Worktree "codex/asset-allocation-stochastic-core", Kontrollrunde 38).
 *
 * This file is scoped to the two remaining Pflichttest items for this
 * finding that the sibling red test
 * (goalForm.realContractGap.test.ts, commit 4ad20d8, round38-redtest-06)
 * does not cover:
 *   6. React/Classic payload golden parity for a recurring/pension goal.
 *   7. No-op edit round-trip preserves probability/pillar/rank/hardness/weight.
 *
 * ---------------------------------------------------------------------------
 * Classic-side comparison strategy (read this before touching the test):
 * ---------------------------------------------------------------------------
 * `5eyes_v2.html` is a single inline <script> in a non-module HTML file —
 * there is no ES-module export to `import` into a vitest file, and no
 * msw/supertest/live-server harness exists anywhere under reporting/
 * (checked). Per the task's fallback instruction, the relevant Classic
 * normalization steps are therefore extracted VERBATIM below as
 * `classicGoalPayloadContract()`, a documented, hand-transcribed mirror of
 * the real `saveGoal()` payload construction. Anchors in the current
 * worktree (develop HEAD d1fe2e8; the audit doc's own ~26280/~26721 line
 * hints point at unrelated sections — the real anchors, verified by
 * grepping `function saveGoal` in this worktree, are listed per-anchor
 * below):
 *   - 5eyes_v2.html:27263-27348  saveGoal() payload assembly incl. the
 *     type-gated start/end/frequency/is_ongoing logic and the
 *     amount/wealth/return three-way `if/else if` (27346-27348).
 *   - 5eyes_v2.html:26749-26763  isRecurringGoalType/isWealthGoalType/
 *     isReturnGoalType/isMaxGoalType/goalFrequencyKey helpers.
 *   - 5eyes_v2.html:22340-22343  normalizeCashflowDateValue (identity for
 *     an already-valid "YYYY-MM-DD" string, which is all this test feeds
 *     it — GoalFormInput, like saveGoal()'s DOM reads, carries dates
 *     pre-normalized to that shape).
 *   - 5eyes_v2.html:17058-17061  parseCHF (CHF string → rounded rappen).
 *     Not re-implemented here: GoalFormInput already carries amounts as
 *     rappen integers (see goalForm.ts's own header: "rappen/bps sind
 *     bereits umgerechnet"), so this test's fixtures supply the
 *     *post-parseCHF* rappen value directly instead of a raw CHF string —
 *     this is the one deliberate simplification versus the live DOM path.
 *
 * `classicGoalPayloadContract()` is intentionally narrow: it only computes
 * the fields this Pflichttest compares (amount/start/end/ongoing/frequency/
 * horizon plus the test-7 field set), not the full saveGoal() payload.
 * ---------------------------------------------------------------------------
 */
import { describe, expect, test, it } from 'vitest';
import { buildGoalPayload, type GoalFormInput } from './goalForm';

/** Narrow mirror of the fields saveGoal() emits that this test compares. */
interface ClassicGoalPayloadContract {
  target_amount_rappen: number | null;
  target_wealth_rappen: number | null;
  target_return_bps: number | null;
  start_date: string | null;
  target_date: string | null;
  is_ongoing: boolean;
  frequency: string | null;
  horizon_years: number | null;
  probability_pct: number;
  pension_pillar: string | null;
  rank: number;
  hardness: string;
  weight_bps: number | null;
}

// Verbatim mirror of 5eyes_v2.html:26752-26763.
function isRecurringGoalType(type: string): boolean {
  return type === 'Wiederkehrende_Ausgabe' || type === 'Pensionsausgabe';
}
function isWealthGoalType(type: string): boolean {
  return type === 'Kapitalerhalt' || type === 'Vermögensziel' || type === 'Vermoegensziel';
}
function isReturnGoalType(type: string): boolean {
  return type === 'Renditeziel';
}
function isMaxGoalType(type: string): boolean {
  return type === 'Maximierung';
}

/**
 * Verbatim mirror of 5eyes_v2.html:27263-27348 (saveGoal), narrowed to the
 * fields this Pflichttest cares about. `input` plays the role of the
 * already-read DOM values (`getInputValue(...)` results); the branching
 * below is copied 1:1 from saveGoal's own `if/else if` chain.
 */
function classicGoalPayloadContract(input: GoalFormInput): ClassicGoalPayloadContract {
  const type = input.goal_type;
  let startDate = input.start_date || '';
  let targetDate = input.target_date || '';
  let frequency = input.frequency || 'jaehrlich';
  let isOngoing = input.is_ongoing ?? false;

  // 5eyes_v2.html:27297-27312 (type-gated start/end/frequency/ongoing).
  if (type === 'Einmalige_Ausgabe') {
    if (!targetDate) targetDate = startDate;
    if (!startDate) startDate = targetDate;
    frequency = 'einmalig';
    isOngoing = false;
  } else if (isRecurringGoalType(type)) {
    if (isOngoing) targetDate = '';
    // (27306 end<start guard omitted — not a normalization step, a reject.)
  } else {
    startDate = '';
    frequency = 'jaehrlich';
    isOngoing = false;
    if (isMaxGoalType(type)) targetDate = '';
  }

  const hardnessMap: Record<number, string> = { 1: 'Hart', 2: 'Primär', 3: 'Opportunistisch' };

  const payload: ClassicGoalPayloadContract = {
    target_amount_rappen: null,
    target_wealth_rappen: null,
    target_return_bps: null,
    start_date: startDate || null,
    horizon_years: input.horizon_years ?? null,
    target_date: targetDate || null,
    is_ongoing: isRecurringGoalType(type) ? isOngoing : false,
    frequency: isRecurringGoalType(type) ? frequency : null,
    hardness: hardnessMap[input.rank] || 'Primär',
    probability_pct: input.probability_pct ?? 100,
    pension_pillar: type === 'Pensionsausgabe' ? (input.pension_pillar ?? null) : null,
    rank: input.rank,
    weight_bps: input.weight_bps ?? null,
  };

  // 5eyes_v2.html:27346-27348 — the three-way amount/wealth/return assignment.
  if (isReturnGoalType(type)) {
    payload.target_return_bps = input.target_return_bps ?? null;
  } else if (isWealthGoalType(type)) {
    payload.target_wealth_rappen = input.target_amount_rappen ?? null;
  } else if (!isMaxGoalType(type)) {
    payload.target_amount_rappen = input.target_amount_rappen ?? null;
  }

  return payload;
}

const baseRecurring: GoalFormInput = {
  goal_type: 'Wiederkehrende_Ausgabe',
  label: 'Lebenshaltungskosten',
  rank: 2,
  hardness: 'Primär',
  frequency: 'jaehrlich',
  target_amount_rappen: 10_000_00,
  start_date: '2026-01-01',
  target_date: '2030-01-01',
  is_ongoing: false,
};

const basePension: GoalFormInput = {
  goal_type: 'Pensionsausgabe',
  label: 'Pensionsausgaben Saeule 3a',
  rank: 1,
  hardness: 'Hart',
  frequency: 'monatlich',
  target_amount_rappen: 5_000_00,
  start_date: '2027-01-01',
  is_ongoing: true,
  pension_pillar: '3a',
};

describe('GOAL-RECURRING-EDITOR-CONTRACT-001 Pflichttest 6: React/Classic payload golden parity', () => {
  test.fails(
    'buildGoalPayload matches the Classic contract on target_amount_rappen for Wiederkehrende_Ausgabe (React nulls it, Classic preserves it)',
    () => {
      const reactPayload = buildGoalPayload(baseRecurring);
      const classicPayload = classicGoalPayloadContract(baseRecurring);
      expect(reactPayload.target_amount_rappen).toBe(classicPayload.target_amount_rappen);
    },
  );

  test.fails(
    'buildGoalPayload matches the Classic contract on target_amount_rappen for Pensionsausgabe (React nulls it, Classic preserves it)',
    () => {
      const reactPayload = buildGoalPayload(basePension);
      const classicPayload = classicGoalPayloadContract(basePension);
      expect(reactPayload.target_amount_rappen).toBe(classicPayload.target_amount_rappen);
    },
  );

  it('buildGoalPayload already matches the Classic contract on start_date/frequency/horizon for a finite recurring goal', () => {
    const reactPayload = buildGoalPayload(baseRecurring);
    const classicPayload = classicGoalPayloadContract(baseRecurring);
    expect(reactPayload.start_date).toBe(classicPayload.start_date);
    expect(reactPayload.target_date).toBe(classicPayload.target_date);
    expect(reactPayload.frequency).toBe(classicPayload.frequency);
    expect(reactPayload.is_ongoing).toBe(classicPayload.is_ongoing);
    expect(reactPayload.horizon_years).toBe(classicPayload.horizon_years);
  });

  test.fails(
    'buildGoalPayload matches the Classic contract on target_date for an ongoing pension goal (Classic forces null when is_ongoing, React does not re-derive it)',
    () => {
      // basePension has is_ongoing=true and no target_date supplied, so this
      // specific fixture happens to already agree (both null). Feed an input
      // that mimics a no-op edit of a goal that still carries a stale
      // target_date alongside is_ongoing=true (e.g. the user flipped
      // "ongoing" on without the editor clearing the old end date) to
      // surface the real divergence: Classic's `if(isOngoing)targetDate=''`
      // (5eyes_v2.html:27305) always wins; React's builder has no such
      // re-derivation and would echo the stale value back to the backend.
      const staleOngoing: GoalFormInput = { ...basePension, target_date: '2031-01-01' };
      const reactPayload = buildGoalPayload(staleOngoing);
      const classicPayload = classicGoalPayloadContract(staleOngoing);
      expect(reactPayload.target_date).toBe(classicPayload.target_date);
    },
  );
});

describe('GOAL-RECURRING-EDITOR-CONTRACT-001 Pflichttest 7: no-op edit round-trip field preservation', () => {
  // These fields are untouched by the amount/timing contract gap (test 6)
  // and currently round-trip correctly on both sides for a "no-op edit"
  // (same values loaded back into the form and re-saved without change).
  // This locks today's correct behaviour as a regression guard: when
  // GOAL-RECURRING-EDITOR-CONTRACT-001 is fixed and buildGoalPayload is
  // rewritten (discriminated GoalFormInput union / amount+timing
  // threading), these assertions must keep passing unchanged.
  test.each([
    ['Wiederkehrende_Ausgabe goal', baseRecurring],
    ['Pensionsausgabe goal', basePension],
  ])('%s: probability/pillar/rank/hardness/weight survive a no-op round-trip', (_label, fixture) => {
    const noOpInput: GoalFormInput = {
      ...fixture,
      probability_pct: 87,
      weight_bps: 1500,
    };

    const reactPayload = buildGoalPayload(noOpInput);
    const classicPayload = classicGoalPayloadContract(noOpInput);

    // React preserves exactly what was supplied.
    expect(reactPayload.probability_pct).toBe(87);
    expect(reactPayload.rank).toBe(noOpInput.rank);
    expect(reactPayload.hardness).toBe(noOpInput.hardness);
    expect(reactPayload.weight_bps).toBe(1500);
    expect(reactPayload.pension_pillar).toBe(
      noOpInput.goal_type === 'Pensionsausgabe' ? noOpInput.pension_pillar : null,
    );

    // ...and agrees with the Classic contract on every one of these fields.
    expect(reactPayload.probability_pct).toBe(classicPayload.probability_pct);
    expect(reactPayload.rank).toBe(classicPayload.rank);
    expect(reactPayload.hardness).toBe(classicPayload.hardness);
    expect(reactPayload.weight_bps).toBe(classicPayload.weight_bps);
    expect(reactPayload.pension_pillar).toBe(classicPayload.pension_pillar);
  });
});
