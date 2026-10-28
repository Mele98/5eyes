"""DEPOT-E2E-SNAPSHOT-001: JSON-Depot-Check und Depot-Check-PDF tragen dieselbe
Snapshot-Identitaet.

Audit: docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-
publication-integrity-audit.md.

Befund (bis zu diesem Fix ``xfail(strict=True)``): ``compute_depot_check()``
(JSON) und ``_build_depotcheck_data()`` (PDF) lasen den Bestand je
unabhaengig neu ein und trugen kein gemeinsames Identitaetsfeld -- nichts
bewies, dass beide denselben Bestand zeigen.

Geloester Vertrag (CIO-Entscheid): ein gespeicherter
DepotCheckAnalysisSnapshot bindet das Ergebnis an genau einen DepotSnapshotV1
(``snapshot_id`` + ``snapshot_hash``) mit Analyse-Version und Ergebnis-Hash.
Der JSON-Endpunkt (``GET /depot-check?analysis_snapshot_id=``) und das PDF
lesen denselben gespeicherten Snapshot. Ein Klick auf das PDF speichert ihn fuer
den aktuellen Bestand (idempotent); unvollstaendige Bewertung -> 409 mit Grund.
Nur ohne erfassten Depotbestand: reine SOLL-Analyse, sichtbar gekennzeichnet.

Fixture: der Foundation-Beispielfall (wie
``tests/test_asset_allocation_reference_integrity_edges.py``), weil erst er
die volle PDF-Pipeline erfuellt; dazu ein echter, bewerteter Depotbestand
(Stueckzahl x Marktpreis) fuer die Positionen des gueltigen Laufs.
"""
from __future__ import annotations

import sys
from dataclasses import fields
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.review import PriceHistory, Product, RecommendationHolding, RecommendationPosition  # noqa: E402
from models.users import User  # noqa: E402
from routers.allocation import create_depot_check_analysis, get_depot_check  # noqa: E402
from routers.pdf_reports import _build_depotcheck_data, get_depotcheck_pdf  # noqa: E402
from services import depot_check_snapshot as dca  # noqa: E402
from services import depot_snapshot as ds  # noqa: E402
from services.currency.fx_rates import FXRateSource  # noqa: E402
from services.depot_check import _select_latest_run  # noqa: E402
from tests.test_portfolio_generate_after_saa_recalc import (  # noqa: E402,F401
    _seed_foundation,
    session_factory,
)

NOW = "2026-10-28T10:00:00.000Z"
# Testkurse (keine Fachwerte): nur damit jede Produktwaehrung bewertbar ist.
FX = FXRateSource({"CHF": 1.0, "USD": 0.9, "EUR": 0.95, "GBP": 1.1, "JPY": 0.006})

_IDENTITY_FIELDS = ("analysis_snapshot_id", "snapshot_id", "snapshot_hash", "as_of", "result_hash")


def _seed_with_holdings(session):
    """Foundation-Mandat + echter Depotbestand (1000 Stueck je Laufposition)."""
    mandate = _seed_foundation(session)
    run = _select_latest_run(session, mandate)
    today = date.today().isoformat()
    positions = (
        session.query(RecommendationPosition)
        .filter(RecommendationPosition.run_id == run.id)
        .all()
    )
    assert positions, "Foundation-Lauf ohne Positionen"
    for pos in positions:
        product = session.query(Product).filter(Product.id == pos.product_id).one()
        session.add(RecommendationHolding(
            id=f"h-{pos.id}", run_id=run.id, recommendation_position_id=pos.id,
            product_id=product.id, as_of_date=today, units_milli=1_000_000,
            source="manual", created_at=NOW, updated_at=NOW,
        ))
        session.add(PriceHistory(
            id=f"px-{pos.id}", product_id=product.id, price_date=today, price_rappen=10_000,
            currency=product.currency, source="test", fetched_at=NOW,
        ))
    session.commit()
    advisor = session.query(User).filter(User.id == "advisor-1").one()
    return mandate, advisor


def _store_analysis(session, mandate, advisor):
    snapshot = ds.build_depot_snapshot(session, mandate, as_of=date.today(), fx_source=FX)
    ds.persist_depot_snapshot(
        session, snapshot, mandate=mandate, created_by=advisor.id, created_at=NOW,
    )
    session.commit()
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    created = create_depot_check_analysis(
        mandate.id, snapshot["snapshot_id"], request, db=session, current_user=advisor,
    )
    return snapshot, created


@pytest.mark.timeout(300)
def test_json_depot_check_and_pdf_payload_share_one_snapshot_identity(session_factory):
    with session_factory() as session:
        mandate, advisor = _seed_with_holdings(session)
        snapshot, created = _store_analysis(session, mandate, advisor)

        json_payload = get_depot_check(
            mandate.id, analysis_snapshot_id=created["analysis_snapshot_id"],
            db=session, current_user=advisor,
        )
        analysis = dca.load_depot_check_analysis(
            session, mandate, created["analysis_snapshot_id"],
        )
        pdf_payload = _build_depotcheck_data(mandate, session, analysis=analysis)

    pdf_field_names = {f.name for f in fields(pdf_payload)}
    for key in _IDENTITY_FIELDS:
        assert key in json_payload and key in pdf_field_names, key
        assert json_payload[key] == getattr(pdf_payload, key), key
    assert json_payload["snapshot_id"] == snapshot["snapshot_id"]
    assert json_payload["snapshot_hash"] == snapshot["snapshot_hash"]
    # Derselbe Bestand: der IST des JSON ist der Depot-Snapshot, und das PDF
    # uebernimmt die bestandsabhaengigen Teile aus demselben Ergebnis.
    held = sum(p["amount_base_rappen"] for p in snapshot["positions"])
    assert json_payload["total_advisory_wealth_rappen"] == held
    assert dict(pdf_payload.buckets) == json_payload["buckets"]
    assert dict(pdf_payload.liquidity_profile_bps) == json_payload["liquidity_profile"]
    assert dict(pdf_payload.soll_currency_exposure_bps) == json_payload["soll_currency_exposure_bps"]


# --- Ein-Klick-PDF (CIO-Entscheid) ------------------------------------------

def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _pdf_text(response) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(response.body))
    return " ".join(" ".join((p.extract_text() or "") for p in reader.pages).split())


def _counts(session):
    from models.snapshots import DepotCheckAnalysisSnapshot, DepotSnapshot

    return (
        session.query(DepotSnapshot).count(),
        session.query(DepotCheckAnalysisSnapshot).count(),
    )


@pytest.mark.timeout(300)
def test_pdf_one_click_stores_snapshot_and_analysis_idempotently(session_factory, monkeypatch):
    # Bewertung mit Testkursen statt DB-Kursen (FX ist nicht Gegenstand).
    monkeypatch.setattr(FXRateSource, "from_db_for_model", classmethod(lambda cls, db: FX))
    with session_factory() as session:
        mandate, advisor = _seed_with_holdings(session)
        assert _counts(session) == (0, 0)
        first = get_depotcheck_pdf(
            mandate.id, _request(), analysis_snapshot_id=None, db=session, current_user=advisor,
        )
        assert _counts(session) == (1, 1)
        analysis = dca.load_depot_check_analysis(session, mandate)
        second = get_depotcheck_pdf(
            mandate.id, _request(), analysis_snapshot_id=None, db=session, current_user=advisor,
        )
        assert _counts(session) == (1, 1)
    text = _pdf_text(first)
    assert analysis["snapshot_id"] in text
    assert analysis["analysis_snapshot_id"] in text
    assert "kein Depot erfasst" not in text
    assert analysis["snapshot_id"] in _pdf_text(second)


@pytest.mark.timeout(300)
def test_pdf_with_incomplete_valuation_is_refused_with_reason(session_factory, monkeypatch):
    from models.review import PriceHistory

    monkeypatch.setattr(FXRateSource, "from_db_for_model", classmethod(lambda cls, db: FX))
    with session_factory() as session:
        mandate, advisor = _seed_with_holdings(session)
        doomed = session.query(PriceHistory).first()
        session.delete(doomed)
        session.commit()
        with pytest.raises(HTTPException) as exc:
            get_depotcheck_pdf(
                mandate.id, _request(), analysis_snapshot_id=None, db=session, current_user=advisor,
            )
        assert _counts(session) == (0, 0)
    assert exc.value.status_code == 409
    assert "Preis" in exc.value.detail or "Bewertung" in exc.value.detail, exc.value.detail


@pytest.mark.timeout(300)
def test_pdf_without_recorded_holdings_is_marked_target_only(session_factory):
    with session_factory() as session:
        mandate = _seed_foundation(session)
        advisor = session.query(User).filter(User.id == "advisor-1").one()
        assert dca.mandate_has_recorded_holdings(session, mandate) is False
        response = get_depotcheck_pdf(
            mandate.id, _request(), analysis_snapshot_id=None, db=session, current_user=advisor,
        )
        assert _counts(session) == (0, 0)
    text = _pdf_text(response)
    assert "ohne IST-Bestand (kein Depot erfasst)" in text
    assert "dps-" not in text

