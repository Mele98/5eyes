# ADR-007: Multi-Tenancy-Strategie

- **Status:** Accepted (Strategie), Implementation: deferred
- **Datum:** 2026-06-06
- **Sprint:** U-42 (DB, Roadmap Punkt 42)

## Kontext

5eyes laeuft heute als **Desktop-App** (Electron + lokaler FastAPI-
Backend) auf dem Geraet des Beraters. Innerhalb einer Installation
gibt es bereits Multi-User-Support:

- JWT-basierte Auth (`services/auth.py`, `routers/auth.py`)
- User/Role-Model (`models/users.py` mit `role` advisor/admin)
- Login-Guard mit Brute-Force-Schutz (`services/login_guard.py`)
- Mandanten/Kunden sind via `clients.advisor_id` -> `users.id`
  einem User zugeordnet
- SQLite mit WAL-Journal-Mode (`PRAGMA journal_mode = WAL`) +
  `busy_timeout = 5000` -> mehrere User koennen parallel lesen,
  Schreib-Locks werden mit Backoff abgewickelt
- SQLCipher-Verschluesselung optional aktivierbar

Was es **noch nicht** gibt: **Multi-Tenant-Isolation** — eine
SaaS-Variante in der mehrere Beratungsfirmen sich einen Server teilen,
ohne dass Firma A die Mandanten von Firma B sehen kann.

## Frage

Wann brauchen wir Multi-Tenancy und wie implementieren wir sie?

## Optionen

### Option A: Status-Quo halten (Per-Install-Single-Tenant)

- Eine Installation = eine Beratungsfirma
- SQLite-DB pro Installation, lokal verschluesselt
- Multi-User innerhalb einer Installation via JWT
- Skaliert nicht auf SaaS, ist aber **fuer Desktop-App ausreichend**

### Option B: Tenant-ID-Scoping in SQLite

- Tenant-Tabelle hinzufuegen
- `tenant_id` auf allen Top-Level-Modellen (User, Client, Mandate, ...)
- Application-Layer-Filter in jeder Query
- Risiko: vergessenes Filter = Cross-Tenant-Leak
- Vorteil: Einfache Migration zu Postgres spaeter

### Option C: SQLite-File-pro-Tenant

- Eine `.sqlite`-Datei pro Tenant
- Database-Routing im Connection-Pool
- Isolierung garantiert (Datei = Boundary)
- Skaliert bis ~hunderte Tenants pro Server, danach IO-Limit
- Backup pro Tenant trivial (cp)

### Option D: Postgres mit Row-Level-Security

- Migration zu Postgres
- RLS-Policies (`CREATE POLICY tenant_isolation ON ...`)
- Skaliert SaaS-grade
- Aber: Bestehende Desktop-Installation muss embedded Postgres
  installieren -> Operations-Overhead
- Kosten: Hosting (DigitalOcean/Hetzner ab ~CHF 20/Monat) plus
  Postgres-Erfahrung im Team

## Entscheidung

**Status-Quo halten (Option A) bis SaaS-Bedarf konkret wird.**

Begruendung:
1. **Vertriebs-Reality**: 5eyes wird heute als Desktop-Installation an
   einzelne Berater/Firmen verkauft. SaaS ist nicht das Geschaeftsmodell.
2. **Compliance-Vorteil**: Lokale verschluesselte Datenbank
   (SQLCipher) ist FINMA-freundlicher als Shared-Hosting — Kundendaten
   verlassen das Geraet nicht.
3. **Operations-Komplexitaet**: Postgres-Hosting + Backup-Strategie
   + Disaster-Recovery sind erheblicher Aufwand fuer einen Use-Case,
   der heute nicht existiert.
4. **Migration-Pfad bleibt offen**: SQLAlchemy ORM ist DB-agnostisch
   — bei tatsaechlichem SaaS-Bedarf migrieren wir in einem dedizierten
   Sprint nach Option D (RLS).

## Wann re-evaluieren?

Triggers fuer Neuevaluation:
- Konkretes SaaS-Angebot oder Pilot-Kunde der Hosting wuenscht
- Mehrere unabhaengige Firmen wollen sich eine Installation teilen
  (= Option C/D wird Pflicht)
- Mandanten verlangen Web-Zugriff auf ihre Reports (-> Multi-Tenant-
  Cloud-Backend)

## Vorbereitende Massnahmen (nicht in diesem Sprint)

Wenn der Trigger irgendwann kommt:

1. **Schema-Migration**: `tenant_id NOT NULL` auf User/Client/Mandate/
   alle datenfuehrenden Tabellen
2. **Repository-Layer**: jede Query nimmt `tenant_id` zwingend als
   Parameter (kein Default = kein Vergessen)
3. **Auth-Erweiterung**: JWT-Claim `tid` mit Tenant-ID
4. **Audit-Log**: Tenant-Boundary-Crossing wird geloggt + alert-
   pflichtig
5. **Conformance-Test**: Cross-Tenant-Leak-Test der Repo-Layer
6. **Postgres-Adapter** wenn Option D gewaehlt: SQLAlchemy URL
   austauschbar via Settings

## Konsequenzen

**Positiv:**
- Keine Code-Komplexitaet fuer hypothetischen Bedarf
- Lokales Vertrauensmodell bleibt einfach (Datei = Grenze)
- Kosten: weiterhin CHF 0/Monat fuer DB-Infra
- Compliance-narrativ stark ("Daten verlassen das Geraet nie")

**Negativ:**
- SaaS-Variante braucht eigenen Sprint wenn sie Realitaet wird (3-5
  Tage geschaetzt fuer Schema-Migration + RLS-Policies)
- Bei mehr-als-zwei-Berater-pro-Firma wird WAL-Lock zum Engpass —
  dann muessten wir auf Option D
- Backup/Restore ist heute Berater-Verantwortung (kein zentraler
  Service)

## Implementations-Status

- [✓] WAL-Journal-Mode aktiv (`database.py:78`)
- [✓] `busy_timeout = 5000` (`database.py:79`)
- [✓] SQLCipher optional (`db_use_sqlcipher` Setting)
- [✓] JWT-Auth mit Role-Scoping
- [✓] Login-Guard gegen Brute-Force
- [✓] `clients.advisor_id` Foreign-Key (User-Level-Scoping)
- [ ] Tenant-Tabelle + tenant_id-Spalten (deferred bis SaaS-Bedarf)
- [ ] Postgres-Adapter (deferred bis SaaS-Bedarf)
- [ ] Cross-Tenant-Conformance-Tests (deferred bis SaaS-Bedarf)

## Referenzen

- `database.py` — Connection-Setup, WAL-Konfiguration
- `models/users.py` — aktuelle User-Tabelle
- `services/auth.py` — JWT-Auth-Layer
- ADR-002 (Compliance-Stack) — Datenschutz-Narrativ
- Memory `project_5eyes_audit.md` — Hosting-Modell-Status

---

## Update 2026-06-15 — Multi-Tenancy ist AKTIV (Status: Implemented, App-Level)

Der 2026-06-06 als „deferred" markierte Teil ist umgesetzt (externer Zugriff / Lizenz-Modell):

- [✓] **Tenant-Tabelle + `tenant_id`-Spalten** auf mandantenführenden Tabellen, mit Backfill
  (`ensure_tenant_backfill`) und Create-Inheritance.
- [✓] **`strict_tenant_isolation`** (App-Level-Filter) + Cross-Tenant-404-Guards
  (`get_linked_client_for_user_or_404`); Client-Portal Defense-in-Depth.
- [✓] **Pflicht-2FA-Hard-Gate** (TOTP) + Invite-Onboarding (Token sha256, Ablauf, single-use,
  Resend rate-limited, Revoke).
- [✓] **CI-Security-Gate** (`scripts/security_gate.py`) hält Tenant-Isolation/Auth-Tests grün.
- [ ] **Postgres-RLS** (#9) — physische Absicherung zusätzlich zum App-Filter (geplant).
- [ ] **Postgres-Adapter** (#8) / `tenant_id` NOT NULL (#10) — DB-agnostisch via `DATABASE_URL`.
- [ ] **Per-Tenant-Encryption-at-rest** (#11).

Verbleibend = die DB-physische Schicht (RLS + Postgres + Key-Hierarchie). App-logische
Mandantentrennung + Auth-Härtung sind produktiv. Compliance-Vorlagen: `docs/compliance/`.

---

## Update 2026-07-23 — rls-1 (effektive Strict-Isolation) + Datenklassifizierungs-Gate

**rls-1 (Commit `22b94c6`, 2026-07-19):** Die 3 Lesestellen des App-Level-Filters in
`services/auth.py` (`_apply_tenant_filter_to_client_query`,
`_apply_tenant_filter_to_mandate_query`, die Client-Portal-Linkage-Prüfung) lesen nicht
mehr den rohen `settings.strict_tenant_isolation`-Flag, sondern die neue Helper-Funktion
`_effective_strict_tenant_isolation(settings_obj)` (`services/auth.py:223`). Sie liefert
`True` wenn der Flag explizit gesetzt ist **ODER** das Deployment mandantenfähig ist
(`deployment_tier == "tier2"` bzw. `tenancy_mode == "multi"`) — damit ein Tier-2-/
Multi-Tenant-Setup nie versehentlich ohne Strict-Isolation läuft, auch außerhalb der
staging/production-Config-Validierung. Tier 1 + Tier 3 (single-tenant) bleiben
unverändert (kein Zwang, Backwards-Compat für NULL-tenant-Rows). Test:
`tests/test_rls1_effective_strict_isolation.py`.

**Datenklassifizierungs-Gate auf Vermögenspositionen ausgeweitet (Commit `3906b7a`,
2026-07-19/22):** Das Phase-0-Gate (`services/data_classification.py:
enforce_data_classification`, blockt `data_classification="real"` solange
`settings.allow_real_client_data` falsch ist) wurde bereits für Clients/Cashflows/Goals
aufgerufen (`routers/clients.py`, `routers/wealth.py`), aber `WealthPositionCreate`/
`WealthPositionUpdate` (`schemas/wealth.py`) hatten das Feld `data_classification`
schlicht nicht deklariert — Pydantic verwarf ein mitgesendetes `"real"` bereits beim
Parsen, bevor `enforce_data_classification()` es je sah. Vermögenspositionen (Depot/
Hypothek/Immobilie/Liquidität) waren damit die einzigen mandantenbezogenen, sensiblen
Datensätze, die das Phase-0-Gate umgehen konnten. Fix: Feld ergänzt + Aufruf in
`routers/wealth.py` (`create_wealth_position`, `update_wealth_position`). Dieses Gate ist
kein Tenant-Isolation-Mechanismus im engeren Sinn, sondern der komplementäre
"echte-vs-synthetische-Daten"-Schutz vor Produktivschaltung pro Tenant (siehe ADR-009,
"Gate vor Echtdaten") — hier dokumentiert, weil der Lückenschluss im selben
Audit-Sprint wie rls-1 gefunden wurde.
