"""Canonical fail-closed validation for optimizer-relevant goal inputs."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from services.cashflow_timeline import SUPPORTED_FREQUENCIES, normalize_frequency


class GoalInputError(ValueError):
    """A persisted or submitted goal cannot be interpreted unambiguously."""


_MOJIBAKE_REPLACEMENTS = {
    "Ã¤": "ae",
    "Ã¶": "oe",
    "Ã¼": "ue",
    "Ã„": "ae",
    "Ã–": "oe",
    "Ãœ": "ue",
    "ÃƒÂ¤": "ae",
    "ÃƒÂ¶": "oe",
    "ÃƒÂ¼": "ue",
}


def _fold(value: Any) -> str:
    text = str(value or "").strip().lower()
    for broken, replacement in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken.lower(), replacement)
    return (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace(" ", "_")
    )


def _get(goal: Any, field: str) -> Any:
    if isinstance(goal, Mapping):
        return goal.get(field)
    return getattr(goal, field, None)


def _strict_int(
    value: Any,
    *,
    field: str,
    minimum: int | None = None,
    maximum: int | None = None,
    nullable: bool = False,
) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoalInputError(f"{field} muss eine Ganzzahl sein.")
    if minimum is not None and value < minimum:
        raise GoalInputError(f"{field} muss mindestens {minimum} sein.")
    if maximum is not None and value > maximum:
        raise GoalInputError(f"{field} darf hoechstens {maximum} sein.")
    return value


def _parse_date(value: Any, *, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise GoalInputError(f"{field} muss ein ISO-Datum sein.")
    raw = value.strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise GoalInputError(f"{field} muss ein gueltiges ISO-Datum sein.") from exc


def validate_goal_model_input(goal: Any) -> None:
    """Validate the complete goal state consumed by allocation engines.

    The validator deliberately accepts the historic ASCII spellings used in
    persisted CH rows (``Primaer``, ``Beratungsvermoegen``), but never invents
    a meaning for unknown values.
    """

    label = str(_get(goal, "label") or "Ziel").strip()
    prefix = f"Ziel '{label}'"
    goal_type = _fold(_get(goal, "goal_type"))
    supported_types = {
        "kapitalerhalt",
        "vermoegensziel",
        "einmalige_ausgabe",
        "wiederkehrende_ausgabe",
        "pensionsausgabe",
        "renditeziel",
        "maximierung",
    }
    if goal_type not in supported_types:
        raise GoalInputError(
            f"{prefix}: unbekannter Zieltyp {_get(goal, 'goal_type')!r}."
        )

    family = _fold(_get(goal, "goal_family"))
    allowed_families = {
        "kapitalerhalt": {"vermoegen", "vermoegensaufbau"},
        "vermoegensziel": {"vermoegen", "vermoegensaufbau"},
        "einmalige_ausgabe": {"cashflow", "konsum", "lebenshaltung", "liquiditaet"},
        "wiederkehrende_ausgabe": {"cashflow", "konsum", "lebenshaltung", "liquiditaet"},
        "pensionsausgabe": {"cashflow", "lebenshaltung"},
        "renditeziel": {"rendite"},
        "maximierung": {"maximierung"},
    }
    if family not in allowed_families[goal_type]:
        raise GoalInputError(
            f"{prefix}: goal_family {_get(goal, 'goal_family')!r} passt "
            f"nicht zum Zieltyp {_get(goal, 'goal_type')!r}."
        )

    rank = _strict_int(_get(goal, "rank"), field=f"{prefix} rank", minimum=1)
    del rank
    _strict_int(
        _get(goal, "weight_bps"),
        field=f"{prefix} weight_bps",
        minimum=0,
        maximum=10_000,
        nullable=True,
    )
    _strict_int(
        _get(goal, "success_probability_min_x100"),
        field=f"{prefix} success_probability_min_x100",
        minimum=0,
        maximum=10_000,
        nullable=True,
    )
    _strict_int(
        _get(goal, "probability_pct"),
        field=f"{prefix} probability_pct",
        minimum=0,
        maximum=100,
        nullable=True,
    )
    horizon = _strict_int(
        _get(goal, "horizon_years"),
        field=f"{prefix} horizon_years",
        minimum=1,
        nullable=True,
    )

    hardness = _fold(_get(goal, "hardness"))
    if hardness not in {"hart", "primaer", "opportunistisch"}:
        raise GoalInputError(
            f"{prefix}: hardness muss Hart, Primaer oder Opportunistisch sein."
        )
    scope = _fold(_get(goal, "goal_scope"))
    if scope not in {"beratungsvermoegen", "gesamtvermoegen"}:
        raise GoalInputError(
            f"{prefix}: goal_scope muss Beratungs- oder Gesamtvermoegen sein."
        )
    value_mode = _fold(_get(goal, "value_mode"))
    if value_mode not in {"nominal", "real"}:
        raise GoalInputError(
            f"{prefix}: value_mode muss nominal oder real sein."
        )

    ongoing_raw = _get(goal, "is_ongoing")
    if isinstance(ongoing_raw, bool):
        ongoing = ongoing_raw
    elif isinstance(ongoing_raw, int) and ongoing_raw in (0, 1):
        ongoing = bool(ongoing_raw)
    else:
        raise GoalInputError(f"{prefix}: is_ongoing muss exakt 0 oder 1 sein.")

    start = _parse_date(_get(goal, "start_date"), field=f"{prefix} start_date")
    target_date = _parse_date(
        _get(goal, "target_date"), field=f"{prefix} target_date"
    )
    if start and target_date and target_date < start:
        raise GoalInputError(
            f"{prefix}: target_date darf nicht vor start_date liegen."
        )

    target_amount = _strict_int(
        _get(goal, "target_amount_rappen"),
        field=f"{prefix} target_amount_rappen",
        nullable=True,
    )
    target_wealth = _strict_int(
        _get(goal, "target_wealth_rappen"),
        field=f"{prefix} target_wealth_rappen",
        nullable=True,
    )
    target_return = _strict_int(
        _get(goal, "target_return_bps"),
        field=f"{prefix} target_return_bps",
        nullable=True,
    )
    frequency_raw = _get(goal, "frequency")
    frequency = normalize_frequency(frequency_raw)

    def require_evaluation_timing() -> None:
        # Non-recurring goals are evaluated at target_date or at an explicit
        # model horizon.  start_date is not consumed as their evaluation
        # anchor by the liability builders and therefore must not make an
        # otherwise anchorless raw/legacy row look valid.
        if horizon is None and target_date is None:
            raise GoalInputError(
                f"{prefix}: Ziel benoetigt horizon_years oder target_date; "
                "start_date allein ist fuer diesen Zieltyp kein Timing-Anker."
            )

    def require_stream_timing() -> None:
        if horizon is None and target_date is None and start is None:
            raise GoalInputError(
                f"{prefix}: Ziel benoetigt horizon_years, target_date oder start_date."
            )

    def forbid(value: Any, field: str) -> None:
        if value is not None:
            raise GoalInputError(
                f"{prefix}: {field} ist fuer diesen Zieltyp nicht erlaubt."
            )

    if goal_type == "renditeziel":
        if hardness == "hart":
            raise GoalInputError(f"{prefix}: Renditeziel darf nicht hart sein.")
        if target_return is None or target_return <= 0:
            raise GoalInputError(f"{prefix}: positive Zielrendite fehlt.")
        forbid(target_amount, "target_amount_rappen")
        forbid(target_wealth, "target_wealth_rappen")
        if frequency_raw not in (None, "") or ongoing:
            raise GoalInputError(f"{prefix}: Renditeziel darf nicht wiederkehrend sein.")
        require_evaluation_timing()
    elif goal_type in {"kapitalerhalt", "vermoegensziel"}:
        if target_wealth is None or target_wealth <= 0:
            raise GoalInputError(f"{prefix}: positives Zielvermoegen fehlt.")
        forbid(target_amount, "target_amount_rappen")
        forbid(target_return, "target_return_bps")
        if frequency_raw not in (None, "") or ongoing:
            raise GoalInputError(f"{prefix}: Vermoegensziel darf nicht wiederkehrend sein.")
        require_evaluation_timing()
    elif goal_type == "einmalige_ausgabe":
        if target_amount is None or target_amount <= 0:
            raise GoalInputError(f"{prefix}: positiver Zielbetrag fehlt.")
        forbid(target_wealth, "target_wealth_rappen")
        forbid(target_return, "target_return_bps")
        if frequency_raw not in (None, "") or ongoing:
            raise GoalInputError(f"{prefix}: einmalige Ausgabe darf nicht wiederkehrend sein.")
        require_evaluation_timing()
    elif goal_type in {"wiederkehrende_ausgabe", "pensionsausgabe"}:
        if target_amount is None or target_amount <= 0:
            raise GoalInputError(f"{prefix}: positiver Zielbetrag fehlt.")
        forbid(target_wealth, "target_wealth_rappen")
        forbid(target_return, "target_return_bps")
        if frequency not in SUPPORTED_FREQUENCIES or frequency == "einmalig":
            raise GoalInputError(f"{prefix}: ungueltige wiederkehrende Frequenz.")
        require_stream_timing()
        if not ongoing and target_date is None:
            raise GoalInputError(
                f"{prefix}: ein endliches wiederkehrendes Ziel benoetigt "
                "target_date; ohne Enddatum muss is_ongoing=1 sein."
            )
    elif goal_type == "maximierung":
        forbid(target_amount, "target_amount_rappen")
        forbid(target_wealth, "target_wealth_rappen")
        forbid(target_return, "target_return_bps")
        if frequency_raw not in (None, "") or ongoing:
            raise GoalInputError(f"{prefix}: Maximierung darf nicht wiederkehrend sein.")

    pillar = str(_get(goal, "pension_pillar") or "").strip()
    if goal_type == "pensionsausgabe":
        if pillar and pillar not in {"AHV", "BVG", "3a", "1e", "FZG"}:
            raise GoalInputError(f"{prefix}: unbekannte Vorsorge-Saeule {pillar!r}.")
    elif pillar:
        raise GoalInputError(
            f"{prefix}: pension_pillar ist nur fuer Pensionsausgabe erlaubt."
        )
