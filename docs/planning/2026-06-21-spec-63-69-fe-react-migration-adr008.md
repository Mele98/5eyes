# Spec: Master-Migration FE-Monolith → React/TS (Roadmap #63–#69, ADR-008)

- **Datum:** 2026-06-21
- **Autor:** Claude (Spec), Umsetzung: Codex
- **Status:** Proposed (wartet auf OWNER-DECISIONs in §8)
- **Bezug:** ADR-008 (`docs/adr/ADR-008-html-monolith-migration.md`), Master-Roadmap `docs/planning/2026-06-14-roadmap-master.md` Punkte 63–69 (Zeile 87–93)
- **Scope:** Track 2 (Editor-Workflows) + Track 3 (App-Shell) der ADR-008-Migration

> Diese Datei ist eine **Roadmap-Spec**: Strategie + Reihenfolge + pro Track
> die Migrations-Bausteine (Schema-First → React-Page → Tests → Wiring →
> Drift-Test) + ein konkreter erster Codex-Auftrag für Track #63. Die
> Detail-Specs der Tracks #64–#69 werden je Track separat geschrieben, wenn
> der vorige Track gemerged und stabil ist (Strangler-Fig, siehe §8).

---

## 0. Verifizierte Fakten (file:line)

Alle Aussagen unten sind per Read/Grep am Repo verifiziert:

**ADR-008-Pattern** (`docs/adr/ADR-008-html-monolith-migration.md:74–91`):
Schritt 1 Vorbereitung (TS-Schema = Backend-Pydantic), Schritt 2 Implementation
(React in `src/sections/<name>/`, Tests a11y+unit+snapshot, API-Hook in
`src/api/<name>.ts`), Schritt 3 Wiring (HTML-Section → `<div id="root-<name>">`,
JS-Bootstrap montiert React), Schritt 4 Migration-Test (Drift-Test + Visual-
Regression). Reihenfolge (`:67–72`): Profiling → Goal-Wizard → Mandate-Edit →
CRM → Admin. Entscheidung (`:102`): **Two-Track, KEIN Big-Bang.**

**React-Blaupause** (`5eyes-electron/frontend/reporting/`):
- `package.json:7–14` Scripts: `dev` (vite), `build` (`tsc --noEmit && vite build`), `typecheck`, `test` (`vitest run`). Deps: react 18.3, react-router-dom 6.27, recharts 2.15, framer-motion 11.
- `vite.config.ts:22` `base: '/reporting/'`; `:24–26` Alias `@`→`./src`; `:31–40` Dev-Proxy `^/mandates/.*/advisory-report$` und `/admin` → `localhost:8000`.
- `src/main.tsx:14` `consumeHandoffFromUrlFragment()` VOR Render; `:32` `<BrowserRouter basename="/reporting">`; `:28` Top-Level `<ErrorBoundary>`.
- `src/App.tsx:42–66` Routing (`/mandates/:mandateId/report/...`); `:92–135` `ReportShell` (Sidebar + Skip-Link + Keyboard-Shortcuts); `:245–344` `renderSection`-Dispatcher.
- `src/api/client.ts:47–89` `fetchAdvisoryReport`; `:92–124` `resolveAuthToken` (Electron `window.desktop.getAuthToken` → sessionStorage `5eyes_token` → localStorage → `VITE_5EYES_TOKEN`); `:22–38` `ApiError`/`SchemaError`; `:131–158` `validateSchemaV2` (Top-Level-Key-Check + `schema_version===2`).
- `src/api/handoff.ts:47–88` Token-Handoff via `#token=` URL-Fragment → sessionStorage, dann `history.replaceState`-Cleanup.
- `src/api/reportNotes.ts` GET/PUT-Mutations-Client-Muster (`ReportNotes`/`ReportNotesUpdate`), `src/components/SectionEditWrapper.tsx` EditButton+Drawer-Muster.
- `src/components/Sidebar.tsx:13–37` `REPORT_SECTIONS`-Tabelle (id/nr/title/path) = Single-Source der Nav.
- Test-Blaupause: `src/test/fixtures.ts` (Backend-Payload-Spiegel), `src/App.a11y.test.tsx` (a11y-Pattern), `src/test/setup.ts`.

**Wiring-Ist-Zustand** (`5eyes-electron/frontend/5eyes_v2.html`):
- `:11037–11068` `openReportingApp()` öffnet die React-App per `window.open(apiBase + '/reporting/mandates/<id>/report#token=<jwt>')` in neuem Tab. → **Aktuelles Integrations-Pattern ist „neuer Tab + Token-Handoff", NICHT iframe.**
- `:11058` Backend-Base default `http://127.0.0.1:8000`; Reporting wird vom Backend unter `/reporting/` als Static-Mount serviert.

**Monolith-Workflow-Anker** (`5eyes-electron/frontend/5eyes_v2.html`) — die Datei ist tatsächlich **~24'700 Zeilen** (Grep-Treffer bis 24'281), nicht 17'300:
- Tab-Nav `:1935–1947` 7 Steps `go('sd'|'vg'|'cf'|'rp'|'al'|'po'|'rv')` (Stammdaten, Vermögen, Cashflows&Ziele, Risikoprofil, Asset-Allokation, Portfolio, Review&Abschluss).
- Router-Fn `go(p,b)` `:5357`. Page-Container: `page-sd:2565`, `page-vg:2607`, `page-cf:2616`, `page-rp:2652`, `page-al:3009`, `page-po:3437`, `page-rv:3458`.
- Profiling/Risk: `page-rp:2652`, `saveRiskProfile():14322`, `applyOv()` (Override) `:8924`.
- Goals: `saveGoal():24156`, `refreshGoalsUI():24281`, `goalSaveErrorText():24144`.
- Clients/CRM: `loadClients():5001`, `openStammdatenModal():22985`, `updateStammdatenHeader():22832`.
- Modals: neues Mandat `m-nc:4079`, neues Ziel `m-nz:4239`; Cashflow `openNewCashflow():20858`; AA `bindAllocationTableInteractions():6865`, `toggleSubAllocationGroup():18106`, `calculateInvestmentStrategy():18519`; Risk-Tabs `switchRTab` in `page-rp`.

**Backend-API-Verträge (FastAPI routers/, verifiziert):**
- Profiling/Risk (`routers/profiling.py`): GET `:117`/`:132` risk-assessments(/current), POST `:151` risk-assessments, POST `:291` `.../override`, knowledge GET/POST `:45`/`:58`, suitability-checks GET/POST `:335`/`:347`.
- Goals (`routers/wealth.py`): GET `:675`, POST `:689`, PUT `:727`, DELETE `:766` `/mandates/{id}/goals`, POST `:1047` calculate-max-pension-spending.
- Mandate (`routers/mandates.py`): GET `:24` `/clients/{id}/mandates`, POST `:36`, GET `:81` `/mandates/{id}`, PUT `:90`.
- CRM/Clients (`routers/clients.py`): GET `:104`, PUT `:113`, DELETE `:138` `/clients/{id}`, nationalities `:154`/`:167`, wealth-summary `:244`, cashflow-summary `:267`, cashflows-derived `:315`.
- Asset-Allocation (`routers/allocation.py`): GET `:92` target-allocation/current, GET `:135` .../payload, POST `:193` target-allocation, POST `:367` generate, POST `:394` sensitivity, GET `:466` advisory-report, GET/PUT `:526`/`:549` report-notes.
- Cashflow (`routers/wealth.py`): GET `:571`, POST `:590`, PUT `:641`, DELETE `:619` `/clients/{id}/cashflows`; abgeleitet `clients.py:315` cashflows-derived (read-only), `:397` cashflow-projection.

**Drift-Test-Mechanik** (`5eyes-backend/tests/test_frontend_*_contracts.py`):
Diese Tests lesen `5eyes_v2.html` als String und asserten auf Vorhandensein/
Abwesenheit von DOM-ids, JS-Funktionsnamen und Bindings (z.B.
`test_frontend_navigation_contracts.py:9–14` prüft `go('xx')`-Targets gegen
`VALID_PAGE_KEYS`; `:27` prüft den festen `pages={sd:0,...}`-String). Sie sind
**HTML-String-Assertions**, KEINE laufenden Backend-Call-Vergleiche. Für die
Migration heißt das: jeder Wiring-Schritt verändert die geprüften Strings →
**der zugehörige Drift-Test MUSS im selben PR mitgezogen werden** (siehe §6).

Inventory-Generator: `scripts/audit_html_monolith.py` (Snapshot von ids /
event-handlers / js-functions / css-selectors / modals / sub-sections nach
`docs/audits/2026-06-02-monolith-inventory.json`, mit `source_sha256`).

---

## 1. Strategie-Entscheidung (ADR-008-konform)

**Strangler-Fig, schrittweise, ein Track = ein PR.** Kein Big-Bang. Begründung
direkt aus ADR-008 (`:102–109`): der Monolith muss durchgehend vom Berater
nutzbar bleiben; Drift wird über Backend-API-Contracts + Drift-Tests begrenzt.

Zwei Integrations-Optionen (OWNER-DECISION A in §8):
- **Option A1 — Neuer Tab / eigene Route (wie heute `openReportingApp`).** Der
  migrierte Workflow läuft als zusätzliche Route in der bestehenden
  `reporting`-Sub-App; der Monolith-Button öffnet ihn per `window.open` mit
  Token-Handoff. Geringstes Risiko, null Eingriff in Monolith-Layout, aber
  Kontextwechsel (neuer Tab) für den Berater.
- **Option A2 — In-Place-Mount (iframe oder React-Mount-Point im `page-<x>`-
  div).** ADR-008 (`:56–58`) nennt iframe/embedded Mount. Nahtloser für den
  Berater, aber höheres Drift-/CSS-/Auth-Risiko und macht jeden Wiring-Schritt
  invasiver in `5eyes_v2.html`.

**Spec-Empfehlung:** **A1 für #63–#68** (Editor-Workflows als Routen in der
`reporting`-App, geöffnet per Tab — exakt das schon laufende, getestete Pattern
`openReportingApp`), **A2/Shell-Konsolidierung erst in #69** (App-Shell), wenn
alle Workflows React sind und der Monolith zur Bootstrap-Shell schrumpft.

Sub-App-Layout-Erweiterung (additiv, bricht Reporting nicht):
```
reporting/src/
  sections/              # NEU: Editor-Workflows (#63–#68), je 1 Ordner
    profiling/  goals/  mandate/  crm/  allocation/  cashflow/
  api/                   # je Track ein <track>.ts Mutations-/Query-Client
  pages/  components/  lib/   # bestehend (Reporting)
  App.tsx                # neue Routen additiv eintragen
```

---

## 2. Migrations-Reihenfolge mit Begründung (Risiko / Abhängigkeit)

| Rang | Track | Begründung Reihenfolge | Risiko | Abhängigkeit |
|------|-------|------------------------|--------|--------------|
| 1 | **#63 Profiling** | ADR-008-Prio #1; abgegrenzte Sektion (`page-rp`), Drift-Test existiert bereits (`test_frontend_risk_questionnaire_contracts.py`), klares Schema (risk-assessments + override). Bester Lern-/Pilot-Track. | niedrig | keine |
| 2 | **#64 Goal-Wizard** | ADR-008-Prio #2; viel JS-Logik schon teil-extrahiert (`lib/goalClassification.ts`, `lib/sortGoals.ts` existieren). Klares CRUD-Schema. | mittel | teilt `page-cf` mit #68 |
| 3 | **#67 AA-Edit** | View bereits in React (`pages/AssetAllocation.tsx`) + Drift-Test existiert → kleinster Sprung von View→Editor; reichste API. | mittel | Recommendation-Engine (vorhanden) |
| 4 | **#68 Cashflow-Editor** | Teilt `page-cf` mit #64 → nach #64 ziehen, um doppeltes Anfassen derselben HTML-Sektion zu vermeiden. Abgeleitete Posten read-only. | mittel | nach #64 |
| 5 | **#65 Mandate-Edit** | Viele Felder, profitiert stark von TS-Validierung (ADR-008 Prio #3), aber zentral im Datenfluss → später, wenn Pattern reif. | mittel-hoch | hängt an Client/Mandate-CRUD |
| 6 | **#66 CRM/Stammdaten** | `page-sd` = Einstiegspunkt des ganzen Workflows; hohe Kopplung an App-Shell-Navigation → kurz vor Shell. | hoch | Mandate (#65) |
| 7 | **#69 App-Shell** | ADR-008 Track 3 ausdrücklich **zuletzt** (`:59`). Erst wenn alle Workflows React sind, wird `go()`-Router + Tab-Nav + Auth abgelöst. | sehr hoch | ALLE vorigen |

> Abweichung von der reinen ADR-008-Reihenfolge: #67 vor #65/#66 vorgezogen,
> weil AA bereits eine React-View + Drift-Test hat (niedrigster Aufwand, höchster
> Lerneffekt für Editor-Mutationen). #68 direkt nach #64 wegen geteilter
> `page-cf`-Sektion. OWNER-DECISION B in §8.

---

## 3. Pro-Track-Bausteine (5-Schritt-Pattern)

Jeder Track folgt identisch: **Schema-First → React-Page → Tests → Wiring →
Drift-Test.** Gemeinsame Konventionen:

- **Auth:** kein neuer Mechanismus — `resolveAuthToken()` aus `api/client.ts`
  wiederverwenden (Electron → sessionStorage `5eyes_token` → … ). Token-Handoff
  via `handoff.ts` ist bereits global in `main.tsx` aktiv.
- **Fehler/Schema:** `ApiError`/`SchemaError` + Top-Level-Key-Validierung pro
  neuem Endpoint analog `validateSchemaV2`.
- **Mutations-Client:** Muster aus `api/reportNotes.ts` (GET lädt, PUT/POST
  speichert, optionale Felder = unverändert). Edit-UI-Muster aus
  `SectionEditWrapper.tsx`.
- **Routing:** additive Routen in `App.tsx`, Pfad-Schema
  `/mandates/:mandateId/<track>` bzw. `/clients/:clientId/<track>`.
- **Tests:** vitest unit + a11y (Pattern `App.a11y.test.tsx`) + Fixtures
  (`test/fixtures.ts`-Muster, gespiegelt vom Backend-`test_*`-Pendant).
- **Drift-Test:** existierenden `test_frontend_*_contracts.py` im SELBEN PR an
  den neuen HTML-Zustand anpassen (Wiring ändert die geprüften Strings).

### #63 Profiling-Workflow (`page-rp`)
- **Schema:** `api/types.ts`-Ergänzung `RiskAssessment`, `RiskAssessmentCreate`, `RiskOverride` (spiegelt `profiling.py` GET `:132` / POST `:151` / override `:291` + `schemas/`-Pydantic). Plus Willingness-Profil-Schwellen (Frontend MUSS mit `services/risk_scoring.py:_willingness_profile()` synchron bleiben — geprüft in `test_frontend_risk_questionnaire_contracts.py:105–114`).
- **React:** `sections/profiling/` — `ProfilingPage.tsx` (Fragebogen, KEINE Punkte/Scoreboard sichtbar — Drift-Test `:7–32`), `RiskSummary.tsx` (Override-Badge `overr-badge`, „tieferer Wert zählt"), `api/profiling.ts` (GET current, POST assessment, POST override).
- **Wiring:** Monolith-Button in `page-rp` öffnet `…/reporting/mandates/<id>/risikoprofil-editor` (A1, via `openReportingApp`-Muster).
- **Drift-Test:** `test_frontend_risk_questionnaire_contracts.py` erweitern: nach Wiring zeigt `page-rp` einen „In React öffnen"-Button; bestehende „keine-Punkte/keine-Scoreboard"-Asserts bleiben gültig.
- **Test-Plan:** unit (Score→Profil-Mapping == Backend-Schwellen), a11y (Formular-Labels, Live-Region für Speichern-Status), Fixtures (minimal risk-assessment), Override-Fehler im Modal (Muster `applyOv`-Drift-Test `:134–139`).

### #64 Goal-Wizard (`page-cf`, Goals-Teil)
- **Schema:** `Goal`, `GoalCreate`, `GoalUpdate`, `MaxPensionSpending` (`wealth.py:675/689/727/766/1047`). Hardness/Status-Enums existieren schon in `types.ts:27–36`.
- **React:** `sections/goals/` — Wizard-Steps + Zielliste; nutzt vorhandene `lib/goalClassification.ts` / `lib/sortGoals.ts`. `api/goals.ts` CRUD.
- **Wiring:** Button in `page-cf` (Goals-Block); `saveGoal()`/`refreshGoalsUI()` bleiben bis Cutover als Fallback.
- **Drift-Test:** `test_frontend_cashflow_goal_workspace_contracts.py` + `test_frontend_goal_cashflow_ist_contracts.py` anpassen.
- **Test-Plan:** unit (Klassifikation/Sortierung), a11y, Save-Success/Failure-Contract (Muster `goalSaveErrorText`).

### #67 Asset-Allocation-Edit (`page-al`)
- **Schema:** `TargetAllocation`, `AllocationGeneratePayload`, `Sensitivity` (`allocation.py:92/135/193/367/394`). View-Typen existieren (`types.ts` AssetAllocationData).
- **React:** `sections/allocation/` — Edit-Form + SOLL/IST-Charts als wiederverwendbare Komponente (`BarChartIstSoll.tsx` existiert bereits). `api/allocation.ts` (current/payload/save/generate/sensitivity).
- **Wiring:** `page-al`-Header — Quick-Actions-Layout NICHT brechen (Drift-Test `test_frontend_risk_questionnaire_contracts.py:60–83` prüft sichtbare vs. `aa-more`-Menü-Buttons).
- **Drift-Test:** o.g. Allocation-Header-Asserts + `bindAllocationTableInteractions`/`toggleSubAllocationGroup`-Checks (`:52–58`) mitziehen.
- **Test-Plan:** unit (Bands/Warnings-Rendering, Muster `:142–147`), Chart-Snapshot, a11y.

### #68 Cashflow-Editor (`page-cf`, Cashflow-Teil)
- **Schema:** `Cashflow`, `CashflowCreate/Update` (`wealth.py:571/590/641/619`); `cashflows-derived` (`clients.py:315`) **read-only** + `cashflow-projection` (`:397`).
- **React:** `sections/cashflow/` — editierbare Cashflows + abgeleitete Posten read-only markiert. `api/cashflow.ts`.
- **Wiring/Drift:** nach #64 (gleiche `page-cf`), `cf-row[data-cfid]`-Bindings + valid_until-INKLUSIV-Konvention beachten (Memory `project_5eyes_cashflow_konventionen`).
- **Test-Plan:** unit (Verzehr/Horizont-Logik read-only), a11y, derived-vs-editable-Trennung.

### #65 Mandate-Edit
- **Schema:** `Mandate`, `MandateCreate/Update` (`mandates.py:24/36/81/90`).
- **React:** `sections/mandate/` — Feld-reiche Form mit TS-Validierung. `api/mandate.ts`.
- **Wiring/Drift:** Mandate-Modal/Container im Monolith; neuer Drift-Test (kein vorhandener spezifischer) — `test_frontend_mandate_edit_contracts.py` anlegen.

### #66 CRM/Stammdaten (`page-sd`)
- **Schema:** `Client`, `ClientCreate/Update`, `Nationality`, Summaries (`clients.py:104/113/138/154/244/267`).
- **React:** `sections/crm/` — Suche/Filter/Tabelle + Stammdaten-Form. `api/crm.ts`.
- **Wiring/Drift:** `page-sd` = Workflow-Eintritt; neuer `test_frontend_crm_contracts.py`. Hohe Vorsicht: koppelt an `go('sd')`-Navigation (App-Shell).

### #69 App-Shell (Track 3)
- **Ziel:** `go(p,b)`-Router (`:5357`), Tab-Nav (`:1935–1947`, `pages={sd:0,...}`), Auth-Bootstrap und globale Modals nach React verlagern. `5eyes_v2.html` schrumpft zur Bootstrap-Shell (nur React-Root + Token-Handoff).
- **React:** Top-Level-Router/Shell in `reporting/src/App.tsx` (Workflow-Routen statt nur Report-Routen); ggf. eigenes `AppShell`-Layout mit der 7-Step-Nav als React-Komponente (Single-Source analog `REPORT_SECTIONS`).
- **Wiring/Drift:** `test_frontend_navigation_contracts.py` (`go()`-Targets, `pages={…}`-String) wird hier final umgeschrieben/abgelöst. **Cutover-PR**, nur wenn #63–#68 gemerged + stabil.
- **OWNER-DECISION C (§8):** Shell-Cutover als Big-Bang-Shell-Swap oder weiter inkrementell pro Tab?

---

## 4. React-Komponenten-Struktur (Blaupause = reporting-Sub-App)

Jeder Track-Ordner `sections/<track>/` spiegelt das Reporting-Muster:
```
sections/<track>/
  <Track>Page.tsx        # Container: lädt via api/<track>.ts, rendert Form/Liste
  <Track>Form.tsx        # Edit-Felder (Muster NotesEditForms.tsx)
  <track>.test.tsx       # unit + Render
  <track>.a11y.test.tsx  # a11y-Pattern (Muster App.a11y.test.tsx)
api/<track>.ts           # fetch + mutate, ApiError/SchemaError, resolveAuthToken
```
Geteilt/wiederverwendet (NICHT neu bauen): `components/EditButton`,
`SectionEditWrapper`, `ErrorBoundary`, `BarChartIstSoll`, `lib/format`,
`lib/goalClassification`, `lib/sortGoals`, `design/tokens`, `api/client`.

---

## 5. Wiring-Strategie

**Primär A1 (Tab + Token-Handoff, #63–#68):** Monolith-Button ruft das
bestehende `openReportingApp`-Muster (`5eyes_v2.html:11037`) mit Track-Pfad auf.
Vorteile: null Layout-Eingriff, Token-Handoff + Auth schon getestet, jeder
Wiring-PR ändert nur 1 Button + 1 Route.

**Mount-Point (A2, optional je Track / Pflicht in #69):** HTML-Section
`<div id="page-<x>">` bekommt zusätzlich `<div id="root-<track>">`; ein
JS-Bootstrap-Block montiert die React-Komponente (ADR-008 `:80–86`). Höheres
CSS-/Drift-Risiko → erst wenn A1-Pattern reif und Berater nahtlosen In-Place-
Edit verlangt.

**Cutover je Track:** alter Inline-JS-Pfad bleibt als Fallback bis der React-
Pfad einen Sprint produktiv lief; dann Inline-Block entfernen (eigener
Cleanup-PR, Drift-Test zieht die entfernten Strings nach).

---

## 6. Drift-Test-Anpassung (Pflicht je PR)

Drift-Tests sind HTML-String-Assertions auf `5eyes_v2.html`. Regel:

1. **Wiring-PR ändert HTML** → der zu diesem Bereich gehörende
   `test_frontend_*_contracts.py` **MUSS im gleichen PR** angepasst werden,
   sonst rot. Mapping Track→Test:
   - #63 → `test_frontend_risk_questionnaire_contracts.py`
   - #64/#68 → `test_frontend_cashflow_goal_workspace_contracts.py`, `test_frontend_goal_cashflow_ist_contracts.py`
   - #67 → Allocation-Asserts in `test_frontend_risk_questionnaire_contracts.py:52–83`
   - #69 → `test_frontend_navigation_contracts.py`
   - #65/#66 → NEU anlegen (`test_frontend_mandate_edit_contracts.py`, `test_frontend_crm_contracts.py`)
2. **Inventory-Snapshot** nach jedem Wiring neu erzeugen (`python scripts/audit_html_monolith.py`) und den geänderten `docs/audits/…-monolith-inventory.json` (inkl. neuem `source_sha256`) mit committen — dient als Audit-Trail welche ids/JS-Funktionen verschwunden/dazugekommen sind.
3. **Neue React-Seite** bekommt eine `vitest`-Suite, die das React-Pendant gegen die gleichen Fixtures prüft, die das Backend-`test_*`-Pendant nutzt → so bleibt das TS-Schema ↔ Pydantic synchron.

---

## 7. Risiken

- **Shared `5eyes_v2.html` (Codex-Koordination):** Alle 7 Tracks fassen dieselbe
  Datei an. Risiko von Merge-Konflikten/„landet auf falschem Branch" (Memory
  `feedback_branch_check_before_commit`). Mitigation: strikt seriell mergen
  (ein Track komplett vor Start des nächsten), je Track eigener Branch
  `codex/u<nr>-<track>`, vor jedem Commit `git branch --show-current`.
- **Drift-Test-False-Positives:** String-Asserts sind brüchig; jede HTML-
  Änderung kann unbeteiligte Tests brechen. Mitigation: Wiring minimal halten
  (1 Button/Mount-Point pro PR), Tests im selben PR ziehen.
- **Auth/Token im Tab-Flow:** Token nur via Fragment, sessionStorage-abhängig
  (`handoff.ts:69–76` fail-soft). Bei restriktiven Browsern 401 — in Electron
  unkritisch (window.desktop).
- **Schema-Drift TS↔Pydantic:** kein Codegen — manuelles Nachziehen. Mitigation:
  `validateSchemaV2`-Muster pro Endpoint + Fixture-Spiegelung.
- **`page-cf` doppelt (#64+#68):** zwei Tracks, eine Sektion → Reihenfolge
  #64→#68 zwingend, sonst doppeltes Wiring/Konflikt.
- **App-Shell (#69) Big-Bang-Gefahr:** Shell-Cutover ist inhärent invasiv;
  Risiko, die ADR-008-„kein Big-Bang"-Regel zu verletzen. Mitigation: pro Tab
  inkrementell, Shell zuletzt.
- **Dateigröße:** `5eyes_v2.html` ist ~24'700 Zeilen (nicht 17'300 wie im
  Auftrag angenommen) → Reviews der Wiring-Diffs müssen kleinräumig bleiben.
- **Branding (Memory `feedback_5eyes_branding`):** keine Dritt-Marken in neuen
  React-Komponenten/Texten.

---

## 8. OWNER-DECISIONs (vor Codex-Start zu klären)

- **A — Integrations-Pattern:** A1 (neuer Tab, wie heute) oder A2 (In-Place-
  Mount/iframe)? *Spec-Empfehlung: A1 für #63–#68, A2/Shell erst #69.*
- **B — Reihenfolge:** Spec-Reihenfolge (#63→#64→#67→#68→#65→#66→#69) ok, oder
  strikt ADR-008 (#63→#64→#65→#66→#67→#68→#69)? *Empfehlung: Spec-Reihenfolge.*
- **C — #69 App-Shell-Cutover:** inkrementell pro Tab oder Shell-Big-Bang? *Empfehlung: inkrementell.*
- **D — Mono-Repo vs. neue Sub-App:** Editor-Workflows in die bestehende
  `reporting`-App (eine Vite-App, additive Routen) oder eigene Vite-App
  `frontend/advisory/`? *Empfehlung: bestehende `reporting`-App erweitern —
  teilt Auth/Tokens/Design-Tokens/Tests, geringster Overhead.*
- **E — Tempo:** seriell (1 Track/PR, mergen vor nächstem) bestätigt? *Empfehlung: ja (Shared-File-Risiko).*

---

## 9. Erster konkreter Codex-Auftrag: Track #63 Profiling (Schema-First-Schritt)

Branch `codex/u63-profiling-react`. Scope NUR Schritt 1+2 (Schema + React-Page +
Tests), **noch KEIN Wiring in `5eyes_v2.html`** (separater PR, nachdem Page
reviewt ist). Siehe kopierbarer Prompt-Block in der Rückgabe.

---

## 10. Referenzen
- `docs/adr/ADR-008-html-monolith-migration.md`
- `docs/planning/2026-06-14-roadmap-master.md` (Punkte 63–93)
- `5eyes-electron/frontend/reporting/` (React-Blaupause)
- `5eyes-electron/frontend/5eyes_v2.html` (Monolith)
- `5eyes-backend/routers/{profiling,wealth,mandates,clients,allocation}.py` (API-Verträge)
- `5eyes-backend/tests/test_frontend_*_contracts.py` (Drift-Tests)
- `scripts/audit_html_monolith.py` + `docs/audits/2026-06-02-monolith-inventory.json` (Inventory)
