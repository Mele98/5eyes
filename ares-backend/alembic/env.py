import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Roadmap #90: Baseline-Migration + init_db-Switch create_all<->alembic.
# Alle Model-Module explizit importieren (wie main.py es beim App-Start tut),
# damit Base.metadata jede Tabelle kennt -- ohne main.py selbst zu importieren
# (das wuerde Scheduler/Router-Side-Effects auslösen, die ein CLI-Tool nicht
# braucht).
from database import Base, build_database_url  # noqa: E402
import models.allocation  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.login_attempt  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.market_data_cache  # noqa: E402,F401
import models.market_data_validation_log  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tax  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
#
# disable_existing_loggers=False (Bugfix, gefunden bei Merge des stochastischen
# Optimizer-Branches 2026-08): logging.config.fileConfig()'s DEFAULT ist
# disable_existing_loggers=True. alembic.ini deklariert nur "root",
# "sqlalchemy" und "alembic" als Logger -- jeder andere zu diesem Zeitpunkt
# bereits existierende Logger (z.B. jedes services/*-Modul, das beim App-Start
# oder bei Testkollektion bereits `logging.getLogger(__name__)` aufgerufen
# hat) wuerde sonst permanent `.disabled = True` gesetzt und faellt fuer den
# Rest des Prozesses lautlos aus -- unabhaengig von Level/Handlern/caplog.
# _create_or_migrate_schema() in database.py ruft command.upgrade() (und
# damit dieses env.py) bei JEDEM Postgres-Produktions-App-Start auf: ohne
# diesen Fix wuerde jeder Start beliebige, bereits importierte Logger fuer
# die gesamte Prozesslaufzeit stummschalten (lautloser Logging-Blackout).
# Reproduzierbar im Backend-Test-Suite gefunden: tests/test_alembic_baseline_
# migration.py ruft dieselbe command.upgrade()-Kette auf und schaltete damit
# services.pdf.fonts/services.telemetry fuer den Rest des Testlaufs stumm
# (tests/test_pdf_font_embedding.py::test_missing_ttf_files_degrade_without_crash,
# tests/test_telemetry_opt_in.py::test_capture_exception_no_op_when_inactive,
# tests/test_telemetry_opt_in.py::test_capture_message_no_op_when_inactive).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Roadmap #90: DB-URL kommt aus der App-Config (config.settings/DATABASE_URL),
# nicht aus einer in alembic.ini hartcodierten Verbindung -- alembic.ini
# selbst darf kein Klartext-Secret enthalten.
#
# Reihenfolge (erste greifende Regel gewinnt):
# 1. ALEMBIC_DATABASE_URL_OVERRIDE (Env-Var) -- gezieltes Ueberschreiben,
#    z.B. beim Baseline-Generieren gegen eine leere Wegwerf-DB.
# 2. Eine bereits programmatisch gesetzte sqlalchemy.url (z.B. database.py::
#    _create_or_migrate_schema() oder ein Test baut ein eigenes
#    AlembicConfig-Objekt und ruft cfg.set_main_option(...) VOR command.
#    upgrade() auf) -- MUSS respektiert werden. Bugfix: diese Zeile hat
#    frueher IMMER build_database_url() erneut aufgerufen und damit jede
#    bewusst gesetzte URL stillschweigend verworfen -- ein Test mit einer
#    Wegwerf-SQLite-DB waere sonst gegen die echte Dev-Datenbank gelaufen.
# 3. Fallback: build_database_url() (App-Settings) -- der normale CLI-Pfad
#    (`alembic upgrade head` direkt aus dem Terminal, ohne Override), wo die
#    ini-Datei noch ihren Platzhalter enthaelt.
import os  # noqa: E402

_PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"
_override = os.environ.get("ALEMBIC_DATABASE_URL_OVERRIDE")
_already_configured = config.get_main_option("sqlalchemy.url")
if _override:
    config.set_main_option("sqlalchemy.url", _override)
elif not _already_configured or _already_configured == _PLACEHOLDER_URL:
    config.set_main_option("sqlalchemy.url", build_database_url())
# sonst: die bereits gesetzte URL unveraendert stehen lassen.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
