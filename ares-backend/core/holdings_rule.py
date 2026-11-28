"""KN4-B / N-917R3-03/04 (CTO-Entscheid): EINE Definition von "IST teilweise
abgeleitet" (reines Blatt, nur Standardbibliothek).

Faellt auch nur eine Position der Empfehlung mangels erfasstem Bestand auf ihren
Zielbetrag zurueck, ist das IST (teilweise) SOLL per Konstruktion -- dann gibt es
keine Bandaussage ("nicht beurteilbar – Bestand unvollständig"). Vorher galt im
Depotcheck "alle Positionen ohne Bestand" (``<= 0``) und im Advisory-Report
"alle ``None``": ein Teil-Rueckfall blieb "bewertbar", und beide Seiten desselben
Berichts widersprachen sich. Genutzt von services/depot_check.py und
services/advisory_report.py.
"""
from __future__ import annotations

DERIVED_IST_STATUS = "nicht beurteilbar – Bestand unvollständig"


def _int(value) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _derived(position, held_ids) -> bool:
    if str(getattr(position, "id", "") or "") in held_ids:
        return False  # Bestand ueber die Holding-Route erfasst (EXT-01)
    return _int(getattr(position, "current_amount_rappen", None)) <= 0 and \
        _int(getattr(position, "target_amount_rappen", None)) > 0


def ist_partially_derived(positions, held_ids=()) -> bool:
    """True, sobald eine Position ohne erfassten Bestand (keine Holding,
    ``current_amount_rappen`` fehlt oder <= 0) mit einem Zielbetrag > 0 ins IST
    eingeht. ``held_ids``: Positionen mit Bestand aus ``recommendation_holdings``."""
    held = {str(i) for i in held_ids or ()}
    return any(_derived(position, held) for position in positions or [])


def ist_fully_derived(positions, held_ids=()) -> bool:
    """True, wenn KEINE Position einen erfassten Bestand hat (IST = SOLL)."""
    held = {str(i) for i in held_ids or ()}
    items = list(positions or [])
    return bool(items) and all(_derived(position, held) or (
        str(getattr(position, "id", "") or "") not in held
        and _int(getattr(position, "current_amount_rappen", None)) <= 0) for position in items)


# KN5 / N-917R4-03: EINE Regel fuer Lauf und Holdings -- Depotcheck
# (services/depot_check.py), Live-Rebalancing (portfolio_engine.
# _current_recommendation_run + portfolio_engine_live_rebalancing.
# current_run_holdings) und Druck-FX-Gate (services/print_fx_gate.py).
CURRENT_RUN_STATUSES = ("Draft", "Final")


def _status(run) -> str | None:
    return getattr(run, "result_status", None)


def select_valuation_runs(runs, status=_status):
    """``runs``: alle Laeufe des Mandats, juengster zuerst (``created_at``, dann
    ``id`` absteigend). Liefert ``(bewerteter Lauf, Holdings-Lauf)``:

    * bewerteter Lauf: juengster Final, sonst juengster Draft, sonst juengster;
    * Holdings-Lauf: juengster Draft/Final (CIO-Entscheid 2026-10-28 (b)); seine
      Holdings gelten je Position, sonst je Produkt auch fuer den bewerteten Lauf.

    Vorher waehlte der Depotcheck "Final vor Draft", das Live-Rebalancing "Final
    vor juengstem" und die Holdings den juengsten Draft/Final; ein Final ohne
    Holdings neben einem neueren Draft mit Holdings wurde vom Live-Rebalancing
    bewertet, vom Depotcheck ignoriert (H-176-Pruefung N-917R4-03)."""
    items = list(runs or [])
    valuation = (next((r for r in items if status(r) == "Final"), None)
                 or next((r for r in items if status(r) == "Draft"), None)
                 or (items[0] if items else None))
    holdings = next((r for r in items if status(r) in CURRENT_RUN_STATUSES), None)
    return valuation, holdings
