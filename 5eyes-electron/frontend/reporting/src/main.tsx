import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { consumeHandoffFromUrlFragment } from './api/handoff';
import './styles/globals.css';

// Sprint U-P22.6 — Token-Handoff von der Hauptapp:
// Wenn die Reporting-Sub-App via Hauptapp-Button aufgerufen wird, kommt
// der Bearer-Token im URL-Fragment (`#token=<jwt>`). Wir lesen ihn früh,
// stecken ihn in sessionStorage (= 5eyes-Hauptapp-Konvention) und
// bereinigen die URL, damit der Token weder im Browser-Verlauf noch im
// React-Router-Pfad sichtbar bleibt. Erst danach rendert React.
consumeHandoffFromUrlFragment();

// Sprint U-20 (2026-06-04): React-Router v6 Future-Flags via
// `<BrowserRouter future={...}>` aktivieren — bereitet v7-Migration vor
// und unterdrueckt Console-Warnings.
// Flags-Constant liegt in lib/routerFlags.ts damit Tests sie
// importieren koennen ohne main's createRoot-Side-Effect zu triggern.
import { ROUTER_FUTURE_FLAGS } from './lib/routerFlags';

// Sprint U-87 (2026-06-05): Top-Level Error Boundary.
import { ErrorBoundary } from './components/ErrorBoundary';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {/* Bug-#6 (2026-06-07): basename muss mit Backend-Static-Mount
          (/reporting/) und vite.config base uebereinstimmen, sonst
          springen Routen wie /mandates/:id/report ins 404. */}
      <BrowserRouter basename="/reporting" future={ROUTER_FUTURE_FLAGS}>
        <App />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
