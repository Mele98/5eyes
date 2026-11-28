"""L2d / N-938-06: eine Zeitbasis fuer valid_from/valid_to (Policy-Aktivierung um Mitternacht).

Befund (Livetest r3, 22.11. 00:29 Ortszeit): Der Seed legte die Standard-Policy
mit ``valid_from = date.today()`` an (lokales Datum, ``2026-11-22``). Die
Aktivierung einer neuen Version schrieb ``prev.valid_to = _now()`` (UTC,
``2026-11-21T23:29...Z``). Die CHECK-Regel ``valid_to IS NULL OR valid_to >=
valid_from`` vergleicht Text -> zwischen 00:00 und 01:00 Schweizer Zeit 422.

Fix: ``database.validity_instant()`` liefert valid_from UND valid_to der
Zeitpunkt-Tabelle optimizer_policies (Seed, Anlegen, Aktivieren, Klonen,
Entwurf). Datums-Tabellen nutzen ``database.validity_day()`` fuer beide
Felder (Kalendertag der Prozess-Zeitzone, KN7). Altzeilen mit lokalem Datum
schliesst ``validity_end`` nie vor ihrem Beginn.

Grenztest: 22:30 / 23:30 / 00:30 UTC im Winter und 22:30 UTC im Sommer, Prozess-
Zeitzone UTC und Europe/Zurich (wo ``time.tzset`` existiert; sonst lokal).
Echtes Desktop-Rohschema (ares_schema.sql mit CHECK), echter Seed, echte Route.

Gegenprobe: Seed wieder mit ``valid_from=today`` (lokales Datum) -> unter
Europe/Zurich um 23:30 UTC (Winter) und 22:30 UTC (Sommer) rot mit 422.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.test_kn7_midnight_boundary import BOUNDARY_INSTANTS, _travel, process_zone  # noqa: F401

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = "admin-l2d-validity"


@pytest.fixture
def schema_db(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "l2d_validity.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # Echter Desktop-Startpfad: Rohschema (ares_schema.sql, mit CHECK) + Migrationen.
    monkeypatch.setattr(db_module.settings, "db_bootstrap_schema_on_startup", True, raising=False)
    db_module.init_db(target_engine=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with SF() as db:
        from models.users import User

        db.add(User(id=_ADMIN, username=_ADMIN, password_hash="x", full_name="Admin L2d",
                    role="admin", is_active=1, created_at="2026-01-01T00:00:00.000Z",
                    updated_at="2026-01-01T00:00:00.000Z"))
        db.commit()
    try:
        yield SF
    finally:
        engine.dispose()


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _seed_and_activate_new_version(SF):
    """Seed (Standard-Policy), dann neue Version anlegen und aktivieren -- am
    selben Zeitpunkt, wie im Livetest r3 (Gebuehrenvereinbarung)."""
    from models.allocation import OptimizerPolicy
    from models.users import User
    from routers.allocation import activate_optimizer_policy
    from services.optimizer_policy_lifecycle import new_draft_version
    from services.portfolio_engine import _ensure_runtime_reference_data_ch

    with SF() as db:
        seeded, _cma = _ensure_runtime_reference_data_ch(db, _ADMIN)
        db.commit()
        seeded_id = seeded.id
    with SF() as db:
        source = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == seeded_id).one()
        draft = new_draft_version(db, source, now=_now_instant(), created_by=_ADMIN)
        db.commit()
        draft_id = draft.id
    with SF() as db:
        admin = db.query(User).filter(User.id == _ADMIN).one()
        activate_optimizer_policy(draft_id, _request(), db=db, current_user=admin)
    with SF() as db:
        prev = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == seeded_id).one()
        new = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == draft_id).one()
        return prev, new


def _now_instant():
    from database import validity_instant

    return validity_instant()


@pytest.mark.parametrize("instant", BOUNDARY_INSTANTS, ids=lambda i: i.strftime("%m%d-%H%MZ"))
def test_policy_activation_never_breaks_validity_check_at_midnight(schema_db, process_zone, instant):
    with _travel(instant, process_zone):
        prev, new = _seed_and_activate_new_version(schema_db)
    stamp = instant.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Eine Uhr, eine Form: Seed-Beginn, Ende und neuer Beginn sind derselbe UTC-Zeitpunkt.
    assert prev.valid_from == stamp, (process_zone, prev.valid_from)
    assert prev.valid_to == stamp and prev.is_current == 0
    assert new.valid_from == stamp and new.valid_to is None and new.is_current == 1
    assert prev.valid_to >= prev.valid_from


@pytest.mark.parametrize("instant", BOUNDARY_INSTANTS, ids=lambda i: i.strftime("%m%d-%H%MZ"))
def test_legacy_policy_with_local_date_closes_without_422(schema_db, process_zone, instant):
    """Altzeile vor L2d: valid_from = lokales Datum. Die Abloesung endet nie vor
    dem Beginn (leeres Intervall statt CHECK-Verstoss)."""
    from database import validity_day
    from models.allocation import OptimizerPolicy

    with _travel(instant, process_zone):
        with schema_db() as db:
            from services.portfolio_engine import _ensure_runtime_reference_data_ch

            seeded, _ = _ensure_runtime_reference_data_ch(db, _ADMIN)
            local_day = validity_day()
            seeded.valid_from = local_day  # so schrieb der Seed vor L2d
            db.commit()
        prev, new = _seed_and_activate_new_version(schema_db)
        assert prev.valid_from == local_day
        assert prev.valid_to >= prev.valid_from
        expected_end = max(instant.strftime("%Y-%m-%dT%H:%M:%S.000Z"), local_day)
        assert prev.valid_to == expected_end
        assert new.is_current == 1
        with schema_db() as db:
            assert db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).count() == 1


def test_check_rule_really_rejects_mixed_clocks(schema_db):
    """Positivkontrolle: die CHECK-Regel greift auf diesem Schema wirklich.
    Ohne sie waere der Grenztest oben aus dem falschen Grund gruen."""
    from models.allocation import OptimizerPolicy
    from models.users import User
    from routers.allocation import activate_optimizer_policy
    from services.optimizer_policy_lifecycle import new_draft_version
    from services.portfolio_engine import _ensure_runtime_reference_data_ch

    with schema_db() as db:
        seeded, _ = _ensure_runtime_reference_data_ch(db, _ADMIN)
        seeded.valid_from = "2099-01-01"
        db.commit()
        draft = new_draft_version(db, seeded, now="2026-11-21T23:30:00.000Z", created_by=_ADMIN)
        db.commit()
        draft_id, seeded_id = draft.id, seeded.id
    with schema_db() as db:
        db.execute(
            OptimizerPolicy.__table__.update()
            .where(OptimizerPolicy.__table__.c.id == seeded_id)
            .values(valid_to=None)
        )
        db.commit()
    import sqlalchemy

    with schema_db() as db:
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.execute(
                OptimizerPolicy.__table__.update()
                .where(OptimizerPolicy.__table__.c.id == seeded_id)
                .values(valid_to="2026-11-21T23:30:00.000Z")
            )
            db.commit()
    # Die Route schliesst die Altzeile korrekt (validity_end), kein 422.
    with schema_db() as db:
        admin = db.query(User).filter(User.id == _ADMIN).one()
        try:
            activate_optimizer_policy(draft_id, _request(), db=db, current_user=admin)
        except HTTPException as exc:  # pragma: no cover - Diagnose
            pytest.fail(f"Aktivierung scheiterte: {exc.status_code} {exc.detail}")
    with schema_db() as db:
        prev = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == seeded_id).one()
        assert prev.valid_to == "2099-01-01"


def test_validity_helpers_share_one_clock():
    from database import validity_day, validity_end, validity_instant
    import time_machine

    with time_machine.travel(datetime(2026, 11, 21, 23, 30, tzinfo=timezone.utc), tick=False):
        assert validity_instant() == "2026-11-21T23:30:00.000Z"
        assert validity_day() == datetime.now().date().isoformat()
    assert validity_end("2026-11-22", "2026-11-21T23:30:00.000Z") == "2026-11-22"
    assert validity_end("2026-11-21T22:00:00.000Z", "2026-11-21T23:30:00.000Z") == "2026-11-21T23:30:00.000Z"
    assert validity_end(None, "2026-11-21T23:30:00.000Z") == "2026-11-21T23:30:00.000Z"
