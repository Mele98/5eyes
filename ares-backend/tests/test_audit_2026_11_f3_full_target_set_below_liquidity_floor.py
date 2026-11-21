"""F-3 (Pruefrunde #859): volles Zielset mit Liquiditaet unter der
Liquiditaets-Untergrenze.

Bisher ungetestet. Erwartet (in der Pruefrunde gemessen): keine 422,
sondern sichtbare Kappung -- die Liquiditaet steigt auf die Untergrenze
(Testmandat Score 8: Zielreserve 2.01 %, in beiden Modi seit E-1), die
uebrigen fixierten Ziele geben nach, jede Abweichung als
WARN_TARGET_ADJUSTED mit der gespeicherten Quote.
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
from models.mandates import Mandate  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

FULL_SET = {
    "bands": {
        "equities": {"target_bps": 6800},
        "bonds": {"target_bps": 1600},
        "real_estate": {"target_bps": 800},
        "alternatives": {"target_bps": 600},
        "liquidity": {"target_bps": 200},
    }
}


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_full_target_set_below_liquidity_floor_is_capped_visibly(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"f3{mode[:3]}")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, FULL_SET)  # keine 422
        s.commit()
    ta = result["target_allocation"]
    floor = int(ta.band_liquidity_min_bps)
    assert floor == 201
    assert int(ta.target_liquidity_bps) == floor
    adjusted = {
        w["body_advisor"].split(":")[0]: w
        for w in result["warnings"]
        if w.get("code") == "WARN_TARGET_ADJUSTED"
    }
    liq = adjusted.get("Liquiditaet")
    assert liq is not None, result["warnings"]
    assert "2.00 %" in liq["body_advisor"] and "2.01 %" in liq["body_client"]
    assert len(adjusted) >= 2  # mindestens ein weiteres fixiertes Ziel gibt nach
    for label, warning in adjusted.items():
        bucket = {v: k for k, v in pe.BUCKET_LABELS.items()}[label]
        persisted = f"{int(getattr(ta, f'target_{bucket}_bps')) / 100:.2f} %"
        assert persisted in warning["body_client"], (label, persisted, warning["body_client"])
