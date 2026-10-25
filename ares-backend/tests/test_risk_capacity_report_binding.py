"""RISK-CAPACITY-PLAUSIBILITY-001 -- Bindung des publizierten Report-Status.

Closure-Review PR #677 (Codex-Gate
``test_2026_10_23_pr677_risk_capacity_report_binding_adversarial.py``, hier
ohne xfail uebernommen): der kompakte Report-Auszug muss das bewertete
Risikoprofil nennen, und ein fehlendes aktuelles Profil ist ein sichtbares,
typisiertes ``not_evaluable`` statt eines leeren Feldes.

Ergaenzend: Identitaetsdrift zwischen Ergebnis und Assessment ist
``integrity_mismatch``; der Bezug zur Suitability-Referenz wird gekennzeichnet;
der Kundenkanal bleibt ruhig (CIO-Entscheid aus PR #677).
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest


def _backend_root() -> Path:
    """Backend per Struktur finden (Verzeichnis mit ``main.py`` + ``services``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "main.py").is_file() and (parent / "services").is_dir():
            return parent
    raise RuntimeError("Backend-Verzeichnis nicht gefunden")


_BACKEND = _backend_root()
for _p in (_BACKEND, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services.risk_capacity_plausibility_report import (  # noqa: E402
    AVAILABILITY_EVALUATED,
    AVAILABILITY_INTEGRITY_MISMATCH,
    AVAILABILITY_MISSING_INPUT,
    AVAILABILITY_UNAVAILABLE,
    BINDING_MISMATCH_NOTE,
    EVALUATION_BASIS,
    NO_ASSESSMENT_NOTE,
    REASON_ASSESSMENT_BINDING_MISMATCH,
    REASON_NO_CURRENT_RISK_ASSESSMENT,
    REFERENCE_MISMATCH_NOTE,
    bind_to_suitability_reference,
    compact_view,
    evaluate_for_assessment,
)


def _partial_result() -> dict:
    return {
        "status": "partial",
        "reason_code": None,
        "risk_assessment_id": "ra-current-v3",
        "findings": [],
        "not_evaluable": [
            {"check": "OBLIGATIONS_BELOW_RECORDED", "reason": "missing"},
        ],
    }


# ---------------------------------------------------------------------------
# Codex-Gate PR #677 (ohne xfail)
# ---------------------------------------------------------------------------

def test_compact_report_preserves_evaluated_assessment_identity() -> None:
    """A customer-impacting verdict must be attributable to one assessment."""
    view = compact_view(_partial_result())

    assert view is not None
    assert view.get("risk_assessment_id") == "ra-current-v3", view


def test_missing_current_assessment_is_explicitly_not_evaluable() -> None:
    """Missing core input is unavailable evidence, never silent absence."""
    db = SimpleNamespace(info={})
    mandate = SimpleNamespace(id="mandate-a", client_id="client-a")

    result = evaluate_for_assessment(db, mandate, None)
    view = compact_view(result)

    assert view is not None, "missing assessment currently removes the whole status"
    assert view["status"] == "not_evaluable", view
    assert view["note"], view


# ---------------------------------------------------------------------------
# Typisierte Availability, Evidence-Felder, Identitaetsdrift
# ---------------------------------------------------------------------------

def test_missing_assessment_is_typed_missing_input_with_capture_note() -> None:
    view = compact_view(evaluate_for_assessment(
        SimpleNamespace(info={}), SimpleNamespace(id="m", client_id="c"), None,
    ))
    assert view["availability"] == AVAILABILITY_MISSING_INPUT
    assert view["reason_code"] == REASON_NO_CURRENT_RISK_ASSESSMENT
    assert view["risk_assessment_id"] is None
    assert view["note"] == NO_ASSESSMENT_NOTE
    assert "Risikoprofil erfassen" in view["note"]


def test_compact_view_publishes_binding_evidence() -> None:
    view = compact_view({
        **_partial_result(), "version": "RCP-x", "evaluation_hash": "a" * 64,
    })
    assert view["availability"] == AVAILABILITY_EVALUATED
    assert view["evaluation_basis"] == EVALUATION_BASIS
    assert view["rules_version"] == "RCP-x"
    assert view["evaluation_hash"] == "a" * 64


@pytest.mark.parametrize("status", ["consistent", "partial", "inconsistent"])
def test_evaluated_status_without_assessment_identity_is_integrity_mismatch(status) -> None:
    view = compact_view({"status": status, "findings": [], "not_evaluable": []})
    assert view["status"] == "not_evaluable", view
    assert view["availability"] == AVAILABILITY_INTEGRITY_MISMATCH
    assert view["reason_code"] == REASON_ASSESSMENT_BINDING_MISMATCH
    assert view["note"] == BINDING_MISMATCH_NOTE


def _patch_evaluator(monkeypatch, result):
    from services import risk_capacity_plausibility as rcp

    monkeypatch.setattr(rcp, "evaluate_mandate_safely", lambda *_a, **_k: result)


def test_result_for_other_assessment_is_rejected(monkeypatch) -> None:
    _patch_evaluator(monkeypatch, {**_partial_result(), "risk_assessment_id": "ra-old"})
    result = evaluate_for_assessment(
        SimpleNamespace(info={}), SimpleNamespace(id="m", client_id="c"),
        SimpleNamespace(id="ra-current-v3"),
    )
    view = compact_view(result)
    assert view["status"] == "not_evaluable"
    assert view["availability"] == AVAILABILITY_INTEGRITY_MISMATCH
    assert view["risk_assessment_id"] == "ra-current-v3"


def test_matching_result_is_returned_unchanged(monkeypatch) -> None:
    original = _partial_result()
    _patch_evaluator(monkeypatch, original)
    result = evaluate_for_assessment(
        SimpleNamespace(info={}), SimpleNamespace(id="m", client_id="c"),
        SimpleNamespace(id="ra-current-v3"),
    )
    assert result is original


def test_unbound_evaluator_failure_stays_not_evaluable_for_requested_profile(monkeypatch) -> None:
    _patch_evaluator(monkeypatch, {
        "status": "not_evaluable", "reason_code": None, "findings": [],
        "not_evaluable": [{"check": "ALL"}],
    })
    view = compact_view(evaluate_for_assessment(
        SimpleNamespace(info={}), SimpleNamespace(id="m", client_id="c"),
        SimpleNamespace(id="ra-1"),
    ))
    assert view["status"] == "not_evaluable"
    assert view["availability"] == AVAILABILITY_UNAVAILABLE
    assert view["risk_assessment_id"] == "ra-1"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [("ra-current-v3", True), ("ra-old", False), (None, None), ("", None)],
)
def test_suitability_reference_match_is_explicit(reference, expected) -> None:
    block = compact_view(_partial_result())
    bound = bind_to_suitability_reference(block, reference)
    assert bound["suitability_reference_match"] is expected
    assert "suitability_reference_match" not in block  # Cache-Eintrag unveraendert


# ---------------------------------------------------------------------------
# PDF (intern) und Aggregator
# ---------------------------------------------------------------------------

def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)


def _render_with_block(block) -> str:
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    from test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    ss = dict(payload.get("suitability_summary") or {})
    ss["risk_capacity_plausibility"] = block
    payload["suitability_summary"] = ss
    return _pdf_text(render_advisory_report_pdf_from_payload(payload))


def test_internal_pdf_shows_missing_assessment_capture_request() -> None:
    block = compact_view(evaluate_for_assessment(
        SimpleNamespace(info={}), SimpleNamespace(id="m", client_id="c"), None,
    ))
    text = _render_with_block(block)
    assert "Kein aktuelles Risikoprofil vorhanden" in text
    assert "Risikoprofil erfassen" in text


def test_internal_pdf_labels_reference_mismatch() -> None:
    block = bind_to_suitability_reference(compact_view(_partial_result()), "ra-old")
    text = _render_with_block(block)
    assert "nicht auf das in der Eignungsprüfung referenzierte Profil" in text
    same = bind_to_suitability_reference(compact_view(_partial_result()), "ra-current-v3")
    assert "referenzierte Profil" not in _render_with_block(same)
    assert REFERENCE_MISMATCH_NOTE.startswith("Plausibilitätsprüfung")


from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402


def test_advisory_payload_binds_block_to_current_assessment(session_factory) -> None:
    from models.mandates import Mandate
    from services.advisory_report import compute_advisory_report

    _adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "rcb-bind")
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        report = compute_advisory_report(db, mandate)
    block = report["suitability_summary"]["risk_capacity_plausibility"]
    assert block["risk_assessment_id"] == aid
    assert block["availability"] in (AVAILABILITY_EVALUATED, AVAILABILITY_UNAVAILABLE)
    assert "suitability_reference_match" in block


def test_advisory_payload_without_current_assessment_is_visible(session_factory) -> None:
    from models.mandates import Mandate
    from models.profiling import RiskAssessment
    from services.advisory_report import compute_advisory_report

    _adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "rcb-nora")
    with session_factory() as db:
        db.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).update(
            {RiskAssessment.is_current: 0}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        report = compute_advisory_report(db, mandate)
    block = report["suitability_summary"]["risk_capacity_plausibility"]
    assert block["status"] == "not_evaluable"
    assert block["availability"] == AVAILABILITY_MISSING_INPUT
    assert block["reason_code"] == REASON_NO_CURRENT_RISK_ASSESSMENT
    assert block["note"] == NO_ASSESSMENT_NOTE


def test_client_facing_payload_carries_no_advisor_plausibility_note(session_factory) -> None:
    """CIO-Entscheid PR #677: Hinweise nur in Beraterkanaelen, Kundensicht ruhig."""
    from models.mandates import Mandate
    from models.profiling import RiskAssessment
    from services.advisory_report import compute_advisory_report

    _adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "rcb-client")
    with session_factory() as db:
        db.query(RiskAssessment).filter(RiskAssessment.mandate_id == mid).update(
            {RiskAssessment.is_current: 0}
        )
        db.commit()
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        report = compute_advisory_report(db, mandate, client_facing=True)
    assert report["suitability_summary"]["risk_capacity_plausibility"] is None
