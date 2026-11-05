"""N-870-6 (2026-11-05): Betreiber-CLI fuer den Offline-Rewrap der Master-KEK.

Wann
----
Ares startet nicht, weil die bisherige Passphrase-KEK die Staerkeregel
verletzt (Meldung "TENANT_MASTER_KEK ist als Passphrase zu schwach").
Die Daten sind unveraendert; die Tenant-DEKs sind nur noch mit dieser alten
Passphrase verpackt. Platzhalter, Vorlagenwerte und oeffentlich
rekonstruierbare Ableitungen werden auch hier abgelehnt -- solche
Installationen laufen ueber den Migrator.

Ablauf
------
1. Server stoppen und eine Sicherung anlegen (``python scripts/backup_now.py``).
2. Einen neuen Fernet-Key erzeugen und NUR fuer diesen Aufruf als
   ``TENANT_MASTER_KEK_NEW`` in die Umgebung setzen. ``TENANT_MASTER_KEK``
   bleibt die alte Passphrase (Quelle).
3. ``python scripts/rewrap_tenant_master_kek.py --yes``
   Alle Tenant-DEKs werden in EINER Transaktion von der alten auf die neue KEK
   umverpackt und gegen die neue KEK rueckgeprueft; jeder Fehler laesst den
   Bestand unveraendert. Ausgegeben wird nur die Anzahl, nie ein Schluessel.
4. Den neuen Key als ``TENANT_MASTER_KEK`` setzen, ``TENANT_MASTER_KEK_NEW``
   entfernen, die alte Passphrase verwerfen, Server starten.

Die Datenbank kommt aus ``config.settings`` (DB_PATH / DATABASE_URL) --
dieselbe Quelle wie der Server.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TARGET_ENV = "TENANT_MASTER_KEK_NEW"


def _register_all_models() -> None:
    """N-870-9: alle ORM-Modelle registrieren, bevor eine Session Mapper
    konfiguriert (wie main bzw. services.postgres_rls.import_tenant_models).
    Sonst scheitert schon die Tenant-Abfrage an Beziehungen anderer Modelle
    (z. B. PortfolioHandoff -> 'Mandate'), wenn das Skript allein laeuft."""
    import importlib
    import pkgutil

    import models as models_pkg

    for module_info in pkgutil.iter_modules(models_pkg.__path__, prefix=f"{models_pkg.__name__}."):
        importlib.import_module(module_info.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tenant-DEKs von TENANT_MASTER_KEK auf TENANT_MASTER_KEK_NEW umverpacken",
    )
    parser.add_argument("--yes", action="store_true", help="Bestaetigung (Pflicht)")
    args = parser.parse_args(argv)

    if not args.yes:
        print("Abbruch: --yes fehlt. Vorher Server stoppen und Sicherung anlegen.", file=sys.stderr)
        return 2
    target = str(os.environ.get(TARGET_ENV, "") or "").strip()
    if not target:
        print(f"Abbruch: {TARGET_ENV} fehlt (neuer Fernet-Key).", file=sys.stderr)
        return 2

    _register_all_models()
    import database
    from config import settings
    from services.tenant_crypto import TenantCryptoError, rewrap_tenant_deks_to_master_kek

    source = str(getattr(settings, "tenant_master_kek", "") or "").strip()
    with database.SessionLocal() as db:
        try:
            count = rewrap_tenant_deks_to_master_kek(db, source_kek=source, target_kek=target)
            db.commit()
        except TenantCryptoError as exc:
            db.rollback()
            print(f"Abbruch, nichts geaendert: {exc}", file=sys.stderr)
            return 1
    print(
        f"rewrapped_deks={count}. Jetzt den neuen Key als TENANT_MASTER_KEK setzen "
        f"und {TARGET_ENV} entfernen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
