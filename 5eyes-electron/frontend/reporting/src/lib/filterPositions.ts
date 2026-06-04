/**
 * Sprint U-49 (Roadmap-Punkt 49, 2026-06-04): Positionen-Such/Filter-Logik.
 *
 * Pure-Functions, separat zu Positionen.tsx damit testbar.
 *
 * Such-Logik
 * ----------
 * - Query als String (case-insensitive)
 * - Matched gegen product_name, isin, provider, currency
 * - Leerer Query: alle Gruppen + Positionen unveraendert
 * - Wenn alle Positions einer Group raus-filtered werden: Group
 *   bleibt drin (mit positions=[]), damit Header sichtbar bleibt
 *   und zeigt "Keine Treffer in dieser Anlageklasse".
 *   Alternative-Wahl: complete-empty-group entfernen.
 *
 * Entscheidung: Hide-Empty-Group-Wenn-Filter-Active = TRUE (UX-Win,
 * weniger Rauschen). Ohne Filter: alle Gruppen sichtbar.
 */
import type { PositionEntry, PositionGroup } from '@/api/types';


export function matchesQuery(
  position: PositionEntry,
  query: string,
): boolean {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const haystack = [
    position.product_name,
    position.isin,
    position.provider,
    position.currency,
  ]
    .filter((v): v is string => Boolean(v))
    .join(' ')
    .toLowerCase();
  return haystack.includes(q);
}


export interface FilterStats {
  total_positions_before: number;
  total_positions_after: number;
  groups_before: number;
  groups_after: number;
}


export interface FilteredResult {
  groups: PositionGroup[];
  stats: FilterStats;
}


export function filterPositions(
  groups: PositionGroup[],
  query: string,
): FilteredResult {
  const totalsBefore = groups.reduce(
    (n, g) => n + (g.positions?.length ?? 0), 0,
  );
  const q = query.toLowerCase().trim();
  if (!q) {
    return {
      groups,
      stats: {
        total_positions_before: totalsBefore,
        total_positions_after: totalsBefore,
        groups_before: groups.length,
        groups_after: groups.length,
      },
    };
  }
  const filtered: PositionGroup[] = [];
  let totalsAfter = 0;
  for (const group of groups) {
    const positions = (group.positions ?? []).filter((p) =>
      matchesQuery(p, query),
    );
    totalsAfter += positions.length;
    if (positions.length === 0) {
      // Hide-Empty-Group bei aktivem Filter
      continue;
    }
    filtered.push({ ...group, positions });
  }
  return {
    groups: filtered,
    stats: {
      total_positions_before: totalsBefore,
      total_positions_after: totalsAfter,
      groups_before: groups.length,
      groups_after: filtered.length,
    },
  };
}


/**
 * Sub-Set-Filter: nur Gruppen mit allowed_bucket_keys.
 * Wird OHNE Such-Query gefuellt werden — Sub-App-Sidebar kann
 * Anlageklassen-Toggles anbieten.
 */
export function filterByBuckets(
  groups: PositionGroup[],
  allowedKeys: ReadonlySet<string>,
): PositionGroup[] {
  if (allowedKeys.size === 0) return groups;
  return groups.filter((g) => allowedKeys.has(g.key));
}
