"""Database-level race protection for versioned current anchors.

The SQLite reference schema has always expressed these invariants as partial
unique indexes.  SQLite databases created from ORM metadata and PostgreSQL
databases created by Alembic must enforce the same logical scopes:

* one live/current RiskAssessment per mandate;
* one live/current TargetAllocation per mandate;
* one current OptimizerPolicy globally, matching the runtime selector.

OptimizerPolicy intentionally has no tenant/jurisdiction/deleted-at columns in
the current domain model, and every runtime selector expects exactly one active
row.  A unique partial index on ``is_current`` therefore protects the actual
global-singleton contract without inventing a jurisdiction or tenant scope.
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_current_anchor_unique_indexes  # noqa: E402
import models.allocation  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.users import User  # noqa: E402
import routers.allocation as allocation_router  # noqa: E402
from routers.allocation import (  # noqa: E402
    activate_optimizer_policy,
    create_optimizer_policy,
    create_target_allocation,
)
from routers.profiling import create_risk_assessment  # noqa: E402
from schemas.allocation import OptimizerPolicyCreate, TargetAllocationCreate  # noqa: E402
from schemas.profiling import RiskAssessmentCreate  # noqa: E402
from test_runtime_contracts import complete_risk_questionnaire_answers  # noqa: E402


INDEX_SPECS = {
    "risk_assessments": {
        "name": "ux_risk_one_current",
        "columns": ["mandate_id"],
        "where": "is_current = 1 AND deleted_at IS NULL",
    },
    "target_allocations": {
        "name": "ux_target_alloc_one_current",
        "columns": ["mandate_id"],
        "where": "is_current = 1 AND deleted_at IS NULL",
    },
    "optimizer_policies": {
        "name": "ux_optimizer_one_current",
        "columns": ["is_current"],
        "where": "is_current = 1",
    },
}


def _normalise_sql(value: object) -> str:
    return " ".join(str(value).lower().split())


def _alembic_config(database_url: str, *, output_buffer=None):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(
        str(BACKEND_ROOT / "alembic.ini"), output_buffer=output_buffer
    )
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _index_by_name(table_name: str, index_name: str):
    table = Base.metadata.tables[table_name]
    return next((index for index in table.indexes if index.name == index_name), None)


@pytest.mark.parametrize("table_name,spec", INDEX_SPECS.items())
def test_orm_metadata_matches_reference_partial_unique_index(table_name, spec):
    index = _index_by_name(table_name, spec["name"])

    assert index is not None, f"ORM-Index {spec['name']} fehlt"
    assert index.unique is True
    assert [column.name for column in index.columns] == spec["columns"]
    assert _normalise_sql(index.dialect_options["sqlite"]["where"]) == _normalise_sql(
        spec["where"]
    )
    assert _normalise_sql(
        index.dialect_options["postgresql"]["where"]
    ) == _normalise_sql(spec["where"])

    raw_schema = (BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql").read_text(
        encoding="utf-8"
    )
    raw_pattern = re.compile(
        rf"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+{spec['name']}\s+"
        rf"ON\s+{table_name}\s*\(\s*{spec['columns'][0]}\s*\)\s+"
        rf"WHERE\s+{re.escape(spec['where'])}\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    assert raw_pattern.search(raw_schema), (
        f"SQLite-Rohschema und ORM sind fuer {spec['name']} nicht deckungsgleich"
    )


def test_alembic_upgrade_and_downgrade_manage_current_anchor_indexes(tmp_path):
    from alembic import command

    db_file = tmp_path / "current_anchor_indexes.db"
    cfg = _alembic_config(f"sqlite:///{db_file}")

    command.upgrade(cfg, "b6a7d9124e53")
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        before = {
            table_name: {item["name"] for item in inspect(engine).get_indexes(table_name)}
            for table_name in INDEX_SPECS
        }
        assert all(spec["name"] not in before[table] for table, spec in INDEX_SPECS.items())

        command.upgrade(cfg, "head")
        after = {
            table_name: {
                item["name"]: item for item in inspect(engine).get_indexes(table_name)
            }
            for table_name in INDEX_SPECS
        }
        for table_name, spec in INDEX_SPECS.items():
            migrated = after[table_name][spec["name"]]
            assert migrated["unique"] == 1
            assert migrated["column_names"] == spec["columns"]
            assert _normalise_sql(
                migrated["dialect_options"]["sqlite_where"]
            ) == _normalise_sql(spec["where"])

        # Exercise the upgraded schema itself (not Base.metadata.create_all)
        # so an index that was only declared in the ORM cannot create a false
        # green migration test.
        with engine.begin() as connection:
            for table, first, second in (
                (
                    RiskAssessment.__table__,
                    _risk_row("migrated-risk-1", mandate_id="migrated-mandate"),
                    _risk_row("migrated-risk-2", mandate_id="migrated-mandate"),
                ),
                (
                    TargetAllocation.__table__,
                    _allocation_row(
                        "migrated-target-1", mandate_id="migrated-mandate"
                    ),
                    _allocation_row(
                        "migrated-target-2", mandate_id="migrated-mandate"
                    ),
                ),
                (
                    OptimizerPolicy.__table__,
                    _policy_row("migrated-policy-1", policy_name="One"),
                    _policy_row("migrated-policy-2", policy_name="Two"),
                ),
            ):
                connection.execute(table.insert(), first)
                with pytest.raises(IntegrityError):
                    connection.execute(table.insert(), second)

        command.downgrade(cfg, "b6a7d9124e53")
        downgraded = {
            table_name: {item["name"] for item in inspect(engine).get_indexes(table_name)}
            for table_name in INDEX_SPECS
        }
        assert all(
            spec["name"] not in downgraded[table]
            for table, spec in INDEX_SPECS.items()
        )
    finally:
        engine.dispose()


def test_alembic_head_emits_postgres_partial_unique_indexes():
    from alembic import command

    output = StringIO()
    command.upgrade(
        _alembic_config(
            "postgresql://migration-test:unused@localhost/unused",
            output_buffer=output,
        ),
        "head",
        sql=True,
    )
    ddl = _normalise_sql(output.getvalue())

    for table_name, spec in INDEX_SPECS.items():
        expected = _normalise_sql(
            f"CREATE UNIQUE INDEX {spec['name']} ON {table_name} "
            f"({spec['columns'][0]}) WHERE {spec['where']}"
        )
        assert expected in ddl, f"PostgreSQL-DDL fuer {spec['name']} fehlt"


def test_sqlite_legacy_policy_index_is_repaired_idempotently(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'legacy-policy-index.db'}"
    engine = create_engine(db_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE optimizer_policies ("
                "id TEXT PRIMARY KEY, policy_name TEXT NOT NULL, "
                "is_current INTEGER NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX ux_optimizer_one_current "
                "ON optimizer_policies(policy_name) WHERE is_current = 1"
            )
            connection.exec_driver_sql(
                "INSERT INTO optimizer_policies VALUES ('old', 'Old', 1)"
            )

        ensure_current_anchor_unique_indexes(engine)
        ensure_current_anchor_unique_indexes(engine)

        migrated = {
            item["name"]: item
            for item in inspect(engine).get_indexes("optimizer_policies")
        }["ux_optimizer_one_current"]
        assert migrated["unique"] == 1
        assert migrated["column_names"] == ["is_current"]
        assert _normalise_sql(
            migrated["dialect_options"]["sqlite_where"]
        ) == "is_current = 1"

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO optimizer_policies VALUES ('new', 'New', 1)"
                )
    finally:
        engine.dispose()


def test_sqlite_legacy_index_repair_fails_closed_on_ambiguous_current_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ambiguous-policy-index.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE optimizer_policies ("
                "id TEXT PRIMARY KEY, policy_name TEXT NOT NULL, "
                "is_current INTEGER NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX ux_optimizer_one_current "
                "ON optimizer_policies(policy_name) WHERE is_current = 1"
            )
            connection.exec_driver_sql(
                "INSERT INTO optimizer_policies VALUES "
                "('one', 'One', 1), ('two', 'Two', 1)"
            )

        with pytest.raises(IntegrityError):
            ensure_current_anchor_unique_indexes(engine)

        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM optimizer_policies WHERE is_current = 1"
            ).scalar_one() == 2
    finally:
        engine.dispose()


def _risk_row(row_id: str, *, mandate_id: str, is_current: int = 1, deleted_at=None):
    return {
        "id": row_id,
        "mandate_id": mandate_id,
        "version": 1,
        "is_current": is_current,
        "valid_from": "2026-08-20",
        "q_income_points": 1,
        "q_obligations_points": 1,
        "q_savings_points": 1,
        "q_wealth_points": 1,
        "risk_capacity_total": 4,
        "risk_capacity_profile": "Ausgewogen",
        "investment_horizon_years": 10,
        "investment_horizon_label": "Lang",
        "risk_capacity_score_x10": 30,
        "q_investment_goal_points": 1,
        "q_risk_preference_points": 1,
        "q_risk_behavior_points": 1,
        "risk_willingness_total": 3,
        "risk_willingness_profile": "Ausgewogen",
        "risk_willingness_score_x10": 30,
        "final_score_x10": 30,
        "final_profile": "Ausgewogen",
        "is_overridden": 0,
        "assessed_at": "2026-08-20T00:00:00Z",
        "assessed_by": "user-1",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z",
        "deleted_at": deleted_at,
    }


def _allocation_row(
    row_id: str, *, mandate_id: str, is_current: int = 1, deleted_at=None
):
    return {
        "id": row_id,
        "mandate_id": mandate_id,
        "version": 1,
        "is_current": is_current,
        "target_equities_bps": 2000,
        "target_bonds_bps": 2000,
        "target_real_estate_bps": 2000,
        "target_alternatives_bps": 2000,
        "target_liquidity_bps": 2000,
        "band_equities_min_bps": 0,
        "band_equities_max_bps": 10000,
        "band_bonds_min_bps": 0,
        "band_bonds_max_bps": 10000,
        "band_real_estate_min_bps": 0,
        "band_real_estate_max_bps": 10000,
        "band_alternatives_min_bps": 0,
        "band_alternatives_max_bps": 10000,
        "band_liquidity_min_bps": 0,
        "band_liquidity_max_bps": 10000,
        "policy_id": "policy-1",
        "set_by": "user-1",
        "set_at": "2026-08-20T00:00:00Z",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z",
        "deleted_at": deleted_at,
    }


def _policy_row(row_id: str, *, policy_name: str, is_current: int = 1):
    return {
        "id": row_id,
        "policy_name": policy_name,
        "version": 1,
        "is_current": is_current,
        "valid_from": "2026-08-20",
        "optimizer_engine": "goal_based_v1",
        "max_real_estate_bps": 2000,
        "max_alternatives_bps": 1000,
        "min_liquidity_bps": 0,
        "allow_other_assets_for_goals": 1,
        "created_by": "user-1",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z",
    }


def _request_stub():
    return SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


def _seed_advisor_and_mandate(engine) -> None:
    now = "2026-08-20T00:00:00Z"
    with Session(engine) as session:
        session.add_all(
            [
                User(
                    id="advisor-anchor",
                    username="advisor-anchor",
                    password_hash="x",
                    full_name="Anchor Advisor",
                    role="admin",
                    is_active=1,
                    created_at=now,
                    updated_at=now,
                ),
                Client(
                    id="client-anchor",
                    client_number="ANCHOR-1",
                    first_name="Anchor",
                    last_name="Client",
                    country_of_residence="CH",
                    language="DE",
                    household_type="Einzelperson",
                    client_classification="Privatkunde",
                    is_professional_opt_out=0,
                    is_qualified_investor=0,
                    advisor_id="advisor-anchor",
                    created_at=now,
                    updated_at=now,
                ),
                Mandate(
                    id="mandate-anchor",
                    client_id="client-anchor",
                    mandate_number="ANCHOR-M-1",
                    mandate_type="Anlageberatung",
                    status="Aktiv",
                    base_currency="CHF",
                    advisory_language="DE",
                    opened_at="2026-08-20",
                    investment_universe="Standard",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()


def _risk_payload() -> RiskAssessmentCreate:
    return RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=complete_risk_questionnaire_answers(),
    )


def _target_payload(policy_id: str) -> TargetAllocationCreate:
    return TargetAllocationCreate(
        target_equities_bps=6000,
        target_bonds_bps=3000,
        target_real_estate_bps=0,
        target_alternatives_bps=0,
        target_liquidity_bps=1000,
        band_equities_min_bps=5000,
        band_equities_max_bps=7000,
        band_bonds_min_bps=2000,
        band_bonds_max_bps=4000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=1000,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=1000,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=2000,
        policy_id=policy_id,
    )


@pytest.fixture
def orm_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "table,first,second",
    [
        (
            RiskAssessment.__table__,
            _risk_row("risk-1", mandate_id="mandate-1"),
            _risk_row("risk-2", mandate_id="mandate-1"),
        ),
        (
            TargetAllocation.__table__,
            _allocation_row("target-1", mandate_id="mandate-1"),
            _allocation_row("target-2", mandate_id="mandate-1"),
        ),
        (
            OptimizerPolicy.__table__,
            _policy_row("policy-1", policy_name="Standard"),
            _policy_row("policy-2", policy_name="Standard"),
        ),
    ],
)
def test_orm_schema_rejects_duplicate_current_anchor(orm_engine, table, first, second):
    with orm_engine.begin() as connection:
        connection.execute(table.insert(), first)
        with pytest.raises(IntegrityError):
            connection.execute(table.insert(), second)


def test_soft_deleted_and_historical_mandate_anchors_do_not_block_current(orm_engine):
    with orm_engine.begin() as connection:
        connection.execute(
            RiskAssessment.__table__.insert(),
            [
                _risk_row(
                    "risk-deleted",
                    mandate_id="mandate-1",
                    deleted_at="2026-08-19T00:00:00Z",
                ),
                _risk_row("risk-history", mandate_id="mandate-1", is_current=0),
                _risk_row("risk-current", mandate_id="mandate-1"),
            ],
        )
        connection.execute(
            TargetAllocation.__table__.insert(),
            [
                _allocation_row(
                    "target-deleted",
                    mandate_id="mandate-1",
                    deleted_at="2026-08-19T00:00:00Z",
                ),
                _allocation_row("target-history", mandate_id="mandate-1", is_current=0),
                _allocation_row("target-current", mandate_id="mandate-1"),
            ],
        )


def test_optimizer_policy_uniqueness_is_global_and_historical_rows_remain_allowed(
    orm_engine,
):
    with orm_engine.begin() as connection:
        connection.execute(
            OptimizerPolicy.__table__.insert(),
            [
                _policy_row("standard-history", policy_name="Standard", is_current=0),
                _policy_row(
                    "conservative-history", policy_name="Conservative", is_current=0
                ),
                _policy_row("standard-current", policy_name="Standard"),
            ],
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                OptimizerPolicy.__table__.insert(),
                _policy_row("conservative-current", policy_name="Conservative"),
            )


def test_policy_activation_clears_old_anchor_before_setting_new_one(orm_engine):
    """Immediate unique indexes require deterministic two-phase activation.

    The IDs deliberately sort the draft before the current row.  Without an
    explicit flush after clearing the old anchor, SQLAlchemy may batch the
    UPDATEs in primary-key order and momentarily create two current rows.
    """
    with orm_engine.begin() as connection:
        connection.execute(
            Base.metadata.tables["users"].insert(),
            {
                "id": "admin-anchor",
                "username": "admin-anchor",
                "password_hash": "x",
                "full_name": "Anchor Admin",
                "role": "admin",
                "is_active": 1,
                "created_at": "2026-08-20T00:00:00Z",
                "updated_at": "2026-08-20T00:00:00Z",
            },
        )
        connection.execute(
            OptimizerPolicy.__table__.insert(),
            [
                _policy_row("z-current", policy_name="Current"),
                _policy_row("a-draft", policy_name="Draft", is_current=0),
            ],
        )

    with Session(orm_engine) as session:
        activated = activate_optimizer_policy(
            "a-draft",
            request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            db=session,
            current_user=SimpleNamespace(id="admin-anchor", full_name="Anchor Admin"),
        )
        assert activated.id == "a-draft"

    with Session(orm_engine) as session:
        current_ids = [
            row.id
            for row in session.query(OptimizerPolicy)
            .filter(OptimizerPolicy.is_current == 1)
            .all()
        ]
        assert current_ids == ["a-draft"]


def test_risk_assessment_api_rollover_keeps_exactly_one_current_anchor(orm_engine):
    _seed_advisor_and_mandate(orm_engine)

    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-anchor")
        create_risk_assessment(
            "mandate-anchor",
            _risk_payload(),
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        create_risk_assessment(
            "mandate-anchor",
            _risk_payload(),
            _request_stub(),
            db=session,
            current_user=advisor,
        )

    with Session(orm_engine) as session:
        rows = (
            session.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == "mandate-anchor")
            .order_by(RiskAssessment.version)
            .all()
        )
        assert [(row.version, row.is_current) for row in rows] == [(1, 0), (2, 1)]
        assert rows[1].supersedes_id == rows[0].id


def test_direct_target_allocation_api_rollover_keeps_one_current_anchor(
    orm_engine, monkeypatch
):
    _seed_advisor_and_mandate(orm_engine)
    monkeypatch.setattr(allocation_router.settings, "optimizer_mode", "house_matrix")

    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-anchor")
        create_risk_assessment(
            "mandate-anchor",
            _risk_payload(),
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        session.add(OptimizerPolicy(**_policy_row("policy-anchor", policy_name="Anchor")))
        session.commit()

        first = create_target_allocation(
            "mandate-anchor",
            _target_payload("policy-anchor"),
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        second = create_target_allocation(
            "mandate-anchor",
            _target_payload("policy-anchor"),
            _request_stub(),
            db=session,
            current_user=advisor,
        )
        assert second.version == first.version + 1

    with Session(orm_engine) as session:
        rows = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == "mandate-anchor")
            .order_by(TargetAllocation.version)
            .all()
        )
        assert [(row.version, row.is_current) for row in rows] == [(1, 0), (2, 1)]


def test_active_policy_create_releases_previous_global_anchor_first(orm_engine):
    _seed_advisor_and_mandate(orm_engine)
    with Session(orm_engine) as session:
        session.add(OptimizerPolicy(**_policy_row("old-current", policy_name="Old")))
        session.commit()
        advisor = session.get(User, "advisor-anchor")
        created = create_optimizer_policy(
            OptimizerPolicyCreate(policy_name="Replacement"),
            _request_stub(),
            activate=True,
            db=session,
            current_user=advisor,
        )
        assert created.is_current == 1

    with Session(orm_engine) as session:
        rows = session.query(OptimizerPolicy).order_by(OptimizerPolicy.id).all()
        assert sum(int(row.is_current) for row in rows) == 1
        assert next(row for row in rows if row.is_current == 1).policy_name == "Replacement"
