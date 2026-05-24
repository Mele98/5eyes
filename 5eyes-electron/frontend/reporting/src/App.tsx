import { Routes, Route, Navigate } from 'react-router-dom';

/**
 * Root-Layout der Reporting-Sub-App.
 *
 * Routing-Strategie (Sprint U-P22.1 — Scaffold):
 *   /                                     → 404-Hinweis (kein Default-Mandat)
 *   /mandates/:mandateId/report           → Single-Page-Report (alle 15 Sektionen)
 *
 * In U-P22.2+ wird der Single-Page-Report durch eine 15-Routen-Struktur
 * mit Sticky-Nav ersetzt (eine Route pro Sektion). Heute zeigt der Stub
 * nur eine Landing-Message — Datenflow wird in U-P22.3 (API-Client) und
 * U-P22.4 (Cover-Seite) verkabelt.
 */
function App() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <Routes>
        <Route
          path="/"
          element={
            <ScaffoldHome />
          }
        />
        <Route
          path="/mandates/:mandateId/report"
          element={<ReportShell />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

function ScaffoldHome() {
  return (
    <main className="mx-auto max-w-editorial px-page-x py-page-y">
      <p className="text-micro uppercase tracking-wider text-ink-subtle">
        5eyes Reporting · Scaffold v0.1
      </p>
      <h1 className="mt-block font-serif text-display text-ink">
        Strategische Portfolioanalyse
      </h1>
      <p className="mt-block max-w-prose text-body text-ink-muted">
        Diese Sub-App liefert den institutionellen Depotcheck und
        Advisory-Report eines Mandats. Datenquelle ist der Backend-Endpoint
        <code className="ml-1 px-2 py-0.5 bg-canvas-subtle rounded-card text-caption">
          GET /mandates/&#123;id&#125;/advisory-report
        </code>
        (Sprint U-P21).
      </p>
      <p className="mt-block text-caption text-ink-subtle">
        Aufruf-Beispiel: <code>/mandates/&lt;mandat-id&gt;/report</code>
      </p>
    </main>
  );
}

function ReportShell() {
  return (
    <main className="mx-auto max-w-editorial px-page-x py-page-y">
      <p className="text-micro uppercase tracking-wider text-ink-subtle">
        Sprint U-P22.1 · Scaffold
      </p>
      <h1 className="mt-block font-serif text-display text-ink">
        Report-Pipeline initialisiert
      </h1>
      <p className="mt-block max-w-prose text-body text-ink-muted">
        Die 15 Berichts-Sektionen werden in den Folge-Sprints U-P22.3 bis
        U-P25 implementiert. Aktuell wird der Endpoint noch nicht
        konsumiert &mdash; das Setup steht.
      </p>
    </main>
  );
}

export default App;
