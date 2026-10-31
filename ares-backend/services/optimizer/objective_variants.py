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

und die Chance-Penalty ist so gewichtet, dass ein MATERIELLES Zieldefizit
mehr kostet als der ganze Wertebereich jedes Primaerterms. Eine Variante
verschiebt also, welche Allokation unter den ziel-zulaessigen die beste ist,
nicht ob die Ziele ueberhaupt zaehlen. Das ist der Unterschied zu einem freien
Menue von Zielfunktionen: eine Risikomass-Optimierung ohne Ziel-Untergrenze
waere ein Eignungsrisiko.

OBJECTIVE-NORMALIZATION-001 (2026-10-18): bis dahin war die Penalty
``1e6 * Defizit^2`` -- "um Groessenordnungen dominanter als jeder
Primaerterm". Das war zu viel des Guten: auch ein statistisch bedeutungsloses
Defizit von wenigen Pfaden ueberstimmte den ganzen Primaerterm. Gemessen auf
dem Fundament-Mandat (Strafe 1.1e6 gegen Drawdown 0.26) lieferten
``max_drawdown`` und ``min_volatility`` 67.9 % bzw. 70.3 % Aktien -- MEHR als
der Default (67.3 %). Jetzt ist die Strafe linear im Defizit mal
``(Zielvolumen / W0)^2``, also in derselben Einheit wie L(w) und die
Varianten (siehe ``objective.chance_constraint_penalty``).

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

Gemessen wird die Streuung der **Einperioden**-Portfoliorendite um den
Erwartungswert JEDER Periode, gepoolt ueber die Perioden (gepoolte
Innerhalb-Perioden-Varianz, siehe ``_one_period_return_dispersion``). Das ist,
was ein Kunde mit "so wenig Schwankung wie moeglich" meint, und je Periode
dieselbe Groesse, die ``sqrt(w' Sigma_t w)`` analytisch liefert.

Korrektur 2026-10-25 (MIN-VOLATILITY-WITHIN-PERIOD-001, CIO-Entscheid)
......................................................................

Bis Engine v15 wurde ueber Pfade UND Jahre um einen globalen Mittelwert
gepoolt. Das zaehlte die deterministische Streuung der Periodenmittel
(Zinsstruktur, Mean-Pfad) als Risiko mit: ``Var(R) = E_t[Var(R_t|t)] +
Var_t(E[R_t|t])``. Jetzt zaehlt nur der erste Summand; ein Wuerfel mit rein
deterministischen, periodenweise verschiedenen Renditen hat Vola 0, und eine
deterministische Mean-Verschiebung je Periode aendert das Mass nicht.

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

# MIN-VOLATILITY-WITHIN-PERIOD-001: Kennung des min_volatility-Schaetzers
# (gepoolte Innerhalb-Perioden-Varianz, ddof/Kish-korrigiert, quadratisches
# Zeitmittel). Steht im Nachweis-Block; ein Schaetzerwechsel braucht eine
# neue Kennung.
MIN_VOLATILITY_ESTIMATOR_VERSION = "within_period_pooled_variance_v1"

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
        # MIN-VOLATILITY-WITHIN-PERIOD-001: ein deterministischer
        # Renditeverlauf ueber die Jahre ist keine Schwankung.
        "Minimiert die Einperioden-Volatilitaet der Portfoliorendite: die "
        "Streuung ueber die Szenarien um den Erwartungswert jedes Jahres; "
        "deterministische Renditeverlaeufe zaehlen nicht als Schwankung."
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
    basis: dict[str, object] = {
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
    if resolved == OBJECTIVE_MIN_VOLATILITY:
        # Nur in diesem Modus: der Default-Nachweis bleibt bytegleich.
        basis["risk_measure_estimator"] = MIN_VOLATILITY_ESTIMATOR_VERSION
    return basis


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


def _require_finite_values(values: np.ndarray) -> None:
    """Schaetzer-WERTE muessen endlich sein -- gueltige Gewichte reinigen nichts.

    OPTIMIZER-OBJECTIVE-DOMAIN-001 (Residual, Codex-Reproducer 2026-10-14):
    ``_normalized_weights`` prueft nur die Gewichte. ``weighted_mean([0, nan],
    [1, 1])`` lieferte ``nan``, ``weighted_std([0, inf], [1, 1])`` ebenfalls
    ``nan`` -- ohne Fehler, als regulaerer Schaetzwert.
    """
    if not np.all(np.isfinite(values)):
        n_bad = int(np.count_nonzero(~np.isfinite(values)))
        raise ObjectiveDomainError(
            "objective_values_not_finite",
            f"{n_bad} von {np.size(values)} Schaetzer-Werten sind nicht "
            "endlich (nan/inf).",
        )


def _require_finite_estimate(value: float, estimator: str) -> float:
    """Ein Schaetzwert aus endlichen Werten kann trotzdem ueberlaufen.

    Summe oder Quadrat endlicher, aber grosser Werte wird ``inf`` (gemessen:
    ``weighted_mean([max, max], None) = inf``). Nur eine Pruefung, keine
    Rechenaenderung -- endliche Schaetzwerte bleiben bitidentisch.
    """
    if not np.isfinite(value):
        raise ObjectiveDomainError(
            "objective_estimate_not_finite",
            f"{estimator} ueber endliche Werte ist nicht endlich ({value!r}); "
            "numerischer Ueberlauf.",
        )
    return value


def require_finite_objective(value: float, *, where: str) -> float:
    """Zielfunktionswert fail-closed: endlich oder ``ObjectiveDomainError``.

    OPTIMIZER-OBJECTIVE-DOMAIN-001: EINE Stelle fuer den Reason-Code
    ``objective_value_not_finite`` -- jeder Ausgang von ``primary_objective``,
    die Solver-Closure (``_objective_from_inputs``/``_objective_from_array``)
    und ``evaluate_weights`` pruefen hier, BEVOR der Wert an SLSQP geht oder
    als ``objective_value`` publiziert wird. Gibt den Wert unveraendert zurueck.
    """
    result = float(value)
    if not np.isfinite(result):
        raise ObjectiveDomainError(
            "objective_value_not_finite",
            f"Zielfunktionswert in {where} ist nicht endlich ({result!r}); "
            "ein solcher Kandidat ist nicht bewertbar und wird verworfen.",
        )
    return result


def weighted_mean(values: np.ndarray, weights: np.ndarray | None) -> float:
    _require_finite_values(values)
    normalized = _normalized_weights(weights, values.shape[0])
    if normalized is None:
        return _require_finite_estimate(float(np.mean(values)), "weighted_mean")
    return _require_finite_estimate(
        float(np.sum(values * normalized)), "weighted_mean",
    )


def weighted_std(values: np.ndarray, weights: np.ndarray | None) -> float:
    _require_finite_values(values)
    normalized = _normalized_weights(weights, values.shape[0])
    if normalized is None:
        return _require_finite_estimate(float(np.std(values)), "weighted_std")
    mean = float(np.sum(values * normalized))
    deviations = values - mean
    return _require_finite_estimate(
        float(np.sqrt(max(0.0, np.sum(normalized * deviations * deviations)))),
        "weighted_std",
    )


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
    _require_finite_values(values)
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
    return _require_finite_estimate(
        contribution / tail_fraction, "weighted_lower_tail_mean",
    )


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
    """Gepoolte Innerhalb-Perioden-Streuung der Einperiodenrenditen.

    MIN-VOLATILITY-WITHIN-PERIOD-001 (CIO-Entscheid 2026-10-25):
    deterministische, periodenabhaengige Erwartungswerte (Zinsstruktur,
    Mean-Pfad) sind KEINE Volatilitaet. Gemessen wird nur die stochastische
    Streuung jeder Periode um IHREN eigenen Erwartungswert:

        m_t   = sum_i w_i r_it                      (Periodenmittel)
        s_t^2 = sum_i w_i (r_it - m_t)^2 / (1 - sum_i w_i^2)
        sigma = sqrt( (1/T) * sum_t s_t^2 )

    mit normierten Pfadgewichten ``w`` (ohne IS: ``w_i = 1/n``, dann ist
    ``s_t^2`` die Stichprobenvarianz mit ``ddof = 1``). Das ist der klassische
    gepoolte Within-Group-Schaetzer; jede Periode des Horizonts zaehlt gleich.

    Warum nicht mehr global gepoolt: Bis Engine v15 wurden alle Pfad-Jahr-
    Beobachtungen um EINEN globalen Mittelwert zentriert. Das misst

        Var(R) = E_t[Var(R_t | t)] + Var_t(E[R_t | t])

    und der zweite Summand ist die deterministische Streuung der
    Periodenmittel, kein Marktrisiko. Audit-Gegenbeispiel 2026-10-14: gleiche
    Innerhalb-Perioden-Schocks (-10/0/+10 %), einmal stationaer, einmal mit
    der Kurve -20/0/+20 %: 0.0816 gegen 0.1826. Ein Wuerfel mit rein
    deterministischen, periodenweise verschiedenen Renditen hat jetzt Vola 0.

    Konservative Konventionen, bewusst gewaehlt:

    * Freiheitsgrad-Korrektur (Bessel ohne IS; unter IS die Standard-
      korrektur ``1 - sum w^2`` fuer normierte Zuverlaessigkeitsgewichte):
      ohne IS erwartungstreu fuer die Varianz; der Populationsschaetzer
      (``ddof = 0``) wuerde die Streuung systematisch unterschaetzen.
    * Zeitaggregation als quadratisches Mittel der Periodenvolas: bei
      zeitvariabler Vola ist das mindestens das arithmetische Mittel der
      Periodenvolas, unabhaengig von der Horizontlaenge.
    * Die IS-Gewichte gelten pro PFAD und werden in JEDER Periode separat
      angewandt (Mittel und Streuung je Periode unter der Zielverteilung);
      ein zeituebergreifender gewichteter Mittelwert wird nie gebildet.
    * Nicht schaetzbar (weniger als zwei Pfade bzw. alle Masse auf einem
      Pfad): fail-closed mit ``objective_dispersion_not_estimable`` statt
      eines stillen Werts 0.

    Unveraendert gilt: Einperioden-Skala (nicht annualisierte Endrendite, die
    mean-abhaengig ist, siehe Modul-Docstring) -- fuer stationaere Wuerfel
    trifft der Wert die vorgegebene Einperioden-Sigma.

    Die Kennung dieses Schaetzers steht als ``risk_measure_estimator`` im
    Nachweis-Block (``objective_basis``) und damit in Modellbasis und
    ``allocation_context_hash``; zusaetzlich traegt jeder Lauf die
    Engine-Version.
    """
    one_period_returns = np.asarray(factors, dtype=np.float64) - 1.0
    _require_finite_values(one_period_returns)
    n_paths, n_periods = one_period_returns.shape
    if weights is None:
        normalized = np.full(n_paths, 1.0 / n_paths, dtype=np.float64)
    else:
        path_weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        if path_weights.shape[0] != n_paths:
            # Eigene Meldung mit der PFADzahl (nicht pfade*jahre).
            raise ValueError(
                f"weights.shape[0]={path_weights.shape[0]} != n_paths={n_paths}"
            )
        normalized = _normalized_weights(path_weights, n_paths)
    correction = 1.0 - float(np.sum(normalized * normalized))
    if n_paths < 2 or correction <= 0.0:
        raise ObjectiveDomainError(
            "objective_dispersion_not_estimable",
            "Die Innerhalb-Perioden-Streuung braucht mindestens zwei Pfade "
            f"mit positiver Masse (Pfade: {n_paths}, effektive Masse auf "
            "einem Pfad).",
        )
    # Vorab je Periode um einen Referenzpfad verschieben: mathematisch ohne
    # Wirkung (die Varianz ist verschiebungsinvariant), numerisch aber so,
    # dass identische Pfade EXAKT 0 liefern und eine deterministische
    # Periodenkurve schon vor der Mittelung bitgenau herausfaellt.
    anchored = one_period_returns - one_period_returns[0:1, :]
    period_means = normalized @ anchored  # (perioden,)
    deviations = anchored - period_means[None, :]
    period_variances = (normalized @ (deviations * deviations)) / correction
    pooled_variance = float(np.sum(period_variances)) / n_periods
    return _require_finite_estimate(
        float(np.sqrt(max(0.0, pooled_variance))), "within_period_dispersion",
    )


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
        # OPTIMIZER-OBJECTIVE-DOMAIN-001: auch der durchgereichte L(w)-Wert
        # ist ein Ausgang dieser Funktion und wird geprueft.
        return require_finite_objective(
            goal_shortfall_value, where=f"primary_objective[{resolved}]",
        )

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

    # OPTIMIZER-OBJECTIVE-DOMAIN-001: endliche, strikt positive Faktoren
    # koennen trotzdem ueberlaufen (``cumprod`` -> inf -> inf/inf = nan im
    # Drawdown; Quadrat im Std; Summe im Mittel). Jeder Ausgang laeuft darum
    # ueber ``require_finite_objective`` -- reine Pruefung, gleicher Wert.
    where = f"primary_objective[{resolved}]"
    if resolved == OBJECTIVE_MAX_DRAWDOWN:
        return require_finite_objective(
            weighted_mean(_annual_grid_max_drawdowns(factors), weights),
            where=where,
        )
    if resolved == OBJECTIVE_MIN_VOLATILITY:
        # OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001: Einperioden-Streuung, siehe
        # _one_period_return_dispersion. Bewusst VOR der Annualisierung, damit
        # diese Variante sie nicht mehr berechnet -- sie braucht sie nicht,
        # und in jeder SLSQP-Iteration waere das verworfene Arbeit.
        return require_finite_objective(
            _one_period_return_dispersion(factors, weights), where=where,
        )

    annualized = _annualized_returns_from_factors(factors)
    if resolved == OBJECTIVE_CVAR_RETURN:
        # Expected Shortfall als positive Verlustzahl: der Tail-Mittelwert
        # wird negiert, damit "kleiner ist besser" gilt. Liegt auch der Tail
        # im Plus, wird der Term negativ und belohnt das -- bewusst nicht bei
        # 0 abgeschnitten, sonst waere die Zielfunktion dort flach und der
        # Solver bekaeme kein Gefaelle mehr.
        return require_finite_objective(
            -weighted_lower_tail_mean(annualized, weights), where=where,
        )
    if resolved == OBJECTIVE_MAX_RETURN:
        return require_finite_objective(
            -weighted_mean(annualized, weights), where=where,
        )

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
