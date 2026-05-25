# Codex-Sprint U-P27 — Electron-Window-Integration (Polish-Phase)

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** U-P23, U-P24, U-P25 (Frontend voll) + U-P26 (PDF) müssen
> fertig sein. Dieser Sprint **schließt die Production-Lücke**: keine
> Browser-Tab-Akrobatik mehr, alles in der gepackten Electron-App.
> **Größenordnung:** ~10-15 Stunden, 3 PRs.

---

## Zweck

Heute öffnet die Reporting-Sub-App in einem **separaten Browser-Tab**
auf `http://localhost:5173` (Vite-Dev-Server). Das ist explizit als
Dev-only markiert (siehe `docs/planning/2026-05-25-sprint-u-p22-6-...md`).

**Production-Anforderung:** Berater klickt „Advisory-Report" in der
Electron-Hauptapp → es öffnet sich ein **zweites Electron-Window**
mit der Reporting-Sub-App, die das gebundelte `dist/`-Output lädt.
**Keine externen Browser, keine npm-Dependency in der gepackten App.**

---

## Was umzubauen ist

### 1. Vite-Build-Integration in Electron-Packaging

`5eyes-electron/package.json` Build-Pipeline:
- Vor `electron-builder` läuft `npm run build` in `frontend/reporting/`
- Das `frontend/reporting/dist/` wird im electron-builder als
  `extraResources` mitgebundlet
- PyInstaller-Spec (`5eyes-backend/`) bleibt unverändert (Backend liefert
  weiter JSON, ist davon entkoppelt)

### 2. Neues BrowserWindow in `main.js`

Neue Funktion `createReportingWindow(mandateId, token)`:
```javascript
async function createReportingWindow(mandateId, token) {
  const reportingWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 800,
    autoHideMenuBar: true,
    backgroundColor: '#FAFAF6',  // Editorial Offwhite
    parent: mainWindow,           // Modal-Child der Hauptapp
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
    },
  });

  // Token NICHT via URL-Fragment (das war Dev-Workflow).
  // Stattdessen: window.desktop.getAuthToken() greift direkt aus dem
  // bestehenden IPC (preload.js auth:get-token).

  const reportingIndex = app.isPackaged
    ? path.join(process.resourcesPath, 'reporting-dist/index.html')
    : path.join(__dirname, 'frontend/reporting/dist/index.html');

  reportingWindow.loadFile(reportingIndex, {
    hash: `/mandates/${mandateId}/report`,
  });

  reportingWindow.once('ready-to-show', () => reportingWindow.show());
}
```

### 3. IPC-Bridge erweitern (`preload.js` + `main.js`)

Neue IPC-Channel:
- `reporting:open` → erhält mandateId, ruft `createReportingWindow`
- `reporting:close` → schließt das zweite Window

### 4. Hauptapp `5eyes_v2.html` Button-Update

`openReportingApp()` umbauen:
```javascript
async function openReportingApp(){
  const mid = getActiveMandateId();
  if(!mid){ alert('Bitte zuerst ein Mandat oeffnen.'); return; }

  // Production: nativer Electron-Window via IPC
  if (window.desktop && typeof window.desktop.openReporting === 'function') {
    await window.desktop.openReporting(mid);
    return;
  }

  // Dev-Fallback: weiterhin Browser-Tab (Vite-Dev)
  const token = sessionStorage.getItem('5eyes_token') || '';
  window.open(
    'http://localhost:5173/mandates/' + encodeURIComponent(mid) + '/report' +
    (token ? '#token=' + encodeURIComponent(token) : ''),
    '_blank', 'noopener'
  );
}
```

### 5. Reporting-App `handoff.ts` defensive

`consumeHandoffFromUrlFragment` bleibt als **No-op-Fallback** für den
Production-Fall (in Electron kommt der Token via `getAuthToken()`,
kein Fragment).

---

## Tests

`tests/test_electron_reporting_integration.py` (NEU):
- Statische Checks: `main.js` deklariert `createReportingWindow`
- `preload.js` exposed `openReporting`
- `5eyes_v2.html` ruft `window.desktop.openReporting` mit Fallback
- electron-builder-Config bundelt `frontend/reporting/dist/`
- Branding-Compliance

---

## PR-Aufteilung

| PR | Inhalt |
|---|---|
| **PR A** | Vite-Build-Integration + electron-builder extraResources |
| **PR B** | `createReportingWindow` + IPC-Bridge + preload-Erweiterung |
| **PR C** | `openReportingApp` Production-Path + Dev-Fallback |

---

## Acceptance

1. Berater startet gepackte Electron-App (kein npm, kein Vite)
2. Klick „Advisory-Report" → zweites Electron-Window öffnet sich
3. Cover-Seite rendert sofort mit echten Mandat-Daten
4. Token automatisch via Electron-IPC (kein URL-Fragment sichtbar)
5. „PDF herunterladen"-Button funktioniert (lädt das U-P26 PDF)
6. Schliessen des Reporting-Windows beeinträchtigt Hauptapp nicht
7. **Dev-Modus** (npm run dev): URL-Fragment-Fallback weiter aktiv
