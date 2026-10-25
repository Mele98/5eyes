/**
 * Sprint U-12 (Roadmap-Punkt 12): Goal-Klassifikation gegen
 * Monte-Carlo-Pfade. Reine Funktion, kein React, separat getestet.
 *
 * Entscheidet pro Goal, ob das Ziel nach den p5/p50/p75-Pfaden im
 * `target_date`-Jahr erreichbar ist.
 *
 * Konvention
 * ----------
 * - target_date ISO YYYY-MM-DD; wir matchen aufs Jahr (4-Stellen-Prefix)
 * - time_axis ist Liste von Jahres-Strings (z.B. "2026", "2027", ...)
 * - Wenn Goal-Jahr < time_axis[0]: 'past' (Ziel war in der Vergangenheit)
 * - Wenn Goal-Jahr > time_axis[-1]: 'beyond_horizon' (jenseits MC-Horizont)
 * - Sonst Index = Goal-Jahr - Start-Jahr
 *
 * Status
 * ------
 *   p50[t] >= target            -> 'erreichbar' (Median trifft Ziel)
 *   p75[t] >= target > p50[t]   -> 'knapp' (nur im Best-Case)
 *   p75[t] < target             -> 'nicht_erreichbar' (auch Best-Case verfehlt)
 */
import type { GoalEntry, MonteCarloPaths } from '@/api/types';

export type GoalAchievabilityStatus =
  | 'erreichbar'
  | 'knapp'
  | 'nicht_erreichbar'
  | 'past'
  | 'beyond_horizon'
  | 'unknown';

export interface GoalClassification {
  goal_id: string;
  status: GoalAchievabilityStatus;
  /** Index in time_axis (null wenn past / beyond_horizon / unknown) */
  t_index: number | null;
  /** p5/p50/p75 Werte am Goal-Jahr (null wenn nicht verfuegbar) */
  p5_at_target: number | null;
  p50_at_target: number | null;
  p75_at_target: number | null;
}

/**
 * Liefert eine Klassifikation pro Goal.
 *
 * Defensive Asserts:
 * - Wenn `mc.data_pending` -> alle Goals = 'unknown'
 * - Wenn p5/p50/p75 Laengen nicht uebereinstimmen -> alle = 'unknown'
 *   (sichert UI gegen mal-aligned Backend-Daten)
 * - Wenn target_amount_rappen <= 0 -> 'unknown' (kein numerisches Ziel)
 */
export function classifyGoals(
  goals: GoalEntry[],
  mc: MonteCarloPaths | undefined | null,
): GoalClassification[] {
  if (!mc || mc.data_pending) {
    return goals.map((g) => _unknown(g.goal_id));
  }
  const time_axis = mc.time_axis ?? [];
  const p5 = mc.p5 ?? [];
  const p50 = mc.p50 ?? [];
  const p75 = mc.p75 ?? [];

  if (
    time_axis.length === 0 ||
    p5.length !== time_axis.length ||
    p50.length !== time_axis.length ||
    p75.length !== time_axis.length
  ) {
    return goals.map((g) => _unknown(g.goal_id));
  }

  const startYear = Number.parseInt(time_axis[0] ?? '0', 10);
  const endYear = Number.parseInt(time_axis[time_axis.length - 1] ?? '0', 10);
  if (!Number.isFinite(startYear) || !Number.isFinite(endYear)) {
    return goals.map((g) => _unknown(g.goal_id));
  }

  return goals.map((g) => {
    const targetYear = _parseYear(g.target_date);
    const targetAmount = g.target_amount_rappen;

    if (!Number.isFinite(targetYear) || targetAmount <= 0) {
      return _unknown(g.goal_id);
    }
    if (targetYear < startYear) {
      return { ..._unknown(g.goal_id), status: 'past' };
    }
    if (targetYear > endYear) {
      return { ..._unknown(g.goal_id), status: 'beyond_horizon' };
    }

    const t = targetYear - startYear;
    const p5v = p5[t];
    const p50v = p50[t];
    const p75v = p75[t];

    if (p5v === undefined || p50v === undefined || p75v === undefined) {
      return _unknown(g.goal_id);
    }

    let status: GoalAchievabilityStatus;
    if (p50v >= targetAmount) {
      status = 'erreichbar';
    } else if (p75v >= targetAmount) {
      status = 'knapp';
    } else {
      status = 'nicht_erreichbar';
    }

    return {
      goal_id: g.goal_id,
      status,
      t_index: t,
      p5_at_target: p5v,
      p50_at_target: p50v,
      p75_at_target: p75v,
    };
  });
}

function _unknown(goal_id: string): GoalClassification {
  return {
    goal_id,
    status: 'unknown',
    t_index: null,
    p5_at_target: null,
    p50_at_target: null,
    p75_at_target: null,
  };
}

function _parseYear(targetDate: string): number {
  if (!targetDate) return NaN;
  const m = targetDate.match(/^(\d{4})/);
  return m ? Number.parseInt(m[1] ?? '0', 10) : NaN;
}
