import { useEffect, useState } from 'react';
import { Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom';
import { useAdvisoryReport } from '@/api/useAdvisoryReport';
import type { AdvisoryReport } from '@/api/types';
import { Sidebar, REPORT_SECTIONS } from '@/components/Sidebar';
import {
  KEYBOARD_SHORTCUTS,
  getFirstSection,
  getLastSection,
  getNextSection,
  getPrevSection,
  isTypingInInput,
  sectionHref,
} from '@/lib/sectionNavigation';
import { Cover } from '@/pages/Cover';
import { Disclaimer } from '@/pages/Disclaimer';
import { Inhaltsverzeichnis } from '@/pages/Inhaltsverzeichnis';
import { Ausgangslage } from '@/pages/Ausgangslage';
import { Positionen } from '@/pages/Positionen';
import { Pruefpunkte } from '@/pages/Pruefpunkte';
import { Erkenntnisse } from '@/pages/Erkenntnisse';
import { AssetAllocation } from '@/pages/AssetAllocation';
import { Risikowaehrungen } from '@/pages/Risikowaehrungen';
import { Branchen } from '@/pages/Branchen';
import { Goals } from '@/pages/Goals';
import { Risikoprofil } from '@/pages/Risikoprofil';
import { BuildingBlocks } from '@/pages/BuildingBlocks';
import { StatementPm } from '@/pages/StatementPm';
import { WeiteresVorgehen } from '@/pages/WeiteresVorgehen';
import { Beratungsprotokoll } from '@/pages/Beratungsprotokoll';
import { Compliance } from '@/pages/Compliance';
import { Eignung } from '@/pages/Eignung';
import { GoalsEditor } from '@/sections/goals/GoalsEditor';
import { AllocationEditor } from '@/sections/allocation/AllocationEditor';
import { CashflowEditor } from '@/sections/cashflow/CashflowEditor';
import { MandateEditor } from '@/sections/mandate/MandateEditor';
import { CrmEditor } from '@/sections/crm/CrmEditor';

type ReportSectionId = (typeof REPORT_SECTIONS)[number]['id'];

const SECTION_ROUTES: Array<{ id: ReportSectionId; path: string }> =
  REPORT_SECTIONS.map((section) => ({
    id: section.id,
    path: section.path,
  }));

function App() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/mandates/:mandateId/report"
          element={<ReportShell sectionId="cover" />}
        />
        <Route
          path="/mandates/:mandateId/report/cover"
          element={<ReportShell sectionId="cover" />}
        />
        {SECTION_ROUTES.filter((route) => route.path).map((route) => (
          <Route
            key={route.id}
            path={`/mandates/:mandateId/report/${route.path}`}
            element={<ReportShell sectionId={route.id} />}
          />
        ))}
        {/* Track #64: Goal-Editor (Editor-Workflow, KEINE Report-Sektion). */}
        <Route
          path="/mandates/:mandateId/goals-editor"
          element={<GoalsEditorRoute />}
        />
        {/* Track #67: Asset-Allocation-Editor. */}
        <Route
          path="/mandates/:mandateId/allocation-editor"
          element={<AllocationEditorRoute />}
        />
        {/* Track #68: Cashflow-Editor (am Client). */}
        <Route
          path="/clients/:clientId/cashflow-editor"
          element={<CashflowEditorRoute />}
        />
        {/* Track #65: Mandate-Editor. */}
        <Route
          path="/mandates/:mandateId/mandate-editor"
          element={<MandateEditorRoute />}
        />
        {/* Track #66: CRM/Stammdaten-Editor (Workflow-Eintritt). */}
        <Route path="/crm-editor" element={<CrmEditor />} />
        <Route path="/clients/:clientId/crm-editor" element={<CrmEditorRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

function GoalsEditorRoute() {
  const { mandateId } = useParams<{ mandateId: string }>();
  if (!mandateId) {
    return (
      <ErrorPanel
        headline="Kein Mandat"
        detail="URL erwartet :mandateId-Parameter."
      />
    );
  }
  return <GoalsEditor mandateId={mandateId} />;
}

function AllocationEditorRoute() {
  const { mandateId } = useParams<{ mandateId: string }>();
  if (!mandateId) {
    return (
      <ErrorPanel
        headline="Kein Mandat"
        detail="URL erwartet :mandateId-Parameter."
      />
    );
  }
  return <AllocationEditor mandateId={mandateId} />;
}

function CashflowEditorRoute() {
  const { clientId } = useParams<{ clientId: string }>();
  if (!clientId) {
    return (
      <ErrorPanel
        headline="Kein Kunde"
        detail="URL erwartet :clientId-Parameter."
      />
    );
  }
  return <CashflowEditor clientId={clientId} />;
}

function MandateEditorRoute() {
  const { mandateId } = useParams<{ mandateId: string }>();
  if (!mandateId) {
    return (
      <ErrorPanel
        headline="Kein Mandat"
        detail="URL erwartet :mandateId-Parameter."
      />
    );
  }
  return <MandateEditor mandateId={mandateId} />;
}

function CrmEditorRoute() {
  const { clientId } = useParams<{ clientId: string }>();
  return <CrmEditor initialClientId={clientId} />;
}

function Landing() {
  return (
    <main className="mx-auto max-w-editorial px-page-x py-page-y">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        5eyes Reporting · Sub-App v0.1
      </p>
      <h1 className="mt-block font-serif text-display text-ink">
        Strategische Portfolioanalyse
      </h1>
      <p className="mt-block max-w-prose text-body text-ink-muted">
        Diese Anwendung erzeugt den institutionellen Advisory-Report eines Mandats
        auf Basis des 5eyes-Backend-Endpoints
        <code className="ml-1 rounded-card bg-canvas-subtle px-2 py-0.5 text-caption">
          GET /mandates/&#123;id&#125;/advisory-report
        </code>
        .
      </p>
      <p className="mt-block text-caption text-ink-subtle">
        Aufruf-Beispiel: <code>/mandates/&lt;mandat-id&gt;/report</code>
      </p>
    </main>
  );
}

function ReportShell({ sectionId }: { sectionId: ReportSectionId }) {
  const { mandateId } = useParams<{ mandateId: string }>();
  const { state, data, error, reload } = useAdvisoryReport(mandateId);

  if (!mandateId) {
    return (
      <ErrorPanel
        headline="Kein Mandat"
        detail="URL erwartet :mandateId-Parameter."
      />
    );
  }
  if (state === 'loading' || state === 'idle') {
    return <LoadingPanel />;
  }
  if (state === 'error' || !data) {
    return (
      <ErrorPanel
        headline="Daten konnten nicht geladen werden"
        detail={error?.message ?? 'Unbekannter Fehler.'}
      />
    );
  }
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      {/* Sprint U-90: Skip-Link fuer Tastatur-Nutzer + Screen-Reader. */}
      <a
        href="#report-main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
      >
        Direkt zum Hauptinhalt
      </a>
      <Sidebar mandateId={mandateId} activeSection={sectionId} />
      <main
        id="report-main-content"
        tabIndex={-1}
        aria-label={`Beratungsreport-Hauptinhalt: ${sectionId}`}
      >
        {renderSection(sectionId, data, mandateId, reload)}
      </main>
      <KeyboardShortcuts mandateId={mandateId} activeSection={sectionId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sprint U-51: Tastatur-Shortcuts (j/k Nav, g/G Erste/Letzte, ? Help, Esc)
// ---------------------------------------------------------------------------

function KeyboardShortcuts({
  mandateId,
  activeSection,
}: {
  mandateId: string;
  activeSection: string;
}) {
  const navigate = useNavigate();
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isTypingInInput(e.target)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      switch (e.key) {
        case 'j': {
          const next = getNextSection(REPORT_SECTIONS, activeSection);
          if (next) {
            e.preventDefault();
            navigate(sectionHref(mandateId, next));
          }
          break;
        }
        case 'k': {
          const prev = getPrevSection(REPORT_SECTIONS, activeSection);
          if (prev) {
            e.preventDefault();
            navigate(sectionHref(mandateId, prev));
          }
          break;
        }
        case 'g': {
          // 'g' allein -> erste Sektion (Vim-style: 'g g' wird hier vereinfacht)
          if (!e.shiftKey) {
            const first = getFirstSection(REPORT_SECTIONS);
            if (first) {
              e.preventDefault();
              navigate(sectionHref(mandateId, first));
            }
          }
          break;
        }
        case 'G': {
          const last = getLastSection(REPORT_SECTIONS);
          if (last) {
            e.preventDefault();
            navigate(sectionHref(mandateId, last));
          }
          break;
        }
        case '?': {
          e.preventDefault();
          setShowHelp((v) => !v);
          break;
        }
        case 'Escape': {
          if (showHelp) {
            e.preventDefault();
            setShowHelp(false);
          }
          break;
        }
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [activeSection, mandateId, navigate, showHelp]);

  if (!showHelp) return null;
  return (
    <div
      data-testid="keyboard-help-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 no-print"
      onClick={() => setShowHelp(false)}
    >
      <div
        className="max-w-md rounded border border-rule bg-canvas-panel p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Tastatur-Shortcuts
        </p>
        <h2 className="mt-2 font-serif text-h3 text-ink">Navigation</h2>
        <dl className="mt-4 space-y-2 text-caption">
          {KEYBOARD_SHORTCUTS.map((s) => (
            <div key={s.key} className="flex items-baseline justify-between gap-4">
              <dt>
                <kbd className="rounded border border-rule bg-canvas px-2 py-0.5 font-mono text-micro text-ink">
                  {s.label}
                </kbd>
              </dt>
              <dd className="text-ink-muted">{s.description}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-micro text-ink-subtle">
          (Shortcuts werden in Eingabefeldern automatisch ignoriert.)
        </p>
      </div>
    </div>
  );
}

function renderSection(
  sectionId: ReportSectionId,
  data: AdvisoryReport,
  mandateId: string,
  reload: () => void,
) {
  if (sectionId === 'cover') {
    return <Cover data={data.cover} />;
  }
  if (sectionId === 'disclaimer') {
    return <Disclaimer data={data.disclaimer} />;
  }
  if (sectionId === 'toc') {
    return <Inhaltsverzeichnis data={data.inhaltsverzeichnis} />;
  }
  if (sectionId === 'ausgangslage') {
    return <Ausgangslage data={data.ausgangslage} />;
  }
  if (sectionId === 'positionen') {
    return <Positionen data={data.positionen} />;
  }
  if (sectionId === 'pruefpunkte') {
    return <Pruefpunkte data={data.pruefpunkte} />;
  }
  if (sectionId === 'erkenntnisse') {
    return <Erkenntnisse data={data.erkenntnisse} />;
  }
  if (sectionId === 'asset-allocation') {
    return (
      <AssetAllocation
        data={data.asset_allocation}
        mandateId={mandateId}
        onReload={reload}
      />
    );
  }
  if (sectionId === 'risikowaehrungen') {
    return (
      <Risikowaehrungen
        data={data.risikowaehrungen}
        mandateId={mandateId}
        onReload={reload}
      />
    );
  }
  if (sectionId === 'branchen') {
    return (
      <Branchen
        data={data.branchen}
        mandateId={mandateId}
        onReload={reload}
      />
    );
  }
  if (sectionId === 'goals') {
    return <Goals data={data.goal_based_investing} />;
  }
  if (sectionId === 'risikoprofil') {
    return <Risikoprofil data={data.risikoprofilierung} />;
  }
  if (sectionId === 'building-blocks') {
    return <BuildingBlocks data={data.building_blocks} />;
  }
  if (sectionId === 'statement-pm') {
    return <StatementPm data={data.statement_pm} />;
  }
  if (sectionId === 'weiteres-vorgehen') {
    return (
      <WeiteresVorgehen
        data={data.weiteres_vorgehen}
        mandateId={mandateId}
        onReload={reload}
      />
    );
  }
  if (sectionId === 'beratungsprotokoll') {
    return (
      <Beratungsprotokoll
        data={data.beratungsprotokoll}
        mandateId={mandateId}
        onReload={reload}
      />
    );
  }
  if (sectionId === 'compliance') {
    return (
      <Compliance
        suitability={data.suitability_compliance}
        methodology={data.methodology_models}
        recommendation={data.recommendation_methodology}
        mandateLock={data.mandate_lock_status}
        liquidityCascade={data.liquidity_cascade}
      />
    );
  }
  if (sectionId === 'eignung') {
    return <Eignung data={data.suitability_summary} />;
  }
  return <PendingSection sectionId={sectionId} />;
}

function PendingSection({ sectionId }: { sectionId: ReportSectionId }) {
  const section = REPORT_SECTIONS.find((item) => item.id === sectionId);
  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <p className="text-micro uppercase text-ink-subtle">
        Sektion {section?.nr}
      </p>
      <h1 className="mt-block font-serif text-h1 text-ink">
        {section?.title}
      </h1>
      <p className="mt-block max-w-prose text-body text-ink-muted">
        In Vorbereitung.
      </p>
    </article>
  );
}

function LoadingPanel() {
  return (
    <main
      data-testid="report-loading"
      aria-busy="true"
      aria-live="polite"
      className="mx-auto max-w-editorial px-page-x py-page-y"
    >
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Bericht wird geladen
      </p>
      <p className="mt-block text-body text-ink-muted">
        Die Sektionen werden vom Backend zusammengestellt.
      </p>
    </main>
  );
}

function ErrorPanel({
  headline,
  detail,
}: {
  headline: string;
  detail: string;
}) {
  return (
    <main
      data-testid="report-error"
      role="alert"
      aria-live="assertive"
      className="mx-auto max-w-editorial px-page-x py-page-y"
    >
      <p className="text-micro uppercase tracking-widest text-status-rot">
        Fehler
      </p>
      <h1 className="mt-block font-serif text-h1 text-ink">{headline}</h1>
      <p className="mt-block text-body text-ink-muted">{detail}</p>
    </main>
  );
}

export default App;
