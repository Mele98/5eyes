"""Roadmap #28 (Standpunkt 2026-08-07): Refresh-Token-Rotation.

Bisher gab es nur ein einzelnes, mittellebiges JWT-Access-Token (Default
480 Minuten, Production-Cap 1440 Minuten) -- kein Refresh-Mechanismus. Ein
geleaktes Access-Token blieb bis zum Ablauf voll gueltig.

Dieses Model speichert Refresh-Tokens NICHT als JWT (das waere unrevozierbar
ohne Blacklist), sondern als opake, zufaellige Strings, deren SHA-256-Hash
in der DB liegt -- identisches Muster zu ``users.invite_token_hash`` und
den Password-Reset-Tokens in ``services/account_recovery.py``.

Rotation + Reuse-Detection (OAuth2-Refresh-Token-Best-Practice, RFC 6749
Sec. 10.4): jede erfolgreiche Nutzung eines Refresh-Tokens verbraucht es
(``revoked_at`` gesetzt, ``replaced_by_id`` zeigt auf den Nachfolger) und
stellt einen NEUEN Refresh-Token mit derselben ``family_id`` aus. Wird ein
bereits verbrauchter (``revoked_at`` gesetzt) Token erneut praesentiert,
ist das ein starkes Diebstahl-Signal (ein Angreifer hat eine aeltere Kopie
der Token-Kette) -- der Aufrufer (``services/refresh_tokens.py``) revoziert
dann die GESAMTE Familie, nicht nur den einen Token.

Schema-Disziplin: Tabelle wird ausschliesslich ueber ``Base.metadata``
(``create_all``) angelegt, Registrierung via ``models/__init__.py``
(identisches Muster zu ``models/login_attempt.py``).
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, String

from database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    # SHA-256-Hex-Digest des rohen Tokens -- der rohe Wert wird NIE gespeichert,
    # nur einmalig bei der Ausstellung an den Client zurueckgegeben.
    token_hash = Column(String, nullable=False, unique=True, index=True)
    # Gemeinsame ID fuer eine ganze Rotations-Kette (Login -> Refresh -> Refresh
    # -> ...). Ermoeglicht "gesamte Kette revozieren" bei Reuse-Detection oder
    # Logout, ohne jeden einzelnen Vorgaenger-Token nachschlagen zu muessen.
    family_id = Column(String, nullable=False, index=True)
    created_at = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    # None = noch gueltig/unbenutzt. Gesetzt = verbraucht (normale Rotation)
    # ODER vorzeitig revoziert (Logout, Reuse-Detection, Passwortwechsel).
    revoked_at = Column(String)
    # Zeigt auf den Nachfolger-Token nach einer Rotation (Audit-Trail der Kette).
    replaced_by_id = Column(String)
    created_ip = Column(String)

    # family_id hat bereits ueber Column(index=True) einen Index -- ein
    # zweiter expliziter Index mit demselben auto-generierten Namen
    # (ix_refresh_tokens_family_id) wuerde beim CREATE TABLE kollidieren.
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
    )
