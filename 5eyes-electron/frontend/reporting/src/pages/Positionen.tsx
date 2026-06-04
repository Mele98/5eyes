/**
 * U-FE-1: Sektion 5 — Übersicht Positionen.
 *
 * Editorial Tabellen-Layout, gruppiert nach Anlageklasse-Bucket:
 * - Header pro Bucket: Label · Anteil · Total
 * - 4-Spalten-Tabelle: Position · ISIN · Anteil · Wert
 * - Provider + Currency als Sub-Title unter dem Produktnamen
 * - Total am Ende der Sektion
 */
import { useMemo, useState } from 'react';

import type { PositionEntry, PositionGroup, PositionenData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatChfRappen } from '@/lib/format';
import { filterPositions } from '@/lib/filterPositions';

interface PositionenProps {
  data: PositionenData;
}

export function Positionen({ data }: PositionenProps) {
  const groups = data.groups ?? [];
  const total = data.total_rappen ?? 0;

  // Sprint U-49: Such-Filter (case-insensitive in product_name/isin/
  // provider/currency).
  const [query, setQuery] = useState('');
  const { groups: filteredGroups, stats } = useMemo(
    () => filterPositions(groups, query),
    [groups, query],
  );

  return (
    <ReportPage
      nr={5}
      kicker="Übersicht Positionen"
      title="Übersicht Ihrer Positionen"
      subtitle="Empfohlene Anlageklassen-Allokation mit Einzelpositionen, ISIN und Anteilen."
    >
      {data.hinweis ? (
        <p className="mb-block text-caption text-ink-muted">{data.hinweis}</p>
      ) : null}

      {groups.length > 0 ? (
        <PositionsSearchBar
          query={query}
          onQueryChange={setQuery}
          stats={stats}
        />
      ) : null}

      {groups.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Positionen erfasst.
        </p>
      ) : filteredGroups.length === 0 ? (
        <p className="italic text-caption text-ink-subtle" data-testid="positionen-no-results">
          Keine Treffer für „{query}".
        </p>
      ) : (
        <div className="space-y-section">
          {filteredGroups.map((g) => (
            <BucketGroup key={g.key} group={g} />
          ))}
        </div>
      )}

      {total > 0 ? (
        <p className="mt-section border-t border-rule pt-3 text-right text-body text-ink">
          Total: <span className="font-mono font-semibold">{formatChfRappen(total)}</span>
        </p>
      ) : null}
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------
// Sprint U-49: Such-Leiste
// ---------------------------------------------------------------------------

function PositionsSearchBar({
  query,
  onQueryChange,
  stats,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  stats: ReturnType<typeof filterPositions>['stats'];
}) {
  const isActive = query.trim().length > 0;
  const hint = isActive
    ? `${stats.total_positions_after} von ${stats.total_positions_before} Positionen`
    : `${stats.total_positions_before} Positionen gesamt`;
  return (
    <div className="mb-block flex items-center gap-3 no-print">
      <input
        type="search"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Position, ISIN, Anbieter..."
        data-testid="positionen-search-input"
        className="flex-1 rounded border border-rule px-3 py-2 text-caption focus:outline-none focus:ring-1 focus:ring-accent"
      />
      {isActive ? (
        <button
          type="button"
          onClick={() => onQueryChange('')}
          data-testid="positionen-search-clear"
          className="text-micro uppercase tracking-widest text-ink-subtle hover:text-ink"
        >
          Zuruecksetzen
        </button>
      ) : null}
      <span className="text-micro text-ink-subtle" data-testid="positionen-search-stats">
        {hint}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------

function BucketGroup({ group }: { group: PositionGroup }) {
  return (
    <section>
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule pb-2">
        <h2 className="font-serif text-h3 text-ink">{group.label}</h2>
        <div className="flex gap-4 text-caption text-ink-muted">
          <span>
            Anteil:{' '}
            <span className="font-mono text-ink">
              {formatBpsAsPct(group.share_bps)}
            </span>
          </span>
          <span>
            Total:{' '}
            <span className="font-mono text-ink">
              {formatChfRappen(group.total_rappen)}
            </span>
          </span>
        </div>
      </header>

      {group.positions.length === 0 ? (
        <p className="mt-3 italic text-caption text-ink-subtle">
          Keine Positionen in dieser Anlageklasse.
        </p>
      ) : (
        <table className="mt-3 w-full text-caption">
          <thead>
            <tr className="border-b border-rule">
              <th className="pb-2 pr-3 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Position
              </th>
              <th className="pb-2 pr-3 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                ISIN
              </th>
              <th className="pb-2 pr-3 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Anteil
              </th>
              <th className="pb-2 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Wert
              </th>
            </tr>
          </thead>
          <tbody>
            {group.positions.map((p) => (
              <PositionRow key={`${p.isin}-${p.product_name}`} p={p} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function PositionRow({ p }: { p: PositionEntry }) {
  const detailParts: string[] = [];
  if (p.provider && p.provider !== '—') detailParts.push(p.provider);
  if (p.currency && p.currency !== '—') detailParts.push(p.currency);
  const detail = detailParts.join(' · ');

  return (
    <tr className="border-b border-rule last:border-b-0">
      <td className="py-3 pr-3 align-top">
        <div className="text-ink">{p.product_name || '—'}</div>
        {detail ? (
          <div className="text-micro text-ink-subtle">{detail}</div>
        ) : null}
      </td>
      <td className="py-3 pr-3 align-top font-mono text-micro text-ink-muted">
        {p.isin || '—'}
      </td>
      <td className="py-3 pr-3 text-right align-top font-mono text-ink">
        {formatBpsAsPct(p.share_bps)}
      </td>
      <td className="py-3 text-right align-top font-mono text-ink">
        {formatChfRappen(p.market_value_rappen)}
      </td>
    </tr>
  );
}
