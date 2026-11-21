"""H-859-4/-5 (Pruefrunde #859): Bandbreiten-Eingabefehler als deutsche 422.

Vorher:
- Ein Ziel ausserhalb der Bandbreite ergab "Bandbreiten fuer Aktien sind
  inkonsistent: Min 6000 / Ziel 8000 / Max 7500." -- rohe bps, ohne
  Herkunft der Grenze, als 409.
- Minima ueber 100 % ergaben eine deutsche Meldung, aber 409, waehrend
  unerfuellbare Maxima (A5) 422 ergaben. Beides sind Eingabefehler.

Nachher: ``AllocationInputError`` (Unterklasse von ValueError) fuer alle
Bandbreiten-Eingabefehler, mit Prozentwerten und Herkunft (Hausmatrix,
Mandats-Policy, Berater-Vorgabe); der Generate-Router antwortet einheitlich
422. Uebrige ValueError bleiben 409.
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
    AllocationInputError,
    BandEnvelopeInfeasibleError,
    _apply_band_preferences,
)
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

HOUSE_TARGETS = {"equities": 6800, "bonds": 1600, "real_estate": 800, "alternatives": 600, "liquidity": 200}
HOUSE_MIN = {"equities": 6000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 0}
HOUSE_MAX = {"equities": 7500, "bonds": 2500, "real_estate": 2000, "alternatives": 1000, "liquidity": 200}


def _apply(bands, *, policy_bound_keys=frozenset(), maximums=None):
    return _apply_band_preferences(
        bands, dict(HOUSE_TARGETS), dict(HOUSE_MIN), dict(maximums or HOUSE_MAX), [],
        house_profile="Wachstumsorientiert", score_bucket=8,
        policy_bound_keys=policy_bound_keys,
    )


def test_target_above_house_max_names_percent_and_source():
    with pytest.raises(AllocationInputError) as exc_info:
        _apply({"equities": {"target_bps": 8000}})
    msg = str(exc_info.value)
    assert "Berater-Ziel fuer Aktien von 80.00 %" in msg, msg
    assert "ueber dem Hausmatrix-Maximum von 75.00 %" in msg, msg
    assert "Score 8" in msg and "Wachstumsorientiert" in msg, msg
    assert "Maximum als Berater-Vorgabe mitsetzen" in msg, msg
    assert "8000" not in msg and "Min 6000" not in msg, msg


def test_target_below_advisor_min_names_advisor_as_source():
    with pytest.raises(AllocationInputError) as exc_info:
        _apply({"equities": {"min_bps": 6500, "target_bps": 6200}})
    msg = str(exc_info.value)
    assert "62.00 %" in msg and "unter dem Berater-Minimum von 65.00 %" in msg, msg


def test_target_above_policy_max_names_policy_as_source():
    maximums = {**HOUSE_MAX, "real_estate": 1500}
    with pytest.raises(AllocationInputError) as exc_info:
        _apply({"real_estate": {"target_bps": 1800}},
               policy_bound_keys=frozenset({("real_estate", "max")}), maximums=maximums)
    msg = str(exc_info.value)
    assert "ueber dem Maximum der Mandats-Policy von 15.00 %" in msg, msg


def test_minimums_over_100_are_envelope_errors_with_policy_source():
    with pytest.raises(BandEnvelopeInfeasibleError) as exc_info:
        _apply({"equities": {"min_bps": 8500, "max_bps": 9000}})
    msg = str(exc_info.value)
    assert "Mindestquoten summieren sich auf" in msg and "Aktien 85.00 % (Berater-Vorgabe)" in msg, msg


@pytest.mark.parametrize(
    "prefs",
    [
        {"bands": {"equities": {"target_bps": 8000}}},
        {"bands": {"equities": {"min_bps": 8500, "max_bps": 9000}}},
    ],
    ids=["target_outside_band", "minimums_over_100"],
)
def test_generate_raises_allocation_input_error(session_factory, monkeypatch, prefs):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="h45")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(AllocationInputError):
            pe.generate_target_allocation(s, mandate, adv, prefs)
        s.rollback()


def _call_generate_endpoint(monkeypatch, exc):
    def _raise(**_kwargs):
        raise exc

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
            mandate_id="m", body=SimpleNamespace(preferences=None), request=SimpleNamespace(),
            db=SimpleNamespace(), current_user=SimpleNamespace(id="u", full_name="U"),
        )
    return exc_info.value


@pytest.mark.parametrize(
    "exc",
    [
        AllocationInputError("Das Berater-Ziel fuer Aktien von 80.00 % liegt ueber ..."),
        BandEnvelopeInfeasibleError("Die Mindestquoten summieren sich auf 108.00 % ..."),
    ],
)
def test_generate_router_maps_all_band_input_errors_to_422(monkeypatch, exc):
    http_exc = _call_generate_endpoint(monkeypatch, exc)
    assert http_exc.status_code == 422
    assert http_exc.detail == str(exc)


def test_generate_router_keeps_409_for_other_value_errors(monkeypatch):
    assert _call_generate_endpoint(monkeypatch, ValueError("Zustandskonflikt")).status_code == 409
