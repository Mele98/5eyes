# Postgres-Schema-Migrationen (Alembic) — Roadmap #90

Betrifft nur den Postgres-Betrieb (E1-Stufe, vor echten Kundendaten — siehe
`docs/deploy/README.md`). Der SQLite-Entwicklungs-/Desktop-Pfad ändert sich
nicht: dort bootstrapped `init_db()` weiterhin über
`Base.metadata.create_all()` + die etablierten `ensure_*()`-Idempotenz-
Funktionen in `database.py`.

## Warum

Bis jetzt entstand das Schema bei jedem App-Start implizit aus den aktuellen
SQLAlchemy-Models (`create_all`) plus einer wachsenden Liste additiver
`ensure_*()`-Migrationsfunktionen. Für SQLite (Einzelplatz-Desktop-App) ist
das ausreichend robust. Für eine echte Postgres-Produktionsdatenbank mit
Kundendaten ist ein **versionierter** Migrationspfad sicherer: jede
Schema-Änderung ist eine benannte, review-bare, umkehrbare Revision statt
einer impliziten Diff-Anwendung beim Deploy.

## Was schon da ist

- `alembic.ini` + `alembic/env.py` — liest die DB-URL aus
  `database.build_database_url()` (also aus der App-Config/`DATABASE_URL`),
  **nicht** aus einer Datei mit Klartext-Connection-String.
- `alembic/versions/c91f2c722881_baseline_schema.py` — die Baseline-Revision,
  generiert aus dem *aktuellen* `Base.metadata` (alle 17 `models/*.py`-Module).
  Wendet man sie auf eine leere Datenbank an, entsteht exakt dasselbe Schema
  wie `create_all()` es für SQLite erzeugt (verifiziert in
  `tests/test_alembic_baseline_migration.py`).
- `database.py::_create_or_migrate_schema()` — der Dispatch in `init_db()`:
  - SQLite-URL → `Base.metadata.create_all()` (unverändert).
  - Postgres-URL → `alembic upgrade head` (programmatisch, über die Alembic-
    Python-API). Idempotent — beim nächsten App-Start ohne neue Revision
    passiert nichts.

Das heisst: **sobald `DATABASE_URL` auf eine Postgres-Instanz zeigt, reicht
ein normaler App-Start** (`uvicorn main:app` bzw. der systemd-Service), um
das komplette Baseline-Schema anzulegen — kein separater manueller Schritt
nötig für die *erste* Inbetriebnahme.

## Eine neue Migration schreiben (nach der Baseline)

Sobald ein neues Model-Feld/eine neue Tabelle zu `models/*.py` hinzukommt,
muss eine neue Alembic-Revision dazu:

```bash
cd 5eyes-backend
# gegen eine leere Wegwerf-DB generieren, NICHT gegen die echte Dev-DB:
ALEMBIC_DATABASE_URL_OVERRIDE="sqlite:///$(mktemp -u).db" \
  python -m alembic revision --autogenerate -m "kurze beschreibung"
```

Die generierte Datei in `alembic/versions/` **immer durchlesen** (Alembic-
Autogenerate erkennt nicht alles zuverlässig, z.B. reine Umbenennungen sehen
wie Drop+Add aus) und danach `tests/test_alembic_baseline_migration.py`
laufen lassen — der Drift-Test schlägt fehl, wenn eine Model-Änderung ohne
passende Migration committet wurde.

## Manuell ausführen (Diagnose/Rollback)

```bash
# aktuellen Stand einer laufenden Postgres-Instanz auf den neuesten Stand bringen
ALEMBIC_DATABASE_URL_OVERRIDE="postgresql://user:pw@host/db" python -m alembic upgrade head

# einen Schritt zurück
ALEMBIC_DATABASE_URL_OVERRIDE="postgresql://user:pw@host/db" python -m alembic downgrade -1

# aktuelle Revision anzeigen
ALEMBIC_DATABASE_URL_OVERRIDE="postgresql://user:pw@host/db" python -m alembic current
```

`ALEMBIC_DATABASE_URL_OVERRIDE` ist nur zum gezielten Überschreiben da (Tests,
Diagnose gegen eine andere Instanz als die konfigurierte). Im normalen
Produktionsbetrieb läuft alles automatisch über `init_db()` beim App-Start.
