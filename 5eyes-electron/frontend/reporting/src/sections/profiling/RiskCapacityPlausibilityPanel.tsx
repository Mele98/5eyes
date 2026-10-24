/**
 * RISK-CAPACITY-REPORT-001: kompakte Berater-Anzeige der
 * Plausibilitaetspruefung Risikofaehigkeit (Fragebogen vs. erfasste Daten).
 *
 * Reiner Hinweis: das Risikoprofil wird dadurch nie automatisch geaendert,
 * nichts wird blockiert. Der Berater entscheidet (Fragebogen korrigieren oder
 * Profil per Override nach unten dokumentieren).
 */
import type { ReactNode } from 'react';
import { riskCapacityCheckLabel } from '@/api/riskCapacityPlausibility';
import type {
  RiskCapacityPlausibilityCompact,
  RiskCapacityPlausibilityStatus,
} from '@/api/riskCapacityPlausibility';

const STATUS_META: Record<
  RiskCapacityPlausibilityStatus,
  { label: string; tone: string; summary: string }
> = {
  consistent: {
    label: 'Konsistent',
    tone: 'border-status-gruen text-status-gruen',
    summary: 'Die Angaben zur Risikofähigkeit passen zu den erfassten Finanzdaten.',
  },
  partial: {
    label: 'Teilweise geprüft',
    tone: 'border-status-gelb text-status-gelb',
    summary:
      'Kein Widerspruch gefunden, aber einzelne Prüfungen sind mangels erfasster Daten offen.',
  },
  inconsistent: {
    label: 'Widerspruch',
    tone: 'border-status-rot text-status-rot',
    summary: 'Einzelne Angaben zur Risikofähigkeit weichen von den erfassten Finanzdaten ab.',
  },
  not_evaluable: {
    label: 'Nicht prüfbar',
    tone: 'border-status-neutral text-status-neutral',
    summary: 'Die Angaben zur Risikofähigkeit konnten nicht gegen erfasste Daten geprüft werden.',
  },
};

const NOT_EVALUABLE_HINT = 'Risikofähigkeit mangels Daten nicht prüfbar – Finanzdaten erfassen.';

const NO_ASSESSMENT_HINT = 'Kein aktuelles Risikoprofil vorhanden – Risikoprofil erfassen.';

const BINDING_MISMATCH_HINT =
  'Prüfergebnis ist keinem aktuellen Risikoprofil eindeutig zuordenbar – nicht als geprüft werten.';

const REFERENCE_MISMATCH_HINT =
  'Die Prüfung bezieht sich auf das aktuelle Risikoprofil, nicht auf das in der Eignungsprüfung referenzierte Profil.';

const NO_AUTO_CHANGE = 'Das Risikoprofil wird dadurch nicht automatisch geändert.';

/**
 * Kompakte Variante aus dem Advisory-Report-Payload (betragsfrei).
 * Rendert bei partial/inconsistent/not_evaluable (CIO-Entscheid: fehlende
 * Daten bleiben nie stumm) -- nur bei consistent oder ohne Daten null.
 */
export function RiskCapacityPlausibilityNotice({
  data,
}: {
  data: RiskCapacityPlausibilityCompact | null | undefined;
}) {
  if (!data || data.status === 'consistent') {
    return null;
  }
  const meta = STATUS_META[data.status] ?? STATUS_META.not_evaluable;
  const checks = data.status === 'inconsistent' ? data.finding_checks : data.open_checks;
  const topics = checks.map(riskCapacityCheckLabel).join(' · ');
  return (
    <PanelFrame status={data.status} label={meta.label} tone={meta.tone} printHidden>
      <p className="mt-3 text-caption text-ink-muted">
        {data.status === 'not_evaluable' ? compactNotEvaluableHint(data) : meta.summary}
      </p>
      {topics ? <p className="mt-2 text-caption text-ink">{topics}</p> : null}
      {data.suitability_reference_match === false ? (
        <p className="mt-2 text-caption text-ink-muted">{REFERENCE_MISMATCH_HINT}</p>
      ) : null}
      <Footer
        reasonCode={data.reason_code}
        verificationCode={data.verification_code ?? null}
      />
    </PanelFrame>
  );
}

function compactNotEvaluableHint(data: RiskCapacityPlausibilityCompact): string {
  if (data.availability === 'missing_input' || data.reason_code === 'NO_CURRENT_RISK_ASSESSMENT') {
    return NO_ASSESSMENT_HINT;
  }
  if (data.availability === 'integrity_mismatch') {
    return BINDING_MISMATCH_HINT;
  }
  return NOT_EVALUABLE_HINT;
}

function PanelFrame({
  status,
  label,
  tone,
  printHidden = false,
  children,
}: {
  status: RiskCapacityPlausibilityStatus;
  label: string;
  tone: string;
  printHidden?: boolean;
  children: ReactNode;
}) {
  return (
    <section
      aria-label="Plausibilitätsprüfung Risikofähigkeit"
      data-status={status}
      className={`border border-rule bg-canvas-panel p-5${printHidden ? ' print:hidden' : ''}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Plausibilitätsprüfung Risikofähigkeit · Beraterhinweis
        </p>
        <span className={`border px-3 py-1 text-micro uppercase tracking-widest ${tone}`}>
          {label}
        </span>
      </div>
      {children}
    </section>
  );
}

function Footer({
  reasonCode,
  verificationCode,
}: {
  reasonCode: string | null;
  verificationCode: string | null;
}) {
  const codes = [reasonCode, verificationCode].filter(Boolean).join(' · ');
  return (
    <p className="mt-3 text-micro text-ink-subtle">
      {NO_AUTO_CHANGE}
      {codes ? <span className="block font-mono">{codes}</span> : null}
    </p>
  );
}
