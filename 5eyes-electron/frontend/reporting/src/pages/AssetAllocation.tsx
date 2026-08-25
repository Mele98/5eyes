/**
 * U-FE-3: Sektion 8 — Asset Allocation.
 *
 * Bar-Chart IST/SOLL für 5 Anlageklassen inkl. Toleranzbänder. Editorial-
 * Anmerkung (Berater-Override aus U-P28 PR B). Datenstand-Banner wenn
 * `ist_basiert_auf_soll=True` (alte Mandate ohne aktuelle Bestände).
 *
 * EditButton + SingleFieldForm aus U-P28 PR C — Berater kann eigene
 * Anmerkungen pflegen, leerer Text fällt auf Auto-Default zurück.
 */
import type { AssetAllocationData } from '@/api/types';
import { BarChartIstSoll } from '@/components/BarChartIstSoll';
import { EditorialNote, ReportPage } from '@/components/ReportPage';
import { SingleFieldEditWrapper } from '@/components/SectionEditWrapper';

interface AssetAllocationProps {
  data: AssetAllocationData;
  mandateId: string;
  onReload: () => void;
}

export function AssetAllocation({
  data,
  mandateId,
  onReload,
}: AssetAllocationProps) {
  return (
    <ReportPage
      nr={8}
      kicker="Asset Allocation"
      title="Asset Allocation"
      subtitle="IST-Portfolio gegen strategische SOLL-Allokation und Toleranzband."
      toolbar={
        <SingleFieldEditWrapper
          mandateId={mandateId}
          field={{
            kind: 'aa_anmerkungen',
            title: 'Anmerkungen Asset Allocation',
          }}
          autoDefaultText={data.anmerkungen}
          onSaved={onReload}
        />
      }
    >
      {data.ist_basiert_auf_soll ? <DataBasisBanner /> : null}

      <div className="grid gap-block lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="border border-rule bg-canvas-panel p-5">
          <BarChartIstSoll items={data.items} showBands />
        </section>
        <EditorialNote title="Einordnung" body={data.anmerkungen} />
      </div>
    </ReportPage>
  );
}

function DataBasisBanner() {
  return (
    <div className="mb-block border border-rule bg-canvas-subtle p-4 text-caption text-ink-muted">
      <span className="font-semibold text-ink">Datenstand:</span> IST basiert
      aktuell auf SOLL-/Empfehlungswerten. Sobald aktuelle Bestände gepflegt
      sind, zeigt der Bericht echte Portfolio-Drifts.
    </div>
  );
}
