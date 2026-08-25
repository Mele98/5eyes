/**
 * U-FE-2: Sektion 7 — Erkenntnisse aus dem Depotcheck.
 *
 * 4-Spalten-Tabelle: Prüfpunkt · Ampel-Pill · Beurteilung · Handlungsempfehlung.
 *
 * Ampel-Pills aus components/AmpelPill mit matten 5eyes-Status-Farben
 * (nicht signal-grün/-rot — Design-Direktive).
 */
import type { ErkenntnisseData } from '@/api/types';
import { AmpelPill } from '@/components/AmpelPill';
import { ReportPage } from '@/components/ReportPage';

interface ErkenntnisseProps {
  data: ErkenntnisseData;
}

export function Erkenntnisse({ data }: ErkenntnisseProps) {
  const checks = data.checks ?? [];
  return (
    <ReportPage
      nr={7}
      kicker="Depotcheck-Erkenntnisse"
      title="Erkenntnisse aus dem Depotcheck"
      subtitle="Verdikt pro Prüfpunkt mit Beurteilung und konkreter Handlungsempfehlung."
    >
      {checks.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Erkenntnisse erfasst.
        </p>
      ) : (
        <table className="w-full text-caption">
          <thead>
            <tr className="border-b border-rule">
              <th className="pb-3 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Prüfpunkt
              </th>
              <th className="pb-3 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Status
              </th>
              <th className="pb-3 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Beurteilung
              </th>
              <th className="pb-3 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
                Handlungsempfehlung
              </th>
            </tr>
          </thead>
          <tbody>
            {checks.map((c, idx) => (
              <tr
                key={`${c.pruefpunkt}-${idx}`}
                className="border-b border-rule last:border-b-0"
              >
                <td className="py-4 pr-4 align-top font-semibold text-ink">
                  {c.pruefpunkt || '—'}
                </td>
                <td className="py-4 pr-4 align-top">
                  <AmpelPill status={c.bewertung} />
                </td>
                <td className="py-4 pr-4 align-top text-ink-muted">
                  {c.beurteilung || '—'}
                </td>
                <td className="py-4 align-top text-ink-muted">
                  {c.handlungsempfehlung || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ReportPage>
  );
}
