"""PG-002 ratchet: tables with a client/mandate reference must be tenant_direct.

``tenant_derived`` tables are outside the PostgreSQL RLS plan. Each new
append-only evidence table so far shipped as ``tenant_derived`` first and
had to be moved later (red-team review 2026-10-28, finding 6). From now on a
table with a client/mandate reference (own ``client_id``/``mandate_id``
column, or a derivation route that runs through ``clients``/``mandates``)
may only be ``tenant_derived`` if it is listed with an explicit reason in
``services.tenant_scope_inventory.TENANT_DERIVED_BACKLOG``. The list only
shrinks: no stale entries, and a ceiling that is lowered with every
migrated table.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import import_tenant_models  # noqa: E402

import_tenant_models()

from database import Base  # noqa: E402
from services import tenant_scope_inventory as inventory  # noqa: E402

# Lower this number when a backlog table gets its own tenant_id; never raise it.
BACKLOG_CEILING = 30


def test_every_client_or_mandate_bound_table_is_tenant_direct_or_justified():
    bound = inventory.client_or_mandate_bound_derived_tables(Base.metadata.tables)
    missing = sorted(bound - set(inventory.TENANT_DERIVED_BACKLOG))
    assert missing == [], (
        "tenant_derived mit Kunden-/Mandatsbezug ohne Begruendung -- tenant_id direkt "
        f"anlegen (Muster services/mandate_evidence_tenant_boundary.py): {missing}"
    )


def test_backlog_has_reasons_no_stale_entries_and_only_shrinks():
    bound = inventory.client_or_mandate_bound_derived_tables(Base.metadata.tables)
    backlog = inventory.TENANT_DERIVED_BACKLOG
    assert sorted(set(backlog) - bound) == [], "veraltete Backlog-Eintraege entfernen"
    assert all(reason.strip() for reason in backlog.values())
    assert len(backlog) <= BACKLOG_CEILING


def test_ratchet_flags_a_synthetic_new_derived_table():
    probe = MetaData()
    tables = dict(Base.metadata.tables)
    tables["synthetic_evidence"] = Table(
        "synthetic_evidence", probe, Column("id", String, primary_key=True), Column("mandate_id", String),
    )
    tables["synthetic_child"] = Table(
        "synthetic_child", probe, Column("id", String, primary_key=True), Column("parent_id", String),
    )
    routes = dict(inventory.TENANT_DERIVED_TABLES)
    routes["synthetic_evidence"] = ("mandate_id", "mandates")
    routes["synthetic_child"] = ("parent_id", "recommendation_runs")
    bound = inventory.client_or_mandate_bound_derived_tables(tables, routes)
    assert {"synthetic_evidence", "synthetic_child"} <= bound
    # Berater-/Login-Tabellen ohne Kundenbezug fallen nicht unter die Ratsche.
    assert "adviser_registrations" not in bound and "refresh_tokens" not in bound


def test_recently_migrated_tables_are_not_in_the_backlog():
    for table in (
        "depot_snapshots", "onsite_signature_events", "onsite_signature_challenges",
        "onsite_signature_evidence", "depot_check_analysis_snapshots", "product_eligibility_overrides",
    ):
        assert inventory.classification()[table] == inventory.TENANT_DIRECT, table
        assert table not in inventory.TENANT_DERIVED_BACKLOG
