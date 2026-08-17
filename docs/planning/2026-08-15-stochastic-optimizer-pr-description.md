# PR: Stochastischer Optimizer wird Produktions-Default + Fail-Closed-Härtung Asset-Allocation

**Branch:** `codex/asset-allocation-stochastic-core` (`ea53a63`) → `develop`
**Merge-Typ:** Squash-Merge empfohlen
**Verifiziert in:** `C:\tmp\5eyes-merge-stochastic` (isolierter Merge-Worktree, `merge/asset-allocation-stochastic-core-into-develop`, Merge-Commit `d1e26cb`)

## Zusammenfassung

Dieser PR macht den stochastischen Monte-Carlo-Optimierer zum produktiven Default
für die Ziel-Asset-Allokation (`optimizer_mode` wechselt von `house_matrix` auf
`stochastic` in `5eyes-backend/config.py`). Die House-Matrix bleibt als
auditierter, technischer Fallback bestehen; `app_env=production` erzwingt
`stochastic` per Guard (verhindert versehentlichen Rückfall in Produktion).

Zusätzlich enthält der PR mehrere mathematische Korrektheits-Fixes im
Optimizer-Kern und eine breite Fail-Closed-Härtung der Eingabevalidierung für
Risiko-, Ziel-, CMA- und Mandats-Inputs.

## Warum das wichtig ist

- **Produktions-Default-Flip**: Der stochastische Solver war bisher nur
  opt-in (`OPTIMIZER_MODE=stochastic`). Ab diesem PR ist er der Standardpfad
  für jede neue Zielallokations-Berechnung — die House Matrix wird zum
  Fallback für den Fall, dass der Solver nicht konvergiert.
- **Mathematische Korrektheit**: Mehrere Bugs im Objective/Moment-Matching
  führten zu systematisch verzerrten Ergebnissen (siehe unten). Diese sind
  jetzt behoben und gegen Hull (2017) Kap. 14 verifiziert.
- **Fail-Closed statt stiller Fallbacks**: Ungültige oder unvollständige
  Eingaben (Risikoprofil, Ziele, CMA, Mandatspräferenzen) werden jetzt an
  zentralen, strikten Grenzen abgelehnt statt lautlos mit falschen Defaults
  weiterverarbeitet zu werden.

## Inhaltliche Änderungen

### Kernänderung
- `5eyes-backend/config.py`: `optimizer_mode: str = 'stochastic'` (vorher
  `'house_matrix'`). `app_env == 'production'` erzwingt `stochastic` per
  Validierungs-Guard.

### Mathematische Korrektheits-Fixes im Optimizer
- `services/return_moments.py`: Momententreue Umrechnung arithmetischer
  CMA-Momente (μ, σ) auf Lognormal-Parameter (Hull 2017, Kap. 14). Die
  bisherige direkte Verwendung von σ als Log-Volatilität überschätzte die
  einfache Return-Volatilität systematisch.
- `services/optimizer/objective.py`:
  - Shortfalls werden vor dem Quadrieren durch eine gemeinsame Context-Skala
    geteilt → dimensionslose Objective (statt einer Größenordnungs-abhängigen
    Straffunktion).
  - Doppelzählung bei `cashflow_in_year`-Zielen behoben (Outflow war bereits
    im Wealth-Pfad abgezogen und wurde zusätzlich im Objective bestraft).
  - `outflow_stream` prüft jetzt jeden Fälligkeitstermin statt nur das
    Endvermögen → deckt vorher verdeckte Zwischen-Finanzierungslücken auf.
- `services/optimizer/scenario_engine.py`: Strikte PSD-Faktorisierung statt
  stillem Identity-Fallback bei ungültiger Korrelationsmatrix.

### Neue kanonische Fail-Closed-Semantik-Module (`services/`)
`goal_semantics`, `risk_assessment_semantics`, `wealth_position_semantics`,
`mandate_preferences`, `mandate_model_inputs`, `cma_validation`,
`calendar_horizon` — ersetzen verstreute, teils fehlende Validierung durch
zentrale, strikte Verträge statt stiller Fallbacks auf falsche Defaults.

### Phase 6: Sensitivity-Endpoint
`POST .../target-allocation/sensitivity` für Goal-Sensitivitätsanalyse
(Baseline- vs. modifizierter Solver-Lauf).

### Während der Verifikation zusätzlich gefundene und gefixte Produktionsbugs
1. `schemas/allocation.py` + `services/portfolio_engine.py:_normalize_preferences`:
   `AllocationPreferencesPayload` hatte Key-Validatoren nur für 2 von 8
   Sektionen (`tilts`, `bands`). Tippfehler in `policy`/`product`/`limits`/
   `geo`/`assetClasses`/`simulation` blieben lautlos wirkungslos. Validatoren
   ergänzt; `_normalize_preferences` validiert jetzt zentral (API,
   Sensitivity, Reload, direkte Service-Aufrufer).
2. `services/portfolio_engine.py:build_target_payload_from_allocation`:
   Content-Validierung (`validate_risk_assessment_model_input`) lief vor der
   Identitätsprüfung des Assessments — ein falsch zugeordnetes
   Assessment-Objekt schlug mit einer irreführenden Feldfehler-Meldung fehl
   statt mit "falsches Risikoprofil". Reihenfolge korrigiert.
3. `services/portfolio_engine.py:_current_risk_assessment_or_none`: Ein
   Refactoring in einen gemeinsamen Helper hatte das `selectinload(answers)`
   für `GET .../risk-assessments/current` verloren; `eager_answers`-Parameter
   ergänzt.

### Golden-Snapshot-Baseline neu eingefroren
`tests/fixtures/golden_ch_recommendations/` wurde mit den durch obige
Korrektheits-Fixes veränderten, mathematisch verifizierten Werten neu
eingefroren. Die Sharpe-ähnliche Kennzahl verbessert sich in allen
betroffenen Fällen (z. B. `bucket5_ausgewogen_equities_global`:
0.543 → 0.581) — konsistent mit einer Korrektur vormals überschätzten
Risikos, nicht mit einer Verhaltensregression. Dabei wurde außerdem eine
bestehende Mojibake-Korruption ("Liquidit?t") in einer Fixture behoben.

~19 Testdateien mit veralteten Fixtures repariert (inkonsistente
Score/Profil-Paare, fehlende CMA-Teilklassen-Zuordnungen, fehlender
kanonischer Zieltyp, `optimizer_mode` nicht explizit gepinnt nach dem
Default-Wechsel, fehlende `tenants`-Modell-Registrierung für isolierte
Testläufe).

## Merge-Konflikt-Auflösung

Divergenz-Analyse: Der Feature-Branch `ea53a63` basiert auf `8fd18b5`
(unmittelbarer Elternknoten von `develop`s damaligem HEAD `27b6f36`). Zum
Zeitpunkt des Merges war `develop` genau **einen** Commit weiter
(`27b6f36`, "Soft-Limit-Warn-UI für Tenant-Auslastung"), der Feature-Branch
war ein einziger großer, bereits gebündelter Commit. Die Divergenz war damit
minimal.

**Ein Merge-Konflikt**, ausschließlich in:
`docs/audits/2026-06-02-monolith-inventory.json`

Ursache: Diese Datei ist ein **generierter** Snapshot (Sprint U-35,
`scripts/audit_html_monolith.py`), der Zeilennummern von IDs, Event-Handlern,
JS-Funktionen usw. innerhalb der Monolith-Datei
`5eyes-electron/frontend/5eyes_v2.html` festhält. Beide Branches hatten
`5eyes_v2.html` unabhängig voneinander verändert (das HTML selbst mergte
automatisch konfliktfrei), wodurch sich in beiden Branches unterschiedliche
Zeilennummern für dieselben IDs/Handler ergaben — der Git-Merge konnte diese
reinen Zeilennummer-Diffs nicht automatisch versöhnen (>4000 Konfliktmarker,
ausschließlich in `"line": N`-Feldern).

**Auflösung**: Statt die Konflikte Zeile für Zeile manuell aufzulösen (was bei
einer generierten Datei sachlich falsch wäre und Drift gegenüber dem
tatsächlichen HTML einführen würde), wurde die Datei nach dem Auto-Merge von
`5eyes_v2.html` frisch aus dem Generator regeneriert:

```
python scripts/audit_html_monolith.py
```

Dies ist exakt der Mechanismus, den `tests/test_monolith_inventory_stable.py`
ohnehin erzwingt (`test_monolith_inventory_snapshot_matches_current_html`
vergleicht die Snapshot-Datei 1:1 gegen `build_inventory()` auf der aktuellen
HTML-Datei). Die Regenerierung garantiert, dass der Snapshot exakt den
gemergten Stand von `5eyes_v2.html` widerspiegelt — keine Handauswahl
zwischen den beiden Konfliktseiten war nötig oder inhaltlich sinnvoll.
Verifiziert: `test_monolith_inventory_stable.py` (3 Tests) läuft grün als Teil
der vollen Suite.

Keine weiteren Konflikte in Code-, Schema-, Migrations- oder Testdateien.
`develop`s einziger Zusatz-Commit (`27b6f36`) betraf ausschließlich
`routers/tenants.py`, `schemas/tenants.py`, `services/quota.py` und zwei neue
Testdateien — kein Überschneidungsbereich mit dem Optimizer-/Allocation-Kern.

## Testevidenz

| Prüfung | Ergebnis |
|---|---|
| Backend-Vollsuite (`pytest tests/ -q`, 5981 Tests gesammelt) | ✅ grün nach Fix (siehe unten): 5969 passed, 10 skipped, 1 xfailed, 2 vorbestehende/unabhängige Flakes (siehe eigener Abschnitt) |
| Golden-Snapshot-Regression (`test_golden_snapshot_ch_regression.py`) | ✅ 7/7 Fälle grün |
| `test_monolith_inventory_stable.py` | ✅ grün (Teil der Vollsuite) |
| Frontend `reporting`: `npm run typecheck` | ✅ keine Fehler |
| Frontend `reporting`: `npm test` (vitest) | ✅ 536/536 Tests, 47/47 Dateien |
| Frontend `reporting`: `npm run build` | ✅ erfolgreich (`tsc --noEmit && vite build`) |
| `config.py` Default-Check | ✅ `optimizer_mode: str = 'stochastic'` (Zeile 240), Production-Guard aktiv (Zeile 518-520) |

### Zusatzfund + Fix: Alembic `fileConfig()` deaktivierte stillschweigend bereits
### existierende Logger (echter, vorbestehender Produktionsbug)

Bei der ersten vollen Suite-Läufen (mehrfach reproduziert, deterministisch)
schlugen exakt 3 Tests fehl:
- `tests/test_pdf_font_embedding.py::test_missing_ttf_files_degrade_without_crash`
- `tests/test_telemetry_opt_in.py::test_capture_exception_no_op_when_inactive`
- `tests/test_telemetry_opt_in.py::test_capture_message_no_op_when_inactive`

Alle drei sind reine `caplog`-Assertions (pytest-Log-Capture), keine
Business-Logik. Systematische Bisektion (Prefix-Slices der collection-order
Testliste, binär halbiert von 4201 auf exakt 1 Test) identifizierte den
deterministischen Auslöser: `tests/test_alembic_baseline_migration.py::
test_baseline_migration_matches_current_models` (Testposition 905 von 5981).

**Root Cause**: `alembic/env.py` ruft `fileConfig(config.config_file_name)`
ohne `disable_existing_loggers=False` auf. Pythons `logging.config.fileConfig()`
hat als **Default** `disable_existing_loggers=True` — das setzt `.disabled =
True` auf JEDEM zu diesem Zeitpunkt bereits existierenden Logger, der nicht
explizit in `alembic.ini`s `[loggers]`-Sektion deklariert ist (dort stehen nur
`root`, `sqlalchemy`, `alembic`). Ein `disabled`-Logger verwirft JEDEN Log-Aufruf
bedingungslos, unabhängig von Level/Handlern — exakt das beobachtete Symptom
(`caplog.text == ''`, `caplog.records == []`).

Das ist **kein reiner Test-Isolationsbug**: `5eyes-backend/database.py:1376`
(`_create_or_migrate_schema`) ruft `alembic.command.upgrade(cfg, "head")` bei
**jedem Postgres-Produktions-App-Start** auf — und das durchläuft denselben
`env.py`-Pfad. In echter Postgres-Produktion (Tier 2/3-Hosting) würde also
jeder App-Start beliebige, zu diesem Zeitpunkt bereits importierte Logger
(z.B. `services.telemetry`, `services.pdf.fonts`, oder jeder andere
Modul-Logger) für die gesamte Prozesslaufzeit stummschalten — ein stiller
Logging-Blackout, der z.B. Sentry-Telemetrie oder Diagnose-Logs unbemerkt
ausfallen lassen könnte.

Der Test-Trigger existiert bereits seit Commit `e009e36` ("Alembic-
Erstmigration + init_db-Switch", Roadmap #90) auf **beiden** Branches (develop
UND dem Feature-Branch) — dies ist also ein vorbestehender Bug, nicht durch
diesen Merge eingeführt. Er wurde nur durch DIESEN Merge-Verifikationslauf
erstmals mit der vollen 5981-Test-Suite in exakt dieser Reihenfolge sichtbar.

**Fix** (in diesem Worktree bereits committet, Teil dieses PRs):
`5eyes-backend/alembic/env.py` — `fileConfig(config.config_file_name,
disable_existing_loggers=False)`. Verifiziert: die identifizierte
905-Test-Bisektions-Slice läuft jetzt 906/906 grün (vorher 1 failed); die
volle Suite bestätigt beide Telemetrie-Tests und den Font-Test grün.

### Bekannter, unabhängiger Flake (NICHT Teil dieses PRs, nicht gemergt-induziert)

In einem Suite-Lauf (nach obigem Fix) traten zusätzlich 2 neue Fehlschläge auf:
- `tests/test_account_recovery.py::test_reset_link_ignores_attacker_host_header_when_public_base_url_configured`
- `tests/test_account_recovery.py::test_reset_link_falls_back_to_host_header_when_public_base_url_unset`

Beide schlagen mit `429 Too Many Requests` statt `200` fehl, laufen aber
isoliert (`pytest tests/test_account_recovery.py`) 13/13 grün. Root Cause
identifiziert: `services/login_guard.py::_get_guard_engine()` cached seine
DB-Engine modul-global über die gesamte Session (`_ENGINE_CACHE`, geschlüsselt
auf `settings.db_path` — NICHT auf die per-Test-tmp-DB), und
`routers/auth.py::_login_guard_key()` schlüsselt den Rate-Limit-Zähler auf die
Client-IP, die bei `TestClient`-Requests für die gesamte Suite identisch ist.
Dadurch akkumulieren sich Fehlversuche aus GANZ ANDEREN, nicht
zusammenhängenden Tests (jeder Test, der einen guard-geschützten
Auth-Endpunkt aufruft) über die volle Session hinweg in demselben Zähler; ob
der Schwellwert exakt bei diesen beiden Tests reißt, hängt vom
Echtzeit-Timing des jeweiligen Laufs ab (das Zeitfenster des Guards ist
zeitbasiert) — daher nicht-deterministisch (in 2 von 3 vollen Läufen dieser
Verifikation grün, in 1 von 3 rot).

**Weder `services/login_guard.py` noch `routers/auth.py` noch
`tests/test_account_recovery.py` werden von diesem Merge berührt** — bestätigt
über `git show --stat` auf den Merge-Commit. Dies ist ein vorbestehender,
unabhängiger Test-Isolationsbug im Login-Guard, keine Regression dieses PRs.
Empfehlung: separates Ticket (Guard-Engine testbar/injizierbar machen bzw.
Rate-Limit-Key um einen Test-Reset-Hook ergänzen). Blockiert dieses PR nicht.

## Risiken / worauf ein Reviewer achten sollte

- Dies ist ein **Verhaltens-Default-Flip in Produktion**: Jede neue
  Zielallokations-Berechnung nutzt ab sofort den stochastischen Solver statt
  der House Matrix. Bestehende, bereits gespeicherte Allokationen sind nicht
  betroffen (keine rückwirkende Neuberechnung), aber neue Berechnungen können
  numerisch abweichende SOLL-Allokationen liefern als vorher (siehe
  Golden-Snapshot-Deltas).
- Die Sharpe-ähnliche Kennzahl-Verbesserung in den Golden-Snapshots ist eine
  **Korrektur vormals überschätzten Risikos** (Log-Vola-Bug), keine
  Modelländerung im eigentlichen Sinne — sollte aber vom Reviewer im Diff der
  Fixture-Dateien stichprobenartig nachvollzogen werden.
- Die Regenerierung von `docs/audits/2026-06-02-monolith-inventory.json` ist
  ein reiner Artefakt-Refresh ohne fachliche Bedeutung — die Diff-Größe
  (~1475 Zeilen geändert) kommt ausschließlich von verschobenen
  Zeilennummern, nicht von inhaltlichen Änderungen an IDs/Handlern/Funktionen.

