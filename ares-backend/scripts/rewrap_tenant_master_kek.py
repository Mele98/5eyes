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

Grenzen
-------
- Nur fuer eine Quell-KEK, die als Passphrase an der Staerkeregel scheitert.
  Ein Fernet-Key oder eine starke Passphrase startet ohnehin: Exit 2,
  "kein Rewrap noetig" (N-870-13).
- KEK-Ablage (DPAPI; ``TENANT_MASTER_KEK_FILE`` zeigt auf eine vorhandene
  Datei, oder die Desktop-Standardablage ``tenant-master-kek.dpapi`` im
  userData-Ordner existiert): der Lauf wird verweigert, bevor etwas geaendert
  wird. Datenbank und
  Ablage lassen sich nicht atomar gemeinsam ersetzen; ein Teilerfolg haette
  DB und Ablage auseinanderlaufen lassen. Die Desktop-App legt dort immer
  einen Fernet-Key ab, der keinen Rewrap braucht.
- Ein Audit-Eintrag (Anzahl, SHA-256 der Tenant-IDs, kein Schluessel) wird in
  derselben Transaktion geschrieben; bei einem Fehler gibt es weder Rewrap
  noch Eintrag.

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


AUDIT_ACTOR = "cli-operator"

# N-870-13: Die Desktop-App setzt TENANT_MASTER_KEK_FILE nur fuer ihren
# Backend-Prozess (ares-desktop/main.js: app.getPath('userData') /
# tenant-master-kek.dpapi). Eine Shell kennt die Variable nicht; deshalb auch
# die Standardorte des userData-Ordners pruefen (productName "Ares"; "ares-
# desktop" fuer Entwicklungslaeufe ohne productName).
KEK_STORE_FILENAME = "tenant-master-kek.dpapi"
_DESKTOP_APP_DIRS = ("Ares", "ares-desktop")


def _default_kek_store_candidates() -> list[Path]:
    bases: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        bases.append(Path(appdata))
    home = Path.home()
    bases.append(home / "AppData" / "Roaming")
    bases.append(Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config")))
    bases.append(home / "Library" / "Application Support")
    return [base / name / KEK_STORE_FILENAME for base in bases for name in _DESKTOP_APP_DIRS]


def _existing_kek_store(store_setting: str) -> bool:
    """True, wenn eine KEK-Ablage existiert (konfiguriert oder Standardort).
    Der Pfad wird nie ausgegeben."""
    candidates = [Path(store_setting).expanduser()] if store_setting else []
    candidates.extend(_default_kek_store_candidates())
    return any(candidate.exists() for candidate in candidates)


def _audit_rewrap(db, result) -> None:
    """N-870-10: Revisionsnachweis in DERSELBEN Transaktion wie der Rewrap
    (ein Commit fuer beides). Nur Anzahl und SHA-256 der sortierten Tenant-IDs,
    kein Schluesselmaterial und kein KEK-Fingerabdruck. action='UPDATE' ist
    ein bestehender audit_log-Wert (kein neuer CHECK-Wert, kein Neuaufbau);
    unter PostgreSQL im expliziten Operator-Bypass."""
    import hashlib
    import json

    from services.audit import log
    from services.tenant_context import operator_bypass

    ids_digest = hashlib.sha256(",".join(sorted(result.tenant_ids)).encode("utf-8")).hexdigest()
    with operator_bypass(db):
        log(
            db,
            user_id=AUDIT_ACTOR,
            user_name=AUDIT_ACTOR,
            table_name="tenants",
            record_id="*",
            action="UPDATE",
            field_name="encrypted_dek",
            new_value=json.dumps({
                "operation": "master_kek_rewrap",
                "rewrapped_deks": result.count,
                "tenant_ids_sha256": ids_digest,
            }, sort_keys=True),
        )


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
    from sqlalchemy.exc import SQLAlchemyError

    import database
    from config import settings
    from services.tenant_crypto import (
        KekRewrapNotNeeded,
        TenantCryptoError,
        rewrap_tenant_deks_to_master_kek,
    )

    # N-870-12: Eine KEK-Ablage (DPAPI, TENANT_MASTER_KEK_FILE) laesst sich
    # nicht in derselben Transaktion wie die Datenbank ersetzen. Ein Lauf
    # wuerde DB und Ablage auseinanderlaufen lassen (Start danach: "widerspricht
    # der KEK-Ablage"). Deshalb fail-closed verweigern, bevor etwas passiert.
    if _existing_kek_store(str(getattr(settings, "tenant_master_kek_file", "") or "").strip()):
        print(
            "Abbruch, nichts geaendert: Es gibt eine KEK-Ablage (TENANT_MASTER_KEK_FILE "
            "oder Standardablage der Desktop-App). "
            "Der Rewrap unterstuetzt nur Installationen, deren KEK allein aus "
            "TENANT_MASTER_KEK kommt. Die Ablage der Desktop-App enthaelt immer einen "
            "Fernet-Key und braucht keinen Rewrap.",
            file=sys.stderr,
        )
        return 2

    source = str(getattr(settings, "tenant_master_kek", "") or "").strip()
    with database.SessionLocal() as db:
        try:
            result = rewrap_tenant_deks_to_master_kek(db, source_kek=source, target_kek=target)
            _audit_rewrap(db, result)
            db.commit()
            count = result.count
        except KekRewrapNotNeeded as exc:
            db.rollback()
            print(f"Abbruch, nichts geaendert: {exc}", file=sys.stderr)
            return 2
        except TenantCryptoError as exc:
            db.rollback()
            print(f"Abbruch, nichts geaendert: {exc}", file=sys.stderr)
            return 1
        except SQLAlchemyError as exc:
            # N-870-11: str(exc) und der Traceback enthalten "[parameters: ...]"
            # -- darin stuende der neu verpackte DEK. Nur Klasse + Treiber-
            # meldung ausgeben, ohne Exception-Kette.
            db.rollback()
            print(
                f"Abbruch (Datenbankfehler), nichts geaendert: {database._db_error_summary(exc)}",
                file=sys.stderr,
            )
            return 1
    print(
        f"rewrapped_deks={count}. Jetzt den neuen Key als TENANT_MASTER_KEK setzen "
        f"und {TARGET_ENV} entfernen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
