"""AUTH-03: Persistenter/geteilter Brute-Force-Login-Guard.

Akzeptanzkriterien (siehe docs/planning/2026-07-03-top10-implementation-specs.md,
Abschnitt "## 6. AUTH-03"):
1. Nach ``login_max_attempts`` Fehlversuchen -> ``check`` = allowed=False +
   retry_after; ein ZWEITER frisch konstruierter Guard gegen dieselbe DB
   (simuliert 2. Worker) sieht denselben Lockout (Shared-State).
2. Persistenz/Restart-Fest: neue Guard-Instanz gegen dieselbe DB sieht den
   Lockout.
3. Fenster-Ablauf -> wieder allowed=True.
4. ``register_success`` loescht den Key (Zaehler 0, kein Lockout).
5. ``login_rate_limit_enabled=False`` -> nie Lockout / kompletter Bypass.
6. Parallele ``register_failure`` zaehlen korrekt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
import services.login_guard as lg
from services.login_guard import LoginAttemptGuard, LoginGuardDecision


@pytest.fixture()
def guard_engine(tmp_path):
    """Temp-SQLite-Engine, in die der Guard schreibt (Tabellen via _ensure_tables)."""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'guard.db'}",
        connect_args={"check_same_thread": False},
    )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(autouse=True)
def _rate_limit_on(monkeypatch):
    # Deterministische Guard-Config fuer die Tests.
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "login_max_attempts", 5, raising=False)
    monkeypatch.setattr(settings, "login_window_seconds", 60, raising=False)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600, raising=False)


def _fail_n(guard: LoginAttemptGuard, key: str, n: int) -> LoginGuardDecision:
    decision = LoginGuardDecision(allowed=True)
    for _ in range(n):
        decision = guard.register_failure(key)
    return decision


# ── (1) Lockout nach max Fehlversuchen + Shared-State (2. Worker) ──────────
def test_lockout_after_max_attempts_and_shared_state(guard_engine):
    key = "  User@Example.COM  "  # prueft zugleich Key-Normalisierung
    guard_a = LoginAttemptGuard(engine=guard_engine)

    last = _fail_n(guard_a, key, settings.login_max_attempts)
    assert last.allowed is False
    assert last.retry_after_seconds > 0

    # naechster check auf demselben Guard -> gesperrt
    dec_a = guard_a.check(key)
    assert dec_a.allowed is False
    assert dec_a.retry_after_seconds > 0
    assert dec_a.reason

    # ZWEITER Guard (simuliert 2. Worker) gegen DIESELBE DB -> selber Lockout
    guard_b = LoginAttemptGuard(engine=guard_engine)
    dec_b = guard_b.check(key)
    assert dec_b.allowed is False
    assert dec_b.retry_after_seconds > 0


# ── (2) Persistenz / restart-fest (neue Instanz, dieselbe DB) ──────────────
def test_lockout_persists_across_new_instance(guard_engine):
    key = "brute@host"
    _fail_n(LoginAttemptGuard(engine=guard_engine), key, settings.login_max_attempts)

    # "Neustart": voellig neue Guard-Instanz gegen dieselbe DB-Datei.
    fresh = LoginAttemptGuard(engine=guard_engine)
    dec = fresh.check(key)
    assert dec.allowed is False
    assert dec.retry_after_seconds > 0


# ── (3) Fenster-Ablauf -> wieder erlaubt ───────────────────────────────────
def test_window_expiry_reallows(guard_engine, monkeypatch):
    # Kleines Fenster; alte Fehlversuche fallen aus dem Zaehlfenster.
    monkeypatch.setattr(settings, "login_window_seconds", 60, raising=False)
    key = "expire@host"
    guard = LoginAttemptGuard(engine=guard_engine)

    # 4 Fehlversuche (unter max=5) -> noch nicht gesperrt.
    _fail_n(guard, key, settings.login_max_attempts - 1)
    assert guard.check(key).allowed is True

    # Gespeicherte event_at-Zeitstempel kuenstlich weit in die Vergangenheit
    # schieben, sodass sie ausserhalb des Fensters liegen.
    with guard_engine.begin() as conn:
        conn.execute(
            text("UPDATE login_attempts SET event_at = :old"),
            {"old": "2000-01-01T00:00:00.000Z"},
        )

    # check raeumt abgelaufene Zeilen auf -> wieder erlaubt.
    assert guard.check("expire@host").allowed is True

    # und ein neuer Fehlversuch startet frisch (Zaehler 1, nicht 5).
    dec = guard.register_failure("expire@host")
    assert dec.allowed is True
    with guard_engine.begin() as conn:
        cnt = conn.execute(
            text("SELECT COUNT(*) FROM login_attempts WHERE key = :k"),
            {"k": "expire@host"},
        ).scalar_one()
    assert cnt == 1


def test_window_expiry_unlocks_after_lockout_expires(guard_engine, monkeypatch):
    key = "unlock@host"
    guard = LoginAttemptGuard(engine=guard_engine)
    _fail_n(guard, key, settings.login_max_attempts)
    assert guard.check(key).allowed is False

    # Lockout-Zeitpunkt in die Vergangenheit schieben -> cleanup entfernt ihn.
    with guard_engine.begin() as conn:
        conn.execute(
            text("UPDATE login_lockouts SET locked_until = :old"),
            {"old": "2000-01-01T00:00:00.000Z"},
        )
    assert guard.check(key).allowed is True


# ── (4) register_success loescht den Key ───────────────────────────────────
def test_register_success_clears_key(guard_engine):
    key = "reset@host"
    guard = LoginAttemptGuard(engine=guard_engine)
    _fail_n(guard, key, settings.login_max_attempts)
    assert guard.check(key).allowed is False

    guard.register_success(key)
    assert guard.check(key).allowed is True

    with guard_engine.begin() as conn:
        attempts = conn.execute(
            text("SELECT COUNT(*) FROM login_attempts WHERE key = :k"),
            {"k": "reset@host"},
        ).scalar_one()
        locks = conn.execute(
            text("SELECT COUNT(*) FROM login_lockouts WHERE key = :k"),
            {"k": "reset@host"},
        ).scalar_one()
    assert attempts == 0
    assert locks == 0


# ── (5) Bypass wenn rate limit deaktiviert ─────────────────────────────────
def test_disabled_never_locks(guard_engine, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit_enabled", False, raising=False)
    key = "bypass@host"
    guard = LoginAttemptGuard(engine=guard_engine)

    for _ in range(settings.login_max_attempts * 3):
        dec = guard.register_failure(key)
        assert dec.allowed is True
    assert guard.check(key).allowed is True

    # Keine Tabellen/Zeilen wurden angelegt (kompletter Bypass, kein DB-Zugriff).
    with guard_engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='login_attempts'"
            )
        ).fetchone()
    assert exists is None


# ── (6) Parallele register_failure zaehlen korrekt ─────────────────────────
def test_parallel_register_failure_counts_correctly(guard_engine):
    import threading

    key = "parallel@host"
    n_threads = settings.login_max_attempts
    barrier = threading.Barrier(n_threads)
    results: list[LoginGuardDecision] = []
    lock = threading.Lock()

    # Jeder Thread hat einen EIGENEN Guard (simuliert konkurrierende Worker),
    # alle gegen dieselbe DB-Engine.
    def worker():
        guard = LoginAttemptGuard(engine=guard_engine)
        barrier.wait()
        dec = guard.register_failure(key)
        with lock:
            results.append(dec)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Es wurden genau n_threads Zeilen geschrieben (kein Lost-Update).
    with guard_engine.begin() as conn:
        cnt = conn.execute(
            text("SELECT COUNT(*) FROM login_attempts WHERE key = :k"),
            {"k": key},
        ).scalar_one()
    assert cnt == n_threads

    # Genau ein Aufruf erreichte/ueberschritt das Limit -> gesperrt.
    locked = [r for r in results if not r.allowed]
    assert len(locked) >= 1
    # Endzustand: gesperrt.
    assert LoginAttemptGuard(engine=guard_engine).check(key).allowed is False


# ── (7) Fallback: DB nicht verfuegbar -> fail-open ─────────────────────────
def test_fallback_fail_open_on_db_error(monkeypatch):
    bad = create_engine("sqlite:///:memory:")

    class _Boom:
        def begin(self):
            raise __import__("sqlalchemy").exc.OperationalError("x", {}, Exception("no db"))

    guard = LoginAttemptGuard(engine=_Boom())
    assert guard.check("any").allowed is True
    assert guard.register_failure("any").allowed is True
    # register_success darf nicht werfen.
    guard.register_success("any")
    bad.dispose()
