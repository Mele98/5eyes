"""Roadmap #28 (Standpunkt 2026-08-07): Refresh-Token-Rotation.

Siehe models/refresh_token.py fuer die Sicherheits-Begruendung (opake,
gehashte Tokens statt JWT; Rotation + Reuse-Detection nach RFC 6749 Sec.
10.4). Dieses Modul ist die einzige Stelle, die refresh_tokens liest/
schreibt -- Router bleiben duenne Wrapper.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import update as _sa_update
from sqlalchemy.orm import Session

from config import settings
from models.refresh_token import RefreshToken
from models.users import User


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class IssuedRefreshToken:
    raw_token: str
    row: RefreshToken


class RefreshTokenReuseDetected(Exception):
    """Ein bereits verbrauchter/revozierter Refresh-Token wurde erneut
    praesentiert -- starkes Diebstahl-Signal. Der Aufrufer (Router) MUSS
    daraufhin 401 antworten; die gesamte Token-Familie wurde bereits
    revoziert, bevor diese Exception geworfen wird."""


def issue_refresh_token(
    db: Session,
    user: User,
    *,
    family_id: str | None = None,
    ip: str | None = None,
) -> IssuedRefreshToken:
    """Stellt einen neuen Refresh-Token aus. family_id=None -> neue Familie
    (Login). family_id gesetzt -> Fortsetzung einer Rotations-Kette."""
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=max(1, int(settings.refresh_token_expire_days)))
    row = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw),
        family_id=family_id or str(uuid.uuid4()),
        created_at=_now(),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
        created_ip=ip,
    )
    db.add(row)
    return IssuedRefreshToken(raw_token=raw, row=row)


def rotate_refresh_token(
    db: Session,
    raw_token: str,
    *,
    ip: str | None = None,
) -> tuple[User, IssuedRefreshToken] | None:
    """Verifiziert + rotiert einen Refresh-Token.

    Returns (user, neuer_token) bei Erfolg, None wenn der Token unbekannt,
    abgelaufen oder der zugehoerige User inaktiv/geloescht ist.

    Wirft RefreshTokenReuseDetected (und revoziert dabei die GESAMTE
    Familie), wenn der praesentierte Token bereits zuvor verbraucht wurde --
    das ist der Kernschutz der Rotation: ein Angreifer mit einer alten Kopie
    der Kette loest beim naechsten Versuch die Revocation der kompletten
    Kette aus (inkl. des Tokens, den der LEGITIME Client aktuell besitzt --
    bewusst, siehe RFC 6749 Sec. 10.4: im Zweifel beide Seiten aussperren
    und zum Neu-Login zwingen ist sicherer als eine kompromittierte Kette
    unbemerkt weiterlaufen zu lassen).
    """
    token_hash = _sha256((raw_token or "").strip())
    if not token_hash or not raw_token:
        return None
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row is None:
        return None

    expires_at = _parse_iso(row.expires_at)
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        return None

    if row.revoked_at is not None:
        # Reuse eines bereits verbrauchten/revozierten Tokens -- ganze
        # Familie sofort stilllegen (auch bereits unbenutzte Nachfolger).
        revoke_family(db, row.family_id)
        db.commit()
        raise RefreshTokenReuseDetected(f"refresh token reuse for family {row.family_id}")

    user = db.query(User).filter(User.id == row.user_id, User.deleted_at.is_(None)).first()
    if user is None or not user.is_active:
        return None

    # AUTH-TEN-02 (Codex-Audit 2026-08-25): atomarer CAS statt read-then-write.
    # Ohne dies koennten zwei parallele Rotationsversuche mit demselben Token
    # BEIDE die revoked_at-Pruefung oben bestehen, bevor irgendeiner committet,
    # und je einen eigenen Nachfolger erzeugen (das vom Audit reproduzierte
    # Zwei-Transaktionen-Race). Die WHERE-Klausel macht das Revozieren zur
    # exklusiven, atomaren Bedingung: unter SQLite serialisiert die Whole-DB-
    # Schreibsperre (+ PRAGMA busy_timeout) konkurrierende Writer, unter
    # PostgreSQL das Zeilen-Lock der UPDATE-Anweisung selbst -- in beiden
    # Faellen sieht der zweite Writer nach Erhalt der Sperre bereits
    # revoked_at IS NOT NULL und aktualisiert 0 Zeilen (rowcount=0 unten).
    now_iso = _now()
    result = db.execute(
        _sa_update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now_iso)
    )
    if result.rowcount == 0:
        # Race verloren -- ein konkurrierender Rotationsversuch war schneller.
        # Gemaess demselben Reuse-Vertrag wie oben: ganze Familie stilllegen
        # (inkl. des vom Gewinner ausgestellten Nachfolgers) und 401 ausloesen.
        revoke_family(db, row.family_id)
        db.commit()
        raise RefreshTokenReuseDetected(
            f"refresh token rotation race lost for family {row.family_id}"
        )

    new_token = issue_refresh_token(db, user, family_id=row.family_id, ip=ip)
    # ORM-Objekt synchron halten -- das obige db.execute(update(...)) ist ein
    # Core-Statement und aktualisiert `row` im Identity-Map nicht automatisch.
    row.revoked_at = now_iso
    row.replaced_by_id = new_token.row.id
    return user, new_token


def revoke_family(db: Session, family_id: str) -> int:
    """Revoziert alle noch aktiven (revoked_at IS NULL) Tokens einer Familie.
    Gibt die Anzahl betroffener Zeilen zurueck."""
    rows = db.query(RefreshToken).filter(
        RefreshToken.family_id == family_id,
        RefreshToken.revoked_at.is_(None),
    ).all()
    now = _now()
    for row in rows:
        row.revoked_at = now
    return len(rows)


def revoke_all_for_user(db: Session, user_id: str) -> int:
    """Logout/Passwortwechsel: alle aktiven Refresh-Tokens EINES Users
    revozieren (alle Sessions/Geraete), konsistent zum bestehenden
    User.token_revoked_before-Mechanismus (AUTH-04), der ebenfalls user-weit
    statt nur die aktuelle Session trifft."""
    rows = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    ).all()
    now = _now()
    for row in rows:
        row.revoked_at = now
    return len(rows)
