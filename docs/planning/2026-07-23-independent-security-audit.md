# Unabhängige Sicherheits-Tiefenprüfung — 2026-07-23

Frische, eigenständige Analyse (nicht auf ein bestehendes Audit-Dokument gestützt) mit
Fokus auf Tenant-Isolation, Auth-Boundary-Fälle und Daten-Leck-Risiken. Methodik: jeder
Router (`5eyes-backend/routers/*.py`, 20 Dateien, ~10'350 Zeilen) wurde vollständig
gelesen; jeder Endpoint mit Pfad-Parameter (`{client_id}`, `{mandate_id}`, `{user_id}`,
`{baustein_id}`, `{policy_id}`, …) wurde gegen das etablierte Ownership-Muster geprüft
(`get_client_for_user_or_404`, `get_mandate_for_user_or_404`,
`get_linked_client_for_user_or_404`, `_assert_user_visible_to`, `has_global_client_access`
+ `_apply_tenant_filter_to_client_query`/`_apply_tenant_filter_to_mandate_query`).
Zusätzlich: IDOR-Analyse (ID-Format), 404-vs-403-Existenz-Leak-Konsistenz,
Passwort/Token/Secret-Logging-Grep.

Branch: `security/deep-audit-2026-07-23` (von `develop`). Alle Fixes additiv, mit Tests.

## Zusammenfassung

| # | Titel | Schweregrad | Status |
|---|-------|-------------|--------|
| F1 | Cross-Tenant-Passwort-Übernahme via `PUT /users/{user_id}/password` | **KRITISCH** | **GEFIXT** |
| F2 | Cross-Tenant-Zugriff auf FINMA-Beraterregistrierung | **MITTEL** | **GEFIXT** |
| F3 | Cross-Tenant-Leck in der Beratungsprotokoll-Bausteine-Bibliothek | **MITTEL** | **GEFIXT** |
| F4 | Phase-0-Datenklassifizierungs-Gate fehlt bei WealthInflow/PlanningAssumption | NIEDRIG | dokumentiert, nicht gefixt |
| F5 | `super_admin` durch Tippfehler von eigener Adviser-Registration-Ansicht ausgeschlossen | INFO (Nebenfund) | als Teil von F2-Fix mitkorrigiert |
| F6 | Postgres-RLS-Prädikat behandelt `tenant_id IS NULL`-Zeilen für `super_admin` potenziell restriktiv | INFO | dokumentiert, nicht gefixt (fail-closed, kein Leck) |
| F7 | `/admin/system/clients/{client_id}/purge-demo` — IDOR-Verdacht verifiziert und **entkräftet** | — | kein Fund (false positive ausgeschlossen) |

**3 Findings gefixt (1 kritisch, 2 mittel), 2 nur dokumentiert (niedrig/info), 1 Verdacht
geprüft und als sicher bestätigt.** Alle Fixes sind additive Tenant-/Sichtbarkeits-Checks,
die exakt dem bereits etablierten `_assert_user_visible_to`- bzw.
`_apply_tenant_filter_to_client_query`-Muster folgen. 13 neue Regressions-/Exploit-Tests in
`tests/test_independent_security_audit_2026_07_23.py`, alle grün. `scripts/security_gate.py`
grün (165 passed, 4 skipped [Postgres-only]).

---

## F1 — KRITISCH: Cross-Tenant-Passwort-Übernahme via `PUT /users/{user_id}/password`

**Datei:** `5eyes-backend/routers/auth.py`, Funktion `reset_user_password` (vor Fix: Zeilen
695–724).

**Befund:** Der Endpoint erlaubt zwei Pfade: Self-Service (eigenes Passwort) oder
Admin-Reset (fremdes Passwort). Der Admin-Pfad prüfte ausschließlich die **Rolle**
(`admin`/`super_admin`), aber **nie** die Tenant-Zugehörigkeit des Ziel-Users:

```python
is_self = (current_user.id == user_id)
if not is_self and getattr(current_user, "role", None) not in ("admin", "super_admin"):
    raise HTTPException(status_code=403, detail="Nur das eigene Passwort oder als Admin aenderbar")
user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
if not user:
    raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
user.password_hash = hash_password(body.new_password)   # <- KEIN Tenant-Check davor
```

Das ist exakt das im Auftrag beschriebene Muster: ein bestehender Sicherheitsmechanismus
(`_assert_user_visible_to`, Zeile 727 vor dem Fix) existiert im selben Router und wird
für `update_user` (Zeile 653), `resend_invite` (Zeile 743) und `revoke_invite` (Zeile 787)
korrekt aufgerufen — aber **nicht** für `reset_user_password`. Ein tenant-gebundener
Firmen-Admin (role='admin', z.B. Firma A) konnte damit das Passwort **jedes Users in der
gesamten Datenbank** setzen — auch von Usern eines fremden Tenants (Firma B) oder eines
anderen Admins — sofern die (UUID-)`user_id` bekannt war. Das ist eine vollständige
Account-Übernahme quer über die Mandantengrenze (Tenant-Isolation-Bruch mit
Privilegien-Eskalation).

**Impact:** Vollständige Kontoübernahme eines fremden Tenants durch einen
niedriger-privilegierten Firmen-Admin. FINMA/DSG-kritisch (Zugriff auf alle Kundendaten
des übernommenen Accounts).

**Fix (bereits angewendet):** Ruft vor dem Passwort-Set `_assert_user_visible_to(current_user,
user)` auf (identisches Muster wie `resend_invite`/`revoke_invite`), aber nur im
Fremd-Reset-Zweig (`not is_self`) — der Self-Service-Pfad bleibt unverändert erreichbar
(kein Aussperren). 404 (nicht 403) bei fremdem Tenant, damit die Existenz des Ziel-Users
nicht geleakt wird — konsistent mit dem Rest des Routers.

**Tests:** `tests/test_independent_security_audit_2026_07_23.py`
- `test_admin_cannot_reset_password_of_foreign_tenant_user` — 404, Passwort unverändert
- `test_admin_can_reset_password_of_same_tenant_user` — Regression: Same-Tenant weiter erlaubt
- `test_self_password_reset_still_works_without_tenant` — Regression: Self-Service intakt
- `test_super_admin_can_reset_password_across_tenants` — Regression: Operator-Rolle bleibt unscoped

---

## F2 — MITTEL: Cross-Tenant-Zugriff auf FINMA-Beraterregistrierung

**Datei:** `5eyes-backend/routers/auth.py`, `get_adviser_registration` /
`upsert_adviser_registration` (vor Fix: Zeilen 812–857).

**Befund:** Gleiches Muster wie F1, andere Ressource. `GET` prüfte nur
`current_user.role != "admin" and current_user.id != user_id` (403 sonst), `PUT` nur
`require_admin` — beide **ohne** `_assert_user_visible_to`. Ein Firmen-Admin von Firma A
konnte damit die FINMA-Registrierungsdaten (Registernummer, Ombudsstelle,
Ombudsmitgliedsnummer, Qualifikationen) eines Beraters von Firma B lesen **und
überschreiben** (`upsert`, kein Delete-Endpoint vorhanden).

```python
if current_user.role != "admin" and current_user.id != user_id:
    raise HTTPException(status_code=403, ...)
reg = db.query(AdviserRegistration).filter(AdviserRegistration.user_id == user_id, ...).first()
```

Nebenfund (F5, kein Sicherheitsproblem, aber Verfügbarkeits-Bug): die Rollen-Prüfung
`!= "admin"` schloss `super_admin` fälschlich aus (super_admin konnte fremde
Registrierungen nicht einsehen, obwohl er das laut Rollenkonzept dürfen sollte) — beim
Fix mit auf `not in ("admin", "super_admin")` korrigiert (reine Erweiterung, kein
Sicherheitsverlust).

**Impact:** Cross-Tenant-Informationsleck (Personendaten eines Beraters einer fremden
Firma) + Möglichkeit, fremde Compliance-Stammdaten zu manipulieren (Integritätsrisiko für
FINMA-Nachweise).

**Fix:** `_assert_user_visible_to(current_user, target_user)` in beiden Endpoints vor dem
eigentlichen Read/Write, analog F1.

**Tests:** `test_admin_cannot_view_foreign_tenant_adviser_registration`,
`test_admin_cannot_upsert_foreign_tenant_adviser_registration` (verifiziert zusätzlich,
dass **kein** Datensatz für den fremden User entsteht), `test_admin_can_manage_same_tenant_adviser_registration` (Regression).

---

## F3 — MITTEL: Cross-Tenant-Leck in der Beratungsprotokoll-Bausteine-Bibliothek

**Datei:** `5eyes-backend/routers/protocol_bausteine.py`.

**Befund:** Als einziger Router in der Codebase (verglichen mit `clients.py`, `auth.py`,
`review.py`, …) wendete dieser Router **nie** einen Tenant-Filter an, obwohl
`ProtocolBaustein.tenant_id` existiert (`models/protocol_bausteine.py:25`, sogar mit
eigenem Index `ix_protocol_bausteine_tenant`) und bei `create_baustein` korrekt befüllt
wird (Zeile 128 vor Fix). Drei konkrete Lücken:

1. **`list_bausteine`** (vor Fix, Zeile 87–111): für `role == "admin"` komplett
   ungefiltert — ein Admin sah die **gesamte** Baustein-Bibliothek **aller** Tenants.
   ```python
   q = db.query(ProtocolBaustein).filter(ProtocolBaustein.deleted_at.is_(None))
   if current_user.role != "admin":
       q = q.filter((ProtocolBaustein.advisor_id == current_user.id) | (ProtocolBaustein.advisor_id.is_(None)))
   # kein Tenant-Filter, weder hier noch fuer admin
   ```
   Vergleiche `routers/clients.py::list_clients`, wo explizit dokumentiert ist:
   *"Tenant-Filter IMMER anwenden — auch fuer globale Admins. Sonst sieht ein
   tenant-gebundener Admin (role=admin) Clients fremder Tenants."* — exakt dieses Muster
   fehlte hier.
2. **`_can_edit_baustein`** (vor Fix, Zeile 72–79): gab für **jeden** `admin` blanko
   `True` zurück, unabhängig vom Tenant des Bausteins. `update_baustein` und
   `delete_baustein` konnten damit von einem Firma-A-Admin auf einen Firma-B-Baustein
   angewendet werden (Inhalts-Manipulation/-Löschung fremder Firmendaten).
3. **`replace_mandate_selections`** (vor Fix, Zeile 245–286): die Ownership-Prüfung der
   ausgewählten Bausteine prüfte nur `advisor_id` und nur für Nicht-Admins — ein
   **globaler** (`advisor_id IS NULL`) Baustein einer fremden Firma B konnte von JEDEM
   Berater (auch Firma A) unbemerkt in ein Mandat von Firma A gezogen werden. Damit
   könnte firmeninternes/proprietäres Protokolltext-Material von Firma B im
   kundenfacing Beratungsprotokoll von Firma A auftauchen.

**Einordnung Postgres/Tier-2:** Auf PostgreSQL (Shared-Cloud, das einzige echte
Multi-Tenant-Deployment) ist `protocol_bausteine` unter den RLS-geschützten Tabellen
(`services/postgres_rls.py::import_tenant_models`), d.h. dort greift zusätzlich eine
DB-seitige Tenant-Policy als zweite Verteidigungslinie. Auf SQLite (Tier 1, i.d.R.
Single-Tenant) ist die Frage praktisch irrelevant, da es dort nur einen Tenant gibt.
Der Router-Layer-Fix schließt trotzdem die Lücke in der Verteidigungslinie, die laut
etabliertem Codebase-Standard ("Tenant-Filter IMMER anwenden") an dieser Stelle erwartet
wird (Defense-in-Depth, keine Abhängigkeit von einer einzigen Schicht).

**Fix:** Neue Helper `_baustein_tenant_visible` (Einzel-Objekt-Check) und
`_apply_tenant_filter_to_baustein_query` (Query-Variante) — 1:1-Spiegel von
`services.auth._apply_tenant_filter_to_client_query` (gleiche Legacy-/Strict-Semantik:
User ohne Tenant sieht alles unverändert; Baustein ohne Tenant ist global sichtbar außer
im Strict-Modus). Angewendet in `list_bausteine` (immer, auch für admin),
`_can_edit_baustein` (Vorbedingung vor dem Rollen-Check) und
`replace_mandate_selections` (zusätzliche Prüfung über alle Rollen, unabhängig vom
bestehenden `advisor_id`-Check).

**Tests:** `test_admin_list_bausteine_excludes_foreign_tenant`,
`test_admin_cannot_edit_foreign_tenant_baustein`,
`test_admin_cannot_delete_foreign_tenant_baustein`,
`test_admin_can_edit_same_tenant_baustein` (Regression),
`test_replace_mandate_selections_rejects_foreign_tenant_baustein`,
`test_replace_mandate_selections_allows_same_tenant_baustein` (Regression, inkl. globaler
`tenant_id=None`-Baustein).

---

## F4 — NIEDRIG (dokumentiert, nicht gefixt): Phase-0-Datenklassifizierungs-Gate fehlt bei WealthInflow/PlanningAssumption

**Dateien:** `5eyes-backend/schemas/wealth.py` (`WealthInflowCreate`/`Update`,
`PlanningAssumptionCreate` — kein `data_classification`-Feld), entsprechend
`routers/wealth.py::create_wealth_inflow`/`update_wealth_inflow`/
`create_planning_assumptions`/`upsert_planning_assumptions` rufen nie
`enforce_data_classification()` auf.

**Befund:** `services/data_classification.py::enforce_data_classification` blockiert in
Phase 0 (`settings.allow_real_client_data=False`) das Schreiben von echten (nicht
synthetischen) Kundendaten — ein Compliance-Testbetrieb-Schutz, kein klassischer
Auth-Bug. Der Router-Code selbst dokumentiert bereits einen historischen Fall exakt
dieses Musters (`schemas/wealth.py:61-66`, Kommentar zu `WealthPositionCreate`: *"bislang
FEHLTE dieses Feld... Vermoegenspositionen waren damit die einzigen sensiblen
Datensaetze, die das Phase-0-Gate umgehen konnten"*) — dieselbe Lücke besteht aktuell
noch für `WealthInflow` (Erbschaft/Bonus-Beträge, `schemas/wealth.py:286-318`) und
`PlanningAssumption` (`schemas/wealth.py:550-557`).

**Warum nicht gefixt:** Kein Tenant-Isolation-/Auth-Boundary-Fall (Kern-Scope dieses
Audits), sondern eine Policy-Kontrolle. Ein korrekter Fix erfordert ein neues Feld auf
zwei Pydantic-Schemas (`schemas/wealth.py`, außerhalb der zulässigen Datei-Grenze
`routers/*.py` dieses Auftrags) plus Router-Anpassung — kein reiner additiver
Router-Fix. Empfehlung: gleiches Muster wie bei `WealthPositionCreate` in einem
eigenständigen kleinen Fix nachziehen (`data_classification: Literal["synthetic",
"real"] = "synthetic"` auf beiden Create-Schemas + `enforce_data_classification(...)`-
Aufruf in den vier Endpoints).

---

## F6 — INFO (dokumentiert, kein Fix nötig): Postgres-RLS-Prädikat und `tenant_id IS NULL`

**Datei:** `5eyes-backend/services/postgres_rls.py::_policy_predicate`,
`services/tenant_context.py::set_tenant_context`.

**Beobachtung:** Das RLS-Prädikat ist `tenant_id::text = current_tenant OR bypass`. Für
`super_admin` wird der Tenant-GUC explizit auf leer gesetzt (`set_tenant_context(db,
None)` in `services/auth.py::get_current_user`), was via `NULLIF(...,'')` zu `NULL`
wird — `tenant_id::text = NULL` ist in SQL immer `NULL` (falsy), nicht `TRUE`, auch für
Zeilen mit `tenant_id IS NULL`. Ohne einen expliziten `operator_bypass()`-Kontext würde
ein `super_admin` auf PostgreSQL dadurch **gar keine** Zeilen sehen (fail-closed) —
kein Leck, aber ein potenzieller Funktions-/Verfügbarkeits-Bug, falls ein
`super_admin`-Pfad existiert, der ohne `operator_bypass()` auf RLS-Tabellen zugreift, ohne
das zu erwarten. Dies liegt außerhalb des Scopes "Tenant-Isolation/Leck" (es ist die
sichere Richtung: zu wenig statt zu viel Zugriff) und wurde nicht tiefer verifiziert
(kein PostgreSQL-Testsystem in dieser Session verfügbar; SQLite überspringt RLS komplett,
siehe `test_postgres_rls_adversarial.py`-Skips im Gate-Lauf). Empfehlung: gezielter
Folge-Check, ob alle `super_admin`-Leseflüsse auf RLS-Tabellen entweder `operator_bypass()`
nutzen oder bewusst leer zurückkommen sollen.

---

## F7 — Verdacht geprüft und entkräftet: `POST /admin/system/clients/{client_id}/purge-demo`

**Datei:** `5eyes-backend/routers/system.py:713-733`, Service
`services/foundation_purge.py::purge_demo_client_data`/`assert_demo_client_purge_allowed`.

**Erst-Verdacht:** Endpoint nimmt einen rohen `client_id`-Pfad-Parameter und ist nur mit
`require_admin` geschützt (kein `get_client_for_user_or_404`) — sieht auf den ersten
Blick nach einem IDOR aus, mit dem ein tenant-gebundener Admin einen fremden Client
hart löschen könnte.

**Verifikation:** `purge_demo_client_data` ruft zuerst
`assert_demo_client_purge_allowed(db, client_id)` auf, welche prüft, ob `client_id`
identisch mit dem fest verdrahteten Foundation-/Demo-Kunden ist
(`_is_foundation_client`, Abgleich über `FOUNDATION_CLIENT_NUMBER`/
`FOUNDATION_MANDATE_NUMBER` — Konstanten, kein Nutzereingabe-Pfad). Für jede andere
`client_id` liefert die Funktion `{"status": "not_found", ...}` **ohne** irgendeine
Löschung. Zusätzlich blockt `_app_env() == "production"` das Purge komplett. Der
Endpoint ist also — trotz fehlendem Ownership-Check — **nicht** exploitierbar: er kann
strukturell nur den einen bekannten Demo-Datensatz treffen, nie einen echten
Kunden-Datensatz eines fremden (oder des eigenen) Tenants. Kein Fund, keine Änderung
nötig.

---

## Vollständigkeits-Nachweis (keine weiteren Funde)

Folgende Router wurden vollständig gelesen und boten **keine** Auffälligkeiten (jeder
Endpoint mit `{client_id}`/`{mandate_id}`/`{user_id}`-Pfadparameter ruft vor
Datenzugriff den etablierten Ownership-Helper auf; 404 statt 403 wird konsistent
verwendet, um Existenz-Leaks zu vermeiden):

- `routers/clients.py`, `routers/mandates.py`, `routers/wealth.py`,
  `routers/profiling.py`, `routers/allocation.py`, `routers/review.py`
  (inkl. `products_router`/`recommendations_router`/`dashboard_router`),
  `routers/snapshots.py`, `routers/tenants.py`, `routers/client_portal.py`,
  `routers/pdf_reports.py` (alle 11 PDF-Endpoints verifiziert),
  `routers/cost_disclosure.py`, `routers/fx_rates.py`, `routers/prices.py`,
  `routers/market_data.py`, `routers/tax.py`, `routers/health.py`.
- `routers/system.py`: alle Endpoints außer dem geprüften F7 sind entweder global
  (Marktdaten/DB-Wartung, korrekt `require_admin`/`require_super_admin`) oder
  bereits korrekt mandatengescoped (`/shadow-comparison/{mandate_id}` ruft
  `get_mandate_for_user_or_404` — mit explizitem Sicherheits-Kommentar im Code).
- `OptimizerPolicy`/`HouseMatrix`/`BuildingBlock`/`CapitalMarketAssumption`/
  `FXRate`/`Product` sind global geteilte Referenzdaten ohne `tenant_id`-Spalte —
  Admin-weite Sichtbarkeit ist hier by design, kein Leck.

**IDOR-Bewertung (Item 4 im Auftrag):** Alle Primärschlüssel werden über
`database.py::new_uuid()` (= `str(uuid.uuid4())`) erzeugt — keine sequentiellen IDs in
der gesamten Codebase gefunden. Rate-/Enumeration-Angriffe auf IDs sind praktisch nicht
durchführbar; die primäre (und einzige verlässliche) Schutzschicht bleibt der
Ownership-Check pro Endpoint, der mit den drei oben genannten Ausnahmen (F1-F3)
durchgängig korrekt implementiert ist.

**Secret-Logging-Grep (Item 6 im Auftrag):** `grep -rn` nach
`log(ger|ging)\.\w+\(...(password|secret|token)` über den gesamten Backend-Code ergab
**keinen Treffer**. Manuelle Durchsicht von `routers/auth.py` (Login, 2FA, Passwort-Reset,
Invite), `services/login_guard.py` und `services/mailer.py` bestätigt: Log-Statements
transportieren nur `username`, Guard-Keys (IP/Username) und Fehlermeldungen — nie
Klartext-Passwörter, TOTP-Secrets, Recovery-Codes oder Reset-/Invite-Tokens. Passwort-
Reset-Tokens werden ausschließlich als SHA-256-Hash persistiert (`_hash_invite_token`,
`issue_reset_token`), nie im Klartext geloggt oder in der DB gespeichert.

---

## Nachweis: Tests + Gate

```
cd 5eyes-backend && python -m pytest tests/test_independent_security_audit_2026_07_23.py -q -p no:cacheprovider
# 13 passed

python scripts/security_gate.py   # Repo-Root
# 165 passed, 4 skipped (Postgres-only) — Data-Integrity-Audit-Gate: SAUBER
```

Zusätzliche Regressions-Läufe (bestehende Tenant-/Auth-/Bausteine-Suiten, alle grün):
`test_tenant_isolation_hardening.py`, `test_repository_tenant_scoping.py`,
`test_sec1_client_login_tenant.py`, `test_tenant_admin_api.py`,
`test_rls1_effective_strict_isolation.py`, `test_user_tenant_inheritance.py`,
`test_mandate_tenant_inheritance.py`, `test_invite_onboarding.py`,
`test_tenant_quota_enforcement.py`, `test_bug13a_protocol_bausteine.py`,
`test_bug13a_frontend_bausteine_modal.py`, `test_bug13b_protokoll_pdf_bausteine.py`,
`test_onboarding_password.py`, `test_tenant_endpoint_leak_regression.py`,
`test_multi_tenant_concurrency.py`, `test_2fa_login.py`,
`test_auth06_totp_replay_guard.py`, `test_runtime_contracts.py`,
`test_user_admin_tenant_scoping.py` (insgesamt >200 Tests, 0 Fehlschläge).

## Unsicherheiten / offene Punkte

- Kein PostgreSQL-Testsystem verfügbar in dieser Session — F3s RLS-Mitigations-Annahme
  (Tier-2) und F6 wurden anhand des Codes verifiziert, nicht live gegen Postgres getestet.
- F4 wurde bewusst nicht gefixt (Datei-Grenze `routers/*.py` + Policy- statt
  Auth-Boundary-Charakter) — sollte als eigenständiger kleiner Folge-Fix behandelt werden.
- Es wurde nicht jede Zeile jedes Service-/Engine-Moduls gelesen (out of scope: der
  Auftrag fokussiert auf Router-Endpoints als Auth-Boundary; Business-Logic-Bugs in
  `services/portfolio_engine.py` etc. sind Gegenstand der bereits vorhandenen
  fachlichen Audits, nicht dieser Sicherheitsprüfung).
