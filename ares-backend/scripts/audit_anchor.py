"""F4 (Codex-Entscheid Runde 3, 2026-11-07): Betreiber-CLI fuer den Audit-Anker.

Zweck
-----
Die Audit-Kette ist ohne externen Bezugspunkt nicht gegen Abschneiden des
Endes oder vollstaendige Neuberechnung geschuetzt. Ein Anker (Kettenkopf +
Bestandssiegel, ohne Kundendaten) wird deshalb ausserhalb des Rechners und
der Backups abgelegt: ausgedruckt bzw. in einer append-only/WORM- oder
Treuhand-Ablage (Owner-Schritt, Runbook). Spaeter laesst sich pruefen, ob die
Kette den Anker-Stand unveraendert enthaelt.

Aufruf
------
    python scripts/audit_anchor.py export [--out DATEI]
        Vollpruefung; nur bei intakter Kette wird die Quittung ausgegeben
        (sonst Exit 2). Mit --out wird die Datei neu angelegt (bestehende
        Datei: Exit 2, nie ueberschreiben). Der Export wird auditiert.
    python scripts/audit_anchor.py verify DATEI
        Exit 0 = Anker-Stand unveraendert enthalten, Exit 1 = Abweichung,
        Exit 2 = Anker unlesbar.
    python scripts/audit_anchor.py verify-manifest BACKUP.db.json
        Signatur und db_sha256 eines Backup-Manifests pruefen und dessen
        Anker anzeigen (Exit 0/1).

Die Datenbank kommt aus ``config.settings`` (DB_PATH / DATABASE_URL), der
Signaturschluessel aus BACKUP_HMAC_KEY (optional). Ausgegeben werden nur
Sequenznummern, Hashes, Zaehler und Gruende -- nie Inhalte oder Pfade.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

AUDIT_ACTOR = "cli-operator"


def _register_all_models() -> None:
    import importlib
    import pkgutil

    import models as models_pkg

    for module_info in pkgutil.iter_modules(models_pkg.__path__, prefix=f"{models_pkg.__name__}."):
        importlib.import_module(module_info.name)


def _export(out: str | None) -> int:
    from config import settings
    from database import SessionLocal
    from services.audit import log
    from services.audit import AuditAnchorError, export_audit_anchor, format_anchor_text
    from services.tenant_context import operator_bypass

    target = Path(out).expanduser() if out else None
    if target is not None and target.exists():
        print("Zieldatei existiert bereits; ein Anker wird nie ueberschrieben.", file=sys.stderr)
        return 2
    with SessionLocal() as db, operator_bypass(db):
        try:
            anchor = export_audit_anchor(db, key=settings.backup_hmac_key)
        except AuditAnchorError as exc:
            print(f"Kein Anker ausgestellt: {exc}", file=sys.stderr)
            return 2
        log(
            db,
            user_id=AUDIT_ACTOR,
            user_name=AUDIT_ACTOR,
            table_name="audit_anchor",
            record_id=str(anchor["fingerprint"]),
            action="EXPORT",
            new_value=str(anchor["chain_sequence"]),
        )
        db.commit()
    receipt = format_anchor_text(anchor)
    if target is not None:
        with open(target, "x", encoding="ascii", newline="\n") as fh:
            fh.write(receipt)
        print(f"Anker geschrieben (Kettenkopf {anchor['chain_sequence']}, Fingerabdruck {anchor['fingerprint']}).")
    else:
        sys.stdout.write(receipt)
    return 0


def _verify(path: str) -> int:
    from config import settings
    from database import SessionLocal
    from services.audit import AuditAnchorError, verify_audit_anchor
    from services.tenant_context import operator_bypass

    payload = Path(path).expanduser().read_text(encoding="ascii")
    with SessionLocal() as db, operator_bypass(db):
        try:
            result = verify_audit_anchor(db, payload, key=settings.backup_hmac_key)
        except AuditAnchorError as exc:
            print(f"Anker nicht lesbar: {exc}", file=sys.stderr)
            return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def _verify_manifest(path: str) -> int:
    from services.backup import verify_backup_manifest

    result = verify_backup_manifest(path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ares Audit-Anker exportieren und pruefen")
    sub = parser.add_subparsers(dest="command", required=True)
    export_parser = sub.add_parser("export", help="Anker nach Vollpruefung ausgeben")
    export_parser.add_argument("--out", default=None, help="Zieldatei (wird neu angelegt)")
    verify_parser = sub.add_parser("verify", help="Anker gegen die heutige Kette pruefen")
    verify_parser.add_argument("path")
    manifest_parser = sub.add_parser("verify-manifest", help="Backup-Manifest pruefen")
    manifest_parser.add_argument("path")
    args = parser.parse_args(argv)

    _register_all_models()
    if args.command == "export":
        return _export(args.out)
    if args.command == "verify":
        return _verify(args.path)
    return _verify_manifest(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
