"""E2E2-03 / KN3-B N-917R2-02: Verzehr-Regel der Kunden-PDFs (reines Blatt,
nur Standardbibliothek).

Faellt der mittlere Verlauf unter null, ergeben zeitgewichtete Median-Rendite
(-100 %), Drawdown (100 %) und Sharpe-Ratio sinnlose Zahlen. Statt dieser Werte
steht in jedem Kunden-PDF "nicht aussagekräftig – Vermögen aufgebraucht ab
JJJJ" wie in der App (advisor-guidance.js ``depletionYear``/
``depletionPhrase``). Eine Quelle fuer alle Erzeuger (Anlagestrategie,
Vertrag, SOLL/IST-Vergleich, Depotcheck, Advisory-Report); Re-Exporte in
services/pdf/base.py und services/pdf/components/sollist_vergleich.py.
"""
from __future__ import annotations

NOT_MEANINGFUL = "nicht aussagekräftig"
TOTAL_LOSS_BPS = -10_000


def depletion_note(year_labels, series, offset: int = 0) -> str | None:
    """Erstes Jahr strikt unter null im Verlauf ``series`` (+ ``offset``, z. B.
    die externe Reserve wie beim gedruckten Endwert). Gleiche Regel wie die App
    (advisor-guidance.js ``depletionYear``/``depletionPhrase``): "Vermögen
    aufgebraucht ab JJJJ", bei Startwert <= 0 "Finanzierungslücke ab JJJJ"."""
    if not isinstance(series, (list, tuple)) or not series:
        return None
    values = [int(value or 0) + (int(offset) if value else 0) for value in series]
    labels = list(year_labels) if isinstance(year_labels, (list, tuple)) else []
    for index, value in enumerate(values):
        if value < 0:
            year = str(labels[index])[:4] if index < len(labels) and labels[index] is not None else None
            phrase = "Vermögen aufgebraucht" if values[0] > 0 else "Finanzierungslücke"
            return f"{phrase} ab {year}" if year else phrase
    return None


def not_meaningful_text(note: str | None) -> str:
    """Kennzahl-Ersatz bei Verzehr: "nicht aussagekräftig – <Hinweis>"."""
    return f"{NOT_MEANINGFUL} – {note}" if note else NOT_MEANINGFUL


def depleted(note: str | None, cagr_bps: int | None) -> bool:
    """Verzehr belegt (Hinweis) oder Totalverlust-Median (-100 %)."""
    return bool(note) or (cagr_bps is not None and int(cagr_bps) <= TOTAL_LOSS_BPS)
