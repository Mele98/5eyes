# SQLAlchemy ORM models for 5Eyes
# Each file maps to a group of related tables from the v4.0 schema.

# AUTH-03: Persistenter Brute-Force-Login-Guard. Import hier, damit die
# Tabellen (login_attempts / login_lockouts) an Base.metadata registriert
# sind und von database.create_all() angelegt werden (ohne Eingriff in
# database.py).
from . import login_attempt  # noqa: F401,E402
