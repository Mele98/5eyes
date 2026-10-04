# Risikobudget-Fallback-, Context- und Finalisierungs-Integritätsaudit

**Kontrollrunde 43 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Der House-Modus darf nach dem bewusst gewählten Best-Effort-Vertrag aus Juni
bei einem strukturell unerreichbaren Risikobudget die konservativste
erreichbare Allocation erzeugen und den Berater warnen. Dieser Vertrag ist
nicht der neue Befund.

Die aktuelle Implementierung verletzt jedoch zwei davon unabhängige
Integritätsgrenzen:

1. Ein solcher House-Fallback wird mit `optimization_method =
   fallback_house_matrix` persistiert, während seine gehashte
   `optimization_model_basis.active_method` weiterhin `house_matrix` lautet.
   Der erfolgreiche Generate erzeugt damit eine moderne, als current gesetzte
   TargetAllocation, die der eigene Reload-/Recommendation-/Finalize-Pfad
   unmittelbar danach als nicht integer zurückweist.
2. Wird ausschließlich dieser Metadatenwiderspruch konsistent repariert und
   der Context korrekt neu gehasht, finalisiert der Server dieselbe Allocation
   trotz 5.627 bp Risky Fraction bei nur 100 bp Risikobudget. Der vorhandene
   Mandate-Lock erkennt die Verletzung korrekt, ist aber ausdrücklich
   read-only und wird vom Finalisierungs-Gate nicht konsumiert.

Zusätzlich enthält die Generate-Antwort im strukturell unerreichbaren Pfad
zweimal dieselbe `WARN_FALLBACK`-Warnung.

Damit ist weder „Generate erfolgreich“ noch ein grüner bestehender
Finalisierungstest ein Freigabenachweis. Reale Beratung, Finalisierung, PDF,
Signatur und Handoff bleiben für diesen Pfad gesperrt.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
a8cdf9c8c5ffd07c66bae149761fdb4aa57751d7
docs(audit): document policy constraint integrity gaps
```

Geprüft wurden insbesondere:

- House-Risikobudget-Enforcement und Best-Effort-Cascade;
- Persistenz von Optimizer-Methode, Status und immutable Model Basis;
- Hash- und Reload-Verifikation moderner Allocation-Contexts;
- Recommendation-Generate und Recommendation-Finalisierung;
- read-only Mandate-Lock und Advisory-Consumer;
- Warnungsbildung und angrenzende Regressionstests;
- historische Befunde `#AA-1`, `#AA-3` und `SIGN-ELIGIBILITY-001`.

Nicht verändert wurden Produktionscode, Schemas, Migrationen, Seed-Daten,
Tests oder UI. Die gezielte Probe war temporär und wurde nach der Beweissicherung
entfernt.

## Abgrenzung zu bestehenden Befunden

### Kein Wiederöffnen von `#AA-1`

Der Audit vom 11.06.2026 dokumentiert ausdrücklich die damalige
Designentscheidung:

- sub-allocation-gewichtetes Risikomaß;
- `_enforce_risk_budget(..., allow_best_effort=True)` in der letzten
  House-Eskalationsstufe;
- konservativste erreichbare Allocation plus Compliance-Warnung statt HTTP
  500, falls Pflichtbänder und Building Blocks das Budget strukturell
  unerreichbar machen.

Dieser Audit beanstandet **nicht**, dass der House-Modus überhaupt eine
Best-Effort-Allocation erzeugt. Beanstandet werden:

- die danach widersprüchlich persistierte, nicht reloadbare Evidence;
- die fehlende serverseitige Releaseentscheidung für eine erkannte
  Budgetverletzung;
- die doppelte identische Warnung.

`#AA-1` und `#AA-3` bleiben bezüglich ihrer damaligen Fehlerursachen geschlossen.

### Beziehung zu `SIGN-ELIGIBILITY-001`

Der Signatur-/Publikationsaudit vom 03.09.2026 hält bereits fest, dass `Final`
nicht vollständig an fachliche Freigabeevidence gebunden ist. Der hier
reproduzierte Risikobudgetfall ist eine konkrete, ausführbare Erweiterung
dieser allgemeinen Eligibility-Lücke. Er erhält eine eigene technische ID,
damit Claude den roten Regressionstest und den zentralen Gate-Vertrag ohne
Verwechslung mit Signatur-, Kosten- oder Suitability-Evidence schließen kann.

## Stabiles Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `RISK-FALLBACK-CONTEXT-001` | P1 | bestätigt | Ein echter House-Best-Effort-Fallback persistiert `fallback_house_matrix`, aber hasht eine `house_matrix`-Modellbasis. Die neue current TA ist danach in Current-Payload, Recommendation-Generate und Finalisierung nicht mehr verwendbar. |
| `RISK-BUDGET-FINALIZATION-001` | P1 | bestätigt; konkrete Erweiterung von `SIGN-ELIGIBILITY-001` | Nach ausschließlicher Konsistenzreparatur des modernen Contexts setzt die Finalisierung denselben Run trotz `5627 > 100` auf `Final`. Der bestehende `risk_budget_violated`-Lock wird nicht als serverseitiger Gate verwendet. |
| `RISK-FALLBACK-WARNING-001` | P2 | bestätigt | Der strukturell unerreichbare House-Pfad hängt dasselbe `WARN_FALLBACK`-Objekt zweimal an `warnings`. |

## End-to-End-Reproduktion

### Ausgangslage

Die Probe verwendete ausschließlich produktive ORM- und Servicepfade:

- realistisches Score-8-Mandat aus der bestehenden Test-Seed-Hilfe;
- `OPTIMIZER_MODE = house_matrix`;
- aktuelle OptimizerPolicy und aktuelle HouseMatrix;
- `HouseMatrix.max_risky_fraction_bps = 100`;
- echte `generate_target_allocation()`;
- nur der teure Reporting-Monte-Carlo wurde deterministisch kurzgeschlossen;
- echte `TargetAllocation`-, `RecommendationRun`-, Product- und Position-
  Persistenz;
- echte `finalize_recommendation()`.

Die 100 bp sind durch das öffentliche House-Matrix-Schema zulässig. Der Fall
ist deshalb kein Invalid-Input-Probe.

### Phase 1: Erfolgreicher Generate persistiert Budgetverletzung

Der produktive House-Generate lieferte:

```text
risky_fraction_bps_at_generation = 5627
risk_budget_bps_at_generation    = 100
risky_fraction_headroom_bps      = -5527
mandate_lock.is_editable         = false
mandate_lock.lock_reasons        enthält risk_budget_violated
```

Dies entspricht der historischen Best-Effort-Absicht: kein Crash, aber eine
klar erkennbare fachliche Verletzung.

### Phase 2: Der unveränderte moderne Context ist selbstwidersprüchlich

Direkt danach scheiterte die echte Finalisierung mit HTTP 422:

```text
Der verankerte Allocation-Kontext ist nicht mehr integer:
Persistierte Optimizer-Modellbasis widerspricht der aktiven
TargetAllocation-Methode.
```

Die gleiche zentrale Rekonstruktion wird vom Current-Allocation-Payload und
von `generate_recommendation_run()` verwendet. Der Schaden ist daher breiter
als der Finalize-Endpunkt:

- der Generate-Response erscheint erfolgreich;
- die neue Allocation wird current;
- der nächste Reload kann HTTP 409 liefern;
- ein neuer RecommendationRun kann nicht sauber erzeugt werden;
- ein bereits vorhandener Draft kann nicht wegen seiner echten
  Budgetverletzung, sondern wegen widersprüchlicher Provenienz finalisiert
  werden.

### Phase 3: Nur Metadatenkonsistenz repariert

Um den unabhängigen Finalisierungsvertrag zu isolieren, wurde nicht auf einen
Legacy-Pfad ausgewichen. Im weiterhin modernen Context wurden ausschließlich
die Felder korrigiert, die der Generate selbst konsistent hätte erzeugen
müssen:

```text
optimization_model_basis.active_method = fallback_house_matrix
optimization_model_basis.basis_id      = house_matrix_fallback_v1
optimization_model_basis.purpose       = controlled_fallback
```

Danach wurde der unveränderte moderne Context mit exakt derselben kanonischen
Hashstruktur wie die Produktion neu gehasht. Targets, Bounds, Risky Fraction,
Risikobudget, Sub-Allokationen, Policy, CMA, Assessment und Input Snapshot
blieben unverändert.

Ergebnis der echten Finalisierung:

```text
result_status persisted = Final
risky_fraction          = 5627
risk_budget             = 100
```

Damit ist bewiesen: Der Budgetverstoß ist selbst kein Finalisierungsfehler.
Nur der vorgelagerte, unabhängige Metadatenbug hatte ihn zufällig verdeckt.

### Phase 4: Doppelte Warnung

Die Generate-Antwort enthielt zwei byte-/feldgleiche Einträge:

```text
warnings[0].code = WARN_FALLBACK
warnings[1].code = WARN_FALLBACK
warnings[0] == warnings[1]
```

Es handelt sich nicht um zwei unterschiedliche Eskalationsursachen oder
Actions, sondern um dasselbe formatierte Message-Objekt.

## Root Cause A: Model Basis wird vor der effektiven Fallback-Provenienz gebaut

Der House-Risikopfad setzt `risk_budget_fallback = True`, sobald die erste
Budgetprüfung scheitert. Für den nicht-stochastischen Modus versucht er danach
House-Mitte, Bandrestauration, Risk-Budget-Enforcement, Liquiditäts-Caps von
3 beziehungsweise 10 Prozent und zuletzt `allow_best_effort=True`.

Nach dieser Cascade wird die Model Basis gebaut. Zu diesem Zeitpunkt gilt im
reinen House-Modus jedoch weiterhin:

```python
optimizer_mode == "house_matrix"
optimizer_result is None
allocation is None
```

`_build_allocation_model_basis()` leitet daraus korrekt für diese übergebenen
Werte ab:

```text
active_method = house_matrix
basis_id      = house_matrix_policy_v1
purpose       = allocation_selection
```

Erst später überschreibt die Persistenzvorbereitung bei
`risk_budget_fallback` den separaten Optimizer-Audit:

```python
optimization_method = "fallback_house_matrix"
optimization_status = "fallback_house_matrix"
```

`effective_constraints_json.active_method`, `.active_status` und die
typisierten TargetAllocation-Spalten übernehmen den Override. Die bereits
gebaute verschachtelte `optimization_model_basis` bleibt aber unverändert.
Alle Werte landen gemeinsam im Context-Hash. Der Hash ist kryptografisch
korrekt über einen **fachlich widersprüchlichen** Payload.

Die Reload-Verifikation vergleicht anschließend zu Recht:

- `effective_constraints.active_method` gegen `TargetAllocation.optimization_method`;
- `optimization_model_basis.active_method` gegen dieselbe Methode;
- den vollständigen kanonischen Context gegen den gespeicherten Hash.

Der zweite Vergleich deckt den Widerspruch auf. Das Problem liegt somit nicht
im Verifier, sondern in der Reihenfolge und den getrennten Sources of Truth
bei der Erzeugung.

## Root Cause B: Mandate-Lock ist Diagnose, kein Release-Gate

`audit_mandate_editability()` erkennt exakt:

```python
if risky_fraction_bps_at_generation > risk_budget_bps_at_generation:
    lock_reasons.append("risk_budget_violated")
```

Sein eigener Vertrag bezeichnet die Funktion jedoch als `non-breaking
read-only`. Der Consumer ist der Advisory-/PDF-Report. Die Funktion wird weder
von `_validate_recommendation_for_finalization()` noch vom Recommendation-
Generate als Eligibility-Gate aufgerufen.

Der Finalisierungsvalidator prüft Currentness und Bindung von Assessment,
TargetAllocation, Policy und CMA, Allocation-Context-Integrität, Positionen,
Produktaktivität, Gewichtsabstimmung und einige Warnungen. Er prüft nicht:

- `risky_fraction_bps_at_generation <= risk_budget_bps_at_generation`;
- einen degraded/false Mandate-Lock;
- einen explizit genehmigten Best-Effort-Override;
- die Bindung einer solchen Genehmigung an TA, RA, Policy, Context-Hash und
  Final-Run.

Deshalb kann ein Bericht „nicht editierbar / risk_budget_violated“ melden,
während derselbe Serverzustand dennoch `Final` wird.

## Root Cause C: Warnung wird zweimal angehängt

In der 10-Prozent-/Best-Effort-Stufe wird bereits

```python
warnings.append(format_message(WARN_FALLBACK))
```

ausgeführt. Nach Abschluss der gesamten Exception-Cascade hängt der äußere
Fallbackblock dieselbe Warnung bedingungslos nochmals an. Es gibt weder einen
Code-/Scope-Key noch eine Deduplizierung.

## Betroffene Codegrenzen

| Grenze | Relevanz |
|---|---|
| `5eyes-backend/services/portfolio_engine.py:3443-3624` | Risk-Budget-Fallback, Best-Effort und doppelter Warning-Append |
| `5eyes-backend/services/portfolio_engine.py:2552-2665` | Ableitung von `active_method`, Basis-ID und Purpose |
| `5eyes-backend/services/portfolio_engine.py:3718-3728` | Model Basis wird mit House-Modus/ohne Fallback-Methode gebaut |
| `5eyes-backend/services/portfolio_engine.py:3789-3802` | spätere separate Audit-Feld-Überschreibung |
| `5eyes-backend/services/portfolio_engine.py:3937-3988` | gemischter immutable Context und Hashbildung |
| `5eyes-backend/services/portfolio_engine.py:3990-4033` | Typisierung/Persistenz der widersprüchlichen TA |
| `5eyes-backend/services/portfolio_engine.py:4175-4364` | korrekte Reload-/Hash-/Model-Basis-Verifikation |
| `5eyes-backend/services/portfolio_engine.py:6519-6528` | Recommendation-Generate konsumiert denselben Reloadvertrag |
| `5eyes-backend/services/mandate_lock_audit.py:62-138` | korrekte, aber read-only Erkennung der Budgetverletzung |
| `5eyes-backend/routers/review.py:137-235` | Finalisierungsvalidator ohne Risk-Budget-/Lock-Gate |
| `5eyes-backend/routers/review.py:2290-2327` | atomarer Statuswechsel auf `Final` nach unvollständigem Gate |

## Verbindlicher Fixvertrag für Claude

### 1. Eine einzige Fallback-Provenienz vor Model-Basis und Hash

Vor `_build_allocation_model_basis()`, Effective-Constraints, Hash und ORM-
Persistenz muss genau ein kanonischer Zustand feststehen, zum Beispiel:

```text
active_method
active_status
active_basis_id
active_purpose
risk_budget_outcome = compliant | best_effort_unreachable | invalid
```

Alle folgenden Felder müssen ausschließlich daraus abgeleitet werden:

- `TargetAllocation.optimization_method`;
- `TargetAllocation.optimization_status`;
- `effective_constraints.active_method`;
- `effective_constraints.active_status`;
- `optimization_model_basis.active_method`;
- `optimization_model_basis.basis_id`;
- `optimization_model_basis.purpose`;
- OptimizerRun-Rolle/Methode/Status, soweit vorhanden;
- API- und PDF-Methodiklabel.

Kein später Dict-Override darf nur einen Teil dieser Evidence umetikettieren.

Für den aktuellen House-Best-Effort ist die konsistente Semantik mindestens:

```text
active_method = fallback_house_matrix
active_status = fallback_house_matrix
basis_id      = house_matrix_fallback_v1
purpose       = controlled_fallback
```

Vor `db.flush()` ist eine interne Invariante auszuführen. Bei Divergenz wird
keine neue TA current und keine alte TA superseded.

### 2. Best-Effort als explizites Outcome, nicht als implizite Warnung

Die Budgetverletzung darf nicht nur aus zwei Zahlen oder einem generischen
Warning rekonstruiert werden. Der immutable Allocation-Context benötigt ein
versioniertes Outcome mit mindestens:

- verlangtes Budget;
- erreichte Risky Fraction;
- Headroom/Überschreitung;
- `structurally_reachable`;
- aktive Bounds und risky coefficients;
- durchlaufene Eskalationsstufen;
- Grund für Unmöglichkeit;
- resultierende Eligibility;
- gegebenenfalls gebundene Override-Evidence.

`best_effort_unreachable` ist weder `converged` noch automatisch
publikationsfähig.

### 3. Zentraler serverseitiger Release-Eligibility-Gate

Eine gemeinsame pure Funktion muss mindestens vor folgenden Zustandswechseln
denselben immutable Context prüfen:

- Recommendation-Generate beziehungsweise Auswahl einer TA als
  releasefähige Basis;
- Recommendation-Finalisierung;
- finales Kunden-PDF;
- SignedPublication/Signatur;
- Portfolio-Handoff/ExecutionInstruction.

Mindestregel ohne genehmigten Override:

```text
risky_fraction_bps_at_generation <= risk_budget_bps_at_generation
```

Für moderne Allocations sind fehlende, boolesche, malformed oder außerhalb
0..10.000 liegende Werte fail-closed. Das Gate darf nicht nur den read-only
Advisory-Report oder einen Frontend-Button färben.

Die historische Best-Effort-Absicht kann dabei erhalten bleiben: Eine
Allocation- oder Recommendation-**Preview** darf als explizit
`best_effort_unreachable` beziehungsweise `Blocked` sichtbar sein. Sie darf
aber ohne gebundene Freigabeevidence nicht als releasefähig gelten, auf
`Final` wechseln oder in einen finalen Kundenkanal gelangen.

### 4. Falls Best-Effort publizierbar sein soll: echte Override-Evidence

Wenn die Fachentscheidung den Juni-Vertrag über reine Preview hinaus erhalten
will, ist kein generisches „Warnung akzeptiert“-Flag ausreichend. Erforderlich
ist ein append-only, principal- und zeitgebundener Entscheid mit mindestens:

- Mandat, Client und Tenant;
- Assessment-ID und Risk-Profile-Version;
- TargetAllocation-ID und Allocation-Context-Hash;
- Policy-/CMA-ID;
- verlangtes und effektives Risiko;
- strukturierter Unmöglichkeitsgrund;
- dokumentierte Alternativen/Reassessment;
- Entscheiderrolle und Begründung;
- Gültigkeit, Widerruf und Supersession;
- Bindung an genau den Final-Run und Publikationssnapshot.

Ohne diese Evidence bleibt der Run Draft/Blocked. Ein UI-Confirm ohne
serverseitige Revalidierung genügt nicht.

### 5. Warnung genau einmal erzeugen

Die Warnung ist nach Abschluss der Cascade genau einmal aus dem finalen
Outcome abzuleiten. Alternativ ist eine stabile Deduplizierung nach
`(code, goal_id, scope)` zulässig. Ein globales Dedupe nur nach `code` wäre zu
grob, weil echte ziel- oder scope-spezifische Warnungen verloren gehen können.

### 6. Current-Rollover atomar machen

Die neue Allocation darf erst current werden, wenn:

- die komplette Evidence intern konsistent ist;
- der Context-Hash erfolgreich rückverifiziert wurde;
- das Release-Outcome explizit bestimmt ist.

Bei Fehler bleibt die bisherige current TA unverändert. Das verhindert, dass
ein erfolgreicher Generate das Mandat mit einem sofort unlesbaren Current-
Datensatz blockiert.

### 7. Bestandsdaten inventarisieren und quarantänisieren

Vor Freigabe sind mindestens zu scannen:

- current und historische TA mit `risky > budget`;
- `optimization_method = fallback_house_matrix` bei
  `optimization_model_basis.active_method != fallback_house_matrix`;
- moderne Contexts mit House-Fallback-Basis-ID ohne passende Methode;
- Final-/Signed-/Handoff-Artefakte, die eine solche TA referenzieren;
- doppelte WARN_FALLBACK-Evidence, soweit persistiert.

Immutable Hashes dürfen nicht in-place „repariert“ werden. Historische
Artefakte bleiben als fehlerhaft klassifiziert; für weitere Beratung ist eine
neue, konsistente Version zu erzeugen oder der Datensatz zu quarantänisieren.

## Verbindliche rote Vorher-/grüne Nachher-Tests

### Context und Current-Rollover

1. Reiner House-Modus, strukturell unerreichbares Budget: Generate erzeugt
   konsistente `fallback_house_matrix`-Evidence in Spalten, Effective-
   Constraints, Model Basis und Hash.
2. Derselbe Generate lässt sich direkt über Current-Payload reloaden.
3. Recommendation-Generate konsumiert dieselbe TA ohne Provenienzfehler.
4. Jeder manipulierte Method/Status/Basis-ID/Purpose-Widerspruch endet
   fail-closed.
5. Ein interner Konsistenzfehler lässt die vorherige current TA bestehen.
6. House, stochastic, shadow, Solver-Exception und Risk-Budget-Fallback werden
   als vollständige Modusmatrix getestet.

### Release-Eligibility

1. `risky < budget` und `risky == budget` bleiben finalisierbar.
2. `risky > budget` markiert Recommendation-Generate eindeutig als
   nicht-releasefähig und blockiert Finalize/PDF/Sign/Handoff ohne Override.
3. Ein read-only Lock allein gilt nicht als Gate-Nachweis.
4. Fehlende/malformed Risk-Felder moderner TAs blockieren.
5. Eine gültige Override-Evidence ist exakt an TA/Context/RA/Policy/CMA/Run
   gebunden.
6. Stale, fremdtenantige, widerrufene oder auf andere Hashes bezogene Overrides
   blockieren.
7. Zwei parallele Finalisierungen beziehungsweise Override-Transitions können
   weder doppelte Final-Runs noch hybride Evidence erzeugen.

### Warning- und Kanalparität

1. Der Best-Effort-Pfad liefert genau eine `WARN_FALLBACK` pro Scope.
2. API, React, Classic, Advisory-Report und PDFs zeigen dasselbe Budget,
   effektive Risiko, Outcome und Eligibility-Verdict.
3. Ein Blocked-Run darf in keinem Kundenkanal als final/freigegeben erscheinen.

### Datenbank und Zielumgebung

1. SQLite und PostgreSQL erzwingen dieselben Domains und Transitions.
2. Migration/Backfill klassifiziert bestehende widersprüchliche Contexts
   deterministisch.
3. Rollback/Restore erhält die Quarantäne- und Override-Evidence.
4. Vollständige Backend-, Frontend-, Browser-, PDF-, Electron- und
   Zielumgebungsabnahme läuft auf demselben Fixcommit.

## Unzureichende Scheinlösungen

Nicht ausreichend sind:

- den Reload-Verifier zu lockern;
- `optimization_method` wieder auf `None` zu setzen und den Fallback zu
  verschweigen;
- nur die Basis-ID zu ändern, ohne alle Consumer und Hashfelder abzugleichen;
- die Budgetverletzung nur als gelbe UI-Warnung anzuzeigen;
- ausschließlich `audit_mandate_editability()` im PDF aufzurufen;
- Finalisierung trotz Verletzung mit einer ungebundenen Checkbox zu erlauben;
- die 100-bp-Probe aus Tests zu entfernen oder das Schema still auf positive
  Seed-Werte zu verengen;
- die zwei Warnungen durch UI-CSS zu verstecken;
- historische Hashes in-place umzuschreiben;
- nur Happy-Path-House-Caps zu testen.

## Testnachweis

### Einmalige produktive Gegenprobe

Der temporäre Test führte den oben beschriebenen echten Generate- und
Finalize-Pfad aus. Ergebnis:

```text
GENERATED_VIOLATION:
  risky=5627, budget=100, headroom=-5527
  warnings=[WARN_FALLBACK, WARN_FALLBACK]

MODERN_CONTEXT_REJECTION:
  HTTP 422, Optimizer-Modellbasis widerspricht aktiver TA-Methode

REPAIRED_MODERN_CONTEXT_FINALIZED_VIOLATION:
  result_status=Final, persisted_status=Final

1 passed
```

Der Test „passed“, weil er beide Fehler als erwartete Gegenbeispiele
assertierte. Er ist kein Nachweis korrekten Produktverhaltens.

### Angrenzende Bestands-Suites

Ausgeführt wurden:

```powershell
python -m pytest -q --disable-warnings `
  tests/test_kapitalschutz_risk_budget_regression.py `
  tests/test_risk_budget_cap.py `
  tests/test_risk_budget_logging.py `
  tests/test_mandate_lock_status_audit.py `
  tests/test_finalize_mandate_lock.py `
  tests/test_optimizer_production_contract.py `
  tests/test_allocation_messages.py `
  tests/test_advisory_log_aggregator.py
```

Ergebnis: **100 passed**, 0 failed, 52,72 Sekunden.

Zusätzlich:

```powershell
python -m pytest -q --disable-warnings `
  tests/test_asset_allocation_current_integrity_contracts.py `
  tests/test_finalize_rejects_non_current_policy_and_cma.py `
  tests/test_recommendation_methodology_audit.py `
  tests/test_house_matrix_risk_budget_consistency.py `
  tests/test_optimizer_context.py `
  tests/test_optimizer_effective_context.py
```

Ergebnis: **76 passed**, 0 failed, 9,19 Sekunden.

In Summe: **176 grüne Bestandstests plus 1 gezielte Gegenprobe**.

Die grünen Tests beweisen normale Caps, Risk-Enforcement-Helfer, Current-
Context-Tamper-Erkennung, Policy-/CMA-Currentness, Mandate-Lock-Diagnose und
normale Finalisierung. Sie prüfen gerade nicht die Kombination:

- strukturell unerreichbarer reiner House-Fallback;
- sofortiger Reload desselben Fallback-Contexts;
- konsistenter moderner Context mit `risky > budget` im Finalize-Gate;
- einmalige Warnung über die gesamte Eskalationscascade.

Nicht ausgeführt wurden die vollständige Backend-/Frontend-Suite, Browser-E2E,
Electron-Packaging, PDF-Pixelvergleich, echte PostgreSQL-Constraints/Races,
Migration/Backfill oder Zielumgebungs-Replay. Diese bleiben Teil der
Implementierungsabnahme.

## Empfohlene Umsetzungsreihenfolge

1. Rote Tests für den echten House-Best-Effort-Generate plus direkten Reload.
2. Kanonischen Active-Outcome-Vertrag vor Model-Basis/Hash einführen.
3. Current-Rollover erst nach interner Rückverifikation durchführen.
4. Rote Finalize-/Generate-/PDF-/Sign-/Handoff-Tests für `risky > budget`.
5. Zentralen Release-Eligibility-Gate einführen.
6. Fachentscheidung für gebundene Override-Evidence umsetzen oder Best-Effort
   auf Preview beschränken.
7. Warning-Erzeugung aus finalem Outcome deduplizieren.
8. Bestandsdaten inventarisieren, quarantänisieren und neue Versionen erzeugen.
9. Vollständige Kanal-, Datenbank-, Concurrency- und Zielumgebungsabnahme.

## Definition of Done

Der Release-Hold dieser Runde darf erst aufgehoben werden, wenn:

1. `RISK-FALLBACK-CONTEXT-001` mit rotem Vorher-/grünem Nachher-End-to-End-
   Test geschlossen ist;
2. Method, Status, Basis-ID, Purpose, Effective-Constraints, ORM-Spalten und
   Hash aus genau einem Outcome stammen;
3. ein erfolgreicher Generate niemals eine sofort unlesbare current TA
   hinterlässt;
4. `RISK-BUDGET-FINALIZATION-001` in allen Releasekanälen serverseitig
   geschlossen ist;
5. Best-Effort entweder Preview-only ist oder eine vollständig gebundene,
   unveränderliche Override-Evidence verlangt;
6. `RISK-FALLBACK-WARNING-001` genau eine Warnung pro Scope liefert;
7. historische betroffene TAs und Publikationen inventarisiert und
   quarantänisiert sind;
8. SQLite/PostgreSQL, Backend, React, Classic, PDF, Signatur, Handoff, Browser,
   Electron und Zielumgebung auf demselben Fixcommit grün sind;
9. frühere P0/P1-Gates durch die Änderung nicht regressieren.

## Abschließender Selbst-Audit dieser Runde

1. **Wurde der absichtliche Juni-Best-Effort fälschlich als neuer Fehler
   gemeldet?** Nein. Die Designentscheidung bleibt ausdrücklich erhalten;
   beanstandet werden Evidencekonsistenz und Release-Eligibility danach.
2. **Ist der 100-bp-Fall öffentlich zulässig?** Ja. Die House-Matrix-Schemas
   erlauben null bis 10.000; 100 ist kein invalider Testwert.
3. **Ist der Contextfehler nur statisch vermutet?** Nein. Die echte
   Finalisierung lieferte den produktiven 422-Text zur Model-Basis-Divergenz.
4. **Ist der Finalisierungsbefund nur ein Legacy-Bypass?** Nein. Die Probe
   behielt `context_artifacts_required=1`, korrigierte nur die moderne
   Fallback-Provenienz und berechnete den kanonischen Hash neu.
5. **Wurde das Risikobudget für die zweite Probe verändert?** Nein. Targets,
   Risky Fraction 5.627 bp und Budget 100 bp blieben identisch.
6. **Wurde der read-only Lock übersehen?** Nein. Er wurde ausgeführt und
   lieferte `is_editable=false`; gerade seine fehlende Gate-Wirkung ist der
   Befund.
7. **Ist `SIGN-ELIGIBILITY-001` doppelt gezählt?** Nein. Die Beziehung ist
   explizit; die neue ID bezeichnet den konkreten Risk-Budget-Test-/Fixvertrag.
8. **Ist die doppelte Warnung belegt?** Ja. Beide vollständigen Dicts waren im
   echten Generate-Response identisch; die zwei Append-Stellen sind statisch
   nachvollzogen.
9. **Wurden Produkt- oder Teständerungen versteckt?** Nein. Die Probe wurde
   entfernt; das Manifest enthält ausschließlich Dokumentation.
10. **Beweisen 176 grüne Tests die Freigabe?** Nein. Ihre genaue
    Abdeckungslücke und die nicht ausgeführten Gates sind dokumentiert.

Ergebnis: Die zwei P1-Vertragsbrüche und der P2-Warnungsfehler bleiben nach
Deduplizierung, Gegenprobe und Selbstprüfung bestätigt.

## Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen durch die Runde verändert werden:

1. `docs/audits/2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`
