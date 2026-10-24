"""INFLOW-CERTAINTY-001: API/Schema/Migration/Monolith fuer die Zufluss-Gewissheit."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.wealth import WealthInflow  # noqa: E402
from test_vorsorge_transfer_guards import (  # noqa: E402,F401 - pytest fixtures
    _create_client,
    _create_position,
    advisor_user,
    auth_client,
    session_factory,
)

REVISION = "e5a1c7f3b9d2"
DOWN_REVISION = "e8a4c2f7d913"
MONOLITH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"


def _inflow_body(**overrides) -> dict:
    body = {
        "label": "Erbschaft", "source_type": "Erbschaft",
        "amount_rappen": 25_000_000, "expected_year": 2030,
    }
    body.update(overrides)
    return body


def test_default_is_sicher_and_unsicher_round_trips(auth_client, advisor_user):
    cid = _create_client(auth_client, advisor_user, "cert-1")
    default = auth_client.post(f"/clients/{cid}/wealth-inflows", json=_inflow_body())
    assert default.status_code == 201, default.text
    assert default.json()["certainty"] == "sicher"

    uncertain = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_body(label="Bonus", certainty="unsicher"),
    )
    assert uncertain.status_code == 201, uncertain.text
    assert uncertain.json()["certainty"] == "unsicher"

    # Partielles Update laesst die Gewissheit stehen; explizites Umschalten wirkt.
    inflow_id = uncertain.json()["id"]
    kept = auth_client.put(f"/wealth-inflows/{inflow_id}", json={"amount_rappen": 1_000_000})
    assert kept.status_code == 200, kept.text
    assert kept.json()["certainty"] == "unsicher"
    switched = auth_client.put(f"/wealth-inflows/{inflow_id}", json={"certainty": "sicher"})
    assert switched.json()["certainty"] == "sicher"

    invalid = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_body(certainty="vielleicht"),
    )
    assert invalid.status_code == 422


def test_linked_pension_withdrawal_is_always_sicher(auth_client, advisor_user):
    cid = _create_client(auth_client, advisor_user, "cert-2")
    pos_id = _create_position(auth_client, cid)
    rejected = auth_client.post(
        f"/clients/{cid}/wealth-inflows",
        json=_inflow_body(label="3a-Bezug", linked_position_id=pos_id, certainty="unsicher"),
    )
    assert rejected.status_code == 422
    assert "immer" in rejected.text

    # Ein unsicherer Zufluss darf nicht nachtraeglich verknuepft werden.
    free = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_body(certainty="unsicher"),
    )
    relink = auth_client.put(
        f"/wealth-inflows/{free.json()['id']}", json={"linked_position_id": pos_id},
    )
    assert relink.status_code == 422


def test_legacy_null_row_is_listed_as_sicher(auth_client, advisor_user, session_factory):
    cid = _create_client(auth_client, advisor_user, "cert-3")
    created = auth_client.post(f"/clients/{cid}/wealth-inflows", json=_inflow_body())
    with session_factory() as session:
        session.execute(
            WealthInflow.__table__.update()
            .where(WealthInflow.id == created.json()["id"])
            .values(certainty=None)
        )
        session.commit()
    listed = auth_client.get(f"/clients/{cid}/wealth-inflows").json()
    assert [row["certainty"] for row in listed] == ["sicher"]


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_migration_is_in_chain_on_previous_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_migration_adds_nullable_column_with_sicher_default_and_downgrades(tmp_path):
    from alembic import command

    db_path = tmp_path / "certainty.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db_path)) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(wealth_inflows)")}
        assert "certainty" not in cols
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO wealth_inflows (id, client_id, label, source_type, amount_rappen, "
            "expected_year, is_recurring, value_mode, is_active, created_at, updated_at) "
            "VALUES ('wi-old','c','Alt','Bonus',100,2030,0,'nominal',1,'t','t')"
        )
        conn.commit()
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(str(db_path)) as conn:
        info = {row[1]: row for row in conn.execute("PRAGMA table_info(wealth_inflows)")}
        assert info["certainty"][3] == 0  # nullable
        assert conn.execute(
            "SELECT certainty FROM wealth_inflows WHERE id='wi-old'"
        ).fetchone() == ("sicher",)
    command.downgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db_path)) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(wealth_inflows)")}
    assert "certainty" not in cols
    create_engine(db_url).dispose()


def test_runtime_patch_adds_certainty_column(tmp_path, monkeypatch):
    import database as db_module
    from database import Base

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(
        db_path=db_path, schema_path=BACKEND_ROOT / "ares_schema.sql",
    )
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("ALTER TABLE wealth_inflows DROP COLUMN certainty")
        conn.commit()
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(str(db_path)) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(wealth_inflows)")}
    assert "certainty" in cols


def test_monolith_inflow_dialog_has_certainty_choice_and_hint():
    html = MONOLITH.read_text(encoding="utf-8")
    assert 'id="awi-certainty"' in html
    assert '<option value="unsicher">' in html
    assert "nicht eingerechnet (unsicher)" in html
    assert "Info-Sensitivität „mit Zufluss“" in html
    # Speichern sendet die Gewissheit; verknuepfter Bezug erzwingt 'sicher'.
    assert "payload.certainty=(linkedPositionId||certainty!=='unsicher')?'sicher':'unsicher';" in html
    assert "if(isLinked)certaintySel.value='sicher';certaintySel.disabled=isLinked;" in html
    # Bearbeiten laedt den gespeicherten Wert, Neu setzt den Default.
    assert "setSelectValue('awi-certainty',inflow.certainty==='unsicher'?'unsicher':'sicher');" in html
    assert "setSelectValue('awi-certainty','sicher');" in html
