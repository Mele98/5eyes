"""AF-6 (2026-10-23): Betreiber-CLI fuer den Massenwiderruf.

Aufruf
------
    python scripts/revoke_all_sessions.py --yes
    python scripts/revoke_all_sessions.py --yes --tenant-id <mandant>

Ohne ``--tenant-id`` wirkt der Widerruf global (alle Mandanten, auf
PostgreSQL unter explizitem Operator-Bypass): jedes bisher ausgestellte
Access- und Refresh-Token wird ungueltig, alle Benutzer muessen sich neu
anmelden. Ein Audit-Eintrag wird geschrieben. Die Datenbank kommt aus
``config.settings`` (DB_PATH / DATABASE_URL) -- dieselbe Quelle wie der
Server.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Massenwiderruf aller Sessions (Access + Refresh)")
    parser.add_argument("--tenant-id", default=None, help="nur diesen Mandanten (Default: global)")
    parser.add_argument("--actor", default="cli-operator", help="Name im Audit-Eintrag")
    parser.add_argument("--yes", action="store_true", help="Bestaetigung (Pflicht)")
    args = parser.parse_args(argv)

    if not args.yes:
        print("Abbruch: --yes fehlt. Der Widerruf meldet alle betroffenen Benutzer ab.", file=sys.stderr)
        return 2

    import database
    from services.session_revocation import revoke_all_sessions

    with database.SessionLocal() as db:
        result = revoke_all_sessions(
            db,
            actor_user_id=args.actor,
            actor_name=args.actor,
            tenant_id=args.tenant_id,
        )
        db.commit()
    print(
        f"scope={result.scope} tenant_id={result.tenant_id or '-'} "
        f"revoked_before={result.revoked_before} users={result.users} "
        f"refresh_tokens={result.refresh_tokens}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
