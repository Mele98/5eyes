"""Pruefrunde #856: SELECT-Budget des Kostenausweises je Lauf festhalten.

PO-17/N-856-3/N-856-9 lesen Bestaende des Laufs und nicht uebernommene
Bestaende frueherer Laeufe in EINER Abfrage mit den Positionen. Gemessen auf
612b510f: 5 SELECTs fuer ``build_cost_disclosure_for_run`` in diesem Szenario
(Lauf ohne eigenes Gebuehrenmodell -> Policy-Abfrage, Positionen+Holdings
ueber alle Laeufe, Produkt-Konditionen, Soll-Allokation,
Interessenkonflikte). Jede zusaetzliche Abfrage (z. B. eine
zweite Holding-Abfrage wie in der N-856-3-Fassung) macht diesen Test rot und
muss bewusst begruendet werden; das Report-Gesamtbudget pinnt
tests/test_aggregator_n1_baseline.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import Base
from models.review import Product, RecommendationHolding, RecommendationPosition, RecommendationRun
from services.cost_disclosure import build_cost_disclosure_for_run

NOW = "2026-11-02T00:00:00"
COST_DISCLOSURE_SELECT_BUDGET = 5


@pytest.fixture()
def engine_and_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'qb.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield engine, session
    finally:
        session.close()
        engine.dispose()


def _seed(s):
    mandate = SimpleNamespace(id="qb-m", tenant_id=None, base_currency="CHF", jurisdiction="CH")
    old_run = RecommendationRun(
        id="qb-old", mandate_id=mandate.id, client_id="c", policy_id="p", run_type="Optimizer",
        result_status="Final", created_by="u", created_at="2026-10-01T00:00:00", updated_at=NOW,
    )
    run = RecommendationRun(
        id="qb-run", mandate_id=mandate.id, client_id="c", policy_id="p", run_type="Optimizer",
        result_status="Draft",  # kein Run-Gebuehrenmodell -> Policy-Abfrage (5. SELECT)
        created_by="u", created_at=NOW, updated_at=NOW,
    )
    products = [
        Product(id=f"qb-p{i}", product_name=f"P{i}", provider="x", product_type="ETF",
                asset_class="Aktien", sub_asset_class="Aktien Schweiz", currency="CHF",
                ter_bps=10, is_active=1, created_at=NOW, updated_at=NOW)
        for i in (1, 2, 3)
    ]
    s.add_all([old_run, run, *products])
    s.flush()
    s.add_all([
        RecommendationPosition(id="qb-old-pos3", run_id=old_run.id, product_id="qb-p3",
                               target_weight_bps=10000, target_amount_rappen=2_000_000,
                               created_at=NOW, updated_at=NOW),
        RecommendationPosition(id="qb-pos1", run_id=run.id, product_id="qb-p1",
                               target_weight_bps=6000, target_amount_rappen=6_000_000,
                               created_at=NOW, updated_at=NOW),
        RecommendationPosition(id="qb-pos2", run_id=run.id, product_id="qb-p2",
                               target_weight_bps=4000, target_amount_rappen=4_000_000,
                               created_at=NOW, updated_at=NOW),
    ])
    s.flush()
    s.add_all([
        RecommendationHolding(id="qb-h1", run_id=run.id, recommendation_position_id="qb-pos1",
                              product_id="qb-p1", market_value_rappen=5_000_000,
                              created_at=NOW, updated_at=NOW),
        RecommendationHolding(id="qb-h-old", run_id=old_run.id, recommendation_position_id="qb-old-pos3",
                              product_id="qb-p3", market_value_rappen=2_000_000,
                              created_at=NOW, updated_at=NOW),
    ])
    s.flush()
    return mandate, run


def test_cost_disclosure_select_count_is_pinned(engine_and_session):
    engine, s = engine_and_session
    mandate, run = _seed(s)
    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = build_cost_disclosure_for_run(s, mandate, run)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    # Durchstich: Umschlag = Kauf 1'000'000 + Kauf 4'000'000 + Verkauf alt 2'000'000
    item = next(i for i in result["cost_items"] if i["key"] == "initial_transaction_costs")
    assert item["basis_rappen"] == 7_000_000
    assert len(statements) == COST_DISCLOSURE_SELECT_BUDGET, "\n---\n".join(statements)
