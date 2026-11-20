"""Kern-Integration H12+K1: H12 und K1 wussten nichts voneinander. Diese Tests
belegen am integrierten Stand, dass beide Summenpfade des Beratungsvermoegens
dieselbe strikte FX-Basis nutzen und dasselbe Ergebnis liefern:

* H12 N-910-11: ``routers.pdf_reports._advisory_wealth_from_capture``
  (Risikoprofil/Vertrag, Pruefklasse ``advisory_positions_live``),
* K1 CK-01: ``GET /clients/{id}/wealth-summary`` (``services.fx_basis``).

Beide konvertieren zeilenweise ueber ``services.fx_basis.load_fx_basis`` /
``FxBasis.convert`` (eine Implementierung, gleiche Frische- und
Ersatzkursregel). Unterschiedlich ist nur der Umfang der benoetigten Kurse --
bewusst: Die Kundensumme zeigt auch Brutto/Verbindlichkeiten und braucht alle
Positionswaehrungen; die beiden PDFs drucken nur das Beratungsvermoegen und
pruefen nur dessen Waehrungen (H12 N-909-20). Der zweite Test haelt diesen
Unterschied fest, damit er nicht unbemerkt kippt.

Die Kurse sind synthetische Testvektoren, keine Fachwerte.
"""
from __future__ import annotations

import pytest

from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate
from tests.test_k1_ck01_wealth_summary_fx import CHF_DEPOT, USD_DEPOT, _post, _set_usd

CHF_OTHER = {
    "label": "Synthetic CHF other", "position_type": "Liquidität", "assignment": "Anderes Vermögen",
    "current_value_rappen": 50_000_00, "currency": "CHF", "data_classification": "synthetic",
}
EUR_OTHER = {
    "label": "Synthetic EUR other", "position_type": "Liquidität", "assignment": "Anderes Vermögen",
    "current_value_rappen": 20_000_00, "currency": "EUR", "data_classification": "synthetic",
}


def _capture(session_factory, mandate_id):
    from models.mandates import Mandate
    from routers.pdf_reports import _advisory_wealth_from_capture

    with session_factory() as db:
        return _advisory_wealth_from_capture(db.get(Mandate, mandate_id), db)


def test_capture_and_wealth_summary_agree_on_advisory_wealth(api, advisor_user, session_factory):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _set_usd(api, "Manual")
    _post(api, client_id, CHF_DEPOT)
    _post(api, client_id, USD_DEPOT)
    _post(api, client_id, CHF_OTHER)

    summary = api.get(f"/clients/{client_id}/wealth-summary", params={"mandate_id": mandate_id})
    assert summary.status_code == 200, summary.text[:300]
    data = summary.json()
    # CHF 400'000 + USD 100'000 * 0.88 = CHF 488'000; Anderes Vermoegen zaehlt nur brutto.
    assert data["advisory_wealth_rappen"] == 488_000_00, data
    assert data["gross_wealth_rappen"] == 538_000_00, data
    assert _capture(session_factory, mandate_id) == data["advisory_wealth_rappen"]


def test_fx_scope_differs_by_design(api, advisor_user, session_factory):
    """EUR nur in einer Position ausserhalb des Beratungsvermoegens, ohne
    belegten Kurs: Die Kundensumme sperrt typisiert (sie braucht EUR fuer das
    Brutto), Risikoprofil/Vertrag drucken weiter das Beratungsvermoegen."""
    from services.fx_basis import FxBasisError

    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _set_usd(api, "Manual")
    _post(api, client_id, CHF_DEPOT)
    _post(api, client_id, USD_DEPOT)
    _post(api, client_id, EUR_OTHER)

    data = api.get(f"/clients/{client_id}/wealth-summary", params={"mandate_id": mandate_id}).json()
    assert str(data["amount_block_reason_code"]).startswith("CCX_FX_BASIS_"), data
    assert "EUR" in data["amount_block_currencies"], data
    assert data["advisory_wealth_rappen"] is None
    assert _capture(session_factory, mandate_id) == 488_000_00

    # Gegenrichtung: USD (im Beratungsvermoegen) nur als Ersatzkurs -> beide sperren.
    _set_usd(api, "Default")
    blocked = api.get(f"/clients/{client_id}/wealth-summary", params={"mandate_id": mandate_id}).json()
    assert str(blocked["amount_block_reason_code"]).startswith("CCX_FX_BASIS_"), blocked
    assert blocked["advisory_wealth_rappen"] is None
    with pytest.raises(FxBasisError):
        _capture(session_factory, mandate_id)


def test_k2_frontend_contracts_match_the_integrated_backend():
    """K2 <-> K1/H12: (a) jede Sperrursache der Kundensumme (K1,
    ``fx_basis.status_reason``) hat in ``advisor-guidance.js`` (BLOCK_CAUSE) eine
    eigene Ursache; (b) die H12-Ablehnung von ``PUT /tenants/me`` liefert ueber
    den zentralen Handler 409 mit ``detail.message``, die K2 im Klartext zeigt
    (``errorText``) -- nicht nur einen Code."""
    import re
    from pathlib import Path

    from core.middleware import domain_error_as_http_exception
    from core.reason_codes import DomainError, ReasonCode
    from services.fx_basis import STATUS_MISMATCH, STATUS_MISSING, STATUS_STALE, status_reason

    js = (Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "advisor-guidance.js").read_text(
        encoding="utf-8")
    block = re.search(r"var BLOCK_CAUSE = \{(.*?)\};", js, re.S)
    assert block, "BLOCK_CAUSE fehlt in advisor-guidance.js"
    frontend_codes = set(re.findall(r"(CCX_FX_BASIS_[A-Z_]+)\s*:", block.group(1)))
    backend_codes = {status_reason(s).value for s in (STATUS_MISSING, STATUS_STALE, STATUS_MISMATCH)}
    assert backend_codes == frontend_codes, (backend_codes, frontend_codes)

    exc = DomainError(ReasonCode.CCX_SINGLE_PERSON_FIRM_IMPLAUSIBLE, "Genau eine Person.", http_status=409,
                      extra={"eligible_approver_count": 2})
    http = domain_error_as_http_exception(exc)
    assert http.status_code == 409
    assert http.detail["reason_code"] == "CCX_SINGLE_PERSON_FIRM_IMPLAUSIBLE"
    assert isinstance(http.detail["message"], str) and http.detail["message"]
