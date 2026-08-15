"""ADR-014, Schritt 5: MC-Simulation, extrahiert aus
`services/portfolio_engine.py` (God-Modul-Split, Welle 3.2).

Reine Datei-Grenz-Verschiebung, 0 Zeilen Fachlogik-Aenderung: die Funktionen
unten sind Byte-fuer-Byte-Kopien ihrer vormaligen Definitionen in
`portfolio_engine.py`. Zum Zeitpunkt dieser Extraktion (nach den bereits
angewandten Schritten 1-3 -- Gesamtvermoegen, Live-Rebalancing, CMA) lag der
Cluster in zwei physisch getrennten Blöcken: Zeilen 1096-1322 (Simulation-
Preferences-Parsing + deterministische Bucket-Pfad-Simulation) und Zeilen
1393-1549 (`_build_simulation_payload`) sowie Zeilen 2016-2769 (Monte-Carlo-
Statistik-Primitiven bis zum Kern-MC-Loop). Dazwischen (Zeilen 1323-1392 und
1550-2015) liegen Payload-Bau-/Goal-Metadaten-Funktionen (`_build_asset_class_
assumptions`, `_goal_hardness_key`, `_build_goal_analysis` etc.), die NICHT
Teil dieses Clusters sind und unangetastet in `portfolio_engine.py` bleiben.
`portfolio_engine.py` re-exportiert die Namen unten weiterhin unter denselben
Namen (Rueckwaerts-Kompatibilitaet fuer `services/advisory_report.py`, das
`_simulation_horizon_years` direkt importiert, sowie fuer alle bestehenden
Tests, die z.B. `from services.portfolio_engine import _run_allocation_monte_
carlo` o.ae. nutzen).

Exhaustive Grep-Verifikation (siehe Task-Report fuer Details): der einzige
tatsaechliche EXTERNE Nicht-Test-Konsument des gesamten Clusters ist
`_simulation_horizon_years` (importiert von `services/advisory_report.py`,
Zeile 3140). Alle anderen scheinbaren Treffer in `services/optimizer/*.py`,
`models/allocation.py`, `schemas/allocation.py`, `services/cma_import.py`
und `services/rates/ns_calibration_2024.py` sind entweder Doc-Kommentare
("konsistent zu portfolio_engine._run_allocation_monte_carlo") oder
unabhaengige DB-/Schema-Felder mit zufaellig gleichem `*_return_bps`-Suffix
(z.B. `bonds_chf_ig_return_bps`) -- KEINE echten Imports/Aufrufe. Ebenso ist
`_annualized_return_bps` intern in `portfolio_engine.py` inzwischen toter
Code (0 Aufrufe -- durch die time-weighted `_twr_annualized_bps`, #AA-5,
abgeloest); nur Tests importieren sie noch direkt beim Namen, daher bleibt
sie Teil dieser Extraktion.

Goal-Metadaten-Helfer-Aufloesung fuer `_monte_carlo_goal_summary` (Auftrag
dieser Extraktion): die Funktion ruft `_norm_text`, `_goal_hardness_key`,
`_compute_goal_score`, `_annualize_goal_amount`, `_goal_target_wealth_rappen`
sowie `_goal_reserve_for_goal`, `_goal_probability_factor` und
`_goal_pension_state_funded` auf. Per `services/portfolio_engine_reserve.py`
(Schritt-4-Entwurf, von der Koordination noch NICHT auf `portfolio_engine.py`
angewandt) sind `_goal_probability_factor` und `_goal_pension_state_funded`
im Reserve-Cluster-Entwurf bereits definiert -- SIE LIEGEN ABER, solange
dieser Entwurf nicht angewandt ist, PHYSISCH NOCH in `portfolio_engine.py`
(verifiziert per `grep -n "^def "`: Zeilen 184 bzw. 224 der aktuellen Datei).
`_goal_reserve_for_goal` liegt ebenfalls noch physisch in `portfolio_engine.py`
(Zeile 1793, wandert laut Reserve-Entwurf spaeter dorthin um). `_goal_hardness_
key`, `_compute_goal_score`, `_annualize_goal_amount`, `_goal_target_wealth_
rappen` sind Payload-Bau-Helfer und bleiben laut ADR ohnehin in
`portfolio_engine.py`. Konsequenz fuer DIESES Modul: alle 7 Namen werden ganz
normal per Lazy-Import aus `services.portfolio_engine` bezogen -- so wie
jeder andere Konsument dieser (noch) nicht verschobenen Namen auch, unabhaengig
davon, ob sie kuenftig in `portfolio_engine_reserve.py` landen oder dauerhaft
in `portfolio_engine.py` bleiben. Sollte der Reserve-Schritt spaeter angewandt
werden, aendert sich an dieser Extraktion nichts: der Lazy-Import-Zielpfad
(`services.portfolio_engine`) bleibt gueltig, weil `portfolio_engine.py` diese
Namen dann per Re-Export aus `portfolio_engine_reserve.py` weiterreicht --
exakt das gleiche Verhalten wie bereits fuer die CMA- und Gesamtvermoegen-
Cluster etabliert.

Zirkular-Import-Haertung (identisches Muster zu den Schritten 1-4): Funktionen,
die Konstanten/Helfer aus `services.portfolio_engine` selbst brauchen
(`BUCKET_FIELDS`, `BUCKET_LABELS`, `_bps`, `DEFAULT_SIMULATION_HORIZON_YEARS`,
`DEFAULT_SIMULATION_STRESS_MULTIPLIER`, `DEFAULT_REBALANCE_TRANSACTION_COST_
BPS`, `ALLOWED_SIMULATION_REBALANCE_MODES`, `DEFAULT_MONTE_CARLO_SIMULATIONS`,
`_norm_text`, `_parse_iso_date`, `_goal_projection_years`, `_annualize_goal_
amount`, `_goal_hardness_key`, `_goal_target_wealth_rappen`, `_compute_goal_
score`, `_goal_reserve_for_goal`, `_goal_probability_factor`,
`_goal_pension_state_funded`) sowie aus dem bereits extrahierten CMA-Cluster
(`_weighted_bucket_metrics`, `_build_cholesky_from_cma`, `_cornish_fisher_
transform`, `_inflation_path_series`, `_real_series_from_nominal` -- physisch
in `services/portfolio_engine_cma.py`, aber unter `services.portfolio_engine`
re-exportiert) und dem Gesamtvermoegen-Cluster (`_goal_uses_total_scope`,
`_external_assets_inflation_value` -- physisch in
`services/portfolio_engine_gesamtvermoegen.py`, ebenso re-exportiert)
importieren diese function-local (lazy) aus `services.portfolio_engine`,
NICHT auf Modul-Ebene -- ein Modul-Top-Level-Import waere nur sicher, wenn
`portfolio_engine.py` IMMER der Einstiegspunkt der Import-Kette ist, was
nicht garantiert ist. Modelle (`Goal`, `Mandate`, `OptimizerPolicy`,
`CapitalMarketAssumption`, `PortfolioSummary`) werden in diesem Cluster
ausschliesslich als Typ-Annotationen bzw. fuer Attributzugriffe verwendet
(nie fuer `isinstance`/Konstruktion) -- sie stehen daher nur unter
`TYPE_CHECKING`, ergaenzt durch `from __future__ import annotations`, damit
gar kein Laufzeit-Import noetig ist. `services.planning_horizon.
life_expectancy_year_for` ist dagegen ein ganz normaler Modul-Top-Level-Import
-- das Modul haengt nicht von `services.portfolio_engine` ab, also kein
Zyklus moeglich.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date
from typing import TYPE_CHECKING

from services.calendar_horizon import calendar_years_until
from services.planning_horizon import life_expectancy_year_for
from services.return_moments import (
    arithmetic_moments_to_log_parameters,
    bounded_cornish_fisher,
)

if TYPE_CHECKING:
    from models.allocation import CapitalMarketAssumption, OptimizerPolicy
    from models.mandates import Mandate
    from models.wealth import Goal
    from services.portfolio_engine import PortfolioSummary


def _simulation_horizon_years(
    simulation_prefs: dict | None,
    goals: list[Goal],
    mandate: Mandate | None = None,
) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import DEFAULT_SIMULATION_HORIZON_YEARS

    raw = (simulation_prefs or {}).get("horizonYears")
    has_explicit_override = raw not in (None, "", False)
    try:
        requested = int(str(raw).strip()) if has_explicit_override else DEFAULT_SIMULATION_HORIZON_YEARS
    except (TypeError, ValueError):
        requested = DEFAULT_SIMULATION_HORIZON_YEARS
        has_explicit_override = False
    def _dated_goal_horizon(goal) -> int:
        candidates = [int(getattr(goal, "horizon_years", 0) or 0)]
        for field in ("start_date", "target_date"):
            raw_date = str(getattr(goal, field, "") or "").strip()[:10]
            if not raw_date:
                continue
            try:
                goal_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            candidates.append(max(1, calendar_years_until(goal_date)))
        return max(candidates)

    # A dated liability must never be truncated merely because horizon_years
    # was left NULL. This is especially important for pension/recurring goals,
    # where target_date is the final due year rather than optional metadata.
    goal_horizon = max((_dated_goal_horizon(goal) for goal in goals), default=0)

    # Ein expliziter Berater-Horizont hat Vorrang vor der automatischen
    # Lebenserwartung. Zielhorizonte werden dennoch nicht abgeschnitten.
    if has_explicit_override:
        return max(7, requested, goal_horizon)

    life_year = life_expectancy_year_for(mandate=mandate)
    life_horizon = max(0, life_year - date.today().year + 1) if life_year else 0
    return max(7, requested, goal_horizon, life_horizon)


def _simulation_stress_multiplier(simulation_prefs: dict | None) -> float:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import DEFAULT_SIMULATION_STRESS_MULTIPLIER

    raw = (simulation_prefs or {}).get("stressMultiplier")
    try:
        value = float(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_SIMULATION_STRESS_MULTIPLIER
    except (TypeError, ValueError):
        value = DEFAULT_SIMULATION_STRESS_MULTIPLIER
    return max(0.25, min(2.5, value))


def _simulation_transaction_cost_bps(simulation_prefs: dict | None) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import DEFAULT_REBALANCE_TRANSACTION_COST_BPS

    raw = (simulation_prefs or {}).get("transactionCostBps")
    # Cave: `0 in (None, "", False)` ist True (0 == False in Python).
    # Daher explizit auf None/leer pruefen, damit ein User-Input 0 NICHT zum
    # Default-Fallback fuehrt.
    if raw is None or raw == "" or raw is False:
        return DEFAULT_REBALANCE_TRANSACTION_COST_BPS
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = DEFAULT_REBALANCE_TRANSACTION_COST_BPS
    return max(0, min(200, value))


def _simulation_rebalance_mode(simulation_prefs: dict | None) -> str:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import ALLOWED_SIMULATION_REBALANCE_MODES

    raw = str((simulation_prefs or {}).get("rebalanceMode") or "bands").strip().lower()
    aliases = {
        "band": "bands",
        "bands": "bands",
        "calendar": "calendar",
        "jaehrlich": "calendar",
        "none": "none",
        "off": "none",
        "aus": "none",
    }
    mode = aliases.get(raw, "bands")
    return mode if mode in ALLOWED_SIMULATION_REBALANCE_MODES else "bands"


def _simulation_crisis_strength(simulation_prefs: dict | None) -> float:
    """Sprint U-P4 Fix M5: Crisis-Korrelations-Stärke aus simulation-Prefs.

    Default 0.0 (off). Akzeptiert Bool ("crisisMode": true → 1.0) ODER Float
    in [0,1] für graduellen Übergang Normal→Crisis-Regime.
    """
    if not simulation_prefs:
        return 0.0
    raw = simulation_prefs.get("crisisMode") or simulation_prefs.get("crisisStrength")
    if raw is None:
        return 0.0
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _simulation_use_tail_risk(simulation_prefs: dict | None) -> bool:
    """Sprint U-P4 Fix M6: Default False (Backwards-Compat). Wenn True und
    CMA Skewness/Kurtosis-Felder hat, wird Cornish-Fisher-Transform auf
    die Normal-Samples angewendet."""
    if not simulation_prefs:
        return False
    raw = simulation_prefs.get("tailRisk") or simulation_prefs.get("cornishFisher")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def _target_bucket_values(total_rappen: int, weights_bps: dict[str, int]) -> dict[str, int]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS

    values = {key: 0 for key in BUCKET_FIELDS}
    remaining = int(total_rappen or 0)
    for idx, key in enumerate(BUCKET_FIELDS):
        if idx == len(BUCKET_FIELDS) - 1:
            values[key] = remaining
            break
        amount = int(round(total_rappen * int(weights_bps.get(key, 0)) / 10000))
        values[key] = amount
        remaining -= amount
    return values


def _weights_from_bucket_values(values: dict[str, int]) -> dict[str, int]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, _bps

    total = sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS)
    if total <= 0:
        return {key: 0 for key in BUCKET_FIELDS}
    return {
        key: _bps(max(0, int(values.get(key, 0))), total)
        for key in BUCKET_FIELDS
    }


def _apply_cashflow_to_bucket_values(values: dict[str, int], cashflow_rappen: int) -> int:
    """Applies cashflow to bucket values. Returns deficit remainder if buckets are exhausted.

    Positive cashflow lands in liquidity. Negative cashflow draws from buckets in order
    (liquidity, bonds, equities, alternatives, real_estate). If all buckets are zero and
    negative remainder still exists, returns it as positive int so the caller can
    accumulate it as a separate deficit (Lebensluecke). For non-negative input or fully
    funded outflow, returns 0.
    """
    amount = int(cashflow_rappen or 0)
    if amount >= 0:
        values["liquidity"] = int(values.get("liquidity", 0)) + amount
        return 0
    remaining = abs(amount)
    for key in ("liquidity", "bonds", "equities", "alternatives", "real_estate"):
        available = max(0, int(values.get(key, 0)))
        if available <= 0:
            continue
        used = min(available, remaining)
        values[key] = available - used
        remaining -= used
        if remaining <= 0:
            break
    return remaining


def _rebalance_bucket_values_to_targets(values: dict[str, int], targets: dict[str, int]) -> tuple[dict[str, int], int]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS

    total = sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS)
    target_values = _target_bucket_values(total, targets)
    turnover = int(round(sum(abs(int(target_values[key]) - int(values.get(key, 0))) for key in BUCKET_FIELDS) / 2))
    return target_values, turnover


def _simulate_bucket_path(
    *,
    start_values: dict[str, int],
    returns_by_asset: dict[str, int],
    cashflow_series_rappen: list[int],
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    start_year: int,
    rebalance_mode: str,
    transaction_cost_bps: int = 0,
    initial_deficit_rappen: int = 0,
    vols_by_asset: dict[str, int] | None = None,  # momententreues Lognormal-Mapping
) -> tuple[list[int], list[dict]]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS

    values = {key: max(0, int(start_values.get(key, 0))) for key in BUCKET_FIELDS}
    # Z8-W2: Lebensluecke wird als positiver Schuldenstand mitgefuehrt.
    # initial_deficit_rappen erlaubt es, externe Verbindlichkeiten (Hypothek etc.)
    # in die Total-Pfad-Simulation einzubringen; sie wachsen nicht mit, weil
    # Schuldzinsen ohnehin als recurring expense in cashflow_series_rappen liegen.
    accumulated_deficit = max(0, int(initial_deficit_rappen or 0))
    totals = [sum(values.values()) - accumulated_deficit]
    events: list[dict] = []
    for offset, contribution in enumerate(cashflow_series_rappen):
        year = start_year + offset
        for key in BUCKET_FIELDS:
            r = int(returns_by_asset.get(key, 0)) / 10000
            if vols_by_asset:
                # Deterministic median under the same arithmetic CMA moments.
                sigma = int(vols_by_asset.get(key, 0)) / 10000
                # CMA returns are arithmetic expected returns. Convert their
                # gross factor to log space before applying volatility drag;
                # using ``r`` directly would make 10% become exp(.10)-1.
                log_location, _ = arithmetic_moments_to_log_parameters(
                    r,
                    sigma,
                )
                growth = math.exp(log_location)
            else:
                growth = 1 + r
            values[key] = int(round(max(0, values[key]) * growth))
        deficit_rest = _apply_cashflow_to_bucket_values(values, int(contribution or 0))
        accumulated_deficit += deficit_rest
        weights = _weights_from_bucket_values(values)
        breached = []
        for key in BUCKET_FIELDS:
            mn = int(minimums.get(key, 0))
            mx = int(maximums.get(key, 0))
            # Zero bands = Bucket nicht aktiv konfiguriert -> keine Breach-Pruefung.
            if mn == 0 and mx == 0:
                continue
            if weights[key] < mn or weights[key] > mx:
                breached.append(BUCKET_LABELS[key])
        should_rebalance = False
        note = ""
        if rebalance_mode == "calendar":
            should_rebalance = sum(values.values()) > 0
            note = "Kalender-Rebalancing auf strategische Sollgewichte."
        elif rebalance_mode == "bands" and breached:
            should_rebalance = True
            note = "Bandbreiten-Rebalancing wegen Drift ausserhalb der Zielbaender."
        if should_rebalance:
            values, turnover = _rebalance_bucket_values_to_targets(values, targets)
            if transaction_cost_bps > 0 and turnover > 0:
                cost_rappen = int(round(turnover * transaction_cost_bps / 10000))
                total_after = max(1, sum(values.values()))
                for key in BUCKET_FIELDS:
                    values[key] = max(0, int(round(
                        values[key] * (1 - cost_rappen / total_after)
                    )))
            if turnover > 0 or breached:
                events.append(
                    {
                        "year": year,
                        "mode": rebalance_mode,
                        "breached_buckets": breached,
                        "turnover_rappen": turnover,
                        "notes": note,
                    }
                )
        # Z8-W2: Asset-Buckets bleiben physisch >= 0; akkumulierter Defizit
        # (Lebensluecke) macht totals negativ wenn Vermoegen aufgezehrt ist.
        totals.append(sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS) - accumulated_deficit)
    return totals, events


def _coerce_external_foundation_projection(
    projection: dict | None,
    horizon_years: int,
) -> tuple[list[int], list[int], list[int]] | None:
    if projection is None:
        return None
    if not isinstance(projection, dict):
        raise ValueError("external_foundation_projection must be an object")
    expected_length = max(0, int(horizon_years)) + 1
    property_series = projection.get("property_series_rappen")
    liability_series = projection.get("liability_series_rappen")
    pledged_asset_series = projection.get("pledged_asset_series_rappen")
    if not all(
        isinstance(series, list)
        for series in (
            property_series,
            liability_series,
            pledged_asset_series,
        )
    ):
        raise ValueError(
            "external_foundation_projection requires property, liability and "
            "pledged-asset series"
        )
    if any(
        len(series) != expected_length
        for series in (
            property_series,
            liability_series,
            pledged_asset_series,
        )
    ):
        raise ValueError(
            "external_foundation_projection length must match the simulation horizon"
        )
    if any(
        type(value) is not int or value < 0
        for series in (
            property_series,
            liability_series,
            pledged_asset_series,
        )
        for value in series
    ):
        raise ValueError(
            "external_foundation_projection values must be non-negative "
            "integer Rappen"
        )
    return (
        list(property_series),
        list(liability_series),
        list(pledged_asset_series),
    )


def _total_financial_summary_without_direct_property(
    total_summary: PortfolioSummary,
    property_start_rappen: int,
    bucket_fields,
) -> PortfolioSummary:
    from services.portfolio_engine import PortfolioSummary as _PortfolioSummary

    amounts = {
        key: max(0, int(total_summary.amounts_rappen.get(key, 0)))
        for key in bucket_fields
    }
    property_start = max(0, int(property_start_rappen or 0))
    if property_start > amounts["real_estate"]:
        raise ValueError(
            "External direct-property principal exceeds the total real-estate bucket"
        )
    amounts["real_estate"] -= property_start
    return _PortfolioSummary(
        amounts_rappen=amounts,
        total_rappen=sum(amounts.values()),
    )


def _combine_financial_and_foundation_series(
    financial_series: list[int],
    property_series: list[int],
    liability_series: list[int],
    pledged_asset_series: list[int],
) -> list[int]:
    return [
        int(financial)
        + int(property_value)
        + int(pledged_asset)
        - int(liability)
        for financial, property_value, liability, pledged_asset in zip(
            financial_series,
            property_series,
            liability_series,
            pledged_asset_series,
        )
    ]


def _build_simulation_payload(
    *,
    advisory_summary: PortfolioSummary,
    cashflow_projection_series_rappen: list[int],
    cma: CapitalMarketAssumption,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    start_year: int,
    simulation_prefs: dict | None,
    sub_allocations: list[dict] | None = None,
    target_total_rappen: int | None = None,
    target_start_value_rappen: int | None = None,  # alias from rp-ueberarbeitung
    total_summary: PortfolioSummary | None = None,
    total_liabilities_rappen: int = 0,
    external_foundation_projection: dict | None = None,
) -> dict:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        _inflation_path_series,
        _real_series_from_nominal,
        _weighted_bucket_metrics,
    )
    from services.portfolio_engine_gesamtvermoegen import (
        _total_financial_target_weights,
    )

    if target_start_value_rappen is not None and target_total_rappen is None:
        target_total_rappen = target_start_value_rappen
    horizon_years = max(1, len(cashflow_projection_series_rappen))
    external_foundation = _coerce_external_foundation_projection(
        external_foundation_projection,
        horizon_years,
    )
    stress_multiplier = _simulation_stress_multiplier(simulation_prefs)
    rebalance_mode = _simulation_rebalance_mode(simulation_prefs)
    transaction_cost_bps = _simulation_transaction_cost_bps(simulation_prefs)
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation, falls vorhanden.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    # 2026-06-17 (User-Fachentscheid): Liquidität wertet in der PROJEKTION NICHT auf
    # (Cash = 0%, sofern nicht anders gesetzt). Tatsächliche Zinsen kommen ausschliesslich
    # über den abgeleiteten Zinsertrag-Cashflow rein -> kein Doppelzählen, ein 0%-Konto
    # bleibt flach. cma.liquidity_return_bps bleibt fuer risk-free/Sharpe/Optimizer unberührt.
    returns = {**returns, "liquidity": 0}
    vols = {**vols, "liquidity": 0}
    target_start_total = int(target_total_rappen if target_total_rappen is not None else advisory_summary.total_rappen)
    target_values = _target_bucket_values(target_start_total, targets)
    # Z8-W2 Phase 2: Total-Pfad nutzt Asset-Buckets aus Gesamtvermoegen,
    # Liabilities werden als initial_deficit eingebracht. Schuldzinsen
    # liegen ohnehin als recurring expense im cashflow_series.
    total_liabilities_rappen = max(0, int(total_liabilities_rappen or 0))
    downside_returns = {
        key: int(max(-9500, round(returns[key] - vols[key] * stress_multiplier)))
        for key in BUCKET_FIELDS
    }
    upside_returns = {
        key: int(round(returns[key] + vols[key] * stress_multiplier))
        for key in BUCKET_FIELDS
    }
    # Hauptpfade (current/target) nutzen dieselbe momententreue lognormale
    # Wachstumskonvention wie die Monte-Carlo-Simulation. Fuer arithmetische
    # CMA-Momente gilt v=log(1+(sigma/(1+mu))^2) und der Medianfaktor ist
    # exp(log(1+mu)-v/2). Dadurch konvergiert die deterministische Hauptlinie
    # zum MC-Median; Mean und einfache Return-Volatilitaet bleiben zugleich die
    # publizierten CMA-Momente.
    current_series, _ = _simulate_bucket_path(
        start_values=advisory_summary.amounts_rappen,
        returns_by_asset=returns,
        vols_by_asset=vols,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode="none",
        transaction_cost_bps=0,
    )
    target_series, rebalance_events = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=returns,
        vols_by_asset=vols,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    downside_series, _ = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=downside_returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    upside_series, _ = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=upside_returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    # Total-wealth paths keep direct property outside the listed-real-estate
    # bucket. Only financial assets receive CMA returns/rebalancing; the
    # position-derived property series and outstanding mortgage principal are
    # added afterwards. Rent remains exactly once in the common cashflow path.
    if total_summary is not None:
        if external_foundation is not None:
            property_series, liability_series, pledged_asset_series = (
                external_foundation
            )
            financial_summary = _total_financial_summary_without_direct_property(
                total_summary,
                property_series[0],
                BUCKET_FIELDS,
            )
            total_target_values = _target_bucket_values(
                financial_summary.total_rappen,
                _total_financial_target_weights(targets),
            )
            financial_current_series, _ = _simulate_bucket_path(
                start_values=financial_summary.amounts_rappen,
                returns_by_asset=returns,
                vols_by_asset=vols,
                cashflow_series_rappen=cashflow_projection_series_rappen,
                targets=targets,
                minimums=minimums,
                maximums=maximums,
                start_year=start_year,
                rebalance_mode="none",
                transaction_cost_bps=0,
            )
            financial_target_series, _ = _simulate_bucket_path(
                start_values=total_target_values,
                returns_by_asset=returns,
                vols_by_asset=vols,
                cashflow_series_rappen=cashflow_projection_series_rappen,
                targets=targets,
                minimums=minimums,
                maximums=maximums,
                start_year=start_year,
                rebalance_mode=rebalance_mode,
                transaction_cost_bps=transaction_cost_bps,
            )
            total_current_series = _combine_financial_and_foundation_series(
                financial_current_series,
                property_series,
                liability_series,
                pledged_asset_series,
            )
            total_target_series = _combine_financial_and_foundation_series(
                financial_target_series,
                property_series,
                liability_series,
                pledged_asset_series,
            )
        else:
            # Backwards compatibility for direct low-level callers that have
            # not supplied the position-derived foundation contract yet.
            total_target_start = max(
                0,
                int(total_summary.total_rappen) - total_liabilities_rappen,
            )
            total_target_values = _target_bucket_values(total_target_start, targets)
            total_current_series, _ = _simulate_bucket_path(
                start_values=total_summary.amounts_rappen,
                returns_by_asset=returns,
                vols_by_asset=vols,
                cashflow_series_rappen=cashflow_projection_series_rappen,
                targets=targets,
                minimums=minimums,
                maximums=maximums,
                start_year=start_year,
                rebalance_mode="none",
                transaction_cost_bps=0,
                initial_deficit_rappen=total_liabilities_rappen,
            )
            total_target_series, _ = _simulate_bucket_path(
                start_values=total_target_values,
                returns_by_asset=returns,
                vols_by_asset=vols,
                cashflow_series_rappen=cashflow_projection_series_rappen,
                targets=targets,
                minimums=minimums,
                maximums=maximums,
                start_year=start_year,
                rebalance_mode=rebalance_mode,
                transaction_cost_bps=transaction_cost_bps,
            )
    else:
        total_current_series = []
        total_target_series = []
    inflation_series_bps = _inflation_path_series(cma, horizon_years, start_year)
    return {
        "horizon_years": horizon_years,
        "start_year": start_year,
        "year_labels": [start_year + offset for offset in range(horizon_years + 1)],
        "rebalance_mode": rebalance_mode,
        "stress_multiplier": stress_multiplier,
        "current_mix_series_rappen": current_series,
        "target_mix_series_rappen": target_series,
        "total_mix_current_series_rappen": total_current_series,
        "total_mix_target_series_rappen": total_target_series,
        "downside_series_rappen": downside_series,
        "upside_series_rappen": upside_series,
        "real_target_series_rappen": _real_series_from_nominal(target_series, inflation_series_bps),
        "inflation_series_bps": inflation_series_bps,
        "rebalancing_events": rebalance_events,
    }


def _monte_carlo_simulations(simulation_prefs: dict | None) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import DEFAULT_MONTE_CARLO_SIMULATIONS

    raw = (simulation_prefs or {}).get("monteCarloRuns")
    try:
        value = int(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_MONTE_CARLO_SIMULATIONS
    except (TypeError, ValueError):
        value = DEFAULT_MONTE_CARLO_SIMULATIONS
    return max(250, min(2500, value))


def _monte_carlo_seed(*parts) -> int:
    payload = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _percentile(values: list[int | float], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return int(round(ordered[0]))
    q = max(0.0, min(1.0, float(quantile)))
    index = q * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return int(round(ordered[lower]))
    weight = index - lower
    value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return int(round(value))


def _annualized_return_bps(start_value: int, end_value: int, years: int) -> int:
    # #AA-6 Fix (2026-06-12): Aufgebrauchte Pfade (end_value <= 0) sind ein
    # Totalverlust und muessen mit -100% (-10000 bps) einfliessen, nicht mit 0
    # (das verzerrte Median + Erfolgsrate nach oben). Konsistent zu _return_bps.
    if end_value <= 0:
        return -10000
    if years <= 0 or start_value <= 0:
        return 0
    return int(round((math.pow(end_value / start_value, 1 / years) - 1) * 10000))


def _twr_annualized_bps(growth_product: float, years: int) -> int:
    # #AA-5 (2026-06-12): annualisierte time-weighted Rendite aus dem Produkt der
    # jaehrlichen Markt-Wachstumsfaktoren (cashflow-bereinigt). Eingebrochene Pfade
    # (Produkt <= 0) -> -100% (analog _annualized_return_bps Floor, #AA-6).
    if years <= 0:
        return 0
    if growth_product <= 0:
        return -10000
    return int(round((math.pow(growth_product, 1 / years) - 1) * 10000))


def _return_bps(start_value: int, end_value: int) -> int:
    if start_value <= 0 or end_value <= 0:
        return -10000 if end_value <= 0 else 0
    return int(round((end_value / start_value - 1) * 10000))


def _loss_bps(start_value: int, end_value: int) -> int:
    return max(0, -_return_bps(start_value, end_value))


def _stddev_bps(values: list[int | float]) -> int:
    """Populations-Standardabweichung (in bps) einer Return-Verteilung — fuer die
    simulierte 1-Jahres-Volatilitaet (SOLL/IST-Kennzahlenvergleich)."""
    if not values or len(values) < 2:
        return 0
    mean = sum(float(v) for v in values) / len(values)
    var = sum((float(v) - mean) ** 2 for v in values) / len(values)
    return int(round(math.sqrt(var)))


def _conditional_percentile_average(values: list[int | float], quantile: float, *, upper_tail: bool = False) -> int:
    if not values:
        return 0
    threshold = _percentile(values, quantile)
    if upper_tail:
        tail = [float(value) for value in values if float(value) >= float(threshold)]
    else:
        tail = [float(value) for value in values if float(value) <= float(threshold)]
    if not tail:
        return int(threshold)
    return int(round(sum(tail) / len(tail)))


def _max_drawdown_bps(path_values: list[int]) -> int:
    peak = 0
    max_drawdown = 0
    for raw_value in path_values:
        value = max(0, int(raw_value or 0))
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = int(round((peak - value) / peak * 10000))
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _year_index_for_goal(goal: Goal, start_year: int, horizon_years: int) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _goal_projection_years

    years = _goal_projection_years(goal)
    return max(1, min(int(years or 1), int(horizon_years)))


def _full_goal_duration_years(goal: Goal) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _parse_iso_date

    start_date = _parse_iso_date(goal.start_date)
    target_date = _parse_iso_date(goal.target_date)
    if start_date and target_date and target_date >= start_date:
        return max(1, target_date.year - start_date.year + 1)
    return 1


def _goal_duration_years(goal: Goal, start_year: int, horizon_years: int) -> int:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _parse_iso_date

    start_date = _parse_iso_date(goal.start_date)
    target_date = _parse_iso_date(goal.target_date)
    if start_date and target_date and target_date >= start_date:
        sim_end_year = int(start_year) + int(horizon_years)
        overlap_start = max(start_date.year, int(start_year))
        overlap_end = min(target_date.year, sim_end_year)
        return max(0, overlap_end - overlap_start + 1)
    if int(goal.is_ongoing or 0):
        anchor = max(start_year, start_date.year if start_date else start_year)
        return max(1, horizon_years - (anchor - start_year))
    return 1


def _monte_carlo_goal_summary(
    goal: Goal,
    *,
    path_values_by_year: list[list[int]],
    total_path_values_by_year: list[list[int]] | None = None,
    annualized_return_samples_bps: list[int],
    inflation_series_bps: list[int],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    start_year: int,
    horizon_years: int,
    policy: OptimizerPolicy,
) -> dict:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        _annualize_goal_amount,
        _compute_goal_score,
        _external_assets_inflation_value,
        _goal_hardness_key,
        _goal_pension_state_funded,
        _goal_probability_factor,
        _goal_reserve_for_goal,
        _goal_target_wealth_rappen,
        _goal_uses_total_scope,
        _norm_text,
    )

    index = _year_index_for_goal(goal, start_year, horizon_years)
    # Advisory goals use the advised portfolio paths. Total-wealth goals can
    # additionally consume the exact total paths (direct property, liabilities
    # and pledged assets included) built by this same Monte-Carlo run.
    scaled_values = list(path_values_by_year[index])
    p10 = _percentile(scaled_values, 0.10)
    p25 = _percentile(scaled_values, 0.25)
    p50 = _percentile(scaled_values, 0.50)
    p90 = _percentile(scaled_values, 0.90)
    goal_type = _norm_text(goal.goal_type)
    hardness_key = _goal_hardness_key(goal)
    evaluation_note = None
    target = 0
    outside_simulation_horizon = False
    # 2026-07-24 (goals-1, Formel-Audit): siehe Kommentar an der Verzweigung
    # unten -- ein Flag statt der Bedingung zweimal zu wiederholen, weil sie
    # auch den pessimistic_shortfall_rappen-Block betrifft.
    pension_state_funded_goal = (
        goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe")
        and _goal_pension_state_funded(goal)
    )

    # B5: Score = alpha * success_rate_pct + (1-alpha) * funded_ratio_pct
    # Pro Goal-Typ: success_rate_pct (binaer/MC) und funded_ratio_pct als
    # einheitliche Inputs in _compute_goal_score.
    if goal_type == "Renditeziel":
        target = int(goal.target_return_bps or 0)
        success_rate_pct = int(round(sum(1 for sample in annualized_return_samples_bps if sample >= target) / max(1, len(annualized_return_samples_bps)) * 100))
        median_return = _percentile(annualized_return_samples_bps, 0.50) if annualized_return_samples_bps else 0
        funded_ratio_p50 = 0.0 if target <= 0 else round(max(0.0, min(2.0, median_return / target)), 4)
        funded_ratio_pct = 100 if target <= 0 else max(0, min(200, int(round(median_return / target * 100))))
        score = _compute_goal_score(
            success_rate_pct=success_rate_pct,
            funded_ratio_pct=funded_ratio_pct,
            hardness_key=hardness_key,
        )
    elif pension_state_funded_goal:
        # 2026-07-24 (goals-1, Formel-Audit): AHV/Renten-Goals sind staatlich
        # gedeckt -- der deterministische Pfad (_goal_reserve_for_goal,
        # Sprint B3) behandelt sie deshalb als voll erfuellt (keine
        # Portfolio-Finanzierung noetig), UNABHAENGIG von den Jahren bis
        # Zieleintritt. Der MC-Pfad rief _goal_pension_state_funded nie ab
        # und bewertete dasselbe Goal wie ein normales, voll aus dem
        # simulierten Portfolio zu finanzierendes Ausgabenziel -- Folge: der
        # MC-Bericht zeigte einen unabhaengig (und meist niedrigeren)
        # berechneten Score als der deterministische Bericht fuer dasselbe
        # Ziel. Fix: identische Formel wie _goal_reserve_for_goal (target *
        # Wahrscheinlichkeitsfaktor), damit beide Berichte konsistent sind.
        base_target = max(1, int(
            _annualize_goal_amount(goal)
            if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
            else int(goal.target_amount_rappen or 0)
        ))
        target = base_target
        available = _goal_reserve_for_goal(goal)
        success_rate_pct = 100 if available >= base_target else 0
        funded_ratio_p50 = round(available / base_target, 4)
        funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
        score = _compute_goal_score(
            success_rate_pct=success_rate_pct,
            funded_ratio_pct=funded_ratio_pct,
            hardness_key=hardness_key,
        )
    elif goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        target = _annualize_goal_amount(goal)
        # 2026-07-24 (Formel-Audit, Folgefund zu goals-1): bedingte Goals
        # (probability_pct < 100, Sprint B6) wurden im deterministischen Pfad
        # ueber _goal_reserve_for_goal() bereits mit dem Wahrscheinlichkeits-
        # faktor gewichtet -- der MC-Pfad wendete ihn fuer Ausgabenziele nie
        # an (nur fuer Renditeziel, Zeile ~3082). Ein 50%-wahrscheinliches
        # Ausgabenziel wurde im MC-Bericht wie ein sicheres (100%) behandelt.
        # Fix: denselben Faktor auf das Ziel anwenden -- ein bedingtes Ziel
        # braucht proportional weniger Deckung, konsistent zur Reserve-Logik.
        target = target * _goal_probability_factor(goal)
        if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
            full_duration = _full_goal_duration_years(goal)
            duration = _goal_duration_years(goal, start_year, horizon_years)
            if duration <= 0:
                target = max(1, int(target))
                success_rate_pct = 0
                funded_ratio_p50 = 0.0
                score = 0
                outside_simulation_horizon = True
                evaluation_note = f"Ziel liegt ausserhalb des aktuellen Simulationshorizonts (Horizont: {horizon_years} Jahre)."
            else:
                target *= duration
                target = max(1, int(target))
                success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
                funded_ratio_p50 = round(p50 / target, 4)
                funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
                score = _compute_goal_score(
                    success_rate_pct=success_rate_pct,
                    funded_ratio_pct=funded_ratio_pct,
                    hardness_key=hardness_key,
                )
                if duration < full_duration:
                    evaluation_note = f"Bewertet fuer {duration} von {full_duration} Jahren (Simulationshorizont: {horizon_years} Jahre)."
        else:
            target = max(1, int(target))
            success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
            funded_ratio_p50 = round(p50 / target, 4)
            funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
    elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
        probability_factor = _goal_probability_factor(goal)
        target = int(round(
            _goal_target_wealth_rappen(goal, index, inflation_series_bps)
            * probability_factor
        ))
        # Total-scope goals use the exact pathwise external foundation instead
        # of reconstructing it as a CPI-grown scalar.  Expected-funding
        # semantics for contingent goals remain unchanged:
        #   advisory + p * (total - advisory) >= p * target.
        # At p=100% this is exactly the visible total-wealth path.
        if _goal_uses_total_scope(goal):
            exact_total_values = None
            if total_path_values_by_year is not None:
                if index >= len(total_path_values_by_year):
                    raise ValueError(
                        "Total-wealth goal path does not cover the goal horizon"
                    )
                exact_total_values = list(total_path_values_by_year[index])
                if len(exact_total_values) != len(scaled_values):
                    raise ValueError(
                        "Advisory and total goal paths must contain identical samples"
                    )
            if exact_total_values is not None:
                scaled_values = [
                    int(round(
                        advisory_value
                        + probability_factor * (total_value - advisory_value)
                    ))
                    for advisory_value, total_value in zip(
                        scaled_values, exact_total_values, strict=True
                    )
                ]
            else:
                # Backwards compatibility for direct low-level callers that do
                # not yet provide total paths. Production passes the exact path.
                external_projected = _external_assets_inflation_value(
                    max(
                        0,
                        int(total_wealth_rappen or 0)
                        - int(advisory_wealth_rappen or 0),
                    ),
                    index,
                    inflation_series_bps,
                )
                scaled_values = [
                    int(round(value + external_projected * probability_factor))
                    for value in scaled_values
                ]
            p10 = _percentile(scaled_values, 0.10)
            p25 = _percentile(scaled_values, 0.25)
            p50 = _percentile(scaled_values, 0.50)
            p90 = _percentile(scaled_values, 0.90)
        if target <= 0:
            success_rate_pct = 100
            funded_ratio_p50 = 2.0
            funded_ratio_pct = 200
        else:
            success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
            funded_ratio_p50 = round(p50 / target, 4)
            funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
        score = _compute_goal_score(
            success_rate_pct=success_rate_pct,
            funded_ratio_pct=funded_ratio_pct,
            hardness_key=hardness_key,
        )
    elif goal_type == "Maximierung":
        target = max(1, advisory_wealth_rappen)
        success_rate_pct = 100
        funded_ratio_p50 = round(p50 / target, 4)
        score = 100
    else:
        target = max(1, advisory_wealth_rappen)
        success_rate_pct = 100
        funded_ratio_p50 = round(p50 / target, 4)
        score = max(0, min(100, int(round((_percentile(annualized_return_samples_bps, 0.50) / 100))))) if annualized_return_samples_bps else 50

    # PAR-3/PAR-6: Methodik-konforme Anzeige. Die Zielerreichung ist
    # effektiv/gewuenscht im Median, auf 100 % gedeckelt. Der pessimistische
    # CHF-Fehlbetrag basiert auf dem schlechtesten Quartil (P25-Pfad) —
    # so wie in der Beratungs-Methodik fuer Nicht-Cashflow-Ziele das
    # schlechteste Quartil ausgewiesen wird. Beim Renditeziel wird die
    # Rendite in ein implizites Endvermoegen umgerechnet, damit die Differenz
    # ebenfalls als CHF-Betrag ausweisbar ist.
    if pension_state_funded_goal:
        # 2026-07-24 (goals-1): der "pessimistische" Fehlbetrag darf hier
        # NICHT vom simulierten Portfolio-P25 abhaengen -- die Deckung kommt
        # von der staatlichen Saeule, nicht vom Portfolio. Fehlbetrag =
        # Ziel minus das, was _goal_reserve_for_goal als gedeckt ausweist
        # (0, ausser das Ziel ist bedingt/wahrscheinlichkeitsgewichtet).
        median_achievement_pct = max(0, min(100, int(round(funded_ratio_p50 * 100))))
        pessimistic_shortfall_rappen = max(0, int(target) - int(round(target * funded_ratio_p50)))
    elif goal_type == "Renditeziel":
        if target <= 0:
            median_achievement_pct = 100
            pessimistic_shortfall_rappen = 0
        else:
            median_achievement_pct = max(0, min(100, int(round(funded_ratio_p50 * 100))))
            pessimistic_return_bps = (
                _percentile(annualized_return_samples_bps, 0.25)
                if annualized_return_samples_bps
                else -10000
            )
            desired_growth = max(0.0, 1.0 + target / 10000.0) ** index
            pessimistic_growth = max(0.0, 1.0 + pessimistic_return_bps / 10000.0) ** index
            desired_value = int(round(max(0, advisory_wealth_rappen) * desired_growth))
            pessimistic_value = int(round(max(0, advisory_wealth_rappen) * pessimistic_growth))
            pessimistic_shortfall_rappen = max(0, desired_value - pessimistic_value)
    elif goal_type == "Maximierung":
        median_achievement_pct = 100
        pessimistic_shortfall_rappen = 0
    else:
        median_achievement_pct = max(0, min(100, int(round(funded_ratio_p50 * 100))))
        pessimistic_shortfall_rappen = (
            max(0, int(target))
            if outside_simulation_horizon
            else max(0, int(target) - int(p25))
        )

    return {
        "goal_id": goal.id,
        "label": goal.label,
        "years": index,
        "success_rate_pct": success_rate_pct,
        "funded_ratio_p50": funded_ratio_p50,
        "median_achievement_pct": median_achievement_pct,
        "pessimistic_shortfall_rappen": pessimistic_shortfall_rappen,
        "projected_value_p10_rappen": p10,
        "projected_value_p25_rappen": p25,
        "projected_value_p50_rappen": p50,
        "projected_value_p90_rappen": p90,
        "score": max(0, min(100, score)),
        "evaluation_note": evaluation_note,
    }


def _sequence_of_returns_depletion(
    depletion_offsets: list[int | None], start_year: int
) -> tuple[int, int | None]:
    """#96 Sequence-of-Returns / Verzehr-Kennzahl: Anteil der MC-Pfade, deren
    Vermoegen VOR Horizontende aufgezehrt ist (Pfad-Total <= 0), plus mittleres
    Erschoepfungsjahr (Median der betroffenen Pfade). Misst das Sequence-of-
    Returns-Risiko: schlechte Renditen frueh im Verzehr zehren das Kapital
    schneller auf. In der Akkumulation (keine Netto-Entnahmen) ist die Quote ~0%.

    depletion_offsets: pro Simulation der Jahres-Offset der ersten Erschoepfung
    (Pfad-Total <= 0) oder None, wenn der Pfad nie erschoepft."""
    n = max(1, len(depletion_offsets))
    depleted = sorted(offset for offset in depletion_offsets if offset is not None)
    probability_pct = int(round(len(depleted) / n * 100))
    median_year = (start_year + int(depleted[len(depleted) // 2])) if depleted else None
    return probability_pct, median_year


def _run_allocation_monte_carlo(
    *,
    advisory_summary: PortfolioSummary,
    cashflow_projection_series_rappen: list[int],
    goal_inflation_series_bps: list[int],
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    cma: CapitalMarketAssumption,
    goals: list[Goal],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    policy: OptimizerPolicy,
    mandate_id: str,
    simulation_prefs: dict | None,
    start_year: int,
    sub_allocations: list[dict] | None = None,
    target_total_rappen: int | None = None,
    target_start_value_rappen: int | None = None,  # alias from rp-ueberarbeitung
    total_summary: "PortfolioSummary | None" = None,
    total_liabilities_rappen: int = 0,
    external_foundation_projection: dict | None = None,
) -> dict:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import (
        BUCKET_FIELDS,
        _build_cholesky_from_cma,
        _weighted_bucket_metrics,
    )
    from services.portfolio_engine_gesamtvermoegen import (
        _total_financial_target_weights,
    )

    if target_start_value_rappen is not None and target_total_rappen is None:
        target_total_rappen = target_start_value_rappen
    horizon_years = max(1, len(cashflow_projection_series_rappen))
    external_foundation = _coerce_external_foundation_projection(
        external_foundation_projection,
        horizon_years,
    )
    simulations = _monte_carlo_simulations(simulation_prefs)
    stress_multiplier = _simulation_stress_multiplier(simulation_prefs)
    rebalance_mode = _simulation_rebalance_mode(simulation_prefs)
    # Sprint U-P4 Fix M5+M6: Crisis-Korrelations-Mode + Tail-Risk-Cornish-Fisher
    crisis_strength = _simulation_crisis_strength(simulation_prefs)
    use_tail_risk = _simulation_use_tail_risk(simulation_prefs)
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    # 2026-06-17 (User-Fachentscheid): Liquidität wertet in der PROJEKTION NICHT auf
    # (Cash = 0%). mu=0 & sigma=0 -> growth_factor=exp(0)=1.0 -> Liquidität flach im MC.
    # Echte Zinsen laufen nur über den abgeleiteten Zinsertrag-Cashflow (kein Doppelzählen).
    returns = {**returns, "liquidity": 0}
    vols = {**vols, "liquidity": 0}
    chol = _build_cholesky_from_cma(cma, crisis_strength=crisis_strength)
    # Sprint U-P4 Fix M6: Skewness/Kurtosis pro Bucket aus CMA (Cornish-Fisher)
    skew_per_bucket = [
        float(getattr(cma, f"{b}_skewness_bps", 0) or 0) / 10000.0
        for b in BUCKET_FIELDS
    ]
    excess_kurt_per_bucket = [
        float(getattr(cma, f"{b}_excess_kurt_bps", 0) or 0) / 10000.0
        for b in BUCKET_FIELDS
    ]
    log_parameters = [
        arithmetic_moments_to_log_parameters(
            returns[bucket] / 10_000.0,
            vols[bucket] / 10_000.0 * stress_multiplier,
            skew=skew_per_bucket[index],
            excess_kurtosis=excess_kurt_per_bucket[index],
            use_cornish_fisher=use_tail_risk,
        )
        for index, bucket in enumerate(BUCKET_FIELDS)
    ]
    n_assets = len(BUCKET_FIELDS)
    transaction_cost_bps = _simulation_transaction_cost_bps(simulation_prefs)
    target_start_total = int(target_total_rappen if target_total_rappen is not None else advisory_summary.total_rappen)
    target_start_values = _target_bucket_values(target_start_total, targets)
    # C3: Sub-Allocation in den MC-Seed aufnehmen, damit Aenderungen der
    # tatsaechlichen Sub-Verteilung (z.B. EM-Tilt aktiviert) zu einer
    # neuen, deterministisch reproduzierbaren Pfadschar fuehren.
    sub_alloc_signature = json.dumps(
        sorted(
            [
                (
                    str(item.get("asset_class") or ""),
                    str(item.get("sub_asset_class") or ""),
                    int(item.get("target_weight_bps") or 0),
                )
                for item in (sub_allocations or [])
            ]
        ),
        sort_keys=True,
    )
    seed = _monte_carlo_seed(
        mandate_id,
        cma.id,
        horizon_years,
        simulations,
        stress_multiplier,
        rebalance_mode,
        json.dumps(targets, sort_keys=True),
        sub_alloc_signature,
        transaction_cost_bps,
        cma.correlation_matrix_json or "",
    )
    rng = random.Random(seed)

    current_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    target_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    # F23: Total-Vermoegen-Pfade in MC parallel zu advisory. Liabilities werden
    # als initial deficit auf den IST-Total getragen; SOLL-Total bekommt sie
    # bereits beim Start abgezogen. Wenn total_summary fehlt, bleiben die Listen
    # leer und der Caller bekommt [] zurueck.
    total_current_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    total_target_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    total_liabilities_rappen = max(0, int(total_liabilities_rappen or 0))
    if total_summary is not None:
        if external_foundation is not None:
            (
                foundation_property_series,
                foundation_liability_series,
                foundation_pledged_asset_series,
            ) = external_foundation
            total_financial_summary = (
                _total_financial_summary_without_direct_property(
                    total_summary,
                    foundation_property_series[0],
                    BUCKET_FIELDS,
                )
            )
            total_target_start = total_financial_summary.total_rappen
        else:
            foundation_property_series = [0] * (horizon_years + 1)
            foundation_liability_series = [0] * (horizon_years + 1)
            foundation_pledged_asset_series = [0] * (horizon_years + 1)
            total_financial_summary = total_summary
            total_target_start = max(
                0,
                int(total_summary.total_rappen) - total_liabilities_rappen,
            )
        total_target_start_values = _target_bucket_values(
            total_target_start,
            _total_financial_target_weights(targets),
        )
    else:
        foundation_property_series = [0] * (horizon_years + 1)
        foundation_liability_series = [0] * (horizon_years + 1)
        foundation_pledged_asset_series = [0] * (horizon_years + 1)
        total_financial_summary = None
        total_target_start = 0
        total_target_start_values = {key: 0 for key in BUCKET_FIELDS}
    current_annualized_returns: list[int] = []
    target_annualized_returns: list[int] = []
    target_year_one_returns: list[int] = []
    target_year_one_losses: list[int] = []
    target_max_drawdowns: list[int] = []
    # 2026-06-14: IST-Risiko symmetrisch zum SOLL erfassen, damit der Kennzahlen-
    # Vergleich (VaR/CVaR/Drawdown/Verlust-Wkeit/Vola) zweispaltig SOLL vs IST sein kann.
    current_year_one_returns: list[int] = []
    current_year_one_losses: list[int] = []
    current_max_drawdowns: list[int] = []
    # #96 Verzehr/Sequence-of-Returns: pro Pfad der Jahres-Offset der ERSTEN
    # Vermoegens-Erschoepfung (Pfad-Total <= 0) oder None.
    target_depletion_offsets: list[int | None] = []
    current_depletion_offsets: list[int | None] = []

    for _simulation_idx in range(simulations):
        current_values = {key: max(0, int(advisory_summary.amounts_rappen.get(key, 0))) for key in BUCKET_FIELDS}
        target_values = {key: max(0, int(target_start_values.get(key, 0))) for key in BUCKET_FIELDS}
        # W2.5: Lebensluecke pro Simulation als positiver Schuldenstand mitgefuehrt,
        # parallel zur deterministischen _simulate_bucket_path-Logik. Wenn Cashflow
        # mehr Vermoegen abzieht als vorhanden, akkumuliert der Rest hier und macht
        # den Pfad-Total negativ (Vermoegen aufgezehrt).
        current_deficit = 0
        target_deficit = 0
        # Total paths simulate only financial assets when a position-derived
        # foundation is supplied. Direct property and mortgage principal are
        # deterministic additions below, outside CMA and rebalancing.
        if total_summary is not None:
            total_current_values = {
                key: max(
                    0,
                    int(total_financial_summary.amounts_rappen.get(key, 0)),
                )
                for key in BUCKET_FIELDS
            }
            total_target_values = {key: max(0, int(total_target_start_values.get(key, 0))) for key in BUCKET_FIELDS}
            total_current_deficit = (
                0 if external_foundation is not None else total_liabilities_rappen
            )
            total_target_deficit = 0
            total_current_by_year[0].append(
                sum(total_current_values.values())
                - total_current_deficit
                + foundation_property_series[0]
                + foundation_pledged_asset_series[0]
                - foundation_liability_series[0]
            )
            total_target_by_year[0].append(
                sum(total_target_values.values())
                - total_target_deficit
                + foundation_property_series[0]
                + foundation_pledged_asset_series[0]
                - foundation_liability_series[0]
            )
        else:
            total_current_values = None
            total_target_values = None
            total_current_deficit = 0
            total_target_deficit = 0
        current_by_year[0].append(sum(current_values.values()) - current_deficit)
        target_by_year[0].append(sum(target_values.values()) - target_deficit)

        current_start = max(1, sum(current_values.values()))
        target_start = max(1, sum(target_values.values()))
        # #AA-4 (2026-06-12): Marktwert nach Jahr-1-Wachstum, VOR Cashflow —
        # Basis fuer cashflow-bereinigte 1-Jahres-VaR/CVaR/Loss-Prob. Eine
        # Einzahlung ist kein Markt-Gewinn und darf das Verlustrisiko nicht
        # unterschaetzen lassen (bzw. eine Entnahme nicht ueberschaetzen).
        target_year1_market_value: int | None = None
        current_year1_market_value: int | None = None
        # #AA-5 (2026-06-12): time-weighted Rendite (TWR) — geometrische Verkettung
        # der jaehrlichen MARKT-Wachstumsfaktoren (vor Cashflow). Misst die
        # Strategie-Performance unabhaengig vom Ein-/Auszahlungs-Timing; das
        # bisherige money-weighted end/start verzerrte die ausgewiesene Rendite
        # (eine Einzahlung vor einem guten Jahr hob die "CAGR" kuenstlich).
        target_twr_product = 1.0
        current_twr_product = 1.0
        # #AA-10 (2026-07-24): cashflow-neutraler Markt-Index-Pfad fuer Max
        # Drawdown. Vorher lief _max_drawdown_bps ueber target_by_year/
        # current_by_year, die den kumulierten Cashflow-Deficit (Entnahmen)
        # NETTO enthalten -- bei einem Entnahme-Mandat (Verzehrphase) zeigt
        # ein defensives Portfolio dadurch einen "Max Drawdown", der
        # ueberwiegend aus geplanten Ausgaben besteht, nicht aus Marktverlust.
        # CAGR (TWR, #AA-5) und VaR/CVaR/Loss-Prob (Jahr-1-Marktwert, #AA-4)
        # sind bereits cashflow-bereinigt -- Max Drawdown bekam diese
        # Behandlung nie und wird hier nachgezogen: derselbe post/pre-growth-
        # Faktor wie beim TWR wird zu einem eigenen Index-Pfad verkettet, der
        # gleiche Skala wie der Start-Wert hat (Interpretierbarkeit), aber nie
        # durch Entnahmen/Einzahlungen bewegt wird.
        target_market_index = float(target_start)
        current_market_index = float(current_start)
        target_market_path = [target_market_index]
        current_market_path = [current_market_index]

        for year_index, contribution in enumerate(cashflow_projection_series_rappen, start=1):
            target_pre_growth = max(1, sum(target_values.values()))
            current_pre_growth = max(1, sum(current_values.values()))
            # Draw n_assets independent standard normals, then correlate via Cholesky: Z = L * W
            indep = [rng.gauss(0.0, 1.0) for _ in range(n_assets)]
            corr = [sum(chol[i][j] * indep[j] for j in range(i + 1)) for i in range(n_assets)]
            # Sprint U-P4 Fix M6: Cornish-Fisher-Transform fuer Tail-Risk
            if use_tail_risk:
                corr = [
                    float(
                        bounded_cornish_fisher(
                            corr[i],
                            skew_per_bucket[i],
                            excess_kurt_per_bucket[i],
                        )
                    )
                    for i in range(n_assets)
                ]
            for idx, key in enumerate(BUCKET_FIELDS):
                log_location, log_scale = log_parameters[idx]
                growth_factor = math.exp(
                    log_location + log_scale * corr[idx]
                )
                current_values[key] = int(round(max(0, current_values[key]) * growth_factor))
                target_values[key] = int(round(max(0, target_values[key]) * growth_factor))
                if total_current_values is not None:
                    total_current_values[key] = int(round(max(0, total_current_values[key]) * growth_factor))
                    total_target_values[key] = int(round(max(0, total_target_values[key]) * growth_factor))

            target_post_growth = sum(target_values.values())
            current_post_growth = sum(current_values.values())
            # #AA-5: Jahres-Marktfaktor (post-growth / pre-growth, beide VOR Cashflow)
            # geometrisch akkumulieren. Transaktionskosten heben sich im Verhaeltnis
            # auf -> TWR ist brutto-of-Rebalancing-Kosten (Kosten-Drag 2. Ordnung).
            target_twr_product *= target_post_growth / target_pre_growth
            current_twr_product *= current_post_growth / current_pre_growth
            # #AA-10: derselbe Markt-Faktor, aber als eigener Pfad verkettet
            # (statt nur zum Endprodukt) -- fuer den Peak-to-Trough-Drawdown
            # brauchen wir die Zwischenwerte pro Jahr, nicht nur das Ergebnis.
            target_market_index *= target_post_growth / target_pre_growth
            current_market_index *= current_post_growth / current_pre_growth
            target_market_path.append(target_market_index)
            current_market_path.append(current_market_index)
            if year_index == 1:
                # #AA-4: Marktwert nach Wachstum, VOR Cashflow/Rebalancing erfassen.
                target_year1_market_value = target_post_growth
                current_year1_market_value = current_post_growth

            current_deficit += _apply_cashflow_to_bucket_values(current_values, int(contribution or 0))
            target_deficit += _apply_cashflow_to_bucket_values(target_values, int(contribution or 0))
            if total_current_values is not None:
                total_current_deficit += _apply_cashflow_to_bucket_values(total_current_values, int(contribution or 0))
                total_target_deficit += _apply_cashflow_to_bucket_values(total_target_values, int(contribution or 0))

            if rebalance_mode in ("bands", "calendar"):
                target_weights = _weights_from_bucket_values(target_values)
                breached = [
                    key for key in BUCKET_FIELDS
                    if target_weights[key] < int(minimums.get(key, 0)) or target_weights[key] > int(maximums.get(key, 0))
                ]
                if rebalance_mode == "calendar" or breached:
                    target_values, rebal_turnover = _rebalance_bucket_values_to_targets(target_values, targets)
                    if transaction_cost_bps > 0 and rebal_turnover > 0:
                        # Deduct transaction cost from portfolio proportionally across all buckets
                        cost_rappen = int(round(rebal_turnover * transaction_cost_bps / 10000))
                        total_after = max(1, sum(target_values.values()))
                        for key in BUCKET_FIELDS:
                            target_values[key] = max(0, int(round(
                                target_values[key] * (1 - cost_rappen / total_after)
                            )))
                if total_target_values is not None:
                    total_target_weights = _weights_from_bucket_values(total_target_values)
                    total_breached = [
                        key for key in BUCKET_FIELDS
                        if total_target_weights[key] < int(minimums.get(key, 0)) or total_target_weights[key] > int(maximums.get(key, 0))
                    ]
                    if rebalance_mode == "calendar" or total_breached:
                        total_target_values, total_rebal_turnover = _rebalance_bucket_values_to_targets(total_target_values, targets)
                        if transaction_cost_bps > 0 and total_rebal_turnover > 0:
                            cost_rappen = int(round(total_rebal_turnover * transaction_cost_bps / 10000))
                            total_after = max(1, sum(total_target_values.values()))
                            for key in BUCKET_FIELDS:
                                total_target_values[key] = max(0, int(round(
                                    total_target_values[key] * (1 - cost_rappen / total_after)
                                )))

            current_by_year[year_index].append(sum(current_values.values()) - current_deficit)
            target_by_year[year_index].append(sum(target_values.values()) - target_deficit)
            if total_current_values is not None:
                total_current_by_year[year_index].append(
                    sum(total_current_values.values())
                    - total_current_deficit
                    + foundation_property_series[year_index]
                    + foundation_pledged_asset_series[year_index]
                    - foundation_liability_series[year_index]
                )
                total_target_by_year[year_index].append(
                    sum(total_target_values.values())
                    - total_target_deficit
                    + foundation_property_series[year_index]
                    + foundation_pledged_asset_series[year_index]
                    - foundation_liability_series[year_index]
                )

        # Sprint U-P1 Fix C1: Pfad-Indizierung explizit via _simulation_idx
        # statt [-1]. Vorher: target_by_year[1][-1] funktionierte zufaellig
        # (Append-Reihenfolge), aber bricht bei jeder Parallelisierung silent.
        # #AA-5: time-weighted (cashflow-bereinigt) statt money-weighted end/start.
        current_annualized_returns.append(_twr_annualized_bps(current_twr_product, horizon_years))
        target_annualized_returns.append(_twr_annualized_bps(target_twr_product, horizon_years))
        if target_year1_market_value is not None:
            # #AA-4: cashflow-bereinigt — Markt-Rendite (Pre-Cashflow) statt der
            # cashflow-verzerrten target_by_year[1] (Post-Cashflow).
            year_one_return = _return_bps(target_start, target_year1_market_value)
            target_year_one_returns.append(year_one_return)
            target_year_one_losses.append(_loss_bps(target_start, target_year1_market_value))
        target_path = [values[_simulation_idx] for values in target_by_year if values]
        # #AA-10: Max Drawdown auf dem cashflow-neutralen Markt-Index-Pfad, NICHT
        # auf target_path (der enthaelt die Entnahmen/Einzahlungen -- korrekt fuer
        # die Verzehr-Erschoepfung direkt darunter, aber falsch fuer eine reine
        # Marktrisiko-Kennzahl).
        target_max_drawdowns.append(_max_drawdown_bps(target_market_path))
        # #96: erster Jahres-Offset mit aufgezehrtem Vermoegen (Pfad-Total <= 0).
        target_depletion_offsets.append(
            next((offset for offset, value in enumerate(target_path) if value <= 0), None)
        )
        if current_year1_market_value is not None:
            current_year_one_returns.append(_return_bps(current_start, current_year1_market_value))
            current_year_one_losses.append(_loss_bps(current_start, current_year1_market_value))
        current_path = [values[_simulation_idx] for values in current_by_year if values]
        # #AA-10: siehe target_market_path oben -- symmetrisch fuer IST.
        current_max_drawdowns.append(_max_drawdown_bps(current_market_path))
        current_depletion_offsets.append(
            next((offset for offset, value in enumerate(current_path) if value <= 0), None)
        )

    goal_summaries = [
        _monte_carlo_goal_summary(
            goal,
            path_values_by_year=target_by_year,
            total_path_values_by_year=(
                total_target_by_year if total_summary is not None else None
            ),
            annualized_return_samples_bps=target_annualized_returns,
            inflation_series_bps=goal_inflation_series_bps,
            advisory_wealth_rappen=advisory_wealth_rappen,
            total_wealth_rappen=total_wealth_rappen,
            start_year=start_year,
            horizon_years=horizon_years,
            policy=policy,
        )
        for goal in goals
    ]
    current_goal_summaries = [
        _monte_carlo_goal_summary(
            goal,
            path_values_by_year=current_by_year,
            total_path_values_by_year=(
                total_current_by_year if total_summary is not None else None
            ),
            annualized_return_samples_bps=current_annualized_returns,
            inflation_series_bps=goal_inflation_series_bps,
            advisory_wealth_rappen=advisory_wealth_rappen,
            total_wealth_rappen=total_wealth_rappen,
            start_year=start_year,
            horizon_years=horizon_years,
            policy=policy,
        )
        for goal in goals
    ]

    target_terminal_values = target_by_year[-1]
    downside_probability_pct = int(round(sum(1 for value in target_terminal_values if value < target_start_total) / max(1, len(target_terminal_values)) * 100))

    # #96 Verzehr/Sequence-of-Returns-Kennzahl (SOLL + IST).
    target_depletion_probability_pct, target_depletion_median_year = _sequence_of_returns_depletion(
        target_depletion_offsets, start_year
    )
    current_depletion_probability_pct, current_depletion_median_year = _sequence_of_returns_depletion(
        current_depletion_offsets, start_year
    )

    has_total_paths = total_summary is not None and total_current_by_year[0]
    return {
        "simulations": simulations,
        "seed": seed,
        "horizon_years": horizon_years,
        "start_year": start_year,
        "year_labels": [start_year + offset for offset in range(horizon_years + 1)],
        "current_p10_series_rappen": [_percentile(values, 0.10) for values in current_by_year],
        "current_p50_series_rappen": [_percentile(values, 0.50) for values in current_by_year],
        "current_p90_series_rappen": [_percentile(values, 0.90) for values in current_by_year],
        "target_p10_series_rappen": [_percentile(values, 0.10) for values in target_by_year],
        "target_p50_series_rappen": [_percentile(values, 0.50) for values in target_by_year],
        "target_p90_series_rappen": [_percentile(values, 0.90) for values in target_by_year],
        # F23: Total-Vermoegen-Pfade (Gesamtvermoegen, Liabilities mit Lebensluecke).
        # Leer wenn der Aufrufer kein total_summary uebergeben hat.
        "total_current_p10_series_rappen": (
            [_percentile(values, 0.10) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_current_p50_series_rappen": (
            [_percentile(values, 0.50) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_current_p90_series_rappen": (
            [_percentile(values, 0.90) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_target_p10_series_rappen": (
            [_percentile(values, 0.10) for values in total_target_by_year] if has_total_paths else []
        ),
        "total_target_p50_series_rappen": (
            [_percentile(values, 0.50) for values in total_target_by_year] if has_total_paths else []
        ),
        "total_target_p90_series_rappen": (
            [_percentile(values, 0.90) for values in total_target_by_year] if has_total_paths else []
        ),
        "current_annualized_return_p50_bps": _percentile(current_annualized_returns, 0.50),
        "target_annualized_return_p50_bps": _percentile(target_annualized_returns, 0.50),
        # Sprint U-P1 Fix C3: VaR_95 = -(5%-Quantil der Returns), als positive
        # Loss-Zahl (Industriekonvention). Vorher: 95%-Quantil einer auf [0,∞)
        # abgeschnittenen Loss-Verteilung. Bug: wenn <5% der Pfade negativ
        # waren, lieferte das verfaelschte (zu kleine) VaR-Werte, weil viele
        # Loss-Werte exakt 0 waren und das 95%-Quantil somit den Median-Loss
        # statt das echte Tail-Quantil traf.
        "target_var_95_1y_bps": max(0, -_percentile(target_year_one_returns, 0.05)),
        "target_cvar_95_1y_bps": max(0, -_conditional_percentile_average(target_year_one_returns, 0.05, upper_tail=False)),
        "target_loss_probability_1y_pct": int(round(sum(1 for value in target_year_one_returns if value < 0) / max(1, len(target_year_one_returns)) * 100)),
        "target_max_drawdown_p50_bps": _percentile(target_max_drawdowns, 0.50),
        # 2026-06-14: IST-Risiko symmetrisch (gleiche MC-Methodik) fuer den
        # zweispaltigen SOLL-vs-IST-Kennzahlenvergleich im Frontend.
        "current_var_95_1y_bps": max(0, -_percentile(current_year_one_returns, 0.05)),
        "current_cvar_95_1y_bps": max(0, -_conditional_percentile_average(current_year_one_returns, 0.05, upper_tail=False)),
        "current_loss_probability_1y_pct": int(round(sum(1 for value in current_year_one_returns if value < 0) / max(1, len(current_year_one_returns)) * 100)),
        "current_max_drawdown_p50_bps": _percentile(current_max_drawdowns, 0.50),
        "target_volatility_1y_bps": _stddev_bps(target_year_one_returns),
        "current_volatility_1y_bps": _stddev_bps(current_year_one_returns),
        "target_max_drawdown_p95_bps": _percentile(target_max_drawdowns, 0.95),
        "target_downside_probability_pct": downside_probability_pct,
        # #96 Verzehr/Sequence-of-Returns: Anteil Pfade mit aufgezehrtem Vermoegen
        # vor Horizontende + mittleres Erschoepfungsjahr (None = kein Verzehr-Risiko).
        "target_depletion_probability_pct": target_depletion_probability_pct,
        "target_depletion_median_year": target_depletion_median_year,
        "current_depletion_probability_pct": current_depletion_probability_pct,
        "current_depletion_median_year": current_depletion_median_year,
        "goal_summaries": goal_summaries,
        "current_goal_summaries": current_goal_summaries,
    }
