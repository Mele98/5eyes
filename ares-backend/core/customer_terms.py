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

# (Umschrift in den Daten, Anzeigeform) -- nur eindeutige Namensbestandteile
# von Sub-Anlageklassen/Musterprodukten (wie ``aresTerm``). Bewusst kein
# allgemeines Wort wie "Liquiditaet": das kaeme auch in Prosa vor und wuerde
# einen Satz nur halb umstellen.
DATA_TERM_DISPLAY = (
    ("Schwellenlaender", "Schwellenländer"),
    ("schwellenlaender", "schwellenländer"),
    ("Gluecksspiel", "Glücksspiel"),
)


def customer_term(text) -> str:
    """Anzeigeform fuer Kunden-PDFs (unveraendert, wenn kein Datenbegriff)."""
    value = "" if text is None else str(text)
    for old, new in DATA_TERM_DISPLAY:
        if old in value:
            value = value.replace(old, new)
    return value


# CCX P5 (Vertrag §8): jedes Kunden-PDF nennt den versiegelten Beratungsentscheid,
# aus dem seine Zahlen stammen (Pruefnummer = erste 12 Zeichen des Envelope-
# Hashes, Fassung = Schema-Version), oder ausdruecklich, dass keiner gebunden ist.
DECISION_NONE_TEXT = "Beratungsentscheid: keiner versiegelt"


# N-925-05: solange der Risikoparametersatz nicht IC-freigegeben ist, traegt
# jedes Kunden-PDF diesen Vermerk (Text = core.risk_parameter_set.IC_UNRELEASED_LABEL).
IC_UNRELEASED_FOOTER = "Vorlagewerte – nicht IC-freigegeben"


def decision_footer_label(decision_ref) -> str:
    ref = decision_ref or {}
    if not ref.get("envelope_hash"):
        label = DECISION_NONE_TEXT
    else:
        label = (f"Beratungsentscheid: {str(ref['envelope_hash'])[:12]} "
                 f"· Fassung {ref.get('fassung') or '1'}")
    status = ref.get("ic_release_status")
    if status is not None and status != "RELEASED":
        label += " · " + IC_UNRELEASED_FOOTER
    return label
