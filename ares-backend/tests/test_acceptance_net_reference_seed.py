"""Abnahmenetz G6: Referenzdaten-Seed einer frischen Installation eingefroren.

Laenderpaket-Schritt X0 (nur Tests). Spaetere Schritte (X12 Produktkatalog,
X13 Marktreferenz, Hausmatrix-Defaults aus dem Laenderpaket) muessen einen
leeren Dump-Diff liefern.

Dump: alle Tabellen einer frischen SQLite-Installation (``init_db`` plus
Start-/Engine-Seeds), Zeilen in Einfuegereihenfolge. Volatil und deshalb
normalisiert: UUIDs (stabile Aliase in Reihenfolge des ersten Auftretens,
damit Fremdschluessel-Bezuege erhalten bleiben), Zeitstempel, das heutige
Datum und Hex-Hashes ueber diese Werte. Floats mit 12 signifikanten Stellen.

Basiswert: je Tabelle Spaltenliste, Zeilenzahl und Digest je Zeile (keine
Klartexte im Repo). Klartext-Dump lokal: ``ACCEPTANCE_NET_DUMP_DIR``.
Nicht abgedeckt: der zweite Teil von G6 (Bestands-Fixture); dafuer gibt es
noch keine eingecheckte Bestands-DB.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from tests.acceptance_net_install import fresh_installation  # noqa: E402
from tests.acceptance_net_support import (  # noqa: E402
    assert_matches_baseline,
    canonical,
    canonical_json,
    digest,
    dump_actual,
)

_UUID_FULL = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TS_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_HEX_FULL = re.compile(r"^[0-9a-fA-F]{32,}$")


def _today_values() -> set[str]:
    now = _dt.datetime.now(_dt.UTC)
    return {_dt.date.today().isoformat(), now.date().isoformat()}


def _normalized_dump(engine, today: set[str]) -> dict:
    aliases: dict[str, str] = {}

    def norm(value):
        if isinstance(value, str):
            if _UUID_FULL.match(value):
                return aliases.setdefault(value.lower(), f"<uuid#{len(aliases) + 1}>")
            if _TS_FULL.match(value):
                return "<ts>"
            if value in today:
                return "<today>"
            if _HEX_FULL.match(value):
                return "<hex>"
            return value
        return canonical(value, mask=False)

    dump: dict[str, dict] = {}
    with engine.connect() as conn:
        for table in sorted(inspect(engine).get_table_names()):
            result = conn.execute(text(f'SELECT * FROM "{table}" ORDER BY rowid'))
            columns = sorted(result.keys())
            rows = [{col: norm(row[col]) for col in columns} for row in result.mappings()]
            if rows:
                dump[table] = {"columns": columns, "rows": rows}
    return dump


def test_fresh_installation_reference_seed_matches_baseline(tmp_path):
    before = _today_values()
    with fresh_installation(tmp_path / "fresh.db") as (engine, _factory):
        today = before | _today_values()
        dump = _normalized_dump(engine, today)

    dump_actual("reference_seed_dump.json", json.dumps(dump, sort_keys=True, ensure_ascii=False, indent=1))
    summary = {
        table: {
            "columns": content["columns"],
            "row_count": len(content["rows"]),
            "row_sha256": [digest(canonical_json(row))[:32] for row in content["rows"]],
        }
        for table, content in dump.items()
    }
    assert_matches_baseline("reference_seed_ch.json", {
        "tables": summary,
        "dump_sha256": digest(dump),
    })
