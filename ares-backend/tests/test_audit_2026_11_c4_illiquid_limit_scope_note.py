"""AUDIT-2026-11 C4: ``limits.maxIlliquid`` deckelt nur Private Equity -- ohne Hinweis.

Befund (Audit 01, C4): ``maxIlliquid=0`` liess die SAA unveraendert
(Alternative 5.92 % stochastisch). Das ist Absicht (Referenzmethodik:
maxIlliquid = nur PE), fuer den Berater aber nicht ersichtlich -- "illiquid
0 %" liest sich wie "keine Alternativen". Verhalten bleibt; das Reasoning
nennt jetzt den Wirkungsbereich.
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

NOTE = "begrenzt nur Private Equity"


def _generate(SF, mid, adv, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        result = pe.generate_target_allocation(s, mandate, adv, prefs)
        s.commit()
        return result


def _buckets(ta):
    return (ta.target_equities_bps, ta.target_bonds_bps, ta.target_real_estate_bps,
            ta.target_alternatives_bps, ta.target_liquidity_bps)


def test_max_illiquid_zero_keeps_saa_and_explains_scope(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    adv, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="c4")
    base = _generate(session_factory, mid, adv, None)
    capped = _generate(session_factory, mid, adv, {"limits": {"maxIlliquid": "0"}})
    # Verhalten unveraendert: die Alternative-Quote bleibt (nur PE wird gedeckelt).
    assert _buckets(capped["target_allocation"]) == _buckets(base["target_allocation"])
    assert not any(NOTE in line for line in base["reasoning"])
    notes = [line for line in capped["reasoning"] if NOTE in line]
    assert len(notes) == 1, capped["reasoning"]
    assert "0.00 %" in notes[0]
    assert "Alternative-Quote insgesamt" in notes[0]
