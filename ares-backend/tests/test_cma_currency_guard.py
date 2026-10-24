"""CMA-CURRENCY-GUARD-001 (Variablen-Audit, Abschnitt 1.13 Basiswaehrung).

Befund: die CMA wird nur nach Jurisdiktion gewaehlt; ein CH-Mandat mit
Basiswaehrung EUR rechnete still mit CHF-Renditen/-Volas. Jetzt:

- Strategie bleibt berechenbar, traegt aber ``cma_currency_guard`` mit
  Reason-Code CMA_CURRENCY_MISMATCH und den Hinweis zuoberst im Reasoning
  ("Kapitalmarktannahmen in CHF – für Basiswährung EUR nicht freigegeben").
- Finalisierung und CMA-abhaengige Kundendokumente: 409, bis der Berater die
  Abweichung dokumentiert bestaetigt (``cmaCurrencyMismatchReason``).
- CH-Mandat in CHF: unveraendert (kein Hinweis, kein Gate).
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from services.cma_currency_guard import (  # noqa: E402
    CMA_CURRENCY_MISMATCH,
    attach_to_strategy_payload,
    cma_currency_basis,
    evaluate_cma_currency,
)
from test_band_override_house_matrix_disclosure import _draft_run_with_position  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

MESSAGE_EUR = "Kapitalmarktannahmen in CHF – für Basiswährung EUR nicht freigegeben."
GOOD_REASON = (
    "Kunde lebt in der Schweiz, Mandat wird nur in EUR ausgewiesen; "
    "Waehrungsrisiko wurde im Gespraech besprochen und bewusst akzeptiert."
)


def _seed(SF, suffix: str, base_currency: str):
    adv, _cid, mid, aid = _seed_realistic_mandate(SF, suffix)
    with SF() as s:
        s.query(Mandate).filter(Mandate.id == mid).one().base_currency = base_currency
        s.commit()
    return adv, mid, aid


def _generate(SF, mid, adv, prefs=None) -> dict:
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        attach_to_strategy_payload(s, mandate, result)
        s.commit()
        return result


# --------------------------------------------------------------------------
# Waehrungsbasis der CMA
# --------------------------------------------------------------------------


def test_ch_cma_basis_is_chf_without_profile_row():
    assert cma_currency_basis(None, SimpleNamespace(jurisdiction=None)) == "CHF"


def test_unknown_jurisdiction_basis_is_unknown_and_fail_closed():
    cma = SimpleNamespace(jurisdiction="XX")
    assert cma_currency_basis(None, cma) is None
    guard = evaluate_cma_currency(None, SimpleNamespace(base_currency="XXX"), cma)
    assert guard["reason_code"] == CMA_CURRENCY_MISMATCH
    assert guard["released"] is False
    assert "unbekannter Währungsbasis" in guard["message"]


def test_missing_cma_is_not_a_currency_mismatch():
    """Ohne verankerte CMA gibt es nichts zu vergleichen (eigene Gates)."""
    guard = evaluate_cma_currency(None, SimpleNamespace(base_currency="CHF"), None)
    assert guard["status"] == "not_applicable" and guard["reason_code"] is None
    payload = attach_to_strategy_payload(None, SimpleNamespace(base_currency="CHF"), {"reasoning": ["x"]})
    assert payload["reasoning"] == ["x"]


def test_matching_currency_is_released_without_reason_code():
    guard = evaluate_cma_currency(None, SimpleNamespace(base_currency="chf"), SimpleNamespace(jurisdiction="CH"))
    assert guard["status"] == "ok" and guard["released"] and guard["reason_code"] is None


# --------------------------------------------------------------------------
# Strategie: berechenbar, aber nicht freigegeben
# --------------------------------------------------------------------------


def test_eur_mandate_on_chf_cma_is_computed_but_marked_not_released(session_factory):
    adv, mid, _aid = _seed(session_factory, "cur-eur", "EUR")
    result = _generate(session_factory, mid, adv)

    assert result["target_allocation"] is not None  # bleibt berechenbar
    guard = result["cma_currency_guard"]
    assert guard["reason_code"] == CMA_CURRENCY_MISMATCH
    assert guard["status"] == "mismatch" and guard["released"] is False
    assert guard["mandate_base_currency"] == "EUR" and guard["cma_currency"] == "CHF"
    assert guard["message"] == MESSAGE_EUR
    assert result["reasoning"][0].startswith(MESSAGE_EUR)
    assert CMA_CURRENCY_MISMATCH in result["reasoning"][0]


def test_chf_mandate_has_no_currency_hint(session_factory):
    adv, mid, _aid = _seed(session_factory, "cur-chf", "CHF")
    result = _generate(session_factory, mid, adv)
    assert result["cma_currency_guard"]["status"] == "ok"
    assert not [line for line in result["reasoning"] if CMA_CURRENCY_MISMATCH in line]


def test_documented_acknowledgement_marks_strategy_released(session_factory):
    adv, mid, _aid = _seed(session_factory, "cur-ack", "EUR")
    result = _generate(session_factory, mid, adv, {"cmaCurrencyMismatchReason": GOOD_REASON})
    guard = result["cma_currency_guard"]
    assert guard["status"] == "acknowledged" and guard["released"] is True
    assert guard["acknowledgement_reason"] == GOOD_REASON
    assert GOOD_REASON in result["reasoning"][0]


def test_reload_payload_endpoint_carries_guard(session_factory):
    """GET .../target-allocation/current/payload (AA-Ansicht nach Reload)."""
    from routers.allocation import get_current_allocation_payload
    from routers import allocation as allocation_router

    adv, mid, _aid = _seed(session_factory, "cur-reload", "EUR")
    _generate(session_factory, mid, adv)
    with session_factory() as s:
        user = s.query(User).filter(User.id == adv).one()
        original = allocation_router._get_mandate_or_404
        allocation_router._get_mandate_or_404 = lambda m, db, u: db.query(Mandate).filter(Mandate.id == m).one()
        try:
            payload = get_current_allocation_payload(mid, db=s, current_user=user)
        finally:
            allocation_router._get_mandate_or_404 = original
    assert payload["cma_currency_guard"]["reason_code"] == CMA_CURRENCY_MISMATCH
    assert payload["reasoning"][0].startswith(MESSAGE_EUR)


def test_preference_contract_keeps_snapshot_stable_without_reason():
    assert "cmaCurrencyMismatchReason" not in pe._normalize_preferences({})
    assert pe._normalize_preferences({"cmaCurrencyMismatchReason": GOOD_REASON})["cmaCurrencyMismatchReason"] == GOOD_REASON
    with pytest.raises(Exception):
        pe._normalize_preferences({"cmaCurrencyMismatchReason": 5})


# --------------------------------------------------------------------------
# Finalisierung: 409 bis zur dokumentierten Bestaetigung
# --------------------------------------------------------------------------


def _finalize(SF, mid, run_id):
    from routers.review import _enforce_run_cma_currency

    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        run = s.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        return _enforce_run_cma_currency(s, mandate, run)


def test_finalization_blocked_with_409_on_currency_mismatch(session_factory):
    adv, mid, aid = _seed(session_factory, "cur-fin", "EUR")
    _generate(session_factory, mid, adv)
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)
    with pytest.raises(HTTPException) as exc_info:
        _finalize(session_factory, mid, run_id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason_code"] == CMA_CURRENCY_MISMATCH
    assert MESSAGE_EUR in exc_info.value.detail["message"]


@pytest.mark.parametrize("reason", ["Kundenwunsch", "ok passt so"])
def test_finalization_blocked_with_insufficient_reason(session_factory, reason):
    adv, mid, aid = _seed(session_factory, f"cur-bad-{len(reason)}", "EUR")
    _generate(session_factory, mid, adv, {"cmaCurrencyMismatchReason": reason})
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)
    with pytest.raises(HTTPException) as exc_info:
        _finalize(session_factory, mid, run_id)
    assert exc_info.value.status_code == 409
    assert "genügt nicht" in exc_info.value.detail["message"]


def test_finalization_released_after_documented_acknowledgement(session_factory):
    adv, mid, aid = _seed(session_factory, "cur-fin-ack", "EUR")
    _generate(session_factory, mid, adv, {"cmaCurrencyMismatchReason": GOOD_REASON})
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)
    warning = _finalize(session_factory, mid, run_id)
    assert warning and MESSAGE_EUR in warning and GOOD_REASON in warning


def test_finalization_unchanged_for_chf_mandate(session_factory):
    adv, mid, aid = _seed(session_factory, "cur-fin-chf", "CHF")
    _generate(session_factory, mid, adv)
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)
    assert _finalize(session_factory, mid, run_id) is None


def test_finalize_endpoint_checks_currency_before_other_validation():
    import inspect

    from routers.review import finalize_recommendation

    source = inspect.getsource(finalize_recommendation)
    assert source.index("_enforce_run_cma_currency(") < source.index("_validate_recommendation_for_finalization(")


# --------------------------------------------------------------------------
# Kundendokumente / Report
# --------------------------------------------------------------------------


def test_customer_document_blocked_with_409(session_factory):
    from routers.pdf_reports import _enforce_cma_currency_release

    adv, mid, _aid = _seed(session_factory, "cur-pdf", "EUR")
    _generate(session_factory, mid, adv)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(HTTPException) as exc_info:
            _enforce_cma_currency_release(s, mandate)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason_code"] == CMA_CURRENCY_MISMATCH


def test_all_cma_dependent_pdf_endpoints_are_gated():
    import inspect

    import routers.pdf_reports as pdf_router

    assert "_enforce_cma_currency_release(db, mandate)" in inspect.getsource(pdf_router._attach_provisional_notice)
    assert "_enforce_cma_currency_release(db, mandate)" in inspect.getsource(pdf_router.get_advisory_report_pdf)


def test_report_notice_and_pdf_banner_after_acknowledgement(session_factory):
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    from routers.pdf_reports import _enforce_cma_currency_release
    from services.pdf.provisional_notice import (
        make_provisional_notice_banner,
        resolve_pdf_provisional_notice,
    )

    adv, mid, _aid = _seed(session_factory, "cur-pdf-ack", "EUR")
    _generate(session_factory, mid, adv, {"cmaCurrencyMismatchReason": GOOD_REASON})
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        _enforce_cma_currency_release(s, mandate)  # kein 409 mehr
        notice = resolve_pdf_provisional_notice(s, mandate)
    assert notice["reason_code"] == CMA_CURRENCY_MISMATCH
    assert MESSAGE_EUR in notice["message"] and GOOD_REASON in notice["message"]

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build([make_provisional_notice_banner(notice, table_width=400)])
    text = " ".join(PdfReader(BytesIO(buf.getvalue())).pages[0].extract_text().split())
    assert "WÄHRUNGSBASIS NICHT FREIGEGEBEN" in text
    assert "Basiswährung EUR nicht freigegeben" in text


def test_report_notice_without_acknowledgement_shows_hint(session_factory):
    """Advisory-Report-JSON (provisional_data_warning) zeigt den Hinweis auch
    ohne Bestaetigung -- der Report blockiert nicht, das PDF schon."""
    from services.pdf.provisional_notice import resolve_pdf_provisional_notice

    adv, mid, _aid = _seed(session_factory, "cur-json", "EUR")
    _generate(session_factory, mid, adv)
    with session_factory() as s:
        notice = resolve_pdf_provisional_notice(s, s.query(Mandate).filter(Mandate.id == mid).one())
    assert notice["reason_code"] == CMA_CURRENCY_MISMATCH
    assert notice["acknowledged"] is False
    assert MESSAGE_EUR in notice["message"]


def test_ch_chf_mandate_notice_stays_db_free():
    fake = SimpleNamespace(jurisdiction="CH", id="x", tenant_id=None, base_currency="CHF")
    from services.pdf.provisional_notice import resolve_pdf_provisional_notice

    assert resolve_pdf_provisional_notice(None, fake) is None


# --------------------------------------------------------------------------
# AA-Ansicht (Monolith)
# --------------------------------------------------------------------------


def _monolith() -> str:
    path = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"
    return path.read_text(encoding="utf-8")


def _function_body(html: str, name: str, length: int = 2500) -> str:
    start = html.index(f"function {name}(")
    return html[start:start + length]


def test_monolith_aa_view_renders_guard_banner_above_reasoning():
    html = _monolith()
    assert "rationale.innerHTML=buildCmaCurrencyGuardHtml(result.cma_currency_guard)+" in html
    body = _function_body(html, "buildCmaCurrencyGuardHtml")
    assert "if(!guard||!guard.reason_code)return '';" in body
    assert "Strategie nicht freigegeben" in body
    assert 'id="aa-cma-currency-reason"' in body
    assert "guard.reason_code" in body


def test_monolith_acknowledgement_is_bound_to_preferences_and_survives_merge():
    html = _monolith()
    collect = _function_body(html, "collectAllocationPreferencesFromUI", 20000)
    assert "aa-cma-currency-reason" in collect
    assert "prefs.cmaCurrencyMismatchReason" in collect
    merge = _function_body(html, "mergeAllocationPreferences", 1500)
    assert "cmaCurrencyMismatchReason" in merge
    handler = _function_body(html, "onCmaCurrencyReasonChange", 400)
    assert "persistAllocationPreferences()" in handler and "markStrategyDirty" in handler
    for forbidden in ("window.prompt", "window.confirm", "window.alert"):
        assert forbidden not in handler
