"""Versioned, complete tenant-scope inventory of every ORM table (PG-002).

Closure review of PR #666: ``tenant_scoped_table_names()`` discovers RLS
tables only by a physical ``tenant_id`` column. A sensitive table without
that column was silently outside the RLS plan, and the CI guard stayed green
because it only checked tables it had already discovered.

This registry classifies EVERY table of ``Base.metadata`` explicitly:

``tenant_direct``     own ``tenant_id`` column, strict RLS policy.
``global_reference``  shared reference data: either a ``tenant_id`` where NULL
                      means "valid for all tenants" (RLS read-all/write-own,
                      ``services.postgres_rls.GLOBAL_REFERENCE_TABLES``) or no
                      tenant column at all (market data, FX, house matrix ...).
``tenant_derived``    tenant only reachable through a parent
                      (``(column, parent_table)``); NOT yet in the RLS plan.
                      Each such table is an open PG-002 item until it gets
                      a direct ``tenant_id``. The parent route must end in a
                      ``tenant_direct`` table.
``system_only``       installation/system state without tenant data.

``tests/test_tenant_database_boundary.py`` fails when a table is missing
from the registry, when the registry names a table that no longer exists,
or when the classification contradicts the schema / the RLS plan. A new
table therefore cannot ship unclassified.
"""
from __future__ import annotations

INVENTORY_VERSION = "2026-10-26.1"

TENANT_DIRECT = "tenant_direct"
GLOBAL_REFERENCE = "global_reference"
TENANT_DERIVED = "tenant_derived"
SYSTEM_ONLY = "system_only"

CATEGORIES = (TENANT_DIRECT, GLOBAL_REFERENCE, TENANT_DERIVED, SYSTEM_ONLY)

TENANT_DIRECT_TABLES: frozenset[str] = frozenset({
    "audit_log",
    "clients",
    "mandates",
    "product_eligibility_snapshots",
    "product_universe_entries",
    "protocol_bausteine",
    # PG-002 (Closure-Review PR #662): append-only Risiko-Evidence, Mandant
    # aus dem Mandat abgeleitet (services/risk_evidence_tenant_boundary.py).
    "risk_override_decisions",
    "risk_profile_signoffs",
    # RISK-CAPACITY-EVALUATION-SNAPSHOT-001: append-only Plausibilitaets-
    # Evidenz, Mandant aus dem Mandat (hash-gebunden).
    "risk_capacity_plausibility_evaluations",
    "users",
    # PG-002 (Closure-Review PR #666): bisher nur transitiv ueber clients.
    "wealth_inflows",
    "wealth_positions",
})

# Tables with a nullable tenant_id where NULL = global (read for all tenants).
GLOBAL_REFERENCE_TENANT_TABLES: frozenset[str] = frozenset({
    "capital_market_assumptions",
    "product_eligibility_rule_sets",
    "product_eligibility_rules",
    "products",
})

# Shared reference data without any tenant column.
GLOBAL_REFERENCE_PLAIN_TABLES: frozenset[str] = frozenset({
    "asset_class_annual_returns",
    "asset_class_fx_history",
    "asset_class_price_history",
    "building_blocks",
    # CMA-001: CMA_POLICY-Paket (global wie optimizer_policies; Schreiben nur
    # Portfolio Management).
    "cma_policies",
    "cma_policy_approvals",
    "cma_policy_components",
    "fx_rates",
    "house_matrix",
    "jurisdiction_home_bias_defaults",
    "jurisdiction_profiles",
    "market_data_cache",
    "optimizer_policies",
    "price_history",
    "product_suitability",
    "tax_parameter_sets",
})

SYSTEM_ONLY_TABLES: frozenset[str] = frozenset({
    "audit_log_sequence_counter",
    "bootstrap_lock",
    "login_attempts",
    "login_lockouts",
    "market_data_validation_log",
    "tenants",
})

# (column, parent table): the route along which the tenant is derived today.
TENANT_DERIVED_TABLES: dict[str, tuple[str, str]] = {
    "adviser_registrations": ("user_id", "users"),
    "advisory_log": ("mandate_id", "mandates"),
    "cashflows": ("client_id", "clients"),
    "client_due_diligence": ("client_id", "clients"),
    "client_knowledge": ("client_id", "clients"),
    "client_logins": ("client_id", "clients"),
    "client_nationalities": ("client_id", "clients"),
    "client_opt_history": ("client_id", "clients"),
    "client_pii_keys": ("client_id", "clients"),
    "client_tax_residencies": ("client_id", "clients"),
    "conflict_of_interest_disclosures": ("mandate_id", "mandates"),
    "contract_documents": ("mandate_id", "mandates"),
    "financial_coverage_attestations": ("mandate_id", "mandates"),
    "goal_lifecycle_transitions": ("mandate_id", "mandates"),
    "goal_revision_decisions": ("mandate_id", "mandates"),
    "goals": ("mandate_id", "mandates"),
    "mandate_baustein_selections": ("mandate_id", "mandates"),
    "mandate_report_notes": ("mandate_id", "mandates"),
    "optimizer_runs": ("mandate_id", "mandates"),
    "planning_assumptions": ("mandate_id", "mandates"),
    "portfolio_handoffs": ("mandate_id", "mandates"),
    "product_eligibility_decisions": ("snapshot_id", "product_eligibility_snapshots"),
    # ELIG-OVERRIDE-CAPTURE-001: captured overrides carry no snapshot_id; the
    # always-set route to the tenant is the run.
    "product_eligibility_overrides": ("recommendation_run_id", "recommendation_runs"),
    "recommendation_holdings": ("run_id", "recommendation_runs"),
    "recommendation_positions": ("run_id", "recommendation_runs"),
    "recommendation_runs": ("mandate_id", "mandates"),
    "refresh_tokens": ("user_id", "users"),
    "review_triggers": ("mandate_id", "mandates"),
    "risk_assessment_answers": ("assessment_id", "risk_assessments"),
    "risk_assessments": ("mandate_id", "mandates"),
    "strategy_snapshots": ("mandate_id", "mandates"),
    "suitability_checks": ("mandate_id", "mandates"),
    "target_allocations": ("mandate_id", "mandates"),
}


def classification() -> dict[str, str]:
    """table name -> category (each table exactly once)."""
    result: dict[str, str] = {}
    groups = (
        (TENANT_DIRECT, TENANT_DIRECT_TABLES),
        (GLOBAL_REFERENCE, GLOBAL_REFERENCE_TENANT_TABLES | GLOBAL_REFERENCE_PLAIN_TABLES),
        (TENANT_DERIVED, frozenset(TENANT_DERIVED_TABLES)),
        (SYSTEM_ONLY, SYSTEM_ONLY_TABLES),
    )
    for category, names in groups:
        for name in names:
            if name in result:
                raise ValueError(f"Tabelle {name!r} ist doppelt klassifiziert ({result[name]}, {category})")
            result[name] = category
    return result


def rls_planned_tables() -> frozenset[str]:
    """Tables that must carry an RLS policy (strict or reference)."""
    return TENANT_DIRECT_TABLES | GLOBAL_REFERENCE_TENANT_TABLES


def inventory_problems(metadata_tables: dict) -> list[str]:
    """Contradictions between the registry and the ORM schema (empty = consistent)."""
    problems: list[str] = []
    try:
        classified = classification()
    except ValueError as exc:
        return [str(exc)]
    names = set(metadata_tables)
    for name in sorted(names - set(classified)):
        problems.append(f"unklassifizierte Tabelle: {name}")
    for name in sorted(set(classified) - names):
        problems.append(f"Registry nennt unbekannte Tabelle: {name}")
    for name in sorted(names & set(classified)):
        columns = set(metadata_tables[name].c.keys())
        category = classified[name]
        has_tenant = "tenant_id" in columns
        if category == TENANT_DIRECT and not has_tenant:
            problems.append(f"{name}: tenant_direct ohne tenant_id-Spalte")
        if name in GLOBAL_REFERENCE_TENANT_TABLES and not has_tenant:
            problems.append(f"{name}: globale Referenztabelle ohne tenant_id-Spalte")
        if category in (TENANT_DERIVED, SYSTEM_ONLY) and has_tenant:
            problems.append(f"{name}: hat tenant_id, ist aber als {category} klassifiziert")
        if name in GLOBAL_REFERENCE_PLAIN_TABLES and has_tenant:
            problems.append(f"{name}: hat tenant_id, ist aber als tenantlose Referenz klassifiziert")
        if category == TENANT_DERIVED:
            column, parent = TENANT_DERIVED_TABLES[name]
            if column not in columns:
                problems.append(f"{name}: Ableitungsspalte {column} fehlt")
            seen = {name}
            current = parent
            while current in TENANT_DERIVED_TABLES and current not in seen:
                seen.add(current)
                current = TENANT_DERIVED_TABLES[current][1]
            if current not in TENANT_DIRECT_TABLES:
                problems.append(f"{name}: Ableitungskette endet nicht in tenant_direct ({current})")
    return problems
