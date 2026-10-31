/**
 * Sprint U-48 (Roadmap-Punkt 48, 2026-06-04): Goals-Table Sort-Logik.
 *
 * Reine Pure-Functions, separat zu Goals.tsx damit testbar ohne
 * React-Render.
 *
 * Sort-Spalten (alle stabil sortiert):
 *   - label (alpha)
 *   - type (alpha auf goal_type)
 *   - target (numeric auf target_amount_rappen, null als hoechster)
 *   - status (Order: erreichbar -> knapp -> nicht_erreichbar -> data_pending)
 *   - probability (numeric auf probability_bps, null als 0)
 */
import type { GoalEntry } from '@/api/types';

export type SortColumn =
  | 'label'
  | 'type'
  | 'target'
  | 'status'
  | 'probability';

export type SortDirection = 'asc' | 'desc';

export interface SortConfig {
  column: SortColumn;
  direction: SortDirection;
}

// U-48: Status-Reihenfolge fuer 'erreichbar zuerst' (asc) bzw.
// 'kritisch zuerst' (desc).
const STATUS_PRIORITY: Record<string, number> = {
  erreichbar: 0,
  knapp: 1,
  nicht_erreichbar: 2,
  data_pending: 3,
  '': 3,
};


function compareNullableNumber(
  a: number | null | undefined,
  b: number | null | undefined,
  nullFallback: number,
): number {
  const aVal = a ?? nullFallback;
  const bVal = b ?? nullFallback;
  return aVal - bVal;
}


function compareLabels(a: string, b: string): number {
  // Locale-aware alphabetical compare (de-CH)
  return a.localeCompare(b, 'de-CH', { sensitivity: 'base' });
}


export function compareGoals(
  a: GoalEntry,
  b: GoalEntry,
  column: SortColumn,
): number {
  switch (column) {
    case 'label':
      return compareLabels(a.label || '', b.label || '');
    case 'type':
      return compareLabels(a.goal_type || '', b.goal_type || '');
    case 'target':
      // Null-target sortiert ans Ende bei asc (hoechster Fallback)
      return compareNullableNumber(
        a.target_amount_rappen,
        b.target_amount_rappen,
        Number.MAX_SAFE_INTEGER,
      );
    case 'status': {
      const prioA = STATUS_PRIORITY[a.status] ?? 99;
      const prioB = STATUS_PRIORITY[b.status] ?? 99;
      return prioA - prioB;
    }
    case 'probability':
      return compareNullableNumber(
        a.probability_bps, b.probability_bps, 0,
      );
    default:
      return 0;
  }
}


export function sortGoals(
  goals: GoalEntry[],
  config: SortConfig | null,
): GoalEntry[] {
  if (config === null) return goals;
  // Stable sort: kopiere Array (mutiert sonst Props)
  const sorted = [...goals].sort((a, b) =>
    compareGoals(a, b, config.column),
  );
  if (config.direction === 'desc') {
    sorted.reverse();
  }
  return sorted;
}


export function nextSortConfig(
  current: SortConfig | null,
  column: SortColumn,
): SortConfig | null {
  // U-48 UX-Pattern (Three-State-Toggle):
  //   1. Klick auf neue Spalte -> asc
  //   2. Klick auf gleiche Spalte (asc) -> desc
  //   3. Klick auf gleiche Spalte (desc) -> reset (null = original order)
  if (current === null || current.column !== column) {
    return { column, direction: 'asc' };
  }
  if (current.direction === 'asc') {
    return { column, direction: 'desc' };
  }
  return null;
}
