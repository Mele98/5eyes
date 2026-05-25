import { Routes, Route, Navigate, useParams } from 'react-router-dom';
import { useAdvisoryReport } from '@/api/useAdvisoryReport';
import { Cover } from '@/pages/Cover';

/**
 * Root-Layout der Reporting-Sub-App.
 *
 * Routing-Strategie (Sprint U-P22.2/.3 — API + Cover):
 *   /                                      → Landing-Hinweis (kein Default-Mandat)
 *   /mandates/:mandateId/report            → Single-Page-Report (heute: Cover)
 *   /mandates/:mandateId/report/cover      → expliziter Cover-Direkt-Link
 *
 * Ab U-P23 wird die Single-Page-Struktur durch eine 15-Routen-Sektion-Tour
 * mit Sticky-Side-Nav ersetzt. Heute ist nur die Cover-Seite implementiert,
 * weitere Sektionen kommen sukzessive (U-P23-25).
 */
function App() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/mandates/:mandateId/report"
          element={<ReportShell />}
        />
        <Route
          path="/mandates/:mandateId/report/cover"
          element={<ReportShell />}
        />
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
        <code className="ml-1 px-2 py-0.5 bg-canvas-subtle rounded-card text-caption">
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

function ReportShell() {
  const { mandateId } = useParams<{ mandateId: string }>();
  const { state, data, error } = useAdvisoryReport(mandateId);

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
  return <Cover data={data.cover} />;
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
