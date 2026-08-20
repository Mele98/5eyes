"""Tests fuer Roadmap #61 — Reserve-Erklaerbarkeit im Advisory-Report.

Deckt services/advisory_report.py::_build_reserve_explainability ab:
- (a) Mandat MIT externer Reserve (SAA-Liquiditaets-Ceiling ueberschritten)
- (b) Mandat OHNE externe Reserve (einfacher Fall, Reserve innerhalb SAA-Cap)
- (c) Fehlerfall degradiert statt zu crashen (fail-closed)

Die Sektion aendert KEINE Zahlen: reserve_needed_rappen/external_reserve_rappen
kommen immer aus den persistierten Feldern der aktuellen TargetAllocation
(reserve_needed_at_generation_rappen / external_reserve_at_generation_rappen).
Die Komposition (narrative) wird nur gezeigt, wenn eine rein lesende
Nachrechnung ueber die Engine-Single-Source-of-Truth-Funktion
(_compute_reserve_for_inputs) exakt dieselben Totale liefert.
"""
from __future__ import annotations

import datetime
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
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.tenant  # noqa: F401
configure_mappers()

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.advisory_report import _build_reserve_explainability, compute_advisory_report
from services.portfolio_engine import ensure_runtime_reference_data, generate_target_allocation
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reserve_explainability.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_assessment(
    session_factory,
    *,
    advisory_wealth_rappen: int,
) -> tuple[str, str, str, str]:
    """Seedet Advisor+Client+Mandate+RiskAssessment+eine Beratungsvermoegen-
    Position. Rueckgabe: (advisor_id, client_id, mandate_id, assessment_id)."""
    advisor_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"adv-{advisor_id[:6]}", password_hash="h",
            full_name="Adv Test", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-{cid[:6]}", first_name="Res", last_name="Serve",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"pos-{mid[:6]}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=advisory_wealth_rappen, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        risk_fields = derive_current_risk_fields(
            q_income_points=2,
            q_obligations_points=3,
            q_savings_points=2,
            q_wealth_points=2,
            investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3,
            q_risk_preference_points=3,
            q_risk_behavior_points=3,
        )
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            **risk_fields,
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


# ---------------------------------------------------------------------------
# (a) Mandat MIT externer Reserve (SAA-Ceiling ueberschritten)
# ---------------------------------------------------------------------------

def test_reserve_explainability_with_external_reserve(session_factory):
    """Manuelle Reserve-Vorgabe (minReserve) deutlich ueber dem 3%-SAA-Cap
    -> externe Reserve wird empfohlen, Komposition ist nachvollziehbar und
    stimmt exakt mit den persistierten Totalen ueberein."""
    advisor_id, cid, mid, aid = _seed_mandate_with_assessment(
        session_factory, advisory_wealth_rappen=500_000_00,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        # CHF 100'000 manuelle Reserve auf CHF 500'000 Beratungsvermoegen (20%)
        # >> 3% SAA-Hard-Cap (CHF 15'000) -> externe Reserve = 100k - 15k = 85k.
        generate_target_allocation(
            s, mandate, advisor_id, preferences={"limits": {"minReserve": "100000"}},
        )
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is True
    assert section["reserve_needed_rappen"] == 100_000_00
    assert section["saa_liquidity_ceiling_bps"] == 300
    assert section["external_reserve_rappen"] == 100_000_00 - 15_000_00
    assert section["external_reserve_recommended"] is True
    assert section["external_reserve_reason"] is not None
    assert "SAA" in section["external_reserve_reason"] or "Liquiditaets" in section["external_reserve_reason"]
    # Komposition sollte fuer diesen frischen, unveraenderten Fall verfuegbar sein.
    assert section["composition_available"] is True
    assert section["drift_detected"] is False
    assert isinstance(section["narrative"], list)
    assert len(section["narrative"]) >= 1
    # Kein Anderes-Vermoegen-Pool vorhanden -> keine Absorption.
    assert section["other_assets_absorption_rappen"] == 0

    # Auch end-to-end ueber den vollen Report-Payload verfuegbar.
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        report = compute_advisory_report(s, mandate, advisor=None)
    assert report["reserve_explainability"]["external_reserve_recommended"] is True
    assert report["reserve_explainability"]["reserve_needed_rappen"] == 100_000_00


# ---------------------------------------------------------------------------
# (b) Mandat OHNE externe Reserve (einfacher Fall)
# ---------------------------------------------------------------------------

def test_reserve_explainability_without_external_reserve(session_factory):
    """Reserve-Bedarf bleibt innerhalb des 3%-SAA-Cap -> keine externe
    Reserve, aber die Komposition (manuelle Reserve-Vorgabe) ist trotzdem
    sichtbar."""
    advisor_id, cid, mid, aid = _seed_mandate_with_assessment(
        session_factory, advisory_wealth_rappen=1_000_000_00,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        # CHF 20'000 auf CHF 1'000'000 (2%) < 3% SAA-Cap (CHF 30'000)
        # -> keine externe Reserve.
        generate_target_allocation(
            s, mandate, advisor_id, preferences={"limits": {"minReserve": "20000"}},
        )
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is True
    assert section["reserve_needed_rappen"] == 20_000_00
    assert section["external_reserve_rappen"] == 0
    assert section["external_reserve_recommended"] is False
    assert section["external_reserve_reason"] is None
    assert section["composition_available"] is True
    assert section["drift_detected"] is False
    assert section["other_assets_absorption_rappen"] == 0


def test_reserve_explainability_no_reserve_needed(session_factory):
    """Kein Reserve-Bedarf (keine Cashflow-Shortfalls/Ziele/Vorgabe)
    -> degradiert sauber auf 'kein Bedarf', nicht auf 'nicht verfuegbar'."""
    advisor_id, cid, mid, aid = _seed_mandate_with_assessment(
        session_factory, advisory_wealth_rappen=1_000_000_00,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is True
    assert section["reserve_needed_rappen"] == 0
    assert section["external_reserve_rappen"] == 0
    assert section["composition_available"] is True
    assert section["narrative"] == [
        "Fuer dieses Mandat besteht aktuell kein zusaetzlicher Liquiditaetsreserve-Bedarf."
    ]


# ---------------------------------------------------------------------------
# (c) Fehlerfall degradiert statt zu crashen
# ---------------------------------------------------------------------------

def test_reserve_explainability_no_target_allocation_degrades(session_factory):
    """Kein aktives TargetAllocation -> degradiert auf leeres Schema,
    kein Crash."""
    now = _now()
    with session_factory() as s:
        advisor_id = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        s.add(User(id=advisor_id, username=f"adv-{advisor_id[:6]}", password_hash="h",
                    full_name="Adv", role="advisor", is_active=1,
                    created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}", first_name="No", last_name="TA",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        mandate = Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                           mandate_type="Anlageberatung", opened_at=now,
                           created_at=now, updated_at=now)
        s.add(mandate)
        s.commit()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is False
    assert section["reserve_needed_rappen"] is None
    assert section["external_reserve_rappen"] is None
    assert section["composition_available"] is False
    assert section["narrative"] == []
    assert section["hinweis"]


def test_reserve_explainability_degrades_on_unexpected_exception(session_factory, monkeypatch):
    """Wenn die Cache-/TA-Lookup-Kette unerwartet raised (z.B. Schema-Drift),
    degradiert die Sektion fail-closed statt den gesamten Report crashen zu
    lassen."""
    import services.advisory_report as advisory_report_module

    advisor_id, cid, mid, aid = _seed_mandate_with_assessment(
        session_factory, advisory_wealth_rappen=1_000_000_00,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    def _boom(_db, _mandate):
        raise RuntimeError("simulated schema drift")

    monkeypatch.setattr(advisory_report_module, "_cached_current_ta", _boom)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is False
    assert section["reserve_needed_rappen"] is None
    assert section["composition_available"] is False
    assert section["narrative"] == []


def test_reserve_explainability_legacy_ta_without_persisted_fields_degrades(session_factory):
    """TargetAllocation ohne persistierte Reserve-Audit-Felder (Legacy,
    reserve_needed_at_generation_rappen ist None) -> Hinweis statt falscher
    Zahl (0 waere fachlich falsch/irrefuehrend)."""
    advisor_id, cid, mid, aid = _seed_mandate_with_assessment(
        session_factory, advisory_wealth_rappen=1_000_000_00,
    )
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    from models.allocation import TargetAllocation
    with session_factory() as s:
        ta = s.query(TargetAllocation).filter(TargetAllocation.mandate_id == mid).first()
        ta.reserve_needed_at_generation_rappen = None
        ta.external_reserve_at_generation_rappen = None
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        section = _build_reserve_explainability(s, mandate)

    assert section["available"] is False
    assert section["reserve_needed_rappen"] is None
    assert "Legacy" in section["hinweis"]
