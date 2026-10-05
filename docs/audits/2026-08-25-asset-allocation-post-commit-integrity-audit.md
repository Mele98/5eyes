---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-post-commit-integrity-audit"
status_as_of: "2026-08-25"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "5216c583becf7a1f93950c81d4a5a40915723db3"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_handoff_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
prior_handoff_commit: "5216c583becf7a1f93950c81d4a5a40915723db3"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md"
audit_mode: "read_only_static_offline_focused_tests_and_in_memory_reproductions"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 9
scope: "postgresql release path, current-anchor concurrency, advisory/client publication integrity, documentation drift"
release_decision: "blocked_confirmed_p0_p1"
known_open_p0: true
known_open_p1: true
postgresql_rehearsal_executed: false
alembic_head: "f2a7c91e4b63"
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
latest_full_backend_gate_scope: "default backend suite; no real PostgreSQL-16/RLS rehearsal"
required_next_action: "close PostgreSQL/RLS architecture first, then concurrency and publication integrity; keep release blocked"
---

# Post-Commit Release- und Integritätsaudit

## Zweck und Quellenrangfolge

Dieses Dokument hält die nach dem Implementierungs- und Handoff-Commit neu
gefundenen Release-, Mandantentrennungs- und Publikationsrisiken fest. Es ist für
Claude, GPT, Codex und menschliche Reviewer die verbindliche Ergänzung zum
[kanonischen Einstieg](../ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md) und zum
[technischen Handoff vom 20. August](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gilt folgende Reihenfolge:

1. aktueller Code, Tests und Alembic-Migrationen;
2. dieser Post-Commit-Audit für die hier untersuchten Releasepfade;
3. der technische Handoff vom 20. August für den implementierten Optimizer-Stand;
4. ältere Berater-, Methodik-, Planning-, Stage- und Migrationsdokumente nur als
   historische Quellen.

Die frühere Aussage „keine bekannten offenen P0/P1 im geprüften Scope“ ist für
PostgreSQL/RLS, Current-Anchor-Concurrency sowie Advisory-/Kundenpublikation durch
diesen Audit ersetzt. Der grüne Backend-Gesamtgate bleibt valide, deckt diese
produktiven PostgreSQL- und Publikationsverträge aber nicht vollständig ab.

## Kurzurteil

**Nicht releasen.** Der stochastische Optimizer-Kern und sein SQLite-basierter
Backend-Gesamtgate sind grün. Der produktive PostgreSQL-/RLS-Betrieb ist jedoch
noch nicht funktions- und isolationstauglich. Außerdem umgehen Advisory-Report,
Advisory-PDF und Kundenportal Teile des kanonischen Snapshot-, Hash- und
Publikations-Preflights.

Die Analyse hat keine Produktdatei verändert. Ein echter PostgreSQL-16-Test war
lokal nicht möglich, weil keine PostgreSQL-Instanz, kein Container-Runtime, kein
PostgreSQL-CLI und kein Psycopg-Treiber im aktiven Python verfügbar waren.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `PG-001` | P0 | offen | Login, JWT und Bootstrap unter wirksamer `users`-RLS |
| `PG-002` | P0 | offen | vollständige physische Tenant-Isolation einschließlich FK-Kindtabellen |
| `PG-003` | P0 | offen | globale `tenant_id=NULL`-Semantik ohne pauschalen Backfill |
| `PG-004` | P0 | offen | getrennte Migrator-/Runtime-Rollen und gelockter One-shot-Start |
| `PG-005` | P0 | offen | versionierbarer Rollback sowie echter PostgreSQL-Backup-/Restore-Pfad |
| `PG-006` | P0 | offen | globale Referenzdaten nur über einen expliziten Operator-/Reference-Writer-Pfad |
| `CON-001` | P1 | offen | konkurrierender Current-Anchor endet kontrolliert in 409/Retry statt 500 |
| `REP-001` | P1 | offen | Advisory-MC verwendet verifizierten Snapshot, Hash und Sub-Allokationen |
| `REP-002` | P1 | offen | ausschließlich Final-Run und aktuelles RA werden kundenwirksam publiziert |
| `REP-003` | P1 | offen | unbekannte Cashflow-Typen sind Domainfehler statt positiver Zufluss |
| `REP-004` | P1 | offen | alle Report-, Kosten-, Handoff- und PDF-Consumer verwenden denselben Publikationskontext |
| `REP-005` | P1 | offen | finaler Produkt-/Kosten-Snapshot, Fingerprint, Cache und Kundensignatur sind unveränderlich gebunden |
| `DOC-001` | P1 | offen | aktive Betriebs-/Berater-/Methodikdokumente entsprechen dem Code |

Die IDs bleiben stabil. Ein Finding darf erst nach reproduziertem Negativtest,
implementiertem Fix, vollständigem Abnahmegate und dokumentiertem Fixcommit auf
„geschlossen“ gesetzt werden.

## Unverändert bestätigte Evidenz

- Implementierungscommit:
  `661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4`
- auditierter Repository-Head:
  `5216c583becf7a1f93950c81d4a5a40915723db3`
- Alembic-Head: `f2a7c91e4b63`
- vollständiger Backend-Gate: **6074 passed, 0 failed, 10 skipped,
  1 xfailed, 269 warnings** in 1681,86 Sekunden
- tracked Worktree zum Abschluss des Read-only-Audits unverändert;
  `git diff --check` grün

Ein grüner SQLite-Gate beweist weder PostgreSQL-RLS noch Mehrprozessmigration,
Rollenrechte, PostgreSQL-Backup/Restore oder kundenfähige Publikationsreife.

## P0 – PostgreSQL und physische Mandantentrennung

### P0.1 [`PG-001`] Öffentliche Auth-Familie scheitert unter wirksamer RLS

`users` wird mit `ENABLE/FORCE ROW LEVEL SECURITY` geschützt. Nicht nur Login und
JWT, sondern die gesamte öffentliche Auth-Familie muss `users` oder
`refresh_tokens` abfragen, bevor ein Tenant bekannt beziehungsweise gesetzt ist:

- Bootstrap-Status und Bootstrap-Admin;
- Login und JWT-Auflösung;
- Refresh-Token-Rotation;
- Passwort-Reset Request/Confirm;
- Invite Preview/Accept.

Belege: `5eyes-backend/routers/auth.py:60,194,256,360,615,650,872,879,895`
und `5eyes-backend/services/auth.py:122-152`.

Unter einer echten unprivilegierten Runtime-Rolle liefert die RLS-Policy ohne
Tenant-GUC keine Zeile. Zusätzlich erzeugt der Bootstrap-Pfad einen Benutzer ohne
`tenant_id`, obwohl der PostgreSQL-Start für `users.tenant_id` `NOT NULL`
erzwingt. Der Bootstrap-Lock ist nur pro Python-Prozess; zwei Worker können zwei
Erstadmins anlegen. Refresh-Tokens besitzen keinen vorab auswertbaren
Tenant-Anker. Ein Passwort-Reset per nicht eindeutigem `email` kann bei gleicher
Adresse in mehreren Tenants einen beliebigen ersten Benutzer wählen.

Auch der Super-Admin-Vertrag widerspricht FORCE RLS: `get_current_user()` setzt
für `super_admin` absichtlich einen leeren Tenant-Kontext. Damit sieht der
Operator keine Users, Clients oder Mandates, obwohl Provisioning-, Audit- und
Tenant-Admin-Routen tenantübergreifenden Zugriff erwarten. Der vorhandene
`operator_bypass()` wird produktiv nicht verwendet.

**Abnahmekriterium:** Ein eng begrenzter Pre-Auth-Locator liefert nur `user_id`
und `tenant_id` für Username beziehungsweise Token-Hash. Danach wird der Tenant
gesetzt und erst dann der ORM-User geladen. JWT enthält zwingend einen signierten
`tid`-Claim; Bootstrap ist DB-atomar und legt den Admin in einem expliziten
Tenant an. Login, Refresh, Invite und Reset bestehen FORCE-RLS-Tests mit einer
Nicht-Owner-/Nicht-Bypass-Rolle.

### P0.2 [`PG-002`] RLS schützt nur einen Teil der sensitiven Tabellen

Die 52 ORM-Tabellen teilen sich in acht direkte `tenant_id`-Tabellen, 29 indirekt
tenantabhängige Tabellen und 15 echte globale Tabellen. Der Runtime-Resolver
schützt nur die acht direkten Tabellen.

Die 29 ungeschützten indirekten Tabellen sind:

- über User: `adviser_registrations`, `refresh_tokens`;
- über Client: `client_logins`, `cashflows`, `client_knowledge`,
  `client_nationalities`, `client_opt_history`, `wealth_positions`;
- über Mandate: `advisory_log`, `conflict_of_interest_disclosures`,
  `contract_documents`, `goals`, `mandate_baustein_selections`,
  `mandate_report_notes`, `optimizer_runs`, `planning_assumptions`,
  `portfolio_handoffs`, `recommendation_runs`, `review_triggers`,
  `risk_assessments`, `strategy_snapshots`, `suitability_checks`,
  `target_allocations`, `wealth_inflows`;
- tiefer abgeleitet: `risk_assessment_answers`, `recommendation_positions`,
  `recommendation_holdings`;
- über Product-Overlay: `price_history`, `product_suitability`.

RLS auf `clients` oder `mandates` propagiert nicht automatisch zu Kindtabellen.
Rohe SQL-Abfragen gegen ungeschützte Kinder können deshalb tenantübergreifende
Daten liefern.

**Abnahmekriterium:** Für jede sensitive Tabelle ist eine explizite
Tenant-Ableitung und eine PostgreSQL-Policy versioniert. Adversarial Tests mit
zwei Tenants prüfen direkte Queries auf Eltern und Kindern.

### P0.3 [`PG-003`] Pauschaler NULL-Backfill zerstört Scope und Audit

`5eyes-backend/services/postgres_rls.py` setzt jede direkte
`tenant_id IS NULL` auf den Tenant `main` und erzwingt danach `NOT NULL`.
`NULL` ist im Fachmodell jedoch absichtlich belegt:

- globale Produkte;
- CH-/firmenweite Capital Market Assumptions;
- tenantgebundene beziehungsweise noch zu migrierende Legacy-Protokollbausteine;
- System-/Operator-Auditzeilen.

`protocol_bausteine.advisor_id=NULL` bedeutet tenantweit, nicht global über alle
Tenants. Im Strict-Modus verlangt der Router einen exakten `tenant_id`-Match.
Legacy-NULL-Tenants benötigen deshalb eine belegbare Tenant-Zuordnung und dürfen
weder pauschal global noch pauschal `main` werden.

Die CH-CMA-Erstellung persistiert ausdrücklich `tenant_id=None`, und der
Jurisdiktionsresolver sucht firmweite CH-CMAs mit `tenant_id IS NULL`. Der
PostgreSQL-Pfad kann neue CH-CMAs dadurch ablehnen oder Bestandsdaten aus dem
Resolver-Scope verschieben. Historische `audit_log`-Updates können außerdem am
Immutable-Trigger scheitern.

Der Konflikt ist technisch und compliance-seitig: Migration `e84f9a2d1c70`
blockiert jedes `audit_log`-UPDATE per Trigger; der Runtime-Backfill versucht
danach dennoch `tenant_id` zu aktualisieren. Ohne Trigger würde die nachträgliche
Scope-Änderung die gespeicherten Audit-Integrity-Hashes fachlich entwerten.

**Abnahmekriterium:** Tabellen werden explizit in tenantgebunden, global und
FK-abgeleitet klassifiziert. Kein pauschales `NULL -> main`. Jede Migration hat
eine fachlich definierte Datenabbildung und einen Konflikt-Preflight.

### P0.4 [`PG-004`] Runtime-Rolle und Migrationsrolle widersprechen sich

Die Anwendung verlangt eine unprivilegierte Nicht-Owner-Runtime-Rolle. Dieselbe
Verbindung soll beim App-Start aber Alembic, `ALTER TABLE`, `FORCE RLS` und
Policy-DDL ausführen. Diese Operationen benötigen Owner-/Migrationsrechte.

**Abnahmekriterium:** Getrennte Migrator- und Runtime-URLs/Rollen. Migrationen
laufen als einmaliger Deployment-Schritt; Runtime-Startup führt kein Schema- oder
Policy-DDL aus.

### P0.5 [`PG-004`] Mehrere Worker starten DDL und globale Jobs mehrfach

Jeder FastAPI-Lifespan ruft `init_db()` auf. Die dokumentierte systemd-Unit
startet zwei Gunicorn-Worker. Ein One-shot-Migrationsschritt oder PostgreSQL-
Advisory-Lock fehlt. Zusätzlich starten beide Worker Tax-Seeding, Price-/Market-
Data-Scheduler und SQLite-Backup-Scheduler (`main.py:82,109-110`,
`docs/deploy/5eyes.service:15`).

**Abnahmekriterium:** Genau ein gelockter Migrator läuft vor den App-Workern.
Ein Zwei-Worker-Starttest beweist, dass keine zweite Migration und keine
halbfertige Policy-Installation möglich ist.

### P0.6 [`PG-005`] PostgreSQL-Backup und Rollback sind nicht ausführbar

RLS und Tenant-`NOT NULL` werden imperativ außerhalb Alembic installiert.
`alembic current` kann daher einen grünen Head melden, obwohl Policies fehlen
oder nur ein Teil der Änderungen aktiv ist. Ein Alembic-Downgrade entfernt diese
Änderungen nicht.

Der standardmäßig aktive Backup-Scheduler ruft auch bei PostgreSQL den
SQLite-Backupdienst für `settings.db_path` auf. Er kann damit ein erfolgreiches
Backup einer irrelevanten SQLite-Datei melden. Der DR-Plan behandelt
`pg_dump`/PITR weiterhin nur als Zukunftsziel.

**Abnahmekriterium:** RLS und Constraints sind Alembic-versioniert. Vor dem
Release existieren ein ausführbarer `pg_dump`-Pfad, Restore-Probe, dokumentierte
RPO/RTO und ein nachweislich wiederherstellbares Backup.

### P0.7 [`PG-006`] Firmen-Admins können globale Referenzdaten verändern

Normale `admin`-Accounts sind Firmen-Admins. Trotzdem dürfen sie aktuell global
wirksame Daten mutieren: CH-CMA (`routers/allocation.py:391-484`), globale
OptimizerPolicy, BuildingBlocks und HouseMatrix (Admin-Routen ab
`allocation.py:1017`), globale Produktmetadaten (`routers/review.py:1460,1492`)
sowie weitere FX-/Jurisdiktionsreferenzen. Ein Tenant kann damit Empfehlungen
anderer Tenants beeinflussen.

**Abnahmekriterium:** Eine explizite globale Reference-Writer-/Operatorrolle ist
die einzige DML-Berechtigung für globale CMA, Policy, HouseMatrix,
BuildingBlocks, Produkte, FX, Jurisdiktion und Tax-Referenzen. Tenant-Admins
dürfen globale Zeilen nur lesen und ausschließlich eigene private Overlays
verwalten.

## P1 – PostgreSQL-Releasehärtung

### P1.1 Migrations- und Treiberverträge

- Migration `d4e8f1a9c2b7` erzeugt nicht-konkurrierende Unique-Indizes ohne
  ausführbaren Lock-, Tabellenvolumen-, Namens- und Duplicate-Preflight.
- Die PostgreSQL-CI prüft eine handgebaute `clients`-Tabelle, nicht den echten
  Alembic-/Startup-/Login-/RLS-Pfad.
- Dokumentierte Bare-URLs `postgresql://...` wählen mit SQLAlchemy 2 standardmäßig
  Psycopg2; installiert wird Psycopg 3. Der kanonische Treiberstring muss
  `postgresql+psycopg://...` sein.
- Prozentkodierte Passwörter werden roh an Alembics ConfigParser übergeben.
  Reproduktion mit `%25`: `ValueError: invalid interpolation syntax`.
- Pool-GUC-Reset und `idle in transaction` benötigen einen echten PostgreSQL-
  Wiederverwendungstest.

### P1.2 Runbook und Verifikation

Der aktuelle Runbook prüft weder Schema-Qualifikation noch `pg_policy`,
`relrowsecurity`, `relforcerowsecurity`, Rollenrechte, Authentisierung oder
Restore. Diese Prüfungen müssen ausführbar und CI-fähig werden.

### P1.3 Operator-Bypass, Ankerkonsistenz und Scheduler

- Die Policy akzeptiert `app.rls_bypass='on'`; eine normale Runtime-Verbindung
  kann eine Custom-GUC grundsätzlich selbst setzen. Der Bypass gehört nicht in
  Runtime-Policies. Operatorzugriff braucht eine separate DB-Rolle oder eng
  begrenzte `SECURITY DEFINER`-Funktionen.
- Mehrfach gespeicherte fachliche IDs, etwa in `recommendation_runs`,
  `suitability_checks`, `goals`, `planning_assumptions` und
  `target_allocations`, sind nicht überall per mandate-/tenantkonsistenter FK
  abgesichert. Cross-Tenant-Anker müssen DB-seitig unmöglich werden.
- Migration, Tax-Seeding, Marktpreisjobs und Backup dürfen nicht pro
  Gunicorn-Worker gestartet werden.

## P1 – Current-Anchor-Concurrency und HTTP-Vertrag

Die Partial-Unique-Indizes für aktuelle RiskAssessments und TargetAllocations pro
Mandat sowie die globale aktuelle OptimizerPolicy sind korrekt. Die
Servicepfade sperren aber nur eine bereits vorhandene Current-Zeile. Zwei
parallele Erstschreibvorgänge können denselben leeren Anchor-Slot sehen.

Der Unique-Index entscheidet dann korrekt; der Verlierer erhält jedoch einen
ungefangenen `IntegrityError`, der als HTTP 500 endet. Betroffen sind mindestens:

- RiskAssessment-Create;
- direkter TargetAllocation-Create;
- generierte TargetAllocation;
- OptimizerPolicy-Create und -Activate.

Zusätzlich verwenden einzelne Lesepfade weiterhin `.first()` statt eines
zentralen Exactly-one-Resolvers. Bei prä-migrations- oder beschädigten Daten kann
dadurch ein beliebiger Current-Anker gewählt werden.

**Abnahmekriterium:** Echte parallele Zwei-Transaktions-Tests gegen PostgreSQL.
Der Verlierer erhält konsistent HTTP 409 oder einen begrenzten, sicheren Retry;
es bleibt exakt ein aktueller Anchor. Alle Consumer verwenden denselben
Exactly-one-Vertrag.

## P1 – Advisory-Report, PDF und Kundenportal

### P1.1 [`REP-001`] Der allgemeine Report umgeht den Strategie-/Hash-Preflight

`5eyes-backend/services/monte_carlo_paths.py` lädt aktuelle TargetAllocation und
globale aktuelle CMA getrennt. Der Pfad prüft weder
`context_artifacts_required`, `allocation_context_hash`, `input_snapshot_hash`
noch die verankerte Snapshot-CMA.

Reproduktion:

```text
ACCEPTED_TAMPERED_CONTEXT=True
CMA_USED=cma-current
SNAPSHOT_CMA_ANCHOR=cma-snapshot
```

Vier Strategy-PDF-Routen besitzen bereits einen 409-Preflight für TA, RA, Policy,
Snapshot-CMA und Engine-Rebuild. Sie sind dennoch nicht durchgängig sicher, weil
Recommendation-, Produkt-, Kosten- und Provisional-Pfade teils erneut aus dem
neuesten beliebigen Run geladen oder fail-soft behandelt werden. Advisory-JSON,
Advisory-PDF und Kundenportal umgehen selbst diesen Anchor-Preflight derzeit
vollständig.

### P1.2 [`REP-001`] Persistierte Sub-Allokationen werden in Monte Carlo ignoriert

Der MC-Pfad ruft `scenario_inputs_from_cma(cma)` ohne persistierte
Sub-Allokationen auf. Der Core erhält kein Sub-Allokationsargument. CH-heavy und
international-heavy Portfolios können dadurch auf denselben Bucket-Durchschnitt
reduziert werden, obwohl der kanonische Optimizer unterschiedliche Renditen
modelliert.

### P1.3 [`REP-003`] Unbekannte Cashflow-Typen werden als Einkommen behandelt

Der Legacy-Projektor in `monte_carlo_paths.py` addiert unbekannte Cashflow-Typen
positiv. Reproduktion:

```text
UNKNOWN_CASHFLOW_SERIES=[25000, 25000, 25000]
```

Außerdem fehlen gegenüber der kanonischen Engine Laufzeiten, FX, Inflation,
Wealth-Inflows sowie abgeleitete Steuer- und Vermögenscashflows.

### P1.4 [`REP-002`] Draft-Empfehlungen gelangen in die Kundenpublikation

Der Advisory-Aggregator wählt den neuesten RecommendationRun ohne
`result_status == Final` und ohne Bindung an die aktuelle TargetAllocation. Das
Kundenportal und der Advisory-PDF-Renderer übernehmen dessen Positionen.

Reproduktion:

```text
RUN_STATUS=Draft
EXPOSED_PRODUCTS=['DRAFT_ONLY_PRODUCT']
```

### P1.5 [`REP-002`] Nichtaktuelle Risikoprofile beeinflussen den Kundenbericht

Ein als „current“ benannter Helper wählt das neueste RiskAssessment ohne
`is_current`- und `deleted_at`-Filter. Andere Sektionen wählen korrekt die aktuelle
Zeile. Ein Bericht kann sich dadurch selbst widersprechen und ein inaktives
Profil als aktuell/grün deklarieren.

Reproduktion:

```text
CLIENT_INFO_PROFILE=INACTIVE_WILLINGNESS
RISK_CHECK=gruen:Risikoprofil aktuell und vollständig erfasst.
CURRENT_SECTION_PROFILE=Wachstumsorientiert
```

### P1.6 [`REP-004`] Weitere Consumer wählen eigene Hybridkontexte

Der Defekt ist nicht auf den Advisory-Aggregator begrenzt:

- `depot_check.py:243-540` kombiniert neuesten beliebigen Run mit aktueller TA;
- `cost_disclosure.py:47-157` kombiniert neuesten Run, Live-Produkte/TER und
  Run-TA-/Current-TA-Fallback;
- `_build_anlagestrategie_data` preflightet die Strategieanker, wählt Produkte
  aber weiterhin aus dem neuesten beliebigen Run und verschluckt Fehler
  (`pdf_reports.py:491-535`);
- `_build_portfolio_data` erlaubt Final oder Draft. Ein zunächst verschluckter
  TA-Ladefehler endet danach generisch in 409; separat gefangene Positions-,
  Produkt- und Holdingfehler können dagegen einen partiellen oder leeren
  200-Payload erzeugen (`pdf_reports.py:1012-1149`);
- Protokoll und Contract-Signoff übernehmen den neuesten beliebigen Run;
- der Provisional-Banner richtet sich bei den angebundenen PDF-Typen nach dem
  neuesten Run und kann durch einen späteren Draft gesetzt oder entfernt werden;
  `contract-signoff.pdf` und `depotcheck.pdf` rufen
  `_attach_provisional_notice()` überhaupt nicht auf und besitzen damit kein
  entsprechendes Gate;
- Portfolio-Handoff akzeptiert Draft/Superseded/alte Runs als Handelsliste
  (`routers/portfolio_handoff.py:86-154`);
- Backtest- und Risikoprofil-PDFs verwenden eigene `.first()`-/Fallback-Pfade;
- `build_target_payload_from_allocation` injiziert aktuell selbst einen Final-
  oder Latest-Run in `live_rebalancing`, statt den expliziten Publikationsrun zu
  verwenden.

Der Cache (`advisory_report_cache.py:13-30,154-176`) ist nur nach Mandat und
Advisor geschlüsselt, läuft pro Prozess und wird vor einem Integritäts-Preflight
ausgeliefert. Final-, Kunden- und PDF-Aufrufe dürfen ihn nicht als
Integritätsgarantie verwenden.

### P1.7 [`REP-005`] Finaler Produktstand und Kundensignatur sind nicht gebunden

`RecommendationPosition` speichert Gewicht, Betrag, Preis und Begründung, aber
nicht alle kundenwirksamen Produkt-/Kostenfelder. Eine spätere Änderung an Name,
ISIN, Anbieter, Währung, Asset-/Subassetklasse, TER oder Overrides kann einen
bereits finalen Bericht verändern.

Die Kundensignatur in `client_portal.py:119-175` signiert irgendeine `.first()`-
Current-RA ohne Publikationsfingerprint. Ein RA-Rollover zwischen GET und POST
kann dadurch einen anderen Stand bestätigen als der Kunde gesehen hat.

**Abnahmekriterium:** Bei Finalisierung wird ein versionierter, kanonisch
sortierter Produkt-/Kosten-Snapshot mit `recommendation_publication_hash`
persistiert. Die Kundenansicht enthält einen stabilen
`publication_fingerprint`. Die Signatur übermittelt RA-ID und Fingerprint,
sperrt Mandat/RA, resolvt den finalen Kontext erneut und liefert bei jeder
Abweichung 409.

### Gemeinsamer Abnahmevertrag für Advisory-Publikation

1. Zentraler `resolve_advisory_publication_context()`-Preflight vor Cache,
   Aggregator und Renderer. Er liefert einen unveränderlichen Kontext mit Modus,
   Mandat, TA, RA, Policy, Snapshot-CMA, exaktem RecommendationRun, Positionen,
   Produkt-Snapshot, verifiziertem Target-Payload, Fingerprint und
   Provisional-Status.
2. Der Resolver läuft read-only in einem konsistenten DB-Snapshot und erzeugt,
   seedet oder verändert keine Daten. `session.new`, `dirty` und `deleted` bleiben
   vor/nach identisch.
3. Zentraler Invariantenvertrag:
   - exakt eine aktuelle TargetAllocation;
   - moderne Contextartefakte vollständig;
   - Hash und Input-Snapshot aktuell;
   - Policy-, RiskAssessment- und Snapshot-CMA-Anker vorhanden und konsistent;
   - Jurisdiktion, Tenant, Approval und Model-Basis stimmen;
   - ausschließlich exakt ein Final-Run der aktuellen TA für Kunden;
   - Run-Anker für Mandat, Client, TA, RA, Policy und CMA stimmen vollständig;
   - Positionen und Produkte sind vollständig, eindeutig, aktiv und im erlaubten
     Tenant-/Global-Universum.
4. JSON-, PDF-, Kosten-, Depotcheck-, Handoff- und Kundenendpunkte nutzen denselben
   Kontext. Integritätsfehler werden konsistent auf HTTP 409 abgebildet.
5. Advisor-Preview ist ein separater, explizit als Entwurf markierter Pfad. Ein
   Preview-PDF trägt Dateiname/Header und auf jeder Seite `ENTWURF`. Ein
   unmarkiertes PDF ist ausschließlich `CUSTOMER_FINAL`.
6. Monte Carlo wird aus dem verifizierten kanonischen Allocation-Payload gespeist;
   keine zweite CMA-, Sub-Allokations- oder Cashflow-Fachlogik.
7. Unbekannte Cashflow-Typen sind Domainfehler, niemals Einkommen. Alle nicht
   gelöschten Rows werden vor Aktivfilterung vollständig validiert; FX-,
   Inflations-, Wealth- und Tax-Cashflows stammen aus der kanonischen Timeline.
8. Final-/Kunden-/PDF-Pfade umgehen den alten Prozesscache. Ein Preview-Cache ist
   erst nach dem Preflight zulässig und bindet mindestens Modus, Run-ID,
   Fingerprint, Advisor und View-Konfiguration.
9. DB-Vertrag ergänzen: erlaubte Run-Status `Draft|Final|Superseded`, Partial-
   Unique-Index für **höchstens einen** Final-Run pro Mandat und ein bedingter
   CHECK `result_status <> 'Final' OR (... alle Final-Anker IS NOT NULL ...)`.
   Der `CUSTOMER_FINAL`-Preflight verlangt fachlich **genau einen** Final-Run.
   Duplicate-Preflight vor Migration, niemals willkürliche Wahl.

Stabile HTTP-Konfliktcodes sollen mindestens fehlende/mehrdeutige Current-TA,
Legacy-Kontext, ungültige RA-/Policy-/CMA-Anker, falschen CMA-Scope, korrupte oder
stale Hashes, fehlenden/mehrdeutigen Final-Run, Run-Anker-Mismatch, ungültige
Positionen/Produkte/Cashflows und einen während der Publikation geänderten Kontext
unterscheiden. Renderer werden nach 409 niemals aufgerufen; unbekannte technische
Fehler bleiben 500 und erzeugen keinen partiellen 200-Report.

## P2 – Reporting- und Schemahygiene

- Das Modellfeld heißt `sub_allocations_json`; der Advisory-Report liest
  `sub_allocation_json` und prüft zusätzlich das nicht existente
  `TargetAllocation.is_active`. Korrekt sind `is_current == 1`,
  `deleted_at IS NULL` und `sub_allocations_json`. Das Auditfeld
  `sub_allocation_aware` meldet deshalb bei modernen Allokationen regelmäßig
  fälschlich `false`.
- Der Advisory-PDF-Renderer akzeptiert `watermark_mode`, verdrahtet ihn im aktiven
  Two-Pass-Renderer aber nicht. Ein expliziter Entwurfsmodus erzeugt kein
  sichtbares Entwurfswasserzeichen.
- `tax_estimate_in_cashflow_enabled` ist Integer ohne DB-CHECK auf `0/1`.
- `ALEMBIC_DATABASE_URL_OVERRIDE` kann beim App-Startup die programmatisch gesetzte
  URL übersteuern und sollte auf CLI/Test begrenzt werden.

## Dokumentationsdrift mit operativem Risiko

Mehrere aktive Dokumente beschreiben weiterhin House Matrix als Default,
Stochastic als Opt-in oder Alembic als Baseline-only. Das ist besonders für
Claude-/GPT-Retrieval gefährlich.

Zuerst zu synchronisieren:

1. `docs/BERATER_README.md`
2. `docs/BERATER_ONBOARDING.md`
3. `docs/GLOSSAR.md`
4. `docs/engine-spec.md`
5. `docs/methodology/5eyes-engine-whitepaper.md`
6. `docs/whitepaper/2026-07-19-5eyes-methodik-whitepaper.md`
7. `docs/SCHEMA_MIGRATIONS.md`
8. `docs/deploy/postgres-migrations.md`

Historische Stage-, Shadow-, ADR-, Planning- und Statusdokumente dürfen nicht
umgeschrieben werden. Sie benötigen einen einheitlichen historischen Banner mit
Link auf den kanonischen Einstieg. Ein Doku-Gate soll aktive Aussagen zu
Production-Stochastic, Fallback-Allowlist und House-Feasibility, normalisierter
Objective, v4-Snapshot/Ankern sowie der Alembic-Kette bis `f2a7c91e4b63`
erzwingen.

## Verbindliche Fixreihenfolge

### Block 1 – PostgreSQL-P0 schließen

1. Release eingefroren lassen.
2. Isolierte PostgreSQL-16-Kopie und restorable `pg_dump` bereitstellen.
3. Separate Owner-/Migrator- und Runtime-Rollen einführen.
4. Migration als gelockten One-shot-Schritt vor dem App-Start ausführen.
5. RLS und Constraints vollständig Alembic-versionieren.
6. Tenant-, globale und FK-abgeleitete Tabellen fachlich klassifizieren.
7. Login/JWT/Bootstrap für wirksame `users`-RLS neu entwerfen.
8. Zwei-Tenant-, Pool-Reuse-, Multiworker- und Restore-Tests ausführen.

Konkretisierter Implementierungsvertrag:

1. **Rollen und Startup**
   - `fiveeyes_migrator`: Schema-/Tabellen-Owner, nur für den Deployment-Job;
   - `fiveeyes_app`: `NOSUPERUSER`, `NOBYPASSRLS`, kein Owner, nur notwendige
     DML-Rechte;
   - separate Operator-/Reference-Writer-Rolle, nie in normalen Requests;
   - Runtime führt weder Alembic noch RLS-DDL aus, sondern prüft nur Head,
     Rollen, Owner, Grants und Policy-Inventar;
   - SQLAlchemy-Connection an Alembic übergeben statt die URL ungeescaped in
     ConfigParser zu schreiben; verbindlich `postgresql+psycopg://`.
2. **Versionierte Scope-/RLS-Migration**
   - neue additive Alembic-Revisionen, keine Runtime-DDL-Helfer;
   - `NOT NULL` nur für deterministisch tenant-owned Tabellen;
   - Overlay-SELECT: `tenant_id IS NULL OR tenant_id=current_tenant`;
   - Tenant-DML nur auf `tenant_id=current_tenant`;
   - globale DML ausschließlich über Reference-Writer;
   - eigene `EXISTS`-Policy plus passende FK-Indizes für alle 29 Kinder;
   - Audit-Historie und Hashes byte-identisch erhalten.
3. **Pre-Auth-Locator**
   - eng begrenzte `SECURITY DEFINER`-Resolver mit NOLOGIN-Owner;
   - Rückgabe ausschließlich `user_id` und `tenant_id` für normalisierten
     Username, Invite-, Reset- und Refresh-Token-Hash sowie Bootstrap-Status;
   - schemaqualifizierte Namen, fixes `search_path`,
     `REVOKE EXECUTE FROM PUBLIC`;
   - nach Auflösung sofort Tenant-GUC setzen, erst danach ORM-User laden;
   - Legacy-JWT ohne signierten `tid` beim Cutover invalidieren;
   - E-Mail-Reset benötigt Tenant-Slug oder exakt einen Treffer.
4. **Tenant-Kontext pro Transaktion**
   - Tenant in `Session.info` halten und bei jedem Transaction-Begin lokal setzen;
   - Commit innerhalb eines Requests verliert den Scope nicht;
   - Pool-Reuse übernimmt niemals einen alten Tenant;
   - `app.rls_bypass` aus normalen Policies entfernen;
   - Super-Admin erhält nur über einen expliziten, auditierten Operatorpfad
     Cross-Tenant-Datensicht.
5. **Globale Governance**
   - neue Dependency wie `require_global_reference_manager`;
   - Tenant-Admin darf globale Referenzen nur lesen und eigene private Produkte
     beziehungsweise ProductUniverseEntries verwalten;
   - fremde Tenant-Overrides dürfen auch per Query-Parameter nicht adressierbar
     sein.
6. **Backup und Scheduler**
   - SQLite-Backup bei PostgreSQL hart deaktivieren;
   - PostgreSQL über Managed Backup, pgBackRest oder mindestens
     `pg_dump --format=custom` sichern;
   - Rollen separat als IaC oder `pg_dumpall --roles-only` sichern;
   - Scheduler als externen Single-Instance-Job, niemals pro App-Worker;
   - Restore in eine leere PG16-Instanz und danach Head-, Rollen-, Policy-,
     Login- und Zwei-Tenant-Smoke.

Verbindlicher echter PostgreSQL-16-Testgate:

- leere DB sowie Legacy-Stände `b6`, `d4` und `f2` bis Head migrieren;
- URL-Passwörter mit `%`, `@` und `:`;
- zwei parallele Migratoren, unaufgelöste Tenant-NULLs und globale
  Product-/CMA-NULLs;
- Runtime kann kein DDL und ist weder Owner noch Superuser/BYPASSRLS;
- Bootstrap mit zwei Workern ergibt exakt einen Erfolg und einen Konflikt;
- Login, JWT, Refresh, Invite und Reset vollständig unter FORCE RLS;
- falscher/fehlender `tid`, gesperrter Tenant und doppelte E-Mail;
- Isolation parameterisiert über alle acht direkten und 29 indirekten Tabellen;
- Cross-Tenant INSERT/UPDATE/DELETE, Commit, Rollback und Pool-Reuse;
- globale Overlays für Tenant A/B, aber globale DML nur durch Operator;
- Audit-Immutability und historische Hashes unverändert;
- zwei App-Worker ohne Migration oder doppelte Scheduler;
- Backup → Restore → Login/RLS-Smoke.

Die heutige CI-Prüfung in `.github/workflows/test.yml:105-145` verwendet nur eine
künstliche `clients`-Tabelle und erfüllt diesen Vertrag nicht.

### Block 2 – Publikationsintegrität schließen

1. Neue zentrale Fläche `services/advisory_publication.py` mit den Modi
   `ADVISOR_PREVIEW` und `CUSTOMER_FINAL` sowie unveränderlichem
   `AdvisoryPublicationContext` einführen.
2. Advisor-JSON, React-Reporting, Kundenportal, Advisory-PDF, Portfolio-PDF,
   Anlagestrategie, AssetAllocation, Signoff, Depotcheck, Protokoll, Kosten,
   Portfolio-Handoff, Backtest-PDF und Risikoprofil-PDF auf denselben Context-
   beziehungsweise einen ausdrücklich abgegrenzten Exactly-one-/Snapshot-
   Preflight umstellen.
3. `build_target_payload_from_allocation` um einen expliziten RecommendationRun
   beziehungsweise `include_live_rebalancing=False` erweitern; kein impliziter
   Final-/Latest-Run im finalen Kontext.
4. Final-/Current-/Anchor-, Jurisdiktions-, Status-, Positionen- und
   Produktverträge schließen. Produkt-/Kosten-Snapshot und Fingerprint bei
   Finalisierung persistieren.
5. MC aus `context.target_payload` speisen und Legacy-CMA-/Sub-Allokations-/
   Cashflow-Projektoren aus kundenwirksamen Pfaden entfernen.
6. Final-/PDF-/Portal-Cache umgehen; Preview-Cache erst nach Preflight und mit
   Fingerprint-Key.
7. Kundensignatur an exakte RA-ID, Final-Run und Fingerprint binden.
8. Wasserzeichen und `sub_allocations_json`-Auditfeld funktional testen.

Neue Kern-Suites:

- `tests/test_advisory_publication_preflight.py`: genau ein Current-Kontext,
  moderne Artefakte, Anker/Scope/Hash, keine Writes, Finalstatus,
  Positionen/Produkte, Cashflows, FX, Sub-Allokationen und exakte MC-Model-Basis;
- `tests/test_advisory_publication_endpoints.py`: sämtliche Consumer liefern bei
  jedem Invariantenfehler 409, rufen keinen Renderer auf und erzeugen keinen
  partiellen Payload;
- Client-Signatur: GET → RA-Rollover → POST ergibt 409 und verändert keine RA;
- Cache: zwischen zwei Sessions/Workern geänderter Final-/RA-Stand wird nie aus
  altem Cache publiziert;
- Portfolio-Handoff: Draft, Superseded, alte TA, Duplicate Final und ungültige CMA
  blockieren;
- echte PDF-Prüfung: Preview enthält auf jeder Seite `ENTWURF`, Final nicht;
- zwei parallele Finalisierungen ergeben genau einen Final-Run;
- Reporting-Frontend übernimmt die kanonischen
  `target/current_p10/p50/p90_series_rappen`-Felder; der separate Legacy-MC-Pfad
  mit seinen echten, aber methodisch anderen `p5/p50/p75`-Quantilen entfällt.

### Block 3 – Concurrency-/409-Vertrag schließen

1. Unique-Verletzungen eng auf bekannte Current-Anchor-Indizes klassifizieren.
2. Transaktion sicher zurückrollen.
3. Konsistent 409 oder begrenzten Retry liefern.
4. Echte parallele PostgreSQL-Tests für alle fünf Schreibpfade ergänzen.
5. Alle Current-Consumer auf einen Exactly-one-Resolver umstellen.

### Block 4 – Dokumente synchronisieren

Aktive Berater-, Methodik- und Migrationsdokumente korrigieren; historische
Dokumente bannern; maschinenlesbares Doku-Gate ergänzen. Erst danach dürfen
Claude/GPT diese Sekundärquellen wieder als aktuellen Betriebsvertrag verwenden.

## Definition of Done für den nächsten Review

- [ ] Alle sechs PostgreSQL-P0-Kategorien sind test-first geschlossen.
- [ ] PostgreSQL-16-Up-/Downgrade läuft mit getrennten Rollen.
- [ ] Login/JWT funktioniert unter echter FORCE-RLS-Runtime-Rolle.
- [ ] Zwei Tenants sind auch bei rohen Kindtabellenqueries isoliert.
- [ ] Globale CMA-/Produktzeilen bleiben global auflösbar; Protokollbausteine
      bleiben tenantgebunden und Legacy-Zeilen sind belegbar zugeordnet.
- [ ] Zwei App-Worker starten ohne parallele Migration.
- [ ] Ein `pg_dump` wurde erfolgreich in eine leere Instanz restauriert.
- [ ] Advisory-JSON, Advisory-PDF und Kundenportal blockieren Snapshot-/Hash-Drift
      sowie fehlende oder gelöschte Anker mit 409.
- [ ] Kundenansicht veröffentlicht ausschließlich einen Final-Run der aktuellen
      TargetAllocation.
- [ ] Depotcheck, Kosten, Protokoll, Portfolio-Handoff und alle Strategie-PDFs
      verwenden denselben unveränderlichen Publikationskontext.
- [ ] Finalisierung persistiert einen versionierten Produkt-/Kosten-Snapshot und
      einen stabilen Publikationsfingerprint.
- [ ] Kundensignatur bindet exakte RA-ID, Final-Run und Fingerprint; ein Rollover
      zwischen GET und POST führt zu 409.
- [ ] Sub-Allokationen und kanonische Cashflows fließen bitgenau in Reporting-MC.
- [ ] Preview-PDFs tragen auf jeder Seite `ENTWURF`; unmarkierte PDFs sind nur
      aus einem `CUSTOMER_FINAL`-Kontext erzeugbar.
- [ ] Fünf Current-Anchor-Schreibpfade bestehen echte Paralleltests.
- [ ] Aktive Sekundärdokumente sind synchronisiert und historische Quellen
      eindeutig gebannert.
- [ ] Vollständiger Backend-Gate, PostgreSQL-Gate, Reporting-Build und Renderer-
      Gate sind auf demselben Commit grün.
- [ ] Owner und Compliance haben die verbleibenden Betriebsrisiken freigegeben.

## Startcheckliste für Claude

1. Lies zuerst diesen Audit und danach den technischen Handoff vom 20. August.
2. Behaupte nicht, der Release sei wegen des grünen SQLite-Gates freigegeben.
3. Behandle PostgreSQL-P0, Advisory-Publikation und Concurrency als getrennte
   Fixblöcke; keine breite Mischänderung.
4. Schreibe zuerst Negativtests; aktualisiere keine Golden Snapshots blind.
5. Verwende echte PostgreSQL-Transaktionen für RLS und Concurrency.
6. Ersetze globale `NULL`-Semantik niemals pauschal durch Tenant `main`.
7. Veröffentliche keine Draft-Runs und rekonstruiere keine moderne Strategie mit
   Live-CMA oder ungeprüften Current-Ankern.
8. Halte dieses Dokument nach jedem Fixblock mit exakten Tests, Commit und
   verbleibenden Risiken aktuell.

## Anhang A – Dokumentationsmanifest dieses Audits

Der reine Dokumentationsstand umfasst exakt diese neun Pfade:

1. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
2. `docs/CLAUDE_HANDOFF.md`
3. `docs/SCHEMA_MIGRATIONS.md`
4. `docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md`
5. `docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md`
6. `docs/compliance/stage8-berater-runbook.md`
7. `docs/deploy/disaster-recovery-plan.md`
8. `docs/deploy/postgres-migrations.md`
9. `docs/deploy/provisioning-runbook.md`

Die externe Commit-Provenienz dieses Dokuments wird nach dem Doku-Commit so
ermittelt:

```powershell
git log -1 --format=%H -- docs/audits/2026-08-25-asset-allocation-post-commit-integrity-audit.md
```

Keinen Selbsthash in das Dokument schreiben. Produktfixes werden später zuerst
als eigener Implementierungscommit gesichert und erst danach in einem separaten
Evidenzcommit mit exaktem Hash hier nachgetragen.
