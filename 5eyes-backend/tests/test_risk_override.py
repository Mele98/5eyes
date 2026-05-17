from unittest.mock import MagicMock

import pytest

from schemas.profiling import RiskAssessmentOverride
from services.portfolio_engine import _risk_score_bucket, risk_assessment_ready_for_strategy
from services.risk_scoring import profile_for_score_x10


def _make_assessment(
    *,
    is_overridden=0,
    override_score_x10=None,
    final_score_x10=50,
    override_reason="",
    override_client_confirmed=0,
    override_warning_delivered=0,
    with_schema_markers=True,
):
    ra = MagicMock()
    ra.is_overridden = is_overridden
    ra.override_score_x10 = override_score_x10
    ra.final_score_x10 = final_score_x10
    ra.override_reason = override_reason
    ra.override_client_confirmed = override_client_confirmed
    ra.override_warning_delivered = override_warning_delivered
    ra.knowledge_services_json = "{}" if with_schema_markers else None
    ra.knowledge_instruments_json = "{}" if with_schema_markers else None
    ra.income_sources_json = "[]" if with_schema_markers else None
    ra.answers = []
    return ra


def test_score_bucket_zero_maps_to_bucket_1_not_10():
    """Score 0 (Kapitalschutz, Kurzfrist-Horizon) must map to bucket 1, not via falsy fallback."""
    ra = _make_assessment(final_score_x10=0)
    assert _risk_score_bucket(ra) == 1


def test_score_bucket_uses_override_when_overridden():
    ra = _make_assessment(is_overridden=1, override_score_x10=70, final_score_x10=30)
    assert _risk_score_bucket(ra) == 7


def test_score_bucket_uses_final_when_not_overridden():
    ra = _make_assessment(is_overridden=0, override_score_x10=70, final_score_x10=30)
    assert _risk_score_bucket(ra) == 3


def test_score_bucket_uses_final_when_override_score_is_none():
    """is_overridden=1 but override_score_x10=None should still use final score."""
    ra = _make_assessment(is_overridden=1, override_score_x10=None, final_score_x10=50)
    assert _risk_score_bucket(ra) == 5


def test_score_bucket_all_valid_scores_stay_in_range():
    for score_x10 in range(0, 101, 10):
        ra = _make_assessment(final_score_x10=score_x10)
        bucket = _risk_score_bucket(ra)
        assert 1 <= bucket <= 10, f"score_x10={score_x10} -> bucket={bucket} out of range"


def _make_full_answers():
    """Minimal complete answer list for the current questionnaire."""
    rows = [
        (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
        (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
        (3, "CHF 12'000 bis 20'000", 3),
        (4, "Herkunft: Berufliche Taetigkeit", 0),
        (5, "CHF 3'000 bis 5'000", 3),
        (6, "CHF 1'000'000 bis 2'000'000", 9),
        (7, "25 bis 50 %", 9),
        (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
        (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
        (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
        (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
    ]
    answers = []
    for qn, label, points in rows:
        answer = MagicMock()
        answer.question_number = qn
        answer.answer_label = label
        answer.answer_points = points
        answers.append(answer)
    return answers


def _make_legacy_answers_with_all_numbers():
    answers = []
    for qn in range(1, 12):
        answer = MagicMock()
        answer.question_number = qn
        answer.answer_label = f"A{qn}"
        answer.answer_points = 2
        answers.append(answer)
    return answers


def test_documented_override_with_score_is_strategy_ready_even_without_answers():
    """Documented override bypasses answer completeness."""
    ra = _make_assessment(
        is_overridden=1,
        override_score_x10=70,
        final_score_x10=30,
        override_reason="Kundenwunsch dokumentiert",
        override_client_confirmed=1,
        override_warning_delivered=1,
    )
    ra.answers = []
    assert risk_assessment_ready_for_strategy(ra) is True


def test_non_override_with_complete_answers_is_ready():
    ra = _make_assessment(is_overridden=0, final_score_x10=50)
    ra.answers = _make_full_answers()
    assert risk_assessment_ready_for_strategy(ra) is True


def test_non_override_with_incomplete_answers_is_not_ready():
    ra = _make_assessment(is_overridden=0, final_score_x10=50)
    ra.answers = _make_full_answers()[:-1]
    assert risk_assessment_ready_for_strategy(ra) is False


def test_non_override_with_legacy_answer_numbers_is_not_ready():
    ra = _make_assessment(is_overridden=0, final_score_x10=70, with_schema_markers=False)
    ra.answers = _make_legacy_answers_with_all_numbers()
    assert risk_assessment_ready_for_strategy(ra) is False


def test_non_override_without_current_schema_markers_is_not_ready():
    ra = _make_assessment(is_overridden=0, final_score_x10=50, with_schema_markers=False)
    ra.answers = _make_full_answers()
    assert risk_assessment_ready_for_strategy(ra) is False


def test_none_assessment_is_not_ready():
    assert risk_assessment_ready_for_strategy(None) is False


def test_assessment_with_no_scores_is_not_ready():
    ra = _make_assessment(final_score_x10=None, override_score_x10=None)
    ra.answers = _make_full_answers()
    assert risk_assessment_ready_for_strategy(ra) is False


def test_overridden_flag_without_override_score_still_needs_answers():
    """is_overridden=1 but override_score_x10=None is not a valid override."""
    ra = _make_assessment(is_overridden=1, override_score_x10=None, final_score_x10=50)
    ra.answers = []
    assert risk_assessment_ready_for_strategy(ra) is False


def test_override_without_reason_is_not_strategy_ready():
    ra = _make_assessment(is_overridden=1, override_score_x10=70, final_score_x10=50)
    assert risk_assessment_ready_for_strategy(ra) is False


def test_large_upward_override_without_warning_is_not_strategy_ready():
    ra = _make_assessment(
        is_overridden=1,
        override_score_x10=70,
        final_score_x10=30,
        override_reason="Kundenwunsch dokumentiert",
    )
    assert risk_assessment_ready_for_strategy(ra) is False


def test_small_or_downward_override_with_reason_is_strategy_ready():
    ra = _make_assessment(
        is_overridden=1,
        override_score_x10=70,
        final_score_x10=50,
        override_reason="Kundenwunsch dokumentiert",
    )
    assert risk_assessment_ready_for_strategy(ra) is True


def _valid_override(**kwargs):
    defaults = dict(
        override_score_x10=70,
        override_profile="Wachstumsorientiert",
        override_reason="Kundenwunsch dokumentiert",
    )
    defaults.update(kwargs)
    return RiskAssessmentOverride(**defaults)


def test_override_score_70_matches_wachstumsorientiert():
    override = _valid_override(override_score_x10=70, override_profile="Wachstumsorientiert")
    assert override.override_score_x10 == 70


def test_override_score_100_matches_aktien():
    override = _valid_override(override_score_x10=100, override_profile="Aktien")
    assert override.override_score_x10 == 100


def test_override_score_10_matches_kapitalschutz():
    override = _valid_override(override_score_x10=10, override_profile="Kapitalschutz")
    assert override.override_score_x10 == 10


def test_override_score_90_matches_dynamisch():
    override = _valid_override(override_score_x10=90, override_profile="Dynamisch")
    assert override.override_score_x10 == 90


@pytest.mark.parametrize(
    "score_x10,wrong_profile",
    [
        (10, "Aktien"),
        (10, "Dynamisch"),
        (10, "Wachstumsorientiert"),
        (50, "Kapitalschutz"),
        (50, "Aktien"),
        (100, "Kapitalschutz"),
        (100, "Ausgewogen"),
        (90, "Aktien"),
        (90, "Kapitalschutz"),
    ],
)
def test_override_rejects_inconsistent_score_profile_combinations(score_x10, wrong_profile):
    with pytest.raises(ValueError):
        _valid_override(override_score_x10=score_x10, override_profile=wrong_profile)


def test_override_score_boundary_kapitalschutz_24():
    override = _valid_override(override_score_x10=24, override_profile="Kapitalschutz")
    assert override.override_profile == "Kapitalschutz"


def test_override_score_boundary_defensiv_25():
    override = _valid_override(override_score_x10=25, override_profile="Defensiv")
    assert override.override_profile == "Defensiv"


def test_override_score_boundary_aktien_95():
    override = _valid_override(override_score_x10=95, override_profile="Aktien")
    assert override.override_profile == "Aktien"


def test_override_score_boundary_dynamisch_94():
    override = _valid_override(override_score_x10=94, override_profile="Dynamisch")
    assert override.override_profile == "Dynamisch"


@pytest.mark.parametrize(
    "score_x10,expected",
    [
        (10, "Kapitalschutz"),
        (24, "Kapitalschutz"),
        (25, "Defensiv"),
        (44, "Defensiv"),
        (45, "Ausgewogen"),
        (64, "Ausgewogen"),
        (65, "Wachstumsorientiert"),
        (84, "Wachstumsorientiert"),
        (85, "Dynamisch"),
        (94, "Dynamisch"),
        (95, "Aktien"),
        (100, "Aktien"),
    ],
)
def test_profile_for_score_x10_covers_all_boundaries(score_x10, expected):
    assert profile_for_score_x10(score_x10) == expected
