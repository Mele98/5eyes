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
# p5/p50/p75 speisen die Ziel-Klassifikation (Report + PDF). p10/p25/p90
# (REPORT-FAN-CHART-BANDS-001) liefern die zwei SYMMETRISCHEN Faecher-Baender
# des Reports: P10-P90 (zentrale 80 % der Pfade) und P25-P75 (zentrale
# 50 %), konsistent mit den P10/P90-Kennzahlen der App. Das fruehere
# Report-Band p5-p75 war asymmetrisch und deckte nur 70 % ab.
QUANTILES = (5, 10, 25, 50, 75, 90)
_QUANTILE_KEYS = tuple(f"p{q}" for q in QUANTILES)


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
    cma: Any = None,
    death_year_index: int | None = None,
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
    cma
        Optional explizite CMA. Default (None): die in der Soll-Allokation
        verankerte Snapshot-CMA (``resolve_allocation_cma``) -- NIE still die
        global aktuelle CMA (MC-CONTEXT-001).
    death_year_index
        Optionaler Mortalitaets-Cutoff-Index (siehe
        ``report_mc_death_year_index``). None = Feature aus = keine
        Mortalitaets-Transformation, identisch zum Solver (MORT-CHANNEL-001).

    Staleness (Risikoprofil-/Input-Anker) prueft der Aufrufer vorab mit
    ``services.report_projection_gate`` -- siehe
    ``services.advisory_report._build_monte_carlo_paths_section``.

    Returns
    -------
    Stable JSON-Schema:
        {
          "data_pending": False,
          "p5":  [rappen, rappen, ...],   # laenge horizon_years+1
          "p50": [rappen, ...],
          "p75": [rappen, ...],
          "p10"/"p25"/"p90": [rappen, ...],  # Faecher-Baender (Report)
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

    if cma is None:
        cma, cma_note = resolve_allocation_cma(db, ta)
        if cma is None:
            return fail | {"projection_status": "blocked", "note": cma_note}

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
    sub_allocations = _sub_allocations_from_ta(ta)
    return _compute_paths_core(
        initial_wealth_rappen=int(initial_wealth_rappen),
        horizon_years=int(horizon_years),
        weights=weights,
        cma=cma,
        sub_allocations=sub_allocations,
        cashflow_series=cashflow_series,
        n_paths=int(n_paths),
        seed=int(seed),
        death_year_index=death_year_index,
    )


def report_mc_death_year_index(
    offset_years: int | None, *, horizon_years: int,
) -> int | None:
    """MORT-CHANNEL-001: Mortalitaets-Cutoff in Index-Form, exakt nach der
    Solver-Konvention (``services.optimizer.solver``:
    ``np.clip(mortality_fixed_offset_years, 1, horizon_years)``). None bleibt
    None -- Feature aus heisst keine Transformation."""
    if offset_years is None:
        return None
    return int(np.clip(int(offset_years), 1, int(horizon_years)))


def resolve_allocation_cma(db: Session, ta: Any) -> tuple[Any, str]:
    """MC-CONTEXT-001: die CMA, auf der die Soll-Allokation berechnet wurde.

    Frueher lud die Report-MC die global AKTUELLE CMA -- nach einem CMA-
    Update rechnete sie die alten Gewichte also mit neuen Annahmen, ohne
    Hinweis. Jetzt gilt derselbe Snapshot-Anker wie im kanonischen Payload
    (``build_target_payload_from_allocation``):

    * Anker vorhanden -> genau diese CMA; ist sie geloescht/fehlt sie,
      wird blockiert (keine Ersatzannahmen).
    * kein Anker (Altbestand) -> blockiert (Legacy-Quarantaene): eine Kurve
      mit aktuellen Ersatzannahmen saehe wie ein Beleg der Allokation aus,
      ist es aber nicht.

    Rueckgabe ``(cma, "")`` oder ``(None, Berater-Hinweis)``.
    """
    from models.allocation import CapitalMarketAssumption

    cma_id = str(getattr(ta, "capital_market_assumptions_id", "") or "").strip()
    if not cma_id:
        return None, (
            "Die Soll-Allokation ist mit keinen Kapitalmarkt-Annahmen "
            "verankert (Altbestand). Eine Prognose mit aktuellen "
            "Ersatzannahmen waere kein Beleg dieser Strategie. Bitte "
            "Strategie neu berechnen."
        )
    cma = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.id == cma_id,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .first()
    )
    if cma is None:
        return None, (
            "Die von der Soll-Allokation referenzierten Kapitalmarkt-Annahmen "
            "sind nicht mehr verfuegbar; eine Prognose mit Ersatzannahmen ist "
            "unzulaessig. Bitte Strategie neu berechnen."
        )
    return cma, ""


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
        **{key: [] for key in _QUANTILE_KEYS},
        "time_axis": [],
        "n_paths": 0,
        "seed": None,
        "horizon_years": int(horizon_years or 0),
        "initial_wealth_rappen": int(initial_wealth_rappen or 0),
        "note": "",
        # MC-CONTEXT-001: current | stale | blocked | data_pending.
        "projection_status": "data_pending",
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


def _sub_allocations_from_ta(ta) -> list[dict] | None:
    """REP-001 (Codex-Audit 2026-08-25): scenario_inputs_from_cma() akzeptiert
    seit Sprint B1 ein optionales sub_allocations-Argument, um Bucket-Returns/
    -Vols nach den REALEN Sub-Gewichten zu gewichten statt nach dem
    generischen Bucket-Durchschnitt -- _compute_paths_core() gab dieses
    Argument bisher nie weiter. Monte-Carlo-Projektionen ignorierten damit
    jede Sub-Allokations-Tilt-Entscheidung (Themen-Tilts, EM-Uebergewichtung,
    Hedged-vs-unhedged-Wahl etc.) komplett -- unabhaengig vom DB-Backend.

    Fail-soft (Modul-Prinzip, siehe Docstring oben): ein fehlendes oder nicht
    parsebares sub_allocations_json fuehrt NICHT zu data_pending/Crash,
    sondern zum dokumentierten Backwards-Compat-Verhalten von
    scenario_inputs_from_cma() (historische Bucket-Defaults) -- exakt das
    Verhalten von vor diesem Fix, nur noch fuer den (seltenen) Fehlerfall
    statt immer.
    """
    import json

    raw = getattr(ta, "sub_allocations_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("sub_allocations_json auf TargetAllocation %s nicht parsebar.", getattr(ta, "id", "?"))
        return None
    if not isinstance(parsed, list) or not all(isinstance(row, dict) for row in parsed):
        logger.warning("sub_allocations_json auf TargetAllocation %s hat unerwartete Form.", getattr(ta, "id", "?"))
        return None
    return parsed


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
            # REP-003 (Codex-Audit 2026-08-25): das Schema laesst nur
            # "Income"/"Expense" zu (schemas/wealth.py), aber die DB-Spalte
            # selbst hat keinen CHECK-Constraint -- ein unbekannter/legacy
            # Wert wurde bisher als Income gewertet (Vorzeichen still
            # gekippt, Vermoegenstrajektorie zu optimistisch). "Neutral"
            # heisst hier: NICHT mitzaehlen statt zu raten, konsistent mit
            # dem fail-soft-Prinzip dieses Moduls (kein Crash, aber auch
            # kein stillschweigend falsches Vorzeichen).
            logger.warning(
                "Unbekannter cashflow_type %r bei Cashflow %s -- wird bei der "
                "Monte-Carlo-Netto-Cashflow-Berechnung nicht gezaehlt.",
                getattr(cf, "cashflow_type", None), getattr(cf, "id", "?"),
            )
    return [annual_net for _ in range(horizon_years)]


def _sub_allocations_missing_cma_coverage(
    cma: Any, sub_allocations: list[dict],
) -> bool:
    """True nur, wenn mindestens ein sub_allocations-Eintrag eine
    sub_asset_class benennt, fuer die die CMA schlicht KEINE Kennzahl
    besitzt (das einzige Szenario, in dem `_compute_paths_core` fail-soft
    auf Bucket-Defaults zurueckfallen darf, siehe REP-005-Kommentar dort).
    Jede andere Fehlerursache (kaputte Eintraege, asset_class-Mismatch,
    korrupte CMA-Basisdaten) ist NICHT hier abgedeckt -- der Aufrufer laesst
    OptimizerInputError in diesen Faellen bewusst propagieren."""
    from services.portfolio_engine_cma import _sub_asset_class_model_map

    # LIQUIDITY-INSTRUMENT-MODEL-001: Rechen-Abdeckung (inkl. deklarierter
    # Code-Defaults), nicht Evidenz-Abdeckung.
    assumptions = _sub_asset_class_model_map(cma)
    for item in sub_allocations:
        if not isinstance(item, dict):
            continue
        sub_label = str(item.get("sub_asset_class") or "")
        if sub_label and sub_label not in assumptions:
            return True
    return False


def _compute_paths_core(
    *,
    initial_wealth_rappen: int,
    horizon_years: int,
    weights: np.ndarray,
    cma: Any,
    cashflow_series: list[int],
    n_paths: int,
    seed: int,
    sub_allocations: list[dict] | None = None,
    death_year_index: int | None = None,
) -> dict[str, Any]:
    """Reine Engine-Schicht — keine DB-Zugriffe. Direkt testbar.

    ``death_year_index`` (MORT-CHANNEL-001): None = keine Mortalitaets-
    Transformation; sonst fuer alle Pfade identischer Cutoff wie im Solver."""
    from services.optimizer.scenario_engine import (
        build_scenario_paths,
        scenario_inputs_from_cma,
        simulate_wealth_paths,
    )

    try:
        inputs = scenario_inputs_from_cma(cma, sub_allocations)
    except ValueError:
        # REP-005 (Kontrollrunde 2026-09-25): dieser except-Zweig war vorher
        # ein blindes `except ValueError`, das JEDE Fehlerursache aus
        # scenario_inputs_from_cma() identisch behandelte -- inklusive
        # OptimizerInputError, dessen eigener Docstring explizit sagt "must
        # not become a silent fallback". scenario_inputs_from_cma() buendelt
        # darin aber viele voellig unterschiedliche Ursachen in denselben
        # Exception-Typ: eine fehlende Sub-Asset-Class-Abdeckung in der CMA
        # (der einzige Fall, den dieser Fallback tatsaechlich abfedern soll),
        # ABER AUCH echte Datenkorruption (falsch zugeordnete asset_class/
        # sub_asset_class, kaputte Korrelationsmatrix, nicht-endliche
        # CMA-Renditen). Ein Sub-Allocations-Eintrag, der z.B. eine Aktien-
        # Position faelschlich als "Obligationen" deklariert, wurde bisher
        # STILL auf Bucket-Defaults zurueckgestuft statt den Fehler zu
        # melden -- das Risiko-Projektions-Ergebnis waere dadurch fachlich
        # falsch (Aktienrisiko als Obligationen-Risiko gerechnet), ohne dass
        # irgendetwas im Report darauf hinweist. Live reproduziert.
        #
        # Fix: nur noch der eine, tatsaechlich gemeinte Fall (eine benannte
        # Sub-Asset-Class hat schlicht KEINE CMA-Kennzahl) loest den
        # Fail-soft-Rueckfall aus -- explizit VORAB geprueft, nicht aus dem
        # Exception-Typ erraten. Jede andere Ursache (Datenkorruption)
        # propagiert weiterhin hart, wie es OptimizerInputError verlangt.
        if sub_allocations is None or not _sub_allocations_missing_cma_coverage(
            cma, sub_allocations,
        ):
            raise
        logger.warning(
            "sub_allocations enthaelt Sub-Asset-Classes ohne CMA-Abdeckung "
            "(%s) -- Monte-Carlo faellt auf Bucket-Defaults ohne "
            "Sub-Allokations-Gewichtung zurueck.",
            sub_allocations,
        )
        inputs = scenario_inputs_from_cma(cma, None)
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
        death_year_index_per_path=(
            None
            if death_year_index is None
            else np.full(int(n_paths), int(death_year_index), dtype=np.int32)
        ),
    )
    # wealth_paths shape: (n_paths, horizon + 1) — wealth[:, 0] = initial
    pcts = np.percentile(wealth_paths, list(QUANTILES), axis=0)
    # pcts shape: (len(QUANTILES), horizon + 1)

    from services.valuation_clock import valuation_date
    base_year = valuation_date().year  # ADR-1b: gebundener Stichtag
    time_axis = [str(base_year + t) for t in range(horizon_years + 1)]

    return {
        "data_pending": False,
        **{
            key: [int(round(v)) for v in row.tolist()]
            for key, row in zip(_QUANTILE_KEYS, pcts)
        },
        "time_axis": time_axis,
        "n_paths": int(n_paths),
        "seed": int(seed),
        "horizon_years": int(horizon_years),
        "initial_wealth_rappen": int(initial_wealth_rappen),
        "note": "",
    }
