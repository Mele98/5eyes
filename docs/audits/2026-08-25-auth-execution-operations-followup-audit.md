---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-auth-execution-operations-followup-audit"
status_as_of: "2026-08-25"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "f74c231c9a5a6ff1b64ff60bb1003c589824f95d"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md"
prior_release_audit_commit: "f74c231c9a5a6ff1b64ff60bb1003c589824f95d"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-25-auth-execution-operations-followup-audit.md"
audit_mode: "read_only_static_focused_http_and_selected_two_session_reproductions"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 9
scope: "authentication, tenant authorization, recommendation execution, signatures, backup, deployment, readiness and release chain"
release_decision: "blocked_confirmed_p0_p1"
known_open_p0: true
known_open_p1: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "contain external exposure and backup/config P0, then close auth lifecycle and execution integrity before any release"
---

# Auth-, Ausführungs- und Operations-Folgeaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die zweite Read-only-Kontrollrunde auf
Repository-Head `f74c231c`. Er ergänzt den
[PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md)
und den
[technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Folgeaudit, der erste Post-Commit-Audit und anschließend der technische
Handoff. Ältere Deployment-, Stage-, Methodik- und Planning-Dokumente sind keine
aktuelle Source of Truth.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der grüne vollständige
Backend-Gate bleibt valide, besitzt aber keine Negativabdeckung für die hier
belegten Token-, Parallelitäts-, Signatur-, Backup- und Deploymentverträge.

## Kurzurteil

**Release weiterhin hart blockiert.** Drei zusätzliche P0-Kategorien sind
bestätigt:

1. Der generische Quick-Tunnel kann die normale, vorhandene SQLite-Datenbank
   öffentlich verfügbar machen.
2. Tier 2 kann in Production mit Single-Tenant, SQLite, deaktivierter strikter
   Isolation und ohne 2FA akzeptiert werden.
3. Ein fehlendes `return` im Backup-Retention-Validator lässt normale Backupjobs
   nach Dateierstellung, aber vor Retention, Offsite-Replikation und
   Erfolgsstatus scheitern.

Zusätzlich bestehen P1 in Token-Revocation/-Rotation, Cross-Tenant-Produkten,
Recommendation-Finalisierung, Handoff-Races, Signatur- und Kostennachweisen,
Readiness, Scheduler-Singletons sowie Artefakt-, Promotion- und Rollbackkette.

## Stabiles Findings-Register

### Auth und Tenant-Autorisierung

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `AUTH-TEN-01` | P1 | offen | Recovery sowie Legacy-Self-/Admin-Reset widerrufen Sessions und verlangen den passenden Auth-Nachweis |
| `AUTH-TEN-02` | P1 | offen | Refresh-Rotation ist atomar; genau ein Nachfolger pro Token |
| `AUTH-TEN-03` | P1 | offen | Tenant-Zuweisung migriert niemals eine alte Session in den Ziel-Tenant |
| `AUTH-TEN-04` | P1 | offen | Tenant-Admin kann nur eigene CMA lesen/schreiben/freigeben |
| `AUTH-TEN-05` | P1 | offen | private Produkte und Produktreferenzen sind tenantisoliert |
| `AUTH-TEN-06` | P1 | offen | globale FX-, Policy-, Marktdaten- und Systemaktionen erfordern Plattformrolle |
| `AUTH-TEN-07` | P1 | offen | Login-Guard ist PostgreSQL-fähig und nicht fail-open |
| `AUTH-TEN-08` | P1 | offen | Bootstrap, Invite, Reset, TOTP und Recovery-Codes werden atomar genau einmal verbraucht |

### Recommendation, Ausführung und Nachweis

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `REC-001` | P1 | offen | Generator, Universe und manuelle Positionen sehen nur globale/eigene Produkte |
| `REC-002` | P1 | offen | Finalpositionen sind einzeln gültig, nichtnegativ und produkt-eindeutig |
| `REC-003` | P1 | offen | provisorische oder nicht freigegebene Nicht-CH-Empfehlung wird nie Final/Handoff |
| `REC-004` | P1 | offen | nur Draft-Entscheidungsdaten/-positionen sind mutierbar; Final-/Superseded-Snapshots bleiben unveränderlich |
| `REC-005` | P1 | offen | Handoff-Endstatus wechselt atomar genau einmal |
| `REC-006` | P1 | offen | Signatur bindet unveränderliche Dokumentrevision und SHA-256 der signierten Bytes |
| `REC-007` | P1 | offen | Kostensnapshot, Run und Publikationsfingerprint sind Teil des Integritätshashs |
| `REC-008` | P1 | offen | aktive ProductUniverseEntries sind eindeutig; TER-Auflösung ist deterministisch |

### Operations und Release

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `OPS-001` | P0 | offen | externer Quick-Tunnel kann nie eine normale oder reale Datenbank publizieren |
| `OPS-002` | P0 | offen | Deployment-Tier, Tenancy, DB, RLS, 2FA und URL bilden eine fail-closed Matrix |
| `OPS-003` | P0 | offen | Backup-Retention, Offsite und Erfolgsstatus funktionieren end-to-end |
| `OPS-004` | P1 | offen | Migration, Backup und Marktdaten laufen als getrennte Singletons |
| `OPS-005` | P1 | offen | Readiness prüft Schema, Rolle, RLS und Releasevoraussetzungen ohne Interna zu leaken |
| `OPS-006` | P1 | offen | Release ist ein signiertes, unveränderliches Artefakt mit Promotion-Gates |
| `OPS-007` | P1 | offen | aktive Deployment-Rezepte sind ausführbar, reproduzierbar und nicht stale |
| `OPS-008` | P1 | offen | Reset-/Invite-Secrets erscheinen nie in URLs, Referern oder Logs |
| `OPS-009` | P1 | offen | Rollback verwendet kompatibles Artefakt oder Restore, keinen blinden Schema-Downgrade |
| `OPS-010` | P2 | offen | systemd, DB-Pool, Credentials und Dateirechte sind gehärtet |

Ein Finding darf erst nach rotem Negativtest, Fix, vollständigem Gate und
dokumentiertem Fixcommit geschlossen werden.

## Auth- und Tenant-Findings

### `AUTH-TEN-01` – Recovery-/Legacy-Reset lässt Refresh-Familien aktiv

Isolierte HTTP-Reproduktionen zeigten: Nach `password_reset_confirm` sowie dem
Legacy-Self-/Admin-Pfad `reset_user_password` blieb ein vorher ausgestellter
Refresh-Token gültig und erzeugte erneut ein Access-Token. Der Legacy-Self-Pfad
verlangt außerhalb des bewusst erlaubten erzwungenen Erstwechsels kein aktuelles
Passwort. Der reguläre Endpoint `/auth/change-password` ist davon nicht
betroffen: Er verlangt bereits das aktuelle Passwort und widerruft Refresh-
Tokens.

Betroffen: `routers/auth.py::password_reset_confirm`,
`routers/auth.py::reset_user_password` sowie der Self-Passwortpfad.

**Fixvertrag:** Jeder Recovery-/Admin-/Legacy-Reset widerruft die komplette
Refresh-Familie und setzt `token_revoked_before`. Self-Service verlangt außer
beim expliziten erzwungenen Erstwechsel das aktuelle Passwort. Matrix-Test:
regulärer Wechsel, Recovery, Legacy-Self, Admin und Erstwechsel besitzen je einen
expliziten Vertrag; alte Access-/Refresh-Tokens liefern nach dem jeweiligen
Widerruf 401.

### `AUTH-TEN-02` – Refresh-Rotation hat ein Zwei-Transaktionen-Race

Zwei getrennte Sessions akzeptierten denselben Refresh-Token vor Commit und
erzeugten unterschiedliche Nachfolger. `services/refresh_tokens.py:107-129`
verwendet weder Row-Lock noch atomaren Compare-and-set.

**Fixvertrag:** Atomarer CAS beziehungsweise `FOR UPDATE` plus Recheck. Ein
echter PostgreSQL-Paralleltest ergibt genau einen Rotationserfolg; der
konkurrierende Replay-Versuch liefert 401 und widerruft gemäß bestehendem
Reuse-Vertrag die gesamte Tokenfamilie.

### `AUTH-TEN-03` – Alte Session wandert bei Tenant-Zuweisung mit

Ein vor der Tenant-Zuweisung ausgestellter Refresh-Token erhielt danach ein
gültiges Token für den neuen Tenant. Damit wird eine Session ohne erneute
Authentisierung in einen anderen Mandantenscope übertragen.

**Fixvertrag:** Tenant-Zuweisung, Deaktivierung und sicherheitsrelevante
Rollenänderungen widerrufen alle Access-/Refresh-Sessions. Alte Tokens dürfen nie
in einen Ziel-Tenant wechseln.

### `AUTH-TEN-04` bis `AUTH-TEN-06` – Scope und Rollen sind zu breit

- Tenant-Admin kann fremde oder globale CMA lesen, ändern und freigeben
  (`routers/allocation.py`, `routers/jurisdiction.py`).
- Der zentrale Produktlookup besitzt keinen Tenantfilter; Firma A konnte ein
  privates Produkt von Firma B ändern. Betroffen sind Update, Mapping,
  ProductUniverse und manuelle Positionen.
- `require_advisor` erlaubt globale FX-Änderungen; `require_admin` vermischt
  Firmen- und Plattformadmin für globale Policy, Marktdaten, Logs, Backups und
  Betriebsaktionen. Selbst globale Cache-Purge-Pfade sind zu breit freigegeben.

**Fixvertrag:** Tenant-aware Resolver liefern ausschließlich globale Lesedaten
und eigene private Zeilen. Fremde Objekt-IDs ergeben 404. Globale Mutationen
erfordern `require_platform_admin` beziehungsweise eine IC-/Reference-Writer-
Rolle. Rollen×Scope-Matrix für Advisor, Firmen-Admin, Portfolio Management und
Plattformadmin.

### `AUTH-TEN-07` – Login-Guard arbeitet auf PostgreSQL fail-open

Der Login-Guard erzeugt zur Requestlaufzeit SQLite-spezifisches
`AUTOINCREMENT`-DDL. Die PostgreSQL-Inkompatibilität ist statisch eindeutig,
wurde mangels lokaler PG-Instanz aber nicht live gegen PostgreSQL ausgeführt.
Separat reproduziert ist das fail-open-Verhalten bei Guard-DB-Fehlern.

**Fixvertrag:** Tabellen ausschließlich über Alembic. PostgreSQL-Test mit zwei
Workern beweist einen gemeinsamen Lockout. Fehlerverhalten ist bewusst
fail-closed oder ein klar abgesicherter Degraded Mode.

### `AUTH-TEN-08` – One-Time-Secrets werden Read-then-Write verbraucht

Bootstrap-Lock ist pro Prozess; Invite-, Reset- und TOTP-Verbrauch sind nicht
atomar. Zwei Worker können denselben Einmalvertrag gleichzeitig akzeptieren.

**Fixvertrag:** DB-seitiger Bootstrap-Singleton; atomare
`UPDATE ... WHERE token_hash ... RETURNING`-Verträge für Invite/Reset; atomarer
Compare-and-set auf `totp_last_counter`; Recovery-Codes werden jeweils atomar
einmal verbraucht. Paralleltest: exakt ein Bootstrap beziehungsweise
Einmal-Token-/TOTP-Zähler-/Recovery-Code-Verbrauch erfolgreich.

## Recommendation-, Handoff- und Signaturfindings

### `REC-001` – Private Produkte anderer Tenants werden sichtbar

`generate_recommendation_run()` lädt aktive Produkte; der nachgelagerte Filter
begrenzt ohne kuratierte Einträge nur nach Jurisdiktion, nicht nach
`Product.tenant_id`. Auch `create_product_universe_entry()` kann ein fremdes
privates Produkt referenzieren.

**Fixvertrag:** Zentraler Produktresolver mit
`tenant_id IS NULL OR tenant_id == mandate.tenant_id`, Jurisdiktion und
Positivliste. Derselbe Resolver gilt für Generator, Universe-Create, manuelle
Positionen und alle Consumer.

### `REC-002` und `REC-004` – Korrupte oder historische Positionen bleiben möglich

Das Positionsschema besitzt keine Bounds. Positionsseitig prüft die
Finalisierung nur die Summe um 10.000 bps und aktive Produkte; andere
Finalisierungsanker werden separat geprüft. Reproduktionen mit Einzelgewichten
`-5000/+15000` sowie doppeltem Produkt wurden als finalisierbar akzeptiert.
`add_position()` blockiert nur Final, nicht Superseded.

**Fixvertrag:** Entscheidungsdaten und RecommendationPosition sind ausschließlich
in Draft mutierbar. Final-/Superseded-Entscheidungssnapshots bleiben
unveränderlich. `RecommendationHolding` bildet dagegen den separat gepflegten
Live-Depotbestand ab und bleibt ausschließlich versioniert mutierbar. Schema- und
DB-CHECKs erzwingen `0..10000 bps` und nichtnegative Beträge; ein DB-UNIQUE-
Constraint beziehungsweise Unique-Index erzwingt `(run_id, product_id)`.
Finalisierung validiert jede Position, nicht nur die Gesamtsumme.

### `REC-003` – Provisorische Empfehlung kann Final und Handoff werden

Die Finalisierungsprüfung berücksichtigt weder `provisional_data_warning` noch
den verbindlichen Non-CH-Approval-Status. Der Handoff-Pfad übernimmt einen
solchen Final-Run anschließend.

**Fixvertrag:** Nicht-CH-Finalisierung und Handoff verlangen die exakt verankerte
`committee_approved`-CMA und einen nichtprovisorischen Publikationskontext.

### `REC-005` – Handoff-Endzustände sind Last-write-wins

Execute und Cancel prüfen jeweils nur den gelesenen Status `Gesendet`. Ohne
Row-Lock oder atomaren CAS können beide erfolgreich protokollieren; der letzte
Commit bestimmt den Endzustand.

**Fixvertrag:** Atomarer `UPDATE ... WHERE status='Gesendet'`. Genau ein Gewinner,
der zweite erhält 409. Auditzeile und Statuswechsel liegen in derselben
Transaktion.

### `REC-006` – Unterzeichnetes Dokument kann überschrieben werden

Der Signaturendpoint besitzt kein Status-, Versions- oder Checksum-Gate. Eine
vorhandene Kundensignatur kann nach `Unterzeichnet` ersetzt werden.
`signature_client_signed_at` wird dabei erneuert, während das generische
`signed_at` auf dem ersten Signaturzeitpunkt bleibt; der Nachweis widerspricht
sich zeitlich. Das Schema akzeptiert außerdem syntaktisch ungültige Data-URI-/
Base64-Inhalte.

**Fixvertrag:** Signatur bindet Dokumentrevision und SHA-256 der tatsächlich
signierten Bytes. Re-Sign erzeugt eine neue Version oder 409. MIME, Data-URI und
Base64 werden vollständig validiert.

### `REC-007` – Kostennachweis ist nicht hashgeschützt

`AdvisoryLog.recommendation_run_id` ist bereits Bestandteil des v1-Hashs.
`cost_disclosure_snapshot_json` selbst, dessen `source_run_id` und der
Publikationsfingerprint fehlen jedoch. Eine nachträgliche Snapshot-Änderung blieb
in der Reproduktion `integrity_verified=True`. Außerdem kann
`cost_disclosure_given=1` ohne vollständigen Snapshot bestehen bleiben.

**Fixvertrag:** AdvisoryLog-Hash v2 mit `integrity_version`, vollständigem
kanonischem Kostensnapshot inklusive `source_run_id` und
Publikationsfingerprint. Der vorhandene Run-Anker bleibt enthalten. Legacy-v1
wird getrennt verifiziert. Kein `given=True` ohne validen Snapshot.

### `REC-008` – ProductUniverse-Duplikate machen TER nichtdeterministisch

Für `(tenant_id, jurisdiction, product_id)` besteht kein Unique-Vertrag. Zwei
parallele Creates können den `.first()`-Precheck passieren; die Kostenlogik
reduziert mehrere Overrides anschließend ohne definierte Reihenfolge nach
„letzte Zeile gewinnt“.

**Fixvertrag:** Partial-/aktive Unique-Regel, bekannte Concurrency-Verletzung auf
409 und persistierter TER-/Kosten-Snapshot für finalisierte Empfehlungen.

## Operations- und Releasefindings

### `OPS-001` – Quick-Tunnel kann eine vorhandene Live-DB exponieren

`docs/deploy/start-external.ps1` setzt keinen separaten `DB_PATH`, startet gegen
die normale Settings-/`.env`-Datenbank und veröffentlicht sie über einen
öffentlichen Cloudflare-Quick-Tunnel. `ALLOW_REAL_CLIENT_DATA=false` ist nur ein
Write-Gate; vorhandene Daten bleiben lesbar, fehlende Klassifikation gilt sogar
als synthetisch. Der isolierte Stagingpfad existiert, der README empfiehlt aber
primär den generischen Pfad.

**Sofortmaßnahme:** Generischen Tunnelpfad nicht verwenden. Vor Prozess- und
Netzstart müssen DB-Identität, frischer Wegwerfpfad und erlaubter Demo-Seed
bewiesen sein. Normale `.env`-/DB-Pfade oder vorhandene Client-/Mandatszeilen
führen zum Abbruch. Tunnel und Backend werden gemeinsam beendet.

### `OPS-002` – Tier-2-Konfiguration ist fail-open

Production akzeptiert `tier2` zusammen mit `single`, SQLite/SQLCipher,
`strict_tenant_isolation=false`, `require_2fa=false` und fehlender öffentlicher
Basis-URL. Die angebliche Auto-Derivation missdeutet Klassen-Defaults als
Overrides; Raw-Consumer lesen weiterhin `settings.tenancy_mode`.

**Fixvertrag:** Eine einzige resolved Matrix:

- T1: Single-Tenant + SQLCipher lokal;
- T2: Multi-Tenant + PostgreSQL + strikte Isolation + 2FA;
- T3: Single-Tenant + PostgreSQL;
- Dev/Test-Overrides explizit getrennt.

Widersprüche, unbekannte Tiers, fehlende TLS-/Rollen-/Backupvoraussetzungen und
Raw-/Effective-Abweichungen blockieren Startup.

### `OPS-003` – Backup-Retention-Validator liefert immer `None`

`config.py:496-500` gibt im Validator `validate_backup_keep_minimum` den
validierten Wert nicht zurück. Default und explizite Werte werden dadurch
`None`. `_prune_old_backups()` führt später `all_backups[None:]` aus und wirft,
nachdem Backup und Sidecar bereits angelegt wurden, aber vor Erfolgsreturn,
Retention und Offsite-Replikation. Der Scheduler schluckt den Fehler.

**Fixvertrag:** Validator gibt den Wert zurück und Startup prüft Typ/Range.
Backup-Erfolg und Freshness sind persistent und alarmierbar. E2E-Test mit
Temp-DB erzeugt ein hashverifiziertes Backup, pruned korrekt, repliziert Offsite
und setzt observable Status; Fehler tun dies ausdrücklich nicht.

### `OPS-004` – Multiworker-Scheduler kollidieren

Jeder Gunicorn-Worker startet eigene Migration-, Backup- und Marktdatenjobs.
Backupdateinamen haben nur Sekundengenauigkeit; parallele Prozesse zielen damit
auf dieselbe finale Backupdatei und dasselbe finale Sidecar. Die atomaren Kopien
verwenden zwar eindeutige Partial-Dateien, doch die Orphan-Bereinigung eines
Prozesses kann die noch aktive Partial-Datei des anderen löschen. Der globale
Preis-Scheduler-Schalter deaktiviert außerdem separate Market-Data-Jobs trotz
deren eigener Enabled-Flags.

**Fixvertrag:** Migration, Backup und Marktdaten als getrennte Single-Instance-
Worker/Timer mit DB-Lease und eindeutiger Run-ID. Webworker starten keine Jobs.
Featureflags bleiben unabhängig.

### `OPS-005` – Readiness ist ein `SELECT 1`-Schein-Gate

`/health/ready` erkennt weder falschen Alembic-Head noch fehlende RLS/Policies,
falsche Runtime-Rolle, ungültige Tiermatrix oder fehlendes Reporting-Bundle. Die
Fehlerantwort veröffentlicht rohe DB-Details; Caddy/systemd warten nicht auf
Readiness.

**Fixvertrag:** `/live` bleibt minimal. `/ready` prüft Head, resolved Config,
Rolle/Owner/Grants/RLS und Releasebundle mit stabilen, nicht sensitiven
Reason-Codes. Backup-/Scheduler-Freshness erhält einen separaten Operational-
Health-Kanal. Traffic wird erst nach Ready freigeschaltet.

### `OPS-006`, `OPS-007` und `OPS-009` – Keine belastbare Release-/Rollbackkette

CI baut und testet, veröffentlicht aber kein gemeinsames, signiertes Backend-/
Reportingartefakt. Der Server-Runbook klont mutable Quellen; Reporting-Dist und
Gunicorn sind nicht Teil eines gelockten Artefakts. Release-Tags verlangen weder
gleichen grünen SHA noch abgeschlossenen Compliance-Review. Aktive Tier-Rezepte
verwenden unter anderem mutable `latest`, DB-Superuser, bare PostgreSQL-URLs,
Live-WAL-Dateikopien oder `git pull develop`.

Der dokumentierte pauschale `alembic downgrade -1` kann Datenfelder und Indizes
entfernen, während imperative RLS-Änderungen ohnehin nicht zurückgerollt werden.

**Fixvertrag:** Clean Clone eines exakten SHA; gelockte Dependencies; gemeinsames
Artefakt mit SBOM, Digest, Signatur/Attestation und Release-Manifest
(Commit, Versionen, Alembic-Head, Configschema). Promotion erst nach DB-, Restore-,
Readiness- und Reporting-Gates. Standardrollback deployt das vorige kompatible
Artefakt; inkompatible DB-Zustände werden nur durch genehmigtes PITR/Restore bei
gestopptem Dienst zurückgeführt.

### `OPS-008` – Reset-/Invite-Secrets landen in Accesslogs

Backend baut Reset/Invite-Links mit Secret in Query beziehungsweise URL-Pfad.
Caddy loggt die Request-URI; gültige Recovery-Secrets können dadurch in Logs und
Backups landen.

**Fixvertrag:** Linksecret nur im URL-Fragment, sofortiges `replaceState`,
Preview/Accept nur per POST-Body und Log-Redaction. Bestehende Logs werden als
potenzieller Secret-Incident behandelt. Proxyintegration beweist, dass Token
weder URI, Referer, Exception noch Auditlog erreichen.

### `OPS-010` – Betriebshärtung

systemd wartet nicht auf `network-online`, besitzt keinen ExecStartPre-
Releasecheck und macht den gesamten Apppfad schreibbar. Credential-Rechte,
graceful Drain und DB-Timeouts sind nicht vollständig definiert.

**Fixvertrag:** Appcode/venv read-only; nur State/Log/Run schreibbar; root-owned
Credentials/`LoadCredential`; definierter Drain/Timeout; runtime explizit
migrationsfrei; `systemd-analyze verify` sowie Neustart-, DB-Ausfall- und
Long-Request-Tests.

## Verbindliche Fixreihenfolge

### Sofortige Eindämmung

1. Generischen Quick-Tunnel sperren und vorhandene Tunnel-/Accesslog-Nutzung
   prüfen.
2. Tier-2-/Tier-3-Deployment nicht starten.
3. Backup nicht als erfolgreich deklarieren; bis zum E2E-Fix manuell
   verifiziertes Backup/Restore verwenden.
4. Globale Mutationsrouten auf Plattform-/IC-Operator begrenzen.

### Block A – Operations-P0

1. `OPS-001`, `OPS-002` und `OPS-003` test-first schließen.
2. One-shot-Migration und Singleton-Jobs gemäß erstem Post-Commit-Audit.
3. Echten Backup→Restore→Login/RLS-Smoke auf PG16 und SQLite durchführen.

### Block B – Auth-Lifecycle

1. Sessionrevocation bei Passwort-, Tenant- und Rollenänderungen.
2. Atomare Refresh-/Invite-/Reset-/Bootstrap-/TOTP-/Recovery-Code-Verträge.
3. Plattform-/Tenant-Rollen und tenant-aware Resolver zentralisieren.
4. PostgreSQL-Login-Guard über Alembic und zwei Worker testen.

### Block C – Recommendation und Execution

1. Produkt-Tenantfilter und ProductUniverse-Uniqueness.
2. Positions-Domain und Run-Immutability.
3. Final-/Approval-/Publication-Vertrag aus dem ersten Audit.
4. Handoff-CAS, Signaturrevision und AdvisoryLog-Hash v2.

### Block D – Releasekette

1. Signiertes gemeinsames Artefakt und Release-Manifest.
2. Readiness-/Promotion-Gate und Singleton-Scheduler.
3. N-1-Artefaktrollback plus separater PITR-/Restore-Notfallvertrag und aktive
   Runbook-Synchronisierung.

## Neue Pflichtsuites

- `test_deployment_config_matrix.py`
- `test_backup_scheduler_e2e.py`
- `test_scheduler_singleton_multiprocess.py`
- echte `test_postgres_release_contract.py`
- `test_health_readiness_contract.py`
- Proxyintegration für Reset-/Invite-Redaction und Ready-Routing
- `test_release_artifact_smoke.py`
- `test_n_minus_one_rollback_compat.py`
- Auth-Passwort-/Tenant-/Refresh-/One-Time-Token-Matrix
- Recommendation-Positions-/Product-Tenant-/Approval-Matrix
- parallele Finalisierung, ProductUniverse-Create und Handoff-Endzustände
- Signaturbytes-/Revision-/Hash- und AdvisoryLog-v1/v2-Regressionen
- `systemd-analyze verify` und Caddy-Konfigurationsprüfung

## Definition of Done

- [ ] `OPS-001` bis `OPS-003` sind test-first geschlossen.
- [ ] Kein externer Start kann eine normale oder reale DB publizieren.
- [ ] T1/T2/T3 und Dev/Test bilden eine einzige fail-closed Configmatrix.
- [ ] Ein Backup wurde end-to-end erzeugt, verifiziert, repliziert und restauriert.
- [ ] Passwort-/Tenant-/Rollenänderungen widerrufen alle alten Sessions.
- [ ] Bootstrap, Refresh, Invite, Reset, TOTP und Recovery-Codes bestehen echte
      Paralleltests mit genau einem erfolgreichen Verbrauch.
- [ ] Tenant A sieht oder mutiert nie private Produkte/CMA von Tenant B.
- [ ] Globale Mutationen sind ausschließlich über die dokumentierte Plattform-/
      IC-Rolle erreichbar; die vollständige Rollen×Scope-Matrix ist negativ
      getestet.
- [ ] Der PostgreSQL-Login-Guard besteht mit zwei Workern einen gemeinsamen
      Lockout-Test und fällt bei Guard-Fehlern nicht unkontrolliert offen.
- [ ] Nur gültige Draft-Positionen können Final werden; Final-/Superseded-
      Entscheidungssnapshots und RecommendationPositions sind unveränderlich.
      RecommendationHoldings folgen dem separat versionierten
      Live-Bestandsvertrag.
- [ ] Provisorische/nicht freigegebene Empfehlungen erreichen weder Final noch
      Handoff.
- [ ] Handoff-Endstatus, Dokumentunterschrift und Kostennachweis sind atomar und
      unveränderlich gebunden.
- [ ] Reset-/Invite-Secrets erscheinen in keinem Proxy-/App-/Auditlog.
- [ ] Das freigegebene Artefakt ist signiert, reproduzierbar und an Schema,
      Config und Backup-ID gebunden.
- [ ] Promotion wartet auf echte Readiness; ein N-1-Artefaktrollback ohne
      Schema-Downgrade wurde geprobt.
- [ ] Für inkompatible oder datenbankbezogene Notfälle wurde ein isolierter
      PITR-/Restore-Drill mit dem tatsächlich gesicherten Backup geprobt.
- [ ] Vollständiger Backend-, PostgreSQL-, Reporting-, PDF- und Deployment-Gate
      ist auf demselben Commit grün.
- [ ] Owner/Compliance haben die Betriebs- und Publikationsverträge freigegeben.

## Startcheckliste für Claude

1. Zuerst diesen Folgeaudit, dann den ersten Post-Commit-Audit lesen.
2. Release, Quick-Tunnel und Tier-2/3 nicht freigeben.
3. Produktfixe strikt in Operations-P0, Auth, Execution und Releasekette trennen.
4. Jede Finding-ID nur mit rotem Test, Fixcommit und Abnahmegate schließen.
5. Keine Token-, Tenant-, Signatur- oder Hashdaten still migrieren.
6. Keine Golden Snapshots oder Kosten-/PDF-Orakel ohne fachliche Prüfung ändern.
7. Nach jedem Fixblock einen Implementierungscommit und danach einen reinen
   Evidenzcommit mit dessen Hash erzeugen.

## Anhang A – Dokumentationsmanifest dieses Folgeaudits

Dieser reine Dokumentationsstand umfasst exakt neun Pfade:

1. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
2. `docs/CLAUDE_HANDOFF.md`
3. `docs/audits/2026-08-25-auth-execution-operations-followup-audit.md`
4. `docs/deploy/README.md`
5. `docs/deployment/README.md`
6. `docs/deployment/phase1-cloudflare-tunnel.md`
7. `docs/deployment/tier1-self-hosted.md`
8. `docs/deployment/tier2-shared-cloud.md`
9. `docs/deployment/tier3-dedicated.md`

Commit-Provenienz nach dem Doku-Commit:

```powershell
git log -1 --format=%H -- docs/audits/2026-08-25-auth-execution-operations-followup-audit.md
```
