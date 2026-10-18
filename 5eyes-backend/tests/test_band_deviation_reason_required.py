"""BAND-DEVIATION-REASON-REQUIRED-001 (Produktentscheid 2026-10-14).

Folgeentscheid zu BAND-OVERRIDE-DISCLOSURE-001: eine Mandatsbandbreite
ausserhalb der Hausmatrix-Bandbreite des Risikoprofils bleibt erlaubt, braucht
aber eine DOKUMENTIERTE Begruendung (Praeferenzfeld ``bandDeviationReason``,
geprueft mit ``validate_override_reason_quality``). Ohne Begruendung ist die
Freigabe BLOCKIERT (Fehler, nicht Warnung). Abweichung und Begruendung
erscheinen in den Kundendokumenten (Anlagestrategie-PDF, Beratungsentscheid)
als "Abweichung vom Eignungsrahmen des Risikoprofils".
"""
from __future__ import annotations

import json
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402
from test_band_override_house_matrix_disclosure import (  # noqa: E402
    _draft_run_with_position,
    _generate,
)
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

HEADING = "Abweichung vom Eignungsrahmen des Risikoprofils"
GOOD_REASON = (
    "Kundin haelt ausserhalb des Mandats erhebliche Immobilienwerte und "
    "wuenscht bewusst eine hoehere Aktienquote im Beratungsdepot."
)
OUTSIDE_BANDS = {"equities": {"min_bps": 7600, "max_bps": 8500}}
INSIDE_BANDS = {"equities": {"min_bps": 6200, "max_bps": 7000}}


def _gate(SF, mid, aid, adv, prefs):
    _generate(SF, mid, adv, prefs)
    run_id = _draft_run_with_position(SF, mid, aid, adv)
    with SF() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        return _validate_recommendation_for_finalization(db, mandate, run)


# --------------------------------------------------------------------------
# Freigabe-Gate: Fehler statt Warnung
# --------------------------------------------------------------------------


def test_band_outside_house_matrix_without_reason_blocks_finalization(session_factory):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "br-none")
    errors, _warnings = _gate(session_factory, mid, aid, adv, {"bands": OUTSIDE_BANDS})

    blocking = [e for e in errors if HEADING in e]
    assert blocking, errors
    assert "Aktien" in blocking[0] and "76.00" in blocking[0] and "75.00" in blocking[0], blocking
    assert "Begruendung" in blocking[0], blocking


@pytest.mark.parametrize("reason", ["", "   ", "Kundenwunsch", "ok passt so", "Kunde will das"])
def test_band_outside_house_matrix_with_insufficient_reason_blocks(session_factory, reason):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, f"br-bad-{len(reason)}")
    errors, _warnings = _gate(
        session_factory, mid, aid, adv,
        {"bands": OUTSIDE_BANDS, "bandDeviationReason": reason},
    )
    assert [e for e in errors if HEADING in e], errors


def test_band_outside_house_matrix_with_documented_reason_passes_gate(session_factory):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "br-ok")
    errors, warnings = _gate(
        session_factory, mid, aid, adv,
        {"bands": OUTSIDE_BANDS, "bandDeviationReason": GOOD_REASON},
    )
    assert not [e for e in errors if HEADING in e or "Hausmatrix" in e], errors
    documented = [w for w in warnings if HEADING in w]
    assert documented, warnings
    assert GOOD_REASON in documented[0], documented


def test_reason_added_after_generation_unblocks_gate_on_regenerate(session_factory):
    """Nachgetragene Begruendung + Neuberechnung muss das Gate freigeben.

    Absicherung gegen REGENERATE-IDEMPOTENT-001: eine Neuberechnung, die sich
    nur in der Begruendung unterscheidet, darf NICHT als identisch gelten und
    die alte Allokation (Snapshot ohne Begruendung) aktuell lassen -- sonst
    bliebe die Freigabe dauerhaft blockiert."""
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "br-later")
    from models.allocation import TargetAllocation

    def _current_ta_id():
        with session_factory() as db:
            return str(db.query(TargetAllocation.id).filter(
                TargetAllocation.mandate_id == mid,
                TargetAllocation.is_current == 1,
            ).one()[0])

    _generate(session_factory, mid, adv, {"bands": OUTSIDE_BANDS})
    first_id = _current_ta_id()
    errors, warnings = _gate(
        session_factory, mid, aid, adv,
        {"bands": OUTSIDE_BANDS, "bandDeviationReason": GOOD_REASON},
    )
    assert not [e for e in errors if HEADING in e], errors
    assert [w for w in warnings if HEADING in w and GOOD_REASON in w], warnings
    assert _current_ta_id() != first_id


def test_band_inside_house_matrix_needs_no_reason(session_factory):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "br-inside")
    errors, warnings = _gate(session_factory, mid, aid, adv, {"bands": INSIDE_BANDS})
    assert not [e for e in errors if HEADING in e], errors
    assert not [w for w in warnings if HEADING in w], warnings


# --------------------------------------------------------------------------
# Praeferenz-Vertrag
# --------------------------------------------------------------------------


def test_reason_field_is_part_of_the_preference_contract():
    normalized = pe._normalize_preferences({"bandDeviationReason": GOOD_REASON})
    assert normalized["bandDeviationReason"] == GOOD_REASON


def test_absent_reason_does_not_change_the_preference_snapshot():
    """Ohne Begruendung bleibt der persistierte Praeferenz-Snapshot
    byte-identisch zu heute -- sonst meldete die Drift-Erkennung jede
    bestehende Allokation als veraltet."""
    assert "bandDeviationReason" not in pe._normalize_preferences({})
    assert "bandDeviationReason" not in pe._normalize_preferences(None)
    assert "bandDeviationReason" not in pe._normalize_preferences({"bandDeviationReason": None})


def test_reason_field_rejects_non_string():
    with pytest.raises(Exception):
        pe._normalize_preferences({"bandDeviationReason": 123})


def test_generate_payload_exposes_house_matrix_bands(session_factory):
    """Der Bandbreiten-Editor im Monolith braucht die Hausmatrix-Bandbreite,
    um das Begruendungsfeld einzublenden; die Bucket-Bandbreite ist nach
    einem Override bereits die Mandatsbandbreite."""
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "br-payload")
    result = _generate(session_factory, mid, adv, {"bands": OUTSIDE_BANDS})
    house = result["house_matrix_bands"]
    assert house["equities"] == {"min_bps": 6000, "max_bps": 7500}, house
    assert set(house) == {"equities", "bonds", "real_estate", "alternatives", "liquidity"}

    from routers.pdf_reports import _require_strategy_decision_anchors

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        allocation, policy, assessment, cma = _require_strategy_decision_anchors(mandate, db)
        current = pe.build_target_payload_from_allocation(
            db=db, mandate=mandate, allocation=allocation, policy=policy,
            cma=cma, assessment=assessment, preferences=None,
        )
    assert current["house_matrix_bands"]["equities"] == {"min_bps": 6000, "max_bps": 7500}


# --------------------------------------------------------------------------
# Kundendokumente
# --------------------------------------------------------------------------


def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ctx():
    from services.pdf.base import PDFContext

    return PDFContext(
        mandate_name="Kundin Beispiel",
        advisor_name="Berater Beispiel",
        advisor_org="Beratungshaus",
        report_date=date(2026, 10, 14),
        audit_hash="band-reason",
    )


DEVIATION = {
    "bucket": "equities",
    "bucket_label": "Aktien",
    "house_min_bps": 6000,
    "house_max_bps": 7500,
    "mandate_min_bps": 7600,
    "mandate_max_bps": 8500,
}


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def test_contract_signoff_pdf_shows_deviation_and_reason():
    from services.pdf.base import ContractSignoffData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    data = ContractSignoffData(
        mandate_number="M-BR-01",
        advisory_wealth_rappen=500_000_00,
        risk_profile_label="Wachstumsorientiert",
        target_allocation_bps={"equities": 8000, "bonds": 1500, "liquidity": 500},
        bucket_bands_bps={"equities": (7600, 8500)},
        band_house_deviations=[DEVIATION],
        band_house_profile="Wachstumsorientiert",
        band_deviation_reason=GOOD_REASON,
    )
    text = _normalize_ws(_pdf_text(ReportLabRenderer().render_contract_signoff(_ctx(), data)))
    assert HEADING in text, text[:2000]
    assert "Aktien" in text and "76.0" in text and "75.0" in text
    assert _normalize_ws(GOOD_REASON)[:40] in text


def test_contract_signoff_pdf_without_deviation_has_no_section():
    from services.pdf.base import ContractSignoffData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    data = ContractSignoffData(
        mandate_number="M-BR-02",
        target_allocation_bps={"equities": 6500, "bonds": 3000, "liquidity": 500},
    )
    text = _normalize_ws(_pdf_text(ReportLabRenderer().render_contract_signoff(_ctx(), data)))
    assert HEADING not in text


def test_anlagestrategie_data_carries_deviation_and_reason(session_factory, monkeypatch):
    from routers.pdf_reports import _build_anlagestrategie_data, _build_contract_signoff_data

    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "br-pdf")
    _generate(session_factory, mid, adv, {"bands": OUTSIDE_BANDS, "bandDeviationReason": GOOD_REASON})
    # Der Beratungsentscheid verlangt seit COST-RUN-RESOLVER-001 (#621) eine
    # aktuelle Produktempfehlung zur aktuellen Soll-Allokation -- wie im echten
    # Ablauf (SAA -> Portfolio -> Beratungsentscheid).
    _draft_run_with_position(session_factory, mid, aid, adv)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        data = _build_anlagestrategie_data(mandate, db)
        signoff = _build_contract_signoff_data(mandate, db)

    assert data.band_deviation_reason == GOOD_REASON
    assert [d["bucket"] for d in data.band_house_deviations] == ["equities"]
    assert data.band_house_deviations[0]["house_max_bps"] == 7500
    assert data.band_house_profile == "Wachstumsorientiert"
    assert signoff.band_deviation_reason == GOOD_REASON
    assert signoff.band_house_deviations == data.band_house_deviations


def test_anlagestrategie_pdf_renders_deviation_section(session_factory):
    from routers.pdf_reports import _build_anlagestrategie_data
    from services.pdf.reportlab_renderer import ReportLabRenderer

    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "br-pdf-render")
    _generate(session_factory, mid, adv, {"bands": OUTSIDE_BANDS, "bandDeviationReason": GOOD_REASON})
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        data = _build_anlagestrategie_data(mandate, db)
    text = _normalize_ws(_pdf_text(ReportLabRenderer().render_anlagestrategie(_ctx(), data)))
    assert HEADING in text
    assert _normalize_ws(GOOD_REASON)[:40] in text


# --------------------------------------------------------------------------
# Monolith: Begruendungsfeld im Bandbreiten-Editor
# --------------------------------------------------------------------------


def _monolith() -> str:
    path = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    return path.read_text(encoding="utf-8")


def test_monolith_band_editor_has_reason_field_bound_to_preferences():
    html = _monolith()
    assert 'id="aa-band-deviation-reason"' in html
    assert "bandDeviationReason" in html
    assert HEADING in html
    # Der Editor vergleicht gegen die Hausmatrix-Bandbreite aus dem Payload,
    # nicht gegen die (bereits ueberschriebene) Bucket-Bandbreite.
    assert "house_matrix_bands" in html


def test_monolith_merge_keeps_reason_across_reload():
    html = _monolith()
    start = html.index("function mergeAllocationPreferences(")
    body = html[start:start + 1200]
    assert "bandDeviationReason" in body, body
