"""
Risk Scoring Service
Implements the 5Eyes / Advisory-Methodik risk profiling logic (Fachlogik v1.6).

Risikofähigkeit (max 28 Punkte im FE-Pfad / generisch bis 32) → Score 0–10 via horizon × capacity matrix
Risikobereitschaft (max 12 Punkte) → Score 0–10
Final Score = MIN(capacity_score, willingness_score)
Final Score → Profile name
"""

from dataclasses import dataclass
import math


# ── Profile mapping ────────────────────────────────────────────────────────────

SCORE_TO_PROFILE = {
    (1, 2): "Kapitalschutz",
    (3, 4): "Defensiv",
    (5, 6): "Ausgewogen",
    (7, 8): "Wachstumsorientiert",
    (9, 9): "Dynamisch",
    (10, 10): "Aktien",
}

CAPACITY_TOTAL_TO_PROFILE = {
    (0, 2): "Risikoarm",
    (3, 5): "Sicherheitsorientiert",
    (6, 9): "Ausgewogen",
    (10, 13): "Wachstumsorientiert",
    (14, 32): "Dynamisch",
}

WILLINGNESS_SCORE_TO_PROFILE = {
    (10, 24): "Kapitalschutz",
    (25, 44): "Defensiv",
    (45, 64): "Ausgewogen",
    (65, 84): "Wachstumsorientiert",
    (85, 94): "Dynamisch",
    (95, 100): "Aktien",
}

# Horizon label → years (midpoint for matrix lookup)
HORIZON_YEARS = {
    "Bis 2 Jahre": 1,
    "2 bis 3 Jahre": 2,
    "4 bis 5 Jahre": 4,
    "6 bis 7 Jahre": 6,
    "8 bis 11 Jahre": 9,
    "Mehr als 12 Jahre": 15,
    "0 bis 4 Jahre": 2,
    "5 bis 7 Jahre": 6,
    "12 Jahre und mehr": 15,
    # Legacy frontend labels
    "1 bis 3 Jahre": 2,
    "3 bis 5 Jahre": 4,
    "5 bis 10 Jahre": 6,
    "10 Jahre und mehr": 15,
}

CANONICAL_HORIZON_LABELS = {
    "Bis 2 Jahre": "Bis 2 Jahre",
    "2 bis 3 Jahre": "2 bis 3 Jahre",
    "4 bis 5 Jahre": "4 bis 5 Jahre",
    "6 bis 7 Jahre": "6 bis 7 Jahre",
    "8 bis 11 Jahre": "8 bis 11 Jahre",
    "Mehr als 12 Jahre": "Mehr als 12 Jahre",
    "0 bis 4 Jahre": "2 bis 3 Jahre",
    "5 bis 7 Jahre": "6 bis 7 Jahre",
    "12 Jahre und mehr": "Mehr als 12 Jahre",
    "1 bis 3 Jahre": "2 bis 3 Jahre",
    "3 bis 5 Jahre": "4 bis 5 Jahre",
    "5 bis 10 Jahre": "6 bis 7 Jahre",
    "10 Jahre und mehr": "Mehr als 12 Jahre",
}

# Risk capacity profile → numeric band (1–5)
CAPACITY_BAND = {
    "Risikoarm": 1,
    "Sicherheitsorientiert": 2,
    "Ausgewogen": 3,
    "Wachstumsorientiert": 4,
    "Dynamisch": 5,
}

# Horizon × Capacity → Score x10 (matrix)
# Rows: horizon years (1,2,4,6,9,15)
# Cols: capacity band (1-5)
HORIZON_CAPACITY_MATRIX: dict[tuple[int, int], int] = {
    (1, 1): 0,   (1, 2): 0,   (1, 3): 0,   (1, 4): 0,   (1, 5): 0,
    (2, 1): 10,  (2, 2): 10,  (2, 3): 20,  (2, 4): 20,  (2, 5): 20,
    (4, 1): 10,  (4, 2): 40,  (4, 3): 45,  (4, 4): 50,  (4, 5): 50,
    (6, 1): 20,  (6, 2): 45,  (6, 3): 55,  (6, 4): 60,  (6, 5): 60,
    (9, 1): 20,  (9, 2): 50,  (9, 3): 60,  (9, 4): 65,  (9, 5): 70,
    (15, 1): 30, (15, 2): 50, (15, 3): 60, (15, 4): 75, (15, 5): 100,
}


def map_surplus_points(income_chf: float, obligations_chf: float) -> int:
    income = max(0.0, float(income_chf or 0))
    obligations = max(0.0, float(obligations_chf or 0))
    if income <= 0:
        return 0
    surplus_ratio = (income - obligations) / income
    if surplus_ratio < 0:
        return 0
    if surplus_ratio < 0.10:
        return 1
    if surplus_ratio < 0.25:
        return 2
    if surplus_ratio < 0.45:
        return 3
    return 4


def _profile_from_score(score_x10: int) -> str:
    score = score_x10 / 10
    rounded_score = max(1, min(10, math.floor(score + 0.5)))
    for (lo, hi), name in SCORE_TO_PROFILE.items():
        if lo <= rounded_score <= hi:
            return name
    return "Kapitalschutz"


def _capacity_profile(total: int) -> str:
    for (lo, hi), name in CAPACITY_TOTAL_TO_PROFILE.items():
        if lo <= total <= hi:
            return name
    return "Risikoarm"


def _willingness_profile(score_x10: int) -> str:
    for (lo, hi), name in WILLINGNESS_SCORE_TO_PROFILE.items():
        if lo <= score_x10 <= hi:
            return name
    return "Kapitalschutz"


# ── Public API ─────────────────────────────────────────────────────────────────

@dataclass
class ScoringResult:
    # Risikofähigkeit
    risk_capacity_total: int
    risk_capacity_profile: str
    risk_capacity_score_x10: int
    # Risikobereitschaft
    risk_willingness_total: int
    risk_willingness_profile: str
    risk_willingness_score_x10: int
    # Final
    final_score_x10: int
    final_profile: str


def canonicalize_horizon_label(label: str) -> str:
    normalized = str(label or "").strip()
    return CANONICAL_HORIZON_LABELS.get(normalized, normalized)


def compute_scores(
    *,
    q_income_points: int,
    q_obligations_points: int,
    q_savings_points: int,
    q_wealth_points: int,
    investment_horizon_label: str,
    q_investment_goal_points: int,
    q_risk_preference_points: int,
    q_risk_behavior_points: int,
) -> ScoringResult:
    """
    Compute all risk scores from raw questionnaire answers.

    All point values must be pre-validated (range checks done in Pydantic schema).
    """
    for name, value, minimum, maximum in (
        ("q_income_points", q_income_points, 0, 4),
        ("q_obligations_points", q_obligations_points, 0, 4),
        ("q_savings_points", q_savings_points, 0, 12),
        ("q_wealth_points", q_wealth_points, 0, 12),
        ("q_investment_goal_points", q_investment_goal_points, 1, 4),
        ("q_risk_preference_points", q_risk_preference_points, 1, 4),
        ("q_risk_behavior_points", q_risk_behavior_points, 1, 4),
    ):
        numeric = int(value)
        if numeric < minimum or numeric > maximum:
            raise ValueError(f"{name}={value} ausserhalb [{minimum},{maximum}]")

    # ── Risikofähigkeit ────────────────────────────────────────────────────────
    capacity_total = (
        q_income_points + q_obligations_points
        + q_savings_points + q_wealth_points
    )
    cap_profile = _capacity_profile(capacity_total)
    cap_band = CAPACITY_BAND[cap_profile]
    investment_horizon_label = canonicalize_horizon_label(investment_horizon_label)
    horizon_years = HORIZON_YEARS.get(investment_horizon_label, 1)
    capacity_score_x10 = HORIZON_CAPACITY_MATRIX.get((horizon_years, cap_band), 0)

    # ── Risikobereitschaft ─────────────────────────────────────────────────────
    willingness_total = (
        q_investment_goal_points + q_risk_preference_points + q_risk_behavior_points
    )
    raw_will_score = int(round(((willingness_total - 3) / 9) * 90 + 10))
    will_score_x10 = max(10, min(100, raw_will_score))
    will_profile = _willingness_profile(will_score_x10)

    # ── Final ──────────────────────────────────────────────────────────────────
    final_x10 = min(capacity_score_x10, will_score_x10)
    final_profile = _profile_from_score(final_x10)

    return ScoringResult(
        risk_capacity_total=capacity_total,
        risk_capacity_profile=cap_profile,
        risk_capacity_score_x10=capacity_score_x10,
        risk_willingness_total=willingness_total,
        risk_willingness_profile=will_profile,
        risk_willingness_score_x10=will_score_x10,
        final_score_x10=final_x10,
        final_profile=final_profile,
    )


def get_house_matrix_profile(score_x10: int) -> str:
    """Map a final score to a house matrix profile name."""
    return _profile_from_score(score_x10)


def profile_for_score_x10(score_x10: int) -> str:
    """Public wrapper for the profile name of a score_x10 value (10-100)."""
    return _profile_from_score(score_x10)
