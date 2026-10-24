"""Sprint U-27 (Roadmap-Punkt 27): Tests fuer _format_swiss_datetime.

Bug-Befund (pre-U-27): die Funktion gab UTC-Z-Timestamps 1:1 als
"Schweizer-Format" zurueck — Berater las "14:32" obwohl es UTC war
und tatsaechlich 16:32 CEST war. FINMA-relevant.

Fix: ZoneInfo("Europe/Zurich")-Konvertierung fuer aware Datetimes.
Naive Datetimes (kein TZ) bleiben unangetastet (Backwards-Compat).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.components.advisory_page_chrome import _format_swiss_datetime


# ---------------------------------------------------------------------------
# UTC -> Europa/Zurich Konvertierung (der eigentliche Bugfix)
# ---------------------------------------------------------------------------

def test_utc_summer_z_is_converted_to_cest_plus_2h():
    """26.05.2026 14:32 UTC -> 26.05.2026 16:32 CEST (CET+2)."""
    out = _format_swiss_datetime("2026-05-26T14:32:00.000Z")
    assert out == "26.05.2026 16:32"


def test_utc_winter_z_is_converted_to_cet_plus_1h():
    """26.12.2026 14:32 UTC -> 26.12.2026 15:32 CET (CET+1)."""
    out = _format_swiss_datetime("2026-12-26T14:32:00.000Z")
    assert out == "26.12.2026 15:32"


def test_utc_z_at_day_boundary_rolls_into_next_day():
    """26.05.2026 23:30 UTC -> 27.05.2026 01:30 CEST (Tag-Rollover)."""
    out = _format_swiss_datetime("2026-05-26T23:30:00Z")
    assert out == "27.05.2026 01:30"


def test_aware_iso_with_offset_is_converted():
    """+00:00 ist ein aware Datetime und muss konvertiert werden."""
    out = _format_swiss_datetime("2026-05-26T14:00:00+00:00")
    assert out == "26.05.2026 16:00"


def test_aware_iso_with_non_zero_offset_is_normalized():
    """+05:00 (Indian time) 14:00 -> 09:00 UTC -> 11:00 CEST."""
    out = _format_swiss_datetime("2026-05-26T14:00:00+05:00")
    assert out == "26.05.2026 11:00"


# ---------------------------------------------------------------------------
# Naive datetimes (Backwards-Compat)
# ---------------------------------------------------------------------------

def test_naive_iso_is_formatted_as_is():
    """Kein TZ-Suffix -> naive datetime -> 1:1 formatieren ohne Konvertierung
    (Test-Stuetze fuer Code-Pfade, die noch naive Strings uebergeben)."""
    out = _format_swiss_datetime("2026-05-26T14:32:00")
    assert out == "26.05.2026 14:32"


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

def test_empty_string_returns_dash():
    assert _format_swiss_datetime("") == "—"


def test_none_returns_dash():
    # type: ignore (Test gegen Defensive)
    assert _format_swiss_datetime(None) == "—"  # type: ignore[arg-type]


def test_invalid_format_returns_raw_string():
    """Falscher Format -> ValueError -> raw zurueckgeben."""
    out = _format_swiss_datetime("not a valid timestamp")
    assert out == "not a valid timestamp"


# ---------------------------------------------------------------------------
# Determinismus (sanity)
# ---------------------------------------------------------------------------

def test_deterministic_repeated_calls():
    """Gleicher Input -> gleicher Output (audit-relevant)."""
    iso = "2026-08-15T10:00:00Z"
    a = _format_swiss_datetime(iso)
    b = _format_swiss_datetime(iso)
    c = _format_swiss_datetime(iso)
    assert a == b == c == "15.08.2026 12:00"
