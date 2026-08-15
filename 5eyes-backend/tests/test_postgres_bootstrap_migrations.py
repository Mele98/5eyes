"""Production bootstrap contracts for the PostgreSQL/Alembic boundary."""
from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database  # noqa: E402
from services.market_data import provider_health_registry  # noqa: E402
import services.postgres_rls as postgres_rls  # noqa: E402


def _alembic_config(database_url: str, *, output_buffer=None) -> AlembicConfig:
    cfg = AlembicConfig(
        str(BACKEND_ROOT / "alembic.ini"),
        output_buffer=output_buffer,
    )
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _patch_post_schema_boot_steps(monkeypatch) -> None:
    for name in (
        "ensure_default_tenant",
        "ensure_default_ch_jurisdiction",
        "ensure_default_de_jurisdiction",
        "ensure_client_login_user_tenant_backfill",
        "ensure_tenant_backfill",
    ):
        monkeypatch.setattr(database, name, lambda: None)
    monkeypatch.setattr(postgres_rls, "ensure_postgres_tenant_not_null", lambda engine: None)
    monkeypatch.setattr(postgres_rls, "ensure_postgres_rls_policies", lambda engine: None)


def test_postgres_init_db_never_enters_sqlite_legacy_schema_path(monkeypatch):
    calls: list[tuple[str, str | None]] = []
    postgres_url = "postgresql://migration-test:unused@localhost/unused"

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: postgres_url)
    monkeypatch.setattr(
        database,
        "_create_or_migrate_schema",
        lambda url: calls.append(("alembic", url)),
    )
    monkeypatch.setattr(
        database,
        "_run_sqlite_legacy_schema_maintenance",
        lambda: calls.append(("sqlite_legacy", None)),
    )
    _patch_post_schema_boot_steps(monkeypatch)

    database.init_db()

    assert calls == [("alembic", postgres_url)]


def test_sqlite_init_db_keeps_legacy_schema_path(monkeypatch):
    calls: list[tuple[str, str | None]] = []
    sqlite_url = "sqlite:///irrelevant.db"

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: sqlite_url)
    monkeypatch.setattr(database.settings, "db_bootstrap_schema_on_startup", False)
    monkeypatch.setattr(
        database,
        "_create_or_migrate_schema",
        lambda url: calls.append(("schema", url)),
    )
    monkeypatch.setattr(
        database,
        "_run_sqlite_legacy_schema_maintenance",
        lambda: calls.append(("sqlite_legacy", None)),
    )
    _patch_post_schema_boot_steps(monkeypatch)

    database.init_db()

    assert calls == [("schema", sqlite_url), ("sqlite_legacy", None)]


def test_lazy_sqlite_schema_helpers_are_noops_for_postgres():
    class PostgresEngineWithoutConnections:
        dialect = SimpleNamespace(name="postgresql")

        def begin(self):  # pragma: no cover - failure message is the contract
            raise AssertionError("SQLite legacy helper opened a PostgreSQL connection")

    fake_engine = PostgresEngineWithoutConnections()
    database.ensure_purge_history_table(fake_engine)
    provider_health_registry.ensure_provider_health_table(fake_engine)


def test_provider_health_query_does_not_use_sqlite_rowid_on_postgres(monkeypatch):
    statements: list[str] = []

    class EmptyResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params):
            statements.append(str(statement))
            return EmptyResult()

    monkeypatch.setattr(
        provider_health_registry,
        "ensure_provider_health_table",
        lambda engine: None,
    )

    assert provider_health_registry.list_provider_health(FakeSession()) == []
    assert len(statements) == 1
    assert "rowid" not in statements[0].lower()
    assert "id DESC" in statements[0]


def test_alembic_head_creates_market_data_runtime_tables_and_indexes(tmp_path):
    db_file = tmp_path / "postgres_runtime_schema_contract.db"
    db_url = f"sqlite:///{db_file}"
    command.upgrade(_alembic_config(db_url), "head")

    engine = create_engine(db_url)
    db_inspector = inspect(engine)
    assert {
        column["name"]
        for column in db_inspector.get_columns("provider_health_events")
    } == {
        "id",
        "provider_name",
        "status",
        "reason",
        "operation",
        "error_type",
        "consecutive_errors",
        "observed_at",
        "unhealthy_until",
        "recovered_at",
        "source",
        "created_at",
        "updated_at",
    }
    assert {
        index["name"] for index in db_inspector.get_indexes("provider_health_events")
    } == {
        "ix_provider_health_events_provider_observed",
        "ix_provider_health_events_status",
    }
    assert {
        column["name"]
        for column in db_inspector.get_columns("market_data_purge_history")
    } == {
        "id",
        "started_at",
        "finished_at",
        "purged_rows",
        "skipped_providers_json",
        "duration_seconds",
        "errors_json",
    }
    assert {
        index["name"]
        for index in db_inspector.get_indexes("market_data_purge_history")
    } == {"ix_market_data_purge_history_started"}
    assert "ix_strategy_snapshots_mandate" in {
        index["name"] for index in db_inspector.get_indexes("strategy_snapshots")
    }
    assert "idx_risk_answers" in {
        index["name"]
        for index in db_inspector.get_indexes("risk_assessment_answers")
    }
    assert {
        "idx_audit_mandate_table",
        "idx_audit_record",
        "idx_audit_mandate",
        "idx_audit_user",
        "idx_audit_time",
    }.issubset(
        {index["name"] for index in db_inspector.get_indexes("audit_log")}
    )
    engine.dispose()


def test_alembic_head_emits_postgres_ddl_for_market_data_runtime_tables():
    output = StringIO()
    command.upgrade(
        _alembic_config(
            "postgresql://migration-test:unused@localhost/unused",
            output_buffer=output,
        ),
        "head",
        sql=True,
    )

    ddl = output.getvalue().lower()
    assert "create table provider_health_events" in ddl
    assert "create index ix_provider_health_events_provider_observed" in ddl
    assert "create index ix_provider_health_events_status" in ddl
    assert "create table market_data_purge_history" in ddl
    assert "serial not null" in ddl
    assert "create index ix_market_data_purge_history_started" in ddl
    for index_name in (
        "ix_strategy_snapshots_mandate",
        "idx_risk_answers",
        "idx_audit_mandate_table",
        "idx_audit_record",
        "idx_audit_mandate",
        "idx_audit_user",
        "idx_audit_time",
    ):
        assert f"create index {index_name}" in ddl
    for constraint_name in (
        "ck_risk_answers_question_number",
        "ck_risk_answers_question_section",
        "uq_risk_answers_assessment_question",
        "ck_audit_log_action_allowed",
    ):
        assert f"constraint {constraint_name}" in ddl
    assert "create function fn_5eyes_audit_log_immutable()" in ddl
    assert "create trigger trg_audit_log_no_update" in ddl
    assert "create trigger trg_audit_log_no_delete" in ddl
    for sqlite_only_token in (
        "pragma ",
        "sqlite_master",
        "autoincrement",
        "raise(abort",
        "insert or ignore",
    ):
        assert sqlite_only_token not in ddl
