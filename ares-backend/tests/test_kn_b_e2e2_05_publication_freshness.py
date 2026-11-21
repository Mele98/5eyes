"""KN-B / E2E2-05: Status-API meldet eine veraltete Publikation mit Ursache.

Befund (Dok. 117): Nach einer USD-Kursaenderung lieferten die Payloads 409
("Wechselkurs USD seit der Berechnung geaendert"), die Publikation blieb aber
``PUBLISHED`` mit ``blocker_codes: []`` -- die Asset-Allokation-Seite konnte
die Ursache nicht nennen.

Vertrag (abgeleitet, der Publikationsdatensatz bleibt append-only):
GET /mandates/{id}/allocation-publication liefert ``freshness`` =
``{status: FRESH|STALE|UNKNOWN|null, reason_code, message, causes: [{kind,
text, currencies}]}``; ist die Allokation publiziert, aber STALE, lauten
``publication_status`` und ``active_publication.status``
``PUBLICATION_INVALID`` (``reason_code`` ``CCX_INPUT_STALE``).
GET /mandates/{id}/advisory-envelopes/current/freshness liefert ``causes``.

Gegenprobe: ``publication_freshness`` ohne Input-Pruefung bzw.
``apply_publication_freshness`` ohne Statusableitung -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

from core.fx_freshness import freshness_cause
from services.report_projection_gate import apply_publication_freshness, publication_freshness
from tests.test_k1_e2e03_fx_freshness import USD_DEPOT, _rate, _setup  # noqa: F401
from tests.test_e2e_thierry_goessi_walkthrough import advisor_user, api, session_factory  # noqa: F401


def _ta_state(session_factory, mandate_id):
    from models.allocation import TargetAllocation
    from models.mandates import Mandate

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).one()
        ta = db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate_id,
                                               TargetAllocation.is_current == 1).one()
        state = SimpleNamespace(status="PUBLISHED", reason_code=None, target_allocation_id=ta.id,
                                envelope_id=None, drift=())
        return publication_freshness(db, mandate, state)


def test_usd_rate_change_is_reported_with_currency(api, advisor_user, session_factory):
    mandate_id = _setup(api, advisor_user, usd=True)
    assert _ta_state(session_factory, mandate_id) == {"status": "FRESH", "reason_code": None,
                                                     "message": None, "causes": []}
    _rate(api, "GBP", 1.13)  # irrelevant: bleibt FRESH
    assert _ta_state(session_factory, mandate_id)["status"] == "FRESH"
    _rate(api, "USD", 0.90)
    fresh = _ta_state(session_factory, mandate_id)
    assert fresh["status"] == "STALE" and fresh["reason_code"] == "CCX_INPUT_STALE", fresh
    assert fresh["causes"] == [{"kind": "fx_rate", "text": "Wechselkurs USD geändert", "currencies": ["USD"]}]
    assert "Wechselkurs USD geändert" in fresh["message"]


def test_overview_derives_publication_invalid_and_keeps_record():
    overview = {"publication_status": "PUBLISHED", "blocker_codes": [],
                "active_publication": {"status": "PUBLISHED", "reason_code": None, "publication_id": "p1"}}
    freshness = {"status": "STALE", "reason_code": "CCX_INPUT_STALE", "message": "x",
                 "causes": [freshness_cause("fx_rate", ["USD"])]}
    out = apply_publication_freshness(overview, freshness)
    assert out["publication_status"] == "PUBLICATION_INVALID"
    assert out["active_publication"] == {"status": "PUBLICATION_INVALID", "reason_code": "CCX_INPUT_STALE",
                                         "publication_id": "p1"}
    assert out["freshness"] is freshness
    assert overview["publication_status"] == "PUBLISHED"  # Eingabe unveraendert
    fresh = apply_publication_freshness(overview, {"status": "FRESH", "causes": []})
    assert fresh["publication_status"] == "PUBLISHED"


def test_endpoint_reports_cause_for_stale_published_allocation(api, advisor_user, session_factory, monkeypatch):
    """Router: publizierte Allokation (Status simuliert) + USD-Aenderung ->
    PUBLICATION_INVALID mit Ursache "Wechselkurs USD geändert"."""
    import routers.allocation as router
    import services.allocation_publication_gate as gate
    from models.allocation import TargetAllocation

    mandate_id = _setup(api, advisor_user, usd=True)
    with session_factory() as db:
        ta_id = db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate_id,
                                                  TargetAllocation.is_current == 1).one().id
    published = gate.PublicationState("PUBLISHED", None, publication_id="pub-1", target_allocation_id=ta_id)
    monkeypatch.setattr(gate, "active_publication_state", lambda db, mandate, deep=True: published)
    monkeypatch.setattr(router, "active_publication_state", lambda db, mandate, deep=True: published)
    before = api.get(f"/mandates/{mandate_id}/allocation-publication").json()
    assert before["publication_status"] == "PUBLISHED" and before["freshness"]["status"] == "FRESH", before
    _rate(api, "USD", 0.90)
    after = api.get(f"/mandates/{mandate_id}/allocation-publication").json()
    assert after["publication_status"] == "PUBLICATION_INVALID", after
    assert after["active_publication"]["status"] == "PUBLICATION_INVALID"
    assert after["active_publication"]["reason_code"] == "CCX_INPUT_STALE"
    assert after["freshness"]["causes"][0]["text"] == "Wechselkurs USD geändert"


def test_published_state_without_envelope_is_typed_not_500(api, advisor_user, session_factory, monkeypatch):
    """P5b-CI-Fix (H-183/H-185): ``decision_envelope_reference`` (GET
    allocation-publication, target-allocation/current[/payload]) liest das
    Kanal-Gate. Fehlt der Entscheid zu einer als publiziert gemeldeten
    Allokation, antwortet es typisiert (``CCX_ENVELOPE_MISSING``, nicht
    auslieferbar) statt mit AttributeError/500.
    Gegenprobe: Absicherung ``envelope is None`` entfernen -> 500 -> rot."""
    import routers.allocation as router
    import services.allocation_publication_gate as gate
    from models.allocation import TargetAllocation
    from models.mandates import Mandate

    mandate_id = _setup(api, advisor_user, usd=True)
    with session_factory() as db:
        ta_id = db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate_id,
                                                  TargetAllocation.is_current == 1).one().id
    for envelope_id in (None, "envelope-gibt-es-nicht"):
        published = gate.PublicationState("PUBLISHED", None, publication_id="pub-1",
                                          target_allocation_id=ta_id, envelope_id=envelope_id)
        monkeypatch.setattr(gate, "active_publication_state", lambda db, mandate, deep=True, _p=published: _p)
        monkeypatch.setattr(router, "active_publication_state", lambda db, mandate, deep=True, _p=published: _p)
        with session_factory() as db:
            decision = gate.evaluate_channel_envelope(db, db.get(Mandate, mandate_id))
        assert decision.applicable and not decision.ok and decision.reason_code == "CCX_ENVELOPE_MISSING", decision
        assert decision.cause.startswith("Der versiegelte Beratungsentscheid ist nicht auffindbar"), decision.cause
        response = api.get(f"/mandates/{mandate_id}/allocation-publication")
        assert response.status_code == 200, response.text
        reference = response.json()["decision_envelope"]
        assert reference["state"] != "deliverable" and reference["reason_code"] == "CCX_ENVELOPE_MISSING", reference
        assert reference["pruefnummer"] is None, reference
