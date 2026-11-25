"""AUDIT-2026-11 A5: unerfuellbare Maxima ergaben einen englischen internen Fehler.

Befund (Audit 01, A5): ``_raise_if_band_envelope_infeasible`` prueft bewusst
nur die Summe der Minima (die Liquiditaets-Obergrenze kann spaeter noch
angehoben werden). Aktien Min 0 / Max 20 % fuehrte darum erst in
``_rebalance_to_total`` zu ``ValueError: Target allocation cannot be
normalized to 10000 bps within min/max bounds (total=7700, targets={...})``
und im Router zu 409.

Fix: ``BandEnvelopeInfeasibleError`` (Unterklasse von ValueError) mit
deutscher Meldung, die jede Obergrenze nennt; der Generate-Router
antwortet 422.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import routers.allocation as allocation_router  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from services.portfolio_engine_house_matrix import (  # noqa: E402
    BandEnvelopeInfeasibleError,
    _rebalance_to_total,
)
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

PREFS = {"bands": {"equities": {"min_bps": 0, "max_bps": 2000}}}


def _assert_german_maxima_message(msg: str) -> None:
    assert "cannot be normalized" not in msg, msg
    assert "targets=" not in msg, msg
    # Hausmatrix-Modus seit E-1: Liquiditaets-Maximum auf die Zielreserve
    # 2.01 % angehoben -> 77.01 %; stochastisch 77.00 %.
    assert ("Hoechstquoten lassen zusammen nur 77.00 %" in msg
            or "Hoechstquoten lassen zusammen nur 77.01 %" in msg), msg
    assert "Aktien max. 20.00 %" in msg, msg
    assert "Obligationen max. 25.00 %" in msg, msg
    assert "100 %" in msg, msg


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_infeasible_maxima_raise_german_envelope_error(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"a5{mode[:3]}")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
            pe.generate_target_allocation(s, mandate, adv, PREFS)
        s.rollback()
    _assert_german_maxima_message(str(exc_info.value))


def test_unit_minima_over_100_are_german_too():
    bounds = {"equities": 6000, "bonds": 3000, "real_estate": 1000, "alternatives": 500, "liquidity": 0}
    with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
        _rebalance_to_total(dict(bounds), bounds, {k: 10000 for k in bounds})
    msg = str(exc_info.value)
    assert "Mindestquoten verlangen zusammen 105.00 %" in msg, msg
    assert "Aktien min. 60.00 %" in msg, msg


def test_generate_router_maps_envelope_error_to_422(monkeypatch):
    message = "Die Hoechstquoten lassen zusammen nur 77.00 % zu (Aktien max. 20.00 %)."

    def _raise(**_kwargs):
        raise BandEnvelopeInfeasibleError(message)

    monkeypatch.setattr(allocation_router, "_admit_solver_slot", contextlib.nullcontext)
    monkeypatch.setattr(allocation_router, "_get_mandate_or_404", lambda *a, **k: SimpleNamespace(id="m"))
    # E2b/N-888-02: die Untergrenze der Nachhaltigkeitspraeferenz liest die DB;
    # hier ein Fake (keine Erfassung = keine Wirkung), aufgerufen VOR der Engine.
    floor_calls = []
    monkeypatch.setattr(
        allocation_router, "assert_sustainability_preference_floor",
        lambda db, mandate, preferences=None, **kw: floor_calls.append(kw.get("channel")) or {"status": "none"},
    )
    monkeypatch.setattr(allocation_router, "generate_target_allocation", _raise)
    monkeypatch.setattr(allocation_router.settings, "require_suitability_before_recommendation", False)
    with pytest.raises(HTTPException) as exc_info:
        allocation_router.generate_target_allocation_endpoint(
            mandate_id="m",
            body=SimpleNamespace(preferences=None),
            request=SimpleNamespace(),
            db=SimpleNamespace(),
            current_user=SimpleNamespace(id="u", full_name="U"),
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == message


def test_other_value_errors_stay_409(monkeypatch):
    def _raise(**_kwargs):
        raise ValueError("Bandbreiten fuer Aktien sind inkonsistent")

    monkeypatch.setattr(allocation_router, "_admit_solver_slot", contextlib.nullcontext)
    monkeypatch.setattr(allocation_router, "_get_mandate_or_404", lambda *a, **k: SimpleNamespace(id="m"))
    # E2b/N-888-02: die Untergrenze der Nachhaltigkeitspraeferenz liest die DB;
    # hier ein Fake (keine Erfassung = keine Wirkung), aufgerufen VOR der Engine.
    floor_calls = []
    monkeypatch.setattr(
        allocation_router, "assert_sustainability_preference_floor",
        lambda db, mandate, preferences=None, **kw: floor_calls.append(kw.get("channel")) or {"status": "none"},
    )
    monkeypatch.setattr(allocation_router, "generate_target_allocation", _raise)
    monkeypatch.setattr(allocation_router.settings, "require_suitability_before_recommendation", False)
    with pytest.raises(HTTPException) as exc_info:
        allocation_router.generate_target_allocation_endpoint(
            mandate_id="m",
            body=SimpleNamespace(preferences=None),
            request=SimpleNamespace(),
            db=SimpleNamespace(),
            current_user=SimpleNamespace(id="u", full_name="U"),
        )
    assert exc_info.value.status_code == 409
