"""Sprint U-10 — DSG-Datenexport CLI.

H10 N-899-10 (DSG-Technikaudit): der Export entsteht nur noch ueber einen
freigegebenen Auskunftsfall oder als auditierter Admin-Notfall.

Aufruf
------
    # Regelfall: Export ueber die Betroffenenanfrage (Entscheid erfuellen/
    # einschraenken, Identitaet bestaetigt, Angaben des Verantwortlichen und
    # Verzeichnis freigegeben)
    python scripts/data_export.py --subject-request-id <FALL-ID> --actor-user-id <ADMIN> --output export.json

    # Notfall (z. B. Backend nicht startbar): nur Administration, mit Begruendung,
    # wird im Audit-Log festgehalten
    python scripts/data_export.py --emergency-admin <ADMIN> --reason "<Grund>" --client-id <UUID> --output export.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ADMIN_ROLES = ("admin", "super_admin")


def _write(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"EXPORT ok -> {output} ({len(text)} bytes)")
    else:
        print(text)


def _admin(db, user_id: str):
    from models.users import User

    user = db.get(User, user_id)
    if user is None or user.role not in ADMIN_ROLES or not user.is_active:
        raise SystemExit(f"Benutzer {user_id!r} ist kein aktiver Administrator")
    return user


def main(argv: list[str] | None = None, *, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description="Ares DSG-Datenexport CLI")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--subject-request-id", help="ID eines freigegebenen Auskunftsfalls")
    mode.add_argument("--emergency-admin", help="Benutzer-ID eines Administrators (Notfall)")
    parser.add_argument("--actor-user-id", help="Ausfuehrender Administrator (Regelfall)")
    parser.add_argument("--reason", help="Begruendung (Pflicht im Notfall)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--client-id")
    target.add_argument("--client-number")
    parser.add_argument("--output", default=None, help="Ziel-Datei (.json). Default: STDOUT.")
    args = parser.parse_args(argv)

    from models.clients import Client
    from models.privacy import PrivacySubjectRequest, PrivacySubjectRequestEvent
    from services import privacy_case_events, privacy_subject_requests
    from services.audit import log
    from services.data_export import export_client_data

    if session_factory is None:
        from database import SessionLocal as session_factory  # noqa: N813

    with session_factory() as db:
        if args.subject_request_id:
            if not args.actor_user_id:
                parser.error("--actor-user-id ist Pflicht")
            actor = _admin(db, args.actor_user_id)
            case = db.get(PrivacySubjectRequest, args.subject_request_id)
            if case is None:
                print("Auskunftsfall nicht gefunden", file=sys.stderr)
                return 2
            document = privacy_subject_requests.build_export(db, case, actor_id=actor.id)
            privacy_case_events.append_event(db, PrivacySubjectRequestEvent, tenant_id=case.tenant_id,
                                             case_id=case.id, event_type="export", actor_id=actor.id,
                                             payload={"export_sha256": document["export_sha256"], "channel": "cli"})
            log(db, user_id=actor.id, user_name=actor.full_name, table_name="privacy_subject_requests",
                record_id=case.id, action="EXPORT", client_id=case.client_id,
                new_value=json.dumps({"export_sha256": document["export_sha256"], "channel": "cli"}))
            db.commit()
            _write(document, args.output)
            return 0

        reason = str(args.reason or "").strip()
        if not reason:
            parser.error("--reason ist im Notfall Pflicht")
        actor = _admin(db, args.emergency_admin)
        if args.client_id:
            client_id = args.client_id
        elif args.client_number:
            client = db.query(Client).filter(Client.client_number == args.client_number).first()
            if client is None:
                print(f"Kein Client mit number={args.client_number!r}", file=sys.stderr)
                return 2
            client_id = client.id
        else:
            parser.error("--client-id oder --client-number angeben")
        payload = export_client_data(db, client_id)
        log(db, user_id=actor.id, user_name=actor.full_name, table_name="clients", record_id=client_id,
            action="EXPORT", field_name="cli_emergency_export", client_id=client_id,
            new_value=json.dumps({"reason": reason, "manifest_total": sum(payload["manifest"].values())},
                                 ensure_ascii=False))
        db.commit()
        _write(payload, args.output)
        return 0


if __name__ == "__main__":
    sys.exit(main())
