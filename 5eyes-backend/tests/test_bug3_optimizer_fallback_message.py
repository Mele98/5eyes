"""Bug-#3 (2026-06-07): Optimizer-Bandbreiten-Fallback-Meldung.

User-Befund: Bei jedem Warn-Status zeigte das Optimizer-Panel den
gleichen Text 'Solver konvergierte nicht — House-Matrix-Default
verwendet'. Das war faktisch falsch:

- `fallback_house_matrix`: echter Fallback auf House-Matrix-Mitte
- `diverged_infeasible`: Solver hat Loesung, aber Bandbreiten verletzt
  (kein Fallback, gezeigte Gewichte sind ungueltig)
- `diverged`: Solver konvergierte nicht, kein Fallback ausgefuehrt
- `converged_robustified`: feasible via Multi-Start (nicht Warn-faerbig)

Fix: Banner-Text + Status-Pill pro Status differenzieren. Drift-Test
verhindert Regression auf den Sammel-Text.
"""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html_text() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_bug3_marker_vorhanden():
    """Drift-Wache fuer den Fix-Marker."""
    assert "Bug-#3 (2026-06-07)" in _html_text()


def test_banner_fallback_house_matrix_redet_von_fallback():
    """fallback_house_matrix-Banner muss 'Fallback' und 'House-Matrix-'
    sowie 'Bandbreiten' enthalten."""
    text = _html_text()
    idx = text.find("if(status==='fallback_house_matrix'){")
    assert idx > 0, "fallback_house_matrix-Block fehlt"
    block = text[idx:idx + 600]
    assert "Fallback auf House-Matrix-Mittelwert" in block
    assert "Bandbreiten-Default" in block


def test_banner_diverged_infeasible_warnt_vor_bandbreiten_verletzung():
    """diverged_infeasible-Banner muss klarstellen: kein Fallback,
    Gewichte verletzen Bandbreiten."""
    text = _html_text()
    idx = text.find("}else if(status==='diverged_infeasible'){")
    assert idx > 0, "diverged_infeasible-Block fehlt"
    block = text[idx:idx + 600]
    assert "ausserhalb der" in block and "Bandbreiten" in block
    assert "kein gueltiger Anlagevorschlag" in block


def test_banner_diverged_unterscheidet_sich_von_fallback():
    """diverged-Banner darf NICHT 'House-Matrix-Mittelwert' behaupten,
    weil kein Fallback ausgefuehrt wurde."""
    text = _html_text()
    idx = text.find("}else if(status==='diverged'){")
    assert idx > 0, "diverged-Block fehlt"
    block = text[idx:idx + 600]
    assert "Solver konvergierte nicht" in block
    # Wichtiger Negativ-Check: kein 'House-Matrix-Default verwendet'.
    assert "House-Matrix-Default verwendet" not in block


def test_alter_sammeltext_ist_weg():
    """Regression-Wache: der irrefuehrende alte Banner-String darf nicht
    mehr als user-facing Text gesetzt werden. (Kommentare/Doku in denen
    der alte Text erwaehnt wird sind erlaubt, solange er nicht zugewiesen
    wird.)
    """
    text = _html_text()
    bad = "'Solver konvergierte nicht — House-Matrix-Default verwendet"
    assert bad not in text, (
        "Alter pauschaler Banner-Text wird noch zugewiesen — Fix unvollstaendig"
    )


def test_status_pill_kennt_converged_robustified():
    """converged_robustified ist KEIN Warn-Status (Solver hat feasible
    Loesung gefunden), aber war im Pill-Mapping nicht abgebildet."""
    text = _html_text()
    assert "converged_robustified:'Konvergiert (robustifiziert)'" in text
    # Im setStatusPill-Block: separater Zweig vor dem Warn-Sammelblock.
    pill_block_start = text.find("function setStatusPill(")
    pill_block_end = text.find("\n}\n", pill_block_start)
    pill_block = text[pill_block_start:pill_block_end]
    assert "s==='converged_robustified'" in pill_block
