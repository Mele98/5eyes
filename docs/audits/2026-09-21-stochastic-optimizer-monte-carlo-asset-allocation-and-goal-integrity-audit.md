---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-stochastic-monte-carlo-asset-allocation-goal-integrity-followup-audit"
status_as_of: "2026-09-21"
audit_started_on: "2026-09-21"
audit_completed_on: "2026-09-21"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "d2a88cfe405f46a6e8f7518c42b368f756293389"
prior_release_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
audit_mode: "read_only_static_optimizer_objective_importance_sampling_monte_carlo_goal_allocation_and_publication_review_plus_deterministic_python_reproductions_and_focused_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "stochastic scenario and importance-sampling estimator integrity, optimizer objective and explainability, allocation constraints and context, Monte Carlo path and goal semantics, goal horizons and weights, score aggregation, and customer-facing publication consistency"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 2
focused_existing_tests_passed: 609
focused_existing_tests_skipped: 0
focused_existing_tests_failed: 0
focused_existing_test_runs_confirmed: 1
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "make every optimizer decision, probability, driver and quantile consume one validated estimator contract; compute return-goal evidence at each goal's own horizon; decide and migrate the zero-weight domain; apply goal hardness exactly once; then bind one immutable stochastic run evidence snapshot to optimizer, Monte Carlo, API, UI, PDF, signature and handoff and close the previously documented goal/MC publication blockers"
---

# Stochastic-Optimizer-, Monte-Carlo-, Asset-Allocation- und Zielintegritätsaudit

## Geltung, Abgrenzung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die dreiunddreißigste Read-only-
Kontrollrunde. Sie wurde am 21. September 2026 gegen den unveränderten
Repository-Head `d2a88cfe405f46a6e8f7518c42b368f756293389`
durchgeführt. Produktcode und Tests wurden nicht verändert. Nach Abschluss
der Prüfung werden ausschließlich die fünf im Dokumentationsmanifest
genannten Dokumentationspfade angepasst.

Geprüft wurde bewusst das fachliche Herzstück:

1. Szenarioerzeugung und Importance Sampling,
2. Optimizer-Objective, Chance Constraints und Explainability,
3. Asset-Allocation-Bounds, Rundung, Kontextbindung und Fallback,
4. Monte-Carlo-Pfade und risikobereinigte Kennzahlen,
5. Zieltypen, Zielhorizonte, Zielgewichte und Mandatsaggregation,
6. sowie die Übergabe dieser Evidenz an API, UI und kundenwirksame
   Publikationen.

Der Audit bewertet keine konkrete Anlageempfehlung und keine erwartete
Marktrendite. Er prüft, ob das implementierte mathematische Modell intern
dieselbe Frage beantwortet, die der Benutzeroberfläche, dem Kunden und dem
Audit-Trail erklärt wird.

Er ergänzt insbesondere:

1. den
   [Zielerreichbarkeits- und Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
2. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
3. den
   [Post-Commit-Integritätsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
4. sowie die
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Für Aussagen über den beobachteten Ist-Stand gelten aktueller Code,
ausgeführte Reproduktionen und Tests zuerst. Für den zu implementierenden
Zielvertrag gilt dieser Audit vor älteren Handoffs. Grüne Bestandstests
belegen vorhandene Positivkontrollen, nicht die Abwesenheit der hier mit
neuen Gegenbeispielen nachgewiesenen Vertragsbrüche.

Alle Release-Sperren dieses Dokuments sind Governance-Akzeptanzkriterien.
Der aktuelle Runtimepfad erzwingt sie noch nicht durchgängig serverseitig.

## Kurzurteil

Der Stochastic Core besitzt eine substanzielle und in vielen Teilen sauber
abgesicherte mathematische Basis. Insbesondere werden der produktive
`stochastic`-Modus, exakte Suballocations, likelihood-ratio-gewichtetes
Objective, Bounds, Sum-to-one, Rundung und cashflow-neutrale Risikokennzahlen
in den geprüften Pfaden grundsätzlich korrekt behandelt.

Eine Freigabe des gesamten Entscheidungs- und Publikationsvertrags ist
trotzdem nicht möglich. Zwei neue P1-Verträge sind reproduzierbar verletzt:

1. **`OPTIMIZER-IS-EVIDENCE-001`:** Bei aktivem Importance Sampling wird die
   Entscheidung mit Likelihood-Ratio-Gewichten optimiert, die publizierte
   Rangfolge der Zieltreiber aber mit einem uniformen Mittel berechnet. Ein
   Ziel kann deshalb als größter Optimizer-Treiber erklärt werden, obwohl die
   tatsächlich optimierte Verlustfunktion nahezu vollständig von einem
   anderen Ziel dominiert wird. Die im Evaluationsobjekt berechneten
   Endvermögensquantile sind ebenfalls ungewichtet und müssen im selben
   Estimatorvertrag korrigiert werden.
2. **`GOAL-RETURN-HORIZON-001`:** Ein Renditeziel wird sowohl im Optimizer als
   auch in der zentralen Asset-Allocation-Monte-Carlo-Auswertung gegen die
   annualisierte Rendite des gesamten Simulationshorizonts bewertet. Der
   individuelle Zielhorizont wird für diese Entscheidung nicht verwendet.
   Ein Einjahresziel kann dadurch auf denselben Pfaden von korrekt 33 Prozent
   auf publizierte 67 Prozent Erfolg drehen.

Zusätzlich wurden zwei konkrete Erweiterungen des bereits offenen
`GOAL-SCORE-001` bestätigt:

- Ein explizites `weight_bps=0` ist schema- und semantisch zulässig, wird im
  Optimizer und in der Goal-Analyse aber teilweise als „nicht gesetzt“
  interpretiert und durch das Rank-Default ersetzt; die Mandatsaggregation
  behandelt denselben Wert dagegen als null.
- Die produktive Mandatsaggregation multipliziert die Goal-Hardness zweimal:
  einmal beim Erzeugen der Goal-Zeile und nochmals beim Aggregieren. Der
  sichtbare Mandats-Score kann dadurch deutlich vom dokumentierten
  einmaligen Gewichtungsvertrag abweichen.

Die bereits offenen Goal-/Monte-Carlo-/Publikationsfindings vom 2. September
bleiben bestätigt. Für Asset-Allocation-Bounds, Sum-to-one, Suballocation-
Momente, Post-Round-Validierung und cashflow-neutrale VaR-/Drawdown-Berechnung
wurde in dieser Runde kein zusätzlicher P1 gefunden. Diese Positivkontrolle
schließt die estimator-, zielhorizont- und publikationsbezogenen Blocker nicht.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `OPTIMIZER-IS-EVIDENCE-001` | P1 | neu bestätigt | Objective und Chance Probability verwenden IS-Gewichte; Zieltreiber und Evaluationsquantile verwenden uniforme Pfade. Entscheidung und Erklärung können sich widersprechen. |
| `GOAL-RETURN-HORIZON-001` | P1 | neu bestätigt | Optimizer und Haupt-MC bewerten jedes Renditeziel mit der annualisierten Rendite des gesamten Run-Horizonts statt mit der Prefix-TWR am individuellen Zielhorizont. |
| `GOAL-SCORE-001 / ZERO-WEIGHT` | P1 | bestehender Vertrag, neue Evidence | `0` ist zulässig, wird je nach Consumer als Rank-Default, Mindestgewicht eins oder echtes Nullgewicht behandelt. |
| `GOAL-SCORE-001 / HARDNESS-ONCE` | P1 | bestehender Vertrag, neue Evidence | `_goal_weight()` materialisiert bereits die Hardness; `_build_mandate_score()` multipliziert sie im Produktionspfad erneut. |
| `GOAL-SNAPSHOT-001` / `GOAL-DOMAIN-001` / `GOAL-CONDITIONAL-001` | P1 | erneut bestätigt | Goal-Zustand, Probability-Domain und bedingte Zielsemantik besitzen weiterhin keinen einheitlichen unveränderlichen Vertrag. |
| `MC-CONTEXT-001` / `MC-CASHFLOW-CURRENCY-001` / `MC-STATUS-001` / `MC-QUANTILE-001` | P1 | erneut bestätigt | Live-MC, Cashflow-/Currency-Modell, Statusfrage und Quantilbeschriftung bleiben vom Entscheidungsnachweis getrennt oder semantisch falsch. |
| `GOAL-PUBLICATION-001` | P1 | erneut bestätigt | API, Classic UI, React, Advisory-PDF, Signed Artifact und Handoff besitzen weiterhin keine einheitliche, rungebundene Goal-/MC-Evidenz. |

Es wurde kein neuer P0 bestätigt. Keine bestehende Finding-ID wird durch
diesen Audit geschlossen.

## Ende-zu-Ende-Systembild

Der gegenwärtige Pfad lässt sich auf vier fachliche Ebenen reduzieren:

```text
CMA + Suballocations + Cashflows + Goals + Policy
                         |
                         v
               OptimizerContext / Szenarien
                         |
              +----------+-----------+
              |                      |
              v                      v
     Objective + Constraints    Evaluation/Explainability
       (IS-gewichtet)           (teilweise uniform)
              |                      |
              +----------+-----------+
                         |
                         v
               Target Allocation / Goal JSON
                         |
              +----------+-----------+
              |                      |
              v                      v
       Haupt-Monte-Carlo       Report-Live-Monte-Carlo
     (eigene Goal-Auswertung)   (abweichender Kontext)
              |                      |
              +----------+-----------+
                         |
                         v
             API / Classic UI / React / PDF
```

Die neue Kernbeobachtung ist nicht, dass eine einzelne Formel fehlt. Der
Entscheidungsestimator verzweigt: Im selben Run werden Pfade teilweise mit
Likelihood Ratios, teilweise uniform, Renditeziele teilweise mit dem
Run-Horizont und Zielwerte mit dem Goal-Horizont bewertet. Danach werden
zusätzlich andere Live-Pfade für die Kundenpublikation erzeugt. Eine lokale
Labelkorrektur kann diesen Bruch nicht schließen.

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende vorhandene Eigenschaften nicht zurückbauen:

1. `stochastic` ist der produktive Modus; die House Matrix ist nur
   klassifizierter technischer Sicherheitsfallback.
2. Der Optimizer-Kontext besitzt die exakten Suballocations und daraus
   abgeleitete, getestete Lognormal-/Cornish-Fisher-Momente.
3. Cache- und Run-Kontext binden den Suballocation-Hash; spätere Mutationen
   der Eingabeliste ändern den bereits aufgebauten Kontext nicht.
4. Das primäre Shortfall-Objective und die Chance-Constraint-Probability
   verwenden bei aktivem Importance Sampling die Scenario-/Likelihood-
   Gewichte.
5. Effektive Bounds und Constraints werden vor dem Solver validiert; die
   finale gerundete Allokation wird nochmals gegen Sum-to-one, Bandbreiten und
   Risk-Cap geprüft.
6. Risky Fraction und Allokationen werden als exakte Basispunktwerte geführt;
   die Zielallokation summiert auf 10.000 Basispunkte.
7. Solver, technischer Fallback und Explainability erhalten denselben
   `OptimizerContext`. Die neue Reparatur muss diesen gemeinsamen Kontext
   stärken, nicht durch parallele Berechnungswege ersetzen.
8. Das Haupt-Monte-Carlo verwendet Suballocation-Momente und einen
   deterministischen Seed, koppelt Current und Target über dieselben Schocks,
   modelliert Rebalancing-Kosten und berechnet TWR, Year-1-VaR und Max
   Drawdown cashflow-neutral.
9. Total-Scope-Ziele können eigene Total-Wealth-Pfade inklusive direkter
   Vermögenswerte und Liabilities verwenden.
10. Goal Liabilities unterscheiden Wealth-at-T, einmalige und wiederkehrende
    Ausgaben, Renditeziele, Maximierung sowie staatlich gedeckte Ziele.

## Codeanker des auditierten Stands

### Stochastik und Importance Sampling

- `5eyes-backend/services/optimizer/importance_sampling.py:245-340`:
  Auto-IS ist standardmäßig aktivierbar und greift bei konservativem Profil,
  Retirement oder mindestens einem harten Ziel. Der Befund betrifft damit
  normale Produktkontexte und keinen rein manuellen Sondermodus.
- `5eyes-backend/services/optimizer/solver.py:592-610` und `613-655`:
  Objective und Evaluation erhalten `context.scenario_weights`; die
  Endvermögensquantile in Zeile 641 verwenden dennoch `np.percentile` ohne
  Gewichte.
- `5eyes-backend/services/optimizer/objective.py:409-479`:
  `shortfall_objective()` berechnet bei gesetzten Gewichten den gewichteten
  Mittelwert `sum(per_path * weights) / sum(weights)`.
- `5eyes-backend/services/optimizer/objective.py:549-591`:
  `shortfall_contributions()` besitzt kein `weights`-Argument und verwendet
  immer `1 / n_paths`.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:1183-1207`:
  Die Explainability ruft diese uniforme Contribution-Funktion auf und
  publiziert ihre sortierte Rangfolge als Goal Drivers.
- `5eyes-electron/frontend/5eyes_v2.html:27122-27141`:
  Die Classic UI rendert genau diese Goal-Driver-Rangfolge.

### Renditezielhorizont

- `5eyes-backend/services/optimizer/solver.py:286-296`:
  `_annualized_twr_bps_per_path()` mittelt Log-Returns über alle Jahre von
  `context.return_paths` und liefert nur einen Wert je Pfad.
- `5eyes-backend/services/optimizer/solver.py:601-610`, `626-635` und
  `1548-1557`: Derselbe Vollhorizontwert wird Objective, Evaluation und
  Chance Constraint für sämtliche Goals übergeben.
- `5eyes-backend/services/optimizer/objective.py:201-234`:
  Der Goal-Horizont wird für das Return-Target verwendet; sobald ein TWR-
  Vektor übergeben wurde, stammt der Vergleichswert aber aus dem gemeinsamen
  Vollhorizontvektor.
- `5eyes-backend/services/optimizer/objective.py:315-331`:
  Die Probability vergleicht den übergebenen TWR direkt mit dem Goal-Target
  und selektiert keinen `target_year_index`.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:1481-1486`:
  Das Haupt-MC materialisiert pro Pfad nur die über den gesamten Run-Horizont
  annualisierte TWR.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:871-906` und
  `1513-1527`: Die Vermögenspfade werden goal-spezifisch indiziert; ein
  Renditeziel erhält dagegen die gemeinsame Vollhorizont-TWR-Liste.

### Goal-Gewicht und Mandats-Score

- `5eyes-backend/schemas/wealth.py:539-605` und
  `5eyes-backend/services/goal_semantics.py:120-128`:
  `weight_bps` ist optional; die zentrale Semantik lässt explizit 0 bis
  10.000 zu.
- `5eyes-backend/services/optimizer/goal_liabilities.py:99-103`:
  `if goal.weight_bps` ersetzt `0` durch das Rank-Default.
- `5eyes-backend/services/portfolio_engine_payload.py:235-241`:
  Derselbe Truthiness-Fallback gilt für die Goal-Analyse; zusätzlich wird
  hier bereits der Hardness-Multiplikator angewandt.
- `5eyes-backend/services/portfolio_engine_payload.py:266-283`:
  Die Mandatsaggregation behandelt ein angekommenes Nullgewicht als null und
  multipliziert jedes Gewicht nochmals mit Hardness.
- `5eyes-backend/services/portfolio_engine_payload.py:607-628`:
  Die zuvor hardness-gewichtete `_goal_weight()` wird als `weight_bps` in die
  Goal-Analyse geschrieben und danach an die Aggregation übergeben.
- `5eyes-backend/services/optimizer/objective.py:464-478` und `570-590`:
  Selbst ein bis dorthin erhaltenes Nullgewicht wird durch `max(1, ...)` zu
  einem positiven Mindestgewicht.

### Bereits offene Monte-Carlo- und Publikationsverträge

- `5eyes-backend/services/advisory_report.py:2061-2082` startet für den Report
  weiterhin eine neue Live-Monte-Carlo-Berechnung statt die unveränderliche
  Evidenz des Allocation-Runs zu verwenden.
- `5eyes-backend/services/monte_carlo_paths.py:307-344` baut Szenarioinputs
  nur aus CMA, ohne exakten Suballocation-Snapshot, und publiziert p5/p50/p75.
- `5eyes-electron/frontend/reporting/src/components/MonteCarloPathsChart.tsx:135`
  und `269` nennen p5-p75 ein Konfidenzband beziehungsweise „90% des
  Pfade-Korridors“. Empirisch liegen zwischen p5 und p75 nur 70 Prozent der
  Pfadmasse.
- `5eyes-electron/frontend/reporting/src/components/MonteCarloPathsChart.tsx:301-306`
  formatiert die Werte hart als CHF.
- `5eyes-electron/frontend/reporting/src/lib/goalClassification.ts:5-20`
  definiert einen zusätzlichen p50/p75-Status und bezeichnet p75 als
  „Best-Case“.

## Finding `OPTIMIZER-IS-EVIDENCE-001`

### Beobachtung

Der Solver minimiert bei aktivem Importance Sampling einen Likelihood-Ratio-
gewichteten Erwartungswert. Das ist fachlich korrekt: Proposal-Pfade dürfen
nicht so behandelt werden, als wären sie aus der ursprünglichen Verteilung
uniform gezogen worden. Die Explainability berechnet denselben Goal-
Shortfall jedoch nochmals als uniformes Pfadmittel.

Damit gilt im heutigen Code nicht die notwendige Invariante:

```text
sum(published_goal_driver_contributions)
    == shortfall_objective_of_the_published_allocation
```

Die Abweichung kann nicht als Rundungsdifferenz erklärt werden. Sie kann die
Reihenfolge der Treiber umdrehen.

### Deterministisches Gegenbeispiel

Der isolierte Repro verwendet zehn Pfade und zwei gleich gewichtete Ziele:

- Ziel A verfehlt ausschließlich einen Pfad mit sehr hoher IS-Wahrscheinlichkeit.
- Ziel B verfehlt mehrere Pfade, deren gesamte IS-Wahrscheinlichkeit sehr
  klein ist.

Der ausgeführte Repro lieferte:

```text
published_driver_order = [('B', 0.225), ('A', 0.1)]
weighted_objective_by_goal = [('A', 0.99), ('B', 0.0025)]
uniform_total = 0.325
weighted_total = 0.9925
```

Die Oberfläche würde B als größten Treiber erklären. Der tatsächlich vom
Solver optimierte Verlust wird zu rund 99,75 Prozent von A verursacht.

### Wirkung

1. Der Berater kann eine andere Zielpriorität als ursächlich ansehen als die,
   die den Optimizer-Entscheid tatsächlich bewegt hat.
2. Review, PDF und Audit-Trail können den Run nicht aus den publizierten
   Contributions rekonstruieren.
3. Ein Fix nur an der Sortierung ist unzureichend; die Beiträge selbst sind
   mit dem falschen Estimator berechnet.
4. `evaluate_weights()` berechnet p10/p50/p90 derzeit ebenfalls uniform. Auch
   wenn diese Felder im geprüften Produktpfad nicht als dominanter
   Kundenoutput gefunden wurden, wäre ihre spätere Publikation bei aktivem IS
   methodisch inkonsistent.

### Verbindlicher Reparaturvertrag

1. Eine zentrale Funktion validiert Scenario Weights einmalig:
   eindimensional, exakt `n_paths`, endlich, nichtnegativ und mit strikt
   positiver Summe. `NaN`, `inf`, negative Werte und Nullsumme brechen
   fail-closed ab.
2. `shortfall_contributions()` erhält dieselben normalisierten Gewichte wie
   `shortfall_objective()` und verwendet exakt dieselbe gewichtete
   Erwartungswertdefinition.
3. Die Explainability übergibt `context.scenario_weights`; kein Consumer darf
   still auf uniform zurückfallen, wenn der Run IS-aktiv ist.
4. Für empirische Quantile wird eine einzige versionierte weighted-quantile-
   Definition festgelegt. Interpolation, Randbehandlung und Verhalten bei
   Gewichtsbindungen müssen dokumentiert und getestet sein.
5. Die Run-Evidence persistiert mindestens `is_active`, Estimator-Version,
   Weight-Hash, normalisierte Gewichtssumme und Effective Sample Size
   `ESS=(sum(w)^2)/sum(w^2)`.
6. Jede Contribution-, Probability- und Quantile-Aussage referenziert dieselbe
   Run-/Estimator-ID. Eine gewichtete Entscheidung darf keine uniforme
   Erklärung erhalten.

### Pflicht-Negativ- und Invariantentests

1. Der obige Skewed-Weight-Repro muss A vor B ranken.
2. All-ones-Gewichte müssen bit- oder toleranzgleich zum uniformen Altpfad
   sein.
3. Summe der Goal Contributions muss dem Primary Shortfall Objective für
   dieselbe Allocation entsprechen.
4. Falsche Länge, `NaN`, `inf`, negative Werte und Summe null müssen
   fail-closed scheitern.
5. Weighted Quantiles müssen mit handberechneten diskreten Beispielen und
   Grenzfällen geprüft werden.
6. API-/UI-Test muss die gewichtete Driver-Reihenfolge des Run-Snapshots
   anzeigen, nicht eine lokal neu berechnete uniforme Reihenfolge.

## Finding `GOAL-RETURN-HORIZON-001`

### Beobachtung

Ein Renditeziel beantwortet eine zeitgebundene Frage, beispielsweise:
„Erreicht das Portfolio bis Ende Jahr 1 annualisiert mindestens 5 Prozent?“
Der Code erzeugt aber nur eine annualisierte TWR je Pfad über den gesamten
Simulationsträger. Diese Vollhorizont-TWR wird anschließend an sämtliche
Renditeziele übergeben, auch wenn deren `target_year_index` früher liegt.

Das Vermögensziel und das Renditeziel desselben Jahres können dadurch
unterschiedliche Perioden auswerten. Besonders problematisch ist, dass
spätere Erholung eine frühe Zielverfehlung rückwirkend in einen Erfolg drehen
kann oder ein späterer Verlust ein bereits erreichtes frühes Ziel nachträglich
als verfehlt erscheinen lässt.

### Deterministisches Optimizer-Gegenbeispiel

Für drei Pfade mit zwei Jahren wurden folgende Wealth-Verläufe verwendet:

```text
Pfad 1: [100,  50, 200]
Pfad 2: [100,  50, 200]
Pfad 3: [100, 200, 100]
```

Das Goal ist ein Einjahres-Renditeziel von 5 Prozent. Die im Produktionspfad
über beide Jahre annualisierten TWR-Werte sind ungefähr:

```text
full_horizon_twr_bps = [4142, 4142, 0]
correct_goal_horizon_success = [0, 0, 1]
production_with_full_twr_success = [1, 1, 0]
correct_success_rate = 33%
production_success_rate = 67%
```

Die Klassifikation dreht sich vollständig: Beide Pfade mit einem Verlust im
Zieljahr gelten wegen der Erholung im Folgejahr als Erfolg; der Pfad mit
Gewinn im Zieljahr gilt wegen des späteren Rückgangs als Misserfolg.

### Deterministisches Haupt-MC-Gegenbeispiel

Der direkte Aufruf von `_monte_carlo_goal_summary()` mit denselben
Vollhorizont-Samples lieferte für das Einjahresziel:

```text
{'years': 1, 'success_rate_pct': 67,
 'funded_ratio_p50': 2.0, 'score': 84}
```

Korrekt sind für den Zielhorizont 33 Prozent Erfolg und eine negative mediane
Einjahresrendite. Der Fehler betrifft daher nicht nur den Optimizer, sondern
auch die zentrale Asset-Allocation-Monte-Carlo-Zielanalyse.

### Wirkung

1. Chance Constraint, Achievement Probability und Goal Score können das
   falsche Zeitfenster bewerten.
2. Zwei Renditeziele mit verschiedenen Horizonten erhalten im selben Run
   dieselben Pfad-TWR-Samples.
3. Spätere Marktjahre beeinflussen rückwirkend bereits fällige Zielurteile.
4. Optimizer und MC teilen zwar denselben Fehler, aber nicht zwingend denselben
   Kontext; scheinbare Parität ist daher kein Korrektheitsbeleg.

### Verbindlicher Reparaturvertrag

1. Aus den cashflow-neutralen Portfoliofaktoren wird pro Pfad einmal eine
   Prefix-TWR-Matrix berechnet:

   ```text
   prefix_twr[path, year] = exp(
       sum(log(factor[path, 1:year+1])) / year
   ) - 1
   ```

2. Objective, Chance Constraint und Explainability selektieren für jedes
   Renditeziel exakt die Spalte `target_year_index - 1`.
3. Das Haupt-MC führt dieselbe Prefix-TWR-Serie für Current und Target. Die
   Vollhorizont-TWR bleibt eine separate Portfolio-Kennzahl und darf nicht als
   universeller Goal-Input wiederverwendet werden.
4. Zieltermin, daraus abgeleiteter Year Index und verwendete Prefix-Spalte
   werden im Snapshot persistiert.
5. Liegt ein Ziel außerhalb des simulierten Horizonts, wird es als nicht
   auswertbar mit explizitem Grund markiert oder der Run-Horizont vorab
   erweitert. Stilles Clamping ist unzulässig.
6. Optimizer, Haupt-MC, Report und UI verwenden dieselbe versionierte
   Renditezieldefinition.

### Pflicht-Negativ- und Invariantentests

1. Das obige Drei-Pfad-Gegenbeispiel muss 33 Prozent liefern.
2. Zwei Renditeziele mit unterschiedlichen Horizonten müssen in einem Run
   unterschiedliche Prefix-TWR-Spalten verwenden.
3. `target_date`, abgeleitetes `horizon_years` und `target_year_index` müssen
   dieselbe Fälligkeit adressieren.
4. Ein Ziel nach dem Simulationsende muss fail-closed als unavailable gelten,
   nicht auf das letzte Jahr geklemmt werden.
5. Einzahlungen und Entnahmen dürfen die cashflow-neutrale TWR nicht ändern.
6. Optimizer Probability, Haupt-MC Goal Summary und publizierte Goal-Zeile
   müssen für dieselbe Run-Evidence identisch sein.

## Erweiterung `GOAL-SCORE-001`: explizites Nullgewicht

### Beobachtung und Repro

Die Domain lässt `weight_bps=0` ausdrücklich zu. Der Wert besitzt aber vier
verschiedene Bedeutungen:

1. Optimizer Liability: Truthiness-Fallback auf Rank-Default.
2. Goal-Analyse: Truthiness-Fallback auf Rank-Default und Hardness.
3. Objective: `max(1, weight_bps)` erzwingt mindestens ein Basispunktgewicht.
4. Mandatsaggregation: ein angekommenes Nullgewicht bleibt null.

Der ausgeführte Repro für `weight_bps=0, rank=1` ergab:

```text
optimizer_liability_weight_bps = 10000
per_goal_payload_effective_weight_bps = 10000
mandate_score = {'weighted_score': None, ...}
```

Dasselbe gespeicherte Goal ist damit im Optimizer maximal priorisiert, in der
Mandatsaggregation aber vollständig ausgeschlossen.

### Verbindliche Owner-Entscheidung

Die sicherste und einfachste Semantik ist:

- `weight_bps` ist entweder `null` für das eindeutig dokumentierte
  Rank-Default oder liegt in `[1, 10000]`.
- Ein Ziel wird ausschließlich über `is_active=false` ausgeschlossen.

Falls Produktverantwortliche `0` bewusst als „aus Score und Objective
ausgeschlossen“ beibehalten wollen, muss stattdessen überall `is not None`
verwendet, jedes versteckte `max(1, ...)` entfernt und explizit entschieden
werden, ob Chance Constraints für ein Nullgewichtsziel weiter gelten. Beides
darf nicht gleichzeitig implizit sein.

Legacy-Nullwerte werden vor Freigabe deterministisch migriert oder
quarantänisiert. Ein stilles Uminterpretieren vorhandener Daten ist
unzulässig.

### Pflicht-Tests

1. Schema-/Service-/DB-Parität für `null`, `0`, `1`, `10000`, negativ und
   größer als `10000`.
2. Dieselbe effektive Gewichtung in Liability, Objective, Goal-Analyse,
   Mandats-Score und Publikation.
3. Migration oder Quarantäne vorhandener Nullwerte.
4. Expliziter Test der gewählten Chance-Constraint-Semantik.

## Erweiterung `GOAL-SCORE-001`: Hardness genau einmal

### Beobachtung und Repro

`_goal_weight()` multipliziert das Basisgewicht bereits mit dem
Hardness-Faktor. `_build_goal_analysis()` publiziert das Ergebnis als
`weight_bps`. `_build_mandate_score()` hält dieses Feld erneut für ein
Basisgewicht und multipliziert ein zweites Mal.

Der ausgeführte Repro mit gleichem Basisgewicht `1000` für ein hartes und ein
opportunistisches Ziel ergab:

```text
_goal_weight(hard) = 2000
_goal_weight(opportunistic) = 400
production_mandate_score = 96
single_multiplier_expected = 83
```

Der bestehende Unit-Test reicht rohe Gewichte direkt an die Aggregation und
prüft dadurch nur einen Multiplikator. Er deckt die produktive Verkettung
`_build_goal_analysis()` -> `_build_mandate_score()` nicht ab.

### Verbindlicher Reparaturvertrag

1. Jede Goal-Zeile führt getrennt:
   `raw_priority_weight_bps`, `hardness_multiplier_bps` und
   `effective_weight`.
2. Die Hardness wird an genau einer benannten Schicht angewandt.
3. Mandatsaggregation, Optimizer-Weighting und Kundenlabel erhalten
   versionierte, explizite Methodennamen. Der optionale Optimizer-Modus
   `OPTIMIZER_GOAL_WEIGHTING=hardness` darf nicht versehentlich mit dem
   Reporting-Score vermischt werden.
4. Ein Integrationstest muss die echte Produktionsverkettung aufrufen und
   gegen eine handberechnete Aggregation prüfen.

## Revalidierung der vorhandenen Goal-/MC-/Publikationsblocker

| Bestehende ID | Aktuelle Evidence | Erforderlicher Abschluss |
|---|---|---|
| `GOAL-SNAPSHOT-001` | Goal-Mutationen und Report lesen weiterhin keine vollständig gemeinsam versionierte Goal-Analyse. | Immutable GoalAnalysisSnapshot an Goal-Version und Allocation Run binden; stale Snapshot vor Publikation blockieren. |
| `GOAL-DOMAIN-001` | Die neu bestätigte Gewichtsdrift ergänzt die bereits dokumentierte Probability-/NaN-Domaininkonsistenz. | Eine strikte Domain an API, Service, DB, Replay und allen Publishern. |
| `GOAL-CONDITIONAL-001` | Erwartungswertskalierte Targets bleiben von bedingter und unbedingter Erfolgswahrscheinlichkeit semantisch getrennt zu modellieren. | Eintritt, Erfolg bei Eintritt und unbedingter Erfolg separat rechnen und benennen. |
| `MC-CONTEXT-001` | `advisory_report.py:2061-2082` startet weiterhin Live-MC statt Run-Evidence zu lesen. | Kein kundenwirksamer Re-Run; identische Manifest-/Run-ID in Entscheidung und Publikation. |
| `MC-CASHFLOW-CURRENCY-001` | Legacy-Report-MC bleibt ohne vollständigen Suballocation-, Cashflow-, FX-, Fee-, Tax-, Reserve- und Rebalancingvertrag. | Einen kanonischen Pfadgenerator und eine Currency-/Cashflow-Evidence verwenden. |
| `MC-STATUS-001` | Goal-`tau` und zusätzlicher p50/p75-Status beantworten weiter verschiedene Fragen. | Eine fachliche Frage pro Label; unterschiedliche Fragen explizit getrennt anzeigen. |
| `MC-QUANTILE-001` | React nennt p5-p75 weiter 90-Prozent-/Konfidenzband und p75 „Best-Case“. | Empirische Quantile exakt benennen; Coverage korrekt ableiten; kein Best-Case-Claim. |
| `GOAL-PUBLICATION-001` | Neue IS- und Horizon-Drift zeigt zusätzlich, dass selbst Solver-Evidence vor der Publikation auseinanderläuft. | Gemeinsamer Snapshot, Preflight, Hash und kanalgleiche Serialisierung. |

`REP-001` aus dem Post-Commit-Audit bleibt ebenfalls relevant: Eine
Monte-Carlo-Ausgabe darf ohne exakt belegten CMA-, Suballocation-, Cashflow-,
Goal- und Estimator-Snapshot weder persistiert noch als Entscheidungsnachweis
publiziert werden.

## Ergebnis der Asset-Allocation-Kontrolle

In der geprüften Runde wurde kein neuer isolierter P1 in der eigentlichen
Allokationsrechnung bestätigt. Folgende Kontrollen blieben im Code und im
609-Test-Gate grün:

- effektive Bandgrenzen und Sum-to-one,
- Risk-Cap/Risky-Fraction,
- vollständige 10.000-Basispunkt-Rundung,
- Post-Round-Feasibility,
- exakt weitergereichte Suballocations,
- suballocation-aware Moments und Cache-Key,
- gemeinsamer Optimizer-Kontext für Solver und Fallback,
- Current-/Target-Paarschocks,
- Rebalancing-Kosten,
- cashflow-neutrale TWR, Year-1-VaR und Max Drawdown,
- sowie Total-Wealth-Goal-Pfade.

Das ist eine enge Positivkontrolle, keine Gesamtfreigabe. Die gewählte
Allokation kann korrekt innerhalb ihrer Constraints liegen und dennoch mit
einem falschen Goal-Horizont bewertet oder mit einem falschen IS-Treiber
erklärt werden. Außerdem bleiben die früher dokumentierten Snapshot-,
Publication-, Asset-/Liability-, Tax-, Cost-, Preference-, Liquidity- und
Alternative-Asset-Verträge release-blockierend.

## Kanonischer Zielvertrag für Claude

Claude soll keine weitere lose JSON-Erweiterung bauen, sondern einen
unveränderlichen, versionierten `StochasticRunEvidence`-Vertrag unter dem
bestehenden `AllocationRunInputManifest` einführen oder einen gleichwertigen
bereits vorhandenen Root-Vertrag gezielt erweitern.

Mindestens erforderlich sind:

```text
StochasticRunEvidence
  identity
    run_id
    allocation_manifest_id
    methodology_version
    created_at / as_of
  scenario_context
    seed
    n_paths
    horizon_years
    cma_snapshot_id
    suballocation_snapshot_id / hash
    cashflow_snapshot_id / hash
    goal_snapshot_id / hash
  estimator
    importance_sampling_active
    proposal_version
    estimator_version
    scenario_weight_hash
    normalized_weight_sum
    effective_sample_size
    weighted_quantile_version
  allocation
    exact_weights_bps
    bounds / effective_constraints
    post_round_verdict
    fallback_status
  path_evidence
    prefix_twr_by_path_or_bound_artifact
    terminal_wealth_quantiles
    current_and_target_risk_metrics
  goal_evidence[]
    goal_id / goal_version
    goal_type
    target_year_index
    raw_priority_weight_bps
    hardness_multiplier_bps
    effective_weight
    probability
    tau
    objective_contribution
    score / status / explicit_method
  publication
    evidence_hash
    channel_contract_version
    stale / readiness verdict
```

Große Pfadmatrizen dürfen als content-addressed Artifact gespeichert werden;
der Snapshot muss dann deren Hash, Shape, Dtype, Estimatorversion und
Retentionstatus binden. Es ist nicht erforderlich, jede Matrix mehrfach in
JSON zu duplizieren.

## Empfohlene Implementierungsreihenfolge

### Phase 0: rote Vertrags- und Reprotests

Zuerst die vier reproduzierten Fehler als rote Tests festschreiben:

1. IS-Driver-Rank-Reversal,
2. einjähriges Renditeziel gegen Zwei-Jahres-Run,
3. explizites Nullgewicht über alle Consumer,
4. produktive doppelte Hardness-Verkettung.

Damit wird verhindert, dass eine lokale Reparatur nur einen Consumer grün
macht.

### Phase 1: Goal-Weight- und Score-Domain schließen

1. Owner-Entscheidung zu `weight_bps=0` treffen und migrationsfähig
   dokumentieren.
2. Schema, Service, DB und Publisher angleichen.
3. Rohgewicht, Hardness und Effektivgewicht trennen.
4. Hardness genau einmal anwenden.

Diese Phase ist klein, deterministisch und reduziert Mehrdeutigkeit für die
folgenden Objective-/Snapshot-Änderungen.

### Phase 2: goal-spezifische Prefix-TWR

1. Eine numerisch stabile Prefix-TWR-Funktion implementieren.
2. Matrix einmal je Allocation/Pathset berechnen.
3. Objective, Chance Constraint, Explainability und Haupt-MC auf
   `goal.target_year_index` umstellen.
4. Out-of-horizon fail-closed behandeln.

Keine separate TWR-Formel je Consumer einführen.

### Phase 3: einheitlicher IS-Estimator

1. Gewichte zentral validieren/normalisieren.
2. Contributions und Quantile auf denselben Estimator umstellen.
3. ESS und Estimatorversion persistieren.
4. Reconciliation-Invarianten zwischen Objective, Contributions,
   Probability und publizierten Feldern erzwingen.

### Phase 4: Run-Evidence und Publication vereinheitlichen

1. `StochasticRunEvidence` an Allocation Run und Goal Snapshot binden.
2. Live-Re-Simulation im Reportpfad entfernen oder ausschließlich als klar
   getrennte, nicht entscheidungswirksame Vorschau kennzeichnen.
3. API, Classic UI, React, PDF, Signed Artifact und Handoff lesen dieselbe
   Evidenz.
4. Stale, unvollständige oder estimatorinkonsistente Evidence blockiert
   Generate, Finalize, Sign und Handoff fail-closed.

### Phase 5: Migration, Replay und gestufte Freigabe

1. Legacy Goal Weights und persistierte Goal-/MC-JSONs inventarisieren.
2. Deterministisch migrieren oder quarantänisieren.
3. Alte Runs mit neuer Version nicht still als gleichwertig ausgeben.
4. Shadow-Replay auf repräsentativen Mandaten, danach kontrollierter Rollout
   mit Difference Budget und klarer Rollbackgrenze.

## Harte Invarianten der Abnahme

1. **Estimator-Parität:** Jede aus einem IS-Run abgeleitete Zahl verwendet
   denselben gewichteten Estimator oder ist explizit als Proposal-Statistik
   getrennt und nicht kundenwirksam.
2. **Contribution-Reconciliation:** Die Summe aller primären Goal-
   Contributions entspricht dem Primary Shortfall Objective derselben
   Allocation innerhalb definierter numerischer Toleranz.
3. **Horizon-Parität:** Jede Goal Probability und jeder Goal Score verwendet
   ausschließlich die Rendite-/Wealth-Serie bis zum eigenen Zielhorizont.
4. **Weight-Parität:** Ein Goal besitzt über Schema, DB, Optimizer, MC,
   Reporting und Publikation dieselbe dokumentierte Roh- und Effektivgewichtung.
5. **Hardness-once:** Kein Pfad multipliziert Hardness null- oder zweimal,
   sofern die Methodenversion genau einmal verlangt.
6. **Snapshot-Parität:** Allocation, Probability, Driver, Score, Status und
   Quantile referenzieren dieselbe Run-, Goal-, CMA-, Suballocation- und
   Cashflow-Evidence.
7. **No-live-rewrite:** Ein Read-/Report-Aufruf ändert die mathematische
   Evidenz eines bereits entschiedenen Runs nicht.
8. **Fail-closed:** Unknown, malformed, stale, out-of-horizon, invalid-weight,
   unreconciled oder unbound blockiert kundenwirksame Publikation.

## Unzureichende Scheinlösungen

Folgende Änderungen schließen den Audit ausdrücklich nicht:

1. Nur das UI-Label der Goal Drivers oder des p5-p75-Bands ändern.
2. Contributions nach dem gewichteten Objective sortieren, aber ihre
   ungewichteten Werte beibehalten.
3. IS für betroffene Mandate deaktivieren; Auto-IS ist eine beabsichtigte
   Schutzfunktion.
4. Den Goal-Horizont auf den Run-Horizont überschreiben oder Goals still auf
   das letzte simulierte Jahr klemmen.
5. Nur den MC-Report oder nur den Optimizer reparieren.
6. `weight_bps=0` mit einem weiteren Truthiness-Fallback kaschieren.
7. Einen der beiden Hardness-Multiplikatoren entfernen, ohne rohe und
   effektive Gewichte sowie bestehende Daten zu migrieren.
8. Neue Felder in JSON schreiben, ohne Hash, Version, Readiness und
   kanalgleiche Consumer zu binden.
9. Grüne Bestandstests als Ersatz für die vier neuen Gegenbeispiele behandeln.

## Verifikationsnachweis

### Ausgeführtes fokussiertes Bestands-Gate

Aus `5eyes-backend` wurde ein isoliertes, cachefreies Core-Gate ausgeführt:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp=..\tmp\pytest-round33-core `
  tests/test_optimizer_scenario_engine.py `
  tests/test_optimizer_importance_sampling.py `
  tests/test_optimizer_is_auto_activation.py `
  tests/test_optimizer_objective_constraints.py `
  tests/test_optimizer_objective_with_weights.py `
  tests/test_optimizer_objective_dimensionless.py `
  tests/test_optimizer_explainability.py `
  tests/test_optimizer_goal_liabilities.py `
  tests/test_optimizer_effective_context.py `
  tests/test_optimizer_strict_core_contract.py `
  tests/test_optimizer_solver.py `
  tests/test_optimizer_solver_with_is.py `
  tests/test_optimizer_production_contract.py `
  tests/test_optimizer_integration.py `
  tests/test_monte_carlo_paths.py `
  tests/test_goal_scoring_horizon.py `
  tests/test_chance_constraint.py `
  tests/test_goals_conditional_probability_mc_path.py `
  tests/test_goals1_ahv_mc_path_consistency.py `
  tests/test_total_scope_goal_path_contract.py `
  tests/test_total_wealth_allocation.py `
  tests/test_sub_allocation_aware_returns.py `
  tests/test_simulation_rebalance_costs.py `
  tests/test_aa4_year1_var_cashflow_neutral.py `
  tests/test_aa10_max_drawdown_cashflow_neutral.py `
  tests/test_goal_domain_fail_closed_contracts.py `
  tests/test_allocation_preferences_fail_closed_contracts.py `
  tests/test_asset_allocation_current_integrity_contracts.py `
  tests/test_asset_allocation_remaining_integrity_edges.py `
  tests/test_asset_allocation_reference_integrity_edges.py
```

Ergebnis:

```text
609 passed in 176.99s (0:02:56)
```

Es gab keine Fehler und keine übersprungenen Tests. Das Gate beweist die oben
genannten Positivkontrollen. Es enthält jedoch weder den IS-Rank-Reversal-
Test noch das goal-horizont-spezifische Drei-Pfad-Gegenbeispiel noch die echte
Nullgewicht-/Hardness-Produktionsverkettung. Daher widerspricht sein grüner
Status den Findings nicht.

### Weitere bewusst nicht behauptete Gates

- Kein Browser-DOM-Lauf wurde in dieser Runde ausgeführt.
- Kein echter PostgreSQL-/Concurrency-Lauf wurde in dieser Runde ausgeführt.
- Kein Full-Backend-Gate wurde erneut gestartet; der dokumentierte
  609-Test-Fokus deckt den geprüften Kern ab und vermeidet eine
  ressourcenintensive Wiederholung unveränderter Bereiche.

## Dokumentationsmanifest

Diese Kontrollrunde ändert genau folgende fünf Dokumentationspfade:

1. `docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen und Runtime-Konfiguration bleiben
unverändert.

## Claude-Startcheckliste

Vor der ersten Codeänderung muss Claude:

1. diesen Audit vollständig lesen,
2. die Findings-IDs beibehalten und keine Duplikat-IDs erzeugen,
3. den September-2-Goal-/MC-Audit und den August-20-Core-Handoff lesen,
4. die vier Gegenbeispiele zuerst als rote Tests materialisieren,
5. die Owner-Entscheidung für `weight_bps=0` dokumentieren,
6. eine einzige Prefix-TWR- und eine einzige Weight-Estimator-
   Implementierung festlegen,
7. das Snapshot-/Manifest-Schema vor UI- oder PDF-Patches definieren,
8. Migration/Quarantäne für bestehende Goal-/Run-Daten planen,
9. nach jeder Phase die Invarianten und das 609-Test-Gate erneut ausführen,
10. und erst nach kanalgleichem Replay, echten PostgreSQL-Tests und
    Publication-Preflight eine Release-Freigabe beantragen.

## Releaseentscheidung

**Release bleibt hart blockiert.** Vor Freigabe müssen mindestens
`OPTIMIZER-IS-EVIDENCE-001`, `GOAL-RETURN-HORIZON-001` und die beiden
`GOAL-SCORE-001`-Erweiterungen geschlossen sein. Zusätzlich bleiben die
bereits offenen Goal-/MC-/Publication-P1 bestehen. Ein korrekter Optimizer
ohne korrekte Erklärung und ein korrektes Portfolio ohne zielhorizontgerechte
Erfolgswahrscheinlichkeit sind keine belastbare Beratungs- oder
Publikationsbasis.
