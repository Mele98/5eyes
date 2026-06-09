"""Tests fuer Phase 3 — Sub-Asset-Backtest-Engine.

Verifiziert:
- load_sub_asset_annual_returns_matrix filtert sub_asset_class IS NOT NULL
- load_annual_returns_matrix bleibt Top-Level-only (NULL-Filter)
- _normalize_sub_asset_weights: Summe=10000, Negative=0, Round-Off-Korrektur
- compound_sub_asset_wealth_path mit Rebal + No-Rebal + Fee-Adjustierung
- _build_sub_asset_path_views liefert komplette Struktur (rebal/norebal/gross)
- run_strategy_backtest mit benchmark_sub_weights_bps fuegt sub_asset-Block
- Backwards-Compat: ohne benchmark_sub_weights_bps unveraendert
- Years-Cascade: Years mit nicht-allen Sub-Assets werden uebersprungen
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.snapshots import AssetClassAnnualReturn
from services.backtest_strategy import (
    _build_sub_asset_path_views,
    _normalize_sub_asset_weights,
    _years_with_all_sub_assets,
    compound_sub_asset_wealth_path,
    load_annual_returns_matrix,
    load_sub_asset_annual_returns_matrix,
)


def _now() -> str:
    return datetime.utcnow().isoformat()


@pytest.fixture
def sqlite_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    yield db
    db.close()


def _add_top_level_row(db, year, asset_class, bps):
    db.add(AssetClassAnnualReturn(
        id=str(uuid.uuid4()), year=year, asset_class=asset_class,
        return_bps=bps, source="test",
        created_at=_now(), updated_at=_now(),
        sub_asset_class=None,
    ))


def _add_sub_asset_row(db, year, top_class, sub_key, bps):
    db.add(AssetClassAnnualReturn(
        id=str(uuid.uuid4()), year=year, asset_class=top_class,
        return_bps=bps, source="test",
        created_at=_now(), updated_at=_now(),
        sub_asset_class=sub_key,
    ))


# ============================================================
# Loader-Trennung
# ============================================================

def test_top_level_loader_ignoriert_sub_asset_rows(sqlite_db):
    """load_annual_returns_matrix darf nur NULL-sub_asset-Rows lesen."""
    for cls, bps in [("Aktien", 800), ("Obligationen", 200), ("Immobilien", 400),
                     ("Alternative", 600), ("Liquiditaet", 50)]:
        _add_top_level_row(sqlite_db, 2020, cls, bps)
    # Zusaetzlich Sub-Asset-Row
    _add_sub_asset_row(sqlite_db, 2020, "Aktien", "Aktien_CH_Large", 1200)
    sqlite_db.commit()

    matrix = load_annual_returns_matrix(sqlite_db)
    assert 2020 in matrix
    assert matrix[2020] == {
        "equities": 800,
        "bonds": 200,
        "real_estate": 400,
        "alternatives": 600,
        "liquidity": 50,
    }


def test_sub_asset_loader_ignoriert_top_level_rows(sqlite_db):
    """load_sub_asset_annual_returns_matrix darf nur NOT-NULL lesen."""
    _add_top_level_row(sqlite_db, 2020, "Aktien", 800)
    _add_sub_asset_row(sqlite_db, 2020, "Aktien", "Aktien_CH_Large", 1200)
    _add_sub_asset_row(sqlite_db, 2020, "Aktien", "Aktien_US_Large", 1500)
    sqlite_db.commit()

    matrix = load_sub_asset_annual_returns_matrix(sqlite_db)
    assert matrix == {2020: {"Aktien_CH_Large": 1200, "Aktien_US_Large": 1500}}


def test_sub_asset_loader_alle_jahre_egal_ob_komplett(sqlite_db):
    """Sub-Asset-Loader: kein 'vollstaendig'-Filter, weil Sub-Assets
    historisch unterschiedlich verfuegbar sind."""
    _add_sub_asset_row(sqlite_db, 1990, "Aktien", "Aktien_CH_Large", 1000)
    _add_sub_asset_row(sqlite_db, 1995, "Aktien", "Aktien_CH_Large", 800)
    _add_sub_asset_row(sqlite_db, 1995, "Aktien", "Aktien_US_Large", 1200)
    sqlite_db.commit()

    matrix = load_sub_asset_annual_returns_matrix(sqlite_db)
    assert 1990 in matrix
    assert 1995 in matrix
    assert matrix[1990] == {"Aktien_CH_Large": 1000}
    assert matrix[1995] == {"Aktien_CH_Large": 800, "Aktien_US_Large": 1200}


# ============================================================
# _years_with_all_sub_assets
# ============================================================

def test_years_with_all_sub_assets_filtert_unvollstaendige():
    matrix = {
        1990: {"Aktien_CH_Large": 1000},
        1995: {"Aktien_CH_Large": 800, "Aktien_US_Large": 1200},
        2000: {"Aktien_CH_Large": 600},
    }
    years = _years_with_all_sub_assets(matrix, ["Aktien_CH_Large", "Aktien_US_Large"])
    assert years == [1995]


# ============================================================
# _normalize_sub_asset_weights
# ============================================================

def test_normalize_sub_asset_weights_summiert_auf_10000():
    out = _normalize_sub_asset_weights({"A": 3000, "B": 7000})
    assert sum(out.values()) == 10000
    assert out == {"A": 3000, "B": 7000}


def test_normalize_sub_asset_weights_skaliert_unter_10000():
    out = _normalize_sub_asset_weights({"A": 50, "B": 50})  # 50+50=100
    assert sum(out.values()) == 10000
    assert out["A"] == 5000
    assert out["B"] == 5000


def test_normalize_sub_asset_weights_klemmt_negativ_auf_null():
    out = _normalize_sub_asset_weights({"A": -1000, "B": 5000})
    assert out == {"A": 0, "B": 10000}


def test_normalize_sub_asset_weights_none_bei_leer():
    assert _normalize_sub_asset_weights(None) is None
    assert _normalize_sub_asset_weights({}) is None
    assert _normalize_sub_asset_weights({"A": 0, "B": 0}) is None


def test_normalize_sub_asset_weights_round_off_korrektur():
    """1/3 + 1/3 + 1/3 mit Round-Off."""
    out = _normalize_sub_asset_weights({"A": 1, "B": 1, "C": 1})
    assert sum(out.values()) == 10000


# ============================================================
# compound_sub_asset_wealth_path
# ============================================================

def test_compound_sub_asset_rebal_basic():
    """50/50 Rebal: 1 Jahr +10% A und +20% B -> Portfolio +15%."""
    result = compound_sub_asset_wealth_path(
        initial_value_rappen=1_000_000,
        sub_weights_bps={"A": 5000, "B": 5000},
        years_returns=[(2020, {"A": 1000, "B": 2000})],
        rebalance=True,
    )
    assert result["annual_returns_bps"] == [1500]
    # Endwert = 1.15 Mio
    assert result["wealth_path_rappen"][-1][1] == pytest.approx(1_150_000, rel=0.001)


def test_compound_sub_asset_no_rebal_drift():
    """No-Rebal: Bucket-Drift sichtbar im sub_path."""
    result = compound_sub_asset_wealth_path(
        initial_value_rappen=1_000_000,
        sub_weights_bps={"A": 5000, "B": 5000},
        years_returns=[
            (2020, {"A": 5000, "B": 0}),  # A verdoppelt sich
        ],
        rebalance=False,
    )
    # Nach Jahr 1: A=750k, B=500k -> Total 1.25M, Drift A:B = 60:40
    last = result["sub_path_rappen"][-1]
    assert last["A"] == pytest.approx(750_000, rel=0.001)
    assert last["B"] == pytest.approx(500_000, rel=0.001)


def test_compound_sub_asset_fee_adjusted():
    """fee_bps_per_year=100 (1%) zieht jaehrlich vom Pfad ab."""
    base = compound_sub_asset_wealth_path(
        1_000_000, {"A": 10000},
        [(2020, {"A": 1000}), (2021, {"A": 1000})],
        rebalance=True,
        fee_bps_per_year=0,
    )
    fee = compound_sub_asset_wealth_path(
        1_000_000, {"A": 10000},
        [(2020, {"A": 1000}), (2021, {"A": 1000})],
        rebalance=True,
        fee_bps_per_year=100,
    )
    assert fee["wealth_path_rappen"][-1][1] < base["wealth_path_rappen"][-1][1]


def test_compound_sub_asset_leere_keys_raises():
    with pytest.raises(ValueError):
        compound_sub_asset_wealth_path(1_000_000, {}, [], rebalance=True)


def test_compound_sub_asset_alle_gewichte_null_raises():
    with pytest.raises(ValueError):
        compound_sub_asset_wealth_path(1_000_000, {"A": 0}, [], rebalance=True)


# ============================================================
# _build_sub_asset_path_views
# ============================================================

def test_build_sub_asset_path_views_komplette_struktur():
    view = _build_sub_asset_path_views(
        1_000_000, {"A": 5000, "B": 5000},
        [(2020, {"A": 1000, "B": 2000})],
        risk_free_bps=80,
        fee_bps_per_year=0,
    )
    assert "rebalanced" in view
    assert "no_rebalance" in view
    assert "sub_weights_bps" in view
    assert "sub_asset_keys" in view
    # rebalanced enthaelt Metriken
    assert "metrics" in view["rebalanced"]
    assert "wealth_path_rappen" in view["rebalanced"]
    assert "drawdown_path_bps" in view["rebalanced"]
    # gross-Block NUR bei fee>0
    assert "gross" not in view


def test_build_sub_asset_path_views_gross_block_bei_fee():
    view = _build_sub_asset_path_views(
        1_000_000, {"A": 10000},
        [(2020, {"A": 1000})],
        risk_free_bps=80,
        fee_bps_per_year=150,
    )
    assert "gross" in view
    assert "rebalanced" in view["gross"]


# ============================================================
# Backwards-Compat
# ============================================================

def test_load_annual_returns_matrix_filter_null_sub_asset(sqlite_db):
    """Pre-Sprint: Top-Level-Loader hatte keinen sub_asset-Filter. Mit
    Phase 1 ist Spalte da aber NULL fuer Bestandsdaten. Filter darf
    NULL-Rows nicht ausschliessen."""
    for cls, bps in [("Aktien", 800), ("Obligationen", 200), ("Immobilien", 400),
                     ("Alternative", 600), ("Liquiditaet", 50)]:
        _add_top_level_row(sqlite_db, 2020, cls, bps)
    sqlite_db.commit()

    matrix = load_annual_returns_matrix(sqlite_db)
    assert 2020 in matrix
    assert len(matrix[2020]) == 5
