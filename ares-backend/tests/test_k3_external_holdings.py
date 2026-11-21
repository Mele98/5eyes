"""K3 / N-915-06: Bestand ausserhalb der Empfehlung (Fremdbestand).

Vertrag (H-189):
* Titel, die der Kunde haelt, die aber nicht in der Empfehlung stehen, werden an
  der Depot-Position im Beratungsvermoegen erfasst und von Depotcheck,
  Depot-Snapshot und Handelsliste mit DERSELBEN Bewertung beruecksichtigt
  (``core.external_holdings_rule.evaluate``).
* Nie still ignoriert, nie aus dem Soll abgeleitet, nie doppelt gezaehlt:
  ist Fremdbestand erfasst, zaehlt ein Titel der Empfehlung ohne Bestand 0
  (nicht sein Zielbetrag); eine ISIN der Empfehlung ist ein Doppel.
* Fehlende Bewertung -> "nicht bewertbar" (kein Ersatzwert): keine Bandaussage,
  kein Depot-Snapshot, keine Handelsliste.
* Handelsliste: Fremdtitel IST = Wert, SOLL = 0, Aktion nur Vorschlag
  (``REVIEW``), nie eine ausfuehrbare Instruktion; nie unter der
  Anzeigeschwelle ausgeblendet.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _finalizable_run

TODAY = date.today().isoformat()

# KN6: jeder Test laeuft am Importtag (tests/import_day_clock.py).
from tests.import_day_clock import fixed_import_clock  # noqa: E402

_fixed_import_clock = fixed_import_clock(TODAY)


def _item(label="Titel A", asset_class="Aktien", currency="CHF", value=100_000_00, as_of=TODAY, isin=None):
    return {"label": label, "isin": isin, "asset_class": asset_class, "currency": currency,
            "market_value_rappen": value, "valuation_date": as_of}


def _depot_id(db, client_id):
    from models.wealth import WealthPosition

    return db.query(WealthPosition).filter(
        WealthPosition.client_id == client_id, WealthPosition.position_type == "Depot",
        WealthPosition.deleted_at.is_(None)).first().id


def _set_external(session_factory, mid, items):
    from models.mandates import Mandate
    from models.wealth import WealthPosition

    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        depot = db.get(WealthPosition, _depot_id(db, mandate.client_id))
        depot.external_holdings_json = json.dumps(items) if items else None
        db.commit()


def _depot_check(session_factory, mid):
    from models.mandates import Mandate
    from services.depot_check import compute_depot_check

    with session_factory() as db:
        return compute_depot_check(db, db.get(Mandate, mid))


def _run_targets(session_factory, run_id):
    from models.review import RecommendationPosition

    with session_factory() as db:
        return sum(int(p.target_amount_rappen or 0) for p in
                   db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).all())


def _run_isin(session_factory, run_id):
    from models.review import Product, RecommendationPosition

    with session_factory() as db:
        pos = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).first()
        product = db.get(Product, pos.product_id)
        if not product.isin:
            product.isin = _valid_isin("CH000000123")
            db.commit()
        return product.isin


def _valid_isin(body11: str) -> str:
    """Pruefziffer unabhaengig berechnet (ISO 6166: Buchstaben -> Zahlen, Luhn)."""
    digits = "".join(str(int(c, 36)) for c in body11)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return body11 + str((10 - total % 10) % 10)


# ── Validierung und Bewertung ───────────────────────────────────────────────


def test_isin_check_digit_and_item_schema():
    from pydantic import ValidationError

    from core.external_holdings_rule import isin_is_valid
    from schemas.allocation import ExternalHoldingItem

    good = _valid_isin("CH000000123")
    assert isin_is_valid(good)
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert not isin_is_valid(bad)
    item = ExternalHoldingItem(label="  Titel   A ", isin=good.lower(), asset_class="Aktien", currency="chf")
    assert (item.label, item.isin, item.currency, item.market_value_rappen) == ("Titel A", good, "CHF", None)
    for broken in ({"isin": bad}, {"asset_class": "Krypto"}, {"currency": "CH"}, {"market_value_rappen": 0}):
        with pytest.raises(ValidationError):
            ExternalHoldingItem(**{"label": "X", "asset_class": "Aktien", "currency": "CHF", **broken})


def test_unvalued_items_get_status_never_a_substitute_value(session_factory):
    from core import external_holdings_rule as eh
    from models.mandates import Mandate
    from services.depot_check import _select_latest_run, external_holdings_valuation

    _adv, mid, _aid, run_id = _finalizable_run(session_factory, "k3val")
    future = (date.today() + timedelta(days=3)).isoformat()
    isin = _run_isin(session_factory, run_id)
    _set_external(session_factory, mid, [
        _item("ok"), _item("ohne Wert", value=None), _item("ohne Stichtag", as_of=None),
        _item("Zukunft", as_of=future), _item("ohne Kurs", currency="XAU"),
        _item("Doppel", isin=isin),
    ])
    with session_factory() as db:
        mandate = db.get(Mandate, mid)
        val = external_holdings_valuation(db, mandate, _select_latest_run(db, mandate))
    status = {i["label"]: (i["status"], i["amount_base_rappen"]) for i in val["items"]}
    assert status == {
        "ok": (eh.STATUS_OK, 100_000_00),
        "ohne Wert": (eh.STATUS_MISSING_VALUE, None),
        "ohne Stichtag": (eh.STATUS_MISSING_DATE, None),
        "Zukunft": (eh.STATUS_FUTURE_DATE, None),
        "ohne Kurs": (eh.STATUS_MISSING_FX, None),
        "Doppel": (eh.STATUS_IN_RECOMMENDATION, None),
    }, status
    assert (val["total_rappen"], val["unvalued_count"]) == (100_000_00, 5)
    assert all("nicht bewertbar" in eh.STATUS_TEXT[s] for s, _a in status.values() if s != eh.STATUS_OK)


# ── Depotcheck (live) ───────────────────────────────────────────────────────


def test_depot_check_with_only_external_holdings_uses_real_stock_not_targets(session_factory):
    """Vorher: ohne Holding fiel jeder Titel der Empfehlung auf seinen Zielbetrag
    zurueck (IST = SOLL) und der Fremdbestand fehlte. Jetzt: IST = Fremdbestand."""
    _adv, mid, _aid, run_id = _finalizable_run(session_factory, "k3only")
    before = _depot_check(session_factory, mid)
    assert before["ist_basiert_auf_soll"] is True and "fremdbestand" not in before
    targets = _run_targets(session_factory, run_id)
    assert targets > 0
    _set_external(session_factory, mid, [_item("Aktie Inland", value=300_000_00),
                                         _item("Anleihe", asset_class="Obligationen", value=100_000_00)])
    dc = _depot_check(session_factory, mid)
    assert dc["total_advisory_wealth_rappen"] == 400_000_00  # kein Zielbetrag, kein Depotwert daneben
    assert dc["ist_basiert_auf_soll"] is False and dc["ist_teilweise_abgeleitet"] is False
    assert dc["buckets"]["equities"]["ist_rappen"] == 300_000_00
    assert dc["buckets"]["bonds"]["ist_rappen"] == 100_000_00
    assert dc["buckets"]["equities"]["ist_bps"] == 7500
    assert sum(b["ist_rappen"] for b in dc["buckets"].values()) == dc["total_advisory_wealth_rappen"]
    assert dc["fremdbestand_rappen"] == 400_000_00 and dc["fremdbestand_nicht_bewertbar"] == 0
    assert [p["status"] for p in dc["fremdbestand"]] == ["ok", "ok"]
    outside = [p for p in dc["top_positions"] if p.get("ausserhalb_empfehlung")]
    assert {p["product_name"] for p in outside} == {"Aktie Inland", "Anleihe"}
    if not dc["soll_ausgeblendet"]:
        assert any(b["in_band"] is not None for b in dc["buckets"].values()), dc["buckets"]


def test_depot_check_unvalued_external_title_blocks_band_statement(session_factory):
    _adv, mid, _aid, _run = _finalizable_run(session_factory, "k3unval")
    _set_external(session_factory, mid, [_item("bewertet", value=200_000_00), _item("offen", value=None)])
    dc = _depot_check(session_factory, mid)
    assert dc["fremdbestand_nicht_bewertbar"] == 1
    assert dc["total_advisory_wealth_rappen"] == 200_000_00  # nur Belegtes, kein Ersatzwert
    assert all(b["in_band"] is None for b in dc["buckets"].values())
    assert any("nicht bewertbar" in w and "offen" in w for w in dc["warnings"]), dc["warnings"]
    offen = next(p for p in dc["fremdbestand"] if p["label"] == "offen")
    assert offen["amount_rappen"] is None and offen["weight_bps"] is None


def test_depot_check_only_unvalued_external_is_visible_not_empty(session_factory):
    _adv, mid, _aid, _run = _finalizable_run(session_factory, "k3none")
    _set_external(session_factory, mid, [_item("offen", value=None)])
    dc = _depot_check(session_factory, mid)
    assert dc["total_advisory_wealth_rappen"] == 0
    assert [p["status"] for p in dc["fremdbestand"]] == ["missing_value"]
    assert not any("Kein Beratungsvermögen erfasst" in w for w in dc["warnings"])


def test_depot_check_mixed_holding_and_external_is_not_double_counted(session_factory):
    from tests.test_kn4_b_ext01_holding_depot_check import _positions, _put_holding

    _adv, mid, _aid, run_id = _finalizable_run(session_factory, "k3mix")
    positions = _positions(session_factory, run_id)
    first_id, _target, _cls = positions[0]
    _put_holding(session_factory, mid, run_id, first_id, 150_000_00)
    _set_external(session_factory, mid, [_item("Fremd", asset_class="Immobilien", value=50_000_00)])
    dc = _depot_check(session_factory, mid)
    # Holding 150k + Fremd 50k; uebrige Titel der Empfehlung ohne Bestand = 0.
    assert dc["total_advisory_wealth_rappen"] == 200_000_00
    assert dc["buckets"]["real_estate"]["ist_rappen"] == 50_000_00
    assert sum(b["ist_rappen"] for b in dc["buckets"].values()) == dc["total_advisory_wealth_rappen"]


# ── Depot-Snapshot / PDF-Quelle ─────────────────────────────────────────────


def _snapshot_seed(s, *, with_holdings=True):
    from models.review import RecommendationHolding
    from models.wealth import WealthPosition
    from tests.test_depot_snapshot_ist_stress import NOW, _seed

    advisor, mandate = _seed(s)
    if not with_holdings:
        for row in s.query(RecommendationHolding).all():
            row.deleted_at = NOW
    s.add(WealthPosition(
        id="wp-depot", client_id=mandate.client_id, label="Depot", position_type="Depot",
        assignment="Beratungsvermögen", current_value_rappen=1_000_000_00, currency="CHF",
        alloc_equities_bps=6000, alloc_bonds_bps=4000, alloc_real_estate_bps=0,
        alloc_liquidity_bps=0, alloc_alternatives_bps=0, is_active=1, created_at=NOW, updated_at=NOW,
    ))
    s.flush()
    return advisor, mandate


def _snapshot_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'k3.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()


def test_snapshot_without_external_is_unchanged_and_with_external_adds_positions(tmp_path):
    from services import depot_snapshot as ds
    from tests.test_depot_snapshot_ist_stress import AS_OF, FX

    s = _snapshot_session(tmp_path)
    _advisor, mandate = _snapshot_seed(s)
    plain = ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)
    assert all("source_kind" not in p for p in plain["positions"])  # bestehende Snapshots inhaltsgleich
    from models.wealth import WealthPosition

    s.get(WealthPosition, "wp-depot").external_holdings_json = json.dumps(
        [_item("Fremd USD", currency="USD", value=10_000_00, as_of=AS_OF.isoformat())])
    s.flush()
    snap = ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)
    ext = [p for p in snap["positions"] if p.get("source_kind") == "external_holding"]
    assert len(ext) == 1 and ext[0]["amount_base_rappen"] == 8_800_00  # USD 0.88 aus der FX-Basis
    assert ext[0]["bucket_weights_bps"] == {"equities": 10000} and ext[0]["product_id"] is None
    assert len(snap["positions"]) == len(plain["positions"]) + 1
    assert "USD" in json.dumps(snap["fx_evidence"])
    ds.verify_depot_snapshot(snap)


def test_snapshot_with_only_external_and_fail_closed_when_unvalued(tmp_path):
    from models.wealth import WealthPosition
    from services import depot_snapshot as ds
    from services.depot_check import compute_depot_check
    from services.portfolio_handoff import HoldingsValuationIncompleteError
    from tests.test_depot_snapshot_ist_stress import AS_OF, FX

    s = _snapshot_session(tmp_path)
    _advisor, mandate = _snapshot_seed(s, with_holdings=False)
    with pytest.raises(HoldingsValuationIncompleteError):
        ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)  # wie bisher: kein Bestand
    depot = s.get(WealthPosition, "wp-depot")
    depot.external_holdings_json = json.dumps([_item("Fremd", value=500_000_00, as_of="2026-10-20")])
    s.flush()
    snap = ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)
    assert [p["source_kind"] for p in snap["positions"]] == ["external_holding"]
    assert snap["holdings_as_of"] == "2026-10-20"
    dc = compute_depot_check(s, mandate, holdings_snapshot=snap)
    assert dc["total_advisory_wealth_rappen"] == 500_000_00
    assert dc["buckets"]["equities"]["ist_rappen"] == 500_000_00
    assert [p["label"] for p in dc["fremdbestand"]] == ["Fremd"]
    depot.external_holdings_json = json.dumps([_item("Fremd", value=None, as_of="2026-10-20")])
    s.flush()
    with pytest.raises(HoldingsValuationIncompleteError, match="nicht bewertbar"):
        ds.build_depot_snapshot(s, mandate, as_of=AS_OF, fx_source=FX)


# ── Handelsliste ────────────────────────────────────────────────────────────


def _live(rows):
    return {
        "holding_positions_count": sum(1 for r in rows if r["holding_present"]),
        "implied_positions_count": sum(1 for r in rows if not r["holding_present"]),
        "missing_prices_count": 0, "stale_positions_count": 0, "fx_conversion_failed_count": 0,
        "position_drifts": rows, "live_total_value_rappen": 1,
    }


def _product_row(pid, target, held=False):
    return {"id": pid, "product_id": pid, "product_name": f"Fonds {pid}", "asset_class": "Aktien",
            "target_weight_bps": target * 10000 // 400_000_00,
            "target_amount_rappen": target, "run_target_amount_rappen": target,
            "holding_present": held, "current_market_value_rappen": 0 if not held else target,
            "holding_as_of_date": TODAY if held else None, "latest_price_rappen": 10_000}


def _external_row(value=400_000_00):
    return {"id": "ext-wp-1", "wealth_position_id": "wp", "product_id": None, "product_name": "Aktie Inland",
            "isin": None, "asset_class": "Aktien", "product_currency": "CHF", "target_weight_bps": 0,
            "target_amount_rappen": 0, "latest_price_rappen": None, "reference_price_rappen": None,
            "holding_present": True, "holding_as_of_date": TODAY, "valuation_basis": "external_market_value",
            "current_market_value_rappen": value, "holding_origin": "external_holding"}


def test_trade_list_with_only_external_stock_is_reachable_and_marks_proposal():
    """N-915-06: vorher Sackgasse (kein Bestand + Depot -> keine Neugeld-Bestaetigung)."""
    from services.portfolio_handoff import (
        HOLDINGS_BASIS_RECORDED_DEPOT,
        HoldingsValuationIncompleteError,
        _snapshot_trade,
        resolve_handoff_holdings_basis,
    )

    live = _live([_product_row("a", 250_000_00), _product_row("b", 150_000_00)])
    with pytest.raises(HoldingsValuationIncompleteError):
        resolve_handoff_holdings_basis(live)  # ohne Fremdbestand: wie bisher
    rows, total, basis = resolve_handoff_holdings_basis(live, external_holdings=[_external_row()])
    assert (total, basis) == (400_000_00, HOLDINGS_BASIS_RECORDED_DEPOT)
    by_id = {r["id"]: r for r in rows}
    assert by_id["a"]["current_market_value_rappen"] == 0 and by_id["a"]["rebalance_action_code"] == "BUY"
    ext = by_id["ext-wp-1"]
    assert ext["rebalance_action_code"] == "REVIEW" and "Vorschlag" in ext["rebalance_action"]
    assert ext["rebalance_amount_rappen"] == -400_000_00 and ext["target_amount_rappen"] == 0
    trade = _snapshot_trade(ext, {})
    assert trade["instruction_kind"] == "rebalancing_recommendation"  # nie ausfuehrbar
    assert trade["holding_origin"] == "external_holding"
    with pytest.raises(HoldingsValuationIncompleteError, match="Widerspruch"):
        resolve_handoff_holdings_basis(live, confirm_no_existing_holdings=True,
                                       investable_wealth_rappen=1, external_holdings=[_external_row()])


def test_snapshot_handoff_keeps_small_external_rows_and_blocks_unvalued(session_factory, monkeypatch):
    import services.portfolio_handoff as ph
    import services.portfolio_engine_live_rebalancing as lr
    from models.mandates import Mandate
    from models.review import RecommendationRun

    _adv, mid, _aid, run_id = _finalizable_run(session_factory, "k3ho")
    live = _live([_product_row("a", 1_000_000_00)])
    monkeypatch.setattr(ph, "build_recommendation_payload_from_run",
                        lambda **_kw: {"live_rebalancing": {**live, "live_total_value_rappen": 1_000_000_00}})
    monkeypatch.setattr(lr, "holdings_not_carried_over", lambda *_a, **_k: [])
    monkeypatch.setattr(ph, "advisory_cash_entries", lambda *_a, **_k: [])
    _set_external(session_factory, mid, [_item("gross", value=995_000_00), _item("klein", value=1_000_00)])
    with session_factory() as db:
        trades, total, _basis = ph.snapshot_handoff(db, db.get(Mandate, mid), db.get(RecommendationRun, run_id), "u")
    names = {t["product_name"]: t for t in trades}
    assert total == 996_000_00
    assert "klein" in names and names["klein"]["rebalance_action_code"] == "REVIEW"  # unter 0.5 %, sichtbar
    assert not any(t["rebalance_action_code"] == "SELL" for t in trades)
    _set_external(session_factory, mid, [_item("gross", value=None)])
    with session_factory() as db:
        with pytest.raises(ph.HoldingsValuationIncompleteError, match="nicht bewertbar") as exc:
            ph.snapshot_handoff(db, db.get(Mandate, mid), db.get(RecommendationRun, run_id), "u")
    assert exc.value.reason_code == ph.REASON_HOLDINGS_INCOMPLETE


# ── Erfassungs-Route ────────────────────────────────────────────────────────


def test_route_validates_depot_rejects_recommendation_isin_and_reports_status(session_factory):
    from fastapi import HTTPException

    from models.mandates import Mandate
    from models.users import User
    from models.wealth import WealthPosition
    from routers.allocation import list_external_holdings, put_external_holdings as replace_external_holdings
    from schemas.allocation import ExternalHoldingItem, ExternalHoldingsUpdate

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "k3route")
    isin = _run_isin(session_factory, run_id)
    with session_factory() as db:
        user = db.get(User, advisor_id)
        mandate = db.get(Mandate, mid)
        depot_id = _depot_id(db, mandate.client_id)
        other = db.query(WealthPosition).filter(WealthPosition.client_id == mandate.client_id,
                                                WealthPosition.position_type != "Depot").first()
        good = ExternalHoldingItem(label="Aktie Inland", asset_class="Aktien", currency="CHF",
                                   market_value_rappen=120_000_00, valuation_date=date.today())
        if other is not None:
            with pytest.raises(HTTPException) as exc:
                replace_external_holdings(mid, other.id, ExternalHoldingsUpdate(items=[good]), db=db, current_user=user)
            assert exc.value.status_code == 422
        dup = ExternalHoldingItem(label="Doppel", isin=isin, asset_class="Aktien", currency="CHF")
        with pytest.raises(HTTPException) as exc:
            replace_external_holdings(mid, depot_id, ExternalHoldingsUpdate(items=[good, dup]), db=db, current_user=user)
        assert exc.value.status_code == 409 and exc.value.detail["reason_code"] == "EXTERNAL_HOLDING_IN_RECOMMENDATION"
        open_item = ExternalHoldingItem(label="Ohne Wert", asset_class="Obligationen", currency="CHF")
        res = replace_external_holdings(mid, depot_id, ExternalHoldingsUpdate(items=[good, open_item]),
                                        db=db, current_user=user)
        assert res.total_base_rappen == 120_000_00 and res.unvalued_count == 1
        listed = list_external_holdings(mid, db=db, current_user=user)
        statuses = [i.status for d in listed.depots for i in d.items]
        assert statuses == ["ok", "missing_value"]
        stored = json.loads(db.get(WealthPosition, depot_id).external_holdings_json)
        assert [r["label"] for r in stored] == ["Aktie Inland", "Ohne Wert"]
        cleared = replace_external_holdings(mid, depot_id, ExternalHoldingsUpdate(items=[]), db=db, current_user=user)
        assert cleared.depots[0].items == [] and db.get(WealthPosition, depot_id).external_holdings_json is None


# ── Freshness-Querschnitt ───────────────────────────────────────────────────


def test_external_change_makes_own_decision_stale_irrelevant_change_keeps_fresh(session_factory, monkeypatch):
    """Bestandsaenderung (Fremdbestand) -> eigener Entscheid STALE, Handelsliste
    gesperrt; Fremdbestand eines anderen Kunden und ein Kurs einer nicht
    gehaltenen Waehrung lassen den Entscheid unveraendert FRESH."""
    from core.reason_codes import DomainError
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from models.users import User
    from routers.portfolio_handoff import _assert_run_is_published
    from tests.test_ccx_p4_allocation_publish import _published
    from tests.test_kern_integration_cross_freshness import _new_rate, _snapshot

    _adv, approver, mid, _aid, run_id, decision = _published(session_factory, "k3fa")
    _adv_b, _appr_b, mid_b, _aid_b, run_b, decision_b = _published(session_factory, "k3fb")
    before = _snapshot(session_factory, mid, run_id, decision.envelope_id, monkeypatch)
    assert before["envelope"] == ("SEALED", "FRESH"), before

    # irrelevant: Fremdbestand eines anderen Kunden, Kurs einer nicht gehaltenen Waehrung
    _set_external(session_factory, mid_b, [_item("Fremd B", value=50_000_00)])
    with session_factory() as db:
        with db.no_autoflush:
            _new_rate(db, "GBP", 1.1111)
        db.commit()
    after = _snapshot(session_factory, mid, run_id, decision.envelope_id, monkeypatch)
    assert after == before, ("irrelevante Aenderung", before, after)
    other = _snapshot(session_factory, mid_b, run_b, decision_b.envelope_id, monkeypatch)
    assert other["envelope"][1] == "STALE", other  # Positivkontrolle: Kunde B selbst

    # relevant: Fremdbestand des eigenen Kunden
    _set_external(session_factory, mid, [_item("Fremd A", value=50_000_00)])
    stale = _snapshot(session_factory, mid, run_id, decision.envelope_id, monkeypatch)
    assert stale["envelope"][1] == "STALE", stale
    with session_factory() as db:
        user = db.get(User, approver)
        with pytest.raises(DomainError) as exc:
            _assert_run_is_published(db, db.get(Mandate, mid), db.get(RecommendationRun, run_id), user, None)
    assert str(exc.value.reason_code) == "CCX_ALLOCATION_NOT_PUBLISHABLE", exc.value.as_detail()


# ── Kunden-PDF (KN7/KN3-B-Waechterregeln) ───────────────────────────────────


def test_depotcheck_pdf_lists_external_titles_without_ids_or_raw_keys(session_factory):
    import re
    from io import BytesIO

    from pypdf import PdfReader

    from services.pdf.base import DepotCheckData, PDFContext
    from services.pdf.reportlab_renderer import ReportLabRenderer

    _adv, mid, _aid, _run = _finalizable_run(session_factory, "k3pdf")
    _set_external(session_factory, mid, [_item("Aktie Inland", value=300_000_00, as_of="2026-11-20"),
                                         _item("Anleihe Übersee", asset_class="Obligationen", value=None)])
    dc = _depot_check(session_factory, mid)
    ctx = PDFContext(mandate_name="Muster Mandat", advisor_name="Beratung", advisor_org="Beratungshaus",
                     report_date=date(2026, 11, 21), audit_hash="k3")
    pdf = ReportLabRenderer().render_depotcheck(ctx, DepotCheckData(
        mandate_number="M-K3", external_holdings=dc["fremdbestand"], warnings=dc["warnings"],
        cost_disclosure={"data_pending": True, "note": "Daten ausstehend."},
        performance={"data_pending": True, "note": "Daten ausstehend."},
    ))
    flat = " ".join(" ".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages).split())
    assert "Titel ausserhalb der Empfehlung" in flat and "Aktie Inland" in flat and "20.11.2026" in flat
    assert "nicht bewertbar – Marktwert fehlt" in flat and "Anleihe Übersee" in flat
    assert "Verkaufen oder halten ist ein Vorschlag" in flat
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", flat)
    assert not re.search(r"\b[0-9a-f]{16,}\b", flat)
    for raw in ("missing_value", "external_holding", "ext-", "in_recommendation", "None", "True"):
        assert raw not in flat, raw
    for translit in ("zaehlt", "Waehrung", "pruefen", "fuer ", "ueber"):
        assert translit not in flat, translit
