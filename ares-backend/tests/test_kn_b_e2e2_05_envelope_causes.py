"""KN-B / E2E2-05 (Teil Envelope): echte Publikation + Zielaenderung.

Beide Status-APIs nennen die konkrete Ursache ("Ziele geändert"); die
Ableitung schreibt keinen neuen Publikationsdatensatz (append-only).
Gegenprobe: ``causes`` in ``current_envelope_freshness`` entfernen bzw.
``apply_publication_freshness`` ohne Ableitung -> rot.
"""
from __future__ import annotations

from sqlalchemy import text

from services.report_projection_gate import apply_publication_freshness, publication_freshness
from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p2_invalidation import _mutate_goal
from tests.test_ccx_p4_allocation_publish import _published


def test_envelope_invalidation_cause_in_both_status_apis(session_factory):
    """Echte Publikation + Zielaenderung: beide Status-APIs nennen "Ziele geändert"."""
    from models.mandates import Mandate
    from services.advisory_decision_envelope import current_envelope_freshness
    from services.allocation_publication_gate import active_publication_state, publication_overview
    advisor_id, _approver, mid, _aid, _run, decision = _published(session_factory, "kn-05")
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        state = active_publication_state(db, mandate)
        assert publication_freshness(db, mandate, state)["status"] == "FRESH"
    with session_factory() as db:
        db.info["ares_actor_user_id"] = advisor_id
        _mutate_goal(db, {"mid": mid})
        db.commit()
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        state = active_publication_state(db, mandate)
        out = apply_publication_freshness(publication_overview(db, mandate),
                                          publication_freshness(db, mandate, state))
        envelope = current_envelope_freshness(db, mandate=mandate)
        count = db.execute(text("SELECT COUNT(*) FROM allocation_publication_decisions WHERE mandate_id = :m"),
                           {"m": mid}).scalar()
    assert out["publication_status"] == "PUBLICATION_INVALID"
    assert out["freshness"]["status"] == "STALE"
    assert {"kind": "goals", "text": "Ziele geändert", "currencies": []} in out["freshness"]["causes"]
    assert envelope["causes"] == [{"kind": "goals", "text": "Ziele geändert", "currencies": []}]
    assert count == 1  # append-only: kein neuer Publikationsdatensatz durch die Ableitung
