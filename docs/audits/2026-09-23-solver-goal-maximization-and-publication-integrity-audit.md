---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-solver-goal-maximization-and-publication-integrity-followup-audit"
status_as_of: "2026-09-27"
audit_started_on: "2026-09-22"
audit_completed_on: "2026-09-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "9a87afb0e5d952468f736112bbce0f23f4698246"
prior_numerical_audit_path: "docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md"
prior_core_audit_path: "docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-23-solver-goal-maximization-and-publication-integrity-audit.md"
audit_mode: "read_only_static_solver_acceptance_constraint_rounding_goal_objective_probability_and_publication_review_plus_deterministic_python_reproductions_and_focused_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "solver acceptance and fallback, continuous-to-bps feasibility, two-phase objective ordering and monetary-scale invariance, goal dispatch, targetless maximization semantics, goal probability, run horizon and API/Classic-UI/React/PDF publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 4
confirmed_prior_p1_extension_groups: 2
new_hardening_p2_count: 0
deterministic_reproduction_groups: 7
focused_existing_tests_passed: 488
focused_existing_tests_skipped: 0
focused_existing_tests_failed: 0
focused_existing_test_runs_confirmed: 1
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "reject raw infeasible solver outputs before any repair; replace argmax remainder rounding with deterministic constraint-aware 10000-bps apportionment; replace the candidate-dependent pseudo-two-phase objective with a scale-invariant lexicographic solve; freeze the Maximierung goal for real advice until an owner-approved targetless-growth objective, horizon, mixed-goal ordering, typed non-probability result and channel-parity contract are implemented; invalidate false 100-percent legacy evidence"
---

# Solver-, Objective-, Zielmaximierungs- und Publikationsintegritätsaudit

## Geltung, Abgrenzung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die fünfunddreißigste Read-only-
Kontrollrunde. Die Prüfung begann am 22. September und wurde am 27. September
2026 gegen den unveränderten Repository-Head
`9a87afb0e5d952468f736112bbce0f23f4698246` abgeschlossen. Produktcode,
Tests, Migrationen und Runtime-Konfiguration wurden nicht verändert. Nach der
Prüfung werden ausschließlich die fünf Pfade des Dokumentationsmanifests
angepasst.

Geprüft wurden:

1. Annahme, Ablehnung und Fallback von SLSQP-/DE-Kandidaten,
2. kontinuierliche und auf ganzzahlige Basispunkte gerundete Constraints,
3. produktive Revalidierung und Re-Evaluation des aktiven House-Fallbacks,
4. Goal-Dispatch, Shortfall, Chance Probability und kombinierte Objective,
5. die besondere Semantik des Zieltyps `Maximierung`,
6. Goal-Horizont und gemischte Zielsets,
7. sowie Persistenz, API, Classic UI, React-Report und beide PDF-Kanäle.

Der Audit ersetzt keine Finding-ID der Audits vom 21. und 22. September.
`GOAL-PUBLICATION-001` bleibt der allgemeine Vertrag für kanalgleiche,
rungebundene Goal-Evidence. `GOAL-DOMAIN-001` bleibt der allgemeine Vertrag
für validierte Probability- und Goal-Domänen. Vier neue IDs beschreiben
getrennte Fehlergrenzen: `SOLVER-CANDIDATE-ACCEPTANCE-001` betrifft die
Annahme erst nach synthetischer Projektion, `SOLVER-BPS-APPORTIONMENT-001`
die constraints-blinde Restverteilung auf 10.000 Basispunkte,
`OPTIMIZER-TWO-PHASE-OBJECTIVE-001` die kandidatenabhängige Umschaltung
zwischen Ziel- und Volatilitätsobjective und
`GOAL-MAXIMIZATION-OBJECTIVE-001` die Tatsache, dass der
unterstützte Produkttyp „Maximierung“ in der Entscheidung kein
Maximierungsziel ist, aber anschließend als sicher erreicht veröffentlicht
wird.

Aktueller Code und ausgeführte Reproduktionen haben Vorrang bei der
Beschreibung des Ist-Stands. Die Planungsdokumente werden nur dort als
zusätzlicher Soll-Anker verwendet, wo sie eine eindeutig abweichende
Produktsprache festhalten. Grüne Bestandstests beweisen vorhandene
Positivkontrollen; sie widerlegen kein Gegenbeispiel, das von ihnen nicht
assertiert wird.

## Kurzurteil

In dieser Runde wurden **vier neue release-blockierende P1** reproduziert.
Die vorhandenen Endkontrollen erkennen viele Constraint-Verletzungen, aber
zwei vorgelagerte Transformationen verfälschen die Herkunft beziehungsweise
verwerfen einen vorhandenen zulässigen Integer-Kandidaten:

**`SOLVER-CANDIDATE-ACCEPTANCE-001`:** Ein finiter Non-success-Rohkandidat
wird vor seiner Feasibility-Prüfung geclippt und normalisiert. Die so erzeugte
synthetische Allocation kann als `feasible_candidate=True` in die
Robustifizierung eingehen. Im Gegenbeispiel lieferten alle SLSQP- und DE-
Versuche ausschließlich `x=[2,2,2,2,2]`, `success=False`; dennoch endete der
Run als `converged_robustified` und aktivierbare 100-Prozent-Liquiditäts-
Allocation. Damit wird weder ein erfolgreicher Solver noch ein von ihm
gelieferter zulässiger Kandidat ausgewiesen.

**`SOLVER-BPS-APPORTIONMENT-001`:** Die Basispunktkonvertierung rundet jeden
Bucket einzeln und gibt die gesamte Restsumme immer dem größten Gewicht. Bei
einer kontinuierlich zulässigen Allocation an einer 50-Prozent-Aktien- und
Risk-Cap-Grenze entstehen dadurch 5.001 Aktien-bps. Der Post-Round-Check
erkennt die Verletzung und stuft den erfolgreichen Solver als
`diverged_infeasible` zurück, obwohl die streng nähere Verteilung
`5000/1750/999/999/1252` exakt 10.000 bps summiert und alle Constraints
erfüllt. Produktiv kann dies unnötig die House-Allocation aktivieren.

**`OPTIMIZER-TWO-PHASE-OBJECTIVE-001`:** Die kombinierte Objective fügt
Volatilität nur bei einem Kandidaten mit `primary + chance < 1e-12` hinzu.
Ein vollständig zielerfüllender Kandidat zahlt dadurch eine positive
Varianzstrafe; ein Kandidat mit noch so kleinem Shortfall oberhalb der
Switchschwelle zahlt gar keine Varianzstrafe. Im Gegenbeispiel verlor der
vollständig erfüllende Kandidat mit Objective `2.5e-05` gegen einen Kandidaten,
der einen von 100 Pfaden um zwei Rappen verfehlte und nur `4e-12` zahlte. Bei
einem zweiten Paar kippte die Rangfolge allein durch Multiplikation aller
Geldwerte mit zehn. Damit ist die angebliche Sekundäroptimierung weder
lexikografisch noch skaleninvariant.

Im Goal-Herzstück wurde der vierte P1 reproduziert:

**`GOAL-MAXIMIZATION-OBJECTIVE-001`:** Ein `Maximierung`-Goal erzeugt eine
Null-Liability, null Shortfall auf jedem Pfad, Erfolg eins auf jedem Pfad und
keine Chance-Penalty. Sobald Primary plus Chance null sind, minimiert die
kombinierte Objective die Varianz des Endvermögens. Ein reiner
Maximierungs-Run ist daher entscheidungsseitig exakt gleich zu einem Run ohne
Ziele und bevorzugt
unter sonst gleichen Bedingungen geringeres statt höheres erwartetes oder
medianes Endvermögen. Trotzdem werden Probability, Tau, Status, Haupt-MC-
Score, mediane Zielerreichung und pessimistischer Fehlbetrag als
`1.0 / 1.0 / erreichbar / 100 / 100 / 0` ausgegeben. Selbst vier Pfade mit
vollständigem Vermögensverlust werden als vier Erfolge gezählt.

Der falsche Wert bleibt nicht intern. Er wird in `TargetAllocation`
persistiert, per Current-Payload geliefert, im Classic-Review als grünes
100-Prozent-Ziel gerendert, kann die Hauptziel-Kachel belegen, erhöht den
gewichteten Advisory-Zielscore und erscheint im React-Report sowie in
Strategie- und Advisory-PDF. Damit betrifft der Befund Entscheidung,
Erklärung und kundenwirksame Publikation.

Es wurde kein neuer P0 bestätigt. Die Releasefreigabe bleibt wegen dieser
vier P1 und der bereits offenen P1 ausgeschlossen.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `SOLVER-CANDIDATE-ACCEPTANCE-001` | P1 | neu bestätigt | Roh infeasible Non-success-Ausgaben werden vor der Prüfung synthetisch repariert und können danach als `converged_robustified` aktivierbar werden. |
| `SOLVER-BPS-APPORTIONMENT-001` | P1 | neu bestätigt | Die argmax-Restverteilung kann eine kontinuierlich zulässige Lösung unnötig verletzen und trotz vorhandener zulässiger 10.000-bps-Verteilung einen House-Fallback auslösen. |
| `OPTIMIZER-TWO-PHASE-OBJECTIVE-001` | P1 | neu bestätigt | Die kandidatenabhängige Volatilitätsumschaltung kann einen minimal zielverletzenden Kandidaten gegenüber vollständiger Erfüllung bevorzugen und ändert die Rangfolge mit der Geldwertskala. |
| `GOAL-MAXIMIZATION-OBJECTIVE-001` | P1 | neu bestätigt | `Maximierung` ist entscheidungsseitig identisch zu „kein Ziel“ und löst Varianzminimierung aus, wird aber als sicher erreicht und mit Score 100 publiziert. |
| `GOAL-PUBLICATION-001` | P1 | offen, neue Evidence | Die falsche 100-Prozent-Aussage fließt ungefiltert durch Persistenz, API, Classic UI, React, Strategie-PDF und Advisory-PDF. |
| `GOAL-DOMAIN-001` | P1 | offen, neue Evidence | Ein targetloses Optimierungsziel wird fälschlich in dieselbe Probability-/Tau-/Status-Domain wie binäre Mindestziele gezwungen; unbekannte interne `target_kind` fallen weiterhin still auf null Shortfall/eins Erfolg. |
| Solver-/Constraint-/Fallback-Endkontrollen | — | positive Kontrolle mit Lücken | Continuous- und Integer-bps-Endkandidat, Aktivierung und aktiver House-Fallback werden gegen harte Constraints geprüft; diese Kontrollen beweisen aber weder die Provenienz eines zuvor projizierten Rohkandidaten noch die Existenz einer besseren zulässigen bps-Apportionierung. |

Keine bestehende Finding-ID wird durch diesen Audit geschlossen.

## Ende-zu-Ende-Systembild

```text
Non-success raw x=[2,2,2,2,2]
              |
              v
      clip + normalize zuerst
              |
              v
 synthetischer feasible Kandidat --------> converged_robustified

continuous feasible an Cap
              |
              v
 round je Bucket + Rest zu argmax
              |
              v
 5.001 Aktien-bps, Cap verletzt ----------> diverged_infeasible/House

vollständig erfüllter Goal-Kandidat
              |
              v
 primary + chance = 0 --> + 1e-12 * raw Var(Rappen)

minimal verfehlter Goal-Kandidat
              |
              v
 primary > epsilon ------> keine Varianzstrafe
              |
              v
  schlechtere Zielerfüllung kann gewinnen

GoalCreate(goal_type="Maximierung")
              |
              v
GoalLiability(target_kind="maximize", target=0)
              |
       +------+-------------------+
       |                          |
       v                          v
Shortfall je Pfad = 0     Success je Pfad = 1
       |                          |
       +------------+-------------+
                    v
        Primary + Chance = 0
                    |
                    v
        min Varianz(terminal wealth)
        (identisch zu keine Goals)
                    |
                    v
       Probability 100 %, erreichbar
                    |
      +-------------+----------------------------+
      |             |             |              |
      v             v             v              v
Current API      Classic UI   React Report   Strategie-/Advisory-PDF
      |                           |
      +-------------+-------------+
                    v
       gewichteter Zielscore kann steigen
```

Die falsche Aussage entsteht damit vor UI und PDF. Ein reines
Darstellungs-Patch kann weder die Allocation noch die gespeicherte Evidence
reparieren.

## Positivkontrollen, die erhalten bleiben müssen

1. `goal_to_liability()` normalisiert öffentliche Goal-Typen zentral und
   weist unbekannte öffentliche Typen zurück.
2. Externe bps-Allocations müssen exakt die fünf Optimizer-Buckets enthalten,
   ganzzahlig sein, im Bereich `0..10000` liegen und exakt 10.000 bps summieren.
3. Ein finiter Non-success-Kandidat wird nicht allein wegen vorhandener
   Gewichte angenommen. Der aktuelle Code prüft jedoch erst die bereits
   geclippte und normalisierte Form; die Roh-Feasibility muss vor jeder
   Reparatur geprüft werden.
4. Der kontinuierliche Endkandidat wird vor Ausgabe auf Bounds, Sum-to-one
   und alle Constraints geprüft.
5. Die tatsächlich ausgegebene Integer-bps-Allocation wird nach Rundung
   erneut geprüft; eine Rundungsverletzung darf keinen `converged`-Status
   behalten. Vor dem Fallback muss künftig zusätzlich eine constraints-
   bewusste zulässige 10.000-bps-Apportionierung gesucht werden.
6. Die produktive Integrationsgrenze revalidiert einen als konvergiert
   gemeldeten Kandidaten vor Aktivierung.
7. Ein abgelehnter Solverkandidat bleibt auditierbar, wird aber nicht als
   aktive Allocation publiziert.
8. Der tatsächlich aktive House-Fallback wird unter dem retained
   `OptimizerContext` neu auf Objective, Feasibility und Goal-Probability
   ausgewertet.
9. Domain-/Programmierfehler werden nicht pauschal in normalen House-Fallback
   umgedeutet; nur die explizite technische/numerische Allowlist darf diesen
   Pfad auslösen.
10. Ergebnis-Objective und Goal-Achievability werden nach Integer-bps-Rundung
    auf den tatsächlich zurückgegebenen Gewichten neu berechnet.

Diese Endkontrollen sollen bei den Reparaturen erhalten und um vorgelagerte
Provenienz- und Apportionierungsverträge ergänzt werden.

## Codeanker des auditierten Stands

### Solverannahme und Basispunkt-Apportionierung

- `5eyes-backend/services/optimizer/solver.py:683-700` implementiert
  `_normalize_to_bounds()` als Clip, Skalierung, erneuten Clip und erneute
  Skalierung. Die Funktion selbst verspricht nur Best Effort.
- `5eyes-backend/services/optimizer/solver.py:1051-1086` prüft in
  `_finite_feasible_candidate()` zunächst nur Shape und Endlichkeit des
  Rohvektors. Danach wird dieser geclippt und normalisiert; erst die daraus
  erzeugte Allocation geht in `is_feasible()` ein.
- `5eyes-backend/services/optimizer/solver.py:1300-1467` sammelt solche
  projizierten Kandidaten aus allen SLSQP-Starts und dem DE-Fallback. Wenn kein
  Solver `success=True` meldet, kann der beste davon ausgewählt, weiter
  derisked und als akzeptierter Non-success-Kandidat markiert werden.
- `5eyes-backend/services/optimizer/solver.py:1514-1535` validiert sowohl den
  kontinuierlichen Endkandidaten als auch seine Basispunktform. Eine
  Rundungsverletzung wird korrekt als `diverged_infeasible` markiert.
- `5eyes-backend/services/optimizer/solver.py:1640-1652` rundet jeden Bucket
  separat und schlägt die gesamte Differenz zu 10.000 bps stets dem größten
  kontinuierlichen Bucket zu, ohne dessen Bound oder den Risk-Cap bei der
  Auswahl des Restempfängers zu berücksichtigen.
- `5eyes-backend/services/portfolio_engine_optimizer_integration.py:134-141`
  zählt `converged_robustified` zu den konvergierten Status; `:493-518`
  übernimmt dessen Basispunktgewichte als Zielallokation.
- `5eyes-backend/services/portfolio_engine.py:3364-3375` und `:3627-3635`
  führen einen nicht konvergierten Hauptpfad in die Synchronisierung des
  aktiven House-Fallbacks; die Integrationslogik in
  `portfolio_engine_optimizer_integration.py:540-653` bewertet und publiziert
  anschließend dessen tatsächlich aktive Gewichte neu.
- `5eyes-backend/services/recommendation_audit.py:30-40` zählt
  `fallback_house_matrix` zu den akzeptablen Status, während
  `mandate_lock_audit.py:96-109` `diverged_infeasible`, nicht aber den
  synchronisierten Fallback sperrt. Der unnötige Methodenwechsel kann daher
  regulär weiterpubliziert werden.
- `5eyes-backend/services/portfolio_engine.py:4368-5382` gibt in der Goal-
  Sensitivität Solvergewichte und Status ohne die Hauptpfad-Synchronisierung
  zurück. Ein rundungsbedingt `diverged_infeasible` markierter 5.001-bps-
  Kandidat kann so zusätzlich in Sensitivitätsevidence erscheinen.
- `docs/planning/2026-05-24-stochastic-stage9-spec-solver-robustifizierung.md:128-148`
  erlaubt Finite-feasible Candidate Acceptance nur nach unabhängiger strikter
  Prüfung aller harten Constraints und ausdrücklich nicht als Ersatz für eine
  tatsächliche Constraint-Verletzung. `:236-245` wiederholt diese Reihenfolge
  in der Eskalationslogik.

### Kandidatenabhängiger Objective-Phasenwechsel

- `5eyes-backend/services/optimizer/objective.py:594-641` nennt die Funktion
  `combined_objective_two_phase()`, führt aber keinen zweiten Solve aus. Die
  rohe Endvermögensvarianz wird für jeden einzelnen Kandidaten nur dann
  addiert, wenn dessen `primary + chance < epsilon` ist.
- Die Primary-Objective ist dimensionslos normalisiert, während
  `volatility_objective()` in `objective.py:482-513` rohe Rappen zum Quadrat
  liefert. Der feste Faktor `1e-12` stellt keine Einheiteninvarianz her.
- `5eyes-backend/services/optimizer/solver.py:593-611` nutzt diese Funktion
  direkt im Solver-Closure; `:615-641` nutzt sie erneut in
  `evaluate_weights()`. Der Befund beeinflusst daher Auswahl und spätere
  Bewertung mit derselben falschen Rangordnung.
- `docs/planning/2026-05-05-stochastic-optimizer-spec.md:115-120` beschreibt
  stattdessen eine echte Sekundäroptimierung: erst `L(w*)`, danach Varianz
  unter `L(w) <= L(w*) + delta` und allen übrigen Constraints; `:389-401`
  zeigt dafür ausdrücklich einen zweiten Solve.
- `5eyes-backend/tests/test_optimizer_objective_dimensionless.py:31-65`
  prüft Geldskalierung nur bei `volatility_weight=0`. `:179-207` bestätigt
  sogar, dass bei einem kleinen positiven Primary-Wert keine Volatilität
  berechnet wird, vergleicht diesen Kandidaten aber nicht mit vollständiger
  Zielerfüllung.

### Produkttyp, Liability und Objective

- `5eyes-backend/schemas/wealth.py:430-544` führt `Maximierung` als reguläre
  Goal-Familie und regulären Goal-Typ. Ein fixer Betrag, eine Zielrendite und
  ein Zieldatum sind verboten; `horizon_years` ist im Schema dagegen
  weiterhin akzeptiert.
- `5eyes-backend/services/optimizer/goal_liabilities.py:43-65` dokumentiert
  `maximize` als „keine Constraint, nur in Vol-Min relevant“.
- `5eyes-backend/services/optimizer/goal_liabilities.py:488-501` erzeugt eine
  Null-Liability und setzt `target_year_index` auf den globalen Run-Horizont.
- `5eyes-backend/services/optimizer/objective.py:198-199` setzt den Shortfall
  eines Maximierungsziels auf einen Nullvektor.
- `5eyes-backend/services/optimizer/objective.py:293-294` setzt den Erfolg
  eines Maximierungsziels auf einen Einsvektor.
- `5eyes-backend/services/optimizer/objective.py:99-100` setzt den Default-
  Tau auf 100 Prozent; `:393` nimmt `maximize` zugleich aus der Chance-Penalty.
- `5eyes-backend/services/optimizer/objective.py:482-513` definiert die
  sekundäre Objective als Varianz des terminalen Vermögens.
- `5eyes-backend/services/optimizer/objective.py:594-641` aktiviert genau
  diese Varianzminimierung, wenn Primary plus Chance numerisch null sind.

### Haupt-Monte-Carlo und Publikation

- `5eyes-backend/services/portfolio_engine_mc_simulation.py:1044-1048`
  setzt für `Maximierung` `success_rate_pct=100` und `score=100`, unabhängig
  von den simulierten Werten.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:1086-1088` setzt
  mediane Zielerreichung auf 100 und pessimistischen Fehlbetrag auf null.
  Der gleichzeitig zurückgegebene `funded_ratio_p50` kann dennoch kleiner als
  eins sein.
- `5eyes-backend/services/portfolio_engine.py:3803-3813` persistiert die
  Achievability-Zeilen; `:4122-4123` liefert sie im Generate-Payload.
- `5eyes-backend/services/portfolio_engine.py:6068-6084` lädt dieselben Zeilen
  wieder; `:6124-6125` liefert sie im Current-Payload.
- `5eyes-backend/services/advisory_report.py:704-735` bezieht jede
  Probability-Zeile ohne Zieltypfilter in den gewichteten Gesamt-Score ein.
- `5eyes-backend/services/advisory_report.py:2018-2052` publiziert die Zeile
  und denselben Score in Goal-Based Investing.
- `5eyes-electron/frontend/5eyes_v2.html:7483-7501` rendert die Probability im
  Optimizer-Panel; `:24286-24298` kann die Zeile zum Hauptziel wählen;
  `:24320-24335` zeigt sie im Review-Cockpit mit grüner 100-Prozent-Ampel.
- `5eyes-electron/frontend/reporting/src/pages/Goals.tsx:54-67` publiziert den
  gewichteten Score; `:164-181` Probability und Status je Ziel.
- `5eyes-backend/services/pdf/components/goal_achievability.py:214-278`
  rendert `maximize` als Maximierung mit Probability-Balken und Status.
- `5eyes-backend/services/pdf/documents/advisory_report.py:1350-1420` rendert
  Gesamt-Score, Probability und Status im Advisory-PDF.

### UI-Zeitfenster

- `5eyes-electron/frontend/5eyes_v2.html:26288-26296` zeigt für
  `Maximierung` nur das Prioritätsfeld. Der Zeithorizont ist ausgeblendet.
- `5eyes-electron/frontend/5eyes_v2.html:26509-26512` sagt gleichzeitig, Scope
  und Zeitfenster seien relevant.
- `5eyes-electron/frontend/5eyes_v2.html:26720-26809` sendet das versteckte
  `horizon_years`-Feld grundsätzlich mit und entfernt für Maximierung nur das
  Zieldatum.
- Der Liability-Builder liest `goal.horizon_years` für Maximierung nicht; er
  ersetzt es durch den allgemeinen Solverhorizont.

### Bestandstests, die das heutige Verhalten festschreiben

- `5eyes-backend/tests/test_optimizer_objective_constraints.py:232-236`
  assertiert, dass der Maximierungs-Shortfall immer null ist.
- `5eyes-backend/tests/test_optimizer_solver.py:608-643` assertiert, dass ohne
  Goals deterministisch die terminale Vermögensvarianz minimiert wird.
- Es existiert kein Gegenstück, das `Maximierung` gegenüber „keine Goals“
  unterscheidet, eine Wachstumsmetrik maximiert oder bei Totalverlust die
  100-Prozent-Aussage verbietet.

## `SOLVER-CANDIDATE-ACCEPTANCE-001` – Projektion ersetzt den gelieferten Kandidaten

### Reproduktion: ausschließlich roh infeasible Non-success-Ausgaben

Beide Solver-Einstiegspunkte wurden deterministisch so instrumentiert, dass
jeder SLSQP-Start und der DE-Fallback dasselbe `OptimizeResult` lieferten:

```text
x       [2.0, 2.0, 2.0, 2.0, 2.0]
sum(x)  10.0
success False
status  9
message forced non-success raw infeasible
```

Bounds und Risk-Cap des Testkontexts waren bewusst weit genug, dass eine
echte zulässige Allocation existierte. Kein Solver meldete Erfolg; keiner
lieferte Sum-to-one oder einen raw-validen Kandidaten. `run_solver()` endete
dennoch wie folgt:

```text
status       converged_robustified
method       stochastic
weights_bps  {'equities': 0, 'bonds': 0, 'real_estate': 0,
              'alternatives': 0, 'liquidity': 10000}
objective    0.0021833878900947485

attempts     5 x SLSQP + 1 x differential_evolution
             alle status=non_success, alle feasible_candidate=True
projected attempt objective  1.622411858278759
final_reason strict_feasibility_check_passed_risk_tiebreak_derisked
```

Die Endallocation ist für sich zulässig. Genau deshalb reicht die spätere
Feasibility-Prüfung nicht: Sie kann nicht mehr erkennen, dass der Solver diese
Allocation nie geliefert hat. Der Rohvektor wurde zuerst auf eine andere
Allocation projiziert und anschließend nochmals durch die Derisking-Logik
verändert. Trotzdem behaupten Status und Integrationsmeldung, der Optimizer
sei mit Stage-9-Robustifizierung konvergiert und die Allocation könne aktiv
angewendet werden.

### Warum dies P1 ist

1. Die Stage-9-Spezifikation erlaubt die Ausnahme nur für einen vom Solver
   gelieferten finite-feasible Kandidaten, nicht für eine beliebige nachträglich
   erzeugte Allocation.
2. Shape und Endlichkeit sind keine Feasibility; `x=[2,2,2,2,2]` verletzt
   Sum-to-one und alle oberen Bounds eines üblichen Kontexts offensichtlich.
3. `converged_robustified` ist produktiv ein aktivierbarer Status. Der Fehler
   betrifft daher reale Zielgewichte und nicht nur Diagnosetext.
4. Eine nachgelagerte Revalidierung bestätigt lediglich die synthetische
   Allocation und kann die verlorene Provenienz nicht wiederherstellen.
5. Beliebig schlechte oder defekte Solver-Ausgaben können so eine fachlich
   neue Allocation begründen, ohne dass deren Erzeugung als eigener Solve-
   Schritt, Fallback oder Projection-Verfahren ausgewiesen wird.

### Verbindlicher Reparaturvertrag

1. Rohvektor zuerst unverändert gegen Shape, Endlichkeit, Sum-to-one,
   sämtliche Bounds und sämtliche Constraints prüfen.
2. Nur ein in dieser Rohform zulässiger Non-success-Kandidat darf unter dem
   bisherigen Stage-9-Vertrag als `converged_robustified` akzeptiert werden.
3. Eine minimale numerische Reparatur ist nur mit explizit versionierter
   Toleranz, maximaler Distanz, vollständigem Vorher-/Nachher-Audit und
   constraint-bewusster Projektion zulässig. Sie ist als eigener
   Projection-/Solve-Schritt zu klassifizieren, nicht als Annahme des
   gelieferten Kandidaten.
4. Evidence muss Raw-Hash beziehungsweise Raw-Werte, Raw-Verletzungen,
   Reparaturquelle, Reparaturdelta, Solverstatus und finalen Kandidaten binden.
5. Ist der Rohkandidat infeasible, läuft die definierte Retry-/Fallbackkette
   weiter. Ein späterer zulässiger Fallback muss ehrlich dessen Methode und
   Status tragen.

### Rote Tests

1. `x=[2,2,2,2,2], success=False` ergibt nie
   `feasible_candidate=True` und nie `converged_robustified`.
2. Auch `success=True` darf einen roh infeasible Kandidaten nicht durch
   Projektion in einen konvergierten Status heben.
3. Ein raw-feasible `success=False`-Kandidat wird weiterhin nach unabhängiger
   Objective-/Constraint-Prüfung akzeptiert.
4. Werte knapp innerhalb und knapp außerhalb jeder versionierten Toleranz
   liefern deterministisch unterschiedliche Entscheidungen.
5. Jede erlaubte Reparatur persistiert Raw-Verletzung, Distanz, Algorithmus-
   version und den tatsächlich aktivierten Kandidaten.
6. Die produktive Aktivierungsgrenze lehnt einen Status ab, dessen Provenienz
   nicht zum finalen Kandidaten passt.

## `SOLVER-BPS-APPORTIONMENT-001` – Zulässige Rundung wird nicht gesucht

### Reproduktion: direkte Rundung an Bound und Risk-Cap

Für einen validen Context mit Equity-Upper-Bound `0.50`, Risk-Cap `0.50`,
`risky_fraction(equities)=1`, Risky Fraction null für die übrigen Buckets und
den produktiven globalen Real-Estate-/Alternatives-Caps war der folgende
Vektor kontinuierlich zulässig:

```text
[0.50000, 0.17494, 0.09994, 0.09994, 0.12518]
```

liefert `_weights_to_bps_dict()`:

```text
equities 5001, bonds 1749, real_estate 999,
alternatives 999, liquidity 1252
```

Die Einzelrundungen ergeben nur 9.999 bps. Weil Aktien der größte Bucket
sind, wird der Rest dort addiert. Damit liegt Equity bei 50,01 Prozent und
verletzt sowohl die 50-Prozent-Upper-Bound als auch den daran gebundenen
Risk-Cap um einen Basispunkt. Eine streng nähere zulässige Verteilung
existiert; ihr Fehler ist unter L1, quadratischer L2 und L-infinity kleiner:

```text
equities 5000, bonds 1750, real_estate 999,
alternatives 999, liquidity 1252
```

### End-to-End-Bestätigung: erfolgreicher Solver wird produktiv zurückgestuft

Mit einem deterministisch erfolgreichen Solverresultat und dem
kontinuierlichen Kandidaten

```text
[0.50000, 0.17494, 0.09994, 0.09994, 0.12518]
```

waren Summe, House-Bounds, globale Real-Estate-/Alternatives-Limits und der
Risk-Cap zulässig. `run_solver()` gab dagegen aus:

```text
status       diverged_infeasible
weights_bps  {'equities': 5001, 'bonds': 1749, 'real_estate': 999,
              'alternatives': 999, 'liquidity': 1252}
violations   equities above max 0.5000 (got 0.5001)
             ineq constraint violated (value=-0.000100)
```

Die deterministische Alternative
`5000/1750/999/999/1252` summiert exakt 10.000 bps und erfüllt dieselben
Constraints. Der Post-Round-Check arbeitet korrekt, aber zu spät: Statt eine
zulässige Apportionierung zu suchen, wird ein erfolgreicher kontinuierlicher
Solve als infeasible verworfen. Die Produktions-Fallback-Synchronisierung
wurde ebenfalls ausgeführt und ersetzte den verworfenen Kandidaten tatsächlich
durch `3000/5000/500/500/1000` mit Status und Methode
`fallback_house_matrix`.

### Warum dies P1 ist

1. Der Befund kann Methode, Status und aktive Beratung allokationswirksam auf
   House-Fallback umschalten, obwohl eine zulässige 10.000-bps-Lösung direkt
   neben dem kontinuierlichen Optimum existiert.
2. Bindende Upper-Bounds und Risk-Caps sind normale Optimizerfälle, keine
   pathologische Eingabe.
3. Die heutige Korrektur ist weder constraint-bewusst noch eine optimale
   größte-Rest-/Distanz-Apportionierung; `argmax(weights)` ist fachlich kein
   zulässiger Empfängerbeweis.
4. Der korrekte Post-Round-Check verhindert zwar eine Constraint-Verletzung,
   aber nicht die unnötige Änderung der Empfehlung durch falschen Fallback.

### Verbindlicher Reparaturvertrag

1. Die Basispunktkonvertierung als deterministische ganzzahlige Projektion auf
   exakt 10.000 bps implementieren. Bei fünf Buckets kann die engste
   Floor-/Ceil-Nachbarschaft vollständig enumeriert werden; maximal 32
   Kombinationen werden auf Summe und Constraints geprüft.
2. Liefert diese engste Nachbarschaft nichts, muss eine begrenzte ganzzahlige
   Feasibility-/Projektionssuche folgen; die 32 Kandidaten allein beweisen
   keine globale Integer-Infeasibility.
3. Integer-Unter-/Obergrenzen, lineare Risk-Caps und weitere in bps
   ausdrückbare harte Constraints bereits bei der Restverteilung einhalten.
4. Unter den zulässigen Integerlösungen zuerst eine versionierte Distanz und
   gegebenenfalls Objective-Verlust minimieren und danach deterministisch nach
   dokumentierter Bucket-Reihenfolge tie-breaken.
5. Nur wenn nachweislich keine zulässige 10.000-bps-Lösung existiert, darf der
   Pfad als Integer-infeasible enden; dieser Grund ist von Continuous-
   Infeasibility zu unterscheiden.
6. Evidence bindet kontinuierliche Gewichte, Integergewichte, Deltas,
   Algorithmusversion, Constraint-Slacks und Feasibility-Nachweis.

### Rote Tests

1. Das direkte und das End-to-End-Cap-Gegenbeispiel ergeben die zulässigen
   5.000 Aktien-bps und behalten einen konvergierten Status.
2. Restverteilung respektiert gleichzeitig mehrere aktive Lower-/Upper-Bounds
   und einen linearen Risk-Cap.
3. Gleichstände sind deterministisch, plattformstabil und idempotent.
4. Kleine Fälle werden gegen eine vollständige Brute-Force-/Integer-Oracle
   geprüft; jede vorhandene zulässige Lösung verhindert falschen Fallback.
5. Ein tatsächlich integer-infeasibles Constraint-Set liefert einen eigenen,
   belegten Status und wird nicht als Solverdivergenz fehlklassifiziert.
6. Auch bei negativer Rundungsdifferenz darf die Korrektur den größten Bucket
   nicht unter eine aktive Lower-Bound drücken.

## `OPTIMIZER-TWO-PHASE-OBJECTIVE-001` – Zielerfüllung zahlt eine Sprungstrafe

### Reproduktion: minimale Verfehlung schlägt vollständige Erfüllung

`combined_objective_two_phase()` wurde direkt mit einem primären
Vermögensziel über 100 gleich gewichtete Pfade, `tau=0.80`, einem Jahr und
`initial_wealth_rappen=100000` ausgewertet. Der vollständig erfüllende
Kandidat endete auf 50 Pfaden bei 90.000 und auf 50 Pfaden bei 100.000 Rappen;
das Ziel betrug 90.000 Rappen:

```text
vollständig erfüllt
  probability       1.00
  primary + chance  0
  raw variance      25,000,000 Rappen²
  objective         1e-12 * variance = 2.5e-05
```

Der Vergleichskandidat endete auf einem Pfad bei 89.998 und auf 99 Pfaden
bei 90.000 Rappen:

```text
ein Pfad um 2 Rappen verfehlt
  probability       0.99
  chance penalty    0, weil 0.99 >= tau 0.80
  primary           ((2 / 100000)^2) / 100 = 4e-12
  volatility term   0, weil primary + chance >= epsilon 1e-12
  objective         4e-12
```

Die Objective erklärt damit die minimale Zielverfehlung für rund 6,25
Millionen Mal besser als vollständige Erfüllung. Der Sprung entsteht nicht
aus einer fachlichen Risikoabwägung, sondern ausschließlich daraus, dass die
Volatilitätsstrafe kandidatenabhängig vollständig ein- oder ausgeschaltet
wird.

### Skalenreproduktion: identische Ökonomie kippt die Rangfolge

Ein zweites Kandidatenpaar verwendete dieselbe vollständig erfüllende
Verteilung. Der andere Kandidat verfehlte auf einem von 100 Pfaden das Ziel
um zehn Prozent des Initialvermögens. Seine dimensionslose Primary-Objective
war `0.0001`; die Probability blieb mit `0.99` oberhalb Tau.

```text
Skala 1:
  vollständig erfüllt  0.000025
  ein Pfad verfehlt     0.000100
  Gewinner              vollständig erfüllt

alle Geldwerte x 10:
  vollständig erfüllt  0.002500
  ein Pfad verfehlt     0.000100
  Gewinner              ein Pfad verfehlt
```

Initialvermögen, Ziel und sämtliche Wealth-Werte wurden gemeinsam mit zehn
multipliziert; Wahrscheinlichkeiten und relative Fehlbeträge blieben gleich.
Die rohe Rappenvarianz stieg jedoch um Faktor 100, während Primary und Chance
dimensionslos konstant blieben. Eine reine Änderung der Geldeinheit oder
Mandatsgröße kann deshalb die Optimizerpräferenz umkehren.

### Warum dies P1 ist

1. Der Fehler betrifft gewöhnliche Vermögens-, Cashflow- und Renditeziele,
   nicht nur den separat defekten Typ `Maximierung`.
2. Die reale Solver-Closure und `evaluate_weights()` verwenden dieselbe
   Funktion; die falsche Ordnung steuert somit Auswahl, gespeicherte
   Objective und spätere Vergleichs-/Erklärpfade.
3. Vollständige Zielerfüllung kann exakt wegen ihres Phase-2-Eintritts
   schlechter bewertet werden als eine Verfehlung. Das kehrt die deklarierte
   Priorität „Goals zuerst, Risiko danach“ um.
4. Der Fehler ist deterministisch und durch mehr Pfade, andere Seeds oder
   bessere numerische Konvergenz nicht behoben.
5. Die feste Mischung dimensionsloser Primary-Werte mit rohen Rappen² macht
   die Empfehlung von der Geldskala abhängig.

### Verbindlicher Reparaturvertrag

1. Die Spezifikation als echte lexikografische Optimierung umsetzen:
   Phase A minimiert Primary plus Chance und speichert das Optimum `L*`;
   Phase B minimiert eine versioniert normalisierte Risikometrik unter
   `L(w) <= L* + delta` sowie allen House-/Risk-Constraints.
2. `delta` absolut/relativ, numerisch begründet und in Evidence versionieren;
   es darf nicht implizit aus der Geldgröße entstehen.
3. Kein kandidatenseitiger `if primary < epsilon`-Switch innerhalb einer
   gemeinsamen skalaren Objective.
4. Volatilität beziehungsweise die gewählte Risikometrik dimensionslos oder
   auf eine explizite gemeinsame Context-Skala normalisieren.
5. Phase-A-/Phase-B-Status, `L*`, Delta, Risikometrik, Skala und finalen
   Constraint-Slack in `StochasticRunEvidence` binden.
6. Für leere Ziellisten und targetlose Wachstumsziele getrennte, explizite
   Verträge verwenden; sie dürfen nicht zufällig in denselben Switch fallen.

### Rote Tests

1. Der vollständig erfüllende Kandidat schlägt den Zwei-Rappen-Miss.
2. Gemeinsame Multiplikation aller Rappenwerte mit 10, 100 oder 0,01 ändert
   weder Rangfolge noch normalisierte Objective-Komponenten.
3. Phase B verschlechtert `L*` höchstens um das dokumentierte Delta.
4. Ein Kandidat knapp unter und knapp über dem früheren Epsilon erzeugt keinen
   diskontinuierlichen Wegfall der gesamten Risikometrik.
5. Probability oberhalb Tau neutralisiert die Chance-Penalty, aber nicht den
   lexikografischen Vorrang eines kleineren Primary-Shortfalls.
6. Solver-Closure, `evaluate_weights()`, robustified Kandidat und aktiver
   House-Fallback berichten dieselben versionierten Objective-Komponenten.

## `GOAL-MAXIMIZATION-OBJECTIVE-001` – Targetloses Wachstumsziel ist ein No-op

### Reproduktion 1: Maximierung ist exakt identisch zu keiner Zielliste

Mit den echten Produktionsfunktionen `run_solver()`, der realistischen
Wachstums-CMA und House-Matrix aus `test_optimizer_solver.py`, Seed `4242`,
500 Pfaden und zehn Jahren wurden zwei Runs ausgeführt. Alle Inputs waren
gleich; nur die Goal-Liste unterschied sich.

```text
no_goal  converged
  {'equities': 4500, 'bonds': 3684, 'real_estate': 0,
   'alternatives': 0, 'liquidity': 1816}
  objective 223.239413853

maximize converged
  {'equities': 4500, 'bonds': 3684, 'real_estate': 0,
   'alternatives': 0, 'liquidity': 1816}
  objective 223.239413853

same_weights   True
same_objective True
achievability  probability=1.0, tau=1.0,
               status='erreichbar', hardness='opportunistisch'
```

Das Ergebnis ist nicht nur ähnlich. Gewichte und Objective sind exakt gleich.
Das Maximierungsziel fügt der Optimierung keinerlei Präferenz für Wachstum
hinzu.

### Reproduktion 2: Feasible höhere Wealth-Verteilung verliert

Unter demselben retained Context wurde die gewählte Allocation gegen eine
ebenfalls vollständig feasible Wachstumsallocation verglichen:

```text
gewählt: 45.00 % Equity, 36.84 % Bonds, 0 % Real Estate,
          0 % Alternatives, 18.16 % Liquidity
  mean terminal wealth: CHF 734'616.22
  p50 terminal wealth:  CHF 718'913.61
  objective:            223.239413853

feasible growth: 65 % Equity, 23 % Bonds, 0 % Real Estate,
                 10 % Alternatives, 2 % Liquidity
  mean terminal wealth: CHF 822'406.80
  p50 terminal wealth:  CHF 788'593.93
  objective:            651.245544486
```

Die alternative Allocation besitzt im identischen Szenariowürfel rund
CHF 87'791 mehr erwartetes und rund CHF 69'680 mehr medianes Endvermögen.
Sie verliert ausschließlich, weil die aktuelle Objective geringere
Endvermögensvarianz belohnt. Für ein Produktziel mit der Bezeichnung
„Maximierung“ ist das die entgegengesetzte Optimierungsrichtung.

Diese Reproduktion behauptet nicht, dass die Wachstumsallocation fachlich
automatisch die richtige Empfehlung ist. Sie beweist, dass die aktuelle
Objective weder Mean noch Median noch Nutzen maximiert und das Goal daher
keine definierte Wachstumspräferenz ausdrückt.

### Reproduktion 3: Totalverlust gilt als sicherer Erfolg

`goal_probability_per_path()` wurde mit vier Wealth-Pfaden aufgerufen, deren
gesamte Werte einschließlich Endvermögen null waren:

```text
[1, 1, 1, 1]
```

Das widerspricht sogar dem schwachen historischen Planungsanker
`docs/planning/2026-05-05-stochastic-optimizer-spec.md:130-138`, der den
trivialen Score nur für `W_T > W_0` vorsah. Der Produktionscode prüft weder
Wachstum noch Kapitalerhalt; er setzt Erfolg bedingungslos auf eins.

### Reproduktion 4: akzeptierter Goal-Horizont wird verworfen

Ein valides `GoalCreate` mit `goal_type='Maximierung'` und
`horizon_years=3` wurde akzeptiert. Bei Konvertierung in einem zehnjährigen
Run entstand:

```text
schema_horizon               3
liability_target_year_index 10
run_horizon                 10
```

Die Classic UI blendet den Horizont für dieses Goal aus, nennt ein
„Zeitfenster“ aber relevant. Direkte API-Caller können einen Horizont setzen,
der anschließend still ignoriert wird. Damit ist selbst die Zeitbasis einer
künftigen Wachstumsmetrik heute nicht wahrheitsgetreu.

## Warum dies P1 ist

1. `Maximierung` ist ein vollständig unterstützter, sichtbarer Produkttyp,
   kein rein interner Debugmodus.
2. Das Goal kann eine reale Asset-Allocation beeinflussen, indem es gerade
   keine Wachstumspräferenz hinzufügt und dadurch die Min-Variance-Phase
   aktiviert.
3. Die Engine veröffentlicht Sicherheit für ein fachlich undefiniertes
   Ereignis; selbst Totalverlust bleibt 100 Prozent Erfolg.
4. In gemischten Zielsets ist das Goal entscheidungsseitig wirkungslos,
   reportingseitig aber wirksam. Der Advisory-Score berechnet beispielsweise
   aus einem echten Ziel mit `p=0.50, weight=5000` und Maximierung mit
   `p=1.00, weight=1000` einen Score von 58,33 Prozent statt 50 Prozent.
5. Der falsche Wert kann als Hauptziel und grüne Ampel erscheinen und in
   kundenwirksame beziehungsweise signierbare Dokumente gelangen.
6. Mehr Pfade, ein anderer Seed oder bessere Konvergenz lösen den Fehler
   nicht; die Semantik ist deterministisch falsch.

## Verbindlicher Reparaturvertrag

### 1. Fachliche Owner-Entscheidung vor Code

Der Name „Maximierung“ reicht mathematisch nicht. Der Owner muss genau einen
versionierten Vertrag wählen, zum Beispiel:

1. erwartetes terminales Vermögen,
2. medianes terminales Vermögen,
3. erwarteter Log-Nutzen,
4. CRRA-Nutzen mit dokumentiertem Risikoaversionsparameter,
5. oder eine explizite risikoadjustierte Wachstumsmetrik.

Die Empfehlung dieses Audits ist **nicht**, blind den Erwartungswert zu
maximieren. Eine rohe Mean-Wealth-Objective kann jede zulässige Risikogrenze
ausreizen und Tail-Risiken übergehen. Für Beratung ist typischerweise eine
versionierte Utility-/Risk-Trade-off-Entscheidung oder ein lexikografischer
Vertrag nötig. Bis diese Owner-Entscheidung vorliegt, ist der Goal-Typ für
reale Beratung zu sperren oder ehrlich als heutige Min-Variance-Funktion
umzubenennen.

### 2. Getrennte Resultattypen

Ein binäres Target-Goal darf weiter liefern:

```text
target_value, probability, tau, status, shortfall
```

Ein targetloses Optimierungsziel darf dagegen nicht synthetisch dieselben
Felder erhalten. Es benötigt einen diskriminierten Vertrag, etwa:

```text
objective_kind
metric_name
metric_version
horizon_years
baseline_allocation_id
baseline_metric
selected_metric
delta
wealth_quantiles
risk_metrics
```

Ohne binäres Ereignis gibt es keine „Erreichungswahrscheinlichkeit“, keinen
Tau und kein `erreichbar`.

### 3. Mixed-Goal-Ordnung

Für gemischte Zielsets muss die Reihenfolge explizit sein. Ein belastbarer
Vertrag wäre beispielsweise:

1. harte/primäre Shortfall- und Chance-Anforderungen minimieren,
2. das erreichte primäre Optimum nur innerhalb einer versionierten Toleranz
   verlassen,
3. innerhalb dieses zulässigen Sets die gewählte Wachstums-/Utility-Metrik
   maximieren,
4. erst danach Risiko als Tiebreak minimieren.

Alternativ ist ein vollständig spezifizierter Mehrziel-/Paretovertrag
zulässig. Nicht zulässig ist, das Maximierungsgewicht im Report zu verwenden,
aber in der Objective zu ignorieren.

### 4. Horizontwahrheit

Schema, UI, Builder und Evidence müssen denselben Maximierungshorizont
verwenden. Entweder wird ein explizites Pflichtfeld erfasst oder eine klar
benannte, versionierte Ableitungsregel verwendet. Ein akzeptiertes Feld darf
nicht still durch den Run-Horizont ersetzt werden.

### 5. Evidence und Persistenz

`StochasticRunEvidence` muss mindestens binden:

- Goal-Snapshot und Goal-Version,
- Objective-Kind und Methodenversion,
- exakten Horizont,
- Utility-/Risiko-Parameter,
- Mixed-Goal-Toleranz und Prioritätsreihenfolge,
- Baseline und ausgewählte Allocation,
- ausgewertete Metrik, Quantile und Risiken,
- Szenario-/Weight-/CMA-Hashes,
- Solver-/Fallbackstatus,
- sowie Publication-Readiness.

### 6. Publisher und Score

1. Targetlose Optimierungsziele werden nicht in einen Probability-
   Durchschnitt aufgenommen.
2. Classic UI, React, API und PDF rendern den diskriminierten Zieltyp mit
   derselben Metrik und demselben Horizont.
3. Ein fehlender oder legacy-untypisierter Vertrag ist `unavailable` oder
   `invalid`, niemals 100 Prozent.
4. Hauptziel-Kachel und Ampel dürfen nur echte, validierte Probability-Ziele
   verwenden.
5. Strategie- und Advisory-PDF müssen dieselbe Evidence-ID wie die aktive
   Allocation referenzieren.

### 7. Legacy-Migration

Alle bestehenden Runs mit `target_kind='maximize'` und Probability eins sind
als semantisch unbewiesen zu behandeln:

1. nicht still unter neuer Methodik weiterverwenden,
2. Goal- und Allocation-Snapshot deterministisch identifizieren,
3. soweit Inputs vollständig sind unter der neuen Version replayen,
4. sonst quarantänisieren,
5. alte 100-Prozent-Scores und daraus abgeleitete Reports invalidieren,
6. signierte historische Artefakte unverändert aufbewahren, aber klar als
   Legacy-Methodik kennzeichnen und nicht als aktuellen Nachweis ausgeben.

## Rote Goal-Tests vor der Implementierung

Zusätzlich zu den zwölf Solver-/Apportionierungsverträgen und sechs
Objective-Verträgen der drei vorangehenden Findings sind folgende Goal-
Verträge vor dem Produktfix rot zu materialisieren:

1. **No-goal-Differenz:** Ein einzelnes Maximierungsziel darf nicht dieselbe
   Objective und Allocation wie eine leere Goal-Liste erzeugen.
2. **Metrik-Monotonie:** Zwischen zwei feasible Allocations muss die mit der
   höheren gewählten Wachstums-/Utility-Metrik gewinnen, sofern primäre
   Constraints gleichwertig erfüllt sind.
3. **Totalverlust:** Null-Wealth-Pfade dürfen keine 100-Prozent-
   Zielerreichung für Maximierung erzeugen.
4. **Keine Fake-Probability:** Targetlose Goals besitzen weder Probability
   noch Tau noch binären Status.
5. **Mixed Goals:** Hinzufügen von Maximierung darf ein hartes Ziel nicht
   außerhalb der dokumentierten lexikografischen Toleranz verschlechtern.
6. **Gewichtswahrheit:** Maximierungsgewicht muss entweder in der definierten
   Multi-Objective wirken oder aus Probability-Scores ausgeschlossen sein.
7. **Horizont:** Goal-Horizont drei in einem zehnjährigen Run bewertet exakt
   Jahr drei und wird kanalgleich publiziert.
8. **Fallback-Parität:** Solver-, robustified- und House-Fallbackpfad nutzen
   denselben Zieltypvertrag; kein Moduswechsel darf die Semantik umkehren.
9. **Score:** Ein targetloses Goal kann den gewichteten Probability-Score
   weder erhöhen noch senken.
10. **Kanäle:** API, Classic UI, React, Strategie-PDF und Advisory-PDF zeigen
    denselben typisierten Wert und dieselbe Evidence-ID.
11. **Migration:** Legacy-100-Prozent-Zeilen werden replayed oder fail-closed
    gesperrt.
12. **Domain:** Unbekannte interne `target_kind` werfen einen Domainfehler;
    sie fallen nicht auf Shortfall null und Erfolg eins zurück.

## Empfohlene Implementierungsreihenfolge für Claude

### Phase 0: Semantik einfrieren und rote Repros materialisieren

1. `Maximierung` für neue reale Goals vorübergehend sperren.
2. Alle sieben Reproduktionsgruppen dieses Audits als Tests übernehmen.
3. Solver-Provenienz-, Integer-Apportionierungs-, Score-, Hauptziel-, UI- und
   PDF-Negativtests ergänzen.
4. Bestehende Endkontrollen zu Constraints/Fallback erhalten.

### Phase 1: Solvergrenzen reparieren

1. Raw-Feasibility vor jede Normalisierung/Projektion ziehen.
2. Eine optionale numerische Projektion als eigenen versionierten Solve-
   Schritt mit Distanz- und Provenienznachweis modellieren.
3. Constraint-bewusste deterministische 10.000-bps-Apportionierung
   implementieren.
4. Erst nach Raw-/Integer-Feasibility einen aktivierbaren Status vergeben.

### Phase 2: Objective-Ordnung reparieren

1. Phase A und Phase B als echte getrennte Optimierung materialisieren.
2. Dimensionslose Risikometrik, `L*` und versioniertes Delta festlegen.
3. Skalen-, Grenz- und Rangordnungstests auf Solver- und Evaluationspfad
   schließen.
4. Alte Objective-Evidence als methodisch inkompatibel markieren.

### Phase 3: Owner-ADR

1. Metrik und Risikopräferenz wählen.
2. Single- und Mixed-Goal-Ordnung festlegen.
3. Horizontquelle, Toleranz und Baseline bestimmen.
4. Typisierten Ergebnisvertrag und Methodenversion beschließen.

### Phase 4: Domain und Maximierungsobjective

1. Discriminated Goal-/Result-Typen einführen.
2. `maximize` aus Shortfall-/Probability-Fallbacks entfernen.
3. Gewählte Wachstums-/Utility-Objective implementieren.
4. Mixed-Goal-Lexikografie mit expliziter Toleranz umsetzen.
5. Unbekannte `target_kind` fail-closed behandeln.

### Phase 5: Evidence, Score und Kanäle

1. Metrik, Horizont, Baseline und Parameter in `StochasticRunEvidence`
   binden.
2. Probability-Score auf echte Target-Goals beschränken.
3. Hauptzielwahl typisieren.
4. API, Classic UI, React und PDFs gemeinsam umstellen.
5. Publication-Preflight bei fehlender/alter Evidence fail-closed machen.

### Phase 6: Migration und Shadow-Replay

1. Legacy-Maximierungsruns inventarisieren.
2. Replay-/Quarantäneentscheidung anwenden.
3. Repräsentative Mandate mit verschiedenen Horizonten, Risk-Caps und
   gemischten Goals shadow-replayen.
4. Allocation-, Utility-, Risiko- und Publikationsdifferenzen dokumentieren.
5. Erst danach reale Freigabe beantragen.

## Harte Invarianten der Abnahme

1. **Raw-Provenienz:** Ein akzeptierter Solver-Kandidat ist in der gelieferten
   Rohform zulässig; jede Transformation ist separat typisiert, versioniert
   und vollständig auditierbar.
2. **Integer-Existenz:** Ein vorhandener zulässiger 10.000-bps-Kandidat wird
   nicht durch constraints-blinde Restverteilung übersehen.
3. **Statuswahrheit:** `converged`, `converged_robustified`, Projection und
   House-Fallback bezeichnen unterschiedliche, belegte Erzeugungspfade.
4. **Lexikografie:** Phase B darf das Phase-A-Optimum nur innerhalb des
   expliziten versionierten Delta verlassen; vollständige Zielerfüllung zahlt
   keine kandidatenabhängige Sprungstrafe.
5. **Skaleninvarianz:** Gemeinsame Skalierung aller Geldwerte ändert weder
   Objective-Rangfolge noch Allocation.
6. **Semantik:** `Maximierung` optimiert exakt die versionierte, sichtbare
   Metrik.
7. **Nichtidentität:** Ein Maximierungsziel ist nicht identisch zu keiner
   Goal-Liste.
8. **Keine Scheinsicherheit:** Ein targetloses Goal erzeugt keine erfundene
   Probability, Tau oder Erreichbarkeitsampel.
9. **Horizon:** Schema, Objective, Evidence und Publisher verwenden denselben
   Horizont.
10. **Mixed Goals:** Harte/primäre Ziele bleiben innerhalb der dokumentierten
   Toleranz geschützt.
11. **Score:** Nur kommensurable echte Probability-Ziele werden aggregiert.
12. **Constraints:** Continuous- und Integer-bps-Allocation bleiben unter allen
   harten Bounds und Caps feasible.
13. **Fallback:** Der aktive Fallback wird im selben Context ausgewertet und
   ändert nicht still die Goal-Semantik.
14. **Evidence:** Entscheidung, Erklärung und alle Publisher binden dieselbe
   Run-/Goal-/Methodenidentität.
15. **Legacy:** Nicht replaybare alte 100-Prozent-Evidence ist sichtbar
    quarantänisiert und nicht current.
16. **Fail-closed:** Unbekannter Goal-Typ, unbekannter `target_kind`, fehlende
    Methodenversion oder fehlender Horizont blockiert vor Finalisierung.

## Unzureichende Scheinlösungen

Folgende Änderungen schließen den Audit ausdrücklich nicht:

1. Rohkandidaten zuerst clippen/normalisieren und ausschließlich das Ergebnis
   prüfen; damit bleibt die Herkunft weiterhin falsch ausgewiesen.
2. Die argmax-Rundung beibehalten und bei jeder Verletzung direkt auf House
   fallen, ohne eine zulässige Integer-Apportionierung zu suchen.
3. Nur den festen Volatilitätsfaktor verkleinern; für genügend kleine
   Shortfalls bleibt der kandidatenabhängige Sprung bestehen.
4. Primary und rohe Rappenvarianz weiterhin ohne gemeinsame dimensionslose
   Skala addieren.
5. Nur `probability=1` aus der UI ausblenden, während die Objective ein No-op
   bleibt.
6. Nur den Namen in „Wachstum“ ändern.
7. Erfolg als `W_T > W_0` definieren, aber weiterhin Varianz minimieren.
8. Probability auf null statt eins setzen; ein targetloses Goal besitzt keine
   binäre Erfolgsfrage.
9. Maximierung aus dem Advisory-Score entfernen, aber in API/PDF weiter als
   erreicht publizieren.
10. Den globalen Run-Horizont still als Goal-Horizont behalten.
11. Rohes erwartetes Wealth ohne dokumentierten Risiko-/Utility-Vertrag
   maximieren.
12. Risk-Cap oder House-Bounds lockern, um „mehr Wachstum“ zu erzwingen.
13. Nur Single-Goal reparieren und Mixed-Goal-Reihenfolge undefiniert lassen.
14. Legacy-Runs ohne Versions-/Snapshotprüfung unter der neuen Methodik
    anzeigen.
15. Die 488 grünen Bestandstests als Ersatz für die neuen Gegenbeispiele
    behandeln.

## Verifikationsnachweis

### Deterministische Reproduktionen

Gegen die echten Produktionsfunktionen des auditierten Heads wurden sieben
Gruppen ausgeführt:

1. ausschließlich roh infeasible Non-success-SLSQP-/DE-Ausgaben gegen
   `run_solver()` und den aktivierbaren Robustified-Status,
2. direkte und End-to-End-Basispunkt-Apportionierung an einer bindenden
   Upper-Bound und einem bindenden Risk-Cap,
3. Objective-Rangordnung bei vollständiger Erfüllung, minimaler Verfehlung
   und gemeinsamer Skalierung sämtlicher Geldwerte,
4. `run_solver()` ohne Goals gegen ein einzelnes Maximierungsziel,
5. gewählte gegen höhere feasible Wealth-Allocation unter identischem
   retained Context und Szenariowürfel,
6. Goal-Probability bei vollständigem Wealth-Verlust,
7. Schema-Horizont gegen tatsächlich gebauten Liability-Horizont.

Alle im Audit angegebenen Zahlen stammen aus diesen Ausführungen.

### Ausgeführtes fokussiertes Bestands-Gate

Aus `5eyes-backend` wurde ein isoliertes Gate über Solver, GA-Fallback,
Objective, Goal-Liabilities, Context, Fail-closed-Grenzen, Produktionsvertrag,
Chance-Constraints, Goal-Domain/-Horizon/-Invalidation, Asset-Allocation-
Integrität, Advisory-Report und Goal-PDF-Komponenten ausgeführt.

```text
488 passed in 263.67s (0:04:23)
```

Es gab keine Fehler und keine übersprungenen Tests. Das Gate bestätigt die
normalen Solver-, Constraint-, Post-Round- und Fallbackpfade. Es enthält aber
weder das Gegenbeispiel eines ausschließlich roh infeasiblen finiten
Solveroutputs noch den Cap-Fall, in dem die erste Rundung verletzt, obwohl
eine streng nähere zulässige 10.000-bps-Apportionierung existiert. Es fehlt
auch der Vergleich zwischen vollständiger Zielerfüllung und einem minimalen
Miss über mehrere Geldskalen. Ebenso fehlt ein Test, der Maximierung von einer
leeren Goal-Liste unterscheidet, einen
Totalverlust als Nichterfolg verlangt, den Maximierungshorizont bindet oder
targetlose Goals aus Probability-Score und Publishern entfernt. Das Gate
widerlegt daher keine der vier neuen Finding-IDs.

### Bewusst nicht behauptete Gates

- Kein Browser-DOM-Lauf wurde in dieser Runde ausgeführt.
- Kein echter PostgreSQL-/Concurrency-Lauf wurde in dieser Runde ausgeführt.
- Kein Full-Backend-Gate wurde erneut gestartet; das 488-Test-Gate deckt die
  geprüften Core- und Publication-Module fokussiert ab.
- Die vorbestehenden ACL-Warnungen beim Lesen alter `.pytest_tmp*`-
  Verzeichnisse wurden nicht als Produktfehler interpretiert.

## Dokumentationsmanifest

Diese Kontrollrunde ändert genau folgende fünf Dokumentationspfade:

1. `docs/audits/2026-09-23-solver-goal-maximization-and-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen und Runtime-Konfiguration bleiben
unverändert.

## Claude-Startcheckliste

Vor der ersten Codeänderung muss Claude:

1. diesen Audit sowie die Audits vom 21. und 22. September vollständig lesen,
2. `SOLVER-CANDIDATE-ACCEPTANCE-001`,
   `SOLVER-BPS-APPORTIONMENT-001`,
   `OPTIMIZER-TWO-PHASE-OBJECTIVE-001` und
   `GOAL-MAXIMIZATION-OBJECTIVE-001` als neue stabile IDs beibehalten,
3. `GOAL-PUBLICATION-001` und `GOAL-DOMAIN-001` nicht duplizieren,
4. die sieben Reproduktionsgruppen und 30 roten Testverträge zuerst
   materialisieren,
5. Raw-Provenienz vor Projektion und constraint-bewusste bps-Apportionierung
   implementieren,
6. die echte skaleninvariante Zwei-Phasen-Objective mit dokumentiertem Delta
   implementieren,
7. die mathematische Maximierungsmetrik und Mixed-Goal-Ordnung per Owner-ADR
   festlegen,
8. targetlose Optimierungsziele typisiert von Probability-Zielen trennen,
9. Horizont, Methodenversion und Parameter in Run-Evidence binden,
10. alle Publisher und den gewichteten Score gemeinsam umstellen,
11. Legacy-100-Prozent-Evidence replayen oder quarantänisieren,
12. nach jeder Phase das 488-Test-Gate und die neuen Reprotests ausführen,
13. danach die numerischen Gates der beiden Vortage ausführen,
14. und erst nach Shadow-Replay und Publication-Preflight eine Freigabe
    beantragen.

## Releaseentscheidung

**Release bleibt hart blockiert.** Kein Solverresultat darf aktivierbar sein,
wenn nur seine nachträgliche Projektion zulässig ist. Ein erfolgreicher
kontinuierlicher Solve darf nicht auf House fallen, solange eine zulässige
solvernahe 10.000-bps-Apportionierung existiert. Die Goal-Objective darf keine
minimale Verfehlung allein durch Wegfall der Varianzstrafe gegenüber voller
Erfüllung bevorzugen oder ihre Rangfolge mit der Geldskala ändern.
`Maximierung` darf nicht als
reale Wachstumsentscheidung oder Zielerreichungsnachweis verwendet werden,
solange `GOAL-MAXIMIZATION-OBJECTIVE-001` offen ist. Zusätzlich bleiben alle
P1 der Audits vom 21. und 22. September offen. Die bestätigten Endkontrollen
sind zu erhalten, schließen aber weder Provenienz-, Apportionierungs- noch
Objective-Semantikfehler.
