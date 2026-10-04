---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-mixed-goal-sensitivity-objective-evidence-integrity-followup-audit"
status_as_of: "2026-09-28"
audit_started_on: "2026-09-27"
audit_completed_on: "2026-09-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "dd3ed657ed596ff16930c9687a13449050f4ac45"
prior_solver_audit_path: "docs/audits/2026-09-23-solver-goal-maximization-and-publication-integrity-audit.md"
prior_core_audit_path: "docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
prior_goal_publication_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
audit_mode: "read_only_static_mixed_goal_chance_constraint_sensitivity_objective_serialization_configuration_hash_and_publication_review_plus_deterministic_python_and_javascript_reproductions_and_focused_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "mixed-goal shortfall and chance-constraint ordering, objective weighting mode, objective serialization precision, goal sensitivity counterfactuals, status gating, typed target units, API/Classic-UI/React contract and forensic evidence"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 3
confirmed_prior_p1_extension_groups: 6
new_hardening_p2_count: 0
deterministic_reproduction_groups: 4
focused_existing_tests_passed: 175
focused_existing_tests_skipped: 0
focused_existing_tests_failed: 0
focused_existing_test_runs_confirmed: 1
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "freeze real-advice sensitivity publication; replace the obsolete milli-rappen-squared serializer with a versioned lossless dimensionless objective representation and raw-value delta calculation; introduce a discriminated target/result contract with feasibility-aware status gating and immutable sensitivity evidence; validate and freeze goal-weighting configuration into optimizer context, model basis and every relevant hash; replay or quarantine ambiguous legacy evidence"
---

# Mixed-Goal-, Sensitivitäts-, Objective-Evidence- und Publikationsintegritätsaudit

## Geltung, Abgrenzung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die sechsunddreißigste Read-only-
Kontrollrunde. Geprüft wurde der unveränderte Repository-Head
`dd3ed657ed596ff16930c9687a13449050f4ac45`. Produktcode, Tests,
Migrationen und Runtime-Konfiguration wurden nicht verändert. Nach Abschluss
der Prüfung werden ausschließlich die fünf Pfade des Dokumentationsmanifests
angepasst.

Die Runde konzentriert sich auf das Herzstück der Zieloptimierung:

1. Shortfall- und Chance-Constraint-Verhalten in gemischten Zielsets,
2. Gleichgewichtung versus optionale Hardness-Gewichtung,
3. Bindung der verwendeten Objective-Methodik an Run und Hash,
4. Serialisierung der seit der Normalisierung dimensionslosen Objective,
5. Goal-Sensitivity als gepaarter Baseline-/Gegenfaktumlauf,
6. Einheiten- und Statusvertrag der Sensitivity-Response,
7. Classic UI, React-Typvertrag und forensische Audit-Evidence.

Dieser Audit ersetzt keine bestehende Finding-ID. `GOAL-SCORE-001 /
ZERO-WEIGHT` und `GOAL-SCORE-001 / HARDNESS-ONCE` bleiben die allgemeinen
Verträge für Zielgewicht und genau einmal angewandte Hardness.
`GOAL-PUBLICATION-001`, `GOAL-SNAPSHOT-001` und `REP-001` bleiben die
allgemeinen Verträge für kanalgleiche, unveränderliche und rungebundene
Goal-Evidence. Drei neue IDs grenzen neue Fehler präzise ab:

- `GOAL-SENSITIVITY-PUBLICATION-001` betrifft den untypisierten Zielwert und
  die statusblinde Was-wenn-Aussage;
- `OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001` betrifft die verlustbehaftete,
  semantisch veraltete Objective-Serialisierung;
- `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001` betrifft die nicht validierte und
  nicht an Context, Hash oder Run gebundene Objective-Gewichtungsmethode.

Aktueller Code und ausgeführte Reproduktionen haben Vorrang. Planning-
Dokumente dienen nur als Soll-Anker. Grüne Bestandstests beweisen vorhandene
Positivkontrollen; sie widerlegen keine nicht assertierten Gegenbeispiele.

## Kurzurteil

Die Runde bestätigt **drei neue release-blockierende P1**.

**`GOAL-SENSITIVITY-PUBLICATION-001`:** Die Response besitzt zwar separate
`target_return_bps_*`-Felder, schreibt bei einem Renditeziel dieselben
Basispunkte zusätzlich in das Pflichtfeld `target_amount_rappen_*`. Die
Classic UI erzeugt den Slider für jede Goal-Analysezeile und rendert ausnahmslos
`target_amount_rappen_new / 100` als CHF. Ein Renditeziel von 500 bps mit
`+20 %` wird dadurch als `CHF 6` statt als `6.00 % p.a.` angezeigt. Dieselbe
UI ignoriert `status_baseline` und `status_new`; ein `diverged`,
`diverged_infeasible` oder unsynchronisierter Fallback kann dennoch eine
Objective-Richtung „besser erreichbar“ oder „schwerer erreichbar“ erzeugen.
Der Endpoint liefert solche Statuswerte regulär mit HTTP 200, und ein
Bestandstest erlaubt sie ausdrücklich. Die Auditzeile speichert lediglich
Goal-ID und Target-Delta, nicht Horizon-Delta, Status, Hash, Gewichte,
Objective oder das tatsächlich angezeigte Resultat.

**`OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001`:** Das primäre Shortfall-
Objective wurde auf eine dimensionslose Größe normalisiert. Die Persistenz
verwendet aber weiterhin den historischen Vertrag
`int(round(objective * 1000))`, dessen Kommentare und Planning-Spezifikation
noch von „milli-rappen²“ ausgehen. Jeder positive Wert unter `0.0005` wird zu
null; wegen Ties-to-even kann auch `0.0005` zu null werden. Die ausgeführten
Beispiele zeigen: `0.0001 -> 0` und `0.0002 -> 0`, sodass ein wahrer Anstieg
von 100 Prozent als `None` veröffentlicht wird. `0.0006 -> 1` und
`0.0014 -> 1`, sodass ein wahrer Anstieg von 133.33 Prozent als `0.0 %`
erscheint. Das betrifft Sensitivity, `TargetAllocation`, `OptimizerRun`,
Goal-Driver und den Classic-UI-Auditfooter. Positive Objectives und Beiträge
werden damit von echter Null ununterscheidbar.

**`OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001`:** Die Objective liest
`OPTIMIZER_GOAL_WEIGHTING` direkt und dynamisch aus `os.environ`. Nur der
exakte normalisierte Wert `hardness` aktiviert 10/1/0.2; jeder unbekannte Wert
fällt still auf Gleichgewichtung. Im Repro hatten ein hartes und ein
opportunistisches Ziel bei unset den Faktor 1, bei `hardness` den Faktor 50
und beim Tippfehler `hardnes` wieder den Faktor 1. Diese entscheidungsrelevante
Methodik fehlt in zentraler Settings-Validierung, OptimizerContext,
`optimization_model_basis`, `allocation_context_hash`, Sensitivity-
`model_input_hash` und `OptimizerRun`. Zwei Sensitivity-Läufe können daher
denselben deklarierten Input-Hash tragen, obwohl sie unterschiedliche
Objective-Mathematik verwenden. Ein gespeicherter Allocation-Run kann nicht
beweisen, welche der beiden akzeptierten Methoden ihn erzeugt hat.

Die Chance-Constraint-Formel selbst folgt im geprüften Stand dem akzeptierten
Soft-Strict-Vertrag: IS-Likelihood-Gewichte werden angewandt, harte und primäre
Ziele zahlen bei `p < tau` die quadratische Penalty, opportunistische und
targetlose Maximierungsziele nicht. Es wurde dort kein zusätzlicher isolierter
Finding neben den bereits offenen Zero-Weight-, Conditional-, Status-,
Maximierungs- und Zwei-Phasen-Verträgen behauptet. Insbesondere bleibt aber
ungeklärt, ob ein Ziel mit explizitem Nullgewicht weiterhin eine Chance-
Penalty auslösen soll; das ist bereits `GOAL-SCORE-001 / ZERO-WEIGHT`.

Es wurde kein neuer P0 bestätigt. Die Releasefreigabe bleibt wegen dieser drei
P1 und der bereits offenen P1 ausgeschlossen.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `GOAL-SENSITIVITY-PUBLICATION-001` | P1 | neu bestätigt | Rendite-bps werden zusätzlich als Rappen ausgegeben und im Classic UI als CHF gerendert; Solverstatus und Feasibility begrenzen die Aussage nicht. |
| `OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001` | P1 | neu bestätigt | Der historische Faktor 1.000 kollabiert dimensionslose Objectives und Goal-Beiträge auf null beziehungsweise identische Integer; Sensitivity-Deltas werden daraus falsch oder fehlen. |
| `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001` | P1 | neu bestätigt | `equal` versus `hardness` verändert die Objective bis Faktor 50, ist aber weder validiert noch in Context, Model-Basis, Hash oder Run-Evidence gebunden. |
| `GOAL-SCORE-001 / ZERO-WEIGHT` | P1 | offen, erneut bestätigt | Shortfall erzwingt mindestens 1 bps Gewicht; Chance-Penalty ignoriert Zielgewicht. Die Semantik eines expliziten Nullgewichts bleibt consumerabhängig. |
| `GOAL-SCORE-001 / HARDNESS-ONCE` | P1 | offen, neue Evidence | Der optionale Optimizer-Hardnessmodus ist nicht versioniert und darf nicht mit der bereits separat fehlerhaften Reporting-Hardness verkettet werden. |
| `GOAL-PUBLICATION-001` / `GOAL-SNAPSHOT-001` / `REP-001` | P1 | offen, neue Evidence | Sensitivity ist flüchtige Live-Evidence; die Auditzeile beweist nur den Request, nicht Context, Resultat oder Anzeige. |
| `SOLVER-BPS-APPORTIONMENT-001` | P1 | offen, neue Evidence | Sensitivity gibt einen `diverged_infeasible`-Kandidaten direkt aus, statt wie der Hauptpfad das tatsächlich aktive Fallback zu synchronisieren. |
| `OPTIMIZER-TWO-PHASE-OBJECTIVE-001` | P1 | offen, neue Evidence | Objective-Version, Volatilitätsgewicht, Epsilon und Chance-Lambda fehlen ebenfalls in der rungebundenen Methodenevidence. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
OPTIMIZER_GOAL_WEIGHTING aus os.environ
          |
          +-- unset / Tippfehler --------> equal
          |
          +-- hardness ------------------> 10 / 1 / 0.2
          |
          v
unterschiedliche Shortfall-Objective
          |
          +--> nicht in OptimizerContext / model basis / run evidence
          +--> nicht in allocation_context_hash
          +--> nicht in sensitivity model_input_hash

raw dimensionless objective
          |
          v
int(round(value * 1000))
          |
          +--> kleine positive Werte werden 0
          +--> verschiedene Werte werden gleich
          |
          +--> TargetAllocation / OptimizerRun / Goal-Driver / UI
          |
          +--> Sensitivity berechnet Delta aus den gerundeten Integern

Renditeziel 500 bps, Delta +20 %
          |
          v
target_return_bps_new = 600
target_amount_rappen_new = 600
          |
          v
Classic UI teilt durch 100 und schreibt "CHF 6"

status_new = diverged_infeasible
          |
          +--> API 200
          +--> UI ignoriert Status
          +--> Objective-Richtung kann wie belastbare Beratung wirken
```

Die drei Fehler liegen damit nicht nur in der Darstellung. Methodik,
Evidence-Serialisierung und Ergebnisfreigabe sind voneinander entkoppelt.

## Positivkontrollen, die erhalten bleiben müssen

1. Baseline und Gegenfaktum verwenden innerhalb eines Sensitivity-Aufrufs
   denselben gepinnten Seed.
2. Bei unterschiedlichen Horizonten werden gemeinsame Pfade aus demselben
   maximalen Szenariowürfel als exakte Präfixe verwendet.
3. Der Live-Context bindet CMA, aktuelle Vermögensbasis, Cashflows, Inflation,
   externe Vermögensserie, Goal-Snapshot, Bounds, Risky Fractions, Steuer-,
   Mortalitäts- und FX-Basis in die beiden Sensitivity-Input-Hashes.
4. Die Response exponiert Baseline- und Modified-Hash getrennt.
5. `target_return_bps_baseline/new` existieren bereits im Backend-Schema und
   müssen als typisierte Quelle erhalten bleiben.
6. `status_baseline/new` existieren bereits und dürfen künftig nicht nur
   informativ sein, sondern müssen die Publizierbarkeit steuern.
7. Ziel-ID gehört fail-closed zum Mandat; unbekannte Ziele liefern 404.
8. Target-Delta ist auf die fünf vorgesehenen Stufen beschränkt; Horizon-
   Delta ist begrenzt.
9. Chance Probability verwendet bei Importance Sampling die Likelihood-
   Gewichte und validiert Shape sowie positive Gewichtssumme.
10. Shadow-Methodenvergleich berechnet sein Prozentdelta bereits aus den
    rohen Float-Werten vor der Integerdarstellung. Dieser richtige Teil darf
    bei der Vereinheitlichung nicht auf gerundete Werte zurückgebaut werden.
11. Die Zielreihenfolge der Goal-Driver wird vor der Serialisierung aus den
    rohen Beiträgen ermittelt; künftig müssen auch die sichtbaren Werte diese
    Rangfolge numerisch belegen können.
12. Die Classic UI reaktiviert die fünf Sensitivity-Buttons nach Erfolg und
    Fehler in einem gemeinsamen `Promise.finally()`-Pfad.

## Codeanker des auditierten Stands

### Sensitivity-Service, Schema und Endpoint

- `5eyes-backend/services/portfolio_engine.py:5214-5263` baut den
  Sensitivity-Input-Hash. Goal-Weighting- und Objective-Vertragsversion fehlen.
- `5eyes-backend/services/portfolio_engine.py:5276-5315` führt Baseline und
  Gegenfaktum über `run_solver()` aus.
- `5eyes-backend/services/portfolio_engine.py:5317-5331` rundet zuerst beide
  Objectives auf `value * 1000` als Integer und berechnet erst danach das
  Prozentdelta.
- `5eyes-backend/services/portfolio_engine.py:5333-5338` wählt für das
  generische Pflichtfeld den ersten truthy Wert aus Betrag, Vermögensziel oder
  Rendite-bps.
- `5eyes-backend/services/portfolio_engine.py:5372-5382` schreibt dadurch bei
  Renditezielen bps in `target_amount_rappen_*`, liefert daneben die korrekt
  benannten Return-Felder und gibt Solvergewichte und Status unverändert aus.
- `5eyes-backend/schemas/allocation.py:1069-1102` besitzt kein
  `goal_type`, `target_kind`, `target_unit`, Feasibility- oder
  discriminated-result-Feld. `target_amount_rappen_*` ist für jeden Zieltyp
  Pflicht.
- `5eyes-backend/routers/allocation.py:544-588` liefert das Resultat mit HTTP
  200 und schreibt als „FINMA-Trace“ nur Goal-ID und `target_delta_pct`.
  `horizon_delta_years`, beide Input-Hashes, Seed, Status, Objective und
  angezeigtes Resultat werden nicht gespeichert.
- `5eyes-backend/tests/test_optimizer_phase6.py:1187-1196` akzeptiert im
  erfolgreichen Endpointtest ausdrücklich `converged`,
  `converged_robustified`, `diverged`, `diverged_infeasible` oder
  `fallback_house_matrix` als `status_new`.
- `5eyes-backend/tests/test_optimizer_phase6.py:722-772` bestätigt zwar für
  500 bps und `+20 %` das korrekte Return-Feld 600, assertiert aber nicht, dass
  das generische Amount-Feld und die UI ihre Einheit korrekt behandeln.

### Classic UI und React-Vertrag

- `5eyes-electron/frontend/5eyes_v2.html:27284-27318` erzeugt einen Slider für
  jede Zeile aus `result.goal_analysis`; Zieltyp und Einheit werden nicht in
  den Buttonvertrag übernommen.
- `5eyes-electron/frontend/5eyes_v2.html:27321-27341` teilt
  `target_amount_rappen_new` immer durch 100, präfixiert immer `CHF` und leitet
  besser/schlechter ausschließlich aus dem Vorzeichen von
  `delta_objective_pct` ab. Beide Statusfelder werden ignoriert.
- `5eyes-electron/frontend/5eyes_v2.html:27342-27346` reaktiviert die zuvor
  deaktivierten Buttons korrekt in `Promise.finally()`; diese Positivkontrolle
  ist bei einer UI-Umstellung zu erhalten.
- `5eyes-electron/frontend/reporting/src/api/types.ts:1039-1052` führt nur den
  alten Amount-/Objective-/Statusvertrag. Return-bps, Horizon-Baseline/-Neu,
  Solverhorizonte, Context-/Input-Hashes, Pairing-, FX-, CMA-, Wealth-,
  Constraint- und Foundation-Basis des Backend-Schemas fehlen.
- `5eyes-electron/frontend/reporting/src/api/allocation.test.ts:121-127`
  prüft nur URL, Request und `delta_pct`, nicht die Response-Semantik.

### Objective-Serialisierung

- `5eyes-backend/services/optimizer/objective.py:126-151` normalisiert
  Rappen-Shortfalls auf eine gemeinsame Context-Skala; das produktive
  Objective ist damit dimensionslos.
- `5eyes-backend/services/portfolio_engine.py:2206-2209` beschreibt den
  Persistenz-Cap weiterhin mit historischem `rappen^2`-Overflow.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:666-690`
  serialisiert die aktive Allocation-Objective mit Faktor 1.000 und
  Integer-Rundung.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:725-736`
  wiederholt denselben Konverter für Methodenvergleich, Goal-Driver und
  OptimizerRun.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:1183-1207`
  rankt Goal-Beiträge roh, publiziert ihren Zahlenwert aber nur nach der groben
  Milli-Rundung.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:1323-1345`
  persistiert den gerundeten Wert in `OptimizerRun`.
- `5eyes-backend/models/allocation.py:112-118` und `:174-188` speichern nur
  das Integerfeld ohne Objective-Version, Einheit oder Skala.
- `5eyes-electron/frontend/5eyes_v2.html:27128-27138` zeigt die gerundeten
  Goal-Driver-Zahlen; `:27236-27241` teilt die gespeicherte Objective wieder
  durch 1.000 und kann einen positiven Wert als `0.000e+0` ausgeben.
- `docs/planning/2026-05-05-stochastic-optimizer-spec.md:211-218` nennt das
  Feld ausdrücklich „milli-rappen²“. Dieser Kommentar ist seit der
  dimensionslosen Normalisierung semantisch veraltet.

### Zielgewichtungs- und Chance-Constraint-Vertrag

- `5eyes-backend/services/optimizer/objective.py:51-69` liest
  `OPTIMIZER_GOAL_WEIGHTING` direkt aus `os.environ`; unbekannte Werte werden
  nicht abgelehnt und wirken wie `equal`.
- Die Repository-Suche findet diesen Konfigurationsschlüssel außerhalb von
  Tests und Methodikdokumenten nur in `objective.py`; er ist kein zentral
  validiertes Setting.
- `5eyes-backend/services/optimizer/objective.py:409-479` wendet die Methode
  im primären Shortfall an. `max(1, weight_bps)` hält zugleich den bereits
  offenen Zero-Weight-Befund aufrecht.
- `5eyes-backend/services/optimizer/objective.py:335-406` berechnet die
  Chance-Penalty mit gewichteter Probability und konstantem Lambda, aber ohne
  Goal-Weight. Das entspricht dem akzeptierten Soft-Strict-Vertrag; die
  Nullgewicht-Semantik bleibt dennoch explizit zu entscheiden.
- `5eyes-backend/services/portfolio_engine.py:2650-2729` beschreibt die
  Optimizer-Modellbasis, enthält aber weder Goal-Weighting-Modus noch
  Objective-Version, Normalisierung, Chance-Lambda, Volatilitätsgewicht oder
  Phasen-Epsilon.
- `5eyes-backend/services/portfolio_engine.py:3937-3988` bindet diese
  unvollständige Modellbasis in den Allocation-Context-Hash.
- `5eyes-backend/services/portfolio_engine.py:5214-5263` lässt dieselben Felder
  auch im Sensitivity-Input-Hash aus.
- `docs/adr/ADR-011-engine-methodik-2026-06.md:25-28` akzeptiert `equal` als
  Default und `hardness` als Opt-in. Der Audit beanstandet nicht diese
  Owner-Entscheidung, sondern ihre fehlende Validierung und Evidence-Bindung.

## Deterministische Reproduktionen

### Repro A: Renditeziel wird CHF

Der bestehende Return-Goal-Test liefert für 500 bps und `+20 %`:

```text
target_return_bps_baseline = 500
target_return_bps_new      = 600
```

Die produktive Fallbackauswahl des generischen Felds liefert zugleich:

```text
target_amount_rappen_baseline = 500
target_amount_rappen_new      = 600
```

Der unveränderte Classic-UI-Ausdruck wurde mit diesem Body ausgeführt:

```json
{
  "target_amount_rappen_new": 600,
  "target_return_bps_new": 600,
  "delta_objective_pct": 0,
  "status_baseline": "converged",
  "status_new": "diverged_infeasible"
}
```

Ergebnis:

```text
Neuer Zielwert: CHF 6 | Objective +0.0%
```

Der vorhandene korrekte Returnwert und der infeasible Status wurden nicht
verwendet.

### Repro B: Objective-Delta kollabiert

Die produktive Konversion `round(value * 1000)` ergibt:

| Raw Baseline | Raw Neu | Wahres Delta | Gespeichert Baseline/Neu | Publiziertes Delta |
|---:|---:|---:|---:|---:|
| `0.0001` | `0.0002` | `+100.00 %` | `0 / 0` | `None` |
| `0.0006` | `0.0014` | `+133.33 %` | `1 / 1` | `0.00 %` |
| `0.00049` | `0.00051` | `+4.08 %` | `0 / 1` | `None` |

Die direkte Ausführung des produktiven `_objective_to_milli()` bestätigte
zusätzlich:

```text
4e-12  -> 0
4e-06  -> 0
4e-05  -> 0
0.00049 -> 0
0.00050 -> 0
0.00060 -> 1
0.00140 -> 1
```

Damit ist das Problem keine hypothetische Float-Formatierung, sondern die
definierte Persistenzabbildung.

### Repro C: Unsichtbarer Objective-Modus

Zwei identische Wealth-Ziele mit identischem Shortfall, aber unterschiedlicher
Hardness, wurden direkt durch das produktive `shortfall_objective()` geführt:

```text
OPTIMIZER_GOAL_WEIGHTING unset
  hard objective          = 4.0e-06
  opportunistic objective = 4.0e-06
  ratio                   = 1

OPTIMIZER_GOAL_WEIGHTING=hardness
  hard objective          = 4.0e-05
  opportunistic objective = 8.0e-07
  ratio                   = 50

OPTIMIZER_GOAL_WEIGHTING=hardnes
  hard objective          = 4.0e-06
  opportunistic objective = 4.0e-06
  ratio                   = 1
```

Der Tippfehler wird nicht abgelehnt. Eine Source-Inspektion bestätigte
gleichzeitig:

```text
weighting_reads_raw_env              = true
weighting_in_model_basis             = false
weighting_in_sensitivity_hash_scope  = false
sensitivity_source_has_model_hash    = true
```

Der vorhandene Hash behauptet damit vollständigen Live-Input, bindet aber
einen entscheidungsrelevanten Input nicht.

### Repro D: Grüne Tests besitzen die Lücke

Der fokussierte Bestandsgate lief unverändert:

```text
175 passed in 173.57s (0:02:53)
```

Enthalten waren:

```text
tests/test_optimizer_phase6.py
tests/test_chance_constraint.py
tests/test_optimizer_objective_constraints.py
tests/test_optimizer_objective_dimensionless.py
tests/test_optimizer_production_contract.py
tests/test_optimizer_shadow_mode.py
tests/test_allocation_editor_wiring_contract.py
```

Die Tests belegen Seed-/Horizon-Pairing, Return-Target-Änderung, Chance-
Probability, Objective-Normalisierung, Context-Verträge und Schemas. Sie
assertieren aber weder typgerechtes UI-Rendering noch Status-Gating, kleine
Objective-Werte an der Serialisierungsgrenze, Mode-Bindung in Hash/Run noch
vollständige Sensitivity-Evidence.

## `GOAL-SENSITIVITY-PUBLICATION-001`

### Fehlergrenze

Das Problem besteht aus vier gemeinsam wirksamen Vertragsbrüchen:

1. ein semantisch überladenes Pflichtfeld trägt je nach Zieltyp Rappen,
   Vermögens-Rappen, Return-bps oder null;
2. die Response besitzt keinen Discriminator, der Consumer zur richtigen
   Einheit zwingt;
3. Solverstatus und Integer-Feasibility begrenzen die Beratungsbotschaft nicht;
4. es existiert kein unveränderlicher Resultatnachweis für die angezeigte
   Was-wenn-Aussage.

Ein isolierter UI-Patch auf `Renditeziel` genügt nicht. Auch Maximierung,
zukünftige Zieltypen, Fallbacks, divergierte Solver und Replay benötigen einen
serverseitig typisierten und statusgebundenen Vertrag.

### Verbindlicher Zielvertrag

Die Response wird als discriminated union modelliert, beispielsweise:

```text
GoalSensitivityResult
  identity
    analysis_id
    mandate_id
    goal_id
    goal_version / goal_snapshot_hash
    allocation_id / allocation_context_hash
  context
    model_input_hash_baseline
    model_input_hash_modified
    objective_contract_hash
    seed / n_paths / horizon / pairing_basis
  target
    kind = amount | wealth | return_rate | growth_utility
    currency? / amount_rappen?
    return_bps? / return_horizon_years?
    growth_metric? / utility_parameters?
    baseline / modified
  comparison
    state = available | unavailable | invalid
    reason_code?
    solver_status_baseline / solver_status_modified
    feasible_baseline / feasible_modified
    active_method_baseline / active_method_modified
    exact_weights_bps_baseline / modified
    objective_baseline / objective_modified / delta_pct
  evidence
    created_at
    actor_id
    request_hash
    result_hash
```

Nur `state=available` darf eine Richtung „besser/schlechter erreichbar“
tragen. Mindestens müssen beide tatsächlich publizierten Allocations
integer-feasible sein und einen fachlich freigegebenen Status besitzen. Ein
abgelehnter Solverkandidat darf nicht als Sensitivity-Allokation erscheinen.
Wenn ein House-Fallback verglichen werden soll, muss wie im Hauptpfad zuerst
das tatsächlich aktive Fallback unter demselben retained Context neu bewertet
und als Methodenwechsel sichtbar gemacht werden.

### Pflicht-Tests

1. Amount-, Wealth-, Return- und Maximierungs-/Utility-Ziel liefern
   disjunkte, einheitenrichtige Varianten.
2. 500 -> 600 bps rendert `6.00 % p.a.` und niemals `CHF 6`.
3. `diverged`, `diverged_infeasible`, nicht feasible oder unsynchronisierter
   Fallback liefert `unavailable`, keine Richtung und keine aktive Allocation.
4. `converged` und `converged_robustified` benötigen zusätzlich den
   unabhängigen Post-Round-Feasibility-Nachweis.
5. Baseline available, Modified unavailable bleibt als asymmetrischer
   fachlicher Zustand sichtbar und erzeugt kein Delta.
6. Audit-Evidence bindet Request, Horizon-Delta, beide Input-Hashes, Objective-
   Vertrag, Seed, Status, Feasibility, Gewichte und Resultat-Hash.
7. Classic UI und React exhaustiv rendern jede Unionvariante; TypeScript darf
   keine Backendfelder unterschlagen.
8. Ein UI-Regressionstest erhält den vorhandenen `finally`-Pfad, der Buttons
   nach Success und Error reaktiviert.

## `OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001`

### Fehlergrenze

Der Solver selbst rechnet mit Float-Werten. Die Allocation kann deshalb trotz
dieses Findings numerisch ausgewählt worden sein. Fehlerhaft sind aber die
persistierte und veröffentlichte Evidence sowie das Sensitivity-Delta, das
aus dieser verlustbehafteten Darstellung berechnet wird.

Besonders gefährlich ist die Vermischung dreier Zustände:

```text
raw objective = 0         -> stored 0
raw objective = 4e-12     -> stored 0
raw objective = 4e-4      -> stored 0
```

„Vollständig erfüllt“, „minimaler Miss“ und „materieller kleiner Shortfall“
können denselben Nachweis besitzen. Goal-Driver bleiben zwar nach Rohwert
sortiert, zeigen aber mehrere Beiträge `0`; damit ist ihre Erklärung intern
nicht reconciliable.

### Verbindlicher Zielvertrag

1. Eine Objective erhält `objective_contract_version`, `unit=dimensionless`,
   klare Komponenten und eine kanonische verlustfreie Darstellung.
2. Bevorzugt wird eine kanonische Decimal-/Scientific-String-Repräsentation
   mit definierter signifikanter Präzision. Ein neuer Fixed-Point-Integer ist
   nur zulässig, wenn Domain, Overflowgrenze und maximaler relativer Fehler
   formal festgelegt und getestet sind.
3. Delta wird aus den rohen beziehungsweise kanonischen hochpräzisen Werten
   berechnet, nie aus Anzeige- oder Legacy-Integern.
4. Exakte Null, positive Sub-Epsilon-Werte, non-finite und unavailable bleiben
   verschiedene Zustände.
5. Primary Shortfall, Chance Penalty und sekundäre Risikokomponente werden
   getrennt gespeichert; ihre Summe muss die publizierte Total-Objective
   reproduzieren.
6. `TargetAllocation`, `OptimizerRun`, MethodComparison, GoalDriver,
   Sensitivity, API, UI und PDF verwenden denselben Konverter und dieselbe
   Vertragsversion.
7. Das alte `*_milli`-Feld darf übergangsweise nur als klar markiertes
   Legacy-Feld verbleiben. Neue Entscheidungen dürfen nicht daraus verglichen
   werden.

### Legacy- und Migrationsvertrag

Alte Integer-Nullen beweisen keine rohe Objective von null. Deshalb:

1. verfügbare vollständige Run-Inputs deterministisch replayen;
2. neue Objective-Evidence separat versioniert persistieren;
3. nicht replaybare Werte als `legacy_precision_ambiguous` markieren;
4. alte Deltas und Goal-Driver nicht still unter der neuen Skala anzeigen;
5. signierte historische Dokumente unverändert aufbewahren, aber nicht als
   aktuelle hochpräzise Methodenevidence umdeuten.

### Pflicht-Tests

1. Roundtrip für `0`, `4e-12`, `4e-6`, `4e-5`, `0.00049`, `0.0005`,
   `0.0006`, `0.0014`, Chance-Penalty-Größen und nahe Overflowgrenze.
2. Raw `0.0001 -> 0.0002` ergibt exakt das definierte 100-Prozent-Delta.
3. Raw `0.0006 -> 0.0014` ergibt 133.33 Prozent, nicht null.
4. Baseline exakt null liefert einen expliziten mathematisch undefinierten
   Delta-Zustand; eine kleine positive Baseline nicht.
5. Summe kanonischer Goal-Beiträge entspricht Primary Objective innerhalb der
   spezifizierten Toleranz.
6. Persistenz-/Reload-, JSON-, API-, TypeScript- und UI-Roundtrip erhalten
   Einheit, Version und Wert.
7. Regressionstest verhindert Rückfall auf „milli-rappen²“ nach
   dimensionsloser Normalisierung.

## `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001`

### Fehlergrenze

`equal` und `hardness` sind zwei fachlich verschiedene Optimierungsmodelle.
Sie dürfen als Owner-Optionen koexistieren, aber nicht als unsichtbarer
Prozesszustand. Der aktuelle direkte Environment-Read hat vier Folgen:

1. Tippfehler und unbekannte Werte fallen fail-open auf eine andere Methodik;
2. die Methode kann nicht aus einem gespeicherten Run rekonstruiert werden;
3. Sensitivity-Input-Hashes identifizieren unterschiedliche Mathematik als
   denselben Input;
4. Objective, Goal-Driver, Retry, Fallback und Replay haben keinen explizit
   eingefrorenen gemeinsamen Methodenwert.

### Verbindlicher Zielvertrag

Ein versionierter `ObjectiveContract` wird einmal pro Run validiert und in den
retained Context kopiert:

```text
ObjectiveContract
  version
  goal_weighting_mode = equal | hardness
  hardness_weights = {hard, primary, opportunistic}
  goal_priority_weight_semantics
  zero_weight_semantics
  shortfall_normalization
  chance_constraint
    lambda
    applicable_hardness
    tau_source / defaults
    importance_weighting_version
  secondary_objective
    type
    weight
    epsilon / lexicographic_tolerance
  serialization_version
```

Dieser Vertrag muss Bestandteil sein von:

1. zentral validierten Startup-Settings,
2. OptimizerContext und jeder Evaluation,
3. `optimization_model_basis`,
4. Allocation- und Sensitivity-Input-Hash,
5. `OptimizerRun` und `TargetAllocation`-Evidence,
6. Fallback-/Shadow-/Sensitivity-Replay,
7. API-/UI-/PDF-Methodendisclosure.

Objective-Funktionen lesen danach kein `os.environ` mehr. Ein unbekannter Wert
stoppt den Startup beziehungsweise den Run fail-closed. Modeänderung ändert
den Context-Hash selbst dann, wenn zufällig dieselben 10.000-bps-Gewichte
resultieren.

### Pflicht-Tests

1. `equal` erzeugt den dokumentierten Faktor 1; `hardness` den Faktor 50 im
   Hard-versus-Opportunistic-Gegenbeispiel.
2. `hardnes`, Leerstring, Whitespace-only, unbekannte Groß-/Kleinschreibung
   nach Normalisierung und nicht-stringartige Configwerte werden gemäß
   zentralem Vertrag behandelt; kein stiller Moduswechsel.
3. Modeänderung ändert Model-Basis, Objective-Contract-Hash, Allocation-
   Context-Hash und beide Sensitivity-Hashes.
4. Identischer eingefrorener Context bleibt unverändert, selbst wenn sich ein
   Prozess-Environment nach Runstart ändert.
5. Solver-Closure, `evaluate_weights`, Goal-Driver, House-Fallback und Replay
   verwenden exakt denselben Contract.
6. Reporting-Hardness wird nicht zusätzlich in die Optimizer-Objective
   multipliziert; `HARDNESS-ONCE` bleibt geschlossen prüfbar.
7. Zero-Weight-Ownerentscheidung gilt identisch in Shortfall, Chance-Penalty,
   Driver, Mandats-Score und Publikation.

## Revalidierung der Mixed-Goal- und Chance-Constraint-Verträge

### Bestätigte korrekte Teilverträge

- Success wird pro Ziel und Pfad bestimmt.
- Uniforme Pfade verwenden den Stichprobenmittelwert.
- Importance Sampling verwendet die normalisierten Likelihood-Gewichte.
- Falsche Weight-Shape und nichtpositive Gewichtssumme werfen Fehler.
- `tau` wird zielindividuell bestimmt.
- Harte und primäre Ziele zahlen unterhalb Tau die dokumentierte quadratische
  Soft-Strict-Penalty mit Lambda `1e6`.
- Opportunistische Goals zahlen keine Chance-Penalty, bleiben aber im
  Shortfall-Objective.
- `maximize` ist aus der Chance-Penalty ausgenommen. Seine weiterhin falsche
  Entscheidungs- und Probability-Semantik bleibt vollständig unter
  `GOAL-MAXIMIZATION-OBJECTIVE-001` offen.

### Bewusst nicht als neuer Befund dupliziert

1. Explizites `weight_bps=0` wird in Liability, Objective, Chance-Penalty und
   Reporting verschieden interpretiert: `GOAL-SCORE-001 / ZERO-WEIGHT`.
2. Hardness wird im Reportingpfad doppelt materialisiert:
   `GOAL-SCORE-001 / HARDNESS-ONCE`.
3. Bedingte Expected-Value-Targets und ihre Probability:
   `GOAL-CONDITIONAL-001`.
4. Tau-Status versus p50/p75-Status: `MC-STATUS-001`.
5. Targetlose Maximierung als sichere Erreichung:
   `GOAL-MAXIMIZATION-OBJECTIVE-001`.
6. Kandidatenabhängiger Pseudo-Zwei-Phasen-Switch:
   `OPTIMIZER-TWO-PHASE-OBJECTIVE-001`.

Claude soll diese IDs gemeinsam lesen, aber nicht in einer neuen pauschalen
„Chance-Constraint repariert“-Änderung vermischen.

## Kanonischer Sensitivity-Evidence-Vertrag für Claude

Sensitivity ist kein bloßer UI-Request, sondern eine eigene Analyse mit zwei
gekoppelten Runs. Der vorhandene `StochasticRunEvidence`-Zielvertrag wird um
einen unveränderlichen Counterfactual-Envelope ergänzt:

```text
GoalSensitivityEvidence
  analysis_id
  created_at / actor / mandate
  baseline
    allocation_anchor
    goal_snapshot
    model_input_hash
    objective_contract
    result / feasibility / status
  counterfactual
    mutation = target_delta | horizon_delta
    modified_goal_snapshot
    model_input_hash
    result / feasibility / status
  pairing
    seed
    shared_scenario_artifact_hash
    prefix_contract
    estimator / weight hashes
  comparison
    typed_target_delta
    exact_objective_values
    delta_semantics
    availability_verdict
  publication
    result_hash
    channel_contract_version
    rendered_value_and_unit
```

Große Szenariomatrizen müssen nicht dupliziert werden. Ein content-addressed
Artifact mit Hash, Shape, Dtype, Generator-/Estimatorversion und Retentionstatus
genügt. Baseline und Counterfactual müssen aber beweisbar dasselbe gepaarte
Artifact beziehungsweise die erlaubten Präfixe verwenden.

## Empfohlene Implementierungsreihenfolge für Claude

### Phase 0: Fail-closed und rote Repros

1. Sensitivity in echter Beratung vorübergehend sperren oder ausschließlich
   als `unavailable` ohne Richtungsclaim darstellen.
2. Die Repros A bis C als rote Unit-/Integration-/UI-Tests materialisieren.
3. Die offenen Round-35-Repros für Solverannahme, bps-Apportionierung und
   Zwei-Phasen-Objective mitlaufen lassen; Sensitivity darf deren fehlerhafte
   Kandidaten nicht separat veröffentlichen.

### Phase 1: ObjectiveContract einfrieren

1. Goal-Weighting in zentrale validierte Settings überführen.
2. vollständigen `ObjectiveContract` definieren und einmal pro Run in den
   Context kopieren;
3. Context-, Model-Basis-, Run- und Hash-Bindung ergänzen;
4. Zero-Weight- und Hardness-Ownerentscheidungen explizit festschreiben.

### Phase 2: verlustfreie Objective-Evidence

1. kanonische dimensionless Decimal-Repräsentation einführen;
2. Total und Komponenten gemeinsam persistieren;
3. Deltas ausschließlich aus kanonischen Rohwerten berechnen;
4. Legacy-Milli nur lesend und klar als mehrdeutig behandeln.

### Phase 3: typisierte Sensitivity

1. discriminated Target-/Result-Union implementieren;
2. Feasibility- und Status-Gating serverseitig erzwingen;
3. Hauptpfad-Fallbacks unter retained Context synchronisieren;
4. unveränderliche `GoalSensitivityEvidence` persistieren und auditieren.

### Phase 4: Consumer und Migration

1. Classic UI und React exhaustiv auf den neuen Unionvertrag umstellen;
2. vorhandenen `finally`-Button-Lifecycle bei der Umstellung erhalten;
3. alte Objective-/Sensitivity-Evidence replayen oder quarantänisieren;
4. API, UI, PDF, Signatur und Handoff auf dieselbe Evidence-ID binden.

### Phase 5: Abnahme

1. alle neuen roten Tests grün;
2. vollständiger Backend- und Frontend-Gate;
3. deterministischer Replay mit `equal` und `hardness`;
4. Browser-DOM-Test für alle Zieltypen und Statuswerte;
5. PostgreSQL-Persistenz-/Concurrency-Test der immutable Evidence;
6. Publication-Preflight für Finalisierung, PDF, Signatur und Handoff.

## Definition of Done

Die drei neuen IDs dürfen erst geschlossen werden, wenn:

- Zielwert und Einheit serverseitig typisiert und consumerseitig exhaustiv
  gerendert werden;
- kein nicht feasible oder nicht freigegebener Solverstatus eine
  besser/schlechter-Aussage erzeugt;
- Objective-Wert, Komponenten und Delta ohne materialitätsgefährdenden
  Präzisionsverlust roundtrippen;
- echte Null und kleine positive Objective unterscheidbar sind;
- der Goal-Weighting-Modus validiert, im Run eingefroren und in jedem
  relevanten Hash enthalten ist;
- ein vollständiger Sensitivity-Nachweis Request, Context, Pairing, beide
  Resultate und Publication bindet;
- Legacy-Evidence replayed oder sichtbar als mehrdeutig quarantänisiert ist;
- und die Abnahme auf Backend, Classic UI, React, PDF, Signatur und Handoff
  denselben Resultat-/Evidence-Hash bestätigt.

## Testnachweis und bewusst nicht behauptete Gates

Ausgeführt wurde:

```powershell
python -m pytest -q --basetemp .pytest_tmp_round36 `
  tests/test_optimizer_phase6.py `
  tests/test_chance_constraint.py `
  tests/test_optimizer_objective_constraints.py `
  tests/test_optimizer_objective_dimensionless.py `
  tests/test_optimizer_production_contract.py `
  tests/test_optimizer_shadow_mode.py `
  tests/test_allocation_editor_wiring_contract.py
```

Ergebnis:

```text
175 passed in 173.57s (0:02:53)
```

Zusätzlich wurden die oben dokumentierten Python- und JavaScript-Repros direkt
gegen die produktiven Konverter beziehungsweise unveränderte UI-Ausdrücke
ausgeführt.

Bewusst nicht behauptet werden:

- kein Browser-DOM-/Playwright-Lauf;
- kein echter PostgreSQL-/Concurrency-Lauf;
- kein Full-Backend- oder vollständiger Frontend-Gate;
- keine Bewertung regulatorischer Rechtsfragen;
- keine Produktcode-, Test-, Schema- oder Migrationsänderung;
- keine Schließung eines bestehenden Findings.

Der globale Worktree-Status wird wegen bereits vorhandener, ACL-bedingt nicht
lesbarer Pytest-Verzeichnisse nicht als vollständig clean behauptet. Die
getrackte Diff-Basis war vor der Dokumentation leer.

## Releaseentscheidung

Der Release-Hold bleibt bestehen. Zusätzlich zu den vorherigen Blockern gilt:

1. Sensitivity darf in echter Beratung keine typfalsche oder statusblinde
   Richtungsbotschaft publizieren.
2. Gerundete Legacy-Milliwerte dürfen nicht als hinreichender Objective-
   Nachweis oder als Basis eines Sensitivity-Deltas gelten.
3. Ein Run ohne gebundenen `ObjectiveContract`, insbesondere ohne expliziten
   Goal-Weighting-Modus, ist methodisch nicht reproduzierbar.
4. Ein AuditLog-Eintrag nur über die Sliderbewegung ist keine Evidence des
   berechneten oder angezeigten Resultats.

Der Hold ist weiterhin eine Governance-Entscheidung und wird im aktuellen
Runtimepfad nicht in allen Berechnungs- und Publikationskanälen vollständig
serverseitig erzwungen.
