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
        "Minimiert die Streuung der annualisierten Portfoliorendite ueber "
        "die Szenarien."
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
    if weights is None:
        return None
    array = np.asarray(weights, dtype=np.float64).reshape(-1)
    if array.shape[0] != n_paths:
        raise ValueError(f"weights.shape[0]={array.shape[0]} != n_paths={n_paths}")
    total = float(np.sum(array))
    if total <= 0.0:
        raise ValueError("Sum-of-weights must be > 0")
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
    """
    safe = np.maximum(np.asarray(factors, dtype=np.float64), 1e-12)
    return np.exp(np.mean(np.log(safe), axis=1)) - 1.0


def _annual_grid_max_drawdowns(factors: np.ndarray) -> np.ndarray:
    """Max-Drawdown pro Pfad als Anteil, auf dem cashflow-neutralen Index.

    Jahresgitter -- siehe Modul-Docstring, Abschnitt "Max-Drawdown".
    """
    safe = np.maximum(np.asarray(factors, dtype=np.float64), 1e-12)
    index = np.cumprod(safe, axis=1)
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

    if resolved == OBJECTIVE_MAX_DRAWDOWN:
        return weighted_mean(_annual_grid_max_drawdowns(factors), weights)

    annualized = _annualized_returns_from_factors(factors)
    if resolved == OBJECTIVE_CVAR_RETURN:
        # Expected Shortfall als positive Verlustzahl: der Tail-Mittelwert
        # wird negiert, damit "kleiner ist besser" gilt. Liegt auch der Tail
        # im Plus, wird der Term negativ und belohnt das -- bewusst nicht bei
        # 0 abgeschnitten, sonst waere die Zielfunktion dort flach und der
        # Solver bekaeme kein Gefaelle mehr.
        return -weighted_lower_tail_mean(annualized, weights)
    if resolved == OBJECTIVE_MIN_VOLATILITY:
        return weighted_std(annualized, weights)
    if resolved == OBJECTIVE_MAX_RETURN:
        return -weighted_mean(annualized, weights)

    raise ObjectiveModeError(f"Objective-Modus {resolved!r} ist nicht implementiert.")


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
    # Lazy Import: drawdown_refinement haengt an numpy, nicht am Optimizer.
    from services.drawdown_refinement import refine_max_drawdowns

    factors = np.asarray(portfolio_return_factors, dtype=np.float64)
    safe = np.maximum(factors, 1e-12)
    index = np.cumprod(safe, axis=1)
    ones = np.ones((index.shape[0], 1), dtype=np.float64)
    annual_paths = np.concatenate([ones, index], axis=1)

    coarse = weighted_mean(_annual_grid_max_drawdowns(factors), weights)
    refinement = refine_max_drawdowns(annual_paths, seed=int(seed))
    refined_values = np.asarray(refinement.refined_bps, dtype=np.float64) / 10000.0
    refined = weighted_mean(refined_values, weights)
    return {
        "annual_grid_mean_drawdown": float(coarse),
        "refined_mean_drawdown": float(refined),
        "understatement": float(refined - coarse),
        "sub_steps_per_year": int(refinement.sub_steps),
        "model_version": refinement.model_version,
    }
