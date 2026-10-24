"""Sprint U-10 — DSG-Datenexport CLI.

Offline-Variante des `GET /clients/{id}/data-export`-Endpoints. Liest
direkt die DB, ohne HTTP-Layer. Nuetzlich:
- Wenn der Backend-Server nicht laeuft
- Wenn das Export-Format separat archiviert werden soll
- Vor Migrations, um Pre-/Post-Migration-Snapshots zu vergleichen

Aufruf
------
    python scripts/data_export.py --client-id <UUID>
    python scripts/data_export.py --client-number C-001234
    python scripts/data_export.py --client-id <UUID> --output /tmp/export.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="5eyes DSG-Datenexport CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client-id", type=str, help="Client.id (UUID)")
    group.add_argument(
        "--client-number",
        type=str,
        help="Client.client_number (z.B. C-001234)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Ziel-Datei (.json). Default: STDOUT.",
    )
    args = parser.parse_args()

    from database import SessionLocal  # lazy
    from models.clients import Client
    from services.data_export import export_client_data

    db = SessionLocal()
    try:
        if args.client_id:
            client_id = args.client_id
        else:
            client = (
                db.query(Client)
                .filter(Client.client_number == args.client_number)
                .first()
            )
            if client is None:
                print(
                    f"Kein Client mit number={args.client_number!r}",
                    file=sys.stderr,
                )
                return 2
            client_id = client.id

        payload = export_client_data(db, client_id)
    finally:
        db.close()

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        total = sum(payload["manifest"].values())
        print(
            f"EXPORT ok -> {args.output} "
            f"({len(text)} bytes, {total} Datensaetze, "
            f"client_number={payload['client_number']})"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
