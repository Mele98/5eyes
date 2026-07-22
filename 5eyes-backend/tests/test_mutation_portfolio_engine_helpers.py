"""Mutations-Tests fuer kleine, reine Helper-Formeln in
services/portfolio_engine.py (Roadmap #86).

Zweck (siehe tests/_mutation_helpers.py fuer die volle Methodik-Erklaerung):
Diese Tests beweisen, dass die Risiko-Kennzahlen-Formeln ``_return_bps``,
``_loss_bps``, ``_percentile``, ``_stddev_bps`` und ``_max_drawdown_bps``
NICHT durch eine plausible Ein-Operator-Aenderung kaputt gemacht werden
koennten, ohne dass eine Assertion anschlaegt.

Bewusst NICHT mutiert: die grosse Monte-Carlo-Simulation
(``run_scenario_simulation`` / ``_simulate_paths`` etc.) -- laut Auftrag nur
die kleinen, reinen Kennzahlen-Helper, die deterministisch und einfach
gegen Hand-Rechnungen zu verifizieren sind.

Fuer jede Mutation wird:
  1. die ECHTE Funktion via ``tests._mutation_helpers.mutate`` an genau einer
     Stelle bewusst falsch abgeaendert (Vorzeichen-Fehler, vertauschter
     Vergleich, falscher Operator, vertauschte Interpolationsgewichte --
     klassische mutmut-Mutationsarten: ArithmeticOperator,
     RelationalOperator, ComparisonOperator),
  2. dieselben Eingaben an Original und Mutant gegeben,
  3. gezeigt, dass beide unterschiedliche Ergebnisse liefern und dass das
     Original den analytisch von Hand nachgerechneten (oder aus einem
     bestehenden Test zitierten) Erwartungswert weiterhin trifft.

``_return_bps(1_000_000, 0) == -10000`` ist zusaetzlich direkt an die
bestehende Konsistenz-Assertion aus
``tests/test_aa6_annualized_return_depleted.py::test_consistent_with_return_bps_on_depletion``
gekoppelt (``_annualized_return_bps(1_000_000, 0, 5) == _return_bps(1_000_000, 0)``)
-- eine Mutation an ``_return_bps`` wuerde also nicht nur diesen Test hier,
sondern auch jenen bestehenden Regressionstest zum Kippen bringen.

Was das NICHT abdeckt
----------------------
- Nur die hier gewaehlten Mutationen, keine erschoepfende Exploration.
- ``_annualized_return_bps``, ``_twr_annualized_bps``,
  ``_conditional_percentile_average`` sind bereits anderswo direkt/indirekt
  getestet (test_aa5/test_aa6) und werden hier nicht erneut mutiert.
- Kein Ersatz fuer einen echten ``mutmut run`` unter WSL (siehe
  tests/_mutation_helpers.py, warum das hier nativ auf Windows nicht geht).
"""
from __future__ import annotations

from services import portfolio_engine as pe
from tests._mutation_helpers import mutate


# ── _return_bps ─────────────────────────────────────────────────────────────

def test_mutation_return_bps_ratio_inverted():
    """``end_value / start_value`` durch ``start_value / end_value`` ersetzt.

    Fuer +10% Wertentwicklung (1.0 Mio -> 1.1 Mio) muss die Rendite +1000 bps
    sein; die invertierte Ratio liefert etwas komplett anderes (negativ).
    """
    mutant = mutate(
        pe,
        "_return_bps",
        "return int(round((end_value / start_value - 1) * 10000))",
        "return int(round((start_value / end_value - 1) * 10000))",
    )
    real = pe._return_bps(1_000_000, 1_100_000)
    assert real == 1000
    mutated = mutant(1_000_000, 1_100_000)
    assert mutated != real


def test_mutation_return_bps_total_loss_floor_flipped():
    """Floor-Werte fuer Totalverlust vertauscht: ``-10000 if ... else 0``
    durch ``0 if ... else -10000`` ersetzt.

    Ein aufgebrauchter Pfad (end_value <= 0) muss -10000 bps (-100%) liefern,
    NICHT 0 -- sonst wird ein Totalverlust rechnerisch wie "keine
    Wertveraenderung" behandelt (verzerrt Median/Erfolgsrate nach oben, siehe
    Kommentar #AA-6 im Produktivcode). Diese Mutation wuerde zusaetzlich
    tests/test_aa6_annualized_return_depleted.py::
    test_consistent_with_return_bps_on_depletion zum Kippen bringen, da dort
    ``_annualized_return_bps(1_000_000, 0, 5) == _return_bps(1_000_000, 0)``
    direkt gegen den echten ``_return_bps``-Wert geprueft wird.
    """
    mutant = mutate(
        pe,
        "_return_bps",
        "return -10000 if end_value <= 0 else 0",
        "return 0 if end_value <= 0 else -10000",
    )
    real = pe._return_bps(1_000_000, 0)
    assert real == -10000
    mutated = mutant(1_000_000, 0)
    assert mutated != real
    assert mutated == 0


# ── _loss_bps ────────────────────────────────────────────────────────────────

def test_mutation_loss_bps_negation_dropped():
    """``max(0, -_return_bps(...))`` durch ``max(0, _return_bps(...))`` ersetzt.

    Ohne die Negation wird ein NEGATIVER Return (Verlust) durch
    ``max(0, ...)`` faelschlich auf 0 geklemmt statt als positiver
    Verlust-Betrag ausgewiesen -- ein Verlust von 20% muesste 2000 bps
    Verlust zeigen, nicht 0.
    """
    mutant = mutate(
        pe,
        "_loss_bps",
        "return max(0, -_return_bps(start_value, end_value))",
        "return max(0, _return_bps(start_value, end_value))",
    )
    real = pe._loss_bps(1_000_000, 800_000)
    assert real == 2000
    mutated = mutant(1_000_000, 800_000)
    assert mutated != real
    assert mutated == 0


# ── _percentile ──────────────────────────────────────────────────────────────

def test_mutation_percentile_interpolation_weights_swapped():
    """Interpolationsgewichte vertauscht: ``lower*(1-w) + upper*w`` durch
    ``lower*w + upper*(1-w)`` ersetzt.

    Fuer [100, 200, 300, 400] beim 25%-Quantil (Index 0.75 zwischen den
    sortierten Werten 100 und 200) muss das Original 175 liefern
    (100*0.25 + 200*0.75); die vertauschten Gewichte liefern 125
    (100*0.75 + 200*0.25) -- ein anderer, falscher Wert.
    """
    mutant = mutate(
        pe,
        "_percentile",
        "value = ordered[lower] * (1 - weight) + ordered[upper] * weight",
        "value = ordered[lower] * weight + ordered[upper] * (1 - weight)",
    )
    real = pe._percentile([100, 200, 300, 400], 0.25)
    assert real == 175
    mutated = mutant([100, 200, 300, 400], 0.25)
    assert mutated != real
    assert mutated == 125


def test_mutation_percentile_clamp_min_max_swapped():
    """Quantil-Clamp ``max(0.0, min(1.0, q))`` durch ``min(0.0, max(1.0, q))``
    ersetzt.

    Die vertauschte Clamp-Reihenfolge zwingt ``q`` in den meisten Faellen auf
    einen konstanten Grenzwert statt den echten Quantil-Wert durchzulassen.
    Fuer das 50%-Quantil von [100, 200, 300, 400] muss das Original 250
    liefern; die kaputte Clamp-Funktion liefert einen anderen Wert.
    """
    mutant = mutate(
        pe,
        "_percentile",
        "q = max(0.0, min(1.0, float(quantile)))",
        "q = min(0.0, max(1.0, float(quantile)))",
    )
    real = pe._percentile([100, 200, 300, 400], 0.5)
    assert real == 250
    mutated = mutant([100, 200, 300, 400], 0.5)
    assert mutated != real


# ── _stddev_bps ──────────────────────────────────────────────────────────────

def test_mutation_stddev_denominator_off_by_one():
    """Populations- durch Stichproben-Varianz ersetzt: Nenner ``len(values)``
    durch ``len(values) - 1`` ersetzt.

    Fuer [100, 200, 300, 400, 500] (Mittelwert 300, Populations-Varianz
    20'000) muss die Populations-Standardabweichung round(sqrt(20000)) = 141
    bps sein; mit Bessel-Korrektur (n-1 = 4 statt 5) ergibt sich ein anderer,
    hoeherer Wert.
    """
    mutant = mutate(
        pe,
        "_stddev_bps",
        "var = sum((float(v) - mean) ** 2 for v in values) / len(values)",
        "var = sum((float(v) - mean) ** 2 for v in values) / (len(values) - 1)",
    )
    real = pe._stddev_bps([100, 200, 300, 400, 500])
    assert real == 141
    mutated = mutant([100, 200, 300, 400, 500])
    assert mutated != real


def test_mutation_stddev_mean_division_dropped():
    """Mittelwert-Formel ``sum(...) / len(values)`` durch ``sum(...)``
    (Division entfernt) ersetzt.

    Ohne Division durch die Anzahl Werte ist ``mean`` die reine Summe statt
    des Durchschnitts -- die daraus abgeleitete "Standardabweichung" ist
    dann um Groessenordnungen falsch.
    """
    mutant = mutate(
        pe,
        "_stddev_bps",
        "mean = sum(float(v) for v in values) / len(values)",
        "mean = sum(float(v) for v in values)",
    )
    real = pe._stddev_bps([100, 200, 300, 400, 500])
    assert real == 141
    mutated = mutant([100, 200, 300, 400, 500])
    assert mutated != real


# ── _max_drawdown_bps ────────────────────────────────────────────────────────

def test_mutation_max_drawdown_peak_tracking_inverted():
    """Peak-Tracking ``max(peak, value)`` durch ``min(peak, value)`` ersetzt.

    Fuer den Pfad [1000, 1200, 800, 1500, 600] betraegt der maximale
    Drawdown vom Peak 1500 auf 600 = 60% = 6000 bps. Mit ``min`` statt
    ``max`` sinkt der getrackte "Peak" nur noch, der Drawdown wird nie
    korrekt gegen den echten Hoechststand gemessen.
    """
    mutant = mutate(
        pe,
        "_max_drawdown_bps",
        "peak = max(peak, value)",
        "peak = min(peak, value)",
    )
    real = pe._max_drawdown_bps([1000, 1200, 800, 1500, 600])
    assert real == 6000
    mutated = mutant([1000, 1200, 800, 1500, 600])
    assert mutated != real


def test_mutation_max_drawdown_numerator_flipped():
    """Drawdown-Zaehler ``(peak - value)`` durch ``(value - peak)`` ersetzt
    (Vorzeichen-Fehler).

    Da ``value <= peak`` immer gilt, wird der Zaehler nie positiv --
    ``max_drawdown`` bleibt bei 0 statt der korrekten 6000 bps.
    """
    mutant = mutate(
        pe,
        "_max_drawdown_bps",
        "drawdown = int(round((peak - value) / peak * 10000))",
        "drawdown = int(round((value - peak) / peak * 10000))",
    )
    real = pe._max_drawdown_bps([1000, 1200, 800, 1500, 600])
    assert real == 6000
    mutated = mutant([1000, 1200, 800, 1500, 600])
    assert mutated != real
    assert mutated == 0


def test_mutation_max_drawdown_comparator_flipped():
    """Vergleich ``drawdown > max_drawdown`` durch ``drawdown < max_drawdown``
    ersetzt (klassische RelationalOperator-Mutation).

    Die Aktualisierung des laufenden Maximums greift dann nur noch, wenn der
    aktuelle Drawdown KLEINER als das bisherige Maximum ist -- das Ergebnis
    kollabiert auf 0 statt den tatsaechlichen maximalen Drawdown zu finden.
    """
    mutant = mutate(
        pe,
        "_max_drawdown_bps",
        "if drawdown > max_drawdown:",
        "if drawdown < max_drawdown:",
    )
    real = pe._max_drawdown_bps([1000, 1200, 800, 1500, 600])
    assert real == 6000
    mutated = mutant([1000, 1200, 800, 1500, 600])
    assert mutated != real
    assert mutated == 0
