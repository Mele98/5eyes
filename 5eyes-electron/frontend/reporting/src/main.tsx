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

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
