"""H-187 Fixrunde 1, N-935-03: Kundeninformation ohne Gebuehrenvereinbarung.

Ohne vereinbarten jaehrlichen Dienstleistungssatz druckt die Kundeninformation
kein "Total erstes Jahr" (es waere zu tief), sondern "Dienstleistungsgebühr:
nicht vereinbart", und das Dokument ist ein Entwurf (Wasserzeichen, nie
archiviert). Mit vereinbartem Satz (auch 0) unveraendert final und archiviert.
"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import TENANT, Req, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402

from models.review import ContractDocument  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import (  # noqa: E402
    ensure_test_contract_layer_tenant, ensure_test_legal_profile,
)
from test_h187_fixrunde1_n935 import _full_payload, _payload_with_zero_fee, _payload_without_fee  # noqa: E402


def _ready(db):
    ensure_test_legal_profile(db, TENANT)
    ensure_test_contract_layer_tenant(db, TENANT, actor_id="adm-1")
    db.commit()


@pytest.mark.no_test_fee_model
def test_kundeninformation_without_fee_agreement_is_a_draft_without_total(sf, monkeypatch):
    from routers.pdf_reports import FEE_NOT_AGREED_NOTE, _build_kundeninformation_data, get_kundeninformation_pdf

    monkeypatch.setattr("routers.pdf_reports.build_cost_disclosure", lambda db, m: _payload_without_fee())
    with sf() as db:
        adv = user(db, "adv-1")
        _ready(db)
        data = _build_kundeninformation_data(db, mandate(db), gate.load_tenant_legal_profile(db, TENANT))
        assert data.fee_agreement_missing is True
        labels = [label for label, _value in data.cost_lines]
        assert "Total erstes Jahr" not in labels
        assert ("Dienstleistungsgebühr", "nicht vereinbart") in data.cost_lines
        assert data.cost_note.startswith(FEE_NOT_AGREED_NOTE)
        resp = get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=adv)
        assert resp.body.startswith(b"%PDF")
        assert resp.headers.get("X-Ares-Draft") == "gebuehren"
        assert "X-Client-Information-Document-Id" not in resp.headers
        assert db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").count() == 0


@pytest.mark.no_test_fee_model
@pytest.mark.parametrize("payload_factory", [_full_payload, _payload_with_zero_fee], ids=["satz", "satz-0"])
def test_kundeninformation_with_fee_agreement_stays_final_and_archived(sf, monkeypatch, payload_factory):
    from routers.pdf_reports import get_kundeninformation_pdf

    monkeypatch.setattr("routers.pdf_reports.build_cost_disclosure", lambda db, m: payload_factory())
    with sf() as db:
        adv = user(db, "adv-1")
        _ready(db)
        resp = get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=adv)
        assert "X-Ares-Draft" not in resp.headers
        assert resp.headers["X-Client-Information-Document-Id"]
        assert db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").count() == 1
