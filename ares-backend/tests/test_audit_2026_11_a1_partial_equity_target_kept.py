"""AUDIT-2026-11 A1: ein Aktien-Teilziel ueber der Hausquote wurde still
auf die Hausquote zurueckgeschnitten.

Befund (Audit 01, Asset Allocation): ``_rebalance_to_total`` nahm einen
Ueberschuss ueber 10000 bps immer zuerst aus Aktien. Setzt der Berater nur
``bands.equities.target_bps = 7000`` (Hausband 60-75 %, Hausquote 68 %),
ergab sich 7000 + 1600 + 800 + 600 + 200 = 10200; die 200 bps kamen wieder
aus Aktien, Ergebnis 6800 -- in beiden Modi, ohne Hinweis. Ein Ziel UNTER
der Hausquote wirkte dagegen exakt, weil ein Unterschuss zuerst bei
Obligationen aufgefuellt wurde. Bei 7500 stiegen Obligationen im
stochastischen Modus sogar (1662 statt 1600).

Gemessen vor dem Fix (Testmandat, Score 8):
- Hausmatrix-Modus: 6200 -> 6200, 6900 -> 6800, 7000 -> 6800, 7500 -> 6800
- stochastisch:     6200 -> 6199, 6900 -> 6799, 7000 -> 6799,
                    7500 -> 6905 (Obligationen 1662)

Fix: explizit gesetzte Ziele sind in der Summen-Projektion fixiert; der
Ausgleich kommt anteilig aus den uebrigen Klassen. Muss eine fixierte
Klasse dennoch bewegt werden (wirksame Grenze, z. B. globale
Liquiditaets-Untergrenze), wird das als ``WARN_TARGET_ADJUSTED`` und im
Reasoning ausgewiesen.
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
from services.portfolio_engine_house_matrix import (  # noqa: E402
    _rebalance_to_total,
    disclose_manual_target_deviations,
)
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

HOUSE_TARGETS = {"equities": 6800, "bonds": 1600, "real_estate": 800, "alternatives": 600, "liquidity": 200}
HOUSE_MIN = {"equities": 6000, "bonds": 1000, "real_estate": 500, "alternatives": 300, "liquidity": 0}
HOUSE_MAX = {"equities": 7500, "bonds": 2500, "real_estate": 2000, "alternatives": 1000, "liquidity": 200}
CODE = "WARN_TARGET_ADJUSTED"


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def _codes(result) -> list[str]:
    return [w.get("code") for w in result["warnings"] if isinstance(w, dict)]


# --------------------------------------------------------------------------
# Einheit: _rebalance_to_total
# --------------------------------------------------------------------------


@pytest.mark.parametrize("target", [6200, 6900, 7000, 7500])
def test_locked_equity_target_survives_rebalance(target):
    seed = {**HOUSE_TARGETS, "equities": target}
    result = _rebalance_to_total(seed, HOUSE_MIN, HOUSE_MAX, locked={"equities"})
    assert sum(result.values()) == 10000
    assert result["equities"] == target
    for bucket in ("bonds", "real_estate", "alternatives"):
        if target > HOUSE_TARGETS["equities"]:
            assert result[bucket] <= HOUSE_TARGETS[bucket], (bucket, result)
        else:
            assert result[bucket] >= HOUSE_TARGETS[bucket], (bucket, result)
    assert result["liquidity"] == HOUSE_TARGETS["liquidity"]


def test_unlocked_rebalance_is_unchanged():
    """Ohne explizites Ziel bleibt die bisherige Reihenfolge-Logik bitgleich."""
    seed = {**HOUSE_TARGETS, "equities": 7000}
    assert _rebalance_to_total(seed, HOUSE_MIN, HOUSE_MAX) == HOUSE_TARGETS


def test_locked_bucket_moves_only_when_others_are_pinned_and_is_disclosed():
    minimums = {**HOUSE_MIN, "bonds": 1600, "real_estate": 800, "alternatives": 600, "liquidity": 200}
    seed = {**HOUSE_TARGETS, "equities": 7000}
    result = _rebalance_to_total(seed, minimums, HOUSE_MAX, locked={"equities"})
    assert result["equities"] == 6800
    reasoning: list[str] = []
    warnings: list = []
    disclose_manual_target_deviations(
        {"equities": 7000}, result, result, minimums, HOUSE_MAX, reasoning, warnings,
        bucket_labels=pe.BUCKET_LABELS,
    )
    assert [w["code"] for w in warnings] == [CODE]
    assert "70.00 %" in warnings[0]["body_advisor"]
    assert "68.00 %" in warnings[0]["body_advisor"]
    assert any("Berater-Ziel von 70.00 %" in line for line in reasoning)


# --------------------------------------------------------------------------
# Integration: generate_target_allocation, beide Modi
# --------------------------------------------------------------------------


@pytest.mark.parametrize("target", [6200, 6900, 7000, 7500])
def test_house_matrix_mode_keeps_partial_equity_target(session_factory, monkeypatch, target):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"a1h{target}")
    result = _generate(session_factory, mid, adv, {"bands": {"equities": {"target_bps": target}}})
    ta = result["target_allocation"]
    assert ta.target_equities_bps == target
    if target > HOUSE_TARGETS["equities"]:
        assert ta.target_bonds_bps <= HOUSE_TARGETS["bonds"]
    assert CODE not in _codes(result)


@pytest.mark.parametrize("target", [6900, 7500])
def test_stochastic_mode_keeps_partial_equity_target(session_factory, monkeypatch, target):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"a1s{target}")
    result = _generate(session_factory, mid, adv, {"bands": {"equities": {"target_bps": target}}})
    ta = result["target_allocation"]
    assert ta.optimization_status == "converged"
    assert abs(int(ta.target_equities_bps) - target) <= 5, ta.target_equities_bps
    # Obligationen steigen nicht gegenlaeufig (vorher 1662 bei Ziel 7500).
    assert ta.target_bonds_bps <= HOUSE_TARGETS["bonds"]
    assert CODE not in _codes(result)


def test_stochastic_liquidity_target_below_global_floor_is_capped_visibly(session_factory, monkeypatch):
    """Liquiditaets-Ziel 1 % liegt im Hausband (0-2 %), aber unter der
    globalen Modell-Untergrenze von 2 % -- es wird auf den Bandrand
    gekappt, sichtbar statt still."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="a1liq")
    result = _generate(session_factory, mid, adv, {"bands": {"liquidity": {"target_bps": 100}}})
    ta = result["target_allocation"]
    assert ta.target_liquidity_bps >= 200
    assert CODE in _codes(result)
    assert any("Berater-Ziel von 1.00 %" in line for line in result["reasoning"])


# --------------------------------------------------------------------------
# H-859-1 (Pruefrunde #859, Art. 8 FIDLEG): die Warnung nennt die
# GESPEICHERTE Quote, nicht den Anker vor dem Optimierer.
# --------------------------------------------------------------------------


def test_target_adjusted_warning_names_persisted_quote_stochastic(session_factory, monkeypatch):
    """Pruefrunde #859: Aktien 75 % + Obligationen 25 % (mit den Minima der
    uebrigen Klassen ueber 100 %). Vorher nannte die Warnung den Anker
    (64.99 %), gespeichert wurden 66.24 %."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="h1sto")
    prefs = {"bands": {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 2500}}}
    result = _generate(session_factory, mid, adv, prefs)
    ta = result["target_allocation"]
    by_label = {w["body_client"].split(" wird")[0]: w for w in result["warnings"] if w.get("code") == CODE}
    eq = by_label["Für Aktien"]
    persisted = f"{int(ta.target_equities_bps) / 100:.2f} %"
    assert persisted in eq["body_client"], (persisted, eq["body_client"])
    assert persisted in eq["body_advisor"], (persisted, eq["body_advisor"])


def test_disclosure_uses_final_quote_and_separates_optimizer_deviation():
    reasoning: list[str] = []
    warnings: list = []
    labels = pe.BUCKET_LABELS
    anchor = {**HOUSE_TARGETS, "equities": 6499}
    final = {**HOUSE_TARGETS, "equities": 6624}
    disclose_manual_target_deviations(
        {"equities": 7500}, anchor, final, HOUSE_MIN, HOUSE_MAX, reasoning, warnings,
        bucket_labels=labels,
    )
    assert "66.24 %" in warnings[0]["body_client"] and "64.99" not in warnings[0]["body_client"]
    # Nur der Optimierer weicht ab (Anker == Ziel): keine Kappungs-Warnung,
    # aber ein Reasoning-Satz mit der Abweichung.
    reasoning, warnings = [], []
    disclose_manual_target_deviations(
        {"equities": 7000}, {**HOUSE_TARGETS, "equities": 7000}, {**HOUSE_TARGETS, "equities": 6997},
        HOUSE_MIN, HOUSE_MAX, reasoning, warnings, bucket_labels=labels,
        optimizer_applied=True,
    )
    assert warnings == []
    assert any("-3 bps" in line for line in reasoning), reasoning


# --------------------------------------------------------------------------
# H-859-3: Risikobudget-Fallback setzt ein Berater-Ziel auf die Bandmitte
# zurueck -- das braucht einen eigenen, klaren Hinweis.
# --------------------------------------------------------------------------

FALLBACK_CODE = "WARN_TARGET_FALLBACK_RESET"


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_fallback_reset_of_advisor_target_is_disclosed(session_factory, monkeypatch, mode):
    from services.risk_matrix import RiskBudgetExceeded

    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    real_assert = pe.assert_risk_budget_ok
    calls = {"n": 0}

    def _first_call_exceeds(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RiskBudgetExceeded(args[0], args[1])
        return real_assert(*args, **kwargs)

    monkeypatch.setattr(pe, "assert_risk_budget_ok", _first_call_exceeds)
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix=f"h3{mode[:3]}")
    prefs = {"bands": {"equities": {"target_bps": 7200}, "bonds": {"max_bps": 1300}}}
    result = _generate(session_factory, mid, adv, prefs)
    ta = result["target_allocation"]
    assert "WARN_FALLBACK" in _codes(result)
    assert ta.target_equities_bps != 7200
    assert ta.target_bonds_bps <= 1300  # Berater-Max bleibt (Fix 3.8.)
    resets = [w for w in result["warnings"] if w.get("code") == FALLBACK_CODE]
    assert len(resets) == 1, result["warnings"]
    body = resets[0]["body_advisor"]
    persisted = f"{int(ta.target_equities_bps) / 100:.2f} %"
    assert "Aktien" in body and "72.00 %" in body and persisted in body, body
    assert "Risikobudget" in body, body
    assert CODE not in _codes(result)  # keine irrefuehrende Kappungs-Meldung
    assert any("72.00 %" in r and "Risikobudget" in r for r in result["reasoning"])
