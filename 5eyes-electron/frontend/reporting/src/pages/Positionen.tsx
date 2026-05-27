/**
 * U-FE-1: Sektion 5 — Übersicht Positionen.
 *
 * Editorial Tabellen-Layout, gruppiert nach Anlageklasse-Bucket:
 * - Header pro Bucket: Label · Anteil · Total
 * - 4-Spalten-Tabelle: Position · ISIN · Anteil · Wert
 * - Provider + Currency als Sub-Title unter dem Produktnamen
 * - Total am Ende der Sektion
 */
import type { PositionEntry, PositionGroup, PositionenData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatChfRappen } from '@/lib/format';

interface PositionenProps {
  data: PositionenData;
}

export function Positionen({ data }: PositionenProps) {
  const groups = data.groups ?? [];
  const total = data.total_rappen ?? 0;

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

      {groups.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Positionen erfasst.
        </p>
      ) : (
        <div className="space-y-section">
          {groups.map((g) => (
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
