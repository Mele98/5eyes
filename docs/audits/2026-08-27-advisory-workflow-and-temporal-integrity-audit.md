---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-advisory-workflow-and-temporal-integrity-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "9f7f642a822a895d08a61891bf60c5071d0d40c9"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-review-trigger-and-reassessment-integrity-audit.md"
prior_release_audit_commit: "9f7f642a822a895d08a61891bf60c5071d0d40c9"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-advisory-workflow-and-temporal-integrity-audit.md"
audit_mode: "read_only_static_source_existing_test_schema_in_memory_service_and_frontend_contract_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "advisor cockpit to AdvisoryLog API compatibility, compound trigger/log/resolve atomicity, advisory decision transitions, timestamps and retention anchors"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 603
focused_adjacent_tests_failed: 0
frontend_reporting_build_passed: true
required_next_action: "replace duplicated frontend compliance payloads with one generated contract, execute advisory plus trigger transitions atomically, and derive ordering and retention only from validated server-side temporal values"
---

# Advisory-Workflow- und Zeitintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die zehnte Read-only-Kontrollrunde auf
Repository-Head `9f7f642a`. Er ergänzt, ersetzt aber nicht:

1. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
2. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
3. den
   [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
4. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
5. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
6. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
7. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
8. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
9. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
10. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die zehn vorgenannten Dokumente in dieser
Reihenfolge. Ein grüner TypeScript-Build und vorhandene Backend-Positivtests
beweisen nicht, dass das aktive, nicht typisierte Cockpit denselben
Compliance-Requestvertrag verwendet.

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Drei weitere P1-Verträge sind offen:

1. Drei aktive Review-Cockpit-Pfade senden noch das alte AdvisoryLog-Format.
   Es fehlen immer fünf inzwischen verpflichtende FIDLEG-Felder; der
   Zieländerungsflow sendet zusätzlich den nicht erlaubten Typ
   `Zielaenderung`. Im realen Ablauf wird der ReviewTrigger jedoch vorher in
   einer eigenen Transaktion angelegt. Der Repro endete mit einem committed
   Trigger, keinem AdvisoryLog und sechs Validierungsfehlern.
2. AdvisoryLog, Trigger-Resolution und Statusfortschreibung sind über mehrere
   Requests verteilt. Fehler beim Resolve werden teilweise nur geloggt und die
   UI meldet trotzdem Erfolg. Gleichzeitig erlaubt der Updatepfad einen
   versionierten Status `Beschlossen` mit `decision=None`; genau diesen
   status-only Request sendet das Cockpit. Damit können UI, Trigger und
   Beratungsnachweis dauerhaft widersprüchliche Wahrheiten tragen.
3. `entry_datetime` und das Legacy-Feld `entry_date` sind freie Strings. Ein
   vollständig schemaakzeptierter Wert `not-a-date` erzeugte eine
   Aufbewahrungsfrist ab heute, während `entry_date=9999-99-99` unverändert als
   Sortier- und Review-Anker gespeichert werden kann.

`ADV-WORKFLOW-002` vertieft den bereits dokumentierten
`FIDLEG-STATE-002`-Vertrag um den konkreten status-only UI-Pfad und die
fehlende Transaktionsgrenze. `ADV-WORKFLOW-003` ergänzt `PRIV-003` um die
Herkunft der falschen Retentionbasis und `REVIEW-STATE-001` um den ungültigen
Zeitanker. Diese Befunde werden nicht als behoben betrachtet, nur weil die
übergeordneten IDs bereits offen sind.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `ADV-WORKFLOW-001` | P1 | offen | Jeder produktive Beratungs-/Ereignisflow sendet den kanonischen vollständigen AdvisoryLog-Vertrag; ein Validierungsfehler hinterlässt weder Trigger noch anderen Teilzustand |
| `ADV-WORKFLOW-002` | P1 | offen | Advisory-Entscheid, Statusübergang und zugehörige Trigger-Resolution bilden genau eine atomare, idempotente und auditierbare Transaktion; terminale Zustände ohne Entscheid sind unmöglich |
| `ADV-WORKFLOW-003` | P1 | offen | Beratungszeitpunkt, Reihenfolge und Retention werden aus validierten, timezonebewussten Serverwerten abgeleitet; ungültige Zeitstrings fallen niemals auf heute oder lexikografische Reihenfolge zurück |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| aktiver Ereignisflow und veralteter Entry-Typ | `5eyes-electron/frontend/5eyes_v2.html:9395-9432` |
| manuelles Review-Cockpit und verschluckter Resolve-Fehler | `5eyes-electron/frontend/5eyes_v2.html:24732-24775` |
| status-only Cockpit-Transition | `5eyes-electron/frontend/5eyes_v2.html:24083-24112` |
| Entscheidungsvorlage als Zwei-Request-Workflow | `5eyes-electron/frontend/5eyes_v2.html:25016-25046` |
| kanonischer AdvisoryLog-Create-Vertrag | `5eyes-backend/schemas/review.py:70-151` |
| Update-Schema ohne Post-State-Decision-Gate | `5eyes-backend/schemas/review.py:158-188` |
| Statusmatrix und Update-Route | `5eyes-backend/routers/review.py:815-823`, `:877-947` |
| Versionierung kopiert fehlenden Entscheid | `5eyes-backend/services/advisory_log_service.py:201-267` |
| freie Zeitstrings und Retentionfallback | `5eyes-backend/schemas/review.py:89-100`; `5eyes-backend/services/advisory_log_integrity.py:74-96` |
| lexikografische Latest-Reihenfolge | `5eyes-backend/services/advisory_log_service.py:288-307` |
| React-Editor bietet Status ohne Decision-Feld | `5eyes-electron/frontend/reporting/src/components/AdvisoryLogEditor.tsx:49-86`, `:157-174` |
| duplizierter handgeschriebener React-Requesttyp | `5eyes-electron/frontend/reporting/src/api/advisoryLog.ts:44-70` |

Die Zeilenangaben sind an `audited_repository_head` gebunden. Nach einem Fix
müssen Tests, Migrationen und stabile Funktionsnamen die Traceability tragen.

## Reproduktions- und Evidenzledger

| Prüfung | Beobachtung | Ergebnis |
|---|---|---|
| Cockpit-Payload mit langem gültigem Text und Entscheid gegen `AdvisoryLogCreate` | fünf Pflichtfelder fehlen: Zeitpunkt, Dauer, Kanal, Themen, Kostenhinweis | `ADV-WORKFLOW-001` bestätigt |
| Zielereignis-Payload gegen `AdvisoryLogCreate` | zusätzlich zu fünf Pflichtfeldern ist `Zielaenderung` kein erlaubter Literalwert | `ADV-WORKFLOW-001` bestätigt |
| reale Reihenfolge Trigger-Create, dann Log-Validierung | `trigger_committed=1`, `advisory_logs=0`, `validation_errors=6`, Status `Aktiv` | `ADV-WORKFLOW-001/002` bestätigt |
| Empfohlen-Eintrag ohne Entscheid, danach status-only Update | neue Version `Beschlossen`, `decision=None` | `ADV-WORKFLOW-002` bestätigt |
| vollständiger Create mit `entry_datetime=not-a-date`, `entry_date=9999-99-99` | Schema akzeptiert; `retain_until=2036-08-27` aus aktuellem Datum | `ADV-WORKFLOW-003` bestätigt |
| fokussierter AdvisoryLog-/Review-Cockpit-Backendring | 67 bestanden, 0 fehlgeschlagen, 1 Deprecation-Warnung | Positivpfade grün; neue E2E-Verträge fehlen |
| vollständiger Reporting-Frontend-Test | 47 Dateien, 536 Tests bestanden | React-Positivstand grün; kein Test der betroffenen Cockpit- oder Terminalstatusverträge |
| Reporting-Typecheck und Produktionsbuild | 461 Module gebaut, Exit 0 | Build grün; handgeschriebene Verträge bleiben dennoch divergent |

## Detailbefunde

### `ADV-WORKFLOW-001` – Das aktive Cockpit spricht nicht mehr den Backendvertrag

#### Ist-Zustand

`AdvisoryLogCreate` verlangt seit der FINMA-Härtung unter anderem:

- `entry_datetime`,
- `duration_minutes`,
- `communication_channel`,
- mindestens ein `topics`-Element und
- `cost_disclosure_given`.

Das aktive Monolith-Cockpit konstruiert in `saveAdvisoryLogEntry()`,
`runtimeProtokolliereEreignis()` und `documentDecisionTemplate()` weiterhin
nur Titel, Beschreibung, Entscheid, Legacy-Datum und optionale Anker. Selbst
bei langem Text und einem erlaubten Entscheid fehlen deshalb deterministisch
fünf Felder. Für ein Zielereignis erzeugt der Code außerdem
`Zielaenderung`; Backend und React-Vertrag erlauben ausschließlich
`Zieländerung`.

Der Ereignisflow ist besonders gefährlich: Er legt zuerst per POST einen
Trigger an und sendet erst danach das AdvisoryLog. FastAPI validiert den
zweiten Request vor dem Router, sodass dessen 422 die bereits committed erste
Transaktion nicht zurückrollen kann.

Der einzelne Auto-Log-Pfad für den Kostenausweis enthält die neuen Pflichtfelder
und beweist, dass das Cockpit beide Vertragsgenerationen gleichzeitig trägt.
Der Reporting-React-Editor baut den vollständigen Standardpayload, ist aber
eine getrennte handgeschriebene Implementierung und schützt den Monolith nicht.

#### Reproduktionen

Ein typischer Cockpit-Payload scheiterte trotz gültigem Text:

```text
5 validation errors for AdvisoryLogCreate
entry_datetime: Field required
duration_minutes: Field required
communication_channel: Field required
topics: Field required
cost_disclosure_given: Field required
```

Der Zielereignis-Payload erzeugte sechs Fehler, einschließlich des Literals.
Der tatsächliche Teilzustand nach der Requestreihenfolge war:

```text
{'trigger_committed': 1,
 'advisory_logs': 0,
 'validation_errors': 6,
 'trigger_status': 'Aktiv'}
```

#### Risiko

Ein zentraler FIDLEG-Arbeitsablauf ist aus dem aktiven Cockpit nicht belastbar
ausführbar. Je nach Einstieg entstehen sichtbare Fehler, verwaiste Trigger oder
ein im Demo-Modus scheinbar erfolgreicher Zustand, den das Backend nie
persistieren würde. Manuelle Nacharbeit kann daraufhin doppelte oder
widersprüchliche Evidenz erzeugen.

#### Verbindlicher Fixvertrag

1. OpenAPI beziehungsweise ein anderes kanonisches Schema generiert
   Frontendtypen und Requestbuilder. Literale und Pflichtfelder werden nicht in
   drei Oberflächen kopiert.
2. Alle produktiven Cockpit-Pfade verwenden denselben vollständigen
   `AdvisoryLogCreate`-Builder; Demo-Modus validiert ebenfalls dagegen.
3. Zieländerung und alle übrigen Ereignisse stammen aus derselben Enum wie das
   Backend. Keine ASCII-Ersatzwerte im Transportvertrag.
4. Pflichtfelder werden fachlich erhoben oder mit klar belegten serverseitigen
   Werten vorbefüllt; keine erfundenen Kundenbestätigungen, Kostenhinweise oder
   Gesprächsdauern.
5. Browser-E2E-Tests intercepten den echten Request und validieren ihn mit dem
   Backend-Schema. Ein TypeScript-Build allein ist kein Contracttest.
6. Ein Backend-422 hinterlässt nachweislich keinerlei Trigger-, Log- oder
   sonstigen Teilzustand.

### `ADV-WORKFLOW-002` – Compliance-Transitionen sind mehrere unabhängige Requests

#### Ist-Zustand

Das Cockpit koordiniert mindestens drei zusammengesetzte Abläufe clientseitig:

- Ereignis: Trigger anlegen, danach AdvisoryLog anlegen;
- Review protokollieren: AdvisoryLog anlegen, danach Trigger resolven;
- Entscheidungsvorlage: AdvisoryLog anlegen, danach Trigger resolven.

Beim normalen Review wird ein Resolve-Fehler ausdrücklich nur per
`console.warn` verarbeitet. Anschließend zeigt die UI trotzdem
`Protokolleintrag gespeichert`. Die Entscheidungsvorlage meldet zwar Fehler,
doch das AdvisoryLog ist dann bereits committed; ein Retry kann einen weiteren
Logkopf erzeugen.

Die Statusfortschreibung hat eine zweite Lücke. Das Cockpit sendet nur
`{status: newStatus}`. Die Backendmatrix prüft den Übergang, verlangt einen
Kommentar nur für `Abgelehnt` und `Überarbeitung nötig`, validiert aber den
vollständigen Post-State nicht auf einen Entscheid. Der Versionierungsservice
kopiert den bisherigen `None`-Entscheid. Dadurch ist ein formal
`Beschlossen`er und anschließend `Umgesetzt`er Datensatz ohne Entscheid
erreichbar.

Der React-Editor bietet dieselben terminalen Statuswerte bereits beim Create
an, besitzt aber kein Decision-Feld im Form-State und nimmt `decision` nicht in
den Payload auf. Dort stoppt der Backendvalidator den Request mit 422; die zwei
Oberflächen besitzen somit sogar unterschiedliche Fehlzustände für denselben
fachlichen Vorgang.

#### Reproduktion

```text
{'status': 'Beschlossen',
 'decision': None,
 'version': 2,
 'supersedes_id': '<vorheriger Logkopf>'}
```

#### Risiko

Triggerdashboard, Beratungsprotokoll und tatsächlicher Entscheid können
auseinanderlaufen. Ein erfolgreicher UI-Hinweis belegt nicht, dass der Trigger
erledigt wurde. Umgekehrt kann ein terminal wirkender Beratungsstatus ohne den
inhaltlichen Entscheid existieren. Retries und Parallelaufrufe vervielfachen
die Inkonsistenz.

#### Verbindlicher Fixvertrag

1. Ein serverseitiger Command-Service führt Log, Statusübergang,
   Triggerresolution, Evidenz und Auditlog in genau einer DB-Transaktion aus.
2. Der Request enthält eine Idempotency-ID beziehungsweise erwartete Version.
   Retry liefert dasselbe Resultat; konkurrierende Abweichung ergibt 409.
3. Jeder nicht rein offene Zustand verlangt einen typisierten Entscheid und
   die jeweils erforderliche Begründung/Evidence im vollständigen Post-State.
4. Trigger-ID, Recommendation-/Assessment-/Dokumentanker werden vor der
   Mutation auf Mandat, Client, Tenant und aktuellen fachlichen Kontext
   geprüft.
5. Resolve- oder Auditfehler werden nie verschluckt. Der Client erhält nur dann
   Erfolg, wenn alle Teilzustände committed sind.
6. UI und React-Editor zeigen ausschließlich fachlich ausführbare
   Transitionen; Decision-Eingabe und Required-Felder folgen der
   servergelieferten Zustandsmatrix.
7. PostgreSQL-Paralleltests beweisen genau einen neuen Logkopf, genau eine
   Triggerresolution und einen Auditdatensatz.

### `ADV-WORKFLOW-003` – Ungültige Zeitstrings erzeugen plausible Retention und Reihenfolge

#### Ist-Zustand

`entry_datetime` ist trotz Beschreibung als ISO-Zeitpunkt ein freier String;
`entry_date` bleibt ebenfalls frei. Der Schema-Validator prüft weder Syntax,
Timezone noch Beziehung der beiden Felder.

Der Service übernimmt `entry_datetime` unverändert. Ein explizites
`entry_date` gewinnt; sonst werden lediglich die ersten zehn Zeichen des
Zeitstrings abgeschnitten. `compute_retain_until()` versucht ISO-Parsing und
fällt bei jedem Fehler still auf die aktuelle Serverzeit zurück. Der
Latest-Resolver sortiert die gespeicherten Strings absteigend.

Damit kann ein Datensatz gleichzeitig behaupten, aus einem unmöglichen fernen
Datum zu stammen, im Integritätshash formal gültig sein und eine
Aufbewahrungsfrist tragen, die vom heutigen Serverdatum statt vom behaupteten
Beratungstermin berechnet wurde.

#### Reproduktion

```text
{'accepted_entry_datetime': 'not-a-date',
 'accepted_entry_date': '9999-99-99',
 'retain_until': '2036-08-27'}
```

#### Risiko

„Letzter Review“, Jahresfrist, Versionsanzeige, Retention und Export können von
verschiedenen Zeitwahrheiten ausgehen. Lexikografisch große Rohwerte verdrängen
echte Einträge. Ein Fail-open-Retentionfallback kann Datensätze früher oder
später als fachlich vorgesehen zur Löschung freigeben.

#### Verbindlicher Fixvertrag

1. `entry_datetime` wird timezonebewusst als Pydantic-Datetime validiert und
   kanonisch in UTC persistiert; Naiv-, ungültig- und nicht finite Werte sind
   422.
2. `entry_date` wird serverseitig aus dem verifizierten Zeitpunkt abgeleitet
   oder als ausdrücklich typisiertes Legacyfeld vollständig abgeglichen. Der
   Client darf keine widersprüchliche zweite Wahrheit setzen.
3. Fachlich zulässige Rückdatierung hat explizite Grenzen, Actor, Grund und
   Audit-Evidence. Zukünftige unmögliche Termine werden blockiert.
4. Retention wird ausschließlich aus dem validierten Ereigniszeitpunkt und der
   versionierten Policy berechnet. Parsingfehler sind Domainfehler, niemals
   `today`.
5. Latest-/Review-Anker-Abfragen sortieren echte Date-/Timestamp-Spalten und
   ignorieren keine ungültigen Raw-Zeilen. Altbestände werden vor der Migration
   inventarisiert und fail-closed bereinigt.
6. DB-Constraints und PostgreSQL-Typen sichern die neue Domain; SQLite- und
   PostgreSQL-Verhalten werden gemeinsam getestet.

## Verbindliche Testmatrix

### Frontend-/Backend-Contract

- Browser-E2E für manuelles Protokoll, Ereignis, Zieländerung und
  Entscheidungsvorlage prüft den vollständigen echten Request.
- Jeder Payload wird im Test durch `AdvisoryLogCreate` validiert; kein eigener
  Test-Stub mit schwächerem Interface.
- Demo- und Realmodus erzeugen dieselben fachlichen Daten oder kennzeichnen
  Demo-Evidence unmissverständlich als nicht persistiert.
- React-Editor zeigt für jeden angebotenen Status die erforderliche
  Decision-/Kommentar-/Evidence-Eingabe und sendet sie.
- Eine API-Schemaänderung lässt Frontend-Codegenerierung beziehungsweise
  Contracttest rot werden.

### Atomare Workflows

- Erzwungener Logfehler nach Triggerplanung hinterlässt null Trigger und null
  Logs.
- Erzwungener Resolve-/Auditfehler nach Logaufbau hinterlässt null neue
  Versionen und unveränderten Trigger.
- Zwei Retries mit derselben Idempotency-ID ergeben eine einzige Transition.
- Zwei echte PostgreSQL-Sessions mit verschiedenen Entscheiden ergeben genau
  einen Gewinner und einen 409-Konflikt.
- `Empfohlen → Beschlossen → Umgesetzt` ist ohne vollständigen Entscheid an
  keiner API-, Service-, Raw- oder UI-Grenze möglich.
- Renderer, Cache und Dashboard sehen erst den vollständig committed Zustand.

### Zeit- und Retentiondomain

- Ungültige, naive, unmögliche und unzulässig zukünftige Zeitpunkte sind 422;
  direkte Raw-Zeilen führen zu einem sichtbaren Domainkonflikt.
- `entry_date` und `entry_datetime` können nicht widersprechen.
- Schaltjahr, Zeitzonenwechsel und Kalenderjahresgrenzen erzeugen dieselbe
  fachliche Retention auf SQLite und PostgreSQL.
- Kein Parsingfehler ruft `datetime.now()` als Ersatzbasis auf.
- Ungültige Altzeilen können keinen Latest-/Jahresreview-Anker verdrängen.
- Retention- und Legal-Hold-Tests belegen, dass kein Datensatz aufgrund eines
  erfundenen Fallbackdatums gelöscht wird.

## Empfohlene Umsetzungsreihenfolge

1. Kanonischen Advisory-Command- und Zeitvertrag definieren; OpenAPI-Client für
   beide Frontends generieren.
2. Datetime-/Retentiondomain im Schema, Service und per additiver Migration
   fail-closed machen.
3. Servertransaktionen für Ereignis+Log und Entscheid+Resolve implementieren,
   einschließlich Idempotency/CAS und Evidence-Bindung.
4. Monolith-Cockpit und React-Editor auf die Commands umstellen; alte
   clientseitige Mehrfachrequest-Orchestrierung entfernen.
5. Browser-, API-, Raw-Daten-, Retention- und echte PostgreSQL-Paralleltests
   ergänzen.
6. Erst danach UI-Erfolgsmeldungen, Kalenderexport, Reviewdashboard und
   Compliance-/Retention-Dokumentation synchronisieren.

## Definition of Done

`ADV-WORKFLOW-001..003` gelten erst als geschlossen, wenn gleichzeitig:

- alle produktiven Cockpit- und React-Pfade den generierten kanonischen
  Advisory-Vertrag verwenden;
- Zieländerung und andere Literale über eine gemeinsame Enum transportiert
  werden;
- kein fehlgeschlagener Workflow einen Trigger, Logkopf oder Statusrest
  hinterlässt;
- Status, Entscheid, Triggerresolution und Auditlog atomar und idempotent sind;
- terminale beziehungsweise beschlossene Logs ohne Entscheid DB- und
  servicesseitig unmöglich sind;
- Zeitpunkte echte timezonebewusste Werte sind und Retention nie auf heute
  zurückfällt;
- Latest-, Jahresreview- und Retentionlogik dieselbe Zeitwahrheit verwenden;
- Browser-E2E, API-Negativtests und echte PostgreSQL-Concurrency-Tests grün
  sind;
- der vollständige Backend- und Frontend-Gate auf dem Fixcommit erneut grün
  ist; und
- dieser Audit mit Fixcommit, Migration, Testzahlen und verbleibenden
  Restpunkten aktualisiert oder durch einen klar verlinkten Abschlussaudit
  ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an AdvisoryLog, Review-Cockpit, Triggerresolution oder
Retention:

1. Diesen Audit vollständig lesen.
2. `ADV-WORKFLOW-001..003`, `FIDLEG-STATE-002`, `REVIEW-STATE-001/003` und
   `PRIV-003` als zusammenhängenden Vertrag behandeln.
3. Keine Pflichtfelder oder Literale lokal in HTML/TypeScript duplizieren.
4. Keine Compliance-Transition über zwei unabhängige Browserrequests
   koordinieren.
5. Resolve-/Auditfehler nicht verschlucken und keinen partiellen Erfolg melden.
6. Ungültige Zeitstrings niemals mit `now`, `today` oder Stringsortierung
   plausibilisieren.
7. Vor Commit Browser-E2E, Pydantic-Contract, Raw-Daten-, Retention- und
   PostgreSQL-Paralleltests ausführen.
8. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Die fokussierten Auditläufe auf dem aktuellen Head ergaben:

```text
67 passed, 1 warning in 33.95s
47 frontend test files passed; 536 frontend tests passed
TypeScript noEmit + Vite production build: Exit 0, 461 modules transformed
```

Diese grünen Positivtests widerlegen die drei Befunde nicht. Sie enthalten
keinen E2E-Vertrag für die betroffenen Cockpit-Payloads, keine atomare
Mehrschritt-Fehlerprobe und keinen ungültigen Zeit-/Retentionfall.
