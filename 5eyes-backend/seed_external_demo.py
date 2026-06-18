"""Seed fuer den EXTERNEN TEST (Phase 0) — eigene Staging-DB, NUR synthetische Daten.

Legt eine SEPARATE DB (Default: ~/5eyes/5eyes-staging.db) mit Demo-Tenants + Accounts an
— voellig getrennt von der Live-DB mit echten Mandanten. So kann beim Extern-Test
GARANTIERT keine echte Kundendaten exponiert werden (es ist schlicht keine da).

Aufruf (aus 5eyes-backend):  python seed_external_demo.py
Optional anderer Pfad:       python seed_external_demo.py "C:\\Pfad\\zu\\staging.db"

Danach: docs/deploy/start-external-staging.ps1 starten (nutzt diese DB via DB_PATH).
"""
from __future__ import annotations

import os
import sys
import uuid
import datetime
from pathlib import Path

# --- Staging-DB-Pfad VOR dem Import von database/config setzen ---
_default = str(Path.home() / "5eyes" / "5eyes-staging.db")
_db_path = sys.argv[1] if len(sys.argv) > 1 else _default
os.environ["DB_PATH"] = _db_path
# Seeden im Development-Modus (kein Secret-Guard noetig); der RUNTIME-Staging-Modus
# (mit Secret) kommt erst beim start-external-staging.ps1.
os.environ.setdefault("APP_ENV", "development")

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import init_db, SessionLocal  # noqa: E402
# Alle Modelle registrieren (Client<->WealthPosition-Relationships), sonst scheitert
# die Mapper-Konfiguration.
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users as _users, wealth, tenant as _tenant,
)
from models.tenant import Tenant, TIER_2_SHARED_CLOUD, LICENSE_STATUS_TRIAL  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import hash_password  # noqa: E402

configure_mappers()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# Initial-Passwort fuer alle Demo-Accounts (beim 1. Login Wechsel + 2FA erzwungen).
INITIAL_PW = "Start-5eyes-2026!"

TENANTS = [
    ("tnt-internal", "5eyes Intern (Demo)", "5eyes-internal"),
    ("tnt-firma-a", "Demo Firma A (Treuhand)", "demo-firma-a"),
    ("tnt-firma-b", "Demo Firma B (VV)", "demo-firma-b"),
]

# (username, full_name, role, tenant_id)
# Hinweis: das Bootstrap-Schema erlaubt per CHECK nur ('admin','advisor','readonly').
# 'super_admin'/'client' fehlen dort (separater Schema-Bug) -> Operator hier als 'admin'.
USERS = [
    ("operator", "Operator (du)", "admin", "tnt-internal"),
    ("a.berater", "Anna Berater (Firma A)", "advisor", "tnt-firma-a"),
    ("a.admin", "Adrian Admin (Firma A)", "admin", "tnt-firma-a"),
    ("b.berater", "Bruno Berater (Firma B)", "advisor", "tnt-firma-b"),
    ("b.admin", "Bea Admin (Firma B)", "admin", "tnt-firma-b"),
]


def main() -> int:
    print(f"Staging-DB: {_db_path}")
    init_db()
    created_t, created_u = 0, 0
    with SessionLocal() as s:
        existing_t = {t.id for t in s.query(Tenant).all()}
        for tid, display, slug in TENANTS:
            if tid in existing_t:
                continue
            s.add(Tenant(
                id=tid, display_name=display, slug=slug,
                hosting_tier=TIER_2_SHARED_CLOUD, license_status=LICENSE_STATUS_TRIAL,
                max_users=10, max_mandates=50, is_active=1,
                created_at=_now(), updated_at=_now(),
            ))
            created_t += 1
        s.commit()

        existing_u = {u.username for u in s.query(User).all()}
        pw_hash = hash_password(INITIAL_PW)
        for username, full_name, role, tenant_id in USERS:
            if username in existing_u:
                continue
            s.add(User(
                id=str(uuid.uuid4()), tenant_id=tenant_id, username=username,
                password_hash=pw_hash, full_name=full_name,
                email=f"{username}@demo.5eyes.local", role=role, is_active=1,
                must_change_password=1, totp_enabled=0,
                created_at=_now(), updated_at=_now(),
            ))
            created_u += 1
        s.commit()

    print(f"Angelegt: {created_t} Tenants, {created_u} Accounts.")
    print(f"Initial-Passwort fuer ALLE: {INITIAL_PW}  (Wechsel + 2FA beim 1. Login erzwungen)")
    print("Accounts:")
    for username, full_name, role, tenant_id in USERS:
        print(f"  - {username:12s} | {role:11s} | {tenant_id}  ({full_name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
