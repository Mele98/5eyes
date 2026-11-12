"""advisory_log.retain_until ab Mandatsende statt ab Eintrag (Bestand).

H7 C-6 (Compliance-Audit 2026-11-07, Luecke 6): ``retain_until`` war
``entry_datetime + 10 Jahre``. Die Aufbewahrung laeuft aber ab Ende der
Geschaeftsbeziehung bzw. des Mandats (GwG Art. 7 Abs. 3; Beweissicherung
OR 127). Regel (identisch zu services/advisory_log_integrity.py::
extended_retain_until und database.py::
migrate_advisory_log_retention_from_mandate_end fuer SQLite):

* Mandat offen (``closed_at`` leer/unlesbar): die Altberechnung
  ``Eintrag + 10 J.`` wird NULL -- die Frist laeuft noch nicht (aufbewahren
  bis Mandatsende + 10 Jahre). Jede andere Frist bleibt als Mindestfrist.
* Mandat beendet: Maximum aus bisheriger Frist, Eintrag + 10 Jahre und
  Mandatsende + 10 Jahre. Nie verkuerzend.

Nachvollziehbar: reine Datenmigration ohne Schemaaenderung; die Zahl der
geaenderten Zeilen wird ausgegeben. ``retain_until`` ist nicht Teil des
Integritaets-Hashes. Downgrade ist bewusst ein No-op (eine Rueckkehr zu
kuerzeren Fristen waere verkuerzend).

Revision ID: e1c6a7d4b2f9
Revises: f8c1d5a3e7b2
Create Date: 2026-11-07
"""
from __future__ import annotations

from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "e1c6a7d4b2f9"
down_revision: Union[str, Sequence[str], None] = "f8c1d5a3e7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETENTION_YEARS = 10


def _plus_years(value: str | None) -> str | None:
    raw = str(value or "").strip()[:10]
    try:
        base = date.fromisoformat(raw)
    except ValueError:
        return None
    try:
        return base.replace(year=base.year + RETENTION_YEARS).isoformat()
    except ValueError:  # 29. Februar
        return base.replace(year=base.year + RETENTION_YEARS, day=28).isoformat()


def _target(current: str | None, entry_datetime: str | None, closed_at: str | None) -> str | None:
    end = _plus_years(closed_at)
    if end is None:
        # Offenes Mandat: nur die Altberechnung "Eintrag + 10 J." entfaellt;
        # jede andere Frist bleibt als Mindestfrist (N-884-06).
        kept = str(current).strip()[:10] if str(current or "").strip() else None
        return None if kept is not None and kept == _plus_years(entry_datetime) else current
    candidates = [end]
    floor = _plus_years(entry_datetime)
    if floor is not None:
        candidates.append(floor)
    if str(current or "").strip():
        candidates.append(str(current).strip()[:10])
    return max(candidates)


_DATE_RE = "'^[0-9]{4}-[0-9]{2}-[0-9]{2}'"
# Offline (--sql, PostgreSQL): gleiche Regel als SQL. Online rechnet Python
# (robust gegen unlesbare Altwerte, die ein ::date-Cast abbrechen liesse).
OFFLINE_PG_SQL = (
    "UPDATE advisory_log AS a SET retain_until = CASE "
    f"WHEN m.closed_at ~ {_DATE_RE} THEN GREATEST("
    "COALESCE(substr(a.retain_until, 1, 10), ''), "
    "to_char(substr(m.closed_at, 1, 10)::date + INTERVAL '10 years', 'YYYY-MM-DD'), "
    f"CASE WHEN a.entry_datetime ~ {_DATE_RE} THEN "
    "to_char(substr(a.entry_datetime, 1, 10)::date + INTERVAL '10 years', 'YYYY-MM-DD') "
    "ELSE '' END) "
    f"WHEN a.entry_datetime ~ {_DATE_RE} AND substr(a.retain_until, 1, 10) = "
    "to_char(substr(a.entry_datetime, 1, 10)::date + INTERVAL '10 years', 'YYYY-MM-DD') "
    "THEN NULL ELSE a.retain_until END "
    "FROM mandates AS m WHERE m.id = a.mandate_id"
)
BYPASS_GUC = "app.rls_bypass"


def upgrade() -> None:
    if context.is_offline_mode():
        if context.get_context().dialect.name == "postgresql":
            op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
            op.execute(sa.text(OFFLINE_PG_SQL))
        return
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    rows = bind.execute(sa.text(
        "SELECT a.id, a.retain_until, a.entry_datetime, m.closed_at "
        "FROM advisory_log a JOIN mandates m ON m.id = a.mandate_id"
    )).fetchall()
    changed = 0
    for row_id, current, entry_datetime, closed_at in rows:
        target = _target(current, entry_datetime, closed_at)
        if target != current:
            bind.execute(
                sa.text("UPDATE advisory_log SET retain_until = :value WHERE id = :id"),
                {"value": target, "id": row_id},
            )
            changed += 1
    print(f"H7 C-6: retain_until von {changed} Beratungsprotokoll-Zeilen auf Mandatsende umgestellt")


def downgrade() -> None:
    # Bewusst kein Rueckweg: die alten Fristen (Eintrag + 10 Jahre) waeren
    # bei laufenden Mandaten kuerzer als die gesetzliche Aufbewahrung.
    pass
