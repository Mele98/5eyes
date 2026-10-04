"""RISK-BUDGET-FINALIZATION-001 (round 46 red test).

Audit-Befund (2026-10-04-risk-budget-fallback-context-and-finalization-
integrity-audit.md, nicht in diesem Worktree): ``services/mandate_lock_audit.
py::audit_mandate_editability`` berechnet einen harten Lock-Reason
``REASON_RISK_BUDGET_VIOLATED`` ("risk_budget_violated"), sobald die
risky-Fraktion einer TargetAllocation deren Risk-Budget uebersteigt (siehe
dort Zeile ~140-147: ``if int(risky) > int(budget): lock_reasons.append(...)``).

``routers/review.py::_validate_recommendation_for_finalization`` -- das
tatsaechliche Server-Gate, das ``finalize_recommendation`` (Zeile ~2671)
vor dem Setzen von ``result_status = "Final"`` aufruft -- prueft Draft-
Status, Risikoprofil-/Allokations-/Policy-/CMA-Aktualitaet, Kreuz-
referenzen und (ueber ``build_target_payload_from_allocation``) die interne
Selbst-Konsistenz des persistierten Allocation-Context (Hash, Sub-
Allokationen, Bucket-Bandbreiten). Es ENTHAELT ABER KEINEN Verweis auf
``risk_budget_violated`` oder ``mandate_lock_audit`` (grep in
routers/review.py: keine Treffer) und prueft an keiner Stelle, ob die
typisierte ``risky_fraction_bps_at_generation``-Spalte das typisierte
``risk_budget_bps_at_generation``-Budget uebersteigt. Eine Empfehlung,
deren verankerte Soll-Allokation das Risk-Budget krass verletzt, wird
deshalb klaglos finalisiert.

Dieser Test reproduziert das Szenario end-to-end mit einer REALEN, vom
Engine generierten Allokation (kein Mock):
1. Baut ein reales Mandat + eine reale TargetAllocation ueber den
   regulaeren Erzeugungsweg (generate_target_allocation), wie
   test_finalize_mandate_lock.py.
2. Senkt NUR das typisierte Risk-Budget (risk_budget_bps_at_generation)
   weit unter die vom Engine tatsaechlich berechnete risky-Fraktion --
   analog zur Audit-Groessenordnung (5627 vs. 100 bps; hier real generiert:
   siehe Testlauf-Log fuer den exakten Wert, typischerweise ca. 5900-6000
   bps gegen das erzwungene Budget von 100 bps). Die risky-Fraktion selbst
   bleibt unberuehrt -- sie stammt unveraendert vom Engine-Lauf.
3. Haelt den persistierten Allocation-Context (effective_constraints_json,
   allocation_context_hash) exakt in derselben Weise selbst-konsistent, wie
   es die Produktionslogik in services/portfolio_engine.py
   (_verified_persisted_allocation_context) beim naechsten Laden selbst
   nachrechnet -- NUR das Risikobudget-Feld wird mitsamt neu berechnetem
   Hash abgesenkt. Das stellt sicher, dass build_target_payload_from_
   allocation() keinen UNABHAENGIGEN Integritaetsfehler wirft und der
   einzige gepruefte Zustand tatsaechlich die Risk-Budget-Verletzung ist.
4. Verifiziert ueber den REALEN Lock-Audit-Entry-Point
   (``audit_mandate_editability``), dass das System diese Verletzung
   tatsaechlich als ``risk_budget_violated``-Lock erkennt (Sanity-Check,
   kein Bug -- mandate_lock_audit.py selbst funktioniert korrekt).
5. Ruft die reale ``finalize_recommendation``-Endpoint-Funktion auf einem
   sonst vollstaendig gueltigen Draft-Run auf, der exakt auf dieser
   verletzenden Allokation basiert.

Erwuenschtes Verhalten: finalize_recommendation muss ablehnen (HTTPException/
422), solange der risk_budget_violated-Lock fuer das Mandat aktiv ist.
Tatsaechliches Verhalten heute: kein Fehler, _validate_recommendation_for_
finalization liefert eine leere errors-Liste, der Run wird klaglos "Final".
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401
from database import new_uuid
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from routers.review import finalize_recommendation
from services.mandate_lock_audit import (
    REASON_RISK_BUDGET_VIOLATED,
    audit_mandate_editability,
)
from services.portfolio_engine import BUCKET_FIELDS, generate_target_allocation
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


# Erzwungenes Risk-Budget -- weit unter jeder realistisch vom Engine
# berechneten risky-Fraktion (Audit-Repro: 5627 vs. 100 bps-Groessenordnung).
_FORCED_RISK_BUDGET_BPS = 100


def _current_allocation_id(session_factory, mandate_id, advisor_id):
    with session_factory() as s:
        row = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id,
            TargetAllocation.is_current == 1,
        ).first()
        if row:
            return row.id
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        return result["target_allocation"].id


def _force_risk_budget_violation(session_factory, allocation_id: str) -> int:
    """Senkt NUR das typisierte Risk-Budget weit unter die real vom Engine
    berechnete risky-Fraktion, und haelt effective_constraints_json /
    allocation_context_hash dabei exakt so selbst-konsistent, wie
    services.portfolio_engine._verified_persisted_allocation_context es
    beim naechsten Laden nachrechnet (gleiche Payload-Form, gleicher
    Hash-Algorithmus -- keine Abkuerzung, keine Mock-Logik). Dadurch bleibt
    die Risk-Budget-Verletzung die EINZIGE im Test erzeugte Anomalie;
    jede andere Integritaetspruefung in build_target_payload_from_
    allocation bleibt gruen.

    Gibt die tatsaechlich vom Engine berechnete risky-Fraktion (bps) zurueck,
    fuer die Assertion im Test.
    """
    with session_factory() as s:
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id
        ).one()
        realized_risky_bps = int(allocation.risky_fraction_bps_at_generation)
        assert realized_risky_bps > _FORCED_RISK_BUDGET_BPS, (
            "Setup-Fehler: die vom Engine real berechnete risky-Fraktion "
            f"({realized_risky_bps} bps) muss ueber dem erzwungenen Budget "
            f"({_FORCED_RISK_BUDGET_BPS} bps) liegen, sonst liegt gar keine "
            "Verletzung vor."
        )

        stored_constraints = json.loads(allocation.effective_constraints_json)
        stored_sub_allocations = json.loads(allocation.sub_allocations_json)
        stored_constraints["risk_budget_bps"] = _FORCED_RISK_BUDGET_BPS

        targets = {
            "equities": int(allocation.target_equities_bps),
            "bonds": int(allocation.target_bonds_bps),
            "real_estate": int(allocation.target_real_estate_bps),
            "alternatives": int(allocation.target_alternatives_bps),
            "liquidity": int(allocation.target_liquidity_bps),
        }
        # Identische Payload-Form wie services.portfolio_engine.
        # build_target_payload_from_allocation / _verified_persisted_
        # allocation_context (Zeile ~4643-4664), damit der Hash dort
        # reproduzierbar nachgerechnet und als gueltig erkannt wird.
        persisted_context_payload = {
            "engine_version": stored_constraints.get("engine_version"),
            "policy_id": str(allocation.policy_id),
            "cma_id": str(allocation.capital_market_assumptions_id),
            "assessment_id": str(allocation.based_on_assessment_id),
            "input_snapshot_hash": str(allocation.input_snapshot_hash),
            "preferences_json": allocation.preferences_json,
            "targets_bps": {bucket: int(targets[bucket]) for bucket in BUCKET_FIELDS},
            "sub_allocations": stored_sub_allocations,
            "effective_constraints": stored_constraints,
            "optimization_seed": getattr(allocation, "optimization_seed", None),
        }
        recomputed_hash = hashlib.sha256(
            json.dumps(
                persisted_context_payload, sort_keys=True,
                separators=(",", ":"), default=str,
            ).encode("utf-8")
        ).hexdigest()

        allocation.risk_budget_bps_at_generation = _FORCED_RISK_BUDGET_BPS
        allocation.effective_constraints_json = json.dumps(stored_constraints)
        allocation.allocation_context_hash = recomputed_hash
        s.commit()
        return realized_risky_bps


def _allocation_policy_and_cma(session_factory, allocation_id):
    with session_factory() as s:
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id
        ).one()
        return allocation.policy_id, allocation.capital_market_assumptions_id


def _make_run(session_factory, mandate_id, allocation_id, assessment_id, created_by, policy_id, cma_id, *, result_status="Draft") -> str:
    rid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        s.add(RecommendationRun(
            id=rid, mandate_id=mandate_id, client_id=mandate.client_id,
            assessment_id=assessment_id, target_allocation_id=allocation_id,
            policy_id=policy_id, capital_market_assumptions_id=cma_id,
            run_type="Optimizer", result_status=result_status,
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return rid


def _add_full_position(session_factory, run_id) -> None:
    """Genau eine Position mit 10000 bps auf einem aktiven Produkt --
    erfuellt alle Positions-/Gewichts-Checks in
    _validate_recommendation_for_finalization, damit die einzige Variable
    im Test die risk_budget_violated-Verletzung bleibt."""
    now = _iso(datetime.now(timezone.utc))
    pid = new_uuid()
    with session_factory() as s:
        s.add(Product(
            id=pid, product_name="Test ETF", provider="X",
            product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Welt",
            currency="CHF", ter_bps=20, sfdr_class="6",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=run_id, product_id=pid,
            target_weight_bps=10000, target_amount_rappen=500_000_00,
            created_at=now, updated_at=now,
        ))
        s.commit()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RISK-BUDGET-FINALIZATION-001 -- round 46 red test, see audit "
        "2026-10-04-risk-budget-fallback-context-and-finalization-integrity-"
        "audit.md (not committed in this repo)"
    ),
)
def test_finalize_recommendation_must_reject_active_risk_budget_violated_lock(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(
        session_factory, suffix="risk-budget-finalization-001",
    )
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)

    # Erzwinge die Risk-Budget-Verletzung (reale risky-Fraktion vom Engine
    # unveraendert, nur das typisierte Budget wird weit darunter gesetzt --
    # Audit-Groessenordnung 5627 vs. 100 bps).
    realized_risky_bps = _force_risk_budget_violation(session_factory, alloc_id)
    assert realized_risky_bps > _FORCED_RISK_BUDGET_BPS

    # Sanity-Check: der REALE Lock-Audit-Entry-Point muss diese Verletzung
    # tatsaechlich als risk_budget_violated-Lock erkennen. Das ist kein Teil
    # des Bugs -- mandate_lock_audit.py selbst funktioniert korrekt.
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        audit = audit_mandate_editability(db, mandate)
    assert audit["lock_reasons"] == [REASON_RISK_BUDGET_VIOLATED], (
        "Setup-Fehler: die Verletzung muss den realen risk_budget_violated-"
        f"Lock triggern, bekam stattdessen {audit['lock_reasons']!r}"
    )

    policy, cma = _allocation_policy_and_cma(session_factory, alloc_id)
    run_id = _make_run(
        session_factory, mid, alloc_id, aid, advisor_id, policy, cma,
        result_status="Draft",
    )
    _add_full_position(session_factory, run_id)

    # Gewuenschtes Verhalten: finalize_recommendation MUSS ablehnen, solange
    # der risk_budget_violated-Lock fuer das Mandat aktiv ist.
    # Tatsaechliches Verhalten heute: _validate_recommendation_for_
    # finalization kennt mandate_lock_audit/risk_budget_violated nicht --
    # keine HTTPException, der Run wird klaglos "Final".
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        with pytest.raises(HTTPException) as exc_info:
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(),
                db=db, current_user=advisor,
            )
        assert exc_info.value.status_code == 422
