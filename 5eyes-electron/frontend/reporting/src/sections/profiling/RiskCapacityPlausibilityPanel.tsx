/**
 * RISK-CAPACITY-REPORT-001: kompakte Berater-Anzeige der
 * Plausibilitaetspruefung Risikofaehigkeit (Fragebogen vs. erfasste Daten).
 *
 * Reiner Hinweis: das Risikoprofil wird dadurch nie automatisch geaendert,
 * nichts wird blockiert. Der Berater entscheidet (Fragebogen korrigieren oder
 * Profil per Override nach unten dokumentieren).
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  fetchRiskCapacityPlausibility,
  riskCapacityCheckLabel,
} from '@/api/riskCapacityPlausibility';
import type {
  RiskCapacityPlausibility,
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

const NO_AUTO_CHANGE = 'Das Risikoprofil wird dadurch nicht automatisch geändert.';

export function RiskCapacityPlausibilityView({
  result,
}: {
  result: RiskCapacityPlausibility;
}) {
  const meta = STATUS_META[result.status] ?? STATUS_META.not_evaluable;
  const actions = result.resolution_actions ?? [];
  return (
    <PanelFrame status={result.status} label={meta.label} tone={meta.tone}>
      <p className="mt-3 text-caption text-ink-muted">
        {result.status === 'inconsistent' && result.advisor_text
          ? result.advisor_text
          : meta.summary}
      </p>
      {result.status === 'inconsistent' && result.findings.length > 0 ? (
        <ul className="mt-3 space-y-2 text-caption" aria-label="Abweichungen">
          {result.findings.map((finding, index) => (
            <li key={`${finding.check}-${index}`} className="border-l-2 border-status-rot pl-3">
              <span className="font-semibold text-ink">
                {riskCapacityCheckLabel(finding.check)}
              </span>
              {finding.message ? (
                <span className="block text-ink-muted">{finding.message}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {result.status !== 'consistent' && result.not_evaluable.length > 0 ? (
        <ul className="mt-3 space-y-2 text-caption" aria-label="Nicht prüfbar">
          {result.not_evaluable.map((row, index) => (
            <li key={`${row.check}-${index}`} className="border-l-2 border-rule pl-3">
              <span className="font-semibold text-ink">
                {riskCapacityCheckLabel(row.check)}
              </span>
              {row.reason ? <span className="block text-ink-muted">{row.reason}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {actions.length > 0 ? (
        <div className="mt-3 text-caption">
          <p className="font-semibold text-ink">Nächste Schritte</p>
          <ul className="mt-1 list-disc pl-5 text-ink-muted">
            {actions.map((action, index) => (
              <li key={`action-${index}`}>{action}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <Footer
        reasonCode={result.reason_code}
        verificationCode={result.verification_code ?? null}
      />
    </PanelFrame>
  );
}

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
        {data.status === 'not_evaluable' ? NOT_EVALUABLE_HINT : meta.summary}
      </p>
      {topics ? <p className="mt-2 text-caption text-ink">{topics}</p> : null}
      <Footer
        reasonCode={data.reason_code}
        verificationCode={data.verification_code ?? null}
      />
    </PanelFrame>
  );
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

type LoadState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; result: RiskCapacityPlausibility }
  | { kind: 'error' };

/**
 * Laedt die Pruefung fuer das Mandat. `assessmentId` dient als Refresh-Key:
 * nach dem Speichern eines neuen Profils wird neu geladen; ohne aktuelles
 * Profil (null) wird nichts angezeigt.
 */
export function RiskCapacityPlausibilityPanel({
  mandateId,
  assessmentId,
}: {
  mandateId: string | undefined;
  assessmentId: string | null | undefined;
}) {
  const [state, setState] = useState<LoadState>({ kind: 'idle' });

  useEffect(() => {
    if (!mandateId || !assessmentId) {
      setState({ kind: 'idle' });
      return;
    }
    const controller = new AbortController();
    setState({ kind: 'loading' });
    fetchRiskCapacityPlausibility(mandateId, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setState({ kind: 'ready', result });
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setState({ kind: 'error' });
      });
    return () => controller.abort();
  }, [mandateId, assessmentId]);

  if (state.kind === 'idle') return null;
  if (state.kind === 'loading') {
    return (
      <section
        aria-label="Plausibilitätsprüfung Risikofähigkeit"
        aria-busy="true"
        className="border border-rule bg-canvas-panel p-5 text-caption text-ink-muted"
      >
        Plausibilitätsprüfung wird geladen …
      </section>
    );
  }
  if (state.kind === 'error') {
    // Fail-closed: ein Ladefehler wird nie als "konsistent" dargestellt.
    return (
      <section
        aria-label="Plausibilitätsprüfung Risikofähigkeit"
        data-status="error"
        className="border border-status-neutral bg-canvas-panel p-5 text-caption text-ink-muted"
      >
        Plausibilitätsprüfung Risikofähigkeit konnte nicht geladen werden –
        Status unbekannt, nicht als geprüft werten.
      </section>
    );
  }
  return <RiskCapacityPlausibilityView result={state.result} />;
}
