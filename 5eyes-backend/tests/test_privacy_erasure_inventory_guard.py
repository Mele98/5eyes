"""PRIVACY-001 Ratsche: jede Tabelle mit Kunden-/Mandatsbezug im
Tenant-Inventar hat eine Disposition-Klassifikation im Loeschinventar.

Eine neue Tabelle mit ``client_id``/``mandate_id`` (oder abgeleitet ueber
eine solche Tabelle) kann damit nicht ohne Eintrag in
services/privacy_erasure_inventory.py ausgeliefert werden.
"""
from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table

from database import Base
from services import privacy_erasure_inventory as inv
from services import tenant_scope_inventory as tenant_inventory
from services.pii_vault import SEALED_APPEND_ONLY_COLUMNS
from services.postgres_rls import import_tenant_models

import_tenant_models()


def test_every_client_bound_table_has_a_disposition_classification():
    problems = inv.inventory_problems(Base.metadata.tables, tenant_inventory.TENANT_DERIVED_TABLES)
    assert problems == []


def test_client_bound_set_covers_the_tenant_inventory_routes():
    bound = inv.client_bound_tables(Base.metadata.tables, tenant_inventory.TENANT_DERIVED_TABLES)
    for name, (_column, parent) in tenant_inventory.TENANT_DERIVED_TABLES.items():
        if parent in bound:
            assert name in bound, name
    assert {"risk_assessment_answers", "recommendation_positions", "product_eligibility_overrides"} <= bound
    assert "adviser_registrations" not in bound  # Berater, anderes Datensubjekt


def test_guard_flags_a_synthetic_unclassified_client_table():
    metadata = MetaData()
    tables = dict(Base.metadata.tables)
    tables["synthetic_client_notes"] = Table(
        "synthetic_client_notes", metadata, Column("id", String, primary_key=True), Column("client_id", String),
    )
    tables["synthetic_child"] = Table(
        "synthetic_child", metadata, Column("id", String, primary_key=True), Column("parent_id", String),
    )
    routes = dict(tenant_inventory.TENANT_DERIVED_TABLES)
    routes["synthetic_child"] = ("parent_id", "synthetic_client_notes")
    problems = inv.inventory_problems(tables, routes)
    assert any("synthetic_client_notes" in p for p in problems)
    assert any("synthetic_child" in p for p in problems)


def test_privacy_tables_are_tenant_direct_and_exempt_tables_exist():
    classified = tenant_inventory.classification()
    for table in ("privacy_retention_policies", "privacy_role_designations", "privacy_legal_holds",
                  "privacy_erasure_cases", "privacy_erasure_dispositions"):
        assert classified[table] == tenant_inventory.TENANT_DIRECT
    assert set(inv.EXEMPT_TABLES) <= set(Base.metadata.tables)


def test_every_sealed_column_is_crypto_shred_and_methods_are_consistent():
    crypto = {
        (table, column)
        for table, entry in inv.PERSONAL_DATA_INVENTORY.items()
        for category in entry.categories if category.method == inv.CRYPTO_SHRED
        for column in category.columns
    }
    assert set(SEALED_APPEND_ONLY_COLUMNS) <= crypto
    for table, entry in inv.PERSONAL_DATA_INVENTORY.items():
        for category in entry.categories:
            if category.name == inv.SEALED_FREE_TEXT:
                assert category.method == inv.CRYPTO_SHRED, table
            if category.name == inv.RECORD:
                assert category.method is None, table


def test_risk_and_plausibility_evidence_are_inventoried():
    types = {
        table: {category.evidence_type for category in entry.categories}
        for table, entry in inv.PERSONAL_DATA_INVENTORY.items()
    }
    assert types["risk_capacity_plausibility_evaluations"] == {"risk_capacity_plausibility_evidence"}
    assert types["financial_coverage_attestations"] == {"risk_capacity_plausibility_evidence"}
    for table in ("risk_assessments", "risk_assessment_answers", "risk_override_decisions",
                  "risk_profile_signoffs"):
        assert types[table] == {"risk_profile_evidence"}
