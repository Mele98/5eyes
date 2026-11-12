"""Groessen-Budget des Monolithen (Electron-Frontend, eine HTML-Datei).

Ratchet, nur sinkend: neue Fachlogik gehoert in Module bzw. die React-App,
nicht in den Monolithen. Die Grenze ist die Zeilenzahl beim Einfuehren
des Budgets, Toleranz 0. Wer den Monolithen verkleinert, senkt
``MONOLITH_MAX_LINES`` im selben PR auf den neuen Stand; anheben ist nicht
vorgesehen (nur per ausdruecklichem Owner-Entscheid).

N-861-5 (Pruefrunde #861): zusaetzlich ein Byte-Budget. Das Zeilen-Budget
allein liess sich umgehen, indem Code an bestehende Zeilen angehaengt wird.
Gemessen mit LF-Zeilenenden (eine CRLF-Arbeitskopie zaehlt gleich). Grenze =
Stand beim Einfuehren, Toleranz 0, ebenfalls nur sinkend.

N-861-9: 1908660 = gemessener gemeinsamer Stand nach dem Merge von #858
(r5/livetest-fixes, enthaelt #853) in #861 (Merge-Reihenfolge #858 -> #861).
Kein Anheben gegenueber einem gemergten Stand: das Budget existierte nur auf
#861 (1902644), #858 brachte seine geprueften Live-Test-Fixes (+6016 Bytes)
ohne Byte-Budget mit; beide Staende werden hier zusammengefuehrt.

H3/I-04 (2026-11-07): Nach der Integrationsprobe lag der Monolith exakt am
Budget (31190 Zeilen / 1908660 Bytes). Drei in sich geschlossene Bloecke
wurden verhaltensneutral ausgelagert (ares.css, intro-sequence.js,
goal-review-runtime.js; siehe tests/monolith_source.py). Budget gesenkt auf
den neuen Stand 27675 / 1695446 (der Ratchet bleibt: nur sinkend). Die
ausgelagerten Dateien bekommen je ein eigenes Budget nach derselben Regel
(Stand beim Einfuehren, Toleranz 0) -- sonst waere die Auslagerung ein
Schlupfloch, ueber das der Monolith unbemerkt weiterwaechst.

H8 Kundeninformation/KYC/Vertretung (2026-11-07): neue Masken im neuen Teil
client-compliance.js (eigenes Budget, Stand bei Einfuehrung); sie haengen sich
selbst in Administration und Stammdaten ein. Im Monolithen nur die Einbindung;
renderAuditLogTable ist mit der Feldbezeichnung (N-873-09) in den Teil
umgezogen. Der Monolith schrumpft dabei (Budget auf den neuen Stand).

C-890-01 (2026-11-11): client-compliance.js +5 Zeilen/+727 Bytes fuer die
Statuszeile der KYC-Wiedervorlage-Policy (Budget auf den neuen Stand).
C-890-01 Nachtrag 1: neuer Teil kyc-review-policy.js (eigenes Budget, Stand bei
Einfuehrung); adminUpdateNewUserRoleHint aus dem Monolithen umgezogen -- der
Monolith schrumpft trotz Einbindung (Budget gesenkt: 27631 Z./1692930 B).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MONOLITH = REPO_ROOT / "ares-desktop" / "frontend" / "ares.html"

MONOLITH_MAX_LINES = 27631
TOLERANCE_LINES = 0
MONOLITH_MAX_BYTES = 1692930
TOLERANCE_BYTES = 0

# Ausgelagerte Teile: Dateiname -> (max. Zeilen, max. Bytes LF-normalisiert).
EXTRACTED_PART_BUDGETS = {
    "ares.css": (1162, 91800),
    "intro-sequence.js": (761, 36861),
    "goal-review-runtime.js": (1589, 84633),
    "client-compliance.js": (460, 29080),
    "kyc-review-policy.js": (296, 16405),
}


def _line_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def test_monolith_does_not_grow_beyond_budget():
    actual = _line_count(MONOLITH)
    assert actual <= MONOLITH_MAX_LINES + TOLERANCE_LINES, (
        f"Monolith hat {actual} Zeilen, Budget {MONOLITH_MAX_LINES} (Toleranz "
        f"{TOLERANCE_LINES}). Logik auslagern statt den Monolithen zu vergroessern."
    )


def _byte_count(path: Path) -> int:
    return len(path.read_bytes().replace(b"\r\n", b"\n"))


def test_monolith_does_not_grow_beyond_byte_budget():
    actual = _byte_count(MONOLITH)
    assert actual <= MONOLITH_MAX_BYTES + TOLERANCE_BYTES, (
        f"Monolith hat {actual} Bytes, Budget {MONOLITH_MAX_BYTES} (Toleranz "
        f"{TOLERANCE_BYTES}). Logik auslagern statt an bestehende Zeilen anzuhaengen."
    )


def test_byte_budget_counts_appended_code_on_existing_lines(tmp_path):
    """Gegenprobe im Kleinen: gleiche Zeilenzahl, mehr Bytes -> erkannt."""
    base = tmp_path / "m.html"
    base.write_bytes(b"a\nb\n")
    grown = tmp_path / "g.html"
    grown.write_bytes(b"a; extra()\nb\n")
    assert _line_count(base) == _line_count(grown)
    assert _byte_count(grown) > _byte_count(base)
    crlf = tmp_path / "c.html"
    crlf.write_bytes(b"a\r\nb\r\n")
    assert _byte_count(crlf) == _byte_count(base)


def test_budget_has_no_tolerance():
    assert TOLERANCE_LINES == 0
    assert TOLERANCE_BYTES == 0


def test_extracted_parts_do_not_grow_beyond_budget():
    from tests.monolith_source import EXTRACTED_PARTS

    assert {name for name, _kind in EXTRACTED_PARTS} == set(EXTRACTED_PART_BUDGETS)
    for name, (max_lines, max_bytes) in EXTRACTED_PART_BUDGETS.items():
        path = MONOLITH.parent / name
        lines, size = _line_count(path), _byte_count(path)
        assert lines <= max_lines + TOLERANCE_LINES, (
            f"{name} hat {lines} Zeilen, Budget {max_lines}. Neue Logik in eigene Module."
        )
        assert size <= max_bytes + TOLERANCE_BYTES, (
            f"{name} hat {size} Bytes, Budget {max_bytes}. Neue Logik in eigene Module."
        )
