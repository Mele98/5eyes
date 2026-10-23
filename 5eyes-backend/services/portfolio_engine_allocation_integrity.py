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
from services.reserve_funding_ledger_snapshot import verify_persisted_ledger_snapshot


# MANUAL-SAVE-DEADEND-001 (2026-10-14): Vertrag des manuellen Speicherpfads
# (POST /mandates/{id}/target-allocation, React-AllocationEditor). Ein
# manueller Datensatz ist ein vollwertiger Allocation-Anker: dieselbe
# Hash-Form, dieselben Artefakte und derselbe Verifier wie Generate -- nur
# Methode/Status/Engine-Version sagen ehrlich, dass der Berater die Quoten
# gesetzt hat und kein Solver.
STOCHASTIC_ENGINE_VERSIONS = frozenset({"stochastic_core_v1", "stochastic_core_v2"})
MANUAL_OVERRIDE_ENGINE_VERSION = "manual_override_v1"
MANUAL_OVERRIDE_METHOD = "manual_override"
MANUAL_OVERRIDE_STATUS = "manual"


def allocation_context_hash_for(
    *,
    engine_version: str,
    policy_id,
    cma_id,
    assessment_id,
    input_snapshot_hash,
    preferences_json: str | None,
    targets: dict[str, int],
    sub_allocations: list[dict],
    effective_constraints: dict,
    optimization_seed,
) -> str:
    """Kanonischer allocation_context_hash -- EINE Form fuer Generate, den
    manuellen Speicherpfad und den Verifier.

    Vorher baute jeder Schreibpfad sein eigenes Hash-Dict; der manuelle Pfad
    liess preferences_json/optimization_seed weg und konnte deshalb vom
    Verifier nie bestaetigt werden.
    """
    from services.portfolio_engine import BUCKET_FIELDS

    payload = {
        "engine_version": str(engine_version),
        "policy_id": str(policy_id),
        "cma_id": str(cma_id),
        "assessment_id": str(assessment_id),
        "input_snapshot_hash": str(input_snapshot_hash),
        "preferences_json": preferences_json,
        "targets_bps": {
            bucket: int(targets[bucket]) for bucket in BUCKET_FIELDS
        },
        "sub_allocations": sub_allocations,
        "effective_constraints": effective_constraints,
        "optimization_seed": optimization_seed,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _verify_manual_override_contract(
    stored_constraints: dict,
    *,
    expected_method: str,
    expected_status: str,
    verified_total_risky_bps: int,
) -> None:
    """Zusatzpruefungen fuer ``engine_version == manual_override_v1``.

    Methode und Status muessen manuell sein (die Gleichheit von Spalte und
    Constraints prueft der Aufrufer bereits), die Begruendung muss vorliegen,
    und die verifizierte Risky Fraction darf das gehashte Risikobudget nicht
    ueberschreiten: der Schreibpfad lehnt genau das ab, ein solcher
    Datensatz kann also nur manipuliert sein.
    """
    if (
        expected_method != MANUAL_OVERRIDE_METHOD
        or expected_status != MANUAL_OVERRIDE_STATUS
    ):
        raise ValueError(
            "Manuelle Allocation-Engine-Version widerspricht der "
            "Optimierungsmethode/-status der TargetAllocation."
        )
    manual_block = stored_constraints.get("manual_override")
    if not isinstance(manual_block, dict) or not str(
        manual_block.get("reason") or ""
    ).strip():
        raise ValueError(
            "Manuelle Soll-Allokation ohne dokumentierte Begruendung."
        )
    budget = stored_constraints.get("risk_budget_bps")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise ValueError(
            "Manuelle Soll-Allokation ohne gueltiges Risikobudget."
        )
    if int(verified_total_risky_bps) > int(budget):
        raise ValueError(
            "Manuelle Soll-Allokation ueberschreitet das gehashte "
            "Risikobudget."
        )


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
        # RESERVE-LEDGER-SNAPSHOT-001: ohne gehashten Context ist ein evtl.
        # vorhandener Ledger-Snapshot ungebunden; der Reload behandelt ihn
        # deshalb als Legacy "unverifiable" (nie als Historical Replay).
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
    # PENSION-TRANSFER-LEDGER-001: gespeicherter Vorsorge-Transfer-Snapshot
    # und seine gehashte Referenz muessen gemeinsam vorliegen und passen.
    from services.pension_transfer_ledger_snapshot import (
        verify_bound_pension_transfer_ledger_snapshot,
    )

    verify_bound_pension_transfer_ledger_snapshot(allocation, stored_constraints)

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
    if (
        str(stored_constraints.get("engine_version") or "")
        == MANUAL_OVERRIDE_ENGINE_VERSION
        and getattr(allocation, "optimization_method", None) is None
    ):
        # Manuelle Datensaetze aus der Zeit vor MANUAL-SAVE-DEADEND-001
        # (2026-10-09..14) hatten nie Methode/Status-Spalten und sind nicht
        # nachtraeglich verifizierbar -- klare Handlungsanweisung statt des
        # generischen Spalten-Widerspruchs.
        raise ValueError(
            "Diese manuell gespeicherte Soll-Allokation stammt aus einem "
            "aelteren, nicht verifizierbaren Format. Bitte die Strategie neu "
            "berechnen oder die Allokation im Editor erneut speichern."
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
    if stored_engine_version in STOCHASTIC_ENGINE_VERSIONS:
        # Eine Engine-Allokation darf sich nie als manuelle Uebersteuerung
        # ausgeben (die Gegenrichtung prueft der manuelle Vertrag).
        if expected_method == MANUAL_OVERRIDE_METHOD:
            raise ValueError(
                "Persistierte Engine-Version widerspricht der manuellen "
                "Optimierungsmethode."
            )
    elif stored_engine_version == MANUAL_OVERRIDE_ENGINE_VERSION:
        _verify_manual_override_contract(
            stored_constraints,
            expected_method=expected_method,
            expected_status=expected_status,
            verified_total_risky_bps=int(verified_total_risky_bps),
        )
    else:
        raise ValueError(
            "Persistierte Allocation-Engine-Version ist unbekannt oder fehlt."
        )

    recomputed_context_hash = allocation_context_hash_for(
        engine_version=stored_engine_version,
        policy_id=allocation.policy_id,
        cma_id=allocation.capital_market_assumptions_id,
        assessment_id=allocation.based_on_assessment_id,
        input_snapshot_hash=allocation.input_snapshot_hash,
        preferences_json=allocation.preferences_json,
        targets=targets,
        sub_allocations=stored_sub_allocations,
        effective_constraints=stored_constraints,
        optimization_seed=getattr(allocation, "optimization_seed", None),
    )
    if recomputed_context_hash != str(stored_context_hash):
        raise ValueError(
            "Allocation-Context-Hash stimmt nicht mit den persistierten "
            "Entscheidungsartefakten ueberein."
        )
    # RESERVE-LEDGER-SNAPSHOT-001: Ledger-Hash aus den gespeicherten Zeilen
    # rekalkulieren und gegen Hash-Spalte + gehashte Referenz pruefen.
    verify_persisted_ledger_snapshot(allocation, stored_constraints)
    return stored_sub_allocations, stored_constraints


def _identical_previous_allocation(
    previous,
    *,
    allocation_context_hash: str,
    input_snapshot_hash: str,
    policy_id,
    cma_id,
    assessment,
    targets: dict,
    minimums: dict,
    maximums: dict,
) -> bool:
    """REGENERATE-IDEMPOTENT-001: ist die neue Allokation exakt die bisherige?

    Die Generierung ist deterministisch -- unveraenderte Eingaben ergeben
    exakt dieselbe Allokation (gleicher ``allocation_context_hash``). Frueher
    entstand trotzdem eine neue Version, die aktuelle wurde demotiert und
    eine bereits zertifizierte Final-Empfehlung verwaiste (409 "basiert nicht
    auf der aktuellen Soll-Allokation", unsichtbar im Kundenportal). Jetzt
    bleibt die bestehende Allokation aktuell (gleiche id/Version, unveraendert
    mit ihrem urspruenglichen Solver-Lauf verknuepft; der neue, identische
    Lauf wird trotzdem im Audit-Trail persistiert), wenn Hash,
    Input-Snapshot, Anker und alle Quoten/Baender identisch sind und das
    Risikoprofil seither nicht per Override geaendert wurde.
    """
    from services.portfolio_engine import BUCKET_FIELDS

    if previous is None:
        return False
    if int(getattr(previous, "context_artifacts_required", 0) or 0) != 1:
        return False
    if str(getattr(previous, "allocation_context_hash", "") or "") != str(allocation_context_hash):
        return False
    if str(getattr(previous, "input_snapshot_hash", "") or "") != str(input_snapshot_hash):
        return False
    if (
        str(getattr(previous, "policy_id", "") or "") != str(policy_id)
        or str(getattr(previous, "capital_market_assumptions_id", "") or "") != str(cma_id)
        or str(getattr(previous, "based_on_assessment_id", "") or "") != str(getattr(assessment, "id", ""))
    ):
        return False
    for bucket in BUCKET_FIELDS:
        if (
            int(getattr(previous, f"target_{bucket}_bps") or 0) != int(targets[bucket])
            or int(getattr(previous, f"band_{bucket}_min_bps") or 0) != int(minimums[bucket])
            or int(getattr(previous, f"band_{bucket}_max_bps") or 0) != int(maximums[bucket])
        ):
            return False
    # Ein Override nach der Generierung (gleiche Assessment-id, in place)
    # darf nie eine alte Allokation wiederbeleben.
    if int(getattr(assessment, "is_overridden", 0) or 0):
        override_at = str(getattr(assessment, "override_at", "") or "")
        created_at = str(getattr(previous, "created_at", "") or "")
        if not override_at or not created_at or override_at > created_at:
            return False
    return True
