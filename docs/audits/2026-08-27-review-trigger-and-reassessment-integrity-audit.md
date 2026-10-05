---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-review-trigger-and-reassessment-integrity-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "04a716764e50326a9028d054b0cfe4d09b41c0d7"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-client-classification-and-compliance-state-audit.md"
prior_release_audit_commit: "04a716764e50326a9028d054b0cfe4d09b41c0d7"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-review-trigger-and-reassessment-integrity-audit.md"
audit_mode: "read_only_static_source_existing_test_schema_and_in_memory_service_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "annual review anchors, manual review schedules, review-trigger resolution evidence, recurrence and replay semantics"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 39
focused_adjacent_tests_failed: 0
required_next_action: "use one typed review-event taxonomy, reject invalid schedule inputs, and resolve recurring triggers through an atomic evidence-preserving transition that cannot postpone obligations by replay"
---

# Review-Trigger- und Reassessment-Integritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die neunte Read-only-Kontrollrunde auf
Repository-Head `04a71676`. Er ergänzt, ersetzt aber nicht:

1. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
2. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
3. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
4. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
5. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
6. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
7. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
8. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
9. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die neun vorgenannten Dokumente in dieser
Reihenfolge. Der grüne Backend-Gate beweist den auditierten Optimizerstand,
nicht die fachliche Gültigkeit oder Unveränderbarkeit von Review-Fristen.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

1. Der automatische Jahresreview sucht ausschließlich nach den internen
   `AdvisoryLog.entry_type`-Werten `Beratungsprotokoll` und `Anlageberatung`.
   Beide Werte sind im öffentlichen `AdvisoryEntryType` unzulässig. Ein über
   den API-Vertrag erfasster `Jahresreview` kann den nächsten Reviewtermin daher
   nicht ankern; das System fällt auf das Mandatseröffnungsdatum zurück.
2. Ein manueller Zeit-Trigger akzeptiert freie Frequenzen und Datumsstrings.
   Ein Tippfehler wie `weekly` wird nicht abgelehnt, sondern still in
   `jährlich` umgedeutet. Gleichzeitig bleiben `not-a-date` und ein stark
   negativer Schwellenwert speicherbar.
3. Die Resolve-Route verwirft das Pflichtfeld `decision`, besitzt keinen
   atomaren Status-/Versionsvertrag und ist wiederholt ausführbar. Bei jedem
   frühen Replay wird die nächste Jahresfrist aus der aktuellen Serverzeit neu
   berechnet; ein zweiter Resolve verschob die Pflicht im Repro um weitere elf
   Monate, ohne Entscheidnachweis.

Die bereits dokumentierten frei requestsetzbaren Advisory-Endzustände bleiben
`FIDLEG-STATE-002`; die fehlende Bindung von Compliance-Evidence bleibt
`TEN-COMP-002`. Dieser Audit zählt sie nicht erneut, sondern schließt die
separate **Fristen-, Review-Anker- und Trigger-Transitionslücke**.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `REVIEW-STATE-001` | P1 | offen | Ein abgeschlossener Review verwendet eine gemeinsame typisierte Ereignistaxonomie; der nächste Jahresreview wird ausschließlich aus einem gültigen, aktuellen und mandatgebundenen Review-Anker berechnet |
| `REVIEW-STATE-002` | P1 | offen | Triggerfrequenz, Datum, Schwelle und typspezifische Felder werden API- und Runtime-seitig strikt validiert; unbekannte Werte werden niemals in einen anderen Termin umgedeutet |
| `REVIEW-STATE-003` | P1 | offen | Resolve ist eine atomare, evidencegebundene und nicht replaybare Zustandsänderung; der Entscheid wird persistiert und ein früher Wiederholungsaufruf kann keine Pflicht verschieben |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| öffentliches Review-Ereignisvokabular | `5eyes-backend/schemas/review.py:46-58` |
| inkompatible Jahresreview-Abfrage | `5eyes-backend/services/review_engine.py:168-182` |
| ungültiges Datum fällt auf heute zurück | `5eyes-backend/services/review_engine.py:77-84` |
| manuelles Trigger-Schema | `5eyes-backend/schemas/review.py:7-17` |
| Frequenznormalisierung und stiller Jahresfallback | `5eyes-backend/routers/review.py:562-590` |
| Trigger-Create | `5eyes-backend/routers/review.py:630-669` |
| Resolve ohne Decision-/CAS-Vertrag | `5eyes-backend/routers/review.py:682-709` |
| persistiertes Trigger-Modell ohne Decision-Evidence | `5eyes-backend/models/review.py:6-28` |
| Baseline ohne Trigger-Domain-/Eindeutigkeitsconstraints | `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:907-927` |
| bestehender Test mit nicht öffentlichem Legacy-Typ | `5eyes-backend/tests/test_runtime_contracts.py:4119-4156` |

Die Zeilenangaben sind an `audited_repository_head` gebunden. Nach einem Fix
müssen Tests, Migrationen und stabile Funktionsnamen die Traceability tragen.

## Reproduktions- und Evidenzledger

| Prüfung | Beobachtung | Ergebnis |
|---|---|---|
| gültiger öffentlicher `Jahresreview` am 10.04.2026, Mandatseröffnung 01.01.2026 | tatsächlicher Termin `2027-01-01`, erwarteter Review-Anker `2027-04-10` | `REVIEW-STATE-001` bestätigt |
| manueller Zeittrigger mit `frequency=weekly`, `next_due_at=not-a-date`, `threshold_bps=-999999` | gespeichert als `frequency=jährlich`, Datum und negative Schwelle unverändert | `REVIEW-STATE-002` bestätigt |
| Resolve am 01.09.2026, früher Replay am 01.01.2027 | Termin zuerst `2027-09-01`, danach `2028-01-01`; Status erneut `Aktiv` | `REVIEW-STATE-003` bestätigt |
| Persistenzprüfung des Resolve-Requests | keine Decision-Spalte; `decision` nicht gelesen, `triggered_notes=None` | `REVIEW-STATE-003` bestätigt |
| fokussierter Systemtrigger-/Runtime-Ring | 6 bestanden, 82 abgewählt | bestehende Positivpfade grün; neue Negativverträge fehlen |
| angrenzender Review-/Frontend-/Data-Classification-/ADR-Ring | 33 bestanden, 0 fehlgeschlagen, 1 Deprecation-Warnung | angrenzende Verträge grün |

## Detailbefunde

### `REVIEW-STATE-001` – Das öffentliche Review kann seinen Jahrestermin nicht ankern

#### Ist-Zustand

Das Schema erlaubt als fachlichen Eintrag unter anderem `Jahresreview`,
`Quartalscheck`, `Strategie-Anpassung` und `Initialer Beratungsabschluss`.
`refresh_system_review_triggers()` sucht dagegen ausschließlich nach
`Beratungsprotokoll` und `Anlageberatung`. Diese zwei Begriffe kommen im
öffentlichen Literal nicht vor.

Bleibt die Abfrage leer, verwendet die Engine `mandate.opened_at`. Ein
tatsächlich später durchgeführter Jahresreview verschiebt den nächsten Termin
deshalb nicht. Der bestehende Test schützt den Fehler nicht: Er fügt per
direktem ORM-Insert gerade den nicht öffentlichen Legacy-Wert
`Beratungsprotokoll` ein und beweist damit nur diesen Rohdatenpfad.

Die Hilfsfunktion `_parse_iso_date()` verschärft die Unsicherheit: Ein
ungültiger Anker wird nicht als Inputfehler gemeldet, sondern als heutiges Datum
interpretiert. Dadurch kann auch ein beschädigter Altbestand eine plausibel
wirkende neue Frist erzeugen.

#### Reproduktion

```text
{'public_entry_type': 'Jahresreview',
 'review_date': '2026-04-10',
 'mandate_opened': '2026-01-01',
 'actual_next_due': '2027-01-01',
 'expected_from_review': '2027-04-10'}
```

#### Risiko

Eine gesetzte Jahresreview-Frist kann zu früh, zu spät oder vom falschen Datum
aus erscheinen. Das System bildet damit nicht zuverlässig ab, wann eine
Überprüfung tatsächlich abgeschlossen wurde. Ein formal grüner Trigger kann
eine falsche Compliance-Frist tragen.

#### Verbindlicher Fixvertrag

1. Eine gemeinsame Enum definiert, welche Advisory-Ereignisse einen Review
   abschließen. API, Engine, Persistenz und UI importieren denselben Vertrag.
2. Der Anker ist ein nicht gelöschter, nicht supersedierter,
   mandate-/client-/tenantgebundener und fachlich abgeschlossener Eintrag.
3. Das Ereignisdatum wird serverseitig als echtes Datum validiert. Ungültige
   oder fehlende persistierte Werte führen fail-closed zu 409 beziehungsweise
   einem sichtbaren Datenqualitätskonflikt; sie werden nicht zu `today`.
4. Gibt es mehrere gleichrangige aktuelle Abschlussanker, wird Ambiguität
   gemeldet, nicht per `.first()` aufgelöst.
5. Die Fristberechnung nutzt einen gemeinsamen kalenderbasierten Helper und
   speichert Anker-ID, Ankerdatum und Berechnungsversion nachvollziehbar.
6. Legacy-Begriffe werden nur über eine explizite Migration in die kanonische
   Taxonomie überführt; neue Requests dürfen sie nicht erzeugen.

### `REVIEW-STATE-002` – Ungültige Zeitpläne werden als gültige Jahrespflicht gespeichert

#### Ist-Zustand

`ReviewTriggerCreate` typisiert nur `trigger_type`. Name, Frequenz und Datum
sind freie Strings; die Schwelle ist ein ungegrenzter optionaler Integer. Die
Normalisierung erkennt einige deutsche Aliase. Jeder unbekannte Wert eines
Zeit-Triggers fällt anschließend kommentarlos auf `jährlich` zurück.

Der Create-Pfad validiert die Felder nach der Normalisierung nicht als
vollständigen typspezifischen Zustand. Damit können gleichzeitig eine
semantisch fremde Schwelle, ein ungültiger Datumstext und eine erfundene
Frequenz gespeichert werden. Die Datenbank besitzt dafür weder Checks noch
einen kanonischen Datentyp.

#### Reproduktion

```text
{'requested_frequency': 'weekly',
 'stored_frequency': 'jährlich',
 'stored_next_due': 'not-a-date',
 'stored_threshold_bps': -999999}
```

#### Risiko

Ein Tippfehler wird zu einer anderen Kontrollpflicht, statt den Request zu
stoppen. Kalender, Dashboard und Folgeprozesse zeigen danach einen formal
gültigen, aber nie bewusst vereinbarten Termin. Beschädigte Raw-/Legacy-Zeilen
können denselben Pfad erreichen.

#### Verbindlicher Fixvertrag

1. Frequenz ist ein striktes Enum (`monatlich`, `quartalsweise`,
   `halbjährlich`, `jährlich`, gegebenenfalls `einmalig`) mit dokumentierter
   Alias-Normalisierung nur vor der Validierung.
2. `next_due_at` ist ein echtes ISO-Datum beziehungsweise UTC-Datetime;
   ungültige Werte sind 422, im Runtimebestand ein Domainkonflikt.
3. Schwellen sind exakte Nicht-Bool-Integer mit fachlich begrenztem Bereich.
   Nur Triggerarten, die eine Schwelle verwenden, dürfen sie besitzen.
4. Ein zentraler Merged-State-Validator erzwingt Feldisolierung für `Zeit`,
   `Markt` und `Ereignis`. Unbekanntes wird nie auf einen Defaultplan gemappt.
5. Dieselbe Runtimevalidierung läuft beim Lesen, Refresh, Resolve, Export und
   Dashboard, damit Raw-/Legacy-Daten nicht vorbeigefiltert werden.
6. DB-Checks sichern Typ, Status, Flags und zulässige Kombinationen. Eine
   additive Migration auditiert vorhandene ungültige Zeilen und erfindet keine
   stillen Ersatzwerte.
7. Pro Mandat, Systemstatus, Typ und kanonischem Systemnamen ist höchstens ein
   nicht gelöschter Systemtrigger zulässig; Duplikate führen fail-closed.

### `REVIEW-STATE-003` – Resolve verwirft den Entscheid und kann Fristen per Replay verschieben

#### Ist-Zustand

Der Request verlangt `decision`, doch die Route greift ausschließlich auf
`triggered_notes` zu. Im Modell gibt es keine Decision-Spalte oder andere
immutable Resolution-Evidence.

Die Route prüft den Ausgangsstatus nicht und sperrt die Zeile nicht. Sie setzt
zunächst `Erledigt`; bei einem Zeittrigger wird der nächste Termin aus dem
aktuellen Serverdatum plus Frequenz berechnet und der Trigger sofort wieder
`Aktiv`. Derselbe Endpunkt kann deshalb beliebig oft aufgerufen werden. Jeder
Aufruf verschiebt die Frist erneut, auch wenn seit der letzten Resolution kein
Review stattfand. Das Auditlog enthält nur den resultierenden Status, nicht den
verlorenen Entscheid oder den vorherigen und neuen Fälligkeitsanker.

#### Reproduktion

```text
{'first_next_due': '2027-09-01',
 'second_early_resolve_next_due': '2028-01-01',
 'status': 'Aktiv',
 'decision_column_exists': False,
 'triggered_notes': None}
```

#### Risiko

Eine Reviewpflicht kann ohne durchgeführten Review und ohne Nachweis nach
hinten geschoben werden. Gleichzeitige oder wiederholte Requests sind
last-write-wins. Im Audit lässt sich nicht rekonstruieren, welcher Entscheid
eine Frist erledigt oder neu eröffnet hat.

#### Verbindlicher Fixvertrag

1. Resolve ist ein zentraler Transitionsservice mit Row-Lock oder atomarem
   Compare-and-Swap. Zulässiger Ausgang, Triggerart und Zielstatus sind
   explizit; ein Replay liefert 409 oder exakt dasselbe idempotente Ergebnis.
2. `decision`, Notiz, Actor, Serverzeit, vorheriger Anker, vorherige Fälligkeit,
   nächste Fälligkeit und Evidence-IDs werden append-only persistiert und in
   den Integritätshash/Auditlog aufgenommen.
3. Eine Resolution verlangt einen tatsächlich ausgelösten oder fälligen
   Trigger. Ein aktiver, noch nicht fälliger Zeittrigger darf nicht durch einen
   allgemeinen Resolve-Aufruf nach hinten verschoben werden.
4. Eine wiederkehrende Frist wird nach expliziter Fachregel aus dem bisherigen
   Fälligkeitsanker oder einem verifizierten neuen Review-Abschluss berechnet,
   nicht pauschal aus `now`.
5. Systemtrigger und manuelle Trigger besitzen getrennte, dokumentierte
   Transitionen. Ein Systemtrigger kann nicht ohne passenden System- oder
   Reviewkontext als erledigt behauptet werden.
6. Paralleltests auf PostgreSQL beweisen bei zwei Resolvern genau eine
   Transition, einen Evidenzsatz und einen nächsten Termin.

## Verbindliche Testmatrix

### Jahresreview-Anker

- Ein über das öffentliche Schema erzeugter `Jahresreview` bestimmt exakt die
  nächste Jahresfrist.
- Ein `Quartalscheck` oder informeller Eintrag ankert nur, wenn die gemeinsame
  Fachmatrix dies ausdrücklich erlaubt.
- Gelöschte, supersedierte, fremde und ungültig datierte Einträge werden nicht
  verwendet und erzeugen einen sichtbaren Konflikt.
- Zwei gleichrangige Abschlussanker werden nicht per Datenbankreihenfolge
  entschieden.
- Der alte Test mit Rohwert `Beratungsprotokoll` wird in einen expliziten
  Legacy-Migrationsvertrag umgebaut.

### Triggerinput und Runtimebestand

- Unbekannte Frequenz, ungültiges Datum, Bool-/String-Schwelle, negative und
  übergroße Schwelle ergeben 422 und keine Zeile.
- Jeder Trigger-Typ wird gegen seine vollständige erlaubte Feldkombination
  geprüft.
- Raw-/Legacy-Zeilen mit denselben Fehlern stoppen Liste, Refresh, Resolve,
  Kalenderexport und Dashboard fachlich; sie werden nicht umgedeutet.
- Doppelte Systemtrigger derselben logischen Identität führen vor jeder
  Mutation fail-closed.

### Resolution, Replay und Concurrency

- Der übergebene Entscheid wird vollständig gespeichert und ist im Audit
  nachweisbar.
- Resolve eines nicht fälligen oder nicht ausgelösten Triggers ist 409 und
  ändert keine Frist.
- Ein zweiter identischer oder abweichender Resolve ist idempotent oder 409;
  die erste Frist bleibt unverändert.
- Zwei parallele Sessions auf PostgreSQL ergeben genau einen Gewinner, einen
  Evidence-Datensatz und einen Folgeanker.
- Eine periodische Resolution nutzt den dokumentierten alten Fälligkeitsanker
  beziehungsweise einen verifizierten Reviewabschluss, nicht beliebiges
  Requesttiming.
- Fehler mappen deterministisch auf 409/422; unbekannte DB-/Programmfehler
  bleiben 500 und werden nicht als erfolgreiche Resolution ausgegeben.

## Empfohlene Umsetzungsreihenfolge

1. Gemeinsame Review-Ereignis-, Triggerfrequenz-, Status- und
   Decision-Taxonomie definieren.
2. Strikten API-/Runtime-State-Validator und kalendarische Terminberechnung
   einführen.
3. Review-Ankerresolver auf kanonische, aktuelle und mandategebundene
   Abschlussereignisse umstellen.
4. Append-only Resolution-Evidence, Version/CAS und erforderliche
   DB-Constraints per additiver Migration ergänzen.
5. Create, System-Refresh, Resolve, Kalenderexport und Dashboard auf dieselben
   Resolver/Validatoren umstellen.
6. Negativ-, Replay- und echte PostgreSQL-Paralleltests implementieren.
7. Erst nach den Tests UI-/Kalendertexte und Betreiber-/Compliance-Dokumente
   auf den neuen Vertrag synchronisieren.

## Definition of Done

`REVIEW-STATE-001..003` gelten erst als geschlossen, wenn gleichzeitig:

- ein öffentlich erzeugbarer, verifizierter Review den Jahresanker bestimmt;
- ungültige persistierte Reviewdaten niemals auf Eröffnung oder `today`
  zurückfallen;
- Triggerinputs und Raw-/Legacy-Zeilen strikt dieselbe Domain erfüllen;
- ein Resolve den Entscheid und alle Evidence-/Fristanker immutable speichert;
- frühe, wiederholte und parallele Resolutionen keine Pflicht verschieben;
- Systemtrigger pro logischem Schlüssel eindeutig sind;
- API-Negativtests sowie echte PostgreSQL-Concurrency-Tests grün sind;
- Migration, Upgrade/Downgrade beziehungsweise expand/contract und
  Altbestandsaudit nachgewiesen sind;
- der vollständige Backend-Gate auf dem Fixcommit erneut grün ist; und
- dieser Audit mit Fixcommit, Testzahlen und verbleibenden Restpunkten
  aktualisiert oder durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Review, Reassessment, AdvisoryLog oder Kalenderexport:

1. Diesen Audit vollständig lesen.
2. `REVIEW-STATE-001..003` als gemeinsame Domäne behandeln; keinen Einzelpfad
   mit lokalem Default härten.
3. Öffentliche `AdvisoryEntryType`-Werte und Systemabfragen auf eine gemeinsame
   Taxonomie bringen.
4. Keine ungültige Frequenz oder Datumsangabe auf `jährlich` oder `today`
   degradieren.
5. `decision` nicht als ungenutztes Requestfeld belassen; Evidence und
   Fristanker append-only binden.
6. Vor jedem Commit API-, Raw-Daten-, Replay- und PostgreSQL-Parallelverträge
   ausführen.
7. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Die fokussierten Auditläufe auf dem aktuellen Head ergaben:

```text
6 passed, 82 deselected in 8.94s
33 passed, 1 warning in 10.54s
```

Diese grünen Positivtests widerlegen die drei Befunde nicht. Die erforderlichen
Negativ-, Replay- und Parallelverträge existieren noch nicht.
