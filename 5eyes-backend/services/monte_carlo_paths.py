"""Sprint U-11 (2026-05-31, Roadmap-Punkt 11): Monte-Carlo Wealth-Pfade
mit Quantilen (p5/p50/p75) fuer Sektion 11 des Advisory-Reports.

Was dieses Modul liefert
------------------------
Eine reine Funktion `compute_quantile_paths()`, die

  Input:  Mandate-DB-Zustand (TA, CMA, Cashflows, Horizont, Wealth)
  Output: stable JSON-Schema mit p5/p50/p75 Wealth-Trajectories
          ueber den Anlagehorizont

Sie konsumiert die bestehende vektorisierte Stochastic-Engine:
  - services.optimizer.scenario_engine.build_scenario_paths
  - services.optimizer.scenario_engine.simulate_wealth_paths
  - services.optimizer.scenario_engine.scenario_inputs_from_cma

und ist Sprint U-18-cache-aware: alle DB-Lookups gehen ueber die in
services.advisory_report definierten _cached_*-Helpers, sodass auch
diese Sektion keine eigenen N+1-Queries erzeugt.

Architektur-Prinzipien
----------------------
* Reine Funktion (kein Service-State). Identisches Input -> identisches
  Output (deterministisch via Seed).
* Fallback `data_pending=True` mit erklaerender Note, wenn TA / CMA /
  Wealth fehlt. UI rendert dann Platzhalter — KEIN Crash.
* Performance-Budget: < 200ms typisch bei n_paths=1000, horizon=15-30
  Jahren (numpy-vektorisiert, antithetic variates).
* Bucket-Reihenfolge = ASIP-Standard ("equities", "bonds",
  "real_estate", "alternatives", "liquidity") — gleich wie Engine.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from models.mandates import Mandate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning-Knobs
# ---------------------------------------------------------------------------

# Fuer institutionelle Reports reichen 1000 Pfade fuer stabile p5/p50/p75
# Quantile (CI breite ~ 1/sqrt(n)). Bei Performance-Problemen: auf 500
# reduzieren — Confidence-Bands bleiben aussagekraeftig.
DEFAULT_N_PATHS = 1000

# Deterministischer Seed: gleiche Eingabe -> gleiches Ergebnis. Wir nutzen
# eine feste Konstante (nicht hash(mandate.id)) damit zwei Aufrufe auf dem
# SELBEN Mandat in derselben Session identisch sind, was die UI zwischen
# zwei Sektion-Refreshes konsistent haelt.
DEFAULT_SEED = 0x1AD51_ADD15  # nicht-trivial, aber deterministisch

# Quantile, die wir liefern. Reihenfolge bestimmt den Output-Key.
QUANTILES = (5, 50, 75)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_quantile_paths(
    db: Session,
    mandate: Mandate,
    *,
    initial_wealth_rappen: int,
    horizon_years: int,
    n_paths: int = DEFAULT_N_PATHS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Berechnet Monte-Carlo Wealth-Pfade mit Quantilen.

    Parameter
    ---------
    db
        SQLAlchemy-Session. Wird genutzt um TA + CMA zu laden (Cache-aware).
    mandate
        ORM-Mandate-Instanz. mandate.client_id wird zum Cashflow-Lookup
        verwendet.
    initial_wealth_rappen
        Start-Vermoegen (Beratungsvermoegen) zum Pfad-Beginn. Wenn 0 oder
        negativ: `data_pending=True`.
    horizon_years
        Anlagehorizont in Jahren. Wenn <=0: `data_pending=True`.
    n_paths
        Anzahl MC-Pfade. Default 1000 — Trade-off Stabilitaet vs Latenz.
    seed
        PCG64-Seed fuer Reproduzierbarkeit. Default DEFAULT_SEED.

    Returns
    -------
    Stable JSON-Schema:
        {
          "data_pending": False,
          "p5":  [rappen, rappen, ...],   # laenge horizon_years+1
          "p50": [rappen, ...],
          "p75": [rappen, ...],
          "time_axis": ["2026", "2027", ..., "2041"],
          "n_paths": 1000,
          "seed": 0x1AD51ADD15,
          "horizon_years": 15,
          "initial_wealth_rappen": 50_000_000,
          "note": ""
        }
    oder bei fehlenden Daten:
        {
          "data_pending": True,
          "note": "Konkreter Grund...",
          ...andere Felder ggf. None oder []
        }
    """
    fail = _data_pending_response(horizon_years, initial_wealth_rappen)
    if initial_wealth_rappen is None or initial_wealth_rappen <= 0:
        return fail | {
            "note": (
                "Kein Beratungsvermoegen erfasst — Monte-Carlo-Pfade "
                "koennen nicht berechnet werden."
            ),
        }
    if horizon_years is None or horizon_years <= 0:
        return fail | {
            "note": (
                "Anlagehorizont nicht definiert — Monte-Carlo-Pfade "
                "koennen nicht berechnet werden."
            ),
        }

    ta = _load_current_ta(db, mandate)
    if ta is None:
        return fail | {
            "note": (
                "Keine aktuelle Anlagestrategie hinterlegt — bitte zuerst "
                "die Soll-Allokation berechnen und freigeben."
            ),
        }

    cma = _load_current_cma(db)
    if cma is None:
        return fail | {
            "note": (
                "Keine Kapitalmarkt-Annahmen hinterlegt — bitte zuerst "
                "im Admin-Bereich die CMA setzen."
            ),
        }

    weights = _weights_from_ta(ta)
    if not np.isclose(weights.sum(), 1.0, atol=0.01):
        # Defekte TA — sollte durch FIDLEG-Validation verhindert sein,
        # aber wir kapseln hier defensiv.
        return fail | {
            "note": (
                "Anlagestrategie ist nicht vollstaendig (Summe der "
                "Bucket-Gewichte != 100%)."
            ),
        }

    cashflow_series = _annual_cashflow_series(db, mandate, horizon_years)
    return _compute_paths_core(
        initial_wealth_rappen=int(initial_wealth_rappen),
        horizon_years=int(horizon_years),
        weights=weights,
        cma=cma,
        cashflow_series=cashflow_series,
        n_paths=int(n_paths),
        seed=int(seed),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _data_pending_response(
    horizon_years: int | None,
    initial_wealth_rappen: int | None,
) -> dict[str, Any]:
    """Liefert das stabile Fallback-Schema. Caller setzt nur `note`."""
    return {
        "data_pending": True,
        "p5": [],
        "p50": [],
        "p75": [],
        "time_axis": [],
        "n_paths": 0,
        "seed": None,
        "horizon_years": int(horizon_years or 0),
        "initial_wealth_rappen": int(initial_wealth_rappen or 0),
        "note": "",
    }


def _load_current_ta(db: Session, mandate: Mandate) -> Any:
    """U-18-cache-aware Lookup der aktuellen TA."""
    try:
        from services.advisory_report import _cached_current_ta
        return _cached_current_ta(db, mandate)
    except ImportError:
        # Defensive fallback wenn Modul-Reihenfolge gestoert ist
        from models.allocation import TargetAllocation
        return (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_current == 1,
                TargetAllocation.deleted_at.is_(None),
            )
            .first()
        )


def _load_current_cma(db: Session) -> Any:
    """Lookup der aktuellen Capital Market Assumption.

    CMA ist global (nicht per-Mandat), daher nicht im Aggregator-Cache.
    Wir cachen sie pro compute()-Aufruf via db.info — wenn keine
    Aggregator-Session aktiv ist, faellt die Query direkt durch.
    """
    from models.allocation import CapitalMarketAssumption

    # Cache-aware: wenn der Aggregator-Cache aktiv ist, dort einhaengen.
    cache = db.info.get("_advisory_aggregator_call_cache")
    if cache is not None and "current_cma" in cache:
        return cache["current_cma"]

    cma = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .first()
    )
    if cache is not None:
        cache["current_cma"] = cma
    return cma


def _weights_from_ta(ta) -> np.ndarray:
    """Extract weights in BUCKET_ORDER aus TargetAllocation.

    BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
    """
    raw = np.array([
        float(getattr(ta, "target_equities_bps", 0) or 0),
        float(getattr(ta, "target_bonds_bps", 0) or 0),
        float(getattr(ta, "target_real_estate_bps", 0) or 0),
        float(getattr(ta, "target_alternatives_bps", 0) or 0),
        float(getattr(ta, "target_liquidity_bps", 0) or 0),
    ], dtype=np.float64) / 10_000.0
    return raw


def _annual_cashflow_series(
    db: Session, mandate: Mandate, horizon_years: int
) -> list[int]:
    """Net-Cashflow pro Jahr in Rappen (Income - Expense), gehalten konstant
    ueber den Horizont.

    V1-Annahme: aktuelle Cashflow-Run-Rate. Inflation + Cashflow-Aenderungen
    werden in einem Folge-Sprint dazukommen (heute aus Scope).
    """
    try:
        from services.advisory_report import _cached_active_cashflows
        cfs = _cached_active_cashflows(db, str(getattr(mandate, "client_id", "") or ""))
    except ImportError:
        cfs = []

    annual_net = 0
    for cf in cfs:
        amount = int(getattr(cf, "amount_rappen", 0) or 0)
        if amount == 0:
            continue
        freq = str(getattr(cf, "frequency", "") or "").lower()
        if "monat" in freq:
            amount *= 12
        elif "quartal" in freq:
            amount *= 4
        cf_type = str(getattr(cf, "cashflow_type", "") or "").lower()
        if "income" in cf_type:
            annual_net += amount
        elif "expense" in cf_type:
            annual_net -= amount
        else:
            annual_net += amount  # unbekannt: neutral als positiv werten
    return [annual_net for _ in range(horizon_years)]


def _compute_paths_core(
    *,
    initial_wealth_rappen: int,
    horizon_years: int,
    weights: np.ndarray,
    cma: Any,
    cashflow_series: list[int],
    n_paths: int,
    seed: int,
) -> dict[str, Any]:
    """Reine Engine-Schicht — keine DB-Zugriffe. Direkt testbar."""
    from services.optimizer.scenario_engine import (
        build_scenario_paths,
        scenario_inputs_from_cma,
        simulate_wealth_paths,
    )

    inputs = scenario_inputs_from_cma(cma)
    return_paths = build_scenario_paths(
        inputs,
        horizon_years=horizon_years,
        n_paths=n_paths,
        seed=seed,
        antithetic=True,
    )
    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=initial_wealth_rappen,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=cashflow_series,
    )
    # wealth_paths shape: (n_paths, horizon + 1) — wealth[:, 0] = initial
    pcts = np.percentile(wealth_paths, list(QUANTILES), axis=0)
    # pcts shape: (len(QUANTILES), horizon + 1)
    p5, p50, p75 = pcts[0], pcts[1], pcts[2]

    from datetime import date
    base_year = date.today().year
    time_axis = [str(base_year + t) for t in range(horizon_years + 1)]

    return {
        "data_pending": False,
        "p5": [int(round(v)) for v in p5.tolist()],
        "p50": [int(round(v)) for v in p50.tolist()],
        "p75": [int(round(v)) for v in p75.tolist()],
        "time_axis": time_axis,
        "n_paths": int(n_paths),
        "seed": int(seed),
        "horizon_years": int(horizon_years),
        "initial_wealth_rappen": int(initial_wealth_rappen),
        "note": "",
    }
