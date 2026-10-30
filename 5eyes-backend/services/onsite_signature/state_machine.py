"""Zustaende und erlaubte Uebergaenge der Vor-Ort-Signatur (SIGN-001).

Reine Tabelle ohne DB-Zugriff. Jedes Ereignis ist nur aus den hier
genannten Zustaenden erlaubt und fuehrt in genau einen Folgezustand.

    OPEN -> IDENTITY_VERIFIED -> CHALLENGE_ISSUED -> FACTOR_VERIFIED
         -> WITNESSED -> SIGNED -> DELIVERY_PENDING -> DELIVERED

* Fehlgeschlagene Challenge-Zustellung oder abgelehnter Kundenfaktor fuehren
  zurueck nach IDENTITY_VERIFIED (neue Challenge noetig, alte verbraucht).
* ABORTED ist terminal und aus jedem Zustand vor SIGNED erreichbar
  (Abbruch, Identitaetspruefung negativ, Dokument nach Anzeige geaendert).
* Ein Zustellfehler macht die Signatur nicht ungueltig: DELIVERY_FAILED
  bleibt in DELIVERY_PENDING; Folgeprozesse sind bis DELIVERED gesperrt.
"""
from __future__ import annotations

OPEN = "OPEN"
IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
CHALLENGE_ISSUED = "CHALLENGE_ISSUED"
FACTOR_VERIFIED = "FACTOR_VERIFIED"
WITNESSED = "WITNESSED"
SIGNED = "SIGNED"
DELIVERY_PENDING = "DELIVERY_PENDING"
DELIVERED = "DELIVERED"
ABORTED = "ABORTED"

STATES = (
    OPEN, IDENTITY_VERIFIED, CHALLENGE_ISSUED, FACTOR_VERIFIED, WITNESSED,
    SIGNED, DELIVERY_PENDING, DELIVERED, ABORTED,
)
PRE_SIGNATURE_STATES = (OPEN, IDENTITY_VERIFIED, CHALLENGE_ISSUED, FACTOR_VERIFIED, WITNESSED)
TERMINAL_STATES = (DELIVERED, ABORTED)
# Signiert, aber die Kundenkopie ist noch nicht nachweislich zugestellt.
FOLLOWUP_BLOCKING_STATES = (SIGNED, DELIVERY_PENDING)

EV_OPENED = "OPENED"
EV_IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
EV_CHALLENGE_ISSUED = "CHALLENGE_ISSUED"
EV_CHALLENGE_DELIVERY_FAILED = "CHALLENGE_DELIVERY_FAILED"
EV_FACTOR_VERIFIED = "FACTOR_VERIFIED"
EV_FACTOR_REJECTED = "FACTOR_REJECTED"
EV_WITNESSED = "WITNESSED"
EV_SIGNED = "SIGNED"
EV_DELIVERY_REQUESTED = "DELIVERY_REQUESTED"
EV_DELIVERY_FAILED = "DELIVERY_FAILED"
EV_DELIVERED = "DELIVERED"
EV_ABORTED = "ABORTED"

# event_type -> (erlaubte Ausgangszustaende, Folgezustand)
TRANSITIONS: dict[str, tuple[tuple[str | None, ...], str]] = {
    EV_OPENED: ((None,), OPEN),
    EV_IDENTITY_VERIFIED: ((OPEN,), IDENTITY_VERIFIED),
    EV_CHALLENGE_ISSUED: ((IDENTITY_VERIFIED, CHALLENGE_ISSUED), CHALLENGE_ISSUED),
    EV_CHALLENGE_DELIVERY_FAILED: ((IDENTITY_VERIFIED, CHALLENGE_ISSUED), IDENTITY_VERIFIED),
    EV_FACTOR_REJECTED: ((CHALLENGE_ISSUED,), IDENTITY_VERIFIED),
    EV_FACTOR_VERIFIED: ((CHALLENGE_ISSUED,), FACTOR_VERIFIED),
    EV_WITNESSED: ((FACTOR_VERIFIED,), WITNESSED),
    EV_SIGNED: ((WITNESSED,), SIGNED),
    EV_DELIVERY_REQUESTED: ((SIGNED,), DELIVERY_PENDING),
    EV_DELIVERY_FAILED: ((DELIVERY_PENDING,), DELIVERY_PENDING),
    EV_DELIVERED: ((DELIVERY_PENDING,), DELIVERED),
    EV_ABORTED: (PRE_SIGNATURE_STATES, ABORTED),
}
EVENT_TYPES = tuple(TRANSITIONS)


def next_state(current: str | None, event_type: str) -> str | None:
    """Folgezustand oder ``None``, wenn der Uebergang nicht erlaubt ist."""
    allowed_from, target = TRANSITIONS[event_type]
    return target if current in allowed_from else None
