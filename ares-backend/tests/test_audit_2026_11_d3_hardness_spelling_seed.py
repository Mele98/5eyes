"""AUDIT-2026-11 D3: die Schreibweise des Haertegrads aenderte den Seed.

Befund (Audit 01, D3): "Primär" und "Primaer" sind fachlich gleich
(``goal_liabilities._HARDNESS_LABELS_TO_KEY``), gingen aber roh in den
Inhalts-Fingerabdruck ``goal_economic_fingerprint`` und damit in
``optimizer_content_seed`` ein. Gemessen: Vermoegensziel "Primär" ->
Aktien 6771 bps, "Primaer" -> 6755 bps, sonst identisches Mandat.

Fix: der Haertegrad wird vor dem Hashing auf die gespeicherte Form
kanonisiert ("Hart"/"Primär"/"Opportunistisch" -- Modell-/Schema-Default
und Frontend). Diese Form behaelt ihren bisherigen Seed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.evidence import SCHEME_V1_ASCII, canonical_json  # noqa: E402
from services.optimizer.solver import GOAL_ECONOMIC_FIELDS, goal_economic_fingerprint  # noqa: E402


def _goal(hardness):
    return {
        "goal_type": "Vermoegensziel", "target_wealth_rappen": 300_000_00,
        "target_date": "2036-06-30", "start_date": None, "is_active": 1,
        "hardness": hardness,
    }


def _legacy_row(goal):
    """Fingerabdruck-Zeile wie vor dem Fix (roher Wert, Datum relativ)."""
    row = {name: goal.get(name) for name in GOAL_ECONOMIC_FIELDS}
    row["target_date"] = "Y+10-06-30"
    return canonical_json(row, scheme=SCHEME_V1_ASCII)


@pytest.mark.parametrize(
    ("spellings", "stored"),
    [
        (("Primär", "Primaer", "primär", "primaer", "PRIMAER", " Primary "), "Primär"),
        (("Hart", "hart", "hard"), "Hart"),
        (("Opportunistisch", "opportunistisch", "opportunistic", "opp"), "Opportunistisch"),
    ],
)
def test_equivalent_spellings_share_one_fingerprint(spellings, stored):
    fingerprints = {
        tuple(goal_economic_fingerprint([_goal(value)], valuation_year=2026))
        for value in spellings
    }
    assert len(fingerprints) == 1, fingerprints
    # Die gespeicherte Schreibweise behaelt ihren bisherigen Fingerabdruck
    # (und damit ihren Seed) bitgleich.
    assert fingerprints.pop() == (_legacy_row(_goal(stored)),)


def test_semantically_different_hardness_still_differs():
    fp = goal_economic_fingerprint
    assert fp([_goal("Primär")], valuation_year=2026) != fp([_goal("Hart")], valuation_year=2026)
    assert fp([_goal("Primär")], valuation_year=2026) != fp([_goal("Opportunistisch")], valuation_year=2026)


@pytest.mark.parametrize("value", [None, "", "Unbekannt", 1])
def test_unknown_or_missing_hardness_is_canonicalized_like_the_engine_reads_it(value):
    """H-859-8 (Pruefrunde #859): goal_liabilities._hardness_key liest None
    und unbekannte Werte als "primaer" -- der Seed-Fingerabdruck jetzt auch."""
    from services.optimizer.goal_liabilities import _hardness_key
    from types import SimpleNamespace

    assert _hardness_key(SimpleNamespace(hardness=value)) == "primaer"
    assert goal_economic_fingerprint([_goal(value)], valuation_year=2026) == [_legacy_row(_goal("Primär"))]


def test_engine_version_marks_the_canonicalization():
    """H-859-8: Neuberechnungen von Altdaten mit abweichender Schreibweise
    ziehen einen anderen Wuerfel; die Engine-Version trennt sie von v18."""
    from services.optimizer import solver

    assert solver.OPTIMIZER_ENGINE_VERSION == "saa_resampled_v19"
