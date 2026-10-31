"""WP-500-Fix (2026-07-01): eine NULL in property_rental_inflation_linked darf die
`/wealth-positions`-Serialisierung (response_model=list[WealthPositionResponse])
nicht mehr mit 500 (ResponseValidationError) killen.

Ursache: die Spalte wurde in einer frühen Migration OHNE Default/Backfill zugefügt
-> Bestandszeilen NULL. Response-Schema erwartet int -> ein einziges NULL riss die
GESAMTE Positionsliste im Frontend weg (nichts sichtbar/editierbar).

Zwei Verteidigungslinien getestet:
1. Schema coerct present-None -> 0 (Feld-Default greift nur bei FEHLENDEM Wert).
2. database.ensure_runtime_columns backfillt Alt-NULLs idempotent auf 0.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
import database
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()
from models.wealth import WealthPosition
from schemas.wealth import WealthPositionResponse


def _mk_position(session, **over):
    pos = WealthPosition(
        id=str(uuid.uuid4()),
        client_id="c1",
        label="Wohnung in Vietnam",
        position_type="Immobilien",
        assignment="Anderes Vermögen",
        current_value_rappen=10_000_000,
        currency="CHF",
        property_rental_income_rappen=300_000,
        created_at="2026-03-20T00:00:00.000Z",
        updated_at="2026-03-20T00:00:00.000Z",
        **over,
    )
    session.add(pos)
    session.commit()
    return pos


# ── 1. Schema-Coercion ───────────────────────────────────────────────────────

def test_schema_coerces_null_inflation_linked_to_zero(tmp_path):
    from types import SimpleNamespace
    eng = create_engine(f"sqlite:///{tmp_path/'a.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    pos = _mk_position(s)
    # Alle Spaltenwerte übernehmen, aber inflation_linked auf None (Legacy-NULL) —
    # ohne die DB-NOT-NULL-Constraint zu verletzen (from_attributes liest das Objekt).
    attrs = {c.name: getattr(pos, c.name) for c in WealthPosition.__table__.columns}
    attrs["property_rental_inflation_linked"] = None
    resp = WealthPositionResponse.model_validate(SimpleNamespace(**attrs), from_attributes=True)
    assert resp.property_rental_inflation_linked == 0  # ohne Fix -> ValidationError
    assert resp.label == "Wohnung in Vietnam"


def test_schema_keeps_explicit_one(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path/'b.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    pos = _mk_position(s, property_rental_inflation_linked=1)
    resp = WealthPositionResponse.model_validate(pos, from_attributes=True)
    assert resp.property_rental_inflation_linked == 1


# ── 2. Migration-Backfill ────────────────────────────────────────────────────

def test_ensure_runtime_columns_backfills_null(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'c.db'}")
    # create_all legt u.a. risk_assessments an (ensure_runtime_columns braucht das).
    Base.metadata.create_all(eng)
    # wealth_positions durch die LEGACY-Variante ersetzen: Spalte existiert, ist aber
    # NULLABLE (so wie sie eine frühe Migration ohne Default zugefügt hätte).
    with eng.begin() as c:
        c.execute(text("DROP TABLE wealth_positions"))
        c.execute(text(
            "CREATE TABLE wealth_positions (id TEXT PRIMARY KEY, property_rental_inflation_linked INTEGER)"
        ))
        c.execute(text(
            "INSERT INTO wealth_positions (id, property_rental_inflation_linked) VALUES ('a', NULL), ('b', 1)"
        ))

    monkeypatch.setattr(database, "engine", eng)
    database.ensure_runtime_columns()

    rows = dict(eng.connect().execute(text(
        "SELECT id, property_rental_inflation_linked FROM wealth_positions"
    )).fetchall())
    assert rows["a"] == 0   # Alt-NULL -> 0 gebackfillt
    assert rows["b"] == 1   # bestehender Wert unangetastet
