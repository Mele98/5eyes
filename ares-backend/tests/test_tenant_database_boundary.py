"""PG-002 -- database tenant boundary for wealth positions and inflows.

Closure review of PR #666: the router guards the Vorsorge link, but below it
(raw SQL, ORM, imports, workers) an inflow of tenant A could be linked to a
position of tenant B, and both tables were invisible to the PostgreSQL RLS
plan (no local ``tenant_id``).

1. Audit reproducer, adopted without xfail: both tables are in the RLS plan;
   a direct ORM write of the cross-tenant link fails with IntegrityError.
2. Complete, versioned scope inventory: every ORM table is classified; an
   unclassified/contradicting table makes this test red.
3. Same tenant but other client, dangling and soft-deleted targets, raw SQL,
   relink, unchanged legacy link, moving a linked position, tenant spoofing.
4. Migration ``94089093281c`` along the chain (never "is head"): backfill,
   triggers, abort on invalid legacy links, downgrade.

The live PostgreSQL contract (RLS, FORCE, composite FK, triggers under a
non-owner role) is in ``tests/test_postgres_wealth_tenant_boundary_live.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, text
from sqlalchemy.exc import IntegrityError

from database import Base
from models.clients import Client
from models.tenant import Tenant
from models.users import User
from models.wealth import WealthInflow, WealthPosition
from services import tenant_scope_inventory as inventory
from services.postgres_rls import import_tenant_models, tenant_scoped_table_names
from tests.test_risk_capacity_plausibility import (
    NOW,
    session_factory,  # noqa: F401 - pytest fixture re-export
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_REVISION = "94089093281c"
MIGRATION_DOWN_REVISION = "2cbc77503cd9"


def _user(uid: str, tenant_id: str) -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid, role="advisor",
        is_active=1, tenant_id=tenant_id, created_at=NOW, updated_at=NOW,
    )


def _client(cid: str, advisor_id: str, tenant_id: str) -> Client:
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Tenant",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=advisor_id, tenant_id=tenant_id,
        created_at=NOW, updated_at=NOW,
    )


def _position(pid: str, client_id: str, **extra) -> WealthPosition:
    values = dict(
        id=pid, client_id=client_id, label=pid, position_type="Vorsorge",
        assignment="Anderes Vermögen", pension_type="Säule 3a",
        current_value_rappen=10_000_000, currency="CHF", is_active=1,
        created_at=NOW, updated_at=NOW,
    )
    values.update(extra)
    return WealthPosition(**values)


def _inflow(iid: str, client_id: str, **extra) -> WealthInflow:
    values = dict(
        id=iid, client_id=client_id, label=iid, source_type="Andere",
        amount_rappen=5_000_000, expected_year=2030, is_recurring=0,
        frequency="einmalig", value_mode="nominal", is_active=0,
        created_at=NOW, updated_at=NOW,
    )
    values.update(extra)
    return WealthInflow(**values)


def _seed_two_tenants(session) -> None:
    session.add_all([
        Tenant(id="tenant-a", display_name="A", slug="tenant-a", created_at=NOW, updated_at=NOW),
        Tenant(id="tenant-b", display_name="B", slug="tenant-b", created_at=NOW, updated_at=NOW),
        _user("advisor-a", "tenant-a"),
        _user("advisor-b", "tenant-b"),
    ])
    session.flush()
    session.add_all([
        _client("client-a", "advisor-a", "tenant-a"),
        _client("client-a2", "advisor-a", "tenant-a"),
        _client("client-b", "advisor-b", "tenant-b"),
    ])
    session.flush()


# --- 1. audit reproducer (adopted without xfail) ------------------------------


def test_new_sensitive_wealth_tables_are_in_tenant_rls_plan():
    """New pension/link fields must not live on RLS-invisible parent tables."""
    scoped = set(tenant_scoped_table_names())
    assert {"wealth_positions", "wealth_inflows"}.issubset(scoped)


def test_cross_tenant_inflow_position_link_has_database_constraint(session_factory):  # noqa: F811
    """A raw/internal write must not bypass the router's same-client check."""
    with session_factory() as session:
        _seed_two_tenants(session)
        session.add(_position("position-b", "client-b"))
        session.add(_inflow("inflow-a", "client-a"))
        session.commit()

        session.get(WealthInflow, "inflow-a").linked_position_id = "position-b"
        with pytest.raises(IntegrityError):
            session.commit()


# --- 2. scope inventory --------------------------------------------------------


def test_every_orm_table_is_classified_consistently():
    import_tenant_models()
    assert inventory.inventory_problems(Base.metadata.tables) == []
    assert set(tenant_scoped_table_names()) == inventory.rls_planned_tables()
    assert inventory.INVENTORY_VERSION


def test_inventory_rejects_unclassified_and_contradicting_tables():
    import_tenant_models()
    probe = MetaData()
    Table("new_secret_table", probe, Column("id", String, primary_key=True), Column("client_id", String))
    tables = dict(Base.metadata.tables)
    tables.update(probe.tables)
    assert "unklassifizierte Tabelle: new_secret_table" in inventory.inventory_problems(tables)

    other = MetaData()
    Table("cashflows", other, Column("id", String, primary_key=True), Column("tenant_id", String))
    tables = dict(Base.metadata.tables)
    tables["cashflows"] = other.tables["cashflows"]
    assert any("cashflows: hat tenant_id" in p for p in inventory.inventory_problems(tables))


# --- 3. SQLite invariants ------------------------------------------------------


def test_tenant_id_is_derived_from_the_client(session_factory):  # noqa: F811
    with session_factory() as session:
        _seed_two_tenants(session)
        session.add_all([_position("pos-b", "client-b"), _inflow("in-b", "client-b")])
        session.commit()
        assert session.get(WealthPosition, "pos-b").tenant_id == "tenant-b"
        assert session.get(WealthInflow, "in-b").tenant_id == "tenant-b"
        # Raw SQL without tenant_id: filled from the client by the database.
        _raw_insert(session.connection(), "wealth_positions", id="raw-a", client_id="client-a")
        session.commit()
        assert session.execute(text("SELECT tenant_id FROM wealth_positions WHERE id = 'raw-a'")).scalar() == "tenant-a"


def test_spoofed_tenant_id_is_rejected_by_the_database(session_factory):  # noqa: F811
    with session_factory() as session:
        _seed_two_tenants(session)
        session.commit()
        with pytest.raises(IntegrityError):
            _raw_insert(session.connection(), "wealth_positions", id="spoof", client_id="client-a", tenant_id="tenant-b")
        session.rollback()
        # The ORM always overwrites a request value with the client's tenant.
        session.add(_position("orm-spoof", "client-a", tenant_id="tenant-b"))
        session.commit()
        assert session.get(WealthPosition, "orm-spoof").tenant_id == "tenant-a"


@pytest.mark.parametrize(
    "target",
    ["pos-a2", "missing-position", "pos-a-deleted"],
    ids=["same-tenant-other-client", "dangling", "soft-deleted"],
)
@pytest.mark.parametrize("inflow_active", [0, 1], ids=["inactive", "active"])
def test_link_outside_own_live_positions_is_rejected(session_factory, target, inflow_active):  # noqa: F811
    with session_factory() as session:
        _seed_two_tenants(session)
        session.add_all([
            _position("pos-a2", "client-a2"),
            _position("pos-a-deleted", "client-a", deleted_at=NOW),
            _inflow("in-a", "client-a", is_active=inflow_active),
        ])
        session.commit()
        session.get(WealthInflow, "in-a").linked_position_id = target
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        # Same contract on INSERT and through raw SQL.
        with pytest.raises(IntegrityError):
            _raw_insert(session.connection(), "wealth_inflows", id="raw-in", client_id="client-a",
                        is_active=inflow_active, linked_position_id=target)
        session.rollback()


def test_own_link_relink_unlink_and_unchanged_legacy_link(session_factory):  # noqa: F811
    with session_factory() as session:
        _seed_two_tenants(session)
        session.add_all([
            _position("pos-a1", "client-a"),
            _position("pos-a3", "client-a"),
            _inflow("in-a", "client-a", linked_position_id="pos-a1", is_active=1),
        ])
        session.commit()
        inflow = session.get(WealthInflow, "in-a")
        inflow.linked_position_id = "pos-a3"  # relink within the client
        session.commit()
        inflow.is_active = 0  # deactivate
        session.commit()
        # Source later soft-deleted: an unchanged legacy link stays editable.
        session.get(WealthPosition, "pos-a3").deleted_at = NOW
        session.commit()
        inflow.label = "renamed"
        inflow.is_active = 1
        session.commit()
        inflow.linked_position_id = None  # unlink
        session.commit()
        assert session.get(WealthInflow, "in-a").linked_position_id is None


def test_linked_position_cannot_move_to_another_client(session_factory):  # noqa: F811
    with session_factory() as session:
        _seed_two_tenants(session)
        session.add_all([
            _position("pos-a1", "client-a"),
            _inflow("in-a", "client-a", linked_position_id="pos-a1"),
        ])
        session.commit()
        session.get(WealthPosition, "pos-a1").client_id = "client-a2"
        with pytest.raises(IntegrityError):
            session.commit()


# --- 4. migration along the chain ---------------------------------------------


def _alembic_config(database_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


_RAW_DEFAULTS = {
    "users": dict(username="adv", password_hash="h", full_name="Adv", role="advisor", is_active=1,
                  totp_enabled=0, must_change_password=0),
    "tenants": dict(hosting_tier="tier1", license_status="trial", default_retrocession_reimbursement=0,
                    discretionary_management_licensed=1, is_active=1),
    "clients": dict(country_of_residence="CH", language="DE", household_type="Einzelperson",
                    client_classification="Privatkunde", is_professional_opt_out=0, is_qualified_investor=0,
                    advisor_id="adv", first_name="F", last_name="L"),
    "wealth_positions": dict(label="x", position_type="Vorsorge", assignment="Anderes Vermögen",
                             current_value_rappen=1, currency="CHF", alloc_equities_bps=0, alloc_bonds_bps=0,
                             alloc_real_estate_bps=0, alloc_liquidity_bps=0, alloc_alternatives_bps=0,
                             property_rental_income_rappen=0, pension_wef_possible=0,
                             mortgage_amortization_rappen=0, is_available_for_goal_funding=0, is_active=1),
    "wealth_inflows": dict(label="x", source_type="Andere", amount_rappen=1, expected_year=2030,
                           is_recurring=0, value_mode="nominal", is_active=1),
}


def _raw_insert(conn, table: str, **values) -> None:
    row = {**_RAW_DEFAULTS[table], "created_at": NOW, "updated_at": NOW, **values}
    columns = ", ".join(row)
    params = ", ".join(f":{key}" for key in row)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), row)


def _seed_pre_migration(engine, *, bad_link: bool) -> None:
    with engine.begin() as conn:
        for tid in ("t-a", "t-b"):
            _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
        _raw_insert(conn, "users", id="adv", tenant_id="t-a")
        for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
            _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
        for pid, cid in (("p-a", "c-a"), ("p-b", "c-b")):
            _raw_insert(conn, "wealth_positions", id=pid, client_id=cid)
        _raw_insert(conn, "wealth_inflows", id="i-a", client_id="c-a", linked_position_id="p-b" if bad_link else "p-a")


def test_migration_is_in_the_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert MIGRATION_REVISION in chain
    assert script.get_revision(MIGRATION_REVISION).down_revision == MIGRATION_DOWN_REVISION


def test_migration_backfills_installs_triggers_and_downgrades(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'chain.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        _seed_pre_migration(engine, bad_link=False)
        command.upgrade(cfg, MIGRATION_REVISION)
        with engine.connect() as conn:
            rows = dict(conn.execute(text("SELECT id, tenant_id FROM wealth_positions")).all())
            assert rows == {"p-a": "t-a", "p-b": "t-b"}
            assert conn.execute(text("SELECT tenant_id FROM wealth_inflows WHERE id = 'i-a'")).scalar() == "t-a"
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("UPDATE wealth_inflows SET linked_position_id = 'p-b' WHERE id = 'i-a'"))
        command.downgrade(cfg, MIGRATION_DOWN_REVISION)
        with engine.connect() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(wealth_inflows)")).all()}
            triggers = conn.execute(text(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_wealth_%'"
            )).scalar()
        assert "tenant_id" not in columns and triggers == 0
        command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        engine.dispose()


def test_migration_aborts_on_cross_client_legacy_link(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'chain_bad.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        _seed_pre_migration(engine, bad_link=True)
        with pytest.raises(RuntimeError, match="i-a"):
            command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        engine.dispose()


def test_sqlite_runtime_patch_backfills_legacy_desktop_db_and_reports_bad_links(tmp_path, caplog):
    from services.wealth_tenant_boundary import ensure_sqlite_wealth_tenant_boundary

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            for table in ("wealth_inflows", "wealth_positions"):
                for (name,) in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :t"
                ), {"t": table}).all():
                    conn.execute(text(f"DROP TRIGGER {name}"))
        _seed_pre_migration(engine, bad_link=True)
        with engine.begin() as conn:
            conn.execute(text("UPDATE wealth_positions SET tenant_id = NULL"))
        with caplog.at_level("ERROR"):
            assert ensure_sqlite_wealth_tenant_boundary(engine) == ["i-a"]
        assert "i-a" in caplog.text
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT id, tenant_id FROM wealth_positions")).all()) == {
                "p-a": "t-a", "p-b": "t-b",
            }
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _raw_insert(conn, "wealth_inflows", id="i-new", client_id="c-a", linked_position_id="p-b")
    finally:
        engine.dispose()
