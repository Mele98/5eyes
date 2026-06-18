"""Macht die Demo-Accounts der Staging-DB SOFORT nutzbar (Kollegen-Test).

Setzt fuer alle Demo-Accounts:
  - ein festes, gemeinsames Passwort (DEMO_PW)
  - must_change_password = 0   (kein erzwungener Wechsel)
  - totp_enabled = 0, totp_secret = NULL   (kein 2FA-Zwang)

Damit loggen sich die Kollegen direkt mit Benutzername + Passwort ein.
NUR fuer den Phase-0-Test mit SYNTHETISCHEN Daten (separate Staging-DB)!
Fuer den echten Rollout 2FA + Passwortwechsel wieder aktivieren.

Aufruf (aus 5eyes-backend):  python make_demo_accounts_easy.py
Optional anderer DB-Pfad:    python make_demo_accounts_easy.py "C:\\Pfad\\staging.db"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_default = str(Path.home() / "5eyes" / "5eyes-staging.db")
_db_path = sys.argv[1] if len(sys.argv) > 1 else _default
os.environ["DB_PATH"] = _db_path
os.environ.setdefault("APP_ENV", "development")

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users as _users, wealth, tenant as _tenant,
)
from models.users import User  # noqa: E402
from services.auth import hash_password  # noqa: E402

configure_mappers()

# Gemeinsames Demo-Passwort fuer ALLE Test-Accounts.
DEMO_PW = "5eyes-demo-2026"
DEMO_USERNAMES = ["operator", "a.berater", "a.admin", "b.berater", "b.admin"]


def main() -> int:
    print(f"Staging-DB: {_db_path}")
    pw_hash = hash_password(DEMO_PW)
    updated = 0
    with SessionLocal() as s:
        for username in DEMO_USERNAMES:
            user = s.query(User).filter(User.username == username).first()
            if not user:
                print(f"  ! nicht gefunden: {username} (uebersprungen)")
                continue
            user.password_hash = pw_hash
            user.must_change_password = 0
            user.totp_enabled = 0
            user.totp_secret = None
            updated += 1
            print(f"  - {username:12s} | huerden-frei, Passwort gesetzt")
        s.commit()

    print(f"\nFertig: {updated} Accounts direkt nutzbar.")
    print(f"Passwort fuer ALLE: {DEMO_PW}")
    print("Start ohne 2FA-Zwang:  $env:REQUIRE_2FA = 'false'  vor start-external.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
