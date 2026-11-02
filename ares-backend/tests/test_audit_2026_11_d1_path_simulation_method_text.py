"""AUDIT-2026-11 D1: der Methodentext nannte "normalverteilte Jahresrenditen".

Befund (Audit 01, D1): ``generate_target_allocation`` und der Payload der
bestehenden Soll-Allokation schrieben unbedingt "Pfadsimulation mit
normalverteilten Jahresrenditen" ins kundensichtbare Reasoning. Gerechnet
wird lognormal, standardmaessig mit Cornish-Fisher-Korrektur der
CMA-Tail-Momente (``_simulation_use_tail_risk``, Default True seit
CMA-TAIL-ACTIVATION-GOVERNANCE-001). Der Text folgt jetzt demselben
Schalter wie die Rechnung.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine_mc_simulation import (  # noqa: E402
    _simulation_use_tail_risk,
    path_simulation_method_sentence,
    path_simulation_projection_sentence,
)

_NORMAL_CLAIM = re.compile(r"normalverteilte[nr]?\s+Jahresrendite", re.IGNORECASE)


@pytest.mark.parametrize("prefs", [None, {}, {"tailRisk": True}, {"cornishFisher": "true"}])
def test_default_text_names_cornish_fisher(prefs):
    assert _simulation_use_tail_risk(prefs) is True
    for sentence in (path_simulation_method_sentence(prefs), path_simulation_projection_sentence(prefs)):
        assert "Cornish-Fisher-Korrektur" in sentence
        assert "lognormalen Jahresrenditen" in sentence
        assert not _NORMAL_CLAIM.search(sentence)


def test_explicit_tail_off_text_says_lognormal_without_correction():
    prefs = {"tailRisk": False}
    assert _simulation_use_tail_risk(prefs) is False
    sentence = path_simulation_method_sentence(prefs)
    assert "ohne Tail-Korrektur" in sentence
    assert not _NORMAL_CLAIM.search(sentence)


def test_no_customer_text_claims_normal_annual_returns():
    """Kein Backend-, PDF- oder Frontend-Text behauptet mehr normalverteilte
    Jahresrenditen (Kommentare/Docstrings ausgenommen: nur String-Literale
    in .py-Dateien und HTML/JS des Frontends werden geprueft)."""
    offenders: list[str] = []
    for path in (BACKEND_ROOT / "services").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\"[^\"\n]*\"|'[^'\n]*'", text):
            if _NORMAL_CLAIM.search(match.group(0)):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
    frontend = REPO_ROOT / "ares-desktop" / "frontend"
    for pattern in ("*.html", "*.js"):
        for path in frontend.rglob(pattern):
            if "vendor" in path.parts or "node_modules" in path.parts:
                continue
            if _NORMAL_CLAIM.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
