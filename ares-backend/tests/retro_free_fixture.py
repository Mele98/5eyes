"""H7 C-4: Testhilfe fuer Finalisierungs-Fixtures.

Seit dem Retro-Gate (services/cost_disclosure.py::retrocession_finalization_block)
ist ein Lauf mit Produkten unbekannter Retrozession (``retrocession_bps``
NULL) nicht finalisierbar (Art. 26 FIDLEG, fail-closed). Bestehende Tests,
die etwas anderes als die Retrozession pruefen, erklaeren ihre Fixture-
Produkte ausdruecklich als retrozessionsfrei -- mit Quelle, nie stillschweigend.
"""
from __future__ import annotations

from sqlalchemy import text

RETRO_FREE_SOURCE = "Testfixture: retrozessionsfrei (H7 C-4)"


def declare_all_products_retro_free(session) -> None:
    session.execute(
        text(
            "UPDATE products SET retrocession_bps = 0, retrocession_source = :src "
            "WHERE retrocession_bps IS NULL"
        ),
        {"src": RETRO_FREE_SOURCE},
    )
    session.flush()
