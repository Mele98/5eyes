"""AUTH-03: Persistenter/geteilter Brute-Force-Login-Guard.

Frueher hielt ``LoginAttemptGuard`` Zaehler + Lockout in In-Memory-Dicts
(``self._failures`` / ``self._locked_until``). Auf einer gehosteten App mit
mehreren Worker-Prozessen war das Limit dadurch effektiv ``N x max`` (jeder
Worker zaehlt separat) und ein Neustart (Deploy/Crash) hat den Lockout
zurueckgesetzt -> Brute-Force/Credential-Stuffing praktikabel.

Diese Fassung persistiert Zaehler + Lockout in der DB (Tabellen
``login_attempts`` / ``login_lockouts``, siehe ``models/login_attempt.py``),
sodass alle Worker denselben Zustand teilen und Lockouts restart-fest sind.

Design / Vertrag:
- Das oeffentliche Interface (``check`` / ``register_failure`` /
  ``register_success`` + ``LoginGuardDecision`` mit ``allowed`` /
  ``retry_after_seconds`` / ``reason``) bleibt 100% stabil — die Aufrufer in
  ``routers/auth.py`` muessen NICHT angepasst werden.
- Jeder Aufruf holt sich eine eigene Connection ueber eine standalone Engine
  (Muster analog ``services/account_recovery.py``), damit Aufrufer keine
  Session uebergeben muessen und laufende Transaktionen nicht gestoert werden.
- Key-Normalisierung (``strip().lower()``) bleibt.
- ``login_rate_limit_enabled = False`` -> kompletter Bypass (Tier-1/Tests).
- Zaehlung/Upsert laufen in EINER Transaktion pro Aufruf -> korrekt unter
  Nebenlaeufigkeit (``register_failure``).
- Lazy-Cleanup abgelaufener Zeilen in ``check``/``register_failure`` (kein
  Scheduler).

Fallback-Entscheidung (dokumentiert):
- Ist das DB-Backend nicht verfuegbar (Connection-/OperationalError), wird
  **fail-open** gewaehlt: ``check``/``register_failure`` liefern
  ``allowed=True`` und der Fehler wird geloggt. Begruendung: ein hartes
  fail-closed wuerde bei DB-Ausfall JEDEN Login (auch legitime Berater/Kunden)
  total aussperren — fuer eine Beratungs-App das groessere Betriebsrisiko.
  Der Login selbst prueft weiterhin Passwort/2FA; der Guard ist eine
  zusaetzliche Rate-Limit-Schicht, kein Auth-Ersatz.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateIndex, CreateTable

from config import settings

logger = logging.getLogger(__name__)

# Standalone-Engine-Cache (pro DB-URL), analog zur App-Engine, aber bewusst
# getrennt, damit die Guard-Transaktionen keine App-Session teilen.
_ENGINE_CACHE: dict[str, object] = {}


def _get_guard_engine():
    """Liefert eine standalone SQLAlchemy-Engine fuer den Guard.

    Nutzt dieselbe DB wie die App (``build_database_url``), aber eine eigene
    (gecachte) Engine. In Tests kann diese Funktion monkeypatch-t werden bzw.
    ``LoginAttemptGuard`` erhaelt eine Engine via Konstruktor-Argument.
    """
    from database import build_database_url, build_connect_args

    url = build_database_url(
        db_path=settings.db_path, db_key=getattr(settings, "db_key", None)
    )
    eng = _ENGINE_CACHE.get(url)
    if eng is None:
        from sqlalchemy import create_engine

        kwargs = {"connect_args": build_connect_args(db_key=getattr(settings, "db_key", None))}
        module = None
        try:
            from database import _sqlcipher_enabled  # type: ignore

            if _sqlcipher_enabled(db_key=getattr(settings, "db_key", None)):
                import sqlcipher3  # type: ignore

                module = sqlcipher3
        except Exception:
            module = None
        if module is not None:
            kwargs["module"] = module
        eng = create_engine(url, **kwargs)
        _ENGINE_CACHE[url] = eng
    return eng


@dataclass
class LoginGuardDecision:
    allowed: bool
    retry_after_seconds: int = 0
    reason: str | None = None


_LOCK_REASON = 'Zu viele Fehlversuche. Bitte später erneut versuchen.'


class _GuardResetProxy:
    """Backwards-Compat: bildet das alte ``dict``-Interface auf DB-Reset ab.

    Nur ``.clear()`` wird tatsaechlich gebraucht (Test-Fixtures). Truncatet die
    zugeordnete Guard-Tabelle. Fehlt die Tabelle noch, ist das ein No-Op.
    """

    def __init__(self, guard: "LoginAttemptGuard", table: str) -> None:
        self._guard = guard
        self._table = table

    def clear(self) -> None:
        try:
            with self._guard._bind().begin() as conn:
                conn.execute(text(f"DELETE FROM {self._table}"))
        except SQLAlchemyError:
            pass  # Tabelle (noch) nicht vorhanden -> nichts zu leeren.

    def get(self, *_args, **_kwargs):  # pragma: no cover - defensiver Shim
        return None


class LoginAttemptGuard:
    """Brute-Force-Guard, DB-gestuetzt (persistent + worker-uebergreifend).

    :param engine: Optionale, explizite SQLAlchemy-Engine (fuer Tests). Ist
        keine gesetzt, wird pro Aufruf ``_get_guard_engine()`` genutzt (teilt
        die App-DB, gecachte standalone Engine).
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine
        # Backwards-Compat-Shims: frueher hielt der Guard In-Memory-Dicts
        # ``_failures`` / ``_locked_until``. Bestehende Test-Fixtures rufen
        # ``guard._failures.clear()`` / ``guard._locked_until.clear()`` auf, um
        # den prozessweiten Zustand zwischen Tests zu resetten. Diese Proxies
        # bilden ``.clear()`` auf ein Leeren der DB-Tabellen ab, sodass die
        # Aufrufer (und routers/auth.py) unveraendert bleiben.
        self._failures = _GuardResetProxy(self, "login_attempts")
        self._locked_until = _GuardResetProxy(self, "login_lockouts")

    # ── Helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize(username: str) -> str:
        return (username or "").strip().lower()

    @staticmethod
    def _to_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    @staticmethod
    def _from_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = str(value).strip().replace("Z", "")
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
        return None

    def _bind(self):
        return self._engine if self._engine is not None else _get_guard_engine()

    def _ensure_tables(self, conn) -> None:
        """Legt die Tabellen an, falls (noch) nicht vorhanden.

        In der laufenden App erledigt das ``create_all``/Alembic beim Boot
        (siehe ``database.py::_create_or_migrate_schema``, dialekt-korrekt
        fuer SQLite UND Postgres); fuer standalone/Test-Engines oder sehr
        fruehe Aufrufe wird hier defensiv idempotent nachgezogen (kein
        Eingriff in database.py).

        AUTH-TEN-07 (Codex-Audit 2026-08-25): vorher rohes SQLite-DDL-Literal
        (``... AUTOINCREMENT ...``) -- das ist keine gueltige PostgreSQL-
        Syntax und wirft dort bei JEDEM Aufruf einen Syntaxfehler, VOR jeder
        "existiert schon"-Pruefung. Da alle drei oeffentlichen Methoden
        SQLAlchemyError abfangen und fail-open zurueckgeben, war der Guard
        auf Postgres dadurch bei JEDEM Login-Versuch stillschweigend
        wirkungslos. Jetzt ueber die echten ORM-Modelle (dieselbe Quelle wie
        die Alembic-Baseline-Migration) -- SQLAlchemy compiliert das DDL pro
        Dialekt korrekt.

        ``CreateTable(..., if_not_exists=True)`` statt ``Table.create(...,
        checkfirst=True)``: Letzteres prueft Existenz separat VOR dem CREATE
        (TOCTOU-Race unter echter Nebenlaeufigkeit -- zwei parallele
        Connections koennen beide "existiert nicht" sehen und beide CREATE
        versuchen, die zweite crasht dann mit "already exists", was den
        Guard fuer diesen Call fail-open macht). ``IF NOT EXISTS`` im DDL
        selbst ist dagegen atomar auf Statement-Ebene (SQLite UND Postgres
        unterstuetzen die Syntax).
        """
        from models.login_attempt import LoginAttempt, LoginLockout

        for table in (LoginAttempt.__table__, LoginLockout.__table__):
            conn.execute(CreateTable(table, if_not_exists=True))
            for index in table.indexes:
                conn.execute(CreateIndex(index, if_not_exists=True))

    def _cleanup(self, conn, key: str, window_start_iso: str, now_iso: str) -> None:
        """Abgelaufene Fehlversuch-Zeilen + abgelaufene Lockouts entfernen."""
        conn.execute(
            text(
                "DELETE FROM login_attempts WHERE key = :key AND event_at < :ws"
            ),
            {"key": key, "ws": window_start_iso},
        )
        conn.execute(
            text(
                "DELETE FROM login_lockouts WHERE locked_until <= :now"
            ),
            {"now": now_iso},
        )

    # ── Public interface (STABIL — von routers/auth.py aufgerufen) ─────────
    def check(self, username: str) -> LoginGuardDecision:
        if not settings.login_rate_limit_enabled:
            return LoginGuardDecision(allowed=True)

        now = self._now()
        normalized = self._normalize(username)
        window_start = now - timedelta(seconds=settings.login_window_seconds)
        now_iso = self._to_iso(now)
        ws_iso = self._to_iso(window_start)

        try:
            with self._bind().begin() as conn:
                self._ensure_tables(conn)
                self._cleanup(conn, normalized, ws_iso, now_iso)
                row = conn.execute(
                    text(
                        "SELECT locked_until FROM login_lockouts WHERE key = :key"
                    ),
                    {"key": normalized},
                ).fetchone()
        except SQLAlchemyError as exc:  # Fallback: fail-open + Log
            logger.warning("login_guard.check DB-Fehler (fail-open): %s", exc)
            return LoginGuardDecision(allowed=True)

        locked_until = self._from_iso(row[0]) if row else None
        if locked_until and locked_until > now:
            retry_after = int((locked_until - now).total_seconds()) + 1
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                reason=_LOCK_REASON,
            )
        return LoginGuardDecision(allowed=True)

    def register_failure(self, username: str) -> LoginGuardDecision:
        if not settings.login_rate_limit_enabled:
            return LoginGuardDecision(allowed=True)

        now = self._now()
        normalized = self._normalize(username)
        window_start = now - timedelta(seconds=settings.login_window_seconds)
        now_iso = self._to_iso(now)
        ws_iso = self._to_iso(window_start)

        try:
            # EINE Transaktion: cleanup -> insert -> count -> (upsert lockout).
            # Damit zaehlt register_failure auch unter parallelen Aufrufen
            # korrekt (die Transaktion serialisiert die konkurrierenden
            # Insert/Count-Sequenzen; SQLite sperrt beim Schreiben).
            with self._bind().begin() as conn:
                self._ensure_tables(conn)
                self._cleanup(conn, normalized, ws_iso, now_iso)
                conn.execute(
                    text(
                        "INSERT INTO login_attempts (key, event_at) "
                        "VALUES (:key, :now)"
                    ),
                    {"key": normalized, "now": now_iso},
                )
                count = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM login_attempts "
                        "WHERE key = :key AND event_at >= :ws"
                    ),
                    {"key": normalized, "ws": ws_iso},
                ).scalar_one()

                if count >= settings.login_max_attempts:
                    locked_until = now + timedelta(
                        seconds=settings.login_lockout_seconds
                    )
                    lu_iso = self._to_iso(locked_until)
                    # Upsert (portabel: DELETE + INSERT, key ist PK).
                    conn.execute(
                        text("DELETE FROM login_lockouts WHERE key = :key"),
                        {"key": normalized},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO login_lockouts (key, locked_until) "
                            "VALUES (:key, :lu)"
                        ),
                        {"key": normalized, "lu": lu_iso},
                    )
        except SQLAlchemyError as exc:  # Fallback: fail-open + Log
            logger.warning("login_guard.register_failure DB-Fehler (fail-open): %s", exc)
            return LoginGuardDecision(allowed=True)

        if count >= settings.login_max_attempts:
            retry_after = int(settings.login_lockout_seconds) + 1
            return LoginGuardDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                reason=_LOCK_REASON,
            )

        remaining = max(settings.login_max_attempts - count, 0)
        return LoginGuardDecision(
            allowed=True,
            retry_after_seconds=0,
            reason=f'Anmeldung fehlgeschlagen. Verbleibende Versuche: {remaining}.',
        )

    def register_success(self, username: str) -> None:
        normalized = self._normalize(username)
        try:
            with self._bind().begin() as conn:
                self._ensure_tables(conn)
                conn.execute(
                    text("DELETE FROM login_attempts WHERE key = :key"),
                    {"key": normalized},
                )
                conn.execute(
                    text("DELETE FROM login_lockouts WHERE key = :key"),
                    {"key": normalized},
                )
        except SQLAlchemyError as exc:  # Fallback: still, nicht kritisch
            logger.warning("login_guard.register_success DB-Fehler: %s", exc)


login_attempt_guard = LoginAttemptGuard()
