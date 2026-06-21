# Spec: QA/CI/OPS-Härtungs-Cluster (#79, #80, #81, #83, #84, #85, #86)

## Meta

- Titel: QA/CI/OPS-Härtung — E2E, EXE-Build-CI, Visual-Regression, Performance-Budget, Concurrency, Lint-Gate, Mutations-Test
- Datum: 2026-06-21
- Owner: Emanuele (ekonzelmann@bluewin.ch)
- Issues: Roadmap #79, #80, #81, #83, #84, #85, #86 (docs/planning/2026-06-18-roadmap-200-detailliert.md)
- Branch-Vorschlag: `codex/u79-e2e-playwright` (Start-Cluster), Folge-Branches je Punkt (siehe Reihenfolge)

---

## Ziel

Den Release-Stand mit einem belastbaren QA-/CI-/OPS-Sicherheitsnetz absichern: durchgehende
E2E-Verifikation der Hauptapp (Login→Strategie→Charts→PDF), ein in CI gebauter und smoke-getesteter
Electron-EXE-Artefakt, Screenshot-basierte Visual-Regression der SOLL/IST-Charts, ein hartes
Performance-Budget (Wall-Time + SELECT-Count) für Aggregator/Engine, Last-/Concurrency-Tests mit
Cross-Tenant-Leak-Wache, ein Lint-Gate (ruff/black/mypy) und Mutations-Tests der Risiko-/Cashflow-Formeln.
Alle Gates laufen automatisiert in GitHub Actions und sind lokal reproduzierbar (Single-Source-of-Truth
nach Vorbild `scripts/security_gate.py`).

## Problem

Heute ist die CI stark, aber lückenhaft:

- Es gibt **keine echte UI-E2E** (Renderer/Electron). Die "E2E"-Datei
  `5eyes-backend/tests/test_e2e_full_pipeline_smoke.py:1` ist ein **API-Pipeline-Smoke über `TestClient`**
  (`test_e2e_full_pipeline_smoke.py:77` `with TestClient(app)`), kein Browser-/Electron-E2E. Login, Charts,
  PDF-Download durch die echte UI sind ungetestet.
- Der **EXE-Build läuft nie in CI**. `package.json:14` (`dist:win`) und
  `5eyes-electron/scripts/build-backend.js:189` (PyInstaller) werden nur lokal/manuell ausgeführt; ein
  fehlender Hidden-Import (vgl. `build-backend.js:91-110`) bricht erst beim Kunden auf.
- **Visual-Regression** der Charts existiert nicht. Reporting-Sub-App-Tests sind reine JSDOM-Component-Tests
  (`5eyes-electron/frontend/reporting/vitest.config.ts:19` `environment: 'jsdom'`), kein Pixel-Diff.
- **Performance ist nur punktuell budgetiert**: `tests/test_aggregator_n1_baseline.py:309` `BUDGET = 50`
  deckt den SELECT-Count von `compute_advisory_report` ab — aber es gibt **kein Wall-Time-Budget** und keine
  Budget-Wache für die SAA-Engine (`POST /mandates/{id}/target-allocation/generate`,
  `routers/allocation.py:367`).
- **Kein Concurrency-/Last-Test**: Tenant-Isolation wird funktional getestet (`scripts/security_gate.py:24-39`),
  aber nie unter **parallelem Mehr-Tenant-Last** (Race-Conditions, Session-/Cache-Bleed).
- **Kein Lint-Gate**: `.github/workflows/test.yml` hat security-gate, pytest, postgres-rls, vitest — aber
  weder ruff/black/mypy noch eslint/tsc-CI-Gate (tsc läuft nur im vitest-Build implizit via `npm run build`,
  `test.yml:171-173`).
- **Keine Mutations-Tests**: Risiko-Scoring (`services/risk_scoring.py`) und Cashflow-Formeln
  (`services/cashflow_timeline.py`) haben Unit-Tests, aber deren Aussagekraft ist unbekannt — ein invertiertes
  `>=` würde evtl. nicht auffallen.

## Scope

- 7 Roadmap-Punkte (#79, #80, #81, #83, #84, #85, #86) als implementierungsfertige Teil-Specs.
- Neue CI-Jobs in `.github/workflows/` (teils neue Workflow-Dateien).
- Neue Test-/Harness-Dateien; neue Gate-Skripte unter `scripts/` (Vorbild `security_gate.py`).
- Konfigurationsdateien (Playwright, ruff/black/mypy, mutmut/cosmic-ray).

## Nicht-Scope

- Refactoring von Produktionscode zur Performance-Verbesserung (Budgets dokumentieren IST + setzen Drift-Wache;
  Optimierungs-Sprints sind separat). **Ausnahme:** echte Bugs, die ein Mutations-Test oder Concurrency-Test
  aufdeckt, werden minimalinvasiv gefixt (Befund→Reproduktion→Minimalfix).
- macOS-/Linux-EXE-Builds in CI (#80 nur Windows-NSIS/portable; mac/linux bleibt manuell).
- Code-Signing in CI (`CSC_LINK`, siehe `5eyes-electron/scripts/release-check.js:101`) — bleibt manueller
  Release-Schritt.

## Bestehender CI-Stand (IST, verifiziert)

`.github/workflows/test.yml`:
- `concurrency` cancel-in-progress (`test.yml:17-19`); Trigger push auf `develop`/`main`/`codex/**` + PR (`test.yml:3-12`).
- Job `security-gate` (`test.yml:22-50`): Python 3.12, `pip cache` mit `cache-dependency-path: 5eyes-backend/requirements.txt`, `timeout-minutes: 10`, ruft `python scripts/security_gate.py` (`test.yml:50`).
- Job `pytest` (`test.yml:52-103`): Python 3.12 matrix, `timeout-minutes: 30`, `pytest tests/ ... --maxfail=5 --cov=...` (`test.yml:85-87`), Coverage-Artefakt (`test.yml:89-95`).
- Job `postgres-rls` (`test.yml:105-145`): postgres:16 service, `timeout-minutes: 12`, `POSTGRES_TEST_DATABASE_URL` env (`test.yml:144`).
- Job `vitest` (`test.yml:147-185`): Node 20, `npm cache` mit `cache-dependency-path: 5eyes-electron/frontend/reporting/package-lock.json` (`test.yml:165`), `npm ci` → `npm run build` → `npx vitest run` (`test.yml:169-177`).

`.github/workflows/market_data_smoketest.yml`: separater Workflow (schedule + path-filtered PR + workflow_dispatch), Python 3.11, Vorbild für **opt-in/scheduled**-Jobs und `--no-network`-Flag (`market_data_smoketest.yml:48-65`).

Gate-Vorbild `scripts/security_gate.py`:
- Liste `SECURITY_TESTS` (`security_gate.py:24-51`), harte Fehlermeldung bei fehlenden Pfaden (`security_gate.py:107-112`), `--list`-Maschinenmodus (`security_gate.py:114-117`), `pytest ... --maxfail=1 -q` (`security_gate.py:119-126`), zusätzlicher Smoke-Subprozess (`security_gate.py:88-99`). **Dieses Muster wird für #83/#85/#86-Gates kopiert.**

Engine-/Aggregator-Entry-Points (verifiziert):
- Aggregator: `services/advisory_report.py:184` `compute_advisory_report(db, mandate, *, advisor=None) -> dict`
  (SYNC; call-scoped Cache ab `advisory_report.py:217`), aufgerufen in `tests/test_aggregator_n1_baseline.py:316`;
  Endpoint `GET /mandates/{id}/advisory-report` (`routers/allocation.py:466`, ruft `cached_compute_advisory_report`).
- SAA-Engine: `services/portfolio_engine.py` (pure Helper ab `portfolio_engine.py:77`); öffentlicher Entry
  `generate_target_allocation` (Import `routers/allocation.py:31`); Endpoint
  `POST /mandates/{id}/target-allocation/generate` (`routers/allocation.py:367`, ruft
  `generate_target_allocation(db, mandate, user_id, preferences)` `routers/allocation.py:377`). Alles SYNC
  (Thread-Pool-Concurrency-Modell — relevant für #84).
- PDF: PyInstaller-Hidden-Imports listen die Dokumente (`build-backend.js:91-110`); Render via
  `services/pdf/documents/advisory_report.py`.
- DB/Session/Tenant: `database.py::engine` (`database.py:135`), `SessionLocal` (`database.py:136`),
  `get_db` mit Tenant-Reset (`database.py:143-153`), SQLite-PRAGMA WAL+busy_timeout (`database.py:104-107`),
  Tenant-Context-Funktionen `set_tenant_context(session, tenant_id)` (`services/tenant_context.py:62`,
  Postgres-GUC `app.tenant_id` für RLS / SQLite `session.info["tenant_id"]`) und `reset_tenant_context`
  (`services/tenant_context.py:79`), eingehängt in `get_db` (`database.py:149`).
- SELECT-Counter-Muster: `tests/test_aggregator_n1_baseline.py:69-105` (`_QueryCounter` via
  SQLAlchemy `before_cursor_execute`-Event auf `Engine`).
- Pure Formel-Module für #86: `services/risk_scoring.py` (`compute_scores` `risk_scoring.py:161`,
  `map_surplus_points` `risk_scoring.py:99`, `_profile_from_score` `risk_scoring.py:116`,
  `_capacity_profile` `risk_scoring.py:125`, `_willingness_profile` `risk_scoring.py:132`) +
  `services/cashflow_timeline.py` (`contribution_for_year` `cashflow_timeline.py:92`,
  `totals_for_year` `cashflow_timeline.py:225`, `future_value_with_cashflow_series`
  `cashflow_timeline.py:361`, `_compound_inflation_factor` `cashflow_timeline.py:165`). Bestehende Tests:
  `tests/test_risk_scoring.py`, `tests/test_cashflow_timeline.py`, `tests/test_cashflow_annualization_properties.py`.

---

## Priorisierte Reihenfolge (was zuerst)

Begründung: erst das billigste/hochwertigste Netz, dann die teuren Browser-/Build-Jobs.

1. **#85 CI-Lint-Gate** — billigster Job, sofortiger Nutzen, blockiert nichts inhaltlich; etabliert das
   Pattern für die anderen Gates. (`codex/u85-lint-gate`)
2. **#83 Performance-Budget** — baut direkt auf existierendem `_QueryCounter`/`BUDGET=50` auf; reine
   Python-Tests, kein neuer Runner. (`codex/u83-perf-budget`)
3. **#86 Mutations-Test** — reine Python, opt-in/nightly; deckt Test-Lücken in Kern-Formeln auf.
   (`codex/u86-mutation-formulas`)
4. **#84 Concurrency/Multi-Tenant** — Python-Threads/httpx, nutzt vorhandene Tenant-Fixtures;
   sicherheitsrelevant (oberste Maxime Mandanten-Trennung). (`codex/u84-concurrency-tenant`)
5. **#79 Playwright/E2E Hauptapp** — neuer Browser-Runner; größter Aufwand, aber Voraussetzung für #81.
   **Start-Cluster: `codex/u79-e2e-playwright`.**
6. **#81 Visual-Regression** — baut auf der Playwright-Infrastruktur aus #79 auf. (`codex/u81-visual-regression`)
7. **#80 EXE-Build-CI** — teuerster/langsamster Job (PyInstaller + electron-builder), zuletzt; profitiert
   davon, dass #79 den Smoke-Pfad bereits definiert. (`codex/u80-exe-build-ci`)

> Hinweis: #79 ist der namensgebende Start-Branch laut Auftrag; die Punkte 1-4 sind aber unabhängig und
> sollen parallel zu #79 als eigene kleine PRs laufen, da sie die CI sofort härten ohne den Browser-Runner.

---

## #85 — CI-Lint-Gate (ruff/black/mypy + eslint/tsc)

### Ziel
Statische Qualität als hartes Gate, **schrittweise** scharf gestellt, damit nicht 3000+ Bestandsfehler den
ersten PR blockieren.

### IST
- Kein ruff/black/mypy in CI (`.github/workflows/test.yml` enthält keine Lint-Schritte).
- Kein Lint-Config: kein `ruff.toml`/`.ruff.toml`, kein `[tool.ruff]`/`[tool.black]`/`[tool.mypy]` (keine
  `pyproject.toml`/`setup.cfg`/`pytest.ini` im Backend-Root; einzige `conftest.py`-Treffer liegen unter
  `.venv/`). → **OWNER-DECISION-relevant: Config muss neu erstellt werden.**
- TS: `tsc --noEmit` läuft nur implizit im `npm run build` (`reporting/package.json:9`); eslint fehlt.

### SOLL
**Tool-Wahl:** ruff (lint + format-check, ersetzt black-Funktion via `ruff format --check`; black optional
zusätzlich), mypy (Python). Für TS: bestehendes `tsc --noEmit` als eigener Gate-Step; eslint **optional**
(OWNER-DECISION).

**Neue Dateien:**
- `5eyes-backend/pyproject.toml` mit `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`, `[tool.mypy]`.
- `scripts/lint_gate.py` (Vorbild `security_gate.py`): ruft `ruff check`, `ruff format --check`, `mypy`
  gegen definierte Pfade; `--list`/`--fix`-Flags; harte Exit-Codes. Single-Source-of-Truth für CI + lokal.
- requirements: ruff, mypy in `5eyes-backend/requirements.txt` ergänzen (Test-/Dev-Sektion).

**Neuer CI-Job** in `test.yml` (nach Vorbild `security-gate` `test.yml:22-50`):
```yaml
  lint-gate:
    name: Lint Gate (ruff/format/mypy)
    runs-on: ubuntu-latest
    timeout-minutes: 8
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with: { python-version: '3.12', cache: pip, cache-dependency-path: 5eyes-backend/requirements.txt }
      - run: python -m pip install --upgrade pip && pip install -r 5eyes-backend/requirements.txt
      - run: python scripts/lint_gate.py
```
TS-Lint als Schritt im bestehenden `vitest`-Job ergänzen (vor `npm run build`):
`- run: npx tsc --noEmit` (working-directory `5eyes-electron/frontend/reporting`).

### Schwellenwerte / Strenge (schrittweise — OWNER-DECISION)
- **Stufe 0 (Start, dieser PR):** ruff nur mit "sicheren" Regelgruppen `E,F,I` (pyflakes, Import-Sort,
  kritische Syntax) + `ruff format --check`. mypy im Modus `--ignore-missing-imports` und **nur** auf einem
  kuratierten Kernpfad-Set (z.B. `services/risk_scoring.py`, `services/cashflow_timeline.py`,
  `services/portfolio_engine.py`, `services/advisory_report.py`). Rest via `[tool.mypy] exclude`.
- **Stufe 1 (Folge-PR):** Regelgruppen erweitern (`B`, `UP`, `SIM`); mypy-Pfad-Set vergrößern.
- **Stufe 2:** mypy strict auf Kernmodule, ganze `services/` unter ruff.
- Bestehende Verstöße: entweder Stufe-0-Scope eng halten, oder einmalig `ruff check --fix` + `ruff format`
  als separater "Format-Bestand"-Commit (OWNER-DECISION: großer Diff akzeptabel?).

### Edge-Cases
- Line-Endings: Repo hat `.gitattributes`; `ruff format` muss mit CRLF/LF konsistent sein → in pyproject
  `line-ending = "lf"` setzen, sonst CI-Diff auf Windows-committeten Dateien.
- `.venv/` und `node_modules/` zwingend aus ruff/mypy excluden.
- Generierte/`tmp_*`-Dateien im Root (z.B. `tmp_*.js`, `.tmp_*.js`) nicht linten.

---

## #83 — Performance-Budget Aggregator/Engine (Wall-Time + SELECT-Budget)

### Ziel
Harte Drift-Wache für (a) SELECT-Count und (b) Laufzeit von `compute_advisory_report` UND der SAA-Engine.

### IST
- SELECT-Budget existiert nur für den Aggregator: `tests/test_aggregator_n1_baseline.py:309` `BUDGET = 50`,
  per-Table-Asserts `test_aggregator_n1_baseline.py:330-367`. Counter-Muster `_QueryCounter`
  (`test_aggregator_n1_baseline.py:69-105`).
- **Kein Wall-Time-Budget** irgendwo. Kein Budget für die SAA-Engine
  (`POST .../target-allocation/generate`, `routers/allocation.py:367`).

### SOLL
**Tool-Wahl:** reines `pytest` + `time.perf_counter()` (deterministisch, kein neuer Runner). **Keine**
`pytest-benchmark`-Pflicht (CI-Runner-Varianz zu hoch für harte ms-Grenzen → großzügige Obergrenzen, siehe
Schwellen). SELECT-Count via Wiederverwendung des `_QueryCounter` (in `tests/_perf_helpers.py` extrahieren,
damit #83 und der bestehende N1-Test dieselbe Quelle nutzen — **kein Editieren** des bestehenden Tests
nötig, neuer Helper importiert nur).

**Neue Dateien:**
- `5eyes-backend/tests/_perf_helpers.py`: kopiert/extrahiert `QueryCounter` + `seed_realistic_mandate`
  (Seed-Logik aus `test_aggregator_n1_baseline.py:125-288` als wiederverwendbare Fixture-Factory; **neue**
  Datei, kein Edit).
- `5eyes-backend/tests/test_perf_budget_aggregator.py`: Wall-Time + SELECT-Budget für `compute_advisory_report`.
- `5eyes-backend/tests/test_perf_budget_engine.py`: Wall-Time + SELECT-Budget für den SAA-Generate-Pfad
  (über `TestClient` `POST .../target-allocation/generate`, Muster aus
  `test_e2e_full_pipeline_smoke.py:70-99`).
- `scripts/perf_gate.py` (Vorbild `security_gate.py`): führt nur die beiden Perf-Tests aus, `--maxfail=1`.

**Neuer CI-Job** `perf-budget` in `test.yml` (Python 3.12, `timeout-minutes: 12`, ruft `python scripts/perf_gate.py`).
Läuft als eigener Job (nicht im Haupt-pytest), damit Timing-Flake nicht den Coverage-Lauf rot macht.

### Schwellenwerte (konkret, CI-Runner-tauglich, großzügig)
- **SELECT-Aggregator:** `<= 50` (identisch zur bestehenden Baseline `test_aggregator_n1_baseline.py:309`;
  per-Table-Asserts übernehmen).
- **SELECT-Engine (generate):** Baseline beim ersten Lauf **messen und als Konstante einfrieren** (Codex:
  Wert ins Test-Docstring + Assert schreiben), Obergrenze = `gemessen + 30%` aufgerundet auf nächste 10er.
- **Wall-Time-Aggregator:** `compute_advisory_report` über das #83-Seed-Mandat: **< 2.0 s** (lokal i.d.R.
  < 200 ms; 10× Headroom für CI-Runner). Median aus 3 Läufen, härtester Run zählt.
- **Wall-Time-Engine (generate, house-matrix-Modus, OPTIMIZER_MODE unset):** **< 5.0 s**.
  *(Stochastischer Optimizer OPTIMIZER_MODE=stochastic ist NICHT im Budget — separater, nightly-Pfad.)*
- Alle Zeit-Asserts mit `pytest.mark` `perf` markieren; Umgebungsvariable `PERF_BUDGET_STRICT=1` schaltet
  die ms-Asserts scharf, sonst nur Warn-Print (lokal flake-frei).

### Edge-Cases
- Erster `compute()`-Aufruf hat Import-/Mapper-Cold-Start → vor der Messung einen Warmup-Call (verworfen).
- SQLite-`tmp_path`-DB ist schneller als echte → Budget bewusst großzügig; Ziel ist **Drift-Erkennung**, nicht
  Absolut-Performance.
- `OPTIMIZER_MODE`-Env muss im Test explizit auf house-matrix/unset gepinnt werden (sonst misst man den Solver).

---

## #86 — Mutations-Test der Risiko-/Cashflow-Formeln

### Ziel
Aussagekraft der bestehenden Unit-Tests für die wertkritischen Formeln messen: ein mutierter Operator
(`>=`→`>`, `+`→`-`, Konstanten-Tweak) MUSS von mindestens einem Test gekillt werden.

### IST
- Pure Formel-Module mit Tests vorhanden (siehe Entry-Points oben). Keine Mutations-Tooling-Konfiguration im Repo.

### SOLL
**Tool-Wahl:** `mutmut` (einfachste Integration, file-basiert). Alternativ `cosmic-ray` (mächtiger, mehr
Setup). **OWNER-DECISION:** mutmut als Default empfohlen.

**Ziel-Module (eng, hochwertig):**
- `services/risk_scoring.py` (Scoring → Risikoprofil; FINMA-relevant, vgl. Memory "Risikoprofil FINMA-konform").
- `services/cashflow_timeline.py` (Verzehr/Beitrag/Inflation; vgl. Memory "Cashflow-Konventionen").
- *(Optional Stufe 2):* ausgewählte pure Helper aus `services/portfolio_engine.py`
  (`_renditeziel_equity_tilt_bps`, `_reserve_decay_factor` `portfolio_engine.py:85`,
  `_time_bucket_reserve_factor` `portfolio_engine.py:138`, `_risk_score_bucket` `portfolio_engine.py:592`).

**Neue Dateien:**
- `5eyes-backend/mutmut_config.py` ODER `[tool.mutmut]` in `pyproject.toml`: `paths_to_mutate` = die 2 Kernmodule;
  `tests_dir = tests/`; Runner = die zugehörigen Tests (`test_risk_scoring.py`, `test_cashflow_timeline.py`,
  `test_cashflow_annualization_properties.py`) für schnelle Iteration.
- `scripts/mutation_gate.py`: führt mutmut auf den Ziel-Modulen aus, parsed das Ergebnis, vergleicht
  Kill-Rate gegen Schwelle, Exit-Code entsprechend. (Vorbild `security_gate.py`-Struktur.)
- requirements: `mutmut` ergänzen (Dev-Sektion).

**Neuer Workflow** `.github/workflows/mutation_test.yml` (Vorbild `market_data_smoketest.yml`):
**nicht** im PR-Pflichtlauf (zu langsam/instabil), sondern `schedule` (z.B. wöchentlich) +
`workflow_dispatch`. Artefakt = Mutations-Report (Vorbild `market_data_smoketest.yml:67-73`).

### Schwellenwerte (OWNER-DECISION)
- **Start-Schwelle Kill-Rate >= 80%** der generierten Mutanten je Ziel-Modul (überlebende Mutanten als
  Report-Artefakt; Build gelb statt rot bei 70-80%, rot < 70% — konfigurierbar via Env).
- Bekannte unkillbare "Equivalent Mutants" (z.B. Log-Strings, Defensive-Branches) in einer
  Allowlist-Datei `tests/mutation_allowlist.txt` pflegen (Codex: erste Liste nach Erstlauf).

### Edge-Cases
- mutmut braucht einen **schnellen** Test-Subset, sonst Laufzeit explodiert → Runner auf die 2-3 zugehörigen
  Test-Dateien einschränken, nicht ganze Suite.
- Timing-Mutanten in `_compound_inflation_factor` (`cashflow_timeline.py:165`) → sicherstellen, dass es
  einen Test mit ≥2 Jahren Inflation gibt (sonst überlebt ein `**`→`*`).
- Nicht-deterministische Module (Monte-Carlo/Optimizer) sind **ausgeschlossen** (kein stabiler Mutations-Kill).

---

## #84 — Last-/Concurrency-Test Multi-Tenant

### Ziel
Unter **parallelem** Mehr-Tenant-Zugriff: keine Cross-Tenant-Leaks, keine Session-/Cache-Bleed, keine
Race-induzierten 500er. Ergänzt die funktionale Isolation (`security_gate.py:24-39`) um die **Nebenläufigkeit**.

### IST
- Funktionale Isolation getestet (security-gate), Postgres-RLS adversarial (`test.yml:105-145`).
- Aggregator-Call-Cache ist call-scoped und wird zwischen Aufrufen geleert
  (`test_aggregator_n1_baseline.py:420-459` belegt Isolation **single-threaded**) — aber nie unter Threads.
- `get_db` setzt Tenant-Context pro Request und resettet im `finally` (`database.py:143-153`); SQLite läuft
  mit WAL + `busy_timeout=5000` (`database.py:105-106`), `check_same_thread: False` (`database.py:92`).

### SOLL
**Tool-Wahl:** **pytest + `concurrent.futures.ThreadPoolExecutor` + FastAPI `TestClient`** (in-process,
deterministisch, CI-tauglich, keine echte Netzwerk-Last). **Locust** als optionaler manueller Last-Generator
(workflow_dispatch, nicht PR-Pflicht) — OWNER-DECISION ob nötig; für die Leak-Wache reicht ThreadPool.

**Test-Strategie (neue Datei `5eyes-backend/tests/test_concurrency_tenant_isolation.py`):**
1. Seed N=3 Tenants, je 1 Advisor + 1 Client + 1 Mandat mit eindeutigen Marker-Werten (Client-Name =
   Tenant-Slug), Muster wie `test_e2e_full_pipeline_smoke.py:82-99` aber pro Tenant.
2. `app.dependency_overrides[get_db]`/`get_current_user` so setzen, dass der **per-Request-Tenant** aus einem
   Header/Override variiert (jeder Thread = anderer Tenant-User).
3. `ThreadPoolExecutor(max_workers=CONCURRENCY)` feuert `CONCURRENCY * ROUNDS` parallele Requests gegen
   `GET /mandates/{id}/advisory-report` und gegen Listen-Endpoints quer über alle Tenants.
4. **Assert:** jede Response enthält ausschließlich den Marker des eigenen Tenants; **kein** fremder
   Slug/Client-Name taucht je auf. Zähle 0 Cross-Leaks, 0 unerwartete 5xx.
5. Race-Spezifisch: parallele `compute_advisory_report` auf demselben Tenant aus mehreren Threads → Ergebnis
   identisch (Cache-Bleed-Wache; ergänzt `test_aggregator_n1_baseline.py:420` um Threading).

**Neuer CI-Job** `concurrency-tenant` in `test.yml` (Python 3.12, `timeout-minutes: 12`). Optional zusätzlich
gegen Postgres-Service (Wiederverwendung des `services: postgres` Blocks aus `test.yml:110-122`), damit die
echte RLS unter Last mitgetestet wird — **empfohlen**, da SQLite-in-memory Race-Verhalten von Postgres abweicht.

### Schwellenwerte / Concurrency-Grad (konkret)
- **CONCURRENCY = 16** parallele Threads, **ROUNDS = 10** → 160 Requests/Endpoint-Set pro Test. (CI-stabil;
  lokal via Env `CONCURRENCY` hochdrehbar für Stress.)
- **Cross-Tenant-Leaks: == 0** (hart, jede Verletzung = sofort rot, `--maxfail=1`).
- **5xx-Rate: == 0** unter Last (ein einziger 500 = Fail; Race-Bug).
- **p95-Latenz** nur informativ geloggt, **kein** hartes Latenz-Gate hier (Latenz-Budget ist #83).
- SQLite-Variante: `busy_timeout` (`database.py:106`) muss ausreichen; falls `database is locked` auftritt →
  **Befund dokumentieren** (echter OPS-Bug unter Last), nicht wegmocken.

### Edge-Cases
- `expire_on_commit=False` (`database.py:136`) → detached-Objekt-Bleed zwischen Threads möglich; Test muss
  pro Thread eine eigene Session bekommen (Override liefert frische `SessionLocal()`).
- Tenant-Context ist potenziell thread-/connection-lokal — sicherstellen, dass `set_tenant`/`reset`
  (`database.py:149`) pro Request greift und nicht über Threads leakt.
- Postgres-Connection-Pool-Größe vs. CONCURRENCY=16: Pool ggf. erhöhen oder CONCURRENCY an Pool anpassen.

---

## #79 — Playwright/E2E Hauptapp (Login→Strategie→Charts→PDF, headless, CI)

### Ziel
Echte UI-E2E der Hauptapp durch den Browser: Login → Strategie/Charts darstellen → Advisory-Report → PDF.
Headless in CI.

### IST
- Keine UI-E2E. Hauptapp-Renderer = `5eyes-electron/frontend/5eyes_v2.html` (geladen via
  `main.js:236-237`/`main.js:502`). Reporting-Sub-App separat (React, `reporting/`).
- **Foundation/ADR existiert bereits:** `docs/E2E_TESTING.md` (Sprint U-55) entscheidet **Playwright über
  Cypress** und skizziert 5 Smoke-Tests (Sub-App Boot, Sidebar-Click, Token-Reject, Client-Portal) + den
  Workflow-Namen `.github/workflows/e2e.yml`. → **#79 MUSS diesen Workflow-Namen verwenden** (sonst bricht
  `tests/test_e2e_foundation.py:48-50`).
- **DRIFT-GUARD-KONFLIKT (kritisch für Codex):** `tests/test_e2e_foundation.py:32-36` (`test_playwright_not_in_package_json`)
  asserted heute, dass `@playwright/test`/`playwright` NICHT in der `reporting/package.json` stehen. Sobald
  Playwright eingeführt wird, ist diese Assertion zu **invertieren/anzupassen** (Foundation→Implemented). Da
  die Regel "keine bestehenden Dateien editieren" für diese Spec gilt, ist das ein expliziter Codex-Schritt im
  #79-Branch: Foundation-Guard auf den neuen Zustand umstellen. Playwright kommt in eine **eigene**
  `e2e/package.json` (nicht in `reporting/package.json`) — dann bleibt `test_playwright_not_in_package_json`
  sogar grün, weil es nur die reporting-package prüft. **Empfehlung: Playwright in `e2e/package.json` halten,
  Foundation-Guard unverändert lassen.**
- Backend startet im Dev über `python main.py` (`main.js:380-392`), Health-Probe auf `/health/ready`
  (`main.js:89`), App-Name-Match `5Eyes WealthArchitekten API` (`main.js:50`, `main.js:325`).
- Frontend lädt `file://.../5eyes_v2.html` (`main.js:481`); `will-navigate` ist gesperrt (`main.js:480-488`),
  Permissions default-deny (`main.js:581-583`).

### SOLL
**Tool-Wahl:** **Playwright** (`@playwright/test`). Zwei E2E-Modi (OWNER-DECISION welcher in CI Pflicht):

- **Modus A (empfohlen für CI, robust): Browser-gegen-Backend.**
  - Backend wie in der Smoke-Suite starten: `python 5eyes-backend/main.py` als CI-Background-Service, warten
    auf `GET /health/ready` (Muster `main.js:321-335`).
  - Den Hauptapp-Renderer `5eyes_v2.html` über einen **statischen lokalen HTTP-Server** ausliefern (Playwright
    `webServer`), gegen das laufende Backend (`APP_PORT`).
  - Playwright steuert Chromium headless: Login (Formular), navigiert zu Strategie/Charts, triggert
    Advisory-Report, löst PDF-Download aus, prüft den Download.
- **Modus B (höhere Treue, fragiler): Electron-E2E** via Playwright `_electron.launch({ args: ['.'] })` gegen
  das echte `main.js`. Deckt IPC `file:save-pdf` (`main.js:549-565`) und Backend-Spawn mit ab, ist aber in CI
  zicke (Display, sandbox). → **OWNER-DECISION: Modus A als Pflicht-Gate, Modus B optional/nightly.**

**Neue Struktur (neues Verzeichnis `5eyes-electron/e2e/`):**
- `playwright.config.ts`: `webServer` (statischer Server für `frontend/`), `use: { headless: true }`,
  `projects: [chromium]`, `outputDir`, Trace `on-first-retry`.
- `tests/login_strategy_charts_pdf.spec.ts`: der Haupt-Flow (siehe Akzeptanzkriterien).
- `fixtures/`: Seed-Helper, der über die Backend-API einen Test-Advisor + Mandat + Goals anlegt
  (Muster `test_e2e_full_pipeline_smoke.py:82-99`), damit Charts echte Daten haben.
- `package.json` (neu, in `e2e/`): devDep `@playwright/test`; scripts `test:e2e`, `test:e2e:ci`.

**Test-Auth in CI:** dedizierter Test-User per Seed-Skript/Endpoint; **keine** echten Kundendaten
(FINMA-Hygiene, vgl. `security_gate.py:47-51` Data-Classification). Login real durchspielen (2FA für den
Test-User deaktiviert lassen).

**Neuer Workflow** `.github/workflows/e2e.yml` (eigene Datei, nicht in `test.yml`, da Browser-Setup schwer):
- Node 20 + Python 3.12, `npx playwright install --with-deps chromium`, Backend starten, Playwright laufen.
- `timeout-minutes: 25`. Trigger: PR auf `develop`/`main` + push `codex/**` (analog `test.yml:3-12`).
- Artefakte: Playwright HTML-Report + Traces bei Fail (`if: failure()`, Vorbild `test.yml:97-103`).

### Schwellenwerte / Konfiguration
- `retries: 2` in CI (Browser-Flake), `0` lokal.
- `expect`-Timeout 10 s, Test-Timeout 60 s.
- Backend-Ready-Polling identisch zu `main.js`: bis 60 s auf `/health/ready` (`main.js:51`).

### Edge-Cases
- PDF-Download: in Modus A löst der Browser einen echten Download aus (Playwright `page.waitForEvent('download')`).
  In Electron (Modus B) geht PDF über IPC `file:save-pdf` (`main.js:549`) → anderer Assert-Pfad.
- `file://`-Auslieferung des HTML funktioniert in Playwright-Chromium nur eingeschränkt (CORS/fetch) → daher
  statischer HTTP-Server statt `file://`.
- Intro-Overlay: `5eyes_v2.html` wird mit `?intro=1` geladen (`main.js:502-504`) → Test muss Intro
  wegklicken/überspringen.
- Fonts/Charts lokal eingebettet (`release-check.js:75-89` verbietet externe CDNs) → keine Netzwerk-Abhängigkeit,
  gut für CI.

---

## #81 — Visual-Regression der Charts (Screenshot-Diff)

### Ziel
Pixel-genaue Regressionswache für die SOLL/IST-Chart-Darstellung (Popup) + Kennzahlen-Tabelle.

### IST
- Charts werden in der UI gerendert; Reporting-Sub-App nutzt `recharts` (`reporting/package.json:20`).
  Component-Tests sind JSDOM (`reporting/vitest.config.ts:19`) → **kein Pixel-Rendering**.
- Keine Baseline-Screenshots im Repo.

### SOLL
**Tool-Wahl:** **Playwright Visual Comparisons** (`expect(page).toHaveScreenshot()`) — baut direkt auf der
#79-Infrastruktur auf (deshalb #81 NACH #79). Deterministisches Rendering erzwingen.

**Neue Tests (in `5eyes-electron/e2e/tests/visual/`):**
- `chart_soll_ist_popup.visual.spec.ts`: navigiert (wie #79) zu einem Mandat mit **deterministischem Seed**,
  öffnet das SOLL/IST-Chart-Popup, macht `toHaveScreenshot('soll-ist-popup.png')`.
- `kennzahlen_tabelle.visual.spec.ts`: Screenshot der Kennzahlen-Tabelle.
- Baselines unter `e2e/tests/visual/__screenshots__/` committen (plattform-suffixed; CI = linux).

**Determinismus-Pflicht:**
- Fester Seed-Datensatz (gleiche SOLL/IST-Werte jedes Mal) via Seed-Fixture.
- Animationen aus: recharts `isAnimationActive={false}` für Test, oder Playwright
  `animations: 'disabled'` + `page.addStyleTag` zum Deaktivieren von CSS-Transitions.
- Datum/Zeit pinnen (PDF/Charts zeigen `generated_at`) — fixe Clock oder Maskierung der Zeit-Region via
  `mask:`-Option.
- Schriftarten lokal eingebettet (gegeben, `release-check.js:25-36`) → font-rendering stabil.

**CI:** als zusätzliche Playwright-Projekt-Gruppe im `e2e.yml`-Workflow (#79), eigener Step
`npx playwright test tests/visual`. Bei Diff: Actual+Diff-PNG als Artefakt hochladen.

### Schwellenwerte / Visual-Diff-Toleranz (OWNER-DECISION)
- **`maxDiffPixelRatio: 0.01`** (max 1% abweichende Pixel) als Start; `threshold: 0.2` (Per-Pixel-YIQ-Toleranz,
  Playwright-Default). Begründung: Anti-Aliasing/Font-Hinting variiert minimal selbst bei gleichem OS.
- Strenger (`0.001`) erst, wenn die CI-Renderumgebung als stabil erwiesen ist (OWNER-DECISION).
- Baseline-Update **nur** bewusst via `--update-snapshots` in einem dedizierten Commit (nie automatisch).

### Edge-Cases
- **OS-Render-Drift:** Baselines aus CI (linux) erzeugen, nicht lokal (Windows) — sonst Dauer-Rot. Playwright
  suffixt Screenshots per Plattform; CI-Pflicht-Baseline = `-linux.png`.
- Headless-vs-headed Render-Unterschiede → immer headless in CI und Baseline-Gen.
- Dynamische Inhalte (Zeitstempel, IDs) maskieren, sonst false-positive Diffs.

---

## #80 — End-to-End EXE-Build in CI (Electron-EXE + Smoke)

### Ziel
GitHub Actions baut den Windows-Installer/portable EXE (PyInstaller-Backend + electron-builder) und führt
einen Smoke-Test gegen die gebaute EXE aus.

### IST
- Build-Kette nur lokal: `npm run dist:win` (`package.json:14`) chained `preflight:release`
  (`release-check.js`) → `build:reporting` → `build:backend` (`build-backend.js` PyInstaller `--onefile`,
  `build-backend.js:142-189`) → `electron-builder --win nsis`.
- Erwartetes Backend-Artefakt: `bundle/backend/5eyes-api.exe` (`build-backend.js:196`,
  `release-check.js:65`); Renderer-dist erwartet (`release-check.js:44-61`).
- `release-check.js` warnt/failt bei fehlenden Icons/Fonts/dist (`release-check.js:18-73`); `STRICT_RELEASE=1`
  macht Warnungen zu Fehlern (`release-check.js:6`).
- **Läuft nie in CI** → Hidden-Import-Regressionen (vgl. `build-backend.js:91-110`) brechen erst beim Kunden.

### SOLL
**Tool-Wahl:** GitHub Actions `windows-latest` Runner (zwingend für `--win nsis`/PyInstaller-EXE).

**Neuer Workflow** `.github/workflows/exe_build.yml` (eigene Datei):
- `runs-on: windows-latest`, `timeout-minutes: 45`.
- Setup: Python 3.12 + `pip install -r 5eyes-backend/requirements.txt` + `pyinstaller`; Node 20 +
  `npm ci` in `5eyes-electron` und in `frontend/reporting`.
- Build: `cd 5eyes-electron && npm run dist:win:portable` (portable ist CI-freundlicher als NSIS-Installer;
  NSIS optional). `STRICT_RELEASE` **nicht** auf 1 (Publish-URL ist Platzhalter `release-check.js:94`,
  CSC fehlt `release-check.js:101`) — sonst failt der Preflight aus release-fremden Gründen.
- **Smoke-Test** der gebauten EXE (neues Skript `5eyes-electron/scripts/smoke-exe.js` oder
  `scripts/smoke_exe.py`):
  1. Start `bundle/backend/5eyes-api.exe` (oder die im dist entpackte EXE) mit `APP_PORT` gesetzt.
  2. Poll `GET /health/ready` bis App-Name == `5Eyes WealthArchitekten API` (Muster `main.js:321-335`),
     Timeout 60 s.
  3. Einen Advisory-Report-relevanten Endpoint smoke-callen, der die kritischen Hidden-Imports zieht
     (Vorbild der U-6-Fixes `build-backend.js:96/109`: advisory_report-Pfad) — Ziel: ein vergessener
     Hidden-Import bricht **hier** in CI, nicht beim Kunden.
  4. Backend-Prozess sauber beenden (`taskkill /t /f`, Muster `main.js:405-406`).
- Artefakte: gebaute EXE (`5eyes-electron/dist/5Eyes-*.exe`) + Backend-EXE als build-artifact hochladen
  (Vorbild `test.yml:89-95`).

**Trigger (OWNER-DECISION):** Build ist teuer (PyInstaller ~mehrere Minuten).
- Empfohlen: `push` auf `main` + `workflow_dispatch` + optional `tags` (Release). **Nicht** auf jedem
  `codex/**`-Push (zu teuer). Alternativ path-filtered PR (nur wenn `5eyes-electron/**`,
  `5eyes-backend/requirements.txt`, `build-backend.js` berührt) — Vorbild `market_data_smoketest.yml:11-17`.

### Schwellenwerte
- Build-Job grün = EXE existiert (`release-check.js:65`-Pfad) UND Smoke alle 4 Schritte ok.
- Smoke-Timeout: 60 s Backend-Ready (identisch `main.js:51`).
- Kein Performance-Gate hier.

### Edge-Cases
- `electron-builder` NSIS braucht ggf. Code-Signing-Skip-Flags; `CSC_LINK` unset → unsigniert (Warnung ok,
  `release-check.js:101-103`). **`portable`-Target zuerst**, NSIS-Installer optional.
- PyInstaller `--onefile` (`build-backend.js:144`) entpackt zur Laufzeit in `_MEIPASS` → Schema-Pfad-Auflösung
  `database.py:31-37` muss in der EXE greifen (Smoke deckt das ab).
- Lange Pfade/AV auf Windows-Runner → `windowsHide`/Timeout großzügig.
- `requirements.txt` muss `pyinstaller` enthalten ODER der Workflow installiert es explizit (heute kein
  Hinweis, dass es drin ist → explizit `pip install pyinstaller` im Workflow).

---

## Integration ins bestehende CI (Übersicht)

| Punkt | Wo | Job/Datei | Runner | Trigger | Pflicht-Gate? |
|------|----|-----------|--------|---------|----------------|
| #85 | `test.yml` (+ vitest-Job) | `lint-gate` | ubuntu | PR+push | ja (Stufe 0 mild) |
| #83 | `test.yml` | `perf-budget` | ubuntu | PR+push | ja |
| #86 | neu `mutation_test.yml` | `mutation` | ubuntu | schedule+dispatch | nein (nightly) |
| #84 | `test.yml` (+ postgres-service) | `concurrency-tenant` | ubuntu | PR+push | ja |
| #79 | neu `e2e.yml` | `e2e` | ubuntu | PR+push | ja (Modus A) |
| #81 | `e2e.yml` | `e2e` visual step | ubuntu | PR+push | ja |
| #80 | neu `exe_build.yml` | `exe-build` | windows | main/dispatch/path-PR | nein (nicht pro PR) |

Alle Pflicht-Gates respektieren die bestehende `concurrency`-Gruppe (`test.yml:17-19`) bzw. definieren eine
eigene in den neuen Workflows. Caching identisch zu IST (`pip`/`npm` mit den vorhandenen
`cache-dependency-path`).

---

## Akzeptanzkriterien (Cluster)

1. **#85:** `python scripts/lint_gate.py` läuft lokal + als CI-Job `lint-gate` grün auf dem aktuellen Stand
   (Stufe-0-Scope), und schlägt rot bei einem absichtlich eingefügten ungenutzten Import / Format-Verstoß im Kernpfad.
2. **#83:** `scripts/perf_gate.py` grün; ein künstlich eingefügter N+1-SELECT in einer `_build_*`-Funktion
   überschreitet das Budget und macht den Job rot; Wall-Time-Asserts laufen flake-frei (10 Wiederholungen lokal).
3. **#86:** `scripts/mutation_gate.py` läuft auf `risk_scoring.py` + `cashflow_timeline.py`; Kill-Rate >= 80%
   ODER überlebende Mutanten dokumentiert; ein absichtlich nicht getesteter Pfad senkt die Kill-Rate sichtbar.
4. **#84:** Concurrency-Test mit CONCURRENCY=16/ROUNDS=10 grün; 0 Cross-Tenant-Leaks, 0 5xx; ein künstlich
   eingebauter Tenant-Filter-Bypass macht den Test rot.
5. **#79:** Playwright-E2E (Modus A) durchläuft Login→Strategie/Charts→Advisory-Report→PDF-Download headless
   in CI grün; Trace/Report-Artefakt bei Fail.
6. **#81:** Visual-Tests grün gegen committete linux-Baselines; ein bewusst geänderter Chart-Wert erzeugt
   einen Diff > Toleranz und macht den Test rot.
7. **#80:** `exe_build.yml` baut die portable Windows-EXE; Smoke-Test startet sie, erreicht `/health/ready`,
   callt den advisory-report-Pfad ohne ModuleNotFoundError; EXE als Artefakt.

## Risiken

- **CI-Kosten/-Laufzeit:** #79/#80/#81 sind teuer. Mitigation: #80 nicht pro PR, #86 nightly,
  `concurrency` cancel-in-progress.
- **Flakiness** (Browser, Timing, Pixel). Mitigation: retries, großzügige Budgets, Determinismus-Pflicht,
  PERF_BUDGET_STRICT-Schalter.
- **Großer Format-Diff** durch ruff/black auf Bestand (OWNER-DECISION).
- **Visual-Baselines OS-abhängig** → nur CI-Baselines.

## Offene Fragen an Owner (OWNER-DECISIONs)

1. **#85 Lint-Strenge:** Start mit Stufe 0 (`E,F,I` + format, mypy nur Kernmodule)? Großer einmaliger
   `ruff format`-Bestands-Commit akzeptabel? eslint für TS gewünscht oder reicht `tsc --noEmit`?
2. **#86 Tooling:** mutmut (empfohlen) oder cosmic-ray? Kill-Rate-Schwelle 80%? Welche Module über die 2
   Kernmodule hinaus (portfolio_engine-Helper ja/nein)?
3. **#84 Concurrency-Grad:** 16/10 ok als Pflicht-Default? Concurrency-Test zusätzlich gegen Postgres-Service
   (empfohlen) oder nur SQLite? Locust-Last-Generator nötig?
4. **#79 E2E-Modus:** Modus A (Browser-gegen-Backend, robust) als Pflicht-Gate + Electron-Modus B optional —
   einverstanden?
5. **#81 Visual-Toleranz:** `maxDiffPixelRatio: 0.01` als Start ok?
6. **#80 EXE-Trigger:** nur `main`+`dispatch`(+tags), oder zusätzlich path-filtered PR? portable-only oder auch
   NSIS-Installer in CI?
7. **#83 Wall-Time-Budgets:** Aggregator < 2 s / Engine(house-matrix) < 5 s als CI-Obergrenzen ok, oder
   strenger/lockerer?
