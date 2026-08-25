# Schema-Migrations mit alembic (opt-in)

Migrations-Workflow fuer das 5eyes-Backend-Schema mit alembic.

**Stand:** 2026-08-07 (Folge-Sprint zu U-41 vom 2026-06-06)
**Roadmap-Punkt:** #90 (Standpunkt 2026-08-07) — vormals #41
**Status:** Der Init-Sprint (Setup + Baseline-Migration + init_db-Switch)
ist **umgesetzt** — siehe `docs/deploy/postgres-migrations.md` fuer die
Betriebs-Anleitung. Betrifft NUR Postgres-Produktion: SQLite (Dev/Test/
Electron-Desktop) laeuft unveraendert weiter ueber `Base.metadata.
create_all` (init_db) — kein Verhaltenswechsel fuer den bestehenden,
sehr gut getesteten Pfad.

Der Rest dieses Dokuments (Setup-Schritte, Per-Sprint-Migrations-
Workflow, SQLite-Batch-Pattern) bleibt als Referenz gueltig -- die
tatsaechliche env.py/Baseline-Migration im Repo (`5eyes-backend/alembic/`)
ist die kanonische, ausfuehrbare Version der hier skizzierten Beispiele.

---

## Warum opt-in?

Aktuelle Realitaet:
- Berater installiert frische 5eyes-App -> DB wird via
  `Base.metadata.create_all` neu angelegt
- Bei Schema-Aenderungen in einem Sprint MUSS der Berater die DB
  manuell migrieren (SQLite ALTER TABLE) oder neu anlegen

alembic loest das, kommt aber mit Setup-Overhead. Daher:
- **Setup als opt-in** (analog U-106/U-107)
- **Nicht in requirements.txt** bis konkret gebraucht
- **Init-Sprint** dokumentiert hier, **Per-Sprint-Migrations** sind
  Folge-Sprints sobald Berater echtes Multi-Mandate-Setup hat

## Setup (Erst-Init)

```powershell
cd 5eyes-backend
.venv\Scripts\Activate.ps1
pip install alembic

alembic init --template generic alembic
# Erzeugt alembic.ini + alembic/-Verzeichnis mit env.py + versions/
```

### `alembic.ini` anpassen

```ini
sqlalchemy.url = sqlite:///./5eyes.db
```

### `alembic/env.py` mit Project-Models verbinden

```python
# in alembic/env.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Base
import models.allocation  # noqa
import models.clients  # noqa
import models.client_login  # noqa  (U-36)
import models.fx_rate  # noqa
import models.mandates  # noqa
import models.profiling  # noqa
import models.review  # noqa
import models.users  # noqa
import models.snapshots  # noqa
import models.wealth  # noqa

target_metadata = Base.metadata
```

## Erste Baseline-Migration

```powershell
alembic revision --autogenerate -m "baseline"
alembic upgrade head
```

`baseline.py` enthaelt alle bestehenden Tables. Auf bestehender
Berater-DB:

```powershell
alembic stamp head  # markiert DB als "auf baseline-State"
```

## Per-Sprint-Migrations

Neue Model-Aenderung? Wirf eine Migration:

```powershell
alembic revision --autogenerate -m "u_XX_<beschreibung>"
# Edit das generierte Skript falls noetig
alembic upgrade head
```

**Wichtig:** autogenerate erkennt nicht alle Aenderungen
(z.B. enum-Werte, indexes ohne Server-Hint). Skript IMMER review!

## Settings-Integration

`5eyes-backend/config.py` koennte ein Setting bekommen:

```python
db_migration_strategy: Literal["create_all", "alembic"] = "create_all"
```

`init_db()` waehlt dann:
- `create_all`: heutige Logik (frische DB, Reset)
- `alembic`: ruft `alembic upgrade head` auf

NICHT in U-41 implementiert — Folge-Sprint sobald erste Migration
existiert.

## SQLite-Spezifika

SQLite hat eingeschraenkte ALTER TABLE Support (kein DROP COLUMN
ohne Recreate). alembic SQLite-Modus wraps das via Batch-Operationen:

```python
def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("new_field", sa.String()))
        batch_op.drop_column("old_field")
```

Pflicht-Pattern in jeder SQLite-Migration. Postgres (siehe #42)
braucht das nicht.

## Umgesetzt seit Roadmap #90 (2026-08-07)

- ✅ alembic als Dependency in requirements.txt (nur fuer den Postgres-Pfad
  relevant -- SQLite importiert das Modul nie, siehe
  `database.py::_create_or_migrate_schema`).
- ✅ Auto-Migration beim App-Startup -- ABER nur fuer Postgres, und nur
  gegen die eingecheckte, review-te Baseline-Revision. Fuer eine FRISCHE
  Postgres-DB (keine bestehenden Daten) ist "ohne Backup" kein Risiko, weil
  nichts zu verlieren ist. Fuer kuenftige Migrationen auf einer Postgres-DB
  MIT echten Kundendaten bleibt das Restrisiko unten bewusst offen.

## Bewusst NICHT in Scope (weiterhin, nach Roadmap #90)

- Backup-vor-Migration-Hook (separater Sprint) -- vor der ERSTEN echten
  Schema-Aenderung auf einer produktiven Postgres-DB mit Kundendaten
  einplanen (siehe `docs/deploy/disaster-recovery-plan.md`).
- Rollback-Tests als CI-Pflichtschritt (per-Sprint; die Baseline selbst hat
  einen Downgrade-Test, siehe test_alembic_baseline_migration.py).
- CI-Migration-Lint (`alembic check`).

## Folge-Sprints

- **erste echte Migration** sobald ein Sprint das Postgres-Schema aendert
  (Anleitung: `docs/deploy/postgres-migrations.md`).
- **Backup-vor-Migration-Hook** (`scripts/migrate.py`).
- **CI-Migration-Lint** (`alembic check`).

## Weiterfuehrendes

- [alembic docs](https://alembic.sqlalchemy.org)
- `docs/CLAUDE_HANDOFF.md` — Migration-Strategie-Notes
- ADR-005 — CHF-0-Disziplin (alembic ist gratis)
- Roadmap-Punkt #42 (Postgres) — alembic ist Voraussetzung
