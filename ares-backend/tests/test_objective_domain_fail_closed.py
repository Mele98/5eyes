"""OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001.

Die Eingangsdomaene der Zielfunktions-Schaetzer war fail-open:
``_normalized_weights()`` prueefte nur die FORM und eine positive SUMME, und
die Faktorhelfer klemmten jeden nicht-positiven Faktor still auf ``1e-12``.
``nan`` und ``inf`` liefen durch beide Pruefungen hindurch, weil
``nan <= 0.0`` und ``inf <= 0.0`` False sind.

Die Folge waren nicht Abstuerze, sondern PLAUSIBEL AUSSEHENDE Zahlen aus
ungueltigen Eingaben -- der gefaehrlichere Fall. Dieses Modul haelt jede
dieser Umdeutungen als Ablehnung mit stabilem Reason-Code fest.

Warum Ablehnung und nicht Absicherung
-------------------------------------
Ein Likelihood-Ratio ist ein Dichteverhaeltnis und ein Wachstumsfaktor ein
multiplikativer Jahresfaktor. Negative, nicht endliche oder nicht positive
Werte koennen aus der validierten lognormalen Scenario-Engine nicht
entstehen; treten sie auf, ist weiter oben etwas kaputt. Ein Clamp macht
daraus eine Aussage ("Totalverlust in diesem Jahr"), die niemand getroffen
hat.

Und warum der Fehler NICHT in den House-Matrix-Fallback kippen darf: die
Allowlist der Produktionsgrenze
(``portfolio_engine_optimizer_integration.py``) umfasst ausdruecklich nur
``SolverTechnicalError``, ``FloatingPointError`` und ``LinAlgError`` --
"Invalid domain input ... deliberately outside this allowlist and therefore
fail closed" steht dort im Kommentar. ``ObjectiveDomainError`` leitet
deshalb von ``ValueError`` ab. Der letzte Test unten haelt das fest, damit
niemand die Klasse spaeter "hilfsbereit" in die Allowlist einhaengt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.objective_variants import (  # noqa: E402
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MAX_RETURN,
    OBJECTIVE_MIN_VOLATILITY,
    ObjectiveDomainError,
    primary_objective,
    refined_drawdown_check_for_winner,
    weighted_mean,
    weighted_std,
)

VARIANT_MODES = (OBJECTIVE_MIN_VOLATILITY, OBJECTIVE_MAX_RETURN, OBJECTIVE_MAX_DRAWDOWN)


def _good_factors(n_paths: int = 50, n_years: int = 6) -> np.ndarray:
    rng = np.random.default_rng(7)
    return 1.0 + rng.normal(0.04, 0.10, size=(n_paths, n_years))


def _objective(mode: str, factors: np.ndarray, weights=None) -> float:
    return primary_objective(
        mode,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors,
        weights=weights,
    )


# ---------------------------------------------------------------------------
# Gewichte
# ---------------------------------------------------------------------------


def test_negative_weight_no_longer_produces_a_mean_outside_the_value_range():
    """Der Reproducer aus dem Review, nachgerechnet.

    Gemessen vor dem Fix: ``values=[0,1]`` mit ``weights=[-1,2]`` ergab
    ``weighted_mean = 2.0`` -- ein gewichteter Mittelwert AUSSERHALB des
    Wertebereichs [0, 1]. Und ``weighted_std = 0.0``, weil die negative
    Varianzsumme in ``weighted_std`` durch ``max(0.0, ...)`` still auf 0
    geklemmt wird: maximale Verzerrung, als vollkommene Sicherheit
    ausgewiesen.
    """
    values = np.array([0.0, 1.0], dtype=np.float64)
    bad_weights = np.array([-1.0, 2.0], dtype=np.float64)

    with pytest.raises(ObjectiveDomainError) as mean_error:
        weighted_mean(values, bad_weights)
    assert mean_error.value.reason_code == "objective_weights_negative"

    with pytest.raises(ObjectiveDomainError) as std_error:
        weighted_std(values, bad_weights)
    assert std_error.value.reason_code == "objective_weights_negative"

    # Gegenprobe: gueltige Gewichte rechnen weiter, und zwar richtig.
    assert weighted_mean(values, np.array([1.0, 3.0])) == pytest.approx(0.75)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_weights_are_rejected(bad):
    """``nan`` und ``inf`` kamen durch, weil ``nan <= 0`` False ist.

    Gemessen vor dem Fix: ``weights=[nan,1]`` und ``weights=[inf,1]``
    lieferten beide ``weighted_mean = nan`` -- kein Fehler, nur ein
    stillschweigend unbrauchbares Ergebnis, das in Vergleich und Ranking
    weiterlief.
    """
    values = np.array([0.0, 1.0], dtype=np.float64)
    weights = np.array([bad, 1.0], dtype=np.float64)

    with pytest.raises(ObjectiveDomainError) as exc:
        weighted_mean(values, weights)
    assert exc.value.reason_code == "objective_weights_not_finite"


def test_zero_total_weight_names_the_missing_mass():
    """Nullsumme war schon vorher abgelehnt -- jetzt mit eigenem Code.

    Die Unterscheidung ist nicht kosmetisch: "kein Pfad traegt Masse" ist ein
    anderer Defekt als "ein Gewicht ist negativ", und nur mit getrennten
    Codes laesst sich das eine vom anderen unterscheiden, ohne
    Fehlermeldungen zu parsen.
    """
    values = np.array([0.0, 1.0], dtype=np.float64)
    with pytest.raises(ObjectiveDomainError) as exc:
        weighted_mean(values, np.zeros(2, dtype=np.float64))
    assert exc.value.reason_code == "objective_weights_no_positive_mass"


def test_uniform_weights_stay_equivalent_to_no_weights():
    """Gegenprobe: die Haertung aendert kein gueltiges Ergebnis.

    Ohne diese Zeile waere eine Implementierung, die ALLES ablehnt, von der
    richtigen nicht zu unterscheiden.
    """
    values = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    assert weighted_mean(values, np.ones(4)) == pytest.approx(float(np.mean(values)))
    assert weighted_std(values, np.ones(4)) == pytest.approx(float(np.std(values)))


# ---------------------------------------------------------------------------
# Wachstumsfaktoren
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", VARIANT_MODES)
def test_zero_factor_is_rejected_instead_of_clamped(mode):
    """Ein Null-Faktor wurde still zu ``1e-12`` -- "Totalverlust".

    Gemessen vor dem Fix: ein Null-Faktor ergab fuer ``max_return`` ein
    Objective von 0.4999995, also eine fast perfekt aussehende Zahl aus einer
    ungueltigen Eingabe. Genau diese Plausibilitaet macht den Clamp
    gefaehrlicher als einen Absturz.
    """
    factors = _good_factors()
    factors[3, 2] = 0.0
    with pytest.raises(ObjectiveDomainError) as exc:
        _objective(mode, factors)
    assert exc.value.reason_code == "objective_factors_not_positive"


@pytest.mark.parametrize("mode", VARIANT_MODES)
def test_negative_factor_is_rejected(mode):
    """Negativ bedeutet "Vermoegen mit gewechseltem Vorzeichen" -- unmoeglich.

    Gemessen vor dem Fix: ein negativer Faktor ergab fuer ``max_drawdown``
    0.4999999999995.
    """
    factors = _good_factors()
    factors[5, 1] = -0.3
    with pytest.raises(ObjectiveDomainError) as exc:
        _objective(mode, factors)
    assert exc.value.reason_code == "objective_factors_not_positive"
    # Die Meldung nennt den schlimmsten Wert, damit die Suche nach der
    # Ursache nicht bei "irgendein Faktor" beginnt.
    assert "-0.3" in str(exc.value)


@pytest.mark.parametrize("mode", VARIANT_MODES)
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_factor_is_rejected(mode, bad):
    """``np.maximum(nan, 1e-12)`` ist ``nan`` -- der Clamp sah es nie."""
    factors = _good_factors()
    factors[0, 0] = bad
    with pytest.raises(ObjectiveDomainError) as exc:
        _objective(mode, factors)
    assert exc.value.reason_code == "objective_factors_not_finite"


@pytest.mark.parametrize("mode", VARIANT_MODES)
def test_valid_factors_still_produce_a_finite_objective(mode):
    """Gegenprobe: der regulaere Pfad ist unveraendert benutzbar."""
    value = _objective(mode, _good_factors())
    assert np.isfinite(value)


def test_refined_drawdown_check_validates_its_own_input():
    """Eigener Eingang, eigene Pruefung.

    ``refined_drawdown_check_for_winner()`` schreibt die Proxy-Verzerrung des
    GEWINNERS in den Audit-Trail und klemmte dabei ebenfalls still. Ein
    geklemmter Faktor haette dort eine erfundene Unterschaetzung ausgewiesen
    -- eine Zahl, die anschliessend als Nachweis gelesen wird.
    """
    factors = _good_factors()
    # Gegenprobe zuerst: mit gueltigen Faktoren liefert die Funktion ihren
    # Nachweisblock.
    report = refined_drawdown_check_for_winner(factors, seed=11)
    assert np.isfinite(report["annual_grid_mean_drawdown"])
    assert np.isfinite(report["refined_mean_drawdown"])

    broken = _good_factors()
    broken[2, 3] = 0.0
    with pytest.raises(ObjectiveDomainError) as exc:
        refined_drawdown_check_for_winner(broken, seed=11)
    assert exc.value.reason_code == "objective_factors_not_positive"


# ---------------------------------------------------------------------------
# Die Fallback-Grenze
# ---------------------------------------------------------------------------


def test_domain_error_is_outside_the_house_matrix_fallback_allowlist():
    """Ein Domaenenfehler darf nicht als House-Matrix-Empfehlung endendurch.

    Die Produktionsgrenze faengt genau ``SolverTechnicalError``,
    ``FloatingPointError`` und ``LinAlgError`` und gibt dafuer eine audited
    House-Matrix-Allokation zurueck. Waere ``ObjectiveDomainError`` davon
    eine Unterklasse, wuerde ein Lauf aus ungueltigen Eingaben still zu einer
    scheinbar regulaeren Empfehlung -- der Fehler waere dann nur noch im Log
    sichtbar, nicht im Ergebnis.

    Dieser Test prueft die Typbeziehung direkt, statt den ganzen
    Produktionspfad zu fahren: die Allowlist ist eine ``except``-Klausel mit
    genau diesen drei Typen, und damit entscheidet allein die
    Vererbungskette.
    """
    from numpy.linalg import LinAlgError

    from services.optimizer.solver import SolverTechnicalError

    assert not issubclass(ObjectiveDomainError, SolverTechnicalError)
    assert not issubclass(ObjectiveDomainError, FloatingPointError)
    assert not issubclass(ObjectiveDomainError, LinAlgError)
    # Und sie IST ein ValueError -- der Typ, den die Allowlist-Begruendung
    # ausdruecklich als "fail closed" benennt.
    assert issubclass(ObjectiveDomainError, ValueError)


def test_allowlist_comment_still_describes_the_three_types():
    """Die Allowlist selbst, aus dem Quelltext gelesen.

    Der Test darueber prueft die Typbeziehung. Er waere aber wertlos, wenn
    jemand die ``except``-Klausel um ``ValueError`` erweitert -- dann waere
    die Vererbung unveraendert und der Fallback trotzdem offen. Deshalb hier
    zusaetzlich die Klausel selbst.
    """
    source = (
        BACKEND_ROOT / "services" / "portfolio_engine_optimizer_integration.py"
    ).read_text(encoding="utf-8")
    assert (
        "except (SolverTechnicalError, FloatingPointError, LinAlgError) as exc:"
        in source
    ), (
        "Die Fallback-Allowlist der Produktionsgrenze hat sich geaendert -- "
        "pruefen, ob ungueltige Domaeneneingaben jetzt in den "
        "House-Matrix-Fallback kippen koennen."
    )
