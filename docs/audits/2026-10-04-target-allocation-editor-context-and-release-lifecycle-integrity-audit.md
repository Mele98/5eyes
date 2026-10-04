# Target-Allocation-Editor-, Context- und Release-Lifecycle-Integritätsaudit

**Kontrollrunde 44 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Der aktive React-Editor und das Backend besitzen für das Speichern einer
bearbeiteten Soll-Allokation keinen gemeinsamen Produktvertrag:

1. Der Editor lädt oder erzeugt eine TargetAllocation, erlaubt Targets und
   Bänder zu ändern und sendet beim Speichern den direkten
   `POST /mandates/{id}/target-allocation`.
2. Produktion erzwingt `optimizer_mode=stochastic`; genau in diesem Modus
   lehnt der direkte POST jede manuelle Allocation mit HTTP 409 ab. Der
   sichtbare Speichern-Workflow ist damit im verbindlichen Produktionsmodus
   funktional unerreichbar.
3. Im einzigen Modus, in dem der POST akzeptiert wird (`house_matrix`),
   ersetzt er die vollständige moderne current Allocation durch eine neue
   Zeile mit `context_artifacts_required=0`, ohne Context-Artefakte, CMA,
   immutable Risikoevidence, Reservebasis, Input-Hash oder Optimizer-Provenienz.
   Ein nach Einführung des Contextvertrags erzeugter Datensatz wird so als
   angeblich historischer Legacy-Datensatz behandelt.
4. Der Editor kopiert `risky_fraction_bps` aus der alten Allocation, obwohl er
   Targets und Bänder geändert hat. Die Probe speicherte 6.558 bp aus dem
   vorherigen Vorschlag; der Reload berechnete für die neue Allocation 8.636
   bp bei einem Budget von 8.000 bp. Der Mandate-Lock blieb trotzdem editierbar,
   weil beide `*_at_generation`-Felder fehlen.
5. Recommendation-Generate akzeptiert diese neue current Allocation und
   persistiert einen Draft gegen die aktuelle CMA. Finalisierung weist
   denselben Draft anschließend zwingend zurück, weil die Allocation selbst
   keine CMA referenziert.

Der Fehler ist kein bloßes Anzeigeproblem. Er betrifft den normalen
UI-Schreibpfad, Current-Aktivierung, Risiko- und Provenienzevidence sowie den
Übergang zur finalen Empfehlung. Reale Allocation-, Recommendation-, PDF-,
Signatur- und Handoff-Nutzung bleibt gesperrt.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
cf02e9c50eb971a573d2fcbae75063e71cc2f313
docs(audit): document risk fallback release gaps
```

Geprüft wurden insbesondere:

- React-Editor, Frontend-Payloadbuilder und Allocation-API-Client;
- direkter TargetAllocation-POST und Engine-Generate-Endpunkt;
- Produktionskonfiguration für `optimizer_mode`;
- ORM-, Migrations- und Legacy-Marker-Vertrag;
- Current-Rollover, Payload-Rekonstruktion und Risikobudget-Lock;
- Recommendation-Generate und Recommendation-Finalisierung;
- bestehender Stale-Run-Schutz und historische Approval-/Eligibility-Befunde.

Nicht verändert wurden Produktionscode, Schemas, Migrationen, Seed-Daten,
Tests oder UI. Die End-to-End-Probe war temporär und wurde nach der
Beweissicherung entfernt.

## Abgrenzung zu bestehenden Befunden

### Der Stale-Run-Schutz ist korrekt

`recommendations/current/payload` darf nur Runs zur aktuellen
TargetAllocation liefern. Nach einem legitimen SAA-Rollover ist HTTP 409 bis
zur Recommendation-Neuberechnung beabsichtigt und bereits durch
`test_portfolio_generate_after_saa_recalc.py` abgesichert.

Dieser Audit beanstandet nicht dieses Verhalten. Beanstandet wird, dass der
aktive Editor entweder gar keine neue Allocation speichern kann oder eine
neue current Allocation erzeugt, für die der angebotene Regenerate-Pfad zwar
einen Draft schreibt, aber keinen finalisierbaren Run erzeugen kann.

### Beziehung zu `SIGN-ELIGIBILITY-001`

`approved_by` und `approved_at` existieren im ORM und Response-Schema, werden
im Produktcode aber nirgends als Freigabetransition gesetzt. Der
Signatur-/Publikationsaudit vom 03.09.2026 dokumentiert diese allgemeinere
Lücke bereits als `SIGN-ELIGIBILITY-001`.

Die sofortige `is_current=1`-Aktivierung einer gespeicherten Allocation ohne
Approval ist deshalb keine neue vierte Finding-ID. Sie ist eine konkrete
Ausprägung des bestehenden Eligibility-Befunds und muss im selben
Lifecycle-Fix geschlossen werden.

### Beziehung zu `RISK-BUDGET-FINALIZATION-001`

Kontrollrunde 43 hat bereits gezeigt, dass ein erkannter
`risk_budget_violated`-Lock nicht als zentraler Finalisierungs-Gate konsumiert
wird. Runde 44 ergänzt einen anderen Pfad: Fehlen die beiden typisierten
At-Generation-Felder vollständig, erkennt der Lock nicht einmal die beim
Reload berechnete Verletzung. Dieser Missing-Evidence-Fail-open wird unter
`TA-LEGACY-FABRICATION-001` geführt, ohne den Befund aus Runde 43 zu duplizieren.

## Stabiles Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `TA-EDITOR-WRITE-CONTRACT-001` | P1 | bestätigt | Der aktive Editor speichert über den manuellen TargetAllocation-POST. Produktion erzwingt `stochastic`, während dieser POST im `stochastic`-Modus ausnahmslos HTTP 409 liefert. Eine sichtbare Bearbeitung kann im verbindlichen Produktionsmodus nicht persistiert werden. |
| `TA-LEGACY-FABRICATION-001` | P1 | bestätigt | Im akzeptierten House-Modus erzeugt derselbe POST nach Einführung des modernen Contextvertrags eine neue current Zeile mit Legacy-Marker und vollständig fehlender Decision Evidence, kopiert einen alten clientseitigen Risikowert und ersetzt die vorherige moderne Allocation. Reload und Roh-GET widersprechen sich; Missing Risk Evidence lässt den Mandate-Lock trotz `8636 > 8000` grün. |
| `TA-RECOMMENDATION-DEADEND-001` | P1 | bestätigt | Recommendation-Generate akzeptiert die künstliche Legacy-Allocation und persistiert einen Draft mit aktueller CMA. Finalisierung lehnt ihn danach zwingend ab, weil die TargetAllocation keine CMA bindet. Der Server erzeugt wissentlich einen nicht finalisierbaren Workflowzustand. |

## Aktiver End-to-End-Pfad

### Frontend

`AllocationEditor.onGenerate()` ruft `generateAllocation()` auf und übernimmt
die vollständige Engine-Allocation als bearbeitbaren Draft.

`AllocationEditor.onSave()`:

- validiert nur Summe und lokale Bandordnung;
- baut aus den bearbeiteten Targets/Bändern einen
  `TargetAllocationCreatePayload`;
- kopiert `record.risky_fraction_bps` aus dem vorherigen Datensatz;
- ruft `saveTargetAllocation()` auf.

Der API-Client sendet diesen Payload unverändert als direkten POST an
`/mandates/{id}/target-allocation`. Der vorhandene Engine-Generate-Endpunkt
und dessen moderner Compiler werden beim Speichern nicht verwendet.

Damit ist folgender Pfad real erreichbar:

```text
Optimizer-Vorschlag
  -> moderne, gehashte current TargetAllocation
  -> Berater ändert Target/Band
  -> Speichern
  -> direkter manueller POST
```

### Backend-Modussplit

Die Konfiguration setzt standardmäßig `optimizer_mode='stochastic'` und
verlangt in Produktion zwingend `stochastic`. Der Admin-Endpunkt schützt
dieselbe Invariante zur Laufzeit.

Der direkte POST besitzt dagegen diese Guard:

```text
wenn optimizer_mode != house_matrix:
    HTTP 409
```

Die UI bietet weder einen alternativen Save-Command noch übersetzt sie den
Draft in `AllocationPreferencesPayload.bands` für einen kanonischen
Engine-Lauf. Das Frontend zeigt also eine schreibbare Oberfläche für einen im
Produktionsmodus absichtlich verbotenen Backend-Befehl.

## Reproduktion

Die temporäre Probe verwendete:

- realistisches Score-8-Mandat aus der bestehenden Test-Seed-Hilfe;
- echte Policy, House Matrix und Building Blocks;
- echten `generate_target_allocation()`-Pfad;
- echten direkten `create_target_allocation()`-Pfad;
- echte Payload-Rekonstruktion;
- echten Mandate-Lock;
- echten Recommendation-Generate- und Finalize-Pfad;
- nur einen deterministischen Stub für den teuren Reporting-Monte-Carlo.

### Phase 1: Produktionsmodus

Nach erfolgreichem Engine-Generate wurde der Editor-Payload mit geänderten
Targets und Bändern unter `optimizer_mode=stochastic` gespeichert.

Ergebnis:

```text
HTTP 409
Manuell erzeugte Soll-Allokationen sind im stochastischen Modus nicht
zulaessig. Bitte den Engine-Generate-Pfad verwenden ...
```

Das ist exakt der in Produktion vorgeschriebene Modus.

### Phase 2: House-Modus

Mit demselben Payload unter `house_matrix` wurde der POST akzeptiert. Die
vorherige moderne Allocation wurde `is_current=0`; die neue Zeile wurde sofort
`is_current=1`.

Persistierter Zustand:

```text
context_artifacts_required              = 0
sub_allocations_json                    = NULL
effective_constraints_json              = NULL
allocation_context_hash                 = NULL
capital_market_assumptions_id           = NULL
input_snapshot_hash                     = NULL
risky_fraction_bps                      = 6558
risky_fraction_bps_at_generation        = NULL
risk_budget_bps_at_generation           = NULL
approved_by / approved_at               = NULL / NULL
```

Die 6.558 bp stammen aus der vor der Bearbeitung generierten Allocation. Sie
wurden nicht aus den neuen Targets hergeleitet.

### Phase 3: Zwei öffentliche Reads, zwei Risikowahrheiten

Der einfache Current-GET gibt die ORM-Zeile und damit 6.558 bp zurück. Der
Current-Payload-GET klassifiziert dieselbe neue Zeile als Legacy, baut
Sub-Allokationen und Risiko aus aktuellen Referenzdaten neu und lieferte:

```text
risky_fraction_total_bps = 8636
risk_budget_bps          = 8000
headroom_bps             = -636
```

Beide Antworten beziehen sich auf dieselbe current Allocation, besitzen aber
verschiedene Risikozahlen und verschiedene Provenienzqualität.

`audit_mandate_editability()` lieferte gleichzeitig:

```text
is_editable  = true
lock_reasons = []
```

Der Lock prüft das Budget nur, wenn
`risky_fraction_bps_at_generation` und
`risk_budget_bps_at_generation` beide vorhanden sind. Fehlende Evidence wird
damit wie „keine Verletzung“ behandelt.

### Phase 4: Draft wird erzeugt, Finalisierung ist unmöglich

`generate_recommendation_run()` akzeptierte die current Allocation. Weil der
TA-CMA-Anker leer ist, verwendete der Service die aktuelle CMA und persistierte
einen Draft:

```text
RecommendationRun.result_status                  = Draft
RecommendationRun.capital_market_assumptions_id  = <aktuelle CMA>
TargetAllocation.capital_market_assumptions_id   = NULL
```

Die echte Finalisierung antwortete anschließend mit HTTP 422:

```text
Soll-Allokation und RecommendationRun referenzieren verschiedene CMA.
```

Der Fehler ist deterministisch: Der Generate-Service erlaubt die fehlende CMA
für Zeilen ohne `input_snapshot_hash`; der Finalize-Service verlangt danach
Identität zwischen TA- und Run-CMA. Ohne Austausch der current Allocation kann
kein Run dieses Kriterium erfüllen.

## Root Cause A: Zwei konkurrierende Schreibmodelle

Der Engine-Generate-Pfad kompiliert eine Allocation aus Assessment, Policy,
CMA, House Matrix, Building Blocks, Vermögen, Reserve, Zielen,
Anlagepräferenzen, Constraints und Optimizer-Ergebnis. Er persistiert unter
anderem:

- `context_artifacts_required=1`;
- Sub-Allokationen und deren Risikokoeffizienten;
- effektive Constraints;
- Context-Hash und Input-Snapshot-Hash;
- Policy-, Assessment- und CMA-Anker;
- Risky Fraction und Risk Budget at generation;
- Vermögens- und Reservebasis;
- Methode, Status, Seed und OptimizerRun-Bindung.

Der direkte POST persistiert dagegen im Wesentlichen nur Requestfelder plus
ID, Version und Setzer. Er ist kein zweiter Compiler, sondern ein Raw-Row-
Writer. Beide Pfade erzeugen jedoch denselben fachlichen Typ
`TargetAllocation` und setzen ihn sofort current.

## Root Cause B: Legacy ist ein Default, keine beweisbare Herkunft

`TargetAllocation.context_artifacts_required` hat ORM- und DB-Default null
beziehungsweise `0`. Die Context-Migration führte den Marker mit
`server_default='0'` ein, damit vorhandene historische Zeilen lesbar bleiben.

Der kanonische Handoff definiert Legacy enger:

```text
Legacy = explizit markierter prä-Context-Datensatz,
nicht einfach ein beschädigter moderner Datensatz.
```

Der aktuelle Validator kann diese Herkunft aber nicht beweisen. Er behandelt
jede Zeile mit Marker 0 und drei NULL-Artefakten als „genuine legacy“ — auch
wenn der öffentliche POST sie heute neu anlegt. Dadurch wird ein zeitlich
begrenzter Read-Kompatibilitätspfad zu einem aktiven Schreibformat.

## Root Cause C: Clientdaten werden als Risikoevidence gespeichert

`TargetAllocationCreate` erlaubt dem Client, `risky_fraction_bps` zu setzen.
Der Editor kopiert den Wert aus dem alten Record; der Server leitet ihn nicht
aus dem neuen Submix ab und persistiert auch keine passende At-Generation-
Evidence.

Die robuste Regel muss lauten:

```text
Risikokennzahlen sind serverberechnete Evidence, keine Client-Claims.
```

Ein Client darf eine gewünschte Zielallokation beziehungsweise Leitplanken
übermitteln. Risky Fraction, Budget, Headroom, Reservewirkung und
Eligibility-Verdict müssen aus genau diesem neuen Context serverseitig
berechnet und gebunden werden.

## Root Cause D: Generate und Finalize haben verschiedene Zulässigkeit

Recommendation-Generate erlaubt eine Allocation ohne CMA, solange
`input_snapshot_hash` ebenfalls fehlt. Das ist für echte historische
Read-Kompatibilität gedacht. Der Service erstellt aber einen neuen
RecommendationRun und bindet ihn an die aktuelle CMA.

Finalize verlangt anschließend immer, dass die TA exakt dieselbe CMA
referenziert. Damit sind die Precondition-Mengen widersprüchlich:

```text
Generate erlaubt Zustand X
Finalize verbietet jeden aus Zustand X erzeugten Run
```

Ein Write-Service darf keinen Draft erzeugen, dessen bekannte, unveränderliche
Inputs eine spätere Finalisierung bereits ausschließen.

## Verbindlicher Lösungsvertrag für Claude

### 1. Einen kanonischen Allocation-Compiler schaffen

Bevorzugte Zielarchitektur:

- Der Editor sendet einen **Intent**, keine TargetAllocation-Zeile.
- Der Intent enthält gewünschte Targets/Bänder, Basis-TA-ID/-Version und einen
  expliziten Grund für den manuellen Eingriff.
- Der Server führt denselben kanonischen Compiler wie Engine-Generate aus.
- Policy-Caps, House Bounds, Risk Budget, Reserve, Illiquidität,
  Sub-Allokationen, Goals und Suitability werden nach der Änderung erneut
  geprüft.
- Erst das Compiler-Ergebnis darf eine moderne TargetAllocation erzeugen.

`AllocationPreferencesPayload.bands` kann dafür wiederverwendet oder zu einem
expliziten Manual-Allocation-Intent erweitert werden. Entscheidend ist nicht
der Endpointname, sondern dass beide Ursprünge denselben Context-, Evidence-
und Hashvertrag durchlaufen.

Den bestehenden Raw-Row-POST entweder entfernen oder ausschließlich als
internen Legacy-Import hinter einem nicht öffentlich erreichbaren,
provenienzprüfenden Migrationspfad behalten.

### 2. Kein post-migrationszeitliches Legacy-Schreiben erlauben

- Neue TargetAllocations erhalten DB- und ORM-seitig standardmäßig den
  aktuellen `decision_context_version` beziehungsweise zwingend
  `context_artifacts_required=1`.
- Marker 0 darf nur aus einer abgeschlossenen, nachvollziehbaren Migration
  stammen; ein normaler API-Write kann ihn nie erzeugen.
- Legacy-Reads bleiben read-only und dürfen weder current aktiviert noch als
  Basis eines neuen RecommendationRuns verwendet werden.
- Bestehende Marker-0-Zeilen, die nach Einführung des Contextvertrags erzeugt
  wurden, migrieren, neu kompilieren oder quarantänisieren; nicht still mit
  aktuellen Referenzdaten rekonstruieren.

Ein Datum allein ist kein ausreichender Provenienznachweis. Benötigt werden
mindestens Schema-/Contextversion, Origin und ein nachvollziehbarer
Migrationsevent.

### 3. Risikoevidence ausschließlich serverseitig ableiten

- `risky_fraction_bps` aus öffentlichen Create-Payloads entfernen oder
  ignorieren.
- Risky Fraction, Budget und Headroom aus den endgültigen Targets,
  Sub-Allokationen und gebundenen Building-Block-Koeffizienten berechnen.
- Roh-GET und Payload-GET müssen dieselbe persistierte Zahl und Provenienz
  liefern.
- Bei fehlender moderner Risk Evidence fail-closed; kein grüner Mandate-Lock.

### 4. Preflight vor Recommendation-Persistenz vereinheitlichen

Vor dem Erzeugen eines RecommendationRuns muss derselbe zentrale Eligibility-
Preflight gelten wie vor Finalisierung:

- aktuelle und mandateigene Assessment-, Policy- und CMA-Anker;
- moderner, vollständiger, hashverifizierter Allocation-Context;
- Risky Fraction innerhalb Budget oder exakt gebundene, zulässige Override-
  Evidence;
- keine künstliche Legacy-Zeile;
- konsistente Targets, Bänder, Reserve und Sub-Allokationen.

Schlägt der Preflight fehl, entsteht kein Draft und keine Position. Der Client
erhält einen deterministischen 409/422 mit Reparaturaktion.

### 5. Proposed, Approved und Active trennen

Die heute vorhandenen Felder `approved_by`/`approved_at` reichen ohne
Transitionlogik nicht aus. Zielzustände:

```text
Draft Intent -> Validated Allocation -> Approved -> Active
```

- Berechnen oder Speichern ersetzt nicht automatisch die bisher aktive
  Allocation.
- Aktivierung ist eine atomare CAS-Transition gegen die erwartete bisherige
  Active-ID/-Version.
- Die vorherige Final-Empfehlung bleibt bis zur gemeinsamen Freigabe einer
  neuen Allocation und Recommendation publizierbar oder wird in derselben
  atomaren Transition explizit superseded.
- Actor, Zeitpunkt, Grund, alter/neuer Hash und Eligibility-Zertifikat werden
  append-only protokolliert.

Dies ist gemeinsam mit `SIGN-ELIGIBILITY-001` umzusetzen; keine parallele
zweite Approval-Wahrheit einführen.

## Erwartete Red/Green-Tests

### Frontend

- Unter Produktionsvertrag `stochastic` führt Bearbeiten + Speichern zu einem
  erfolgreichen kanonischen Compile, nicht zu HTTP 409.
- Save sendet keine alte Risky Fraction als Evidence.
- Konflikt durch zwischenzeitlichen TA-Rollover liefert 409 und überschreibt
  keinen neueren Draft.
- UI unterscheidet Entwurf, validiert, freigegeben und aktiv.

### Backend

- Kein öffentlicher Endpoint kann eine neue Marker-0-TargetAllocation anlegen.
- Manual Intent und automatischer Generate erzeugen denselben vollständigen
  Contextvertrag.
- Geänderte Targets berechnen Risky Fraction neu; Roh- und Payload-GET sind
  identisch.
- Fehlende Risk-/CMA-/Context-Evidence blockiert Recommendation-Generate vor
  Persistenz.
- Ein erfolgreich erzeugter Recommendation-Draft erfüllt alle statischen
  Finalize-Preconditions; späterer legitimer Drift wird als solcher erkannt.
- Risky > Budget blockiert Generate/Finalize oder verlangt exakt gebundene
  Override-Evidence.
- Legacy-Datensätze sind read-only, nie current-aktivierbar und nie Grundlage
  neuer Runs.
- Aktivierung und Supersede sind unter PostgreSQL parallel konfliktfest.

### Migration

- DB-Default und ORM-Default erzeugen für neue Zeilen keinen Legacy-Marker.
- Historische echte Legacy-Zeilen bleiben eingeschränkt lesbar.
- Post-Context Marker-0-Zeilen werden deterministisch gefunden und
  migriert/quarantänisiert.
- Upgrade/Downgrade und SQLite/PostgreSQL-Schema besitzen denselben Vertrag.

## Ausgeführte Verifikation

Temporäre End-to-End-Probe:

```text
1 passed in 3.33s
```

Backend-Regressionen:

```text
92 passed in 101.40s
7 passed in 0.09s (Allocation-Editor-Wiring-Vertrag)
```

Enthalten waren unter anderem Strategy-Gates, Quick Fixes,
Suitability-Pfade, Current-Anchor-Uniqueness, Produktionsvertrag,
Allocation-Current-Integrität, Mandate-Lock, Policy-/CMA-Finalize-Gates,
Allocation-Editor-Wiring und der bewusst korrekte
Stale-Run-Regenerate-Vertrag. Insgesamt waren damit 99 bestehende Backendtests
grün.

Frontend-Regressionen im Reporting-Paket:

```text
3 test files passed
23 tests passed
```

Diese grünen Tests widerlegen die Findings nicht: Die vorhandenen UI-Tests
mocken `saveTargetAllocation`; sie testen nicht die reale Modus- und
Persistenzsemantik. Die Backendtests prüfen einzelne Guards, aber nicht die
aktive Sequenz „Generate -> UI Edit -> Save -> Reload -> Recommendation ->
Finalize“.

## Definition of Done

Der Befund ist erst geschlossen, wenn:

- der aktive Editor im vorgeschriebenen Produktionsmodus erfolgreich über
  einen kanonischen Servercompiler speichert;
- kein regulärer Write neue Legacy-TargetAllocations erzeugen kann;
- Manual- und Auto-Allocation denselben vollständigen Evidencevertrag haben;
- Client-Risikowerte weder Persistenz noch Freigabe steuern;
- Current-Rohdaten, Payload, Mandate-Lock, Recommendation, PDF, Signatur und
  Handoff exakt denselben Allocation-Context verwenden;
- Recommendation-Generate keinen statisch nicht finalisierbaren Draft
  persistiert;
- Approval und Active als echte, atomare, auditierbare Transitionen
  implementiert sind;
- historische Daten migriert oder sichtbar quarantänisiert sind;
- Red/Green-, API-, Browser-E2E-, Migration- und PostgreSQL-Paralleltests auf
  der Zielumgebung grün sind.

Bis dahin bleibt der Release-Hold bestehen.
