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
    raw = [int(value or 0) for value in series]
    values = [value + (int(offset) if value else 0) for value in raw]
    labels = list(year_labels) if isinstance(year_labels, (list, tuple)) else []
    for index, value in enumerate(values):
        if value < 0:
            year = _year_of(labels[index]) if index < len(labels) else None
            # KN4-B / N-917R3-07: Wortwahl wie die App am ROHEN Startwert
            # (advisor-guidance.js), nicht am um die Reserve korrigierten.
            phrase = "Vermögen aufgebraucht" if raw[0] > 0 else "Finanzierungslücke"
            return f"{phrase} ab {year}" if year else phrase
    return None


def _year_of(label) -> str | None:
    """Kalenderjahr aus einem Jahreslabel (``2042``, ``"2042"``, ``"2042-12-31"``,
    ``"Ende 2042"``); ``None``, wenn keine vierstellige Jahreszahl 1900-2999
    enthalten ist (nie blind die ersten vier Zeichen, KN4-B N-917R3-07)."""
    text = "" if label is None else str(label)
    runs, current = [], ""
    for char in text + " ":
        if char.isdigit():
            current += char
        else:
            if current:
                runs.append(current)
            current = ""
    for run in runs:
        if len(run) == 4 and 1900 <= int(run) <= 2999:
            return run
    return None


def not_meaningful_text(note: str | None) -> str:
    """Kennzahl-Ersatz bei Verzehr: "nicht aussagekräftig – <Hinweis>"."""
    return f"{NOT_MEANINGFUL} – {note}" if note else NOT_MEANINGFUL


def depleted(note: str | None, cagr_bps: int | None) -> bool:
    """Verzehr belegt (Hinweis) oder Totalverlust-Median (-100 %)."""
    return bool(note) or (cagr_bps is not None and int(cagr_bps) <= TOTAL_LOSS_BPS)
