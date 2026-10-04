/**
 * Round 38 red test — GOAL-RECURRING-EDITOR-CONTRACT-001
 * (docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
 *  Ares-Worktree "codex/asset-allocation-stochastic-core")
 *
 * Approach note: no msw/supertest/real-server test harness exists anywhere
 * under reporting/ (checked). Rather than stand up a live backend, this test
 * exercises the REAL, unmocked `validateGoalForm()`/`buildGoalPayload()`
 * builder functions the GoalWizard actually calls, and asserts the exact
 * payload shape the audit's Repro 1 fed into the real backend
 * `_normalize_goal_payload()` to get `HTTP 422: Cashflow-Ziel benötigt einen
 * positiven Zielbetrag`. This documents the contract gap at the boundary
 * this frontend owns, without needing the live FastAPI backend.
 *
 * Bug being documented (GoalWizard.tsx / goalForm.ts, matching the audit's
 * code anchors):
 *  - `validateGoalForm()` for Wiederkehrende_Ausgabe/Pensionsausgabe only
 *    requires `frequency` — it never requires a positive amount or any
 *    start/end timing, even though the real backend
 *    (`services/goal_semantics.py`) requires all three.
 *  - `buildGoalPayload()` unconditionally nulls `target_amount_rappen` for
 *    every goal_type except `Einmalige_Ausgabe`, and defaults `is_ongoing`
 *    to `false` — so even a wizard that DID collect an amount/timing would
 *    still send a payload the real backend rejects with 422.
 *
 * Once GOAL-RECURRING-EDITOR-CONTRACT-001 is fixed (discriminated
 * GoalFormInput union, amount+timing required and threaded through for
 * recurring/pension goals), these `test.fails` assertions will start
 * passing and must be flipped to plain `it(...)`.
 */
import { describe, expect, test } from 'vitest';
import { buildGoalPayload, validateGoalForm, type GoalFormInput } from './goalForm';

const baseRecurring: GoalFormInput = {
  goal_type: 'Wiederkehrende_Ausgabe',
  label: 'Lebenshaltungskosten',
  rank: 2,
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
  frequency: 'monatlich',
  target_amount_rappen: 5_000_00,
  start_date: '2027-01-01',
  is_ongoing: true,
  pension_pillar: '3a',
};

describe('GOAL-RECURRING-EDITOR-CONTRACT-001: Wizard builder payload gap', () => {
  test.fails(
    'validateGoalForm requires an amount for Wiederkehrende_Ausgabe (real backend does, client does not)',
    () => {
      const noAmount: GoalFormInput = { ...baseRecurring, target_amount_rappen: null };
      const errors = validateGoalForm(noAmount);
      expect(errors.some((e) => /betrag|amount/i.test(e))).toBe(true);
    },
  );

  test.fails(
    'validateGoalForm requires start_date for Wiederkehrende_Ausgabe (real backend does, client does not)',
    () => {
      const noStart: GoalFormInput = { ...baseRecurring, start_date: null };
      const errors = validateGoalForm(noStart);
      expect(errors.some((e) => /start/i.test(e))).toBe(true);
    },
  );

  test.fails(
    'buildGoalPayload preserves a provided amount for Wiederkehrende_Ausgabe instead of nulling it',
    () => {
      const payload = buildGoalPayload(baseRecurring);
      // This is the exact shape that produces the real backend's
      // "HTTP 422: Cashflow-Ziel benötigt einen positiven Zielbetrag"
      // (audit Repro 1) — a fixed builder must NOT null this.
      expect(payload.target_amount_rappen).toBe(baseRecurring.target_amount_rappen);
    },
  );

  test.fails(
    'buildGoalPayload preserves a provided amount for Pensionsausgabe instead of nulling it',
    () => {
      const payload = buildGoalPayload(basePension);
      expect(payload.target_amount_rappen).toBe(basePension.target_amount_rappen);
    },
  );

  test.fails(
    'buildGoalPayload roundtrips start_date for Wiederkehrende_Ausgabe end-to-end from a complete wizard input',
    () => {
      const payload = buildGoalPayload(baseRecurring);
      expect(payload.start_date).toBe(baseRecurring.start_date);
      expect(payload.is_ongoing).toBe(baseRecurring.is_ongoing);
      // A fixed builder must emit exactly the fields the real backend
      // validator demands for a finite recurring stream: amount, start,
      // frequency, and an explicit end (target_date, since is_ongoing=false).
      expect(payload.target_amount_rappen).not.toBeNull();
      expect(payload.start_date).not.toBeNull();
      expect(payload.target_date).not.toBeNull();
    },
  );
});
