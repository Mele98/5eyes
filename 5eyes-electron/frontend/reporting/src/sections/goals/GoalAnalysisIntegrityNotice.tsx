/**
 * GOAL-ANALYSIS-INTEGRITY-UI-REACT-001: ruhiger Berater-Hinweis, wenn die
 * gespeicherte Zielanalyse oder der Shadow-Container der aktuellen Strategie
 * ihren Integritaetsnachweis verletzen
 * (GET /mandates/{id}/target-allocation/current/analysis-integrity).
 *
 * Reiner Hinweis: die Kanaele zeigen die Analyse dann ohnehin nicht; er sagt
 * nur warum. Blockiert nichts, aendert nichts, nie im Druck.
 */
import { useEffect, useState } from 'react';
import { fetchAnalysisIntegrity } from '@/api/allocation';
import type { AnalysisIntegrityReport } from '@/api/types';
import { useUserRole } from '@/api/useUserRole';

const FALLBACK_LABEL = 'Zielanalyse nicht verifizierbar';

export function GoalAnalysisIntegrityNotice({
  data,
}: {
  data: AnalysisIntegrityReport | null | undefined;
}) {
  if (!data || data.needs_attention !== true) {
    return null;
  }
  return (
    <p
      role="status"
      data-integrity={`${data.goal_analysis}|${data.shadow_analysis}`}
      className="mt-3 border-l-2 border-status-neutral pl-3 text-caption text-ink-muted print:hidden"
    >
      <span className="mr-2 border border-status-neutral px-2 py-0.5 text-micro uppercase tracking-widest text-status-neutral">
        {data.label || FALLBACK_LABEL}
      </span>
      {data.text ?? null}
    </p>
  );
}

/** Laedt den Status fuer das Mandat; Ladefehler bleiben still (nur Hinweis). */
export function GoalAnalysisIntegrity({ mandateId }: { mandateId: string }) {
  const [data, setData] = useState<AnalysisIntegrityReport | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    fetchAnalysisIntegrity(mandateId, { signal: controller.signal })
      .then((report) => {
        if (!controller.signal.aborted) setData(report);
      })
      .catch(() => {
        if (!controller.signal.aborted) setData(null);
      });
    return () => controller.abort();
  }, [mandateId]);
  return <GoalAnalysisIntegrityNotice data={data} />;
}

/** Nur Berater-Ansicht: ohne Bearbeitungsrecht wird nichts geladen. */
export function GoalAnalysisIntegrityForAdvisor({ mandateId }: { mandateId: string }) {
  const { canEdit } = useUserRole();
  return canEdit ? <GoalAnalysisIntegrity mandateId={mandateId} /> : null;
}
