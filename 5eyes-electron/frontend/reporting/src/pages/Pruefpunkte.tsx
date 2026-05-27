/**
 * U-FE-2: Sektion 6 — Was wir im Depotcheck prüfen.
 *
 * Editorial 2-Spalten-Layout: pro Prüfpunkt Titel links (body-bold) und
 * Beschreibung rechts (body-muted). Statische Inhalte aus dem Aggregator
 * — kein Mandant-spezifischer Inhalt.
 */
import type { PruefpunkteData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';

interface PruefpunkteProps {
  data: PruefpunkteData;
}

export function Pruefpunkte({ data }: PruefpunkteProps) {
  const bloecke = data.bloecke ?? [];
  return (
    <ReportPage
      nr={6}
      kicker="Depotcheck-Prüfpunkte"
      title="Was wir im Depotcheck prüfen"
      subtitle="Die Bereiche, gegen die jedes Mandat geprüft wird — von Diversifikation bis Steuerung."
    >
      {bloecke.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Prüfpunkte erfasst.
        </p>
      ) : (
        <dl className="space-y-block">
          {bloecke.map((b) => (
            <div
              key={b.key}
              className="grid gap-block border-b border-rule pb-block last:border-b-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"
            >
              <dt className="font-serif text-h3 text-ink">{b.title}</dt>
              <dd className="text-body text-ink-muted">{b.beschreibung}</dd>
            </div>
          ))}
        </dl>
      )}
    </ReportPage>
  );
}
