"""MANUAL-SAVE-DEADEND-001 (2026-10-14): manueller Speicherpfad der Soll-Allokation.

``POST /mandates/{id}/target-allocation`` (React-AllocationEditor) schrieb
einen ``manual_override_v1``-Datensatz, den
``services.portfolio_engine._verified_persisted_allocation_context`` nie
akzeptierte (Methode/Status-Spalten leer, unbekannte Engine-Version, keine
Bucket-Risikokoeffizienten, anders geformter Context-Hash, Input-Snapshot aus
den Targets statt aus Vermoegen/Cashflows/Zielen). Weil die vorherige
Allokation zu diesem Zeitpunkt bereits auf ``is_current=0`` stand, endeten
Payload, Empfehlung, Finalisierung und Strategie-PDFs in einer Sackgasse.

Dieser Baustein baut den Kandidaten aus denselben Bausteinen wie Generate:

* Sub-Allokationen ueber ``_build_sub_allocations`` (bzw. unveraendert aus
  der vorherigen Allokation, wenn die Quoten identisch sind) und
  ``_enrich_sub_allocations_with_risk`` -> ``risky_fraction_per_bucket_bps``
  und die Portfolio-Risky-Fraction sind serverseitig berechnet,
* ``input_snapshot_hash`` ueber exakt den Rebuild-Code, der spaeter ueber
  "veraltet" entscheidet (``compute_live_allocation_anchors``) -- eine
  Vermoegensaenderung macht den manuellen Datensatz also genauso stale wie
  einen generierten,
* ``allocation_context_hash`` ueber ``allocation_context_hash_for`` (dieselbe
  Funktion, die Generate und der Verifier benutzen).

Der Kandidat wird VOR jeder Aenderung am Bestand mit dem Verifier geprueft.
Der Aufrufer (Router) demoted die vorherige Allokation erst danach.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from core.evidence import canonical_json
from database import new_uuid
from models.allocation import (
    CapitalMarketAssumption,
    OptimizerPolicy,
    TargetAllocation,
)
from models.mandates import Mandate
from models.profiling import RiskAssessment
from services.valuation_clock import valuation_date
from services.reserve_funding_ledger_snapshot import (
    CONSTRAINTS_KEY as LEDGER_CONSTRAINTS_KEY,
    ledger_reference,
    ledger_snapshot_columns,
)


class ManualAllocationRejected(ValueError):
    """Fachliche Ablehnung des manuellen Speicherns (Router -> 409)."""


_HOUSE_BAND_ATTRS = {
    "equities": ("equity_min_bps", "equity_max_bps"),
    "bonds": ("bonds_min_bps", "bonds_max_bps"),
    "real_estate": ("real_estate_min_bps", "real_estate_max_bps"),
    "alternatives": ("alt_min_bps", "alt_max_bps"),
    "liquidity": ("liq_min_bps", "liq_max_bps"),
}


@dataclass
class ManualAllocationCandidate:
    allocation: TargetAllocation
    warnings: list[str] = field(default_factory=list)
    house_band_deviations: list[dict] = field(default_factory=list)
    risky_fraction_bps: int = 0
    risk_budget_bps: int = 0


def _pct(bps: int) -> str:
    return f"{int(bps) / 100:.2f}"


def _targets_of(allocation: TargetAllocation) -> dict[str, int]:
    from services.portfolio_engine import BUCKET_FIELDS

    return {
        bucket: int(getattr(allocation, f"target_{bucket}_bps") or 0)
        for bucket in BUCKET_FIELDS
    }


def _bands_of(allocation: TargetAllocation) -> dict[str, list[int]]:
    from services.portfolio_engine import BUCKET_FIELDS

    return {
        bucket: [
            int(getattr(allocation, f"band_{bucket}_min_bps") or 0),
            int(getattr(allocation, f"band_{bucket}_max_bps") or 0),
        ]
        for bucket in BUCKET_FIELDS
    }


def allocation_audit_snapshot(allocation: TargetAllocation | None) -> dict | None:
    """Kompakter alt/neu-Zustand fuer das Audit-Log."""
    if allocation is None:
        return None
    return {
        "allocation_id": str(allocation.id),
        "version": int(allocation.version or 0),
        "optimization_method": getattr(allocation, "optimization_method", None),
        "targets_bps": _targets_of(allocation),
        "bands_bps": _bands_of(allocation),
        "risky_fraction_bps": getattr(
            allocation, "risky_fraction_bps_at_generation", None
        ),
        "risk_budget_bps": getattr(
            allocation, "risk_budget_bps_at_generation", None
        ),
    }


def house_band_deviations(
    house_matrix,
    bounds_bps: dict[str, tuple[int, int]],
) -> list[dict]:
    """Jede manuelle Bandbreite, die die Hausmatrix-Zeile des Profils
    verlaesst (Untergrenze tiefer oder Obergrenze hoeher). Keine Ablehnung --
    das Risikobudget ist die harte Grenze, die Hausmatrix-Baender sind die
    Hausvorgabe, deren Abweichung ausgewiesen werden muss."""
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS

    rows: list[dict] = []
    for bucket in BUCKET_FIELDS:
        min_attr, max_attr = _HOUSE_BAND_ATTRS[bucket]
        house_min = int(getattr(house_matrix, min_attr))
        house_max = int(getattr(house_matrix, max_attr))
        manual_min, manual_max = (int(v) for v in bounds_bps[bucket])
        if manual_min < house_min or manual_max > house_max:
            rows.append(
                {
                    "bucket": bucket,
                    "label": BUCKET_LABELS[bucket],
                    "house_min_bps": house_min,
                    "house_max_bps": house_max,
                    "manual_min_bps": manual_min,
                    "manual_max_bps": manual_max,
                }
            )
    return rows


def _deviation_note(row: dict, profile_name: str, score_bucket: int) -> str:
    return (
        f"{row['label']}: manuelle Bandbreite "
        f"{_pct(row['manual_min_bps'])}–{_pct(row['manual_max_bps'])} % liegt "
        f"ausserhalb der Hausmatrix-Bandbreite "
        f"{_pct(row['house_min_bps'])}–{_pct(row['house_max_bps'])} % "
        f"(Profil {profile_name}, Score {score_bucket})."
    )


def assert_manual_allocation_has_basis(
    db: Session,
    mandate: Mandate,
    cma: CapitalMarketAssumption,
) -> None:
    """``_assert_allocation_has_basis`` auf denselben Eingaben wie Generate
    (``_load_allocation_inputs``). Wirft ``ManualAllocationRejected`` mit der
    unveraenderten deutschen Generate-Meldung ("Keine Vermögensbasis: ...")."""
    from services.portfolio_engine import (
        _assert_allocation_has_basis,
        _load_allocation_inputs,
    )

    try:
        inputs = _load_allocation_inputs(db, mandate, simulation_prefs={}, cma=cma)
        _assert_allocation_has_basis(
            int(inputs["advisory_wealth_rappen"]),
            int(inputs["recurring_income_rappen"]),
            int(inputs["recurring_expense_rappen"]),
            int(inputs["capital_inflow_rappen"]),
            int(inputs["capital_outflow_rappen"]),
        )
    except ValueError as exc:
        raise ManualAllocationRejected(str(exc)) from exc


def compute_live_allocation_anchors(
    db: Session,
    *,
    mandate: Mandate,
    allocation: TargetAllocation,
    policy: OptimizerPolicy,
    cma: CapitalMarketAssumption,
    assessment: RiskAssessment,
) -> dict:
    """Live-Input-Anker (input_snapshot_hash, Vermoegen, Reserve) fuer einen
    noch nicht versiegelten Kandidaten -- berechnet von genau dem Code, der
    beim Laden ueber "veraltet" entscheidet.

    ``build_target_payload_from_allocation(..., _live_anchor_probe=True)``:
    der Kandidat ist noch nicht versiegelt (sein Context-Hash kann nicht vor
    seinem Input-Snapshot-Hash existieren), deshalb wird die
    Kontext-Verifikation uebersprungen, und die Funktion liefert die
    Live-Anker genau an der Stelle zurueck, an der die Stale-Pruefung sie
    vergleichen wuerde."""
    from services.portfolio_engine import build_target_payload_from_allocation

    return build_target_payload_from_allocation(
        db=db,
        mandate=mandate,
        allocation=allocation,
        policy=policy,
        cma=cma,
        assessment=assessment,
        preferences=None,
        _live_anchor_probe=True,
    )


def _manual_preferences(previous: TargetAllocation | None, mandate: Mandate) -> dict:
    """Praeferenzen der vorherigen Allokation (Simulation, Reserve-Vorgaben,
    Baustein-Wahl) bleiben gueltig; nur die Band-Praeferenzen nicht -- die
    Bandbreiten setzt hier der Berater, sie stehen in den typisierten Spalten."""
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _merge_mandate_defaults_into_prefs,
        _normalize_preferences,
    )

    prefs = _normalize_preferences(_allocation_snapshot_preferences(previous))
    prefs["bands"] = _normalize_preferences(None)["bands"]
    return _merge_mandate_defaults_into_prefs(prefs, mandate)


def _reusable_previous_sub_allocations(
    previous: TargetAllocation | None,
    *,
    targets: dict[str, int],
    policy: OptimizerPolicy,
    cma: CapitalMarketAssumption,
) -> list[dict] | None:
    """Identische Quoten -> die verifizierte Produktaufteilung der vorherigen
    Allokation bleibt unveraendert (sonst wuerde schon das reine
    Wiederspeichern die Risky Fraction verschieben)."""
    from services.portfolio_engine import _verified_persisted_allocation_context

    if previous is None or _targets_of(previous) != targets:
        return None
    if str(previous.policy_id) != str(policy.id):
        return None
    if str(getattr(previous, "capital_market_assumptions_id", "") or "") != str(cma.id):
        return None
    bands = _bands_of(previous)
    try:
        sub_allocations, _constraints = _verified_persisted_allocation_context(
            previous,
            targets=targets,
            minimums={bucket: bands[bucket][0] for bucket in bands},
            maximums={bucket: bands[bucket][1] for bucket in bands},
        )
    except ValueError:
        return None
    return sub_allocations


def build_manual_target_allocation(
    db: Session,
    *,
    mandate: Mandate,
    policy: OptimizerPolicy,
    cma: CapitalMarketAssumption,
    assessment: RiskAssessment,
    previous: TargetAllocation | None,
    targets_bps: dict[str, int],
    bounds_bps: dict[str, tuple[int, int]],
    reason: str,
    user_id: str,
    now: str,
) -> ManualAllocationCandidate:
    """Baut und verifiziert den manuellen Kandidaten, ohne den Bestand zu
    veraendern. Wirft ``ManualAllocationRejected`` bei fachlicher Ablehnung
    (Risikobudget, fehlende Referenzdaten, nicht verifizierbarer Kontext)."""
    from services.jurisdiction.resolve import resolve_mandate_jurisdiction
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        StaleAllocationInputError,
        _risk_score_bucket,
        _sub_class_intra_correlation_x100,
        _verified_persisted_allocation_context,
        allocation_context_hash_for,
    )
    from services.portfolio_engine_allocation_integrity import (
        MANUAL_OVERRIDE_ENGINE_VERSION,
        MANUAL_OVERRIDE_METHOD,
        MANUAL_OVERRIDE_STATUS,
    )
    from services.portfolio_engine_house_matrix import (
        _build_sub_allocations,
        _building_block_risky_map,
        _enrich_sub_allocations_with_risk,
        _house_matrix_or_default,
    )
    from services.risk_matrix import max_risky_fraction_for_mandate

    jurisdiction = resolve_mandate_jurisdiction(mandate)
    universe = getattr(mandate, "investment_universe", None)
    # MANUAL-SAVE-BASIS-001 (Owner-Entscheid 2026-10-14): dieselbe
    # Datenbasis-Regel wie Generate und Sensitivitaet -- ohne
    # Beratungsvermoegen UND ohne Cashflows keine Soll-Allokation, auch keine
    # manuelle. Vor allen anderen fachlichen Pruefungen, damit ein leeres
    # Mandat die ehrliche Meldung bekommt und nicht z.B. "Risikobudget".
    assert_manual_allocation_has_basis(db, mandate, cma)
    try:
        score_bucket = _risk_score_bucket(assessment)
        house_matrix = _house_matrix_or_default(db, policy, score_bucket)
        # Dieselbe Obergrenze wie Generate (risk_budget_bps_at_generation) und
        # wie die Finalisierungs-/Lock-Pruefungen.
        risk_budget_bps = int(
            max_risky_fraction_for_mandate(db, mandate, assessment, policy)
        )
        prefs = _manual_preferences(previous, mandate)
        sub_allocations = _reusable_previous_sub_allocations(
            previous, targets=targets_bps, policy=policy, cma=cma,
        )
        if sub_allocations is None:
            sub_allocations = _build_sub_allocations(
                dict(targets_bps), prefs, jurisdiction=jurisdiction, db=db,
            )
        risky_map = _building_block_risky_map(db, policy.id, universe, jurisdiction)
        sub_allocations, bucket_risky_bps, risky_fraction_bps = (
            _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
        )
    except ValueError as exc:
        raise ManualAllocationRejected(str(exc)) from exc

    if int(risky_fraction_bps) > int(risk_budget_bps):
        raise ManualAllocationRejected(
            "Manuelle Soll-Allokation überschreitet das Risikobudget des "
            f"Risikoprofils: Risikoanteil {_pct(risky_fraction_bps)} % > "
            f"Risikobudget {_pct(risk_budget_bps)} % (Profil "
            f"{house_matrix.profile_name}, Score {score_bucket}). Bitte den "
            "Anteil risikobehafteter Anlageklassen reduzieren oder die "
            "Strategie neu berechnen. Es wurde nichts gespeichert."
        )

    deviations = house_band_deviations(house_matrix, bounds_bps)
    deviation_notes = [
        _deviation_note(row, house_matrix.profile_name, score_bucket)
        for row in deviations
    ]
    reasoning = [
        f"Manuell gesetzte Soll-Allokation (Berater). Begründung: {reason}",
        (
            f"Risikoanteil {_pct(risky_fraction_bps)} % innerhalb des "
            f"Risikobudgets {_pct(risk_budget_bps)} % "
            f"(Profil {house_matrix.profile_name}, Score {score_bucket})."
        ),
        *deviation_notes,
    ]

    effective_constraints = {
        "engine_version": MANUAL_OVERRIDE_ENGINE_VERSION,
        "bounds_bps": {
            bucket: [int(bounds_bps[bucket][0]), int(bounds_bps[bucket][1])]
            for bucket in BUCKET_FIELDS
        },
        "risk_budget_bps": int(risk_budget_bps),
        "risky_fraction_per_bucket_bps": {
            bucket: int(bucket_risky_bps.get(bucket, 0) or 0)
            for bucket in BUCKET_FIELDS
        },
        "active_method": MANUAL_OVERRIDE_METHOD,
        "active_status": MANUAL_OVERRIDE_STATUS,
        # SUBRISK-CONTEXT-REPLAY-001 (2026-10-10): die abgeleiteten
        # Bucket-Risikozahlen haengen an rho, auch wenn die Quoten manuell sind.
        "sub_class_intra_correlation_x100": _sub_class_intra_correlation_x100(),
        "manual_override": {
            "reason": reason,
            "house_matrix_profile": house_matrix.profile_name,
            "score_bucket": int(score_bucket),
            "house_band_deviations": deviations,
            "previous_allocation_id": (
                str(previous.id) if previous is not None else None
            ),
        },
    }
    candidate = TargetAllocation(
        id=new_uuid(),
        mandate_id=mandate.id,
        version=(int(previous.version or 0) if previous is not None else 0) + 1,
        is_current=1,
        # ADR-1b: ein manueller Datensatz ist ein eigener Lauf mit eigenem
        # Bewertungsstichtag (heute bzw. der gebundene Stichtag). Er geht wie
        # bei Generate in den Input-Hash ein, und Reload/Verifier binden ihn.
        valuation_date=valuation_date().isoformat(),
        policy_id=policy.id,
        based_on_assessment_id=assessment.id,
        capital_market_assumptions_id=cma.id,
        set_by=user_id,
        set_at=now,
        created_at=now,
        updated_at=now,
        risky_fraction_bps=int(risky_fraction_bps),
        risky_fraction_bps_at_generation=int(risky_fraction_bps),
        risk_budget_bps_at_generation=int(risk_budget_bps),
        sub_allocations_json=canonical_json(sub_allocations),
        effective_constraints_json=canonical_json(effective_constraints),
        context_artifacts_required=1,
        preferences_json=json.dumps(prefs, sort_keys=True, default=str),
        optimization_method=MANUAL_OVERRIDE_METHOD,
        optimization_status=MANUAL_OVERRIDE_STATUS,
        optimizer_reasoning_json=json.dumps(
            reasoning, separators=(",", ":"), ensure_ascii=False,
        ),
        **{f"target_{bucket}_bps": int(targets_bps[bucket]) for bucket in BUCKET_FIELDS},
        **{
            f"band_{bucket}_min_bps": int(bounds_bps[bucket][0])
            for bucket in BUCKET_FIELDS
        },
        **{
            f"band_{bucket}_max_bps": int(bounds_bps[bucket][1])
            for bucket in BUCKET_FIELDS
        },
    )

    try:
        anchors = compute_live_allocation_anchors(
            db,
            mandate=mandate,
            allocation=candidate,
            policy=policy,
            cma=cma,
            assessment=assessment,
        )
    except StaleAllocationInputError as exc:  # pragma: no cover - defensiv
        raise ManualAllocationRejected(str(exc)) from exc
    except ValueError as exc:
        raise ManualAllocationRejected(
            "Die Eingaben dieses Mandats (Vermögen, Cashflows, Ziele) lassen "
            f"sich nicht als Strategie-Anker auswerten: {exc}"
        ) from exc
    candidate.input_snapshot_hash = anchors["input_snapshot_hash"]
    candidate.advisory_wealth_at_generation_rappen = anchors["advisory_wealth_rappen"]
    candidate.total_wealth_at_generation_rappen = anchors["total_wealth_rappen"]
    candidate.reserve_needed_at_generation_rappen = anchors["reserve_needed_rappen"]
    candidate.external_reserve_at_generation_rappen = anchors["external_reserve_rappen"]
    # PENSION-TRANSFER-LEDGER-001: derselbe Vorsorge-Transfer-Snapshot wie
    # Generate (aus der Live-Foundation des Ankers), Referenz im gehashten
    # Context.
    from services.pension_transfer_ledger_snapshot import bind_pension_transfer_ledger_snapshot

    candidate.pension_transfer_ledger_snapshot_json = bind_pension_transfer_ledger_snapshot(
        effective_constraints, anchors.get("external_foundation_projection"),
    )
    # RESERVE-LEDGER-SNAPSHOT-001: auch der manuelle Anker speichert den
    # Reserve-Funding-Ledger, den der Reload sonst live neu kompilieren muesste,
    # und bindet seine Referenz im gehashten Context. Die Constraints werden
    # nach beiden Bindungen einmal neu serialisiert.
    reserve_ledger = anchors["reserve_funding_ledger"]
    reserve_split = anchors.get("reserve_split")  # RESERVE-CEILING-001: Split-Snapshot mitpersistieren
    effective_constraints[LEDGER_CONSTRAINTS_KEY] = ledger_reference(reserve_ledger, reserve_split)
    candidate.effective_constraints_json = canonical_json(effective_constraints)
    for column, value in ledger_snapshot_columns(reserve_ledger, reserve_split).items():
        setattr(candidate, column, value)
    candidate.allocation_context_hash = allocation_context_hash_for(
        engine_version=MANUAL_OVERRIDE_ENGINE_VERSION,
        policy_id=candidate.policy_id,
        cma_id=candidate.capital_market_assumptions_id,
        assessment_id=candidate.based_on_assessment_id,
        input_snapshot_hash=candidate.input_snapshot_hash,
        preferences_json=candidate.preferences_json,
        targets=targets_bps,
        sub_allocations=sub_allocations,
        effective_constraints=effective_constraints,
        optimization_seed=None,
    )

    # Fail closed: was hier nicht verifiziert, wird nicht gespeichert -- und
    # die vorherige Allokation bleibt aktuell.
    try:
        _verified_persisted_allocation_context(
            candidate,
            targets=dict(targets_bps),
            minimums={bucket: int(bounds_bps[bucket][0]) for bucket in BUCKET_FIELDS},
            maximums={bucket: int(bounds_bps[bucket][1]) for bucket in BUCKET_FIELDS},
        )
    except ValueError as exc:
        raise ManualAllocationRejected(
            "Die manuelle Soll-Allokation wäre nicht verifizierbar und wurde "
            f"deshalb nicht gespeichert: {exc}"
        ) from exc

    return ManualAllocationCandidate(
        allocation=candidate,
        warnings=deviation_notes,
        house_band_deviations=deviations,
        risky_fraction_bps=int(risky_fraction_bps),
        risk_budget_bps=int(risk_budget_bps),
    )
