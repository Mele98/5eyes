"""Sprint U-11 (Roadmap-Punkt 11): Tests fuer services.monte_carlo_paths.

Strategie
---------
- Engine-Schicht (`_compute_paths_core`) wird isoliert mit fertigen Inputs
  getestet (keine DB, kein Mandate-Setup): pruefen wir Mathematik +
  Schema + Determinismus.
- DB-Schicht (`compute_quantile_paths`) wird mit echtem Mandat-Seed
  getestet: pruefen wir Fallback-Pfade (kein TA / keine CMA / kein Wealth)
  und den Happy-Path.
- Performance-Sanity: 1000 Pfade, horizon=15 muss in << 1s laufen.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: F401  (Sprint U-36)
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401  (Bug-#13a)
import models.tenant  # noqa: F401  (Sprint T1)
configure_mappers()
from models.allocation import (
    CapitalMarketAssumption,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.monte_carlo_paths import (
    DEFAULT_N_PATHS,
    DEFAULT_SEED,
    _compute_paths_core,
    compute_quantile_paths,
)


_NOW = "2026-05-31T08:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mc.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_advisor(s):
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(advisor)
    s.flush()
    return advisor


def _seed_client_with_mandate(s, advisor):
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Hans",
        last_name="Muster",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(client)
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(mandate)
    s.flush()
    return client, mandate


def _seed_ta(s, mandate, advisor, policy=None):
    if policy is None:
        policy = OptimizerPolicy(
            id=str(uuid.uuid4()),
            policy_name="P", version=1, is_current=1,
            valid_from=_NOW, created_by=advisor.id,
            created_at=_NOW, updated_at=_NOW,
        )
        s.add(policy)
    ta = TargetAllocation(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        version=1, is_current=1,
        policy_id=policy.id,
        target_equities_bps=4000, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=1000,
        target_liquidity_bps=500,
        band_equities_min_bps=3500, band_equities_max_bps=4500,
        band_bonds_min_bps=3000, band_bonds_max_bps=4000,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=500, band_alternatives_max_bps=1500,
        band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
        risky_fraction_bps=7500,
        set_by=advisor.id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(ta)
    return ta


def _seed_cma(s, advisor):
    cma = CapitalMarketAssumption(
        id=str(uuid.uuid4()),
        assumption_set_name="Standard",
        version=1, is_current=1,
        valid_from=_NOW,
        bonds_chf_ig_return_bps=220, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=430,
        bonds_hy_return_bps=420, bonds_hy_vol_bps=900,
        equity_ch_return_bps=550, equity_ch_vol_bps=1400,
        equity_intl_return_bps=580, equity_intl_vol_bps=1600,
        equity_em_return_bps=700, equity_em_vol_bps=2000,
        real_estate_ch_return_bps=350, real_estate_ch_vol_bps=1100,
        alternatives_gold_return_bps=520, alternatives_gold_vol_bps=1500,
        liquidity_return_bps=80, liquidity_vol_bps=50,
        created_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(cma)
    return cma


def _seed_wealth_and_cashflows(s, client, beratungsvermoegen_rappen=50_000_000):
    s.add(WealthPosition(
        id=str(uuid.uuid4()),
        client_id=client.id,
        position_type="Wertschriftendepot",
        label="Depot",
        current_value_rappen=beratungsvermoegen_rappen,
        currency="CHF",
        assignment="Beratungsvermögen",
        is_active=1,
        created_at=_NOW, updated_at=_NOW,
    ))
    # Net positive cashflow: Income 8'000 CHF/Mo, Expense 4'000 CHF/Mo
    s.add(Cashflow(
        id=str(uuid.uuid4()),
        client_id=client.id,
        cashflow_type="Income",
        label="Lohn",
        amount_rappen=800_000,
        frequency="monatlich",
        is_active=1,
        created_at=_NOW, updated_at=_NOW,
    ))
    s.add(Cashflow(
        id=str(uuid.uuid4()),
        client_id=client.id,
        cashflow_type="Expense",
        label="Lebenshaltung",
        amount_rappen=400_000,
        frequency="monatlich",
        is_active=1,
        created_at=_NOW, updated_at=_NOW,
    ))


# ---------------------------------------------------------------------------
# Engine-Schicht (`_compute_paths_core`)
# ---------------------------------------------------------------------------

def test_core_returns_stable_schema(session_factory):
    """_compute_paths_core liefert alle erwarteten Top-Level-Keys."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        result = _compute_paths_core(
            initial_wealth_rappen=50_000_000,
            horizon_years=10,
            weights=weights,
            cma=cma,
            cashflow_series=[0] * 10,
            n_paths=200,
            seed=42,
        )
    expected_keys = {
        "data_pending", "p5", "p50", "p75", "time_axis",
        "n_paths", "seed", "horizon_years", "initial_wealth_rappen", "note",
    }
    assert set(result.keys()) == expected_keys
    assert result["data_pending"] is False
    assert len(result["p5"]) == 11  # horizon + 1
    assert len(result["p50"]) == 11
    assert len(result["p75"]) == 11
    assert len(result["time_axis"]) == 11


def test_core_quantiles_are_monotonic(session_factory):
    """p5 <= p50 <= p75 muss IMMER gelten (Mathematik der Percentile)."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        result = _compute_paths_core(
            initial_wealth_rappen=10_000_000,
            horizon_years=20,
            weights=weights,
            cma=cma,
            cashflow_series=[0] * 20,
            n_paths=500,
            seed=42,
        )
    for t in range(len(result["p5"])):
        assert result["p5"][t] <= result["p50"][t], f"p5 > p50 at t={t}"
        assert result["p50"][t] <= result["p75"][t], f"p50 > p75 at t={t}"


def test_core_is_deterministic_with_same_seed(session_factory):
    """Gleicher Seed + gleiche Inputs -> exakt identische Pfade.

    KRITISCH fuer Compliance/Audit: ein Berater muss denselben Bericht
    morgen wieder erzeugen koennen ohne Zahlen-Drift.
    """
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        a = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=10,
            weights=weights, cma=cma, cashflow_series=[0] * 10,
            n_paths=500, seed=12345,
        )
        b = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=10,
            weights=weights, cma=cma, cashflow_series=[0] * 10,
            n_paths=500, seed=12345,
        )
    assert a["p5"] == b["p5"]
    assert a["p50"] == b["p50"]
    assert a["p75"] == b["p75"]


def test_core_different_seed_produces_different_paths(session_factory):
    """Anderer Seed -> andere Pfade (Negativ-Sicherung der Determinismus-
    Eigenschaft).
    """
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        a = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=10,
            weights=weights, cma=cma, cashflow_series=[0] * 10,
            n_paths=500, seed=11,
        )
        b = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=10,
            weights=weights, cma=cma, cashflow_series=[0] * 10,
            n_paths=500, seed=999,
        )
    # Wenigstens an einem t-Schritt muss Differenz existieren
    assert a["p50"] != b["p50"]


def test_core_sub_allocations_shift_the_projection(session_factory):
    """REP-001 (Codex-Audit 2026-08-25): scenario_inputs_from_cma() gewichtet
    Bucket-Returns/-Vols nach den REALEN Sub-Gewichten, wenn sub_allocations
    uebergeben wird -- _compute_paths_core() gab dieses Argument bisher nie
    weiter. Ein 100% EM-Aktien-Sub-Allokation (equity_em_return_bps=700) muss
    andere Pfade liefern als der generische Bucket-Default (Durchschnitt aus
    equity_ch=550/equity_intl=580/equity_em=700)."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])

        without_sub_allocations = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=15,
            weights=weights, cma=cma, cashflow_series=[0] * 15,
            n_paths=1000, seed=42,
        )
        with_em_tilt = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=15,
            weights=weights, cma=cma, cashflow_series=[0] * 15,
            n_paths=1000, seed=42,
            sub_allocations=[
                {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 10000},
            ],
        )
    assert without_sub_allocations["p50"] != with_em_tilt["p50"], (
        "sub_allocations aendert das Ergebnis nicht -- Verdrahtung fehlt."
    )


def test_core_falls_back_to_bucket_defaults_when_cma_lacks_sub_asset_class(session_factory):
    """Regressions-Lock: eine sub_allocations_json mit einer Sub-Asset-Class,
    fuer die die aktuelle CMA keine Kennzahlen hat (z.B. waehrend eine
    Jurisdiktion CMA-Abdeckung sukzessive aufbaut), darf NICHT den ganzen
    Advisory-Report zum Absturz bringen -- Fail-soft-Rueckfall auf die
    historischen Bucket-Defaults."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        result = _compute_paths_core(
            initial_wealth_rappen=10_000_000, horizon_years=10,
            weights=weights, cma=cma, cashflow_series=[0] * 10,
            n_paths=200, seed=42,
            sub_allocations=[
                {"asset_class": "Aktien", "sub_asset_class": "Aktien Deutschland", "target_weight_bps": 10000},
            ],
        )
    assert result["data_pending"] is False


def test_core_initial_value_matches_initial_wealth(session_factory):
    """wealth_paths[:, 0] == initial fuer ALLE Pfade -> alle Quantile bei
    t=0 sind initial_wealth."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        result = _compute_paths_core(
            initial_wealth_rappen=42_000_000,
            horizon_years=15,
            weights=weights,
            cma=cma,
            cashflow_series=[0] * 15,
            n_paths=300,
            seed=1,
        )
    assert result["p5"][0] == 42_000_000
    assert result["p50"][0] == 42_000_000
    assert result["p75"][0] == 42_000_000


def test_core_runs_under_performance_budget(session_factory):
    """1000 Pfade x 20 Jahre Horizont muss in < 1.0s laufen (numpy-
    vektorisiert, antithetic). Real bei meiner Workstation ~50ms.
    """
    with session_factory() as s:
        advisor = _seed_advisor(s)
        cma = _seed_cma(s, advisor)
        s.commit()
        weights = np.array([0.4, 0.35, 0.1, 0.1, 0.05])
        start = time.perf_counter()
        _compute_paths_core(
            initial_wealth_rappen=10_000_000,
            horizon_years=20,
            weights=weights,
            cma=cma,
            cashflow_series=[0] * 20,
            n_paths=1000,
            seed=42,
        )
        elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"MC-Berechnung dauerte {elapsed:.3f}s > 1.0s Budget"


# ---------------------------------------------------------------------------
# DB-Schicht (`compute_quantile_paths`)
# ---------------------------------------------------------------------------

def test_compute_returns_data_pending_when_no_ta(session_factory):
    """Kein TA -> data_pending=True mit klarer Begruendung."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_cma(s, advisor)
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        result = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=50_000_000,
            horizon_years=15,
        )
    assert result["data_pending"] is True
    assert "Anlagestrategie" in result["note"]
    assert result["p5"] == []
    assert result["p50"] == []


def test_compute_returns_data_pending_when_no_cma(session_factory):
    """Kein CMA -> data_pending=True mit klarer Begruendung."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_ta(s, mandate, advisor)
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        result = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=50_000_000,
            horizon_years=15,
        )
    assert result["data_pending"] is True
    assert "Kapitalmarkt-Annahmen" in result["note"]


def test_compute_returns_data_pending_when_no_wealth(session_factory):
    """initial_wealth=0 -> data_pending=True. Sub-App rendert Platzhalter."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_ta(s, mandate, advisor)
        _seed_cma(s, advisor)
        s.commit()
        result = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=0,
            horizon_years=15,
        )
    assert result["data_pending"] is True
    assert "Beratungsvermoegen" in result["note"] or "Vermoegen" in result["note"]


def test_compute_happy_path_returns_quantile_arrays(session_factory):
    """Mit TA + CMA + Wealth -> echte Pfade mit korrekter Laenge."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_ta(s, mandate, advisor)
        _seed_cma(s, advisor)
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        result = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=50_000_000,
            horizon_years=15,
            n_paths=500,
        )
    assert result["data_pending"] is False
    assert len(result["p5"]) == 16
    assert len(result["p50"]) == 16
    assert len(result["p75"]) == 16
    assert result["p5"][0] == 50_000_000
    assert result["p50"][0] == 50_000_000
    assert result["p75"][0] == 50_000_000
    assert result["horizon_years"] == 15
    assert result["initial_wealth_rappen"] == 50_000_000


def test_compute_uses_default_n_paths_and_seed_when_unspecified(session_factory):
    """Defaults muessen die Modulkonstanten benutzen (Doku-Schutz)."""
    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_ta(s, mandate, advisor)
        _seed_cma(s, advisor)
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        result = compute_quantile_paths(
            s, mandate,
            initial_wealth_rappen=50_000_000,
            horizon_years=10,
        )
    assert result["n_paths"] == DEFAULT_N_PATHS
    assert result["seed"] == DEFAULT_SEED


def test_compute_end_to_end_wires_sub_allocations_json_from_ta(session_factory):
    """REP-001: eine echte TargetAllocation mit sub_allocations_json muss
    ueber compute_quantile_paths() bis in _compute_paths_core() durchreichen
    und das Ergebnis gegenueber einer TA ohne sub_allocations_json
    veraendern."""
    import json

    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        _seed_ta(s, mandate, advisor)
        _seed_cma(s, advisor)
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        baseline = compute_quantile_paths(
            s, mandate, initial_wealth_rappen=50_000_000, horizon_years=15, n_paths=1000,
        )

    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        # Zweite Session, dieselbe SQLite-Datei -> die is_current=1-Policy aus
        # dem baseline-Block oben existiert bereits (ux_optimizer_one_current
        # laesst nur eine aktuelle Policy zu), wiederverwenden statt eine
        # zweite anzulegen.
        existing_policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        ta = _seed_ta(s, mandate, advisor, policy=existing_policy)
        ta.sub_allocations_json = json.dumps([
            {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 10000},
        ])
        _seed_wealth_and_cashflows(s, client)
        s.commit()
        with_tilt = compute_quantile_paths(
            s, mandate, initial_wealth_rappen=50_000_000, horizon_years=15, n_paths=1000,
        )

    assert baseline["p50"] != with_tilt["p50"]


class _FakeTA:
    def __init__(self, sub_allocations_json):
        self.id = "fake-ta"
        self.sub_allocations_json = sub_allocations_json


def test_sub_allocations_from_ta_parses_valid_json():
    from services.monte_carlo_paths import _sub_allocations_from_ta

    ta = _FakeTA('[{"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 10000}]')
    result = _sub_allocations_from_ta(ta)
    assert result == [{"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 10000}]


def test_sub_allocations_from_ta_returns_none_when_missing():
    from services.monte_carlo_paths import _sub_allocations_from_ta

    assert _sub_allocations_from_ta(_FakeTA(None)) is None
    assert _sub_allocations_from_ta(_FakeTA("")) is None


def test_sub_allocations_from_ta_fails_soft_on_malformed_json():
    """Kaputtes JSON darf NICHT crashen -- Backwards-Compat-Fallback
    (historische Bucket-Defaults), konsistent mit dem fail-soft-Prinzip
    dieses Moduls."""
    from services.monte_carlo_paths import _sub_allocations_from_ta

    assert _sub_allocations_from_ta(_FakeTA("{not valid json")) is None
    assert _sub_allocations_from_ta(_FakeTA('"just a string"')) is None
    assert _sub_allocations_from_ta(_FakeTA('[1, 2, 3]')) is None


def test_annual_cashflow_series_excludes_unknown_cashflow_type(session_factory):
    """REP-003 (Codex-Audit 2026-08-25): ein unbekannter cashflow_type wurde
    bisher als Income gewertet (Vorzeichen still gekippt) -- muss jetzt
    neutral bleiben (nicht mitgezaehlt), nicht als positive Income."""
    from services.monte_carlo_paths import _annual_cashflow_series

    with session_factory() as s:
        advisor = _seed_advisor(s)
        client, mandate = _seed_client_with_mandate(s, advisor)
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client.id,
            cashflow_type="Sonstiges", label="Unbekannt",
            amount_rappen=1_000_000, frequency="jaehrlich",
            is_active=1, created_at=_NOW, updated_at=_NOW,
        ))
        s.commit()
        series = _annual_cashflow_series(s, mandate, horizon_years=5)
    assert series == [0] * 5
