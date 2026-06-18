# ADR-012: PostgreSQL RLS Tenant-Isolation und Tenant-DEK-Hierarchie

- **Status:** Accepted
- **Datum:** 2026-06-18
- **Sprint:** Postgres-RLS Tenant-Crypto Hardening

## Kontext

5eyes bleibt fuer Tier 1 lokal SQLite-kompatibel. Fuer Tier 2/Shared-Cloud
braucht die gleiche Codebase jedoch eine zweite Schutzschicht unterhalb der
FastAPI-/SQLAlchemy-Filter: PostgreSQL Row-Level Security (RLS). Ziel ist, dass
ein vergessener App-Filter nicht automatisch zu einem Cross-Tenant-Leak wird.

Parallel braucht Tier 2 eine Envelope-Encryption-Schicht: pro Tenant ein eigener
Data-Encryption-Key (DEK), verschluesselt mit einem Master-Key-Encryption-Key
(KEK) aus Umgebung oder Vault.

## Entscheidung

1. `DATABASE_URL` aktiviert PostgreSQL; ohne URL bleibt SQLite der Default.
2. Nach erfolgreicher Authentifizierung setzt `services.tenant_context` pro
   Session `app.tenant_id`. Super-Admins sind standardmaessig ungescoped.
3. Pool-Checkout, Pool-Checkin und Request-Finalizer resetten `app.tenant_id`
   und `app.rls_bypass`.
4. Alle SQLAlchemy-Tabellen mit physischer `tenant_id`-Spalte erhalten
   PostgreSQL-only:
   - `ENABLE ROW LEVEL SECURITY`
   - `FORCE ROW LEVEL SECURITY`
   - Policy `tenant_isolation` mit `USING` und `WITH CHECK`
5. PostgreSQL backfillt `tenant_id IS NULL` auf `main` und setzt danach
   `tenant_id NOT NULL`. SQLite bleibt nullable fuer Backwards-Compat.
6. `tenants.encrypted_dek`, `dek_version`, `dek_rotated_at` speichern die
   Envelope-Encryption-Metadaten. Der Klartext-DEK verlaesst nur den
   `services.tenant_crypto`-Helper.

## Operator-BYPASS

Normale Super-Admin-Requests sehen keine tenant-eigenen Zeilen, weil kein
Tenant-Kontext gesetzt wird. Fuer explizit markierte Wartungsabfragen existiert
`operator_bypass(session)`. Diese Verwendung muss im Code sichtbar bleiben und
wird durch Postgres-Adversarialtests abgesichert.

## SQLite-Kompatibilitaet

Alle neuen RLS-/NOT-NULL-Funktionen sind fuer SQLite No-ops. Bestehende Desktop-
Installationen behalten die nullable `tenant_id`-Spalten, weil historische
Daten ueber `ensure_tenant_backfill()` weiterhin sanft migriert werden.

## Tests und CI

- SQLite-Suite prueft No-op-Verhalten, Policy-DDL und DEK-Helper.
- `tests/test_postgres_rls_adversarial.py` laeuft nur mit
  `POSTGRES_TEST_DATABASE_URL`.
- GitHub Actions startet einen dedizierten PostgreSQL-16-Service und fuehrt die
  Adversarialtests separat aus.

## Konsequenzen

Positiv:
- App-Level-Filter und DB-Level-RLS ergaenzen sich.
- Tenant-Kontext-Leaks durch Pool-Reuse werden automatisch geloescht.
- Der spaetere PII-Encryption-Rollout hat eine zentrale DEK-Schnittstelle.

Trade-offs:
- Tier-2-Deployments brauchen PostgreSQL und `TENANT_MASTER_KEK`.
- Explizite Operator-BYPASS-Pfade muessen sparsam und reviewbar bleiben.
- Neue tenant-eigene Tabellen muessen `tenant_id` physisch tragen, damit sie
  automatisch von RLS erfasst werden.
