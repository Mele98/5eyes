# SQLAlchemy ORM models for 5Eyes
# Each file maps to a group of related tables from the v4.0 schema.

# AUTH-03: Persistenter Brute-Force-Login-Guard. Import hier, damit die
# Tabellen (login_attempts / login_lockouts) an Base.metadata registriert
# sind und von database.create_all() angelegt werden (ohne Eingriff in
# database.py).
from . import login_attempt  # noqa: F401,E402

# Roadmap #28 (2026-08-08): Refresh-Token-Rotation -- dito, Tabelle
# refresh_tokens muss an Base.metadata registriert sein.
from . import refresh_token  # noqa: F401,E402

# Weiterleitung ans Asset Management (2026-08-08) -- dito, Tabelle
# portfolio_handoffs muss an Base.metadata registriert sein.
from . import portfolio_handoff  # noqa: F401,E402

# FX ist seit dem fail-closed Modellpfad ein zwingender Bestandteil jedes
# Allocation-Schemas.  Die Registrierung hier stellt sicher, dass auch
# isolierte Base.metadata.create_all()-Setups (Tests/SQLite-Desktop) dieselbe
# Tabelle besitzen wie Alembic/Postgres.
from . import fx_rate  # noqa: F401,E402
