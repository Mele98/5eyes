"""Live-Test 04 / M3: Bandbreiten ausserhalb der Hausmatrix wurden gerechnet
und ohne sichtbaren Hinweis ausgegeben.

Befund: Aktien 60-70 % bei Profil 5 (Hausmatrix 40-55 %) ohne Begruendung
-> Generate 200, Torte und Tabelle ohne Hinweis. Die Engine legte die
Abweichung nur in ``warnings`` ab (WARN_BAND_OUTSIDE_HOUSE_MATRIX); die
Banner der AA- und Review-Maske lesen aber ausschliesslich ``messages``
(ares.html renderAllocationMessageBanner / Review-Banner). Die
Freigabesperre existiert (routers/review.py, fail-closed, siehe
test_band_deviation_reason_required.py), war fuer den Berater aber erst
beim Freigeben sichtbar.

Fix: die Abweichung steht auch in ``messages`` (persistiert, also auch beim
Reload); fehlt eine tragfaehige Begruendung, kommt
CONFLICT_BAND_REASON_MISSING dazu (Konflikt -> Banner-Vorrang), das die
Freigabesperre ankuendigt. Mit dokumentierter Begruendung bleibt nur der
Hinweis.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401,E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import CapitalMarketAssumption  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

OUTSIDE_BANDS = {"equities": {"min_bps": 7600, "max_bps": 8500}}
INSIDE_BANDS = {"equities": {"min_bps": 6200, "max_bps": 7000}}
GOOD_REASON = (
    "Kundin haelt ausserhalb des Mandats erhebliche Immobilienwerte und "
    "wuenscht bewusst eine hoehere Aktienquote im Beratungsdepot."
)


def _generate_and_reload(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        ta = result["target_allocation"]
        cma = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == ta.capital_market_assumptions_id
        ).one()
        payload = pe.build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=ta, policy=result["policy"], cma=cma,
            assessment=result["risk_assessment"], preferences=None,
        )
    return result, payload


def _codes(messages):
    return [m.get("code") for m in messages if isinstance(m, dict)]


@pytest.mark.parametrize("mode", ["stochastic", "house_matrix"])
def test_band_outside_house_without_reason_is_a_visible_conflict(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"m3{mode[:3]}")
    result, payload = _generate_and_reload(session_factory, mid, adv, {"bands": OUTSIDE_BANDS})
    for messages in (result["messages"], payload["messages"]):
        codes = _codes(messages)
        assert "WARN_BAND_OUTSIDE_HOUSE_MATRIX" in codes, codes
        assert "CONFLICT_BAND_REASON_MISSING" in codes, codes
        conflict = [m for m in messages if m.get("code") == "CONFLICT_BAND_REASON_MISSING"][0]
        assert conflict["severity"] == "conflict"
        assert "Aktien" in conflict["body_advisor"] and "Freigabe" in conflict["body_advisor"]


def test_band_outside_house_with_documented_reason_keeps_only_the_notice(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="m3ok")
    result, _payload = _generate_and_reload(
        session_factory, mid, adv, {"bands": OUTSIDE_BANDS, "bandDeviationReason": GOOD_REASON},
    )
    codes = _codes(result["messages"])
    assert "WARN_BAND_OUTSIDE_HOUSE_MATRIX" in codes
    assert "CONFLICT_BAND_REASON_MISSING" not in codes


def test_band_inside_house_has_no_band_message(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="m3in")
    result, _payload = _generate_and_reload(session_factory, mid, adv, {"bands": INSIDE_BANDS})
    codes = _codes(result["messages"])
    assert "WARN_BAND_OUTSIDE_HOUSE_MATRIX" not in codes
    assert "CONFLICT_BAND_REASON_MISSING" not in codes
