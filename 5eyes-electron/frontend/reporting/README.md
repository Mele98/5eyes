# 5eyes Reporting Sub-App

Institutioneller Depotcheck und Advisory-Report (15 Sektionen). Konsumiert
den Backend-Endpoint `GET /mandates/{id}/advisory-report` (Sprint U-P21).

> **Status:** Sprint U-P22.1 — Scaffold-Setup steht. Cover-Seite folgt in
> U-P22.3, weitere Seiten in U-P23-25.

---

## Setup (einmalig)

Voraussetzung: Node.js ≥ 20 lokal installiert.

```bash
cd 5eyes-electron/frontend/reporting
npm install
```

Das installiert React 18, Vite 5, Tailwind 3, Recharts und Framer Motion.
Erst nach diesem Schritt sind alle Build-Commands ausführbar.

---

## Entwicklung

```bash
npm run dev
```

Öffnet `http://localhost:5173` mit Hot-Module-Reload. API-Calls an
`/mandates/*` und `/admin/*` werden automatisch an den FastAPI-Backend-
Dev-Server auf Port 8000 weitergeleitet (siehe `vite.config.ts`).

---

## Token-Handoff Live-Verifikation (Roadmap-Punkt 5)

Der Bearer-Token-Handoff von der Hauptapp `5eyes_v2.html` zur Reporting-
Sub-App ist durch Unit-Tests vollstaendig abgedeckt (`handoff.test.ts`,
`client.test.ts` — 24/24). Die Live-Verifikation in der gepackten
Electron-App folgt dieser Checkliste:

### Pfade die der Token nimmt

```
Hauptapp openReportingApp()            Sub-App main.tsx
    |                                       |
    | window.desktop.getAuthToken()         |
    | (Electron) ODER                       |
    | sessionStorage['5eyes_token']         |
    |                                       |
    v                                       |
http://localhost:5173/...                   |
   /mandates/<ID>/report#token=<JWT>        |
    |                                       |
    +-> window.open(url, '_blank', 'noopener')
                                            |
                                            v
                              consumeHandoffFromUrlFragment()
                                |
                                |--> sessionStorage['5eyes_token']
                                |--> history.replaceState (URL Cleanup)
                                v
                              resolveAuthToken() (bei jedem fetch)
                                |
                                |  1. window.desktop.getAuthToken()
                                |  2. sessionStorage['5eyes_token']
                                |  3. localStorage['5eyes_token']
                                |  4. import.meta.env.VITE_5EYES_TOKEN
                                v
                              Authorization: Bearer <JWT>
```

### Smoke-Check Schritt-fuer-Schritt

1. **Backend starten** (siehe Entwicklung-Abschnitt)
2. **Hauptapp in Electron oeffnen**, einloggen
3. **DevTools oeffnen** (Strg+Shift+I) im Hauptapp-Fenster
4. **Mandat oeffnen**, dann `openReportingApp()` per Button
5. **Erwartung:** Externer Browser-Tab oeffnet sich mit URL
   `http://localhost:5173/mandates/<ID>/report#token=<JWT>`
6. **Im neuen Tab DevTools oeffnen**, Console:
   ```js
   window.location.hash  // sollte "" sein (URL-Cleanup hat gegriffen)
   sessionStorage.getItem('5eyes_token')  // sollte den JWT zeigen
   ```
7. **Network-Tab** → erster `/mandates/<ID>/advisory-report`-Request muss
   einen `Authorization: Bearer <JWT>`-Header haben → Status **200**.
8. **Reload (F5)**: Token bleibt in sessionStorage, kein 401.

### Negative Cases

| Szenario | Erwartung |
|---|---|
| Hauptapp ohne Login → openReportingApp() | URL ohne `#token=`, Sub-App zeigt 401 |
| Tab schliessen + Sub-App-URL direkt aus History | sessionStorage leer → 401 |
| Token abgelaufen (Backend liefert 401) | Sub-App zeigt strukturierten Error-Panel |
| Externer Browser ohne `window.desktop` | Cascade nutzt direkt sessionStorage |

### Was die Unit-Tests bereits abdecken

- Akzeptierte Hash-Patterns: `#token=`, `#/route?token=`, `#a=1&token=`
- URL-Encoded JWT mit `.`, `=`, `+` → korrekt dekodiert
- URL-Cleanup via `history.replaceState`
- Cascade-Reihenfolge: `desktop > session > local > env`
- Fail-Soft: jede Stufe wirft Exception → naechste Stufe greift
- Idempotenz: wiederholte Aufrufe ohne Hash sind No-Op

---

## End-to-End Visual-Check der Cover-Seite

Damit der Berater die Cover-Seite live mit echten Mandats-Daten sieht
(Sprint U-P22.3 Lieferung), funktioniert der Workflow heute über den
**Browser**, nicht über die gepackte Electron-App. Die echte Electron-
Shell-Integration folgt in U-P27 (Polish-Sprint), wenn alle 15 Sektionen
+ PDF fertig sind.

### Schritte

1. **Backend starten** (FastAPI auf Port 8000):
   ```bash
   cd 5eyes-backend
   uvicorn main:app --reload --port 8000
   ```

2. **Login in 5eyes-Hauptapp**, damit der Bearer-Token vorhanden ist
   (`window.desktop.getAuthToken` in Electron, `sessionStorage['5eyes_token']`
   im Browser-Dev-Fallback).
   (die Reporting-Sub-App nutzt dieselbe Session). Hauptapp normal über
   Electron oder `http://localhost:8000` starten und einloggen.

3. **Reporting-Sub-App starten** (in zweitem Terminal):
   ```bash
   cd 5eyes-electron/frontend/reporting
   npm install   # einmalig
   npm run dev
   ```

4. **Browser öffnen** mit dem Mandats-Pfad:
   ```
   http://localhost:5173/mandates/<MANDAT_ID>/report
   ```

5. **Ergebnis:** Cover-Seite wird im institutionellen Editorial-Look
   gerendert. Wenn der Browser einen 401-Fehler zeigt, fehlt der
   Bearer-Token — Schritt 2 wiederholen oder im Dev-Fallback
   `VITE_5EYES_TOKEN` als Build-Env setzen.

### Was du visuell prüfen kannst

- Schrift-Hierarchie (Serif Display, Sans Body)
- Farben (Offwhite Canvas, Navy Ink, Petrol Akzent, mattes Gold)
- Whitespace und Vertikal-Rhythmus
- Schweizer Datums-Format (DD.MM.YYYY)
- Print-Vorschau (Strg+P) → Layout 1:1 zum Bildschirm
- Fade-In-Animation beim Reload (langsam, sophisticated)

Korrekturen am Look fließen direkt in `tailwind.config.ts` (Design-
Tokens) bzw. `src/design/tokens.ts` (Chart-Palette) — beide Synchron
halten (statischer Test in `tests/test_reporting_subapp_scaffold.py`
verhindert Drift).

---

## Build

```bash
npm run build
```

Erzeugt einen Produktions-Build in `dist/`. Die Electron-Shell lädt das
Resultat als statische Dateien — keine Node-Dependency in der gepackten
App.

`npm run typecheck` läuft den TypeScript-Compiler ohne Build, nützlich
vor Commits.

---

## Architektur-Prinzipien

| Prinzip | Umsetzung |
|---|---|
| **Single Source of Truth** | Alle Daten kommen aus `/advisory-report`. Keine Frontend-State-Logik für Geschäfts-Aggregation. |
| **Design-Tokens** | Farben/Typo/Spacing in `tailwind.config.ts` + `src/design/tokens.ts`. Beide synchron halten. |
| **Print-ready** | Bildschirm- und Print-Layout identisch (siehe `@media print` in `globals.css`). |
| **Branding-Disziplin** | Keine Dritt-Marken in Code, Texten oder Assets (per 5eyes-Memory-Regel). |
| **Editorial / institutional** | Serif Headlines, Sans Body, viel Weissraum, keine Fintech-Pills. |

---

## Status der 15 Sektionen

| # | Sektion | Sprint | Stand |
|---|---|---|---|
| 1 | Cover | U-P22.3 | ⏳ |
| 2 | Inhaltsverzeichnis | U-P23 | ⏳ |
| 3 | Ausgangslage | U-P23 | ⏳ |
| 4 | Übersicht Positionen | U-P23 | ⏳ |
| 5 | Was wir prüfen | U-P23 | ⏳ |
| 6 | Erkenntnisse (Ampel) | U-P24 | ⏳ |
| 7 | Asset Allocation | U-P24 | ⏳ |
| 8 | Risikowährungen | U-P24 | ⏳ |
| 9 | Branchen | U-P24 | ⏳ |
| 10 | Goal-Based Investing | U-P24 | ⏳ |
| 11 | Risikoprofilierung | U-P25 | ⏳ |
| 12 | Building Blocks / iSAA | U-P25 | ⏳ |
| 13 | Statement PM | U-P25 | ⏳ |
| 14 | Weiteres Vorgehen | U-P25 | ⏳ |
| 15 | Disclaimer | U-P25 | ⏳ |

---

## Verzeichnisstruktur

```
reporting/
├── package.json          → Dependencies + Scripts
├── vite.config.ts        → Build & Dev-Proxy zu Port 8000
├── tailwind.config.ts    → Design-Tokens (Tailwind-Theme)
├── postcss.config.cjs
├── tsconfig.json
├── tsconfig.node.json
├── index.html            → Vite-Entry
├── src/
│   ├── main.tsx          → React + Router Bootstrap
│   ├── App.tsx           → Routes
│   ├── design/
│   │   └── tokens.ts     → Chart-Palette + JS-Konstanten
│   └── styles/
│       └── globals.css   → Tailwind base + Components
└── dist/                 → Build-Output (gitignored)
```
