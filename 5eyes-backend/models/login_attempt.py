"""AUTH-03: Persistenter/geteilter Brute-Force-Login-Guard.

Der In-Memory-Guard (``services/login_guard.py``) war pro Worker-Prozess
und ging bei Neustart verloren -> auf einer gehosteten App (mehrere Worker)
faktisch bypassbar (N-faches Budget) und nicht restart-fest.

Diese Models persistieren Zaehler + Lockout in der DB, sodass alle Worker
denselben Zustand teilen und ein Neustart den Lockout nicht zuruecksetzt.

- ``LoginAttempt``: eine Zeile pro Fehlversuch, ``key`` = normalisierter
  Guard-Key (IP oder Username, ``strip().lower()``), ``event_at`` = ISO-8601
  UTC-Zeitstempel (String, konsistent zu den uebrigen Zeit-Spalten der App).
- ``LoginLockout``: max. eine Zeile pro Key mit ``locked_until`` (ISO-String).

Schema-Disziplin: die Tabellen werden ausschliesslich ueber
``Base.metadata`` (``create_all``) angelegt — kein Eingriff in database.py.
Registrierung erfolgt in ``models/__init__.py`` bzw. ``init_db``-Import.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String

from database import Base


class LoginAttempt(Base):
    """Eine Zeile pro Login-Fehlversuch innerhalb des Zaehl-Fensters."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Normalisierter Guard-Key (IP oder Username, strip().lower()).
    key = Column(String, nullable=False, index=True)
    # ISO-8601 UTC-Zeitstempel des Fehlversuchs (lexikografisch sortierbar).
    event_at = Column(String, nullable=False)

    __table_args__ = (
        Index("ix_login_attempts_key_event_at", "key", "event_at"),
    )


class LoginLockout(Base):
    """Aktueller Lockout pro Key (max. eine Zeile je Key)."""

    __tablename__ = "login_lockouts"

    # Key ist Primaerschluessel -> hoechstens ein Lockout je Key (Upsert).
    key = Column(String, primary_key=True)
    # ISO-8601 UTC-Zeitstempel, bis wann der Key gesperrt ist.
    locked_until = Column(String, nullable=False)
