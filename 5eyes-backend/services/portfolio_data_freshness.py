"""Komponentenweise Depot-Frische (PORTFOLIO-DATA-001, Entscheiddokument 2026-10-27 §6).

Gemessen wird jede Komponente einzeln aus der Quelle: ``holdings_as_of``,
``cash_as_of``, ``price_as_of``, ``fx_as_of``, ``corporate_actions_checked_at``,
jeweils mit Quelle. Upload- oder Importzeit ist nie Ersatz fuer den fachlichen
Stichtag: fehlt der Stichtag, ist die Komponente fehlend, auch wenn eine
Uploadzeit vorliegt. Die aelteste zwingend benoetigte Komponente bestimmt die
Verwendbarkeit:

- ``final``: Alter <= ``final_max_business_days``;
- ``draft``: Alter <= ``draft_max_business_days`` (nur Entwurf/Szenario, sichtbar veraltet);
- ``blocked``: aelter, Stichtag fehlt/ungueltig/in der Zukunft, Quelle fehlt
  oder ein bekanntes Ereignis nach dem Stichtag verlangt neue Daten.

Das Alter wird in Bankarbeitstagen des Policy-Kalenders gemessen, das
Referenzdatum ist das lokale Datum des Beratungszeitpunkts in der
Policy-Zeitzone. Zeitpunkte ohne Zeitzone werden abgelehnt.
"""
from __future__ import annotations

from datetime import date, datetime

from services.bank_calendar import business_days_elapsed
from services.portfolio_data_policy import PortfolioDataPolicy

USABILITY_FINAL = "final"
USABILITY_DRAFT = "draft"
USABILITY_BLOCKED = "blocked"

# Welche Komponente ein bekanntes Ereignis nach dem Stichtag ungueltig macht.
EVENT_COMPONENTS = {
    "trade": ("holdings_as_of", "cash_as_of"),
    "cash_movement": ("cash_as_of",),
    "corporate_action": ("holdings_as_of", "price_as_of", "corporate_actions_checked_at"),
    "material_change": (
        "holdings_as_of", "cash_as_of", "price_as_of", "fx_as_of", "corporate_actions_checked_at",
    ),
}


class FreshnessInputError(ValueError):
    """Zeitpunkt nicht auswertbar (ohne Zeitzone, unlesbar)."""


def _local_date(value, policy: PortfolioDataPolicy) -> tuple[date, datetime | None]:
    """Datum in der Policy-Zeitzone; ``(datum, aware_datetime | None)``.

    Ein reines Datum (``YYYY-MM-DD``) ist bereits das fachliche Datum. Ein
    Zeitpunkt braucht eine Zeitzone und wird in die Policy-Zeitzone umgerechnet.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        return value, None
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if len(text) == 10:
            try:
                return date.fromisoformat(text), None
            except ValueError as exc:
                raise FreshnessInputError(f"Ungueltiges Datum: {text!r}") from exc
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FreshnessInputError(f"Ungueltiger Zeitpunkt: {text!r}") from exc
    else:
        raise FreshnessInputError("Zeitpunkt fehlt.")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise FreshnessInputError("Zeitpunkt ohne Zeitzone ist nicht eindeutig.")
    local = moment.astimezone(policy.zone())
    return local.date(), local


def _event_after(event_value, component_value, policy: PortfolioDataPolicy) -> bool:
    """Liegt das Ereignis nach dem Komponenten-Stichtag?

    Mit zwei Zeitpunkten wird exakt verglichen. Ist eine Seite nur ein Datum,
    zaehlt ein Ereignis am selben Tag konservativ als danach (der Tagesstichtag
    belegt nicht, ob das Ereignis enthalten ist).
    """
    event_day, event_moment = _local_date(event_value, policy)
    comp_day, comp_moment = _local_date(component_value, policy)
    if event_moment is not None and comp_moment is not None:
        return event_moment > comp_moment
    return event_day >= comp_day


def assess_freshness(
    components: dict,
    *,
    advice_at,
    policy: PortfolioDataPolicy,
    events: list[dict] | None = None,
) -> dict:
    """Bewertet die Frische der Depotdaten.

    ``components``: ``{name: {"as_of": ..., "source": ..., ["uploaded_at": ...]}}``.
    ``advice_at``: Beratungszeitpunkt mit Zeitzone.
    ``events``: bekannte Ereignisse ``{"type": ..., "occurred_at": ...}``.
    """
    reference, _ = _local_date(advice_at, policy)
    calendar = policy.calendar()
    details: dict[str, dict] = {}
    blocking: list[str] = []
    ages: dict[str, int] = {}

    for name in policy.required_components:
        entry = components.get(name) or {}
        detail = {
            "component": name,
            "as_of": entry.get("as_of"),
            "source": entry.get("source"),
            "age_business_days": None,
            "status": None,
        }
        if entry.get("uploaded_at") is not None:
            detail["uploaded_at_ignored"] = True
        if entry.get("not_applicable") is True:
            # z. B. fx_as_of bei einem Depot nur in Basiswaehrung; nur mit Begruendung.
            reason = str(entry.get("reason") or "").strip()
            detail["status"] = "not_applicable" if reason else "not_applicable_without_reason"
            detail["reason"] = reason or None
            if not reason:
                blocking.append(f"{name}:{detail['status']}")
            details[name] = detail
            continue
        if entry.get("as_of") in (None, ""):
            detail["status"] = "missing_as_of"
        elif not str(entry.get("source") or "").strip():
            detail["status"] = "missing_source"
        else:
            try:
                as_of_day, _ = _local_date(entry["as_of"], policy)
            except FreshnessInputError as exc:
                detail["status"] = "invalid_as_of"
                detail["error"] = str(exc)
            else:
                if as_of_day > reference:
                    detail["status"] = "as_of_in_future"
                else:
                    age = business_days_elapsed(calendar, as_of_day, reference)
                    detail["age_business_days"] = age
                    ages[name] = age
                    detail["status"] = "ok"
        if detail["status"] != "ok":
            blocking.append(f"{name}:{detail['status']}")
        details[name] = detail

    refresh_required: list[dict] = []
    for event in events or []:
        event_type = event.get("type")
        affected = EVENT_COMPONENTS.get(event_type)
        if affected is None:
            blocking.append(f"event:unknown_type:{event_type}")
            continue
        for name in affected:
            if name not in details or details[name]["status"] != "ok":
                continue
            try:
                after = _event_after(event.get("occurred_at"), components[name]["as_of"], policy)
            except FreshnessInputError:
                after = True
            if after:
                refresh_required.append({"type": event_type, "component": name})
    if refresh_required:
        blocking.append("refresh_required_after_event")

    oldest = max(ages, key=lambda n: (ages[n], n)) if ages else None
    oldest_age = ages[oldest] if oldest else None
    if oldest is None and not blocking:
        blocking.append("no_dated_component")
    if blocking:
        usability = USABILITY_BLOCKED
    elif oldest_age <= policy.final_max_business_days:
        usability = USABILITY_FINAL
    elif oldest_age <= policy.draft_max_business_days:
        usability = USABILITY_DRAFT
    else:
        usability = USABILITY_BLOCKED
        blocking.append(f"{oldest}:older_than_draft_limit")

    calendar_notes = []
    if not calendar.holidays_modelled:
        calendar_notes.append(getattr(calendar, "limitation_note", "Feiertage nicht modelliert."))

    return {
        "usability": usability,
        "stale": usability != USABILITY_FINAL,
        "reference_date": reference.isoformat(),
        "oldest_component": oldest,
        "oldest_age_business_days": oldest_age,
        "components": details,
        "refresh_required": refresh_required,
        "blocking_reasons": blocking,
        "calendar": {
            "calendar_id": calendar.calendar_id,
            "timezone": policy.timezone,
            "holidays_modelled": calendar.holidays_modelled,
        },
        "calendar_notes": calendar_notes,
        "policy_version": policy.version,
    }
