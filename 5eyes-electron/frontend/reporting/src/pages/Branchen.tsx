/**
 * U-FE-3: Sektion 10 — Diversifikation Branchen.
 *
 * GICS-Sektor-Reihenfolge plus Sammelkategorie „Übrige" für nicht-GICS.
 * Hinweis-Banner erklärt dass nur Aktien-Positionen einbezogen werden.
 * Editorial-Analyse mit Berater-Override.
 */
import type { BranchenData } from '@/api/types';
import { BarChartIstSoll } from '@/components/BarChartIstSoll';
import { EditorialNote, ReportPage } from '@/components/ReportPage';
import { SingleFieldEditWrapper } from '@/components/SectionEditWrapper';

interface BranchenProps {
  data: BranchenData;
  mandateId: string;
  onReload: () => void;
}

export function Branchen({ data, mandateId, onReload }: BranchenProps) {
  return (
    <ReportPage
      nr={10}
      kicker="Diversifikation Branchen"
      title="Diversifikation Branchen"
      subtitle="Sektor-Allokation der Aktien-Bausteine — Konzentrations-Diagnose."
      toolbar={
        <SingleFieldEditWrapper
          mandateId={mandateId}
          field={{
            kind: 'branchen_analyse',
            title: 'Analyse Branchen-Diversifikation',
          }}
          autoDefaultText={data.analyse}
          onSaved={onReload}
        />
      }
    >
      {/* PB-02: Datenstand-Banner wie in AssetAllocation/Risikowaehrungen —
          macht transparent, dass IST mangels Beständen auf SOLL basiert. */}
      {data.ist_basiert_auf_soll ? (
        <div className="mb-block border border-rule bg-canvas-subtle p-4 text-caption text-ink-muted">
          <span className="font-semibold text-ink">Datenstand:</span> IST basiert
          aktuell auf SOLL-/Empfehlungswerten. Sobald aktuelle Bestände gepflegt
          sind, zeigt der Bericht echte Branchen-Drifts.
        </div>
      ) : null}

      {data.hinweis ? (
        <div className="mb-block border border-rule bg-canvas-subtle p-4 text-caption text-ink-muted">
          {data.hinweis}
        </div>
      ) : null}

      <div className="grid gap-block lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="border border-rule bg-canvas-panel p-5">
          <BarChartIstSoll items={data.items} />
        </section>
        <EditorialNote title="Analyse" body={data.analyse} />
      </div>
    </ReportPage>
  );
}
