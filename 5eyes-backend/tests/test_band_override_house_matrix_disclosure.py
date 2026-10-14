"""BAND-OVERRIDE-DISCLOSURE-001 (Audit 2026-10-14, F-BAND-1/2/3).

F-BAND-1: ``_apply_band_preferences`` schrieb Berater-Min/Max ungeprueft
ueber die Hausmatrix-Bandbreite des Risikoprofils. Ein wachstumsorientierter
Kunde (Hausmatrix Aktien 60-75 %) mit Berater-Band Aktien 76-85 % / Ziel 80 %
wurde stochastisch mit 80 % Aktien publiziert -- ``warnings == []`` und keine
Reasoning-Zeile, die den Austritt aus dem Eignungsrahmen benennt. Der
Policy-Cap-Pfad weist dagegen jede Bandverschiebung aus
(``policy_band_clamp_notes``). Die Abweichung bleibt ERLAUBT (Produktregel:
die Hausmatrix ist der Eignungsrahmen, die Mandatsbandbreite darf ihn
verlassen) -- sie muss aber offengelegt werden, im Generate-Lauf UND im
Freigabe-Gate.

F-BAND-2: die globale Alternative-Obergrenze (10 %) klemmte ein Berater-
Maximum/-Ziel von 30 % lautlos auf 10 %.

F-BAND-3: unerfuellbare Restriktionen scheitern zu Recht (fail-closed),
aber mit internem englischem Text ("cannot be normalized ... targets={...}")
bzw. "Min 500 / Max 0", obwohl die 500 das Hausmatrix-Minimum ist, das der
Berater nie gesetzt hat.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from database import new_uuid  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

BAND_CODE = "WARN_BAND_OUTSIDE_HOUSE_MATRIX"
CAP_CODE = "WARN_GLOBAL_CAP_CLAMP"


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def _generate_error(SF, mid, adv, prefs) -> Exception:
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(ValueError) as exc_info:
            pe.generate_target_allocation(s, mandate, adv, prefs)
        s.rollback()
        return exc_info.value


def _codes(result) -> list[str]:
    return [w.get("code") for w in result["warnings"] if isinstance(w, dict)]


@pytest.fixture()
def stochastic(monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")


# --------------------------------------------------------------------------
# F-BAND-1
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["stochastic", "house_matrix"])
def test_advisor_band_above_house_band_is_disclosed(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, f"bo-{mode}")
    prefs = {"bands": {"equities": {"min_bps": 7600, "max_bps": 8500, "target_bps": 8000}}}

    result = _generate(session_factory, mid, adv, prefs)

    assert result["house_matrix_profile"] == "Wachstumsorientiert"
    band_warnings = [w for w in result["warnings"] if isinstance(w, dict) and w.get("code") == BAND_CODE]
    assert len(band_warnings) == 1, result["warnings"]
    body = band_warnings[0]["body_advisor"]
    for needle in ("Aktien", "76.00", "85.00", "60.00", "75.00", "Wachstumsorientiert"):
        assert needle in body, body
    lines = [r for r in result["reasoning"] if "Hausmatrix-Bandbreite" in r and "Aktien" in r]
    assert lines, result["reasoning"]
    line = lines[0]
    for needle in ("Score", "Wachstumsorientiert", "60.00", "75.00", "76.00", "85.00"):
        assert needle in line, line


def test_advisor_band_inside_house_band_is_not_flagged(session_factory, stochastic):
    """Negativkontrolle: eine Verengung INNERHALB des Hausbands ist kein
    Austritt aus dem Eignungsrahmen und darf nicht als solcher markiert
    werden."""
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "bi")
    prefs = {"bands": {"equities": {"min_bps": 6200, "max_bps": 7000}}}

    result = _generate(session_factory, mid, adv, prefs)

    assert BAND_CODE not in _codes(result), result["warnings"]
    assert not [r for r in result["reasoning"] if "Hausmatrix-Bandbreite" in r], result["reasoning"]


def test_finalization_gate_warns_on_band_outside_house_matrix(session_factory):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "gate")
    prefs = {"bands": {"equities": {"min_bps": 7600, "max_bps": 8500}}}
    _generate(session_factory, mid, adv, prefs)
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        errors, warnings = _validate_recommendation_for_finalization(db, mandate, run)

    flagged = [w for w in warnings if "Hausmatrix" in w and "Aktien" in w]
    assert flagged, (errors, warnings)
    assert "76.00" in flagged[0] and "75.00" in flagged[0], flagged
    # Warnung, KEIN neuer Blocker: keine Fehlermeldung nennt die Hausmatrix.
    assert not [e for e in errors if "Hausmatrix" in e], errors


def test_finalization_gate_silent_without_band_deviation(session_factory):
    adv, _cid, mid, aid = _seed_realistic_mandate(session_factory, "gate-ok")
    _generate(session_factory, mid, adv, None)
    run_id = _draft_run_with_position(session_factory, mid, aid, adv)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).one()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        _errors, warnings = _validate_recommendation_for_finalization(db, mandate, run)

    assert not [w for w in warnings if "Hausmatrix" in w], warnings


def _draft_run_with_position(SF, mid, aid, adv) -> str:
    from models.allocation import TargetAllocation

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    rid = new_uuid()
    pid = new_uuid()
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        alloc = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1,
        ).one()
        s.add(RecommendationRun(
            id=rid, mandate_id=mid, client_id=mandate.client_id,
            assessment_id=aid, target_allocation_id=alloc.id,
            policy_id=alloc.policy_id,
            capital_market_assumptions_id=alloc.capital_market_assumptions_id,
            run_type="Optimizer", result_status="Draft",
            created_by=adv, created_at=now, updated_at=now,
        ))
        s.add(Product(
            id=pid, product_name="Test ETF", provider="X",
            product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Welt",
            currency="CHF", ter_bps=20, sfdr_class="6",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=rid, product_id=pid,
            target_weight_bps=10000, target_amount_rappen=500_000_00,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return rid


# --------------------------------------------------------------------------
# F-BAND-2
# --------------------------------------------------------------------------


def test_global_alternatives_cap_clamp_is_disclosed(session_factory, stochastic):
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "cap")
    prefs = {
        "bands": {"alternatives": {"max_bps": 3000, "target_bps": 3000}},
        "assetClasses": {"altsCrypto": True},
    }

    result = _generate(session_factory, mid, adv, prefs)

    assert result["target_allocation"].target_alternatives_bps <= 1000
    cap_warnings = [w for w in result["warnings"] if isinstance(w, dict) and w.get("code") == CAP_CODE]
    assert len(cap_warnings) == 1, result["warnings"]
    for needle in ("Alternative", "30.00", "10.00"):
        assert needle in cap_warnings[0]["body_advisor"], cap_warnings[0]
    lines = [r for r in result["reasoning"] if "globale" in r.lower() and "Alternative" in r]
    assert lines and "30.00" in lines[0] and "10.00" in lines[0], result["reasoning"]


def test_no_cap_disclosure_when_house_band_is_within_global_cap(session_factory, stochastic):
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "cap-ok")
    result = _generate(session_factory, mid, adv, None)
    assert CAP_CODE not in _codes(result), result["warnings"]


# --------------------------------------------------------------------------
# F-BAND-3
# --------------------------------------------------------------------------


def test_sum_of_minimums_over_100_names_buckets_in_german(session_factory, stochastic):
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "inf")
    exc = _generate_error(
        session_factory, mid, adv, {"bands": {"equities": {"min_bps": 8500, "max_bps": 9000}}},
    )
    msg = str(exc)
    assert "cannot be normalized" not in msg, msg
    assert "Mindestquoten summieren sich auf" in msg, msg
    assert "Aktien 85.00 % (Berater-Vorgabe)" in msg, msg
    assert "Hausmatrix-Minimum" in msg, msg
    assert "100 %" in msg, msg


def test_max_below_house_minimum_names_house_minimum(session_factory, stochastic):
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, "re0")
    exc = _generate_error(session_factory, mid, adv, {"bands": {"real_estate": {"max_bps": 0}}})
    msg = str(exc)
    assert "Hausmatrix-Minimum" in msg, msg
    assert "Immobilien" in msg and "0.00 %" in msg, msg
    assert "Berater-Maximum" in msg, msg


def test_router_still_maps_infeasible_restrictions_to_409():
    """Exception-Typ unveraendert: der Router mappt ValueError auf 409."""
    import inspect

    import routers.allocation as allocation_router

    source = inspect.getsource(allocation_router)
    assert "except ValueError as exc" in source and "status_code=409" in source
