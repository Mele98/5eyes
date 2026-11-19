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


def _new_rate(db, currency, rate):
    """Neuer bestaetigter Kurs (alte Zeile abgeloest), wie PUT /fx-rates."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for row in db.query(FXRate).filter(FXRate.currency == currency, FXRate.is_current == 1).all():
        row.is_current, row.valid_until, row.updated_at = 0, now, now
    db.flush()
    db.add(FXRate(id=str(uuid.uuid4()), currency=currency, rate_x10000=int(rate * 10000),
                  valid_from=now[:10], is_current=1, source="Manual", notes="Querschnitt",
                  created_at=now, updated_at=now))


def _pdf_results(session_factory, mid, user_id):
    from models.users import User
    from routers.pdf_reports import get_assetallocation_pdf, get_contract_signoff_pdf
    from tests.test_ccx_p4_allocation_publish import _pdf_text

    out = {}
    for name, call in (("assetallocation", get_assetallocation_pdf), ("contract_signoff", get_contract_signoff_pdf)):
        with session_factory() as db:
            user = db.query(User).filter(User.id == user_id).one()
            kwargs = {"expected_allocation_id": None} if name == "assetallocation" else {}
            try:
                resp = call(mandate_id=mid, db=db, current_user=user, **kwargs)
                body = _pdf_text(resp.body)
                out[name] = (resp.status_code, "veraltet" in body, "nicht publiziert" in body)
            except Exception as exc:  # noqa: BLE001 -- Sperre wird als Ergebnis verglichen
                out[name] = ("EXC", str(getattr(exc, "detail", exc))[:160])
    return out


def test_cross_section_irrelevant_fx_keeps_customer_pdfs_final(session_factory):  # noqa: F811
    """Querschnitt (Pruefer H-164 Test B, ohne H12-Siegel-Ausnahme): ein neuer
    GBP/JPY-Kurs laesst Assetallocation- und Contract-Signoff-PDF eines
    publizierten CHF-Mandats unveraendert final -- kein "Soll-Allokation
    veraltet", kein Entwurf. Rot an P4 69b30854 (basis_id im Input-Hash)."""
    advisor_id, _approver, mid, _aid, _run, _decision = _published(session_factory, "k1xc")
    before = _pdf_results(session_factory, mid, advisor_id)
    assert before == {"assetallocation": (200, False, False), "contract_signoff": (200, False, False)}, before
    with session_factory() as db:
        with db.no_autoflush:
            _new_rate(db, "GBP", 1.1234)
            _new_rate(db, "JPY", 0.0061)
        db.commit()
    after = _pdf_results(session_factory, mid, advisor_id)
    assert after == before, (before, after)
    assert _state(session_factory, mid).published
