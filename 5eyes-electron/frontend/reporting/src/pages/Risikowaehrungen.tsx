/**
 * U-FE-3: Sektion 9 — Risikowährungen.
 *
 * FX-Exposure in 7 Berichts-Kategorien (CHF, USD, EUR, GBP, JPY, EM, Andere).
 * Bar-Chart ohne Toleranzbänder; Berater-Erklärung als EditorialNote +
 * Override-Button.
 */
import type { RisikowaehrungenData } from '@/api/types';
import { BarChartIstSoll } from '@/components/BarChartIstSoll';
import { EditorialNote, ReportPage } from '@/components/ReportPage';
import { SingleFieldEditWrapper } from '@/components/SectionEditWrapper';

interface RisikowaehrungenProps {
  data: RisikowaehrungenData;
  mandateId: string;
  onReload: () => void;
}

export function Risikowaehrungen({
  data,
  mandateId,
  onReload,
}: RisikowaehrungenProps) {
  return (
    <ReportPage
      nr={9}
      kicker="Risikowährungen"
      title="Risikowährungen"
      subtitle="Währungsexposure als Risikodimension neben der Anlageklassen-Sicht."
      toolbar={
        <SingleFieldEditWrapper
          mandateId={mandateId}
          field={{
            kind: 'waehrungen_erklaerung',
            title: 'Erklärung Risikowährungen',
          }}
          autoDefaultText={data.erklaerung}
          onSaved={onReload}
        />
      }
    >
      {data.ist_basiert_auf_soll ? <DataBasisBanner /> : null}

      <div className="grid gap-block lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="border border-rule bg-canvas-panel p-5">
          <BarChartIstSoll items={data.items} />
        </section>
        <EditorialNote title="Einordnung" body={data.erklaerung} />
      </div>
    </ReportPage>
  );
}

function DataBasisBanner() {
  return (
    <div className="mb-block border border-rule bg-canvas-subtle p-4 text-caption text-ink-muted">
      <span className="font-semibold text-ink">Datenstand:</span> IST basiert
      aktuell auf SOLL-/Empfehlungswerten.
    </div>
  );
}
