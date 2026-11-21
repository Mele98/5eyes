"""KN7 (H-181-Pruefung, CTO-Nachtrag Punkte 3/4): kurze Referenzen im Kunden-PDF.

Kunden-PDFs zeigen keine internen Kennungen (UUIDs) und keine vollen Hashes,
sondern eine kurze Nummer bzw. Prüfsumme (die ersten 8 Zeichen), wie der
Depotcheck seit KN6 (``Prüfsumme <8 Zeichen>``). Die vollständigen Werte
bleiben unverändert in DB, Audit-Log, Archiv-Hash und in der Berater-/
Audit-Fassung (``advisor_annex=True``).
"""
from __future__ import annotations

import re

REFERENCE_CHARS = 8

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_SHA_LABELLED = re.compile(r"SHA-256\s+([0-9a-fA-F]{16,})")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{16,}\b")


def short_reference(value) -> str:
    """Erste 8 Zeichen einer Kennung/eines Hashes; leer -> «-»."""
    text = str(value or "").strip()
    return text[:REFERENCE_CHARS] if text else "-"


def customer_reference_text(text: str) -> str:
    """Kürzt Kennungen in einem Kundentext: «SHA-256 <hex>» -> «Prüfsumme
    <8>», UUID und Hex-Folgen ab 16 Zeichen -> erste 8 Zeichen."""
    text = _SHA_LABELLED.sub(lambda m: "Prüfsumme " + m.group(1)[:REFERENCE_CHARS], str(text))
    text = _UUID.sub(lambda m: m.group(0)[:REFERENCE_CHARS], text)
    return _LONG_HEX.sub(lambda m: m.group(0)[:REFERENCE_CHARS], text)
