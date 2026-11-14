"""CCX-02 / CCX-P1: Effective-Input-Manifest eines Beratungsentscheids.

Jede wirkende Inputgruppe bekommt einen domaenenseparierten Kind-Hash
(``ares/advisory-envelope/1/<gruppe>``) ueber die fachlich sortierte
Projektion ihrer Zeilen; das Manifest bindet alle zehn Gruppen plus
Engine-Version, Zufallsstrom und ``rounding_policy_version`` und hat selbst
einen Kind-Hash (``effective-input-manifest``). Jede Aenderung einer
wirkenden Policy, CMA, Restriktion, eines Ziels, Cashflows, Profils, einer
Praeferenz oder eines Bestands aendert damit den Manifest-Hash (CCX-02).

Gruppen und Quelle (je Mandat, nur aktive/nicht geloeschte Zeilen):

* ``client``      -- Kundenzeile des Mandats
* ``mandate``     -- Mandatszeile
* ``goals``       -- Ziele, sortiert ``(priority=rank, due_date=target_date, id)``
* ``cashflows``   -- Cashflows und Zufluesse des Kunden
* ``risk``        -- das Risikoprofil, auf dem die Allokation beruht
* ``preference``  -- alle Nachhaltigkeitspraeferenz-Versionen (append-only)
* ``cma``         -- die CMA des Laufs
* ``policy``      -- Optimizer-Policy der Allokation + gebundene CMA-Policy
* ``constraints`` -- wirkende Restriktionen/Praeferenz-Snapshot der Allokation
* ``holdings``    -- Bestaende, sortiert ``(custodian_id, depot_id, position_id)``

``updated_at`` ist bewusst nicht Teil der Projektion: identische Inhalte
ergeben identische Hashes. Gleitkomma-Spalten werden als exakte
Dezimal-Zeichenkette gebunden (core/advisory_envelope_codec.py).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from core.advisory_envelope_codec import (
    MANIFEST_COMPONENTS,
    MANIFEST_SCHEMA_VERSION,
    manifest_hash,
    none_sort_key,
    rows_child_hash,
)
from core.presentation_rounding import ROUNDING_POLICY_VERSION
from models.allocation import CapitalMarketAssumption, OptimizerPolicy
from models.clients import Client
from models.cma_policy import CmaPolicy
from models.mandates import Mandate
from models.profiling import InvestmentPreferenceDecision, RiskAssessment
from models.review import RecommendationHolding
from models.wealth import Cashflow, Goal, WealthInflow, WealthPosition

_EXCLUDED_COLUMNS = frozenset({"updated_at"})
# Kurzname (Adapter CCX-02) -> Manifest-Feld.
_SHORT_NAMES = {name[: -len("_hash")]: name for name in MANIFEST_COMPONENTS}
_SCALARS = ("tenant_id", "mandate_id", "engine_version", "random_stream_id", "rounding_policy_version")


def build_effective_input_record(components: Mapping[str, Any]) -> dict[str, Any]:
    """Kanonischer Manifest-Datensatz aus Komponenten (Kurz- oder Feldnamen).

    Unbekannte Komponenten sind ein Fehler; eine nicht gelieferte Komponente
    wird als explizites ``null`` gebunden (nie still weggelassen)."""
    record: dict[str, Any] = {"schema_version": MANIFEST_SCHEMA_VERSION}
    record.update({name: None for name in _SCALARS[:2]})
    record.update({name: None for name in MANIFEST_COMPONENTS})
    record.update({name: None for name in _SCALARS[2:]})
    for key, value in components.items():
        field = _SHORT_NAMES.get(key, key)
        if field not in record or field == "schema_version":
            raise ValueError(f"Unbekannte Manifest-Komponente: {key!r}")
        record[field] = value
    return record


def build_effective_input_hash(components: Mapping[str, Any]) -> str:
    """Manifest-Hash ueber alle wirkenden Inputs (Adapter CCX-02)."""
    return manifest_hash(build_effective_input_record(components))


# ── Projektion der Datenbankzeilen ───────────────────────────────────────────


def _columns(model: Any) -> list[str]:
    return [attr.key for attr in sa_inspect(model).column_attrs if attr.key not in _EXCLUDED_COLUMNS]


def _active(query, model):
    if hasattr(model, "deleted_at"):
        query = query.filter(model.deleted_at.is_(None))
    return query


def _hash_rows(kind: str, model: Any, rows: Sequence[Any], sort_fields: Sequence[str]) -> str:
    return rows_child_hash(
        kind, _columns(model), list(rows),
        lambda row: tuple(none_sort_key(getattr(row, name)) for name in sort_fields),
    )


def _combine(kind: str, parts: Mapping[str, str]) -> str:
    names = list(parts)
    return rows_child_hash(kind, names, [dict(parts)], lambda _row: ())


def _by_id(db: Session, model: Any, row_id: Any) -> list[Any]:
    if not row_id:
        return []
    row = db.query(model).filter(model.id == str(row_id)).first()
    return [row] if row is not None else []


def collect_effective_input_components(
    db: Session, *, mandate: Any, run: Any, target_allocation: Any,
) -> dict[str, str]:
    """Kind-Hash je Inputgruppe (zehn Manifest-Komponenten), frisch gelesen."""
    ta = target_allocation
    mandate_id = str(mandate.id)
    client_id = str(mandate.client_id)

    goals = _active(db.query(Goal).filter(Goal.mandate_id == mandate_id), Goal).all()
    cashflows = _active(db.query(Cashflow).filter(Cashflow.client_id == client_id), Cashflow).all()
    inflows = _active(db.query(WealthInflow).filter(WealthInflow.client_id == client_id), WealthInflow).all()
    positions = _active(
        db.query(WealthPosition).filter(WealthPosition.client_id == client_id), WealthPosition,
    ).all()
    run_holdings = _active(
        db.query(RecommendationHolding).filter(RecommendationHolding.run_id == str(run.id)),
        RecommendationHolding,
    ).all()
    preferences = (
        db.query(InvestmentPreferenceDecision)
        .filter(InvestmentPreferenceDecision.mandate_id == mandate_id)
        .all()
    )
    risk_id = getattr(ta, "based_on_assessment_id", None) or getattr(run, "assessment_id", None)
    cma_id = getattr(run, "capital_market_assumptions_id", None) or getattr(
        ta, "capital_market_assumptions_id", None,
    )
    policy_id = getattr(ta, "policy_id", None) or getattr(run, "policy_id", None)
    constraint_columns = (
        "id", "version", "effective_constraints_json", "preferences_json", "allocation_context_hash",
        "input_snapshot_hash", "reserve_funding_ledger_hash", "pension_transfer_ledger_snapshot_json",
        "band_equities_min_bps", "band_equities_max_bps", "band_bonds_min_bps", "band_bonds_max_bps",
        "band_real_estate_min_bps", "band_real_estate_max_bps", "band_alternatives_min_bps",
        "band_alternatives_max_bps", "band_liquidity_min_bps", "band_liquidity_max_bps",
        "valuation_date",
    )
    constraints_rows = (
        [{name: getattr(ta, name, None) for name in constraint_columns}] if ta is not None else []
    )
    return {
        "client_hash": _hash_rows("client", Client, _by_id(db, Client, client_id), ("id",)),
        "mandate_hash": _hash_rows("mandate", Mandate, _by_id(db, Mandate, mandate_id), ("id",)),
        "goals_hash": _hash_rows("goals", Goal, goals, ("rank", "target_date", "id")),
        "cashflows_hash": _combine("cashflows", {
            "cashflows": _hash_rows("cashflow-rows", Cashflow, cashflows, ("id",)),
            "inflows": _hash_rows("inflow-rows", WealthInflow, inflows, ("id",)),
        }),
        "risk_hash": _hash_rows("risk", RiskAssessment, _by_id(db, RiskAssessment, risk_id), ("id",)),
        "preference_hash": _hash_rows(
            "preference", InvestmentPreferenceDecision, preferences, ("sequence_no", "id"),
        ),
        "cma_hash": _hash_rows("cma", CapitalMarketAssumption, _by_id(db, CapitalMarketAssumption, cma_id), ("id",)),
        "policy_hash": _combine("policy", {
            "optimizer_policy": _hash_rows(
                "optimizer-policy", OptimizerPolicy, _by_id(db, OptimizerPolicy, policy_id), ("id",),
            ),
            "cma_policy": _hash_rows(
                "cma-policy", CmaPolicy, _by_id(db, CmaPolicy, getattr(run, "cma_policy_row_id", None)), ("id",),
            ),
        }),
        "constraints_hash": rows_child_hash(
            "constraints", list(constraint_columns), constraints_rows, lambda row: (str(row["id"]),),
        ),
        "holdings_hash": _combine("holdings", {
            "positions": _hash_rows(
                "position-rows", WealthPosition, positions, ("depot_bank", "depot_account_number", "id"),
            ),
            "run_holdings": _hash_rows(
                "run-holding-rows", RecommendationHolding, run_holdings,
                ("depot_bank", "custody_account_number", "id"),
            ),
        }),
    }


def engine_version_of(run: Any, target_allocation: Any) -> str:
    version = str(getattr(run, "optimizer_version", None) or "").strip()
    method = str(getattr(target_allocation, "optimization_method", None) or "").strip()
    return f"optimizer={version or 'unknown'};method={method or 'unknown'}"


def random_stream_id_of(target_allocation: Any) -> str:
    """Zufallsstrom der Allokation, wie gespeichert (P6 versioniert den
    vollstaendigen CRN-Vertrag); ein fehlender Seed bleibt sichtbar."""
    seed = getattr(target_allocation, "optimization_seed", None)
    method = str(getattr(target_allocation, "optimization_method", None) or "").strip() or "unknown"
    return f"{method}:seed={seed if seed is not None else 'none'}"


def build_manifest_record(
    *, tenant_id: str, mandate_id: str, components: Mapping[str, str], run: Any, target_allocation: Any,
) -> dict[str, Any]:
    record = build_effective_input_record({
        "tenant_id": tenant_id,
        "mandate_id": mandate_id,
        **components,
        "engine_version": engine_version_of(run, target_allocation),
        "random_stream_id": random_stream_id_of(target_allocation),
        "rounding_policy_version": ROUNDING_POLICY_VERSION,
    })
    missing = [name for name in MANIFEST_COMPONENTS if not record.get(name)]
    if missing:
        raise ValueError(f"Manifest unvollstaendig: {missing}")
    return record


__all__ = [
    "build_effective_input_hash",
    "build_effective_input_record",
    "build_manifest_record",
    "collect_effective_input_components",
    "engine_version_of",
    "random_stream_id_of",
]
