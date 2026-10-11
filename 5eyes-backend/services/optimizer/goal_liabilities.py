"""Goal -> Liability-Pfad-Konversion fuer Stochastic Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec. 6)

Jedes Goal wird in eine `GoalLiability` konvertiert, die der Optimizer als
Constraint nutzen kann:

- liability_path_rappen[i]: positiver Outflow im KALENDERJAHR
  (date.today().year + i) fuer Spending-Goals (Einmalige_Ausgabe,
  Wiederkehrende, Pensionsausgabe).
  Fuer Wealth-Goals (Vermoegensziel, Kapitalerhalt) und Renditeziel ist der
  Pfad reine Nullen — die Bewertung erfolgt am target_year_index.

- target_amount_rappen: was muss erreicht werden (Wealth-Schwelle / Annualisierter
  Cashflow / Return-Bps je nach target_kind).

- target_year_index: 1-based Jahr-Index ab dem das Goal bewertet wird.

- liability_path_rappen: 0-based, list[0] = Outflow im LAUFENDEN Kalenderjahr,
  list[horizon_years - 1] = Outflow im letzten simulierten Jahr.

  GOAL-RECURRENCE-SCHEDULE-001 / ADR-2 (2026-10-11): list[0] war bis dahin
  "Outflow im naechsten Jahr" und der Startindex ein Jahrestag-Bucket
  (``calendar_years_until``), obwohl der Docstring schon damals Konsistenz
  zu services.cashflow_timeline behauptete. Die Cashflow-Serie
  (``net_cashflow_series``), der Inflationspfad und die Steuerjahre
  (``TaxContext.calendar_year = base_calendar_year + t``) liegen aber alle
  auf der KALENDERJAHR-Achse, und der Wealth-Schritt verrechnet sie mit
  diesem Pfad auf demselben Index
  (``wealth[:, t+1] = ... + cashflow[t] - liability[t]``). Der Outflow
  landete deshalb in 5 von 8 geprueften Startdaten ein Jahr zu frueh.
  Jetzt gilt die behauptete Konsistenz tatsaechlich.

Inflation: wird angewendet wenn goal.value_mode == "real". Default: nominal.
Spending-Goals werden ohne explizite real/nominal-Trennung behandelt — der
Cashflow ist immer der heutige Wert, und mit value_mode='real' erfolgt die
Hochrechnung mit der CMA-Inflation. Konsistent zu B1 (cashflow_timeline).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Sequence

from models.wealth import Goal
from services.calendar_horizon import calendar_years_until
from services.cashflow_timeline import (
    normalize_frequency,
    recurring_occurrence_series,
)


# ============================================================================
# Public DataClass
# ============================================================================


@dataclass(frozen=True)
class GoalLiability:
    """Liability-Beschreibung fuer den Optimizer.

    target_kind:
        "wealth_at_t"          - Pfad-Wealth in Jahr T muss >= target sein
        "cashflow_in_year"     - einmaliger Outflow ist im Pfad abgezogen;
                                 Wealth direkt danach muss >= 0 sein
        "outflow_stream"       - kumulierte Outflows ueber Jahre 1..T abdeckbar
        "return_rate"          - annualized Return ueber Horizont >= target_bps
        "maximize"             - keine Constraint, nur in Vol-Min relevant
        "state_funded"         - extern/staatlich gedeckt; keine Portfolio-Liability
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
    success_probability_min_x100: int | None = None
    evaluation_note: str | None = None
    # GOAL-FUNDING-PRIORITY-001 (CERT-GOAL-FUNDING-001):
    # `rank` ist die einzige Funding-Prioritaet (aufsteigend, 1 = hoechste
    # Prioritaet). Default 1 nur fuer direkte Dataclass-Konstruktion ohne
    # Goal-Kontext (z.B. in bestehenden Unit-Tests) -- der Produktionspfad
    # (goal_to_liability/goals_to_liabilities) uebernimmt immer goal.rank.
    rank: int = 1
    # Kumulativer Prioritaets-Scope-Pfad (Spec Sec. 4.2: S_r = {h | rank(h) <=
    # r}), vorberechnet von goals_to_liabilities() ueber den vollen Goal-Satz
    # eines Aufrufs. None, wenn diese Liability ausserhalb eines Batch-Aufrufs
    # (goal_to_liability() einzeln, oder direkte Dataclass-Konstruktion in
    # Tests) entstanden ist -- dann existiert kein Geschwister-Kontext und es
    # wird KEINE Priority-Protection angewendet (kein stiller Fallback auf
    # eine erfundene Annahme).
    priority_scope_liability_path_rappen: list[int] | None = None
    # Der volle, ungeschuetzte gemeinsame Aggregat-Pfad (= aggregate_liability_
    # path() ueber ALLE Goals desselben Batch-Aufrufs). Identisch fuer jede
    # Liability im selben Batch. Wird benoetigt, um aus dem bereits realisierten
    # (kontaminierten) Wealth-Pfad die Wachstumsfaktoren pro Jahr zurueckzurechnen
    # und denselben Pfad mit dem priorisierten Liability-Scope neu aufzubauen --
    # OHNE eine zweite Zufallsziehung und OHNE spaetere Returns anzusehen (die
    # Returns sind durch den gegebenen wealth_paths bereits realisiert).
    joint_liability_path_rappen: list[int] | None = None


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


# Validierung 2026-06-11: MUSS mit services.portfolio_engine.GOAL_WEIGHT_BY_RANK
# uebereinstimmen (geometrisches Halbieren je Rank; weight_bps/10000 = Fraktion,
# engine-spec Sektion 4). Vorher divergent ({1:1875,...}) bei gleichzeitig falschem
# "konsistent"-Kommentar -> Goals wurden im Optimizer-Objective anders gewichtet als
# in der Mandate-Score-Aggregation. Konsistenz via test_goal_rank_weight_parity.
_DEFAULT_WEIGHT_BY_RANK = {1: 10000, 2: 5000, 3: 2500, 4: 1250, 5: 625}


def _resolve_rank(goal: Goal) -> int:
    """Liest goal.rank fuer GoalLiability.rank.

    GOAL-FUNDING-PRIORITY-001: rank ist die einzige Funding-Prioritaet.
    Produktions-Goal-Zeilen haben eine NOT-NULL `rank`-Spalte (models/wealth.py
    Goal.rank); dieser Fallback greift nur fuer Alt-Aufrufer ausserhalb des
    ORM-Modells. Strikte Fail-Closed-Validierung auf Eindeutigkeit/Gueltigkeit
    ueber ein ganzes Mandat (Spec Sec. 4.1/11.4) ist bewusst NICHT Teil dieses
    Pakets -- siehe PR-Beschreibung/Report fuer den verbleibenden Scope.
    """
    raw = getattr(goal, "rank", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def _weight_bps(goal: Goal) -> int:
    if goal.weight_bps:
        return int(goal.weight_bps)
    rank = int(goal.rank or 5)
    return _DEFAULT_WEIGHT_BY_RANK.get(rank, 312)


def _success_probability_min_x100(goal: Goal, *, default_value: int) -> int:
    raw = getattr(goal, "success_probability_min_x100", None)
    if raw is None:
        return int(default_value)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default_value)
    return max(0, min(10000, value))


def _goal_probability_factor(goal: Goal) -> float:
    """Validierung 2026-06-11 (engine-spec 4.4 / Sprint U-B6): bedingte Goals
    pro-rata gewichten. Spiegelt services.portfolio_engine._goal_probability_factor,
    damit Optimizer-Liability und Reserve-Engine dieselbe Gewichtung nutzen.
    probability_pct in [0,100]; None/ungueltig -> 1.0 (sicher eintretend).
    """
    raw = getattr(goal, "probability_pct", None)
    if raw is None:
        return 1.0
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(100.0, float(pct))) / 100.0


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


def _resolve_target_year_index(
    goal: Goal,
    *,
    horizon_years: int,
    clamp_to_horizon: bool = True,
) -> int:
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
        years = max(1, calendar_years_until(anchor))
    else:
        years = max(1, int(goal.horizon_years or 1))
    years = max(1, years)
    if clamp_to_horizon:
        return min(years, int(horizon_years))
    return years


# GOAL-RECURRENCE-SCHEDULE-001 / ADR-2c (2026-10-11): _outflow_duration_years
# ist ersatzlos ENTFERNT. Die Funktion beantwortete "wie viele Jahre zahlt
# dieses Ziel" mit ``target_date.year - start_date.year + 1``, also mit der
# Anzahl beruehrter Kalenderjahr-LABELS. Unter Occurrence-Semantik hat die
# Frage keine sinnvolle Antwort mehr: ein Teiljahr ist ein Bucket, aber nicht
# ein Jahresbetrag. Wer den Umfang eines Stroms braucht, nimmt die Summe des
# Pfads aus recurring_occurrence_series() -- Geld, nicht Jahre.


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
    normalized = _GOAL_TYPE_NORMS.get(raw)
    if normalized is None:
        raise ValueError(
            f"Unbekannter Zieltyp {goal_type!r}; eine stille Umdeutung zu "
            "'Maximierung' ist nicht zulaessig."
        )
    return normalized


# GOAL-RECURRENCE-SCHEDULE-001 / ADR-2c (2026-10-11): _annualize_amount_rappen
# ist ersatzlos ENTFERNT. "Betrag x 12" unterstellt zwoelf Faelligkeiten im
# Jahr; in einem Teiljahr sind es weniger. Die Annualisierung entsteht jetzt
# dort, wo sie hingehoert: aus der gezaehlten Anzahl Faelligkeiten pro
# Kalenderjahr in recurring_occurrence_series().


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


def _uses_total_wealth_scope(goal: Goal) -> bool:
    """True for the explicit Gesamtvermoegen goal scope."""
    return "gesamt" in str(
        getattr(goal, "goal_scope", "") or ""
    ).strip().lower()


def _is_state_funded_pension(goal: Goal) -> bool:
    """PENSION-AHV-001 (Phase 0, 2026-09): liefert IMMER False.

    Frueher (siehe git history): True fuer pension_pillar='AHV' +
    goal_type='Pensionsausgabe', wodurch der Optimizer fuer dieses Goal
    target_kind='state_funded' setzte -- eine Liability mit target=0 und
    success_probability_min_x100=10000, ausschliesslich weil das Label
    'AHV' gesetzt war. Es existiert kein Feld/keine Reconciliation, die
    eine tatsaechliche erwartete AHV-Rente erfasst (schemas/wealth.py
    GoalCreate/-Update haben nur das reine Pillar-Label, keinen Betrag) --
    die frueher automatisch erzeugte 100%-Deckung war also unbelegt.
    Konservativer Fix: kein automatischer Staatsfinanzierungs-Bonus mehr;
    ein AHV-Pensionsausgabe-Goal durchlaeuft denselben
    _build_recurring_outflow()-Pfad wie jedes andere Wiederkehrende_Ausgabe/
    Pensionsausgabe-Goal, bis eine echte Phase-1-Benefit-Reconciliation
    existiert. _build_state_funded_pension() bleibt unten als vorbereiteter
    Re-Entry-Punkt fuer Phase 1 stehen, wird aber aktuell nie mehr aufgerufen.
    """
    return False


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
        success_probability_min_x100=_success_probability_min_x100(goal, default_value=5000),
    )


def _build_wealth_target(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: Sequence[int] | None = None,
) -> GoalLiability:
    """Kapitalerhalt / Vermoegensziel: Wealth-Schwelle in Zieljahr."""
    target = max(0, int(goal.target_wealth_rappen or 0))
    target_year = _resolve_target_year_index(goal, horizon_years=horizon_years)
    if _is_real_value_mode(goal):
        target = _inflate_at_year(target, target_year, inflation_series_bps)
    note = None
    if _uses_total_wealth_scope(goal):
        # The simulated wealth path contains advised assets only.  Reporting
        # treats external assets conservatively as deterministic, zero-real-
        # growth wealth.  Convert the total-wealth goal to the exact residual
        # that the advised portfolio must fund so optimizer and reporting use
        # the same economic base.
        if external_wealth_series_rappen is not None:
            if target_year >= len(external_wealth_series_rappen):
                raise ValueError(
                    "External-wealth series does not cover the goal horizon"
                )
            external_projected = int(
                external_wealth_series_rappen[target_year]
            )
            note = (
                "Gesamtvermoegensziel: die kanonische externe Vermoegens-, "
                "Verbindlichkeits- und Transfer-Serie wurde angerechnet."
            )
        else:
            external_projected = _inflate_at_year(
                max(0, int(external_wealth_rappen or 0)),
                target_year,
                inflation_series_bps,
            )
            note = (
                "Gesamtvermoegensziel: externe Vermoegenswerte wurden "
                "deterministisch mit Inflation angerechnet."
            )
        target = max(0, target - external_projected)
    # Expected-funding semantics for contingent goals: first determine the
    # actual advisory funding gap, then apply the occurrence probability.  If
    # probability were applied before external assets, a 50%-contingent total-
    # wealth goal could incorrectly collapse to zero although a positive
    # advisory residual remains.
    target = int(round(target * _goal_probability_factor(goal)))
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
        success_probability_min_x100=_success_probability_min_x100(goal, default_value=8000),
        evaluation_note=note,
    )


def _build_einmalige_ausgabe(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
) -> GoalLiability:
    """Einmalige_Ausgabe: Outflow im Kalenderjahr des Zieldatums.

    GOAL-RECURRENCE-SCHEDULE-001 / ADR-2 (2026-10-11): auch dieser Outflow
    liegt jetzt auf der KALENDERJAHR-Achse. Er landet im selben
    ``liability_path_rappen``-Array wie die wiederkehrenden Stroeme und wird
    vom Vermoegen auf demselben Index abgezogen wie Cashflows, Inflation und
    Steuern; zwei Konventionen in EINEM Array (aggregate_liability_path
    summiert sie) waeren schlechter als jede einzelne. Vorher kam der Index
    aus ``_resolve_target_year_index`` und war damit ein Jahrestag-Bucket --
    eine Ausgabe vom Februar wurde dem Vorjahr belastet.

    Die Inflation zaehlt entsprechend ab dem laufenden Kalenderjahr: Faktor
    1.0 im Bucket ``base_year`` (User-Eingabe ist ein heutiger Wert), wie
    bei Cashflows (B1) und beim wiederkehrenden Pfad.
    """
    amount = max(0, int(goal.target_amount_rappen or 0))
    base_year = date.today().year
    target_date = _parse_iso(goal.target_date)
    if target_date is not None:
        target_year = _calendar_bucket_index(target_date, base_year)
    else:
        # Kein Zieldatum: dieselbe Legacy-Lesart wie beim wiederkehrenden
        # Pfad -- horizon_years als "in so vielen Jahren faellig".
        target_year = max(1, int(goal.horizon_years or 1))
    if _is_real_value_mode(goal):
        amount = _inflate_at_year(amount, target_year - 1, inflation_series_bps)
    amount = int(round(amount * _goal_probability_factor(goal)))  # bedingte Goals pro-rata
    path = [0] * horizon_years
    if 1 <= target_year <= horizon_years:
        path[target_year - 1] = amount
    note = None
    if target_year > horizon_years:
        note = (
            "Zahlungszeitpunkt liegt ausserhalb des Optimizer-Horizonts "
            f"(Horizont: {horizon_years} Jahre); keine In-Horizon-Liability."
        )
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
        success_probability_min_x100=_success_probability_min_x100(goal, default_value=8000),
        evaluation_note=note,
    )


def _calendar_bucket_index(anchor: date | None, base_year: int) -> int:
    """1-based Kalenderjahr-Bucket eines Datums auf der Engine-Achse.

    Bucket 1 ist das laufende Kalenderjahr (``base_year``) -- dieselbe
    Achse wie ``net_cashflow_series`` (Index 0 = ``base_year``), nur
    1-based wie ``target_year_index``.
    """
    if anchor is None:
        return 1
    return int(anchor.year) - int(base_year) + 1


def _recurring_outflow_note(
    goal: Goal,
    *,
    start_date: date | None,
    target_date: date | None,
    is_ongoing: bool,
    base_year: int,
    horizon_years: int,
    in_horizon_total: int,
    per_occurrence: int,
    prob_factor: float,
) -> str | None:
    """Offenlegung, wenn der gebuchte Strom nicht der ganze Strom ist.

    Die Dauer wird NICHT mehr in Jahren ausgewiesen, sondern als Betrag:
    unter Occurrence-Semantik sind zwei "Jahre" verschieden viel Geld, wenn
    eines ein Teiljahr ist. Eine Jahreszahl waere hier die Angabe, die den
    Fehler ueberhaupt erst erzeugt hat.
    """
    last_bucket_year = int(base_year) + int(horizon_years) - 1

    # ADR-3-Grenzfall, bewusst explizit: ein Strom, dessen Fenster
    # vollstaendig vor dem laufenden Kalenderjahr endet, hat keine
    # In-Horizon-Verbindlichkeit mehr. Vorher hob ``max(1, ...)`` den
    # Startindex auf Jahr 1 und belebte den abgelaufenen Strom als neue
    # Zahlungspflicht wieder (Audit Repro 3). Jetzt ist er null -- aber
    # nicht stillschweigend: solange ADR-3 (Goal-Lifecycle) nicht
    # implementiert ist, gibt es keinen Zustand, der "abgelaufen, nie
    # bestaetigt" von "erfuellt" unterscheidet, und die Luecke muss am
    # Ziel sichtbar sein statt als 0 zu verschwinden.
    if (
        not is_ongoing
        and target_date is not None
        and int(target_date.year) < int(base_year)
    ):
        return (
            "Zahlungsfenster endete "
            f"{target_date.isoformat()}, also vor dem laufenden "
            f"Kalenderjahr {base_year}: keine In-Horizon-Verbindlichkeit. "
            "Lifecycle-Status (erfuellt / storniert / ueberfaellig) ist "
            "nicht erfasst -- Ziel vor der Beratung bestaetigen."
        )

    if start_date is not None and int(start_date.year) > last_bucket_year:
        return (
            "Zahlungsbeginn liegt ausserhalb des Optimizer-Horizonts "
            f"(Horizont: {horizon_years} Jahre); keine In-Horizon-Liability."
        )

    # Horizont schneidet den Strom ab: vollen Strom gegenrechnen.
    if (
        target_date is not None
        and int(target_date.year) > last_bucket_year
        and per_occurrence
    ):
        full_years = int(target_date.year) - int(base_year) + 1
        full_series = recurring_occurrence_series(
            amount_per_occurrence_rappen=per_occurrence,
            frequency=goal.frequency,
            start_date=start_date,
            end_date=target_date,
            is_ongoing=is_ongoing,
            base_year=base_year,
            horizon_years=full_years,
            inflation_series_bps=None,  # nominal, nur fuer das Verhaeltnis
        )
        full_total = int(round(sum(full_series) * prob_factor))
        if full_total > 0 and in_horizon_total < full_total:
            share = 100.0 * in_horizon_total / full_total
            return (
                f"Bewertet werden {share:.0f} % des Zahlungsstroms "
                f"(bis {last_bucket_year}); der Strom laeuft bis "
                f"{target_date.isoformat()}, also ueber den Horizont von "
                f"{horizon_years} Jahren hinaus."
            )
    return None


def _build_recurring_outflow(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None,
) -> GoalLiability:
    """Wiederkehrende_Ausgabe / Pensionsausgabe: Outflow ab Start.

    GOAL-RECURRENCE-SCHEDULE-001 / ADR-2 (Owner-Entscheid 2026-10-11): die
    Betraege kommen jetzt aus dem kanonischen Occurrence-Enumerator
    (services/cashflow_timeline.py::recurring_occurrence_series), nicht mehr
    aus "annualisierter Betrag x Anzahl beruehrter Kalenderjahr-Labels".
    Die alte Rechnung buchte in ein Teiljahr den VOLLEN Jahresbetrag und
    ueberzeichnete die Verbindlichkeit damit um bis zu 64 % (gemessen:
    monatlich 2026-06-15..2028-03-15 = 22 Zahlungen, gebucht wurden 36).

    Zugleich ist der Bucket-Index jetzt das Kalenderjahr -- dieselbe Achse,
    auf der Cashflow-, Inflations- und Steuerserie schon liegen und auf der
    der Wealth-Schritt alle verrechnet. Vorher war der Startindex ein
    Jahrestag-Bucket (``calendar_years_until``), wodurch der Outflow in
    5 von 8 geprueften Startdaten ein Jahr zu FRUEH vom Vermoegen abgezogen
    wurde.

    Inflation (value_mode='real') wird pro Bucket kumulativ angewandt, mit
    Faktor 1.0 im laufenden Kalenderjahr -- B1-Konvention, wie bei Cashflows.
    """
    start_date = _parse_iso(goal.start_date)
    target_date = _parse_iso(goal.target_date)
    is_ongoing = bool(int(goal.is_ongoing or 0))
    base_year = date.today().year

    # Legacy-Fallback OHNE Startdatum. start_date, target_date und
    # horizon_years sind alle nullable (models/wealth.py), diese Zeilen-Form
    # ist also erreichbar. Die abgeloeste Herleitung nahm hier
    # ``first_year_index = max(1, goal.horizon_years)``, las also
    # horizon_years als "in so vielen Jahren wird das Ziel faellig" -- fuer
    # eine Pensionsausgabe der Pensionierungszeitpunkt. Diese Lesart bleibt
    # erhalten und wird nur auf die Kalenderjahr-Achse uebersetzt.
    #
    # Sie NICHT zu erhalten waere keine Korrektur, sondern eine Erfindung in
    # die andere Richtung: ohne Anker ab dem laufenden Jahr zu enumerieren
    # haette die AHV-Verbindlichkeit im Regressionsfall verzehnfacht
    # (3'000'000 -> 30'000'000 Rappen), ohne dass ein Feld das hergibt.
    derived_start_from_horizon = False
    if start_date is None and target_date is None:
        offset_years = max(1, int(goal.horizon_years or 1)) - 1
        start_date = date(base_year + offset_years, 1, 1)
        derived_start_from_horizon = True
    is_real = _is_real_value_mode(goal)
    prob_factor = _goal_probability_factor(goal)  # bedingte Goals pro-rata

    # Der Periodenbetrag, NICHT der annualisierte: die Annualisierung
    # entsteht im Enumerator aus der echten Anzahl Faelligkeiten pro Jahr.
    per_occurrence = int(goal.target_amount_rappen or 0)
    raw_series = recurring_occurrence_series(
        amount_per_occurrence_rappen=per_occurrence,
        frequency=goal.frequency,
        start_date=start_date,
        end_date=target_date,
        is_ongoing=is_ongoing,
        base_year=base_year,
        horizon_years=horizon_years,
        inflation_series_bps=inflation_series_bps if is_real else None,
    )
    path = [int(round(value * prob_factor)) for value in raw_series]
    cumulative_outflow = sum(path)

    # Auswertungsindex: 1-based Bucket des ersten tatsaechlichen Outflows.
    # Vorher war das der Jahrestag-Startindex, auch wenn in jenem Bucket
    # gar keine Faelligkeit lag.
    first_paid = next((i for i, value in enumerate(path) if value > 0), None)
    if first_paid is not None:
        target_year = first_paid + 1
    else:
        # Keine Faelligkeit im Horizont. Der Index wird hier NICHT auf den
        # Horizont geklemmt: ``target_year_index > horizon_years`` ist das
        # etablierte Signal "liegt ausserhalb des Horizonts", auf das
        # Konsumenten pruefen. Ein geklemmter Wert haette ein Ziel jenseits
        # des Horizonts wie ein Ziel im letzten Horizontjahr aussehen
        # lassen.
        target_year = max(1, _calendar_bucket_index(start_date or target_date, base_year))

    note = _recurring_outflow_note(
        goal,
        start_date=start_date,
        target_date=target_date,
        is_ongoing=is_ongoing,
        base_year=base_year,
        horizon_years=horizon_years,
        in_horizon_total=cumulative_outflow,
        per_occurrence=per_occurrence,
        prob_factor=prob_factor,
    )
    if derived_start_from_horizon and cumulative_outflow > 0:
        # Der Zahlungsplan steht hier auf einer Annahme, nicht auf Daten.
        disclosure = (
            "Kein Start- und kein Enddatum erfasst; der Zahlungsbeginn ist "
            f"aus horizon_years={goal.horizon_years} abgeleitet "
            f"(Kalenderjahr {start_date.year}). Datum am Ziel erfassen, "
            "damit der Strom nicht auf einer Annahme beruht."
        )
        note = f"{note} {disclosure}" if note else disclosure
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
        success_probability_min_x100=_success_probability_min_x100(goal, default_value=8000),
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
        success_probability_min_x100=None,
    )


def _build_state_funded_pension(
    goal: Goal,
    *,
    horizon_years: int,
) -> GoalLiability:
    """Represent an AHV goal truthfully without charging the portfolio."""
    return GoalLiability(
        goal_id=str(goal.id),
        label=str(goal.label or ""),
        goal_type="Pensionsausgabe",
        target_kind="state_funded",
        target_amount_rappen=0,
        target_year_index=_resolve_target_year_index(
            goal, horizon_years=horizon_years
        ),
        liability_path_rappen=[0] * horizon_years,
        hardness_key=_hardness_key(goal),
        weight_bps=_weight_bps(goal),
        success_probability_min_x100=10000,
        evaluation_note=(
            "Staatlich finanzierte AHV-Leistung; keine Finanzierung aus dem "
            "Beratungsportfolio erforderlich."
        ),
    )


# ============================================================================
# Public Dispatch
# ============================================================================


def goal_to_liability(
    goal: Goal,
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None = None,
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: Sequence[int] | None = None,
) -> GoalLiability:
    """Dispatch: Goal-Objekt -> GoalLiability fuer Optimizer.

    horizon_years: Anzahl simulierter Jahre. Goals die ueber den Horizont
    hinausgehen werden auf horizon_years geclamped (mit evaluation_note).

    inflation_series_bps: pro-Jahr Inflation in bps. Genutzt wenn
    goal.value_mode == "real". Default: kein Inflations-Adjustment.
    """
    goal_type = _norm_goal_type(goal.goal_type)
    horizon_years = max(1, int(horizon_years))

    if _is_state_funded_pension(goal):
        built = _build_state_funded_pension(goal, horizon_years=horizon_years)
    elif goal_type == "Renditeziel":
        built = _build_renditeziel(goal, horizon_years=horizon_years)
    elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
        built = _build_wealth_target(
            goal,
            horizon_years=horizon_years,
            inflation_series_bps=inflation_series_bps,
            external_wealth_rappen=external_wealth_rappen,
            external_wealth_series_rappen=external_wealth_series_rappen,
        )
    elif goal_type == "Einmalige_Ausgabe":
        built = _build_einmalige_ausgabe(
            goal, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
        )
    elif goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        built = _build_recurring_outflow(
            goal, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
        )
    elif goal_type == "Maximierung":
        built = _build_maximierung(goal, horizon_years=horizon_years)
    else:
        raise ValueError(f"Nicht unterstuetzter Zieltyp {goal_type!r}.")
    return replace(built, rank=_resolve_rank(goal))


def goals_to_liabilities(
    goals: list[Goal],
    *,
    horizon_years: int,
    inflation_series_bps: list[int] | None = None,
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: Sequence[int] | None = None,
) -> list[GoalLiability]:
    """Konvertiert Goal-Liste in Liability-Liste.

    GOAL-FUNDING-PRIORITY-001 (CERT-GOAL-FUNDING-001): zusaetzlich zur reinen
    Typ-Konvertierung wird hier -- einmalig, ueber den ganzen Batch -- pro
    Goal der kumulative Prioritaets-Scope-Pfad gebildet (Spec Sec. 4.2):

        S_r = { h | rank(h) <= r }
        L_r(t) = Summe liability_h(t) fuer h in S_r

    sowie der volle, ungeschuetzte gemeinsame Aggregatpfad (identisch zu
    aggregate_liability_path() ueber denselben Batch). Beide werden auf jeder
    GoalLiability abgelegt, damit services.optimizer.objective
    goal_probability_per_path() aus dem bereits realisierten (kontaminierten)
    Wealth-Pfad die prioritaetsgeschuetzte Trajektorie je Goal zurueckrechnen
    kann, ohne eine zweite Zufallsziehung zu benoetigen. Ties (gleicher Rang)
    landen im selben Scope -- Permutation der Eingabeliste aendert weder
    Scope-Zuordnung noch Rueckgabereihenfolge (Hard Invariant #2).
    """
    built = [
        goal_to_liability(
            goal,
            horizon_years=horizon_years,
            inflation_series_bps=inflation_series_bps,
            external_wealth_rappen=external_wealth_rappen,
            external_wealth_series_rappen=external_wealth_series_rappen,
        )
        for goal in goals
    ]
    if not built:
        return built
    joint_path = aggregate_liability_path(built, horizon_years)
    scoped: list[GoalLiability] = []
    for liab in built:
        scope_path = [0] * horizon_years
        for sibling in built:
            if sibling.rank > liab.rank:
                continue
            for i, value in enumerate(sibling.liability_path_rappen[:horizon_years]):
                scope_path[i] += int(value)
        scoped.append(replace(
            liab,
            priority_scope_liability_path_rappen=scope_path,
            joint_liability_path_rappen=list(joint_path),
        ))
    return scoped


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
