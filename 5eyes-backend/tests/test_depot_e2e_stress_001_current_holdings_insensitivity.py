"""DEPOT-E2E-STRESS-001 (P1, offen) -- Red-Test fuer das Stress-Replay-Modell.

Audit: docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-
publication-integrity-audit.md (Finding DEPOT-E2E-STRESS-001, P1, offen).

Befund
------
Das Frontend-Modal (5eyes-electron/frontend/5eyes_v2.html, Stress-Replay-
Hinweistext) behauptet explizit:

    "Modell zeigt was passieren waere wenn das aktuelle Depot zu Beginn
    der Krise gehalten wurde."

-- verspricht also einen Replay der ECHTEN aktuellen Positionen/Holdings
des Kunden ("aktuelles Depot").

services/backtest_stress.py::compute_stress_replays() liest dafuer aber
AUSSCHLIESSLICH TargetAllocation.target_*_bps (die SOLL-Gewichtung der
Strategie) -- niemals RecommendationPosition.current_amount_rappen oder
sonstige IST-Holdings-Daten. Das Stress-Resultat ist dadurch komplett
unempfindlich gegenueber den tatsaechlichen aktuellen Holdings des Kunden.

Dieser Test seedet zwei Mandate mit BYTE-IDENTISCHER TargetAllocation
(SOLL), deren tatsaechliche aktuelle Holdings (RecommendationPosition.
current_amount_rappen) sich aber diametral unterscheiden -- Mandat A haelt
aktuell 100% Aktien, Mandat B haelt aktuell 100% Liquiditaet. Ein Modell,
das die Frontend-Behauptung einloest, muesste fuer die Globale Finanzkrise
2008 (Aktien ca. -42% Peak-to-Trough, Liquiditaet ca. +2%) klar
unterschiedliche Resultate liefern. Heute liefert die Engine fuer beide
Mandate BYTE-IDENTISCHE Resultate, weil sie die Holdings nie liest.

Dieser Test ist ABSICHTLICH xfail(strict=True) -- er dokumentiert den Bug
mechanisch, loest ihn aber nicht. Der eigentliche Fix (diskriminierter
Scope current_holdings_snapshot vs. approved_target_allocation, Bindung
der Stress-Resultate an eine Scope-ID) ist eine groessere Modelländerung
und wartet auf Design-Freigabe.
"""
from __future__ import annotations

import sys
import uuid
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
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from services.backtest_stress import compute_stress_replays  # noqa: E402


_NOW = "2026-10-05T10:00:00.000Z"

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
            s.add(RecommendationPosition(
                id=str(uuid.uuid4()), run_id=rec_run.id, product_id=product.id,
                target_weight_bps=weight_bps,
                target_amount_rappen=int(total_rappen * weight_bps / 10000),
                current_amount_rappen=total_rappen if bucket == holdings_asset_class else 0,
                created_at=_NOW, updated_at=_NOW,
            ))
        s.commit()
    return mandate.id


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEPOT-E2E-STRESS-001 (P1, offen; docs/audits/2026-10-05-"
        "depotcheck-end-to-end-product-identity-and-publication-integrity-"
        "audit.md): compute_stress_replays() liest ausschliesslich "
        "TargetAllocation.target_*_bps (SOLL), nie RecommendationPosition."
        "current_amount_rappen (IST-Holdings) -> Stress-Resultate sind fuer "
        "zwei Mandate mit identischer SOLL-Allokation, aber komplett "
        "verschiedenen aktuellen Holdings, identisch -- obwohl das Frontend "
        "(5eyes_v2.html) behauptet, das 'aktuelle Depot' zu stressen. Fix "
        "(diskriminierter Scope current_holdings_snapshot vs. "
        "approved_target_allocation) wartet auf Design-Freigabe."
    ),
)
def test_stress_replay_ignores_actual_current_holdings(session_factory):
    """Zwei Mandate mit IDENTISCHER TargetAllocation, aber Mandat A haelt
    aktuell 100% Aktien und Mandat B haelt aktuell 100% Liquiditaet.

    Das Frontend behauptet, das Stress-Replay zeige "was passieren waere
    wenn das aktuelle Depot zu Beginn der Krise gehalten wurde". Ein Modell,
    das diese Behauptung tatsaechlich einloest, MUSS fuer ein 100%-Aktien-
    Depot in der Globalen Finanzkrise 2008 (Aktien ca. -42% Peak-to-Trough)
    ein klar anderes Resultat liefern als fuer ein 100%-Liquiditaets-Depot.
    Heute liefert die Engine fuer beide Mandate BYTE-IDENTISCHE Resultate.
    """
    mandate_a_id = _seed_mandate_with_actual_holdings(
        session_factory, label="A-All-Equities", holdings_asset_class="equities",
        policy_is_current=1,
    )
    mandate_b_id = _seed_mandate_with_actual_holdings(
        session_factory, label="B-All-Liquidity", holdings_asset_class="liquidity",
        policy_is_current=0,
    )

    with session_factory() as s:
        mandate_a = s.query(Mandate).filter(Mandate.id == mandate_a_id).first()
        mandate_b = s.query(Mandate).filter(Mandate.id == mandate_b_id).first()
        result_a = compute_stress_replays(s, mandate_a)
        result_b = compute_stress_replays(s, mandate_b)

    # Sanity-Check (muss bestehen bleiben): die SOLL-Allokation ist wie
    # beabsichtigt fuer beide Mandate identisch -- der einzige Unterschied
    # sind die tatsaechlichen aktuellen Holdings (siehe Seeding oben). Faellt
    # dieser Sanity-Check, ist das Testsetup kaputt, nicht der Produktbug.
    assert result_a["weights_bps"] == result_b["weights_bps"]

    gfc_a = next(sc for sc in result_a["scenarios"] if sc["id"] == "global_financial_crisis_2008")
    gfc_b = next(sc for sc in result_b["scenarios"] if sc["id"] == "global_financial_crisis_2008")

    # Mandat A haelt aktuell 100% Aktien (GFC 2008 Peak-to-Trough ca. -42%,
    # Erholung 2009 +30%), Mandat B haelt aktuell 100% Liquiditaet (GFC 2008
    # ca. +2%/+0.5%). Ein Stress-Replay, das tatsaechlich das "aktuelle
    # Depot" stresst (wie vom Frontend-Modaltext versprochen), MUSS hier
    # fuer A einen klar anderen max_drawdown_bps liefern als fuer B.
    assert gfc_a["max_drawdown_bps"] != gfc_b["max_drawdown_bps"], (
        "Stress-Replay liefert fuer komplett unterschiedliche aktuelle "
        "Holdings (100% Aktien vs. 100% Liquiditaet) denselben "
        "max_drawdown_bps -> die Engine stresst nachweislich nicht das "
        "'aktuelle Depot', sondern ausschliesslich die (hier bewusst "
        "identisch gehaltene) TargetAllocation."
    )
    assert gfc_a["cumulative_return_bps"] != gfc_b["cumulative_return_bps"]
