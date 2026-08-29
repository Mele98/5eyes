"""RESOURCE-003 (Codex-Audit 2026-08-27, docs/audits/2026-08-27-request-
ingestion-and-resource-governance-audit.md): die zwei schreibenden Solver-
Endpunkte (target-allocation/generate, .../sensitivity) hatten keine
Kapazitaetsgrenze -- eine Barrier-Reproduktion im Audit bewies, dass zwei
Requests gleichzeitig in den vollen NumPy-Modellpfad eintraten.

Diese Tests decken nur die neue, prozessweite Bounded-Concurrency-Schranke
(services/solver_admission.admit()) ab -- die weitergehenden Forderungen des
Fixvertrags (Job-Queue, per-Tenant-Fairness, Idempotency-Key, Deadline/
Cancellation) bleiben ein groesseres, separates Vorhaben.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings  # noqa: E402
import services.solver_admission as solver_admission  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_admission_state():
    solver_admission._in_flight = 0
    yield
    solver_admission._in_flight = 0


def test_admit_allows_up_to_configured_max_concurrent(monkeypatch):
    monkeypatch.setattr(settings, "solver_max_concurrent", 2)
    with solver_admission.admit():
        with solver_admission.admit():
            assert solver_admission._in_flight == 2


def test_admit_rejects_when_at_capacity(monkeypatch):
    monkeypatch.setattr(settings, "solver_max_concurrent", 1)
    with solver_admission.admit():
        with pytest.raises(HTTPException) as ei:
            with solver_admission.admit():
                pass  # pragma: no cover - darf nicht erreicht werden
        assert ei.value.status_code == 429
        assert ei.value.headers.get("Retry-After")


def test_admit_releases_slot_on_normal_exit(monkeypatch):
    monkeypatch.setattr(settings, "solver_max_concurrent", 1)
    with solver_admission.admit():
        pass
    # Slot wieder frei -- ein zweiter (serieller) Aufruf darf nicht ablehnen.
    with solver_admission.admit():
        assert solver_admission._in_flight == 1
    assert solver_admission._in_flight == 0


def test_admit_releases_slot_when_body_raises(monkeypatch):
    monkeypatch.setattr(settings, "solver_max_concurrent", 1)
    with pytest.raises(ValueError):
        with solver_admission.admit():
            raise ValueError("Solver-Fehler")
    assert solver_admission._in_flight == 0
    # Slot ist frei -- ein Folge-Request darf wieder rein.
    with solver_admission.admit():
        assert solver_admission._in_flight == 1


def test_concurrent_admits_never_exceed_configured_max(monkeypatch):
    """Reproduziert die Audit-Barrier-Situation direkt gegen admit(): N echte
    Threads versuchen gleichzeitig einzutreten, die Kapazitaet ist strikt
    begrenzt und niemals ueberschritten (peak_in_flight <= max)."""
    monkeypatch.setattr(settings, "solver_max_concurrent", 3)
    peak = {"value": 0}
    accepted = {"count": 0}
    rejected = {"count": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        try:
            with solver_admission.admit():
                with lock:
                    peak["value"] = max(peak["value"], solver_admission._in_flight)
                    accepted["count"] += 1
                time.sleep(0.05)
        except HTTPException:
            with lock:
                rejected["count"] += 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert peak["value"] <= 3
    assert accepted["count"] + rejected["count"] == 8
    assert rejected["count"] > 0  # 8 Threads, Kapazitaet 3 -- muss Ablehnungen geben
    assert solver_admission._in_flight == 0
