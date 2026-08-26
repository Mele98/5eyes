"""Regression-Lock fuer REC-007 (Codex-Audit 2026-08-25,
docs/audits/2026-08-25-auth-execution-operations-followup-audit.md).

cost_disclosure_snapshot_json (die tatsaechlich gezeigten Kostenzahlen)
fehlte im Integritaets-Hash von AdvisoryLog -- nur das Bool-Flag
cost_disclosure_given war Teil des Vertrags. Eine nachtraegliche Aenderung
der ausgewiesenen Kosten haette integrity_hash unveraendert gelassen.

Der Fix erweitert den Feld-Vertrag in
services/advisory_log_integrity.py::compute_integrity_hash() UND
services/advisory_log_service.py::build_hash_payload() um das neue Feld.
Damit bereits gespeicherte Zeilen nicht faelschlich als "manipuliert"
gelten (sie wurden unter dem ALTEN Vertrag signiert), migriert
database.py::migrate_advisory_log_hash_scheme_cost_disclosure_snapshot()
bestehende Zeilen -- aber NUR, wenn sie den ALTEN Vertrag noch erfuellen.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, migrate_advisory_log_hash_scheme_cost_disclosure_snapshot  # noqa: E402
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: E402,F401
configure_mappers()

from models.review import AdvisoryLog  # noqa: E402
from services.advisory_log_integrity import compute_integrity_hash  # noqa: E402

_NOW = "2026-05-28T14:00:00.000Z"

_OLD_SCHEME_FIELDS = (
    "mandate_id", "advisor_id", "entry_type", "entry_datetime",
    "duration_minutes", "communication_channel", "language", "location",
    "title", "description", "decision", "status", "participants_json",
    "topics_json", "risk_warnings_given_json", "cost_disclosure_given",
    "conflict_disclosure_ids_json", "suitability_check_id",
    "recommendation_run_id", "client_signed", "client_signed_at", "version",
)


def _old_scheme_hash(row: dict) -> str:
    parts = []
    for key in _OLD_SCHEME_FIELDS:
        value = row.get(key)
        if value is None:
            parts.append("")
        elif isinstance(value, bool) or key in ("cost_disclosure_given", "client_signed"):
            parts.append("1" if value else "0")
        else:
            parts.append(str(value))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'rec007.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


def _row_dict(**overrides) -> dict:
    base = dict(
        id="log-1", mandate_id="m-1", advisor_id="a-1", entry_type="Sonstiges",
        entry_datetime=_NOW, duration_minutes=30, communication_channel="persoenlich",
        language="de", location="Zuerich", title="t", description="d",
        decision="dec", status="Empfohlen", participants_json="[]", topics_json="[]",
        risk_warnings_given_json="[]", cost_disclosure_given=1,
        cost_disclosure_snapshot_json='{"annual_rappen": 1200}',
        conflict_disclosure_ids_json="[]", suitability_check_id=None,
        recommendation_run_id=None, client_signed=0, client_signed_at=None,
        version=1,
    )
    base.update(overrides)
    return base


def _insert_advisory_log(engine, row: dict, integrity_hash: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO advisory_log (id, mandate_id, advisor_id, entry_type, "
                "entry_date, entry_datetime, duration_minutes, communication_channel, "
                "language, location, title, description, decision, status, "
                "participants_json, topics_json, risk_warnings_given_json, "
                "cost_disclosure_given, cost_disclosure_snapshot_json, "
                "conflict_disclosure_ids_json, suitability_check_id, "
                "recommendation_run_id, client_signed, client_signed_at, version, "
                "integrity_hash, created_at, updated_at) "
                "VALUES (:id, :mandate_id, :advisor_id, :entry_type, :entry_date, "
                ":entry_datetime, :duration_minutes, :communication_channel, "
                ":language, :location, :title, :description, :decision, :status, "
                ":participants_json, :topics_json, :risk_warnings_given_json, "
                ":cost_disclosure_given, :cost_disclosure_snapshot_json, "
                ":conflict_disclosure_ids_json, :suitability_check_id, "
                ":recommendation_run_id, :client_signed, :client_signed_at, "
                ":version, :integrity_hash, :created_at, :updated_at)"
            ),
            {
                **row,
                "entry_date": "2026-05-28",
                "integrity_hash": integrity_hash,
                "created_at": _NOW,
                "updated_at": _NOW,
            },
        )


def test_migration_recomputes_hash_for_a_row_signed_under_the_old_scheme(engine):
    row = _row_dict()
    old_hash = _old_scheme_hash(row)
    _insert_advisory_log(engine, row, old_hash)

    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(engine)

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT integrity_hash FROM advisory_log WHERE id = :id"),
            {"id": "log-1"},
        ).scalar_one()
    expected_new_hash = compute_integrity_hash(payload=row)
    assert stored == expected_new_hash
    assert stored != old_hash


def test_migration_is_idempotent(engine):
    row = _row_dict()
    old_hash = _old_scheme_hash(row)
    _insert_advisory_log(engine, row, old_hash)

    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(engine)
    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(engine)

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT integrity_hash FROM advisory_log WHERE id = :id"),
            {"id": "log-1"},
        ).scalar_one()
    assert stored == compute_integrity_hash(payload=row)


def test_migration_does_not_touch_a_row_that_was_already_tampered(engine):
    """Eine Zeile, die schon unter dem ALTEN Vertrag nicht mehr passt (echter
    Manipulationsverdacht), darf die Migration NICHT stillschweigend mit
    einem frischen, gueltig aussehenden Hash reparieren."""
    row = _row_dict()
    genuinely_wrong_hash = "0" * 64
    _insert_advisory_log(engine, row, genuinely_wrong_hash)

    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(engine)

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT integrity_hash FROM advisory_log WHERE id = :id"),
            {"id": "log-1"},
        ).scalar_one()
    assert stored == genuinely_wrong_hash


def test_migration_skips_rows_without_a_stored_hash(engine):
    row = _row_dict()
    _insert_advisory_log(engine, row, None)

    # Darf nicht crashen und darf keinen Hash erfinden.
    migrate_advisory_log_hash_scheme_cost_disclosure_snapshot(engine)

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT integrity_hash FROM advisory_log WHERE id = :id"),
            {"id": "log-1"},
        ).scalar_one()
    assert stored is None
