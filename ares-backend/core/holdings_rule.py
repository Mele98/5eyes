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


def ist_partially_derived(positions) -> bool:
    """True, sobald eine Position ohne erfassten Bestand (``current_amount_rappen``
    fehlt oder <= 0) mit einem Zielbetrag > 0 ins IST eingeht."""
    for position in positions or []:
        if _int(getattr(position, "current_amount_rappen", None)) <= 0 and \
                _int(getattr(position, "target_amount_rappen", None)) > 0:
            return True
    return False
