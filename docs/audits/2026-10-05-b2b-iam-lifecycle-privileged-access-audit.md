---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-iam-lifecycle-privileged-access-and-support-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/b2b-iam-lifecycle-privileged-access-audit"
audited_repository_head: "8dfd6cc13a7869e1996331e5d226551fc441a6ee"
prior_audit_path: "docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md"
prior_audit_finding_id: "B2B-COVERAGE-003"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-05-b2b-iam-lifecycle-privileged-access-audit.md"
audit_mode: "read_only_static_source_and_existing_test_inventory_review"
audit_mutated_product_code: false
audit_mutated_tests: false
scope: "IAM Joiner/Mover/Leaver, privileged-access governance (super_admin/portfolio_management), segregation of duties, break-glass, support access and periodic recertification"
new_confirmed_findings: 7
known_open_findings_referenced: 1
---

# IAM-Lifecycle-, Privileged-Access- und Support-Audit (B2B-COVERAGE-003)

## Geltung und Quellenrangfolge

Dieser Audit ist die zweite Runde des in
[`2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md`](2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md)
festgelegten Auditvertrags `B2B-COVERAGE-003` ("Operativer Identity- und
Privileged-Access-Lifecycle fehlt"). Er ist read-only: kein Produktcode, keine
Migration, keine Testdatei und keine Konfiguration wurde verändert oder
ausgeführt. Die Rollen-/Berechtigungsmatrix und alle Codeanker wurden direkt
aus dem Quellcode auf `audited_repository_head` abgeleitet, nicht aus
Dokumentation oder Annahmen.

Bei Widersprüchen gelten aktueller Produktcode zuerst, danach die bereits
existierenden technischen Folgeaudits
[`2026-08-25-auth-execution-operations-followup-audit.md`](2026-08-25-auth-execution-operations-followup-audit.md),
[`2026-08-27-tenant-and-compliance-reference-integrity-audit.md`](2026-08-27-tenant-and-compliance-reference-integrity-audit.md)
und
[`2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md`](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md),
anschließend dieses Dokument. Bereits bestätigte Findings aus diesen drei
Dokumenten (`AUTH-TEN-*`, `TEN-COMP-*`, `HANDOFF-*`) werden hier nicht erneut
vergeben, sondern referenziert, wenn sie denselben Sachverhalt betreffen.

Dieses Dokument erteilt keine Rechts-, FINMA- oder Produktionsfreigabe. Es
beantwortet ausschließlich, was der Code für Joiner/Mover/Leaver,
Rezertifizierung, Segregation of Duties, Break-Glass und Supportzugriff
tatsächlich implementiert — nicht, was organisatorisch gewünscht oder
dokumentiert ist.

## Kurzfazit

Der Code besitzt eine funktionierende, mehrfach audit-gehärtete
**Authentifizierungsschicht** (2FA-Replay-Schutz, atomare Einmal-Token,
Session-Widerruf bei Passwortwechsel/Deaktivierung/Rollenänderung, siehe
`AUTH-TEN-01`..`AUTH-TEN-08`). Der dahinterliegende **organisatorische
Identity-Lifecycle** — wer darf wen mit welcher Rolle anlegen, wie wandert eine
Rolle zwischen "Kunde" und "Mitarbeiter", wer prüft erneut, ob eine Rolle noch
gerechtfertigt ist, und wie wird ein privilegierter Eingriff in eine fremde
Firma nachvollziehbar — existiert dagegen nur fragmentarisch oder gar nicht:

1. Ein einzelner `admin`/`super_admin` kann jede erlaubte interne Rolle
   (`admin`, `advisor`, `portfolio_management`, `readonly`) unilateral
   vergeben; es gibt keinen Vier-Augen-Schritt für die Rollenvergabe selbst.
2. Der generische Rollenänderungs-Endpoint prüft nicht, ob der Zielaccount
   ursprünglich ein Kunden-Portal-Login (`role='client'`) war — ein Kunden-
   Account kann live zu `advisor` befördert werden, inklusive dessen vom
   Kunden selbst gesetztem Passwort.
3. `last_login_at` wird geschrieben, aber nirgends gelesen oder alarmiert —
   es gibt keine Dormant-Account-Erkennung.
4. Zwei konkrete Capital-Market-Assumption-Endpoints erlauben derselben Rolle
   (`portfolio_management`/`super_admin`), eine Kapitalmarktannahme selbst zu
   berechnen UND selbst freizugeben — keine zweite Person erforderlich.
5. Es existiert kein Break-Glass-/Notfallzugriffskonzept; die einzige
   standing privilegierte Rolle (`super_admin`) ist dauerhaft und
   unbefristet, nicht zeitlich begrenzt aktivierbar.
6. Der zentrale Audit-Log hat kein Feld für einen Anlass/eine Begründung
   einer privilegierten Aktion; eine Tenant-Suspendierung durch einen
   Operator ist im Log nicht von einer normalen Selbstverwaltungs-Aktion
   unterscheidbar.
7. Es gibt keinen Support-Session-, Zustimmungs- oder Zeitfenster-Mechanismus
   für Zugriff eines Operators auf Kundendaten — der einzige im Code
   gefundene "Support"-Bezug betrifft Log-Redaction, nicht Datenzugriff.
8. Es existiert keine periodische Rezertifizierung bestehender Rollen — weder
   als Job, noch als UI, noch als Datenfeld.

Das bereits bestätigte Fehlen eines Vier-Augen-Prinzips für die
Handoff-Ausführung (`HANDOFF-EXECUTION-001`) wird hier bestätigt, aber nicht
neu vergeben.

## Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `IAM-JML-001` | P1 | offen | Rollenvergabe (Joiner) verlangt keine zweite Person/Freigabe; ein einzelner Admin kann jede interne Rolle unilateral erteilen |
| `IAM-JML-002` | P1 | offen | Generische Rollenänderung (Mover) prüft keine Kategoriegrenze zwischen Kunden-Portal-Identität und interner Mitarbeiterrolle |
| `IAM-DORMANT-001` | P2 | offen | `last_login_at` wird erfasst, aber nirgends für Dormant-/Stale-Account-Erkennung gelesen oder alarmiert |
| `IAM-SOD-001` | P1 | offen | CMA-Kandidatenberechnung und CMA-Freigabe teilen sich dieselbe Rollen-Dependency ohne Vier-Augen-/Zweitprüfer-Zwang |
| `IAM-BREAKGLASS-001` | P2 | offen | Kein Notfall-/Break-Glass-Zugriffskonzept; `super_admin` ist die einzige privilegierte Rolle und dauerhaft, nicht zeitlich begrenzt |
| `IAM-PAM-001` | P1 | offen | Audit-Log kennt keinen Anlass/keine Begründung; privilegierte Operator-Aktionen sind im Log nicht als solche von Selbstverwaltung unterscheidbar |
| `IAM-SUPPORT-001` | P1, bei realem T2/T3-Betrieb konditional P0 | offen | Kein Support-Session-/Consent-/Zeitfenster-Vertrag für Operatorzugriff auf Kundendaten eines Tenants |
| `IAM-RECERT-001` | P2 | offen | Keine periodische Rezertifizierung bestehender Rollen/Rechte (Job, UI oder Datenfeld) gefunden |

Referenziert, nicht neu vergeben: `HANDOFF-EXECUTION-001`
(Portfolio-Handoff-Ausführung ohne Vier-Augen-Freigabe, siehe
[`2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md:158`](2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md)).

## Reale Rollen-/Berechtigungsmatrix (aus dem Code abgeleitet)

Fünf tatsächlich im Code vorkommende Rollenwerte, abgeleitet aus
`services/auth.py` und `schemas/users.py`:

| Rolle | Vergabepfad | Kernbefugnisse (Codeanker) |
|---|---|---|
| `client` | `routers/clients.py:655-745` (`create_client_login`, `require_advisor`) | nur `require_client`-gated Client-Portal-Endpoints; 1:1-Linkage via `ClientLogin` (`services/auth.py:637-713`) |
| `readonly` | `UserCreate`/`UserUpdate` Literal (`schemas/users.py:11,44`) | kein dedizierter Lesepfad gefunden; weder in `require_advisor` (`services/auth.py:269-272`) noch in `require_reference_data_reader` (`services/auth.py:363-376`) explizit vorgesehen — Rollenbedeutung ist im Code nicht spezifiziert |
| `advisor` | `routers/auth.py:873-924` (`create_user`), `:959-1023` (`invite_user`), beide `require_admin` | `require_advisor` (`services/auth.py:269-272`): eigene Clients/Mandate, Empfehlungen, Review |
| `admin` | wie `advisor`, zusätzlich `require_admin` (`services/auth.py:246-251`) | global innerhalb des eigenen Tenants (`has_global_client_access`, `services/auth.py:411-412`); CMA/FX global nur bei nicht-strict Tier 1 (`services/auth.py:296-304`, `:327-330`) |
| `portfolio_management` | ausschließlich via `create_user`/`invite_user` durch `admin`/`super_admin` | `require_portfolio_management` (`services/auth.py:275-304`): globale CMA-Freigabe/-Berechnung unabhängig vom Tenant |
| `super_admin` | nicht über die Standard-Schemas erzeugbar (Literal schließt ihn aus, siehe unten); nur Bootstrap (`routers/auth.py:276-282`, Rolle hartcodiert `'admin'`) — im Code wurde **keine** Stelle gefunden, die einen bestehenden User zu `super_admin` befördert | `require_super_admin` (`services/auth.py:254-266`): Tenant-CRUD, `assign_user_to_tenant`, globale Operatorrechte; `get_current_user` setzt für diese Rolle `set_tenant_context(db, None)` (`services/auth.py:237-242`) |

Wichtiger Negativbefund: `UserCreate.role` und `UserUpdate.role` sind als
`Literal["admin", "advisor", "readonly", "portfolio_management"]`
typisiert (`schemas/users.py:11`, `:44`, `:188`) — **weder `super_admin` noch
`client` sind über die regulären User-Verwaltungs-Endpoints erreichbar.**
Das ist eine wirksame, bereits vorhandene Schranke gegen horizontale
Privilegieneskalation zu `super_admin` über die normale Admin-API. Wie genau
ein `super_admin`-Konto in der Praxis entsteht (außerhalb des harten
Bootstrap-Pfads, der nur `role='admin'` erzeugt), wurde im Code nicht
gefunden — vermutlich ein direkter DB-Eingriff durch den Betreiber. Das ist
nicht negativ für diesen Audit zu werten, aber es bedeutet: `super_admin`
unterliegt keinem im Code sichtbaren Provisionierungs-Vertrag.

## Detailbefunde

### `IAM-JML-001` — Joiner: Rollenvergabe ohne Zweitfreigabe

**Ist-Zustand:** `POST /users` (`create_user`, `routers/auth.py:873-924`) und
`POST /users/invite` (`invite_user`, `routers/auth.py:959-1023`) sind beide
ausschließlich mit `Depends(require_admin)` geschützt — `require_admin`
akzeptiert `role in ("admin", "super_admin")` (`services/auth.py:246-251`).
Ein einzelner Firmen-Admin kann damit allein, ohne zweite Unterschrift, ohne
Review-Queue und ohne zeitliche Verzögerung einen neuen `admin`- oder
`portfolio_management`-Account für die eigene Firma anlegen
(`body.role`, validiert nur gegen das Literal, nicht gegen einen
Freigabeprozess). Es gibt keinen "pending approval"-Zwischenzustand für neu
angelegte privilegierte Rollen.

**Risiko:** Ein kompromittiertes oder böswilliges Admin-Konto kann sich
beliebig viele weitere `admin`-Konten für dieselbe Firma schaffen, ohne dass
ein zweiter Mensch dies vor der Wirksamkeit sieht. Das Audit-Log (`log()`,
`routers/auth.py:920-921`) protokolliert die Aktion erst NACH dem Commit,
nicht als Freigabeschritt davor.

**Auditvertrag:** Für die Vergabe privilegierter interner Rollen
(`admin`, `portfolio_management`) wird ein Vier-Augen-/Genehmigungsschritt
(zweiter Admin oder Operator bestätigt vor Wirksamkeit) oder zumindest eine
verzögerte, widerrufbare Aktivierung mit Benachrichtigung aller bestehenden
Admins der Firma eingeführt. `advisor`/`readonly` können weiterhin direkt
vergeben werden, sofern dies als bewusste Risikoentscheidung dokumentiert
wird.

### `IAM-JML-002` — Mover: Rollenänderung ignoriert Konto-Kategorie

**Ist-Zustand:** `PUT /users/{user_id}` (`update_user`,
`routers/auth.py:1110-1172`) lädt den Zieluser ausschließlich über
`User.id`/Tenant-Sichtbarkeit (`_assert_user_visible_to`,
`routers/auth.py:1233-1258`) und wendet dann jedes in
`_ALLOWED_USER_UPDATE_FIELDS = {"full_name", "email", "role", "is_active"}`
(`routers/auth.py:1143`) enthaltene Feld direkt an — **ohne zu prüfen, welche
Rolle der User vorher hatte.** `UserUpdate.role` erlaubt
`Literal["admin", "advisor", "readonly", "portfolio_management"]`
(`schemas/users.py:44`). Ein User mit `role='client'` (angelegt über
`create_client_login`, `routers/clients.py:729-745`, mit einem vom Kunden
selbst gewählten Passwort und einer aktiven `ClientLogin`-1:1-Linkage,
`models/client_login.py:18-...`) kann über denselben generischen Endpoint auf
`role='advisor'` gesetzt werden. Der Code erkennt lediglich eine
Rollenänderung generisch (`is_role_changing`, `routers/auth.py:1155`) und
widerruft deswegen korrekt alle Sessions (`AUTH-TEN-03`-Fix) — das verhindert
aber nicht die Änderung selbst, sondern nur ein Fortbestehen der alten
Session. Die `ClientLogin`-Zeile bleibt nach einer solchen Umkategorisierung
unverändert aktiv bestehen; es gibt keinen Code, der sie bei einer
Rollenänderung weg von `client` deaktiviert.

**Risiko:** Ein einziger Admin-Fehlklick oder ein kompromittiertes
Admin-Konto kann einen Kunden-Account in einen internen Mitarbeiter-Account
mit Berater-Rechten verwandeln — mit einem Passwort, das der Kunde selbst
gewählt hat und das damit außerhalb der internen Passwort-/Onboarding-Policy
(`must_change_password`, Invite-Flow) liegt. Umgekehrt kann ein Berater- oder
Admin-Konto genauso ungeprüft zu `readonly` degradiert werden, ohne dass eine
fachliche Prüfung stattfindet, ob der Account damit Zugriff auf Daten behält,
die sein ursprünglicher Rollen-Kontext nicht vorsah.

**Auditvertrag:** `update_user` validiert die erlaubte
Rollenübergangsmatrix explizit (z. B. `client -> {advisor, admin,
portfolio_management}` wird nie automatisch erlaubt; eine solche
Umkategorisierung erfordert einen expliziten, separat protokollierten
"convert account"-Workflow, der die bestehende `ClientLogin`-Linkage
zwingend terminiert). Reguläre interne Rollenwechsel
(`advisor <-> portfolio_management`, Beförderung/Degradierung) bleiben
erlaubt, werden aber mit Alt-/Neu-Wert explizit im Audit-Log festgehalten
(derzeit bereits der Fall, siehe `IAM-PAM-001` für die fehlende
Begründungs-Lücke).

### `IAM-DORMANT-001` — Keine Dormant-/Stale-Account-Erkennung

**Ist-Zustand:** `User.last_login_at` (`models/users.py:21`) wird exakt an
einer Stelle geschrieben: `routers/auth.py:402`
(`user.last_login_at = _now()`, direkt nach erfolgreichem Login). Eine
repository-weite Suche nach Lesezugriffen auf dieses Feld außerhalb von
Tests/Schema-Exposition fand nur `schemas/users.py:55`
(`UserResponse.last_login_at`, reine Anzeige) und
`5eyes_schema_v4.0_FINAL.sql:50`/`alembic/versions/c91f2c722881_baseline_schema.py:229`
(Spaltendefinition). Es gibt **keinen** Scheduler-Job, keinen
Health-/Readiness-Check und keinen Admin-UI-Hinweis, der inaktive Accounts
(z. B. "kein Login seit 90 Tagen") erkennt, meldet oder automatisch
deaktiviert.

**Risiko:** Ein Mitarbeiter, der die Firma verlassen hat und dessen Konto
versehentlich nicht deaktiviert wurde, bleibt mit vollem Zugriff unbegrenzt
bestehen, ohne dass irgendein automatisierter Mechanismus dies auffängt.

**Auditvertrag:** Ein periodischer Job (oder ein Readiness-/Admin-Report)
identifiziert Accounts ohne Login seit einer konfigurierbaren Schwelle und
macht sie für Admins sichtbar; optional automatische Deaktivierung nach
Eskalationsstufe. Muss denselben Singleton-/Scheduler-Verträgen folgen wie
die bereits auditierten Backup-/Marktdaten-Jobs
(`OPS-004`, siehe Auth-/Execution-Folgeaudit).

### `IAM-SOD-001` — CMA-Berechnung und -Freigabe ohne Zweitprüfer

**Ist-Zustand:** `POST /jurisdictions/{code}/cma/compute-candidate`
(`compute_cma_candidate`, `routers/jurisdiction.py:258-284`) und
`POST .../capital-market-assumptions/{id}/approve`
(`approve_capital_market_assumption`, `routers/jurisdiction.py:308-339`)
sind **beide** ausschließlich mit `Depends(require_portfolio_management)`
geschützt (`routers/jurisdiction.py:263`, `:316`).
`require_portfolio_management` (`services/auth.py:275-304`) lässt jeden User
mit Rolle `portfolio_management` oder `super_admin` (und, außerhalb des
Strict-Modus, auch `admin`) durch. Es gibt **keine** Prüfung, ob der
freigebende User (`approve_capital_market_assumption`) eine andere Person ist
als der User, der den Kandidaten erzeugt hat
(`compute_cma_candidate`) — beide Endpoints akzeptieren denselben
`current_user`. Der approve-Endpoint liest `cma.id` direkt und prüft nur
Existenz/`deleted_at`, nicht den erzeugenden Actor.

**Risiko:** Eine einzelne Person kann eine Kapitalmarktannahme berechnen und
sofort selbst auf `committee_approved` freigeben, wodurch sie laut
Docstring (`routers/jurisdiction.py:318-331`) **sofort aktiv** (`is_current=1`)
wird und nachgelagerte Portfolio-/Goal-/Monte-Carlo-Berechnungen beeinflusst.
Das widerspricht dem im WP-Dokument referenzierten IC-Freigabe-Konzept
("data_derived" -> "committee_approved" durch ein Committee, nicht durch den
Ersteller selbst).

**Auditvertrag:** `approve_capital_market_assumption` verlangt, dass
`current_user.id` vom Actor abweicht, der den jeweiligen `candidate`-Eintrag
erzeugt hat (Actor-Feld am `CapitalMarketAssumption`-Datensatz oder über den
Audit-Log-Eintrag der CREATE-Aktion aufgelöst). Fehlt ein abweichender
Zweitprüfer, wird die Freigabe mit 409 abgelehnt. `super_admin` kann als
expliziter, separat protokollierter Notfall-Override ausgenommen werden,
siehe `IAM-BREAKGLASS-001`.

### `IAM-BREAKGLASS-001` — Kein Notfall-/Break-Glass-Konzept

**Ist-Zustand:** Eine repository-weite Suche (Code, Tests, `docs/`) nach
`break glass`, `emergency access`, `Notfallzugriff` und äquivalenten Begriffen
ergab **keinen Treffer** im Produktcode. Die einzige im Code existierende
dauerhaft privilegierte Rolle ist `super_admin`
(`require_super_admin`, `services/auth.py:254-266`) — sie ist eine
Standing-Rolle ohne Ablaufdatum, ohne Aktivierungs-/Deaktivierungs-Workflow
und ohne separate Protokollierung "diese Aktion wurde im Notfallmodus
ausgeführt". `set_operator_bypass`/`operator_bypass`
(`services/tenant_context.py:112-137`) existiert zwar als expliziter
RLS-Bypass-Mechanismus für Wartungsjobs, ist aber laut eigenem Docstring
("Normal `super_admin` request handling does not call this") nicht an
reguläre Request-Pfade angebunden und wird in den durchsuchten Routern nicht
aufgerufen — er ist ein Wartungs-/Job-Primitiv, kein Notfallzugriffs-Feature
für Menschen.

**Risiko:** Jede "dringende" privilegierte Aktion läuft über dieselbe
dauerhafte `super_admin`-Rolle wie der reguläre Betrieb. Es gibt keine
Möglichkeit, eine zeitlich begrenzte, besonders protokollierte Eskalation von
einer regulären Operator-Session zu unterscheiden — was bei einer
nachträglichen Untersuchung (wer hat wann warum auf Kundendaten zugegriffen)
keine Differenzierung erlaubt.

**Auditvertrag:** Falls ein Notfallzugriffspfad fachlich benötigt wird
(z. B. Kunde meldet sich blockiert, Produktionsvorfall), wird er als
expliziter, zeitlich begrenzter, separat begründeter und separat
protokollierter Modus definiert — nicht als impliziter Nebeneffekt der
Standing-`super_admin`-Rolle. Ist kein solcher Pfad gewünscht, wird dies
bewusst als Entscheidung dokumentiert ("kein Break-Glass, jede privilegierte
Aktion läuft über die regulär vergebene `super_admin`-Rolle").

### `IAM-PAM-001` — Audit-Log ohne Anlass/Begründung privilegierter Aktionen

**Ist-Zustand:** `AuditLog` (`models/review.py:490-539`) hat die Felder
`id, user_id, user_name, table_name, record_id, action, field_name,
old_value, new_value, mandate_id, client_id, integrity_hash, ip_address,
created_at, tenant_id, sequence, previous_hash` — **kein Feld für einen vom
Actor angegebenen Anlass/eine Begründung.** `services/audit.py::log()`
(`services/audit.py:191-265`) hat ebenfalls keinen `reason`-Parameter.
`TenantUpdate` (`schemas/tenants.py:81-96`) — über die ein `super_admin` u. a.
`is_active` auf 0 setzen oder `license_status` auf `suspended` setzen kann
(`routers/tenants.py:233-268`, `update_tenant`) — hat ebenfalls kein
`reason`-Feld. Die resultierende Log-Zeile (`action="UPDATE"`,
`table_name="tenants"`) ist identisch aufgebaut, ob ein Firmen-Admin seine
eigene Firmenanschrift ändert (`update_my_tenant`,
`routers/tenants.py:97-127`, ebenfalls `action="UPDATE"`) oder ob ein
Operator eine fremde Firma sperrt — beide Aktionen sind im Log nur über
`user_id`/`tenant_id` und den reinen Feld-Diff unterscheidbar, nicht über
einen erkennbaren "privilegierte Operator-Aktion"-Marker.

**Risiko:** Eine spätere forensische Auswertung kann nicht gezielt nach
"alle Aktionen, bei denen ein Operator außerhalb seines eigenen Tenant-Scopes
gehandelt hat, inklusive Begründung" filtern, ohne jede Zeile einzeln gegen
den aktuellen (nicht historischen) Rollen-/Tenant-Stand des `user_id`
abzugleichen.

**Auditvertrag:** `log()` erhält ein optionales, für klar definierte
privilegierte Aktionskategorien (Tenant-Suspendierung, Cross-Tenant-User-
Zuweisung, globale Referenzdaten-Freigabe) **pflichtiges** `reason`-Feld;
betroffene Endpoints erweitern ihre Request-Schemas entsprechend. Zusätzlich
wird pro Eintrag festgehalten, ob der Actor zum Zeitpunkt der Aktion
innerhalb des eigenen Tenant-Scopes oder im Operator-/Cross-Tenant-Scope
gehandelt hat (nicht erst retrospektiv aus dem aktuellen User-Datensatz
hergeleitet).

### `IAM-SUPPORT-001` — Kein Support-Session-/Consent-/Zeitfenster-Vertrag

**Ist-Zustand:** Eine repository-weite Suche nach `support_access`,
`support_session`, `impersonat*` ergab zwei Treffer, beide fachlich
unabhängig von Live-Datenzugriff: `services/wealth_position_semantics.py`
(unabhängiger Kontext) und `tests/test_optimizer_production_contract.py`.
`docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md:38-41` ("Logs, Diagnostics And
Support Bundles") beschreibt ausschließlich Redaction von Diagnose-Log-
Bundles, nicht Live-Zugriff auf Kundendaten. Der tatsächliche
Live-Datenzugriffspfad für einen Operator ist die Standing-`super_admin`-
Rolle: `get_current_user` setzt für `role == "super_admin"`
`set_tenant_context(db, None)` (`services/auth.py:237-242`); `list_users`
(`routers/auth.py:851-870`) liefert für `super_admin` explizit ALLE Tenants
ohne Filter zurück ("super_admin (Operator) sieht ALLE User", Kommentar
Zeile 856-858). Es gibt **keinen** Mechanismus, der vor einem solchen
Zugriff eine Kundenfirma informiert, eine Zustimmung einholt, den Zugriff auf
ein Zeitfenster begrenzt oder ihn separat von regulärer Plattform-
Administration kennzeichnet.

**Risiko:** In einem produktiven Tier-2/Tier-3-Betrieb mit mehreren
Kundenfirmen auf derselben Installation kann ein Operator-Account jederzeit,
ohne Benachrichtigung der betroffenen Firma und ohne zeitliche Begrenzung,
auf Daten jeder Firma zugreifen. Das ist für ein reines Tier-1-
Einzelinstallationsmodell (ein Tenant `main`) folgenlos, wird aber beim
tatsächlichen Mehrmandanten-Betrieb zu einem Vertrauens-/Vertragsproblem
(siehe `TRUST-05`/`ASSURE-07` im Readiness-Plan).

**Auditvertrag:** Für Tier-2/Tier-3 wird ein expliziter Support-Access-Modus
eingeführt: zeitlich begrenzte Aktivierung für einen konkreten Tenant, mit
Anlass, optionaler Kundenzustimmung/-benachrichtigung je Vertrag, und einer
im Audit-Log klar erkennbaren eigenen Aktionskategorie (nicht impliziter
Nebeneffekt der `super_admin`-Rolle). Tier-1 (Einzelinstallation, ein
Tenant) ist von dieser Pflicht ausgenommen, da dort kein fremder Tenant
existiert.

### `IAM-RECERT-001` — Keine periodische Rezertifizierung

**Ist-Zustand:** Eine repository-weite, case-insensitive Suche nach
`rezertifizier*`/`recertif*` ergab ausschließlich zwei Treffer in
bestehenden Audit-Dokumenten (`2026-09-03-portfolio-handoff-...md`,
`2026-10-04-jurisdiction-cma-...md`), die den Begriff "Vier-Augen" referenzieren
— keinen Treffer im Produktcode, keinen Scheduler-Job, keine UI-Komponente,
kein Datumsfeld wie `role_last_reviewed_at`. Weder `User` noch
`AdviserRegistration` (`models/users.py`) besitzen ein Feld, das eine
regelmäßige Überprüfung der zugewiesenen Rolle festhält.

**Risiko:** Rollen, die einmal vergeben wurden (insbesondere `admin`,
`super_admin`, `portfolio_management`), bleiben ohne jede erzwungene
Wiedervorlage unbegrenzt bestehen, unabhängig davon, ob die fachliche
Rechtfertigung noch besteht (Rollenwechsel im Unternehmen, abgeschlossenes
Projekt, vorübergehende Freigabeerweiterung).

**Auditvertrag:** Ein periodischer Rezertifizierungsprozess (mindestens für
`admin`/`super_admin`/`portfolio_management`) mit Fälligkeitsdatum pro
Zuweisung, sichtbarer Admin-Übersicht überfälliger Rezertifizierungen und
optional automatischer Downgrade/Deaktivierung bei Nichtbestätigung. Muss den
bereits etablierten Scheduler-Singleton-Verträgen folgen (`OPS-004`).

## Beantwortung der zehn Auditpunkte

1. **Rollenmatrix:** siehe Tabelle oben; fünf reale Rollen
   (`client`, `readonly`, `advisor`, `admin`, `portfolio_management`,
   `super_admin` — sechs Werte, `readonly` ohne erkennbare Code-Semantik).
2. **Joiner:** `create_user`/`invite_user`, beide `require_admin`, kein
   Freigabeschritt — `IAM-JML-001`.
3. **Mover:** `update_user` ändert Rolle/Tenant-Zuweisung ohne
   Kategoriegrenzen-Prüfung — `IAM-JML-002`; Tenant-Zuweisung selbst
   (`assign_user_to_tenant`) hat einen Verwaisungs-Guard, aber keinen
   Rollen-Kategorie-Guard.
4. **Leaver:** `is_active=0` über `update_user` widerruft seit `AUTH-TEN-03`
   korrekt alle Sessions (bestätigt, kein neuer Fund); eine vollständige
   Account-/Datenoffboarding-Lücke (Löschung/Anonymisierung) ist bereits unter
   `PRIV-004`/`TRUST-08` im Datenlebenszyklus-Audit dokumentiert und wird hier
   nicht erneut vergeben.
5. **Dormant Accounts:** `last_login_at` existiert, wird aber nirgends
   gelesen — `IAM-DORMANT-001`.
6. **Segregation of Duties:** kein generisches Vier-Augen-Pattern im Code
   gefunden; konkrete Lücke bei CMA-Berechnung/-Freigabe (`IAM-SOD-001`);
   Handoff-Ausführung bereits unter `HANDOFF-EXECUTION-001` bestätigt offen.
7. **Break-Glass:** nicht vorhanden — `IAM-BREAKGLASS-001`.
8. **Privilegierter Audit-Trail:** AuditLog hat Actor/Zeitstempel/Hash, aber
   keinen Anlass/keine Scope-Kennzeichnung — `IAM-PAM-001`.
9. **Supportzugriff:** kein Consent-/Zeitfenster-Mechanismus; Zugriff läuft
   über die Standing-`super_admin`-Rolle — `IAM-SUPPORT-001`.
10. **Rezertifizierung:** nicht vorhanden — `IAM-RECERT-001`.

## Verifikation dieser Runde

- Rollen-/Berechtigungslogik wurde direkt aus `services/auth.py` (vollständig
  gelesen, 714 Zeilen) sowie `routers/auth.py` (vollständig gelesen, 1398
  Zeilen) abgeleitet, nicht aus Kommentaren oder Dokumentation übernommen.
- `models/users.py`, `models/review.py::AuditLog`/`AuditLogSequenceCounter`,
  `services/audit.py`, `services/tenant_context.py`,
  `schemas/users.py`, `schemas/tenants.py`, `routers/tenants.py`,
  `routers/jurisdiction.py` (CMA-Abschnitt) und `routers/clients.py`
  (`create_client_login`) wurden vollständig oder gezielt im relevanten
  Abschnitt gelesen.
- Repository-weite Suchen (nicht nur Stichproben) für
  `vier augen|four eyes|dual_control|second_approver|break.?glass|
  Notfallzugriff|emergency access|recertif|Rezertifizierung`,
  `last_login_at`, `support_access|support_session|impersonat`, und
  `role="client"` wurden ausgeführt; alle Treffer wurden einzeln geprüft
  und sind oben zitiert.
- Es wurde **kein** Produktcode, keine Testdatei, keine Migration und keine
  Konfiguration verändert. Es wurde **keine** Testsuite ausgeführt — dieser
  Audit ist reine statische Quellcode-/Schema-Analyse, kein
  Laufzeit-Reproduktionsaudit wie die referenzierten Folgeaudits.
- Nicht geprüft: Verhalten unter echter PostgreSQL-RLS-Policy-Definition
  (die SQL-Policy-Dateien selbst wurden nicht gelesen); tatsächliches
  Frontend-/UI-Verhalten für Rollenverwaltung; ob ein Betreiber außerhalb des
  Codes (z. B. per manuellem DB-Zugriff) zusätzliche Kontrollen für die
  `super_admin`-Erstvergabe etabliert hat.

## Selbst-Audit und Nachweisgrenzen

- Produktcode verändert: **nein**
- Tests verändert oder ausgeführt: **nein**; reine read-only Quellcode- und
  Schemaanalyse, keine Laufzeit-Reproduktion
- Neue Findings dieser Runde: 8 (`IAM-JML-001/002`, `IAM-DORMANT-001`,
  `IAM-SOD-001`, `IAM-BREAKGLASS-001`, `IAM-PAM-001`, `IAM-SUPPORT-001`,
  `IAM-RECERT-001`)
- Referenzierte, nicht neu vergebene bestehende Findings: `HANDOFF-EXECUTION-001`,
  `AUTH-TEN-01`..`AUTH-TEN-08`, `TEN-COMP-001`, `PRIV-004`/`TRUST-08`
- Nicht behauptet: Vollständigkeit aller Rollen-Gate-Funktionen im gesamten
  Router-Baum (es wurden die für JML/PAM/SoD/Support/Recert relevanten
  Dateien vollständig gelesen, nicht jede einzelne von 21 Router-Dateien
  zeilenweise auf jede denkbare Rollenprüfung); keine Aussage über
  organisatorische Prozesse außerhalb des Repositories (z. B. ob ein
  Betreiber manuell eine Rezertifizierung per E-Mail durchführt)
- Ergebnis: Der in `B2B-COVERAGE-003` verlangte Auditvertrag ist mit dieser
  Runde erfüllt — Rollenmatrix, JML-Vertrag und acht konkrete, mit
  Datei:Zeile belegte Lücken liegen vor. Die Umsetzung der
  Fixverträge ist ein separater, nicht in dieser Runde begonnener Schritt.
