"""Sprint U-96 (2026-06-05): Erweiterte Risikokennzahlen Sortino/Calmar/Information-Ratio.

Pure-Math-Modul ohne DB-/Modell-Abhaengigkeiten. Wird vom portfolio_engine
in den existierenden Metrics-Block eingebettet. Saemtliche Kennzahlen sind
**forward-looking** und basieren auf CMA-Erwartungswerten — *nicht* auf
realisierten Historien (es gibt nicht genuegend Performance-Daten in der
Beratungs-Software).

Konventionen (uebernommen aus portfolio_engine):
  - Alle Inputs/Outputs in **bps** (1 bp = 0.01%)
  - Ratios werden mit Faktor 100 skaliert (sharpe_ratio_x100, sortino_x100, ...)
    weil das Aggregator-Schema Integer-Felder benoetigt
  - Bei nicht berechenbaren Werten (Division durch 0, ungueltige Inputs)
    -> 0 zurueck (Aggregator zeigt dann "—")

Doku der mathematischen Annahmen:
  - **Sortino**: nutzt Downside-Deviation. Bei Normalverteilungs-Annahme
    ist downside_vol ≈ vol / sqrt(2). Wir nehmen diese konservative
    Approximation (Berater sieht "ungefähr halb so volatil wie Sharpe-Vol").
  - **Calmar**: jaehrliche Rendite / erwarteter Max-Drawdown. Wenn
    expected_max_drawdown nicht uebergeben wird, schaetzen wir es
    konservativ als 2*vol (Brownian-Motion-Bound fuer 10-Jahr-Horizont
    bei 95% Wahrscheinlichkeit).
  - **Information-Ratio**: (portfolio_return - benchmark_return) /
    tracking_error_vol. Wenn kein Benchmark uebergeben wird, verwenden
    wir die Risk-Free-Rate als degenerierten Benchmark (-> aequivalent
    zu Sharpe, aber expliziter Naming).
"""
from __future__ import annotations

import math


# Faktor fuer Downside-Vol-Approximation unter Normalverteilung:
# downside_vol ≈ vol / sqrt(2)
_GAUSSIAN_DOWNSIDE_FACTOR = 1.0 / math.sqrt(2.0)


def compute_sortino_ratio_x100(
    return_bps: int,
    vol_bps: int,
    risk_free_bps: int,
    *,
    downside_factor: float = _GAUSSIAN_DOWNSIDE_FACTOR,
) -> int:
    """Sortino-Ratio unter Normalverteilungs-Annahme.

    sortino = (return - risk_free) / downside_vol
    downside_vol ≈ vol * downside_factor (default 1/sqrt(2))

    Args:
        return_bps: Netto-Rendite in bps
        vol_bps: Gesamt-Volatilitaet in bps
        risk_free_bps: Risk-Free-Rate (typisch CMA.liquidity_return_bps)
        downside_factor: Konfigurierbarer Faktor fuer downside_vol/vol.
            Default 1/sqrt(2) ≈ 0.7071 (Gaussian).

    Returns:
        Sortino * 100 als Integer. 0 wenn nicht berechenbar.
    """
    if vol_bps <= 0:
        return 0
    if downside_factor <= 0:
        return 0
    downside_vol = vol_bps * downside_factor
    if downside_vol <= 0:
        return 0
    return int(round(((return_bps - risk_free_bps) / downside_vol) * 100))


def compute_calmar_ratio_x100(
    annual_return_bps: int,
    expected_max_drawdown_bps: int | None,
    *,
    vol_bps: int | None = None,
    horizon_years: int = 10,
) -> int:
    """Calmar-Ratio = jaehrliche Rendite / Max-Drawdown.

    Wenn expected_max_drawdown_bps None ist und vol_bps gegeben, schaetzen
    wir den Drawdown via Brownian-Motion-Bound:
        max_dd_bps ≈ 2 * vol_bps * sqrt(ln(horizon_years)/2)
    (konservativer 95%-Bound fuer 10-Jahr-Horizont ergibt ~2*vol).

    Args:
        annual_return_bps: jaehrliche Rendite in bps (typisch net_return_bps)
        expected_max_drawdown_bps: erwarteter Max-DD in bps; bei None wird
            via vol_bps geschaetzt
        vol_bps: Vola fuer Drawdown-Schaetzung (nur wenn dd None)
        horizon_years: fuer Drawdown-Schaetzung (default 10)

    Returns:
        Calmar * 100 als Integer. 0 wenn nicht berechenbar.
    """
    dd = expected_max_drawdown_bps
    if dd is None:
        if vol_bps is None or vol_bps <= 0:
            return 0
        if horizon_years < 2:
            # ln(<2)/2 ist negativ oder 0 -> degenerierter Bound, nimm einfache 2x-Heuristik
            dd = 2 * vol_bps
        else:
            dd = int(round(2 * vol_bps * math.sqrt(math.log(horizon_years) / 2)))
    if dd <= 0:
        return 0
    return int(round((annual_return_bps / dd) * 100))


def compute_information_ratio_x100(
    portfolio_return_bps: int,
    benchmark_return_bps: int,
    tracking_error_vol_bps: int,
) -> int:
    """Information-Ratio = (Portfolio - Benchmark) / Tracking-Error.

    Args:
        portfolio_return_bps: Rendite des Portfolios
        benchmark_return_bps: Rendite des Benchmarks (z.B. risk_free fuer
            Sharpe-aequivalent oder default-SAA)
        tracking_error_vol_bps: Volatilitaet der Excess-Returns (Portfolio - Benchmark)

    Returns:
        Information-Ratio * 100 als Integer. 0 wenn nicht berechenbar.
    """
    if tracking_error_vol_bps <= 0:
        return 0
    excess = portfolio_return_bps - benchmark_return_bps
    return int(round((excess / tracking_error_vol_bps) * 100))


def compute_extended_risk_metrics(
    *,
    return_bps: int,
    vol_bps: int,
    risk_free_bps: int,
    expected_max_drawdown_bps: int | None = None,
    benchmark_return_bps: int | None = None,
    tracking_error_vol_bps: int | None = None,
    horizon_years: int = 10,
) -> dict[str, int]:
    """Konsolidierte Berechnung der 3 erweiterten KPIs in einem Aufruf.

    Verwendet sinnvolle Defaults:
      - max_drawdown nicht gegeben -> Brownian-Bound-Schaetzung
      - benchmark nicht gegeben -> risk_free (= degenerierter IR ~ Sharpe)
      - tracking_error nicht gegeben -> vol_bps (= degenerierter IR)
    """
    sortino_x100 = compute_sortino_ratio_x100(return_bps, vol_bps, risk_free_bps)
    calmar_x100 = compute_calmar_ratio_x100(
        return_bps, expected_max_drawdown_bps,
        vol_bps=vol_bps, horizon_years=horizon_years,
    )
    benchmark = benchmark_return_bps if benchmark_return_bps is not None else risk_free_bps
    te = tracking_error_vol_bps if tracking_error_vol_bps is not None else vol_bps
    information_x100 = compute_information_ratio_x100(return_bps, benchmark, te)
    return {
        "sortino_ratio_x100": sortino_x100,
        "calmar_ratio_x100": calmar_x100,
        "information_ratio_x100": information_x100,
    }
