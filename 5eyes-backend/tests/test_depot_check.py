"""Tests für services/depot_check.py (Sprint U-P12 Engine + U-P20 SOLL-Drift).

Bisher 0 Tests trotz 367 Zeilen Engine + Endpoint + PDF + Frontend — hier
das Foundation-Test-Set:

- IST-Aggregation (Country/Sector/Currency aus Holdings)
- SOLL-Aggregation (gleiche Exposures, target_amount-Gewichtung)
- IST-SOLL-Drift pro Dimension (U-P20)
- Default-Proxy-Fallback wenn product.country_exposure_json fehlt
- HHI-Konzentrations-Score
- Warnings: Bandbreite, Konzentration, hohe Drift
- Edge Cases: leeres Mandat, kein RecommendationRun
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from services.depot_check import _compute_drift, compute_depot_check


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'depot_check.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _now() -> str:
    return "2026-05-24T12:00:00.000Z"


def _make_user(s, advisor_id: str = "adv-1") -> User:
    user = User(
        id=advisor_id,
        username="advisor",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(user)
    return user


def _make_mandate(s, advisor_id: str = "adv-1") -> Mandate:
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    s.add(Client(
        id=cid, client_number=f"C-{cid[:6]}",
        first_name="Test", last_name="Kunde",
        advisor_id=advisor_id,
        created_at=_now(), updated_at=_now(),
    ))
    mandate = Mandate(
        id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
        mandate_type="Anlageberatung", opened_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    s.add(mandate)
    return mandate


def _make_product(
    s,
    *,
    asset_class: str = "Aktien",
    sub_asset_class: str = "Aktien Schweiz",
    currency: str = "CHF",
    country_exposure_json: str | None = None,
    sector_exposure_json: str | None = None,
    currency_exposure_json: str | None = None,
    ter_bps: int = 20,
    name_prefix: str = "ETF",
) -> Product:
    prod = Product(
        id=str(uuid.uuid4()),
        isin=f"CH{uuid.uuid4().hex[:10].upper()}",
        product_name=f"{name_prefix}-{uuid.uuid4().hex[:4]}",
        product_type="ETF",
        asset_class=asset_class,
        sub_asset_class=sub_asset_class,
        currency=currency,
        ter_bps=ter_bps,
        country_exposure_json=country_exposure_json,
        sector_exposure_json=sector_exposure_json,
        currency_exposure_json=currency_exposure_json,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(prod)
    return prod


def _make_rec_position(
    s,
    *,
    run_id: str,
    product_id: str,
    current_amount_rappen: int,
    target_amount_rappen: int | None = None,
    target_weight_bps: int = 5000,
) -> RecommendationPosition:
    """Erstellt RecommendationPosition mit current_amount_rappen als
    echtem DB-Feld (Sprint U-P20: Spalte hinzugefügt für echten IST/SOLL-
    Drift im depot_check)."""
    pos = RecommendationPosition(
        id=str(uuid.uuid4()),
        run_id=run_id,
        product_id=product_id,
        target_weight_bps=target_weight_bps,
        target_amount_rappen=(
            target_amount_rappen
            if target_amount_rappen is not None
            else current_amount_rappen
        ),
        current_amount_rappen=current_amount_rappen,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(pos)
    s.flush()
    return pos


def _make_optimizer_policy(s, advisor_id: str = "adv-1") -> OptimizerPolicy:
    """Minimale OptimizerPolicy für RecommendationRun.policy_id FK."""
    # Der Current-Anker ist global eindeutig. Falls der Test eine neue Policy
    # braucht, wird die bisherige Version wie im Produkt-Lifecycle abgelöst.
    s.query(OptimizerPolicy).filter(
        OptimizerPolicy.is_current == 1,
    ).update(
        {OptimizerPolicy.is_current: 0},
        synchronize_session=False,
    )
    pol = OptimizerPolicy(
        id=str(uuid.uuid4()),
        policy_name="test-policy",
        version=1,
        is_current=1,
        valid_from=_now(),
        optimizer_engine="goal_based_v1",
        created_by=advisor_id,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(pol)
    s.flush()
    return pol


def _make_rec_run(
    s, *, mandate_id: str, client_id: str, advisor_id: str = "adv-1",
    result_status: str = "Draft", created_at: str | None = None,
) -> RecommendationRun:
    pol = _make_optimizer_policy(s, advisor_id=advisor_id)
    run = RecommendationRun(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        client_id=client_id,
        policy_id=pol.id,
        run_type="Standard",
        result_status=result_status,
        created_by=advisor_id,
        created_at=created_at or _now(),
        updated_at=created_at or _now(),
    )
    s.add(run)
    return run


def _make_target_allocation(
    s,
    *,
    mandate_id: str,
    advisor_id: str = "adv-1",
    equities_bps: int = 5000,
    bonds_bps: int = 3000,
    real_estate_bps: int = 1000,
    alternatives_bps: int = 500,
    liquidity_bps: int = 500,
    context_artifacts_required: int = 0,
    based_on_assessment_id: str | None = None,
) -> TargetAllocation:
    """Erstellt eine minimale TargetAllocation für SOLL-Bucket-Drift-Tests."""
    pol = _make_optimizer_policy(s, advisor_id=advisor_id)
    ta = TargetAllocation(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        version=1,
        is_current=1,
        target_equities_bps=equities_bps,
        target_bonds_bps=bonds_bps,
        target_real_estate_bps=real_estate_bps,
        target_alternatives_bps=alternatives_bps,
        target_liquidity_bps=liquidity_bps,
        band_equities_min_bps=max(0, equities_bps - 500),
        band_equities_max_bps=min(10000, equities_bps + 500),
        band_bonds_min_bps=max(0, bonds_bps - 500),
        band_bonds_max_bps=min(10000, bonds_bps + 500),
        band_real_estate_min_bps=max(0, real_estate_bps - 500),
        band_real_estate_max_bps=min(10000, real_estate_bps + 500),
        band_alternatives_min_bps=max(0, alternatives_bps - 500),
        band_alternatives_max_bps=min(10000, alternatives_bps + 500),
        band_liquidity_min_bps=max(0, liquidity_bps - 500),
        band_liquidity_max_bps=min(10000, liquidity_bps + 500),
        policy_id=pol.id,
        set_by=advisor_id,
        set_at=_now(),
        context_artifacts_required=context_artifacts_required,
        based_on_assessment_id=based_on_assessment_id,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(ta)
    return ta


def _make_risk_assessment(
    s, *, mandate_id: str, advisor_id: str = "adv-1", is_current: int = 1,
) -> RiskAssessment:
    """Minimales RiskAssessment fuer den target_allocation_stale-Check
    (Kontrollrunde 2026-09-20)."""
    ra = RiskAssessment(
        id=str(uuid.uuid4()), mandate_id=mandate_id, version=1,
        is_current=is_current, valid_from=_now()[:10],
        q_income_points=2, q_obligations_points=2,
        q_savings_points=6, q_wealth_points=6,
        risk_capacity_total=16, risk_capacity_profile="Ausgewogen",
        investment_horizon_years=9, investment_horizon_label="8 bis 11 Jahre",
        risk_capacity_score_x10=50,
        q_investment_goal_points=2, q_risk_preference_points=2,
        q_risk_behavior_points=2, risk_willingness_total=6,
        risk_willingness_profile="Ausgewogen", risk_willingness_score_x10=50,
        final_score_x10=50, final_profile="Ausgewogen",
        assessed_at=_now(), assessed_by=advisor_id,
        created_at=_now(), updated_at=_now(),
    )
    s.add(ra)
    s.flush()
    return ra


# ---------------------------------------------------------------------------
# 1. Pure unit test: _compute_drift Helper
# ---------------------------------------------------------------------------

def test_compute_drift_handles_union_of_keys():
    """Drift = IST − SOLL pro Key, mit Union beider Key-Mengen."""
    ist = {"CH": 6000, "US": 2000, "JP": 500}
    soll = {"CH": 4000, "US": 4000, "EU": 1500}
    drift = _compute_drift(ist, soll)
    assert drift == {
        "CH": 2000,   # Überhang
        "US": -2000,  # Unterhang
        "JP": 500,    # nur in IST
        "EU": -1500,  # nur in SOLL
    }


def test_compute_drift_handles_empty_inputs():
    assert _compute_drift({}, {}) == {}
    assert _compute_drift(None, None) == {}
    assert _compute_drift({"CH": 10000}, None) == {"CH": 10000}
    assert _compute_drift(None, {"CH": 10000}) == {"CH": -10000}


# ---------------------------------------------------------------------------
# 2. Edge: leeres Mandat
# ---------------------------------------------------------------------------

def test_empty_mandate_returns_warning(session_factory):
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["total_advisory_wealth_rappen"] == 0
    assert any("Beratungsvermögen" in w for w in result["warnings"])
    assert result["country_exposure_bps"] == {}
    assert result["soll_country_exposure_bps"] == {}


# ---------------------------------------------------------------------------
# 3. Pure-CH IST=SOLL → drift = 0
# ---------------------------------------------------------------------------

def test_pure_ch_portfolio_with_matching_target_has_zero_drift(session_factory):
    """Identische Country-Exposure in IST und SOLL → drift = 0."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(
            s,
            sub_asset_class="Aktien Schweiz",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        s.flush()
        _make_rec_position(
            s,
            run_id=run.id,
            product_id=prod.id,
            current_amount_rappen=1_000_000_00,
            target_amount_rappen=1_000_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["country_exposure_bps"] == {"CH": 10000}
    assert result["soll_country_exposure_bps"] == {"CH": 10000}
    assert result["country_exposure_drift_bps"] == {"CH": 0}


# ---------------------------------------------------------------------------
# 4. IST ≠ SOLL: Drift hat richtiges Vorzeichen + Magnitude
# ---------------------------------------------------------------------------

def test_overweight_ch_underweight_us_drift_has_correct_signs(session_factory):
    """Kunde 80/20 CH/US (IST), Empfehlung 50/50 (SOLL) → CH +30pp Überhang.

    Note: bestehender depot_check-Bug — wenn current_amount_rappen=0, fällt
    Engine auf target_amount zurück (siehe Doku in _make_rec_position).
    Daher setzen wir beide Positionen mit current > 0.
    """
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        ch_prod = _make_product(
            s,
            sub_asset_class="Aktien Schweiz",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        us_prod = _make_product(
            s,
            sub_asset_class="Aktien Global",
            country_exposure_json=json.dumps({"US": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=ch_prod.id,
            current_amount_rappen=800_000_00,  # Kunde hat viel CH
            target_amount_rappen=500_000_00,   # Berater empfiehlt weniger
        )
        _make_rec_position(
            s, run_id=run.id, product_id=us_prod.id,
            current_amount_rappen=200_000_00,  # Kunde hat wenig US
            target_amount_rappen=500_000_00,   # Berater empfiehlt mehr
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    # IST: 80/20 CH/US
    assert result["country_exposure_bps"]["CH"] == 8000
    assert result["country_exposure_bps"]["US"] == 2000
    # SOLL: 50/50 (target-Gewichte)
    assert result["soll_country_exposure_bps"]["CH"] == 5000
    assert result["soll_country_exposure_bps"]["US"] == 5000
    # Drift: CH +30pp, US -30pp
    assert result["country_exposure_drift_bps"]["CH"] == 3000
    assert result["country_exposure_drift_bps"]["US"] == -3000
    # Warning für hohe Drift (≥ 1500 bps)
    assert any("Land-Drift" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 5. Default-Proxy-Fallback wenn product.country_exposure_json fehlt
# ---------------------------------------------------------------------------

def test_default_proxy_used_when_country_exposure_json_missing(session_factory):
    """Ohne explizit gepflegtes Country-JSON greift Sub-Asset-Class-Proxy
    aus services/product_exposures.py (MSCI ACWI 2025)."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        # Aktien Global ohne expliziten JSON → Proxy
        # {"US": 6500, "CH": 300, "GB": 400, "JP": 600, "DE": 250, ...}
        prod = _make_product(
            s,
            sub_asset_class="Aktien Global",
            country_exposure_json=None,
        )
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1_000_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    # Proxy-Werte müssen erkennbar sein (US dominant)
    country_map = result["country_exposure_bps"]
    assert country_map["US"] > 6000  # Proxy hat US=6500 bps
    assert country_map["CH"] < 1000  # Proxy hat CH=300 bps
    assert "JP" in country_map  # Proxy enthält JP=600 bps


# ---------------------------------------------------------------------------
# 6. HHI-Berechnung: Single-Country = 10000, gleich-verteilt = 10000/n
# ---------------------------------------------------------------------------

def test_hhi_concentration_single_country_is_maximum(session_factory):
    """100% in einem Land → HHI = 10000 (Maximum)."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(
            s, country_exposure_json=json.dumps({"CH": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=500_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["concentration_hhi"]["country"] == 10000
    assert any("Länder-Konzentration" in w for w in result["warnings"])


def test_country_hhi_between_2500_and_5000_now_warns(session_factory):
    """Kontrollrunde 2026-09-20: 3-Laender-Split 40/30/30 -> HHI=3400. War
    vorher UNTER der alten 5000-Schwelle (keine Warnung), obwohl die PDF-
    Compliance-Ampel (_check_diversifikation) dieselbe Konzentration bereits
    als 'rot' (>2500) ausweist. Jetzt konsistent: Warnung ab >2500."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        ch_prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        us_prod = _make_product(s, country_exposure_json=json.dumps({"US": 10000}))
        de_prod = _make_product(s, country_exposure_json=json.dumps({"DE": 10000}))
        s.flush()
        _make_rec_position(s, run_id=run.id, product_id=ch_prod.id, current_amount_rappen=400_000_00)
        _make_rec_position(s, run_id=run.id, product_id=us_prod.id, current_amount_rappen=300_000_00)
        _make_rec_position(s, run_id=run.id, product_id=de_prod.id, current_amount_rappen=300_000_00)
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["concentration_hhi"]["country"] == 3400
    assert any("Länder-Konzentration" in w for w in result["warnings"])


def test_large_unknown_liquidity_share_produces_data_quality_warning(session_factory):
    """Kontrollrunde 2026-09-20: unknown_bps (unklassifizierbare Liquiditaet)
    floss vorher in KEINE Warnung ein und konnte echtes Risiko verstecken."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        # product_type "Strukturiertes Produkt" bei bucket=equities matcht
        # keine der _product_liquidity_tier-Heuristiken -> "unknown".
        prod = _make_product(
            s, asset_class="Aktien",
            country_exposure_json=json.dumps({"CH": 10000}),
            name_prefix="Strukt",
        )
        prod.product_type = "Strukturiertes Produkt"
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1_000_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["liquidity_profile"]["unknown_bps"] == 10000
    assert any("Liquiditaets-Einstufung unklar" in w for w in result["warnings"])


def test_multiple_country_drift_offenders_all_listed_not_just_worst(session_factory):
    """Kontrollrunde 2026-09-20: CH +18pp UND US -19pp gleichzeitig ausserhalb
    der Toleranz -- vorher erschien nur der schlimmste (US) in der
    Warnliste, CH blieb unsichtbar."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        ch_prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        us_prod = _make_product(s, country_exposure_json=json.dumps({"US": 10000}))
        s.flush()
        # IST: CH 58%, US 42%. SOLL (target_amount): CH 40%, US 61%.
        _make_rec_position(
            s, run_id=run.id, product_id=ch_prod.id,
            current_amount_rappen=580_000_00, target_amount_rappen=400_000_00,
        )
        _make_rec_position(
            s, run_id=run.id, product_id=us_prod.id,
            current_amount_rappen=420_000_00, target_amount_rappen=610_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    ch_warnings = [w for w in result["warnings"] if "Land-Drift" in w and "'CH'" in w]
    us_warnings = [w for w in result["warnings"] if "Land-Drift" in w and "'US'" in w]
    assert len(ch_warnings) == 1
    assert len(us_warnings) == 1


def test_negative_current_amount_falls_back_to_target_consistently(session_factory):
    """Kontrollrunde 2026-09-20: current_amount_rappen<0 (aktuell ueber keinen
    bekannten Schreibpfad erreichbar, aber auch durch keine DB-Constraint
    verhindert) darf nicht dazu fuehren, dass _load_positions und die
    Haupt-Aggregation unterschiedliche Fallback-Entscheidungen treffen --
    sonst summieren sich die Bucket-Prozente nicht mehr auf 100%."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        s.flush()
        pos = _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1,  # Platzhalter, unten ueberschrieben
            target_amount_rappen=500_000_00,
        )
        pos.current_amount_rappen = -100  # negativ, nicht ueber die API erreichbar
        s.commit()
        result = compute_depot_check(s, mandate)
    # total_rappen (Nenner) UND die Bucket-Aggregation muessen denselben
    # Fallback-Betrag (target_amount) verwendet haben -> IST-Summe = 100%.
    assert result["total_advisory_wealth_rappen"] == 500_000_00
    total_ist_bps = sum(b["ist_bps"] for b in result["buckets"].values())
    assert total_ist_bps == 10000


# ---------------------------------------------------------------------------
# 7. Kein RecommendationRun: SOLL bleibt leer (Fallback zu WealthPositions)
# ---------------------------------------------------------------------------

def test_newer_draft_run_does_not_override_older_final_run(session_factory):
    """Kontrollrunde 2026-09-20: ein rein exploratorischer, nicht freige-
    gebener Draft-Lauf, der CHRONOLOGISCH nach dem freigegebenen Final-Lauf
    erstellt wurde, darf nicht als das tatsaechliche IST-Depot in den
    Depot-Check einfliessen. Final-zuerst-Fallback wie bereits etabliert in
    routers/review.py und services/review_engine.py."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)

        # Final-Lauf (aelter, aber der tatsaechlich freigegebene/gehaltene)
        final_run = _make_rec_run(
            s, mandate_id=mandate.id, client_id=mandate.client_id,
            result_status="Final", created_at="2026-05-01T10:00:00.000Z",
        )
        s.flush()
        final_prod = _make_product(
            s, asset_class="Aktien",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=final_run.id, product_id=final_prod.id,
            current_amount_rappen=1_000_000_00,
        )

        # Draft-Lauf (juenger, rein exploratorisch, nie freigegeben)
        draft_run = _make_rec_run(
            s, mandate_id=mandate.id, client_id=mandate.client_id,
            result_status="Draft", created_at="2026-06-01T10:00:00.000Z",
        )
        s.flush()
        draft_prod = _make_product(
            s, asset_class="Alternative",
            country_exposure_json=json.dumps({"US": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=draft_run.id, product_id=draft_prod.id,
            current_amount_rappen=9_000_000_00,  # deutlich anderer Betrag
        )
        s.commit()
        result = compute_depot_check(s, mandate)

    # Muss den Final-Lauf verwenden (CHF 1 Mio, 100% CH-Aktien), nicht den
    # juengeren, aber nie freigegebenen Draft-Lauf (CHF 9 Mio, Alternative).
    assert result["total_advisory_wealth_rappen"] == 1_000_000_00
    assert result["country_exposure_bps"] == {"CH": 10000}
    assert result["buckets"]["equities"]["ist_bps"] == 10000
    assert result["buckets"]["alternatives"]["ist_bps"] == 0


def test_draft_run_used_when_no_final_run_exists(session_factory):
    """Kein Final-Lauf vorhanden -> Fallback auf den (juengsten) Draft-Lauf,
    identisches Fallback-Muster wie routers/review.py. Kein Verhaltensbruch
    fuer den haeufigen Fall 'noch nichts freigegeben'."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(
            s, mandate_id=mandate.id, client_id=mandate.client_id,
            result_status="Draft",
        )
        s.flush()
        prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1_000_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["total_advisory_wealth_rappen"] == 1_000_000_00


def test_no_recommendation_run_leaves_soll_empty(session_factory):
    """Ohne RecommendationRun greift WealthPosition-Fallback, aber SOLL-
    Exposures sind nicht ableitbar (kein target_amount in WealthPosition)."""
    from models.wealth import WealthPosition
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        s.flush()
        s.add(WealthPosition(
            id=str(uuid.uuid4()),
            client_id=mandate.client_id,
            label="UBS-Konto",
            position_type="Konto",
            assignment="Beratungsvermögen",
            current_value_rappen=200_000_00,
            currency="CHF",
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["total_advisory_wealth_rappen"] == 200_000_00
    assert result["soll_country_exposure_bps"] == {}
    assert result["country_exposure_drift_bps"] == {}


# ---------------------------------------------------------------------------
# 8. RecommendationRun ohne target_amount → Warning
# ---------------------------------------------------------------------------

def test_recommendation_without_target_amount_produces_warning(session_factory):
    """RecommendationPosition mit target_amount=0 → kein SOLL ableitbar.

    Note: depot_check verwendet (current_amount OR target_amount) als
    Aggregations-Basis, daher muss current_amount > 0 sein damit
    die Position überhaupt in IST aufgenommen wird.
    """
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        s.flush()
        # current > 0 damit Position überhaupt verarbeitet wird;
        # target=0 für ALLE Positions → SOLL nicht aggregierbar
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=500_000_00,
            target_amount_rappen=1,  # quasi-zero, aber > 0 damit Fallback nicht greift
        )
        # Setze danach target_amount auf 0
        from models.review import RecommendationPosition
        pos = s.query(RecommendationPosition).filter(
            RecommendationPosition.run_id == run.id
        ).one()
        pos.target_amount_rappen = 0
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["country_exposure_bps"]["CH"] == 10000
    assert result["soll_country_exposure_bps"] == {}
    assert any(
        "SOLL-Vergleich nicht möglich" in w
        for w in result["warnings"]
    )


# ---------------------------------------------------------------------------
# 9. Bucket-Drift gegen TargetAllocation
# ---------------------------------------------------------------------------

def test_bucket_drift_against_target_allocation(session_factory):
    """Bucket-Drift verwendet TargetAllocation.target_*_bps als SOLL."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        # IST: 100% Aktien
        prod_eq = _make_product(
            s, asset_class="Aktien", sub_asset_class="Aktien Schweiz",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod_eq.id,
            current_amount_rappen=1_000_000_00,
        )
        # SOLL: 50/30/10/5/5 (Standard Wachstumsorientiert)
        _make_target_allocation(
            s, mandate_id=mandate.id,
            equities_bps=5000, bonds_bps=3000,
            real_estate_bps=1000, alternatives_bps=500,
            liquidity_bps=500,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    eq_bucket = result["buckets"]["equities"]
    assert eq_bucket["ist_bps"] == 10000
    assert eq_bucket["soll_bps"] == 5000
    assert eq_bucket["drift_bps"] == 5000
    assert eq_bucket["in_band"] is False  # 100% > Band-Max (55%)
    # Out-of-band Warning
    assert any("Aktien außerhalb Toleranzband" in w for w in result["warnings"])
    assert result["target_allocation_stale"] is False


# ---------------------------------------------------------------------------
# 9b. Kontrollrunde 2026-09-20: TargetAllocation-Staleness
# ---------------------------------------------------------------------------

def test_target_allocation_based_on_current_assessment_not_stale(session_factory):
    """TargetAllocation basiert auf dem AKTUELLEN Risikoprofil -> nicht stale."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        ra = _make_risk_assessment(s, mandate_id=mandate.id)
        s.flush()
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1_000_000_00,
        )
        _make_target_allocation(
            s, mandate_id=mandate.id,
            equities_bps=5000, bonds_bps=3000, real_estate_bps=1000,
            alternatives_bps=500, liquidity_bps=500,
            context_artifacts_required=1, based_on_assessment_id=ra.id,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["target_allocation_stale"] is False


def test_target_allocation_predating_current_assessment_is_flagged_stale(session_factory):
    """Kontrollrunde 2026-09-20: TargetAllocation wurde unter einem AELTEREN
    Risikoprofil erstellt, ein neueres ist inzwischen aktuell -> stale. Vorher
    zeigte compute_depot_check hierfuer 'in_band: True' ohne jeden Hinweis,
    obwohl services.suitability_audit.audit_mandate_suitability dasselbe
    Mandat bereits als non-compliant auswies (SUITABILITY-ALLOCATION-
    STALENESS-001, selber Tag)."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        old_ra = _make_risk_assessment(s, mandate_id=mandate.id, is_current=0)
        s.flush()
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        eq_prod = _make_product(
            s, asset_class="Aktien",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        bond_prod = _make_product(
            s, asset_class="Obligationen",
            country_exposure_json=json.dumps({"CH": 10000}),
        )
        s.flush()
        # 50/50 equities/bonds -> equities IST=50%, exakt im Band 45-55%.
        _make_rec_position(
            s, run_id=run.id, product_id=eq_prod.id,
            current_amount_rappen=500_000_00,
        )
        _make_rec_position(
            s, run_id=run.id, product_id=bond_prod.id,
            current_amount_rappen=500_000_00,
        )
        _make_target_allocation(
            s, mandate_id=mandate.id,
            equities_bps=5000, bonds_bps=3000, real_estate_bps=1000,
            alternatives_bps=500, liquidity_bps=500,
            context_artifacts_required=1, based_on_assessment_id=old_ra.id,
        )
        # Neues, aktuelles Risikoprofil -- Mandat wurde re-profiliert, die
        # Allokation aber nie neu berechnet.
        new_ra = _make_risk_assessment(s, mandate_id=mandate.id, is_current=1)
        s.commit()
        result = compute_depot_check(s, mandate)
    assert old_ra.id != new_ra.id
    # Die rohe Band-Berechnung selbst bleibt unveraendert verfuegbar ...
    assert result["buckets"]["equities"]["in_band"] is True
    # ... aber der Staleness-Flag macht sie als Grundlage fuer eine
    # Compliance-Aussage ungueltig.
    assert result["target_allocation_stale"] is True
    assert any("frueheren" in w and "Risikoprofil" in w for w in result["warnings"])


def test_legacy_target_allocation_without_context_artifacts_not_flagged_stale(session_factory):
    """Alt-Allokation ohne context_artifacts_required (vor Einfuehrung dieses
    Feldes) wird aus Rueckwaertskompat-Gruenden NICHT als stale markiert --
    identisches Gate wie im Live-Strategiepfad."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        _make_risk_assessment(s, mandate_id=mandate.id)
        s.flush()
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, country_exposure_json=json.dumps({"CH": 10000}))
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod.id,
            current_amount_rappen=1_000_000_00,
        )
        _make_target_allocation(
            s, mandate_id=mandate.id,
            context_artifacts_required=0, based_on_assessment_id=None,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["target_allocation_stale"] is False


# ---------------------------------------------------------------------------
# 10. Sector-Drift (analog Country)
# ---------------------------------------------------------------------------

def test_sector_drift_computed_alongside_country(session_factory):
    """Sector-Aggregation und -Drift funktionieren parallel zu Country."""
    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod_tech = _make_product(
            s, sub_asset_class="Aktien Global",
            sector_exposure_json=json.dumps(
                {"Information Technology": 10000}
            ),
            country_exposure_json=json.dumps({"US": 10000}),
        )
        prod_diversified = _make_product(
            s, sub_asset_class="Aktien Global",
            sector_exposure_json=json.dumps({
                "Information Technology": 3000,
                "Financials": 2000,
                "Health Care": 2000,
                "Industrials": 1500,
                "Consumer Discretionary": 1500,
            }),
            country_exposure_json=json.dumps({"US": 10000}),
        )
        s.flush()
        _make_rec_position(
            s, run_id=run.id, product_id=prod_tech.id,
            current_amount_rappen=800_000_00,
            target_amount_rappen=200_000_00,
        )
        _make_rec_position(
            s, run_id=run.id, product_id=prod_diversified.id,
            current_amount_rappen=200_000_00,
            target_amount_rappen=800_000_00,
        )
        s.commit()
        result = compute_depot_check(s, mandate)
    # IST: 80% Tech-only + 20% Diversified
    # Tech-only liefert IT=10000, Diversified IT=3000
    # → IT-Anteil = 0.8 * 1.0 + 0.2 * 0.3 = 0.86 (Bei reiner Gewichts-Aggregation
    # vor Re-Skalierung). Aggregate_exposures re-skaliert auf 10000,
    # aber Tech-only liefert nur 1 Sektor, Diversified 5 Sektoren —
    # nach Re-Skalierung kommt IT-Wert ungefähr 8800 raus.
    assert result["sector_exposure_bps"]["Information Technology"] > 8000
    # SOLL: 20% Tech-only + 80% Diversified → ~44% IT
    assert result["soll_sector_exposure_bps"]["Information Technology"] < 5000
    # Drift: Sector ist überhängend
    it_drift = result["sector_exposure_drift_bps"]["Information Technology"]
    assert it_drift > 3000  # > 30 Prozentpunkte Überhang
    assert any("Sektor-Drift Überhang" in w for w in result["warnings"])
