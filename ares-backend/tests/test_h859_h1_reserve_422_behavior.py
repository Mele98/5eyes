"""#859 H-1 (Dok. 86, Pruefrunde #859 Delta): Verhaltenstest fuer die
Herkunftsangabe im stochastischen Reserve-Fall.

Bisher war ein Quelltext-Anker (``name_source_always=True``) der einzige
Waechter. Hier: stochastischer Modus, zwei fixierte Berater-Ziele, die
Zielreserve (2.01 %) als Liquiditaets-Untergrenze hebt die Summe ueber 100 %
-> 422 nennt "(zwingend vorzuhaltende Zielreserve)". Das gilt auch, wenn das
Liquiditaets-Minimum schon vorher auf Reservehoehe lag (Berater-Minimum
2.01 %), die Untergrenze also nichts mehr anhebt.
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
from test_audit_2026_11_h859_2_locked_targets_infeasible import _error  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate, session_factory  # noqa: F401,E402

LOCKED = {"equities": {"target_bps": 7500}, "bonds": {"target_bps": 1500}}


def _seed(session_factory, monkeypatch, suffix):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    return _seed_realistic_mandate(session_factory, suffix=suffix)


def test_stochastic_reserve_floor_422_names_reserve(session_factory, monkeypatch):
    adv, _cid, mid, _aid = _seed(session_factory, monkeypatch, "h1res")
    msg = _error(session_factory, mid, adv, {"bands": dict(LOCKED)})
    assert "fixierten Berater-Ziele (Aktien 75.00 %, Obligationen 15.00 %)" in msg, msg
    assert "Liquiditaet 2.01 % (zwingend vorzuhaltende Zielreserve)" in msg, msg
    assert "100.01 %" in msg, msg


def test_reserve_named_even_if_minimum_already_at_reserve_level(session_factory, monkeypatch):
    """Vorbedingung "Minimum lag schon auf Reservehoehe" ist mit dem
    Seed-Mandat nicht ueber Bandbreiten herstellbar (Haus-Maximum Liquiditaet
    2.00 % < Reserve 2.01 %). Deshalb wird sie unmittelbar vor dem echten
    Reserve-Schritt der Engine gesetzt; Engine-Argumente und
    ``raise_liquidity_floor`` laufen unveraendert."""
    real = pe.raise_liquidity_floor
    seen: list[int] = []

    def _minimum_already_at_floor(targets, preferred, minimums, maximums, locked, **kwargs):
        if kwargs.get("source") == "zwingend vorzuhaltende Zielreserve":
            minimums["liquidity"] = max(int(minimums["liquidity"]), int(kwargs["floor_bps"]))
            seen.append(int(kwargs["floor_bps"]))
        return real(targets, preferred, minimums, maximums, locked, **kwargs)

    monkeypatch.setattr(pe, "raise_liquidity_floor", _minimum_already_at_floor)
    adv, _cid, mid, _aid = _seed(session_factory, monkeypatch, "h1pre")
    msg = _error(session_factory, mid, adv, {"bands": dict(LOCKED)})
    assert seen == [201], seen
    assert "Liquiditaet 2.01 % (zwingend vorzuhaltende Zielreserve)" in msg, msg
