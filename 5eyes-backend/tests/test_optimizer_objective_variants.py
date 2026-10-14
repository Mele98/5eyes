"""OPTIMIZER-OBJECTIVE-VARIANTS-001 -- austauschbarer Primaerterm.

Der Solver optimierte genau eine Zielfunktion (gewichteter Shortfall-MSE
gegen die Ziele). Fuer einen Teil der Mandate ist das nicht die Frage, die der
Kunde stellt: "ich will nicht sehen, dass mein Depot mehr als X verliert" ist
eine Drawdown-Frage, "so wenig Schwankung wie moeglich" eine
Volatilitaetsfrage.

Diese Suite deckt die Eigenschaften ab, auf denen die Varianten stehen:

1. **Fail-closed** -- ein Tippfehler im Modus ist ein Fehler, nie stillschweigend
   der Default. Welche Mathematik einen Lauf erzeugt hat, darf nicht von "unset"
   nicht unterscheidbar sein.
2. **Der Default ist unveraendert** -- ``goal_shortfall`` rechnet bit-identisch
   wie vor der Variantenfaehigkeit.
3. **Die Goal-Chance-Penalty bleibt in JEDER Variante aktiv** -- das ist die
   Eignungs-Untergrenze. Ohne sie bekaeme ein Berater mit "minimiere CVaR" eine
   Allokation, die die Ziele des Mandats aufgibt.
4. **Jede Variante zeigt in die richtige Richtung** und ist dimensionslos in
   vergleichbarer Groessenordnung -- waere sie in Rappen skaliert, wuerde die
   Chance-Penalty sie erdruecken und die Variante waere nominell vorhanden,
   praktisch wirkungslos.
5. **Kein Risikomass laeuft auf den Vermoegenspfaden** -- die enthalten Ein- und
   Auszahlungen; ein Verzehr-Mandat wuerde seinen geplanten Pensionsverzehr als
   Marktrisiko ausgewiesen bekommen (derselbe Fehler, den #AA-10/#AA-4/#AA-5
   fuer die berichteten Kennzahlen behoben haben).
6. **Importance-Sampling-Gewichte werden beruecksichtigt** -- sonst schaetzt
   jeder Primaerterm sein Mass als uniformes Sample-Mean ueber IS-geshiftete
   Pfade und ist verzerrt (die unter OPT-1 dokumentierte Falle).
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np
import pytest

from config import OBJECTIVE_MODES, validate_objective_mode
from services.optimizer.objective_variants import (
    CVAR_TAIL_FRACTION,
    DEFAULT_OBJECTIVE_MODE,
    OBJECTIVE_CVAR_RETURN,
    OBJECTIVE_DESCRIPTIONS,
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MAX_RETURN,
    OBJECTIVE_MIN_VOLATILITY,
    ObjectiveDomainError,
    ObjectiveModeError,
    objective_basis,
    primary_objective,
    refined_drawdown_check_for_winner,
    resolve_objective_mode,
    weighted_lower_tail_mean,
    weighted_mean,
    weighted_std,
)


# ── Hilfsmittel ──────────────────────────────────────────────────────────────


def _factors(annual_returns_per_path: list[list[float]]) -> np.ndarray:
    """Wachstumsfaktoren aus Jahresrenditen, Form (pfade, jahre)."""
    return np.asarray(
        [[1.0 + r for r in path] for path in annual_returns_per_path],
        dtype=np.float64,
    )


# Zwei Portfolios mit GLEICHER annualisierter Endrendite, aber voellig
# verschiedenem Verlauf: das erste schwankt stark und faellt zwischenzeitlich
# tief, das zweite laeuft glatt. Jede Risikomass-Variante muss das zweite
# vorziehen, die Rendite-Variante muss indifferent sein.
_RUHIG = _factors([[0.04, 0.04, 0.04, 0.04]] * 4)
_UNRUHIG = _factors(
    [
        [0.35, -0.22, 0.30, -0.17],
        [0.30, -0.18, 0.28, -0.15],
        [0.38, -0.25, 0.33, -0.20],
        [0.33, -0.20, 0.31, -0.18],
    ]
)


# ── 1. Fail-closed-Modusauflösung ────────────────────────────────────────────


def test_unset_mode_resolves_to_documented_default() -> None:
    assert validate_objective_mode(None) == DEFAULT_OBJECTIVE_MODE
    assert DEFAULT_OBJECTIVE_MODE == OBJECTIVE_GOAL_SHORTFALL


@pytest.mark.parametrize("raw", ["  MAX_DRAWDOWN ", "Cvar_Return", "MIN_VOLATILITY"])
def test_mode_is_normalized(raw: str) -> None:
    assert validate_objective_mode(raw) == raw.strip().lower()


@pytest.mark.parametrize(
    "raw", ["", "   ", "max_drowdown", "shortfall", "cvar", "goal-shortfall", "0"]
)
def test_unknown_mode_raises_instead_of_falling_back(raw: str) -> None:
    """Ein Tippfehler darf nicht als Default durchlaufen.

    Das ist die Lektion aus CERT-OPTIMIZER-OBJECTIVE-001: ein unerkannter Wert
    wurde dort stillschweigend normalisiert und war von "nicht gesetzt" nicht
    unterscheidbar -- ohne Fehler und ohne Spur in der Evidenz.
    """
    with pytest.raises(ValueError, match="OPTIMIZER_OBJECTIVE"):
        validate_objective_mode(raw)


def test_resolve_reads_the_environment_live(monkeypatch) -> None:
    """Live-Read, keine beim Prozessstart eingefrorene Konstante.

    Gleiche Begruendung wie bei resolve_goal_weighting_mode(): eine
    Konfigurationsaenderung muss beim naechsten Optimierungslauf wirken, ohne
    Neustart.
    """
    monkeypatch.delenv("OPTIMIZER_OBJECTIVE", raising=False)
    assert resolve_objective_mode() == OBJECTIVE_GOAL_SHORTFALL
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "max_drawdown")
    assert resolve_objective_mode() == OBJECTIVE_MAX_DRAWDOWN
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "quatsch")
    with pytest.raises(ValueError):
        resolve_objective_mode()


def test_every_mode_has_a_description() -> None:
    """Der Nachweis soll sagen, wonach optimiert wurde, nicht nur einen Schluessel."""
    assert set(OBJECTIVE_DESCRIPTIONS) == set(OBJECTIVE_MODES)
    for mode, text in OBJECTIVE_DESCRIPTIONS.items():
        assert len(text) > 30, mode


# ── 2. Default unveraendert ──────────────────────────────────────────────────


def test_default_mode_passes_through_the_goal_shortfall_unchanged() -> None:
    """Der Default-Primaerterm IST L(w), nicht eine zweite Implementierung.

    Waere hier eine eigene Berechnung, haette sie von shortfall_objective
    abdriften koennen -- dieselbe Divergenzklasse wie bei den
    MC-Paritaetsbefunden.
    """
    for value in (0.0, 1e-9, 0.25, 3.75):
        assert primary_objective(
            OBJECTIVE_GOAL_SHORTFALL,
            goal_shortfall_value=value,
            portfolio_return_factors=None,
        ) == value


def test_default_mode_needs_no_return_factors() -> None:
    """Der Default darf nicht plötzlich ein neues Pflichtargument verlangen."""
    assert primary_objective(
        OBJECTIVE_GOAL_SHORTFALL,
        goal_shortfall_value=0.5,
        portfolio_return_factors=None,
    ) == 0.5


# ── 3. Varianten verlangen cashflow-neutrale Faktoren (kein Rueckfall) ───────


@pytest.mark.parametrize(
    "mode",
    [
        OBJECTIVE_CVAR_RETURN,
        OBJECTIVE_MAX_DRAWDOWN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_RETURN,
    ],
)
def test_variant_without_return_factors_raises(mode: str) -> None:
    """Ohne die cashflow-neutralen Faktoren gibt es keinen Rueckfall.

    Ein Rueckfall auf die Vermoegenspfade wuerde geplante Entnahmen als
    Marktrisiko bewerten und defensive Verzehr-Mandate systematisch als riskant
    einstufen.
    """
    with pytest.raises(ObjectiveModeError, match="cashflow-neutralen"):
        primary_objective(
            mode, goal_shortfall_value=0.0, portfolio_return_factors=None
        )


@pytest.mark.parametrize("bad", [np.zeros((0, 4)), np.zeros((4, 0)), np.zeros(4)])
def test_variant_with_degenerate_factor_shape_raises(bad: np.ndarray) -> None:
    with pytest.raises(ObjectiveModeError):
        primary_objective(
            OBJECTIVE_MIN_VOLATILITY,
            goal_shortfall_value=0.0,
            portfolio_return_factors=bad,
        )


# ── 4. Richtung und Groessenordnung jeder Variante ──────────────────────────


@pytest.mark.parametrize(
    "mode",
    [OBJECTIVE_CVAR_RETURN, OBJECTIVE_MAX_DRAWDOWN, OBJECTIVE_MIN_VOLATILITY],
)
def test_risk_variants_prefer_the_calm_portfolio(mode: str) -> None:
    """Jedes Risikomass muss das ruhige Portfolio vorziehen (kleiner = besser)."""
    calm = primary_objective(
        mode, goal_shortfall_value=0.0, portfolio_return_factors=_RUHIG
    )
    rough = primary_objective(
        mode, goal_shortfall_value=0.0, portfolio_return_factors=_UNRUHIG
    )
    assert calm < rough, f"{mode}: ruhig={calm:.4f} nicht besser als unruhig={rough:.4f}"


def test_max_return_prefers_the_higher_return_regardless_of_path_shape() -> None:
    """Die Rendite-Variante bewertet die Rendite, nicht den Verlauf."""
    low = primary_objective(
        OBJECTIVE_MAX_RETURN,
        goal_shortfall_value=0.0,
        portfolio_return_factors=_factors([[0.02] * 4] * 3),
    )
    high = primary_objective(
        OBJECTIVE_MAX_RETURN,
        goal_shortfall_value=0.0,
        portfolio_return_factors=_factors([[0.06] * 4] * 3),
    )
    assert high < low
    # Vorzeichen: Maximierung wird als Minimierung des Negativen abgebildet.
    assert high < 0.0


@pytest.mark.parametrize(
    "mode",
    [
        OBJECTIVE_CVAR_RETURN,
        OBJECTIVE_MAX_DRAWDOWN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_RETURN,
    ],
)
def test_variants_are_dimensionless_and_commensurate(mode: str) -> None:
    """Jeder Primaerterm liegt im Band, in dem auch L(w) liegt.

    L(w) normalisiert auf das Anfangsvermoegen und liegt typisch in [0, 1].
    Waere eine Variante in Rappen oder Rappen^2 skaliert, wuerde die
    Chance-Penalty (lambda = 1e6) sie entweder voellig erdruecken oder voellig
    verschwinden -- die Variante waere nominell vorhanden und wirkungslos.
    """
    for factors in (_RUHIG, _UNRUHIG):
        value = primary_objective(
            mode, goal_shortfall_value=0.0, portfolio_return_factors=factors
        )
        assert -1.0 < value < 1.0, f"{mode} liefert {value}, ausserhalb des Bandes"


def test_max_drawdown_is_measured_peak_to_trough_not_terminal() -> None:
    """Ein Pfad, der tief faellt und sich erholt, hat trotzdem Drawdown.

    Sonst waere die Kennzahl nur eine Endwert-Betrachtung.
    """
    recovers = _factors([[-0.30, 0.50]] * 3)  # Endwert > Start, aber -30 % unterwegs
    value = primary_objective(
        OBJECTIVE_MAX_DRAWDOWN,
        goal_shortfall_value=0.0,
        portfolio_return_factors=recovers,
    )
    assert value == pytest.approx(0.30, abs=1e-9)


def test_max_drawdown_uses_a_cashflow_neutral_index_starting_at_one() -> None:
    """Der Index startet bei 1, der Startpunkt zaehlt als erster Peak.

    Faengt die Reihe erst nach dem ersten Jahr an, wuerde ein Verlust im
    ersten Jahr nicht als Drawdown gezaehlt.
    """
    first_year_loss = _factors([[-0.20, 0.0, 0.0]] * 3)
    value = primary_objective(
        OBJECTIVE_MAX_DRAWDOWN,
        goal_shortfall_value=0.0,
        portfolio_return_factors=first_year_loss,
    )
    assert value == pytest.approx(0.20, abs=1e-9)


# ── 5. Gewichtete Schaetzer (Importance Sampling) ───────────────────────────


def test_weighted_lower_tail_mean_matches_a_hand_computed_case() -> None:
    """Expected Shortfall gegen eine von Hand nachgerechnete Verteilung.

    10 gleich gewichtete Pfade, Tail-Anteil 0.2 -> die zwei schlechtesten
    Werte, also Mittel von -0.50 und -0.40.
    """
    values = np.asarray(
        [-0.50, -0.40, -0.10, 0.0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    )
    result = weighted_lower_tail_mean(values, None, tail_fraction=0.2)
    assert result == pytest.approx((-0.50 + -0.40) / 2.0, abs=1e-12)


def test_weighted_lower_tail_mean_interpolates_the_boundary_path() -> None:
    """Der Grenzpfad geht anteilig ein, nicht ganz oder gar nicht.

    Ohne die anteilige Beruecksichtigung waere die Kennzahl nicht stetig in den
    Gewichten und der Solver saehe kuenstliche Spruenge.
    """
    values = np.asarray([-1.0, 0.0, 0.0, 0.0])  # je 0.25 Masse
    # Tail 0.25 -> genau der schlechteste Pfad
    assert weighted_lower_tail_mean(values, None, tail_fraction=0.25) == pytest.approx(
        -1.0, abs=1e-12
    )
    # Tail 0.5 -> schlechtester Pfad (0.25) + halbe Masse des zweiten
    assert weighted_lower_tail_mean(values, None, tail_fraction=0.5) == pytest.approx(
        -0.5, abs=1e-12
    )
    # Tail 0.125 -> nur ein Teil des schlechtesten Pfades, Mittel bleibt -1.0
    assert weighted_lower_tail_mean(values, None, tail_fraction=0.125) == pytest.approx(
        -1.0, abs=1e-12
    )


def test_weighted_estimators_shift_with_the_likelihood_ratios() -> None:
    """Die Gewichte muessen wirken, sonst ist die Variante unter IS verzerrt."""
    values = np.asarray([-0.4, -0.1, 0.1, 0.4])
    heavy_on_bad = np.asarray([10.0, 1.0, 1.0, 1.0])
    assert weighted_mean(values, heavy_on_bad) < weighted_mean(values, None)
    assert weighted_std(values, heavy_on_bad) != pytest.approx(
        weighted_std(values, None)
    )
    assert weighted_lower_tail_mean(
        values, heavy_on_bad, tail_fraction=0.5
    ) != pytest.approx(weighted_lower_tail_mean(values, None, tail_fraction=0.5))


def test_weighted_mean_equals_plain_mean_for_uniform_weights() -> None:
    values = np.asarray([-0.4, -0.1, 0.1, 0.4])
    uniform = np.full(4, 7.0)  # beliebige Konstante
    assert weighted_mean(values, uniform) == pytest.approx(weighted_mean(values, None))
    assert weighted_std(values, uniform) == pytest.approx(weighted_std(values, None))


@pytest.mark.parametrize(
    "mode",
    [
        OBJECTIVE_CVAR_RETURN,
        OBJECTIVE_MAX_DRAWDOWN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_RETURN,
    ],
)
def test_variants_honour_importance_sampling_weights(mode: str) -> None:
    """Jede Variante reagiert auf die Likelihood-Ratios.

    Gewichtet wird der schlechteste Pfad stark hochgezogen; jedes Mass muss
    sich dadurch veraendern. Reagiert eines nicht, ignoriert es die Gewichte
    und ist unter Importance Sampling verzerrt.
    """
    # Genug Pfade, damit der 5-%-Tail des CVaR ueber MEHRERE Pfade laeuft --
    # bei wenigen Pfaden entartet er zum Minimum und reagiert dann korrekt
    # nicht auf die Gewichte (siehe
    # test_cvar_degenerates_to_the_minimum_with_few_paths).
    rng = np.random.default_rng(31)
    mixed = 1.0 + rng.normal(0.05, 0.12, size=(80, 6))
    # Gewicht auf die erste Haelfte der Pfade -- unabhaengig davon, wo diese
    # in der Rangfolge liegen, veraendert das die Zielverteilung.
    weights = np.concatenate([np.full(40, 9.0), np.full(40, 1.0)])

    uniform_value = primary_objective(
        mode, goal_shortfall_value=0.0, portfolio_return_factors=mixed
    )
    weighted_value = primary_objective(
        mode,
        goal_shortfall_value=0.0,
        portfolio_return_factors=mixed,
        weights=weights,
    )
    assert weighted_value != pytest.approx(uniform_value), (
        f"{mode} ignoriert die Importance-Sampling-Gewichte"
    )


def test_cvar_degenerates_to_the_minimum_with_few_paths() -> None:
    """Bei wenigen Pfaden IST der 5-%-CVaR der schlechteste Pfad.

    Mit 4 Pfaden traegt jeder 25 % Masse, der 5-%-Tail liegt also vollstaendig
    innerhalb des schlechtesten. Das ist korrektes Verhalten und keine
    Schwaeche des Schaetzers -- aber es heisst, dass die CVaR-Variante bei
    kleinen Pfadzahlen zu einer Minimax-Regel wird und dann auch nicht mehr
    auf Importance-Sampling-Gewichte reagieren KANN. Festgehalten, damit
    niemand das spaeter fuer einen Bug haelt.
    """
    few = _factors(
        [
            [-0.25, -0.15, 0.05, 0.02],
            [0.05, 0.04, 0.06, 0.05],
            [0.08, 0.07, 0.09, 0.08],
            [0.12, 0.10, 0.11, 0.12],
        ]
    )
    plain = primary_objective(
        OBJECTIVE_CVAR_RETURN, goal_shortfall_value=0.0, portfolio_return_factors=few
    )
    skewed = primary_objective(
        OBJECTIVE_CVAR_RETURN,
        goal_shortfall_value=0.0,
        portfolio_return_factors=few,
        weights=np.asarray([20.0, 1.0, 1.0, 1.0]),
    )
    assert plain == pytest.approx(skewed)
    # Und der Wert ist der negierte schlechteste Pfad.
    worst = float(
        np.min(np.exp(np.mean(np.log(np.maximum(few, 1e-12)), axis=1)) - 1.0)
    )
    assert plain == pytest.approx(-worst)


def test_weighted_estimators_reject_degenerate_weights() -> None:
    """Nullsumme und falsche Laenge werden abgelehnt.

    OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: der Nullsummen-Fall matchte
    vorher auf den Freitext "Sum-of-weights". Ein Fehlertext ist kein
    Vertrag -- jede Umformulierung haette den Test gebrochen, ohne dass sich
    das Verhalten aendert. Geprueft wird jetzt der STABILE Reason-Code.

    Die Laengenpruefung bleibt ein nackter ValueError: sie ist ein
    Aufrufvertrag (Array falscher Form), kein Domaenenbefund ueber die
    WERTE, und bekommt deshalb bewusst keinen Reason-Code.

    Die weiteren Domaenenfaelle -- negative, nan- und inf-Gewichte, die
    vorher ALLE durchliefen -- stehen in
    tests/test_objective_domain_fail_closed.py.
    """
    values = np.asarray([0.1, 0.2, 0.3])
    with pytest.raises(ObjectiveDomainError) as exc:
        weighted_mean(values, np.zeros(3))
    assert exc.value.reason_code == "objective_weights_no_positive_mass"
    with pytest.raises(ValueError, match="!= n_paths"):
        weighted_mean(values, np.ones(5))


# ── 6. Nachweis ─────────────────────────────────────────────────────────────


def test_objective_basis_names_the_mode_and_its_basis(monkeypatch) -> None:
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "max_drawdown")
    basis = objective_basis()
    assert basis["mode"] == OBJECTIVE_MAX_DRAWDOWN
    assert basis["goal_chance_constraint_active"] is True
    assert basis["risk_measure_basis"] == "cashflow_neutral_portfolio_return_factors"
    assert set(basis["available_modes"]) == set(OBJECTIVE_MODES)


def test_objective_basis_for_the_default_names_the_goal_basis() -> None:
    basis = objective_basis(OBJECTIVE_GOAL_SHORTFALL)
    assert basis["risk_measure_basis"] == "wealth_paths_vs_goal_liabilities"
    assert basis["goal_chance_constraint_active"] is True


def test_objective_basis_rejects_an_invalid_explicit_mode() -> None:
    with pytest.raises(ValueError):
        objective_basis("nonsense")


# ── 7. Proxy-Verzerrung des Max-Drawdown-Ziels sichtbar machen ──────────────


def test_refined_check_exposes_the_annual_grid_understatement() -> None:
    """Der Gewinner wird auf dem genauen Zeitgitter nachgerechnet.

    ``max_drawdown`` optimiert auf dem Jahresgitter, weil die
    Bruecken-Verfeinerung in jeder Solver-Iteration unbezahlbar waere. Das
    Jahresgitter unterschaetzt aber volatilitaetsabhaengig und bevorzugt damit
    riskantere Allokationen -- genau der Effekt, den DRAWDOWN-TIME-GRID-001
    fuer die berichtete Kennzahl behoben hat. Diese Pruefung macht die
    Verzerrung fuer die gewaehlte Allokation sichtbar, statt sie zu
    verschweigen.
    """
    rng = np.random.default_rng(2026)
    # Breite Streuung ueber die Pfade, damit sigma schaetzbar ist.
    factors = 1.0 + rng.normal(0.05, 0.14, size=(400, 15))
    report = refined_drawdown_check_for_winner(factors, seed=4711)

    assert report["refined_mean_drawdown"] > report["annual_grid_mean_drawdown"], (
        "Das genaue Gitter muss mindestens so tief messen wie das Jahresgitter"
    )
    assert report["understatement"] > 0.0
    assert report["sub_steps_per_year"] > 1
    assert report["model_version"]


def test_refined_check_is_reproducible() -> None:
    rng = np.random.default_rng(7)
    factors = 1.0 + rng.normal(0.04, 0.10, size=(200, 10))
    first = refined_drawdown_check_for_winner(factors, seed=99)
    second = refined_drawdown_check_for_winner(factors, seed=99)
    assert first == second


def test_cvar_tail_fraction_is_a_tail_not_the_whole_distribution() -> None:
    """Eine Plausibilitaetsschranke auf die Konstante selbst."""
    assert 0.0 < CVAR_TAIL_FRACTION <= 0.10


# ── 8. Semantik von min_volatility ──────────────────────────────────────────


def test_min_volatility_measures_the_one_period_volatility() -> None:
    """``min_volatility`` MISST die Einperioden-Volatilitaet, nicht nur ihre Ordnung.

    OPTIMIZER-MIN-VOLATILITY-SEMANTICS-001: dieser Test verlangte vorher
    ``value < one_period_vol`` fuer jeden Fall -- also ausdruecklich den
    ``1/sqrt(T)``-Abfall des ALTEN Masses (Streuung der annualisierten
    Endrendite). Damit hielt er die defekte Semantik als erwarteten Zustand
    fest und waere durch den Fix notwendig falsch geworden.

    Jetzt die staerkere Aussage: die Kennzahl ist die Einperioden-Vola, also
    muss sie den vorgegebenen Wert TREFFEN, nicht nur monoton in ihm sein.
    Monotonie allein waere auch von ``sigma/sqrt(T)`` erfuellt und wuerde den
    Befund nicht ausschliessen.
    """
    measured = []
    for one_period_vol in (0.03, 0.06, 0.10, 0.16, 0.24):
        rng = np.random.default_rng(606)
        factors = 1.0 + rng.normal(0.05, one_period_vol, size=(4000, 12))
        measured.append(
            (
                one_period_vol,
                primary_objective(
                    OBJECTIVE_MIN_VOLATILITY,
                    goal_shortfall_value=0.0,
                    portfolio_return_factors=factors,
                ),
            )
        )

    values = [value for _vol, value in measured]
    assert values == sorted(values), (
        "Das Mass ist nicht monoton in der Einperioden-Volatilitaet: "
        f"{measured}"
    )
    for one_period_vol, value in measured:
        # 4000 Pfade x 12 Jahre = 48'000 Beobachtungen; 2 % relative Toleranz
        # ist dafuer reichlich und faengt trotzdem jede Skalenverwechslung
        # (der alte Wert lag um Faktor ~sqrt(12) daneben).
        assert abs(value - one_period_vol) < 0.02 * one_period_vol, (
            f"Einperioden-Vola {one_period_vol} wurde als {value} gemessen -- "
            "das ist nicht dieselbe Groesse."
        )


def test_min_volatility_does_not_rank_by_expected_return() -> None:
    """Gegenbeispiel: hoeherer Erwartungswert darf nicht als mehr Risiko gelten.

    Das ist der Reproducer des Befundes. Zwei Portfolios mit LOGNORMALEN
    Jahresfaktoren wie in der Scenario-Engine, gleicher Horizont, konstante
    Gewichte -- also genau die iid-Annahme, unter der der Modul-Docstring
    Ranggleichheit mit ``a' Sigma a`` behauptete:

        A: arith. Mean +5.5 %, Ziel-Sigma 40.00 %
        B: arith. Mean -5.0 %, Ziel-Sigma 40.05 %

    A schwankt weniger. Mit dem alten Mass (Streuung der annualisierten
    Endrendite) gewann B -- gemessen 0.103446 gegen 0.105348 -- weil
    ``sd(R_ann) = exp(l + s^2/(2T)) * sqrt(exp(s^2/T) - 1)`` mit dem Log-Mean
    waechst. B hatte sogar die HOEHERE Log-Varianz (0.1636 vs. 0.1342) und
    wurde trotzdem bevorzugt.

    Der vorhandene Monotonietest konnte das konstruktiv nicht sehen: er haelt
    den Mean fest und zieht normale statt lognormale Faktoren.
    """
    T = 12
    n_paths = 60_000

    def lognormal_factors(simple_mean: float, simple_sigma: float, rng) -> np.ndarray:
        """Faktoren mit vorgegebenem ARITHMETISCHEM Mean und Sigma.

        Momentenanpassung, damit "Ziel-Sigma" wirklich die Einperioden-Vola
        ist und nicht eine Log-Groesse -- sonst wuerde der Test seine eigene
        Voraussetzung verfehlen.
        """
        m = 1.0 + simple_mean
        log_var = np.log(1.0 + (simple_sigma * simple_sigma) / (m * m))
        log_mean = np.log(m) - 0.5 * log_var
        return rng.lognormal(log_mean, np.sqrt(log_var), size=(n_paths, T))

    rng = np.random.default_rng(20261011)
    factors_low_vol_high_mean = lognormal_factors(0.055, 0.4000, rng)
    factors_high_vol_low_mean = lognormal_factors(-0.050, 0.4005, rng)

    sampled_vol_a = float(np.std(factors_low_vol_high_mean - 1.0))
    sampled_vol_b = float(np.std(factors_high_vol_low_mean - 1.0))
    # Voraussetzung des Gegenbeispiels: A schwankt wirklich weniger. Ohne
    # diese Zeile koennte der Test aus dem falschen Grund gruen sein.
    assert sampled_vol_a < sampled_vol_b, (sampled_vol_a, sampled_vol_b)

    objective_a = primary_objective(
        OBJECTIVE_MIN_VOLATILITY,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors_low_vol_high_mean,
    )
    objective_b = primary_objective(
        OBJECTIVE_MIN_VOLATILITY,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors_high_vol_low_mean,
    )

    assert objective_a < objective_b, (
        "min_volatility bevorzugt das Portfolio mit der HOEHEREN "
        f"Einperioden-Volatilitaet (A={objective_a}, B={objective_b}; "
        f"Vola A={sampled_vol_a}, B={sampled_vol_b}) -- es ordnet nach "
        "Erwartungswert statt nach Risiko."
    )


def test_min_volatility_is_indifferent_to_the_mean_at_equal_risk() -> None:
    """Gleiches Risiko, verschiedener Mean -> praktisch gleiche Kennzahl.

    Die Kehrseite des Gegenbeispiels: ein Risikomass darf den Erwartungswert
    nicht sehen.

    WICHTIG, nachgemessen: dieser Test DISKRIMINIERT NICHT gegen das alte
    Mass -- mit der Streuung der annualisierten Endrendite bleibt er gruen.
    Bei gleichem ARITHMETISCHEM Sigma heben sich dort zwei Effekte fast auf
    (hoeherer Log-Mean, dafuer kleinere Log-Varianz), die Spanne lag bei
    ~0.0005. Der Defekt zeigt sich erst, wenn sich Mean UND Sigma
    unterscheiden -- das pinnt
    ``test_min_volatility_does_not_rank_by_expected_return``.

    Dieser Test bleibt trotzdem: er haelt den Vertrag fest, dass die
    Kennzahl mean-frei ist, und wuerde einen kuenftigen "Fix" fangen, der
    Rendite in das Risikomass mischt. Er wird aber ausdruecklich NICHT als
    Beleg fuer die Schliessung des Befundes gezaehlt.
    """
    T = 12
    n_paths = 60_000
    sigma = 0.25

    def lognormal_factors(simple_mean: float, rng) -> np.ndarray:
        m = 1.0 + simple_mean
        log_var = np.log(1.0 + (sigma * sigma) / (m * m))
        log_mean = np.log(m) - 0.5 * log_var
        return rng.lognormal(log_mean, np.sqrt(log_var), size=(n_paths, T))

    rng = np.random.default_rng(4711)
    values = [
        primary_objective(
            OBJECTIVE_MIN_VOLATILITY,
            goal_shortfall_value=0.0,
            portfolio_return_factors=lognormal_factors(mean, rng),
        )
        for mean in (-0.02, 0.03, 0.08)
    ]

    spread = max(values) - min(values)
    assert spread < 0.01 * sigma, (
        "Die Kennzahl unterscheidet bei identischem Risiko nach dem "
        f"Erwartungswert (Werte {values}, Spanne {spread}) -- sie ordnet "
        "damit teilweise nach Rendite."
    )


def test_min_volatility_weights_apply_per_path() -> None:
    """Likelihood-Ratios gelten pro Pfad, auch nach dem Flachlegen.

    Die Kennzahl poolt jetzt ueber Pfade UND Jahre; die IS-Gewichte haben
    aber nur eine Laenge pro Pfad. Werden sie falsch ausgerollt, gewichtet
    das Mass stillschweigend die falschen Beobachtungen -- ein Fehler, der
    keine Exception wirft und die Zahl nur leise verschiebt.
    """
    rng = np.random.default_rng(99)
    factors = 1.0 + rng.normal(0.04, 0.15, size=(500, 8))

    unweighted = primary_objective(
        OBJECTIVE_MIN_VOLATILITY,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors,
    )
    uniform_weighted = primary_objective(
        OBJECTIVE_MIN_VOLATILITY,
        goal_shortfall_value=0.0,
        portfolio_return_factors=factors,
        weights=np.ones(500, dtype=np.float64),
    )
    assert abs(unweighted - uniform_weighted) < 1e-9, (
        "Uniforme Gewichte muessen dasselbe Ergebnis liefern wie keine "
        f"Gewichte: {unweighted} vs. {uniform_weighted}"
    )

    # Falsche Laenge -> Fehler, kein stilles Weiterrechnen. Die Meldung muss
    # die PFADZAHL nennen, nicht die flachgelegte Laenge (pfade*jahre), sonst
    # schickt sie den Leser in die falsche Richtung.
    with pytest.raises(ValueError, match="n_paths=500"):
        primary_objective(
            OBJECTIVE_MIN_VOLATILITY,
            goal_shortfall_value=0.0,
            portfolio_return_factors=factors,
            weights=np.ones(8, dtype=np.float64),
        )
