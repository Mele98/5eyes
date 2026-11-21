"""KN3-B Nachtrag 2 (CTO-Entscheid 2026-11-19): eine Bandregel fuer alle
Konsumenten (reines Blatt, nur Standardbibliothek).

Ein Band 0/0 heisst "Obergrenze 0", nicht "keine Grenze": ein vom Profil
ausgeschlossener Bestand (z. B. Aktien bei Kapitalschutz, Band 0-0 %) ist
verletzt, sobald er > 0 ist. Ein Punktband min == max > 0 ist ebenso eine
echte Grenze. "Keine Grenze" gilt nur, wenn die Grenze wirklich fehlt (``None``,
z. B. keine Soll-Allokation oder ein Bucket ohne Bandangabe) -- dann ist das
Ergebnis fail-closed "nicht bewertbar", nie "im Band".

Dieselbe Regel wie die Classic-Oberflaeche (KN3-U, ``kn3-ui.js``
``aresBandOf``/``aresBandStatus``). Konsumenten: Review-Trigger
(services/review_engine.py), Live-Rebalancing
(services/portfolio_engine_live_rebalancing.py), Depotcheck inkl. PDF/Advisory-
Report (services/depot_check.py), SAA-Abgleich der Finalisierung
(services/product_eligibility_finalization.py).
"""
from __future__ import annotations

BAND_IN = "in_band"
BAND_BELOW = "below"
BAND_ABOVE = "above"
BAND_UNKNOWN = "not_evaluable"


def _as_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def band_status(current_bps, min_bps, max_bps) -> str:
    """``in_band``/``below``/``above``; ``not_evaluable`` nur ohne Grenze oder Ist."""
    current = _as_int(current_bps)
    low = _as_int(min_bps)
    high = _as_int(max_bps)
    if current is None or low is None or high is None or low > high:
        return BAND_UNKNOWN
    if current < low:
        return BAND_BELOW
    if current > high:
        return BAND_ABOVE
    return BAND_IN


def band_breach_bps(current_bps, min_bps, max_bps):
    """Abstand zur verletzten Grenze in bps (0 = im Band), ``None`` = nicht bewertbar."""
    status = band_status(current_bps, min_bps, max_bps)
    if status == BAND_UNKNOWN:
        return None
    if status == BAND_BELOW:
        return int(min_bps) - int(current_bps)
    if status == BAND_ABOVE:
        return int(current_bps) - int(max_bps)
    return 0


def in_band(current_bps, min_bps, max_bps):
    """``True``/``False``; ``None`` = nicht bewertbar (nie stillschweigend "im Band")."""
    status = band_status(current_bps, min_bps, max_bps)
    return None if status == BAND_UNKNOWN else status == BAND_IN
