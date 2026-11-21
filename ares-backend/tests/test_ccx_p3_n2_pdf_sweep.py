"""CCX-P3 Nachtrag 2 (N-909-13) -- Live-Sweep ueber alle 12 PDF-Endpunkte.

CHF-Mandat mit CHF-Vermoegen und USD-Depot, Strategie und Empfehlung (Draft,
nicht versiegelt). Mit belegtem USD-Kurs (Quelle Manual, Kurs geprueft)
liefern alle FX-abhaengigen Dokumente; ihre Betraege sind konsistent
(Beratungsvermoegen identisch). Wird USD auf den Ersatzkurs gesetzt, sperren
alle FX-abhaengigen Dokumente typisiert ``CCX_FX_BASIS_MISSING`` -- auch die
mit eingefrorenen Betraegen (Portfolio, Vertrag, Protokoll, Kostenausweis inkl.
``/cost-disclosure/ex-ante``, Backtest), weil der Lauf nicht versiegelt ist.

Alle 12 Dokumente sind FX-abhaengig: die Kundeninformation druckt die
Kostenzeilen des Ex-ante-Kostenausweises, das Risikoprofil die
Vermoegensangabe des Mandats.
"""
from __future__ import annotations

import io
import re

import pytest
from pypdf import PdfReader

from tests.test_ccx_p3_strict_fx_channels import USD_DEPOT, _code
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    _seed_cashflows,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

FX_DEPENDENT = (
    "anlagestrategie.pdf", "assetallocation.pdf", "portfolio.pdf", "vertrag.pdf",
    "contract-signoff.pdf", "protokoll.pdf", "depotcheck.pdf", "backtest.pdf",
    "advisory-report.pdf", "cost-disclosure.pdf", "kundeninformation.pdf", "risikoprofil.pdf",
)


def _set_usd(api, source):
    rate = {"currency": "USD", "rate": 0.88, "source": source, "notes": "Testvektor"}
    if source != "Default":
        rate["confirm_current"] = True  # 0.88 entspricht dem Ersatzkurs -> ausdruecklich geprueft
    resp = api.put("/fx-rates", json={"rates": [rate]})
    assert resp.status_code == 200, resp.text[:300]


def _text(resp) -> str:
    return re.sub(r"[ \t]+", " ", "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages))


def _legal_profile(session_factory, mandate_id):
    """Rechtliche Angaben der Firma als offen gekennzeichnete Testwerte
    (Voraussetzung der Kundeninformation, nicht Gegenstand dieses Tests)."""
    from models.mandates import Mandate
    from services.recommendation_release_gate import mandate_tenant_id
    from tests.client_onboarding_fixture import ensure_test_legal_profile, satisfy_contract_layer

    with session_factory() as db:
        mandate = db.get(Mandate, mandate_id)
        ensure_test_legal_profile(db, mandate_tenant_id(db, mandate))
        # H-179: Datenschutzabschnitt/Depotbank-Angabe der Kundeninformation (Testwerte).
        satisfy_contract_layer(db, mandate)
        db.commit()


def _prepared(api, advisor_user, session_factory):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    resp = api.post(f"/clients/{client_id}/wealth-positions", json=USD_DEPOT)
    assert resp.status_code == 201, resp.text[:300]
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    _set_usd(api, "Manual")
    _legal_profile(session_factory, mandate_id)
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert generated.status_code in (200, 201), generated.text[:300]
    rec = api.post(f"/mandates/{mandate_id}/recommendations/generate", json={})
    assert rec.status_code in (200, 201), rec.text[:300]
    alloc_id = generated.json().get("target_allocation_id") or generated.json().get("id")
    return mandate_id, alloc_id, int(generated.json()["advisory_wealth_rappen"])


def _get(api, mandate_id, report, alloc_id):
    params = {"expected_allocation_id": alloc_id} if report == "anlagestrategie.pdf" else {}
    return api.get(f"/mandates/{mandate_id}/reports/{report}", params=params)


@pytest.mark.timeout(900)
def test_all_pdf_endpoints_with_attested_and_substitute_usd(api, advisor_user, session_factory):
    mandate_id, alloc_id, advisory = _prepared(api, advisor_user, session_factory)
    # 100'000.05 USD x 0.88 = 88'000.04 CHF stecken im Beratungsvermoegen.
    expected_amount = f"{advisory // 100:,}".replace(",", "'")

    attested = {r: _get(api, mandate_id, r, alloc_id) for r in FX_DEPENDENT}
    assert len(attested) == 12
    substitute_free = {}
    for report, resp in attested.items():
        assert resp.status_code == 200, (report, resp.status_code, resp.text[:300])
        assert resp.content[:4] == b"%PDF", report
        substitute_free[report] = _text(resp)
    for report in ("assetallocation.pdf", "portfolio.pdf", "vertrag.pdf", "protokoll.pdf",
                   "cost-disclosure.pdf", "risikoprofil.pdf"):
        assert expected_amount in substitute_free[report], (report, expected_amount)
    ex_ante = api.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert ex_ante.status_code == 200, ex_ante.text[:300]

    _set_usd(api, "Default")
    for report in FX_DEPENDENT:
        resp = _get(api, mandate_id, report, alloc_id)
        assert resp.status_code == 409, (report, resp.status_code, resp.text[:300])
        assert _code(resp) == "CCX_FX_BASIS_MISSING", (report, resp.text[:300])
    ex_ante = api.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert ex_ante.status_code == 409 and _code(ex_ante) == "CCX_FX_BASIS_MISSING", ex_ante.text[:300]
