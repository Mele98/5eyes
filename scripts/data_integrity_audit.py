#!/usr/bin/env python
"""Daten-Integritäts-Audit (FINMA-Hygiene).

Erkennt synthetische / per Skript eingeschleuste Datensätze in der Produktions-DB —
damit niemals Test-/Demo-Daten zwischen echten Kundendaten landen.

Erkennungsmerkmale:
  1. **Skript-Zeitstempel:** Die App schreibt `created_at` IMMER als
     `YYYY-MM-DDTHH:MM:SS.mmmZ`. Direkt-Inserts via Skript (z. B. das frühere
     seed_leart.py mit fehlerhaftem strftime) weichen davon ab → verdächtig.
  2. **Demo-/Foundation-Labels:** bekannte Beispiel-Datensätze (Foundation-Case).

Aufruf:
    python scripts/data_integrity_audit.py [--db PFAD] [--json]
Exit-Code: 0 = sauber, 1 = Funde (CI-/Audit-tauglich).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# App-Format aus services/auth._now() / wealth-Endpoints: ...THH:MM:SS.mmmZ
VALID_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# Bekannte Foundation-/Demo-Labels (services/foundation_example.py).
DEMO_LABELS = {
    "UBS Advisory Depot", "ZKB Liquiditaetsreserve", "Freizuegigkeitsdepot",
    "Saeule 3a Bestand", "Festhypothek Hauptwohnsitz", "Eigentumswohnung Zuerichberg",
    "Daniel Lohn", "Claudia Einkommen", "Mietertrag Zweitobjekt",
}

# Tabellen mit created_at + (client_id/label), die echte Kundendaten tragen.
SCANNED = ["cashflows", "wealth_positions", "goals"]


def _timestamp_is_script(ts) -> bool:
    return bool(ts) and not VALID_TS.match(str(ts))


def scan_database(conn: sqlite3.Connection) -> list[dict]:
    """Liefert eine Liste verdächtiger Datensätze (leere Liste = sauber)."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    findings: list[dict] = []
    for table in SCANNED:
        if table not in tables:
            continue
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
        if "created_at" not in cols:
            continue
        label_col = "label" if "label" in cols else None
        for row in cur.execute(f"SELECT * FROM {table}"):
            keys = row.keys()
            label = (row[label_col] if label_col else None) or ""
            reasons = []
            if _timestamp_is_script(row["created_at"] if "created_at" in keys else None):
                reasons.append(f"Skript-Zeitstempel created_at={row['created_at']}")
            if label in DEMO_LABELS:
                reasons.append("Foundation-/Demo-Label")
            # nur aktive (nicht soft-deleted) Datensätze sind FINMA-relevant
            active = ("deleted_at" not in keys) or (row["deleted_at"] in (None, ""))
            if reasons and active:
                findings.append({
                    "table": table,
                    "id": row["id"] if "id" in keys else None,
                    "client_id": row["client_id"] if "client_id" in keys else None,
                    "label": label,
                    "reasons": reasons,
                })
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Daten-Integritäts-Audit (FINMA-Hygiene).")
    ap.add_argument("--db", default=str(Path.home() / "5eyes" / "5eyes.db"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB nicht gefunden: {db_path}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(str(db_path))
    try:
        findings = scan_database(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        if not findings:
            print(f"[OK] SAUBER - keine synthetischen/Skript-Datensaetze in {db_path.name}")
        else:
            print(f"[WARN] {len(findings)} verdaechtige Datensaetze in {db_path.name}:")
            for f in findings:
                print(f"  [{f['table']}] '{f['label']}' (id={f['id']}) - {'; '.join(f['reasons'])}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
