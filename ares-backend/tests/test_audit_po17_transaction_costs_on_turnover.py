"""PO-17 (Audit 2026-11, SAA -> Portfolio): Transaktionskosten auf den Umschlag.

Vorher rechnete der Ex-ante-Kostenausweis (FIDLEG Art. 8) die pauschalen
Transaktionskosten auf das GANZE empfohlene Produktvolumen -- auch wenn der
Kunde die Positionen bereits haelt und nur ein Teil gehandelt wird. Bei einem
bestehenden Depot war der Ausweis damit zu hoch.

Jetzt: ist fuer den Lauf ein Bestand (RecommendationHolding) erfasst, ist die
Basis das gehandelte Volumen sum(|Ziel - Bestand|), klar beschriftet. Ohne
Bestand bleibt es die Erstumsetzung des ganzen Volumens (unveraendert).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.review import Product, RecommendationHolding, RecommendationPosition, RecommendationRun
from services.cost_disclosure import build_cost_disclosure_for_run, calculate_cost_disclosure

NOW = "2026-11-02T00:00:00"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'po17.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _item(result, key="initial_transaction_costs"):
    return next((i for i in result["cost_items"] if i["key"] == key), None)


def test_without_holdings_the_whole_volume_is_the_basis():
    """Positivkontrolle: Erstumsetzung unveraendert (15 bps auf CHF 100'000)."""
    result = calculate_cost_disclosure(
        advisory_wealth_rappen=10_000_000,
        positions=[{"amount_rappen": 6_000_000, "weight_bps": 6000, "ter_bps": 10},
                   {"amount_rappen": 4_000_000, "weight_bps": 4000, "ter_bps": 20}],
        fee_model=None,
    )
    item = _item(result)
    assert item["basis_rappen"] == 10_000_000
    assert item["amount_rappen"] == 15_000
    assert item["label"] == "Transaktionskosten Erstumsetzung"


def test_with_holdings_only_the_turnover_is_charged():
    """Rot vor dem Fix: Basis war 10'000'000 statt des Umschlags 2'000'000."""
    result = calculate_cost_disclosure(
        advisory_wealth_rappen=10_000_000,
        positions=[
            # haelt 5'000'000, Ziel 6'000'000 -> Kauf 1'000'000
            {"amount_rappen": 6_000_000, "weight_bps": 6000, "ter_bps": 10,
             "holding_present": True, "holding_value_rappen": 5_000_000},
            # haelt 5'000'000, Ziel 4'000'000 -> Verkauf 1'000'000
            {"amount_rappen": 4_000_000, "weight_bps": 4000, "ter_bps": 20,
             "holding_present": True, "holding_value_rappen": 5_000_000},
        ],
        fee_model=None,
    )
    item = _item(result)
    assert item["basis_rappen"] == 2_000_000
    assert item["amount_rappen"] == 3_000
    assert "Gehandeltes Volumen" in item["basis_label"]
    assert any("gehandelte" in w for w in result["warnings"])
    # Produktkosten (TER) bleiben auf dem ganzen Volumen.
    assert _item(result, "product_ter")["basis_rappen"] == 10_000_000


def test_holding_without_market_value_counts_as_full_purchase():
    result = calculate_cost_disclosure(
        advisory_wealth_rappen=10_000_000,
        positions=[{"amount_rappen": 10_000_000, "weight_bps": 10000, "ter_bps": 10,
                    "holding_present": True, "holding_value_rappen": None}],
        fee_model=None,
    )
    assert _item(result)["basis_rappen"] == 10_000_000


def test_fully_held_portfolio_has_no_transaction_item():
    result = calculate_cost_disclosure(
        advisory_wealth_rappen=10_000_000,
        positions=[{"amount_rappen": 10_000_000, "weight_bps": 10000, "ter_bps": 10,
                    "holding_present": True, "holding_value_rappen": 10_000_000}],
        fee_model=None,
    )
    assert _item(result) is None
    assert any("kein Umschlag" in w for w in result["warnings"])


def test_build_for_run_reads_the_runs_holdings(db_session):
    """Durchstich ueber die echte Datenquelle (RecommendationHolding des Laufs)."""
    s = db_session
    mandate = SimpleNamespace(id="po17-m", tenant_id=None, base_currency="CHF", jurisdiction="CH")
    run = RecommendationRun(
        id="po17-run", mandate_id=mandate.id, client_id="c", policy_id="po17-pol", run_type="Optimizer",
        result_status="Draft", fee_assumptions_json='{"transaction_cost_bps": 15}',
        created_by="u", created_at=NOW, updated_at=NOW,
    )
    products = [
        Product(id=f"po17-p{i}", product_name=f"P{i}", provider="x", product_type="ETF",
                asset_class="Aktien", sub_asset_class="Aktien Schweiz", currency="CHF",
                ter_bps=10, is_active=1, created_at=NOW, updated_at=NOW)
        for i in (1, 2)
    ]
    positions = [
        RecommendationPosition(id="po17-pos1", run_id=run.id, product_id="po17-p1",
                               target_weight_bps=6000, target_amount_rappen=6_000_000,
                               created_at=NOW, updated_at=NOW),
        RecommendationPosition(id="po17-pos2", run_id=run.id, product_id="po17-p2",
                               target_weight_bps=4000, target_amount_rappen=4_000_000,
                               created_at=NOW, updated_at=NOW),
    ]
    holdings = [
        RecommendationHolding(id="po17-h1", run_id=run.id, recommendation_position_id="po17-pos1",
                              product_id="po17-p1", market_value_rappen=5_000_000,
                              created_at=NOW, updated_at=NOW),
        # aeltere, ueberholte Holding derselben Position -- darf nicht zaehlen
        RecommendationHolding(id="po17-h1-old", run_id=run.id, recommendation_position_id="po17-pos1",
                              product_id="po17-p1", market_value_rappen=1,
                              created_at=NOW, updated_at="2026-01-01T00:00:00"),
        RecommendationHolding(id="po17-h2", run_id=run.id, recommendation_position_id="po17-pos2",
                              product_id="po17-p2", market_value_rappen=5_000_000,
                              created_at=NOW, updated_at=NOW),
    ]
    s.add(run)
    s.add_all(products)
    s.flush()
    s.add_all(positions)
    s.flush()
    s.add_all(holdings)
    s.flush()
    result = build_cost_disclosure_for_run(s, mandate, run)
    item = _item(result)
    assert item["basis_rappen"] == 2_000_000, result
    assert item["amount_rappen"] == 3_000
