"""SUITABILITY-LOSS-TOLERANCE-001 (Audit 2026-11, AA-8, L16, P11 Vorbereitung).

Reines Modul, NICHT verdrahtet (Flag aus). Getestet werden:

* das Antwort-Mapping aus den bestehenden Optionstexten von Frage 10,
* das 10-%-Quantil der 1-Jahres-Rendite (Quelle MC-Pfade oder lognormal k=0;
  Tail-Momente als Sperrgrundlage gesperrt, N-857-3),
* das Konfliktobjekt (ok / conflict / not_evaluable, fail-closed) und die
  Konfliktbehandlung nach mandate_type,
* das Flag (standardmaessig aus, keine Verdrahtung in der Engine),
* die Platzhalter: nichts erfunden.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
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

ADV = "Anlageberatung"
VV = "Vermögensverwaltung"


def test_lognormal_p10_matches_closed_form():
    mu, sigma = 0.05, 0.10
    v = math.log1p((sigma / (1 + mu)) ** 2)
    z = -1.2815515655446004
    expected = (math.exp(math.log1p(mu) - 0.5 * v + math.sqrt(v) * z) - 1) * 1e4
    assert lt.lognormal_p10_return_bps(500, 1000) == pytest.approx(expected, abs=1e-6)
    assert lt.one_year_p10_return_bps(500, 1000) == pytest.approx(expected, abs=1e-6)


def test_cf_single_asset_matches_mc_transformation():
    """Nur Einzelanlage: CF-Ausweisfunktion = MC-Transformation (keine Sperrgrundlage)."""
    rng = random.Random(20261102)
    draws = sorted(
        standard_normal_to_log_return(rng.gauss(0.0, 1.0), 400, 800, skew=-0.3, excess_kurt=2.0) - 1.0
        for _ in range(40_000)
    )
    empirical = draws[int(0.10 * len(draws))] * 1e4
    analytic = lt.one_year_p10_return_bps(400, 800, skew=-0.3, excess_kurtosis=2.0)
    assert analytic == pytest.approx(empirical, abs=15.0)


def test_kurtosis_moves_p10_inward_which_is_why_moments_cannot_block():
    """N-857-3: bei fester Varianz rueckt P10 mit Kurtosis nach innen (milder)."""
    k0 = lt.lognormal_p10_return_bps(600, 1400)
    k3 = lt.one_year_p10_return_bps(600, 1400, skew=-0.5, excess_kurtosis=3.0)
    assert k3 > k0 + 150  # deutlich milder als lognormal (gemessen ~1.85 pp)


def test_p10_rejects_non_monotonic_cornish_fisher():
    with pytest.raises(ValueError):
        lt.one_year_p10_return_bps(500, 1000, skew=-1.0, excess_kurtosis=0.0)


def test_p10_and_tail_disclosure_from_paths():
    rng = np.random.default_rng(7)
    returns = rng.normal(400.0, 900.0, size=200_000)
    assert lt.p10_from_paths(returns) == pytest.approx(400.0 - 1.28155 * 900.0, abs=10.0)
    tail = lt.tail_disclosure_from_paths(returns)
    assert tail["p5_return_bps"] == pytest.approx(400.0 - 1.64485 * 900.0, abs=12.0)
    # CVaR(10 %) der Normalverteilung: mu - sigma * phi(z_0.10) / 0.10
    assert tail["cvar10_return_bps"] == pytest.approx(400.0 - 900.0 * 1.75498, abs=12.0)
    assert tail["cvar10_return_bps"] < lt.p10_from_paths(returns)
    with pytest.raises(ValueError):
        lt.p10_from_paths([])
    with pytest.raises(ValueError):
        lt.p10_from_paths([1.0, float("nan")])


# ---------------------------------------------------------------------------
# Quellen-Guard (N-857-3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("skew,kurt", [(0.0, 1.0), (-0.3, 2.0), (-0.5, 3.0), (0.2, 0.0)])
def test_moment_path_with_tail_moments_is_not_admissible(skew, kurt):
    check = lt.evaluate_loss_tolerance(
        3, mandate_type=VV, expected_return_bps=600, volatility_bps=1400,
        skew=skew, excess_kurtosis=kurt,
    )
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_TAIL_MOMENTS_NOT_ADMISSIBLE
    assert not check.is_conflict and check.p10_return_bps is None


def test_minimum_of_mc_and_lognormal_is_binding():
    lognormal = lt.lognormal_p10_return_bps(600, 1400)
    milder_mc = lt.evaluate_loss_tolerance(
        4, mandate_type=VV, mc_p10_return_bps=lognormal + 300,
        expected_return_bps=600, volatility_bps=1400,
    )
    assert milder_mc.p10_source == lt.SOURCE_LOGNORMAL_K0
    assert milder_mc.p10_return_bps == pytest.approx(round(lognormal, 2))
    harsher_mc = lt.evaluate_loss_tolerance(
        4, mandate_type=VV, mc_p10_return_bps=lognormal - 300,
        expected_return_bps=600, volatility_bps=1400,
    )
    assert harsher_mc.p10_source == lt.SOURCE_MC_ASSET_PATHS
    assert set(harsher_mc.p10_candidates_bps) == set(lt.ADMISSIBLE_SOURCES)


def test_p5_and_cvar_are_disclosure_only():
    kwargs = dict(mandate_type=VV, mc_p10_return_bps=-900.0)
    plain = lt.evaluate_loss_tolerance(3, **kwargs)
    with_tail = lt.evaluate_loss_tolerance(
        3, p5_return_bps=-5000.0, cvar10_return_bps=-6000.0, **kwargs,
    )
    assert plain.status == with_tail.status == lt.STATUS_OK
    assert with_tail.p5_return_bps == -5000.0 and with_tail.cvar10_return_bps == -6000.0


# ---------------------------------------------------------------------------
# Konfliktobjekt und mandate_type
# ---------------------------------------------------------------------------

def test_conflict_when_p10_below_floor():
    check = lt.evaluate_loss_tolerance(1, mandate_type=ADV, mc_p10_return_bps=-750.0)
    assert check.status == lt.STATUS_CONFLICT
    assert check.is_conflict
    assert check.check_code == lt.REASON_CONFLICT == "LOSS_TOLERANCE_CONFLICT"
    assert check.floor_bps == -400
    assert check.shortfall_bps == 350.0
    assert check.p10_source == lt.SOURCE_MC_ASSET_PATHS
    data = check.to_dict()
    assert data["status"] == "conflict"
    assert data["quantile"] == 0.10 and data["horizon_years"] == 1
    assert data["interpretation_source"] == "AA-8"
    assert isinstance(data["placeholders"], list)


def test_advisory_conflict_requires_advise_against_and_justification():
    check = lt.evaluate_loss_tolerance(1, mandate_type=ADV, mc_p10_return_bps=-750.0)
    assert check.conflict_resolution == lt.RESOLUTION_ADVISE_AGAINST
    assert check.requires_advise_against is True
    assert check.requires_justification is True
    assert check.justification_sufficient is True
    assert "Abraten" in check.message


@pytest.mark.parametrize("mandate_type", [VV, None, "", "Execution-only", "unbekannt"])
def test_discretionary_or_unknown_conflict_blocks_without_justification(mandate_type):
    check = lt.evaluate_loss_tolerance(1, mandate_type=mandate_type, mc_p10_return_bps=-750.0)
    assert check.is_conflict
    assert check.conflict_resolution == lt.RESOLUTION_BLOCK
    assert check.blocks_release is True
    assert check.justification_sufficient is False
    assert check.requires_justification is False
    assert "genuegt nicht" in check.message


def test_ok_when_p10_equals_or_exceeds_floor():
    at_floor = lt.evaluate_loss_tolerance(3, mandate_type=VV, mc_p10_return_bps=-1000.0)
    assert at_floor.status == lt.STATUS_OK
    assert at_floor.check_code is None
    assert at_floor.blocks_release is False
    assert at_floor.conflict_resolution is None
    assert at_floor.shortfall_bps is None
    assert lt.evaluate_loss_tolerance(4, mandate_type=VV, mc_p10_return_bps=-900.0).status == lt.STATUS_OK


def test_evaluation_from_lognormal_moments():
    p10 = lt.lognormal_p10_return_bps(600, 1400)
    assert -1300 < p10 < -1000
    assert lt.evaluate_loss_tolerance(
        3, mandate_type=VV, expected_return_bps=600, volatility_bps=1400,
    ).is_conflict
    ok = lt.evaluate_loss_tolerance(4, mandate_type=VV, expected_return_bps=600, volatility_bps=1400)
    assert ok.status == lt.STATUS_OK
    assert ok.p10_source == lt.SOURCE_LOGNORMAL_K0
    assert ok.p10_return_bps == pytest.approx(round(p10, 2))


@pytest.mark.parametrize("points", [None, True, "2", 2.0])
def test_missing_answer_is_not_evaluable(points):
    check = lt.evaluate_loss_tolerance(points, mandate_type=VV, mc_p10_return_bps=0.0)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_ANSWER_MISSING
    assert not check.is_conflict


@pytest.mark.parametrize("points", [0, 5, 99])
def test_unknown_answer_is_unmapped_placeholder(points):
    check = lt.evaluate_loss_tolerance(points, mandate_type=VV, mc_p10_return_bps=0.0)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_ANSWER_UNMAPPED
    assert check.floor_bps is None
    assert lt.PLACEHOLDER_UNMAPPED in check.placeholders


def test_missing_distribution_is_not_evaluable():
    check = lt.evaluate_loss_tolerance(2, mandate_type=VV)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.check_code == lt.REASON_DISTRIBUTION_MISSING
    assert check.floor_bps == -600
    for kwargs in (
        {"mc_p10_return_bps": float("nan")},
        {"expected_return_bps": 500},
        {"volatility_bps": 1000},
    ):
        assert lt.evaluate_loss_tolerance(2, mandate_type=VV, **kwargs).check_code == (
            lt.REASON_DISTRIBUTION_MISSING
        )


# ---------------------------------------------------------------------------
# Platzhalter und Flag
# ---------------------------------------------------------------------------

def test_eleven_compliance_placeholders_are_listed_and_disclosed():
    assert len(lt.COMPLIANCE_PLACEHOLDERS) == 11
    keys = lt.COMPLIANCE_PLACEHOLDER_KEYS
    assert len(set(keys)) == 11
    assert all(text.strip() for _, text in lt.COMPLIANCE_PLACEHOLDERS)
    check = lt.evaluate_loss_tolerance(2, mandate_type=VV, mc_p10_return_bps=0.0)
    assert check.placeholders == keys
    net = lt.evaluate_loss_tolerance(
        2, mandate_type=VV, mc_p10_return_bps=0.0, return_basis=lt.RETURN_BASIS_NET,
    )
    assert net.placeholders == keys  # Kostenbasis bleibt Compliance-offen (CP04)


def test_flag_is_off_by_default_and_gates_the_entry_point():
    assert lt.LOSS_TOLERANCE_CHECK_ENABLED is False
    assert lt.evaluate_loss_tolerance_if_enabled(1, mandate_type=VV, mc_p10_return_bps=-750.0) is None
    forced = lt.evaluate_loss_tolerance_if_enabled(
        1, enabled=True, mandate_type=VV, mc_p10_return_bps=-750.0,
    )
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


# ---------------------------------------------------------------------------
# N-857-6: "nicht pruefbar" ist nie fail-open
# ---------------------------------------------------------------------------

_NOT_EVALUABLE_CASES = [
    dict(answer_points=None, mc_p10_return_bps=0.0),                      # Antwort fehlt
    dict(answer_points=7, mc_p10_return_bps=0.0),                         # nicht abgebildet
    dict(answer_points=2),                                                # Verteilung fehlt
    dict(answer_points=2, expected_return_bps=600, volatility_bps=1400,
         skew=-0.5, excess_kurtosis=3.0),                                 # Tail-Momente
]


@pytest.mark.parametrize("case", _NOT_EVALUABLE_CASES)
@pytest.mark.parametrize("mandate_type", [VV, None, "", "Execution-only", "Finanzplanung", "Reporting only"])
def test_not_evaluable_blocks_without_justification_outside_advisory(case, mandate_type):
    case = dict(case)
    check = lt.evaluate_loss_tolerance(case.pop("answer_points"), mandate_type=mandate_type, **case)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.blocks_release is True
    assert check.justification_sufficient is False
    assert check.conflict_resolution == lt.RESOLUTION_NOT_EVALUABLE_BLOCK


@pytest.mark.parametrize("case", _NOT_EVALUABLE_CASES)
def test_not_evaluable_in_advisory_requires_documented_justification(case):
    case = dict(case)
    check = lt.evaluate_loss_tolerance(case.pop("answer_points"), mandate_type=ADV, **case)
    assert check.status == lt.STATUS_NOT_EVALUABLE
    assert check.blocks_release is True
    assert check.requires_justification is True
    assert check.justification_sufficient is True
    assert check.conflict_resolution == lt.RESOLUTION_NOT_EVALUABLE_JUSTIFY


def test_only_ok_releases():
    ok = lt.evaluate_loss_tolerance(4, mandate_type=VV, mc_p10_return_bps=-900.0)
    assert ok.status == lt.STATUS_OK and ok.blocks_release is False
