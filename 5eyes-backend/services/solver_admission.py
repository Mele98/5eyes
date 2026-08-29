"""RESOURCE-003 (Codex-Audit 2026-08-27): Admission Control fuer die
schreibenden Solver-Endpunkte (target-allocation/generate, .../sensitivity).

Beide Endpunkte rufen unmittelbar den vollen NumPy-Modellpfad auf und hatten
keinerlei Kapazitaetsgrenze -- zwei parallele Requests traten nachweislich
gleichzeitig in den Solver ein (Barrier-Reproduktion im Audit). Ein
fehlerhafter oder boesartiger Advisor-Client konnte damit CPU/Speicher der
Webworker fuer alle anderen Mandate verdraengen.

Scope dieser Fassung (bewusst NICHT der volle Fixvertrag): eine
PROZESSWEITE (nicht per-Tenant-faire, nicht persistente Job-Queue) bounded
Concurrency-Schranke ueber einen einfachen In-Memory-Zaehler + Lock. Wird
das Limit erreicht, lehnt admit() VOR jedem Datenladen/Szenariobau mit einer
HTTPException(429, Retry-After) ab, statt die teure Arbeit zu queuen oder
zu drosseln. Multi-Worker-/Multi-Tenant-Fairness, Idempotency-Keys und
Cancellation bleiben denselben spaeteren, groesseren Vorhaben vorbehalten
wie die uebrigen Punkte im Fixvertrag.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from fastapi import HTTPException

from config import settings

_lock = threading.Lock()
_in_flight = 0

# Fixer, konservativer Retry-After-Wert: die Endpunkte laufen typischerweise
# im Sekundenbereich (SCENARIO_COUNT-abhaengig), ein paar Sekunden Backoff
# reichen fuer einen Client aus, um nicht sofort erneut abgelehnt zu werden.
_RETRY_AFTER_SECONDS = 5


@contextmanager
def admit():
    """Reserviert einen Solver-Slot oder lehnt mit 429 ab.

    Muss als ALLERERSTES im Endpoint aufgerufen werden -- also vor
    _get_mandate_or_404()/Datenladen, damit ein abgelehnter Request keine
    DB-Queries oder Szenariobau-Arbeit mehr bezahlt.
    """
    global _in_flight
    with _lock:
        if _in_flight >= max(settings.solver_max_concurrent, 1):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Zu viele gleichzeitige Portfolio-Berechnungen -- bitte "
                    "kurz warten und erneut versuchen."
                ),
                headers={"Retry-After": str(_RETRY_AFTER_SECONDS)},
            )
        _in_flight += 1
    try:
        yield
    finally:
        with _lock:
            _in_flight -= 1
