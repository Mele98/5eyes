"""KN4-B (Backend/PDF nach Pruefung R3 und E2E-Runde 4).

Je Befund ein Test; Gegenproben siehe Handoff H-174.

* E2E4-03: Praeferenzen im Kunden-PDF «Vertragsunterzeichnung» nur als
  Kundentexte (Label-Liste), unbekannte Schluessel weggelassen, nie roh.
* E2E4-04 + N-917R3-03/04: eine Definition «IST teilweise abgeleitet»;
  Advisory-Report druckt kein IST aus Sollwerten; Depotcheck nie
  «kein Depot erfasst», wenn ein Depot als Vermoegensposition existiert.
* E2E4-11: Statuslabel «Ausstehend» statt «Pendant».
* N-917R3-05: fehlendes Ist -> nicht bewertbar im Review-Trigger.
* N-917R3-06: tenant_id-Aenderung an Kunden/Mandaten/Positionen gesperrt;
  Uebergangs-Hashes nur fuer Altsiegel.
* N-917R3-07: Verzehr-Wortwahl am rohen Startwert, Jahreslabel geparst.
* N-917R3-08: Depot-Aufteilung mit derselben Toleranz wie die UI.
* E2E4-07: fehlende Kurse -- alle Waehrungen genannt.
* E2E4-10/13: deutsche Servermeldungen ohne Feldnamen.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401


# ── E2E4-03 ──────────────────────────────────────────────────────────────────

UI_PREFERENCES = {
    "policy": {"hedging": "none", "homeBias": "ch_focus", "universe": "funds_only"},
    "assetClasses": {"altsGold": True, "bondsDuration": "Langfristig", "bondsInvestmentGrade": True,
                     "equitiesGeo": "Schweiz Fokus", "equitiesLargeCap": True, "equitiesSmid": False,
                     "liquidityReserveTarget": 5, "futureKey": "x"},
    "product": {"fundsOnly": True},
}
RAW_KEY = re.compile(r"\b[a-z]+[A-Z][A-Za-z]*\s*:")
PYTHON_VALUE = re.compile(r"\b(True|False|None)\b")


def test_signoff_preferences_are_customer_texts_never_raw_keys():
    from routers.pdf_reports import _format_portfolio_orientation

    text = _format_portfolio_orientation(UI_PREFERENCES)
    assert not RAW_KEY.search(text), text
    assert not PYTHON_VALUE.search(text), text
    assert "_" not in text, text
    for expected in ("Heimmarkt Schweiz bevorzugt", "Nur Fonds/ETFs", "Gold und Rohstoffe",
                     "Obligationen mit langer Laufzeit", "Aktien mit Schweiz-Schwerpunkt",
                     "Aktien grosser Unternehmen", "Obligationen guter Bonität"):
        assert expected in text, (expected, text)
    # "Nur Fonds/ETFs" (Universum und Produktvorgabe) nur einmal; unbekannte und
    # nicht freigeschaltete Schluessel (futureKey, liquidityReserveTarget, False) fehlen.
    assert text.count("Nur Fonds/ETFs") == 1
    assert "futureKey" not in text and "liquidityReserveTarget" not in text and "kleiner" not in text


def test_signoff_without_known_preferences_falls_back_to_neutral_sentence():
    from routers.pdf_reports import _format_portfolio_orientation

    text = _format_portfolio_orientation({"policy": {"homeBias": "unbekannt"}, "geo": {"neu": True}})
    assert text.startswith("Die Portfolioausrichtung folgt der dokumentierten Zielallokation"), text


def test_raw_key_guard_detects_the_old_output():
    old = "Dokumentierte Präferenzen: hedging: none; homeBias: ch_focus; altsGold: True."
    assert RAW_KEY.search(old) and PYTHON_VALUE.search(old)


# ── E2E4-04 / N-917R3-03/04 ──────────────────────────────────────────────────


def _pos(current, target):
    return SimpleNamespace(current_amount_rappen=current, target_amount_rappen=target)


def test_one_definition_partially_derived_ist():
    from core.holdings_rule import ist_partially_derived

    assert ist_partially_derived([_pos(100, 100), _pos(0, 50)]) is True      # Teil-Rueckfall
    assert ist_partially_derived([_pos(None, 50)]) is True                   # fehlt
    assert ist_partially_derived([_pos(100, 100), _pos(30, 0)]) is False     # alle mit Bestand
    assert ist_partially_derived([_pos(0, 0)]) is False                      # weder Bestand noch Ziel
    assert ist_partially_derived([]) is False


def test_depot_check_partial_fallback_has_no_band_statement(session_factory):
    from services.depot_check import compute_depot_check
    from tests.test_depot_check import (
        _make_mandate, _make_product, _make_rec_position, _make_rec_run, _make_target_allocation, _make_user,
    )

    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        eq = _make_product(s, asset_class="Aktien", sub_asset_class="Aktien Schweiz")
        bd = _make_product(s, asset_class="Obligationen", sub_asset_class="Obligationen CHF")
        s.flush()
        _make_rec_position(s, run_id=run.id, product_id=eq.id, current_amount_rappen=500_000_00)
        held = _make_rec_position(s, run_id=run.id, product_id=bd.id, current_amount_rappen=0)
        held.target_amount_rappen = 500_000_00
        _make_target_allocation(s, mandate_id=mandate.id, equities_bps=5000, bonds_bps=5000,
                                real_estate_bps=0, alternatives_bps=0, liquidity_bps=0)
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["ist_basiert_auf_soll"] is True
    assert all(bucket["in_band"] is None for bucket in result["buckets"].values()), result["buckets"]


def test_advisory_sections_never_print_ist_from_target_values():
    from services.advisory_report import _build_asset_allocation, _build_branchen, _build_risikowaehrungen

    dc = {"buckets": {"equities": {"ist_bps": 0, "soll_bps": 0, "band_min_bps": 0, "band_max_bps": 0,
                                   "in_band": None},
                      "bonds": {"ist_bps": 9310, "soll_bps": 9310, "band_min_bps": 8000, "band_max_bps": 10000,
                                "in_band": None}},
          "currency_exposure_bps": {"CHF": 10000}, "soll_currency_exposure_bps": {"CHF": 10000}}
    aa = _build_asset_allocation(dc, ist_basiert_auf_soll=True)
    assert aa["ist_bps"] is None and aa["drift_bps"] is None
    assert all(item["ist_bps"] is None and item["in_band"] is None for item in aa["items"])
    assert {item["label"]: item["soll_bps"] for item in aa["items"]}["Obligationen"] == 9310
    assert "nicht vollständig erfasst" in aa["anmerkungen"]
    for section in (_build_risikowaehrungen(dc, ist_basiert_auf_soll=True), _build_branchen(dc, ist_basiert_auf_soll=True)):
        assert section["ist_bps"] is None and all(item["ist_bps"] is None for item in section["items"])
    # Gegenstueck: mit Bestand bleibt das IST sichtbar.
    assert _build_asset_allocation(dc, ist_basiert_auf_soll=False)["ist_bps"]["Obligationen"] == 9310


def test_bar_chart_shows_not_assessable_instead_of_ist_zero():
    from io import BytesIO

    from pypdf import PdfReader
    from reportlab.platypus import SimpleDocTemplate

    from services.pdf.components.advisory_bar_chart import make_bar_chart_ist_soll
    from services.pdf.fonts import register_editorial_fonts

    register_editorial_fonts()
    buf = BytesIO()
    SimpleDocTemplate(buf).build([make_bar_chart_ist_soll([
        {"label": "Aktien", "ist_bps": None, "soll_bps": 0, "drift_bps": None},
        {"label": "Obligationen", "ist_bps": None, "soll_bps": 9310, "drift_bps": None},
    ], inner_width_pt=400)])
    text = " ".join((p.extract_text() or "") for p in PdfReader(BytesIO(buf.getvalue())).pages)
    assert "IST nicht beurteilbar" in " ".join(text.split()) and "IST 0.0" not in text, text


def test_depotcheck_label_never_claims_no_depot_when_a_depot_position_exists():
    from services.pdf.documents.depotcheck import (
        HOLDINGS_NOT_PER_TITLE_LABEL, WITHOUT_HOLDINGS_LABEL, _without_holdings_label,
    )

    assert _without_holdings_label(SimpleNamespace(depot_position_recorded=True)) == HOLDINGS_NOT_PER_TITLE_LABEL
    assert "kein Depot erfasst" not in HOLDINGS_NOT_PER_TITLE_LABEL
    assert _without_holdings_label(SimpleNamespace(depot_position_recorded=False)) == WITHOUT_HOLDINGS_LABEL


def test_advisory_status_label_is_ausstehend():
    from services.pdf.documents import advisory_report as doc

    source = open(doc.__file__, encoding="utf-8").read()
    assert '"nicht_beurteilbar":("Ausstehend"' in source and '("Pendant"' not in source


# ── N-917R3-05 ───────────────────────────────────────────────────────────────


def test_review_trigger_missing_ist_is_not_evaluable():
    from services.review_engine import band_drifts

    assert band_drifts([{"asset_class": "Aktien", "band_min_bps": 1000, "band_max_bps": 2000}]) == []
    assert band_drifts([{"asset_class": "Aktien", "current_weight_bps": None,
                         "band_min_bps": 1000, "band_max_bps": 2000}]) == []
    # Positivkontrolle: 0 % ist ein Wert (unter Minimum).
    assert band_drifts([{"asset_class": "Aktien", "current_weight_bps": 0,
                         "band_min_bps": 1000, "band_max_bps": 2000}])[0]["breach_bps"] == 1000


# ── N-917R3-06 ───────────────────────────────────────────────────────────────


def test_tenant_reassignment_of_existing_rows_is_forbidden(session_factory):
    from tests.test_ccx_p4_allocation_publish import _published
    from models.clients import Client
    from models.mandates import Mandate
    from models.wealth import WealthPosition

    _a, _b, mid, _aid, _run, _decision = _published(session_factory, "kn4-tenant")
    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        client = db.get(Client, mandate.client_id)
        client.tenant_id = "main"  # NULL -> Default (wie Backfill): erlaubt
        db.commit()
        client.tenant_id = "firma-b"
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.commit()
        db.rollback()
    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        mandate.tenant_id = mandate.tenant_id or "main"
        db.commit()
        mandate.tenant_id = "firma-b"
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.commit()
        db.rollback()
    with session_factory() as db:
        with pytest.raises(RuntimeError, match="TENANT_REASSIGNMENT_FORBIDDEN"):
            db.query(WealthPosition).filter(WealthPosition.client_id.isnot(None)).update(
                {WealthPosition.tenant_id: "firma-b"}, synchronize_session=False)
        db.rollback()


def test_legacy_hashes_only_for_envelopes_sealed_before_the_switch():
    from services.effective_input_manifest import DependencyPart, legacy_projection_allowed

    part = DependencyPart("client", "c1", None, "a" * 64, legacy_hashes=("b" * 64,))
    assert part.accepts("b" * 64) and not part.accepts("b" * 64, allow_legacy=False)
    assert part.accepts("a" * 64, allow_legacy=False)
    assert legacy_projection_allowed("2026-11-19T10:00:00.000Z") is True
    assert legacy_projection_allowed("2026-11-21T10:00:00.000Z") is False
    assert legacy_projection_allowed(None) is False


# ── N-917R3-07 ───────────────────────────────────────────────────────────────


def test_depletion_wording_uses_raw_start_like_the_app():
    from core.depletion_display import _year_of, depletion_note

    # Roher Start negativ, Reserve hebt ihn ueber 0: App sagt "Finanzierungslücke".
    assert depletion_note(["2026", "2027"], [-50, -500], offset=100) == "Finanzierungslücke ab 2027"
    assert depletion_note(["2026", "2027"], [100, -500]) == "Vermögen aufgebraucht ab 2027"
    assert _year_of("2042-12-31") == "2042" and _year_of("Ende 2042") == "2042"
    assert _year_of("Jahr 5") is None and _year_of(None) is None
    assert depletion_note(["Jahr 1", "Jahr 2"], [100, -5]) == "Vermögen aufgebraucht"


# ── N-917R3-08 ───────────────────────────────────────────────────────────────


def test_depot_allocation_tolerance_matches_the_ui():
    from pydantic import ValidationError

    from schemas.wealth import WealthPositionCreate, allocation_total_is_100

    assert allocation_total_is_100(9999) and allocation_total_is_100(9995) and allocation_total_is_100(10004)
    assert not allocation_total_is_100(9994) and not allocation_total_is_100(10005)
    base = {"label": "Depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
            "current_value_rappen": 100_000_00, "currency": "CHF"}
    pos = WealthPositionCreate(**base, alloc_equities_bps=3333, alloc_bonds_bps=3333, alloc_liquidity_bps=3333)
    total = pos.alloc_equities_bps + pos.alloc_bonds_bps + pos.alloc_liquidity_bps
    assert total == 10000  # Rundungsrest normiert, nichts erfunden
    with pytest.raises(ValidationError) as exc:
        WealthPositionCreate(**base, alloc_equities_bps=3300, alloc_bonds_bps=3300, alloc_liquidity_bps=3300)
    assert exc.value.errors()[0]["msg"] == "Die Aufteilung des Depots muss zusammen 100 % ergeben (erfasst: 99 %)."


# ── E2E4-07 ──────────────────────────────────────────────────────────────────


def test_missing_rates_name_all_currencies():
    from services.currency.fx_rates import FxBasisError
    from services.fx_basis import build_fx_basis, resolve_as_of

    basis = build_fx_basis("CHF", ["USD", "EUR"], {"USD": None, "EUR": None}, as_of=resolve_as_of(None),
                           max_age_days=5)
    with pytest.raises(FxBasisError) as exc:
        basis.require_convertible(["CHF", "USD", "EUR"])
    assert exc.value.extra["currencies"] == ["EUR", "USD"]
    assert "EUR" in exc.value.message and "USD" in exc.value.message


# ── E2E4-10 / E2E4-13 ────────────────────────────────────────────────────────


def test_kyc_messages_are_german_without_field_names():
    from pydantic import ValidationError

    from schemas.clients import KycConfirmationRequest

    with pytest.raises(ValidationError) as exc:
        KycConfirmationRequest(form_type="A", form_completed_on="2026-11-01", external_reference="abc",
                               risk_category="normal", is_pep=False, identification_confirmed=True,
                               identification_date="2026-11-01", next_review_due="2026-10-01")
    msg = exc.value.errors()[0]["msg"]
    assert msg == "Die nächste Aktualisierung muss nach dem Datum des Formulars liegen."
    assert "_" not in msg and "Value error" not in msg


def test_bootstrap_email_error_is_german():
    from pydantic import ValidationError

    from schemas.users import BootstrapAdminRequest

    with pytest.raises(ValidationError) as exc:
        BootstrapAdminRequest(username="admin", password="Sicher-1234!", full_name="Erika Testberaterin",
                              email="erika@test.invalid")
    msg = exc.value.errors()[0]["msg"]
    assert msg.startswith("Bitte eine gültige E-Mail-Adresse angeben"), msg
    with pytest.raises(ValidationError) as exc:
        BootstrapAdminRequest(username="admin", password="kurz", full_name="Erika Testberaterin")
    assert exc.value.errors()[0]["msg"] == "Das Passwort muss mindestens 10 Zeichen lang sein."
