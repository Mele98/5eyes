/**
 * Sektion 17 (UI) — Compliance-Audit Dashboard.
 *
 * Aggregiert Backend-Sektionen 19-23 (PR #163, 2026-06-04) + 28 (Roadmap
 * #61, Standpunkt 2026-08-07) in einer Berater-tauglichen Übersicht:
 *   - 19 Suitability-Compliance (FIDLEG Art. 11/13/16)
 *   - 20 Methodology-Modelle (NS / KGV / Risikoprämien)
 *   - 21 Recommendation-Methodology (Optimizer-Run)
 *   - 22 Mandate-Lock-Status
 *   - 23 Liquidity-Cascade-Warning
 *   - 28 Reserve-Erklaerbarkeit (WARUM Reservebedarf/externe Reserve) --
 *     Backend (services/advisory_report.py::_build_reserve_explainability)
 *     war seit seiner Einfuehrung fertig berechnet + getypt, aber nirgends
 *     gerendert; dieselbe "computed but never surfaced"-Bugklasse wie das
 *     E-Signing-Sichtbarkeitsproblem (d48c8d5) und der Waehrungs-Abgleich
 *     im Admin-Panel (26fb1c5).
 *
 * Editorial-Stil: kompakte Status-Cards, keine Verkaufsargumente,
 * keine Garantieversprechen. FINMA-bewusst.
 */
import { AmpelPill } from '@/components/AmpelPill';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatChfRappen } from '@/lib/format';
import type {
  LiquidityCascadeData,
  MandateLockStatusData,
  MethodologyModelsData,
  RecommendationMethodologyData,
  ReserveExplainabilityData,
  SuitabilityComplianceData,
} from '@/api/types';

interface ComplianceProps {
  suitability: SuitabilityComplianceData;
  methodology: MethodologyModelsData;
  recommendation: RecommendationMethodologyData;
  mandateLock: MandateLockStatusData;
  liquidityCascade: LiquidityCascadeData;
  reserveExplainability: ReserveExplainabilityData;
}

export function Compliance({
  suitability,
  methodology,
  recommendation,
  mandateLock,
  liquidityCascade,
  reserveExplainability,
}: ComplianceProps) {
  // DL-2: defensiv gegen partielle/ältere Payloads (Aggregator liefert diese
  // Sektionen zwar immer, aber ein fehlendes Objekt soll die Seite nicht crashen).
  const overallCompliant = (
    !!suitability?.is_compliant
    && !!recommendation?.is_compliant
    && !!mandateLock?.is_editable
    && !liquidityCascade?.warning_required
  );

  return (
    <ReportPage
      nr={17}
      kicker="Compliance-Audit"
      title="Compliance-Audit"
      subtitle="Übersicht der FIDLEG/FINMA-relevanten Audit-Pruefungen für dieses Mandat."
    >
      <OverallStatusBanner compliant={overallCompliant} />

      <SuitabilityCard data={suitability} />
      <MethodologyCard data={methodology} />
      <RecommendationCard data={recommendation} />
      <MandateLockCard data={mandateLock} />
      <LiquidityCascadeCard data={liquidityCascade} />
      <ReserveExplainabilityCard data={reserveExplainability} />
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------
// Overall Status
// ---------------------------------------------------------------------------

function OverallStatusBanner({ compliant }: { compliant: boolean }) {
  const status = compliant ? 'gruen' : 'rot';
  const label = compliant ? 'Audit-Bestand sauber' : 'Audit-Handlungsbedarf';
  return (
    <section
      data-testid="compliance-overall-banner"
      className="mt-block border-l-4 border-accent bg-canvas-subtle px-6 py-5"
    >
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Gesamtbild
      </p>
      <div className="mt-2 flex items-center gap-3">
        <AmpelPill status={status} label={label} size="md" />
        <p className="font-serif text-h3 text-ink">
          {compliant
            ? 'Alle 5 Audit-Pruefungen unauffaellig.'
            : 'Mindestens eine Audit-Pruefung erfordert Berater-Aktion.'}
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sektion 19: Suitability
// ---------------------------------------------------------------------------

function SuitabilityCard({ data }: { data: SuitabilityComplianceData }) {
  const status = data.is_compliant ? 'gruen' : 'rot';
  const issueCount = (
    data.logs_without_suitability.length
    + data.freshness_issues.length
    + data.result_issues.length
  );
  return (
    <ComplianceCard
      testId="compliance-suitability"
      title="Geeignetheitspruefung (FIDLEG Art. 11/13/16)"
      status={status}
      summary={`${data.logs_requiring_suitability} pflichtige Logs, ${data.logs_with_suitability} dokumentiert, ${issueCount} Verstoesse`}
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-caption">
        <dt className="text-ink-subtle">Beratungs-Logs gesamt</dt>
        <dd className="font-mono text-ink">{data.total_advisory_logs}</dd>
        <dt className="text-ink-subtle">Pflichtig (Vollberatung)</dt>
        <dd className="font-mono text-ink">{data.logs_requiring_suitability}</dd>
        <dt className="text-ink-subtle">Dokumentiert</dt>
        <dd className="font-mono text-ink">{data.logs_with_suitability}</dd>
        <dt className="text-ink-subtle">Ohne Pruefung</dt>
        <dd className="font-mono text-ink">{data.logs_without_suitability.length}</dd>
        <dt className="text-ink-subtle">Freshness-Verstoesse</dt>
        <dd className="font-mono text-ink">{data.freshness_issues.length}</dd>
        <dt className="text-ink-subtle">Result-Verstoesse</dt>
        <dd className="font-mono text-ink">{data.result_issues.length}</dd>
      </dl>
      <p className="mt-3 text-micro text-ink-subtle">{data.fidleg_basis}</p>
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Sektion 20: Methodology
// ---------------------------------------------------------------------------

interface MethodologyModel {
  model_key: string;
  label?: string;
  active: boolean;
  basis?: string;
  blocker_reason?: string | null;
}

function MethodologyCard({ data }: { data: MethodologyModelsData }) {
  const status = data.active_count > 0 ? 'gruen' : 'nicht_beurteilbar';
  const models = data.models as unknown as MethodologyModel[];
  return (
    <ComplianceCard
      testId="compliance-methodology"
      title="Engine-Methodologie (CMA-Modelle)"
      status={status}
      summary={`${data.active_count} von ${models.length || 3} Modellen aktiv`}
    >
      {models.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine CMA-Daten verfuegbar.
        </p>
      ) : (
        <ul className="space-y-2 text-caption">
          {models.map((m) => (
            <li key={m.model_key} className="flex items-center gap-3">
              <AmpelPill
                status={m.active ? 'gruen' : 'nicht_beurteilbar'}
                label={m.active ? 'Aktiv' : 'Inaktiv'}
                size="sm"
              />
              <span className="font-semibold text-ink">{m.label || m.model_key}</span>
              {m.blocker_reason ? (
                <span className="text-micro text-status-gelb">({m.blocker_reason})</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {data.methodology_notes.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-caption text-ink-muted">
          {data.methodology_notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      ) : null}
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Sektion 21: Recommendation-Methodology
// ---------------------------------------------------------------------------

interface RecommendationRun {
  method?: string;
  status_label?: string;
  status?: string;
  is_acceptable?: boolean;
  seed?: number | null;
  n_paths?: number | null;
  n_iterations?: number | null;
}

function RecommendationCard({ data }: { data: RecommendationMethodologyData }) {
  const status = data.is_compliant ? 'gruen' : 'rot';
  const latest = data.latest_active_run as unknown as RecommendationRun | null;
  return (
    <ComplianceCard
      testId="compliance-recommendation"
      title="Optimizer-Methode (FIDLEG Art. 16)"
      status={status}
      summary={`${data.total_runs} Runs total · ${data.active_count} aktiv · ${data.fallback_count} Fallback`}
    >
      {latest ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-caption">
          <dt className="text-ink-subtle">Aktiver Run</dt>
          <dd className="font-mono text-ink">{latest.method || '—'}</dd>
          <dt className="text-ink-subtle">Status</dt>
          <dd className="font-mono text-ink">{latest.status_label || latest.status || '—'}</dd>
          <dt className="text-ink-subtle">Seed</dt>
          <dd className="font-mono text-ink">{latest.seed ?? '—'}</dd>
          <dt className="text-ink-subtle">MC-Pfade</dt>
          <dd className="font-mono text-ink">{latest.n_paths ?? '—'}</dd>
          <dt className="text-ink-subtle">Iterations</dt>
          <dd className="font-mono text-ink">{latest.n_iterations ?? '—'}</dd>
        </dl>
      ) : (
        <p className="italic text-caption text-ink-subtle">
          Noch kein aktiver Optimizer-Run.
        </p>
      )}
      <p className="mt-3 text-micro text-ink-subtle">{data.fidleg_basis}</p>
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Sektion 22: Mandate-Lock-Status
// ---------------------------------------------------------------------------

function MandateLockCard({ data }: { data: MandateLockStatusData }) {
  const status = data.is_editable ? 'gruen' : 'gelb';
  const label = data.is_editable ? 'Editierbar' : 'Read-Only';
  return (
    <ComplianceCard
      testId="compliance-mandate-lock"
      title="Mandate-Lock-Status"
      status={status}
      summary={label}
    >
      {data.lock_reasons.length === 0 ? (
        <p className="text-caption text-ink-muted">
          Keine Sperren aktiv. Mandat kann normal bearbeitet werden.
        </p>
      ) : (
        <ul className="space-y-2 text-caption">
          {data.lock_reasons.map((reason) => (
            <li key={reason} className="border-l-2 border-status-gelb pl-3">
              <span className="font-semibold text-ink">{reason}</span>
              <p className="mt-1 text-ink-muted">
                {data.lock_reason_labels[reason] || '—'}
              </p>
            </li>
          ))}
        </ul>
      )}
      {data.latest_optimizer_status ? (
        <p className="mt-3 text-micro text-ink-subtle">
          Letzter Optimizer-Status: {data.latest_optimizer_status}
        </p>
      ) : null}
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Sektion 23: Liquidity-Cascade
// ---------------------------------------------------------------------------

function LiquidityCascadeCard({ data }: { data: LiquidityCascadeData }) {
  const stageMap = {
    normal: { ampel: 'gruen' as const, label: 'Normal' },
    hard_cap: { ampel: 'gelb' as const, label: 'Am Hard-Cap' },
    emergency: { ampel: 'rot' as const, label: 'Emergency (>3%)' },
    unknown: { ampel: 'nicht_beurteilbar' as const, label: 'Unbekannt' },
  };
  const stageInfo = stageMap[data.stage];
  return (
    <ComplianceCard
      testId="compliance-liquidity"
      title="Liquiditaets-Cascade"
      status={stageInfo.ampel}
      summary={stageInfo.label}
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-caption">
        <dt className="text-ink-subtle">Aktuelle Liquiditaet</dt>
        <dd className="font-mono text-ink">{formatBpsAsPct(data.liquidity_bps)}</dd>
        <dt className="text-ink-subtle">Hard-Cap</dt>
        <dd className="font-mono text-ink">{formatBpsAsPct(data.hard_cap_bps)}</dd>
        <dt className="text-ink-subtle">Emergency-Cap</dt>
        <dd className="font-mono text-ink">{formatBpsAsPct(data.emergency_cap_bps)}</dd>
        {data.over_hard_cap_by_bps !== null ? (
          <>
            <dt className="text-ink-subtle">Ueber Hard-Cap</dt>
            <dd className="font-mono text-status-gelb">
              {formatBpsAsPct(data.over_hard_cap_by_bps)}
            </dd>
          </>
        ) : null}
      </dl>
      {data.warning_required ? (
        <div className="mt-3 border-l-2 border-status-rot bg-status-rot/5 p-3 text-caption text-ink">
          <p className="font-semibold">Beratungsgespraech pruefen.</p>
          <p className="mt-1 text-ink-muted">{data.stage_label}</p>
        </div>
      ) : null}
      <p className="mt-3 text-micro text-ink-subtle">{data.fidleg_basis}</p>
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Sektion 28 (Roadmap #61): Reserve-Erklaerbarkeit
// ---------------------------------------------------------------------------

function ReserveExplainabilityCard({ data }: { data: ReserveExplainabilityData }) {
  if (!data.available) {
    return (
      <ComplianceCard
        testId="compliance-reserve-explainability"
        title="Reserve-Herleitung"
        status="nicht_beurteilbar"
        summary="Keine Reserve-Herleitung verfuegbar"
      >
        <p className="text-caption text-ink-muted">{data.hinweis}</p>
        <p className="mt-3 text-micro text-ink-subtle">{data.fidleg_basis}</p>
      </ComplianceCard>
    );
  }

  const hasReserve = (data.reserve_needed_rappen ?? 0) > 0;
  const status = !hasReserve ? 'gruen' : data.composition_available ? 'gruen' : 'gelb';
  const summary = !hasReserve
    ? 'Kein zusaetzlicher Liquiditaetsreserve-Bedarf'
    : `${formatChfRappen(data.reserve_needed_rappen)} Reservebedarf`;

  return (
    <ComplianceCard
      testId="compliance-reserve-explainability"
      title="Reserve-Herleitung"
      status={status}
      summary={summary}
    >
      {hasReserve ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-caption">
          <dt className="text-ink-subtle">Reservebedarf</dt>
          <dd className="font-mono text-ink">{formatChfRappen(data.reserve_needed_rappen)}</dd>
          <dt className="text-ink-subtle">SAA-Liquiditaets-Obergrenze</dt>
          <dd className="font-mono text-ink">{formatBpsAsPct(data.saa_liquidity_ceiling_bps)}</dd>
          {data.external_reserve_recommended ? (
            <>
              <dt className="text-ink-subtle">Externe Reserve empfohlen</dt>
              <dd className="font-mono text-ink">{formatChfRappen(data.external_reserve_rappen)}</dd>
            </>
          ) : null}
          {data.other_assets_absorption_rappen ? (
            <>
              <dt className="text-ink-subtle">Absorbiert durch anderes Vermoegen</dt>
              <dd className="font-mono text-ink">{formatChfRappen(data.other_assets_absorption_rappen)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}

      {data.external_reserve_reason ? (
        <p className="mt-3 text-caption text-ink-muted">{data.external_reserve_reason}</p>
      ) : null}

      {data.composition_available && data.narrative.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-caption text-ink-muted">
          {data.narrative.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      ) : null}

      {data.drift_detected ? (
        <div className="mt-3 border-l-2 border-status-gelb bg-status-gelb/5 p-3 text-caption text-ink">
          <p className="font-semibold">Herleitung nicht aktuell.</p>
          <p className="mt-1 text-ink-muted">{data.hinweis}</p>
        </div>
      ) : (
        !data.composition_available && data.hinweis ? (
          <p className="mt-3 text-caption text-ink-muted">{data.hinweis}</p>
        ) : null
      )}

      <p className="mt-3 text-micro text-ink-subtle">{data.fidleg_basis}</p>
    </ComplianceCard>
  );
}

// ---------------------------------------------------------------------------
// Shared Card-Component
// ---------------------------------------------------------------------------

function ComplianceCard({
  title,
  status,
  summary,
  children,
  testId,
}: {
  title: string;
  status: 'gruen' | 'gelb' | 'rot' | 'nicht_beurteilbar';
  summary: string;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <section
      data-testid={testId}
      className="mt-section border-t border-rule pt-block"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-serif text-h2 text-ink">{title}</h2>
          <p className="mt-1 text-caption text-ink-muted">{summary}</p>
        </div>
        <AmpelPill status={status} size="md" />
      </header>
      <div className="mt-3">{children}</div>
    </section>
  );
}
