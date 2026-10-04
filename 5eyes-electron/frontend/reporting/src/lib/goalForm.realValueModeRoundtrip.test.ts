/**
 * Round 40 red test — GOAL-VALUE-MODE-ROUNDTRIP-001
 *
 * Bug (goalForm.ts, buildGoalPayload, ~line 194):
 *
 *   value_mode: wealth ? (input.value_mode ?? 'nominal') : 'nominal',
 *
 * `wealth` (isWealthType) is only true for the wealth-goal types
 * (Kapitalerhalt/Vermoegensziel). For every OTHER goal_type — including
 * Einmalige_Ausgabe, a one-off expense goal — the builder unconditionally
 * forces `value_mode` to 'nominal', discarding whatever value_mode the
 * input actually carries.
 *
 * This matters because `stateFromRecord()` in GoalWizard.tsx (the function
 * that seeds the wizard's state when editing an EXISTING goal) faithfully
 * reads `rec.value_mode` off the real record:
 *
 *   value_mode: (rec.value_mode as GoalValueMode) ?? base.value_mode,
 *
 * and `toFormInput()` passes that straight through into GoalFormInput's
 * `value_mode` field unchanged. So a no-op "Speichern" on an existing
 * Einmalige_Ausgabe goal whose stored value_mode is 'real' (the advisor
 * modelled the expense in today's purchasing power, e.g. a renovation
 * budgeted in real terms) silently rewrites it to 'nominal' on save —
 * a real change to the client's purchasing-power semantics disguised as
 * a no-op edit, with no field the advisor touched explaining why.
 *
 * This test exercises the REAL, unmocked `buildGoalPayload()` the
 * GoalWizard actually calls, with a GoalFormInput shaped exactly like what
 * `toFormInput(stateFromRecord(rec))` produces for an unmodified re-save of
 * such a record, and asserts value_mode is preserved as 'real'.
 *
 * Once GOAL-VALUE-MODE-ROUNDTRIP-001 is fixed (value_mode threaded through
 * for every goal_type that accepts it, not just the wealth family), this
 * `test.fails` assertion will start passing and must be flipped to a plain
 * `it(...)`.
 */
import { describe, expect, test } from 'vitest';
import { buildGoalPayload, type GoalFormInput } from './goalForm';

// Mirrors toFormInput(stateFromRecord(rec)) for an existing Einmalige_Ausgabe
// goal record with value_mode: 'real', re-saved without any edits.
const realValueModeExpenseResave: GoalFormInput = {
  goal_type: 'Einmalige_Ausgabe',
  label: 'Renovation Ferienhaus',
  rank: 2,
  hardness: 'Primär',
  goal_scope: 'Beratungsvermögen',
  value_mode: 'real',
  target_amount_rappen: 80_000_00,
  target_date: '2030-06-01',
  probability_pct: 100,
  is_ongoing: false,
};

describe('GOAL-VALUE-MODE-ROUNDTRIP-001: value_mode lost on non-wealth goal round-trip', () => {
  test.fails(
    'buildGoalPayload preserves value_mode=real for a re-saved Einmalige_Ausgabe goal instead of forcing nominal',
    () => {
      const payload = buildGoalPayload(realValueModeExpenseResave);
      // Currently returns 'nominal' — the bug: a no-op save silently
      // converts a real-value-mode expense goal to nominal.
      expect(payload.value_mode).toBe('real');
    },
  );
});
