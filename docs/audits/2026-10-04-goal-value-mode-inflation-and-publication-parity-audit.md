---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-goal-value-mode-real-spending-inflation-and-publication-parity-followup-audit"
status_as_of: "2026-10-04"
audit_started_on: "2026-10-04"
audit_completed_on: "2026-10-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "d9bc963298c0bdaf9d487121a995ecc9a284a4fc"
prior_goal_timing_audit_path: "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
prior_goal_publication_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
prior_engine_validation_path: "docs/audits/2026-06-11-engine-validation-findings.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md"
audit_mode: "read_only_static_cross_channel_review_plus_deterministic_production_function_and_payload_reproductions_and_focused_backend_react_tests"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "goal value-mode CRUD in React and Classic, real spending inflation in optimizer, reserve, deterministic goal analysis and general Monte Carlo, immutable run evidence, advisory and PDF publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 3
deterministic_reproduction_groups: 2
focused_backend_tests_passed: 291
focused_react_tests_passed: 43
focused_existing_tests_passed_total: 334
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "keep real-value spending CRUD and every affected allocation, goal-probability and publication claim blocked; first materialize the documented failing cross-channel tests, then preserve value_mode losslessly and introduce one versioned resolved goal schedule/effective-target contract consumed and persisted by all engines and publication channels"
---

# Goal-Value-Mode-, Inflations- und Publikationsparitäts-Audit

## Geltung, Quellenrangfolge und Abgrenzung

Dieser additive Folgeaudit dokumentiert die neununddreißigste Read-only-
Kontrollrunde des Asset-Allocation-/Stochastic-Core. Geprüft wurde der
unveränderte Repository-Head
`d9bc963298c0bdaf9d487121a995ecc9a284a4fc`. Produktcode, Migrationen und
Tests wurden nicht verändert. Nach der Prüfung werden ausschließlich die fünf
Pfade des Dokumentationsmanifests angepasst.

Aktueller Code, reale Payload-Transformationen und direkt ausgeführte
Produktionsfunktionen haben Vorrang. Grüne Bestandstests belegen nur ihre
vorhandenen Assertions. Insbesondere widerlegt ein grüner UI-Test keine
semantische Mutation, wenn er `value_mode="real"` für Ausgabenziele nie
prüft; ein grüner Engine-Test widerlegt keine Cross-Consumer-Divergenz, wenn
er nur den Optimizer oder nur den Reportingpfad betrachtet.

Die Runde beantwortet drei eng verbundene Kernfragen:

1. Bleibt `value_mode="real"` bei Anlage und No-op-Edit eines Ausgabenziels
   in React und Classic unverändert erhalten?
2. Berechnen Optimizer, Reserve, deterministische Zielanalyse und allgemeine
   Monte-Carlo-Zielauswertung aus einem realen Zahlungsziel denselben
   inflationsbereinigten Sollbetrag?
3. Kann ein nachgelagerter Empfänger aus persistierter und publizierter
   Evidence zweifelsfrei rekonstruieren, welcher Rohbetrag, CPI-Pfad,
   Fälligkeitsslot und effektive Sollbetrag bewertet wurden?

## Deduplizierung zu bestehenden Findings

Keine bestehende Finding-ID wird geschlossen oder umbenannt.

- `GOAL-RECURRING-EDITOR-CONTRACT-001` bleibt für die fehlenden Betrags- und
  Timingfelder wiederkehrender React-Ziele maßgeblich. Das neue
  `GOAL-VALUE-MODE-ROUNDTRIP-001` betrifft die eigenständige, vom Backend
  akzeptierte Mutation `real -> nominal`. Sie tritt in React bereits bei
  gültigen Einmalzielen und in Classic bei allen Ausgabenzielen auf. Bei
  recurring React-Zielen müssen beide Defekte gemeinsam repariert werden.
- `GOAL-RECURRENCE-SCHEDULE-001` betrifft Anzahl und Lage der Occurrences.
  `GOAL-REAL-SPENDING-INFLATION-PARITY-001` betrifft den Betrag jeder bereits
  ausgewählten Occurrence. Eine Occurrence-Engine ohne Wertmodus löst den
  neuen Fehler nicht.
- `GOAL-CALENDAR-HORIZON-PARITY-001` bestimmt den einheitlichen Zeitindex.
  Der neue Befund zeigt, dass Reserve und Reporting selbst bei einem
  vorgegebenen identischen Index den CPI-Faktor für Ausgabenziele gar nicht
  anwenden.
- Finding #3 im Engine-Validierungsdokument vom 11./12.06.2026 bleibt der
  bekannte Ein-Term-Versatz zwischen Begin-of-Year-Cashflow und
  End-of-Year-Liability. Dieser Audit dupliziert ihn nicht: Neu ist die
  vollständige Inflationsauslassung in Reserve, deterministischer Analyse und
  allgemeinem MC. Die Reparatur muss beide Ursachen in einem expliziten
  Timingvertrag auflösen.
- `GOAL-SNAPSHOT-001`, `GOAL-PUBLICATION-001` und `REP-001` bleiben für
  unveränderliche Goal-Evidence und kanalgleiche Publikation offen. Die hier
  nachgewiesenen fehlenden Effective-Target-Felder und der tote
  `goal_analysis_json`-PDF-Pfad sind konkrete Erweiterungen dieser IDs, keine
  neuen Root-Cause-IDs.
- Funding-, Prioritäts-, Conditional-Probability- und Attributionsfindings
  bleiben orthogonal: Sie setzen voraus, dass der fällige Betrag zuvor
  korrekt aufgelöst wurde.

Zwei neue IDs grenzen die neuen Ursachen präzise ab:

- `GOAL-VALUE-MODE-ROUNDTRIP-001`
- `GOAL-REAL-SPENDING-INFLATION-PARITY-001`

## Kurzurteil

Die Runde bestätigt **zwei neue release-blockierende P1**.

**`GOAL-VALUE-MODE-ROUNDTRIP-001`:** Backend, Datenmodell, Domainvalidator,
Produktionsfixture und Optimizer behandeln `real` ausdrücklich als gültigen
Wertmodus für Ausgabenziele. Der produktive React-Payload-Builder überschreibt
ihn dagegen für jeden Nicht-Vermögenszieltyp mit `nominal`; die Oberfläche
zeigt die Auswahl nur für Vermögensziele. Ein reales, backendgültiges
Einmalziel wird beim No-op-Speichern mit HTTP 200 als nominal persistiert. Der
Classic-Editor lädt den realen Radiowert kurz, setzt ihn beim Typ-Sync aktiv
auf nominal zurück, hardcodiert beim Speichern erneut nominal und verschweigt
den Modus in Listen und Strategietext. Damit ändert ein inhaltlicher No-op die
Kaufkraftsemantik eines Kundenbedarfs. Bei recurring React-Zielen blockiert
der bereits dokumentierte Pflichtfeldfehler aktuell vorher mit HTTP 422; die
Wertmodusmutation liegt trotzdem im gemeinsamen Builder und wird nach dessen
Reparatur unmittelbar wirksam, falls sie nicht zugleich behoben wird.

**`GOAL-REAL-SPENDING-INFLATION-PARITY-001`:** Der Optimizer erhöht reale
Einmal- und recurring Ausgaben je Zieljahr anhand der Inflationsserie.
Reserve, deterministische Zielanalyse und allgemeine Monte-Carlo-
Zielauswertung verwenden dagegen den unveränderten Rohbetrag; nur
Vermögensziele werden dort inflationiert. In der direkten Produktionsfunktions-
Gegenprobe wird ein reales Einmalziel von 10.000 Rappen nach zwei Jahren bei
zweimal 10 Prozent Inflation im Optimizer mit 12.100 Rappen bewertet und ist
bei 11.000 Rappen Vermögen `nicht_erreichbar`, Probability 0 und Penalty
640.000. Dieselbe Eingabe wird von Reserve, deterministischer Analyse und
allgemeinem MC mit 10.000 Rappen bewertet und als `On Track`, Score 100,
Success 100 Prozent und Funding Ratio 1,1 publiziert. Das ist kein
Rundungsunterschied, sondern ein widersprüchliches Entscheidungsresultat für
denselben akzeptierten Datensatz.

Die persistierte Allocation-Evidence speichert weder den effektiven
inflationsbereinigten Zielbetrag noch CPI-Faktor, Occurrence-Schedule oder
Zeit-/Inflations-Policyversion. Advisory und PDFs kombinieren gespeicherte
Probability mit aktuell gelesenen Rohzielmetadaten. Der Strategie-PDF-Loader
liest zusätzlich `TargetAllocation.goal_analysis_json`, obwohl dieses
Modelattribut nicht existiert; die SOLL-Zielanalyse bleibt dadurch leer. Diese
Belege verschärfen die bestehenden Snapshot-/Publikationsblocker.

## Reproduktion A: semantischer `real -> nominal`-No-op

### Backendvertrag

Der Backendvertrag unterstützt den Wertmodus ausdrücklich:

- `schemas/wealth.py:539-579`: `GoalCreate.value_mode` ist das Literal
  `nominal | real`.
- `schemas/wealth.py:582-610`: `GoalUpdate` nimmt den Wertmodus entgegen.
- `models/wealth.py:121-153`: `Goal.value_mode` wird persistent gespeichert.
- `services/goal_semantics.py:150-180`: Der Validator akzeptiert genau
  `nominal` und `real`; die Ausgabenzweige verbieten `real` nicht.
- `routers/wealth.py:205-339` und `817-853`: Complete-State-Validierung,
  Normalisierung und PUT übernehmen den Wert.
- `services/foundation_example.py:603-621`: Die produktive Foundation-Fixture
  enthält eine reale `Pensionsausgabe`.
- `tests/test_goal_cashflow_ist_contract.py:201-224`: Der reale
  Backend-POST-Vertrag erwartet HTTP 201.
- `tests/test_optimizer_goal_liabilities.py:309-321` und `368-388`: Reale
  Einmal- und Pensionsausgaben werden bewusst inflationiert.

Damit ist die stärkste aus dem aktuellen Code ableitbare Fachentscheidung:
`real` ist für Ausgabenziele unterstützt. Wollte der Product Owner das ändern,
müssten Backend, Optimizer, Fixtures und Bestandsdaten fail-closed migriert
werden. Eine stille UI-Konvertierung wäre in keinem Fall zulässig.

### React

Die produktive Transformation liegt in
`reporting/src/lib/goalForm.ts:175-210`:

- Der Kommentar an Zeile 177 beschränkt `value_mode` auf Vermögensziele.
- Zeile 194 setzt jeden anderen Zieltyp hart auf `nominal`.
- Zeile 199 nullt zusätzlich recurring Beträge; dieser Teil gehört zum
  bereits dokumentierten Editorfinding.
- `GoalWizard.tsx:86-109` lädt den gespeicherten Wert korrekt in den State.
- `GoalWizard.tsx:112-144` reicht ihn an den Builder weiter.
- `GoalWizard.tsx:346-368` rendert die Auswahl jedoch nur unter `isWealth`.
- `GoalsEditor.tsx:19-30,129-150` zeigt CHF-Werte ohne Wertmodusmarker.
- Der generische API-Typ in `api/types.ts:867-910` erlaubt beide Werte; die
  API-Schicht ist nicht die Ursache.

Die direkt gegen die transpilierten Produktionsfunktionen ausgeführte Matrix
ergab:

```json
{"goal_type":"Einmalige_Ausgabe","input_value_mode":"real","output_value_mode":"nominal","output_amount":10000,"output_start":"2030-01-01"}
{"goal_type":"Wiederkehrende_Ausgabe","input_value_mode":"real","output_value_mode":"nominal","output_amount":null,"output_start":"2029-01-01"}
{"goal_type":"Pensionsausgabe","input_value_mode":"real","output_value_mode":"nominal","output_amount":null,"output_start":"2029-01-01"}
```

Der resultierende gültige Einmalziel-Payload wurde danach durch das echte
Backend-Schema und `_normalize_goal_payload()` geführt:

```text
accepted=True
status_equivalent=200
persisted_value_mode=nominal
persisted_target_amount_rappen=10000
```

Das ist eine aktuell erreichbare stille Datenmutation. Die 43 grünen
fokussierten React-Tests prüfen diese Matrix nicht; `goalForm.test.ts:122-137`
testet den Wertmodus ausdrücklich nur für Vermögensziele.

### Classic

Der Classic-Pfad bestätigt dieselbe Ursache unabhängig:

- `5eyes_v2.html:26288-26295`: `GOAL_TYPE_FIELDS` aktiviert Wertmodus nur bei
  Vermögenszielen.
- `26422-26473`: Der Sync blendet ihn für Ausgaben aus und prüft aktiv
  `nominal`.
- `26570-26606`: Der Editor lädt den gespeicherten realen Wert und überschreibt
  ihn anschließend durch den Sync.
- `26721-26812`: Speichern hardcodiert für Nicht-Vermögensziele `nominal`,
  erhält aber deren Betrag und Timing; hier akzeptiert das Backend die stille
  Mutation für Einmal- **und** recurring Ausgaben.
- `26255-26256`, `26392` und `26929-26932`: Listen und Strategietext zeigen
  `(real)` ebenfalls nur für Vermögensziele und machen die Mutation unsichtbar.

## Reproduktion B: Optimizer rot, Reporting grün

### Vier unterschiedliche Verbraucher

1. **Optimizer:** `services/optimizer/goal_liabilities.py:273-284` definiert
   CPI-Aufzinsung und Realmodus. Vermögensziele nutzen sie in `324-336`,
   Einmalziele in `388-403` und recurring/Pensionsziele pro Jahr in
   `428-460`.
2. **Reserve:** `services/portfolio_engine_reserve.py:236-282` annualisiert
   beziehungsweise übernimmt den Rohbetrag in `264-268`, ohne `value_mode`
   oder Inflationsserie. Auch die zusätzliche Reserveschleife `371-393`
   bleibt nominal.
3. **Deterministische Analyse:**
   `services/portfolio_engine_payload.py:325-340` besitzt zwar einen
   Inflationshelfer, ruft ihn aber nur für Vermögensziele. Spending verwendet
   in `573` Roh-/Jahresbetrag und in `584-596` die rohe Reserve. Der Output
   nennt in `612` zwar `value_mode`, publiziert in `616` aber den nicht
   inflationierten `target_amount_rappen`.
4. **Allgemeiner MC:**
   `services/portfolio_engine_mc_simulation.py:844-1111` erhält die
   Inflationsserie, nutzt sie für Spending in `917-970` jedoch nicht. Nur der
   Vermögenszweig `978-983` löst ein inflationsbereinigtes Target auf. Der
   Return-Payload `1097-1111` enthält weder effektiven Sollbetrag noch Modus,
   Faktor, Schedule oder Policyhash.

### Deterministische Gegenprobe

Eingabe:

- `Einmalige_Ausgabe`, `value_mode="real"`
- Rohbetrag 10.000 Rappen
- Fälligkeit in Jahr zwei
- Inflationsserie `[1000, 1000]` bps
- Vermögen 11.000 Rappen
- flache Bruttorenditefaktoren 1 und keine weiteren Cashflows

Ausgeführt wurden die echten Produktionshelfer `goal_to_liability`,
`simulate_wealth_paths`, `chance_constraint_penalty`,
`_goal_reserve_for_goal`, `_build_goal_analysis` und
`_monte_carlo_goal_summary`. Ergebnis:

```json
{
  "optimizer_target": 12100,
  "optimizer_path": [0, 12100],
  "optimizer_wealth": [11000, 11000, -1100],
  "optimizer_probability": 0.0,
  "optimizer_status": "nicht_erreichbar",
  "optimizer_penalty": 640000.0,
  "reserve_target": 10000,
  "deterministic_target": 10000,
  "deterministic_status": "On Track",
  "deterministic_score": 100,
  "mc_code_target": 10000,
  "mc_success_pct": 100,
  "mc_funded_ratio": 1.1,
  "mc_shortfall": 0,
  "mc_score": 100,
  "mc_has_target_evidence": false
}
```

Der Unterschied entspricht exakt `10.000 * 1,10 * 1,10 = 12.100`; er ist
nicht durch Stochastik, Zufallssamen, Conditional Probability oder Rundung
erklärbar.

## Persistenz- und Publikationsbefund

### Snapshot bindet Rohinput, nicht die aufgelöste Verpflichtung

- `_projection_context_snapshot()` in
  `services/portfolio_engine.py:2237-2329` bindet die Inflationsserie, aber
  keinen expliziten Bewertungsstichtag.
- `_compute_input_snapshot_hash()` in `2332-2542` bindet seit v4 den rohen
  Wertmodus und die rohen Goal-Felder. Nicht gebunden sind aufgelöster
  Zielindex, Occurrence-Schedule, CPI-Termfolge/-faktor, effektiver Sollbetrag
  und Timing-/Inflations-Policyversion.
- `services/optimizer/objective.py:397-405` persistiert pro Goal nur ID,
  Label, Target-Kind, Probability, Tau, Status und Härte.
- `models/allocation.py:42-139` besitzt `goal_achievability_json`, aber keinen
  unveränderlichen `ResolvedGoalSchedule` oder `EffectiveGoalTarget`.
- Der Allocation-Context-Hash in `portfolio_engine.py:3969-3988` bindet den
  Inputhash und die Modellbasis, aber nicht den vollständigen Goal-Analysis-
  oder MC-Summary-Payload.

Damit kann ein Empfänger beweisen, welcher Rohinput ungefähr vorlag, aber
nicht, welcher konkrete CHF-Betrag an welcher Stelle tatsächlich die
Entscheidung ausgelöst hat.

### Publikation kombiniert gespeicherte Probability mit aktuellem Rohziel

- `services/advisory_report.py:1964-2055` liest gespeicherte
  `goal_achievability_json`-Wahrscheinlichkeiten, ergänzt Zielbetrag und
  Metadaten aber aus dem aktuellen Goal-Datensatz. `value_mode`, CPI-Faktor und
  effektiver Sollbetrag fehlen.
- `reporting/src/api/types.ts:360-370` typisiert die publizierte Goal-Zeile ohne
  diese Evidence; `pages/Goals.tsx:164-182` zeigt den Rohbetrag zusammen mit
  Probability/Status.
- `services/pdf/documents/advisory_report.py:1376-1424` zeigt dieselbe rohe
  Zielspalte neben gespeicherter Wahrscheinlichkeit.
- `routers/pdf_reports.py:632-683` liest für den Strategie-PDF Goal-Metadaten
  ohne Wertmodus. Anschließend wird an Zeile 670
  `getattr(ta_obj, "goal_analysis_json", None)` abgefragt.
- `TargetAllocation` hat dieses Attribut nicht. Daher bleibt die Liste leer;
  `services/pdf/documents/anlagestrategie.py:585-600` publiziert
  "Noch keine Zielerreichungsanalyse gespeichert" und überspringt den
  SOLL-/IST-Zielvergleich, obwohl ein Live-Engine-Payload verfügbar ist.

Der letzte Punkt ist ein konkreter Implementierungsdefekt, wird aber wegen
gleicher Ursache und Wirkung unter `REP-001`/`GOAL-PUBLICATION-001` geführt:
persistierte und dargestellte Decision-Evidence ist nicht kanalgleich und
nicht vollständig gebunden.

## Root Cause

Es gibt keinen gemeinsamen fachlichen Datentyp zwischen Goal-CRUD,
Scheduler, Optimizer, Reserve, Reporting-MC und Publikation.

`Goal` ist zugleich Benutzereingabe und implizite Berechnungsanweisung.
Jeder Verbraucher interpretiert Typ, Wertmodus, Datum, Frequenz, Inflation und
Probability selbst. Der Optimizer besitzt die vollständigste Inflationierung,
die übrigen Verbraucher rekonstruieren vereinfachte Rohziele. Persistiert wird
anschließend eine Probability ohne den exakt bewerteten Verpflichtungspfad.
Die UIs besitzen nochmals eigene typabhängige Feldmatrizen und überschreiben
einen vom Backend unterstützten Wert.

Lokale Einzelpatches – etwa nur das React-Radio sichtbar zu machen oder nur
im MC `target *= inflation` einzufügen – würden den Vertrag weiter
fragmentieren und den bekannten Ein-Term-/Kalenderfehler konservieren.

## Verbindlicher Lösungsweg für Claude

### 1. Fachentscheidung explizit machen

Eine kurze Owner-ADR muss festlegen:

- `nominal`: der gespeicherte CHF-Betrag ist der fällige nominale Betrag.
- `real`: der gespeicherte CHF-Betrag ist Kaufkraft am gebundenen
  Bewertungsstichtag und wird bis zur jeweiligen Fälligkeit mit der
  gebundenen CPI-Termfolge aufgezinst.
- Begin-/End-of-Year- und Stichtagskonvention werden gemeinsam mit dem offenen
  Finding #3 und `GOAL-CALENDAR-HORIZON-PARITY-001` entschieden.
- Rundung erfolgt genau einmal pro Occurrence nach einer versionierten Regel.

### 2. Diskriminierten CRUD-Vertrag reparieren

- Wertmodus für Vermögens- **und** Ausgabenziele zulassen und anzeigen;
  Rendite-/Maximierungsziele dürfen ihn nicht semantisch vortäuschen.
- React: `buildGoalPayload` darf Ausgabenziele nicht auf nominal setzen;
  Wizard und Liste müssen den Modus rendern. Die recurring Pflichtfelder aus
  Runde 38 gleichzeitig ergänzen.
- Classic: Feldmatrix, Sync, Save und Darstellung müssen real verlustfrei
  roundtrippen; keine versteckte Radio-Rücksetzung.
- `GoalUpdate.value_mode` als Literal typisieren. Omission in einem echten
  Partial Update muss den Bestandswert erhalten; explizit ungültige Werte
  müssen 422 ergeben.
- Nach Wertmodusänderung sind alle abgeleiteten Goal-, MC-, Allocation- und
  Publikationsevidenzen stale und dürfen nicht weiter als aktuell erscheinen.

### 3. Einen kanonischen aufgelösten Zielplan einführen

Ein versionierter, unveränderlicher `ResolvedGoalSchedule` beziehungsweise
`EffectiveGoalTarget` muss mindestens enthalten:

- Goal-ID und rohe Goal-Version/hash,
- `valuation_date`, Basiswährung und Zieltyp,
- Rohbetrag und `value_mode`,
- je Occurrence Fälligkeitsdatum, zentralen Pfadindex und Rohbetrag,
- verwendete CPI-Terme, kumulativen Faktor und effektiven nominalen Betrag,
- Conditional-Probability-Basis getrennt vom ungewichteten Sollbetrag,
- Summen/Reconciliation, Rundungsregel sowie Scheduler-, Timing- und
  Inflations-Policyversion.

Dieser Plan wird einmal erzeugt und unverändert von Optimizer, Reserve,
deterministischer Analyse, allgemeinem MC, Sensitivity und Publikation
verwendet. Keine Schicht darf Zielbetrag oder Zieljahr erneut aus `Goal`
ableiten.

### 4. Invarianten und Persistenz

Mindestens folgende Gleichheiten müssen technisch geprüft werden:

```text
sum(effective occurrence amounts)
  == sum(optimizer liability path)
  == reporting cumulative target basis

effective amount at goal index
  == reserve basis before separate reserve policy
  == deterministic target basis
  == MC target basis
```

Der vollständige Plan oder ein kanonischer Hash plus ausreichend eingebettete
Summary-Evidence wird an OptimizerRun, TargetAllocation, Model-Basis,
Input-/Allocation-Context, Sensitivity, Advisory, UI, PDFs, Signatur und
Handoff gebunden. Publikation darf Probability/Status nicht mit später
gelesenen unversionierten Goal-Metadaten zusammenfügen.

### 5. PDF-Pfad korrigieren

- Entweder ein echtes, migrations- und hashgebundenes Goal-Analysis-Snapshot
  auf der Allocation persistieren oder ausschließlich einen nachweislich zur
  Allocation gehörenden Run-Snapshot verwenden.
- Den nicht existierenden `goal_analysis_json`-Read entfernen.
- Kein stiller Empty-State bei vorhandener, aber ungebundener Evidence:
  fail-closed und sichtbar `nicht verifizierbar`.
- Zieltabellen zeigen mindestens Wertmodus, Rohbetrag, effektiven Betrag,
  Stichtag/Fälligkeit sowie Evidence-Version; Soll-/Ist-Vergleich verwendet
  dieselbe gebundene Analyse.

## Zuerst zu materialisierende rote Tests

### CRUD und UI

1. Matrix aller Goaltypen × `nominal|real` für POST, PUT, No-op, Reload.
2. Reales Einmalziel bleibt nach React-Speichern real und HTTP 200.
3. Reale recurring/Pensionsziele bleiben nach der Runde-38-Reparatur mitsamt
   Betrag, Start, Ende, ongoing, Frequenz und Wertmodus identisch.
4. Classic-Browser-E2E für Öffnen/Speichern ohne Änderung und sichtbaren
   `REAL`-/Kaufkraftmarker.
5. React-/Classic-Payload-Parität gegen echten Backend-Complete-State-Guard.
6. Ungültiger Enum-Wert ergibt 422; ausgelassener Partial-Update-Wert bleibt
   unverändert.
7. Foundation-Fixture mit realer Pension ist in beiden Editoren ohne
   Mutation bearbeitbar.

### Rechenkern

8. Nominal/real für Einmal-, endliche recurring-, ongoing- und
   Pensionsziele bei variabler Inflationsserie.
9. Zero-Inflation-Invariante: nominal und real sind betragsgleich.
10. Scheduler-/Optimizer-/Reserve-/Deterministik-/MC-Reconciliation je
    Occurrence und kumulativ.
11. Exakter Status-Flip aus der 10.000/12.100/11.000-Gegenprobe.
12. Horizontgrenzen, vergangene/überfällige Ziele und Schaltjahre auf dem
    gemeinsamen `TemporalContext`.
13. Regression für den offenen Ein-Term-Versatz mit der owner-freigegebenen
    Begin-/End-of-Year-Konvention.
14. Sensitivity ändert Inflation oder Timing nur über einen neuen gebundenen
    Plan und kann keine alte Evidence weiterverwenden.

### Evidence und Publikation

15. Jede Probability ist an Goal-Snapshot, Planhash, effektiven Sollbetrag,
    CPI-/Timingversion und Stichtag gebunden.
16. Mutation von Goal, CPI-Serie oder Stichtag invalidiert Run/Allocation/
    PDF/Signatur reproduzierbar.
17. Advisory, React, Classic, Strategie-PDF und Beratungs-PDF zeigen dieselbe
    Roh-/Effektivbasis und denselben Status.
18. Fehlender/mismatched Planhash blockiert statt Rohdaten und alte
    Probability zu vermischen.
19. Strategie-PDF enthält bei vorhandener gebundener Analyse den
    Zielvergleich; der tote `goal_analysis_json`-Fallback ist nicht mehr
    erreichbar.

## Verifikation dieser Audit-Runde

### Fokussierter Backend-Bestandsgate

Ausgeführt:

```powershell
python -m pytest -q --basetemp ..\.pytest_tmp_round39 `
  tests/test_optimizer_goal_liabilities.py `
  tests/test_goal_scoring_horizon.py `
  tests/test_goal_scope_gesamtvermoegen.py `
  tests/test_goals_conditional_probability_mc_path.py `
  tests/test_goals1_ahv_mc_path_consistency.py `
  tests/test_goal_cashflow_ist_contract.py `
  tests/test_goal_domain_fail_closed_contracts.py `
  tests/test_goal_schema_field_isolation.py `
  tests/test_audit_z6_anchors.py `
  tests/test_current_goal_analysis_contract.py `
  tests/test_advisory_report.py `
  tests/pdf/test_goal_achievability_component.py `
  tests/pdf/test_anlagestrategie_goal_achievability.py `
  tests/pdf/test_goal_achievability_table.py
```

Ergebnis: **291 passed**, 0 failed, 145,45 Sekunden.

### Fokussierter React-Bestandsgate

Ausgeführt:

```powershell
npm.cmd test -- `
  src/lib/goalForm.test.ts `
  src/sections/goals/GoalWizard.test.tsx `
  src/sections/goals/GoalsEditor.test.tsx `
  src/sections/goals/GoalsEditor.a11y.test.tsx `
  src/api/goals.test.ts
```

Ergebnis: **5 Testdateien, 43 Tests passed**, 0 failed.

Die zusammen **334 grünen Bestandstests** enthalten weder die
`real -> nominal`-No-op-Matrix noch die Optimizer/Reserve/Deterministik/MC-
Statusflip-Reconciliation. Sie sind daher ein Regression-Bestandsgate, kein
Gegenbeweis gegen die Findings.

Nicht ausgeführt wurden vollständige Backend-/Frontend-Suites, echte Browser-
E2E, Electron-Packaging, PDF-Pixelvergleich, PostgreSQL-/Multiworker-Tests und
Zielumgebungs-Replay. Diese gehören zur Implementierungsabnahme, nicht zum
Read-only-Nachweis der beiden Root Causes.

## Definition of Done

Der Release-Hold für diese Runde kann erst aufgehoben werden, wenn:

1. beide neuen Finding-IDs durch rote Vorher-/grüne Nachher-Tests geschlossen
   sind;
2. Wertmodus und alle recurring Pflichtfelder in React, Classic und API
   verlustfrei roundtrippen;
3. genau ein versionierter aufgelöster Zielplan alle Rechenverbraucher
   speist;
4. der offene Ein-Term-/Kalendervertrag gemeinsam und nicht widersprüchlich
   entschieden ist;
5. Optimizer, Reserve, Deterministik und MC dieselben effektiven Beträge und
   bei identischer Wealth-Evidence dieselben Statusgrundlagen verwenden;
6. Run, Allocation, Sensitivity und Publikation den Plan unveränderlich und
   hashprüfbar binden;
7. alle UI-/PDF-/Signatur-/Handoff-Kanäle dieselbe nachvollziehbare Evidence
   zeigen oder bei fehlender Bindung fail-closed sperren;
8. Legacy-Evidence replayt oder sichtbar als nicht verifizierbar
   quarantänisiert ist; und
9. fokussierte, vollständige, Browser-, Electron-, PDF- und Zielumgebungs-
   Abnahmen grün sind.

## Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen durch die Runde verändert werden:

1. `docs/audits/2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`
