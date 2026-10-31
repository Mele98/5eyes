/**
 * RISK-CAPACITY-RECHECK-UI-001: ruhiger Berater-Hinweis "neu zu prüfen",
 * wenn die bei der Beratung gebundene Bewertung der Plausibilitaetspruefung
 * nicht mehr der aktuellen Datenlage entspricht (bound_evaluation aus
 * GET /mandates/{id}/risk-capacity-plausibility).
 *
 * Reiner Hinweis: blockiert nichts, aendert nichts, nie im Druck.
 */
import { useEffect, useState } from 'react';
import { fetchRiskCapacityBoundEvaluation } from '@/api/profiling';
import type { RiskCapacityBoundEvaluation } from '@/api/types';

const FALLBACK_LABEL = 'neu zu prüfen';

export function RiskCapacityRecheckNotice({
  data,
}: {
  data: RiskCapacityBoundEvaluation | null | undefined;
}) {
  if (!data || data.needs_recheck !== true) {
    return null;
  }
  const label = data.recheck_label || FALLBACK_LABEL;
  return (
    <p
      role="status"
      data-recheck-code={data.recheck_code ?? ''}
      className="mt-3 border-l-2 border-status-neutral pl-3 text-caption text-ink-muted print:hidden"
    >
      <span className="mr-2 border border-status-neutral px-2 py-0.5 text-micro uppercase tracking-widest text-status-neutral">
        {label}
      </span>
      {data.recheck_text ?? null}
    </p>
  );
}

/** Laedt den Status fuer das Mandat; Ladefehler bleiben still (nur Hinweis). */
export function RiskCapacityRecheck({ mandateId }: { mandateId: string }) {
  const [data, setData] = useState<RiskCapacityBoundEvaluation | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    fetchRiskCapacityBoundEvaluation(mandateId, { signal: controller.signal })
      .then((bound) => {
        if (!controller.signal.aborted) setData(bound);
      })
      .catch(() => {
        if (!controller.signal.aborted) setData(null);
      });
    return () => controller.abort();
  }, [mandateId]);
  return <RiskCapacityRecheckNotice data={data} />;
}
