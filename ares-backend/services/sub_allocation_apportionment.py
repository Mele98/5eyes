"""Eine Aufteilungsregel fuer Sub-Allokationen (SUB-SPLIT-ROUNDING-001).

Soll-Invariante
---------------
Ein Bucket mit ``total`` bps wird auf Sleeves mit nichtnegativen ganzzahligen
Gewichten ``w_i`` (Summe ``W > 0``) aufgeteilt. Ergebnis ``a_i``:

1. Summe exakt: ``sum(a_i) == total``.
2. Nichtnegativ, ganzzahlig.
3. Quote (Hamilton / Largest Remainder): ``a_i`` ist ``floor(total*w_i/W)``
   oder eins mehr; die ``R = total - sum(floor)`` Zusatzpunkte gehen an die
   Sleeves mit dem groessten Rest ``total*w_i mod W``. Damit gilt
   ``|a_i - total*w_i/W| < 1`` fuer jeden Sleeve, und ein Sleeve mit
   groesserem Rest verliert nie gegen einen mit kleinerem.
4. Gleiche Reste: zuerst das groessere Gewicht, dann der Label-Schluessel
   (aufsteigend), zuletzt die Eingabeposition (nur bei identischem Label
   und Gewicht). Das Ergebnis je Label ist damit unabhaengig von der
   Reihenfolge der Eingabezeilen.
5. Deterministisch: reine Ganzzahlarithmetik, keine Floats.

Dieselbe Funktion bedient den direkten Builder (deterministisch, House-
Fallback, Manual Save, Retirement/Wealth), die Normalisierung der Splits auf
10'000, die Kanonisierung des stochastischen Plans und dessen
Materialisierung. Gleiche Quote + gleiche Praeferenzen ergeben auf jedem
Pfad dieselbe Sub-Allokation.
"""
from __future__ import annotations

from typing import Sequence

SUB_ALLOCATION_APPORTIONMENT_POLICY_ID = "largest_remainder_weight_label_v1"


def apportion_bps(
    total_bps: int,
    weights: Sequence[int],
    labels: Sequence[str],
) -> list[int]:
    """Teilt ``total_bps`` nach ``weights`` auf (Regel siehe Modul-Docstring).

    ``labels`` (gleiche Laenge) bestimmt den stabilen Tie-Break. Ist die
    Gewichtssumme 0, ist das Ergebnis lauter Nullen (nichts zu verteilen).
    """
    total = int(total_bps)
    if total < 0:
        raise ValueError(f"total_bps muss >= 0 sein, erhalten {total_bps!r}.")
    if len(weights) != len(labels):
        raise ValueError("weights und labels muessen gleich lang sein.")
    clean: list[int] = []
    for weight in weights:
        if isinstance(weight, bool) or int(weight) != weight or int(weight) < 0:
            raise ValueError(
                f"Sub-Allokationsgewichte muessen ganzzahlig und >= 0 sein: {weight!r}."
            )
        clean.append(int(weight))
    weight_sum = sum(clean)
    if weight_sum <= 0 or total == 0:
        return [0] * len(clean)
    floors = [total * w // weight_sum for w in clean]
    remainders = [total * w % weight_sum for w in clean]
    residual = total - sum(floors)
    order = sorted(
        range(len(clean)),
        key=lambda i: (-remainders[i], -clean[i], str(labels[i]), i),
    )
    for i in order[:residual]:
        floors[i] += 1
    return floors


__all__ = ["SUB_ALLOCATION_APPORTIONMENT_POLICY_ID", "apportion_bps"]
