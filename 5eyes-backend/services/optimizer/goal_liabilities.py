"""Goal -> Liability-Pfad-Konversion fuer Stochastic Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec. 6)

Jedes Goal wird in eine `GoalLiability` konvertiert, die der Optimizer als
Constraint nutzen kann:

- liability_path_rappen[i]: positiver Outflow im Jahr (start_year + i + 1)
  fuer Spending-Goals (Einmalige_Ausgabe, Wiederkehrende, Pensionsausgabe).
  Fuer Wealth-Goals (Vermoegensziel, Kapitalerhalt) und Renditeziel ist der
  Pfad reine Nullen — die Bewertung erfolgt am target_year_index.

- target_amount_rappen: was muss erreicht werden (Wealth-Schwelle / Annualisierter
  Cashflow / Return-Bps je nach target_kind).

- target_year_index: 1-based Jahr-Index ab dem das Goal bewertet wird.

- liability_path_rappen: 0-based, list[0] = Outflow im naechsten Jahr,
  list[horizon_years - 1] = Outflow im letzten simulierten Jahr.
  Konsistent zur Convention in services.cashflow_timeline.

Inflation: wird angewendet wenn goal.value_mode == "real". Default: nominal.
Spending-Goals werden ohne explizite real/nominal-Trennung behandelt — der
Cashflow ist immer der heutige Wert, und mit value_mode='real' erfolgt die
Hochrechnung mit der CMA-Inflation. Konsistent zu B1 (cashflow_timeline).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from models.wealth import Goal
from services.cashflow_timeline import normalize_frequency


# ============================================================================
# Public DataClass
# ============================================================================


@dataclass(frozen=True)
class GoalLiability:
    """Liability-Beschreibung fuer den Optimizer.

    target_kind:
        "wealth_at_t"          - Pfad-Wealth in Jahr T muss >= target sein
        "cashflow_in_year"     - Wealth in Jahr T muss >= einmal-Outflow sein
        "outflow_stream"       - kumulierte Outflows ueber Jahre 1..T abdeckbar
        "return_rate"          - annualized Return ueber Horizont >= target_bps
        "maximize"             - keine Constraint, nur in Vol-Min relevant
    """
    goal_id: str
    label: str
    goal_type: str
    target_kind: str
    target_amount_rappen: int  # bei "return_rate" ist es bps in diesem Feld
    target_year_index: int  # 1-based: Jahr ab Start in dem Goal bewertet wird
    liability_path_rappen: list[int] = field(default_factory=list)  # len == horizon_years
    hardness_key: str = "primaer"
    weight_bps: int = 312  # Fallback wenn goal.weight_bps None
    evaluation_note: str | None = None


# ============================================================================
# Hardness + Weight
# ============================================================================


_HARDNESS_LABELS_TO_KEY = {
    "hart": "hart",
    "hard": "hart",
    "primaer": "primaer",
    "primär": "primaer",
    "primary": "primaer",
    "opportunistisch": "opportunistisch",
    "opportunistic": "opportunistisch",
    "opp": "opportunistisch",
}


def _hardness_key(goal: Goal) -> str:
    raw = str(getattr(goal, "hardness", None) or "Primaer").strip().lower()
    return _HARDNESS_LABELS_TO_KEY.get(raw, "primaer")


# Konsistent zu services.portfolio_engine.GOAL_WEIGHT_BY_RANK Default 312bps
_DEFAULT_WEIGHT_BY_RANK = {1: 1875, 2: 938, 3: 469, 4: 312, 5: 312}


def _weight_bps(goal: Goal) -> int:
    if goal.weight_bps:
        return int(goal.weight_bps)
    rank = int(goal.rank or 5)
    return _DEFAULT_WEIGHT_BY_RANK.get(rank, 312)


# ============================================================================
# Datum / Horizon Helpers
# ============================================================================


def _parse_iso(value: str | None) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _resolve_target_year_index(goal: Goal, *, horizon_years: int) -> int:
    """Bestimmt 1-based Jahr-Index fuer Bewertung bzw. Outflow-Start.

    Semantik je nach Goal-Typ:
    - Wealth-Goals (Vermoegensziel/Kapitalerhalt): target_date = Auswertung
    - Renditeziel: immer horizon_years (annualized return ueber gesamten Horizont)
    - Einmalige_Ausgabe: target_date = Auswertung + Outflow-Jahr
    - Wiederkehrende_Ausgabe / Pensionsausgabe: start_date = Outflow-Beginn
      (target_date markiert das Ende, nicht die Bewertung)

    Diese Trennung ist wichtig fuer den Optimizer: bei Pensionsausgabe muss
    der Liability-Pfad ab dem Pensionsbeginn beginnen, nicht erst am Ende.
    """
    target_date = _parse_iso(goal.target_date)
    start_date = _parse_iso(goal.start_date)
    goal_type = _norm_goal_type(goal.goal_type)
    if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        anchor = start_date or target_date
    else:
        anchor = target_date
    if anchor:
        delta_days = (anchor - date.today()).days
        if delta_days <= 0:
            years = 1
        else:
            years = max(1, int((delta_days + 364) // 365))
    else:
        years = max(1, int(goal.horizon_years or 1))
    return max(1, min(years, int(horizon_years)))


def _outflow_duration_years(goal: Goal, *, target_year_index: int, horizon_years: int) -> int:
    """Anzahl Outflow-Jahre fuer wiederkehrende/Pensions-Goals innerhalb des Horizons.

    - Wenn start_date + target_date gesetzt: overlap mit [target_year_index..horizon_years]
    - Wenn is_ongoing: vom target_year_index bis horizon_years
    - Sonst: 1 Jahr
    """
    start_date = _parse_iso(goal.start_date)
    target_date = _parse_iso(goal.target_date)
    if start_date and target_date and target_date >= start_date:
        full_years = target_date.year - start_date.year + 1
        # ab target_year_index laufen, max bis horizon_years
        return max(0, min(full_years, horizon_years - target_year_index + 1))
    if int(goal.is_ongoing or 0):
        return max(1, horizon_years - target_year_index + 1)
    return 1


# ============================================================================
# Type-Normalization + Annualization
# ============================================================================


_GOAL_TYPE_NORMS = {
    "renditeziel": "Renditeziel",
    "kapitalerhalt": "Kapitalerhalt",
    "vermoegensziel": "Vermoegensziel",
    "vermögensziel": "Vermoegensziel",
    "einmalige_ausgabe": "Einmalige_Ausgabe",
    "einmaligeausgabe": "Einmalige_Ausgabe",
    "wiederkehrende_ausgabe": "Wiederkehrende_Ausgabe",
    "wiederkehrendeausgabe": "Wiederkehrende_Ausgabe",
    "pensionsausgabe": "Pensionsausgabe",
    "maximierung": "Maximierung",
}


def _norm_goal_type(goal_type: str | None) -> str:
    raw = str(goal_type or "").strip().lower().replace(" ", "_")
    return _GOAL_TYPE_NORMS.get(raw, "Maximierung")


def _annualize_amount_rappen(goal: Goal) -> int:
    """Konvertiert frequency-spezifischen Betrag in Jahresbetrag.

    Konsistent zu portfolio_engine._annualize_goal_amount.
    """
    amount = int(goal.target_amount_rappen or 0)
    freq = normalize_frequency(goal.frequency)
    if freq == "monatlich":
        return amount * 12
    if freq == "quartalsweise":
        return amount * 4
    if freq in ("halbjaehrlich", "halbjährlich"):
        return amount * 2
    return amount


# ============================================================================
# Inflation
# ============================================================================


def _cumulative_inflation_factor(years_to_compound: int, inflation_series_bps: list[int] | None) -> float:
    """Kumulativer Inflations-Faktor ueber n Jahre, ab Anfang der Series.

    Eigene Implementierung statt _compound_inflation_factor weil dieser einen
    falsy-Bug bei start_year=0 hat (`int(start_year or target_year)` faellt
    auf target_year zurueck wenn start_year=0).

    Wenn series kuerzer als years_to_compound: letzter Wert wird konstant
    fortgeschrieben (konsistent zur cashflow_timeline-Konvention).
    """
    if not inflation_series_bps or years_to_compound <= 0:
        return 1.0
    factor = 1.0
    for i in range(years_to_compound):
        infl = inflation_series_bps[i] if i < len(inflation_series_bps) else inflation_series_bps[-1]
        factor *= 1.0 + (int(infl or 0) / 10000.0)
    return factor


def _inflate_at_year(amount: int, year_index: int, inflation_series_bps: list[int] | None) -> int:
    """Multipliziert amount mit kumulativem Inflations-Faktor bis Jahr year_index.

    year_index ist 1-based (Jahr 1 = naechstes Jahr nach Start).
    Jahr 1 -> Faktor (1+infl[0]/10000), Jahr 5 -> (1+infl[0])*(1+infl[1])*..*(1+infl[4]).
    """
    factor = _cumulative_inflation_factor(year_index, inflation_series_bps)
    return int(round(amount * factor))


def _is_real_value_mode(goal: Goal) -> bool:
    return str(getattr(goal, "value_mode", "nominal") or "nominal").strip().lower() == "real"


# ============================================================================
# Per-Type Builders
# ============================================================================


def _build_renditeziel(goal: Goal, *, horizon_years: int) -> GoalLiability:
    """Renditeziel: kein Outflow, target ist annualized return in bps."""
    target_bps = max(0, int(goal.target_return_bps or 0))
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type="Renditeziel",
        target_kind="return_rate",
        target_amount_rappen=target_bps,  # in bps - Caller weiss aus target_kind
        target_year_index=horizon_years,
        liability_path_rappen=[0] * horizon_years,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
    )


def _build_wealth_target(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
) -> GoalLiability:
    """Kapitalerhalt / Vermoegensziel: Wealth-Schwelle in Zieljahr."""
    target = max(0, int(goal.target_wealth_rappen or 0))
    target_year = _resolve_target_year_index(goal, horizon_years=horizon_years)
    if _is_real_value_mode(goal):
        target = _inflate_at_year(target, target_year, inflation_series_bps)
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type=_norm_goal_type(goal.goal_type),
        target_kind="wealth_at_t",
        target_amount_rappen=target,
        target_year_index=target_year,
        liability_path_rappen=[0] * horizon_years,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
    )


def _build_einmalige_ausgabe(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
) -> GoalLiability:
    """Einmalige_Ausgabe: Outflow im Zieljahr."""
    amount = max(0, int(goal.target_amount_rappen or 0))
    target_year = _resolve_target_year_index(goal, horizon_years=horizon_years)
    if _is_real_value_mode(goal):
        amount = _inflate_at_year(amount, target_year, inflation_series_bps)
    path = [0] * horizon_years
    if 1 <= target_year <= horizon_years:
        path[target_year - 1] = amount
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type="Einmalige_Ausgabe",
        target_kind="cashflow_in_year",
        target_amount_rappen=amount,
        target_year_index=target_year,
        liability_path_rappen=path,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
    )


def _build_recurring_outflow(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
) -> GoalLiability:
    """Wiederkehrende_Ausgabe / Pensionsausgabe: jaehrlicher Outflow ab Start.

    Annualized amount wird mit Inflation hochgerechnet PRO JAHR (kumulativ),
    weil sowohl Lohn- als auch Lebenshaltungs-Indizes mehrjaehrig wachsen.
    """
    annual = _annualize_amount_rappen(goal)
    target_year = _resolve_target_year_index(goal, horizon_years=horizon_years)
    duration = _outflow_duration_years(
        goal, target_year_index=target_year, horizon_years=horizon_years,
    )
    path = [0] * horizon_years
    is_real = _is_real_value_mode(goal)
    cumulative_outflow = 0
    for offset in range(duration):
        year_idx = target_year + offset  # 1-based
        if year_idx > horizon_years:
            break
        amount = annual
        if is_real:
            amount = _inflate_at_year(annual, year_idx, inflation_series_bps)
        path[year_idx - 1] = amount
        cumulative_outflow += amount
    note = None
    full_duration = _outflow_duration_years(
        goal, target_year_index=1, horizon_years=99999,
    )
    if duration < full_duration:
        note = f"Bewertet fuer {duration} von {full_duration} Jahren (Horizont: {horizon_years})."
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type=_norm_goal_type(goal.goal_type),
        target_kind="outflow_stream",
        target_amount_rappen=cumulative_outflow,  # was muss insgesamt finanziert sein
        target_year_index=target_year,
        liability_path_rappen=path,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
        evaluation_note=note,
    )


def _build_maximierung(goal: Goal, *, horizon_years: int) -> GoalLiability:
    """Maximierung: triviale Liability, ist nur fuer Phase-2-Vol-Min relevant."""
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type="Maximierung",
        target_kind="maximize",
        target_amount_rappen=0,
        target_year_index=horizon_years,
        liability_path_rappen=[0] * horizon_years,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
    )


# ============================================================================
# Public Dispatch
# ============================================================================


def goal_to_liability(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None = None,
) -> GoalLiability:
    """Dispatch: Goal-Objekt -> GoalLiability fuer Optimizer.

    horizon_years: Anzahl simulierter Jahre. Goals die ueber den Horizont
    hinausgehen werden auf horizon_years geclamped (mit evaluation_note).

    inflation_series_bps: pro-Jahr Inflation in bps. Genutzt wenn
    goal.value_mode == "real". Default: kein Inflations-Adjustment.
    """
    goal_type = _norm_goal_type(goal.goal_type)
    horizon_years = max(1, int(horizon_years))

    if goal_type == "Renditeziel":
        return _build_renditeziel(goal, horizon_years=horizon_years)
    if goal_type in ("Kapitalerhalt", "Vermoegensziel"):
        return _build_wealth_target(
            goal, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
        )
    if goal_type == "Einmalige_Ausgabe":
        return _build_einmalige_ausgabe(
            goal, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
        )
    if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        return _build_recurring_outflow(
            goal, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
        )
    if goal_type == "Maximierung":
        return _build_maximierung(goal, horizon_years=horizon_years)
    # Unknown -> default to Maximierung
    return _build_maximierung(goal, horizon_years=horizon_years)


def goals_to_liabilities(
    goals: list[Goal],
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None = None,
) -> list[GoalLiability]:
    """Konvertiert Goal-Liste in Liability-Liste."""
    return [
        goal_to_liability(
            goal,
            horizon_years=horizon_years,
            inflation_series_bps=inflation_series_bps,
        )
        for goal in goals
    ]


def aggregate_liability_path(
    liabilities: list[GoalLiability],
    horizon_years: int,
) -> list[int]:
    """Aggregiert die Liability-Pfade aller Goals zu einem Gesamt-Outflow-Pfad.

    Wird als zusaetzlicher Cashflow-Subtraktor in der Szenario-Engine genutzt
    (parallel zum existing recurring cashflow_projection_series).
    """
    aggregated = [0] * horizon_years
    for liab in liabilities:
        for i, value in enumerate(liab.liability_path_rappen[:horizon_years]):
            aggregated[i] += int(value)
    return aggregated
