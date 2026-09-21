from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import Session

from config import settings
from services.foundation_example import FOUNDATION_CLIENT_NUMBER, FOUNDATION_MANDATE_NUMBER


PRODUCTION_BLOCK_DETAIL = (
    "Foundation-/Demo-Daten-Purge ist in der Produktionsumgebung gesperrt "
    "(FINMA: Demo-Purge nur in regenerierbaren Nicht-Produktionsdatenbanken)."
)

# Kontrollrunde 2026-09-21 (Foundation-Purge-Audit): vorher NUR app_env==
# "production" geblockt (Default ist "development" -- fail-open, wenn ein
# Deployment APP_ENV schlicht vergisst zu setzen). config.py's eigene
# security-relevante Validatoren (secret_key-Laenge, strict_tenant_isolation,
# SMTP-TLS etc.) behandeln bereits "staging" als ebenso schutzwuerdig wie
# "production" (siehe dortige app_env in {'staging','production'}-Checks) --
# dieselbe, bereits etablierte Grenze wird hier uebernommen: ein irreversibler
# Hard-Delete verdient mindestens denselben Schutz wie ein SMTP-TLS-Flag.
# Behebt NICHT das tiefer liegende "APP_ENV wurde nie gesetzt"-Risiko fuer
# die App als Ganzes (das ist eine separate, groessere Architekturfrage
# ausserhalb des Scopes dieses Fixes) -- reduziert aber konkret die Flaeche
# fuer GENAU diese eine irreversible Operation.
_PURGE_BLOCKED_APP_ENVS = frozenset({"staging", "production"})


@dataclass(frozen=True)
class _Scope:
    client_ids: list[str]
    mandate_ids: list[str]
    run_ids: list[str]
    position_ids: list[str]
    assessment_ids: list[str]
    target_allocation_ids: list[str]
    optimizer_run_ids: list[str]


def purge_foundation_example_data(db: Session) -> dict[str, Any]:
    """Hard-delete the regenerable Foundation/Demo client and owned rows.

    Normal clients keep the ordinary soft-delete lifecycle. This routine is
    intentionally scoped to the known Foundation marker only.
    """
    if _app_env() in _PURGE_BLOCKED_APP_ENVS:
        raise HTTPException(status_code=403, detail=PRODUCTION_BLOCK_DETAIL)

    scope = _load_scope(db)
    if not scope.client_ids:
        return {
            "status": "not_found",
            "client_ids": [],
            "mandate_ids": [],
            "deleted": {},
        }

    deleted: dict[str, int] = {}

    # Break optional cycles first: target_allocations <-> optimizer_runs and
    # advisory_log self-links can otherwise block hard deletes with FK checks on.
    _update_null(
        db,
        "target_allocations",
        "optimization_run_id",
        "id",
        scope.target_allocation_ids,
    )
    _update_null(
        db,
        "optimizer_runs",
        "target_allocation_id",
        "id",
        scope.optimizer_run_ids,
    )
    _update_null(db, "advisory_log", "supersedes_id", "mandate_id", scope.mandate_ids)
    _update_null(db, "advisory_log", "superseded_by_id", "mandate_id", scope.mandate_ids)

    # Recommendation chain and objects that may point at recommendation runs.
    # Kontrollrunde 2026-09-21 (Foundation-Purge-Audit): portfolio_handoffs
    # fehlte hier komplett -- PortfolioHandoff hat ZWEI FKs (mandate_id NOT
    # NULL, recommendation_run_id NULLABLE, siehe models/portfolio_handoff.py).
    # Mit SQLite-FK-Enforcement (database.py, immer aktiv) liess ein
    # vorhandener Handoff sowohl DELETE FROM recommendation_runs (via
    # recommendation_run_id) als auch spaeter DELETE FROM mandates (via
    # mandate_id) mit IntegrityError scheitern -- der Purge war fuer jedes
    # Foundation-Mandat, das je die Handoff-Funktion genutzt hat, dauerhaft
    # unbenutzbar. Muss VOR recommendation_runs geloescht werden (wegen der
    # recommendation_run_id-FK), nicht nur vor mandates.
    _delete_in(deleted, db, "portfolio_handoffs", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "recommendation_holdings", "recommendation_position_id", scope.position_ids)
    _delete_in(deleted, db, "recommendation_holdings", "run_id", scope.run_ids)
    _delete_in(deleted, db, "advisory_log", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "suitability_checks", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "recommendation_positions", "run_id", scope.run_ids)
    _delete_in(deleted, db, "recommendation_runs", "id", scope.run_ids)

    # Mandate-scoped advisory artefacts.
    _delete_in(deleted, db, "strategy_snapshots", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "mandate_baustein_selections", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "mandate_report_notes", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "contract_documents", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "conflict_of_interest_disclosures", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "review_triggers", "mandate_id", scope.mandate_ids)

    # Optimizer/allocation state.
    _delete_in(deleted, db, "optimizer_runs", "id", scope.optimizer_run_ids)
    _delete_in(deleted, db, "target_allocations", "id", scope.target_allocation_ids)

    # Risk profile chain.
    _delete_in(deleted, db, "risk_assessment_answers", "assessment_id", scope.assessment_ids)
    _delete_in(deleted, db, "risk_assessments", "id", scope.assessment_ids)

    # Wealth/goal/planning data. Some tables are mandate-scoped, others only
    # client-scoped; both filters are intentionally applied where supported.
    _delete_in(deleted, db, "goals", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "planning_assumptions", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "wealth_inflows", "mandate_id", scope.mandate_ids)
    _delete_in(deleted, db, "wealth_inflows", "client_id", scope.client_ids)
    _delete_in(deleted, db, "cashflows", "client_id", scope.client_ids)
    _delete_in(deleted, db, "wealth_positions", "client_id", scope.client_ids)
    _delete_in(deleted, db, "client_knowledge", "client_id", scope.client_ids)
    _delete_in(deleted, db, "client_nationalities", "client_id", scope.client_ids)
    _delete_in(deleted, db, "client_opt_history", "client_id", scope.client_ids)
    _delete_in(deleted, db, "client_logins", "client_id", scope.client_ids)

    # Parents last.
    _delete_in(deleted, db, "mandates", "id", scope.mandate_ids)
    _delete_in(deleted, db, "clients", "id", scope.client_ids)
    db.flush()

    return {
        "status": "purged",
        "client_ids": scope.client_ids,
        "mandate_ids": scope.mandate_ids,
        "deleted": deleted,
    }


def purge_demo_client_data(db: Session, client_id: str) -> dict[str, Any]:
    """Hard-delete one client only if it is the known Foundation demo client."""
    assert_demo_client_purge_allowed(db, client_id)
    result = purge_foundation_example_data(db)
    if client_id not in set(result.get("client_ids") or []):
        return {
            "status": "not_found",
            "client_ids": [],
            "mandate_ids": [],
            "deleted": {},
        }
    return result


def assert_demo_client_purge_allowed(db: Session, client_id: str) -> None:
    """Validate that a client is the Foundation demo client before hard purge."""
    if _app_env() in _PURGE_BLOCKED_APP_ENVS:
        raise HTTPException(status_code=403, detail=PRODUCTION_BLOCK_DETAIL)
    if not _is_foundation_client(db, client_id):
        raise HTTPException(
            status_code=403,
            detail="Hard-Purge ist nur fuer eindeutig markierte Foundation-/Demo-Kunden erlaubt.",
        )


def _load_scope(db: Session) -> _Scope:
    client_ids = _foundation_client_ids(db)
    mandate_ids = _select_ids_by_in(db, "mandates", "id", "client_id", client_ids)
    mandate_ids = _merge_unique(
        mandate_ids,
        _select_ids(
            db,
            "mandates",
            "id",
            "mandate_number = :mandate_number",
            {"mandate_number": FOUNDATION_MANDATE_NUMBER},
        ),
    )
    run_ids = _merge_unique(
        _select_ids_by_in(db, "recommendation_runs", "id", "mandate_id", mandate_ids),
        _select_ids_by_in(db, "recommendation_runs", "id", "client_id", client_ids),
    )
    position_ids = _select_ids_by_in(db, "recommendation_positions", "id", "run_id", run_ids)
    assessment_ids = _select_ids_by_in(db, "risk_assessments", "id", "mandate_id", mandate_ids)
    target_allocation_ids = _select_ids_by_in(db, "target_allocations", "id", "mandate_id", mandate_ids)
    optimizer_run_ids = _merge_unique(
        _select_ids_by_in(db, "optimizer_runs", "id", "mandate_id", mandate_ids),
        _select_ids_by_in(db, "optimizer_runs", "id", "target_allocation_id", target_allocation_ids),
    )
    return _Scope(
        client_ids=client_ids,
        mandate_ids=mandate_ids,
        run_ids=run_ids,
        position_ids=position_ids,
        assessment_ids=assessment_ids,
        target_allocation_ids=target_allocation_ids,
        optimizer_run_ids=optimizer_run_ids,
    )


def _foundation_client_ids(db: Session) -> list[str]:
    """Kontrollrunde 2026-09-21 (Foundation-Purge-Audit): identifiziert den
    Foundation-Client NUR ueber client_number. Vorher wurde zusaetzlich
    JEDE Mandate.client_id gemergt, deren mandate_number zufaellig/
    fehlerhaft/absichtlich dem reservierten FOUNDATION_MANDATE_NUMBER
    entsprach -- client_number und mandate_number sind unabhaengig
    eindeutige, aber NICHT miteinander verknuepfte Felder auf getrennten
    Tabellen. Ein echter Kunde, dessen Mandat versehentlich (Tippfehler,
    Copy-Paste aus der Foundation-Doku) oder mutwillig diese Mandats-
    nummer traegt, wurde dadurch als KOMPLETTER Foundation-Client
    erkannt -- der naechste "Foundation-Demo-Purge" (routinemaessige
    Hygiene vor dem ersten echten Kunden) haette dessen gesamte Kunden-
    Historie (alle Mandate, Vermoegen, Cashflows, Ziele) unwiderruflich
    geloescht, nicht nur das eine kollidierende Mandat.

    Ein Mandat mit exakt dieser reservierten Nummer bleibt weiterhin Teil
    des mandate_ids-Scopes (siehe _load_scope, eigener, unabhaengiger
    Match auf mandate_number) -- nur die Ausweitung auf den GESAMTEN
    besitzenden Client entfaellt."""
    return _select_ids(
        db,
        "clients",
        "id",
        "client_number = :client_number",
        {"client_number": FOUNDATION_CLIENT_NUMBER},
    )


def _is_foundation_client(db: Session, client_id: str) -> bool:
    return client_id in _foundation_client_ids(db)


def _app_env() -> str:
    return str(getattr(settings, "app_env", "") or "").strip().lower()


def _table_exists(db: Session, table: str) -> bool:
    """Kontrollrunde 2026-09-21 (Foundation-Purge-Audit): vorher direkt
    gegen sqlite_master abgefragt -- crashte mit ProgrammingError auf jedem
    Postgres-Backend (Tier 2/3 gemaess config.py fuer app_env in
    {'staging','production'} vorausgesetzt, aber PRODUCTION_BLOCK_DETAIL
    sagt explizit "Nicht-Produktionsdatenbanken", also z.B. eine lokale
    Postgres-Entwicklungsinstanz). sqlalchemy.inspect() ist dialekt-
    agnostisch und funktioniert identisch fuer SQLite UND Postgres."""
    return table in sa_inspect(db.get_bind()).get_table_names()


def _columns(db: Session, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {col["name"] for col in sa_inspect(db.get_bind()).get_columns(table)}


def _select_ids(
    db: Session,
    table: str,
    id_column: str,
    where_sql: str,
    params: dict[str, Any],
) -> list[str]:
    cols = _columns(db, table)
    if id_column not in cols:
        return []
    sql = f"SELECT DISTINCT {_quote_ident(id_column)} FROM {_quote_ident(table)} WHERE {where_sql}"
    return [str(row[0]) for row in db.execute(text(sql), params).all() if row[0]]


def _select_ids_by_in(db: Session, table: str, id_column: str, filter_column: str, values: list[str]) -> list[str]:
    cols = _columns(db, table)
    if id_column not in cols or filter_column not in cols or not values:
        return []
    clause, params = _in_params(filter_column, values)
    sql = (
        f"SELECT DISTINCT {_quote_ident(id_column)} FROM {_quote_ident(table)} "
        f"WHERE {_quote_ident(filter_column)} IN ({clause})"
    )
    return [str(row[0]) for row in db.execute(text(sql), params).all() if row[0]]


def _delete_in(
    deleted: dict[str, int],
    db: Session,
    table: str,
    column: str,
    values: list[str],
) -> None:
    cols = _columns(db, table)
    if column not in cols or not values:
        return
    clause, params = _in_params(column, values)
    result = db.execute(
        text(f"DELETE FROM {_quote_ident(table)} WHERE {_quote_ident(column)} IN ({clause})"),
        params,
    )
    count = int(result.rowcount or 0)
    if count:
        deleted[table] = deleted.get(table, 0) + count


def _update_null(db: Session, table: str, column: str, filter_column: str, values: list[str]) -> None:
    cols = _columns(db, table)
    if column not in cols or filter_column not in cols or not values:
        return
    clause, params = _in_params(filter_column, values)
    db.execute(
        text(
            f"UPDATE {_quote_ident(table)} SET {_quote_ident(column)} = NULL "
            f"WHERE {_quote_ident(filter_column)} IN ({clause})"
        ),
        params,
    )


def _in_params(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    params = {f"{prefix}_{i}": value for i, value in enumerate(values)}
    return ", ".join(f":{key}" for key in params), params


def _merge_unique(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                out.append(value)
    return out


def _quote_ident(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return '"' + identifier + '"'
