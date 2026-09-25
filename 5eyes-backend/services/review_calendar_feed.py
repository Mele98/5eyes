"""REVIEW-CALENDAR-001 (Kontrollrunde 2026-09-24): persoenlicher .ics-
Kalender-Abo-Feed fuer faellige/bald faellige Review-Trigger.

Nutzer-Anforderung: der Berater soll auf faellige Jahresreviews/Drift-/
Ereignis-Trigger automatisch (via Outlook-Kalenderabo) aufmerksam gemacht
werden, ohne dass 5eyes eine kostenpflichtige oder registrierungspflichtige
Microsoft-Graph-Anbindung braucht. Outlook kann einen beliebigen HTTP(S)-
Endpoint, der einen gueltigen .ics-Text liefert, als "Internetkalender
abonnieren" und aktualisiert ihn danach selbststaendig periodisch.

Da Outlook beim automatischen Abo-Refresh keine interaktive Anmeldung
durchfuehren kann, traegt die Abo-URL selbst ein Geheimnis (Token in der
Query) -- analog zu reset_token_hash/invite_token_hash wird nur der
sha256-Hash gespeichert, der Klartext-Token wird ausschliesslich einmalig
bei der Erzeugung zurueckgegeben (services/account_recovery.py-Muster).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.clients import Client
from models.mandates import Mandate
from models.review import ReviewTrigger
from models.users import User


# Trigger-Status, die eine tatsaechliche Handlungsaufforderung fuer den
# Berater darstellen -- "Erledigt" (kein next_due_at mehr fuer nicht-
# wiederkehrende Trigger) wird bewusst NICHT im Kalender gefuehrt.
ACTIVE_CALENDAR_STATUS_VALUES = ("Aktiv", "Ausgelöst")

# Erinnerungsalarm: so viele Tage vor Faelligkeit soll Outlook erinnern,
# damit der Berater den Kunden noch rechtzeitig fuer einen Termin anrufen
# kann.
REMINDER_DAYS_BEFORE = 14


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def issue_calendar_feed_token(user: User) -> str:
    """Erzeugt (oder ersetzt) den persoenlichen Feed-Token. Klartext wird
    NUR hier zurueckgegeben -- ein bereits bestehendes Outlook-Abo mit dem
    alten Token wird dadurch bewusst invalidiert (Token-Rotation)."""
    token = secrets.token_urlsafe(32)
    user.calendar_feed_token_hash = _sha256(token)
    user.calendar_feed_token_created_at = _now_iso()
    return token


def revoke_calendar_feed_token(user: User) -> None:
    user.calendar_feed_token_hash = None
    user.calendar_feed_token_created_at = None


def resolve_user_by_calendar_feed_token(db: Session, token: str) -> User | None:
    raw = (token or "").strip()
    if not raw:
        return None
    hashed = _sha256(raw)
    return (
        db.query(User)
        .filter(
            User.calendar_feed_token_hash == hashed,
            User.deleted_at.is_(None),
            User.is_active == 1,
        )
        .first()
    )


def _ics_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _all_day_event(
    *,
    uid: str,
    dtstamp: str,
    due_date: str,
    summary: str,
    description: str,
) -> list[str]:
    due_compact = due_date.replace("-", "")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{due_compact}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(description)}",
        "CATEGORIES:5Eyes,Review,Compliance",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_escape(summary)}",
        f"TRIGGER:-P{REMINDER_DAYS_BEFORE}D",
        "END:VALARM",
        "END:VEVENT",
    ]
    return lines


def build_ics_feed(db: Session, user: User) -> str:
    """Baut den .ics-Kalendertext fuer alle faelligen/bald faelligen Review-
    Trigger der Mandate, bei denen `user` aktuell der zugewiesene Berater
    ist (Client.advisor_id == user.id) -- bewusst NICHT der vollstaendige
    Tenant-/Admin-Sichtbarkeitsbereich, sondern der persoenliche
    Arbeitsvorrat des Beraters (analoges Scoping zu routers/clients.py::
    list_clients ohne Admin-Override)."""
    rows = (
        db.query(ReviewTrigger, Mandate, Client)
        .join(Mandate, Mandate.id == ReviewTrigger.mandate_id)
        .join(Client, Client.id == Mandate.client_id)
        .filter(
            Client.advisor_id == user.id,
            ReviewTrigger.deleted_at.is_(None),
            ReviewTrigger.status.in_(ACTIVE_CALENDAR_STATUS_VALUES),
            ReviewTrigger.next_due_at.isnot(None),
        )
        .order_by(ReviewTrigger.next_due_at)
        .all()
    )

    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//5Eyes WealthArchitekten//Review-Kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:5Eyes Reviews",
        "X-PUBLISHED-TTL:PT12H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for trigger, mandate, client in rows:
        due_date = str(trigger.next_due_at or "")[:10]
        if not due_date:
            continue
        client_label = " ".join(
            part for part in (client.first_name, client.last_name) if part
        ).strip() or client.client_number
        summary = f"5Eyes Review: {trigger.trigger_name} -- {client_label}"
        description_parts = [
            f"Mandat: {mandate.mandate_number}",
            f"Trigger-Typ: {trigger.trigger_type}",
            f"Status: {trigger.status}",
        ]
        if trigger.triggered_value:
            description_parts.append(f"Details: {trigger.triggered_value}")
        description = " | ".join(description_parts)
        lines.extend(
            _all_day_event(
                uid=f"5eyes-trigger-{trigger.id}@wealtharchitekten.ch",
                dtstamp=dtstamp,
                due_date=due_date,
                summary=summary,
                description=description,
            )
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
