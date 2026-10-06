# Goal-Sensitivity-, Common-Baseline- und Publikationsintegritätsaudit

**Kontrollrunde 46 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Der Sensitivity-Service koppelt Baseline und Gegenfaktum innerhalb **eines**
Requests korrekt an denselben Seed und bei verschiedenen Horizonten an denselben
maximalen Szenariowürfel. Über die fünf sichtbaren Slider-Stufen hinweg ist die
Baseline jedoch nicht stabil:

1. `target_delta_pct` und `horizon_delta_years` fließen direkt in den Seed ein.
2. Damit erhält jede Slider-Stufe einen anderen Zufallswürfel, obwohl ihre
   Baseline-Wirtschaftsdaten unverändert sind.
3. Der temporäre Service-Test erzeugte für `-20, -10, 0, +10, +20 %` fünf
   verschiedene Baseline-Seeds und fünf verschiedene Baseline-Input-Hashes.
4. Eine direkte Reproduktion mit der produktiven Scenario Engine zeigte bereits
   im ersten Aktienreturn des ersten Pfads fünf verschiedene Werte.
5. Unterschiede zwischen Slider-Stufen enthalten deshalb nicht nur den
   Zielshift, sondern zusätzlich Monte-Carlo-Stichprobenrauschen. Eine scheinbar
   monotone oder nicht monotone Was-wenn-Reihe ist nicht als gemeinsame
   Sensitivitätskurve interpretierbar.

Neu bestätigt ist damit der methodische P2
`GOAL-SENSITIVITY-COMMON-BASELINE-001`.

Die Runde bestätigt außerdem, dass die drei einschlägigen P1 aus Runde 36 noch
offen sind: Renditeziele werden im Classic UI weiter als CHF angezeigt und
Solverstatus begrenzen die Richtungsbotschaft nicht; das Objective-Delta wird
weiter aus verlustbehaftet gerundeten `*_milli`-Integern berechnet; und der
Objective-Gewichtungsmodus ist weiterhin nicht Teil des Sensitivity-Hashes.

Reale Sensitivity-Aussagen, Beratung, PDF, Signatur und Handoff bleiben wegen
der erneut bestätigten P1-Publikationsgrenzen gesperrt. Der neue P2 verschärft
die Vergleichbarkeit zwischen den sichtbaren Stufen. Der korrekte Fix ist kein
bloßes Entfernen zweier Seed-Argumente,
sondern ein versionierter, unveränderlicher `SensitivityAnalysisContext`, der
eine Baseline und alle Counterfactuals an denselben Szenario- und
Objective-Vertrag bindet.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
64cb142
docs(audit): document manual target semantics gaps
```

Geprüft wurden insbesondere:

- `evaluate_goal_sensitivity()` einschließlich Goal-Mutation, Horizontbildung,
  Constraint-/Sub-Allocation-Reuse, Seed, Model-Input-Hash und zwei Solverläufe;
- produktive Scenario-Engine und Präfixvertrag;
- Request-/Response-Schema und Endpoint-AuditLog;
- Classic-UI-Slider und React-API-Typvertrag;
- bestehende Tests zu Sensitivity, Produktionscontext, Objective,
  Preferences-Fail-Closed und Allocation-Editor-Wiring;
- der vorherige Mixed-Goal-/Sensitivity-/Objective-Evidence-Audit.

Produktionscode, Schemas, Migrationen, Tests und UI wurden nicht verändert. Ein
temporärer roter Regressionstest wurde nach der Beweissicherung vollständig
entfernt. Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Abgrenzung zu Runde 36

Runde 36 bestätigte bereits:

- typfalsche Zielwertpublikation bei Renditezielen;
- fehlendes Status-/Feasibility-Gating;
- verlustbehaftete Objective-Serialisierung und daraus berechnete Deltas;
- ungebundene Objective-Gewichtungsmethodik;
- unvollständige, nur requestbezogene Audit-Evidence.

Diese Runde dupliziert jene IDs nicht. Der neue Befund betrifft eine andere
Grenze: Selbst wenn Zieltyp, Status, Objective-Präzision und Evidence repariert
wären, würden verschiedene Slider-Stufen weiterhin auf verschiedenen
Monte-Carlo-Samples beruhen. Das ist ein eigenständiger Fehler im
experimentellen Design des Counterfactual-Vergleichs.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `GOAL-SENSITIVITY-COMMON-BASELINE-001` | P2 | neu bestätigt | Der Seed enthält Target- und Horizon-Delta. Jede Slider-Stufe erzeugt dadurch eine andere Baseline und einen anderen Szenariowürfel. Stufenübergreifende Unterschiede besitzen zusätzliche Stichprobenvarianz und sind keine Common-Random-Numbers-Kurve. |
| `GOAL-SENSITIVITY-PUBLICATION-001` | P1 | offen, erneut bestätigt | Return-bps landen weiter im Pflichtfeld `target_amount_rappen_*`; Classic rendert jedes Ziel als CHF und leitet „besser/schwerer“ ohne Status-/Feasibility-Gate ab. |
| `OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001` | P1 | offen, erneut bestätigt | Baseline und Neu werden erst mit `round(value * 1000)` quantisiert; das Prozentdelta wird anschließend aus den gerundeten Integern statt aus verlustfreien Rohwerten berechnet. |
| `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001` | P1 | offen, erneut bestätigt | `equal` versus `hardness` bleibt ein dynamischer, nicht im Sensitivity-Hash gebundener Objective-Input. |
| `GOAL-PUBLICATION-001` / `GOAL-SNAPSHOT-001` / `REP-001` | P1 | offen, erneut bestätigt | Der Endpoint persistiert nur Goal-ID und Target-Delta, nicht Horizon-Delta, Baseline-/Modified-Hash, Seed, Status, Feasibility, Resultat oder Anzeige. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
gleiche Live-Baseline
  CMA / Goals / Wealth / Cashflows / Constraints unverändert
                         |
                         v
Slider -20  -> seed(..., -20, 0) -> Szenariowürfel A -> Baseline A
Slider -10  -> seed(..., -10, 0) -> Szenariowürfel B -> Baseline B
Slider   0  -> seed(...,   0, 0) -> Szenariowürfel C -> Baseline C
Slider +10  -> seed(..., +10, 0) -> Szenariowürfel D -> Baseline D
Slider +20  -> seed(..., +20, 0) -> Szenariowürfel E -> Baseline E

innerhalb jeder Zeile:
  Baseline und Modified teilen sich korrekt denselben Würfel

zwischen den Zeilen:
  Baseline, Pfade, Hash und mögliche Solverentscheidung wechseln
```

Der lokale Common-Random-Numbers-Vertrag ist somit richtig, der panelweite
Common-Baseline-Vertrag fehlt.

## Positivkontrollen, die erhalten bleiben müssen

1. Innerhalb eines Sensitivity-Paars verwenden Baseline und Modified exakt
   denselben Seed.
2. Bei unterschiedlichem Run-Horizont werden beide Läufe aus einem gemeinsamen
   maximalen Szenariowürfel versorgt; der kürzere Lauf verwendet ein exaktes
   Pfadpräfix.
3. Ein verlängertes Counterfactual re-projiziert Cashflows, Inflation, Steuer,
   FX und externes Vermögen statt die Serie mit Nullen zu füllen.
4. Das Ziel wird über einen `SimpleNamespace` geklont; die persistierte ORM-
   Zeile wird durch die Goal-Mutation nicht verändert.
5. Unbekannte, inaktive oder mandatfremde Ziele werden nicht analysiert.
6. Eine unvollständige Strategie-Risikoeinschätzung stoppt vor dem Solver.
7. Moderne aktive Allocations müssen ihren gehashten Sub-Allocation-/Constraint-
   Context strukturell und semantisch verifizieren; Tampering stoppt vor dem
   Solver.
8. Ohne aktive Allocation wird der kanonische Live-Generate-Constraintcontext
   einschließlich globaler Caps, Reservefloor, Illiquiditätsplan und exakter
   Risky Fractions nachgebaut.
9. Mit aktiver Allocation bleiben deren verifizierte Bounds, Sub-Allokationen
   und Risky Fractions die unveränderliche Constraintbasis; Wealth, Goals,
   Cashflows, Steuer und externe Reserve werden live neu ermittelt.
10. Baseline- und Modified-Input-Hash werden getrennt exponiert.
11. Ziel- und Horizon-Delta besitzen serverseitige Grenzen.
12. Der UI-`finally`-Pfad reaktiviert die Sensitivity-Buttons nach Erfolg und
    Fehler.

Diese Positivkontrollen rechtfertigen keine Freigabe, müssen aber beim Fix
erhalten bleiben.

## Codeanker des geprüften Stands

### Seed und Solverpaar

- `5eyes-backend/services/portfolio_engine.py:5084-5091` beschreibt den Seed
  als für Baseline und Modified gepinnt, nimmt aber zusätzlich
  `target_delta_pct` und `horizon_delta_years` in seine Ableitung auf.
- `5eyes-backend/services/portfolio_engine.py:5293-5303` reicht denselben Seed
  korrekt an jeden Lauf eines Paars weiter.
- `5eyes-backend/services/portfolio_engine.py:5306-5315` startet Baseline und
  Modified nacheinander unter diesem requestlokalen Seed.
- `5eyes-backend/services/optimizer/solver.py:664-675` bildet aus allen Parts
  einen deterministischen 63-Bit-Seed; verschiedene Delta-Parts ändern damit
  erwartungsgemäß den Seed.
- `5eyes-backend/services/optimizer/scenario_engine.py:174-208` initialisiert
  `np.random.default_rng(seed)` und erzeugt daraus den Pfadwürfel.

### Hash und Response

- `5eyes-backend/services/portfolio_engine.py:5221-5255` bindet den Seed in
  jeden Sensitivity-Model-Input-Hash.
- `5eyes-backend/services/portfolio_engine.py:5265-5274` berechnet Baseline-
  und Modified-Hash; wegen des deltaabhängigen Seeds wechselt bereits der
  Baseline-Hash zwischen Slider-Stufen.
- `5eyes-backend/services/portfolio_engine.py:5349-5364` nennt den Lauf
  `live_reoptimization_common_scenarios_current_inputs_v3` und exponiert
  Pairing-Basis, Baseline-Hash und Seed. Die Felder sind requestlokal korrekt,
  machen aber keinen panelweiten gemeinsamen Baseline-Context kenntlich.

### Weiter offene Publikationsgrenzen

- `5eyes-backend/services/portfolio_engine.py:5317-5331` quantisiert beide
  Objectives vor der Delta-Berechnung auf historische `*_milli`-Integer.
- `5eyes-backend/services/portfolio_engine.py:5333-5338` wählt Amount, Wealth
  oder Return-bps über Truthiness in ein generisches Rappenfeld.
- `5eyes-backend/schemas/allocation.py:1069-1102` besitzt noch keinen
  diskriminierten Target-/Unit-/Availability-Vertrag.
- `5eyes-backend/routers/allocation.py:579-587` persistiert im AuditLog nur
  Goal-ID und Target-Delta. Schon `horizon_delta_years` fehlt.
- `5eyes-electron/frontend/5eyes_v2.html:27308-27310` stellt fünf getrennte
  Slider-Requests bereit.
- `5eyes-electron/frontend/5eyes_v2.html:27331-27340` rendert jedes Ergebnis
  als CHF und erzeugt die Richtungsbotschaft nur aus dem Objective-Vorzeichen.
- `5eyes-electron/frontend/reporting/src/api/types.ts:1039-1052` führt weiter
  nur den unvollständigen alten Sensitivity-Typvertrag; eine React-
  Ergebnisoberfläche ist nicht nachgewiesen.

## Deterministische Reproduktion A: fünf Seeds für eine Baseline

Die produktive Seedfunktion wurde mit identischen CMA-, Goal-, Score-,
Horizon- und Pfadparametern ausgeführt. Nur die Slider-Stufe variierte:

```text
-20 -> 7009695896624030015
-10 -> 8555777310907400648
  0 -> 4443223957775101008
+10 -> 9215429745110260497
+20 -> 3604671062738557918
```

Auch ein reiner Horizon-Shift änderte den Seed:

```text
-3 Jahre ->  967812497051239015
+3 Jahre -> 4427242913321220473
```

Das ist kein Hashkollisions- oder Cacheproblem. Die Deltas sind explizite
Seedbestandteile.

## Deterministische Reproduktion B: fünf verschiedene Szenariowürfel

Mit denselben einfachen CMA-Momenten und derselben Identitätskorrelation wurde
je Seed der produktive `build_scenario_paths()`-Pfad ausgeführt. Der erste
Aktienfaktor des ersten Pfads und ersten Jahres war:

```text
-20 -> 1.23490334
-10 -> 1.12044555
  0 -> 1.09274180
+10 -> 1.18656409
+20 -> 0.92624701
```

Damit ist belegt, dass nicht nur die Seedzahl oder der Hash wechselt, sondern
der tatsächlich vom Solver konsumierte Zufallsinput.

## Temporärer roter Service-Test

Der Probe-Test rief `evaluate_goal_sensitivity()` im selben Mandat und in
derselben Session nacheinander für alle fünf Target-Deltas auf. Der teure
Solver wurde nur durch den vorhandenen Call-Capture ersetzt; Seedbildung,
Inputladen, Constraintcontext, Hashbildung und beide Serviceaufrufe blieben
produktiv.

Erwartete Invariante:

```python
assert len({call["seed"] for call in baseline_calls}) == 1
assert len({result["baseline_model_input_hash"] for result in results}) == 1
```

Tatsächliches Resultat:

```text
FAILED
assert (5, 5) == (1, 1)
five distinct baseline seeds and five distinct baseline model-input hashes
```

Der Test wurde danach entfernt. Seine Aufgabe ist, Claude eine präzise rote
Regression für die Implementierung zu geben.

## Warum der Fehler fachlich materiell ist

Ein einzelner gepaarter Vergleich schätzt korrekt:

```text
Effect(delta) = Objective(modified, cube X) - Objective(baseline, cube X)
```

Der heutige Slider erzeugt jedoch:

```text
Effect(-20) auf cube A
Effect(-10) auf cube B
Effect(  0) auf cube C
Effect(+10) auf cube D
Effect(+20) auf cube E
```

Die fünf Werte besitzen dadurch verschiedene Monte-Carlo-Fehler. Insbesondere
kann der Benutzer nicht zuverlässig unterscheiden, ob ein Sprung zwischen
zwei Stufen durch das geänderte Ziel oder durch eine andere Stichprobe
entsteht. Antithetic Variates reduzieren Varianz innerhalb eines Würfels,
ersetzen aber keine gemeinsamen Zufallszahlen zwischen den Stufen.

Das Problem wird durch die aktuelle UI verstärkt: Sie präsentiert fünf
Stufen als zusammengehörige Was-wenn-Auswahl, führt aber fünf unabhängige
Requests aus und exponiert weder Analysis-ID noch gemeinsamen Cube-Hash.

## Verbindlicher Zielvertrag für Claude

### 1. Einen Analysis-Context statt fünf lose Requests erzeugen

Empfohlen ist ein serverseitiger Batchvertrag:

```text
GoalSensitivityAnalysis
  analysis_id
  created_at / valuation_as_of
  mandate_id / goal_id / actor_id
  baseline_context_hash
  objective_contract_hash
  constraint_context_hash
  scenario_artifact
    seed
    n_paths
    max_horizon_years
    generator_version
    estimator_version
    content_hash
  baseline_result
  counterfactuals[]
    target_delta_pct
    horizon_delta_years
    modified_goal_snapshot_hash
    modified_input_hash
    result
```

Ein Request berechnet die freigegebenen Target-Stufen und gegebenenfalls die
Horizon-Stufen gemeinsam. Damit kann der Server Baseline, Scenario Artifact,
Objective Contract und Resultate atomar binden.

### 2. Seed ausschließlich aus stabiler Baseline ableiten

Der Seed darf keinen Counterfactual-Wert enthalten. Er wird aus einem
kanonischen Baseline-Analysis-Key abgeleitet, zum Beispiel:

```text
seed = H(
  baseline economic input hash without seed,
  goal_id,
  objective contract version,
  scenario generator version,
  estimator version,
  n_paths
)
```

Ändern sich echte Live-Baseline-Inputs, darf und soll eine neue Analysis einen
neuen Seed erhalten. Innerhalb derselben Analysis bleiben Seed und Baseline
für alle Deltas identisch.

### 3. Horizon-Stufen als Präfixe desselben Max-Cubes ausführen

Für alle angeforderten Horizon-Deltas wird einmal der größte benötigte
Szenariohorizont bestimmt. Jeder kürzere Lauf verwendet exakt das passende
Präfix desselben Cubes. Die bestehende `scenario_horizon_years`-Mechanik kann
hierfür erhalten werden; nur ihre Lebensdauer wird vom Requestpaar auf die
gesamte Analysis erweitert.

### 4. Baseline genau einmal lösen oder content-addressed wiederverwenden

Eine unveränderte Baseline wird innerhalb der Analysis einmal berechnet. Wenn
der Solver aus technischen Gründen erneut laufen muss, müssen Seed, Context,
Input-Hash, Ergebnis und Status bit-/vertragstreu übereinstimmen. Abweichungen
sind ein Fehlerzustand, kein neues Baseline-Ergebnis.

### 5. Typ, Status und Objective gleichzeitig reparieren

Der Common-Baseline-Fix allein macht die Publikation noch nicht sicher. Die
Response braucht zusätzlich:

- diskriminierten Targettyp und Einheit;
- verlustfreie dimensionless Objective-Werte und daraus berechnete Deltas;
- explizite Availability-/Feasibility-Zustände;
- keine Richtungsbotschaft bei divergiertem, infeasible oder unsynchronisiertem
  Fallback-Ergebnis;
- einen eingefrorenen und gehashten Objective Contract einschließlich
  Goal-Weighting;
- immutable Evidence über Request, alle Varianten und die tatsächlich
  publizierte Darstellung.

## Nicht ausreichende Teilfixes

1. Nur `target_delta_pct` aus dem Seed entfernen, aber
   `horizon_delta_years` belassen.
2. Nur denselben numerischen Seed zurückgeben, ohne einen gemeinsamen
   Scenario-Artifact-/Generatorvertrag zu binden.
3. UI-seitig die Baselinezahl cachen, während der Server Modified-Läufe auf
   anderen Cubes ausführt.
4. Verschiedene Deltas nachträglich glätten oder sortieren.
5. Das Objective-Delta weiter aus `*_milli` berechnen.
6. Nur Renditeziele im UI speziell formatieren, ohne serverseitigen
   Discriminator und Status-Gate.
7. Nur das AuditLog um Horizon-Delta erweitern, ohne Resultat- und Context-
   Evidence.

## Pflicht-Tests

### Common Baseline und Scenario Pairing

1. `-20, -10, 0, +10, +20 %` teilen exakt Seed, Baseline-Input-Hash,
   Baseline-Weights, Baseline-Objective und Baseline-Status.
2. Horizon-Deltas `-10..+10` teilen denselben Seed und den exakten Pfadpräfix
   desselben maximalen Cubes.
3. Reihenfolge und Parallelisierung der Varianten ändern kein Resultat.
4. Wiederholter identischer Batch ist byte-/hashidentisch.
5. Eine echte Baseline-Inputänderung erzeugt eine neue Analysis-ID und einen
   neuen Baseline-Hash; alte Results werden nicht weiterverwendet.
6. Ein Delta darf nur Modified-Goal-Snapshot und daraus abgeleitete Inputs
   ändern, niemals den Baseline-Snapshot.

### Ergebnis- und Publikationsvertrag

7. Amount-, Wealth-, Return- und Maximierungsziel besitzen disjunkte Typen und
   korrekte Einheiten.
8. 500 auf 600 bps erscheint als `6.00 % p.a.`, niemals als `CHF 6`.
9. `diverged`, `diverged_infeasible`, nicht feasible und unsynchronisierter
   Fallback liefern keine besser-/schlechter-Richtung.
10. Objective `0.0001 -> 0.0002` ergibt aus der verlustfreien Darstellung
    100 Prozent, nicht `None`.
11. Goal-Weighting- oder Objective-Contract-Änderung ändert Analysis- und
    Input-Hashes.
12. Classic und React rendern denselben vollständigen Analysis-Envelope.

### Evidence und Nebenwirkungsfreiheit

13. Goal, TargetAllocation und Recommendation bleiben durch die Analyse
    unverändert.
14. Persistiert wird ein append-only Sensitivity-Evidence-Record, keine neue
    current Allocation.
15. Evidence bindet Actor, Mandat, Goal-Snapshot, Baseline, alle Mutationen,
    Seed/Cube, Objective Contract, Status, Feasibility, Gewichte und
    Publication Hash.
16. Abbruch einer Variante hinterlässt keinen partiellen als vollständig
    markierten Analysis-Record.

## Empfohlene Implementierungsreihenfolge

1. Den roten stufenübergreifenden Seed-/Baseline-Test materialisieren.
2. Einen versionierten `SensitivityAnalysisContext` und Batchrequest
   definieren.
3. Seed aus dem stabilen Baseline-Key ableiten; Deltas vollständig aus der
   Seedableitung entfernen.
4. Einen panelweiten Max-Horizon-Cube erzeugen und Präfixgleichheit testen.
5. Baseline einmal lösen und alle Varianten dagegen auswerten.
6. Objective Contract und verlustfreie Werte in Context, Hash und Evidence
   aufnehmen.
7. Discriminated Target-/Result-Union und Status-/Feasibility-Gate umsetzen.
8. Classic und React auf denselben Batchvertrag umstellen.
9. Immutable Audit-Evidence plus Publication Hash persistieren.
10. Backend-, Browser-, PDF-, Signatur-, Replay- und PostgreSQL-Gates ausführen.

## Testnachweis

Temporärer roter Probe-Test:

```text
1 failed, 43 deselected
Failure: (5 baseline seeds, 5 baseline hashes) instead of (1, 1)
```

Anschließend lief der unveränderte Bestandsgate:

```powershell
python -m pytest -q --basetemp C:\tmp\ares_round46_gate `
  tests/test_optimizer_phase6.py `
  tests/test_optimizer_production_contract.py `
  tests/test_optimizer_objective_dimensionless.py `
  tests/test_allocation_editor_wiring_contract.py `
  tests/test_allocation_preferences_fail_closed_contracts.py
```

Ergebnis:

```text
227 passed in 92.76s
```

Der grüne Gate bestätigt die vorhandenen In-Request-Pairing-, Context- und
Fail-Closed-Verträge. Er besitzt keine stufenübergreifende Baseline-Invariante
und widerlegt den neuen P2 daher nicht.

Bewusst nicht behauptet werden:

- kein vollständiger Backend-/Frontend-Gesamtgate;
- kein Browser-DOM-/Electron-Lauf;
- kein echter PostgreSQL-/Concurrency-Test;
- kein realer mehrstufiger End-to-End-Solververgleich mit Publikation;
- keine Produktcode-, Schema-, Test- oder Migrationsänderung;
- keine Schließung eines bestehenden Findings.

## Definition of Done

`GOAL-SENSITIVITY-COMMON-BASELINE-001` darf erst geschlossen werden, wenn:

- alle Varianten einer Analysis dieselbe unveränderliche Baseline besitzen;
- Target- und Horizon-Delta keinen Seed, Baseline-Hash oder Baseline-Result
  verändern;
- unterschiedliche Horizonte nachweislich Präfixe desselben maximalen Cubes
  verwenden;
- der gemeinsame Scenario-/Objective-/Constraintcontext versioniert und
  gehasht ist;
- UI, API, Evidence, PDF, Signatur und Handoff dieselbe Analysis-ID und
  Resultatbasis verwenden;
- und die gleichzeitig offenen Typ-, Status-, Objective-Präzisions-,
  Goal-Weighting- und Publication-Evidence-Verträge geschlossen sind.

## Releaseentscheidung

Der Release-Hold bleibt wegen der erneut bestätigten P1 bestehen. Sensitivity
darf nicht als belastbare Beratungs- oder Kundenfunktion freigegeben werden,
solange die offenen Publikationsverträge typfalsche beziehungsweise
statusblinde Aussagen zulassen. Vor einer vergleichenden Slider-/Kurvenaussage
muss zusätzlich der neue Common-Baseline-P2 geschlossen sein.

Für Claude gilt: zuerst die stufenübergreifende Baseline und den gemeinsamen
Scenario-Artifact-Vertrag herstellen; anschließend Objective-, Target-,
Status- und Evidence-Vertrag gemeinsam schließen. Ein isolierter UI- oder
Seed-Patch ist kein ausreichender Abschluss.
