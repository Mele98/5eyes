# Sprint U-P22.1 — Reporting React-Sub-App Scaffold

## Meta

- **Datum:** 2026-05-24
- **Vorgänger:** Sprint U-P21 (Backend-Aggregator `compute_advisory_report`)
- **Scope:** **Nur Scaffold-Setup.** Kein Daten-Flow, keine Sektion-Komponenten.
  Diese kommen in U-P22.3 (Cover), U-P23-25 (restliche 14 Sektionen).

## Zweck

Der Backend-Endpoint `GET /mandates/{id}/advisory-report` (U-P21) liefert
seit heute ein stabiles JSON-Schema. Bevor wir Komponenten bauen, braucht
es ein **sauberes Frontend-Setup** mit:

- moderner Build-Pipeline (Vite + TypeScript + Tailwind)
- institutionellen Design-Tokens (Farben, Typo, Spacing nach Berater-Spec)
- Routing-Skelett für die 15-Seiten-Struktur
- Build-Output, der von der Electron-Shell konsumiert werden kann
- statischer Test-Coverage, damit das Scaffold nie still verfällt

## Setup-Files (13 Stück)

```
5eyes-electron/frontend/reporting/
├── package.json              React 18 + Vite 5 + Tailwind 3 + Recharts + Framer Motion
├── vite.config.ts            Build → dist/, Dev-Proxy zu Backend:8000
├── tailwind.config.ts        Design-Tokens (Farben, Typo, Spacing)
├── postcss.config.cjs        Autoprefixer
├── tsconfig.json             strict + react-jsx + bundler-Modul-Auflösung
├── tsconfig.node.json        für Konfig-Dateien
├── index.html                Vite-Entry
├── .gitignore                node_modules + dist
├── README.md                 Setup-Anleitung für Berater
└── src/
    ├── main.tsx              React + Router Bootstrap
    ├── App.tsx               Routes (heute: Landing + Report-Stub)
    ├── design/
    │   └── tokens.ts         Chart-Palette + JS-Konstanten (Sync mit Tailwind)
    └── styles/
        └── globals.css       Tailwind base + Components + Print-Layer
```

## Design-Tokens (per Berater-Spec)

| Token-Familie | Werte |
|---|---|
| `canvas` | Offwhite (#FAFAF6), subtler Section-BG, Panel-Weiss |
| `ink` | Sehr dunkles Navy (#0F1C2E), muted (#3B475A), subtle (#6F7A8A) |
| `accent` | Tiefes Petrol (#2C5F5F) — Headlines/KPI |
| `rule` | Linien-Grau (#E5E4DE / #C8C6BD) |
| `gold` | Mattes Gold (#B39455) — sparsam, nur für Verdict-Pills |
| `status` | Ampel-Farben: gruen/gelb/rot/**neutral** (= nicht_beurteilbar) |
| Fonts | Serif Headlines (Cormorant Garamond), Sans Body (Inter), Mono (JetBrains) |
| Spacing | `page-x: 4rem`, `page-y: 5rem`, `section: 4rem`, `block: 2rem` |
| Border-Radius | `card: 4px`, `pill: 999px` — sparsam, nie zu rund |
| Animation | `soft: 400ms` mit editorial cubic-bezier |

**Tailwind-Theme und `tokens.ts` sind synchron** — beide enthalten dieselben
Hex-Werte (über Tests verifiziert).

## Routing

```typescript
/                              → Landing (Hinweis-Stub)
/mandates/:mandateId/report    → Report-Shell (15 Sektionen kommen sukzessive)
*                              → Redirect auf /
```

## Build-Pipeline

- **Dev:** `npm run dev` → http://localhost:5173 mit HMR, API-Calls proxied zu :8000
- **Build:** `npm run build` → typecheck + Vite-Build in `dist/`
- **Electron-Integration:** `dist/` wird von Shell als statische Dateien geladen
  (kommt in U-P22.4 — separater Sprint)

## Tests

`tests/test_reporting_subapp_scaffold.py` — **28 Tests, alle grün in 0.04s**:

| Gruppe | Tests | Was |
|---|---|---|
| Dateistruktur (parametrisiert) | 13 | Jede Setup-Datei existiert |
| package.json | 1 | Valid JSON + Pflicht-Dependencies + Scripts |
| Tailwind-Tokens | 1 | Alle Color-Familien + 4 Status-Farben + Editorial-Spacing |
| tokens.ts ↔ Tailwind | 1 | Synchronizität der Hex-Werte (no Drift) |
| App.tsx Routing | 1 | `/mandates/:mandateId/report` deklariert |
| Vite Backend-Proxy | 1 | `/mandates` + `/admin` → localhost:8000 |
| globals.css | 1 | Tailwind-Direktiven + Print-Layer |
| Branding-Compliance (parametrisiert) | 6 | Keine Dritt-Marken in 6 sichtbaren Files |
| .gitignore | 1 | node_modules + dist drin |
| README | 1 | Setup-Befehle dokumentiert |
| tsconfig | 1 | strict + react-jsx + bundler |

## Was als Nächstes (Folge-Sprints)

| Sprint | Inhalt | Vorraussetzung |
|---|---|---|
| **U-P22.2** | API-Client (Fetch-Wrapper + TypeScript-Typen aus Schema-v1) | `npm install` lokal |
| **U-P22.3** | Cover-Seite (Sektion 1) als Proof — institutioneller Look | U-P22.2 |
| **U-P22.4** | Electron-Shell-Integration (dist/-Loading via Hash-Route) | U-P22.3 |
| **U-P23** | Sektionen 2-5 Frontend | U-P22.2 |
| **U-P24** | Sektionen 6-10 + echte Monte-Carlo-Pfade-Berechnung im Backend | U-P22.2 |
| **U-P25** | Sektionen 11-15 | U-P22.2 |
| **U-P26** | Server-PDF (ReportLab) im identischen Layout | U-P21 (existiert) |

## Owner-Aktion vor U-P22.2

```bash
cd 5eyes-electron/frontend/reporting
npm install
```

Dauer: ~1-2 min. Installiert React 18, Vite 5, Tailwind 3, Recharts 2,
Framer Motion 11 + alle dev-Tools (TypeScript, PostCSS, ESLint via TS).

Danach: `npm run dev` öffnet die Sub-App auf http://localhost:5173 —
heute zeigt sie nur die Scaffold-Landing-Page (Daten-Flow kommt in U-P22.2).
