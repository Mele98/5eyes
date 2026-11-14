"""CCX-P3 Markt- und Depot-Wahrheit + P3-FX -- Pflichtregressionen.

Vertrag 2026-11-13 §6 inkl. Nachtrag P3-FX und 2026-11-14-ccx-p3-fx-contract.

* FX: zeilenweise Konversion vor jeder Addition (CHF+USD+EUR+JPY), ISO-
  Exponent, ``ares-rounding/1`` (.5-Grenze, negative Betraege), fehlender
  USD-Kurs, abgelaufener EUR-Kurs, Kurs nach dem Stichtag, Ersatzkurs
  (``Default``) ist fehlend; ``fx_basis_hash`` bindet Rate, Quelle,
  Beobachtungszeitpunkt und Zielwaehrung.
* Bewertung: jede Position sichtbar (auch Verbindlichkeit, Doppel-Depot,
  nicht uebernommener Altbestand), unbekannt bleibt ``None`` (nie 0),
  COMPLETE/PARTIAL/UNKNOWN, leerer Bestand nur mit Bestaetigung und Cashflows.
* Finalisierung: Snapshot + Ledger als Kind-Bindungen des P1-Envelopes,
  typisierte Blocker mit Audit, Marktdatenwechsel waehrend des Laufs.
* DB: append-only, geschlossener Snapshot, Mandanten-Guard, A->B->A.
* Kanaele: Bericht und App lesen dasselbe MC-Artefakt (gleicher Hash und
  gleiche Reihen); cashflow-summary mandatsgebunden.

Alle Kurse sind synthetische Testvektoren, keine Fachwerte.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from core.reason_codes import DomainError
from services.fx_basis import (
    FxBasisError,
    FxQuote,
    build_fx_basis,
    compute_fx_basis_hash,
    convert_storage_amount,
    convert_with_source,
)
from services.recommendation_position_ledger import reconcile_existing_positions
from services.valuation_completeness import classify_valuation_completeness

TODAY = date.today()


def _q(currency, rate, *, days_old=0, source="Manual", rid=None):
    return FxQuote(currency, rate, source, (TODAY - timedelta(days=days_old)).isoformat() + "T08:00:00",
                   rid or f"fx-{currency}")


# ── FX: reine Konversion ─────────────────────────────────────────────────────


def test_multicurrency_vector_is_converted_row_wise_before_addition():
    basis = build_fx_basis("CHF", ["CHF", "USD", "EUR"],
                           {"USD": _q("USD", 8000), "EUR": _q("EUR", 12000)}, as_of=TODAY)
    lines = [basis.convert(10_001, "CHF"), basis.convert(20_003, "USD"), basis.convert(30_005, "EUR")]
    assert [line.converted_amount_minor for line in lines] == [10_001, 16_002, 36_006]
    assert sum(line.converted_amount_minor for line in lines) == 62_009 != 10_001 + 20_003 + 30_005
    for line in lines:
        assert line.target_currency == "CHF" and line.fx_basis_hash == basis.fx_basis_hash
    assert lines[1].source_observed_at.startswith(TODAY.isoformat())
    assert (lines[1].fx_rate, lines[1].fx_rate_ratio, lines[1].fx_rate_ppm) == ("0.800000000000", "8000/10000", 800_000)


def test_half_minor_unit_boundary_and_negative_amounts_round_half_up_symmetric():
    # 5 * 0.9 = 4.5 -> 5 ; -5 * 0.9 = -4.5 -> -5 (vom Nullpunkt weg, ares-rounding/1)
    assert convert_storage_amount(5, rate_from_x10000=9000, rate_to_x10000=10000, target_currency="CHF") == 5
    assert convert_storage_amount(-5, rate_from_x10000=9000, rate_to_x10000=10000, target_currency="CHF") == -5
    assert convert_storage_amount(4, rate_from_x10000=9000, rate_to_x10000=10000, target_currency="CHF") == 4
    # JPY: ISO-Exponent 0 -> ganze Yen, gespeichert mit Faktor 100.
    assert convert_storage_amount(100_00, rate_from_x10000=10000, rate_to_x10000=60, target_currency="JPY") \
        == 16_667 * 100
    # Kreuzkurs USD->EUR exakt ueber das Verhaeltnis (kein Float).
    assert convert_storage_amount(1_000_00, rate_from_x10000=8000, rate_to_x10000=12000,
                                  target_currency="EUR") == 66_667


def test_missing_stale_future_and_default_rates_block_typed():
    basis = build_fx_basis(
        "CHF", ["USD", "EUR", "GBP", "JPY"],
        {"USD": None, "EUR": _q("EUR", 12000, days_old=6), "GBP": _q("GBP", 11000, days_old=-1),
         "JPY": _q("JPY", 60, source="Default")},
        as_of=TODAY,
    )
    expected = {"USD": "CCX_FX_BASIS_MISSING", "EUR": "CCX_FX_BASIS_STALE",
                "GBP": "CCX_FX_BASIS_MISMATCH", "JPY": "CCX_FX_BASIS_MISSING"}
    for currency, code in expected.items():
        with pytest.raises(FxBasisError) as exc:
            basis.convert(1_00, currency)
        assert exc.value.reason_code == code, currency
    with pytest.raises(FxBasisError) as exc:
        basis.convert(1_00, None)
    assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"
    # Grenze: genau 5 Tage alt ist noch frisch.
    fresh = build_fx_basis("CHF", ["EUR"], {"EUR": _q("EUR", 12000, days_old=5)}, as_of=TODAY)
    assert fresh.convert(1_00, "EUR").converted_amount_minor == 120


def test_fx_basis_hash_binds_rate_source_observation_and_target():
    def h(**kw):
        quote = {"currency": "USD", "rate_x10000": 8000, "source": "Manual",
                 "observed_at": TODAY.isoformat(), "rate_id": "r1"} | kw
        return compute_fx_basis_hash("CHF", TODAY.isoformat(), [FxQuote(**quote)])

    base = h()
    assert base == h()
    assert len({base, h(rate_x10000=8001), h(source="API"), h(observed_at="2026-01-01"), h(rate_id="r2")}) == 5
    assert compute_fx_basis_hash("EUR", TODAY.isoformat(), []) != compute_fx_basis_hash("CHF", TODAY.isoformat(), [])


def test_engine_converter_uses_the_same_exact_rule():
    from services.currency.fx_rates import FXRateSource

    source = FXRateSource(rates_in_chf={"CHF": 1.0, "USD": 0.8, "EUR": 1.2, "JPY": 0.006})
    basis = build_fx_basis("EUR", ["USD", "JPY"], {"USD": _q("USD", 8000), "EUR": _q("EUR", 12000),
                                                    "JPY": _q("JPY", 60)}, as_of=TODAY)
    for amount, ccy in ((20_003, "USD"), (-12_345_67, "USD"), (9_999_99, "JPY")):
        assert convert_with_source(amount, ccy, "EUR", source) == basis.convert(amount, ccy).converted_amount_minor
    # Die strikte Basis ist als Kursquelle verwendbar, blockiert aber unbelegte Kurse.
    with pytest.raises(ValueError):
        convert_with_source(1_00, "GBP", "EUR", basis)


def test_ccx07_unknown_valuation_never_complete():
    assert classify_valuation_completeness({"A": "10.00"}, {"USDCHF": "0.90"}) == {
        "status": "COMPLETE", "release_eligible": True}
    for prices, fx in (({"A": None}, {"USDCHF": "0.9"}), ({"A": "1"}, {"USDCHF": None}), ({}, {})):
        assert classify_valuation_completeness(prices, fx) == {"status": "UNKNOWN", "release_eligible": False}


def test_ccx05_every_existing_position_gets_a_decision():
    result = reconcile_existing_positions(["keep", "remove", "review"], ["keep", "new"], review=["review"])
    assert result == {"keep": "KEEP", "remove": "SELL", "review": "REVIEW"}
    assert "new" not in result


# ── Datenbank / Finalisierung ────────────────────────────────────────────────

from tests.test_ccx_p1_snapshot_hash import (  # noqa: E402
    _audit,
    _finalizable_run,
    _finalize,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401
)


def _prepared_run(session_factory, suffix, setup=None):
    """Mandat seeden, Bestand/Kurse VOR der Strategieberechnung anlegen, dann
    Soll-Allokation und finalisierbaren Lauf erzeugen (keine Staleness)."""
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    if setup is not None:
        with session_factory() as db:
            setup(db, mid)
            db.commit()
    return _finalizable_run(session_factory, suffix, mandate=(advisor_id, mid, aid))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _add_fx(db, currency, rate, *, days_old=0, source="Manual"):
    from models.fx_rate import FXRate

    stamp = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    db.query(FXRate).filter(FXRate.currency == currency, FXRate.is_current == 1).update(
        {"is_current": 0, "valid_until": stamp})
    db.add(FXRate(id=str(uuid.uuid4()), currency=currency, rate_x10000=rate, valid_from=stamp,
                  is_current=1, source=source, created_at=stamp, updated_at=stamp))


def _client_id(db, mid):
    from models.mandates import Mandate

    return db.query(Mandate).filter(Mandate.id == mid).one().client_id


def _add_position(db, mid, *, label, currency, value, assignment="Beratungsvermögen", ptype="Depot",
                  valuation_date=None, bank=None, account=None):
    from models.wealth import WealthPosition

    pid = f"pos-{label}-{uuid.uuid4().hex[:6]}"
    now = _now()
    db.add(WealthPosition(
        id=pid, client_id=_client_id(db, mid), label=label, position_type=ptype, assignment=assignment,
        current_value_rappen=value, currency=currency, valuation_date=valuation_date,
        depot_bank=bank, depot_account_number=account, alloc_equities_bps=10000 if ptype == "Depot" else 0,
        alloc_liquidity_bps=10000 if ptype == "Liquidität" else 0,
        is_active=1, created_at=now, updated_at=now,
    ))
    return pid


def _mandate(db, mid):
    from models.mandates import Mandate

    return db.query(Mandate).filter(Mandate.id == mid).one()


def _project(session_factory, mid, **kw):
    from services.holdings_valuation import project_holdings_valuation

    with session_factory() as db:
        return project_holdings_valuation(db, _mandate(db, mid), **kw)


def test_projection_is_lossless_converted_and_liability_is_negative(session_factory):
    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "p3-lossless")
    with session_factory() as db:
        _add_fx(db, "USD", 8000)
        _add_fx(db, "EUR", 12000)
        usd = _add_position(db, mid, label="usd", currency="USD", value=20_003)
        eur = _add_position(db, mid, label="eur", currency="EUR", value=30_005, ptype="Liquidität")
        debt = _add_position(db, mid, label="debt", currency="USD", value=10_000, assignment="Verbindlichkeit",
                             ptype="Custom")
        db.commit()
    projection = _project(session_factory, mid)
    rows = {r.position_id: r for r in projection.rows}
    assert {usd, eur, debt} <= set(rows)
    assert (rows[usd].base_value_minor, rows[eur].base_value_minor, rows[debt].base_value_minor) == (
        16_002, 36_006, -8_000)
    assert rows[usd].source_amount_minor == 20_003 and rows[usd].price_currency == "USD"
    assert rows[usd].fx_rate_ppm == 800_000 and rows[usd].fx_observed_at
    assert projection.coverage_status == "COMPLETE" and projection.blocker_codes == []
    base_depot = 500_000_00  # Seed: CHF-Depot im Beratungsvermoegen
    assert projection.advisory_base_minor == base_depot + 16_002 + 36_006
    assert projection.total_base_minor == base_depot + 16_002 + 36_006 - 8_000
    assert projection.fx_basis_hash == projection.fx_basis.fx_basis_hash
    assert projection.source_observed_at is not None


def test_missing_fx_is_unknown_never_zero(session_factory):
    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-unknown")
    with session_factory() as db:
        pid = _add_position(db, mid, label="usd", currency="USD", value=50_000_00)
        db.commit()
    projection = _project(session_factory, mid)
    row = next(r for r in projection.rows if r.position_id == pid)
    assert row.data_quality == "MISSING_FX" and row.base_value_minor is None
    assert projection.coverage_status == "UNKNOWN"
    assert projection.total_base_minor is None and projection.advisory_base_minor is None
    assert "CCX_FX_BASIS_MISSING" in projection.blocker_codes
    # Ersatzkurs aus DEFAULT_FX_RATES (Quelle "Default") ist ebenfalls fehlend.
    with session_factory() as db:
        _add_fx(db, "USD", 8800, source="Default")
        db.commit()
    assert _project(session_factory, mid).coverage_status == "UNKNOWN"


def test_stale_fx_and_valuation_after_cutoff_block(session_factory):
    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-stale")
    with session_factory() as db:
        _add_fx(db, "EUR", 12000, days_old=6)
        eur = _add_position(db, mid, label="eur", currency="EUR", value=1_000_00)
        future = _add_position(db, mid, label="fut", currency="CHF", value=1_000_00,
                               valuation_date=(TODAY + timedelta(days=1)).isoformat())
        db.commit()
    projection = _project(session_factory, mid)
    rows = {r.position_id: r for r in projection.rows}
    assert rows[eur].data_quality == "STALE_FX" and rows[eur].base_value_minor is None
    assert rows[future].data_quality == "FUTURE_VALUATION_DATE"
    assert {"CCX_FX_BASIS_STALE", "CCX_VALUATION_INCOMPLETE"} <= set(projection.blocker_codes)


def test_duplicate_depot_stays_visible_and_is_partial(session_factory):
    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-dup")
    with session_factory() as db:
        a = _add_position(db, mid, label="dup1", currency="CHF", value=1_000_00, bank="Bank X", account="CH 12")
        b = _add_position(db, mid, label="dup2", currency="CHF", value=1_000_00, bank="bank x", account="CH12")
        db.commit()
    projection = _project(session_factory, mid)
    rows = {r.position_id: r for r in projection.rows}
    assert rows[a].data_quality == rows[b].data_quality == "DUPLICATE_DEPOT"
    assert rows[a].base_value_minor == 1_000_00  # Wert bleibt sichtbar
    assert projection.coverage_status == "PARTIAL" and projection.total_base_minor is None
    assert projection.blocker_codes == ["CCX_VALUATION_INCOMPLETE"]


def test_empty_holdings_need_confirmation_and_flows(session_factory):
    from models.wealth import Cashflow, WealthPosition

    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-empty")
    with session_factory() as db:
        db.query(WealthPosition).update({"is_active": 0})
        db.commit()
    assert _project(session_factory, mid).blocker_codes == ["CCX_VALUATION_MISSING"]
    confirmed = _project(session_factory, mid, confirm_no_holdings=True)
    assert (confirmed.coverage_status, confirmed.holdings_basis, confirmed.total_base_minor) == (
        "COMPLETE", "confirmed_no_holdings", 0)
    with session_factory() as db:
        db.query(Cashflow).update({"is_active": 0})
        db.commit()
    assert _project(session_factory, mid, confirm_no_holdings=True).blocker_codes == ["CCX_VALUATION_MISSING"]


def test_holding_of_earlier_run_not_carried_over_stays_visible(session_factory):
    from tests.test_finalize_mandate_lock import _allocation_policy_and_cma, _make_run

    advisor_id, mid, aid, run1 = _finalizable_run(session_factory, "p3-carry")
    hid, _pid = _seed_depot_holding(session_factory, run1)
    with session_factory() as db:
        from models.allocation import TargetAllocation
        ta_id = db.query(TargetAllocation.id).filter(TargetAllocation.mandate_id == mid,
                                                     TargetAllocation.is_current == 1).scalar()
    policy, cma = _allocation_policy_and_cma(session_factory, ta_id)
    _make_run(session_factory, mid, ta_id, aid, advisor_id, policy, cma)  # neuer Lauf ohne Bestand
    projection = _project(session_factory, mid)
    row = next(r for r in projection.rows if r.position_id == hid)
    assert row.data_quality == "NOT_CARRIED_OVER" and row.base_value_minor is None
    assert projection.coverage_status == "UNKNOWN" and "CCX_VALUATION_INCOMPLETE" in projection.blocker_codes


def test_inflow_without_currency_blocks_and_is_never_guessed(session_factory):
    from models.wealth import WealthInflow

    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-inflow")
    with session_factory() as db:
        now = _now()
        db.add(WealthInflow(id="inflow-no-ccy", client_id=_client_id(db, mid), label="Erbe", source_type="Erbschaft",
                            amount_rappen=100_000_00, expected_year=TODAY.year + 3, is_recurring=0,
                            value_mode="nominal", is_active=1, created_at=now, updated_at=now))
        db.commit()
    projection = _project(session_factory, mid)
    assert projection.flow_blockers == [{"kind": "wealth_inflow", "id": "inflow-no-ccy", "currency": None,
                                         "data_quality": "MISSING_CURRENCY"}]
    assert projection.blocker_codes == ["CCX_FX_BASIS_MISSING"]
    with session_factory() as db:
        db.query(WealthInflow).update({"currency": "CHF"})
        db.commit()
    assert _project(session_factory, mid).blocker_codes == []


def _seed_depot_holding(session_factory, run_id, *, price_days_old=0, with_price=True):
    """Bestand auf das Zielprodukt des Laufs (KEEP) mit Preis zum Stichtag."""
    from models.review import PriceHistory, RecommendationHolding, RecommendationPosition

    now = _now()
    with session_factory() as db:
        position = db.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id).first()
        if with_price:
            db.add(PriceHistory(id=str(uuid.uuid4()), product_id=position.product_id,
                                price_date=(TODAY - timedelta(days=price_days_old)).isoformat(),
                                price_rappen=123_45, currency="CHF", source="test-fixture", fetched_at=now))
        hid = str(uuid.uuid4())
        db.add(RecommendationHolding(id=hid, run_id=run_id, recommendation_position_id=position.id,
                                     product_id=position.product_id, depot_bank="Bank",
                                     custody_account_number="1", as_of_date=TODAY.isoformat(),
                                     units_milli=10_500, source="manual", created_at=now, updated_at=now))
        db.commit()
    return hid, position.product_id


def test_finalize_binds_snapshot_and_ledger_into_envelope(session_factory):
    from models.snapshots import AdvisoryDecisionEnvelope, AdvisoryEnvelopeBinding
    from models.snapshots import HoldingsValuationRow, HoldingsValuationSnapshot, PositionDecisionLedger
    from services.advisory_decision_envelope import verify_envelope
    from services.holdings_valuation import verify_valuation_snapshot

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "p3-seal")
    hid, _pid = _seed_depot_holding(session_factory, run_id)
    _finalize(session_factory, advisor_id, mid, run_id)
    with session_factory() as db:
        envelope = db.query(AdvisoryDecisionEnvelope).one()
        snapshot = db.query(HoldingsValuationSnapshot).one()
        assert snapshot.coverage_status == "COMPLETE" and snapshot.mandate_id == mid
        assert verify_valuation_snapshot(db, snapshot) is None
        rows = db.query(HoldingsValuationRow).filter(HoldingsValuationRow.snapshot_id == snapshot.id).all()
        assert len(rows) == snapshot.position_count >= 2
        holding_row = next(r for r in rows if r.position_id == hid)
        # 10.5 Stueck x 123.45 = 1296.225 -> 1296.23 (half-up), CHF -> keine Konversion
        assert (holding_row.quantity_decimal_string, holding_row.source_amount_minor,
                holding_row.base_value_minor, holding_row.included_in_total) == ("10.5", 1_296_23, 1_296_23, 0)
        bindings = {b.binding_kind: b for b in db.query(AdvisoryEnvelopeBinding).all()}
        assert bindings["holdings_valuation_snapshot"].child_hash == snapshot.snapshot_hash
        assert bindings["holdings_valuation_snapshot"].object_id == snapshot.id
        ledger = db.query(PositionDecisionLedger).all()
        assert [(entry.position_id, entry.decision, entry.reason_code) for entry in ledger] == [
            (hid, "KEEP", "CCX_POSITION_IN_TARGET")]
        assert ledger[0].envelope_id == envelope.id and ledger[0].source_snapshot_hash == snapshot.snapshot_hash
        assert verify_envelope(db, envelope) is None
        sealed = _audit(db, "ccx.envelope.sealed")[0].new_value
        assert snapshot.snapshot_hash in sealed and snapshot.fx_basis_hash in sealed and "coverage=COMPLETE" in sealed


def test_finalize_blocks_unknown_fx_with_code_audit_and_no_envelope(session_factory):
    from models.review import RecommendationRun
    from models.snapshots import AdvisoryDecisionEnvelope
    from models.snapshots import HoldingsValuationSnapshot

    advisor_id, mid, _aid, run_id = _prepared_run(
        session_factory, "p3-block",
        lambda db, mid: _add_position(db, mid, label="usd", currency="USD", value=10_000_00))
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"
    assert exc.value.extra["coverage_status"] == "UNKNOWN"
    with session_factory() as db:
        assert db.query(AdvisoryDecisionEnvelope).count() == 0
        assert db.query(HoldingsValuationSnapshot).count() == 0
        assert db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one().result_status == "Draft"
        rejected = _audit(db, "ccx.envelope.rejected")
        assert len(rejected) == 1 and "stage=valuation" in rejected[0].new_value
        assert "CCX_FX_BASIS_MISSING" in rejected[0].new_value and rejected[0].tenant_id
        assert rejected[0].mandate_id == mid


@pytest.mark.parametrize("days_old,code", [(None, "CCX_VALUATION_INCOMPLETE"), (6, "CCX_VALUATION_STALE")])
def test_finalize_blocks_missing_or_stale_price(session_factory, days_old, code):
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, f"p3-price-{days_old}")
    _seed_depot_holding(session_factory, run_id, price_days_old=days_old or 0, with_price=days_old is not None)
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert exc.value.reason_code == code


def test_market_data_change_during_run_is_rejected(session_factory, monkeypatch):
    import services.holdings_valuation as envelope_module
    from models.snapshots import AdvisoryDecisionEnvelope

    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "p3-race")
    real = envelope_module.project_holdings_valuation
    calls = {"n": 0}

    def flaky(db, mandate, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # Fence-Lesung: Kurs/Bestand inzwischen geaendert
            from models.wealth import WealthPosition
            db.query(WealthPosition).filter(WealthPosition.client_id == mandate.client_id).update(
                {"current_value_rappen": WealthPosition.current_value_rappen + 1})
        return real(db, mandate, **kw)

    monkeypatch.setattr(envelope_module, "project_holdings_valuation", flaky)
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, advisor_id, mid, run_id)
    assert exc.value.reason_code == "CCX_VALUATION_STALE"
    with session_factory() as db:
        assert db.query(AdvisoryDecisionEnvelope).count() == 0
        assert "stage=valuation_fence" in _audit(db, "ccx.envelope.rejected")[0].new_value


def test_mandate_switch_a_b_a_snapshots_never_leak(session_factory):
    from models.snapshots import HoldingsValuationSnapshot

    a = _finalizable_run(session_factory, "p3-a")
    b = _finalizable_run(session_factory, "p3-b")
    _finalize(session_factory, a[0], a[1], a[3])
    _finalize(session_factory, b[0], b[1], b[3])
    from models.allocation import TargetAllocation

    with session_factory() as db:
        _add_position(db, a[1], label="new-a", currency="CHF", value=1_00)
        db.query(TargetAllocation).filter(TargetAllocation.mandate_id == a[1]).update({"is_current": 0})
        db.commit()
    a_again = _finalizable_run(session_factory, "p3-a2", mandate=(a[0], a[1], a[2]))
    _finalize(session_factory, a_again[0], a_again[1], a_again[3])
    with session_factory() as db:
        snaps = db.query(HoldingsValuationSnapshot).order_by(HoldingsValuationSnapshot.created_at).all()
        by_mandate = {}
        for snap in snaps:
            by_mandate.setdefault(snap.mandate_id, []).append(snap)
        assert len(by_mandate[a[1]]) == 2 and len(by_mandate[b[1]]) == 1
        assert by_mandate[a[1]][0].snapshot_hash != by_mandate[a[1]][1].snapshot_hash
        assert by_mandate[b[1]][0].snapshot_hash not in {s.snapshot_hash for s in by_mandate[a[1]]}


def test_snapshot_rows_and_ledger_are_append_only(session_factory):
    advisor_id, mid, _aid, run_id = _finalizable_run(session_factory, "p3-immut")
    _seed_depot_holding(session_factory, run_id)
    _finalize(session_factory, advisor_id, mid, run_id)
    statements = [
        "UPDATE holdings_valuation_snapshots SET coverage_status = 'COMPLETE'",
        "DELETE FROM holdings_valuation_snapshots",
        "UPDATE holdings_valuation_rows SET base_value_minor = 0",
        "DELETE FROM holdings_valuation_rows",
        "UPDATE position_decision_ledger SET decision = 'KEEP'",
        "DELETE FROM position_decision_ledger",
        "INSERT OR REPLACE INTO holdings_valuation_rows SELECT * FROM holdings_valuation_rows",
        "REPLACE INTO position_decision_ledger SELECT * FROM position_decision_ledger",
        "INSERT INTO holdings_valuation_rows (id, tenant_id, snapshot_id, position_id, source_kind, data_quality, "
        "included_in_total, row_hash) SELECT 'x', tenant_id, snapshot_id, 'extra', 'wealth_position', 'OK', 0, "
        "row_hash FROM holdings_valuation_rows LIMIT 1",
    ]
    for statement in statements:
        with session_factory() as db:
            with pytest.raises((IntegrityError, DBAPIError)):
                db.execute(text(statement))
                db.flush()


def test_tenant_guard_rejects_foreign_tenant_snapshot(session_factory):
    from models.tenant import Tenant
    from models.snapshots import HoldingsValuationSnapshot

    _advisor, mid, _aid, _run = _finalizable_run(session_factory, "p3-tenant")
    projection = _project(session_factory, mid)
    with session_factory() as db:
        now = _now()
        db.add(Tenant(id="tenant-foreign", display_name="Fremd", slug="fremd", created_at=now, updated_at=now))
        db.commit()
        user_id = db.execute(text("SELECT id FROM users LIMIT 1")).scalar()
        db.add(HoldingsValuationSnapshot(
            id="foreign", tenant_id="tenant-foreign", mandate_id=mid, as_of=projection.as_of,
            source_system="manual_valuation", base_currency="CHF", fx_basis_hash=projection.fx_basis_hash,
            fx_basis_json="{}", coverage_status="UNKNOWN", holdings_basis="recorded", position_count=0,
            blocker_codes_json='["CCX_VALUATION_MISSING"]', snapshot_hash="f" * 64, created_at=now,
            created_by=user_id,
        ))
        with pytest.raises((IntegrityError, DBAPIError)) as exc:
            db.flush()
        assert "MANDATE_EVIDENCE_TENANT_MISMATCH" in str(exc.value)


# ── Kanaele: Bericht = App, cashflow-summary ─────────────────────────────────


def _multicurrency_mandate(session_factory, suffix, base_currency="CHF"):
    from models.mandates import Mandate

    advisor_id, mid, aid, run_id = _finalizable_run(session_factory, suffix)
    with session_factory() as db:
        _add_fx(db, "USD", 8000)
        _add_fx(db, "EUR", 12000)
        _add_fx(db, "JPY", 60)
        db.query(Mandate).filter(Mandate.id == mid).update({"base_currency": base_currency})
        _add_position(db, mid, label="usd", currency="USD", value=200_000_00)
        _add_position(db, mid, label="eur", currency="EUR", value=50_000_00, ptype="Liquidität")
        _add_position(db, mid, label="jpy", currency="JPY", value=1_000_000_00, ptype="Liquidität")
        db.commit()
    return advisor_id, mid, aid, run_id


def _regenerate(session_factory, mid, advisor_id):
    from models.allocation import TargetAllocation
    from services.portfolio_engine import generate_target_allocation

    with session_factory() as db:
        db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mid).update({"is_current": 0})
        result = generate_target_allocation(db, _mandate(db, mid), advisor_id, preferences=None)
        db.commit()
        return result["target_allocation"].id


@pytest.mark.parametrize("base_currency", ["CHF", "JPY"])
def test_report_and_app_read_the_same_monte_carlo_artifact(session_factory, base_currency):
    from models.users import User
    from routers.allocation import get_current_allocation_payload
    from services.advisory_report import _build_monte_carlo_paths_section, _build_wealth_summary

    advisor_id, mid, _aid, _run = _multicurrency_mandate(session_factory, f"p3-mc-{base_currency}", base_currency)
    _regenerate(session_factory, mid, advisor_id)
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).one()
        app = get_current_allocation_payload(mandate_id=mid, db=db, current_user=advisor)
        mandate = _mandate(db, mid)
        report = _build_monte_carlo_paths_section(db, mandate)
        wealth = _build_wealth_summary(db, mandate, mandate.client)
    from services.monte_carlo_paths import strategy_mc_artifact_hash

    mc = app["monte_carlo"]
    assert report["projection_status"] == "current", report.get("note")
    # Derselbe Artefakt-Hash ueber die App-Payload (GET .../target-allocation/current/payload).
    assert report["artifact_hash"] == strategy_mc_artifact_hash(mc, int(app.get("external_reserve_rappen") or 0))
    assert report["seed"] == mc["seed"] and report["n_paths"] == mc["simulations"]
    sockel = 0 if mc.get("reserve_accounting_basis") else int(app.get("external_reserve_rappen") or 0)
    for q in ("p5", "p10", "p25", "p50", "p75", "p90"):
        assert report[q] == [int(v) + sockel for v in mc[f"target_{q}_series_rappen"]]
    assert report["amount_currency"] == base_currency and report["fx_basis_hash"] == wealth["fx_basis_hash"]
    # Startvermoegen: Bericht und Engine in derselben Waehrung (konvertiert).
    assert wealth["amount_currency"] == base_currency
    assert wealth["beratungsvermoegen_rappen"] == app["advisory_wealth_rappen"]


def test_report_blocks_projection_and_sums_without_rate(session_factory):
    from models.fx_rate import FXRate
    from services.advisory_report import _build_monte_carlo_paths_section, _build_wealth_summary

    advisor_id, mid, _aid, _run = _multicurrency_mandate(session_factory, "p3-mc-block")
    _regenerate(session_factory, mid, advisor_id)
    with session_factory() as db:
        db.query(FXRate).filter(FXRate.currency == "USD").update({"is_current": 0, "valid_until": _now()})
        db.commit()
        mandate = _mandate(db, mid)
        report = _build_monte_carlo_paths_section(db, mandate)
        wealth = _build_wealth_summary(db, mandate, mandate.client)
    assert report["projection_status"] == "blocked" and report["reason_code"] == "CCX_FX_BASIS_MISSING"
    assert report["p50"] == [] and report["amount_currency"] is None
    assert wealth["gesamtvermoegen_rappen"] is None and wealth["fx_status"]["currencies"] == ["USD"]


def test_cashflow_summary_is_mandate_bound_and_never_silently_chf(session_factory):
    from models.users import User
    from models.wealth import Cashflow
    from routers.clients import cashflow_summary

    advisor_id, mid, _aid, _run = _multicurrency_mandate(session_factory, "p3-cfsum", "EUR")
    with session_factory() as db:
        now = _now()
        cid = _client_id(db, mid)
        db.add(Cashflow(id="cf-usd", client_id=cid, label="USD Rente", cashflow_type="Income",
                        amount_rappen=12_000_00, currency="USD", frequency="jährlich", nature="wiederkehrend",
                        is_active=1, created_at=now, updated_at=now))
        db.commit()
        advisor = db.query(User).filter(User.id == advisor_id).one()
        bound = cashflow_summary(client_id=cid, mandate_id=mid, target_currency=None, db=db, current_user=advisor)
        assert bound.amount_currency == "EUR" and bound.fx_basis_hash and bound.valuation_as_of
        # Seed-Sparen CHF 20'000 -> EUR (1/1.2), USD 12'000 -> EUR (0.8/1.2)
        assert bound.total_income_rappen == 16_666_67 + 8_000_00
        with pytest.raises(DomainError) as exc:
            cashflow_summary(client_id=cid, mandate_id=None, target_currency=None, db=db, current_user=advisor)
        assert exc.value.reason_code == "CCX_FX_BASIS_MISMATCH"


def test_inflow_api_requires_currency():
    from pydantic import ValidationError

    from schemas.wealth import WealthInflowCreate

    base = {"label": "Erbe", "source_type": "Erbschaft", "amount_rappen": 1_00, "expected_year": 2030}
    with pytest.raises(ValidationError):
        WealthInflowCreate(**base)
    with pytest.raises(ValidationError):
        WealthInflowCreate(**base, currency="chf")
    assert WealthInflowCreate(**base, currency="USD").currency == "USD"


def test_engine_inflow_without_currency_fails_closed():
    from types import SimpleNamespace

    from services.currency.fx_rates import FXRateSource
    from services.portfolio_engine_gesamtvermoegen import _wealth_inflow_series_rappen

    inflow = SimpleNamespace(is_active=1, amount_rappen=100_00, expected_year=TODAY.year + 1, is_recurring=0,
                             duration_years=None, frequency="einmalig", value_mode="nominal", currency=None)
    with pytest.raises(ValueError, match="Waehrung fehlt"):
        _wealth_inflow_series_rappen([inflow], 5, TODAY.year, None, fx_source=FXRateSource(), target_currency="CHF")
    inflow.currency = "USD"
    series = _wealth_inflow_series_rappen(
        [inflow], 5, TODAY.year, None,
        fx_source=FXRateSource(rates_in_chf={"CHF": 1.0, "USD": 0.8}), target_currency="CHF")
    assert series[1] == 80_00


# ── Migration / Paritaet ─────────────────────────────────────────────────────

CCX_P3_REV = "6814c14575e9"
CCX_P2_REV = "d868f4eaa028"
P3_TABLES = ("holdings_valuation_snapshots", "holdings_valuation_rows", "position_decision_ledger")


def test_alembic_single_head_p3_and_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from tests.test_ccx_p1_snapshot_hash import CCX_P1_REV, _alembic_cfg

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    # Lineare Kette P1 -> P2 -> P3 (Integration CCX-P4); genau ein Head, P3 darin.
    heads = script.get_heads()
    assert len(heads) == 1
    assert CCX_P3_REV in {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert script.get_revision(CCX_P3_REV).down_revision == CCX_P2_REV
    url = f"sqlite:///{tmp_path / 'p3.db'}"
    cfg = _alembic_cfg(url)

    def snapshot():
        engine = create_engine(url)
        try:
            insp = inspect(engine)
            return set(insp.get_table_names()), {c["name"] for c in insp.get_columns("wealth_inflows")}
        finally:
            engine.dispose()

    command.upgrade(cfg, "head")
    tables, inflow_columns = snapshot()
    assert set(P3_TABLES) <= tables and "currency" in inflow_columns
    command.downgrade(cfg, CCX_P1_REV)
    tables, inflow_columns = snapshot()
    assert not set(P3_TABLES) & tables and "currency" not in inflow_columns
    command.upgrade(cfg, "head")
    assert set(P3_TABLES) <= snapshot()[0]


def test_orm_bootstrap_runtime_patch_and_alembic_are_identical_for_p3(tmp_path, monkeypatch):
    import importlib.util
    import sqlite3

    from alembic import command
    from sqlalchemy import create_engine

    import database as db_module
    from database import (
        HOLDINGS_VALUATION_SQLITE_TABLE_DDL,
        HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS,
        HOLDINGS_VALUATION_SQLITE_TRIGGERS,
        Base,
    )
    from tests.test_ccx_p1_snapshot_hash import BACKEND, _alembic_cfg

    def schema(conn):
        columns = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in P3_TABLES}
        names = ", ".join(f"'{t}'" for t in P3_TABLES)
        triggers = {r[0] for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({names})")}
        indexes = {r[0] for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ({names}) "
            "AND name NOT LIKE 'sqlite_%'")}
        return columns, triggers, indexes

    orm_db = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{orm_db}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(orm_db) as conn:
        orm = schema(conn)

    boot_db = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=boot_db, schema_path=BACKEND / "ares_schema.sql")
    with sqlite3.connect(boot_db) as conn:
        boot_columns = schema(conn)[0]
        for table in reversed(P3_TABLES):
            conn.execute(f"DROP TABLE {table}")
        # Altbestand: wealth_inflows ohne Waehrungsspalte (Laufzeitpatch ergaenzt sie).
        conn.execute("CREATE TABLE IF NOT EXISTS wealth_inflows (id TEXT PRIMARY KEY, client_id TEXT, "
                     "amount_rappen INTEGER)")
        conn.commit()
    engine = create_engine(f"sqlite:///{boot_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    with sqlite3.connect(boot_db) as conn:
        patched = schema(conn)
        assert "currency" in {r[1] for r in conn.execute("PRAGMA table_info(wealth_inflows)")}

    alembic_db = tmp_path / "alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{alembic_db}"), "head")
    with sqlite3.connect(alembic_db) as conn:
        migrated = schema(conn)

    assert orm[0] == boot_columns == patched[0] == migrated[0]
    assert orm[1] == patched[1] == migrated[1]
    assert len(orm[1]) == len(HOLDINGS_VALUATION_SQLITE_TRIGGERS) + len(HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS)
    assert orm[2] == patched[2] == migrated[2]

    schema_sql = (BACKEND / "ares_schema.sql").read_text(encoding="utf-8")
    for ddl in HOLDINGS_VALUATION_SQLITE_TABLE_DDL + HOLDINGS_VALUATION_SQLITE_TRIGGERS:
        assert ddl + ";" in schema_sql
    path = BACKEND / "alembic" / "versions" / f"{CCX_P3_REV}_ccx_p3_holdings_valuation.py"
    spec = importlib.util.spec_from_file_location("ccx_p3_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration._SQLITE_TRIGGERS == HOLDINGS_VALUATION_SQLITE_TRIGGERS + HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS


def test_no_float_in_any_p3_column():
    from models.snapshots import HoldingsValuationRow, HoldingsValuationSnapshot, PositionDecisionLedger

    for model in (HoldingsValuationSnapshot, HoldingsValuationRow, PositionDecisionLedger):
        for column in model.__table__.columns:
            assert column.type.python_type in (str, int), (model.__tablename__, column.name)
    assert json.loads("[]") == []


def test_pdf_shows_server_converted_amounts_with_currency_and_basis(session_factory):
    """App = Bericht = PDF: das PDF druckt die serverseitig konvertierten
    Betraege mit Waehrung, Stichtag und FX-Basis -- es rechnet nie selbst um."""
    from io import BytesIO

    from pypdf import PdfReader

    from core.presentation_rounding import format_stored_amount
    from services.advisory_report import compute_advisory_report
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    advisor_id, mid, _aid, _run = _multicurrency_mandate(session_factory, "p3-pdf")
    _regenerate(session_factory, mid, advisor_id)
    with session_factory() as db:
        payload = compute_advisory_report(db, _mandate(db, mid))
    wealth = payload["ausgangslage"]["wealth_summary"]
    assert wealth["amount_currency"] == "CHF" and wealth["fx_status"] is None
    text = "".join(page.extract_text() for page in PdfReader(BytesIO(
        render_advisory_report_pdf_from_payload(payload))).pages)
    import re

    text = re.sub(r"\s+", " ", text.replace("−", "-").replace(" ", " "))
    expected = format_stored_amount(wealth["beratungsvermoegen_rappen"], "CHF", 0)
    assert expected in text
    assert "Bewertungsstand" in text and wealth["valuation_as_of"] in text
    assert wealth["fx_basis_hash"][:12] in text.replace(" ", "")
