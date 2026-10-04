---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "canonical-technical-handoff"
status_as_of: "2026-08-25"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
base_commit: "ea53a63b8c74f477d1286f2aadfcf1f688e7d206"
current_head: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
handoff_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
covered_state: "base_commit_plus_committed_peer_review_full_gate_fixes"
worktree_clean: false
visible_worktree_paths: 0
audited_implementation_manifest_paths: 69
git_status_acl_unreadable_pytest_temp_dirs: 53
scope: "backend asset-allocation stochastic optimizer and consuming integrity paths"
release_decision: "blocked_pending_definition_of_done"
known_open_p0_p1_in_review_scope: 0
known_open_p0_p1_in_post_commit_scope: true
release_status_superseded_by: "docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md"
post_commit_findings_present: true
postcommit_release_audit: "2026-08-25-asset-allocation-post-commit-integrity-audit.md"
resolved_peer_review_p1_themes: 8
production_mode: "stochastic"
alembic_head: "f2a7c91e4b63"
latest_full_gate_state: "passed"
latest_full_gate_collected: 6085
latest_full_gate_passed: 6074
latest_full_gate_failed: 0
latest_full_gate_skipped: 10
latest_full_gate_xfailed: 1
latest_full_gate_warnings: 269
latest_full_gate_duration_seconds: 1681.86
required_next_action: "inspect and clean the 53 ACL-unreadable temp directories or use a clean worktree, rehearse Alembic head f2a7c91e4b63 on production-like PostgreSQL, verify the current-anchor concurrency/409 contract, synchronize secondary docs, and obtain owner/compliance approval"
---

# Asset Allocation Stochastic Core – technischer Handoff

**Stand:** 25. August 2026
**Branch:** `codex/asset-allocation-stochastic-core`
**Referenz-Commit:** `ea53a63b8c74f477d1286f2aadfcf1f688e7d206`
**Implementierungscommit:** `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4`
**Abgedeckter Stand:** Referenz-Commit plus eingecheckter Peer-Review-Nachlauf.
**Release-Entscheidung:** **Hart blockiert.** Der finale vollständige Backend-Gate auf dem eingefrorenen 69-Pfade-Stand ist mit **6074 Passed und 0 Failed** grün; 10 Tests wurden kontrolliert übersprungen und 1 dokumentierter Test war XFail. Der nachgelagerte [Post-Commit-Audit vom 25. August](2026-08-25-asset-allocation-post-commit-integrity-audit.md) hat jedoch offene PostgreSQL-/RLS-P0 sowie P1 in Advisory-Publikation und Current-Anchor-Concurrency belegt. Diese Pfade waren vom SQLite-basierten Gesamtgate nicht vollständig abgedeckt. Weitere formale Freigabekriterien stehen verbindlich in „Definition of Done“.
**Offene P0/P1:** vorhanden; für Befund, Evidenz und Fixreihenfolge ist der Post-Commit-Audit vom 25. August maßgeblich.

Der vollständige Triage-Lauf davor hatte 70 Fehler. Alle wurden isoliert klassifiziert: 67 waren veraltete Fixtures beziehungsweise Orakel und 3 reine Order-/Global-State-Effekte. Separat deckten die Migrations- und Reihenfolgetests zwei echte Deployment-/Runtime-P1s auf: eine fehlende PostgreSQL-Mandatsspalte und durch Alembic deaktivierte Applikationslogger. Beide sind im Implementierungscommit test-first geschlossen.

> **Wichtiger Agentenhinweis:** Die Peer-Review-Fixes sind **nicht** Bestandteil von `ea53a63b`, sondern von `661fe73c`. Den geprüften Implementierungscommit nicht durch partielle Rücksetzungen entkoppeln. Keine Golden Snapshots blind aktualisieren und doppelte Current-Anker niemals automatisch bereinigen.

## Schnellstart für GPT und Claude

Lies vor jeder weiteren Arbeit mindestens diese Abschnitte:

1. „Nicht verhandelbare Produktionsinvariante“
2. „Änderungs-Traceability seit dem Referenz-Commit“
3. „Persistenz, Hash und Replay“
4. „Technische Fallback-Entscheidungsmatrix“
5. „Datenbank-/Deployment-Runbook“
6. „Guardrails – niemals ohne bewusste neue Fachentscheidung ändern“
7. „Testnachweis“ und „Definition of Done“
8. „Startcheckliste für den nächsten GPT-/Claude-Review“

Quellenrangfolge bei Widersprüchen:

1. aktueller Code, Tests und Alembic-Migrationen im abgedeckten Implementierungscommit;
2. dieses Dokument;
3. synchronisierte Teile von `docs/engine-spec.md` und ADRs;
4. ältere Handoffs, Whitepaper, Planning- und Stage-Notizen nur als historische Quellen.

Die wichtigste Ein-Satz-Zusammenfassung lautet:

> Der stochastische Optimizer ist das produktive Entscheidungsmodell; die House Matrix ist nur ein explizit auditierter Sicherheitsfallback und darf niemals ungültige Eingaben, Referenzen oder Persistenzartefakte kaschieren.

> **Post-Commit-Ergänzung vom 25. August 2026:** Der Optimizer-Kern bleibt grün,
> der Release ist aber wegen offener PostgreSQL-/RLS-P0 und ungeprüfter
> Advisory-/Kundenpublikationspfade blockiert. Vor jeder weiteren Arbeit den
> [verbindlichen Post-Commit-Audit](2026-08-25-asset-allocation-post-commit-integrity-audit.md)
> lesen.

## Zweck und Geltungsbereich

Dieses Dokument ist die zentrale Übergabe für GPT, Claude und menschliche Reviewer zum Asset-Allocation-Optimizer. Es erklärt, welche fachlichen und technischen Verträge umgesetzt wurden, wie die produktive Berechnung abläuft, welche Zustände absichtlich fail-closed sind und wie der Stand verifiziert wird.

Für den hier beschriebenen Optimizer-Stand ist dieses Dokument aktueller als ältere Aussagen in:

- `docs/CLAUDE_HANDOFF.md`, soweit dort noch House Matrix als Produktions-Default beschrieben wird;
- `docs/engine-spec.md`, soweit dort noch die alte nicht normalisierte Objective oder erledigte Integrationspunkte als offen stehen;
- `docs/whitepaper/2026-07-19-5eyes-methodik-whitepaper.md`, soweit dort ein Korrelations-/Identity-Fallback oder House Matrix als Default beschrieben wird;
- älteren Planning- und Stage-Notizen.

Der Code bleibt die technische Quelle der Wahrheit. Dieses Dokument dient als Navigations-, Prüf- und Entscheidungsprotokoll.

### Im Scope

- produktive Generate-, Reload- und Sensitivity-Pfade der Asset Allocation;
- OptimizerContext, Solver, Activation-Validation und House-Fallback-Grenze;
- Ziele, Risikoprofil, Preferences, CMA, Sub-Allocations, Cashflows, FX, Steuer und externe Foundation, soweit sie den Optimizer speisen;
- TargetAllocation-Artefakte, Hash-/Replay-Vertrag, PDF-/Recommendation-Integrität;
- Current-Anker, Alembic-/SQLite-Schema und die nach dem Claude-Commit gefundenen P1s.

### Nicht vollständig im Scope dieses Schluss-Gates

- vollständige Repository-Suite inklusive aller nicht optimizerbezogenen Module;
- reale PostgreSQL-Migration auf einem anonymisierten Produktionsklon;
- echte End-to-End-Browser-/Electron-Beraterreise nach den Nachfixes;
- fachliche Freigabe durch Compliance/Investment Committee;
- vollständige Synchronisierung aller historischen Methodik-, Berater- und Whitepaper-Dokumente.

## Nicht verhandelbare Produktionsinvariante

1. `optimizer_mode="stochastic"` ist der Produktionsmodus und der Default.
2. In `APP_ENV=production` wird jeder andere Modus durch die Settings-Validierung abgelehnt.
3. Die House Matrix ist keine alternative produktive Modellwahl. Sie ist nur ein auditierter Sicherheitsfallback für ausdrücklich klassifizierte Solver-Ausfallzustände: nicht verfügbares Optimizer-Modul, technische/numerische Allowlist-Exception, echte Nichtkonvergenz ohne endlichen zulässigen Kandidaten oder Verwerfung eines Ergebnisses in der abschließenden Aktivierungsprüfung.
4. Input-, Domain-, Datenbank-, Referenz-, CMA-, FX-, Steuer-, Mortalitäts-, Snapshot- und Integritätsfehler dürfen keinen House-Fallback auslösen. Sie müssen vor Persistenz einer neuen Strategie fail-closed enden.
5. Ein gespeicherter moderner Strategieentscheid wird nur mit seinen verifizierten Snapshot-Ankern rekonstruiert. Aktuelle Ersatzdaten dürfen nicht unbemerkt mit alten Zielgewichten kombiniert werden.

Relevante Stellen:

- `5eyes-backend/config.py`: Default und Production-Guard.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py`: technische Fallback-Grenze.
- `5eyes-backend/services/optimizer/solver.py`: `SolverTechnicalError`.

## Peer-Review-Nachlauf vom 20. August 2026

Der unabhängige Review bestätigte die Grundarchitektur des Claude-Commits, fand aber mehrere echte P1-Randlücken. Sie wurden im Implementierungscommit `661fe73c` test-first geschlossen:

1. **Solver-Ausnahmen:** SLSQP, Differential Evolution, Kandidatenprüfung und Robustification dürfen gewöhnliche Exceptions nicht als normale Nichtkonvergenz umdeuten. Auditierte House-Fallback-Pfade bleiben: nicht verfügbares Optimizer-Modul, zurückgegebene Nichtkonvergenz ohne endlichen zulässigen Kandidaten, die ausdrücklich klassifizierte technische/numerische Exception-Allowlist sowie eine fehlgeschlagene Abschlussvalidierung des konkreten Aktivierungskandidaten.
2. **Allocation Preferences:** Nicht nur Keys, sondern auch Werte, Typen und Bereiche aller Sektionen werden strikt validiert. Strings wie `fundsOnly="false"`, unbekannte ESG-Werte, nichtnumerische Limits sowie beschädigtes persistiertes JSON werden abgelehnt.
3. **Risikoprofil-Herleitung:** Capacity, Willingness und Final Score werden bei echten Strategieinputs aus den sieben Rohpunktfeldern und dem kanonischen Anlagehorizont erneut mit `compute_scores` hergeleitet. Manipulierte Zwischenwerte oder Final Scores stoppen Generate, Sensitivity und Reload vor dem Solver. Unverifizierbare Legacy-Horizonte verlangen eine neue Risikoprofilierung.
4. **Goal-Zeitsemantik:** Endliche wiederkehrende Ziele benötigen ein Enddatum; ohne Enddatum müssen sie ausdrücklich ongoing sein. Nichtwiederkehrende Ziele benötigen einen tatsächlich vom Liability-Modell verwendeten Zeitanker. Sensitivity verschiebt auch reine `target_date`-Ziele und verändert keine persistierte ORM-Zeile.
5. **Current-Anchor-Races:** RiskAssessment und TargetAllocation sind pro Mandat, OptimizerPolicy global per Partial-Unique-Index abgesichert. ORM, SQLite-Rohschema und Alembic/PostgreSQL verwenden denselben Vertrag. Alle offiziellen Rollover-Pfade deaktivieren und flushen den Vorgänger vor der neuen Aktivierung.
6. **SQLite-Bestandsdaten:** Ein historisch gleich benannter, aber falsch auf `policy_name` definierter Policy-Index wird beim Start idempotent auf den globalen Current-Vertrag repariert. Mehrdeutige Altbestände scheitern dabei fail-closed.
7. **PostgreSQL-Schema-Parität:** `Mandate.tax_estimate_in_cashflow_enabled` war im ORM und SQLite-Reparaturpfad vorhanden, fehlte aber im Alembic-Schema. Revision `f2a7c91e4b63` ergänzt `INTEGER NOT NULL DEFAULT 0`; ein vollständiger ORM-Spaltenvergleich verhindert künftige tabelleninterne Drift.
8. **Alembic-Logging-Isolation:** `logging.config.fileConfig()` deaktivierte beim In-Process-Upgrade bereits importierte Service-Logger. Alembic bewahrt bestehende Applikationslogger jetzt ausdrücklich mit `disable_existing_loggers=False`.

Diese Änderungen sind nicht Teil des oben genannten Referenz-Commits. Sie wurden als eigener geprüfter Implementierungscommit `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4` gesichert.

## Änderungs-Traceability seit dem Referenz-Commit

| P1-Thema | Ursache | Produktionscode / Symbol | Primäre Regressionstests | Status |
|---|---|---|---|---|
| Solver-Exception-Masking | breite `except Exception`-Blöcke deuteten Programmier-/Domainfehler als Nichtkonvergenz um | `services/optimizer/solver.py`: `_solve_single_start`, `_solve_via_genetic_algorithm`, `_finite_feasible_candidate`, `_derisk_candidate_near_best`; `services/portfolio_engine_optimizer_integration.py`: `_run_stochastic_optimizer_pass` | `test_optimizer_fail_closed_boundaries.py`, `test_optimizer_ga_fallback.py` | geschlossen |
| Preference-Werte und Snapshot-JSON | nur Keys waren geprüft; truthy Strings, ungültige Zahlen und beschädigtes JSON konnten still Defaults aktivieren | `schemas/allocation.py`: `AllocationPreferencesPayload`, `AllocationBandOverridePayload`; `services/portfolio_engine.py`: `_normalize_preferences`, `_allocation_snapshot_preferences` | `test_allocation_preferences_fail_closed_contracts.py`, `test_asset_allocation_remaining_integrity_edges.py` | geschlossen |
| Risikoprofil-Herleitung | persistierter Final Score wurde nicht aus Rohpunkten, Horizon, Capacity und Willingness verifiziert | `services/risk_assessment_semantics.py`: `_validate_persisted_derivation`, `validate_risk_assessment_model_input` | `test_risk_assessment_derivation_integrity.py`, `test_asset_allocation_remaining_integrity_edges.py` | geschlossen |
| Goal-Zeitanker | endliche Streams ohne Ende sowie nichtwiederkehrende Ziele mit wirkungslosem `start_date` wurden akzeptiert | `services/goal_semantics.py`: `validate_goal_model_input` | `test_goal_domain_fail_closed_contracts.py`, `test_optimizer_goal_liabilities.py` | geschlossen |
| Sensitivity-Date-Shifts | reine `target_date`-Ziele ohne `horizon_years` wurden nicht verschoben; ORM-Unveränderlichkeit war nicht vollständig geprüft | `services/portfolio_engine.py`: `evaluate_goal_sensitivity` / `_modified_goal_state` | `test_optimizer_phase6.py` | geschlossen |
| Current-Anchor-Races | Exact-One-Resolver waren vorhanden, aber DB-Races konnten doppelte aktuelle RA/TA/Policy erzeugen | `models/allocation.py`, `models/profiling.py`; `routers/allocation.py`, `routers/profiling.py`; `database.py`; Migration `d4e8f1a9c2b7` | `test_current_anchor_uniqueness.py`, `test_asset_allocation_current_integrity_contracts.py`, `test_asset_allocation_reference_integrity_edges.py` | geschlossen |
| Alembic-/ORM-Schema-Drift beim Tax-Cashflow-Flag | `tax_estimate_in_cashflow_enabled` existierte im ORM/SQLite-Pfad, aber nicht im PostgreSQL-Alembic-Head | `models/mandates.py`; Migration `f2a7c91e4b63_mandate_tax_cashflow_flag.py` | `test_alembic_baseline_migration.py` | geschlossen; Migration-/Schema-Re-Gate 33/33 |
| Alembic deaktivierte Service-Logger | `fileConfig()` verwendete implizit `disable_existing_loggers=True` | `alembic/env.py` | `test_alembic_baseline_migration.py`, `test_pdf_font_embedding.py`, `test_telemetry_opt_in.py` | geschlossen; exakte Reihenfolge 4/4, betroffene Dateien 37/37 |

### Code-Navigation für den Nachlauf

| Datei | Verantwortung im Nachlauf |
|---|---|
| `5eyes-backend/database.py` | SQLite-Bestandsindex prüfen und idempotent reparieren; bei Duplikaten fail-closed |
| `5eyes-backend/alembic/env.py` | In-Process-Migrationen dürfen bestehende Applikationslogger nicht deaktivieren |
| `5eyes-backend/models/allocation.py` | ORM-Partial-Unique-Indizes für TargetAllocation und OptimizerPolicy |
| `5eyes-backend/models/mandates.py` | Nicht-nullbarer ORM-/Server-Default-Vertrag für den Tax-Cashflow-Opt-in |
| `5eyes-backend/models/profiling.py` | ORM-Partial-Unique-Index für RiskAssessment |
| `5eyes-backend/routers/allocation.py` | Vorgänger vor TA-/Policy-Rollover deaktivieren und flushen |
| `5eyes-backend/routers/profiling.py` | Vorgänger vor RiskAssessment-Rollover deaktivieren und flushen |
| `5eyes-backend/schemas/allocation.py` | strikte Preference-Wert-, Typ-, Bereichs- und Bandvalidierung |
| `5eyes-backend/services/goal_semantics.py` | getrennte Zeitanker-Semantik für einmalige/evaluierte Ziele und Streams |
| `5eyes-backend/services/optimizer/solver.py` | Exceptions erhalten; nur echte `OptimizeResult`-Nichtkonvergenz bleibt normaler Solverzustand |
| `5eyes-backend/services/portfolio_engine.py` | Preferences-Snapshot, TA-Rollover und Sensitivity-Gegenfaktum |
| `5eyes-backend/services/portfolio_engine_optimizer_integration.py` | technische Fallback-Allowlist und Activation-Abschlussprüfung |
| `5eyes-backend/services/risk_assessment_semantics.py` | erneute fachliche Herleitung persistierter Risiko-Scores |
| `5eyes-backend/5eyes_schema_v4.0_FINAL.sql` | SQLite-Rohschema-Parität für Current-Indizes |
| `5eyes-backend/alembic/versions/d4e8f1a9c2b7_current_anchor_unique_indexes.py` | PostgreSQL-/SQLite-Migration der drei Partial-Unique-Indizes |
| `5eyes-backend/alembic/versions/f2a7c91e4b63_mandate_tax_cashflow_flag.py` | PostgreSQL-/Alembic-Nachführung des Mandatsfelds für Bestands- und Neuzeilen |
| `5eyes-backend/tests/risk_fixture_helpers.py` | zentrale, `compute_scores`-basierte Herleitung fachlich konsistenter Risikoprofil-Fixtures |

## End-to-End-Datenfluss

```text
Mandat + aktuelles Risikoprofil + Ziele + Cashflows + Vermögen
  -> strikte Domain- und Referenzvalidierung
  -> jurisdiktionsgenaue Policy, House Matrix, Building Blocks und CMA
  -> investierbares Beratungsvermögen / externe Foundation / Reserve
  -> kanonischer Sub-Allocation-Plan inkl. 0%-Buckets
  -> effektive Bounds + einheitliche Risky-Fraction-Funktion
  -> versionierter OptimizerContext und Szenariopfad
  -> stochastischer Solver
  -> Aktivierungsprüfung im exakt gleichen Context
  -> persistierte TargetAllocation + Context-Artefakte + SHA-256
  -> getrennte Entscheidungs- und Umsetzungsprojektion im Response
```

### Entscheidungsmodell und Reportingmodell

Die API weist zwei Modellbasen ausdrücklich getrennt aus:

- `stochastic_decision_v2`: Zielgewichtsauswahl im stochastischen Entscheidungsmodell.
- `implementation_projection_v2`: nachgelagerte Umsetzungsprojektion mit Reporting-/Rebalancing-Annahmen.

`goal_achievability_basis_id` gehört zum Entscheidungsmodell. `goal_analysis_basis_id` gehört zur Umsetzungsprojektion. Abweichungen zwischen beiden sind kein stiller Grund für House-Fallback, sondern müssen als unterschiedliche Modellperspektiven kenntlich bleiben.

## Mathematische Korrekturen

### Renditemomente

`services/return_moments.py` bildet arithmetische CMA-Momente auf Lognormalparameter ab:

```text
v = log(1 + (sigma / (1 + mu))^2)
sigma_log = sqrt(v)
mu_log = log(1 + mu) - v / 2
```

Damit entsprechen Erwartungswert und Standardabweichung der simulierten einfachen Rendite den CMA-Eingaben. Die frühere direkte Verwendung der einfachen Volatilität als Log-Volatilität ist entfernt. Tail-/Cornish-Fisher-Marginalen sind versioniert und momentenkalibriert.

### Objective und Ziele

- Vermögens- und Renditeshortfalls werden vor dem Quadrieren auf eine gemeinsame Context-Skala normiert. Die Objective ist dadurch dimensionslos statt von Rappen-Quadraten dominiert.
- Cashflows werden nicht doppelt als Wealth-Pfad und separates Zieldefizit belastet.
- Wiederkehrende Ausgaben werden nur an tatsächlichen Fälligkeitsterminen geprüft.
- Zielwahrscheinlichkeit, Zielscope, externe Vermögensbasis, Laufzeit und kalenderbasierte Horizonte verwenden zentrale Domainsemantik.
- Sensitivity vergleicht Baseline und Gegenfaktum mit gemeinsamem Seed und gemeinsamem Max-Horizon-Szenariokontext.

### Korrelation und CMA

- Korrelationsmatrizen werden zentral auf Form, Endlichkeit, Symmetrie, Diagonale und positive Semidefinitheit geprüft.
- Eine ungültige explizite Matrix fällt nicht auf Identity oder einen anderen stillen Default zurück.
- Explizite Nullrenditen bleiben Null und werden nicht über Truthiness durch Defaults ersetzt.
- Fehlende oder ungültige aktive Sub-CMA-Zuordnungen enden fail-closed.
- Nelson-Siegel-, KGV- und Risk-Premium-Parameter werden als vollständige Gruppen validiert; unvollständige Gruppen sind inaktiv, vollständige ungültige Gruppen werden abgelehnt.
- Negative fachlich gültige Renditen bleiben in Expected Metrics erhalten.

## Kanonische Input- und Fail-Closed-Verträge

Zentrale Module unter `5eyes-backend/services/`:

| Modul | Vertrag |
|---|---|
| `goal_semantics.py` | Zieltyp, Familie, Scope, Härte, Gewicht, Rang, Betrag, Frequenz und Zeitanker |
| `risk_assessment_semantics.py` | Score-/Profil-Konsistenz, Override, Bestätigung, FZK-Cap |
| `wealth_position_semantics.py` | Positionsart, Zuordnung, Direktimmobilien und Legacy-Lesealiase |
| `mandate_preferences.py` | persistierte Building-Block-Defaults ohne stille Tippfehler |
| `mandate_model_inputs.py` | aktivierte Steuer-/Mortalitätsmodelle und vollständige Mandatsinputs |
| `cma_validation.py` | Core-/Home-CMA, Sub-CMA, Korrelation, PSD und Advanced-Parameter |
| `calendar_horizon.py` | kalenderjahresgenaue Horizonte, inklusive Leap-Day |
| `currency/fx_rates.py` | versionierte, signierte und fail-closed FX-Modellbasis |

Weitere Invarianten:

- `is_active` wird für modellrelevante Rohdaten strikt als 0 oder 1 validiert, bevor inaktive Datensätze ausgefiltert werden.
- Strategieverbrauchende Generate-, Reload-, Sensitivity-, PDF- und Recommendation-Pfade laden aktuelle Risk Assessments, Target Allocations, Policies und referenzierte Daten über Exact-One-/Anchor-Verträge; Mehrdeutigkeit blockiert die Berechnung. Diese Aussage gilt nicht pauschal für jeden rein administrativen Anzeigeendpunkt.
- Jurisdiktionsdaten verwenden Shared-NULL plus exakte Jurisdiktions-Overrides; fremde Jurisdiktionen dürfen nicht leaken.
- Ein explizit gewähltes Investment-Universum fällt bei fehlenden Daten nicht auf ein anderes Universum zurück.
- Allocation Preferences verbieten unbekannte Top-Level- und Sektionskeys. Der gleiche Validator läuft bei API, Generate, Reload, Sensitivity und direkten Service-Aufrufen.
- Aktivierte Steuer- oder Mortalitätsmodelle benötigen vollständige Inputs; „aktiv, aber still ignoriert“ ist unzulässig.

### API-/Service-Verhaltensmatrix

| Pfad | Fehlerklasse | Erwartetes Verhalten |
|---|---|---|
| Preference-, Goal-, Mandate-Create/Update | Schema-/Merged-State-Fehler | HTTP 422; keine partielle Mutation |
| Strategie generieren | Domain-, CMA-, FX-, Tax-, Mortality- oder Referenzfehler | Service fail-closed; Allocation-Router mappt auf Domainkonflikt, keine neue aktuelle TargetAllocation |
| `/target-allocation/current/payload` | Inputdrift, fehlender/deaktivierter Anker, Hash-/Artefaktfehler | HTTP 409; keine Hybridanalyse mit aktuellen Ersatzdaten |
| Goal Sensitivity | unvollständiges Risikoprofil, fehlende Vermögensbasis, ungültiger Live-Kontext | fail-closed vor dem ersten Solver-Aufruf |
| Strategie-PDFs | fehlender Current-TA-, Policy-, Assessment- oder CMA-Anker; Drift | HTTP 409 vor dem Renderer, kein PDF mit Ersatzmathematik |
| Recommendation Generate/Reload | explizit fehlende/fremde TA-ID oder inkonsistente Policy/CMA/Assessment-Anker | 404/409 entsprechend Identität versus Integrität; kein RecommendationRun mit fremdem Kontext |
| technischer Solver-Ausfall | nur klassifizierte Fallback-Bedingung | auditierten House-Kandidaten im retained Context prüfen; bei unzulässigem House ebenfalls fail-closed |

Die genaue HTTP-Zuordnung gehört dem jeweiligen Router. Der Servicevertrag ist entscheidend: Fehler dürfen weder stille Defaults aktivieren noch neue Strategieartefakte persistieren.

## Sub-Allocation, Bounds und Risikobudget

- Der kanonische Sub-Allocation-Plan enthält auch Buckets mit 0% Zielgewicht. Dadurch bleiben deren Zusammensetzung, CMA und Risky-Fraction für Replay und Sensitivity erhalten.
- Explizite 0-bps-Grenzen sind gültig und werden nicht als `False`/fehlend interpretiert.
- Effective Bounds sind der finale Solververtrag. Globale Liquiditäts-, Immobilien-, Alternatives- und Illiquiditätsgrenzen werden vor Solverübergabe integriert.
- Solver, Aktivierungsprüfung, Persistenz und Reporting verwenden dasselbe ganzzahlige Risky-Fraction-Funktional.
- Die verwendeten Building Blocks müssen eine echte `risky_fraction_bps` im Bereich 0..10000 besitzen.

## Cashflow, Steuern, FX und externes Vermögen

- Beratungsliquidität erhält CMA-Total-Return. Ihr abgeleiteter Kontozins wird deshalb aus der Solver-Cashflow-Serie entfernt, bleibt aber in der Reportingdarstellung. Externe Liquiditätszinsen bleiben Cashflow.
- Direkte Immobilien sind externes Gesamtvermögen, nicht handelbare SAA. Ihr Principal wächst positionsweise mit `asset_expected_return_bps`; Miete wird genau einmal als Cashflow addiert.
- Hypotheken und direkte/indirekte Amortisation werden in der externen Foundation konsistent und in Basiswährung projiziert.
- Dynamisch ersetzte Steuern werden nur für den tatsächlich ersetzten Advisory-Anteil aus der Solver-Serie entfernt. Steuern auf externem Vermögen bleiben erhalten.
- Unbekannte Steuerjurisdiktionen, Währungen, ungültige FX-Raten oder fehlerhafte Modelltabellen sind Domainfehler, keine Default-Gelegenheit.

## Persistenz, Hash und Replay

Moderne `TargetAllocation`-Datensätze setzen `context_artifacts_required=1` und benötigen gemeinsam:

- `sub_allocations_json`
- `effective_constraints_json`
- `allocation_context_hash`
- `capital_market_assumptions_id`
- `policy_id`
- `based_on_assessment_id`

Artefakte sind All-or-none. Leere Strings, partielle Zustände, gelöschte Snapshot-CMA, falsche Policy-/Assessment-Anker und Hashabweichungen werden abgelehnt.

Aktuelle Versionen:

- Engine-Context: `stochastic_core_v2`
- Strategieinput-Snapshot: `strategy_inputs_v4_complete_goals`
- Sensitivity-Livecontext: `sensitivity_live_context_v3_complete`
- Optimization Model Basis: `stochastic_decision_v2`
- Reporting Model Basis: `implementation_projection_v2`

### Kompatibilitätsmatrix

| Zustand | Nachweis | Zulässiges Verhalten |
|---|---|---|
| echter historischer Datensatz, `context_artifacts_required=0` und alle Context-Artefakte `NULL` | expliziter Legacy-Marker | eingeschränkter Legacy-Read; nicht als moderner kryptografisch verifizierter Entscheid ausgeben |
| moderner Datensatz, `context_artifacts_required=1` | Sub-Allocations, Effective Constraints, Context-Hash, CMA-, Policy- und Assessment-Anker vollständig | strikter Reload/Replay nach Hash- und Anchor-Prüfung |
| moderner Marker mit fehlendem oder leerem Artefakt | unvollständiger Zustand | immer fail-closed; niemals zu „Legacy“ herabstufen |
| Hashversion v1–v3 | historisch versionsgenau rekonstruierbare Payload | lesbar, aber damals nicht gebundene Felder sind nicht rückwirkend beweisbar |
| Hashversion v4 | vollständige Goal-Felder inklusive nullable Semantik | aktueller vollständiger Strategieinput-Nachweis |
| Sensitivity Live Context v3 | aktueller vollständiger Counterfactual-Kontext inklusive Bounds, Submix, Cashflows und FX-Basis | beide Solver-Läufe müssen exakt diesen Contextvertrag verwenden |

Begriffe in diesem Dokument:

- **modern:** `context_artifacts_required=1`; vollständige, gehashte und verankerte TargetAllocation;
- **Legacy:** explizit markierter prä-Context-Datensatz, nicht einfach ein beschädigter moderner Datensatz;
- **kanonischer Horizon:** ein von `canonicalize_horizon_label` unterstütztes Label, dessen Jahre in `HORIZON_YEARS` definiert sind;
- **echter Strategieinput:** persistierte ORM-Daten oder API-/Service-Daten, die eine Kundenstrategie beeinflussen; kleine interne Unit-Test-Doubles ohne ORM-/Horizonmodell sind keine Produktions-Backcompat-Zusage;
- **retained OptimizerContext:** genau dasselbe Context-Objekt für Solve, Activation-Validation, Explainability und House-Prüfung.

Die Verifikation liest ältere v1-v3-Hashes mit ihrer historischen Payloadsemantik weiter. Sie kann jedoch naturgemäß keine Felder rückwirkend beweisen, die eine alte Hashversion damals nicht gebunden hat. Vollständige Goal-Provenienz gilt ab v4.

Reload rekonstruiert keine moderne Strategie mit aktuellen Ersatzannahmen. Inputdrift führt vor Goal-Analyse/MC zu einem Domainkonflikt. PDF- und Recommendation-Pfade propagieren denselben Integritätsvertrag; sie dürfen keine Hybridstrategie publizieren.

## Alembic-Migrationen

Lineare Kette nach der Baseline:

1. `7b31f8d2a6c4_asset_allocation_context_artifacts.py`
   - Target-Allocation-Contextartefakte
   - `optimizer_runs.robustification_json`
2. `e84f9a2d1c70_postgres_market_data_runtime_tables.py`
   - PostgreSQL-fähige Runtime-/Market-Data-Tabellen
3. `b6a7d9124e53_target_allocation_context_marker.py`
   - `target_allocations.context_artifacts_required`
4. `d4e8f1a9c2b7_current_anchor_unique_indexes.py`
   - höchstens ein aktuelles RiskAssessment je Mandat auf Datenbankebene
   - höchstens eine aktuelle TargetAllocation je Mandat auf Datenbankebene
   - höchstens eine globale aktuelle OptimizerPolicy auf Datenbankebene
5. `f2a7c91e4b63_mandate_tax_cashflow_flag.py`
   - ergänzt `mandates.tax_estimate_in_cashflow_enabled`
   - `INTEGER NOT NULL` mit Server-Default `0`
   - erhält das Verhalten bestehender Mandate und von Inserts außerhalb des ORM

PostgreSQL besitzt sein produktives Schema über Alembic. SQLite-spezifische Legacy-Schemahelper dürfen nach dem PostgreSQL-Upgrade nicht als Ersatzmigration laufen.

### Exakte Current-Index-Verträge

| Index | Tabelle / Spalte | Predicate | Fachlicher Scope |
|---|---|---|---|
| `ux_risk_one_current` | `risk_assessments(mandate_id)` | `is_current = 1 AND deleted_at IS NULL` | höchstens ein lebendes aktuelles Risikoprofil je Mandat |
| `ux_target_alloc_one_current` | `target_allocations(mandate_id)` | `is_current = 1 AND deleted_at IS NULL` | höchstens eine lebende aktuelle Soll-Allokation je Mandat |
| `ux_optimizer_one_current` | `optimizer_policies(is_current)` | `is_current = 1` | höchstens eine globale aktuelle OptimizerPolicy |

Die Partial-Unique-Indizes verhindern Duplikate, garantieren aber keine Existenz. Erst die Exact-One-Resolver der strategie-konsumierenden Generate-, Reload-, Recommendation- und PDF-Pfade verlangen fachlich den jeweils benötigten aktuellen Anker. Admin-/Bootstrap-Pfade dürfen vor einer kontrollierten Erstanlage zeitweise null Current-Zeilen besitzen.

`database.ensure_current_anchor_unique_indexes()` läuft nur für SQLite in der Legacy-Schema-Maintenance. Die Funktion vergleicht die reale Index-DDL mit dem erwarteten Vertrag und ersetzt insbesondere den historischen gleichnamigen Policy-Index auf `policy_name`. Sind bereits doppelte Current-Zeilen vorhanden, schlägt die Neuerstellung bewusst fehl; sie wählt oder archiviert niemals automatisch einen Gewinner.

## Datenbank-/Deployment-Runbook

### 1. Vorprüfung und Backup

Vor Migration auf einer produktionsähnlichen Kopie ausführen:

```sql
SELECT mandate_id, COUNT(*) AS n
FROM risk_assessments
WHERE is_current = 1 AND deleted_at IS NULL
GROUP BY mandate_id
HAVING COUNT(*) > 1;

SELECT mandate_id, COUNT(*) AS n
FROM target_allocations
WHERE is_current = 1 AND deleted_at IS NULL
GROUP BY mandate_id
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS current_policy_count
FROM optimizer_policies
WHERE is_current = 1;
```

Erwartung: die ersten beiden Queries liefern keine Zeile, die dritte exakt `1`. Abweichungen sind fachlich manuell zu klären. Vor jeder Bereinigung und Migration ein restorable Datenbank-Backup erstellen.

Zusätzlich vor dem Rollout einen read-only Domain-Audit über aktive Bestandsdaten laufen lassen:

- aktuelle RiskAssessments mit nicht kanonischem oder fehlendem Horizon → neue Risikoprofilierung;
- vorhandenes `preferences_json`, das kein valides Objekt oder heute ungültige Werte enthält → bewusste fachliche Korrektur;
- aktive nichtwiederkehrende Goals mit nur `start_date` sowie endliche Streams ohne `target_date` → Zeitanker korrigieren;
- explizit aktivierte Tax-/Mortality-Modelle ohne vollständige Inputs → Mandat vervollständigen.

Diese Daten dürfen nicht automatisiert auf Defaults umgeschrieben werden.

### 2. Migration

```powershell
cd 5eyes-backend
python -m alembic heads
python -m alembic upgrade head
python -m alembic current
```

Erwarteter Head: `f2a7c91e4b63`.

Deployment-Grenzen:

- Die PostgreSQL-Migration erzeugt die Indizes derzeit nicht `CONCURRENTLY`; für große Tabellen ist ein geplantes Wartungsfenster erforderlich.
- Der vorhandene PostgreSQL-Test prüft Offline-DDL, nicht einen echten Upgrade-Lauf gegen einen PostgreSQL-Server.
- Ein bereits manuell angelegter gleichnamiger Index kann eine Namenskollision verursachen und muss vorab inspiziert werden.
- SQLite-Rohschema/Desktop-Startmaintenance und PostgreSQL/Alembic sind getrennte Upgradepfade; keiner ersetzt den anderen.
- Es existiert noch kein echter Zwei-Transaktionen-/HTTP-Concurrency-Test. Der Unique-Index schützt die Daten strukturell, aber die UX-Abbildung des unterlegenen Requests als gezielter 409/Retry ist separat nachzuweisen.

### 3. Schema-Verifikation

PostgreSQL:

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname IN (
  'ux_risk_one_current',
  'ux_target_alloc_one_current',
  'ux_optimizer_one_current'
)
ORDER BY indexname;

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'mandates'
  AND column_name = 'tax_estimate_in_cashflow_enabled';

SELECT COUNT(*) AS invalid_null_flags
FROM mandates
WHERE tax_estimate_in_cashflow_enabled IS NULL;
```

Erwartung für das Mandatsfeld: genau eine Integer-Spalte, `is_nullable = 'NO'`, Default `0`; die Nullwert-Query liefert `0`.

Danach mindestens prüfen:

1. neues Risikoprofil historisiert den Vorgänger und hinterlässt genau ein Current;
2. neue TargetAllocation historisiert den Vorgänger und bleibt reloadbar;
3. Policy-Aktivierung setzt global genau eine Policy auf Current;
4. Generate → Current Payload → Strategie-PDF verwendet identische CMA-/Policy-/Assessment-Anker;
5. absichtlich beschädigter Context und gelöschte Snapshot-CMA ergeben 409 statt Ersatzanalyse.

Monitoring nach Rollout: gewöhnliche Solver-/Domainfehler sind nun absichtlich sichtbar und werden nicht mehr als House-Nichtkonvergenz maskiert. Alerts sollten deshalb `OptimizerInputError`, `CMAValidationError`, gewöhnliche Runtime-/ValueErrors und DB-IntegrityErrors separat von klassifizierten technischen Solver-Fallbacks zählen.

### 4. Rollback

Vom Head `f2a7c91e4b63` entfernt `alembic downgrade d4e8f1a9c2b7` ausschließlich `mandates.tax_estimate_in_cashflow_enabled`; dabei gehen gespeicherte Opt-in-Werte verloren. Ein weiterer Downgrade auf `b6a7d9124e53` entfernt zusätzlich die drei Current-Anchor-Indizes aus `d4e8f1a9c2b7`. Code und Schema müssen gemeinsam zurückgesetzt werden. Weder doppelte Current-Anker noch Tax-Flag-Daten dürfen automatisch „bereinigt“ werden.

## Technische Fallback-Entscheidungsmatrix

| Fehlerklasse | Ergebnis |
|---|---|
| Optimizer-Modul nicht importierbar | auditierter House-Fallback mit `optimizer_module_unavailable` |
| Solver liefert keinen endlichen zulässigen Kandidaten / normale Nichtkonvergenz | auditierter House-Fallback mit Restart-/Konvergenzaudit, sofern House im retained Context selbst alle harten Constraints erfüllt |
| `SolverTechnicalError` | auditierter House-Fallback erlaubt |
| `FloatingPointError` | auditierter House-Fallback erlaubt |
| `numpy.linalg.LinAlgError` im numerischen Solve | auditierter House-Fallback erlaubt |
| `OptimizerInputError` / `CMAValidationError` | fail-closed, keine Allocation |
| gewöhnlicher `ValueError` / Domainfehler | fail-closed |
| FX-/Tax-/Mortality-/DB-/Referenzfehler | fail-closed |
| Snapshot-/Hash-/Anchor-Fehler | 409/Domainkonflikt, kein Replay/PDF |
| ungültige Aktivierungsgewichte oder technische Activation-/Risk-Budget-Abschlussprüfung | Kandidat ablehnen; House nur aktivieren und Rejection-Audit persistieren, wenn House im gleichen Context alle harten Constraints erfüllt |

Jeder House-Pfad mit aufgebautem retained OptimizerContext wird vor Veröffentlichung darin erneut geprüft. Ist auch die House-Allokation dort unzulässig, endet der Vorgang fail-closed mit `OptimizerInputError`; eine unzulässige Sicherheitsallokation wird niemals persistiert. Beim Sonderfall `optimizer_module_unavailable` existiert technisch kein OptimizerContext; der Response bleibt deshalb ohne stochastische Analytics und weist den Grund ausdrücklich aus.

`OptimizerRun.robustification_json` bewahrt bei einem abgelehnten Kandidaten unter anderem Grund, Kandidatengewichte und Kandidaten-Constraint-Verletzungen. Die aktiven `constraint_violations_json` beziehen sich nur auf die effektiv verwendete Allocation.

## Testnachweis

**Wichtig:** Die folgenden Suiten überlappen stark. Zahlen dürfen nicht addiert und nicht als Anzahl eindeutiger Repository-Tests interpretiert werden.

Lokale Prüfgrundlage: Windows, Python 3.14.3, pytest 9.0.2, SQLAlchemy 2.0.48, Pydantic 2.12.5, NumPy 2.5.2, SciPy 1.18.0 und Alembic 1.19.0. Bekannte `PytestCacheWarning`-Meldungen (`WinError 183`) betreffen nur die Cache-Infrastruktur; reproduzierbare Befehle verwenden deshalb nach Möglichkeit `-p no:cacheprovider`.

| Run-ID | Abgedeckter Codezustand | Scope / Befehl | Ergebnis | Einordnung |
|---|---|---|---|---|
| `BASE-HIST-5960` | Referenz-Commit laut Commitprotokoll | historische vollständige Backend-Suite | 5960 grün | Fremdevidenz; bestätigt nicht den nachgelagerten Peer-Review-Nachlauf |
| `CLAUDE-REVIEW-496` | Referenz-Commit vor den Nachfixes | kritischer Core-/Integrity-/Risk-Ring | 496/496 | fand die später test-first geschlossenen P1-Randlücken nicht vollständig |
| `POSTFIX-CORE-332` | finaler Produktcode des Nachlaufs | Solver, Preferences, Risk, Current-Anker, Migration, Production Contract | 332/332 | lokaler fokussierter Schluss-Gate |
| `POSTFIX-GOAL-161` | finaler Produktcode des Nachlaufs | Goal Domain, Goal Liabilities, komplette Phase 6 | 161/161 | inklusive ±Date-Shift und ORM-Reload |
| `POSTFIX-BROAD-629` | finaler Produktcode; vor Anpassung dreier veralteter Testsetups | breiter Verbraucher-Ring | 626 passed, 3 failed | alle drei Fails waren DB-Unique-korrekt blockierte Double-Current-Fixtures, keine Produkttracebacks |
| `POSTFIX-ANCHOR-43` | finaler Code plus korrigierte Defense-in-depth-Fixtures | Current-/Reference-/Anchor-Dateien | 43/43 | die drei früher roten Nodes zusätzlich isoliert 3/3 grün |
| `PRE-FIX-FULL-6079` | nach den sechs ursprünglichen P1-Fixes, vor Migration-/Fixture-Nachlauf | vollständige Backend-Suite | 6079 collected; 5998 passed, 70 failed, 10 skipped, 1 xfailed; 260 warnings; 1756.09 s | Triage-Lauf, keine grüne Release-Evidenz |
| `POSTFIX-NONRISK-FIXTURE-70` | korrigierte Anchor-/Goal-/Risk-Nebenfixtures | gezielter Nachlauf | 70/70 | grün; überlappt mit anderen Ringen |
| `POSTFIX-RISK-FIXTURE-58` | fachlich aus Rohantworten hergeleitete Risk-Fixtures | gezielter Nachlauf | 58/58 plus 16 repräsentative Standalone-Prozesse | grün; keine blinden Golden-Updates |
| `POSTFIX-MIGRATION-33` | Alembic-Head `f2a7c91e4b63` und ORM-/Schema-Parität | Migration-/Schema-Re-Gate | 33/33 | grün; ersetzt keine reale PostgreSQL-Probe |
| `POSTFIX-LOGGING-37` | Alembic-Logger-Isolation, PDF und Telemetry | exakte Reihenfolge und betroffene Dateien | 37/37 | grün; vorheriger Full-suite-only State-Leak geschlossen |
| `POSTFIX-FULL-FIRST-6084` | nach Migration-/Fixture-Fixes, vor letztem Advisory-/Logging-Fix | vollständige Backend-Suite | 6069 passed, 4 failed, 10 skipped, 1 xfailed; 269 warnings; 1755.49 s | 1 stale Advisory-Fixture; 3 Alembic-Logging-State-Fails |
| `POSTFIX-FULL-FINAL-6085` | eingefrorener finaler 69-Pfade-Stand | vollständige Backend-Suite | **6074 passed, 0 failed, 10 skipped, 1 xfailed; 269 warnings; 1681.86 s** | grüner finaler Backend-Gate, Exit 0 |

Die drei korrigierten Tests entfernen den jeweiligen Unique-Index ausschließlich in ihrer function-scoped SQLite-Fixture. Das simuliert bewusst eine beschädigte oder prä-Migrations-Datenbank und hält die Service-/PDF-Defense-in-depth prüfbar; Produktionscode oder reale Schemas werden dadurch nicht gelockert.

Klassifikation der 70 Fehler aus `PRE-FIX-FULL-6079`:

| Klasse | Anzahl | Einordnung |
|---|---:|---|
| Stale Risk-Derivation-Fixtures | 59 | Persistierte Scores widersprachen Rohantworten und `compute_scores`; darin ein Legacy-Horizon-Fall. Fixtures werden nun fachlich hergeleitet. |
| Double-Current-Testsetups | 6 | Fixtures verstießen gegen die neue DB-Invariante; reguläre Setups verwenden jetzt echte Rollover. |
| Endlicher wiederkehrender Goal-Stream ohne Ende | 1 | Testdatensatz war nach dem neuen Zeitvertrag ungültig und ist nun ausdrücklich ongoing. |
| Veralteter Validation-Regex | 1 | Erwartung wurde auf die aktuelle präzise Domainmeldung umgestellt. |
| Order-/Global-State-Effekte | 3 | Isoliert grün; der spätere reproduzierte Kontaminator war Alembics Logger-Konfiguration und ist separat test-first geschlossen. |

Summe: 70. Innerhalb dieser 70 wurde kein Produktdefekt isoliert reproduziert. Der separat entdeckte Alembic-Schema-P1 war nicht Teil der 70. Der nachfolgend im ersten Post-Fix-Gesamtlauf reproduzierte Logger-P1 wurde durch `disable_existing_loggers=False` geschlossen und ist im finalen Gesamtlauf grün bestätigt.

### Vom Referenz-Commit dokumentiert

- Vollständige Backend-Suite: **5960 grün** laut Commit-Verifikationsprotokoll vom 15.08.2026.

### Unabhängiger fokussierter Gate am 20.08.2026

- **496/496** kritische Tests grün, 0 Fehler:
  - 126 Core/Production/Stochastik/Goals/Phase 6
  - 268 Integrität/Referenzen/Current-RA/TA/Preferences/Mandate API
  - 102 Risk Override/Signaturen/Shadow-Persistenz
- zusätzlicher unabhängiger Quick-Check: **168/168** Preferences-, Risk- und Current-Integrity-Tests grün.
- `git diff --check`: grün.
- Historischer Ausgangspunkt: Der Referenz-Commit war vor Beginn des Peer-Nachlaufs clean. Die 69 Pfade des geprüften Nachlaufs sind im Anhang vollständig inventarisiert und durch den Implementierungscommit gesichert.

### Eingecheckter Peer-Review-Nachlauf

Zusätzlich bestanden die subsystembezogenen Gates für die nachträglich gefundenen P1s:

- Solver-Exception-Grenze: **46/46** fokussiert und **132/132** angrenzend.
- Preference-Werte und persistiertes JSON: **132/132** Preference, **72/72** Production/Phase 6 und **130/130** Reload/Current/MC.
- Risk-Derivation: **13/13** neue Verträge, **150/150** angrenzend, Phase-6-Zwischenlauf **38/38**, Production Contract **37/37**, DE **13/13**, Golden **7/7**, Performance **3/3**, Backtest **6/6**. Die finale komplette Phase-6-Datei mit **43** Fällen ist im `POSTFIX-GOAL-161`-Lauf enthalten.
- Current-Anchor-Migration und Rollover: **43/43**, inklusive Alembic Upgrade/Downgrade und PostgreSQL-DDL.
- Mandatsfeld-/ORM-Alembic-Parität: **33/33**, inklusive Bestandsrow-Backfill, `head → d4 → head`, vollständiger ORM-Spaltenparität und PostgreSQL-OfflinedDL.
- Alembic-Logging-Isolation: **37/37** über Migration, PDF und Telemetry; die exakt zuvor rote Reihenfolge ist grün.
- Goal-Domain und Sensitivity: **85/85** Goal-Domain, **11/11** gezielte Phase-6-Verträge sowie ein kombinierter Goal/Liability/Phase-6-Lauf mit **161/161**; positive und negative Date-Shifts, Kapitalerhalt und echter ORM-Reload sind enthalten.
- Abschließender lokaler Kernring über Solver, Preferences, Risk, Current-Anker, Migration und Production Contract: **332/332**.
- Im unabhängigen breiten Verbraucher-Erstlauf bestanden **626** Tests und **3** schlugen wegen veralteter Double-Current-Fixtures fehl. Die Tests emulieren nun ausdrücklich eine beschädigte/prä-Migrations-SQLite-Datenbank, indem sie den jeweiligen Index nur in ihrer isolierten Fixture entfernen, und prüfen weiter die Service-/PDF-Defense-in-depth. Exakter Re-Run **3/3**, vollständiger Current-/Reference-/Anchor-Ring **43/43** grün. Im geprüften Scope blieb kein bekannter P0/P1 aus diesem Gate offen.

Der finale vollständige Backend-Lauf bestätigt den Inhalt des Implementierungscommits. Er ersetzt weiterhin weder die produktionsähnliche PostgreSQL-Probe noch fachliche/Compliance-Freigabe.

Empfohlene Reproduktionsbefehle aus `5eyes-backend/`:

```powershell
python -m pytest -p no:cacheprovider tests/test_optimizer_production_contract.py tests/test_optimizer_strict_core_contract.py tests/test_optimizer_phase6.py -q
python -m pytest -p no:cacheprovider tests/test_optimizer_fail_closed_boundaries.py tests/test_optimizer_ga_fallback.py -q
python -m pytest -p no:cacheprovider tests/test_allocation_preferences_fail_closed_contracts.py tests/test_goal_domain_fail_closed_contracts.py -q
python -m pytest -p no:cacheprovider tests/test_asset_allocation_reference_integrity_edges.py tests/test_asset_allocation_current_integrity_contracts.py tests/test_asset_allocation_remaining_integrity_edges.py -q
python -m pytest -p no:cacheprovider tests/test_risk_assessment_derivation_integrity.py tests/test_risk_override.py tests/test_risk_matrix_helpers.py tests/test_cma_strict_runtime_contract.py -q
python -m pytest -p no:cacheprovider tests/test_current_anchor_uniqueness.py tests/test_alembic_baseline_migration.py -q
```

Diese sechs Befehlsgruppen sammeln im aktuellen Stand **529** Tests (`--collect-only`-Abgleich). Das ist eine Inventur, kein zusätzlicher Pass-Nachweis.

Vor Release zusätzlich:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=<EXTERNER_EINDEUTIGER_TEMP_PFAD> tests
alembic upgrade head
git diff --check
```

Für PostgreSQL muss der Migrationstest eine leere Datenbank und ein Upgrade vom vorherigen Head abdecken.

### Dokumentations-QA am 20.08.2026

- Der Manifest-Abgleich gegen `git status --porcelain` ist exakt für **69 von Git sichtbare** geänderte oder neue Pfade.
- `git status` meldet zusätzlich für **53** lokale `.pytest_tmp_*`-Verzeichnisse Windows-ACL-Zugriffsfehler. Diese Verzeichnisse gehören nicht zum Produktmanifest, sind aber noch keine global inventarisierte oder bereinigte Untracked-Fläche.
- Die kanonische Linkkette aus Repository-README, Claude-Handoff, Engine-Spec, Shadow-Entscheid, Stage-Archiv und Whitepaper über `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md` zu diesem Dokument löst vollständig auf.
- `git diff --check` ist grün.
- Drei getrennte Read-only-Gegenlesen prüften Code-/Migrationstraceability, GPT-/Claude-Verständlichkeit und Discoverability. Ihre konkreten Präzisierungen wurden eingearbeitet; danach blieb in diesen Prüfbereichen kein offenes Finding.
- Diese Dokumentations-QA ersetzt weder den vollständigen Backend-Gate noch die produktionsähnliche PostgreSQL-Migrationsprobe.

## Restpunkte und bewusste Grenzen

1. Dieses Dokument schließt die bisher fehlende konsolidierte Übergabe. Die älteren oben genannten Dokumente enthalten noch widersprüchliche Aussagen und sollten nach diesem Handoff einzeln synchronisiert werden.
2. Der finale vollständige Backend-Gate ist mit 6074 Passed, 0 Failed, 10 Skipped und 1 XFailed grün. Nicht ausgeführt wurden die vier PostgreSQL-RLS-Tests ohne `POSTGRES_TEST_DATABASE_URL`, vier manuelle Netzwerk-/Provider-Tests, ein optionaler Hypothesis-Test und ein profilabhängiger Illiquid-Cap-Test.
3. Backward-Kompatibilität alter v1-v3-Hashes kann keine damals ungehashten Felder kryptografisch nachweisen. Neue Datensätze verwenden v4 und den Artefaktmarker.
4. Die Migrationen `d4e8f1a9c2b7` und `f2a7c91e4b63` müssen vor Deployment auf produktionsähnlichen PostgreSQL-Bestandsdaten ausgeführt werden. Vorhandene doppelte Current-Anker werden bewusst nicht automatisch bereinigt, sondern blockieren das Upgrade zur manuellen Klärung.
5. Die nach dem Referenz-Commit entstandenen Peer-Review-Fixes sind im Implementierungscommit `661fe73c` gesichert. Der grüne Gate bezieht sich exakt auf den inventarisierten 69-Pfade-Inhalt dieses Commits.

## Definition of Done und Freigabekriterien

Der dokumentierte Stand ist fachlich und technisch im geprüften Scope konsistent, aber noch **nicht releasefähig**. Eine Freigabe darf erst erfolgen, wenn alle offenen Punkte dieser Liste nachweisbar abgeschlossen sind:

- [x] Stochastischer Produktionspfad, Fail-closed-Grenzen und auditierter House-Fallback sind implementiert und fokussiert getestet.
- [x] Snapshot-/Replay-, Goal-, Preference-, Risk- und Current-Anchor-Verträge sind dokumentiert und regressionsgetestet.
- [x] Alembic-Kette ist linear; erwarteter Head ist `f2a7c91e4b63`; lokaler Migration-/Schema-Re-Gate 33/33.
- [x] Die 70 Fehler des Pre-Fix-Full-Gates sind vollständig klassifiziert und die korrigierten Fixture-Ringe 70/70 beziehungsweise 58/58 grün.
- [x] Finaler vollständiger Backend-Gate: 6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings, 1681.86 s.
- [x] Dieses Handoff ist über `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`, das Repository-README und die historischen Einstiegspunkte auffindbar.
- [ ] Die 53 ACL-blockierten `.pytest_tmp_*`-Verzeichnisse werden von einem autorisierten Operator kontrolliert geprüft/bereinigt oder in einem neuen Clean-Worktree umgangen; kein `git add .` oder `git add -A` verwenden.
- [x] Alle 69 im Anhang inventarisierten Änderungen wurden explizit nach Pfad gestaged, reviewed und als Implementierungscommit `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4` gesichert. Dieser nachgelagerte reine Evidenz-/Dokumentationscommit trägt dessen Hash als `covered_implementation_commit`; der Hash des Dokuments selbst wird extern über Git ermittelt.
- [ ] Die Migration wird auf einer produktionsähnlichen PostgreSQL-Kopie inklusive Duplicate-Preflight, Backup, Upgrade, Indexprüfung, Applikations-Smoke und Rollbackprobe erfolgreich geprobt.
- [ ] Für konkurrierende Current-Anker wird mindestens ein echter Zwei-Transaktionen- oder HTTP-Test ausgeführt und die unterlegene Anfrage kontrolliert als 409/Retry-Vertrag behandelt.
- [ ] Sekundäre Dokumente mit altem House-/Fallback-/Objective-Vertrag werden inhaltlich synchronisiert oder dauerhaft deutlich als historisch markiert.
- [ ] Investment/Compliance beziehungsweise der fachlich zuständige Owner bestätigt die Modell- und Deploymentänderung.

Erst wenn alle offenen Kästchen geschlossen sind, darf `release_decision` im Frontmatter auf `approved` geändert werden. Ein grüner fokussierter Testlauf allein genügt dafür nicht.

## Guardrails – niemals ohne bewusste neue Fachentscheidung ändern

- Den geprüften Implementierungscommit nicht mit `git reset --hard`, Checkout oder Teil-Restore entkoppeln; er enthält die test-first Peer-Review-Nachfixes.
- Production niemals auf `house_matrix`, `shadow_stochastic` oder `iterative` umstellen. House bleibt ein klassifizierter Sicherheitsfallback, kein wählbares Entscheidungsmodell.
- Domain-, CMA-, FX-, Steuer-, Mortalitäts-, Referenz-, Snapshot-, Hash- oder DB-Fehler niemals in einen House-Fallback oder Defaultwert umdeuten.
- Eine moderne TargetAllocation niemals mit einer aktuellen Ersatz-CMA, Ersatz-Policy oder einem neuen RiskAssessment analysieren. Snapshot-Anker müssen exakt passen oder der Pfad endet fail-closed.
- Doppelte Current-Anker niemals automatisch löschen, zusammenführen oder anhand der jüngsten ID „gewinnen“ lassen. Erst fachlich klären, dann kontrolliert bereinigen.
- Golden Snapshots niemals blind rebaselinen. Zuerst deterministischen Seed, CMA-ID, Modellversion und fachliche Ursache prüfen.
- Fehlende oder ungültige Inputs nicht durch Hardcodes, Truthiness-Coercion, leere Dicts oder stilles JSON-Fallback ersetzen.
- Direkte Immobilien nicht als investierbares Advisory-SAA-Exposure modellieren; externe Immobilie, Listed Real Estate und Mietertrag bleiben getrennte Verträge.
- Optimization- und Reporting-Wahrscheinlichkeiten nicht als dieselbe Modellwahrheit darstellen. Ihre Basis-IDs und Modellannahmen bleiben getrennt sichtbar.
- Hash-, Model-basis-, Momenten- oder Objective-Semantik nicht ohne neue Versionskennung, Migrations-/Replay-Entscheidung und Regressionstests ändern.
- Die Partial-Unique-Indizes nicht entfernen, um fehlerhafte Bestandsdaten „durchzubringen“. Test-Fixtures dürfen sie nur lokal und ausdrücklich zur Prüfung der Defense-in-depth entfernen.

## Glossar

| Begriff | Bedeutung in diesem Dokument |
|---|---|
| **CMA** | Capital Market Assumptions: versionierte Rendite-, Volatilitäts-, Korrelations- und erweiterte Modellannahmen. |
| **SAA** | Strategic Asset Allocation: strategische Zielgewichte und Bänder. |
| **RA** | RiskAssessment, der verankerte Risikoprofil-Entscheid. |
| **TA** | TargetAllocation, der persistierte Strategieentscheid mit Policy-, CMA-, Assessment- und Context-Ankern. |
| **Modernes Artefakt** | Nach Einführung des Context-Markers erzeugte TA mit `context_artifacts_required=1`; vollständige Artefakte und Snapshot-CMA sind Pflicht. |
| **Legacy-Artefakt** | Nachweisbar prä-migrativer Datensatz mit Marker `0`, für den nur explizit dokumentierte Kompatibilität gilt. „Artefakte wurden gelöscht“ macht keinen modernen Datensatz zu Legacy. |
| **Retained OptimizerContext** | Der konkrete, unveränderliche Solverkontext, in dem Kandidat, Objective, Constraints und gegebenenfalls House-Fallback bewertet werden. |
| **Fail-closed** | Bei ungültigem oder unbeweisbarem Zustand wird keine neue Strategie, Analyse oder PDF-Ersatzwahrheit veröffentlicht. |
| **Technischer Fallback** | Auditierter House-Pfad ausschließlich für klassifizierte technische/numerische Solverzustände; bei vorhandenem Context nur nach erneuter Feasibility-Prüfung. |
| **Model basis** | Versionierter Metadatenvertrag, der Zweck, Dynamik, Renditemaß, Tail-/Tax-/Kostenbasis und Herkunft einer Kennzahl erklärt. |
| **Snapshot/Replay** | Rekonstruktion eines gespeicherten Entscheids ausschließlich aus seinen gebundenen Ankern und verifizierten Hash-/Context-Artefakten. |
| **Current-Anker** | Die DB erlaubt höchstens ein nicht gelöschtes aktuelles RA und TA je Mandat sowie höchstens eine globale aktuelle OptimizerPolicy; strategie-konsumierende Exact-One-Resolver verlangen zusätzlich deren Existenz. |

## Startcheckliste für den nächsten GPT-/Claude-Review

1. Repository und Branch prüfen; Referenz-Commit mit diesem Dokument vergleichen.
2. `git status --short` und `git diff --check` ausführen.
3. Alembic-Head und ORM-Spaltenparität prüfen.
4. Sicherstellen, dass Production nur `stochastic` akzeptiert.
5. House-Fallback-Catch auf die technische Allowlist prüfen.
6. Einen Generate-Reload-Roundtrip inklusive Context-Hash und Snapshot-CMA testen.
7. Einen absichtlich manipulierten Context, eine gelöschte Snapshot-CMA und doppelte Current-Anker fail-closed testen.
8. Sensitivity mit gemeinsamem Szenariopfad, vollständigen Cashflows, FX-Signatur und unveränderter ORM-Zeile testen.
9. Optimization- und Reporting-Model-Basis getrennt prüfen.
10. Erst nach grünem Gate fachliche Golden Snapshots bewusst rebaselinen; niemals blind aktualisieren.

## Anhang A – Manifest des Implementierungscommits

Die folgende Inventur ist Bestandteil der Übergabe. Sie beschreibt die 69 Pfade des am 25.08.2026 erstellten Implementierungscommits `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4`. Eine Abweichung bei späteren Änderungen muss über `git status --short`, den tatsächlichen Diff und die Commit-Historie erklärt werden.

### Produktionscode, Schema und Migration

- `5eyes-backend/5eyes_schema_v4.0_FINAL.sql`
- `5eyes-backend/alembic/env.py`
- `5eyes-backend/database.py`
- `5eyes-backend/models/allocation.py`
- `5eyes-backend/models/mandates.py`
- `5eyes-backend/models/profiling.py`
- `5eyes-backend/routers/allocation.py`
- `5eyes-backend/routers/profiling.py`
- `5eyes-backend/schemas/allocation.py`
- `5eyes-backend/services/goal_semantics.py`
- `5eyes-backend/services/optimizer/solver.py`
- `5eyes-backend/services/portfolio_engine.py`
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py`
- `5eyes-backend/services/risk_assessment_semantics.py`
- `5eyes-backend/alembic/versions/d4e8f1a9c2b7_current_anchor_unique_indexes.py` *(neu)*
- `5eyes-backend/alembic/versions/f2a7c91e4b63_mandate_tax_cashflow_flag.py` *(neu)*

### Regressionstests und fachlich korrigierte Fixtures

- `5eyes-backend/tests/risk_fixture_helpers.py`
- `5eyes-backend/tests/test_advisory_report.py`
- `5eyes-backend/tests/test_alembic_baseline_migration.py`
- `5eyes-backend/tests/test_allocation_preferences_fail_closed_contracts.py`
- `5eyes-backend/tests/test_ar2_persist_mc_risk_kpis.py`
- `5eyes-backend/tests/test_asset_allocation_current_integrity_contracts.py`
- `5eyes-backend/tests/test_asset_allocation_reference_integrity_edges.py`
- `5eyes-backend/tests/test_asset_allocation_remaining_integrity_edges.py`
- `5eyes-backend/tests/test_audit_b4_goal_base_consistency.py`
- `5eyes-backend/tests/test_audit_b6_mandate_score.py`
- `5eyes-backend/tests/test_audit_f23_mc_total_paths.py`
- `5eyes-backend/tests/test_audit_f3_cma_drift.py`
- `5eyes-backend/tests/test_audit_quick_fixes.py`
- `5eyes-backend/tests/test_audit_z1_strategy_gates.py`
- `5eyes-backend/tests/test_audit_z5_strategy_base.py`
- `5eyes-backend/tests/test_audit_z6_anchors.py`
- `5eyes-backend/tests/test_audit_z7_strategy_context.py`
- `5eyes-backend/tests/test_audit_z8_lifegap_series.py`
- `5eyes-backend/tests/test_backtest_ab.py`
- `5eyes-backend/tests/test_chance_constraint.py`
- `5eyes-backend/tests/test_daily_market_data_refresh.py`
- `5eyes-backend/tests/test_de_onboarding_integration.py`
- `5eyes-backend/tests/test_depot_check.py`
- `5eyes-backend/tests/test_e2e_full_pipeline_smoke.py`
- `5eyes-backend/tests/test_engine_de_jurisdiction_wiring.py`
- `5eyes-backend/tests/test_finalize_rejects_non_current_policy_and_cma.py`
- `5eyes-backend/tests/test_goal_domain_fail_closed_contracts.py`
- `5eyes-backend/tests/test_golden_snapshot_ch_regression.py`
- `5eyes-backend/tests/test_kapitalschutz_risk_budget_regression.py`
- `5eyes-backend/tests/test_optimizer_fail_closed_boundaries.py`
- `5eyes-backend/tests/test_optimizer_ga_fallback.py`
- `5eyes-backend/tests/test_optimizer_integration.py`
- `5eyes-backend/tests/test_optimizer_phase6.py`
- `5eyes-backend/tests/test_optimizer_runs.py`
- `5eyes-backend/tests/test_optimizer_shadow_mode.py`
- `5eyes-backend/tests/test_performance_budget.py`
- `5eyes-backend/tests/test_reference_data_fail_closed_gates.py`
- `5eyes-backend/tests/test_reserve_explainability_section.py`
- `5eyes-backend/tests/test_restriktionen_tilts_audit_fixes.py`
- `5eyes-backend/tests/test_risk_budget_cap.py`
- `5eyes-backend/tests/test_sequence_of_returns_depletion.py`
- `5eyes-backend/tests/test_sprint_a_quick_wins.py`
- `5eyes-backend/tests/test_suitability_optin_gate.py`
- `5eyes-backend/tests/test_current_anchor_uniqueness.py` *(neu)*
- `5eyes-backend/tests/test_risk_assessment_derivation_integrity.py` *(neu)*

### Dokumentation und Discoverability

- `README.md`
- `docs/CLAUDE_HANDOFF.md`
- `docs/decisions/SHADOW_STOCHASTIC_DEFAULT.md`
- `docs/engine-spec.md`
- `docs/gpt_stage_notes_archive/README.md`
- `docs/whitepaper/2026-07-19-5eyes-methodik-whitepaper.md`
- `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md` *(neu, stabiler Einstiegspunkt)*
- `docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md` *(neu, dieses Dokument)*

Die ACL-blockierten `.pytest_tmp_*`-Verzeichnisse gehören nicht zum Produktmanifest. Da Git ihren Inhalt nicht lesen konnte, darf jedoch nicht behauptet werden, ihr Zustand sei vollständig inventarisiert. Vor einem globalen Clean-Claim müssen sie unter explizit geprüftem Pfad kontrolliert bereinigt oder in einem neuen Clean-Worktree umgangen werden. Nicht blind rekursiv löschen und niemals mit `git add .` oder `git add -A` stagen.

## Anhang B – verbleibender Dokument-Synchronisierungsbedarf

Die zentralen Einstiegspunkte enthalten jetzt einen deutlichen Verweis auf dieses Handoff. Folgende Dokumente benötigen dennoch einen separaten inhaltlichen Sync, bevor sie wieder als eigenständige aktuelle Methodikquelle gelten können:

| Dokument | Verbleibender Bedarf |
|---|---|
| `docs/engine-spec.md` | alte Objective-, Default- und „offen“-Abschnitte vollständig auf den versionierten stochastischen Vertrag bringen; Warnhinweis ist bereits gesetzt |
| `docs/whitepaper/2026-07-19-5eyes-methodik-whitepaper.md` | House-/Shadow-Default und Korrelationsfallback fachlich neu schreiben; aktueller Nicht-Produktionshinweis ist gesetzt |
| `docs/CLAUDE_HANDOFF.md` | historische Bereiche weiter bereinigen; aktueller Optimizer-Hinweis und korrigierter Goal-Spec-Link sind gesetzt |
| `docs/BERATER_README.md` | sichtbare Begriffe für Optimizer-P und Pfaderfolg sowie House-Fallback-Status synchronisieren |
| `docs/BERATER_ONBOARDING.md` | produktiven Stochastikpfad, Fail-closed-Reaktionen und nötige Datenkorrekturen aufnehmen |
| `docs/GLOSSAR.md` | CMA, retained Context, Model-basis, Snapshot/Replay und technischen House-Fallback definieren |

Bis zum vollständigen Sync gilt bei Widersprüchen die am Dokumentanfang definierte Quellenrangfolge. Historische Planning-/Stage-Dokumente werden nicht still umgeschrieben, sondern bleiben als zeitgebundene Entscheidungsbelege erhalten.

## Kurzurteil zum Claude-Commit

Die Kernumsetzung des Commits `ea53a63b` ist architektonisch konsistent: Production-Default, Momentenmodell, Snapshot-/Replay-Vertrag und der stochastische Hauptpfad sind sauber. Der unabhängige Review zeigte jedoch, dass die ursprüngliche Aussage „vollständig fail-closed“ an mehreren Randgrenzen noch zu weit ging. Der Peer-Review-Nachlauf schloss diese P1s test-first; die Fixes sind in `661fe73c` gesichert. Dieses Dokument ist deshalb die maßgebliche Übergabe für den Stand aus Referenz-Commit **plus** Nachlauf; ältere widersprüchliche Dokumente bleiben ausdrücklich nachzuziehen.
