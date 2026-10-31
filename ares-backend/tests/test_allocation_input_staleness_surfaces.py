"""ALLOCATION-INPUT-STALENESS-001.

Nach einer materiellen Aenderung von Vermoegen/Cashflows/Zielen blockieren
Payload (409), Finalisierung und Strategie-PDF bereits korrekt
(``StaleAllocationInputError``: gespeicherter ``input_snapshot_hash`` passt
nicht mehr zu den Live-Inputs). Depot-Check (Sektion 7/8) und Building
Blocks (Sektion 13) im Beratungsreport prueften bisher nur die
Risikoprofil-Identitaet und zeigten die veraltete Soll-Allokation ohne
jeden Hinweis -- der "kundenfertige" Beratungsreport praesentierte damit
eine Allokation, die jede andere Oberflaeche bereits als veraltet ablehnt.

Erwartungen aus erster Hand (nicht aus dem Fix abgeleitet):
- Unveraenderte Inputs: Payload baut, also darf KEINE Oberflaeche "veraltet"
  melden (Positivkontrolle gegen ein immer-True-Flag).
- Groesste Position -75 %: Payload wirft StaleAllocationInputError, also
  muessen Depot-Check UND Building Blocks dieselbe Aussage treffen.
- Alt-Allokation ohne input_snapshot_hash: keine Aussage moeglich ->
  unmarkiert (identisch zum bestehenden Assessment-Helper).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import configure_mappers, sessionmaker  # noqa: E402

from database import Base  # noqa: E402
from models import (  # noqa: F401,E402
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
from models import tenant as _tenant  # noqa: F401,E402

configure_mappers()

from models.allocation import CapitalMarketAssumption, OptimizerPolicy, TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import WealthPosition  # noqa: E402
from services.advisory_report import compute_advisory_report  # noqa: E402
from services.depot_check import compute_depot_check  # noqa: E402
from services.foundation_example import (  # noqa: E402
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)
from services.portfolio_engine import (  # noqa: E402
    StaleAllocationInputError,
    _current_risk_assessment_or_none,
    build_target_payload_from_allocation,
)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'input_stale.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    s = SF()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _seed(s):
    adv = User(
        id="advisor-1", username="advisor", password_hash="h", full_name="Advisor",
        role="advisor", is_active=1,
        created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
    )
    s.add(adv)
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    mandate = s.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()
    return adv, mandate


def _current_ta(s, mandate):
    return s.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).one()


def _payload_is_stale(s, mandate, ta) -> bool:
    """Die bestehende, bereits korrekte Wahrheit: der Payload-Pfad."""
    policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == ta.policy_id).one()
    cma = s.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == ta.capital_market_assumptions_id
    ).one()
    try:
        build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=ta, policy=policy, cma=cma,
            assessment=_current_risk_assessment_or_none(s, mandate.id),
            preferences=None,
        )
    except StaleAllocationInputError:
        return True
    return False


def _reduce_largest_position(s, mandate):
    pos = s.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
    ).order_by(WealthPosition.current_value_rappen.desc()).first()
    pos.current_value_rappen = int(pos.current_value_rappen) // 4
    s.commit()


def test_unchanged_inputs_are_not_flagged(session):
    adv, mandate = _seed(session)
    ta = _current_ta(session, mandate)
    assert ta.input_snapshot_hash, "Fixture muss eine moderne, gehashte Allokation liefern"
    assert _payload_is_stale(session, mandate, ta) is False

    from services.allocation_input_staleness import allocation_inputs_stale
    assert allocation_inputs_stale(session, mandate, ta) is False

    dc = compute_depot_check(session, mandate)
    assert dc["target_allocation_stale"] is False
    assert dc["target_allocation_inputs_stale"] is False

    rep = compute_advisory_report(session, mandate, advisor=adv)
    bb = rep["building_blocks"]
    assert bb["target_allocation_stale"] is False
    assert not bb.get("staleness_hinweis")


def test_wealth_change_flags_depot_check_and_building_blocks(session):
    adv, mandate = _seed(session)
    ta = _current_ta(session, mandate)
    _reduce_largest_position(session, mandate)
    # Vorbedingung: die bestehende Payload-Wahrheit sagt "veraltet".
    assert _payload_is_stale(session, mandate, ta) is True

    dc = compute_depot_check(session, mandate)
    assert dc["target_allocation_stale"] is True
    assert dc["target_allocation_inputs_stale"] is True
    assert any(
        "Vermoegen, Cashflows oder Ziele" in w for w in dc["warnings"]
    ), dc["warnings"]
    # Kein falscher Grund: das Risikoprofil ist unveraendert.
    assert not any("frueheren, nicht mehr aktuellen Risikoprofil" in w for w in dc["warnings"])

    rep = compute_advisory_report(session, mandate, advisor=adv)
    aa_verdict = next(
        c for c in rep["erkenntnisse"]["checks"] if c["pruefpunkt"] == "Asset Allocation"
    )
    assert aa_verdict["bewertung"] == "nicht_beurteilbar"
    assert "Vermoegen, Cashflows oder Ziele" in aa_verdict["beurteilung"]
    assert rep["asset_allocation"]["target_allocation_stale"] is True
    assert "Vermoegen, Cashflows oder Ziele" in rep["asset_allocation"]["anmerkungen"]

    bb = rep["building_blocks"]
    assert bb["target_allocation_stale"] is True
    assert "Vermoegen, Cashflows oder Ziele" in bb["staleness_hinweis"]

    client_rep = compute_advisory_report(session, mandate, advisor=adv, client_facing=True)
    assert client_rep["building_blocks"]["target_allocation_stale"] is True

    from services.allocation_input_staleness import allocation_inputs_stale
    assert allocation_inputs_stale(session, mandate, ta) is True


def test_legacy_allocation_without_hash_stays_unflagged(session):
    adv, mandate = _seed(session)
    ta = _current_ta(session, mandate)
    ta.input_snapshot_hash = None
    session.commit()
    _reduce_largest_position(session, mandate)

    from services.allocation_input_staleness import allocation_inputs_stale
    assert allocation_inputs_stale(session, mandate, ta) is False
    dc = compute_depot_check(session, mandate)
    assert dc["target_allocation_stale"] is False
    assert dc["target_allocation_inputs_stale"] is False


def _bb_payload(**extra):
    return {
        "blocks": [{"key": "equities", "label": "Aktien", "target_bps": 5000,
                    "band_min_bps": 4500, "band_max_bps": 5500}],
        "constraints": [],
        "methodologie": "",
        **extra,
    }


def test_building_blocks_pdf_renders_staleness_notice():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import _build_building_blocks_flowables

    hinweis = "Soll-Allokation ist veraltet: Vermoegen, Cashflows oder Ziele haben sich geaendert."
    flowables = _build_building_blocks_flowables(
        _bb_payload(target_allocation_stale=True, staleness_hinweis=hinweis),
        make_advisory_styles(),
    )
    texts = [getattr(f, "text", "") for f in flowables]
    assert any("Vermoegen, Cashflows oder Ziele" in t for t in texts), texts


def test_building_blocks_pdf_without_flag_has_no_notice():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import _build_building_blocks_flowables

    flowables = _build_building_blocks_flowables(_bb_payload(), make_advisory_styles())
    texts = [getattr(f, "text", "") for f in flowables]
    assert not any("veraltet" in t for t in texts)
