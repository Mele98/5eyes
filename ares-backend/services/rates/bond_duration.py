"""Laufzeitpraeferenz -> repraesentative Kurvenlaufzeit.

NS-BOND-SLEEVE-COLLAPSE-001 / NS-YIELD-RETURN-HORIZON-001
=========================================================

Die Nelson-Siegel-Kurve ist nachweislich laufzeitsensitiv (die hinterlegte
CHF-Swap-Kalibrierung per 2024-12-31 liefert 35 bps bei 2 Jahren, 50 bps bei
5 und 65 bps bei 10). Es gab aber keine Groesse, mit der ein Lauf ausdruecken
konnte, WELCHER Punkt der Kurve fuer ein Mandat gilt -- gelesen wurde immer
der fixe 5-Jahres-Punkt.

Dieses Modul definiert die Uebersetzung und, wichtiger, die
**Referenzlaufzeit**, gegen die der Tilt gerechnet wird.

Warum ueberhaupt eine Referenz
------------------------------

Die Bond-Returns des CMA (``bonds_chf_ig_return_bps`` und die
Sub-Asset-Class-Annahmen: CHF IG 180, Global Hedged 220, High Yield 420 bps)
sind Basis-plus-Spread-Groessen -- sie enthalten den Kreditaufschlag. Die
NS-Kurve ist dagegen eine Swap-/Staatskurve ohne Kreditaufschlag.

Setzt man den Bond-Return auf den Kurvenwert, verschwindet der gesamte
Kreditaufschlag: ein gewichteter Obligationen-Return von 228 bps wird zu
50 bps, und CHF IG, Global Hedged, High Yield und Emerging kollabieren auf
denselben Wert. Die Kurve darf also nicht das NIVEAU setzen, sondern nur die
TERMSTRUKTUR beitragen:

    bonds_return = cma_gewichteter_return + ( y(laufzeit) - y(referenz) )

Die Referenz ist die Laufzeit, auf die die CMA-Bond-Returns implizit quotiert
sind. Das ist im Datenmodell nirgends hinterlegt -- das CMA hat keine
Laufzeit-Dimension. Gewaehlt wird deshalb
``NELSON_SIEGEL_DEFAULT_MATURITY_YEARS`` (5.0), weil genau dieser Punkt schon
vorher die einzige gelesene Laufzeit war: die Annahme ist damit nicht neu,
sondern nur ausgesprochen. Steht die Laufzeit eines Tages am CMA, ist das
hier die einzige Stelle, die sich aendert.

Folgen der Konstruktion:

* Die Sleeve-Differenzierung bleibt vollstaendig erhalten -- der Tilt ist fuer
  alle Sleeves derselbe additive Betrag, die Rangfolge CHF IG < Mix < High
  Yield also unveraendert.
* Der Kreditaufschlag bleibt vollstaendig erhalten.
* Bei Laufzeit == Referenz ist der Tilt **exakt 0**. Ein Mandat ohne
  Laufzeitpraeferenz rechnet damit genau wie vorher ohne NS-Bond-Anpassung.
* Die Groessenordnung ist fachlich plausibel: mit der hinterlegten
  CHF-Kalibrierung sind es -15 bps (kurz) bis +15 bps (lang) statt einer
  Niveau-Zerstoerung um 178 bps.

Die Laufzeit-Zuordnung
----------------------

``BOND_DURATION_MATURITY_YEARS`` uebersetzt die drei zulaessigen Werte der
``bondsDuration``-Praeferenz (siehe ``schemas/allocation.py``) in
repraesentative Kurvenpunkte. 2 / 5 / 10 Jahre folgt der ueblichen
Bond-Markt-Einteilung (kurz 1-3, mittel 3-7, lang 7-10+) und bleibt am
unteren Ende der jeweiligen Baender -- bei normal steigender Kurve ist das die
konservative Wahl, weil es den positiven Tilt begrenzt.

Das ist eine **definitorische** Festlegung (was heisst "langfristig" fuer eine
Kurvenabfrage), keine unbelegte Marktannahme: sie erfindet keinen Preis und
keine Korrelation, sondern benennt einen Abfragepunkt, den der Code vorher
implizit auf 5 Jahre festgenagelt hatte.

Was dieses Modul NICHT tut
--------------------------

Es verdrahtet die Praeferenz nicht bis zur Kurve. ``bondsDuration`` wirkt
heute ueber den Sleeve-MIX (Kurzfristig 70 % CHF IG vs. Langfristig 55 %),
also als Kredit-/Geografie-Verschiebung -- die Sleeve-Labels tragen gar keine
Laufzeit. Damit die Praeferenz zusaetzlich die Termstruktur erreicht, muss sie
durch sechs Aufrufstellen von ``_weighted_bucket_metrics()`` **und** in den
Szenario-Cache-Key wandern (sonst liefert der Cache Pfade aus der alten
Laufzeit -- derselbe Befund wie bei den effektiven ScenarioInputs). Das ist
als eigener Reproducer offen; siehe
``tests/test_ns_bond_sleeve_collapse_and_horizon_binding.py``.

Halb verdrahtet waere schlechter als gar nicht: bekaeme der Solver-Kanal den
Tilt und der Reporting-Kanal nicht, waere die Solver/Reporting-Paritaet
wieder offen, die gerade geschlossen wurde.
"""

from __future__ import annotations

from services.cma_validation import NELSON_SIEGEL_DEFAULT_MATURITY_YEARS

# Laufzeit, auf die die CMA-Bond-Returns implizit quotiert sind. Siehe
# Modul-Docstring, Abschnitt "Warum ueberhaupt eine Referenz".
CMA_REFERENCE_MATURITY_YEARS = NELSON_SIEGEL_DEFAULT_MATURITY_YEARS

# Zulaessige Werte exakt wie in schemas/allocation.py::_ALLOWED_CHOICES.
BOND_DURATION_MATURITY_YEARS: dict[str, float] = {
    "Kurzfristig": 2.0,
    "Gemischt": 5.0,
    "Langfristig": 10.0,
}


class BondDurationError(ValueError):
    """Unzulaessige Laufzeitpraeferenz (nie ein stiller Default)."""


def resolve_bond_maturity_years(preference: str | None) -> float:
    """Repraesentative Kurvenlaufzeit fuer eine ``bondsDuration``-Praeferenz.

    ``None`` (keine Praeferenz gesetzt) liefert die Referenzlaufzeit, der Tilt
    ist dann exakt 0 -- das Mandat rechnet wie ohne NS-Bond-Anpassung. Das ist
    ein neutraler Default und keine Aufweichung einer Pruefung: es gibt keine
    sichere Laufzeit, die hier "vorsichtshalber" angenommen werden koennte,
    und jede andere Wahl wuerde einem Mandat eine Termstruktur-Meinung
    unterstellen, die niemand geaeussert hat.

    Ein nicht leerer, aber unbekannter Wert ist dagegen ein Fehler. Ein
    Tippfehler darf nicht als "keine Praeferenz" durchlaufen -- das waere von
    "nicht gesetzt" ununterscheidbar.
    """
    if preference is None:
        return float(CMA_REFERENCE_MATURITY_YEARS)
    normalized = str(preference).strip()
    if not normalized:
        return float(CMA_REFERENCE_MATURITY_YEARS)
    if normalized not in BOND_DURATION_MATURITY_YEARS:
        raise BondDurationError(
            f"Unbekannte Obligationen-Laufzeitpraeferenz {preference!r}. "
            f"Zulaessig: {', '.join(sorted(BOND_DURATION_MATURITY_YEARS))}."
        )
    return float(BOND_DURATION_MATURITY_YEARS[normalized])
