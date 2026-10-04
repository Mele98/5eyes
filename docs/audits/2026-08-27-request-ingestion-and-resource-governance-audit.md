---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-request-ingestion-and-resource-governance-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "6c2deb44a0105019c4306452a491e8c97866ceef"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-27-recovery-link-mail-transport-security-audit.md"
prior_release_audit_commit: "6c2deb44a0105019c4306452a491e8c97866ceef"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-request-ingestion-and-resource-governance-audit.md"
audit_mode: "read_only_static_local_http_model_upload_history_and_concurrency_reproductions"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Public and authenticated request-size boundaries, multipart buffering, persisted report payload cardinality and solver admission control"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "enforce edge and application body budgets before parsing, bound persisted field/history cardinality, and add tenant-fair admission control for solver work before exposing the service"
---

# Request-Ingestion- und Ressourcen-Governance-Audit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die sechste Read-only-Kontrollrunde auf
Repository-Head `6c2deb44`. Er ergänzt, ersetzt aber nicht:

1. den
   [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
2. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
3. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
4. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
5. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
6. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die sechs vorgenannten Dokumente in dieser
Reihenfolge. Historische Upload-, Proxy-, Reporting- und Deploymenthinweise
sind keine Freigabequelle.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der grüne vollständige
Backend-Gate bleibt ein Regressionsnachweis für den eingecheckten
Optimizerstand, beweist aber weder Request-Budgets noch Ressourcenfairness.

## Kurzurteil

**Release bleibt hart blockiert.** Drei neue P1-Verträge sind offen:

1. Backend und dokumentierter Caddy-Eintritt besitzen keine harte
   Request-Body-Grenze. Ein unauthentifizierter Reset-Request mit mehr als
   8 MiB wurde vollständig geparst und mit HTTP 200 beantwortet. Der
   CSV-Importer liest ebenfalls die gesamte Datei, bevor er seinen eigenen
   2-MiB-Grenzwert prüft.
2. Kunden- und berichtsrelevante Text-/Listenfelder besitzen vielfach weder
   Byte-/Zeichen- noch Kardinalitätsgrenzen. Die Report-Notes-Historie kopiert
   bei jedem Edit alte und neue Inhalte in ein unbegrenzt wachsendes JSON und
   liefert die gesamte Historie standardmäßig wieder aus.
3. Allocation-Generate und Goal-Sensitivity besitzen keine Admission Control,
   Nutzer-/Tenant-Quota, Warteschlange oder Idempotenz. Zwei parallele
   Generate-Aufrufe traten gleichzeitig in den teuren Modellpfad ein;
   Sensitivity führt pro Request zwei Solverläufe aus.

Die bereits dokumentierte Unvollständigkeit des DSG-Exports bleibt
`PRIV-002`; die Signatur-/Dokumentbindungsfehler bleiben `REC-006`; der
Current-Anchor-/HTTP-409-Race bleibt im Post-Commit-Audit. Sie werden hier
nicht als neue Findings doppelt gezählt. Dieser Audit betrifft ausschließlich
Ressourcenverbrauch **vor**, **während** und **nach** der fachlichen
Validierung.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `RESOURCE-001` | P1 | offen | Edge und Anwendung lehnen übergroße Bodies vor JSON-/Multipart-Parsing, Auth, DB und Mail mit einem stabilen 413-Vertrag ab |
| `RESOURCE-002` | P1 | offen | Persistierte Texte, JSON-Strukturen, Listen und Versionshistorien besitzen fachliche Byte-/Kardinalitätsbudgets sowie eine beweisbare Retention-/Pagination-Strategie |
| `RESOURCE-003` | P1 | offen | CPU-/speicherintensive Solverarbeit wird global begrenzt, tenant-fair zugelassen, idempotent dedupliziert und ohne partielle Entscheidungsartefakte abgebrochen |

Ein Finding darf erst nach rotem Grenz-/Paralleltest, Produktfix, echter
Proxy-/Multiworkerprüfung und vollständigem Gate auf demselben Fixcommit
geschlossen werden. Ein Pydantic-Feldlimit allein, ein Caddy-Limit allein oder
ein serieller Unit-Test beweist den End-to-End-Vertrag nicht.

## Reproduktions- und Evidenzledger

| Scope | Methode | Ergebnis |
|---|---|---|
| Öffentlicher JSON-Body | echter FastAPI-`TestClient` gegen `/auth/password-reset/request`, isolierte Temp-DB, Scheduler aus | 8.388.659 Bytes wurden vollständig geparst; Response 200 |
| App-/Edge-Inventar | `main.py`, `core/middleware.py`, dokumentierter `Caddyfile` | CORS-/Header-Middleware vorhanden; kein Body-Limit, keine Streamzählung, kein Route-Budget |
| CSV-Grenze | direkter produktiver Importpfad mit instrumentiertem File-Objekt | `.read()` wurde ohne Größenargument aufgerufen; erst nach 2.097.153 materialisierten Bytes kam 413 |
| Schema-Kardinalität | direkte Pydantic-Validierung | 4-MiB-`title`, 4-MiB-`content_json`, 4-MiB-Notiz und 200.000 To-dos wurden akzeptiert |
| Notes-Amplification | produktiver `snapshot_to_history()`-Helper | sechs alternierende 256-KiB-Edits erzeugten 2.884.258 Bytes History-JSON |
| Solver-Admission | zwei Threads gegen den produktiven Generate-Router mit Barrier-Capture am Modellaufruf | zwei Aufrufe, Peak zwei gleichzeitig, kein Admission-Fehler |
| Cache-Nachprüfung | 16 Threads, 1.600.000 `ScenarioCache.get()`-Operationen auf demselben Key | kein reproduzierbarer Fehler; deshalb kein separates Cache-Race-Finding |
| Abgrenzung DSG-Export | Code-/Audit-Gegenlese | globale Response-Middleware setzt `Cache-Control: no-store`; Export-Fail-soft ist bereits `PRIV-002` |
| Bestehende Regressionen | Security-Header, Fondsuniversum/CSV, Notes-History, DSG-Export und Phase-6-Sensitivity auf isolierter Temp-DB | 133 von 133 Tests grün; eine bekannte `datetime.utcnow()`-Deprecation |

Die öffentliche Body-Reproduktion ergab:

```json
{
  "request_bytes": 8388659,
  "status": 200,
  "response": {
    "message": "Falls ein Konto existiert, wurde eine Reset-Anleitung an die hinterlegte E-Mail gesendet."
  }
}
```

Die persistente Größenprobe ergab:

```json
{
  "contract_title_bytes": 4194304,
  "contract_content_bytes": 4194304,
  "notes_bytes": 4194304,
  "todo_items": 200000,
  "history_entries": 6,
  "history_bytes": 2884258
}
```

Die Solver-Admission-Probe ergab:

```json
{
  "calls": 2,
  "peak_concurrent_generate": 2,
  "errors": []
}
```

Es wurden ausschließlich synthetische Inhalte und temporäre Datenbanken
verwendet. Kein echter Account, Kundendatensatz, Mailtransport oder externer
Dienst wurde kontaktiert.

## Befunde und verbindliche Fixverträge

### `RESOURCE-001` – Request- und Uploadgrößen werden erst nach Vollbufferung begrenzt

`5eyes-backend/main.py:125-132` registriert nur Request-Context- und
CORS-Middleware. `core/middleware.py:54-66` ruft die Anwendung auf, ohne den
eingehenden ASGI-Body zu zählen. Auch der dokumentierte Reverse-Proxy
`docs/deploy/Caddyfile:1-20` enthält kein Request-Body-Limit.

Der öffentliche Reset-Endpunkt wird erst nach vollständigem Pydantic-Parsing
aufgerufen (`routers/auth.py:587-630`). Sein Login-Guard kann den bereits
empfangenen und materialisierten Body daher nicht schützen. Weil das
Requestmodell unbekannte Felder standardmäßig ignoriert, wurde ein 8-MiB-
`padding`-Feld nicht einmal fachlich abgelehnt.

Der einzige Uploadpfad besitzt zwar einen fachlichen Grenzwert von 2 MiB,
verwendet aber `file.file.read()` ohne Größenargument und vergleicht erst
anschließend (`routers/review.py:1232-1233,1396-1412`). Multipart-Spooling
verhindert damit nicht, dass der komplette Upload erneut in Prozessspeicher
materialisiert wird. Ein gesendeter oder gefälschter `Content-Length` ist kein
belastbarer Schutz.

**Auswirkung:** Ein nicht authentifizierter Netzwerkakteur kann mit wenigen
großen Requests Speicher, Eventloop-/Workerzeit und
Verbindungsressourcen binden, bevor Auth-, Rate-Limit- oder Domainlogik greifen.
Ein authentifizierter Admin kann denselben Effekt über Multipart verstärken.
Im dokumentierten Zwei-Worker-Betrieb ist dies eine gemeinsame
Verfügbarkeitsgrenze aller Firmen.

**Fixvertrag:**

1. Am Edge einen expliziten globalen Maximalbody, Request-/Read-Deadline und
   passende Rate-Limits konfigurieren; direkte Backendexposition bleibt
   gesperrt.
2. In der ASGI-Anwendung den tatsächlichen Byte-Stream zählen. Fehlender,
   falscher oder chunked `Content-Length` darf die Grenze nicht umgehen.
3. Pro Endpoint kleinere fachliche Budgets definieren: Auth-/Recovery-JSON,
   normale CRUD-Requests, Signaturdaten und CSV-Upload sind getrennte Klassen.
4. Vor Überschreitung beziehungsweise spätestens beim ersten Byte über dem
   Limit mit stabilem 413-Code abbrechen; weder Pydantic-/Multipart-Parsing,
   Auth, DB, Mail noch Audit-Fachaktionen dürfen danach laufen.
5. CSV höchstens mit `read(max_bytes + 1)` oder echt streamend lesen,
   Zeilen-/Spalten-/Feldlängen während des Streams begrenzen und das
   Uploadobjekt sicher schließen.
6. Rejections und aktive Bodyressourcen tenant-/IP-sicher metrisch erfassen,
   ohne Body, Bearer oder Personeninhalt zu loggen.

**Rote Tests:** echte HTTP-Requests mit `max`, `max+1`, falschem, fehlendem und
zu kleinem `Content-Length`; chunked und langsam übertragen; JSON, Form und
Multipart; mehrere parallele Requests. Bei Ablehnung bleiben DB, Mail,
Importfunktion und Auditlog unverändert, RSS/Tempdateien innerhalb des
festgelegten Budgets und die Response stabil 413.

### `RESOURCE-002` – Persistierte Berichtsartefakte wachsen ohne Feld- oder Historienbudget

`ContractDocumentCreate.title` und `content_json` besitzen keine Längen- oder
Strukturgrenze (`schemas/review.py:233-243`). `ReportNotesUpdate` lässt neun
freie Text-/Listenfelder ohne Zeichen-, Byte-, Item- oder Itemlängengrenze zu
(`schemas/review.py:895-908`). Die zugehörigen DB-Spalten sind freie
`String`-Felder (`models/review.py:31-61,469-512`).

Beim Report-Notes-PUT werden Listen vollständig zu JSON serialisiert. Jede
tatsächliche Änderung lädt die gesamte bisherige Historie, fügt einen Snapshot
mit altem und neuem Wert ein und serialisiert alles erneut
(`routers/allocation.py:702-810`). `services/notes_versioning.py:20-29`
dokumentiert ausdrücklich „Append-only ohne Compaction; alle Versionen“.
GET und PUT liefern danach über `previous_versions` die komplette Historie
wieder aus.

Das ist nicht nur ein einmaliger großer Body. Schon wenige Wechsel zwischen
großen Werten duplizieren Inhalte dauerhaft, erhöhen DB-/Backup-/DSG-Export-
Größe und verursachen bei jedem Edit und Read erneut O(Historiengröße)
Parse-/Serialize-/Responsearbeit. Advisory-JSON und PDF konsumieren dieselben
Texte. Ein berechtigter Advisor einer Firma kann so gemeinsamen Prozess-,
Speicher-, DB- und Backupdruck aufbauen.

**Abgrenzung:** `REC-006` bleibt für MIME/Base64, Unveränderlichkeit und
Dokumenthash von Signaturen zuständig. `PRIV-002` bleibt für Vollständigkeit und
Fail-closed-Status des DSG-Exports zuständig. Die hier geforderten Größen- und
Kardinalitätsbudgets gelten zusätzlich für deren Payloads und Downstream-
Verarbeitung.

**Fixvertrag:**

1. Für jedes persistierte und kundenrelevante String-/JSON-/Listenfeld
   explizite Maximalwerte in Zeichen **und** UTF-8-Bytes definieren; Listen
   erhalten Itemzahl und Itemgröße.
2. Vertrags-`content_json`, Produkt-Exposure-JSON und ähnliche Felder als
   versioniertes, strikt typisiertes Schema validieren, nicht als beliebigen
   JSON-String.
3. Notes-Versionen vorzugsweise normalisiert in einer eigenen Tabelle
   speichern. History standardmäßig paginieren; keine vollständige Historie im
   normalen GET/PUT-Response.
4. Retention, Legal Hold und erlaubte Kompaktierung fachlich festlegen. Kein
   stilles Abschneiden von Beweisdaten.
5. Größen-/Kardinalitätsregeln zusätzlich in Service-/Runtime-Gates und, wo
   portabel, DB-Constraints verankern. Direkte/Legacy-DB-Zustände dürfen PDF,
   Export oder Publikation nicht unkontrolliert aufblasen.
6. Tenant-Speicherquota und beobachtbare 413/422/409-Grenzen einführen.
   Bestehende Übergrößen werden inventarisiert und kontrolliert migriert oder
   read-only blockiert, nie still gekürzt.

**Rote Tests:** pro Feld und Liste `max`/`max+1`, Mehrbyte-Unicode,
verschachteltes JSON, viele kleine Items und ein großes Item; wiederholte
alternierende Updates; History-Pagination und Legal Hold. DB-, Response-,
Backup-, Export- und PDF-Größe sowie Peak-RSS bleiben unter einem festgelegten
Budget.

### `RESOURCE-003` – Stochastische Modellarbeit besitzt keine Admission Control

Die beiden schreibenden Modellendpunkte sind für jeden Advisor erreichbar
(`routers/allocation.py:497-576`). Generate ruft unmittelbar den vollständigen
Allocation-/Optimizerpfad auf. Sensitivity baut Live-Kontext auf und ruft den
Solver für Baseline und Counterfactual zweimal auf
(`services/portfolio_engine.py:4368-4425,5282-5315`).

In Router, Engine, Konfiguration und dokumentiertem Caddy-Pfad gibt es keine
globale Kapazitätsgrenze, per-Tenant-/per-User-Quota, bounded Queue,
Idempotency-Key oder Retry-Vertrag. Die direkte Barrier-Reproduktion bewies,
dass zwei Generate-Aufrufe gleichzeitig in den Modellcall eintreten.
Verschiedene Mandate umgehen naturgemäß auch die Current-Anchor-Unique-Regel;
beim gleichen Mandat wird die teure Arbeit vor einem möglichen Anchor-Konflikt
doppelt ausgeführt.

**Auswirkung:** Ein kompromittierter oder fehlerhafter Advisor-Client kann
gezielt Generate/Sensitivity wiederholen und die CPU-/NumPy-/Speicherressourcen
der zwei dokumentierten Webworker für andere Firmen verdrängen. Der vorhandene
Login-Guard schützt authentifizierte Business-Endpunkte nicht. Das ist von der
bereits dokumentierten HTTP-409-Behandlung eines Current-Anchor-Races zu
unterscheiden: selbst ein korrekt gemappter Verlierer hat die Modellarbeit dann
schon bezahlt.

**Fixvertrag:**

1. Solverarbeit aus Webworker-Threads in eine begrenzte Jobausführung mit
   globaler Kapazität, per-Tenant-Fairness und fester Queue verschieben.
2. Pro Nutzer, Mandat und Tenant Frequenz-, Gleichzeitigkeit- und Tagesbudget
   definieren. Ablehnung erfolgt **vor** Datenladen/Szenariobau mit 429 plus
   `Retry-After` oder einem dokumentierten 503-Kapazitätsvertrag.
3. Idempotency-Key und kanonischen Live-Input-Hash verwenden: identische
   Wiederholungen teilen ein Ergebnis; widersprüchliche Wiederverwendung wird
   abgelehnt.
4. Pro Mandat höchstens einen mutierenden Generate-Job zulassen. Sensitivity
   darf keinen Current-Anchor schreiben und erhält ein separates, niedrigeres
   Budget.
5. Deadline, Cancellation und Worker-Absturz atomar behandeln. Kein
   `TargetAllocation`-, `OptimizerRun`- oder Audit-Halbzustand darf bleiben.
6. Queuezeit, Laufzeit, RSS, CPU, Abbruch, Tenantfairness und Rejection-Code
   secretfrei messen. Ein Tenant darf die globale Queue nicht monopolieren.

**Rote Tests:** echte parallele HTTP-Aufrufe aus zwei Nutzern und zwei Tenants;
gleicher und verschiedener Mandatsschlüssel; Generate und Sensitivity gemischt;
Queue voll, Timeout, Cancel und Worker-Absturz. Exakt die zugelassene Zahl
erreicht den ersten Solveraufruf, der Rest erhält den stabilen Kapazitätscode.
Idempotente Wiederholung erzeugt keine zweite Berechnung und keinen zweiten
Entscheidungsanker.

## Verbindliche Umsetzungsreihenfolge für Claude

### Block A – Ingress vor Parsing begrenzen

1. Zuerst rote End-to-End-Tests für JSON, Multipart, chunked und langsame
   Übertragung schreiben.
2. Edge- und ASGI-Grenzen mit expliziten, dokumentierten Budgets ergänzen.
3. CSV und sonstige Datei-/Data-URI-Pfade streamend beziehungsweise `max+1`
   prüfen.
4. Direkte Backendexposition und Body-Logging weiterhin ausschließen.

### Block B – Persistenz- und Historienbudgets etablieren

1. Inventar aller Requestmodelle und persistierten Freitext-/JSON-/Listenfelder
   erzeugen; pro Datenklasse ein Budget beschließen.
2. Pydantic-, Service- und DB-Gates test-first umsetzen.
3. Report-Notes-Historie normalisieren/paginieren und Legacy-Übergrößen
   kontrolliert behandeln.
4. PDF, Advisory, DSG-Export, Backup und Portal gegen dieselben Budgets prüfen.

### Block C – Solverarbeit fair zulassen

1. Admission-/Idempotency-Vertrag vor dem ersten Modellinput-Load definieren.
2. Begrenzte Jobausführung und Tenantfairness implementieren.
3. Current-Anchor-CAS/409 anschließend mit derselben Transaktion abstimmen.
4. Timeout-/Cancel-/Crash-Semantik und Metriken beweisen.

### Block D – Proxy, Multiworker und vollständiger Gate

1. Caddy-/ASGI-Integration auf der echten Zielumgebung prüfen.
2. Zwei Webworker plus getrennte Solverjobs unter Last und Tenantkonkurrenz
   testen.
3. Erst danach Dokumentation und Runbooks synchronisieren.
4. Alle früheren P0/P1 bleiben separat offen; dieser Block hebt keinen Auth-,
   Recovery-, PostgreSQL-, Advisory-, Crypto- oder Desktopblocker auf.

## Verbindlicher Testvertrag

Neue oder erweiterte Suites mindestens:

- `5eyes-backend/tests/test_request_body_limits.py`
- `5eyes-backend/tests/test_product_csv_streaming_limits.py`
- `5eyes-backend/tests/test_persisted_payload_size_contracts.py`
- `5eyes-backend/tests/test_report_notes_history_budget.py`
- `5eyes-backend/tests/test_solver_admission_control.py`
- `5eyes-backend/tests/test_solver_tenant_fairness.py`
- `5eyes-backend/tests/test_deployment_proxy_body_limits.py`

Der Request-Test muss den echten ASGI-Empfangspfad verwenden und darf nicht nur
einen Header oder Pydantic-Validator aufrufen. Der Solver-Test braucht echte
parallele Requests mit getrennten Sessions; ein Barrier-Double darf den
Admission-Punkt sichtbar machen, der abschließende Lasttest muss den echten
Solverprozess verwenden.

## Definition of Done

Dieser Block ist erst geschlossen, wenn:

- [ ] JSON, Form und Multipart über ihrer Routegrenze vor Fachlogik mit 413
      enden;
- [ ] fehlender, falscher und chunked `Content-Length` die Bytezählung nicht
      umgehen;
- [ ] langsame oder abgebrochene Uploads keine Worker/Tempdateien dauerhaft
      binden;
- [ ] CSV nie mehr als `max+1` Bytes materialisiert und Zeilen/Felder während
      des Lesens begrenzt;
- [ ] alle persistierten Kunden-/Reportfelder explizite Byte-/Kardinalitäts-
      budgets besitzen;
- [ ] Notes-History paginiert, bounded und Legal-Hold-/Retention-konform ist;
- [ ] Legacy-Übergrößen inventarisiert und ohne stillen Datenverlust behandelt
      sind;
- [ ] Solverjobs global begrenzt und tenant-fair sind;
- [ ] Idempotenz, Timeout, Cancel und Crash keine doppelten oder partiellen
      Entscheidungsartefakte hinterlassen;
- [ ] Proxy-, ASGI-, Multiworker- und echte Solverlasttests auf der
      Zielumgebung grün sind;
- [ ] fokussierte Ressourcen-Suites und vollständiger Backend-Gate auf
      demselben Fixcommit grün sind;
- [ ] Security, Operations und fachlicher Owner die Budgets freigegeben haben.

## Claude-Startcheckliste

1. Dieses Dokument und danach alle sechs Vorgängerdokumente vollständig lesen.
2. Keine Produktänderung vor roten Body-, Persistenz- und Paralleltests.
3. Bodylimit immer am Edge **und** in der Anwendung umsetzen.
4. `Content-Length` nie als alleinige Wahrheit verwenden.
5. Keine historische Beweisdaten still kürzen oder überschreiben.
6. Solver-Admission muss vor Szenariobau, DB-Mutation und teurer Validierung
   liegen.
7. `RESOURCE-003` nicht mit dem bestehenden Current-Anchor-409-Finding
   zusammenlegen; beide Verträge müssen separat grün sein.
8. `PRIV-002` und `REC-006` nicht als durch Größenlimits geschlossen markieren.
9. Pro Finding roten Test, Produktfix, fokussierten Ring und vollständigen Gate
   auf demselben Commit dokumentieren.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-27-request-ingestion-and-resource-governance-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- öffentliche 8-MiB-HTTP-Reproduktion: bestätigt;
- CSV-Vollbuffer-Reproduktion: bestätigt;
- Pydantic-/History-Größenreproduktion: bestätigt;
- parallele Generate-Admission-Reproduktion: bestätigt;
- Cache-Stresstest ohne Fehler: bewusst kein neues Finding;
- fokussierter Security-/CSV-/Notes-/Export-/Phase-6-Ring: 133 von 133 Tests
  grün;
- Finding-Register: 3 eindeutige IDs, 3 zugehörige Detailsektionen;
- Produkt- und Testdateien: unverändert;
- lokale Links, Markdown-Fences, Manifest und `git diff --check`: vor Commit
  vollständig zu prüfen;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
