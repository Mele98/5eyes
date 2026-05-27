import { Routes, Route, Navigate, useParams } from 'react-router-dom';
import { useAdvisoryReport } from '@/api/useAdvisoryReport';
import type { AdvisoryReport } from '@/api/types';
import { Sidebar, REPORT_SECTIONS } from '@/components/Sidebar';
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
import { WeiteresVorgehen } from '@/pages/WeiteresVorgehen';

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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
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
        Diese Anwendung erzeugt den institutionellen Depotcheck eines Mandats
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
      <Sidebar mandateId={mandateId} activeSection={sectionId} />
      <main>{renderSection(sectionId, data, mandateId, reload)}</main>
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
  if (sectionId === 'weiteres-vorgehen') {
    return (
      <WeiteresVorgehen
        data={data.weiteres_vorgehen}
        mandateId={mandateId}
        onReload={reload}
      />
    );
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
