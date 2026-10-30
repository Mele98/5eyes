"""DEPOT-E2E-STRESS-001 Option 2 + DEPOT-E2E-SNAPSHOT-001: IST-Stress auf einem
unveraenderlichen, hash-gebundenen DepotSnapshotV1.

Vertrag:
* Bestandsquelle sind die Holdings des juengsten nicht abgeloesten Laufs
  (CIO-Entscheid 2026-10-28; keine Mischung ueber Laeufe, abgeloeste Laeufe
  nie), bewertet nach den Regeln der Handelsliste (``value_mandate_holdings`` +
  ``assert_holdings_valuation_complete``); jede Bewertungsluecke (kein
  Bestand, fehlender/veralteter Preis, FX-Fehler, nur Marktwert ohne
  Stueckzahl, fehlender Bestandsstichtag) -> kein Snapshot. Laufpositionen
  ohne Bestand sind irrelevant. ``holdings_as_of`` ist der aelteste Stichtag.
* Der Snapshot-Hash ist stabil und bindet Positionen, Werte, Waehrung,
  Stichtag und FX-Quelle; Manipulation wird erkannt (Replay -> 409),
  UPDATE/DELETE sind per Trigger verboten.
* Der IST-Stress nutzt exakt die Szenarien des SOLL-Stress-Replays, auf den
  IST-Gewichten, und ist als IST beschriftet.
* Positionen ohne eindeutige Anlageklasse -> keine Szenariozahlen
  (fail-closed), kein Default-Bucket.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import (  # noqa: E402
    PriceHistory, Product, RecommendationHolding, RecommendationPosition, RecommendationRun,
)
from models.snapshots import DepotSnapshot  # noqa: E402
from models.users import User  # noqa: E402
from services import depot_snapshot as ds  # noqa: E402
from services.backtest_stress import compute_stress_for_weights  # noqa: E402
from services.currency.fx_rates import FXRateSource  # noqa: E402
from services.portfolio_handoff import HoldingsValuationIncompleteError  # noqa: E402

NOW = "2026-10-26T10:00:00.000Z"
AS_OF = date(2026, 10, 26)
FX = FXRateSource({"CHF": 1.0, "USD": 0.88})
SCHEMA_FILE = next(BACKEND_ROOT.glob("*_schema_v4.0_FINAL.sql"))
REVISION = "c8e2f4a6b1d3"
DOWN_REVISION = "f6b1d4a8c2e7"

# (position_id, asset_class, currency, units_milli, price_rappen)
DEFAULT_HOLDINGS = (
    ("rp-eq", "Aktien", "CHF", 6_000_000, 10_000),     # 6000 Stk x CHF 100
    ("rp-us", "Aktien", "USD", 1_000_000, 10_000),     # 1000 Stk x USD 100
    ("rp-bd", "Obligationen", "CHF", 3_000_000, 10_000),
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'depot_snapshot.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


def _seed(s, holdings=DEFAULT_HOLDINGS, *, suffix="a", price_date=None, with_units=True):
    """Mandat + finaler Lauf + Produkte + echte Depotbestaende + Preise."""
    price_date = price_date or date.today().isoformat()
    advisor = User(
        id=f"adv-{suffix}", username=f"adv-{suffix}", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1, created_at=NOW, updated_at=NOW,
    )
    client = Client(
        id=f"cl-{suffix}", client_number=f"C-{suffix}", first_name="Test", last_name="Kunde",
        advisor_id=advisor.id, country_of_residence="CH", created_at=NOW, updated_at=NOW,
    )
    mandate = Mandate(
        id=f"m-{suffix}", client_id=client.id, mandate_number=f"M-{suffix}",
        mandate_type="Anlageberatung", base_currency="CHF",
        opened_at=NOW, created_at=NOW, updated_at=NOW,
    )
    policy = OptimizerPolicy(
        id=f"pol-{suffix}", policy_name=f"p-{suffix}", version=1, is_current=1,
        valid_from=NOW[:10], optimizer_engine="goal_based_v1", max_real_estate_bps=2000,
        max_alternatives_bps=1000, min_liquidity_bps=0, allow_other_assets_for_goals=1,
        created_by=advisor.id, created_at=NOW, updated_at=NOW,
    )
    ta = TargetAllocation(
        id=f"ta-{suffix}", mandate_id=mandate.id, policy_id=policy.id, version=1, is_current=1,
        target_equities_bps=6000, target_bonds_bps=4000, target_real_estate_bps=0,
        target_alternatives_bps=0, target_liquidity_bps=0,
        band_equities_min_bps=5000, band_equities_max_bps=7000,
        band_bonds_min_bps=3000, band_bonds_max_bps=5000,
        band_real_estate_min_bps=0, band_real_estate_max_bps=0,
        band_alternatives_min_bps=0, band_alternatives_max_bps=0,
        band_liquidity_min_bps=0, band_liquidity_max_bps=0,
        risky_fraction_bps=9000, risk_budget_bps_at_generation=9000,
        set_by=advisor.id, set_at=NOW, created_at=NOW, updated_at=NOW,
    )
    run = RecommendationRun(
        id=f"run-{suffix}", mandate_id=mandate.id, client_id=client.id,
        target_allocation_id=ta.id, policy_id=policy.id, run_type="full",
        result_status="Final", created_by=advisor.id, created_at=NOW, updated_at=NOW,
    )
    s.add_all([advisor, client, mandate, policy, ta, run])
    s.flush()
    for pid, asset_class, currency, units, price in holdings:
        product = Product(
            id=f"prod-{pid}", isin=f"CH{pid.upper().replace('-', ''):0>10}",
            product_name=f"Fonds {pid}", product_type="ETF", asset_class=asset_class,
            currency=currency, ter_bps=20, provider="Test", is_active=1,
            created_at=NOW, updated_at=NOW,
        )
        s.add(product)
        s.flush()
        s.add(RecommendationPosition(
            id=pid, run_id=run.id, product_id=product.id, target_weight_bps=0,
            target_amount_rappen=100_000_00,
            # Kopie im Lauf -- darf NIE als IST-Bestand gelesen werden.
            current_amount_rappen=999_999_999_00,
            reference_price_rappen=price, reference_price_date=price_date,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(RecommendationHolding(
            id=f"h-{pid}", run_id=run.id, recommendation_position_id=pid, product_id=product.id,
            as_of_date=price_date, units_milli=units if with_units else None,
            market_value_rappen=None if with_units else int(units * price / 1000),
            source="manual", created_at=NOW, updated_at=NOW,
        ))
        s.add(PriceHistory(
            id=f"px-{pid}", product_id=product.id, price_date=price_date, price_rappen=price,
            currency=currency, source="test", fetched_at=NOW,
        ))
    s.flush()
    return advisor, mandate


def _build(s, mandate, fx=FX, as_of=AS_OF):
    return ds.build_depot_snapshot(s, mandate, as_of=as_of, fx_source=fx)


def _add_holding_outside_run(s, *, suffix="a", pid="old-li", asset_class="Liquidität",
                             units=2_000_000, price=10_000, price_date=None):
    """Bestand eines Produkts, das KEINE Position des aktuellen Laufs ist
    (Holding haengt an einem frueheren, abgeloesten Lauf)."""
    price_date = price_date or date.today().isoformat()
    s.add(RecommendationRun(
        id=f"run-old-{suffix}", mandate_id=f"m-{suffix}", client_id=f"cl-{suffix}",
        policy_id=f"pol-{suffix}", run_type="full", result_status="Superseded",
        created_by=f"adv-{suffix}", created_at="2025-01-01T00:00:00.000Z",
        updated_at="2025-01-01T00:00:00.000Z",
    ))
    s.add(Product(
        id=f"prod-{pid}", isin="CH0000OLDLI1", product_name="Geldmarkt alt", product_type="ETF",
        asset_class=asset_class, currency="CHF", ter_bps=10, provider="Test", is_active=1,
        created_at=NOW, updated_at=NOW,
    ))
    s.flush()
    s.add(RecommendationPosition(
        id=pid, run_id=f"run-old-{suffix}", product_id=f"prod-{pid}", target_weight_bps=0,
        created_at=NOW, updated_at=NOW,
    ))
    s.add(RecommendationHolding(
        id=f"h-{pid}", run_id=f"run-old-{suffix}", recommendation_position_id=pid,
        product_id=f"prod-{pid}", as_of_date=price_date, units_milli=units, source="manual",
        created_at=NOW, updated_at=NOW,
    ))
    s.add(PriceHistory(
        id=f"px-{pid}", product_id=f"prod-{pid}", price_date=price_date, price_rappen=price,
        currency="CHF", source="test", fetched_at=NOW,
    ))
    s.flush()


# --- Bestandsquelle: gesamter, vollstaendig bewerteter Depotbestand -----------

def test_snapshot_values_units_times_price_with_fx_never_run_amounts(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        snapshot = _build(s, mandate)
    assert snapshot["source"] == "current_run_holdings"
    by_id = {p["position_id"]: p for p in snapshot["positions"]}
    assert set(by_id) == {"h-rp-eq", "h-rp-us", "h-rp-bd"}
    assert by_id["h-rp-eq"]["amount_base_rappen"] == 600_000_00
    # USD-Preis via FX auf CHF: 1000 x USD 100 x 0.88
    assert by_id["h-rp-us"]["amount_base_rappen"] == 88_000_00
    assert by_id["h-rp-us"]["product_currency"] == "USD" and by_id["h-rp-us"]["fx_converted"] is True
    assert all(p["valuation_basis"] == "actual_holding_units" for p in snapshot["positions"])
    assert snapshot["fx_evidence"]["target_currency"] == "CHF"
    assert [c for c, _ in snapshot["fx_evidence"]["effective_rates_x1e8"]] == ["CHF", "USD"]
    result = ds.compute_ist_stress(snapshot)
    total = 600_000 + 88_000 + 300_000
    assert result["weights_bps"] == {
        "equities": round(688_000 / total * 10000), "bonds": round(300_000 / total * 10000),
        "real_estate": 0, "alternatives": 0, "liquidity": 0,
    }


def _record_in_current_run(s, *, product_id, position_id, holding_units=None, run_id="run-a"):
    """Produkt im aktuellen Lauf erfassen: als Position, optional mit Holding
    (``holding_units=0`` = ausdruecklich als verkauft bestaetigt)."""
    s.add(RecommendationPosition(
        id=position_id, run_id=run_id, product_id=product_id, target_weight_bps=0,
        created_at=NOW, updated_at=NOW,
    ))
    s.flush()
    if holding_units is not None:
        s.add(RecommendationHolding(
            id=f"h-{position_id}", run_id=run_id, recommendation_position_id=position_id,
            product_id=product_id, as_of_date=date.today().isoformat(), units_milli=holding_units,
            source="manual", created_at=NOW, updated_at=NOW,
        ))
    s.flush()


def test_holdings_only_in_superseded_run_block_as_not_carried_over(session_factory):
    """CIO-Entscheid 2026-10-28 (a): kein stilles Verschwinden. Ein Bestand,
    der nur in einem abgeloesten Lauf steht, macht die IST-Bewertung
    unvollstaendig, bis er im aktuellen Lauf erfasst ist."""
    with session_factory() as s:
        _, mandate = _seed(s)
        _add_holding_outside_run(s)
        with pytest.raises(HoldingsValuationIncompleteError, match="CH0000OLDLI1") as exc:
            _build(s, mandate)
    assert exc.value.reason_code == "HOLDINGS_NOT_CARRIED_OVER"


def test_superseded_holding_confirmed_as_sold_is_not_part_of_ist(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        _add_holding_outside_run(s)
        _record_in_current_run(s, product_id="prod-old-li", position_id="rp-li-now", holding_units=0)
        snapshot = _build(s, mandate)
    assert {p["position_id"] for p in snapshot["positions"]} == {"h-rp-eq", "h-rp-us", "h-rp-bd"}
    assert snapshot["source"] == "current_run_holdings"


def test_newest_non_superseded_run_is_the_only_source(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        # Neuerer Entwurf: eigener (kleinerer) Aktienbestand; USD und Bonds
        # sind dort als Positionen erfasst, aber ohne Holding -> nichts wird
        # aus dem aelteren Final-Lauf zugemischt.
        s.add(RecommendationRun(
            id="run-new-a", mandate_id="m-a", client_id="cl-a", target_allocation_id="ta-a",
            policy_id="pol-a", run_type="full", result_status="Draft", created_by="adv-a",
            created_at="2026-10-27T10:00:00.000Z", updated_at="2026-10-27T10:00:00.000Z",
        ))
        s.flush()
        _record_in_current_run(s, product_id="prod-rp-us", position_id="rp-new-us", run_id="run-new-a")
        _record_in_current_run(s, product_id="prod-rp-bd", position_id="rp-new-bd", run_id="run-new-a")
        s.add(RecommendationPosition(
            id="rp-new-eq", run_id="run-new-a", product_id="prod-rp-eq", target_weight_bps=0,
            created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        s.add(RecommendationHolding(
            id="h-new-eq", run_id="run-new-a", recommendation_position_id="rp-new-eq",
            product_id="prod-rp-eq", as_of_date=date.today().isoformat(), units_milli=1_000_000,
            source="manual", created_at="2025-01-01T00:00:00.000Z",
            updated_at="2025-01-01T00:00:00.000Z",
        ))
        s.flush()
        snapshot = _build(s, mandate)
    assert [p["position_id"] for p in snapshot["positions"]] == ["h-new-eq"]
    assert snapshot["positions"][0]["amount_base_rappen"] == 100_000_00


def test_live_rebalancing_fallback_uses_current_run_and_reports_not_carried(session_factory):
    """CIO-Entscheid 2026-10-28 (b): der Live-Rebalancing-Fallback nutzt dieselbe
    Quelle wie der Depot-Snapshot; abgeloeste Laeufe nie."""
    from services.portfolio_engine_live_rebalancing import (
        _latest_holdings_by_product_for_mandate,
        holdings_not_carried_over,
    )

    with session_factory() as s:
        _, mandate = _seed(s)
        _add_holding_outside_run(s)
        fallback = _latest_holdings_by_product_for_mandate(s, mandate.id)
        missing = holdings_not_carried_over(s, mandate.id)
    assert set(fallback) == {"prod-rp-eq", "prod-rp-us", "prod-rp-bd"}
    assert [m["product_id"] for m in missing] == ["prod-old-li"]
    assert missing[0]["isin"] == "CH0000OLDLI1"


def test_handoff_blocks_when_holdings_were_not_carried_over(session_factory):
    from services.portfolio_handoff import snapshot_handoff

    with session_factory() as s:
        _, mandate = _seed(s)
        _add_holding_outside_run(s)
        run = s.get(RecommendationRun, "run-a")
        with pytest.raises(HoldingsValuationIncompleteError, match="CH0000OLDLI1") as exc:
            snapshot_handoff(s, mandate, run, "adv-a")
    assert exc.value.reason_code == "HOLDINGS_NOT_CARRIED_OVER"


def test_holding_edits_on_superseded_run_are_rejected(session_factory):
    from routers.review import delete_position_holding, upsert_position_holding
    from schemas.review import RecommendationHoldingUpsert

    with session_factory() as s:
        advisor, mandate = _seed(s)
        _add_holding_outside_run(s)
        s.commit()
        for call in (
            lambda: upsert_position_holding(
                mandate.id, "run-old-a", "old-li", RecommendationHoldingUpsert(units_milli=1),
                db=s, current_user=advisor,
            ),
            lambda: delete_position_holding(mandate.id, "run-old-a", "old-li", db=s, current_user=advisor),
        ):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 409
            assert exc.value.detail["reason_code"] == "HOLDINGS_RUN_SUPERSEDED"
        units = s.query(RecommendationHolding.units_milli).filter(RecommendationHolding.id == "h-old-li").scalar()
        assert units == 2_000_000


def test_holdings_as_of_is_the_oldest_holding_date_and_age_is_shown(session_factory):
    """Red-Team 2026-10-28 Befund 1: der Beleg nennt den aeltesten Bestandsstichtag."""
    with session_factory() as s:
        _, mandate = _seed(s)
        s.query(RecommendationHolding).filter(RecommendationHolding.id == "h-rp-eq").update(
            {"as_of_date": "2026-10-20"}
        )
        s.flush()
        snapshot = _build(s, mandate)
    assert snapshot["holdings_as_of"] == "2026-10-20"
    result = ds.compute_ist_stress(snapshot)
    assert result["holdings_as_of"] == "2026-10-20"
    assert result["holdings_age_days"] == (AS_OF - date(2026, 10, 20)).days


@pytest.mark.parametrize("value", [None, "", "   "])
def test_holding_without_as_of_date_blocks(session_factory, value):
    with session_factory() as s:
        _, mandate = _seed(s)
        s.query(RecommendationHolding).filter(RecommendationHolding.id == "h-rp-bd").update(
            {"as_of_date": value}
        )
        s.flush()
        with pytest.raises(HoldingsValuationIncompleteError, match="Stichtag"):
            _build(s, mandate)


def test_run_position_without_holding_is_irrelevant_for_ist(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        s.query(RecommendationHolding).filter(RecommendationHolding.id == "h-rp-bd").delete()
        s.flush()
        snapshot = _build(s, mandate)
    assert {p["position_id"] for p in snapshot["positions"]} == {"h-rp-eq", "h-rp-us"}
    assert ds.compute_ist_stress(snapshot)["weights_bps"]["equities"] == 10000


def test_missing_price_blocks(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        s.query(PriceHistory).filter(PriceHistory.id == "px-rp-bd").delete()
        s.flush()
        with pytest.raises(HoldingsValuationIncompleteError, match="Marktpreis"):
            _build(s, mandate)


def test_stale_price_of_superseded_run_does_not_matter(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        _add_holding_outside_run(s, price_date="2026-01-02")
        _record_in_current_run(s, product_id="prod-old-li", position_id="rp-li-now", holding_units=0)
        snapshot = _build(s, mandate)
    assert "h-old-li" not in {p["position_id"] for p in snapshot["positions"]}


def test_stale_price_in_current_run_blocks(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        s.query(PriceHistory).filter(PriceHistory.id == "px-rp-bd").update({"price_date": "2026-01-02"})
        s.flush()
        with pytest.raises(HoldingsValuationIncompleteError, match="veraltet"):
            _build(s, mandate)


def test_fx_failure_blocks(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        with pytest.raises(HoldingsValuationIncompleteError, match="Waehrungsumrechnung"):
            _build(s, mandate, fx=FXRateSource({"CHF": 1.0}))


def test_market_value_only_holdings_are_not_accepted(session_factory):
    """Ohne Stueckzahl ist der Wert eine CHF-Eingabe unabhaengig von der
    Produktwaehrung -- nicht belegt, also kein Snapshot."""
    with session_factory() as s:
        _, mandate = _seed(s, with_units=False)
        with pytest.raises(HoldingsValuationIncompleteError, match="Stueckzahl"):
            _build(s, mandate)


def test_no_holdings_means_no_snapshot(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s, holdings=())
        with pytest.raises(HoldingsValuationIncompleteError, match="Kein erfasster Depotbestand"):
            _build(s, mandate)


# --- Hash-Stabilitaet ---------------------------------------------------------

def test_snapshot_hash_is_stable_and_independent_of_row_order(tmp_path):
    hashes = []
    for idx, holdings in enumerate((DEFAULT_HOLDINGS, tuple(reversed(DEFAULT_HOLDINGS)))):
        engine = create_engine(f"sqlite:///{tmp_path / f'order{idx}.db'}")
        Base.metadata.create_all(bind=engine)
        with sessionmaker(bind=engine)() as s:
            _, mandate = _seed(s, holdings)
            first = _build(s, mandate)
            assert _build(s, mandate) == first  # Replay-stabil
            hashes.append(first["snapshot_hash"])
            assert [p["position_id"] for p in first["positions"]] == ["h-rp-bd", "h-rp-eq", "h-rp-us"]
            assert ds.verify_depot_snapshot(json.loads(json.dumps(first))) == first
        engine.dispose()
    assert hashes[0] == hashes[1]


def test_snapshot_hash_binds_units_as_of_and_fx_source(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        base = _build(s, mandate)
        other_day = _build(s, mandate, as_of=date(2026, 10, 27))
        other_fx = _build(s, mandate, fx=FXRateSource({"CHF": 1.0, "USD": 0.89}))
        s.query(RecommendationHolding).filter(RecommendationHolding.id == "h-rp-eq").update(
            {"units_milli": 6_000_001}
        )
        other_units = _build(s, mandate)
    digests = {base["snapshot_hash"], other_day["snapshot_hash"],
               other_fx["snapshot_hash"], other_units["snapshot_hash"]}
    assert len(digests) == 4


# --- Manipulationserkennung ---------------------------------------------------

@pytest.mark.parametrize("tamper", [
    lambda snap: snap["positions"][0].__setitem__("amount_base_rappen", 1),
    lambda snap: snap["positions"][0].__setitem__("bucket_weights_bps", {"liquidity": 10000}),
    lambda snap: snap.__setitem__("as_of", "2020-01-01"),
    lambda snap: snap.__setitem__("currency", "EUR"),
    lambda snap: snap["fx_evidence"].__setitem__("basis_id", "other"),
    lambda snap: snap.__setitem__("snapshot_hash", "0" * 64),
    lambda snap: snap.__setitem__("extra", 1),
])
def test_verify_rejects_manipulated_snapshot(session_factory, tamper):
    with session_factory() as s:
        _, mandate = _seed(s)
        snapshot = _build(s, mandate)
    forged = json.loads(json.dumps(snapshot))
    tamper(forged)
    with pytest.raises(ds.DepotSnapshotIntegrityError):
        ds.verify_depot_snapshot(forged)
    with pytest.raises(ds.DepotSnapshotIntegrityError):
        ds.compute_ist_stress(forged)


def _create(s, mandate, advisor):
    from routers.allocation import create_depot_snapshot

    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    return create_depot_snapshot(mandate.id, request, db=s, current_user=advisor)


def _replay(s, mandate, advisor, snapshot_id):
    from routers.allocation import get_depot_snapshot_stress_replays

    return get_depot_snapshot_stress_replays(mandate.id, snapshot_id, db=s, current_user=advisor)


def test_api_persists_idempotently_and_replays_identically(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s, holdings=(
            ("rp-eq", "Aktien", "CHF", 5_000_000, 10_000),
            ("rp-li", "Liquidität", "CHF", 5_000_000, 10_000),
        ))
        s.commit()
        first = _create(s, mandate, advisor)
        second = _create(s, mandate, advisor)
        assert first["created"] is True and second["created"] is False
        assert first["snapshot"]["snapshot_id"] == second["snapshot"]["snapshot_id"]
        assert s.query(DepotSnapshot).count() == 1
        replay = _replay(s, mandate, advisor, first["snapshot"]["snapshot_id"])
    assert replay == first["ist_stress"]
    assert replay["scope"] == "current_holdings_snapshot"
    assert "IST" in replay["scope_label"]
    assert replay["weights_bps"] == {
        "equities": 5000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 5000,
    }


def test_api_binds_the_snapshot_row_to_the_mandate_tenant(session_factory):
    """PG-002 (Red-Team 2026-10-28, Befund 6): depot_snapshots traegt den
    Mandanten direkt (RLS-Plan); der Snapshot-Hash bleibt mandantenfrei."""
    from models.tenant import Tenant

    with session_factory() as s:
        advisor, mandate = _seed(s)
        s.add(Tenant(id="t-1", display_name="t-1", slug="t-1", created_at=NOW, updated_at=NOW))
        s.flush()
        for row in (advisor, s.get(Client, mandate.client_id), mandate):
            row.tenant_id = "t-1"
        s.commit()
        created = _create(s, mandate, advisor)
        row = s.get(DepotSnapshot, created["snapshot"]["snapshot_id"])
        assert row.tenant_id == "t-1"
        assert "tenant_id" not in created["snapshot"]
        assert ds.verify_persisted_depot_snapshot(row, mandate_id=mandate.id)["snapshot_hash"] == row.snapshot_hash


def test_api_returns_409_and_persists_nothing_when_valuation_incomplete(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s, with_units=False)
        s.commit()
        with pytest.raises(HTTPException) as exc:
            _create(s, mandate, advisor)
        assert exc.value.status_code == 409
        assert s.query(DepotSnapshot).count() == 0


def test_api_replay_detects_tampered_row_with_409(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        s.commit()
        created = _create(s, mandate, advisor)
        snapshot = json.loads(json.dumps(created["snapshot"]))
        snapshot["positions"][0]["bucket_weights_bps"] = {"liquidity": 10000}
        # Zeile mit gefaelschtem Inhalt, aber der alten Hash-Spalte
        # (UPDATE ist per Trigger gesperrt).
        s.add(DepotSnapshot(
            id="dps-forged", schema_version="DepotSnapshotV1", mandate_id=mandate.id,
            client_id=mandate.client_id, as_of_date=snapshot["as_of"], currency="CHF",
            source=snapshot["source"], snapshot_json=json.dumps(snapshot),
            snapshot_hash=snapshot["snapshot_hash"], created_by=advisor.id, created_at=NOW,
        ))
        s.commit()
        with pytest.raises(HTTPException) as exc:
            _replay(s, mandate, advisor, "dps-forged")
        assert exc.value.status_code == 409
        assert "Hash" in exc.value.detail
        with pytest.raises(HTTPException) as missing:
            _replay(s, mandate, advisor, "dps-unknown")
        assert missing.value.status_code == 404


def test_persisted_snapshot_rows_are_immutable(session_factory):
    with session_factory() as s:
        advisor, mandate = _seed(s)
        s.commit()
        snapshot_id = _create(s, mandate, advisor)["snapshot"]["snapshot_id"]
        for statement in (
            "UPDATE depot_snapshots SET snapshot_hash = 'x' WHERE id = :id",
            "DELETE FROM depot_snapshots WHERE id = :id",
        ):
            with pytest.raises(Exception, match="immutable"):
                s.execute(text(statement), {"id": snapshot_id})
            s.rollback()


# --- IST-Stress: Szenarien, Beschriftung, fail-closed -------------------------

def test_ist_stress_uses_existing_scenarios_on_ist_weights(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s)
        snapshot = _build(s, mandate)
    result = ds.compute_ist_stress(snapshot)
    assert result["status"] == "ok"
    assert result["scenarios"] == compute_stress_for_weights(result["weights_bps"])
    assert [sc["id"] for sc in result["scenarios"]] == [
        sc["id"] for sc in compute_stress_for_weights({"equities": 10000})
    ]
    assert result["snapshot_hash"] == snapshot["snapshot_hash"]
    assert len(result["stress_catalog_hash"]) == 64 and len(result["result_hash"]) == 64


def test_product_with_unknown_asset_class_is_fail_closed(session_factory):
    with session_factory() as s:
        _, mandate = _seed(s, holdings=DEFAULT_HOLDINGS + (("rp-art", "Kunst", "CHF", 1_000_000, 10_000),))
        snapshot = _build(s, mandate)
    art = next(p for p in snapshot["positions"] if p["position_id"] == "h-rp-art")
    assert art["bucket_weights_bps"] is None  # depot_check wuerde "alternatives" annehmen
    result = ds.compute_ist_stress(snapshot)
    assert result["status"] == "unclassified_positions"
    assert result["scenarios"] == [] and result["weights_bps"] == {}
    assert result["unclassified_positions"] == [{"position_id": "h-rp-art", "reason": "unknown_asset_class"}]
    assert "warning" in result


# --- Schema: ORM, Bootstrap + Runtime-Patch, Alembic-Kette --------------------

def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _tables(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_bootstrap_plus_runtime_patch_creates_immutable_table(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert "depot_snapshots" in _tables(db_path)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    with test_engine.connect() as conn:
        triggers = {row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='depot_snapshots'"
        ))}
        columns = {c["name"] for c in inspect(conn).get_columns("depot_snapshots")}
    test_engine.dispose()
    assert triggers == {"trg_depot_snapshots_no_update", "trg_depot_snapshots_no_delete"}
    assert columns == {c.name for c in DepotSnapshot.__table__.columns}


def test_alembic_chain_contains_revision_and_round_trips(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION
    command.upgrade(cfg, DOWN_REVISION)
    assert "depot_snapshots" not in _tables(db_path)
    command.upgrade(cfg, REVISION)
    assert "depot_snapshots" in _tables(db_path)
    command.downgrade(cfg, DOWN_REVISION)
    assert "depot_snapshots" not in _tables(db_path)
