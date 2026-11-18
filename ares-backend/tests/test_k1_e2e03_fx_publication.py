"""K1 / E2E-03: ein publiziertes CHF-Mandat bleibt bei einer irrelevanten
Kursaenderung (GBP) publiziert. Vorher: PUBLICATION_INVALID / CCX_INPUT_STALE,
weil die tabellenweite FX-``basis_id`` im Allokations-Pruefwert lag."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from models.fx_rate import FXRate
from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _published, _state


def test_published_mandate_stays_published_on_irrelevant_rate_change(session_factory):  # noqa: F811
    _adv, _approver, mid, _aid, _run, _decision = _published(session_factory, "k1fx")
    assert _state(session_factory, mid).published
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with session_factory() as db:
        db.add(FXRate(id=str(uuid.uuid4()), currency="GBP", rate_x10000=11300, valid_from=now[:10],
                      is_current=1, source="Manual", created_at=now, updated_at=now))
        db.commit()
    state = _state(session_factory, mid)
    assert state.published, (state.status, state.reason_code)
    # Kundenkanaele (Soll-Allokation-Payload) lesen die publizierte Allokation weiter:
    # der Input-Pruefwert ist unveraendert (vorher: StaleAllocationInputError).
    from models.allocation import CapitalMarketAssumption, OptimizerPolicy, TargetAllocation
    from models.mandates import Mandate
    from models.profiling import RiskAssessment
    from services.portfolio_engine import build_target_payload_from_allocation

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        ta = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1).one()
        policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == ta.policy_id).one()
        cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == ta.capital_market_assumptions_id).one()
        assessment = db.query(RiskAssessment).filter(RiskAssessment.id == ta.based_on_assessment_id).one()
        build_target_payload_from_allocation(
            db, mandate, ta, policy, cma, assessment, None, input_snapshot_check_only=True,
        )
