"""C-COMP-02: Produktevidenz in Finalisierung, P5-Siegel, Frische und Kanaelen.

Regressionen 2, 4, 5, 6, 14 der Build-Map samt Negativkontrollen. Die Laeufe
entstehen ueber die CCX-Fixtures; ihre synthetische Evidenz laeuft ueber den
echten Entwurfs-/Freigabeweg (``SYNTHETIC_EVIDENCE_MODULES``).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import services.product_eligibility as evidence
from core import product_evidence as contract
from core.reason_codes import DomainError, ReasonCode
from models.mandates import Mandate
from models.product_eligibility import ProductEvidenceItem, ProductEvidenceSnapshot
from models.review import Product, RecommendationPosition, RecommendationRun
from models.snapshots import AdvisoryDependencyEdge, AdvisoryEnvelopeBinding
from product_evidence_test_support import synthetic_values
from tests.sustainability_test_support import answer_question_one_for_all_mandates
from tests.test_ccx_p1_snapshot_hash import _finalizable_run, session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _finalized, _overview, _published
from tests.test_ccx_p5_channel_envelope import _anlagestrategie, _decision, _status_of
from tests.test_finalize_mandate_lock import _FakeRequest
from tests.test_h12_ccx_hygiene import _gated_calls, _text, _user


def _items(db, mid):
    return db.query(ProductEvidenceItem).join(
        RecommendationPosition, RecommendationPosition.product_id == ProductEvidenceItem.product_id,
    ).join(RecommendationRun, RecommendationRun.id == RecommendationPosition.run_id).filter(
        RecommendationRun.mandate_id == mid, ProductEvidenceItem.status == "approved",
    ).order_by(ProductEvidenceItem.id).all()


def _change(session_factory, mid, action):  # noqa: F811
    with session_factory() as db:
        row = next(r for r in _items(db, mid) if r.evidence_kind == "costs")
        product = db.get(Product, row.product_id)
        if action == "revoke":
            evidence.close_product_evidence_item(
                db, row, status="revoked", reason="SOURCE_WITHDRAWN", actor_id="approver")
        elif action == "retire":
            evidence.close_product_evidence_item(db, row, status="retired", reason="SOURCE_OLD", actor_id="approver")
        elif action == "replace":  # inhaltsgleich, neue Lebenszyklusidentitaet
            successor = evidence.create_product_evidence_draft(
                db, product, values=synthetic_values(product, "costs", supersedes_id=row.id), tenant_id=row.tenant_id,
                actor_id=row.created_by)
            db.flush()
            assert successor.canonical_payload_hash == row.canonical_payload_hash
            evidence.approve_product_evidence_items(
                db, product, seen=[(successor.id, successor.canonical_payload_hash)], tenant_id=row.tenant_id,
                actor_id="approver", is_same_person=lambda _c: False, approver_ids=[], attestation=None,
                min_attestation_length=1)
        elif action == "share_class":
            product.share_class_figi = "SYNTH-OTHER-CLASS"
        elif action == "note":
            product.esg_rating = product.esg_rating  # keine Aenderung
            db.execute(text("UPDATE products SET product_name = product_name || ' (Notiz)' WHERE id = :p"),
                       {"p": product.id})
            evidence.create_product_evidence_draft(
                db, product, values=synthetic_values(product, "kid", note="Nur interne Notiz"),
                tenant_id=row.tenant_id, actor_id=row.created_by)
        db.commit()


# -- P5-Siegel ----------------------------------------------------------------


def test_envelope_binds_the_set_hash_and_one_edge_per_item(session_factory):  # noqa: F811
    _advisor, _approver, mid, _aid, run_id, _d = _published(session_factory, "c02-seal")
    decision = _decision(session_factory, mid)
    assert decision.ok
    with session_factory() as db:
        run = db.get(RecommendationRun, run_id)
        snapshot = db.get(ProductEvidenceSnapshot, run.product_evidence_snapshot_id)
        binding = db.query(AdvisoryEnvelopeBinding).filter_by(
            envelope_id=decision.envelope_id, binding_kind="product_evidence_set").one()
        assert (binding.object_id, binding.child_hash) == (snapshot.id, snapshot.product_evidence_hash)
        payload = json.loads(db.execute(text(
            "SELECT canonical_payload_json FROM advisory_decision_envelopes WHERE id = :e"),
            {"e": decision.envelope_id}).scalar())
        assert [b["child_hash"] for b in payload["bindings"] if b["binding_kind"] == "product_evidence_set"] == [
            snapshot.product_evidence_hash]
        sealed = json.loads(snapshot.canonical_payload_json)
        assert sealed["status"] == "verified" and "as_of" in sealed and "expires_at" in sealed
        edges = {e.dependency_object_id for e in db.query(AdvisoryDependencyEdge).filter_by(
            envelope_id=decision.envelope_id, dependency_kind="product_evidence").all()}
        assert edges == set(json.loads(snapshot.item_ids_json)) and len(edges) >= len(contract.PRODUCT_EVIDENCE_KINDS)


@pytest.mark.parametrize("action,run_code", [
    ("revoke", "PRODUCT_EVIDENCE_REVOKED"), ("retire", "PRODUCT_EVIDENCE_COST_MISSING"),
    ("replace", "PRODUCT_EVIDENCE_STALE"), ("share_class", "PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"),
])
def test_change_after_publication_is_stale_in_every_channel(session_factory, action, run_code):  # noqa: F811
    from routers.client_portal import _assert_portal_report_releasable
    from models.clients import Client
    from fastapi import HTTPException
    from services.allocation_publication_gate import evaluate_allocation_publication, require_channel_envelope
    from services.recommendation_release_gate import CHANNEL_SIGNATURE, assert_recommendation_release_eligible

    advisor_id, _approver, mid, _aid, run_id, _d = _published(session_factory, f"c02-{action[:3]}")
    calls = dict(_gated_calls())
    calls["get_anlagestrategie_pdf"] = lambda m, db, u: _anlagestrategie(db, m, u)
    assert _decision(session_factory, mid).ok
    _change(session_factory, mid, action)
    assert not _decision(session_factory, mid).ok
    # Kunden-PDFs: gesperrt oder sichtbarer Entwurf (P4) -- nie final, nie archiviert.
    archived = _archived(session_factory, mid)
    for name, call in calls.items():
        with session_factory() as db:
            response, (status, _code) = _call(lambda c=call: c(mid, db, _user(db, advisor_id)))
            assert status in (200, 409), (name, status)
            if status == 200 and name != "get_contract_signoff_pdf":  # Vertrag: ohne Allokation
                assert "entwurf" in _text(response.body).lower(), name
    assert _archived(session_factory, mid) == archived
    with session_factory() as db:  # Publikation
        blockers = evaluate_allocation_publication(db, db.get(Mandate, mid)).blockers
        assert run_code in blockers, blockers
    for channel, outdated in (("HANDOFF", ReasonCode.CCX_HANDOFF_ENVELOPE_OUTDATED),
                              ("ADVISOR_SIGNATURE", ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED),
                              ("ONSITE_SIGNATURE", ReasonCode.CCX_SIGNATURE_ENVELOPE_OUTDATED)):
        with session_factory() as db, pytest.raises(DomainError) as exc:
            require_channel_envelope(db, db.get(Mandate, mid), channel=channel, user=_user(db, advisor_id),
                                     outdated_code=outdated)
        assert exc.value.reason_code == outdated.value
    for run_arg in (None, run_id):  # Signatur/PDF (ohne Lauf) und Handoff (mit Lauf)
        with session_factory() as db, pytest.raises(DomainError) as exc:
            assert_recommendation_release_eligible(
                db, db.get(Mandate, mid), channel=CHANNEL_SIGNATURE,
                run=db.get(RecommendationRun, run_arg) if run_arg else None)
        assert exc.value.reason_code == run_code
    with session_factory() as db, pytest.raises(HTTPException) as portal:  # Kundenportal: neutral
        mandate = db.get(Mandate, mid)
        _assert_portal_report_releasable(db, mandate, db.get(Client, mandate.client_id), _user(db, advisor_id))
    assert portal.value.status_code == 409 and "PRODUCT_EVIDENCE" not in str(portal.value.detail)


def _archived(session_factory, mid):  # noqa: F811
    with session_factory() as db:
        return db.execute(text(
            "SELECT count(*) FROM contract_documents WHERE mandate_id = :m AND document_type IN "
            "('Anlagestrategie', 'Anlagerezept', 'Beratungsprotokoll', 'Kostenausweis')"), {"m": mid}).scalar()


def _call(fn):
    holder = []
    status = _status_of(lambda: holder.append(fn()) or holder[0])
    return (holder[0] if holder else None), status


def test_irrelevant_note_stays_fresh(session_factory):  # noqa: F811
    from services.advisory_decision_envelope import current_envelope_freshness

    _advisor, _approver, mid, *_rest = _published(session_factory, "c02-note")
    _change(session_factory, mid, "note")
    assert _decision(session_factory, mid).ok
    with session_factory() as db:
        assert current_envelope_freshness(db, mandate=db.get(Mandate, mid))["freshness_status"] == "FRESH"


def test_expiry_without_mutation_is_stale_with_cause(session_factory, monkeypatch):  # noqa: F811
    import services.advisory_decision_envelope as envelope

    real = evidence.approve_product_evidence_items

    def with_expiry(db, product, **kw):
        for item_id, _hash in kw["seen"]:
            db.get(ProductEvidenceItem, item_id).valid_until = (
                datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        db.flush()
        return real(db, product, **kw)

    import product_evidence_test_support as support

    monkeypatch.setattr(support, "approve_product_evidence_items", with_expiry)
    _advisor, _approver, mid, *_rest = _published(session_factory, "c02-exp")
    assert _decision(session_factory, mid).ok
    later = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(envelope, "utc_now", lambda: later.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    assert _decision(session_factory, mid).reason_code == "CCX_INPUT_STALE"
    with session_factory() as db:
        status = envelope.current_envelope_freshness(db, mandate=db.get(Mandate, mid))
    assert status["freshness_status"] == "STALE" and status["stale_reason_code"] == "PRODUCT_EVIDENCE_STALE"
    assert "Produktnachweis" in status["causes"][-1]["text"]


def test_removing_the_bound_set_hash_check_would_miss_a_rebound_run(session_factory):  # noqa: F811
    """Mutation: der Lauf zeigt auf einen anderen (gueltigen) Satz als das Siegel."""
    _advisor, _approver, mid, _aid, run_id, _d = _published(session_factory, "c02-rebind")
    with session_factory() as db:
        run = db.get(RecommendationRun, run_id)
        old = db.get(ProductEvidenceSnapshot, run.product_evidence_snapshot_id)
        payload = json.loads(old.canonical_payload_json)
        payload["as_of"] = "2000-01-01"
        canonical, digest = evidence.product_evidence_hash(payload)
        values = {c.name: getattr(old, c.name) for c in ProductEvidenceSnapshot.__table__.columns}
        values.update(id="other-snapshot", canonical_payload_json=canonical, product_evidence_hash=digest)
        db.add(ProductEvidenceSnapshot(**values))
        db.flush()
        run.product_evidence_snapshot_id, run.product_evidence_hash = "other-snapshot", digest
        db.commit()
        defect, *_ = contract.run_evidence_state(evidence._evidence_query(db), run_id, today=evidence.evidence_today())
        assert defect is None  # der Satz selbst ist gueltig -- nur nicht der versiegelte
    assert _decision(session_factory, mid).reason_code == "CCX_INPUT_STALE"


# -- Finalisierung -------------------------------------------------------------


@pytest.mark.parametrize("action,code", [
    ("revoke", "PRODUCT_EVIDENCE_REVOKED"), ("replace", "PRODUCT_EVIDENCE_STALE"),
])
def test_change_between_generate_and_finalize_blocks_with_audit_and_no_partial_rows(
    session_factory, action, code,  # noqa: F811
):
    from routers.review import finalize_recommendation

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, f"c02-fin-{action[:3]}")
    _change(session_factory, mid, action)
    with session_factory() as db, pytest.raises(DomainError) as exc:
        finalize_recommendation(mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db,
                                current_user=_user(db, advisor_id), confirm_valuations_current=True)
    assert exc.value.reason_code == code
    with session_factory() as db:
        assert db.get(RecommendationRun, run_id).result_status == "Draft"
        assert db.execute(text("SELECT count(*) FROM advisory_decision_envelopes")).scalar() == 0
        blocked = db.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'product_evidence_blocked'")).all()
        assert len(blocked) == 1 and json.loads(blocked[0][0])["channel"] == "finalize"


def test_revocation_between_finalize_check_and_seal_is_rejected(session_factory, monkeypatch):  # noqa: F811
    """Rennen nach der Finalisierungspruefung: das Siegel prueft selbst nochmals."""
    import routers.review as review

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "c02-race")
    with session_factory() as db:
        answer_question_one_for_all_mandates(db)
        db.commit()
    real = review.bind_run_product_evidence

    def racing(db, mandate, run, **kw):
        snapshot = real(db, mandate, run, **kw)
        row = next(r for r in db.query(ProductEvidenceItem).all()
                   if r.id in json.loads(snapshot.item_ids_json) and r.evidence_kind == "kid")
        evidence.close_product_evidence_item(db, row, status="revoked", reason="RACE_TEST", actor_id="x")
        return snapshot

    monkeypatch.setattr(review, "bind_run_product_evidence", racing)
    monkeypatch.setattr("services.cost_disclosure.retrocession_finalization_block", lambda *a: None)
    with session_factory() as db, pytest.raises(DomainError) as exc:
        review.finalize_recommendation(mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db,
                                       current_user=_user(db, advisor_id), confirm_valuations_current=True)
    assert exc.value.reason_code == "PRODUCT_EVIDENCE_REVOKED"
    with session_factory() as db:
        assert db.get(RecommendationRun, run_id).result_status == "Draft"
        assert db.execute(text("SELECT count(*) FROM advisory_decision_envelopes")).scalar() == 0
        assert db.query(ProductEvidenceItem).filter_by(status="revoked").count() == 0  # ganzer Rollback


def test_seal_itself_refuses_an_unbound_run(session_factory, monkeypatch):  # noqa: F811
    import routers.review as review

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "c02-unbound")
    with session_factory() as db:
        answer_question_one_for_all_mandates(db)
        db.commit()
    monkeypatch.setattr(review, "bind_run_product_evidence", lambda *a, **kw: None)
    monkeypatch.setattr("services.cost_disclosure.retrocession_finalization_block", lambda *a: None)
    with session_factory() as db:
        db.execute(text("UPDATE recommendation_runs SET product_evidence_snapshot_id = NULL, "
                        "product_evidence_hash = NULL, product_evidence_status = NULL"))
        db.commit()
    with session_factory() as db, pytest.raises(DomainError) as exc:
        review.finalize_recommendation(mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db,
                                       current_user=_user(db, advisor_id), confirm_valuations_current=True)
    assert exc.value.reason_code == "PRODUCT_EVIDENCE_MISSING"
    with session_factory() as db:
        assert db.get(RecommendationRun, run_id).result_status == "Draft"


# -- Kosten/Anzeige aus derselben gebundenen Fassung (Regression 14) ----------


def test_app_api_pdf_and_cost_disclosure_show_the_bound_version(session_factory):  # noqa: F811
    from services.cost_disclosure import build_cost_disclosure_for_run
    from services.portfolio_engine_payload import run_ter_lookup

    _advisor, mid, _aid, run_id = _finalized(session_factory, "c02-cost")

    def view():
        with session_factory() as db:
            mandate, run = db.get(Mandate, mid), db.get(RecommendationRun, run_id)
            pid = db.query(RecommendationPosition).filter_by(run_id=run_id).first().product_id
            costs = build_cost_disclosure_for_run(db, mandate, run)
            item = next(i for i in costs["cost_items"] if i["key"] == "product_ter")
            retro = costs["product_retrocessions"]["lines"][0]
            return run_ter_lookup(db, run)(pid), item["rate_bps"], retro["rate_bps"], retro["source"]

    before = view()
    assert before[0][0] == "known" and before[0][1] == before[1]
    with session_factory() as db:  # Stammdaten danach verfaelschen: wirkungslos
        db.execute(text("UPDATE products SET ter_bps = 999, retrocession_bps = 777, retrocession_source = 'x'"))
        db.commit()
    assert view() == before
    _change(session_factory, mid, "revoke")
    with session_factory() as db:  # ungueltig: unbekannt, nie 0 und nie Stammdaten
        run = db.get(RecommendationRun, run_id)
        pid = db.query(RecommendationPosition).filter_by(run_id=run_id).first().product_id
        assert run_ter_lookup(db, run)(pid) == ("missing", None)
        costs = build_cost_disclosure_for_run(db, db.get(Mandate, mid), run)
        assert costs["is_complete"] is False
        assert not [i for i in costs["cost_items"] if i["key"] == "product_ter"]


def test_legacy_run_without_bound_evidence_is_not_deliverable_but_readable(session_factory):  # noqa: F811
    """Altbestand: historisch pruefbar, nicht als aktuell auslieferbar."""
    from services.advisory_decision_envelope import verify_envelope
    from models.snapshots import AdvisoryDecisionEnvelope

    _advisor, _approver, mid, *_rest = _published(session_factory, "c02-legacy")
    decision = _decision(session_factory, mid)
    with session_factory() as db:
        db.execute(text("UPDATE recommendation_runs SET product_evidence_snapshot_id = NULL, "
                        "product_evidence_hash = NULL, product_evidence_status = NULL"))
        db.commit()
    assert not _decision(session_factory, mid).ok
    with session_factory() as db:
        assert verify_envelope(db, db.get(AdvisoryDecisionEnvelope, decision.envelope_id)) is None


def test_publication_overview_names_the_evidence_blocker(session_factory):  # noqa: F811
    _advisor, mid, _aid, _run = _finalized(session_factory, "c02-ov")
    assert not [b for b in _overview(session_factory, mid)["blocker_codes"] if "EVIDENCE" in str(b)]
    _change(session_factory, mid, "revoke")
    assert [b for b in _overview(session_factory, mid)["blocker_codes"] if "PRODUCT_EVIDENCE_REVOKED" in str(b)]
