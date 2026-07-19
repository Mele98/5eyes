"""AR-2 - MC-Risiko-Kennzahlen im FIDLEG-Report persistieren.

Vor dem Fix: services/advisory_report._build_key_metrics lieferte
exp_vol_bps / exp_return_bps / max_drawdown_bps / var_95_bps hartkodiert
als None -> die Report-Karte zeigte immer "—", obwohl der Monte-Carlo-Lauf
die Werte (auf Beratungsvermoegens-Ebene) berechnet.

Fix: generate_target_allocation persistiert die MC-target_*-KPIs auf der
TargetAllocation (neue Spalten mc_exp_vol_bps / mc_exp_return_bps /
mc_max_drawdown_bps / mc_var_95_bps, alle in bps), und _build_key_metrics
liest sie. Alt-TAs ohne die Werte -> weiterhin None (kein Bruch).

Gewaehlte MC-Keys (Scope = Beratungsvermoegen = target_*, NICHT total_*):
  mc_exp_vol_bps      <- target_volatility_1y_bps        (1-J-Vola, stddev)
  mc_exp_return_bps   <- target_annualized_return_p50_bps (annualis. Median)
  mc_max_drawdown_bps <- target_max_drawdown_p50_bps     (Median Max-DD)
  mc_var_95_bps       <- target_var_95_1y_bps            (1-J-VaR95, Loss>0)
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401  (ORM-Registry vollstaendig laden)
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.allocation import TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.advisory_report import _build_key_metrics, _safe_int
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
)

_KPI_KEYS = ("exp_vol_bps", "exp_return_bps", "max_drawdown_bps", "var_95_bps")
_TA_COLUMNS = ("mc_exp_vol_bps", "mc_exp_return_bps", "mc_max_drawdown_bps", "mc_var_95_bps")


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ar2_mc_kpis.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(session_factory):
    """Beratungsdepot mit gemischtem Risiko (40% Aktien) -> MC liefert
    nicht-triviale Vola/Return/MaxDD/VaR."""
    advisor_id = "user-ar2"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv-ar2", password_hash="h",
                   full_name="Adv AR2", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Int", last_name="AR2",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-ar2-depot", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-ar2-savings", client_id=cid, label="Sparplan",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=60, final_profile="Ausgewogen",
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def _current_ta(s, mid) -> TargetAllocation:
    return (
        s.query(TargetAllocation)
        .filter(TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1)
        .first()
    )


def test_ar2_mc_kpis_persisted_on_target_allocation(session_factory):
    """generate_target_allocation schreibt die vier MC-KPIs auf die TA
    (nicht None, integer, bps)."""
    advisor_id, cid, mid, aid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with session_factory() as s:
        ta = _current_ta(s, mid)
        assert ta is not None
        for col in _TA_COLUMNS:
            value = getattr(ta, col)
            assert value is not None, f"{col} muss persistiert sein (nicht None)"
            assert isinstance(value, int), f"{col} muss int (bps) sein, ist {type(value)}"
        # Sanity: Vola und annualisierter Return eines 40%-Aktien-Depots > 0.
        assert ta.mc_exp_vol_bps > 0
        assert ta.mc_exp_return_bps != 0
        # VaR95 ist als positiver Loss definiert (>= 0).
        assert ta.mc_var_95_bps >= 0
        assert ta.mc_max_drawdown_bps >= 0


def test_ar2_build_key_metrics_reads_persisted_kpis(session_factory):
    """_build_key_metrics weist die persistierten KPIs aus (statt hartkodiert
    None) und ist konsistent mit den TA-Spalten."""
    advisor_id, cid, mid, aid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = _current_ta(s, mid)
        metrics = _build_key_metrics(s, mandate)

        # Vola + Return sind praktisch garantiert != 0 -> muessen ausgewiesen sein.
        assert metrics["exp_vol_bps"] is not None
        assert metrics["exp_return_bps"] is not None

        # Konsistenz: jeder Report-Wert == _safe_int(TA-Spalte) or None
        for kpi_key, ta_col in zip(_KPI_KEYS, _TA_COLUMNS):
            expected = _safe_int(getattr(ta, ta_col)) or None
            assert metrics[kpi_key] == expected, (
                f"{kpi_key}={metrics[kpi_key]} != erwartet {expected} aus {ta_col}"
            )


def test_ar2_legacy_ta_without_kpis_yields_none(session_factory):
    """Bestehende TAs ohne persistierte KPIs (NULL) -> _build_key_metrics
    liefert weiterhin None (kein Bruch, Karte zeigt '—')."""
    advisor_id, cid, mid, aid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    # Simuliere Alt-TA: KPIs auf NULL setzen (wie vor der Migration befuellt).
    with session_factory() as s:
        ta = _current_ta(s, mid)
        for col in _TA_COLUMNS:
            setattr(ta, col, None)
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        metrics = _build_key_metrics(s, mandate)
        for kpi_key in _KPI_KEYS:
            assert metrics[kpi_key] is None, f"{kpi_key} muss None sein bei Alt-TA"
