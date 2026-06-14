"""Operator zum super_admin machen (einmalige Einrichtung fuer Firmen-Provisioning).

Aufruf:  python docs/deploy/promote_operator.py <username>
Beispiel: python docs/deploy/promote_operator.py ekonzelmann

Hintergrund: Nur die Rolle 'super_admin' darf Firmen (Tenants) anlegen + Mitarbeiter
zuweisen (Tenant-Admin-API). Tipp: die normale Electron-App vorher schliessen,
damit die DB nicht gelockt ist.
"""
import os
import sqlite3
import sys

DB = os.path.expanduser("~/5eyes/5eyes.db")


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python promote_operator.py <username>")
        return 1
    username = sys.argv[1].strip()
    if not os.path.exists(DB):
        print(f"DB nicht gefunden: {DB}")
        return 1
    con = sqlite3.connect(DB, timeout=15)
    try:
        cur = con.execute(
            "UPDATE users SET role='super_admin' "
            "WHERE username=? AND deleted_at IS NULL",
            (username,),
        )
        con.commit()
        if cur.rowcount:
            print(f"OK: '{username}' ist jetzt super_admin (Operator). "
                  f"Neu einloggen -> Button 'Firmen' erscheint.")
            return 0
        print(f"NICHT GEFUNDEN: kein aktiver User '{username}'.")
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
