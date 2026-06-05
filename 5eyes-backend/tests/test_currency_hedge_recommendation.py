"""Sprint U-98 (2026-06-05): Currency-Hedge-Vorschlag in Erkenntnisse.

Verifiziert
  - die Heuristik _suggest_hedge_ratio_bps liefert konservative Quoten je
    nach Horizont + FX-Groesse
  - die Erkenntnis _check_waehrungsabsicherung baut korrekt aus DepotCheck
    + RiskAssessment.investment_horizon_years
  - die Erkenntnisse-Liste enthaelt das neue Item ohne bestehende zu brechen
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.advisory_report import (
    _build_erkenntnisse,
    _check_waehrungsabsicherung,
    _suggest_hedge_ratio_bps,
)
from test_optimizer_shadow_mode import session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Heuristik-Tests
# ---------------------------------------------------------------------------

def test_no_fx_exposure_returns_zero():
    bps, _ = _suggest_hedge_ratio_bps(fx_total_bps=0, horizon_years=10)
    assert bps == 0


def test_tiny_fx_exposure_returns_zero():
    bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps=1000, horizon_years=5)
    assert bps == 0
    assert "wenig sinnvoll" in rationale


def test_short_horizon_high_hedge_ratio():
    bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps=3000, horizon_years=2)
    assert bps == 8000
    assert "Kurzer Horizont" in rationale


def test_medium_horizon_balanced_ratio():
    bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps=4000, horizon_years=5)
    assert bps == 5000
    assert "Mittelfristiger Horizont" in rationale


def test_long_horizon_partial_hedge():
    bps, _ = _suggest_hedge_ratio_bps(fx_total_bps=5000, horizon_years=10)
    assert bps == 2500


def test_very_long_horizon_no_hedge():
    bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps=6000, horizon_years=20)
    assert bps == 0
    assert "Sehr langer Horizont" in rationale


def test_no_horizon_uses_default_50():
    bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps=4000, horizon_years=None)
    assert bps == 5000
    assert "Default" in rationale or "konservativ" in rationale.lower()


def test_borderline_horizon_3_yr_uses_3_to_7_branch():
    """3 Jahre exakt -> mittelfristig (3-7) Branch, nicht <3."""
    bps, _ = _suggest_hedge_ratio_bps(fx_total_bps=3000, horizon_years=3)
    assert bps == 5000


def test_borderline_horizon_15_yr_uses_long_branch():
    """15 Jahre exakt -> 'Sehr lang' Branch (>=15)."""
    bps, _ = _suggest_hedge_ratio_bps(fx_total_bps=3000, horizon_years=15)
    assert bps == 0


# ---------------------------------------------------------------------------
# _check_waehrungsabsicherung Tests (ohne DB, mit stub-RA)
# ---------------------------------------------------------------------------

class _StubQuery:
    """Mini-Stub fuer db.query(RiskAssessment).filter(...).order_by(...).first()."""

    def __init__(self, result):
        self._result = result

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return self._result


class _StubDB:
    def __init__(self, ra=None):
        self._ra = ra

    def query(self, _model):
        return _StubQuery(self._ra)


def _mandate_stub(mid: str = "m-u98") -> SimpleNamespace:
    return SimpleNamespace(id=mid)


def test_check_with_no_currency_data_returns_nicht_beurteilbar():
    db = _StubDB()
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc={})
    assert out["pruefpunkt"] == "Waehrungsabsicherung"
    assert out["bewertung"] == "nicht_beurteilbar"


def test_check_with_only_chf_returns_gruen():
    db = _StubDB()
    dc = {"currency_exposure_bps": {"CHF": 10000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert out["bewertung"] == "gruen"
    assert "Keine Fremdwaehrungs" in out["beurteilung"]


def test_check_with_tiny_fx_returns_gruen():
    """FX < 15% -> kein Hedge noetig, gruen."""
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years=5))
    dc = {"currency_exposure_bps": {"CHF": 9000, "USD": 1000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert out["bewertung"] == "gruen"


def test_check_with_long_horizon_high_fx_returns_gelb():
    """20 J Horizont, 40% FX -> hedge_bps=0, aber FX gross -> gelb."""
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years=20))
    dc = {"currency_exposure_bps": {"CHF": 6000, "USD": 3000, "EUR": 1000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert out["bewertung"] == "gelb"  # hedge=0 aber FX nicht winzig
    assert "Hedge aktuell nicht empfohlen" in out["handlungsempfehlung"]


def test_check_with_short_horizon_high_fx_returns_rot():
    """2 J + 40% FX -> hedge 80% -> rot."""
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years=2))
    dc = {"currency_exposure_bps": {"CHF": 6000, "USD": 4000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert out["bewertung"] == "rot"
    assert "80%" in out["handlungsempfehlung"]


def test_check_with_medium_horizon_medium_fx_returns_gelb():
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years=5))
    dc = {"currency_exposure_bps": {"CHF": 7000, "USD": 2000, "EUR": 1000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert out["bewertung"] == "gelb"
    assert "50%" in out["handlungsempfehlung"]


def test_check_uses_advice_when_horizon_missing():
    """Kein RA -> Default-Quote 50%."""
    db = _StubDB(ra=None)
    dc = {"currency_exposure_bps": {"CHF": 5000, "USD": 3000, "EUR": 2000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert "50%" in out["handlungsempfehlung"]


def test_check_uses_advice_when_horizon_non_int():
    """RA mit kaputtem horizon -> Default."""
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years="not-an-int"))
    dc = {"currency_exposure_bps": {"CHF": 5000, "USD": 3000, "EUR": 2000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    assert "50%" in out["handlungsempfehlung"]


def test_check_no_drittmarken_no_garantie_in_text():
    """Branding-Disziplin: kein Drittmarken, kein 'garantiert'."""
    db = _StubDB(ra=SimpleNamespace(investment_horizon_years=5))
    dc = {"currency_exposure_bps": {"CHF": 5000, "USD": 3000, "EUR": 2000}}
    out = _check_waehrungsabsicherung(db, _mandate_stub(), dc)
    combined = (out["beurteilung"] + " " + out["handlungsempfehlung"]).lower()
    for forbidden in ("ubs", "pictet", "julius", "swiss life", "garantiert", "3eyes"):
        assert forbidden not in combined


# ---------------------------------------------------------------------------
# Build-Erkenntnisse Tests (stellt sicher dass das neue Item in der Liste ist)
# ---------------------------------------------------------------------------

def test_build_erkenntnisse_has_waehrungsabsicherung_item(session_factory):
    """Erkenntnisse-Liste muss das neue Item enthalten (nicht-beurteilbar reicht)."""
    from test_optimizer_shadow_mode import _seed_realistic_mandate
    from models.mandates import Mandate

    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u98")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_erkenntnisse(s, mandate, dc=None)
    pruefpunkte = [c["pruefpunkt"] for c in result["checks"]]
    assert "Waehrungsabsicherung" in pruefpunkte
    # Bestehende Items duerfen nicht weggefallen sein
    for legacy in ("Risikoprofil", "Asset Allocation", "Währungsstruktur",
                   "Liquidität", "Diversifikation"):
        assert legacy in pruefpunkte


def test_build_erkenntnisse_has_10_items_total(session_factory):
    """9 bestehende + 1 neues (U-98) = 10 Items."""
    from test_optimizer_shadow_mode import _seed_realistic_mandate
    from models.mandates import Mandate

    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u98count")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = _build_erkenntnisse(s, mandate, dc=None)
    assert len(result["checks"]) == 10
