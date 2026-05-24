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
