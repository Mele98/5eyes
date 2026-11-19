"""KN3-B / N-917R2-04 (E2E2-11): Anzeigeform datengebundener Fachbegriffe in
Kunden-PDFs (reines Blatt, nur Standardbibliothek).

Einige Sub-Anlageklassen und Musterprodukte tragen in den Daten historisch
eine ASCII-Umschrift (z. B. ``"Aktien Schwellenlaender"``). Diese Namen sind
Schluessel: CMA-Zeilen, Bausteine, Produkte, Eignungsregeln und gespeicherte
Allokationen verweisen darauf. Eine Umbenennung in den Daten waere eine
Migration ueber alle diese Tabellen (und ueber versiegelte Entscheide). Die
Kunden-PDFs zeigen deshalb -- wie die Oberflaeche (``aresTerm`` in
ares-desktop/frontend/mandate-view.js) -- die Anzeigeform mit echten Umlauten.

Bewusst eine abschliessende Liste bekannter Datenbegriffe statt einer
generischen ae->ä-Ersetzung: Eigennamen, Firmen- und Personennamen (z. B. in
den rechtlichen Angaben) bleiben, wie sie erfasst wurden.
"""
from __future__ import annotations

# (Umschrift in den Daten, Anzeigeform) -- Teilwort-Treffer in dieser
# Reihenfolge (laengere Begriffe zuerst), Gross/klein wie erfasst.
DATA_TERM_DISPLAY = (
    ("Schwellenlaender", "Schwellenländer"),
    ("schwellenlaender", "schwellenländer"),
    ("Gluecksspiel", "Glücksspiel"),
    ("Liquiditaetsreserve", "Liquiditätsreserve"),
    ("Liquiditaet", "Liquidität"),
)


def customer_term(text) -> str:
    """Anzeigeform fuer Kunden-PDFs (unveraendert, wenn kein Datenbegriff)."""
    value = "" if text is None else str(text)
    for old, new in DATA_TERM_DISPLAY:
        if old in value:
            value = value.replace(old, new)
    return value
