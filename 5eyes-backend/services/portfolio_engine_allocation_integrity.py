"""Allocation-Integritaetspruefung: persistierte Entscheidungsartefakte.

ADR-014-Cluster-Submodul. Herausgeloest aus ``services/portfolio_engine.py``
(2026-10-14, ENGINE-LINE-BUDGET), damit die Audit-Fix-PRs #602-#616 ins
Zeilenbudget passen, ohne ``MAX_LINES`` anzuheben -- und weil die Fix-PRs zum
manuellen Speicherpfad (MANUAL-SAVE-DEADEND-001) genau diesen Verifier
erweitern: neue Integritaetslogik gehoert hierher, nicht zurueck in die
Kern-Datei.

``_verified_persisted_allocation_context()`` ist das Integritaets-Gate fuer
jede persistierte ``TargetAllocation``: die drei Artefakt-Spalten
(``sub_allocations_json``, ``effective_constraints_json``,
``allocation_context_hash``) werden strukturell, semantisch und per Hash
gegen die typisierten Spalten geprueft, bevor Payload-Rekonstruktion oder
Sensitivitaetsanalyse sie konsumieren.

Die Verschiebung ist verhaltensidentisch (Funktionskoerper byte-gleich).
``BUCKET_FIELDS``, ``_bucket_key`` und ``_enrich_sub_allocations_with_risk``
werden -- wie in ``portfolio_engine_house_matrix.py`` -- per Lazy-Import aus
``services.portfolio_engine`` aufgeloest: kein Zirkular-Import beim Laden, und
ein Monkeypatch dieser Namen auf ``services.portfolio_engine`` wirkt weiterhin
auch hier. ``portfolio_engine.py`` re-exportiert die Funktion, damit
bestehende Aufrufstellen (``build_target_payload_from_allocation``,
``evaluate_goal_sensitivity``) und Tests unveraendert bleiben.
"""

from __future__ import annotations

import hashlib
import json

from models.allocation import TargetAllocation


def _verified_persisted_allocation_context(
    allocation: TargetAllocation,
    *,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
) -> tuple[list[dict] | None, dict | None]:
    """Load decision artifacts only after structural, semantic, and hash checks.

    All three artifact columns are an atomic unit.  ``NULL`` in all three
    columns identifies a genuine legacy allocation; every other incomplete
    state is an integrity error.  Keeping this verification in one helper is
    important because both payload reconstruction and sensitivity analysis
    consume the stored optimizer context.
    """
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        _bucket_key,
        _enrich_sub_allocations_with_risk,
    )

    raw_sub_allocations = getattr(allocation, "sub_allocations_json", None)
    raw_constraints = getattr(allocation, "effective_constraints_json", None)
    stored_context_hash = getattr(allocation, "allocation_context_hash", None)
    artifact_values = (
        raw_sub_allocations,
        raw_constraints,
        stored_context_hash,
    )
    if all(value is None for value in artifact_values):
        if int(getattr(allocation, "context_artifacts_required", 0) or 0) == 1:
            raise ValueError(
                "Persistierter Allocation-Context fehlt vollstaendig, obwohl "
                "diese Engine-Allokation unveraenderliche Artefakte verlangt."
            )
        return None, None
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in artifact_values
    ):
        raise ValueError(
            "Persistierter Allocation-Context ist partiell oder unvollstaendig; "
            "Sub-Allokationen, Constraints und Hash muessen gemeinsam vorliegen."
        )

    try:
        parsed_sub_allocations = json.loads(raw_sub_allocations)
        if not isinstance(parsed_sub_allocations, list) or not all(
            isinstance(row, dict) for row in parsed_sub_allocations
        ):
            raise ValueError("sub_allocations_json must contain a list of objects")
        bucket_totals = {bucket: 0 for bucket in BUCKET_FIELDS}
        for row in parsed_sub_allocations:
            bucket = _bucket_key(row.get("asset_class"))
            weight = int(row.get("target_weight_bps") or 0)
            if bucket not in bucket_totals or weight < 0:
                raise ValueError("unknown bucket or negative sub-allocation weight")
            bucket_totals[bucket] += weight
        if bucket_totals != targets or sum(bucket_totals.values()) != 10000:
            raise ValueError(
                "stored sub-allocation does not reconcile to stored bucket weights"
            )
        stored_sub_allocations = [dict(row) for row in parsed_sub_allocations]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Persistierte Sub-Allokationen sind ungueltig oder nicht "
            "mit den Bucket-Zielen abstimmbar."
        ) from exc

    try:
        stored_constraints = json.loads(raw_constraints)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Persistierte effektive Allocation-Constraints sind ungueltig."
        ) from exc
    if not isinstance(stored_constraints, dict):
        raise ValueError(
            "Persistierte effektive Allocation-Constraints muessen ein Objekt sein."
        )

    stored_bounds = stored_constraints.get("bounds_bps")
    expected_bounds = {
        bucket: [int(minimums[bucket]), int(maximums[bucket])]
        for bucket in BUCKET_FIELDS
    }
    if stored_bounds != expected_bounds:
        raise ValueError(
            "Persistierte Constraint-Bounds widersprechen den typisierten "
            "Bandspalten der TargetAllocation."
        )
    typed_risk_budget = getattr(
        allocation, "risk_budget_bps_at_generation", None
    )
    if (
        typed_risk_budget is None
        or stored_constraints.get("risk_budget_bps") != int(typed_risk_budget)
    ):
        raise ValueError(
            "Persistiertes Risikobudget widerspricht der typisierten "
            "TargetAllocation-Spalte."
        )
    expected_method = str(
        getattr(allocation, "optimization_method", None) or "house_matrix"
    )
    expected_status = str(
        getattr(allocation, "optimization_status", None) or "house_matrix"
    )
    if str(stored_constraints.get("active_method")) != expected_method:
        raise ValueError(
            "Persistierte aktive Optimierungsmethode widerspricht der "
            "TargetAllocation-Spalte."
        )
    if str(stored_constraints.get("active_status")) != expected_status:
        raise ValueError(
            "Persistierter aktiver Optimierungsstatus widerspricht der "
            "TargetAllocation-Spalte."
        )
    stored_optimization_basis = stored_constraints.get(
        "optimization_model_basis"
    )
    if stored_optimization_basis is not None:
        if not isinstance(stored_optimization_basis, dict):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis muss ein Objekt sein."
            )
        is_shadow_candidate = str(
            stored_optimization_basis.get("basis_id")
        ) in {
            "stochastic_shadow_candidate_v1",
            "stochastic_shadow_candidate_v2",
        }
        if (
            not is_shadow_candidate
            and str(stored_optimization_basis.get("active_method"))
            != expected_method
        ):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis widerspricht der aktiven "
                "TargetAllocation-Methode."
            )

    # Recompute the exact bucket coefficients exclusively from the stored
    # canonical rows. The helper prioritizes each row's persisted risk
    # coefficient, so current BuildingBlocks cannot alter history.
    (
        _verified_rows,
        verified_bucket_risk_bps,
        verified_total_risky_bps,
    ) = _enrich_sub_allocations_with_risk(stored_sub_allocations, {})
    stored_bucket_risk_bps = stored_constraints.get(
        "risky_fraction_per_bucket_bps"
    )
    expected_bucket_risk_bps = {
        bucket: int(verified_bucket_risk_bps[bucket])
        for bucket in BUCKET_FIELDS
    }
    if stored_bucket_risk_bps != expected_bucket_risk_bps:
        raise ValueError(
            "Persistierte Bucket-Risikokoeffizienten widersprechen dem "
            "kanonischen Sub-Allokationsplan."
        )
    typed_total_risky_bps = getattr(
        allocation, "risky_fraction_bps_at_generation", None
    )
    if (
        typed_total_risky_bps is None
        or int(typed_total_risky_bps) != int(verified_total_risky_bps)
    ):
        raise ValueError(
            "Persistierte Portfolio-Risky-Fraction widerspricht dem "
            "gehashten Allocation-Context."
        )

    stored_engine_version = str(
        stored_constraints.get("engine_version") or ""
    )
    if stored_engine_version not in {
        "stochastic_core_v1",
        "stochastic_core_v2",
    }:
        raise ValueError(
            "Persistierte Allocation-Engine-Version ist unbekannt oder fehlt."
        )

    persisted_context_payload = {
        "engine_version": stored_engine_version,
        "policy_id": str(allocation.policy_id),
        "cma_id": str(allocation.capital_market_assumptions_id),
        "assessment_id": str(allocation.based_on_assessment_id),
        "input_snapshot_hash": str(allocation.input_snapshot_hash),
        "preferences_json": allocation.preferences_json,
        "targets_bps": {
            bucket: int(targets[bucket]) for bucket in BUCKET_FIELDS
        },
        "sub_allocations": stored_sub_allocations,
        "effective_constraints": stored_constraints,
        "optimization_seed": getattr(allocation, "optimization_seed", None),
    }
    recomputed_context_hash = hashlib.sha256(
        json.dumps(
            persisted_context_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if recomputed_context_hash != str(stored_context_hash):
        raise ValueError(
            "Allocation-Context-Hash stimmt nicht mit den persistierten "
            "Entscheidungsartefakten ueberein."
        )
    return stored_sub_allocations, stored_constraints
