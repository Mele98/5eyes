"""Live-Test 04 / M2: das Engine-eigene Liquiditaetsband verletzte die
Hausmatrix und erzwang im Bandbreiten-Editor eine Pflicht-Begruendung.

Befund: Ohne jede Berater-Eingabe persistiert die stochastische Engine ein
Liquiditaetsband auf Floor + interner Reserve (Testmandat Score 8:
201/201 bps; Live-Test Profil 5: 3.2/3.2 %). ``house_matrix_bands`` -- die
Vergleichsbasis des Editors -- lieferte die rohe Hausmatrix-Bandbreite
(0-2 % bzw. 0-3 %). Der Editor fuellt seine Felder mit dem gespeicherten
Band und meldet dann "Abweichung vom Eignungsrahmen ... Liquiditaet
ausserhalb Hausmatrix" mit "Ohne dokumentierte Begruendung ist die Freigabe
der Empfehlung blockiert."

Fix (Entscheid AA-7.2, nur so weit fuer die Konsistenz noetig): das
Liquiditaets-Eignungsband ist [Hausmin; max(Hausmax; Floor + Reserve)].
Eine systembedingte Anhebung ist kein Austritt aus der Hausmatrix.
Berater-Abweichungen bleiben unveraendert begruendungspflichtig.
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

BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def _editor_deviations(ta, house_bands) -> list[str]:
    """Spiegelt bandHouseDeviationsFromModal() (ares.html): Editor-Felder =
    gespeichertes Band, Abweichung wenn min < Hausmin oder max > Hausmax."""
    out = []
    for bucket in BUCKETS:
        mn = int(getattr(ta, f"band_{bucket}_min_bps"))
        mx = int(getattr(ta, f"band_{bucket}_max_bps"))
        hb = house_bands[bucket]
        if mn < int(hb["min_bps"]) or mx > int(hb["max_bps"]):
            out.append(f"{bucket} {mn}-{mx} vs {hb['min_bps']}-{hb['max_bps']}")
    return out


@pytest.mark.parametrize("mode", ["stochastic", "house_matrix"])
def test_engine_band_without_advisor_input_never_requires_reason(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"m2{mode[:3]}")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, None)
        s.commit()
        ta = result["target_allocation"]
        assert _editor_deviations(ta, result["house_matrix_bands"]) == []
        # Payload der gespeicherten Allokation (Reload/Review) ebenso.
        policy = result["policy"]
        cma = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == ta.capital_market_assumptions_id
        ).one()
        payload = pe.build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=ta, policy=policy, cma=cma,
            assessment=result["risk_assessment"], preferences=None,
        )
        assert _editor_deviations(ta, payload["house_matrix_bands"]) == []
        # Das Freigabe-Gate sieht ohnehin nur Berater-Baender.
        from services.portfolio_engine_house_matrix import house_band_deviation_disclosure_for_allocation

        disclosure = house_band_deviation_disclosure_for_allocation(s, ta, result["risk_assessment"], policy)
        assert disclosure["deviations"] == []


def test_advisor_liquidity_band_outside_house_still_counts(session_factory, monkeypatch):
    """Die Erweiterung gilt nur fuer die systembedingte Anhebung: ein
    Berater-Minimum von 5 % Liquiditaet (Hausmax 2 %) bleibt eine
    begruendungspflichtige Abweichung."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="m2adv")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(
            s, mandate, adv, {"bands": {"liquidity": {"min_bps": 500, "max_bps": 500}}},
        )
        s.commit()
    assert int(result["house_matrix_bands"]["liquidity"]["max_bps"]) < 500
    assert any("liquidity" in d for d in _editor_deviations(result["target_allocation"], result["house_matrix_bands"]))
    assert "WARN_BAND_OUTSIDE_HOUSE_MATRIX" in [w.get("code") for w in result["warnings"]]
