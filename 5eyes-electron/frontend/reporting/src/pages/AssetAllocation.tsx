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
import type { AssetAllocationData, AssetAllocationItem } from '@/api/types';
import { BarChartIstSoll, type BarChartItem } from '@/components/BarChartIstSoll';
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
      {data.soll_ausgeblendet ? (
        // STALE-ALLOCATION-HIDE-TARGETS-001: veraltete Soll-Allokation ->
        // keine alten Zielzahlen, nur der Hinweis.
        <StaleTargetsNotice hinweis={data.staleness_hinweis || data.anmerkungen} />
      ) : (
        <>
          {data.ist_basiert_auf_soll ? <DataBasisBanner /> : null}

          <div className="grid gap-block lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <section className="border border-rule bg-canvas-panel p-5">
              <BarChartIstSoll items={toBarChartItems(data.items)} showBands />
            </section>
            <EditorialNote title="Einordnung" body={data.anmerkungen} />
          </div>
        </>
      )}
    </ReportPage>
  );
}

/** Nur im nicht-ausgeblendeten Zweig aufgerufen: dort sind alle Zahlen gesetzt. */
function toBarChartItems(items: AssetAllocationItem[]): BarChartItem[] {
  return items.map((it) => ({
    label: it.label,
    ist_bps: it.ist_bps ?? 0,
    soll_bps: it.soll_bps ?? 0,
    drift_bps: it.drift_bps ?? 0,
    band_min_bps: it.band_min_bps ?? undefined,
    band_max_bps: it.band_max_bps ?? undefined,
  }));
}

export function StaleTargetsNotice({ hinweis }: { hinweis?: string | null }) {
  return (
    <div role="alert" className="border border-rule bg-canvas-subtle p-4 text-caption">
      <p className="font-semibold text-status-rot">
        Achtung: {hinweis || 'Soll-Allokation ist veraltet. Strategie neu berechnen.'}
      </p>
      <p className="mt-2 text-ink-muted">
        Die bisherigen Zielgewichte und Bandbreiten werden nicht angezeigt, bis
        die Strategie neu berechnet ist.
      </p>
    </div>
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
