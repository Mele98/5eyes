---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-data-lifecycle-crypto-browser-followup-audit"
status_as_of: "2026-08-26"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "07cff035c7731f4a058fbdb1669c7ea9b89bab44"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-25-auth-execution-operations-followup-audit.md"
prior_release_audit_commit: "07cff035c7731f4a058fbdb1669c7ea9b89bab44"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md"
audit_mode: "read_only_static_selected_subprocess_two_session_and_backup_restore_reproductions"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "privacy lifecycle, export, retention, restore, secrets, JWT, audit chain, SQLCipher conversion, tenant encryption, passwords, backup authenticity and browser token lifecycle"
release_decision: "blocked_confirmed_conditional_p0_and_p1"
known_open_p0: true
known_open_p1: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "contain weak JWT and unsafe SQLCipher migration, then close secret exposure and subject-data lifecycle before any release"
---

# Datenlebenszyklus-, Krypto- und Browser-Folgeaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die dritte Read-only-Kontrollrunde auf
Repository-Head `07cff035`. Er ergänzt, ersetzt aber nicht:

1. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
2. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
3. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit, der Auth-/Execution-/Operations-Audit, der erste Post-Commit-Audit
und zuletzt der technische Handoff. Historische Planning-, Stage-, Deployment-
und Methodikdokumente sind keine aktuelle Source of Truth.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der grüne vollständige
Backend-Gate bleibt als Regressionsnachweis gültig, deckt die hier belegten
Negativverträge zu Secret-Redaction, Krypto-Konfiguration, Datenlöschung,
Retention, Restore, paralleler Audit-Verkettung und Browser-Logout aber nicht ab.

## Kurzurteil

**Release bleibt hart blockiert.** Zwei bedingte P0-Verträge sind bestätigt:

1. Production akzeptiert einen trivial erratbaren JWT-Schlüssel wie `x`. Unter
   einer solchen zulässigen Konfiguration kann ein Angreifer Tokens für jede
   bekannte aktive User-ID signieren und deren in der DB hinterlegte Rolle
   übernehmen; der `tid`-Claim kann wegen Legacy-Kompatibilität fehlen.
2. Der aktiv dokumentierte SQLite→SQLCipher-Konverter kann Trigger oder Views
   wegen falscher Erstellungsreihenfolge verlieren, Fehler nur ausgeben und die
   unvollständige Zieldatenbank trotzdem als erfolgreich aktivieren. Er nimmt
   den Schlüssel zusätzlich über Prozessargument und gibt ihn im Klartext aus.

Zusätzlich bestehen P1 in Support-Bundle-Secrets, Audit-Verkettung,
Client-/Tenant-Offboarding, DSAR-Vollständigkeit, widersprüchlicher Retention,
Restore-Reaktivierung, Backup-Authentizität, Tenant-Krypto/TOTP sowie im
Browser-Token-Lifecycle. Zwei Datenschutzthemen bleiben P2 beziehungsweise bei
EU-/DE-Echtdaten fachlich auf P1 hochzustufen.

## Stabiles Findings-Register

### Datenlebenszyklus und Datenschutz

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `PRIV-001` | P1 | offen | Client-Löschung sperrt Zugriff und verarbeitet alle Kinddaten nach einem expliziten Lifecycle |
| `PRIV-002` | P1 | offen | DSAR-/Portabilitätsexport ist vollständig, versioniert und fail-closed |
| `PRIV-003` | P1 | offen | Retention unterscheidet Drafts, finale Belege, Referenzen und Legal Holds |
| `PRIV-004` | P1 | offen | Tenant- und User-Offboarding besitzt Export-, Sperr-, Lösch- und Bestätigungsworkflow |
| `PRIV-005` | P1 | offen | Restore reaktiviert kein bereits gelöschtes oder anonymisiertes Subjekt |
| `PRIV-006` | P1 | offen | Invite-/Reset-Secrets erscheinen nie in Pfaden, Logs oder Support-Bundles |
| `PRIV-007` | P2/P1 EU-DE | offen | Zweck, Rechtsgrundlage, Notice und gegebenenfalls Consent sind nachweisbar |
| `PRIV-008` | P2 | offen | Audit-, Signatur- und Browserdaten besitzen ausführbare Retention/Anonymisierung |

### Secrets, Kryptografie und Nachweis

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `SEC-001` | P1 | offen | Support-Bundles und Log-Endpoints geben ausschließlich allowlistete, redigierte Betriebsdaten aus |
| `SEC-002` | P0 konditional | offen | Production erzwingt nicht erratbare JWT-Schlüssel und einen festen Algorithmusvertrag |
| `SEC-003` | P1 | offen | Audit-Einträge bilden auch unter Parallelität genau eine verifizierbare Kette |
| `SEC-004` | P0 konditional | offen | SQLCipher-Konversion ist secret-safe, vollständig, atomar und parity-geprüft |
| `SEC-005` | P1 | offen | sensitive Tenant-/TOTP-Daten sind tatsächlich verschlüsselt und Schlüsselrotation ist verlustfrei |
| `SEC-006` | P2 | offen | eine byte-sichere Passwortpolicy gilt identisch für jeden Auth-Pfad |
| `SEC-007` | P1 | offen | Backup-Manifest und Artefakt sind authentisch, nicht nur gegen Zufallskorruption gehasht |

### Browser und Reporting

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `WEB-001` | P1 | offen | Reporting-Tokens und Logout besitzen einen gemeinsamen, beweisbaren Session-Lifecycle |

Ein Finding darf erst nach rotem Negativtest, Produktfix, vollständigem Gate und
dokumentiertem Fixcommit geschlossen werden. Ein geändertes Testorakel allein
schließt keinen Befund.

## Reproduktions- und Evidenzledger

| Scope | Methode | Reproduziertes Ergebnis |
|---|---|---|
| Client-Lifecycle | isolierte SQLite-Serviceausführung | Client tombstoniert; WealthPosition, ClientLogin und User blieben aktiv |
| Export-Fail-soft | Pflicht-Tabelle vor Export entfernt | Sektion wurde `[]`/`count=0`; kein Unvollständigkeitsstatus |
| Restore-Erasure | Backup → Client löschen → altes Backup restaurieren | personenbezogene Client-Row war wieder vorhanden |
| Support-Redaction | subprocess mit sieben eindeutigen Canaries | DB-Password, KEK, API-Key, Webhook und DSN blieben sichtbar; nur JWT-/SMTP-Secret wurde redigiert |
| Production-JWT | direkte `Settings(..., app_env='production')`-Validierung | `secret_key='x'`, `algorithm='HS256'`, leere KEK wurden akzeptiert |
| Audit-Parallelität | zwei SQLAlchemy-Sessions auf frischer DB | zwei Rows, beide gegen leere Genesis gehasht; kein `previous_hash`-Feld |
| SQLCipher-Schema | Source mit Tabelle, Trigger und View in Tool-Reihenfolge kopiert | Trigger scheiterte vor Tabelle; Ziel enthielt Tabelle+View ohne Trigger |
| Passwortbytes | echte installierte bcrypt-5.0.0-Runtime | Schema akzeptierte 73 ASCII-/80 UTF-8-Bytes; Hashing warf jeweils `ValueError` |
| Browser-Logout | lokaler Callgraph-/Negativtestaudit | Test prüft nur lokalen Token-Clear; serverseitiger Logoutfehler wird geschluckt, Reporting-Storage bleibt getrennt |
| Cache/Background | statisches Cache-Key-/Invalidierungs-/Scheduler-Inventar | kein neuer separater P0/P1; bestehende `REP-005`/`OPS-004` bleiben offen |

Alle Canaries sind synthetisch. Kein realer Schlüssel, Token oder Kundendatensatz
wurde für die Reproduktionen verwendet.

## Datenlebenszyklus und Datenschutz

### `PRIV-001` – Client-DELETE hinterlässt aktive Subjektdaten und sperrt den Export

`routers/clients.py::delete_client` setzt nur `Client.deleted_at`. In einer
gezielten Reproduktion blieben eine `WealthPosition`, der `ClientLogin` und der
verknüpfte `User` aktiv. `services/auth.py::get_linked_client_for_user_or_404`
blockiert danach zwar das Portal, aber auch der offizielle Export verwendet die
Active-Client-Prüfung und ist nach der Tombstonierung nicht mehr erreichbar.
`scripts/data_integrity_audit.py` bezeichnet aktive Kinder eines gelöschten
Clients zugleich ausdrücklich als Orphans.

**Fixvertrag:** Lifecycle `active → closing/legal_hold → erased/anonymized`.
Login, Refresh-Familien und Sessions werden transaktional gesperrt. Jede
Client-/Mandats-Kindtabelle erhält eine dokumentierte Klassifikation
`retain`, `anonymize` oder `delete`. Eine DPO-/Operatorrolle kann den
vollständigen Export auch nach der Tombstonierung erzeugen. Der End-to-End-Test
prüft alle Kinder, Tokens, Portalzugriff und Export vor und nach jedem Zustand.

### `PRIV-002` – DSAR-/Portabilitätsexport ist unvollständig und fail-soft

`services/data_export.py` exportiert unter anderem keine `client_logins` samt
verknüpftem User, keine `portfolio_handoffs` und keine `optimizer_runs`.
Mehrere Sektionen fangen pauschal `Exception` und liefern `[]`. In der
Reproduktion ergab eine entfernte Tabelle `wealth_positions=[]`, `count=0` und
keinen Fehler- oder Unvollständigkeitsmarker; der Export sah erfolgreich aus.

**Fixvertrag:** Eine versionierte, deklarative Exportregistry nennt jede
personen- oder mandatsbezogene Tabelle und jedes Pflichtfeld. Das Exportmanifest
enthält Schema-Version, Status, Row Count, Zeitbereich und Fehler pro Sektion.
Fehlt eine Pflichtsektion, darf kein `complete=true` oder erfolgreicher
Auslieferungsstatus entstehen. Ein Sentinel-Test verteilt eindeutige Werte über
alle registrierten Datentypen und beweist deren Export. Das Artefakt wird
verschlüsselt, befristet, gehasht und die Auslieferung auditiert; Credential-
Hashes und Schlüsselmaterial sind explizit ausgeschlossen.

### `PRIV-003` – 90-Tage-Delete widerspricht dem eigenen 10-Jahres-Vertrag

`services/data_export.py` nennt zehn Jahre für Recommendation Runs, Positionen
und Holdings. `services/recommendation_run_cleanup.py` löscht dieselben Daten
standardmäßig nach 90 Tagen physisch. Die Kandidatenauswahl prüft weder
`Final`/`Draft` noch Referenzen, Mandatsschluss, `retain_until` oder Legal Hold.
Der bestehende Test erwartet diese physische Löschung sogar.

**Fixvertrag:** Kurze Retention ist nur für explizit abgebrochene,
unreferenzierte Drafts zulässig. Finale oder in AdvisoryLog, Vertrag, Handoff
oder Publikation referenzierte Entscheidungsbelege bleiben bis zum fachlich und
rechtlich ermittelten `retain_until` erhalten. Legal Hold übersteuert jede
Bereinigung. Zeitbasierte Tests beweisen, dass Final-/referenzierte Rows nach 90
Tagen bestehen und nur der zulässige Draft entfernt wird.

### `PRIV-004` – Tenant-/User-Offboarding fehlt

Die Tenant-Routen bieten Update, Deaktivierung und User-Zuweisung, aber keinen
vollständigen Export-/Löschworkflow. Aktivierte User besitzen ebenfalls keinen
Delete-/DSAR-Prozess; DELETE gilt nur für noch nicht aktivierte Einladungen.

**Fixvertrag:** Idempotenter Workflow
`freeze → Export+Hash → Legal-Hold-/Owner-Freigabe → Session-Sperre →
Anonymisierung/Löschung → Backup-Ablauf → Löschbestätigung`. Ein vollständig
besetzter Zwei-Tenant-Test prüft Cross-Tenant-Isolation, Wiederholungssicherheit,
alle Kinder und den Post-Restore-Zustand.

### `PRIV-005` – Altes Restore reaktiviert gelöschte Personen

`services/backup.py` sichert und restauriert die komplette SQLite-Datenbank.
Ein außerhalb des Backups geführtes Erasure-Ledger oder eine Post-Restore-
Reconciliation existiert nicht. Reproduktion: Backup mit einem Client erzeugt,
Client gelöscht, altes Backup restauriert; die personenbezogene Row war wieder
vorhanden.

**Fixvertrag:** Ein unveränderliches, vom Datenbackup getrenntes
Erasure-/Anonymisierungsledger wird nach jedem Restore zwingend eingespielt.
Readiness bleibt bis zum erfolgreichen Replay blockiert. Lokale und Offsite-
Backups besitzen nachweisbare Expiry-/Deletion-Acknowledgements. Der Restore-
Test beweist, dass ein zuvor gelöschtes Subjekt nach altem Restore gelöscht oder
irreversibel anonymisiert bleibt.

### `PRIV-006` – Invite-Token steht im Log- und Support-Bundle-Pfad

`routers/auth.py` bietet Invite-Preview mit Token im URL-Pfad. Die
Request-Middleware protokolliert den rohen Pfad; die Redaction in
`services/maintenance.py` erkennt Bearer- und `token=`-Muster, nicht jedoch
`/invite/{token}`. Ein direkter Canary blieb nach `redact_log_lines()`
unverändert. Support-Bundles übernehmen diese Logzeilen.

**Fixvertrag:** One-Time-Secrets werden nie als Path- oder Queryparameter
transportiert. Falls eine Übergangsroute bestehen muss, redigiert die Middleware
vor jedem Log anhand des Route-Templates. Canary-Tests prüfen Live-Log,
Rotationen, Proxylog und Support-ZIP auf Tokenfreiheit. Dies vertieft
`OPS-008`; es ist kein separater Freigabepfad.

### `PRIV-007` – Rechtsgrundlage und Notice sind nicht nachweisbar

Die Anwendung speichert umfangreiche Personen-, Familien-, Arbeits-, Vermögens-
und Vorsorgedaten. Gefunden wurde nur ein AVV-Unterzeichnungsdatum am Tenant,
aber kein versionierter Nachweis für Zweck, Rechtsgrundlage, zugestellte Notice
oder – soweit tatsächlich Rechtsgrundlage – Einwilligung und Widerruf.

**Fixvertrag:** Zweckregister pro Jurisdiktion mit Rechtsgrundlage,
Notice-Version, Zeitpunkt und Quelle. Consent wird nur dort verwendet, wo er
rechtlich erforderlich ist; Widerruf stoppt optionale Verarbeitung. Nachweise
gehören in Export und Audit. Die fachliche/rechtliche Freigabe erfolgt durch den
verantwortlichen Owner/DPO, nicht durch Code allein.

### `PRIV-008` – Retention für Audit, Signaturen und Browserdaten ist nicht ausführbar

Audit- und Vertragsmodelle halten Usernamen, IP-Adressen, Vorher-/Nachherwerte,
Signaturbild, Namen und Dokumentpfade. Ein ausführbarer `retain_until`-/Legal-
Hold-/Anonymisierungsprozess fehlt. Die Haupt-App entfernt beim Logout Tokens,
aber nicht alle client-/mandatsbezogenen LocalStorage-Präferenzen.

**Fixvertrag:** Jede sensible Klasse erhält Retention-Policy, `retain_until` und
Legal Hold. Identität und unveränderlicher Beweis werden so getrennt, dass eine
zulässige Pseudonymisierung die technische Beweiskette nicht zerstört. Browser-
Daten sind nach Tenant/User namespaced und werden bei Logout, Löschung und
Offboarding entfernt. Tests nutzen steuerbare Zeit, Legal Hold und ein
Shared-Workstation-Szenario.

## Secrets, Kryptografie und Nachweis

### `SEC-001` – Support-Bundle redigiert bekannte Produktionssecrets nicht

`services/maintenance.py::_SENSITIVE_SETTING_KEYS` ist eine unvollständige
Blocklist. Der folgende subprocess-basierte Canary wurde auf dem auditierten
Stand ausgeführt:

```text
database_url                      -> postgresql+psycopg://dbuser:DBPASS@dbhost/db
tenant_master_kek                 -> MASTER-KEK
alphavantage_api_key              -> ALPHA-KEY
market_data_alert_webhook_url     -> https://hooks.example/SECRET-WEBHOOK
telemetry_dsn                     -> https://PUBLIC:SECRET@telemetry/42
secret_key                        -> ***REDACTED***
smtp_password                     -> ***REDACTED***
```

`create_support_bundle()` schreibt den Snapshot in `system-info.json`.
`tail_app_log()` liefert über den separaten Systemendpoint zudem rohe Logzeilen;
die Rollenbreite dieses Endpoints ist bereits in `AUTH-TEN-06` erfasst.

**Fixvertrag:** Supportdiagnostik verwendet eine kleine positive Allowlist,
nicht eine wachsende Secret-Blocklist. Secretfelder werden als `SecretStr` oder
äquivalent modelliert. Datenbank-URLs werden strukturell geparst und Credentials
vollständig entfernt; `*_api_key`, KEK, DSN, Webhook-Token und alle URLs mit
Userinfo sind verboten. Auch der Logs-Endpoint durchläuft dieselbe Redaction.
Bundleverzeichnis/-datei erhalten restriktive Rechte und TTL. Canary-Tests setzen
für jedes Settings-Feld einen eindeutigen Secretwert und durchsuchen JSON, ZIP,
Logs und Dateinamen byteweise.

### `SEC-002` – Production akzeptiert `secret_key='x'`

`config.py` lehnt in Staging/Production nur den exakten
`DEFAULT_SECRET_KEY` ab. Länge, Entropie und Wiederverwendung werden nicht
geprüft; `algorithm` ist ein freier String. Reproduktion:

```text
Settings(app_env='production', secret_key='x', ...)
=> {'secret_key': 'x', 'algorithm': 'HS256', 'tenant_master_kek': ''}
```

Bei HS256 reicht die Kenntnis dieses akzeptierten Schlüssels zur Signatur eines
Tokens für jede bekannte aktive User-ID. `get_current_user()` lädt die Rolle
zwar aus der Datenbank, der Angreifer übernimmt damit aber genau diese Rolle;
ein fehlender `tid` wird als Legacy-Token akzeptiert. Deshalb ist dies ein
bedingter P0: Die Schwachkonfiguration ist nicht nur möglich, sondern wird vom
Production-Gate ausdrücklich akzeptiert.

**Fixvertrag:** Algorithmus ist ein festes Literal beziehungsweise eine
versionierte, eng begrenzte Allowlist. Production verlangt mindestens 256 Bit
zufälliges Schlüsselmaterial aus Secret Manager/HSM, lehnt bekannte Muster,
kurze Werte und Wiederverwendung als DB-/KEK-/Webhook-Key ab und startet sonst
nicht. JWT enthält `iss`, `aud`, Key-Version/`kid` und einen dokumentierten
Rotationsvertrag mit Überlappungsfenster. Tests decken schwache/kurze Keys,
unbekannte Algorithmen, falsche Audience/Issuer, Rotation und alte Keys ab.

### `SEC-003` – Die Audit-„Hashkette“ kann unter Parallelität verzweigen

`services/audit.py::log` liest den neuesten AuditLog ohne Lock oder Sequenz,
berechnet daraus `previous_hash` und fügt danach eine Row ein. Das Modell
persistiert nur `integrity_hash`, nicht `previous_hash` oder eine Sequenz; ein
vollständiger Runtime-Verifier wurde nicht gefunden. In einer Zwei-Session-
Reproduktion lasen beide Transaktionen die leere Wurzel und erzeugten zwei
unterschiedliche erste Hashes. Der zweite Eintrag verknüpfte nicht auf den
ersten. Die vorhandenen Tests prüfen Unveränderlichkeit und verschiedene Hashes,
nicht die lineare Parallelitätsinvariante.

**Fixvertrag:** Append erhält eine DB-sequenzierte Position und den explizit
persistierten Vorgängerhash. PostgreSQL verwendet Row-/Advisory-Lock oder einen
atomaren Append-CAS; SQLite serialisiert denselben Vertrag. Unique-/Check-
Constraints verhindern zwei Nachfolger derselben Sequenz. Ein Verifier prüft
Genesis, jeden Link, Payloadversion und Ende. Für Manipulationsschutz außerhalb
der DB werden periodische signierte/HMAC-Checkpoints mit getrenntem Schlüssel
beziehungsweise unveränderlichem Ziel benötigt. Echte Zwei-Session-/Zwei-
Prozess-Tests müssen genau eine lineare Kette beweisen.

### `SEC-004` – Der dokumentierte SQLCipher-Konverter kann unvollständig „erfolgreich“ sein

`docs/SQLCIPHER_PREP.md` empfiehlt aktiv:

```text
python migrate_to_sqlcipher.py --key "..."
```

`migrate_to_sqlcipher.py` liest den Schlüssel aus der Prozessliste und gibt
anschließend `DB_KEY=<echter Schlüssel>` aus. Es kopiert die Live-Datei per
`shutil.copy2`, hinterlässt ein vollständiges Klartextbackup, schluckt einzelne
Schemafehler, kopiert Daten mit `INSERT OR IGNORE` und verifiziert nur
`SELECT 1` plus Tabellenanzahl. Danach löscht es die Live-Datei und benennt das
Ziel um.

Die Erstellungsreihenfolge `ORDER BY type DESC, name` wurde mit einer Quelle
`view → trigger → table` reproduziert: Der Trigger schlug vor seiner Tabelle
fehl, wurde nicht erneut angelegt, die Zieldatenbank enthielt Tabelle und View,
aber keinen Trigger. Dieser Zustand würde die aktuelle Erfolgsprüfung bestehen.

**Fixvertrag:** Aktuelles Tool und Runbook bleiben bis zum Ersatz ausdrücklich
gesperrt. Konversion erfolgt offline/exklusiv; Schlüssel kommen aus Secret-FD,
Secret Manager oder interaktivem nicht geloggtem Kanal, nie aus argv/stdout.
SQLite Online-Backup/SQLCipher-Export oder ein anderer bewiesener Mechanismus
erstellt einen konsistenten Snapshot. Schemaobjekte werden dependency-safe
materialisiert. Vor Cutover müssen Tabellen, Spalten, Rows, Indizes, Trigger,
Views, FKs, Constraints, `integrity_check`, Audit-Immutable-Trigger und
anwendungsspezifische Hashes exakt übereinstimmen. Das Backup ist verschlüsselt
und authentisiert. Cutover ist atomar und besitzt getesteten Rollback; die
Originaldatei wird erst nach vollständigem Nachweis behandelt.

### `SEC-005` – Tenant-Krypto ist nicht in den Echtdatenpfad integriert

`models/users.py::User.totp_secret` speichert den Base32-Seed im Klartext.
`services/tenant_crypto.py` implementiert zwar Envelope-Helfer, sie werden laut
Code- und Landmine-Guard außerhalb der Tests nicht von Geschäftsmodellen
verwendet. `rotate_tenant_dek()` überschreibt den DEK sofort; der eigene
Docstring warnt vor Datenverlust, sobald produktive Ciphertexte daran hängen.
Production verlangt `tenant_master_kek` derzeit nicht; `SEC-001` zeigt zudem,
dass der Wert im Support-Bundle offengelegt würde.

**Fixvertrag:** Zuerst Feldklassifikation und realistischer At-rest-Vertrag;
danach tatsächliche Integration für TOTP und ausgewählte sensitive Felder.
Master-Key aus HSM/Vault, in T2/T3 fail-closed erforderlich. Ciphertexte tragen
Tenant, Algorithmus und Key-Version. Rotation ist gestuft: neuen Key anlegen,
dual read, kontrolliert re-encrypten, Vollständigkeit prüfen, alten Key erst
danach sperren. Der destruktive Helper darf nicht produktiv aufrufbar bleiben.
Tests decken Restore, Cross-Tenant-Decrypt, Mischversionen, Abbruch und Resume ab.

### `SEC-006` – Passwortpolicy ist nicht byte-sicher und divergiert

`services/auth.py::hash_password` nutzt direkt `bcrypt`, das in der installierten
Version Passwörter über 72 Bytes mit `ValueError` ablehnt. Die User-Schemas
akzeptierten sowohl 73 ASCII-Zeichen als auch 20 Emoji/80 UTF-8-Bytes; beide
Reproduktionen endeten beim Hashen mit `ValueError`. Einige Auth-Pfade prüfen
acht Zeichen, andere zehn, und `requirements.txt` pinnt `passlib[bcrypt]`, nicht
die tatsächlich direkt importierte `bcrypt`-Version.

**Fixvertrag:** Eine zentrale Policy gilt für Create, Invite, Bootstrap,
Change, Reset und Admin-Reset. Entweder versioniertes Argon2id/bcrypt-sha256 mit
Migration oder bei direktem bcrypt ein explizites UTF-8-Byte-Limit von 72; keine
stille Trunkierung. Ungültige Eingaben ergeben 422, nie 500. Dependencies sind
direkt und reproduzierbar gepinnt. Tests: 72/73 ASCII-Bytes, mehrbyteiges Unicode,
minimale Länge, sehr große Eingabe und bestehender Hash-Migrationspfad.

### `SEC-007` – SHA-Sidecar beweist keine Backup-Authentizität

`services/backup.py` schreibt einen unkeyed `.sha256`-Sidecar neben das Backup,
kopiert beide gemeinsam Offsite und vertraut beim Restore auf diesen Wert. Das
erkennt zufällige Korruption, aber ein Angreifer mit Schreibrecht kann Backup
und Sidecar gemeinsam ersetzen. Der bestehende Text nennt dies stellenweise
„Integritätsgarantie“.

**Fixvertrag:** Versioniertes Manifest mit Artifact-ID, Schema-Head,
Erstellungszeit, Source/Scope, Hash und Schlüsselversion wird mit getrennt
verwaltetem HMAC-/Signaturschlüssel authentisiert und in einem unveränderlichen
oder object-locked Ziel gespeichert. Restore verifiziert Signatur, Hash,
Artifact-ID und erwarteten Release-/Schema-Vertrag vor jedem Schreibzugriff.
Dies ergänzt `OPS-003` und `OPS-009`; es ersetzt nicht den echten Restore-Drill.

## Browser- und Reporting-Lifecycle

### `WEB-001` – Haupt-App kann Logout anzeigen, während Reporting weiter autorisiert bleibt

`resolveReportingAppUrl()` übergibt das Access-Token als URL-Fragment an eine
separate Reporting-Webapp. Diese speichert es in eigenem `sessionStorage`; vier
API-Module lesen zusätzlich einen Legacy-Wert aus `localStorage`. Der
Haupt-App-Logout fängt jeden Fehler von `POST /auth/logout`, protokolliert ihn nur
in der Konsole, löscht lokale Tokens und zeigt anschließend die Loginansicht.
Ein bereits geöffneter externer Reporting-Tab besitzt einen getrennten
Storage-Kontext. Schlägt der serverseitige Widerruf fehl, bleibt dessen Token bis
zum Ablauf – Default acht Stunden – gültig, sobald das Backend wieder erreichbar
ist. Ein Test prüft nur, dass die Haupt-App beide lokalen Tokens löscht.

**Fixvertrag:** Kein langlebiger Bearer wird zwischen Apps übergeben. Die
Haupt-App fordert einen kurzlebigen, einmalig atomar verbrauchten Handoff-Code
an; Reporting tauscht ihn serverseitig gegen eine gebundene Session mit
HttpOnly/Secure/SameSite-Cookie oder gleichwertigem Desktopvertrag. Erfolgreicher
Logout widerruft Sessionversion und Refresh-Familie serverseitig und wird in
allen Oberflächen wirksam. Bei Netzwerkfehler darf die UI nur „lokal getrennt,
serverseitiger Widerruf ausstehend“ anzeigen und muss Retry/Expiry kenntlich
machen. Legacy-LocalStorage- und Production-`VITE_5EYES_TOKEN`-Fallbacks werden
entfernt. Tests simulieren Logout-500/Netzausfall, offenen Reporting-Tab,
Shared-Workstation, erfolgreichen Widerruf und beweisen 401 in allen Tabs.

## Abgegrenzte Cache-/Background-Nachprüfung

Die lokale Nachprüfung von Advisory-Cache, Market-Data-Cache, Scenario-Cache,
Backup-/Price-Scheduler und SessionLocal-Backgroundjobs ergab **keinen neuen
eigenständigen P0/P1** außerhalb der bereits registrierten Verträge:

- Advisory-Publikationscache und fehlende workerweite Invalidierung bleiben
  `REP-005` im ersten Post-Commit-Audit.
- Backup-/Marktdaten-Singletons, Multiworker-Races und gekoppelte Scheduler-
  Schalter bleiben `OPS-004` im Auth-/Execution-/Operations-Audit.
- Market-Data-Cache ist bewusst global nach Marktidentifier; Scenario-Cache
  bindet CMA-/Inputidentität. In dieser Runde wurde kein reproduzierbarer
  Cross-Tenant-Datentransfer über diese beiden Caches gefunden.

Diese Aussage ist eine Scope-Abgrenzung, keine Freigabe der bereits offenen
`REP-005`-/`OPS-004`-Befunde.

## Verbindliche Umsetzungsreihenfolge für Claude

### Block A – Sofortige Eindämmung

1. `SEC-004`: SQLCipher-Tool und aktive Anleitung sperren; keine Live-Migration
   damit ausführen.
2. `SEC-002`: Production-Start mit schwachem JWT-Key oder unbekanntem Algorithmus
   fail-closed machen.
3. `SEC-001`/`PRIV-006`: Support-Bundle-/Log-Secretpfade schließen; vorhandene
   Bundles/Logs als potenziell sensibles Material behandeln.
4. `WEB-001`: Browser-Handoff und Logout-Fehler sichtbar und servergebunden
   machen.

### Block B – Subjektdaten und Retention

1. Dateninventar/Exportregistry erstellen.
2. Client-, User- und Tenant-Lifecycle gemeinsam modellieren.
3. Retention/Legal Hold für Draft-, Final-, Signatur-, Audit- und Handoff-Daten
   durchsetzen.
4. Erasure-Ledger sowie Post-Restore-Reconciliation implementieren.
5. DSFA, Zweck-/Rechtsgrundlagen- und Notice-Nachweis durch Owner/DPO freigeben.

### Block C – Kryptografischer Nachweis

1. Audit-Append linear und verifizierbar machen.
2. Backupmanifest authentisieren und Restore daran binden.
3. Tenant-/TOTP-Verschlüsselung mit versionierter, verlustfreier Rotation
   integrieren.
4. Passwortpolicy zentralisieren und byte-sicher migrieren.
5. SQLCipher-Ersatzkonverter erst danach mit vollständiger Parität und
   Restore-/Rollbacktest freigeben.

### Block D – Regression und Zielumgebungen

Neue fokussierte Suites mindestens:

- `tests/test_support_bundle_secret_allowlist.py`
- `tests/test_production_jwt_key_contract.py`
- `tests/test_audit_chain_concurrency.py`
- `tests/test_sqlcipher_migration_integrity.py`
- `tests/test_tenant_sensitive_field_encryption.py`
- `tests/test_password_policy_bytes.py`
- `tests/test_data_subject_lifecycle.py`
- `tests/test_data_export_completeness.py`
- `tests/test_retention_and_legal_hold.py`
- `tests/test_post_restore_erasure_reconciliation.py`
- `tests/test_reporting_session_logout_contract.py`
- `tests/test_backup_manifest_authenticity.py`

Parallelitäts- und Kettentests müssen auf echtem PostgreSQL laufen; SQLCipher-
und Backup-/Restore-Tests auf realem verschlüsseltem SQLite-Artefakt. Browser-
Tests müssen Haupt-App und separate Reporting-Origin gemeinsam steuern. Reine
String-/Mocktests reichen für diese Verträge nicht.

## Definition of Done

Der Datenlebenszyklus-/Krypto-/Browser-Block ist erst geschlossen, wenn:

- [ ] beide bedingten P0 mit Negativtest und Produktfix geschlossen sind;
- [ ] Support-ZIP, Logendpoint, rotierte Logs und Proxylogs jeden Secret-Canary
      vollständig redigieren;
- [ ] ein vollständiger DSAR-Export jeden registrierten Datentyp enthält und bei
      fehlender Pflichtsektion fail-closed endet;
- [ ] Client-/User-/Tenant-Offboarding einschließlich Tokens, Legal Hold und
      Backup-Ablauf end-to-end bewiesen ist;
- [ ] ein altes Restore kein gelöschtes Subjekt reaktiviert;
- [ ] Retention Final-/referenzierte Belege schützt und nur erlaubte Drafts
      entfernt;
- [ ] parallele Auditwrites exakt eine vollständig verifizierbare Kette ergeben;
- [ ] TOTP/sensitive Felder verschlüsselt und Rotation/Restore verlustfrei sind;
- [ ] Passwortgrenzen bei ASCII und Unicode identisch 422 statt 500 liefern;
- [ ] Reporting nach Logout in jedem Tab 401 erhält und keine langlebigen
      Bearer-Tokens in URL-/Web-Storage-Handoffs verbleiben;
- [ ] Backup-Authentizität sowie tatsächlicher Restore aus dem authentisierten
      Artefakt nachgewiesen sind;
- [ ] vollständiger Backend-, PostgreSQL-, SQLCipher-, Reporting-/Browser- und
      Deployment-Gate auf demselben Fixcommit grün ist;
- [ ] Owner, Security, DPO/Compliance und Operations die jeweils fachlichen
      Nachweise freigegeben haben.

## Claude-Startcheckliste

1. Zuerst dieses Dokument und danach beide Post-Commit-Audits vollständig lesen.
2. Keine historische „grün“-/„fertig“-Aussage als Freigabe interpretieren.
3. Finding-ID im roten Testnamen oder Testdocstring referenzieren.
4. Pro Commit nur einen atomaren Vertrag oder eng gekoppelten Block schließen.
5. Keine schwachen Defaults, Seeder oder Broad-Catches als Kompatibilitätspfad
   einführen.
6. Keine Datenlöschung, Schema-Konversion, Restore- oder Key-Rotation auf realen
   Daten ohne expliziten Owner-Runbookschritt ausführen.
7. Nach jedem Fix fokussierten Ring und am Ende vollständigen Gate auf exakt
   demselben Commit dokumentieren.
8. Releaseentscheidung bleibt `blocked`, bis die Definition of Done vollständig
   erfüllt und extern freigegeben ist.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/SQLCIPHER_PREP.md`
5. `docs/compliance/dsfa-datenschutz-folgenabschaetzung.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- vorhandene Dokumentkonsistenztests: `87 passed`;
- Finding-Register: 16 eindeutige IDs, 16 zugehörige Detailsektionen;
- neue/relative lokale Links im Fünf-Pfade-Batch: 14 geprüft, 14 gültig;
- Markdown-Codefences: paarig;
- `git diff --check`: grün;
- sichtbares Dokumentmanifest: exakt fünf Pfade;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
