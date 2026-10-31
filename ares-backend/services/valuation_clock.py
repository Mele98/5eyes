"""Gebundener Bewertungsstichtag je Lauf (ADR-1b, GOAL-CALENDAR-HORIZON-PARITY-001).

Owner-Entscheid 1b (2026-10-11): jeder Optimizer-Lauf bindet den
Bewertungsstichtag EINMAL beim Ausloesen, persistiert ihn an der
Soll-Allokation (``target_allocations.valuation_date``), und jede
Folgeberechnung (Reload, Staleness-Pruefung, Report-Simulation) liest den
GESPEICHERTEN Stichtag -- nie erneut die Wanduhr.

Vorher las jede Engine-Stelle ``date.today()`` selbst: Liability-Buckets,
Cashflow-Achse, Lifecycle, Reserve-Horizont, Report-Zeitachse. Ein Reload
desselben Datensatzes nach dem Jahreswechsel verschob damit Buckets,
Zielerreichung und Zeitachse, ohne dass sich an den Daten etwas geaendert
hatte.

Mechanik: eine ``ContextVar`` haelt den gebundenen Stichtag fuer die Dauer
eines Laufs. ``valuation_date()`` liefert ihn, ausserhalb eines gebundenen
Laufs die Wanduhr (Unit-Tests, Hilfsaufrufe). Die Engine kennt damit genau
EINE Quelle fuer "heute". Es gibt keine Thread- oder Prozess-Pools in den
Engine-Pfaden; ein Request laeuft vollstaendig im gebundenen Kontext.
"""
from __future__ import annotations

import datetime as _dt
import functools
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Callable, Iterator

_BOUND: ContextVar[date | None] = ContextVar("valuation_date", default=None)


def valuation_date() -> date:
    """Der gebundene Bewertungsstichtag, sonst die Wanduhr."""
    bound = _BOUND.get()
    return bound if bound is not None else date.today()


def bound_valuation_date_or_none() -> date | None:
    """Der gebundene Stichtag oder ``None`` ausserhalb eines gebundenen Laufs."""
    return _BOUND.get()


def parse_valuation_date(value: Any) -> date | None:
    """ISO-Datum (``YYYY-MM-DD``) aus einer persistierten Spalte, sonst None."""
    if isinstance(value, _dt.date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


@contextmanager
def bound_valuation_date(value: date) -> Iterator[date]:
    """Bindet ``value`` fuer die Dauer des Blocks (verschachtelbar)."""
    if not isinstance(value, _dt.date):
        raise TypeError("bound_valuation_date erwartet ein datetime.date")
    token = _BOUND.set(value)
    try:
        yield value
    finally:
        _BOUND.reset(token)


def binds_run_valuation_date(func: Callable) -> Callable:
    """Neuer Lauf: bindet heute, sofern der Aufrufer noch nichts gebunden hat."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if _BOUND.get() is not None:
            return func(*args, **kwargs)
        with bound_valuation_date(date.today()):
            return func(*args, **kwargs)

    return wrapper


def binds_allocation_valuation_date(func: Callable) -> Callable:
    """Replay einer Soll-Allokation: bindet deren gespeicherten Stichtag.

    Die Allokation wird ueber den Parameter ``allocation`` gefunden. Ohne
    gespeicherten Stichtag (Bestand vor ADR-1b) gilt das bisherige
    Verhalten: ein bereits gebundener Stichtag bleibt, sonst die Wanduhr.
    """
    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        allocation = signature.bind_partial(*args, **kwargs).arguments.get("allocation")
        stored = parse_valuation_date(getattr(allocation, "valuation_date", None))
        if stored is None:
            return func(*args, **kwargs)
        with bound_valuation_date(stored):
            return func(*args, **kwargs)

    return wrapper
