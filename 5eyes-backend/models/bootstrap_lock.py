"""AUTH-TEN-08 (Teil 2, Codex-Audit-Followup 2026-08-25): DB-seitiger
Bootstrap-Singleton.

``routers.auth._bootstrap_admin_lock`` (``threading.Lock``) serialisiert die
Ersteinrichtung bisher nur INNERHALB EINES Prozesses. Tier-1 (Electron
spawnt genau einen Backend-Prozess) ist damit vollstaendig abgedeckt --
Tier-2/3 (mehrere Backend-Worker-Prozesse hinter einem Load-Balancer) nicht:
zwei nahezu gleichzeitige POST /auth/bootstrap-admin auf zwei verschiedenen
Worker-Prozessen haetten je einen eigenen (leeren) Lock und koennten beide
den ``_bootstrap_required()``-Check bestehen, bevor irgendeiner committet --
zwei "erste" Admins.

Diese Tabelle haelt hoechstens eine Zeile mit fester ``id='singleton'``.
Der Bootstrap-Versuch, dessen Commit diese Zeile zuerst persistiert,
gewinnt; jeder weitere Versuch (im selben ODER einem anderen Prozess)
bekommt beim Commit eine ``IntegrityError`` (Primary-Key-Verletzung) und
wird von ``routers.auth.bootstrap_admin`` identisch zum bereits
bestehenden "Ersteinrichtung bereits abgeschlossen"-409 behandelt. Die
Zeile wird IM SELBEN Commit wie der neue Admin-User eingefuegt, damit ein
verlorenes Rennen (Rollback) BEIDE Inserts zurücknimmt -- kein verwaister
Admin ohne Lock-Zeile oder umgekehrt.

Schema-Disziplin: Tabelle wird ausschliesslich ueber ``Base.metadata``
(``create_all``) angelegt (SQLite/Tier-1), Registrierung via
``models/__init__.py`` (identisches Muster zu ``models/login_attempt.py``).
Fuer PostgreSQL siehe die begleitende Alembic-Revision.
"""
from __future__ import annotations

from sqlalchemy import Column, String

from database import Base


class BootstrapLock(Base):
    """Singleton-Zeile: genau ein Bootstrap-Vorgang darf jemals gewinnen."""

    __tablename__ = "bootstrap_lock"

    # Fester Wert ("singleton") -- der Primary-Key-Constraint IST der
    # atomare Claim-Mechanismus, siehe Modul-Docstring.
    id = Column(String, primary_key=True)
    created_at = Column(String, nullable=False)
