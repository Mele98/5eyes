"""Jahresweiser Ruhestandsstatus (DYNAMIC-RETIREMENT-PHASE-001).

Vorher war ``is_retired`` ein EINZIGER Wahrheitswert pro Lauf
(``Bewertungsjahr >= mandate.retirement_year``) und galt unveraendert fuer
ALLE Simulationsjahre: ein 55-jaehriger Mandant mit Pensionierung in 5 Jahren
war im Simulationsjahr 20 noch "erwerbstaetig", ein bereits pensionierter
Mandant galt umgekehrt nie als in Erwerbsphase -- es gab keinen
Phasenwechsel.

Dieses Modul leitet den Status je Simulationsjahr ab:
``retired[t] = (reference_year + t) >= retirement_year``. Es aendert KEINE
Regel und fuehrt KEINEN Glidepath ein; es sorgt nur dafuer, dass die
bestehenden phasenabhaengigen Regeln (``TaxContext.is_retired`` je
Steuerjahr) im jeweils richtigen Jahr greifen.

Quelle des Pensionierungsjahrs (Hauptperson), erste Treffer gewinnt:

1. ``mandate.retirement_year`` (direkt am Mandat erfasst),
2. aktuelle ``PlanningAssumption.retirement_age_primary`` + Geburtsjahr
   (``client.date_of_birth``, sonst ``mandate.client_birth_year``).

Partner: ``PlanningAssumption.retirement_age_partner`` +
``client.partner_date_of_birth``. Die rechenwirksame Serie ist die der
HAUPTPERSON -- ``TaxContext.age`` ist ebenfalls das Alter der Hauptperson
(services/tax/base.py), beide Felder beschreiben dieselbe Person. Die
Partner-Serie wird ausgewiesen (Reasoning/Audit); wie ein Haushalts-Status
aus zwei Personen gebildet wird, ist ein Owner-Entscheid und hier bewusst
nicht erfunden.

Fehlt das Pensionierungsjahr: bisheriges Verhalten (durchgehend "nicht
pensioniert") plus ausdruecklicher Hinweis.

Bezugsjahr ``t = 0`` ist das Bewertungsjahr des Mandats
(``services.mortality.horizon.mandate_reference_year``: ``opened_at``, sonst
heute) -- dieselbe Achse wie ``TaxContext.calendar_year``
(``base_calendar_year``), damit Steuerjahr und Phase je ``t`` dasselbe
Kalenderjahr meinen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

PRIMARY_SOURCE_MANDATE = "Mandat (Pensionierungsjahr)"
PRIMARY_SOURCE_PLANNING = "Planungsannahme (Rentenalter + Geburtsjahr)"


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _birth_year(date_of_birth: Any) -> int | None:
    text = str(date_of_birth or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        return year if year > 0 else None
    return None


@dataclass(frozen=True)
class RetirementPhase:
    """Aufgeloeste Pensionierungsjahre (Kalenderjahre) mit Quelle."""

    retirement_year: int | None
    source: str | None
    partner_retirement_year: int | None = None

    def series(self, reference_year: int, horizon_years: int) -> tuple[bool, ...] | None:
        """Ruhestandsstatus der Hauptperson je Simulationsjahr, None ohne Jahr."""
        return retirement_status_series(
            reference_year, horizon_years, self.retirement_year,
        )

    def partner_series(
        self, reference_year: int, horizon_years: int,
    ) -> tuple[bool, ...] | None:
        return retirement_status_series(
            reference_year, horizon_years, self.partner_retirement_year,
        )

    def is_retired_at(self, calendar_year: int) -> bool:
        """Status im Kalenderjahr; ohne Pensionierungsjahr bisheriges Verhalten (False)."""
        return bool(
            self.retirement_year is not None
            and int(calendar_year) >= int(self.retirement_year)
        )


def retirement_status_series(
    reference_year: int, horizon_years: int, retirement_year: int | None,
) -> tuple[bool, ...] | None:
    """``retired[t] = reference_year + t >= retirement_year`` fuer t = 0..H-1."""
    if retirement_year is None:
        return None
    horizon = max(0, int(horizon_years))
    return tuple(
        int(reference_year) + t >= int(retirement_year) for t in range(horizon)
    )


def is_retired_in_year(
    series: Iterable[bool] | None, year_index: int, *, default: bool = False,
) -> bool:
    """Status fuer Jahr ``year_index``; jenseits der Serie gilt der letzte Wert.

    Ohne Serie (``None``/leer): ``default`` -- das ist das statische
    Vor-Verhalten (ein ``is_retired`` fuer alle Jahre).
    """
    if series is None:
        return bool(default)
    values = tuple(series)
    if not values:
        return bool(default)
    index = min(max(0, int(year_index)), len(values) - 1)
    return bool(values[index])


def _resolve_client(mandate: Any, client: Any) -> Any:
    return client if client is not None else getattr(mandate, "client", None)


def _current_planning_assumption(mandate: Any) -> Any:
    """Aktuelle PlanningAssumption des Mandats ueber dessen Session, sonst None."""
    try:
        from sqlalchemy.orm import object_session

        session = object_session(mandate)
    except Exception:  # noqa: BLE001 - kein ORM-Objekt (Test-Double): keine PA
        return None
    if session is None:
        return None
    from models.wealth import PlanningAssumption

    return (
        session.query(PlanningAssumption)
        .filter(
            PlanningAssumption.mandate_id == mandate.id,
            PlanningAssumption.is_current == 1,
        )
        .order_by(PlanningAssumption.valid_from.desc())
        .first()
    )


def resolve_retirement_phase(
    mandate: Any,
    *,
    client: Any = None,
    planning_assumption: Any = None,
    load_planning_assumption: bool = True,
) -> RetirementPhase:
    """Pensionierungsjahr der Hauptperson (und des Partners) aufloesen."""
    client = _resolve_client(mandate, client)
    if planning_assumption is None and load_planning_assumption:
        planning_assumption = _current_planning_assumption(mandate)

    primary_birth = _birth_year(getattr(client, "date_of_birth", None)) or _positive_int(
        getattr(mandate, "client_birth_year", None)
    )
    partner_birth = _birth_year(getattr(client, "partner_date_of_birth", None))
    age_primary = _positive_int(getattr(planning_assumption, "retirement_age_primary", None))
    age_partner = _positive_int(getattr(planning_assumption, "retirement_age_partner", None))
    partner_year = (
        partner_birth + age_partner if partner_birth and age_partner else None
    )

    direct = _positive_int(getattr(mandate, "retirement_year", None))
    if direct is not None:
        return RetirementPhase(direct, PRIMARY_SOURCE_MANDATE, partner_year)
    if primary_birth and age_primary:
        return RetirementPhase(
            primary_birth + age_primary, PRIMARY_SOURCE_PLANNING, partner_year,
        )
    return RetirementPhase(None, None, partner_year)


def retirement_phase_note(
    phase: RetirementPhase, *, reference_year: int, horizon_years: int,
) -> str:
    """Reasoning-Satz: wann der Phasenwechsel im Simulationshorizont liegt."""
    horizon = max(1, int(horizon_years))
    last_year = int(reference_year) + horizon - 1
    if phase.retirement_year is None:
        text = (
            "Ruhestandsphase: kein Pensionierungsjahr erfasst (weder am Mandat "
            "noch als Rentenalter in den Planungsannahmen) -- alle "
            "Simulationsjahre werden wie bisher als Erwerbsphase behandelt. "
            "Bitte Pensionierungsjahr erfassen."
        )
    elif phase.retirement_year <= reference_year:
        text = (
            f"Ruhestandsphase: pensioniert seit {phase.retirement_year} "
            f"({phase.source}) -- alle Simulationsjahre "
            f"{reference_year}-{last_year} in der Ruhestandsphase."
        )
    elif phase.retirement_year > last_year:
        text = (
            f"Ruhestandsphase: Pensionierung {phase.retirement_year} "
            f"({phase.source}) liegt nach dem Simulationshorizont -- alle "
            f"Simulationsjahre {reference_year}-{last_year} in der Erwerbsphase."
        )
    else:
        text = (
            f"Ruhestandsphase: Pensionierung {phase.retirement_year} "
            f"({phase.source}) -- Erwerbsphase {reference_year}-"
            f"{phase.retirement_year - 1}, Ruhestandsphase ab "
            f"{phase.retirement_year}; phasenabhaengige Regeln (Steuerkontext) "
            "wechseln jahresgenau."
        )
    if phase.partner_retirement_year is not None:
        text += (
            f" Partner: Pensionierung {phase.partner_retirement_year} "
            "(ausgewiesen; rechenwirksam ist die Hauptperson)."
        )
    return text


RETIREMENT_PHASE_SNAPSHOT_SCHEME = "dynamic_retirement_phase_v1"


def retirement_phase_snapshot_fields(mandate: Any) -> dict:
    """Beitrag zum Input-Snapshot-Hash (CIO-Entscheid zu #670).

    Nur gesetzt, wenn ein Pensionierungsjahr aufloesbar ist -- genau dann
    weicht die Rechnung vom statischen Vor-Verhalten ab (Phasenserie,
    Entkopplung von der Steuerbasis, Planungsannahme als Quelle). Bestehende
    Allokationen solcher Mandate werden damit "Neuberechnung noetig";
    Mandate ohne Pensionierungsjahr behalten ihren Hash unveraendert.
    """
    if mandate is None:
        return {}
    phase = resolve_retirement_phase(mandate)
    if phase.retirement_year is None:
        return {}
    return {
        "retirement_phase": {
            "scheme": RETIREMENT_PHASE_SNAPSHOT_SCHEME,
            "retirement_calendar_year": int(phase.retirement_year),
        }
    }
