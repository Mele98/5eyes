"""L2d / N-938-01: die Massnahme eines Interessenkonflikts ist eine Kategorie.

Befund (H-192-Pruefung): ``mitigation_action`` war nur im Desktop-Schema eine
CHECK-Liste. Auf Postgres und in der API war es Freitext (Classic: freies
Textfeld); er stand unversiegelt in der Zeile und alt/neu im Audit-Log.

Fix (CTO-Entscheid): eine Liste ueberall -- API-``Literal``, ORM-CHECK,
Postgres-CHECK (Alembic f3c8a1d6b2e4, fail-closed bei Altwerten), Classic-
Auswahlliste (conflict-mitigation.js). Audit-Log nur Kategorie bzw. Hinweis.
"""
from __future__ import annotations

import ast
import re
import sys
import typing
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import Req, alembic_cfg, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402

from models.review import CONFLICT_MITIGATION_ACTIONS  # noqa: E402
from routers import review as api  # noqa: E402
from schemas.review import (  # noqa: E402
    ConflictDisclosureCreate, ConflictMitigateRequest, ConflictMitigationAction,
)

BACKEND_ROOT = TESTS_ROOT.parent
FRONTEND = BACKEND_ROOT.parent / "ares-desktop" / "frontend"
FREE_TEXT = "Retrozession wird vollumfaenglich erstattet (fiktiv)"


def _schema_check_list() -> tuple[str, ...]:
    sql = (BACKEND_ROOT / "ares_schema.sql").read_text(encoding="utf-8")
    block = re.search(r"mitigation_action\s+TEXT CHECK\(mitigation_action IN \((.*?)\)\)", sql, re.S)
    assert block, "CHECK-Liste fuer mitigation_action im Desktop-Schema nicht gefunden"
    return tuple(re.findall(r"'([^']+)'", block.group(1)))


def _migration_actions() -> tuple[str, ...]:
    path = next((BACKEND_ROOT / "alembic" / "versions").glob("f3c8a1d6b2e4_*.py"))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "ACTIONS":
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("ACTIONS fehlt in f3c8a1d6b2e4")


def _js_actions() -> tuple[str, ...]:
    src = (FRONTEND / "conflict-mitigation.js").read_text(encoding="utf-8")
    block = re.search(r"CONFLICT_MITIGATION_ACTIONS=\[(.*?)\]", src)
    assert block
    return tuple(re.findall(r"'([^']+)'", block.group(1)))


def test_one_category_list_everywhere():
    """Desktop-CHECK ist die Quelle (nichts erfunden); API, ORM, Migration und
    Classic-Maske fuehren genau dieselbe Liste."""
    expected = _schema_check_list()
    assert len(expected) == 4
    assert tuple(typing.get_args(ConflictMitigationAction)) == expected
    assert CONFLICT_MITIGATION_ACTIONS == expected
    assert _migration_actions() == expected
    assert _js_actions() == expected


def test_classic_mask_offers_a_select_not_a_free_text_field():
    from tests.monolith_source import read_monolith_bundle

    html = read_monolith_bundle()
    assert '<select class="fi" id="nco-mitigation"></select>' in html
    assert 'id="nco-mitigation" placeholder' not in html
    # Das Bundle zieht ausgelagerte Skripte ein: die Maske laedt die Liste.
    assert (FRONTEND / "conflict-mitigation.js").read_text(encoding="utf-8").strip() in html


@pytest.mark.parametrize("value", [FREE_TEXT, "", "ok", "weitergabe an kunden"])
def test_api_rejects_free_text_on_create_and_mitigate(value):
    with pytest.raises(ValidationError):
        ConflictMitigateRequest(mitigation_action=value)
    with pytest.raises(ValidationError):
        ConflictDisclosureCreate(conflict_type="Konzernverbindung", description="x", mitigation_action=value)


def test_api_accepts_each_category_and_none_on_create():
    for value in CONFLICT_MITIGATION_ACTIONS:
        assert ConflictMitigateRequest(mitigation_action=value).mitigation_action == value
    assert ConflictDisclosureCreate(conflict_type="Konzernverbindung", description="x").mitigation_action is None


def _audit_rows(db):
    return db.execute(text(
        "SELECT old_value, new_value FROM audit_log WHERE field_name = 'mitigation_action' ORDER BY sequence"
    )).all()


def test_audit_log_writes_categories_only_never_free_text(sf):
    with sf() as db:
        created = api.create_conflict(
            mandate_id="m-1",
            body=ConflictDisclosureCreate(conflict_type="Sonstiger Interessenkonflikt", description="Sachverhalt (fiktiv)",
                                          reimbursed_to_client=False),
            request=Req(), db=db, current_user=user(db, "adv-1"))
        for value in ("Ablehnung", "Strukturelle Massnahme"):
            api.mitigate_conflict(mandate_id="m-1", conflict_id=created["id"],
                                  body=ConflictMitigateRequest(mitigation_action=value),
                                  request=Req(), db=db, current_user=user(db, "adv-1"))
        assert _audit_rows(db) == [(None, "Ablehnung"), ("Ablehnung", "Strukturelle Massnahme")]


def test_legacy_free_text_value_never_reaches_the_audit_log(sf):
    """Altwert ausserhalb der Liste (z. B. Postgres vor L2d): im Audit nur der
    Hinweis «geändert», nie der Text. (Die ORM-CHECK verhindert neue solche
    Werte; der Altwert wird hier am CHECK vorbei gesetzt.)"""
    with sf() as db:
        created = api.create_conflict(
            mandate_id="m-1",
            body=ConflictDisclosureCreate(conflict_type="Sonstiger Interessenkonflikt", description="Sachverhalt (fiktiv)",
                                          reimbursed_to_client=False),
            request=Req(), db=db, current_user=user(db, "adv-1"))
        db.execute(text("PRAGMA ignore_check_constraints = ON"))
        db.execute(text("UPDATE conflict_of_interest_disclosures SET mitigation_action = :v WHERE id = :i"),
                   {"v": FREE_TEXT, "i": created["id"]})
        db.execute(text("PRAGMA ignore_check_constraints = OFF"))
        db.commit()
        api.mitigate_conflict(mandate_id="m-1", conflict_id=created["id"],
                              body=ConflictMitigateRequest(mitigation_action="Weitergabe an Kunden"),
                              request=Req(), db=db, current_user=user(db, "adv-1"))
        rows = _audit_rows(db)
        assert rows[-1][1] == "Weitergabe an Kunden"
        assert rows[-1][0].startswith("geändert")
        dump = " ".join(str(v) for r in db.execute(text("SELECT * FROM audit_log")).all() for v in r)
        assert FREE_TEXT not in dump


def test_orm_schema_rejects_free_text(sf):
    import sqlalchemy

    with sf() as db:
        created = api.create_conflict(
            mandate_id="m-1",
            body=ConflictDisclosureCreate(conflict_type="Sonstiger Interessenkonflikt", description="Sachverhalt (fiktiv)",
                                          reimbursed_to_client=False),
            request=Req(), db=db, current_user=user(db, "adv-1"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.execute(text("UPDATE conflict_of_interest_disclosures SET mitigation_action = :v WHERE id = :i"),
                       {"v": FREE_TEXT, "i": created["id"]})


def test_alembic_head_is_linear_and_fails_closed_on_legacy_free_text(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'l2d.db'}"
    script = ScriptDirectory.from_config(alembic_cfg(url))
    assert script.get_heads() == ["d3b7e1f9a5c2"]  # K3 haengt an L2d
    assert script.get_revision("f3c8a1d6b2e4").down_revision == "e2b7c4d9a1f3"
    command.upgrade(alembic_cfg(url), "e2b7c4d9a1f3")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO conflict_of_interest_disclosures (id, mandate_id, conflict_type, description, "
                "disclosed_to_client, client_acknowledged, reimbursed_to_client, mitigation_action, disclosed_by, created_at, updated_at) "
                "VALUES ('coi-legacy', 'm', 'Konzernverbindung', 'x', 0, 0, 0, :v, 'u', 'x', 'x')"), {"v": FREE_TEXT})
        with pytest.raises(RuntimeError, match="coi-legacy") as exc:
            command.upgrade(alembic_cfg(url), "f3c8a1d6b2e4")
        assert FREE_TEXT not in str(exc.value)  # Meldung nennt IDs, nie den Text
        with engine.begin() as conn:
            assert conn.execute(text(
                "SELECT mitigation_action FROM conflict_of_interest_disclosures")).scalar() == FREE_TEXT  # nichts geaendert
            conn.execute(text("UPDATE conflict_of_interest_disclosures SET mitigation_action = 'Ablehnung'"))
        command.upgrade(alembic_cfg(url), "f3c8a1d6b2e4")  # bereinigt -> laeuft
        command.downgrade(alembic_cfg(url), "e2b7c4d9a1f3")
        command.upgrade(alembic_cfg(url), "f3c8a1d6b2e4")
    finally:
        engine.dispose()


def test_alembic_postgres_offline_sql_adds_the_check():
    import io

    from alembic import command

    buf = io.StringIO()
    command.upgrade(alembic_cfg("postgresql://u:p@localhost/db", buf), "e2b7c4d9a1f3:f3c8a1d6b2e4", sql=True)
    sql = buf.getvalue()
    assert "ck_coi_mitigation_action" in sql
    for value in CONFLICT_MITIGATION_ACTIONS:
        assert f"'{value}'" in sql
