"""DEPOT-E2E-STRESS-001 -- SOLL-Stress vs. IST-Stress (Option 1 + Option 2).

Audit: docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-
publication-integrity-audit.md (Finding DEPOT-E2E-STRESS-001, P1).

Befund (urspruenglich): ``compute_stress_replays()`` liest ausschliesslich
``TargetAllocation.target_*_bps`` (SOLL), die Oberflaechen behaupteten aber,
das aktuelle Depot zu stressen.

Aufloesung:
* Option 1 (PR #751): der SOLL-Replay ist ehrlich als SOLL beschriftet
  (``scope = approved_target_allocation``) und bleibt bewusst unabhaengig
  von den Bestaenden.
* Option 2: der IST-Stress (``scope = current_holdings_snapshot``) rechnet
  dieselben Szenarien auf einem hash-gebundenen DepotSnapshotV1 des
  bewerteten Depotbestands (services/depot_snapshot.py).

Dieser Test seedet zwei Mandate mit BYTE-IDENTISCHER TargetAllocation, deren
echte Depotbestaende (RecommendationHolding, Stueckzahl x Marktpreis) sich
diametral unterscheiden -- A haelt 100% Aktien, B 100% Liquiditaet. Der
SOLL-Replay muss identisch bleiben, der IST-Stress muss sich unterscheiden.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
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
import models.tenant  # noqa: E402,F401  (Sprint T1)
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import (  # noqa: E402
    PriceHistory, Product, RecommendationHolding, RecommendationPosition, RecommendationRun,
)
from models.users import User  # noqa: E402
from services.backtest_stress import compute_stress_replays  # noqa: E402
from services.currency.fx_rates import FXRateSource  # noqa: E402
from services.depot_snapshot import build_depot_snapshot, compute_ist_stress  # noqa: E402


_NOW = "2026-10-05T10:00:00.000Z"
_TODAY = date.today().isoformat()

# Identische SOLL-Gewichtung fuer BEIDE Mandate -- der einzige Unterschied
# zwischen Mandat A und B sind die tatsaechlichen aktuellen Holdings weiter
# unten (current_amount_rappen), niemals die TargetAllocation selbst.
_SHARED_TARGET_WEIGHTS_BPS = {
    "equities": 6000,
    "bonds": 2500,
    "real_estate": 500,
    "alternatives": 500,
    "liquidity": 500,
}


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'depot_e2e_stress_001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_actual_holdings(
    session_factory, *, label: str, holdings_asset_class: str, policy_is_current: int,
) -> str:
    """Seedet ein Mandat mit der GEMEINSAMEN TargetAllocation (SOLL) aus
    _SHARED_TARGET_WEIGHTS_BPS, aber tatsaechlichen aktuellen Holdings
    (RecommendationPosition.current_amount_rappen), die zu 100% in
    `holdings_asset_class` konzentriert sind -- zwischen den beiden
    Testmandaten also komplett verschieden, waehrend die SOLL-Allokation
    identisch bleibt.
    """
    suffix = uuid.uuid4().hex[:8]
    advisor = User(
        id=f"adv-{suffix}", username=f"adv-{suffix}", password_hash="h",
        full_name=f"Advisor {label}", role="advisor", is_active=1,
        created_at=_NOW, updated_at=_NOW,
    )
    client = Client(
        id=str(uuid.uuid4()), client_number=f"C-{suffix}",
        first_name=label, last_name="Mandant", advisor_id=advisor.id,
        country_of_residence="CH", created_at=_NOW, updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()), client_id=client.id,
        mandate_number=f"M-{suffix}", mandate_type="Anlageberatung",
        opened_at=_NOW, created_at=_NOW, updated_at=_NOW,
    )
    policy = OptimizerPolicy(
        id=str(uuid.uuid4()), policy_name=f"policy-{suffix}", version=1,
        # ux_optimizer_one_current erlaubt nur EINE global aktuelle Policy --
        # fuer das zweite Testmandat muss is_current=0 gesetzt werden. Die
        # TargetAllocation referenziert ihre Policy per policy_id unabhaengig
        # davon, ob diese "aktuell" ist; fuer compute_stress_replays() ist
        # policy.is_current ohnehin irrelevant (liest nur die TA-Spalten).
        is_current=policy_is_current, valid_from=_NOW[:10], optimizer_engine="goal_based_v1",
        max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0,
        allow_other_assets_for_goals=1, created_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    )
    ta = TargetAllocation(
        id=str(uuid.uuid4()), mandate_id=mandate.id, policy_id=policy.id,
        version=1, is_current=1,
        target_equities_bps=_SHARED_TARGET_WEIGHTS_BPS["equities"],
        target_bonds_bps=_SHARED_TARGET_WEIGHTS_BPS["bonds"],
        target_real_estate_bps=_SHARED_TARGET_WEIGHTS_BPS["real_estate"],
        target_alternatives_bps=_SHARED_TARGET_WEIGHTS_BPS["alternatives"],
        target_liquidity_bps=_SHARED_TARGET_WEIGHTS_BPS["liquidity"],
        band_equities_min_bps=5500, band_equities_max_bps=6500,
        band_bonds_min_bps=2000, band_bonds_max_bps=3000,
        band_real_estate_min_bps=0, band_real_estate_max_bps=1000,
        band_alternatives_min_bps=0, band_alternatives_max_bps=1000,
        band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
        risky_fraction_bps=9000, risk_budget_bps_at_generation=9000,
        set_by=advisor.id, set_at=_NOW,
        created_at=_NOW, updated_at=_NOW,
    )
    rec_run = RecommendationRun(
        id=str(uuid.uuid4()), mandate_id=mandate.id, client_id=client.id,
        target_allocation_id=ta.id, policy_id=policy.id, run_type="full",
        result_status="Approved", created_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    )
    with session_factory() as s:
        s.add_all([advisor, client, mandate, policy, ta, rec_run])
        s.flush()
        # 5 Produkte, eines je Asset-Klasse. target_weight_bps entspricht der
        # gemeinsamen SOLL-Allokation (identisch fuer A und B);
        # current_amount_rappen (= ECHTE aktuelle Holdings) ist zu 100% in
        # `holdings_asset_class` konzentriert und 0 ueberall sonst.
        total_rappen = 1_000_000_000  # CHF 10 Mio in Rappen
        for bucket, weight_bps in _SHARED_TARGET_WEIGHTS_BPS.items():
            product = Product(
                id=str(uuid.uuid4()), isin=f"TESTISIN{suffix}{bucket[:3]}".upper(),
                product_name=f"Test-{bucket}-{suffix}", product_type="ETF",
                asset_class=bucket, sub_asset_class=bucket, currency="CHF",
                ter_bps=20, provider="Test", is_active=1,
                created_at=_NOW, updated_at=_NOW,
            )
            s.add(product)
            position_id = str(uuid.uuid4())
            s.add(RecommendationPosition(
                id=position_id, run_id=rec_run.id, product_id=product.id,
                target_weight_bps=weight_bps,
                target_amount_rappen=int(total_rappen * weight_bps / 10000),
                current_amount_rappen=total_rappen if bucket == holdings_asset_class else 0,
                created_at=_NOW, updated_at=_NOW,
            ))
            if bucket == holdings_asset_class:
                # Echter Depotbestand: 100'000 Stueck x CHF 100 = CHF 10 Mio.
                s.add(RecommendationHolding(
                    id=str(uuid.uuid4()), run_id=rec_run.id,
                    recommendation_position_id=position_id, product_id=product.id,
                    as_of_date=_TODAY, units_milli=100_000_000, source="manual",
                    created_at=_NOW, updated_at=_NOW,
                ))
                s.add(PriceHistory(
                    id=str(uuid.uuid4()), product_id=product.id, price_date=_TODAY,
                    price_rappen=10_000, currency="CHF", source="test", fetched_at=_NOW,
                ))
        s.commit()
    return mandate.id


def test_soll_replay_stays_target_based_and_ist_stress_follows_holdings(session_factory):
    """Zwei Mandate mit IDENTISCHER TargetAllocation; A haelt 100% Aktien,
    B haelt 100% Liquiditaet (echte Bestaende mit Marktpreis)."""
    mandate_a_id = _seed_mandate_with_actual_holdings(
        session_factory, label="A-All-Equities", holdings_asset_class="equities",
        policy_is_current=1,
    )
    mandate_b_id = _seed_mandate_with_actual_holdings(
        session_factory, label="B-All-Liquidity", holdings_asset_class="liquidity",
        policy_is_current=0,
    )
    fx = FXRateSource({"CHF": 1.0})

    with session_factory() as s:
        mandate_a = s.query(Mandate).filter(Mandate.id == mandate_a_id).first()
        mandate_b = s.query(Mandate).filter(Mandate.id == mandate_b_id).first()
        soll_a = compute_stress_replays(s, mandate_a)
        soll_b = compute_stress_replays(s, mandate_b)
        ist_a = compute_ist_stress(build_depot_snapshot(s, mandate_a, as_of=date.today(), fx_source=fx))
        ist_b = compute_ist_stress(build_depot_snapshot(s, mandate_b, as_of=date.today(), fx_source=fx))

    def _gfc(result):
        return next(sc for sc in result["scenarios"] if sc["id"] == "global_financial_crisis_2008")

    # Option 1: SOLL bleibt SOLL -- identisch, unabhaengig von den Bestaenden.
    assert soll_a["scope"] == soll_b["scope"] == "approved_target_allocation"
    assert soll_a["weights_bps"] == soll_b["weights_bps"]
    assert _gfc(soll_a) == _gfc(soll_b)

    # Option 2: IST folgt dem bewerteten Depot.
    assert ist_a["scope"] == ist_b["scope"] == "current_holdings_snapshot"
    assert ist_a["status"] == ist_b["status"] == "ok"
    assert ist_a["weights_bps"]["equities"] == 10000
    assert ist_b["weights_bps"]["liquidity"] == 10000
    # GFC 2008: Aktien -42% (bestehender Szenariokatalog), Liquiditaet +2%.
    assert _gfc(ist_a)["max_drawdown_bps"] == 4200
    assert _gfc(ist_b)["max_drawdown_bps"] == 0
    assert _gfc(ist_a)["cumulative_return_bps"] != _gfc(ist_b)["cumulative_return_bps"]
    # Gleiche Szenarien wie der SOLL-Replay.
    assert [sc["id"] for sc in ist_a["scenarios"]] == [sc["id"] for sc in soll_a["scenarios"]]
