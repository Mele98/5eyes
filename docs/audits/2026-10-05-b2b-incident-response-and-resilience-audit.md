---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-incident-response-and-resilience-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/b2b-incident-resilience-audit"
audited_repository_head: "8dfd6cc13a7869e1996331e5d226551fc441a6ee"
prior_coverage_audit_path: "C:/Users/Emanuele/Documents/ChatGPT/5eyes wird zu Ares/asset-allocation-stochastic-core/docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md"
prior_coverage_audit_finding: "B2B-COVERAGE-006"
readiness_plan_path: "C:/Users/Emanuele/Documents/ChatGPT/5eyes wird zu Ares/asset-allocation-stochastic-core/docs/compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md"
audit_mode: "read_only_audit_inventory_static_code_document_and_test_evidence_review"
audit_mutated_product_code: false
scope: "disaster recovery plan, backup/restore implementation, restore-drill evidence, breach/incident process, resilience scenarios (ransomware, vendor outage, credential compromise, tenant data leak), monitoring/alerting, external penetration test status"
decision: "incident response and resilience remain substantially planned, not practised; close contact-chain, Postgres-restore, offsite-activation and breach-runbook gaps before any T2/T3 go-live"
---

# B2B-Incident-Response- und Resilienz-Audit (Runde 5)

## Geltung und Quellenrangfolge

Dieser Audit ist Runde 5 der im B2B-Trust-/Compliance-Pre-Implementation-
Coverage-Audit (separates Repository, siehe `prior_coverage_audit_path` im
Frontmatter dieses Dokuments) festgelegten Reihenfolge und schliesst
`B2B-COVERAGE-006`
("Incident Response und Resilienz sind geplant, nicht geübt"). Er ist ein
read-only Evidenz-Audit auf dem realen 5eyes-Repository (nicht dem
Audit-Quelldokument-Repository). Bei Widersprüchen gelten aktueller
Produktcode und reproduzierte Tests zuerst, danach dieses Dokument, danach der
Coverage-Audit und der Readiness-Plan. Dieses Dokument erteilt keine Rechts-,
FINMA-, Security- oder Produktionsfreigabe und behauptet keine konkrete
RTO/RPO-Erreichbarkeit — nur was dokumentiert bzw. implementiert vorliegt.

## Kurzfazit

Der Coverage-Audit beschreibt den Zustand korrekt in der Grundtendenz
("geplant, nicht geübt"), aber in einem Detail bereits **veraltet**: Die
Protokolltabelle des DR-Plans ist entgegen der Behauptung in
`B2B-COVERAGE-006` **nicht mehr leer** — sie enthält einen Eintrag vom
2026-09-27 aus einem automatisierten, aber synthetischen SQLite-Sandbox-Drill
(`scripts/restore_drill.py`). Richtig bleibt: dieser Drill deckt **nur**
SQLite in einer isolierten Sandbox ab; ein PostgreSQL-Restorepfad existiert im
Produktcode **nicht**, Off-Site-Backup ist **nicht aktiviert**
(`backup_offsite_enabled` Default `False`), die Eskalations-Kontaktkette im
DR-Plan ist wörtlich als "(auszufüllen)" markiert, und für Ransomware,
Breach-Entscheidungsbaum, forensische Beweissicherung oder
Kommunikationsvorlagen wurde **kein** Dokument und **kein** Code gefunden.
Der externe Penetrationstest ist weiterhin nur Vorbereitung, nicht beauftragt.
Monitoring/Alerting existiert ausschliesslich als interne, optionale
Webhook-Mechanik für zwei enge Fälle (Backup-Fehler, Markt­daten-Abweichung)
plus reine Liveness-/Readiness-HTTP-Probes — keine externe
Uptime-Überwachung, kein PagerDuty/Opsgenie-Äquivalent.

## Findings-Register

| ID | Priorität | Status | Thema |
|---|---:|---|---|
| `IR-DRILL-001` | P1 | teilweise erledigt | Restore-Drill existiert und wurde einmal ausgeführt, aber nur synthetisch/SQLite, nicht gegen Postgres/Tier-2/3-Realinfrastruktur, und bisher kein zweiter (quartalsweiser) Durchlauf protokolliert |
| `IR-PG-RESTORE-001` | P0 für T2/T3 | offen | Kein PostgreSQL-spezifischer Backup-/Restore-Code im Produktcode; `services/backup.py` ist vollständig SQLite/SQLCipher-only |
| `IR-OFFSITE-001` | P1 | offen | Off-Site-Replikation ist implementiert und getestet, aber per Default deaktiviert und nirgends als aktiv belegt |
| `IR-DRP-SCOPE-001` | P1 | offen | DR-Plan deckt explizit nur T2/T3 ab; für T1 (Self-Hosted) existiert kein eigener DR-Plan |
| `IR-ESCALATION-CONTACT-001` | P0 | offen | Eskalations-Kontaktkette im DR-Plan ist ein unausgefüllter Platzhalter |
| `IR-BREACH-PROCESS-001` | P0 | offen | Kein Breach-/Incident-Response-Runbook; nur ein Ein-Satz-Vertragsversprechen (AVV-Template) und keine Vorlagen/Fristen/Rollen |
| `IR-RANSOMWARE-001` | P1 | offen | Keine einzige Erwähnung, Policy oder Prozedur zu Ransomware im gesamten Repository |
| `IR-VENDOR-OUTAGE-001` | P1 | teilweise vorhanden | Markt­daten-Provider-Ausfall hat passive technische Beobachtung (Multi-Provider, Health-Registry), aber keine dokumentierte Eskalations-/Incident-Prozedur |
| `IR-CREDENTIAL-COMPROMISE-001` | P1 | teilweise vorhanden | Technische Bausteine (Login-Guard, Session-Revocation bei Reset, 2FA) vorhanden, aber kein dokumentierter Incident-Response-Ablauf für kompromittierte Credentials |
| `IR-TENANT-LEAK-CONTAINMENT-001` | P1 | offen | Keine Admin-Funktion zur Tenant-Sperrung/-Eindämmung im Vorfall gefunden; nur präventive Isolation (RLS/`strict_tenant_isolation`), keine Post-Incident-Prozedur |
| `IR-MONITORING-001` | P1 | teilweise vorhanden | Nur interne Liveness-/Readiness-Probes + zwei enge Opt-in-Webhooks; keine externe Uptime-/Alerting-Lösung |
| `IR-PENTEST-001` | P0/P1 | offen | `PENTEST_PREPARATION.md` ist ausschliesslich Vorbereitung; kein Pentest beauftragt oder durchgeführt |

## Detailfindings

### `IR-DRILL-001` — Restore-Drill einmalig und nur synthetisch/SQLite

**Repository-Beleg:**
- `docs/deploy/disaster-recovery-plan.md:54-68` (Abschnitt 5 "Restore-Drill"):
  die Protokolltabelle enthält genau **eine** Zeile, datiert 2026-09-27,
  Backup-Stand "Dev-Sandbox (synthetisch, `scripts/restore_drill.py`)", RTO
  "15 ms (synthetische Mini-DB, nicht kapazitätsrelevant)", RPO "~0", Befunde
  "keine". Die zweite Tabellenzeile ist noch der leere Platzhalter
  (`| _…_ | _…_ | _…_ | _…_ | _…_ |`).
- `5eyes-backend/scripts/restore_drill.py:1-42` (Docstring
  "RESTORE-DRILL-NEVER-PERFORMED-001"): bestätigt explizit, dass die
  Protokolltabelle "seit Erstellung des Plans (2026-06-15) leer" war, bis
  dieses Skript sie einmalig befüllte. Das Skript läuft **immer** in einem
  frischen `tempfile.mkdtemp()`-Sandbox-Verzeichnis (Zeile 19-22), **nie**
  gegen `settings.db_path`/`settings.backup_dir`, mit einer minimalen
  synthetischen Tabelle statt echtem App-Schema (Zeile 23-29). Zeile 180-183
  im Skript-Output nennt selbst als offen: "ein Restore-Drill gegen einen
  echten Tier-2/3-Zielhost mit realer Infrastruktur... bleibt eine SEPARATE,
  weiterhin ausstehende Übung."
- `5eyes-backend/tests/test_restore_drill.py:1-109`: fünf Tests laufen den
  echten Skript-Code (nicht gemockt), aber ausschliesslich gegen die Sandbox;
  `test_drill_never_touches_real_settings_paths` (Zeile 52-68) verifiziert
  sogar strukturell, dass das Skript `config.settings` gar nicht importiert.

**Korrektur zum Coverage-Audit (`B2B-COVERAGE-006`):** Die dortige Aussage
"Seine Protokolltabelle ist leer" trifft auf den tatsächlichen
Repository-Stand zum Zeitpunkt dieser Prüfung **nicht mehr zu** — ein
Sandbox-Drill-Eintrag existiert bereits seit 2026-09-27. Weiterhin zutreffend
bleibt aber der Kern: kein Drill gegen reale Tier-2/3-Infrastruktur, keine
zweite (quartalsweise) Wiederholung protokolliert, und die Eskalations-
Kontaktkette bleibt leer (siehe `IR-ESCALATION-CONTACT-001`).

**Auditvertrag:** Mindestens ein Restore-Drill gegen eine reale
Tier-2/3-Zielinfrastruktur (echter Host, echte Backup-Grösse) durchführen und
protokollieren; danach den quartalsweisen Rhythmus tatsächlich einhalten statt
einmalig zu belegen.

### `IR-PG-RESTORE-001` — Kein PostgreSQL-Restorepfad im Produktcode

**Repository-Beleg:**
- `5eyes-backend/services/backup.py:1-697`: vollständig gelesen. Die einzige
  Datenbank-Technologie ist `sqlite3`/`sqlcipher3` (Imports Zeile 39/47,
  `_open_connection` Zeile 373-406). Kein `psycopg2`, kein `pg_dump`, keine
  PITR-Logik im gesamten Modul.
- Grep über `services/*.py` und `scripts/*.py` nach
  `pg_dump|psycopg2|PITR|postgres` (case-insensitiv) ergibt **ausschliesslich**
  einen Treffer in `scripts/restore_drill.py` — dort nur als Prosa-Hinweis auf
  eine **offene** Zukunftsaufgabe (Zeile 181-183: "Postgres+PITR,
  Off-Site-Ziel-Host" als "weiterhin ausstehende Übung"), kein Code.
- `docs/deploy/disaster-recovery-plan.md:23-24` selbst nennt den
  Postgres-Pfad nur als Ziel: "Postgres-Ziel: `pg_dump`/PITR, Roadmap #8/#15"
  — und Abschnitt 7 (Zeile 76-80) listet "Postgres + PITR (#8)" explizit unter
  "Offene technische Voraussetzungen".

**Auditvertrag:** Für T2/T3 (PostgreSQL) einen eigenen, getesteten
Backup-/Restore-Pfad implementieren (z. B. `pg_dump`/`pg_basebackup` + PITR)
und denselben Drill-Mechanismus wie für SQLite anwenden, bevor PostgreSQL
produktiv für Kundendaten genutzt wird.

### `IR-OFFSITE-001` — Off-Site-Backup implementiert, aber nicht aktiviert

**Repository-Beleg:**
- `5eyes-backend/services/backup.py:603-697` (`replicate_offsite`): Funktion
  existiert, kopiert Backup + `.sha256`/`.hmac256`-Sidecars via `rsync`/SSH an
  ein zweites CH-Rechenzentrum, fail-soft (wirft nie, Zeile 638-645).
- `5eyes-backend/config.py:238,240`: `backup_offsite_enabled: bool = False`
  und `backup_offsite_target: str = ''` — beide Defaults deaktiviert/leer.
- `docs/deploy/disaster-recovery-plan.md:30-38,76-80`: bestätigt selbst
  "**noch nicht scharf geschaltet** — braucht einmalig einen echten Ziel-Host
  + SSH-Zugang".
- `5eyes-backend/tests/test_offsite_backup_replication.py` existiert und
  testet den Mechanismus — das beweist nur Code-Korrektheit, nicht Aktivierung
  in einem realen Betrieb.

**Auditvertrag:** Für jeden produktiven T2/T3-Betrieb den Ziel-Host
einrichten, `backup_offsite_enabled=true` setzen und den aktiven Zustand
(nicht nur den Code) im DR-Plan/Betriebsnachweis dokumentieren.

### `IR-DRP-SCOPE-001` — DR-Plan gilt nur für T2/T3

**Repository-Beleg:**
- `docs/deploy/disaster-recovery-plan.md:3`: "gilt für T2/T3
  (betreiber-gehostet)" — explizite Scope-Einschränkung direkt im Titelblock.
  Kein eigenständiges DR-Dokument für T1 (Self-Hosted) gefunden (Grep über
  `docs/deployment/tier1-self-hosted.md` enthält keine RTO/RPO- oder
  Drill-Vorgabe für den Betreiber des Self-Hosted-Falls).

**Auditvertrag:** Entscheiden und dokumentieren, ob/welche
Backup-/Restore-Verantwortung bei T1 beim Berater selbst liegt, und falls ja,
eine eigene (ggf. schlankere) T1-Anleitung mit Backup-Erinnerung/Self-Service-
Restore-Doku ergänzen statt impliziter Fehlannahme.

### `IR-ESCALATION-CONTACT-001` — Eskalations-Kontaktkette unausgefüllt

**Repository-Beleg:**
- `docs/deploy/disaster-recovery-plan.md:70-74` (Abschnitt 6 "Rollen &
  Eskalation"): "**Eskalation:** definierte Kontaktkette (auszufüllen),
  EDÖB-Meldung bei Datensicherheitsverletzung mit hohem Risiko (revDSG)." —
  wörtlicher Platzhalter, keine Namen, Rollen, Telefonnummern oder
  Bereitschaftsregelung.

**Auditvertrag:** Reale Kontaktkette (Betreiber-Rollen, Vertretung,
Erreichbarkeit 24/7 falls zugesagt) ausfüllen und versioniert pflegen, bevor
ein produktiver T2/T3-Betrieb startet.

### `IR-BREACH-PROCESS-001` — Kein Breach-/Incident-Response-Runbook

**Repository-Beleg:**
- `docs/compliance/avv-template.md:49-50` (Pflicht 7): "**Meldung von
  Verletzungen der Datensicherheit** an die Mandantin **unverzüglich** (Ziel:
  < 24 h nach Kenntnis), mit allen für eine EDÖB-Meldung nötigen Angaben." —
  ein einzelner Vertragssatz, kein operativer Prozess: keine Triage-Schritte,
  keine Rollen/Rufnummern, keine Beweissicherungs-Checkliste, keine
  Kommunikationsvorlagen.
- `docs/deploy/disaster-recovery-plan.md:70-74`: einziger weiterer Treffer zu
  EDÖB-Meldung, ebenfalls ohne Prozessdetail (siehe
  `IR-ESCALATION-CONTACT-001`).
- Breite Suche über `docs/` nach `incident|breach|Datenschutzverletzung|
  EDÖB|Vorfall` ergab 15 Dateien; keine davon ist ein eigenständiges
  Incident-Response- oder Breach-Runbook — es sind ausschliesslich
  Compliance-Vorlagen (AVV, DSFA), Roadmap-/Planning-Listen und Architektur-
  ADRs, die das Thema nur nennen, nicht ausführen.
- `docs/compliance/dsfa-datenschutz-folgenabschaetzung.md` ist laut dem
  gelesenen Readiness-Plan (`TRUST-04`) selbst explizit eine "unausgefüllte
  Release-Blocker-Vorlage" — keine Ausnahme von diesem Befund.

**Auditvertrag:** Eigenständiges Incident-/Breach-Runbook erstellen:
24/7-Intake, Triage-Kriterien, Risikoentscheid, Beweissicherung, Rollen mit
Namen/Vertretung/Rufnummern, EDÖB-/Kunden-/Betroffenen-Meldevorlagen mit
Fristen, Eskalationspfad zu Subprocessors, und mindestens ein protokollierter
Tabletop-Test.

### `IR-RANSOMWARE-001` — Keine Ransomware-Erwähnung im gesamten Repository

**Repository-Beleg:**
- Case-insensitive Volltextsuche nach `ransomware` über das gesamte `docs/`
  -Verzeichnis ergab **null** Treffer. Es existiert keine Policy, kein
  Playbook, keine Erwähnung in Roadmap/Planning/ADRs.
- Die einzigen verwandten Konzepte sind generische Backup-/Restore-Bausteine
  (siehe oben) — diese schützen technisch potenziell auch gegen
  Ransomware-Datenverlust, sind aber nicht als Ransomware-Szenario
  durchgespielt oder dokumentiert (kein Übungsprotokoll, keine Entscheidung
  zu Lösegeldforderung/Strafverfolgung/Kommunikation).

**Auditvertrag:** Mindestens ein Ransomware-Szenario (Verschlüsselung der
Produktions-DB/-Host) gegen den bestehenden Backup-/Restore-Mechanismus
durchspielen und dokumentieren: Erkennung, Isolation, Restore-Weg,
Kommunikationsentscheidung, Lessons Learned.

### `IR-VENDOR-OUTAGE-001` — Markt­daten-Provider-Ausfall nur passiv beobachtet

**Repository-Beleg:**
- `5eyes-backend/services/market_data/provider_health_registry.py:1-6`:
  Modul-Docstring selbst: "Phase 1 is passive: the registry records provider
  failures and recoveries, but it does not trigger refreshes, rebalance
  decisions, or active failover tuning."
- `5eyes-backend/routers/health.py:90-95` (`/health/ready`): Preis-Status ist
  bewusst "informational, KEIN 503-Auslöser" — ein Ausfall des
  Marktdaten-Providers blockiert die App nicht, wird aber auch nicht aktiv
  eskaliert.
- `5eyes-backend/services/market_data/notifier.py:1-26`: Webhook-Alert
  existiert, aber nur für Cross-Validation-Abweichungen zwischen Providern
  (Median-Diff > Threshold), nicht für einen vollständigen Provider-Ausfall
  als Vorfall, und ist Opt-in (Default leer/no-op laut Docstring Zeile 7-8).

**Auditvertrag:** Dokumentieren, ab welcher Ausfalldauer/-schwere ein
Marktdaten-Providerausfall als Incident gilt, wer informiert wird, und ob ein
Secondary-Provider-Failover tatsächlich (nicht nur "Phase 1 passiv")
automatisiert werden soll.

### `IR-CREDENTIAL-COMPROMISE-001` — Technische Bausteine ohne dokumentierten Ablauf

**Repository-Beleg:**
- Technische Bausteine existieren (nicht neu geprüft, bereits in
  `docs/audits/2026-08-25-auth-execution-operations-followup-audit.md`
  dokumentiert): `AUTH-TEN-01` ("Recovery sowie Legacy-Self-/Admin-Reset
  widerrufen Sessions") ist dort als **offen (P1)** gelistet — selbst die
  technische Session-Revocation bei Credential-Reset ist laut dem jüngsten
  Folgeaudit nicht vollständig geschlossen.
- Keine eigenständige Incident-Response-Prozedur für "kompromittiertes
  Berater-/Admin-Konto" gefunden (kein Runbook-Dokument, keine
  Not-Workflow-Anleitung zu Mass-Logout/Mass-Secret-Rotation über alle
  Tenants eines Beraters).

**Auditvertrag:** Operativen Ablauf für Credential-Kompromittierung
dokumentieren: Erkennung/Meldung, sofortige Session-Invalidierung (abhängig
von Schliessung von `AUTH-TEN-01`), Zwangs-Passwortwechsel/2FA-Reset,
Prüfung auf Datenabfluss, Kundenkommunikation.

### `IR-TENANT-LEAK-CONTAINMENT-001` — Keine Post-Incident-Tenant-Sperrung gefunden

**Repository-Beleg:**
- Grep über `5eyes-backend` nach `suspend.*tenant|lock.*tenant|
  tenant.*suspend|tenant.*lock|disable.*tenant` traf 23 Dateien, darunter
  `services/tenant_licensing.py`; eine gezielte Prüfung dieser Datei auf
  `def .*suspend|def .*disable|def .*lock` ergab **keinen** Treffer — die
  23 Dateien behandeln präventive Tenant-**Isolation** (RLS, Autorisierung,
  Lizenzprüfung), nicht eine Admin-Aktion zur Notfall-Sperrung eines
  Tenants im Vorfall.
- Präventive Isolation ist an anderer Stelle bereits geprüft
  (`ADR-007-multi-tenancy-strategy.md`, `ADR-012-postgres-rls-tenant-isolation.md`)
  — das ist Schutz vor einem Leck, nicht Eindämmung **nach** einem
  vermuteten Leck.

**Auditvertrag:** Admin-Funktion/Runbook für sofortige Tenant-Sperrung
(Sessions killen, Zugriff read-only/gesperrt, Export für forensische
Prüfung) bei vermutetem Datenleck schaffen und testen.

### `IR-MONITORING-001` — Nur interne Probes und zwei enge Opt-in-Webhooks

**Repository-Beleg:**
- `5eyes-backend/routers/health.py:1-104`: `/health`, `/health/live`,
  `/health/ready`, `/health/db` — reine HTTP-Probes für
  Prozess-Orchestrierung (k8s/systemd-Muster laut Docstring Zeile 1-17), kein
  externer Uptime-Dienst, keine Benachrichtigung bei Ausfall; jemand muss
  aktiv pollen.
- `5eyes-backend/services/market_data/notifier.py` und
  `5eyes-backend/backup_scheduler.py:31-55` (`_alert_backup_problem`):
  zwei schmale, optionale Webhook-Alarme (Markt­daten-Validierungsdiff,
  Backup-Fehler) über denselben `post_alert()`-Mechanismus, beide per Default
  deaktiviert (leere Webhook-URL) und fail-soft (Fehler werden geloggt, nicht
  eskaliert).
- Grep über `5eyes-backend` nach `pagerduty|opsgenie|uptime` (case-insensitiv)
  ergab **keine** Treffer.

**Auditvertrag:** Externe Uptime-/Alerting-Lösung (z. B. gehosteter
Healthcheck-Poller + Pager-Eskalation) für `/health/ready` einrichten, damit
ein Ausfall nicht erst durch einen Kundenanruf auffällt; Backup-/
Markt­daten-Webhooks produktiv aktivieren statt im Default-Zustand zu
belassen.

### `IR-PENTEST-001` — Externer Pentest nicht beauftragt

**Repository-Beleg:**
- `docs/PENTEST_PREPARATION.md:6-9`: "**Stand:** 2026-06-06 ·
  **Roadmap-Punkt:** #110 ... · **Status:** Vorbereitung — wartet auf
  User-Beauftragung eines PenTest-Anbieters." Das gesamte Dokument (Scope,
  Anbieterliste, Kostenindikation, Deliverables) ist Vorbereitungsmaterial;
  Zeile 117 nennt "PenTest-Anbieter-Auswahl + Beauftragung (User-Action)"
  explizit als **nicht** in diesem Dokument erledigt.
- Kein Pentest-Bericht, kein Re-Test-Protokoll und kein
  `EXTERNAL_AUDIT`-Compliance-Workflow-Eintrag (Zeile 102 beschreibt diesen
  nur als zukünftigen Schritt "Was nach dem PenTest passiert") im Repository
  gefunden.

**Auditvertrag:** Entscheidung zur Beauftragung eines CH-Pentest-Anbieters
vor breitem T2/T3-Rollout treffen (Owner-Entscheidung, nicht autonom lösbar);
nach Abschluss Bericht + Re-Test-Nachweis im Repository referenzieren.

## Was bewusst kein eigener Fund ist

- Technische Backup-Atomarität, SHA256-/HMAC-Integrität und
  SQLCipher-Unterstützung für SQLite sind bereits an anderer Stelle solide
  belegt (`services/backup.py`, zugehörige Tests `test_ab1_atomic_backup.py`,
  `test_sec007_backup_hmac_authenticity.py` u. a.) — dieser Audit wiederholt
  das nicht, sondern nimmt es als gegebene technische Grundlage für die
  Resilienz-Lücken oben.
- Präventive Tenant-/Auth-Autorisierungsgrenzen sind Gegenstand der
  Security-Folgeaudits vom 25./26.08.2026 — dieser Audit behandelt nur die
  **Post-Incident**-Dimension (Eindämmung, Meldung, Drill), nicht die
  präventive Autorisierungslogik selbst.

## Verifikation dieser Runde

- `git rev-parse HEAD` im Worktree `C:\tmp\5eyes-b2b-05` →
  `8dfd6cc13a7869e1996331e5d226551fc441a6ee` (Branch
  `codex/b2b-incident-resilience-audit`, Arbeitsverzeichnis vor Beginn
  unverändert/clean).
- Vollständig gelesen: `docs/deploy/disaster-recovery-plan.md`,
  `5eyes-backend/services/backup.py`, `5eyes-backend/scripts/restore_drill.py`,
  `5eyes-backend/tests/test_restore_drill.py`, `5eyes-backend/routers/health.py`,
  `docs/PENTEST_PREPARATION.md`, relevante Ausschnitte aus
  `docs/compliance/avv-template.md`,
  `5eyes-backend/services/market_data/notifier.py`,
  `5eyes-backend/services/market_data/provider_health_registry.py`,
  `5eyes-backend/backup_scheduler.py`, `5eyes-backend/config.py`.
- Gezielte Volltext-/Regex-Suchen über `docs/` und `5eyes-backend/` für:
  DR/RTO/RPO-Dokumente, Backup-/Restore-Code, Postgres/PITR-Referenzen,
  Offsite-/Alert-/Webhook-Konfiguration, Health/Monitoring-Endpunkte,
  Incident/Breach/EDÖB/Datenschutzverletzung, Ransomware,
  Tenant-Suspend/-Lock-Funktionen.
- Keine Produktcode-, Test- oder Konfigurationsdatei wurde verändert; dieser
  Audit fügt ausschliesslich diese eine neue Markdown-Datei hinzu.

## Selbst-Audit und Nachweisgrenzen

- Produktcode verändert: **nein**
- Tests verändert oder ausgeführt: **nein** — keine Testsuite wurde in dieser
  Runde laufen gelassen; alle Aussagen zu Testverhalten stammen aus
  gelesenem Testcode, nicht aus einem Lauf.
- Nicht behauptet: dass die dokumentierten RTO/RPO-Zielwerte in der Praxis
  erreichbar sind; dass der einmalige Sandbox-Drill ein belastbarer Nachweis
  für reale Tier-2/3-Infrastruktur ist; dass passive Marktdaten-Provider-
  Beobachtung einem Incident-Response-Prozess gleichkommt; dass irgendeine
  der hier benannten Lücken bereits vor dieser Runde bekannt oder unbekannt
  war (die Korrektur zu `B2B-COVERAGE-006` betrifft ausschliesslich den
  Protokolltabellen-Befund, nicht die übrigen dort genannten Punkte, die
  sich alle bestätigen liessen).
- Nicht geprüft: tatsächlicher Betrieb/Konfiguration eines realen T2/T3-Hosts
  (dieser Audit sieht nur Code- und Dokumentstand im Repository, keine
  Produktionsumgebung); externe Vertrags-/Owner-Fakten (Kontaktpersonen,
  Rufnummern, SLA) ausserhalb des Repositories.
- Ergebnis: `B2B-COVERAGE-006` bleibt in der Substanz bestätigt — Incident
  Response und Resilienz sind geplant, aber nicht als wiederholte, reale
  Praxis belegt. Eine Detailaussage des Coverage-Audits (leere
  Protokolltabelle) ist durch den tatsächlichen Repository-Stand widerlegt
  und wurde hier präzisiert.
