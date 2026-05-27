/**
 * U-FE-4: Sektion 13 — Building Blocks / iSAA.
 *
 * 5 Anlageklassen mit Target + Bandbreite, plus Constraint-Tabelle und
 * editoriale Methodologie-Erklärung.
 */
import type { BuildingBlocksData } from '@/api/types';
import { EditorialNote, ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct } from '@/lib/format';

interface BuildingBlocksProps {
  data: BuildingBlocksData;
}

export function BuildingBlocks({ data }: BuildingBlocksProps) {
  const blocks = data.blocks ?? [];
  const constraints = data.constraints ?? [];
  return (
    <ReportPage
      nr={13}
      kicker="Building Blocks"
      title="Building Blocks"
      subtitle="Strategische Allokation auf Anlageklassen-Ebene mit Toleranzbändern."
    >
      {blocks.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Building Blocks erfasst.
        </p>
      ) : (
        <table className="w-full text-caption">
          <thead>
            <tr className="border-b border-rule">
              <th className="pb-2 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Anlageklasse
              </th>
              <th className="pb-2 pr-4 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Target
              </th>
              <th className="pb-2 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Band
              </th>
            </tr>
          </thead>
          <tbody>
            {blocks.map((b) => (
              <tr key={b.key} className="border-b border-rule last:border-b-0">
                <td className="py-3 pr-4 font-semibold text-ink">{b.label}</td>
                <td className="py-3 pr-4 text-right font-mono text-ink">
                  {formatBpsAsPct(b.target_bps)}
                </td>
                <td className="py-3 text-right font-mono text-ink-muted">
                  {formatBpsAsPct(b.band_min_bps)} – {formatBpsAsPct(b.band_max_bps)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data.methodologie ? (
        <div className="mt-section">
          <EditorialNote title="Methodologie" body={data.methodologie} />
        </div>
      ) : null}

      {constraints.length > 0 ? (
        <section className="mt-section">
          <h2 className="font-serif text-h2 text-ink">Constraints</h2>
          <table className="mt-3 w-full text-caption">
            <thead>
              <tr className="border-b border-rule">
                <th className="pb-2 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                  Constraint
                </th>
                <th className="pb-2 pr-4 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
                  Wert
                </th>
                <th className="pb-2 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                  Beschreibung
                </th>
              </tr>
            </thead>
            <tbody>
              {constraints.map((c) => (
                <tr key={c.key} className="border-b border-rule last:border-b-0">
                  <td className="py-3 pr-4 font-semibold text-ink">
                    {c.label || '—'}
                  </td>
                  <td className="py-3 pr-4 text-right font-mono text-ink">
                    {formatBpsAsPct(c.value_bps)}
                  </td>
                  <td className="py-3 text-ink-muted">{c.beschreibung || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </ReportPage>
  );
}
