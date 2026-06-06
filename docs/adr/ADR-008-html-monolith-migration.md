# ADR-008: HTML-Monolith zu React/TypeScript Migration

- **Status:** Accepted (Strategie), Implementation: in Progress
- **Datum:** 2026-06-06
- **Sprint:** U-35 (FE, Roadmap Punkt 35)

## Kontext

Die ursprueliche 5eyes-Frontend-Code-Basis ist `5eyes-electron/frontend/
5eyes_v2.html` — eine **1.29 MB grosse Single-HTML-Datei** mit inline
CSS+JS, manuell DOM-manipuliert. Sie deckt alle Beratungs-Workflows ab,
ist aber:

- **Schwer wartbar**: jede Aenderung erfordert manuelles DOM-Suchen
- **Schwer testbar**: keine Component-Tests moeglich, nur E2E
- **Schwer erweiterbar**: neue Berater-Features kollidieren mit
  bestehenden CSS-Regeln
- **Performance-mittelmaessig**: 1.29 MB Parse-Zeit bei jedem App-Start

Parallel wird eine **React + TypeScript** Applikation entwickelt unter
`5eyes-electron/frontend/reporting/`. Diese ist als Standalone-Read-Only-
Reporting-View gestartet, wird aber zur primaeren UI ausgebaut.

## Migration-Status (2026-06-06)

### Bereits in React/TS migriert

**Pages** (20 Komponenten in `src/pages/`):
- AssetAllocation, Ausgangslage, Beratungsprotokoll, Branchen,
  BuildingBlocks, Compliance, Cover, Disclaimer, Erkenntnisse,
  Goals, Inhaltsverzeichnis, Positionen, Pruefpunkte, Risikoprofil,
  Risikowaehrungen, StatementPm, WeiteresVorgehen

**Wiederverwendbare Komponenten** (11 in `src/components/`):
- AmpelPill, BarChartIstSoll, EditButton, ErrorBoundary, Logo,
  NotesDrawer, NotesEditForms, ReportPage, SectionEditWrapper,
  Sidebar, ThemeToggle

**Tests** (a11y + unit-Test-Suites): 68 .ts/.tsx-Files total

### Noch im HTML-Monolith

`5eyes_v2.html` bleibt zustaendig fuer:
- Hauptnavigation / App-Shell
- Datenerfassung / Workflows (Kunden anlegen, Mandate editieren,
  Profiling-Fragebogen, Goal-Wizard)
- Backend-API-Anbindung im Datenfluss
- Editor-Workflows (vs. Read-Only-Reporting in React)

## Strategie

**Two-Track-Migration** (parallel) statt Big-Bang-Rewrite:

1. **Track 1: Reporting (DONE)** — Read-Only PDF-Vorschau + Section-
   Edit ist bereits in React.
2. **Track 2: Editor-Workflows** — schrittweise extrahieren, Sektion
   fuer Sektion. Pro Sektion: Schnittstelle in HTML zu `<iframe>` oder
   embedded React-Mount-Point.
3. **Track 3: App-Shell** — am Ende. Wenn alle Workflows React sind,
   wird die HTML-Datei zur Bootstrap-Shell reduziert (nur Router-
   Initialisierung).

### Reihenfolge der naechsten Extraktionen

Prio nach (a) User-Benefit + (b) Isolation-Risk:

1. **Profiling-Fragebogen** — abgegrenzte Sektion, hoher User-Value
   (Berater bedienen das taeglich)
2. **Goal-Wizard** — schon viel JS-Logik, klare Datenstruktur
3. **Mandate-Edit** — viele Felder, profitiert stark von TS-Validierung
4. **Kunden-CRM** — Suche/Filter/Tabellen
5. **Admin-Panels** — selten benutzt, niedriger Prio

### Migration-Pattern pro Sektion

```
1. Vorbereitung (1 Tag)
   - TypeScript-Schema fuer die Datenstruktur (matched Backend-Pydantic)
   - Storybook-Mock fuer Komponente
2. Implementation (2-4 Tage)
   - React-Komponente in src/sections/<name>/
   - Tests: a11y + unit + Snapshot
   - API-Hook in src/api/<name>.ts
3. Wiring (1 Tag)
   - HTML-Datei: section-Element wird zu <div id="root-<name>"></div>
   - JS-Bootstrap montiert die React-Komponente da
4. Migration-Test (1 Tag)
   - Drift-Test: alte HTML-Sektion vs neue React-Sektion produzieren
     identische Backend-Calls
   - Visual-Regression-Test (Playwright)
```

Geschaetzter Aufwand pro Sektion: **5-8 Tage** (Berater-Workflows sind
komplexer als reine Display-Komponenten).

Verbleibende Sektionen: ~6-8.
**Gesamt-Schaetzung Restmigration: 4-8 Wochen** (Track 2 + Track 3
zusammen, mit Risiko-Puffer).

## Entscheidung

**Two-Track-Migration weiter, KEIN Big-Bang.**

Grund:
- Big-Bang-Rewrite haette die Berater-Arbeit fuer Wochen blockiert
- Two-Track erlaubt: Berater nutzt HTML-Monolith taeglich, neue Features
  kommen in React, alte werden migriert wenn sie ohnehin angefasst werden
- Drift zwischen alt + neu wird durch Backend-API-Contracts begrenzt
  (siehe Drift-Tests in `5eyes-backend/tests/test_frontend_*_contracts.py`)

## Konsequenzen

**Positiv:**
- 5eyes bleibt durchgaengig nutzbar waehrend Migration
- Neue Features sind in React (testbar, wartbar)
- Pro Sektion ein eigenes PR -> reviewbar
- Visual-Regression-Tests fangen Drift

**Negativ:**
- Zwei Stack-Mentalitaeten bis Migration komplett (Inline-JS vs React)
- Backend-API-Contracts MUESSEN drift-getestet sein, sonst silent
  divergence
- Bundle-Size waehrend Transition: HTML-Monolith + React-Bundle laden
  beide -> ~1.5 MB Total. Akzeptabel weil Desktop-App (kein Mobile-3G).

## Implementations-Status (Punkt-Stand)

| Sektion                  | HTML-Monolith | React/TS | Drift-Test |
|--------------------------|---------------|----------|------------|
| Reporting-Sections (20)  | superseded    | ✓        | ✓          |
| Profiling-Fragebogen     | aktiv         | -        | ✓          |
| Goal-Wizard              | aktiv         | -        | -          |
| Mandate-Edit             | aktiv         | -        | -          |
| Kunden-CRM               | aktiv         | -        | -          |
| Asset-Allocation-Edit    | aktiv         | (View ✓) | ✓          |
| Compliance-Dashboard     | aktiv         | (View ✓) | ✓          |
| Cashflow-Review-Editor   | aktiv         | -        | ✓          |
| App-Shell                | aktiv         | -        | -          |

## Wann re-evaluieren?

- Wenn Berater taeglich Reibung mit der HTML-Monolith-UX melden
  -> Naechste Sektion prioritisieren
- Wenn Drift-Tests zu instabil werden (false positives) -> Migration
  beschleunigen
- Wenn neue Anforderung am HTML-Monolith aufwaendiger ist als
  Migration -> direkt in React

## Referenzen

- `5eyes-electron/frontend/5eyes_v2.html` — der Monolith (1.29 MB)
- `5eyes-electron/frontend/reporting/src/pages/` — React Pages (20)
- `5eyes-electron/frontend/reporting/src/components/` — React
  Components (11)
- `5eyes-backend/tests/test_frontend_*_contracts.py` — Drift-Tests
- ADR-004 (Editorial-No-Recharts) — Chart-Architektur-Entscheidung
- Memory `project_5eyes_audit.md` — Track-Migration-Status
