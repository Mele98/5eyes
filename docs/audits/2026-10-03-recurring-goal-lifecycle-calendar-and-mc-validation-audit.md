---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-recurring-goal-editor-occurrence-lifecycle-calendar-timebase-and-monte-carlo-validation-followup-audit"
status_as_of: "2026-10-03"
audit_started_on: "2026-09-29"
audit_completed_on: "2026-10-03"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "61965c6e7eb415bc817826352386562cb70205a4"
prior_goal_funding_audit_path: "docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md"
prior_estimator_audit_path: "docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md"
prior_core_audit_path: "docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
prior_goal_publication_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
prior_withdrawal_timing_audit_path: "docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
audit_mode: "read_only_static_goal_editor_scheduler_lifecycle_calendar_timebase_optimizer_selection_validation_and_publication_review_plus_deterministic_python_react_and_focused_pytest_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "React and Classic recurring/pension goal CRUD, API domain validation, recurring occurrence materialization in optimizer and reporting MC, past and overdue goal lifecycle, valuation-date and calendar-horizon parity, same-cube optimizer selection and probability certification, evidence persistence and publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 5
confirmed_prior_p1_extension_groups: 5
new_hardening_p2_count: 0
deterministic_reproduction_groups: 7
focused_backend_tests_passed: 235
focused_react_tests_passed: 44
focused_existing_tests_passed_total: 279
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "keep real-advice recurring goal CRUD, goal schedules, overdue-goal evidence and green probability certification blocked; first materialize the documented negative tests, then implement a discriminated recurring-goal editor contract, one canonical occurrence scheduler and valuation timebase, an explicit goal lifecycle, and an independent post-selection Monte Carlo validation contract with uncertainty-aware decision evidence"
---

# Recurring-Goal-, Lifecycle-, Kalender- und MC-Validierungs-Audit

## Geltung, Quellenrangfolge und Abgrenzung

Dieser additive Folgeaudit dokumentiert die achtunddreißigste Read-only-
Kontrollrunde des Asset-Allocation-/Stochastic-Core. Geprüft wurde der
unveränderte Repository-Head
`61965c6e7eb415bc817826352386562cb70205a4`. Produktcode, Migrationen und
Tests wurden nicht verändert. Nach der Prüfung werden ausschließlich die fünf
Pfade des Dokumentationsmanifests angepasst.

Aktueller Code und ausgeführte Reproduktionen haben Vorrang. Planungstexte und
ältere Audits sind Soll- und Deduplizierungsanker. Grüne Bestandstests belegen
nur die von ihnen tatsächlich assertierten Verträge. Ein gemockter API-Erfolg
ist insbesondere kein Nachweis, dass der echte Backendvertrag denselben
Payload akzeptiert.

Die Runde schließt fünf bislang nicht vollständig beantwortete Kernfragen:

1. Kann der aktive React-Editor wiederkehrende und Pensionsziele verlustfrei
   anlegen und bearbeiten?
2. Materialisieren Optimizer und allgemeine Monte-Carlo-Zielanalyse exakt die
   im Datumsfenster fälligen Occurrences?
3. Was geschieht mit abgelaufenen beziehungsweise teilweise vergangenen
   aktiven Zielen?
4. Verwenden API, Optimizer und Reporting denselben Bewertungsstichtag und
   dieselbe Kalenderjahreskonvention?
5. Wird eine auf einem Monte-Carlo-Würfel ausgewählte Allokation auf
   unabhängiger Evidenz validiert, bevor ihre Zielwahrscheinlichkeit als
   `erreichbar` publiziert wird?

## Deduplizierung zu bestehenden Findings

Keine bestehende Finding-ID wird geschlossen oder umbenannt.

- `WITHDRAWAL-TIMING-001` bleibt der P2-Vertrag für gespeicherte Tag-/
  Monatspräzision innerhalb eines Jahresmodells. Das neue
  `GOAL-RECURRENCE-SCHEDULE-001` betrifft dagegen eine falsche Anzahl und
  Summe tatsächlich materialisierter Occurrences. Der Fehler kann selbst bei
  bewusstem Jahresbucket-Vertrag eine zusätzliche volle Zahlung erfinden und
  die Zielwahrscheinlichkeit von eins auf null drehen.
- `GOAL-SNAPSHOT-001` und `MC-CONTEXT-001` bleiben die allgemeinen
  Snapshot-/Run-Context-Verträge. `GOAL-CALENDAR-HORIZON-PARITY-001` grenzt die neue
  Ursache ab: ein nicht gebundener Bewertungsstichtag plus gleichzeitig
  eingesetzte 365-Tage- und Kalenderjahresarithmetik erzeugen innerhalb
  desselben aktuellen Laufs unterschiedliche Zieljahre.
- `GOAL-RETURN-HORIZON-001` bleibt auf die Prefix-TWR eines Renditeziels
  begrenzt. Die neue Timebase-ID betrifft alle datierten Zieltypen und bereits
  die Auflösung des Zieljahres.
- `OPTIMIZER-IS-ESS-001` bleibt für Importance-Sampling-Gewichtszerfall,
  effektive Stichprobengröße und den allgemeinen Difference-/Confidence-
  Budget-Vertrag maßgeblich. `OPTIMIZER-POST-SELECTION-CERTIFICATION-001` ist davon unabhängig:
  Es betrifft die erneute Zertifizierung der **aus demselben Sample
  ausgewählten** Allokation auf genau diesem Trainingssample. Der Effekt tritt
  bei Standard-MC mit uniformen Gewichten und `ESS=N` auf.
- `OPTIMIZER-IS-EVIDENCE-001` bleibt für die gemeinsame validierte
  Estimatorbasis aller Consumer maßgeblich; `GOAL-PUBLICATION-001` und
  `REP-001` bleiben für kanalgleiche Veröffentlichung offen.
- `GOAL-FUNDING-PRIORITY-001` und
  `GOAL-ACHIEVABILITY-ATTRIBUTION-001` bleiben für Prioritätsausführung und
  individuelle Attribution maßgeblich. Ein korrekter Scheduler und ein
  Holdout ersetzen das dort geforderte Funding-Ledger nicht.

Fünf neue IDs grenzen neue Ursachen präzise ab:

- `GOAL-RECURRING-EDITOR-CONTRACT-001`
- `GOAL-RECURRENCE-SCHEDULE-001`
- `GOAL-PAST-DATE-LIFECYCLE-001`
- `GOAL-CALENDAR-HORIZON-PARITY-001`
- `OPTIMIZER-POST-SELECTION-CERTIFICATION-001`

## Kurzurteil

Die Runde bestätigt **fünf neue release-blockierende P1**.

**`GOAL-RECURRING-EDITOR-CONTRACT-001`:** Der produktiv verdrahtete React-
`GoalWizard` zeigt für `Wiederkehrende_Ausgabe` und `Pensionsausgabe` nur die
Frequenz. Betrag, `start_date`, Enddatum und `is_ongoing` fehlen. Die interne
Abbildung setzt `target_amount_rappen` ausschließlich für
`Einmalige_Ausgabe`; der Payload-Builder nullt den Betrag für alle anderen
Zieltypen und setzt fehlendes `is_ongoing` auf `false`. Der echte Backend-
Complete-State-Guard antwortet deshalb bei Neuanlage und No-op-Edit mit HTTP
422. Das verhindert im aktuellen Stand eine stille Persistenz beschädigter
Daten, macht aber beide Kernzieltypen im React-Editor vollständig nicht
CRUD-fähig. Der grüne Wizard-Test verwendet selbst einen fachlich ungültigen
Pensionsdatensatz und mockt `updateGoal()` immer erfolgreich.

**`GOAL-RECURRENCE-SCHEDULE-001`:** Der Optimizer zählt für einen endlichen
Stream inklusive Kalenderjahreslabels und multipliziert den Periodenbetrag
zuerst pauschal auf ein volles Jahr. Ein jährliches Ziel vom 31.12.2026 bis
01.01.2027 enthält fachlich genau eine verankerte Fälligkeit. Der Goal-
Scheduler erzeugt zwei volle Zahlungen. Der kanonische Cashflow-Scheduler
enumeriert korrekt eine. Bei CHF 150 Startvermögen, CHF 100 Betrag und null
Rendite erzeugt der aktuelle Goal-Pfad `[100,100,0]`, endet negativ und liefert
`P=0`; der kanonische Occurrence-Pfad `[100,0,0]` bleibt positiv und liefert
`P=1`. Die allgemeine Reporting-MC dupliziert dieselbe
`annual_amount * inclusive_year_count`-Logik.

**`GOAL-PAST-DATE-LIFECYCLE-001`:** API und Domainvalidator akzeptieren vergangene
aktive Ziele ohne Lifecycle-Entscheid. Der Optimizer klemmt jedes Datum auf
mindestens Jahr eins. Ein Einmalziel von 2020 wird dadurch als neue Auszahlung
im nächsten Simulationsjahr angesetzt; ein Vermögensziel von 2020 wird dort
neu bewertet. Ein vollständig abgelaufener monatlicher Stream 2020–2022 wird
als drei neue volle Jahreszahlungen materialisiert. Ein Stream 2020–2028 wird
ab heute nicht mit seinen drei Restjahren, sondern mit neun neuen Jahren bis
weit nach 2028 belastet. Das React-Reporting kann denselben Datensatz
ausdrücklich als `past` markieren. Es existiert keine gemeinsame Semantik für
erfüllt, überfällig, offen, storniert oder historisch.

**`GOAL-CALENDAR-HORIZON-PARITY-001`:** `calendar_years_until()` besitzt zwar
einen sauberen optionalen `as_of`-Parameter. Andere aktive Layer verwenden
jedoch `ceil(delta_days/365)`, reine Kalenderjahrdifferenz oder `365.25` Tage.
Am 03.10.2026 ergibt ein Ziel am exakten 12-Jahres-Jahrestag 03.10.2038 wegen
drei Schaltjahren API/Reporting-Horizont 13, aber Optimizer-Zieljahr 12. Bei
realem Ziel und zwei Prozent Inflation unterscheiden sich dadurch bereits die
Targetwerte. Zusätzlich lassen produktive Caller den Stichtag implizit auf
`date.today()` fallen: Ein Ziel am 04.10.2027 wechselt bei identischem
Rohinput zwischen Bewertungsstichtag 03.10. und 04.10.2026 von Jahr zwei auf
Jahr eins. Die kanalinterne Horizon-Divergenz ist die neue ID; der nicht
gebundene Stichtag erweitert zusätzlich `GOAL-SNAPSHOT-001` und
`MC-CONTEXT-001`.

**`OPTIMIZER-POST-SELECTION-CERTIFICATION-001`:** Der Solver optimiert
sämtliche Kandidaten auf `OptimizerContext.return_paths` und berechnet Objective, finale
Goal-Probability, Status und Chance-Penalty anschließend erneut auf genau
demselben Würfel. Es gibt keinen unabhängigen Validation-Cube und keinen
selection-aware Entscheidungsrand. Ein echter Standard-MC-Solverlauf war auf
2.000 Selektionspfaden mit exakt `P=0.800000` grün; dieselben final gerundeten
Gewichte ergaben auf einem unabhängigen 200.000-Pfad-Cube `P=0.798125` und
`knapp`. Im ergänzenden 100-Paar-Repro mit fünf
marginal identischen Kandidaten, wahrer Erfolgswahrscheinlichkeit
`P=tau=0.80`, 2.000 antithetischen Standard-MC-Pfaden und Auswahl des besten
Kandidaten waren 97 Trainingsresultate grün, aber nur 53 unabhängige
Validierungen; 47 Fälle wechselten von `erreichbar` zu `knapp`. Das ist
Post-Selection-/Winner's-Curse-Bias und bleibt bei `ESS=N` bestehen.

Es wurde kein neuer P0 bestätigt. Die Releasefreigabe bleibt wegen dieser
fünf P1 und der bereits offenen Blocker ausgeschlossen.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `GOAL-RECURRING-EDITOR-CONTRACT-001` | P1 | neu bestätigt | React kann wiederkehrende/Pensionsziele weder anlegen noch no-op bearbeiten: Betrag und Timing fehlen, Payload nullt den Betrag, der echte Backendvertrag antwortet 422. |
| `GOAL-RECURRENCE-SCHEDULE-001` | P1 | neu bestätigt | Optimizer und Reporting-MC multiplizieren den Periodenbetrag mit vollen, berührten Kalenderjahreslabels statt die tatsächlichen Occurrences zu materialisieren. |
| `GOAL-PAST-DATE-LIFECYCLE-001` | P1 | neu bestätigt | Vergangene aktive Ziele werden ohne Lifecycle-Entscheid als neue zukünftige Pflicht beziehungsweise neue Jahr-eins-Bewertung reaktiviert. |
| `GOAL-CALENDAR-HORIZON-PARITY-001` | P1 | neu bestätigt | 365-Tage-, Anniversary-, Jahreslabel- und 365,25-Tage-Arithmetik ordnen denselben Termin unterschiedlichen Zielpfad-Indizes zu; der ungebundene Stichtag verschärft den Replaybruch. |
| `OPTIMIZER-POST-SELECTION-CERTIFICATION-001` | P1 | neu bestätigt | Kandidatenauswahl und grüne Probability-Zertifizierung verwenden denselben MC-Würfel; unabhängige Post-Selection-Validierung fehlt. |
| `OPTIMIZER-IS-ESS-001` | P1 | offen, neue Evidence | Auch Standard-MC am exakten Tau benötigt den bereits geforderten Confidence-/Decision-Budget-Vertrag; keine neue ID für bloßes Sampling Error. |
| `GOAL-SNAPSHOT-001` / `MC-CONTEXT-001` | P1 | offen, neue Evidence | Rohdatenhash ohne gebundenen Bewertungsstichtag und aufgelösten Schedule reproduziert die wirtschaftliche Eingabe nicht. |
| `GOAL-PUBLICATION-001` / `REP-001` | P1 | offen, neue Evidence | Train-Punktschätzer und widersprüchliche Lifecycle-/Schedule-Semantik gelangen ohne Reliability- beziehungsweise Lifecycle-Verdict in Folgekanäle. |
| `WITHDRAWAL-TIMING-001` | P2 | offen, abgegrenzt | Unterjährige Placement-Präzision bleibt offen; die neue falsche Occurrence-Anzahl wird separat als P1 geführt. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
React GoalWizard
  recurring/pension:
    sichtbar: frequency
    fehlt: amount + start + end + ongoing
           |
           v
  target_amount=null, start_date=null, is_ongoing=false
           |
           v
Backend Complete-State-Guard -> HTTP 422

Classic Editor besitzt Betrag + Start + Ende + ongoing
=> zwei aktive UI-Verträge für dieselbe Domain
```

Der Scheduler-Widerspruch verläuft unabhängig davon:

```text
Goal: jährlich CHF 100, 31.12.2026 bis 01.01.2027

kanonischer Occurrence-Scheduler       Goal-Liability / Reporting-MC
31.12.2026: CHF 100                    touched years = 2026, 2027
nächster Termin 31.12.2027 > Ende      annual amount je Label = CHF 100
Summe = CHF 100                        Summe = CHF 200
```

Der Zeitbase-Widerspruch ist eine dritte, orthogonale Achse:

```text
target_date = 03.10.2038
as_of       = 03.10.2026

calendar anniversaries                ceil(delta_days / 365)
12 Jahre                              4.383 Tage -> 13 Jahre
Optimizer target index = 12           API/Reporting horizon = 13
```

Die Monte-Carlo-Zertifizierung verwendet danach keine unabhängige Evidence:

```text
ein Train-Cube
    |
    +--> alle Solver-Kandidaten und Multi-Starts
    +--> Kandidatenauswahl
    +--> Post-Rounding Objective
    +--> finale Goal-Probability
    +--> tau-Vergleich / Status / Penalty
    +--> Persistenz / Message / UI / PDF

kein unveränderlicher Validation-Cube
kein selection-aware Lower Bound
kein statistically_uncertain-Zustand
```

## Positivkontrollen, die erhalten bleiben müssen

1. Der Backend-Complete-State-Guard blockiert unvollständige recurring Goals
   heute mit 422. Diese Fail-closed-Eigenschaft darf beim Editorfix nicht
   gelockert werden.
2. Der Classic Editor besitzt bereits Betrag, Start, Ende, Frequenz und
   `is_ongoing` sowie eine Startpflicht für wiederkehrende Ziele.
3. `cashflow_timeline.contribution_for_year()` zählt verankerte monatliche,
   quartalsweise, halbjährliche und jährliche Occurrences und besitzt bereits
   Property-Tests für Fenstergrenzen.
4. `calendar_years_until(target, as_of=...)` definiert exakte Jahrestage und
   Leap-Day-Mapping korrekt, wenn der Stichtag explizit übergeben wird.
5. Der Optimizer verwendet Common Random Numbers innerhalb des Trainings-
   Cubes. Das ist für fairen Kandidatenvergleich richtig und soll erhalten
   bleiben.
6. Final gerundete bps werden heute auf demselben Context neu bewertet. Der
   Holdout ergänzt diese Kongruenz; er ersetzt sie nicht.
7. Importance-Sampling-Gewichte fließen in Objective, Chance Probability und
   Penalty ein. Eine Validierung muss denselben fachlichen Estimatorvertrag
   verwenden, aber unabhängige Zufalls-Evidence besitzen.
8. React unterscheidet Rang und Härte bereits getrennt; der neue Formvertrag
   darf `GOAL-RANK-HARDNESS-ROUNDTRIP-001` nicht regressieren.
9. Vollständige Goal-Felder werden im aktuellen Input-Snapshot gehasht. Der
   Fix ergänzt den effektiven Stichtag und aufgelöste Schedule-Evidence, statt
   Rohfelder wieder zu entfernen.
10. Vergangene Goals dürfen nicht pauschal gelöscht werden. Historie und
    Nachweis bleiben erhalten; nur ihre aktive wirtschaftliche Behandlung
    braucht einen expliziten Lifecycle-Vertrag.

## Codeanker des auditierten Stands

### React-Editor, Formvertrag und echter API-Guard

- `5eyes-electron/frontend/reporting/src/App.tsx:36-37`, `:84-85` und
  `:130-140` verdrahten `GoalsEditor` und damit `GoalWizard` als echten
  React-Routenpfad.
- `reporting/src/sections/goals/GoalWizard.tsx:43-62` definiert den
  `WizardState` ohne `startDate` und `isOngoing`.
- `GoalWizard.tsx:64-83` sowie `:86-109` initialisieren beziehungsweise laden
  diese Felder deshalb nicht aus einem bestehenden Record.
- `GoalWizard.tsx:112-144` setzt `target_amount_rappen` nur für
  `Einmalige_Ausgabe` und übergibt weder `start_date` noch `is_ongoing`.
- `GoalWizard.tsx:335-345` rendert den Betragsinput ausschließlich für
  Einmalziele; `:370-381` zeigt beim recurring Goal nur die Frequenz;
  `:383-405` zeigt Datum/Horizont nur für Einmal- und Vermögensziele.
- `reporting/src/lib/goalForm.ts:149-153` verlangt clientseitig für recurring
  nur die Frequenz, nicht positiven Betrag oder gültiges Timing.
- `goalForm.ts:180-210` setzt `is_ongoing` standardmäßig auf `false` und
  `target_amount_rappen` ausschließlich beim Einmalziel.
- `5eyes-backend/services/goal_semantics.py:174-180`, `:212-216` und
  `:250-262` verlangen im Backend positiven Betrag, Stream-Timing und für
  endliche Streams ein Enddatum.
- `5eyes-backend/routers/wealth.py:261-279` validiert Updates gegen den
  vollständigen gemergten Zustand; `:282-339` normalisiert danach und ruft
  den strengen Domainvertrag auf.
- `GoalWizard.test.tsx:24-63` baut ein Pensionsziel ohne Betrag und Timing;
  `:70-91` mockt `updateGoal()` erfolgreich und prüft nur drei andere Felder.
- `goalForm.test.ts` besitzt weder einen validen recurring Positivfall noch
  Betrag-/Timing-/Roundtrip-Negativfälle.
- `5eyes-electron/frontend/5eyes_v2.html:4690-4733`, `:26280-26294` und
  `:26721-26806` belegen, dass der Classic-Pfad Betrag, Start, Ende,
  Frequenz und laufend bereits erfasst und übergibt.

### Occurrence-Scheduler und allgemeine Reporting-MC

- `5eyes-backend/services/optimizer/goal_liabilities.py:183-200` berechnet
  die Dauer als `target_date.year - start_date.year + 1`.
- `goal_liabilities.py:233-246` annualisiert den Periodenbetrag pauschal mit
  12, 4, 2 oder 1.
- `goal_liabilities.py:428-485` schreibt diesen vollen Jahresbetrag in jeden
  so bestimmten Bucket.
- `5eyes-backend/services/cashflow_timeline.py:93-157` besitzt bereits die
  kanonische Occurrence-Enumeration vom echten Startanker bis zum inklusiven
  Ende.
- `5eyes-backend/tests/test_cashflow_annualization_properties.py:30-95`
  schützt Frequenzen, Fenster, inklusive Endgrenze und Teiljahresmonotonie.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:816-841`
  implementiert für Goal-Reporting erneut inklusive Jahreslabel-Dauern.
- `portfolio_engine_mc_simulation.py:934-967` multipliziert den annualisierten
  Betrag mit dieser Dauer und prüft die kumulierte Summe an einem Zielindex.
- `tests/test_optimizer_goal_liabilities.py:344-442` deckt nur glatte,
  mehrjährige positive Beispiele auf Basis von `date.today()+365*n` ab;
  Dec/Jan-, kurze Fenster- und Occurrence-Reconciliation fehlen.

### Past-Lifecycle und kanalwidersprüchliche Behandlung

- `5eyes-backend/services/calendar_horizon.py:28-53` gibt für
  `target_date <= as_of` korrekt null zukünftige Buckets zurück.
- `services/optimizer/goal_liabilities.py:148-180` macht daraus mit
  `max(1, ...)` dennoch Zieljahr eins.
- `routers/wealth.py:157-163` normalisiert vergangene Zieldaten ebenfalls
  ausdrücklich auf Horizont eins.
- `services/goal_semantics.py:174-180` prüft nur Reihenfolge und Parsebarkeit,
  nicht den Lifecycle eines vergangenen aktiven Ziels.
- `portfolio_engine_mc_simulation.py:816-841` schneidet vergangene Streams
  aus dem Reporting-Overlap heraus, während der Optimizer sie neu ab Jahr
  eins materialisiert.
- `reporting/src/lib/goalClassification.ts:52-90` gibt für ein Zieljahr vor
  dem MC-Startjahr ausdrücklich Status `past` zurück.
- `goalClassification.test.ts:94-99` schützt diese UI-Klassifikation.
- Die Goal-Domain besitzt `is_active`, aber keinen typisierten Status für
  `planned`, `due`, `overdue`, `fulfilled` oder `cancelled` und keinen
  Outstanding-Betrag.

### Kalender-Timebase, Snapshot und Model-Basis

- `services/calendar_horizon.py:28-53` verwendet `as_of or date.today()`.
- `goal_liabilities.py:174` und
  `portfolio_engine_mc_simulation.py:130-142` übergeben keinen `as_of`.
- `routers/wealth.py:157-163` und
  `services/portfolio_engine_payload.py:353-368` rechnen separat mit
  `ceil(delta_days/365)` und klemmen Past auf eins.
- `reporting/src/lib/goalClassification.ts:73-93` sowie
  `5eyes-backend/services/pdf/components/goal_classification.py:51-72`
  leiten den Zielindex dagegen nur aus der Differenz der vierstelligen
  Kalenderjahre ab.
- `5eyes-electron/frontend/5eyes_v2.html:15114-15132` verwendet im Classic-
  Pfad zusätzlich eine eigene `365.25`-Tage-Näherung.
- `portfolio_engine_payload.py:357-365` verwendet für recurring Goals zuerst
  `target_date`, während der Optimizer in `goal_liabilities.py:166-174`
  zuerst `start_date` verwendet.
- `services/optimizer/solver.py:132-180` definiert `OptimizerContext` ohne
  `valuation_date`/`as_of`; `:321-585` baut den Context ebenfalls ohne diesen
  Anker.
- `services/portfolio_engine.py:2429-2480` hasht die rohen vollständigen
  Goal-Felder; `:2237-2330` bindet viele Projection-Inputs, aber keinen
  Bewertungsstichtag.
- `portfolio_engine.py:2552-2791` publiziert Seed, Pfadzahl und Horizonte in
  der Model-Basis, aber keine Valuation-Timebase.
- `tests/test_calendar_horizon_contract.py:35-65` beweist nur die
  Kalenderhelper- und Optimizer-/Simulation-Horizon-Parität. Router und
  Reporting-`_goal_projection_years()` sind nicht Teil des Tests; der Test
  verwendet für den Produktionsaufruf weiterhin implizit `date.today()`.

### Train-Cube, Kandidatenauswahl und finale Probability

- `services/optimizer/solver.py:132-149` enthält genau einen Seed und ein
  `return_paths`-Array im Context.
- `services/portfolio_engine_optimizer_integration.py:343-372` baut und hält
  genau diesen einen Context für den produktiven Solverpass.
- `solver.py:592-610` simuliert Objective-Kandidaten auf diesem Context.
- `solver.py:1264-1390` reicht dieselbe Objective-Closure an sämtliche
  Multi-Starts und den GA-Fallback.
- `solver.py:1538-1557` bewertet gerundete Finalgewichte und ihre
  Goal-Probability wieder auf demselben Context.
- `services/optimizer/objective.py:335-406` setzt `probability >= tau`
  unmittelbar auf `erreichbar` und Penalty null.
- `objective.py:627-641` integriert diese Chance-Penalty in die
  kandidatenbestimmende Objective.
- `tests/test_chance_constraint.py:93-103` schreibt 1.600 Erfolge aus 2.000
  Pfaden bei `tau=0.80` ausdrücklich als `erreichbar` und Penalty null fest.
- `models/allocation.py:166-190` persistiert für `OptimizerRun` nur einen Seed
  und `n_paths`; Validation-Seed, Cube-Hash, Intervall und Reliability fehlen.
- `portfolio_engine.py:3803-3813` persistiert die nackten Goal-Zeilen;
  `objective.py:397-405` enthält nur Probability, Tau, Status und Hardness.
- `portfolio_engine_optimizer_integration.py:412-450` prüft vor Aktivierung
  Constraints, aber keine unabhängige Probability-Evidence; `:499-517`
  übernimmt danach die konvergierten Gewichte.
- `portfolio_engine.py:2743-2784` kennzeichnet die allgemeine Reporting-MC
  ausdrücklich als separates `post_selection_projection`; sie ist kein
  Same-Model-Zertifizierungsgate des Solverresultats.
- `services/allocation_messages.py:53-80` und `:262-311` leiten daraus unter
  anderem komfortable versus knappe Aussagen ab.
- `routers/pdf_reports.py:756-810` trägt die resultierende Goal-Evidence in
  die PDF-Publikation weiter.

## Deterministische Reproduktionen

### Repro 1 – React recurring Create und No-op-Edit enden in HTTP 422

Die echte `_normalize_goal_payload()` erhielt den vom aktuellen React-
Vertrag erzeugten Kernzustand:

```text
goal_type                  Wiederkehrende_Ausgabe
target_amount_rappen       null
frequency                  jaehrlich
start_date                 null
target_date                null
horizon_years              null
is_ongoing                 false
```

Output:

```text
HTTP 422: Cashflow-Ziel benötigt einen positiven Zielbetrag
```

Der gleiche erste Fehler blockiert finite und ongoing No-op-Edits, weil
`stateFromRecord()` zwar den vorhandenen Betrag in `amountChf` lädt, aber der
Wizard keinen recurring Betragsinput zeigt und `toFormInput()` den Wert
explizit auf null setzt. Der Test sieht den Fehler nicht, weil die API gemockt
ist.

Präzisionsgrenze: Im heutigen Backend wurde **keine** stille Beschädigung
persistiert. Ein isolierter Scheinfix nur für `target_amount_rappen` wäre aber
gefährlich: `start_date` und `is_ongoing` blieben weiterhin verloren und ein
endlicher Stream könnte auf das Enddatum als einzigen Startanker kollabieren.

### Repro 2 – Zwei Kalendertage erzeugen zwei volle Jahreszahlungen

Produktionsfunktionen:

- `goal_to_liability()`
- `contribution_for_year()`
- `simulate_wealth_paths()`
- `goal_probability_per_path()`

Input:

```text
frequency                   jaehrlich
amount                      CHF 100
start                       31.12.2026
end                         01.01.2027
initial wealth              CHF 150
returns / cashflow          0
```

Output:

```text
current goal liability      [100, 100, 0]
current total               CHF 200
current wealth              [150, 50, -50, -50]
current P                    0

canonical occurrences       [100, 0, 0]
canonical total             CHF 100
canonical wealth            [150, 50, 50, 50]
canonical P                  1
```

Dieser Repro benötigt keine Teiljahresproration: Bei einer jährlich ab
31.12. verankerten Serie ist der nächste Termin der 31.12.2027 und liegt klar
nach dem Enddatum 01.01.2027. Die zweite Zahlung ist nicht nur zeitlich grob,
sondern fachlich nicht existent.

Für monatlich CHF 100 ist die Überzeichnung noch größer:

```text
30.12.2026..31.12.2026       Goal CHF 1.200, kanonisch CHF 100
31.12.2026..01.01.2027       Goal CHF 2.400, kanonisch CHF 100
```

### Repro 3 – Vergangene Ziele werden in die Zukunft reaktiviert

Mit `horizon_years=10`, Stand 03.10.2026:

```text
past one-off, target 01.01.2020
  target_year_index          1
  liability_path             [amount,0,0,0,0,0,0,0,0,0]

past wealth target, 01.01.2020
  target_year_index          1
  evaluation                 next simulated year

expired monthly stream, 01.01.2020..31.12.2022, CHF 100/month
  optimizer target           CHF 3.600
  optimizer path             [1200,1200,1200,0,0,0,0,0,0,0]
  reporting overlap years    0

part-past monthly stream, 01.01.2020..31.12.2028, CHF 100/month
  optimizer target           CHF 10.800
  optimizer path             9 future full-year payments
  reporting remaining years  3
```

Die API-Normalisierung akzeptierte sowohl das vergangene Einmalziel als auch
das vergangene Vermögensziel und leitete `horizon_years=1` ab. Der Widerspruch
ist daher im regulären Datendomänenpfad erreichbar.

### Repro 4 – Exakter 12-Jahres-Jahrestag ergibt Jahr 12 und Jahr 13

Input am 03.10.2026:

```text
target_date                  03.10.2038
delta_days                   4.383
```

Output echter Produktionshelper:

```text
router _goal_horizon_from_date        13
reporting _goal_projection_years      13
calendar_years_until                  12
optimizer target_year_index           12
simulation horizon with stored value  13
```

Bei einem realen Target von 1.000.000 Rappen und zwei Prozent jährlicher
Inflation ergab die echte Zielwertlogik:

```text
optimizer, year 12            1.268.242 Rappen
reporting, year 13            1.293.607 Rappen
difference                       25.365 Rappen
```

Die Differenz skaliert linear mit dem Zielbetrag und kann Probability, Status,
Shortfall, Driver und Allokationsentscheidung verschieben.

Ein eingefrorener Cross-Channel-Harness bestätigt, dass dies nicht nur ein
Metadatenunterschied ist:

```text
as_of                        01.01.2024
target_date                  01.01.2025
wealth path                  t0=100, t1=50, t2=150
wealth target                100

router horizon               2
main-MC goal index           2
main-MC success              100 %

optimizer target index       1
optimizer success            0 %
React/PDF target index       1
React/PDF status             nicht_erreichbar
```

Auch „heute fällig“ ist widersprüchlich. Bei `as_of=target=03.10.2026`,
`t0=50`, `t1=150` und Target 100 bewerten Optimizer/Haupt-MC Jahr eins und
melden Erfolg, während React/PDF Kalenderjahrindex null und damit
`nicht_erreichbar` verwenden.

### Repro 5 – Identischer Rohinput ändert sich über Nacht

```text
target_date                  04.10.2027
as_of 03.10.2026             target year 2
as_of 04.10.2026             target year 1
```

Das ist für eine laufende Planung grundsätzlich erwartbar. Nicht zulässig ist,
dass weder Context noch Hash noch Model-Basis den verwendeten Stichtag binden.
Ein Replay mit identischen gespeicherten Rohfeldern kann deshalb eine andere
Liability erzeugen.

Ein zweiter Fixed-Time-Repro mit unverändertem Ziel `01.01.2034` ergab:

```text
as_of 31.12.2026             optimizer index 8
as_of 01.01.2027             optimizer index 7
input snapshot hash          in beiden Läufen identisch
hash prefix                  4bba10012618fe27
```

Der Snapshot behauptet damit Gleichheit, obwohl die wirtschaftliche
Liability-Auflösung verschieden ist.

### Repro 6 – Standard-MC kippt am exakten Tau

Für ein Goal mit theoretisch `P=0.80`, `tau=0.80`, 2.000 antithetischen
Standard-MC-Pfaden und 100 Seeds:

```text
erreichbar                  52
knapp                       48
sample probability range   0.7815 .. 0.8155
```

Bei einem illustrativen unabhängigen Binomialmodell beträgt der Standardfehler
bei `p=0.8`, `n=2000` ungefähr `0.00894`; das 95-Prozent-Wilson-Intervall
liegt ungefähr bei `0.7819..0.8169`. Wegen der Abhängigkeit antithetischer
Paare ist dieses naive Intervall **kein** produktiver Fix. Der Befund erweitert
den Confidence-Budget-Punkt von `OPTIMIZER-IS-ESS-001` und erhält keine zweite
ID.

### Repro 7 – Grüner echter Solvergewinner scheitert auf unabhängigem Cube

Ein realer Standard-MC-Solverlauf mit `score=70`, zehn Jahren,
`n_paths=2000`, `seed=17`, primärem Ziel, `tau=0.80` und Target 126.300
lieferte:

```text
solver status                 converged
final weights bps             equities 4500
                              bonds 4499
                              real_estate 499
                              alternatives 302
                              liquidity 200

selection-cube P              0.800000
selection verdict             erreichbar
chance penalty                0
```

Die exakt gerundeten Finalgewichte wurden mit denselben wirtschaftlichen
Inputs auf einem unabhängigen Standard-MC-Cube `seed=9917`, `n=200000`
ausgewertet:

```text
independent P                 0.798125
independent verdict           knapp
chance penalty                3.515625
illustrative Wald 95 %        0.796366 .. 0.799884
```

Das Intervall ist hier nur Reprodiagnostik; der produktive Fix muss die
Abhängigkeit antithetischer Paare estimatorgerecht behandeln. Entscheidend
ist, dass der heute aktivierbare grüne Grenzentscheid keine unabhängige
Same-Model-Zertifizierung besitzt.

Ein ergänzender Selection-Bias-Repro wiederholte den Vorgang systematisch.

Produktionsnahe Konfiguration:

```text
fünf marginal identische Asset-Kandidaten
wahre P(success) je Kandidat  0.80
tau                           0.80
train paths                   2.000, antithetic Standard-MC
selection                     bestes One-hot-Portfolio nach echter Objective
validation                    unabhängiger Cube
seed pairs                    100
```

Ergebnis:

```text
train erreichbar              97 / 100
train mean P                  0.80660

validation erreichbar         53 / 100
validation mean P             0.79992

train erreichbar,
validation knapp              47 / 100
```

Der Trainingsmittelwert ist nach Auswahl positiv verzerrt, obwohl jede
einzelne Kandidatenverteilung korrekt kalibriert ist. Deterministischer Seed
macht den ausgewählten Einzelentscheid wiederholbar, aber nicht unabhängig
validiert.

## Finding `GOAL-RECURRING-EDITOR-CONTRACT-001`

### Beobachtung und Wirkung

Der React-Wizard behauptet clientseitige Parität zum Backend, implementiert
aber nur einen Teil des discriminated Goal-Vertrags. Für recurring Goals
existiert ein Betrag im Record-State, aber kein sichtbarer Input und kein
Payloadpfad. Timingfelder existieren nicht einmal im State. Damit sind:

1. Neuanlage von wiederkehrenden und Pensionszielen unmöglich;
2. ein inhaltlicher No-op-Edit unmöglich;
3. Classic und React fachlich nicht gleichwertig;
4. der Unit-Test grün, obwohl der echte Request sicher scheitert;
5. ein Teilfix am Betrag geeignet, erst danach einen stillen Timingverlust zu
   aktivieren.

### Verbindlicher Reparaturvertrag

1. `GoalFormInput` wird als diskriminierte Union pro `goal_type` modelliert.
2. Recurring/Pension verlangt positiven Periodenbetrag, unterstützte Frequenz,
   `start_date` sowie genau eine der Endsemantiken:
   `is_ongoing=true` ohne Enddatum oder `is_ongoing=false` mit Enddatum.
3. `stateFromRecord()`, sichtbare Controls, `toFormInput()` und
   `buildGoalPayload()` müssen exakt dieselben Felder roundtrippen.
4. Ein No-op-Edit erzeugt für alle rechenwirksamen Felder semantisch
   bytegleichen Zustand; explizit `null`, `false` und vorhandene Werte dürfen
   nicht durch Defaults verwechselt werden.
5. Frontendvalidation wird aus einem gemeinsamen Schema generiert oder in
   Contracttests direkt gegen den Backendvalidator geprüft.
6. Classic und React senden für denselben fachlichen Input denselben
   normalisierten Payload.
7. API-Fehler bleiben sichtbar und blockierend; kein optimistisches `onSaved`
   vor bestätigter Persistenz.
8. Jede erfolgreiche Mutation invalidiert die abhängige Goal-/Allocation-/
   Probability-Evidence gemäß `GOAL-SNAPSHOT-001`.

### Pflichttests

1. Create/No-op-Edit für endliche und laufende Wiederkehrende_Ausgabe.
2. Create/No-op-Edit für Pensionsausgabe je zulässiger Säule.
3. Matrix über alle Frequenzen und `target_amount_rappen`-Grenzen.
4. Start > Ende, fehlender Start, finite ohne Ende, ongoing mit Ende,
   negativer/null Betrag müssen fail-closed bleiben.
5. Echter React-API-Integrationstest ohne gemocktes `updateGoal()`.
6. React-/Classic-Payload-Golden-Parität.
7. No-op bewahrt Betrag, Start, Ende, ongoing, Horizont, Frequenz,
   Wahrscheinlichkeit, Säule, Rang, Härte und Weight.

## Finding `GOAL-RECURRENCE-SCHEDULE-001`

### Beobachtung und Wirkung

Der Goal-Scheduler besitzt keine Occurrence-Liste. Er berechnet nur, wie viele
Kalenderjahreszahlen zwischen Start- und Endjahr liegen, und belastet jedes
davon mit einem vollen annualisierten Betrag. Dadurch:

1. werden kurze Fenster um Faktor 12 beziehungsweise 4 überzeichnet;
2. erzeugt eine minimale Verschiebung über den 1. Januar eine weitere volle
   Jahreszahlung;
3. können Wealth-Pfade, Goal-P, Chance-Penalty und Solverrangfolge kippen;
4. unterscheiden sich Cashflow- und Goal-Domain trotz gleicher Frequenz- und
   Datumsbegriffe;
5. wiederholt die Reporting-MC die falsche Summenlogik unabhängig vom
   Optimizer;
6. kann ein späteres Funding-Ledger aus Runde 37 nur falsch reconciliieren,
   wenn bereits `amount_due` falsch ist.

### Verbindlicher Reparaturvertrag

1. Es gibt genau einen versionierten `OccurrenceSchedule` für Cashflows und
   Goals oder einen gemeinsamen getesteten Schedulerkern.
2. Der Scheduler enumeriert echte Fälligkeitstermine aus Startanker,
   Frequenz, inklusivem/exklusivem Endvertrag und Kalenderregel.
3. Erst danach werden Occurrences auf die explizit definierten Simulations-
   Buckets gemappt. Jahreslabel und Valuation-Anniversary dürfen nicht
   verwechselt werden.
4. `amount_due` je Bucket ist die Summe der gemappten Occurrences, nicht
   pauschal der volle Jahresbetrag.
5. Inflation, Eintrittswahrscheinlichkeit, Tod/Survival, Tax und Funding
   werden in dokumentierter Reihenfolge angewandt; jede Stufe ist
   reconciliable.
6. Solver, Haupt-MC, Reserve, deterministic Goal Analysis, Sensitivity, UI und
   PDF konsumieren denselben aufgelösten Schedule-Snapshot und dessen Hash.
7. Legacyzeilen ohne eindeutige Anker-/Endsemantik werden replayed oder als
   `schedule_unknown` quarantänisiert.

### Pflichttests

1. Der konkrete 31.12.–01.01.-Jahresrepro enthält genau eine Occurrence.
2. Matrix monatlich/quartalsweise/halbjährlich/jährlich über Same-Year,
   Cross-Year, Exact-End und End-einen-Tag-vor-nächster-Fälligkeit.
3. Monatsende 28/29/30/31, Leap Day und mehrjährige Ankerdrift.
4. Summe Bucketbeträge entspricht exakt Summe Occurrences.
5. Kein Bucket enthält eine Fälligkeit nach `target_date`.
6. Goal- und Cashflow-Scheduler liefern für äquivalente Verträge dieselbe
   Serie.
7. Solver und Reporting-MC verwenden dieselbe Serie und denselben Targetwert.
8. Der CHF-150-Repro liefert nach Fix P=1 und keinen Phantom-Shortfall.

## Finding `GOAL-PAST-DATE-LIFECYCLE-001`

### Beobachtung und Wirkung

`max(1, years)` vermischt drei fachlich verschiedene Zustände:

- historisch erfüllt oder storniert;
- überfällig und noch offen;
- heute beziehungsweise unmittelbar fällig.

Alle werden ohne Nachweis als reguläres Ziel in Simulationsjahr eins
interpretiert. Bei Streams bleibt zusätzlich die historische Gesamtdauer
erhalten und wird ab Jahr eins neu abgespielt. Das kann:

1. nicht mehr bestehende Ausgaben erneut vom Portfolio abziehen;
2. ein altes Vermögensziel als neue Mindestschwelle bewerten;
3. Reporting und Optimizer für denselben Datensatz gegensätzlich färben;
4. Reserve, Risiko, Allokation und Goal-Funding verfälschen;
5. historische Evidence mit einer heutigen überfälligen Forderung
   verwechseln.

### Verbindlicher Reparaturvertrag

1. Ein Goal besitzt einen typisierten Lifecycle, mindestens
   `planned`, `due`, `overdue`, `fulfilled`, `cancelled` und gegebenenfalls
   `historical_unknown`.
2. Lifecycle-Transitionen sind append-only auditiert und binden Actor, Zeit,
   Grund, Outstanding-Betrag sowie Evidenz.
3. Ein vergangenes aktives Goal darf nicht automatisch auf Jahr eins
   geklemmt werden.
4. `fulfilled`/`cancelled` erzeugt keine zukünftige Liability, bleibt aber
   historisch sichtbar.
5. `overdue` benötigt eine Owner-Policy: sofortiger t0-Bedarf, neu
   vereinbartes Fälligkeitsdatum oder blockierender Klärungszustand. Keine
   dieser Varianten darf still als normales Jahr eins erscheinen.
6. Ein teilweise vergangener Stream materialisiert nur noch offene
   Occurrences nach dem Valuation-Stichtag; bereits erfüllte Beträge werden
   nicht erneut geplant.
7. Optimizer, Reporting, UI, PDF, Sensitivity und Snapshot verwenden denselben
   Lifecycle- und Outstanding-Snapshot.

### Pflichttests

1. Gestern, heute, morgen und exakter Jahrestag für Einmal- und Wealth-Ziele.
2. Vollständig vergangener Stream je Lifecycle-Status.
3. Teilweise vergangener Stream: nur offene Rest-Occurrences.
4. Overdue ohne Policy/Evidence blockiert statt Jahr eins zu erfinden.
5. `fulfilled` und `cancelled` bleiben sichtbar, aber wirtschaftlich null.
6. UI-Status `past` darf nie neben zukünftiger Optimizer-Liability stehen.
7. Lifecycle-Transition invalidiert abhängige Evidence atomar.

## Finding `GOAL-CALENDAR-HORIZON-PARITY-001`

### Beobachtung und Wirkung

Die Codebasis besitzt gleichzeitig:

1. kalendergenaue Anniversary-Arithmetik;
2. `ceil(delta_days/365)`;
3. Jahreslabeldifferenz für Streamdauer;
4. implizites `date.today()` in mehreren Modulen;
5. `base_calendar_year` ohne vollständiges Valuation-Datum.

Damit kann derselbe Datensatz in einem Request bereits unterschiedliche
Zieljahre erhalten. Selbst wenn alle Layer zufällig übereinstimmen, ändert
sich die wirtschaftliche Interpretation über Nacht, ohne dass Hash oder
Model-Basis sich ändern.

### Verbindlicher Reparaturvertrag

1. Jeder Run besitzt ein unveränderliches `valuation_date` plus Zeitzone und
   eine versionierte Bucket-Konvention.
2. Alle Goal-, Cashflow-, Life-Course-, Tax- und Reporting-Caller erhalten
   diesen Wert explizit; kein produktiver Kerncaller verwendet direkt
   `date.today()`.
3. Ein zentraler Resolver erzeugt je Goal den kanonischen Lifecycle und
   Occurrence-/Evaluation-Schedule.
4. Rohdaten plus `valuation_date`, Resolverversion, Schedule und Hash werden
   an `OptimizerContext`, Input-Snapshot, Model-Basis, Run, Allocation,
   Sensitivity und Publikation gebunden.
5. API darf `horizon_years` nicht mit einer anderen Arithmetik ableiten als
   der Optimizer. Entweder wird nur der kanonische resolved horizon
   persistiert oder die Ableitung bleibt rein und nachprüfbar.
6. Reload und Replay verwenden den gespeicherten Stichtag; ein heutiger
   Livevergleich wird ausdrücklich als neuer Counterfactual-Run benannt.
7. Mismatch zwischen Raw-Datum, resolved horizon und Schedule blockiert.

### Pflichttests

1. Exakte Jahrestage über 1, 4, 12, 20 und 40 Jahre mit Schaltjahren.
2. 28./29. Februar und Ziel einen Tag vor/am/nach Jahrestag.
3. Router, Validator, Optimizer, Haupt-MC, Reserve und UI erhalten exakt
   denselben Index.
4. Gleicher Run ist bei Replay an einem späteren Kalendertag bytegleich.
5. Unterschiedlicher `valuation_date` ändert Hash und Evidence sichtbar.
6. Recurring Start- und Endanker werden nicht zwischen Layern vertauscht.
7. Der 03.10.2038-Repro ergibt überall Jahr 12.

## Finding `OPTIMIZER-POST-SELECTION-CERTIFICATION-001`

### Beobachtung und Wirkung

Common Random Numbers sind für den Vergleich von Kandidaten richtig. Der
Fehler entsteht danach: Der Gewinner wird auf demselben Sample erneut als
finales Ergebnis zertifiziert. Unter mehreren Kandidaten wird systematisch
derjenige ausgewählt, dessen endlicher Samplefehler günstig ist. Die erneute
Berechnung auf denselben Pfaden entfernt diesen Auswahlbias nicht.

Folgen:

1. `P >= tau` kann nach Auswahl deutlich häufiger grün sein als auf
   unabhängiger Evidenz.
2. Chance-Penalty und Allokation werden durch denselben günstigen Samplefehler
   bestimmt.
3. `OK_COMFORTABLE`/`OK_TIGHT`, Zielkonflikt und PDF-Ampel können überoptimiert
   sein.
4. Ein einzelner Seed ist deterministisch, aber nicht Accuracy- oder
   Generalisierungs-Evidence.
5. Mehr Multi-Starts, GA-Kandidaten oder Assetvarianten erhöhen die
   Selektionschance, ohne dass der veröffentlichte Vertrag dies berücksichtigt.
6. IS-ESS-Gates allein beheben das Problem nicht; es tritt bei uniformen
   Gewichten auf.

### Verbindlicher Reparaturvertrag

1. Training behält einen eingefrorenen CRN-Cube für sämtliche Kandidaten.
2. Nach finaler bps-Rundung wird exakt ein vorregistrierter, unabhängiger
   Validation-Cube oder ein festes unabhängiges Seed-Ensemble ausgewertet.
3. Der Validation-Cube darf nicht zur erneuten Kandidatenauswahl verwendet
   werden. Retry und sequenzielle Erweiterung folgen einer vorab versionierten
   Stopping-Policy.
4. `erreichbar` ist nur zulässig, wenn ein estimatorgerechter einseitiger
   Lower Confidence Bound `>= tau` ist.
5. Überlappt der Unsicherheitsbereich `tau`, lautet der Zustand zunächst
   `statistisch_unsicher`; Pfade dürfen bis zu einem festen Cap erweitert
   werden. Am Cap wird nicht still grün oder gelb geraten.
6. Antithetische Paare werden als abhängige Cluster behandelt. Bei
   selbstnormalisiertem IS kommen geeignete Varianzschätzung, Prefix-
   Likelihood und ESS-/Konzentrations-Gate hinzu.
7. Persistiert werden Train-/Validation-Seed, Pfadzahl, Cube-/Shock-Hash,
   Estimatorversion, effektive Stichprobengröße, Punktschätzer, Intervall,
   Decision Margin, Alpha, Stopping-Rule und Reliability-Verdict.
8. Allocation, Goal-Zeilen, Messages, UI, PDF, Signatur und Handoff binden
   dieselbe Validation-Evidence.
9. Legacy-Punktschätzer ohne Validation werden nicht rückwirkend als validiert
   behandelt; sie werden replayed oder sichtbar quarantänisiert.

### Pflichttests

1. Exakt 1.600/2.000 Erfolge bei `tau=0.80` sind ohne ausreichenden Lower
   Bound nicht automatisch grün.
2. 1.599/2.000 und Boundary knapp oberhalb/unterhalb Tau.
3. Der dokumentierte Fünf-Kandidaten-/100-Seed-Paar-Repro besitzt nach Fix
   keine systematisch überoptimierte Freigabe.
4. Kandidatenpermutation ändert bei identischen Daten die Validation nicht.
5. Train- und Validation-Cube besitzen verschiedene Seeds und Hashes.
6. Manipulation oder Missing eines Validation-Ankers blockiert Reload und
   Veröffentlichung.
7. Sequenzielle Erweiterung respektiert Alpha-/Stopping-Budget und Cap.
8. Low-ESS-/konzentriertes IS liefert `unreliable`, nicht eine grüne Ampel.
9. Replay, API, UI und PDF zeigen identische Estimate-/Interval-/Verdict-
   Evidence.

## Bewusst als Erweiterung statt neue Finding gezählte Punkte

### Allgemeines Sampling Error am Tau

Der 52/48-Seed-Repro ist wichtig, aber die Ursache ist bereits im
Lösungspunkt 7 von `OPTIMIZER-IS-ESS-001` erfasst: kritische Probability-
Entscheide benötigen Seed-Ensemble beziehungsweise sequenzielle Konvergenz
und ein Difference-/Confidence-Budget. Neu ist nur die fehlende unabhängige
Post-Selection-Validierung; dafür steht
`OPTIMIZER-POST-SELECTION-CERTIFICATION-001`.

### Snapshot- und Publikationsbindung

Fehlendes `valuation_date`, Schedule-Hash, Validation-Verdict und
Lifecycle-State liefern neue Beweise für `GOAL-SNAPSHOT-001`,
`MC-CONTEXT-001`, `GOAL-PUBLICATION-001` und `REP-001`. Diese allgemeinen IDs
werden nicht dupliziert.

### Funding und individuelle Attribution

Ein korrekter Occurrence-Schedule definiert `amount_due`. Erst die in Runde 37
geforderte `GoalFundingPolicy` entscheidet `amount_funded`. Ein Holdout kann
eine Probability statistisch validieren, macht eine gemeinsame
Aggregatepfad-Probability aber nicht automatisch zielindividuell. Beide
älteren Findings bleiben vollständig offen.

## Testverifikation

Backend:

```text
python -m pytest -q --basetemp ..\.pytest_tmp_round38 \
  tests/test_optimizer_goal_liabilities.py \
  tests/test_calendar_horizon_contract.py \
  tests/test_goal_domain_fail_closed_contracts.py \
  tests/test_goal_schema_field_isolation.py \
  tests/test_chance_constraint.py \
  tests/test_optimizer_objective_constraints.py \
  tests/test_frontend_goal_editor_isolation.py \
  tests/test_goals_editor_wiring_contract.py \
  tests/test_optimizer_production_contract.py

235 passed in 90.49s
```

React:

```text
npm.cmd test -- \
  src/sections/goals/GoalWizard.test.tsx \
  src/lib/goalForm.test.ts \
  src/lib/goalClassification.test.ts

3 test files passed
44 tests passed
```

Gesamt: **279 bestehende fokussierte Tests bestanden, 0 fehlgeschlagen**.

Die grüne Suite enthält nicht:

- einen validen recurring Create-/No-op-Edit gegen das echte Backend;
- Betrag-/Start-/End-/ongoing-Roundtrip im React-Wizard;
- Dec/Jan-Occurrence-Reconciliation zwischen Goal und Cashflow;
- ein kurzes jährliches Fenster mit genau einer Fälligkeit;
- vergangene One-off-/Wealth-/Stream-Ziele je Lifecycle-Status;
- den 365-Tage-/Kalenderjahres-Leap-Repro über Router, Reporting und
  Optimizer;
- Replay desselben Runs nach einem Kalendertag;
- unabhängige Post-Selection-Validierung;
- einen uncertainty-aware Tau-Entscheid.

Die dokumentierten Gegenbeispiele widersprechen daher keinem vorhandenen
roten Vertrag; sie markieren fehlende Verträge.

## Empfohlene Implementierungsreihenfolge für Claude

1. **Releasegate:** Recurring Goal CRUD in React, neue Goal-Schedule-Evidence,
   vergangene aktive Goals und grüne Probability-Freigaben ohne Validation
   für reale Mandate fail-closed halten.
2. **Rote Tests zuerst:** Alle sieben Reproduktionen und Pflichtinvarianten
   materialisieren, bevor Produktlogik geändert wird.
3. **Owner-ADR Time/Lifecycle:** Valuation-Date, Bucketgrenzen, End-Inklusivität,
   Overdue-Semantik und Lifecycle-Transitionen festlegen.
4. **Kanonischer Resolver:** `GoalLifecycleSnapshot` plus
   `OccurrenceSchedule` aus Rohgoal, Valuation-Date und Resolverversion
   erzeugen; Hash und Reconciliation bereitstellen.
5. **Scheduler vereinheitlichen:** Goal-Liability, Cashflow-Timeline,
   Reporting-MC, Reserve und Sensitivity auf denselben Schedule umstellen.
6. **React Contract:** diskriminierte Union und vollständigen Roundtrip
   implementieren; gegen echten Backendvalidator testen.
7. **Funding-Ledger aus Runde 37:** `amount_due` aus dem neuen Schedule in die
   versionierte Funding-Policy einspeisen.
8. **Train/Validation-Vertrag:** unabhängigen Validation-Cube,
   uncertainty-aware Verdict und persistierte Evidence implementieren.
9. **Publikation:** Lifecycle, Schedule-Scope, Estimate, Intervall und
   Reliability in API, Classic, React, PDF, Signatur und Handoff angleichen.
10. **Legacy:** alte Goal- und Probability-Evidence replayen oder als
    `schedule_unknown`, `lifecycle_unknown` beziehungsweise
    `validation_unknown` quarantänisieren.
11. **Abnahme:** fokussierte und volle Backend-/React-/Electron-/PDF-/Browser-
    E2E-Suites, statistische Kalibrierung, Replay sowie Zielumgebungsgate.

## Nicht ausreichende Scheinfixes

- nur `target_amount_rappen` im React-Payload für recurring freischalten;
- nur den Backendvalidator lockern, damit der heutige React-Payload speichert;
- `full_years` um eins reduzieren, ohne echte Occurrences zu enumerieren;
- kurze Fenster pauschal anteilig proratisieren, obwohl Frequenzanker bekannt
  sind;
- vergangene Ziele generell löschen oder generell als Jahr eins behandeln;
- nur UI-Status `past` ändern, während der Optimizer weiter Zukunftszahlungen
  erzeugt;
- überall `ceil(days/365)` verwenden;
- nur `base_calendar_year` speichern, aber nicht den vollständigen
  Bewertungsstichtag und die Bucketkonvention;
- `n_paths` erhöhen, aber Gewinner und Zertifizierung weiter auf demselben
  Sample bestimmen;
- einen zweiten Seed rechnen und bei schlechtem Ergebnis wieder optimieren,
  bis ein grüner Seed erscheint;
- ein naives Binomial-Wilson-Intervall auf abhängige antithetische oder
  selbstnormalisiert gewichtete Pfade anwenden;
- Holdout-Evidence publizieren, aber weiterhin eine falsch attribuierte
  Aggregate-Goal-Probability als individuell bezeichnen;
- grüne Unit-Tests mit vollständig gemocktem API als E2E-Nachweis werten.

## Definition of Done

- [ ] Recurring/Pension Create und No-op-Edit funktionieren in React und Classic gegen das echte Backend.
- [ ] Betrag, Start, Ende, ongoing und Frequenz roundtrippen verlustfrei.
- [ ] Ein kanonischer Occurrence-Scheduler speist alle Engine-Consumer.
- [ ] Bucket-Summen reconciliieren exakt zu den Occurrences.
- [ ] Kein Goal erzeugt eine Fälligkeit nach seinem Enddatum.
- [ ] Vergangene Ziele besitzen einen expliziten Lifecycle und Outstanding-Vertrag.
- [ ] Kein vergangenes Ziel wird still als normales Jahr eins reaktiviert.
- [ ] Jeder Run bindet vollständiges `valuation_date`, Zeitzone und Bucketversion.
- [ ] Router, Optimizer, Reporting und UI lösen jedes Datum identisch auf.
- [ ] Replay bleibt über Kalendertage bytegleich.
- [ ] Training und finale Probability-Zertifizierung verwenden unabhängige Evidence.
- [ ] `erreichbar` verlangt einen estimatorgerechten Lower Bound über Tau.
- [ ] Unsichere Boundary-Fälle besitzen einen eigenen sichtbaren Zustand.
- [ ] Train-/Validation-/Schedule-/Lifecycle-Evidence ist gehasht und persistiert.
- [ ] Funding-Ledger verwendet den kanonischen `amount_due`.
- [ ] API, Classic, React, PDF, Signatur und Handoff sind semantisch identisch.
- [ ] Legacy-Evidence ist replayed oder sichtbar quarantänisiert.
- [ ] Alle Negativ-, Invarianten-, Kalibrierungs-, Replay- und E2E-Tests sind grün.
- [ ] Releasegate wird erst nach dokumentierter Zielumgebungsabnahme geöffnet.

## Abschlussurteil

Claude hat wichtige Fail-closed-Validierungen, kalendergenaue Helper,
Occurrence-Logik für allgemeine Cashflows, CRN-Vergleich und post-rounding
Reevaluation bereits als gute Bausteine umgesetzt. Die Kernverträge sind aber
noch nicht verbunden:

- der React-Editor erzeugt keinen gültigen recurring Goal-Payload;
- Goal-Liability und Reporting-MC verwenden nicht den vorhandenen
  Occurrence-Scheduler;
- vergangene Ziele besitzen keinen wirtschaftlichen Lifecycle;
- Bewertungsstichtag und Kalenderarithmetik sind nicht kanalgleich gebunden;
- die auf dem Trainingswürfel ausgewählte Allokation zertifiziert sich auf
  demselben Würfel selbst.

Die fünf neuen P1 sind reproduziert, produktionsrelevant und durch 279 grüne
fokussierte Bestandstests nicht abgedeckt. Reale recurring Goal CRUD,
Schedule-/Overdue-Evidence und grüne Goal-Probability-Claims bleiben bis zur
vollständigen Umsetzung des Reparaturvertrags gesperrt.
