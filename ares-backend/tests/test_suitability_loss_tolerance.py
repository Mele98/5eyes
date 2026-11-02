"""SUITABILITY-LOSS-TOLERANCE-001 (Audit 2026-11, AA-8, L16, P11 Vorbereitung).

Reines Modul, NICHT verdrahtet (Flag aus). Getestet werden:

* das Antwort-Mapping aus den bestehenden Optionstexten von Frage 10,
* das 10-%-Quantil der 1-Jahres-Rendite, konsistent zur Monte-Carlo-Abbildung,
* das Konfliktobjekt (ok / conflict / not_evaluable, fail-closed),
* das Flag (standardmaessig aus, keine Verdrahtung in der Engine),
* die Platzhalter: nichts erfunden.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import suitability_loss_tolerance as lt  # noqa: E402
from services.optimizer.distributions import standard_normal_to_log_return  # noqa: E402
from services.risk_questionnaire_integrity import STANDARD_OPTIONS  # noqa: E402


# ---------------------------------------------------------------------------
# Antwort-Mapping (nur gelesen aus dem Fragebogen)
# ---------------------------------------------------------------------------

def test_mapping_is_read_from_question_10_option_texts():
    bands = lt.LOSS_TOLERANCE_BANDS
    assert sorted(bands) == [1, 2, 3, 4]
    assert {p: (b.floor_bps, b.upper_bps) for p, b in bands.items()} == {
        1: (-400, 600),
        2: (-600, 1000),
        3: (-1000, 1600),
        4: (-1600, 2400),
    }
    for points, band in bands.items():
        assert band.is_mapped
        assert band.placeholder is None
        assert band.option_text == STANDARD_OPTIONS[10][band.option_index]
        assert band.option_index == points - 1


def test_point_field_is_the_risk_preference_question():
    assert lt.POINT_FIELD == "q_risk_preference_points"
    assert lt.answer_points_from_assessment({"q_risk_preference_points": 3}) == 3

    class _A:
        q_risk_preference_points = 2

    assert lt.answer_points_from_assessment(_A()) == 2
    assert lt.answer_points_from_assessment(None) is None
    assert lt.answer_points_from_assessment({"q_risk_preference_points": True}) is None
    assert lt.answer_points_from_assessment({"q_risk_preference_points": "3"}) is None


@pytest.mark.parametrize("text,expected", [
    ("(Wertschwankung ca. −4 % bis +6 %)", (-400, 600)),
    ("Wertschwankung ca. -10 % bis +16 %", (-1000, 1600)),
    ("Wertschwankung ca. – 2,5 % bis + 3,5 %", (-250, 350)),
    ("Ich bevorzuge Anlagen mit geringem Risiko.", None),
    ("", None),
])
def test_parse_fluctuation_band(text, expected):
    assert lt.parse_fluctuation_band(text) == expected


def test_unreadable_option_becomes_marked_placeholder_not_invented():
    bands = lt.build_loss_tolerance_bands(
        options=("Wertschwankung ca. −4 % bis +6 %", "Ohne Zahlenangabe"),
        points=(1, 2),
    )
    assert bands[1].is_mapped
    assert bands[2].floor_bps is None and bands[2].upper_bps is None
    assert bands[2].placeholder == lt.PLACEHOLDER_UNMAPPED
    assert not bands[2].is_mapped


def test_mapping_rejects_mismatched_points():
    with pytest.raises(ValueError):
        lt.build_loss_tolerance_bands(options=("a", "b"), points=(1,))


# ---------------------------------------------------------------------------
# 10-%-Quantil, 1 Jahr
# ---------------------------------------------------------------------------

def test_p10_normal_case_matches_lognormal_closed_form():
    mu, sigma = 0.05, 0.10
    v = math.log1p((sigma / (1 + mu)) ** 2)
    z = -1.2815515655446004
    expected = (math.exp(math.log1p(mu) - 0.5 * v + math.sqrt(v) * z) - 1) * 1e4
    assert lt.one_year_p10_return_bps(500, 1000) == pytest.approx(expected, abs=1e-6)


def test_p10_is_consistent_with_mc_sampling():
    rng = random.Random(20261102)
    draws = sorted(
        standard_normal_to_log_return(rng.gauss(0.0, 1.0), 400, 800, skew=-0.3, excess_kurt=2.0) - 1.0
        for _ in range(40_000)
    )
    empirical = draws[int(0.10 * len(draws))] * 1e4
    analytic = lt.one_year_p10_return_bps(400, 800, skew=-0.3, excess_kurtosis=2.0)
    assert analytic == pytest.approx(empirical, abs=15.0)


def test_p10_falls_with_volatility_and_left_skew():
    base = lt.one_year_p10_return_bps(500, 1000)
    assert lt.one_year_p10_return_bps(500, 1500) < base
    left = lt.one_year_p10_return_bps(500, 1000, skew=-0.5, excess_kurtosis=1.0)
    more_left = lt.one_year_p10_return_bps(500, 1000, skew=-0.7, excess_kurtosis=1.0)
    assert more_left < left
    # Bekannte Eigenschaft (kein Fehler): Exzess-Kurtosis verschiebt bei
    # gleicher Vola Masse in die aeusseren Flanken UND in die Mitte; das
    # 10-%-Quantil rueckt dabei nach innen. P10 ist deshalb kein Tail-Mass
    # wie CVaR -- so verlangt es AA-8 (Untergrenze des 80-%-Intervalls).
    assert lt.one_year_p10_return_bps(500, 1000, skew=-0.5, excess_kurtosis=3.0) > left


def test_p10_rejects_non_monotonic_cornish_fisher():
    with pytest.raises(ValueError):
        lt.one_year_p10_return_bps(500, 1000, skew=-1.0, excess_kurtosis=0.0)


# ---------------------------------------------------------------------------
# Konfliktobjekt
# ---------------------------------------------------------------------------

def test_conflict_when_p10_below_floor():
    check = lt.evaluate_loss_tolerance(1, p10_return_bps=-750.0)
    assert check.status == lt.STATUS_CONFLICT
    assert check.is_conflict
    assert check.check_code == lt.REASON_CONFLICT == "LOSS_TOLERANCE_CONFLICT"
    assert check.floor_bps == -400
    assert check.shortfall_bps == 350.0
    assert check.requires_justification is True
    assert "Begruendung" in check.message
    data = check.to_dict()
    assert data["status"] == "conflict"
    assert data["quantile"] == 0.10 and data["horizon_years"] == 1
    assert data["interpretation_source"] == "AA-8"
    assert isinstance(data["placeholders"], list)


def test_ok_when_p10_equals_or_exceeds_floor():
    at_floor = lt.evaluate_loss_tolerance(3, p10_return_bps=-1000.0)
    assert at_floor.status == lt.STATUS_OK
    assert at_floor.check_code is None
    assert at_floor.requires_justification is False
    assert at_floor.shortfall_bps is None
    assert lt.evaluate_loss_tolerance(4, p10_return_bps=-900.0).status == lt.STATUS_OK


def test_evaluation_from_moments():
    # 6 % / 14 % Vola: P10 ~ -11.8 % -> Konflikt bei Antwort 3 (-10 %), ok bei 4 (-16 %).
    p10 = lt.one_year_p10_return_bps(600, 1400)
    assert -1300 < p10 < -1000
    assert lt.evaluate_loss_tolerance(3, expected_return_bps=600, volatility_bps=1400).is_conflict
    ok = lt.evaluate_loss_tolerance(4, expected_return_bps=600, volatility_bps=1400)
    assert ok.status == lt.STATUS_OK
    assert ok.p10_return_bps == pytest.approx(round(p10, 2))


@pytest.mark.parametrize("points", [None, True, "2", 2.0])
def test_missing_answer_is_not_evaluable(points):
    check = lt.evaluate_loss_tolerance(points, p10_return_bps=0.0)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_ANSWER_MISSING
    assert not check.is_conflict


@pytest.mark.parametrize("points", [0, 5, 99])
def test_unknown_answer_is_unmapped_placeholder(points):
    check = lt.evaluate_loss_tolerance(points, p10_return_bps=0.0)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_ANSWER_UNMAPPED
    assert check.floor_bps is None
    assert lt.PLACEHOLDER_UNMAPPED in check.placeholders


def test_missing_distribution_is_not_evaluable():
    check = lt.evaluate_loss_tolerance(2)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_DISTRIBUTION_MISSING
    assert check.floor_bps == -600
    nan = lt.evaluate_loss_tolerance(2, p10_return_bps=float("nan"))
    assert nan.check_code == lt.REASON_DISTRIBUTION_MISSING


def test_non_monotonic_tail_is_not_evaluable():
    check = lt.evaluate_loss_tolerance(
        2, expected_return_bps=500, volatility_bps=1000, skew=-1.0, excess_kurtosis=0.0,
    )
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_CF_NOT_MONOTONIC


# ---------------------------------------------------------------------------
# Platzhalter und Flag
# ---------------------------------------------------------------------------

def test_open_placeholders_are_always_disclosed():
    gross = lt.evaluate_loss_tolerance(2, p10_return_bps=0.0)
    assert set(gross.placeholders) == {
        lt.PLACEHOLDER_Q10_COVERAGE,
        lt.PLACEHOLDER_Q10_HORIZON,
        lt.PLACEHOLDER_NET_BASIS,
    }
    assert gross.return_basis == lt.RETURN_BASIS_GROSS
    net = lt.evaluate_loss_tolerance(2, p10_return_bps=0.0, return_basis=lt.RETURN_BASIS_NET)
    assert lt.PLACEHOLDER_NET_BASIS not in net.placeholders
    for key in (*gross.placeholders, lt.PLACEHOLDER_Q11):
        assert key in lt.OPEN_PLACEHOLDERS


def test_flag_is_off_by_default_and_gates_the_entry_point():
    assert lt.LOSS_TOLERANCE_CHECK_ENABLED is False
    assert lt.evaluate_loss_tolerance_if_enabled(1, p10_return_bps=-750.0) is None
    forced = lt.evaluate_loss_tolerance_if_enabled(1, enabled=True, p10_return_bps=-750.0)
    assert forced is not None and forced.is_conflict


def test_module_is_not_wired_into_production_code():
    """P11 wird erst nach P2b aktiviert: kein Produktionsmodul importiert es."""
    needle = "suitability_loss_tolerance"
    hits = []
    for path in BACKEND_ROOT.rglob("*.py"):
        rel_path = path.relative_to(BACKEND_ROOT)
        rel = rel_path.as_posix()
        if {"tests", "venv", ".venv", "node_modules", "__pycache__"}.intersection(rel_path.parts):
            continue
        if rel == "services/suitability_loss_tolerance.py":
            continue
        if needle in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(rel)
    assert hits == []


def test_questionnaire_source_is_unchanged():
    """Paragraf 2 (Vorlage) bleibt unveraendert: die vier Optionstexte von Frage 10."""
    assert STANDARD_OPTIONS[10] == (
        "Ich bevorzuge Anlagen mit relativ geringem Risiko. Die Rendite steht für mich nicht im Vordergrund. (Wertschwankung ca. −4 % bis +6 %)",
        "Ich bin bereit, für eine moderate Rendite ein leicht höheres Risiko in Kauf zu nehmen. (Wertschwankung ca. −6 % bis +10 %)",
        "Ich strebe eine höhere Rendite an und bin bereit, dafür ein erhöhtes Risiko einzugehen. (Wertschwankung ca. −10 % bis +16 %)",
        "Ich strebe nach der maximalen Rendite und nehme hohe Risiken in Kauf. (Wertschwankung ca. −16 % bis +24 %)",
    )
