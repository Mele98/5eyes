"""PENSION-AVAILABILITY-001 (Phase 0, 2026-09): gesperrtes Vorsorgekapital
darf den heutigen Liquiditaets-Reserve-Bedarf nicht 1:1 mindern, nur weil
is_available_for_goal_funding=1 gesetzt ist.

Audit-Repro: eine CHF 80'000 "Anderes Vermoegen"-Position vom Typ Vorsorge
(Kapitalbezug erst ab Alter 63, noch nicht erreicht) mit
is_available_for_goal_funding=1 reduzierte den externen Reserve-Bedarf so,
als waere das Geld heute abrufbar -- obwohl weder ein erreichtes
Pensionierungsalter noch ein bestaetigtes Verfuegbarkeitsdatum vorlag.

Fix: services.portfolio_engine._position_is_currently_unlocked_for_goal_funding()
ist jetzt die einzige Quelle fuer den 'Schloss-Pool'
(unlocked_other_assets_rappen) in _load_allocation_inputs (Generierungspfad),
im Rebuild-Pfad UND in services/advisory_report.py. Eine Position zaehlt nur
als unlocked, wenn sie KEINE Vorsorge-Restriktionsmerkmale traegt
(unveraendertes Verhalten fuer normale liquide Positionen) ODER ein bereits
erreichtes liquidity_available_from vorweist.

Dieses Modul testet:
1. Direkt (Unit): _position_is_currently_unlocked_for_goal_funding() fuer
   alle vier Kernfaelle aus dem Auftrag.
2. End-to-End (Integration): _load_allocation_inputs() gegen eine echte
   SQLite-DB -- der Schloss-Pool-Delta (unlocked_other_assets_rappen) muss
   sich exakt wie erwartet verhalten, wenn eine Position hinzugefuegt wird.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401 — registriert ALLE Models fuer create_all
import services.portfolio_engine as pe
from models.wealth import WealthPosition
from models.mandates import Mandate
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# ============================================================================
# 1) Unit-Tests: _position_is_currently_unlocked_for_goal_funding()
# ============================================================================


def _base_position(**overrides):
    fields = dict(
        id="pos-1", client_id="c-1", label="Test-Position",
        position_type="Liquidität", assignment="Anderes Vermögen",
        current_value_rappen=80_000_00, currency="CHF",
        is_available_for_goal_funding=1,
        pension_type=None, pension_retirement_age=None,
        pension_payout_form=None, liquidity_available_from=None,
        is_active=1,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_plain_liquid_position_with_flag_counts_as_unlocked():
    """Regressionsschutz: eine normale liquide 'Anderes Vermoegen'-Position
    OHNE jegliche Vorsorge-Merkmale bleibt unveraendert -- is_available_for_
    goal_funding=1 reicht weiterhin aus."""
    pos = _base_position()
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is True


def test_pension_position_future_availability_does_not_count():
    """Kernfund PENSION-AVAILABILITY-001: eine Vorsorge-Position (Kapitalbezug
    ab Alter 63, kein bestaetigtes Verfuegbarkeitsdatum) zaehlt NICHT mehr
    als unlocked, obwohl is_available_for_goal_funding=1 gesetzt ist."""
    pos = _base_position(
        position_type="Vorsorge",
        pension_type="BVG",
        pension_retirement_age=63,
    )
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is False


def test_pension_position_with_future_liquidity_available_from_does_not_count():
    pos = _base_position(
        position_type="Vorsorge",
        pension_type="Säule 3a",
        pension_retirement_age=63,
        liquidity_available_from=(date.today() + timedelta(days=365)).isoformat(),
    )
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is False


def test_pension_position_with_past_availability_date_counts():
    """Wenn das Verfuegbarkeitsdatum bereits erreicht ist, zaehlt die
    Position wieder normal -- das Geld ist nachweislich heute abrufbar."""
    pos = _base_position(
        position_type="Vorsorge",
        pension_type="BVG",
        pension_retirement_age=63,
        liquidity_available_from=(date.today() - timedelta(days=1)).isoformat(),
    )
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is True


def test_pension_position_with_todays_availability_date_counts():
    """Grenzfall: <= heute (nicht nur < heute) zaehlt als erreicht."""
    pos = _base_position(
        position_type="Vorsorge",
        pension_retirement_age=63,
        liquidity_available_from=date.today().isoformat(),
    )
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is True


def test_flag_not_set_never_counts_regardless_of_pension_metadata():
    pos = _base_position(is_available_for_goal_funding=0, position_type="Vorsorge")
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is False


def test_wrong_assignment_never_counts():
    pos = _base_position(assignment="Beratungsvermögen")
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is False


def test_pension_payout_form_alone_is_restrictive_even_without_age():
    """pension_payout_form (z.B. 'Kapital') ist ebenfalls ein Vorsorge-Beleg,
    nicht nur pension_retirement_age -- ohne Verfuegbarkeitsnachweis bleibt
    die Position gesperrt."""
    pos = _base_position(position_type="Vorsorge", pension_payout_form="Kapital")
    assert pe._position_is_currently_unlocked_for_goal_funding(pos) is False


# ============================================================================
# 2) Integration: _load_allocation_inputs() end-to-end gegen SQLite
# ============================================================================


def test_locked_pension_position_does_not_reduce_reserve_pool(session_factory):
    """Audit-Repro: eine CHF 80'000 Vorsorge-Position (Alter 63, noch nicht
    erreicht), is_available_for_goal_funding=1, darf den Schloss-Pool
    (unlocked_other_assets_rappen) NICHT erhoehen."""
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"pension-lock-{uuid.uuid4().hex[:8]}",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        session.add(WealthPosition(
            id=f"pos-pension-locked-{uuid.uuid4().hex[:8]}",
            client_id=client_id,
            label="Säule 3a (Kapitalbezug ab 63)",
            position_type="Vorsorge",
            assignment="Anderes Vermögen",
            current_value_rappen=80_000_00,
            currency="CHF",
            pension_type="Säule 3a",
            pension_retirement_age=63,
            is_available_for_goal_funding=1,
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        session.flush()
        with_locked_pension = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    assert (
        with_locked_pension["unlocked_other_assets_rappen"]
        == baseline["unlocked_other_assets_rappen"]
    ), "gesperrtes Vorsorgekapital darf den Schloss-Pool nicht erhoehen"


def test_unlocked_pension_position_with_reached_availability_reduces_reserve_pool(session_factory):
    """Gegenprobe: dieselbe Position, aber mit einem bereits erreichten
    liquidity_available_from -- jetzt MUSS sie den Schloss-Pool erhoehen."""
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"pension-unlocked-{uuid.uuid4().hex[:8]}",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        session.add(WealthPosition(
            id=f"pos-pension-unlocked-{uuid.uuid4().hex[:8]}",
            client_id=client_id,
            label="Säule 3a (bereits bezogen)",
            position_type="Vorsorge",
            assignment="Anderes Vermögen",
            current_value_rappen=80_000_00,
            currency="CHF",
            pension_type="Säule 3a",
            pension_retirement_age=63,
            liquidity_available_from=(date.today() - timedelta(days=1)).isoformat(),
            is_available_for_goal_funding=1,
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        session.flush()
        with_unlocked_pension = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    delta = (
        with_unlocked_pension["unlocked_other_assets_rappen"]
        - baseline["unlocked_other_assets_rappen"]
    )
    assert delta == 80_000_00


def test_plain_liquid_other_assets_position_still_unlocked_end_to_end(session_factory):
    """Regressionsschutz End-to-End: eine gewoehnliche liquide 'Anderes
    Vermoegen'-Position ohne Vorsorge-Merkmale reduziert die externe Reserve
    weiterhin wie vor PENSION-AVAILABILITY-001."""
    advisor_id, client_id, mandate_id, _aid, _gid = _seed_realistic_mandate(
        session_factory, suffix=f"liquid-unlocked-{uuid.uuid4().hex[:8]}",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

        session.add(WealthPosition(
            id=f"pos-liquid-unlocked-{uuid.uuid4().hex[:8]}",
            client_id=client_id,
            label="Sparkonto (frei verfuegbar)",
            position_type="Liquidität",
            assignment="Anderes Vermögen",
            current_value_rappen=80_000_00,
            currency="CHF",
            is_available_for_goal_funding=1,
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        ))
        session.flush()
        with_liquid = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    delta = (
        with_liquid["unlocked_other_assets_rappen"]
        - baseline["unlocked_other_assets_rappen"]
    )
    assert delta == 80_000_00
