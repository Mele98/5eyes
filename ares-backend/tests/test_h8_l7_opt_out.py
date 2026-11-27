"""H8 Luecke 7 (Compliance-Audit 2026-11-07, Dok. 104): Opting-out nach Art. 5
FIDLEG nur mit Beleg (document_id) und dokumentierter Kriterien-Checkliste;
Opting-in nur mit Beleg. An der Basis rot: document_id optional, keine Kriterien.
"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, codes, mandate, sf, user  # noqa: E402,F401

import json  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from routers.clients import add_opt_history  # noqa: E402
from schemas.clients import OptHistoryCreate, OptOutCriteria  # noqa: E402

def _criteria(**overrides):
    data = dict(basis="vermoegen_2mio", eligible_assets_verified=True,
                client_informed_of_protection_loss=True, declaration_in_text_form=True)
    data.update(overrides)
    return OptOutCriteria(**data)


def test_opt_out_requires_document_and_complete_checklist(sf):
    with pytest.raises(ValidationError):
        _criteria(client_informed_of_protection_loss=False)
    with pytest.raises(ValidationError):
        _criteria(basis="kenntnisse_und_vermoegen_500k", knowledge_basis="")
    with sf() as db:
        adv = user(db, "adv-1")
        for kwargs in ({}, {"document_id": "beleg-1"}, {"opt_out_criteria": _criteria()}):
            with pytest.raises(HTTPException) as exc:
                add_opt_history(client_id="c-1", body=OptHistoryCreate(
                    from_classification="Privatkunde",
                    to_classification="Professioneller Kunde", **kwargs), db=db, current_user=adv)
            assert exc.value.detail["reason_code"] == "OPT_OUT_EVIDENCE_MISSING"
        entry = add_opt_history(client_id="c-1", body=OptHistoryCreate(
            from_classification="Privatkunde",
            to_classification="Professioneller Kunde", document_id="beleg-1",
            opt_out_criteria=_criteria()), db=db, current_user=adv)
        assert entry.document_id == "beleg-1"
        assert json.loads(entry.opt_out_criteria_json)["basis"] == "vermoegen_2mio"
        # Opting-in (Rueckkehr) braucht den Beleg, aber keine Kriterien.
        with pytest.raises(HTTPException):
            add_opt_history(client_id="c-1", body=OptHistoryCreate(
                from_classification="Professioneller Kunde",
                to_classification="Privatkunde"), db=db, current_user=adv)


def test_alembic_postgres_ddl_adds_opt_out_criteria_column():
    from h8_support import h8_postgres_ddl

    assert "ALTER TABLE client_opt_history ADD COLUMN opt_out_criteria_json VARCHAR" in h8_postgres_ddl()


def test_runtime_patch_adds_opt_out_criteria_column(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect

    import database as db_module
    from h8_support import BACKEND_ROOT

    db_path = tmp_path / "runtime.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=BACKEND_ROOT / "ares_schema.sql")
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("client_opt_history")}
    engine.dispose()
    assert "opt_out_criteria_json" in columns


def test_professional_to_institutional_needs_document_but_no_checklist(sf):
    """N-890-05: jeder Wechsel auf ein tieferes Schutzniveau braucht den Beleg."""
    from models.clients import Client

    with sf() as db:
        db.query(Client).filter(Client.id == "c-1").update({"client_classification": "Professioneller Kunde"})
        db.commit()
        adv = user(db, "adv-1")
        with pytest.raises(HTTPException) as exc:
            add_opt_history(client_id="c-1", body=OptHistoryCreate(
                from_classification="Professioneller Kunde", to_classification="Institutioneller Kunde"),
                db=db, current_user=adv)
        assert exc.value.detail["reason_code"] == "OPT_OUT_EVIDENCE_MISSING"
        entry = add_opt_history(client_id="c-1", body=OptHistoryCreate(
            from_classification="Professioneller Kunde", to_classification="Institutioneller Kunde",
            document_id="erklaerung-inst"), db=db, current_user=adv)
        assert entry.event_type == "Opting-out zu Institutionell"


def test_private_cannot_jump_directly_to_institutional(sf):
    with sf() as db:
        with pytest.raises(HTTPException) as exc:
            add_opt_history(client_id="c-1", body=OptHistoryCreate(
                from_classification="Privatkunde", to_classification="Institutioneller Kunde",
                document_id="x", opt_out_criteria=_criteria()), db=db, current_user=user(db, "adv-1"))
        assert exc.value.detail["reason_code"] == "OPTING_TRANSITION_INVALID"


def test_event_type_is_a_fidleg_value_and_must_match_the_transition(sf):
    """N-890-13: freier Text fuehrte zu 500 am DB-CHECK; Bezeichnungen waren vertauscht."""
    with pytest.raises(ValidationError):
        OptHistoryCreate(event_type="Opting-out", from_classification="Privatkunde",
                         to_classification="Professioneller Kunde")
    with sf() as db:
        with pytest.raises(HTTPException) as exc:
            add_opt_history(client_id="c-1", body=OptHistoryCreate(
                event_type="Opting-in zu Privatkunde", from_classification="Privatkunde",
                to_classification="Professioneller Kunde", document_id="b",
                opt_out_criteria=_criteria()), db=db, current_user=user(db, "adv-1"))
        assert exc.value.detail["reason_code"] == "OPTING_TRANSITION_INVALID"
        entry = add_opt_history(client_id="c-1", body=OptHistoryCreate(
            from_classification="Privatkunde", to_classification="Professioneller Kunde",
            document_id="b", opt_out_criteria=_criteria()), db=db, current_user=user(db, "adv-1"))
        assert entry.event_type == "Opting-out zu Professionell"


def test_fidleg_event_values_are_in_the_schema_check_list():
    from h8_support import BACKEND_ROOT

    sql = (BACKEND_ROOT / "ares_schema.sql").read_text(encoding="utf-8")
    for value in ("Opting-out zu Professionell", "Opting-out zu Institutionell",
                  "Opting-in zu Privatkunde", "Opting-in zu Professionell"):
        assert f"'{value}'" in sql
