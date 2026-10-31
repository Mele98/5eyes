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
        monkeypatch.setattr(database, name, lambda target_engine=None: None)
    monkeypatch.setattr(postgres_rls, "ensure_postgres_tenant_not_null", lambda engine, **kwargs: None)
    monkeypatch.setattr(postgres_rls, "ensure_postgres_rls_policies", lambda engine: None)


def test_postgres_init_db_never_enters_sqlite_legacy_schema_path(monkeypatch):
    calls: list[tuple[str, str | None]] = []
    postgres_url = "postgresql://migration-test:unused@localhost/unused"

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: postgres_url)
    monkeypatch.setattr(
        database,
        "_create_or_migrate_schema",
        lambda url, target_engine=None: calls.append(("alembic", url)),
    )
    monkeypatch.setattr(
        database,
        "_run_sqlite_legacy_schema_maintenance",
        lambda target_engine=None: calls.append(("sqlite_legacy", None)),
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
        lambda url, target_engine=None: calls.append(("schema", url)),
    )
    monkeypatch.setattr(
        database,
        "_run_sqlite_legacy_schema_maintenance",
        lambda target_engine=None: calls.append(("sqlite_legacy", None)),
    )
    _patch_post_schema_boot_steps(monkeypatch)

    database.init_db()

    assert calls == [("schema", sqlite_url), ("sqlite_legacy", None)]


def test_postgres_tenant_not_null_backfill_excludes_global_reference_tables(monkeypatch):
    """PG-003 (Codex-Audit 2026-08-25): der Backfill darf capital_market_
    assumptions/products/product_universe_entries/audit_log NICHT anfassen
    -- nur genau die vier Tabellen, die ensure_tenant_backfill() (SQLite)
    bereits als sicher erwiesen hat. Ein Blanket-Backfill auf
    capital_market_assumptions/products haette deren globale/geteilte
    tenant_id=NULL-Semantik unumkehrbar zerstoert (NOT NULL-Constraint)."""
    postgres_url = "postgresql://migration-test:unused@localhost/unused"
    calls: list = []

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: postgres_url)
    monkeypatch.setattr(database, "_create_or_migrate_schema", lambda url, target_engine=None: None)
    for name in (
        "ensure_default_tenant", "ensure_default_ch_jurisdiction",
        "ensure_default_de_jurisdiction", "ensure_client_login_user_tenant_backfill",
        "ensure_tenant_backfill",
    ):
        monkeypatch.setattr(database, name, lambda target_engine=None: None)
    monkeypatch.setattr(
        postgres_rls, "ensure_postgres_tenant_not_null",
        lambda engine, **kwargs: calls.append(kwargs.get("table_names")),
    )
    monkeypatch.setattr(postgres_rls, "ensure_postgres_rls_policies", lambda engine: None)
    monkeypatch.setattr(database.settings, "tenancy_mode", "single")

    database.init_db()

    assert calls == [("users", "clients", "mandates", "protocol_bausteine")]
    for excluded in ("capital_market_assumptions", "products", "product_universe_entries", "audit_log"):
        assert excluded not in calls[0]


def test_postgres_tenant_not_null_backfill_skipped_entirely_in_multi_tenancy_mode(monkeypatch):
    """Analog zu ensure_tenant_backfill() (SQLite): in tenancy_mode="multi"
    ist ein Blanket-'main'-Backfill selbst fuer die vier "sicheren" Tabellen
    ein Risiko (ein noch nicht auditierter Endpoint-Bug koennte NULL-Zeilen
    stillschweigend der Firma zuweisen, die zufaellig 'main' heisst)."""
    postgres_url = "postgresql://migration-test:unused@localhost/unused"
    calls: list = []

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: postgres_url)
    monkeypatch.setattr(database, "_create_or_migrate_schema", lambda url, target_engine=None: None)
    for name in (
        "ensure_default_tenant", "ensure_default_ch_jurisdiction",
        "ensure_default_de_jurisdiction", "ensure_client_login_user_tenant_backfill",
        "ensure_tenant_backfill",
    ):
        monkeypatch.setattr(database, name, lambda target_engine=None: None)
    monkeypatch.setattr(
        postgres_rls, "ensure_postgres_tenant_not_null",
        lambda engine, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(postgres_rls, "ensure_postgres_rls_policies", lambda engine: None)
    monkeypatch.setattr(database.settings, "tenancy_mode", "multi")

    database.init_db()

    assert calls == []


def test_postgres_tenant_not_null_backfill_skipped_for_tier2_without_explicit_tenancy_mode(monkeypatch):
    """Kontrollrunde 2026-09-21 (tier_config-Audit): settings.tenancy_mode
    hat den Klassendefault 'single', nicht None -- ein Tier-2-Deployment, das
    NUR deployment_tier=tier2 setzt (wie services/tier_config.py's Doku es
    verspricht), aber TENANCY_MODE nie explizit setzt, lief VOR dem Fix durch
    diesen Guard (identisches Risiko wie test_..._skipped_entirely_in_multi_
    tenancy_mode oben, nur ueber deployment_tier statt tenancy_mode ausgeloest)."""
    postgres_url = "postgresql://migration-test:unused@localhost/unused"
    calls: list = []

    monkeypatch.setattr(database, "build_database_url", lambda **kwargs: postgres_url)
    monkeypatch.setattr(database, "_create_or_migrate_schema", lambda url, target_engine=None: None)
    for name in (
        "ensure_default_tenant", "ensure_default_ch_jurisdiction",
        "ensure_default_de_jurisdiction", "ensure_client_login_user_tenant_backfill",
        "ensure_tenant_backfill",
    ):
        monkeypatch.setattr(database, name, lambda target_engine=None: None)
    monkeypatch.setattr(
        postgres_rls, "ensure_postgres_tenant_not_null",
        lambda engine, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(postgres_rls, "ensure_postgres_rls_policies", lambda engine: None)
    monkeypatch.setattr(database.settings, "deployment_tier", "tier2")
    assert str(getattr(database.settings, "tenancy_mode", "")).strip().lower() == "single", (
        "Testannahme: Klassendefault ist 'single', nicht explizit gesetzt"
    )

    database.init_db()

    assert calls == []


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


# ---------------------------------------------------------------------------
# Reporting-Views: VOLLSTAENDIGKEIT beider Schema-Quellen
# ---------------------------------------------------------------------------
# Befund 2026-10-12 (E2E-Durchlauf Mock-Mandant "Thierry Goessi"): die drei
# Views standen AUSSCHLIESSLICH in `ares_schema.sql`. Views sind
# nicht Teil des ORM-Metadata, und Alembic enthielt keine einzige
# `CREATE VIEW`. SQLite bekommt sie ueber den Bootstrap, Postgres laeuft nur
# ueber `alembic upgrade head` -- dort fehlten sie, waehrend drei Endpunkte
# sie per rohem SQL ohne Rueckfall lesen (HTTP 500 auf den gehosteten Tiers).


def _bootstrap_view_names() -> set[str]:
    """Die View-Namen aus der SQLite-Bootstrap-Datei.

    Aus der Datei GELESEN, nicht hier abgeschrieben: eine abgeschriebene
    Liste wuerde genau dann nicht mehr stimmen, wenn jemand eine vierte View
    hinzufuegt -- also im einzigen Fall, in dem dieser Guard etwas tun soll.
    """
    import re

    content = (BACKEND_ROOT / "ares_schema.sql").read_text(encoding="utf-8")
    return set(
        re.findall(
            r"CREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
            content,
            flags=re.IGNORECASE,
        )
    )


def test_bootstrap_sql_still_defines_the_expected_views():
    """Sanity-Anker fuer die beiden Guards darunter.

    Faellt die Extraktion auf eine leere Menge (z.B. weil die Datei
    umbenannt oder die Syntax geaendert wurde), wuerden die Guards
    TRIVIAL gruen -- sie wuerden "alle null Views sind migriert" bestaetigen.
    """
    names = _bootstrap_view_names()
    assert names == {
        "v_client_wealth_summary",
        "v_client_cashflow_surplus",
        "v_active_triggers",
    }, names


def test_alembic_head_creates_every_bootstrap_view(tmp_path):
    db_file = tmp_path / "reporting_views_contract.db"
    db_url = f"sqlite:///{db_file}"
    command.upgrade(_alembic_config(db_url), "head")

    engine = create_engine(db_url)
    try:
        existing = set(inspect(engine).get_view_names())
    finally:
        engine.dispose()

    missing = _bootstrap_view_names() - existing
    assert not missing, (
        "Diese Views gibt es im SQLite-Bootstrap, aber nicht auf dem "
        f"Alembic-Pfad: {sorted(missing)}. Auf Postgres laeuft "
        "AUSSCHLIESSLICH Alembic -- jede dort fehlende View ist ein HTTP 500 "
        "in jedem Endpunkt, der sie liest."
    )


def test_alembic_head_emits_postgres_compatible_view_ddl():
    """Die Postgres-Form muss stimmen, nicht nur "irgendeine View".

    Zwei Dinge, die eine blosse Kopie der SQLite-Definition falsch machen
    wuerde:

    1. `CREATE VIEW IF NOT EXISTS` ist SQLite-Syntax; Postgres kennt
       `CREATE OR REPLACE VIEW`.
    2. Beide Summen-Views gruppieren in der SQL-Datei nur nach `c.id`,
       selektieren aber `c.first_name`/`c.last_name`. SQLite erlaubt das,
       Postgres wirft "column must appear in the GROUP BY clause".
    """
    output = StringIO()
    command.upgrade(
        _alembic_config(
            "postgresql://migration-test:unused@localhost/unused",
            output_buffer=output,
        ),
        "head",
        sql=True,
    )
    ddl = output.getvalue()

    for name in _bootstrap_view_names():
        assert f"CREATE OR REPLACE VIEW {name}" in ddl, (
            f"{name} wird fuer Postgres nicht (oder mit SQLite-Syntax) erzeugt"
        )
    assert "IF NOT EXISTS" not in ddl.split("CREATE OR REPLACE VIEW")[-1], (
        "SQLite-Sonderform in der Postgres-DDL"
    )

    # Die vollstaendigen GROUP-BY-Listen, ohne die Postgres die View ablehnt.
    # Ueber Vorkommen GEZAEHLT, weil die kuerzere Klausel ein PRAEFIX der
    # laengeren ist -- ein blosses `in` wuerde die Cashflow-View auch dann
    # bestaetigen, wenn nur die Vermoegens-View korrekt gruppiert.
    # Je DEFINITION gezaehlt: f6b1d4a8c2e7 (MONEY-COLUMN-WIDTH-001) legt beide
    # Views nach dem BIGINT-Umbau neu an -- jede Definition muss vollstaendig
    # gruppieren.
    wealth_definitions = ddl.count("VIEW v_client_wealth_summary AS")
    cashflow_definitions = ddl.count("VIEW v_client_cashflow_surplus AS")
    assert wealth_definitions >= 1 and cashflow_definitions >= 1
    four_columns = "GROUP BY c.id, c.first_name, c.last_name, c.client_classification"
    three_columns = "GROUP BY c.id, c.first_name, c.last_name"
    assert ddl.count(four_columns) == wealth_definitions, "Vermoegens-View gruppiert nicht vollstaendig"
    assert ddl.count(three_columns) == wealth_definitions + cashflow_definitions, (
        "Cashflow-View gruppiert nicht vollstaendig (erwartet: die eigene "
        "Dreier-Klausel plus das Praefix der Vierer-Klausel)"
    )


# ---------------------------------------------------------------------------
# ORM gegen Alembic-Kopf: VOLLSTAENDIGKEIT der Postgres-Strecke
# ---------------------------------------------------------------------------
# Gefunden 2026-10-12 beim Gruenziehen von test_postgres_alembic_views_live.py:
# ein ORM-Insert auf `users` scheiterte auf echtem PostgreSQL mit
# `UndefinedColumn: column "calendar_feed_token_hash" ... does not exist`.
# Systematisch nachgemessen fehlten SIEBEN ORM-Spalten in VIER Kerntabellen
# (clients, contract_documents, mandates, users) nach `alembic upgrade head`.
#
# Warum es auf SQLite nie auffiel: dort laeuft nach dem Bootstrap zusaetzlich
# `create_all()` und danach `_run_sqlite_legacy_schema_maintenance()` mit
# `ensure_column(...)`, wo diese Spalten stehen. Postgres bekommt
# AUSSCHLIESSLICH Alembic. SQLAlchemy generiert in jedem ORM-Statement die
# volle Spaltenliste -- eine dort fehlende Spalte ist deshalb nicht eine
# fehlende Nebenangabe, sondern ein Fehler bei praktisch jeder Anfrage auf
# die betroffene Tabelle.
#
# Dieser Guard prueft die KLASSE, nicht die sieben Spalten: jede kuenftige
# ORM-Spalte ohne Migration faellt hier auf.


def _alembic_head_schema(tmp_path) -> dict[str, set[str]]:
    """Tabellen und Spalten, die `alembic upgrade head` tatsaechlich anlegt."""
    db_url = f"sqlite:///{tmp_path / 'orm_parity_contract.db'}"
    command.upgrade(_alembic_config(db_url), "head")
    engine = create_engine(db_url)
    try:
        db_inspector = inspect(engine)
        return {
            table_name: {
                column["name"] for column in db_inspector.get_columns(table_name)
            }
            for table_name in db_inspector.get_table_names()
        }
    finally:
        engine.dispose()


def _orm_metadata():
    """Das vollstaendige ORM-Metadata, inklusive der lazy importierten Modelle.

    `database.init_db()` importiert `models.tenant` und `models.jurisdiction`
    ausdruecklich VOR `create_all`, damit deren Tabellen entstehen -- derselbe
    Import ist hier noetig, sonst prueft der Guard ein unvollstaendiges
    Metadata und wird dadurch zu mild.
    """
    import models.jurisdiction  # noqa: F401,PLC0415
    import models.tenant  # noqa: F401,PLC0415
    from database import Base  # noqa: PLC0415

    return Base.metadata


def test_orm_metadata_is_reasonably_populated():
    """Sanity-Anker: sonst wird der Guard unten TRIVIAL gruen.

    Waeren die Modelle nicht importiert, waere `Base.metadata` fast leer und
    der Vergleich wuerde "alle null Tabellen sind migriert" bestaetigen.
    """
    metadata = _orm_metadata()
    assert len(metadata.tables) >= 60, (
        f"Nur {len(metadata.tables)} ORM-Tabellen sichtbar -- die Modelle sind "
        "offenbar nicht vollstaendig importiert; der Paritaets-Guard unten "
        "waere dadurch wertlos."
    )


def test_alembic_head_creates_every_orm_table(tmp_path):
    migrated = _alembic_head_schema(tmp_path)
    missing = sorted(set(_orm_metadata().tables) - set(migrated))
    assert not missing, (
        "Diese ORM-Tabellen entstehen auf dem Alembic-Pfad NICHT: "
        f"{missing}. Auf Postgres laeuft ausschliesslich Alembic."
    )


def test_alembic_head_creates_every_orm_column(tmp_path):
    migrated = _alembic_head_schema(tmp_path)
    metadata = _orm_metadata()

    gaps: dict[str, list[str]] = {}
    for table_name, table in metadata.tables.items():
        if table_name not in migrated:
            continue  # eigener Test oben
        orm_columns = {column.name for column in table.columns}
        missing = sorted(orm_columns - migrated[table_name])
        if missing:
            gaps[table_name] = missing

    assert not gaps, (
        "Diese ORM-Spalten entstehen auf dem Alembic-Pfad NICHT:\n"
        + "\n".join(f"  {table}: {cols}" for table, cols in sorted(gaps.items()))
        + "\n\nSQLAlchemy generiert in JEDEM ORM-Statement die volle "
        "Spaltenliste -- auf Postgres scheitert damit praktisch jede Anfrage "
        "auf die betroffene Tabelle mit UndefinedColumn. Fuer jede neue "
        "ORM-Spalte gehoert eine Alembic-Revision dazu; `ensure_column(...)` "
        "in database.py deckt nur den SQLite-Pfad."
    )
