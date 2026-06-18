# Codex-Task: Postgres RLS + Per-Tenant-Encryption (HARD, security-kritisch)

> **Für Codex:** Dies ist deine Aufgaben-Spec. Lies sie ganz, dann planen → umsetzen →
> adversarial testen. Ein Commit pro Task, am Ende EIN PR gegen `develop`.

**Repo:** `C:\5eyes\5eyes_stage9_release_ready` (FastAPI, SQLAlchemy, pytest).
**Kontext:** `docs/planning/2026-06-12-external-access-rollout-plan.md` (§2 Defense-in-depth),
`docs/planning/2026-06-18-roadmap-200-detailliert.md` (#33–#37, #11), ADR-007 (Multi-Tenancy).
**Maxime (Memory):** HARTE Mandanten-Trennung ist oberste Pflicht.

**Ziel:** Die DRITTE, physische Isolationsschicht. Heute ruht die Trennung auf 2 Schichten
(JWT `tid` + App-Repo-Filter `services/auth.py:_apply_tenant_filter_*`). RLS macht ein
VERGESSENES App-Filter **physisch wirkungslos**.

**Erst tief verstehen:** `services/auth.py` (_apply_tenant_filter_*), `database.py`
(Session/Engine-Setup), `models/*.py` (welche Tabellen haben `tenant_id`).

## Harte Regeln (Dual-Agent)
- **NICHT anfassen:** `services/portfolio_engine.py`, `services/optimizer/*`,
  `services/wealth_cashflows.py`, `5eyes-electron/frontend/5eyes_v2.html`,
  `docs/methodology/*`, `docs/adr/*` (nur NEUE ADR anlegen ok), `docs/planning/*`,
  `docs/audits/*monolith-inventory*`.
- Additiv + rückwärtskompatibel. **SQLite muss weiter funktionieren** (RLS ist Postgres-only;
  unter SQLite no-op/Skip). Neue NOT-NULL-Spalten IMMER mit `server_default`.
- Branch: `git checkout -b codex/postgres-rls-tenant-crypto`. VORHER `git branch --show-current`.
- Abschluss: `scripts/security_gate.py` grün + neue Tests grün.
- **Voraussetzung:** #33 Postgres-Adapter (DATABASE_URL, Dialekt-Switch). Falls noch nicht in
  develop → ZUERST minimalen Adapter bauen (Dialekt-Erkennung, SQLite-Spezifika hinter Switch).

## Task 1 — Connection-scoped Tenant-Kontext (das subtile Stück)
- Pro Request nach Auth den aktiven `tenant_id` (aus JWT `tid`) auf der DB-Connection setzen:
  Postgres `SET app.tenant_id = :tid` (oder `set_config`). SQLite: no-op.
- **KRITISCH (Pool-Sicherheit):** die Session-Variable MUSS beim Zurückgeben der Connection an
  den Pool zurückgesetzt werden (RESET / leer) — sonst erbt der nächste Request eines ANDEREN
  Tenants den stale-Wert → Leak. SQLAlchemy-Events (checkin/checkout) oder Request-scoped
  Session-Hook mit `try/finally`.
- `super_admin` (Operator): definierter Modus ohne tenant-Scope (sieht KEINE Kundendaten, nur
  Tenant-Metadaten) — RLS-Bypass NUR für explizit markierte Operator-Queries.
- **DoD:** Helper `set_tenant_context(session, tid)` + garantierter Reset; dokumentiert.

## Task 2 — RLS-Policies pro mandantenführender Tabelle (#34)
- Migration (Postgres-only, hinter Dialekt-Check) pro Tabelle mit `tenant_id`
  (users, clients, mandates, wealth_positions, cashflows, goals, target_allocations,
  recommendation_runs, audit_log, protocol_bausteine, … — vollständig aus `models/*.py`):
  ```sql
  ALTER TABLE x ENABLE ROW LEVEL SECURITY;
  ALTER TABLE x FORCE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON x
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
  ```
- `current_setting(..., true)` → NULL-tolerant (kein Crash; dann 0 Zeilen). Idempotent
  (`DROP POLICY IF EXISTS` davor).
- **DoD:** alle mandantenführenden Tabellen haben FORCE RLS + `tenant_isolation`-Policy.

## Task 3 — tenant_id NOT NULL nach Backfill (#36)
- Postgres: nach `ensure_tenant_backfill()` (NULL→DEFAULT_TENANT_ID) `ALTER … SET NOT NULL`.
- SQLite: bleibt wie heute (App-Level-Strict-Mode). Hinter Dialekt-Check.
- **DoD:** unter Postgres `tenant_id` NOT NULL auf allen genannten Tabellen.

## Task 4 — Per-Tenant-Encryption-Key (#11)
- Key-Hierarchie: Master-KEK (Env/Vault) → per-Tenant-DEK (verschlüsselt at-rest in
  `tenants`, mit KEK entschlüsselt). Helper `get_tenant_dek(tenant_id)`.
- Anwendung: PII-Feldverschlüsselung als Referenzimplementierung (z.B. `client.notes` oder
  Name-Felder) ODER dokumentierte Schnittstelle dafür.
- Key-Rotation: `rotate_tenant_dek(tenant_id)` (re-encrypt) + Doku.
- **DoD:** DEK-Hierarchie + get/rotate + Test (roundtrip, falscher KEK schlägt fehl).

## Task 5 — ADVERSARIALE Isolations-Tests (der eigentliche Beweis)
Nur mit Postgres aussagekräftig (unter SQLite skippen). Test-DB = Postgres-Container.
1. **RLS ohne App-Filter:** `app.tenant_id=A`, ROHE Query OHNE `WHERE tenant_id` gegen clients
   → liefert NUR A-Zeilen (Beweis: vergessenes App-Filter wirkungslos).
2. **Pool-Leak-Test:** zwei aufeinanderfolgende Requests verschiedener Tenants über DENSELBEN
   Pool → der zweite sieht NICHTS vom ersten (Reset greift).
3. **WITH CHECK:** Insert mit fremder `tenant_id` → abgelehnt.
4. **super_admin-Bypass:** nur explizit markierte Operator-Queries sehen tenant-übergreifend;
   normale Endpoints NICHT.
- **DoD:** alle 4 Tests grün gegen Postgres; unter SQLite sauber geskippt.

## Abschluss
- Neue ADR `docs/adr/ADR-012-postgres-rls-tenant-isolation.md` (Kontext/Entscheid/Konsequenzen).
- Pro Task ein Commit; EIN PR → develop mit DoD je Task. CI: SQLite + (neu) Postgres grün.
