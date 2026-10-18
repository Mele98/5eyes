"""Regression COST-RUN-RESOLVER-001.

Befund: ``build_cost_disclosure()`` waehlte den Quelllauf nach Rangfolge
(Final > Draft) ueber ALLE Laeufe des Mandats -- ohne Bindung an die AKTUELLE
TargetAllocation. Nach einer Neugenerierung der Soll-Allokation trug damit der
Final-Lauf der UEBERHOLTEN Allokation den FIDLEG-Kostenausweis, waehrend
Anlagestrategie-PDF, Beratungsentscheid und Portfolio-PDF diesen Lauf bereits
ueber ``resolve_current_recommendation_run`` verwarfen (PDF-RUN-RESOLVER-001).

Neue Regel: der Kostenausweis loest seinen Lauf mit DERSELBEN Funktion auf.
Der eingefrorene Nachweis (COST-CONTEXT-001b) bleibt pro Lauf -- er gilt nur,
wenn sein Lauf der aktuelle ist. Ohne aktuellen Lauf: expliziter Zustand
"keine aktuelle Produktempfehlung" statt Zahlen eines veralteten Laufs.

Zusaetzlich: der Beratungsentscheid (Contract-Signoff) ohne aktuellen Lauf
wird mit 409 blockiert, statt eine leere Produkttabelle zur Unterschrift
vorzulegen.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from services.cost_disclosure import (  # noqa: E402
    build_cost_disclosure,
    freeze_cost_disclosure_for_run,
)
from services.recommendation_run_resolver import (  # noqa: E402
    NO_CURRENT_RECOMMENDATION_MARKER,
)

from test_cert_cost_conflict_001_reproducers import (  # noqa: E402,F401
    _iso, _make_allocation, _make_policy, _make_position, _make_product,
    _make_run, _seed_mandate, cc_session_factory,
)


def _setup(sf, *, suffix: str):
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix=suffix)
    _make_product(sf, f"prd-{suffix}", ter_bps=50)
    _make_policy(sf, f"pol-{suffix}", advisor_id)
    _make_allocation(
        sf, f"ta-{suffix}", mandate_id, f"pol-{suffix}", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    return advisor_id, client_id, mandate_id


def _add_run(sf, *, suffix, ta_id, run_id, mandate_id, client_id, advisor_id,
             status, created_at, fee_bps):
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id=ta_id, policy_id=f"pol-{suffix}",
        created_by=advisor_id, result_status=status, created_at=created_at,
        fee_assumptions={"default_advisory_fee_bps": fee_bps},
    )
    _make_position(sf, run_id, f"prd-{suffix}", weight_bps=10000,
                   amount_rappen=1_000_000_00)


def _regenerate(sf, *, suffix, mandate_id, advisor_id) -> str:
    """Neue aktuelle TA; die bisherige wird historisch (is_current=0)."""
    with sf() as s:
        old = s.query(TargetAllocation).filter(
            TargetAllocation.id == f"ta-{suffix}").one()
        old.is_current = 0
        s.commit()
    new_id = f"ta-{suffix}-v2"
    _make_allocation(
        sf, new_id, mandate_id, f"pol-{suffix}", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    return new_id


def _payload(sf, mandate_id):
    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        return build_cost_disclosure(db, mandate)


def _rates(payload):
    return {
        item["key"]: item["rate_bps"]
        for item in payload["cost_items"]
        if item.get("rate_bps") is not None
    }


def test_final_of_superseded_allocation_is_not_the_cost_basis(cc_session_factory):
    """Der Befund: Final der alten TA trug den Ausweis der neuen Allokation."""
    sf = cc_session_factory
    suffix = "rr-stale"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    _add_run(sf, suffix=suffix, ta_id=f"ta-{suffix}", run_id="run-old-final",
             mandate_id=mandate_id, client_id=client_id, advisor_id=advisor_id,
             status="Final", created_at=_iso(datetime.now(timezone.utc)), fee_bps=25)
    assert _payload(sf, mandate_id)["source_run_id"] == "run-old-final"

    _regenerate(sf, suffix=suffix, mandate_id=mandate_id, advisor_id=advisor_id)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] is None, (
        "Kostenausweis stammt aus dem Lauf einer ueberholten Allokation"
    )
    assert payload["data_pending"] is True
    assert payload["cost_items"] == []
    assert any(
        NO_CURRENT_RECOMMENDATION_MARKER in w for w in payload["warnings"]
    ), payload["warnings"]


def test_frozen_evidence_of_superseded_allocation_is_not_returned(cc_session_factory):
    """COST-CONTEXT-001b bleibt pro Lauf: der Snapshot eines NICHT aktuellen
    Laufs darf den Ausweis der aktuellen Allokation nicht tragen."""
    sf = cc_session_factory
    suffix = "rr-frozen"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    _add_run(sf, suffix=suffix, ta_id=f"ta-{suffix}", run_id="run-frozen-final",
             mandate_id=mandate_id, client_id=client_id, advisor_id=advisor_id,
             status="Final", created_at=_iso(datetime.now(timezone.utc)), fee_bps=25)
    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        run = db.query(RecommendationRun).filter(
            RecommendationRun.id == "run-frozen-final").one()
        run.cost_disclosure_snapshot_json = freeze_cost_disclosure_for_run(db, mandate, run)
        assert run.cost_disclosure_snapshot_json
        db.commit()
    frozen = _payload(sf, mandate_id)
    assert frozen["evidence_frozen"] is True
    assert frozen["source_run_id"] == "run-frozen-final"

    _regenerate(sf, suffix=suffix, mandate_id=mandate_id, advisor_id=advisor_id)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] is None
    assert payload["evidence_frozen"] is False
    assert payload["data_pending"] is True


def test_draft_of_current_allocation_beats_final_of_old_one(cc_session_factory):
    sf = cc_session_factory
    suffix = "rr-draft"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    t0 = datetime.now(timezone.utc)
    _add_run(sf, suffix=suffix, ta_id=f"ta-{suffix}", run_id="run-old-final2",
             mandate_id=mandate_id, client_id=client_id, advisor_id=advisor_id,
             status="Final", created_at=_iso(t0), fee_bps=25)
    new_ta = _regenerate(sf, suffix=suffix, mandate_id=mandate_id, advisor_id=advisor_id)
    _add_run(sf, suffix=suffix, ta_id=new_ta, run_id="run-new-draft",
             mandate_id=mandate_id, client_id=client_id, advisor_id=advisor_id,
             status="Draft", created_at=_iso(t0 + timedelta(minutes=5)), fee_bps=40)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] == "run-new-draft"
    assert _rates(payload).get("default_advisory_fee_bps") == 40


def test_unbound_run_is_not_a_cost_basis(cc_session_factory):
    """Ein Lauf ohne target_allocation_id passt zu keiner Allokation."""
    sf = cc_session_factory
    suffix = "rr-unbound"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    _add_run(sf, suffix=suffix, ta_id=None, run_id="run-unbound",
             mandate_id=mandate_id, client_id=client_id, advisor_id=advisor_id,
             status="Final", created_at=_iso(datetime.now(timezone.utc)), fee_bps=25)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] is None
    assert any(
        NO_CURRENT_RECOMMENDATION_MARKER in w for w in payload["warnings"]
    ), payload["warnings"]


# ---------------------------------------------------------------------------
# Beratungsentscheid ohne aktuellen Lauf -> 409
# ---------------------------------------------------------------------------

from test_pdf_recommendation_run_resolver import (  # noqa: E402
    _regenerate_defensive,
    _seed_foundation,
    session_factory,  # noqa: F401
)


def test_contract_signoff_without_current_run_is_blocked(session_factory):
    import routers.pdf_reports as pdf

    with session_factory() as s:
        mandate = _seed_foundation(s)
        # Vorher: aktueller Run vorhanden -> Beratungsentscheid baubar.
        assert pdf._build_contract_signoff_data(mandate, s).sub_allocations

        _regenerate_defensive(s, mandate)

        with pytest.raises(ValueError) as exc:
            pdf._build_contract_signoff_data(mandate, s)
        message = str(exc.value)
        assert NO_CURRENT_RECOMMENDATION_MARKER in message
        assert "Beratungsentscheid" in message


def test_contract_signoff_endpoint_maps_missing_run_to_409(session_factory, monkeypatch):
    from fastapi import HTTPException

    import routers.pdf_reports as pdf

    with session_factory() as s:
        mandate = _seed_foundation(s)
        _regenerate_defensive(s, mandate)
        monkeypatch.setattr(pdf, "get_mandate_for_user_or_404", lambda *_a, **_k: mandate)
        monkeypatch.setattr(
            pdf, "_build_pdf_context",
            lambda *_a, **_k: type("Ctx", (), {"mandate_name": "m", "report_date": __import__("datetime").date.today()})(),
        )
        # Rendern selbst ist nicht Gegenstand: vorher lief der Endpoint mit
        # leerer Tabelle bis hierher durch.
        monkeypatch.setattr(pdf.ReportLabRenderer, "render_contract_signoff", lambda *_a, **_k: b"%PDF")

        with pytest.raises(HTTPException) as exc:
            pdf.get_contract_signoff_pdf(str(mandate.id), db=s, current_user=object())
        assert exc.value.status_code == 409
        assert NO_CURRENT_RECOMMENDATION_MARKER in str(exc.value.detail)
