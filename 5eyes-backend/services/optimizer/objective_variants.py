"""Austauschbarer Primaerterm der Zielfunktion.

OPTIMIZER-OBJECTIVE-VARIANTS-001
================================

Der Solver optimierte genau eine Zielfunktion: den gewichteten
Shortfall-MSE gegen die Ziele, plus Chance-Penalty, plus einen winzigen
Volatilitaetsterm (``combined_objective_two_phase``). Fuer einen Teil der
Mandate ist das nicht die Frage, die der Kunde stellt. "Ich will nicht sehen,
dass mein Depot mehr als X verliert" ist eine Drawdown-Frage, nicht eine
Zielerreichungs-Frage; "so wenig Schwankung wie moeglich bei mindestens Y"
ist eine Volatilitaetsfrage.

Dieses Modul macht den **Primaerterm** austauschbar. Es aendert nichts an der
Standard-Methodik: ``goal_shortfall`` bleibt der Default und das einzige
Verhalten, wenn ``OPTIMIZER_OBJECTIVE`` nicht gesetzt ist.

Drei Entwurfsentscheidungen, die das Ganze tragen
-------------------------------------------------

**1. Die Goal-Chance-Penalty bleibt in JEDER Variante aktiv.**

Ein Berater, der "minimiere CVaR" waehlt, darf keine Allokation bekommen, die
die Ziele des Mandats aufgibt. Die Zielfunktion ist deshalb immer

    primaerterm(modus) + chance_penalty(ziele)

und die Chance-Penalty ist mit ``LAMBDA_CHANCE_DEFAULT = 1e6`` um Groessen-
ordnungen dominanter als jeder Primaerterm -- sie wirkt als nahezu harte
Nebenbedingung. Eine Variante verschiebt also, welche Allokation unter den
ziel-zulaessigen die beste ist, nicht ob die Ziele ueberhaupt zaehlen. Das ist
der Unterschied zu einem freien Menue von Zielfunktionen: eine Risikomass-
Optimierung ohne Ziel-Untergrenze waere ein Eignungsrisiko.

**2. Jeder Primaerterm ist dimensionslos und in derselben Groessenordnung.**

``shortfall_objective`` normalisiert jeden Rappen-Fehlbetrag auf
``initial_wealth_rappen``, liegt also typisch in [0, 1]. Waere eine Variante
in Rappen oder Rappen^2 skaliert, wuerde die Chance-Penalty entweder voellig
verschwinden oder den Primaerterm voellig erdruecken -- die Variante waere
nominell vorhanden und praktisch wirkungslos. Alle Varianten hier sind
Renditen, Renditestandardabweichungen oder Verlustanteile, also einheitenfrei
und in einem vergleichbaren Band.

**3. Jedes Risikomass laeuft auf den CASHFLOW-NEUTRALEN Renditefaktoren,
nicht auf den Vermoegenspfaden.**

Die Vermoegenspfade enthalten Ein- und Auszahlungen. Ein Verzehr-Mandat
verliert Jahr fuer Jahr Vermoegen durch geplante Ausgaben, voellig unabhaengig
vom Markt. Ein Risikomass darauf gerechnet wuerde den Pensionsverzehr als
Risiko ausweisen und defensive Entnahme-Mandate systematisch als riskant
bewerten -- derselbe Fehler, den #AA-10 fuer den berichteten Max-Drawdown und
#AA-4/#AA-5 fuer VaR und CAGR behoben haben. Die Varianten verlangen deshalb
``portfolio_return_factors`` und arbeiten ausschliesslich damit; fehlt das
Argument, ist das ein Fehler und kein Rueckfall auf die Vermoegenspfade.

Die Ziele selbst bleiben korrekt auf den Vermoegenspfaden bewertet -- ein Ziel
IST eine Frage an das Vermoegen inklusive Cashflows.

Was ``min_volatility`` genau misst
----------------------------------

Gemessen wird die Streuung der **Einperioden**-Portfoliorendite ueber Pfade
und Jahre -- die Jahr-zu-Jahr-Volatilitaet, also die Unruhe des Verlaufs. Das
ist, was ein Kunde mit "so wenig Schwankung wie moeglich" meint, und dieselbe
Groesse, die ``sqrt(w' Sigma w)`` analytisch liefert. Nachgemessen gegen
vorgegebene Sigmas von 12 % bis 40 %: Abweichung hoechstens 0.0002.

Korrektur 2026-10-14 (OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001)
.............................................................

Hier stand bis dahin die Streuung der **annualisierten Endrendite**, mit der
Begruendung, beide Lesarten fuehrten wegen ``sigma_ann ~ sigma_1J / sqrt(T)``
zur gleichen Rangfolge. Dieser Satz ist falsch -- er gilt fuer LOG-Renditen,
nicht fuer die arithmetische Streuung des annualisierten Faktors.

Bei lognormalen Jahresfaktoren ist ``R_ann = exp(X/T)`` mit
``X ~ N(T*l, T*s^2)``, also ``R_ann`` lognormal mit ``(l, s^2/T)`` und

    sd(R_ann) = exp(l + s^2/(2T)) * sqrt(exp(s^2/T) - 1)

Der Vorfaktor ``exp(l + ...)`` waechst mit dem Log-Mean. Das Mass war damit
MEAN-ABHAENGIG und ordnete teilweise nach Rendite statt nach Risiko.
Gegenbeispiel mit der echten Produktfunktion (12 Jahre, 200'000 Pfade, Seed
20261011, lognormale Faktoren wie in der Scenario-Engine):

    A: Mean +5.5 %, Einperioden-Std 0.39983, log-Var 0.1342 -> altes Mass 0.105348
    B: Mean -5.0 %, Einperioden-Std 0.40032, log-Var 0.1636 -> altes Mass 0.103446

A schwankt weniger und hat die kleinere Log-Varianz, wurde aber SCHLECHTER
bewertet. Die Rangumkehr tritt innerhalb der iid-Annahme auf, unter der die
Aequivalenz behauptet wurde -- sie war nicht erst durch Zinsstruktur oder
zeitvariable Volatilitaet verletzt, sondern von Anfang an.

Die Annualisierung bleibt fuer ``cvar_return`` und ``max_return`` richtig:
dort ist die Verteilung des ERGEBNISSES die Frage, nicht die Unruhe des Wegs.

Max-Drawdown: bewusst auf dem Jahresgitter
------------------------------------------

``max_drawdown`` misst den Drawdown auf dem Jahresgitter, nicht auf dem
brueckenverfeinerten Gitter aus DRAWDOWN-TIME-GRID-001. Die Verfeinerung in
jeder Solver-Iteration waere unbezahlbar (SLSQP-Multi-Start ruft die
Zielfunktion tausende Male).

Das ist eine bekannte Verzerrung, nicht eine uebersehene: das Jahresgitter
unterschaetzt den Drawdown umso staerker, je volatiler das Portfolio ist (3.0
bis 10.0 Prozentpunkte zwischen 20 % und 100 % Aktienquote). Als
ZIELFUNKTION heisst das, dass der Optimierer riskantere Allokationen leicht
bevorzugt -- genau der Effekt, den DRAWDOWN-TIME-GRID-001 fuer die
BERICHTETE Kennzahl behoben hat.

Die Antwort ist dieselbe Architektur wie bei der Post-Selection-
Zertifizierung: billig optimieren, **den Gewinner** auf dem genauen Mass
nachrechnen und die Differenz ausweisen (siehe
``refined_drawdown_check_for_winner``). Der Optimierer sucht also auf einem
guenstigen Proxy, und was danach als Kennzahl ausgewiesen und zertifiziert
wird, ist das genaue Mass -- mit einem Hinweis, wenn die Proxy-Verzerrung die
Entscheidung tatsaechlich bewegt haette.
"""

from __future__ import annotations

import numpy as np

from config import OBJECTIVE_MODES, validate_objective_mode

OBJECTIVE_GOAL_SHORTFALL = "goal_shortfall"
OBJECTIVE_CVAR_RETURN = "cvar_return"
OBJECTIVE_MAX_DRAWDOWN = "max_drawdown"
OBJECTIVE_MIN_VOLATILITY = "min_volatility"
OBJECTIVE_MAX_RETURN = "max_return"

DEFAULT_OBJECTIVE_MODE = OBJECTIVE_GOAL_SHORTFALL

# Tail-Anteil fuer cvar_return. 0.05 = Mittel der schlechtesten 5 % Pfade.
CVAR_TAIL_FRACTION = 0.05

# Menschenlesbare Begruendung pro Variante -- landet im Nachweis, damit im
# Bericht nicht nur ein Schluessel steht, sondern wonach optimiert wurde.
OBJECTIVE_DESCRIPTIONS: dict[str, str] = {
    OBJECTIVE_GOAL_SHORTFALL: (
        "Minimiert den gewichteten quadratischen Zielfehlbetrag ueber alle "
        "Szenarien (Standard)."
    ),
    OBJECTIVE_CVAR_RETURN: (
        "Minimiert den Expected Shortfall der Jahresrendite: das Mittel der "
        f"schlechtesten {int(CVAR_TAIL_FRACTION * 100)} % Szenarien."
    ),
    OBJECTIVE_MAX_DRAWDOWN: (
        "Minimiert den erwarteten maximalen Peak-to-Trough-Verlust des "
        "cashflow-neutralen Portfolioindex."
    ),
    OBJECTIVE_MIN_VOLATILITY: (
        # OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001: hiess "Streuung der
        # annualisierten Portfoliorendite". Dieser Text geht in den
        # Nachweis-Block (objective_basis) und damit in Modellbasis, API und
        # PDF -- eine falsche Beschreibung dort ist kein Schoenheitsfehler,
        # sondern ein falscher Nachweis darueber, wonach optimiert wurde.
        "Minimiert die Jahr-zu-Jahr-Schwankung der Portfoliorendite "
        "(Einperioden-Volatilitaet) ueber die Szenarien."
    ),
    OBJECTIVE_MAX_RETURN: (
        "Maximiert die erwartete annualisierte Portfoliorendite innerhalb "
        "des Risikobudgets und der Bandbreiten."
    ),
}

# Varianten, die die cashflow-neutralen Renditefaktoren brauchen.
_NEEDS_RETURN_FACTORS = frozenset(
    {
        OBJECTIVE_CVAR_RETURN,
        OBJECTIVE_MAX_DRAWDOWN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_RETURN,
    }
)


class ObjectiveModeError(ValueError):
    """Unzulaessiger oder unbenutzbarer Objective-Modus (nie ein Fallback)."""


class ObjectiveDomainError(ValueError):
    """Eingangswerte, mit denen kein Schaetzer rechnen darf.

    OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001. Traegt einen STABILEN
    ``reason_code``, damit die Ablehnung maschinell unterscheidbar bleibt und
    nicht nur als Freitext in einem Log landet.

    Bewusst von ``ValueError`` abgeleitet und NICHT von
    ``SolverTechnicalError``: die Fallback-Allowlist der Produktionsgrenze
    (``portfolio_engine_optimizer_integration.py``, ``except
    (SolverTechnicalError, FloatingPointError, LinAlgError)``) schliesst
    ungueltige Domaeneneingaben ausdruecklich aus. Ein Domaenenfehler darf
    also nicht in den House-Matrix-Fallback kippen, sondern muss den Lauf
    scheitern lassen -- eine stillschweigend "regulaere" Empfehlung aus
    ungueltigen Eingaben waere das schlechtere Ergebnis.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


def resolve_objective_mode() -> str:
    """Aktiver Objective-Modus, zentral fail-closed validiert.

    Bewusst ein Live-Read der Umgebung und keine beim Prozessstart
    eingefrorene Konstante -- dieselbe Begruendung wie bei
    ``resolve_goal_weighting_mode()``: eine Konfigurationsaenderung muss beim
    naechsten Optimierungslauf wirken, ohne Neustart. Es gibt genau diese eine
    Aufrufstelle fuer die Umgebungsvariable, damit "welche Mathematik hat
    diesen Lauf erzeugt" eine einzige Quelle hat.
    """
    import os

    return validate_objective_mode(os.environ.get("OPTIMIZER_OBJECTIVE"))


def objective_basis(mode: str | None = None) -> dict[str, object]:
    """Nachweis-Block: wonach optimiert wurde.

    Ohne diesen Block waeren zwei Laeufe, die GENUIN verschiedene
    Zielfunktionen optimiert haben, im Audit-Trail nicht unterscheidbar --
    exakt die Luecke, die CERT-OPTIMIZER-OBJECTIVE-001 fuer die
    Ziel-Gewichtung geschlossen hat.
    """
    resolved = validate_objective_mode(mode) if mode is not None else resolve_objective_mode()
    return {
        "mode": resolved,
        "description": OBJECTIVE_DESCRIPTIONS[resolved],
        "goal_chance_constraint_active": True,
        "risk_measure_basis": (
            "cashflow_neutral_portfolio_return_factors"
            if resolved in _NEEDS_RETURN_FACTORS
            else "wealth_paths_vs_goal_liabilities"
        ),
        "available_modes": list(OBJECTIVE_MODES),
    }


# ── Gewichtete Schaetzer (Importance Sampling) ───────────────────────────────
#
# Jede Variante muss die Likelihood-Ratio-Gewichte beruecksichtigen. Ohne sie
# schaetzt ein Primaerterm sein Mass als uniformes Sample-Mean ueber
# IS-geshiftete Pfade und ist verzerrt -- dieselbe Falle, die bei der
# Chance-Penalty unter OPT-1 dokumentiert ist.


def _normalized_weights(
    weights: np.ndarray | None, n_paths: int
) -> np.ndarray | None:
    """Likelihood-Ratio-Gewichte normalisieren -- fail-closed.

    OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: hier wurden vorher nur die
    FORM und eine positive SUMME geprueft. Damit passierten:

    * einzelne negative Gewichte -- gemessen ``values=[0,1]``,
      ``weights=[-1,2]`` -> ``weighted_mean = 2.0``, ein gewichteter
      Mittelwert AUSSERHALB des Wertebereichs, und ``weighted_std = 0.0``,
      weil die negative Varianzsumme in ``weighted_std`` still auf 0 geklemmt
      wird;
    * ``nan`` und ``inf`` -- ``nan <= 0.0`` und ``inf <= 0.0`` sind beide
      False, die Summenpruefung laesst sie also durch, und das Ergebnis wird
      ``nan``.

    Ein Likelihood-Ratio ist eine Dichteverhaeltnis: nichtnegativ und finit,
    mit mindestens einer positiven Masse. Alles andere ist kein gueltiges
    Sample, sondern ein Defekt weiter oben -- und darf nicht als
    Optimierungsergebnis weiterlaufen.
    """
    if weights is None:
        return None
    array = np.asarray(weights, dtype=np.float64).reshape(-1)
    if array.shape[0] != n_paths:
        raise ValueError(f"weights.shape[0]={array.shape[0]} != n_paths={n_paths}")
    if not np.all(np.isfinite(array)):
        n_bad = int(np.count_nonzero(~np.isfinite(array)))
        raise ObjectiveDomainError(
            "objective_weights_not_finite",
            f"{n_bad} von {array.shape[0]} Likelihood-Gewichten sind nicht "
            "endlich (nan/inf).",
        )
    if np.any(array < 0.0):
        n_bad = int(np.count_nonzero(array < 0.0))
        raise ObjectiveDomainError(
            "objective_weights_negative",
            f"{n_bad} von {array.shape[0]} Likelihood-Gewichten sind negativ; "
            "ein Dichteverhaeltnis ist nichtnegativ.",
        )
    total = float(np.sum(array))
    # Nach den beiden Pruefungen oben ist `total` endlich und >= 0; <= 0
    # bedeutet jetzt genau "keine positive Masse".
    if total <= 0.0:
        raise ObjectiveDomainError(
            "objective_weights_no_positive_mass",
            "Die Summe der Likelihood-Gewichte ist 0; kein Pfad traegt Masse.",
        )
    return array / total


def weighted_mean(values: np.ndarray, weights: np.ndarray | None) -> float:
    normalized = _normalized_weights(weights, values.shape[0])
    if normalized is None:
        return float(np.mean(values))
    return float(np.sum(values * normalized))


def weighted_std(values: np.ndarray, weights: np.ndarray | None) -> float:
    normalized = _normalized_weights(weights, values.shape[0])
    if normalized is None:
        return float(np.std(values))
    mean = float(np.sum(values * normalized))
    deviations = values - mean
    return float(np.sqrt(max(0.0, np.sum(normalized * deviations * deviations))))


def weighted_lower_tail_mean(
    values: np.ndarray,
    weights: np.ndarray | None,
    *,
    tail_fraction: float = CVAR_TAIL_FRACTION,
) -> float:
    """Expected Shortfall: gewichtetes Mittel des unteren ``tail_fraction``-Anteils.

    Implementiert ueber die sortierte Verteilung und die kumulierte
    Gewichtsmasse, damit das Ergebnis auch unter Importance Sampling den
    Tail der ZIELverteilung trifft und nicht den der Vorschlagsverteilung.
    Der Grenzpfad wird anteilig beruecksichtigt, sonst waere die Kennzahl
    nicht stetig in den Gewichten und der Solver saehe kuenstliche Spruenge.
    """
    n_paths = values.shape[0]
    if n_paths == 0:
        return 0.0
    tail_fraction = float(min(1.0, max(1e-9, tail_fraction)))
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    normalized = _normalized_weights(weights, n_paths)
    if normalized is None:
        ordered_weights = np.full(n_paths, 1.0 / n_paths)
    else:
        ordered_weights = normalized[order]

    cumulative = np.cumsum(ordered_weights)
    # Index des ersten Pfades, bei dem die kumulierte Masse das Tail-Quantil
    # erreicht; alles davor liegt vollstaendig im Tail.
    cutoff = int(np.searchsorted(cumulative, tail_fraction, side="left"))
    cutoff = min(cutoff, n_paths - 1)
    full_mass = cumulative[cutoff - 1] if cutoff > 0 else 0.0
    partial_mass = max(0.0, tail_fraction - float(full_mass))
    contribution = float(
        np.sum(ordered_values[:cutoff] * ordered_weights[:cutoff])
        + ordered_values[cutoff] * partial_mass
    )
    return contribution / tail_fraction


# ── Primaerterme ─────────────────────────────────────────────────────────────


def _annualized_returns_from_factors(factors: np.ndarray) -> np.ndarray:
    """Annualisierte Rendite pro Pfad aus den Jahres-Wachstumsfaktoren.

    Geometrisch (Mittel der Log-Faktoren), gleiche Konvention wie
    ``solver._annualized_twr_bps_per_path`` -- die Kennzahl darf nicht davon
    abhaengen, welche Stelle sie berechnet.

    Erwartet bereits gepruefte Faktoren (``_require_valid_growth_factors``).
    Das vormalige ``np.maximum(..., 1e-12)`` ist entfernt: es war keine
    Absicherung, sondern eine stille Umdeutung ungueltiger Eingaben, und
    ``nan`` kam ohnehin durch. Beide Aufrufer pruefen jetzt vorher.
    """
    values = np.asarray(factors, dtype=np.float64)
    return np.exp(np.mean(np.log(values), axis=1)) - 1.0


def _require_valid_growth_factors(factors: np.ndarray) -> None:
    """Wachstumsfaktoren muessen endlich und strikt positiv sein.

    OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: die Helfer unten klemmten
    jeden nicht-positiven Faktor still auf ``1e-12``
    (``np.maximum(factors, 1e-12)``). Das ist keine Absicherung, sondern eine
    stille Umdeutung: ein Faktor 0 oder -0.3 wird damit zu "Totalverlust in
    diesem Jahr" und laeuft als regulaeres Schaetzergebnis weiter. Gemessen
    (Codex-Review, nachgerechnet): ein Null-Faktor ergab
    ``max_return``-Objective 0.4999995, ein negativer ergab
    ``max_drawdown`` 0.4999999999995 -- plausibel aussehende Zahlen aus
    ungueltigen Eingaben.

    ``nan`` passierte sogar unbemerkt: ``np.maximum(nan, 1e-12)`` ist ``nan``,
    und ``log(nan)`` ebenfalls -- die Variante lieferte dann ``nan`` als
    Objective.

    Ein Wachstumsfaktor ist ein multiplikativer Vermoegensfaktor eines
    Jahres. Null oder negativ bedeutet "Vermoegen weg oder vorzeichen-
    gewechselt" und kann aus der lognormalen Scenario-Engine nicht entstehen;
    tritt es auf, ist weiter oben etwas kaputt. Der regulaere Pfad erzeugt
    unter validierten Parametern immer positive Faktoren -- diese Pruefung
    kostet dort nur den Vergleich und aendert kein Ergebnis.
    """
    if not np.all(np.isfinite(factors)):
        n_bad = int(np.count_nonzero(~np.isfinite(factors)))
        raise ObjectiveDomainError(
            "objective_factors_not_finite",
            f"{n_bad} von {factors.size} Renditefaktoren sind nicht endlich "
            "(nan/inf).",
        )
    if np.any(factors <= 0.0):
        n_bad = int(np.count_nonzero(factors <= 0.0))
        worst = float(np.min(factors))
        raise ObjectiveDomainError(
            "objective_factors_not_positive",
            f"{n_bad} von {factors.size} Renditefaktoren sind nicht strikt "
            f"positiv (kleinster: {worst!r}); ein Jahres-Wachstumsfaktor ist "
            "strikt positiv.",
        )


def _one_period_return_dispersion(
    factors: np.ndarray, weights: np.ndarray | None,
) -> float:
    """Streuung der EINPERIODEN-Renditen, ueber Pfade UND Jahre.

    OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001: das ist "die Unruhe des Verlaufs"
    -- die Groesse, die der Modul-Docstring selbst als die benennt, die ein
    Kunde mit "so wenig Schwankung wie moeglich" meint, und die
    ``sqrt(w' Sigma w)`` analytisch liefert.

    Bei iid-Jahren ist der gepoolte Stichproben-Std der Jahresrenditen deren
    direkter Schaetzer. Nachgemessen gegen vorgegebene Einperioden-Sigmas von
    12 % bis 40 %: Abweichung hoechstens 0.0002 bei 200'000 Pfaden und 12
    Jahren.

    Vorher wurde hier die Streuung der ANNUALISIERTEN Endrendite gemessen.
    Die ist bei lognormalen Faktoren MEAN-ABHAENGIG: mit
    ``R_ann = exp(X/T)``, ``X ~ N(T*l, T*s^2)`` ist ``R_ann`` lognormal mit
    ``(l, s^2/T)``, also

        sd(R_ann) = exp(l + s^2/(2T)) * sqrt(exp(s^2/T) - 1)

    Der Faktor ``exp(l + ...)`` waechst mit dem Log-Mean -- ein Portfolio mit
    hoeherer erwarteter Rendite bekommt allein dadurch mehr "Volatilitaet"
    zugeschrieben. Gemessen mit der echten Produktfunktion (12 Jahre,
    200'000 Pfade, Seed 20261011):

        A: Mean +5.5 %, Einperioden-Std 0.39983  ->  altes Mass 0.105348
        B: Mean -5.0 %, Einperioden-Std 0.40032  ->  altes Mass 0.103446

    A schwankt WENIGER und wurde schlechter bewertet; B hatte sogar die
    hoehere Log-Varianz (0.1636 vs. 0.1342) und gewann, nur weil sein
    Erwartungswert niedriger war. Der Modus ordnete damit teilweise nach
    Rendite statt nach Risiko -- und das innerhalb der iid-Annahme, unter der
    der Docstring Ranggleichheit mit ``a' Sigma a`` behauptete.

    ``weights`` sind Likelihood-Ratios aus Importance Sampling und gelten pro
    PFAD. Jede Jahresbeobachtung eines Pfades traegt daher dasselbe Gewicht;
    deshalb ``np.repeat`` ueber die Jahre und nicht ``np.tile``, dessen
    Reihenfolge nicht zur zeilenweisen Flachlegung passen wuerde.
    """
    one_period_returns = np.asarray(factors, dtype=np.float64) - 1.0
    flat = one_period_returns.reshape(-1)
    if weights is None:
        return float(np.std(flat))
    path_weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    n_paths, n_years = one_period_returns.shape
    if path_weights.shape[0] != n_paths:
        # Eigene Pruefung mit eigener Meldung: `weighted_std` saehe nur die
        # flachgelegte Laenge (pfade*jahre) und wuerde eine irrefuehrende
        # Zahl nennen.
        raise ValueError(
            f"weights.shape[0]={path_weights.shape[0]} != n_paths={n_paths}"
        )
    return weighted_std(flat, np.repeat(path_weights, n_years))


def _annual_grid_max_drawdowns(factors: np.ndarray) -> np.ndarray:
    """Max-Drawdown pro Pfad als Anteil, auf dem cashflow-neutralen Index.

    Jahresgitter -- siehe Modul-Docstring, Abschnitt "Max-Drawdown".

    Erwartet bereits gepruefte Faktoren (``_require_valid_growth_factors``);
    das vormalige stille Klemmen auf ``1e-12`` ist entfernt, siehe dort.
    """
    index = np.cumprod(np.asarray(factors, dtype=np.float64), axis=1)
    ones = np.ones((index.shape[0], 1), dtype=np.float64)
    full = np.concatenate([ones, index], axis=1)
    peak = np.maximum.accumulate(full, axis=1)
    drawdown = (peak - full) / np.where(peak > 0.0, peak, 1.0)
    return drawdown.max(axis=1)


def primary_objective(
    mode: str,
    *,
    goal_shortfall_value: float,
    portfolio_return_factors: np.ndarray | None,
    weights: np.ndarray | None = None,
) -> float:
    """Primaerterm fuer den gegebenen Modus. Kleiner ist besser.

    ``goal_shortfall_value`` ist das bereits berechnete L(w) -- es wird im
    Default-Modus durchgereicht, statt hier eine zweite Implementierung
    derselben Mathematik zu halten.

    Fehlt ``portfolio_return_factors`` fuer eine Variante, die es braucht,
    ist das ein ``ObjectiveModeError``: ein Rueckfall auf die Vermoegenspfade
    wuerde geplante Entnahmen als Marktrisiko bewerten (siehe Modul-Docstring,
    Entwurfsentscheidung 3).
    """
    resolved = validate_objective_mode(mode)
    if resolved == OBJECTIVE_GOAL_SHORTFALL:
        return float(goal_shortfall_value)

    if portfolio_return_factors is None:
        raise ObjectiveModeError(
            f"Objective-Modus {resolved!r} braucht die cashflow-neutralen "
            "Renditefaktoren (portfolio_return_factors). Ein Rueckfall auf "
            "die Vermoegenspfade wuerde geplante Ein-/Auszahlungen als "
            "Marktrisiko bewerten."
        )
    factors = np.asarray(portfolio_return_factors, dtype=np.float64)
    if factors.ndim != 2 or factors.shape[0] == 0 or factors.shape[1] == 0:
        raise ObjectiveModeError(
            "portfolio_return_factors muss die Form (pfade, jahre) mit "
            f"mindestens einem Pfad und Jahr haben, bekommen: {factors.shape}."
        )
    _require_valid_growth_factors(factors)

    if resolved == OBJECTIVE_MAX_DRAWDOWN:
        return weighted_mean(_annual_grid_max_drawdowns(factors), weights)
    if resolved == OBJECTIVE_MIN_VOLATILITY:
        # OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001: Einperioden-Streuung, siehe
        # _one_period_return_dispersion. Bewusst VOR der Annualisierung, damit
        # diese Variante sie nicht mehr berechnet -- sie braucht sie nicht,
        # und in jeder SLSQP-Iteration waere das verworfene Arbeit.
        return _one_period_return_dispersion(factors, weights)

    annualized = _annualized_returns_from_factors(factors)
    if resolved == OBJECTIVE_CVAR_RETURN:
        # Expected Shortfall als positive Verlustzahl: der Tail-Mittelwert
        # wird negiert, damit "kleiner ist besser" gilt. Liegt auch der Tail
        # im Plus, wird der Term negativ und belohnt das -- bewusst nicht bei
        # 0 abgeschnitten, sonst waere die Zielfunktion dort flach und der
        # Solver bekaeme kein Gefaelle mehr.
        return -weighted_lower_tail_mean(annualized, weights)
    if resolved == OBJECTIVE_MAX_RETURN:
        return -weighted_mean(annualized, weights)

    raise ObjectiveModeError(f"Objective-Modus {resolved!r} ist nicht implementiert.")


def refined_drawdowns_per_path(
    portfolio_return_factors: np.ndarray,
    *,
    seed: int,
):
    """Verfeinerter Max-Drawdown JE PFAD (Anteil) plus die Verfeinerung selbst.

    Einzige Stelle, die cashflow-neutrale Faktoren in Jahres-Indexpfade
    uebersetzt und die Brueckenverfeinerung aufruft -- sowohl
    ``refined_drawdown_check_for_winner`` (Mittelwert) als auch der gepaarte
    Signifikanztest gegen die Hausmatrix (OPTIMIZER-DRAWDOWN-CERTIFICATION-001,
    der pfadweise Werte fuer die Bootstrap-Replikationen braucht) lesen von
    hier. Der Brueckenstrom haengt nur am Seed und an der Pfadzahl: zwei
    Allokationen auf demselben Cube mit demselben Seed sehen dasselbe
    Bruecken-Rauschen (Common Random Numbers).

    Returns ``(refined, annual_grid, refinement)`` mit ``refined`` und
    ``annual_grid`` als Arrays (pfade,) in Anteilen.
    """
    from services.drawdown_refinement import refine_max_drawdowns

    factors = np.asarray(portfolio_return_factors, dtype=np.float64)
    # OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: eigener Eingang, eigene
    # Pruefung (kein stilles Klemmen auf 1e-12).
    _require_valid_growth_factors(factors)
    index = np.cumprod(factors, axis=1)
    ones = np.ones((index.shape[0], 1), dtype=np.float64)
    annual_paths = np.concatenate([ones, index], axis=1)
    refinement = refine_max_drawdowns(annual_paths, seed=int(seed))
    refined_values = np.asarray(refinement.refined_bps, dtype=np.float64) / 10000.0
    return refined_values, _annual_grid_max_drawdowns(factors), refinement


def refined_drawdown_check_for_winner(
    portfolio_return_factors: np.ndarray,
    *,
    seed: int,
    weights: np.ndarray | None = None,
) -> dict[str, float]:
    """Rechnet den Drawdown des GEWINNERS auf dem genauen Zeitgitter nach.

    Der Modus ``max_drawdown`` optimiert auf dem Jahresgitter, weil die
    Bruecken-Verfeinerung in jeder Solver-Iteration unbezahlbar waere. Das
    Jahresgitter unterschaetzt aber volatilitaetsabhaengig, bevorzugt also
    riskantere Allokationen. Diese Funktion macht die Verzerrung fuer die
    gewaehlte Allokation sichtbar, statt sie zu verschweigen -- dieselbe
    Trennung von "worauf optimiert wurde" und "was zertifiziert wird" wie beim
    unabhaengigen Validierungs-Cube.
    """
    # OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: Pruefung der Faktoren in
    # `refined_drawdowns_per_path` -- hier wurde frueher still auf 1e-12
    # geklemmt; ein geklemmter Faktor haette eine erfundene Unterschaetzung
    # ausgewiesen.
    refined_values, annual_values, refinement = refined_drawdowns_per_path(
        portfolio_return_factors, seed=int(seed),
    )
    coarse = weighted_mean(annual_values, weights)
    refined = weighted_mean(refined_values, weights)
    return {
        "annual_grid_mean_drawdown": float(coarse),
        "refined_mean_drawdown": float(refined),
        "understatement": float(refined - coarse),
        "sub_steps_per_year": int(refinement.sub_steps),
        "model_version": refinement.model_version,
    }
