"""Optimizer-Integration — extrahiert aus ``services/portfolio_engine.py``.

ADR-014 (`docs/adr/ADR-014-engine-module-split-plan.md`), Schritt 6 von 8
("Optimizer-Integration"). Anders als die Cluster 1-5 ist dies laut ADR-014
KEIN urspruenglicher Plan-Kandidat, sondern ein 7. Cluster, den der ADR-014-
Autor beim Durchlesen der Datei entdeckt hat: die 14 Funktionen unten bilden
die Bruecke zwischen den Payload-Bau-Orchestratoren (`generate_target_
allocation`, `evaluate_goal_sensitivity` — beide bleiben in
`portfolio_engine.py`) und `services.optimizer.*` (Solver, Constraints,
Objective, Scenario-Engine).

**0 Zeilen Fachlogik-Aenderung** — jede Funktion ist eine byte-fuer-byte-
Kopie ihrer vormaligen Definition in `services/portfolio_engine.py`
(vormals Zeilen 2884-3751, Stand vor dieser Extraktion, direkt nach den
bereits angewandten Schritten 1-5 [Gesamtvermoegen, Live-Rebalancing, CMA,
Reserve, MC-Simulation]). Die einzigen Text-Aenderungen sind rein
infrastrukturelle Lazy-Import-Zeilen (siehe Zirkular-Import-Abschnitt
unten) — kein Bit der eigentlichen Logik wurde veraendert.

**Kontiguitaets-Scan-Befund (Lektion aus dem MC-Simulation-Beinahe-Fehler):**
ein vollstaendiger `def`-Scan ueber die GESAMTE Spanne Zeile 2884 bis
Zeile 3751 (Beginn der ersten Zielfunktion bis Ende der letzten) ergab
GENAU die 14 unten aufgefuehrten Funktionen, in exakt dieser Reihenfolge,
OHNE jede fremde Funktion dazwischen. Der Cluster ist also — anders als der
MC-Simulation-Cluster — bereits im Original vollstaendig kontiguierlich;
kein Risiko einer versehentlichen Mitloeschung fremder Funktionen. Zwischen
den Zielfunktionen liegen ausschliesslich modul-lokale Konstanten, die als
Teil desselben Clusters ebenfalls mitverschoben wurden (siehe unten).

Extrahierte Funktionen (in Original-Reihenfolge, mit den beiden
mitverschobenen Konstantenbloecken):
    _assessment_score_x10
    _CONVERGED_OPTIMIZER_STATUSES (Konstante, mitverschoben)
    _optimizer_status_is_converged
    _build_tax_solver_kwargs
    _run_stochastic_optimizer_pass
    _optimizer_audit_fields
    _driving_goal_id_from_achievability
    _COMPARISON_BUCKETS, _COMPARISON_MATERIAL_DELTA_BPS (Konstanten, mitverschoben)
    _weights_from_targets
    _objective_to_milli
    _allocation_comparison_note
    _build_allocation_method_comparison
    _build_shadow_comparison_with_evaluations
    _build_shadow_optimization_payload
    _build_optimizer_explainability
    _persist_optimizer_run

Exhaustive Grep-Verifikation (Task-Report enthaelt die vollstaendigen
Fundstellen): es gibt fuer diesen Cluster KEINEN echten externen (Nicht-
Test-)Konsumenten ausserhalb von `portfolio_engine.py` selbst — weder in
`routers/*.py` noch in `services/*.py` (inkl. `services/optimizer/*.py` und
`services/optimizer/scenario_engine.py`) noch in den 5 bereits extrahierten
Schwester-Modulen. Der einzige Treffer in `models/allocation.py` ist ein
Docstring-Kommentar (`"Persistenz-Trigger (siehe portfolio_engine.
_persist_optimizer_run)"`), kein Import/Aufruf. Alle echten internen
Aufrufe liegen — wie vom ADR vorausgesagt — ausschliesslich innerhalb der
beiden Orchestratoren `generate_target_allocation` (Zeilen 4025-4698) und
`evaluate_goal_sensitivity` (Zeilen 4698-4898), die beide in
`portfolio_engine.py` bleiben und diese Helfer direkt aufrufen. Test-Dateien
(`test_tax_solver_wiring.py`, `test_shadow_comparison_aggregator.py`,
`test_shadow_stochastic_persistence.py`, `test_optimizer_runs.py`,
`test_optimizer_shadow_mode.py`, `test_chance_constraint.py`,
`test_risk_budget_cap.py`) importieren teils direkt beim Namen — bleiben
dank Re-Export in `portfolio_engine.py` unveraendert funktionsfaehig.

**Zirkular-Import-Haertung (identisches Muster zu den Schritten 1-5):**
CORE-Namen, die noch physisch in `services.portfolio_engine` leben und von
Funktionen hier zur LAUFZEIT gebraucht werden (`logger`,
`_OPTIMIZER_N_PATHS_DEFAULT`, `_OPTIMIZER_OBJECTIVE_MILLI_CAP`,
`BUCKET_FIELDS`), werden bewusst NICHT auf Modul-Ebene importiert, sondern
lazy (funktionslokal) innerhalb jeder Funktion, die sie tatsaechlich
braucht — aus demselben Grund wie in den Schritten 1-5: `portfolio_engine.py`
re-exportiert am Dateiende die Namen aus diesem Modul; ein Modul-Ebene-
Import in umgekehrter Richtung koennte bei einem Import-Einstieg ueber
DIESES Modul zu einem ImportError auf einem partiell initialisierten
`portfolio_engine`-Modul fuehren. Die bereits im Original vorhandenen
Lazy-Imports von `services.tax.registry`, `services.tax.overrides`,
`services.optimizer.constraints`, `services.optimizer.solver`,
`services.optimizer.objective` und `services.optimizer.scenario_engine`
(inkl. der try/except-ImportError-Fallbacks) wurden UNVERAENDERT als
funktionslokale Lazy-Imports uebernommen — sie sind bereits im Original so
geschrieben und wurden nicht auf Modul-Ebene "hochgezogen".

Echte externe Abhaengigkeiten ohne Zirkularitaetsrisiko (verifiziert per
Grep: keiner der Ziel-Module importiert `services.portfolio_engine` oder
`services.portfolio_engine_optimizer_integration`) werden ganz normal auf
Modul-Ebene importiert, exakt wie im Original: `sqlalchemy.orm.Session`,
`database.new_uuid`, `models.allocation.OptimizerRun`,
`services.allocation_messages.classify_messages`,
`services.risk_matrix.classify_limiting_factor` und
`services.risk_matrix.compute_portfolio_risky_fraction_bps`. Keine
Modell-Typ-Annotationen erfordern einen `TYPE_CHECKING`-Block: alle
Funktionssignaturen in diesem Cluster nutzen ausschliesslich Builtin-Typen
(`str`, `int`, `float`, `dict`, `list`, `tuple`) bzw. ungetypte Parameter
(`mandate`, `cma`, `house_matrix`, `assessment`, `optimizer_result`, ...),
sodass `Session` und `OptimizerRun` die einzigen "echten" Imports sind (beide
sowohl fuer Typ-Annotation als auch fuer echten Laufzeit-Gebrauch —
`db.add(...)` bzw. Konstruktion `OptimizerRun(...)` — benoetigt).

Byte-fuer-byte-Verifikation: ein Diff-Skript hat jede extrahierte
Funktionssignatur + Funktionskoerper (exklusive der hier neu eingefuegten
Lazy-Import-Zeilen) gegen den Original-Text in `portfolio_engine.py`
verglichen — 0 Abweichungen (siehe Task-Report).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import OptimizerRun
from services.allocation_messages import classify_messages
from services.risk_matrix import (
    classify_limiting_factor,
    compute_portfolio_risky_fraction_bps,
)


def _assessment_score_x10(assessment) -> int:
    """0-100 Score-Wert aus Assessment, konsistent zu _risk_score_bucket-Logik."""
    raw = (
        assessment.override_score_x10
        if getattr(assessment, "is_overridden", 0) and assessment.override_score_x10 is not None
        else getattr(assessment, "final_score_x10", None)
    )
    if raw is None:
        raw = 10
    return max(0, min(100, int(raw)))


_CONVERGED_OPTIMIZER_STATUSES = {
    "converged",
    "converged_robustified",
    "converged_with_soft_tau",
}


def _optimizer_status_is_converged(status: str | None) -> bool:
    return str(status or "").strip() in _CONVERGED_OPTIMIZER_STATUSES


def _build_tax_solver_kwargs(mandate) -> dict:
    """Baut die tax-*-kwargs fuer run_solver aus dem Mandat (Sprint U-P2 Fix C9).

    Leeres Dict, wenn keine tax_jurisdiction gesetzt ist ODER beim Laden ein
    Fehler auftritt (fail-soft: der Solver laeuft dann tax-naiv statt zu crashen).
    Bewusst extrahiert, damit die Wiring (tax_regime erreicht run_solver) direkt
    testbar ist und ein Re-Break (#39/46) nicht erneut still durchrutscht.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import logger

    tax_kwargs: dict = {}
    try:
        jurisdiction = str(getattr(mandate, "tax_jurisdiction", "") or "").strip()
        if not jurisdiction:
            return tax_kwargs
        from services.tax.registry import resolve_regime_class
        regime_cls = resolve_regime_class(jurisdiction)
        tax_overrides_json = getattr(mandate, "tax_overrides_json", None)
        # TAX-1: Bei region-spezifischer ID (z.B. 'CH-GE') die Kanton-Factory nutzen —
        # sonst liefert regime_cls() nur den Landes-Pauschalwert (CH 40 statt GE 85 bps).
        # Unbekannte Region -> Basis-Regime (kein Crash).
        region = jurisdiction.split("-", 1)[1].strip() if "-" in jurisdiction else ""
        if region and hasattr(regime_cls, "for_canton"):
            try:
                regime_instance = regime_cls.for_canton(region)
            except (ValueError, KeyError) as region_exc:
                logger.warning(
                    "Unbekannte Tax-Region '%s' (%s) — nutze Basis-Regime",
                    jurisdiction, region_exc,
                )
                regime_instance = regime_cls()
        else:
            regime_instance = regime_cls()
        if tax_overrides_json:
            from services.tax.overrides import apply_overrides
            regime_instance = apply_overrides(regime_instance, tax_overrides_json)
        tax_kwargs["tax_regime"] = regime_instance
        # TAX-2: 'valid_from_year' existiert NICHT auf dem Mandat-Model (frueher:
        # getattr-Default 0 -> current_year hartcodiert 2026). Echtes Bewertungsjahr
        # aus opened_at (ISO 'YYYY-MM-DD'), sonst aktuelles Kalenderjahr.
        opened = str(getattr(mandate, "opened_at", "") or "").strip()
        if len(opened) >= 4 and opened[:4].isdigit():
            current_year = int(opened[:4])
        else:
            from datetime import date as _date
            current_year = _date.today().year
        tax_kwargs["base_calendar_year"] = current_year
        cby = int(getattr(mandate, "client_birth_year", 0) or 0)
        if cby:
            tax_kwargs["mandate_age_at_start"] = max(0, current_year - cby)
        retirement_year = int(getattr(mandate, "retirement_year", 0) or 0)
        if retirement_year and current_year >= retirement_year:
            tax_kwargs["is_retired"] = True
    except Exception as exc:  # noqa: BLE001 - tax loading darf Solver nicht killen
        logger.warning("Tax-Regime nicht ladbar (%s) — Solver laeuft tax-naiv", exc)
        return {}
    return tax_kwargs


def _run_stochastic_optimizer_pass(
    *,
    optimizer_mode: str,
    apply_targets: bool,
    cma,
    goals: list,
    house_matrix,
    assessment,
    advisory_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int],
    targets: dict[str, int],  # mutable: wird in-place ueberschrieben nur wenn apply_targets
    minimums: dict[str, int],
    maximums: dict[str, int],
    reasoning: list[str],
    building_blocks_rows: list | None = None,
    mandate=None,  # Sprint 4 Phase 3: fuer BFS-Mortalitaets-Sampling
):
    """Solver in Shadow- oder Stochastic-Modus aufrufen.

    optimizer_mode 'stochastic'        -> apply_targets=True: bei converged
                                          werden targets in-place ueberschrieben.
    optimizer_mode 'shadow_stochastic' -> apply_targets=False: Solver laeuft fuer
                                          Methodenvergleich, House-Matrix bleibt
                                          aktive Allokation.
    Andere Modi -> None.

    Returns OptimizerResult oder None (wenn Modus nicht relevant oder Solver
    crashed). Bei diverged/fallback bleibt House-Matrix-Default unabhaengig
    vom Modus.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _OPTIMIZER_N_PATHS_DEFAULT, logger

    if optimizer_mode not in {"stochastic", "shadow_stochastic"}:
        # Sprint U-P0 Fix H8: 'iterative' wird im Validator akzeptiert, aber
        # hier nicht gehandhabt → silent fallback auf house_matrix. Warne
        # damit User merkt dass kein Solver lief.
        if optimizer_mode == "iterative":
            logger.warning(
                "OPTIMIZER_MODE='iterative' ist reservierter Legacy-Wert ohne "
                "eigenen Solver-Pfad. Faellt auf 'house_matrix' zurueck."
            )
        return None

    try:
        from services.optimizer.constraints import (
            bucket_risky_fractions_from_building_blocks,
        )
        from services.optimizer.solver import run_solver
    except ImportError as exc:
        logger.warning("Stochastic optimizer module not importable: %s", exc)
        reasoning.append(
            "Stochastic Optimizer-Modul nicht verfuegbar — House-Matrix-Default bleibt."
        )
        return None

    score_x10 = _assessment_score_x10(assessment)
    horizon = max(10, int(len(cashflow_projection_series_rappen) or 10))
    # Phase 5.1: Risky-Fractions aus BuildingBlock-DB statt fester Defaults.
    # Genauer pro Mandant weil unterschiedliche Policies unterschiedliche
    # Sub-Asset-Klassen-Werte haben koennen (z.B. EM-Aktien ein/aus).
    rf_per_bucket = None
    if building_blocks_rows is not None:
        try:
            rf_per_bucket = bucket_risky_fractions_from_building_blocks(building_blocks_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risky-fraction extraction failed: %s", exc)
            rf_per_bucket = None

    # Sprint 4 Phase 3: Mortalitaets-Felder aus Mandate-Objekt extrahieren
    mortality_kwargs = {}
    if mandate is not None:
        cby = getattr(mandate, "client_birth_year", None)
        csex = getattr(mandate, "client_sex", None)
        ums = bool(getattr(mandate, "use_mortality_simulation", 0))
        if ums and cby and csex in ("M", "F"):
            mortality_kwargs = {
                "client_birth_year": int(cby),
                "client_sex": str(csex),
                "use_mortality_simulation": True,
            }

    # Sprint U-P2 Fix C9: tax-aware Solver — wenn das Mandat eine
    # tax_jurisdiction hat, wird das passende TaxRegime aufgeloest und
    # an run_solver durchgereicht. Backwards-Compat: kein Feld → None
    # → simulate_wealth_paths laeuft tax-naiv (wie vorher).
    tax_kwargs = _build_tax_solver_kwargs(mandate)

    try:
        t0 = time.perf_counter()
        result = run_solver(
            cma=cma,
            goals=list(goals),
            house_matrix_row=house_matrix,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            horizon_years=horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=rf_per_bucket,
            max_risky_fraction_bps=int(house_matrix.max_risky_fraction_bps),
            **mortality_kwargs,
            **tax_kwargs,
        )
        elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
        object.__setattr__(result, "elapsed_ms", elapsed_ms)
    except Exception as exc:  # noqa: BLE001 - never crash allocation flow
        logger.warning("Stochastic optimizer crashed: %s", exc, exc_info=True)
        reasoning.append(
            f"Stochastic Optimizer Fehler ({type(exc).__name__}) — "
            "House-Matrix-Default bleibt aktiv."
        )
        return None

    if _optimizer_status_is_converged(result.status):
        if apply_targets:
            # In-place: ersetze House-Matrix-Default-Targets mit Solver-Output.
            # Bands (minimums/maximums) bleiben unveraendert, weil Solver sie
            # respektiert hat.
            for bucket, bps in result.weights_bps.items():
                targets[bucket] = int(bps)
            if result.status == "converged_robustified":
                reasoning.append(
                    f"Stochastic Optimizer (Mulvey-light, {result.n_starts_attempted} "
                    f"Multi-Starts, {result.iterations} Iter): mit Stage-9-"
                    "Robustifizierung konvergiert und als Zielallokation angewendet."
                )
            else:
                reasoning.append(
                    f"Stochastic Optimizer (Mulvey-light, {result.n_starts_attempted} "
                    f"Multi-Starts, {result.iterations} Iter): konvergiert und als "
                    "Zielallokation angewendet."
                )
        else:
            suffix = (
                "mit Stage-9-Robustifizierung konvergiert"
                if result.status == "converged_robustified"
                else "konvergiert"
            )
            reasoning.append(
                f"Shadow-Stochastic Optimizer (Mulvey-light, {result.n_starts_attempted} "
                f"Multi-Starts, {result.iterations} Iter): {suffix}; "
                "House-Matrix bleibt aktive Zielallokation."
            )
        if result.reasoning:
            reasoning.append(result.reasoning[0])
    else:
        reasoning.append(
            f"Stochastic Optimizer Status='{result.status}'. "
            "House-Matrix-Default bleibt aktiv."
        )

    return result


def _optimizer_audit_fields(optimizer_result) -> dict:
    """Extrahiert die Audit-Anchor-Felder fuer TargetAllocation. Returns {} wenn None."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _OPTIMIZER_OBJECTIVE_MILLI_CAP

    if optimizer_result is None:
        return {}
    obj_milli_raw = optimizer_result.objective_value
    if obj_milli_raw == float("inf") or obj_milli_raw != obj_milli_raw:  # NaN check
        obj_milli = None
    else:
        scaled = obj_milli_raw * 1000.0
        if scaled > _OPTIMIZER_OBJECTIVE_MILLI_CAP:
            obj_milli = _OPTIMIZER_OBJECTIVE_MILLI_CAP
        elif scaled < -_OPTIMIZER_OBJECTIVE_MILLI_CAP:
            obj_milli = -_OPTIMIZER_OBJECTIVE_MILLI_CAP
        else:
            obj_milli = int(round(scaled))
    return {
        "optimization_method": optimizer_result.method,
        "optimization_objective_value_milli": obj_milli,
        "optimization_iterations": int(optimizer_result.iterations or 0),
        "optimization_seed": int(optimizer_result.seed or 0),
        "optimization_status": optimizer_result.status,
    }


def _driving_goal_id_from_achievability(achievability: list[dict]) -> str | None:
    priority = [
        row for row in (achievability or [])
        if str(row.get("hardness") or "").strip().lower() in ("hart", "primär", "primaer")
    ]
    if not priority:
        return None
    status_rank = {"nicht_erreichbar": 0, "knapp": 1, "erreichbar": 2}
    row = sorted(
        priority,
        key=lambda item: (
            status_rank.get(str(item.get("status") or ""), 3),
            float(item.get("probability") or 0.0),
        ),
    )[0]
    return str(row.get("goal_id") or "") or None


# --------------------------------------------------------------------------- #
# V3 Sprint 1 (2026-05-08): Methodenvergleich House Matrix vs. Shadow Stochastic
# --------------------------------------------------------------------------- #
_COMPARISON_BUCKETS: tuple[str, ...] = (
    "equities", "bonds", "real_estate", "alternatives", "liquidity",
)
_COMPARISON_MATERIAL_DELTA_BPS: int = 100  # 1 Prozentpunkt = 100 bps


def _weights_from_targets(targets: dict[str, int]) -> dict[str, int]:
    """Extrahiert die fuenf Bucket-Gewichte als bps-int Dict (clamped >= 0)."""
    return {bucket: int(targets.get(bucket, 0) or 0) for bucket in _COMPARISON_BUCKETS}


def _objective_to_milli(value: float | None) -> int | None:
    """Skaliert objective_value (Float) auf int milli mit Cap (matched _optimizer_audit_fields)."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _OPTIMIZER_OBJECTIVE_MILLI_CAP

    if value is None:
        return None
    if value == float("inf") or value == float("-inf") or value != value:  # NaN check
        return None
    scaled = value * 1000.0
    capped = max(-_OPTIMIZER_OBJECTIVE_MILLI_CAP, min(_OPTIMIZER_OBJECTIVE_MILLI_CAP, scaled))
    return int(round(capped))


def _allocation_comparison_note(
    deltas: dict[str, int],
    status: str,
    objective_delta_pct: float | None,
) -> str:
    """Beratungstauglicher Hinweis ohne Marketing-Sprache (V3 §10.5)."""
    if not _optimizer_status_is_converged(status):
        return (
            "Der Shadow-Optimizer konvergierte nicht stabil; "
            "House-Matrix bleibt die relevante Empfehlung."
        )
    if status == "converged_robustified":
        return (
            "Der Shadow-Optimizer wurde mit erweiterter numerischer Prüfung "
            "abgeschlossen; House-Matrix bleibt bis zum Owner-Entscheid die "
            "aktive Empfehlung."
        )
    material = {k: v for k, v in deltas.items() if abs(int(v or 0)) >= _COMPARISON_MATERIAL_DELTA_BPS}
    if not material:
        return (
            "Der Shadow-Optimizer bestaetigt die aktive Allokation weitgehend; "
            "keine wesentliche Abweichung."
        )
    largest_bucket, largest_delta = max(material.items(), key=lambda item: abs(int(item[1] or 0)))
    direction = "hoeher" if int(largest_delta) > 0 else "tiefer"
    obj_text = ""
    if objective_delta_pct is not None:
        obj_text = f" Objective-Delta: {objective_delta_pct:+.2f}%."
    return (
        f"Der Shadow-Optimizer wuerde {largest_bucket} um "
        f"{abs(int(largest_delta)) / 100:.1f} Prozentpunkte {direction} gewichten."
        f"{obj_text}"
    )


def _build_allocation_method_comparison(
    *,
    optimizer_mode: str,
    active_method: str,
    active_weights_bps: dict[str, int],
    optimizer_result,
    active_evaluation=None,
    shadow_evaluation=None,
) -> dict | None:
    """V3 Sprint 1: Methodenvergleich nur im Shadow-Modus.

    Sprint 1 (heute): Gewichte + Deltas + Beratungsnote. Objective-Delta nur,
    wenn Apples-to-Apples (active_evaluation und shadow_evaluation gesetzt).
    Sprint 1b (Plan §5.6, Commit 3): active/shadow unter demselben Context
    bewerten und beide Evaluations uebergeben.
    """
    if optimizer_mode != "shadow_stochastic" or optimizer_result is None:
        return None

    shadow_weights = {
        bucket: int((optimizer_result.weights_bps or {}).get(bucket, 0) or 0)
        for bucket in _COMPARISON_BUCKETS
    }
    deltas = {
        bucket: shadow_weights[bucket] - int(active_weights_bps.get(bucket, 0) or 0)
        for bucket in _COMPARISON_BUCKETS
    }

    objective_delta_pct: float | None = None
    objective_milli_active: int | None = None
    objective_milli_shadow: int | None = None
    if active_evaluation is not None:
        objective_milli_active = _objective_to_milli(float(active_evaluation.objective_value))
    if shadow_evaluation is not None:
        objective_milli_shadow = _objective_to_milli(float(shadow_evaluation.objective_value))
    elif optimizer_result is not None:
        # Sprint 1 Fallback: kein Shadow-Eval, aber Solver-eigener Wert.
        # NICHT Apples-to-Apples vergleichbar; objective_delta_pct bleibt None.
        objective_milli_shadow = _objective_to_milli(getattr(optimizer_result, "objective_value", None))
    if active_evaluation is not None and shadow_evaluation is not None:
        active_obj = float(active_evaluation.objective_value)
        shadow_obj = float(shadow_evaluation.objective_value)
        if active_obj not in (float("inf"), float("-inf"), 0.0) and active_obj == active_obj:
            objective_delta_pct = round((shadow_obj - active_obj) / active_obj * 100.0, 2)

    candidates = [
        {
            "method": active_method,
            "role": "active",
            "status": None,
            "weights_bps": dict(active_weights_bps),
            "objective_value_milli": objective_milli_active,
            "feasible": active_evaluation.feasible if active_evaluation is not None else None,
            "constraint_violations": (
                list(active_evaluation.constraint_violations)
                if active_evaluation is not None else []
            ),
        },
        {
            "method": "stochastic",
            "role": "shadow",
            "status": optimizer_result.status,
            "weights_bps": shadow_weights,
            "objective_value_milli": objective_milli_shadow,
            "feasible": shadow_evaluation.feasible if shadow_evaluation is not None else None,
            "constraint_violations": (
                list(shadow_evaluation.constraint_violations)
                if shadow_evaluation is not None else []
            ),
        },
    ]

    return {
        "active_method": active_method,
        "shadow_method": "stochastic",
        "shadow_status": optimizer_result.status,
        "active_weights_bps": dict(active_weights_bps),
        "shadow_weights_bps": shadow_weights,
        "weight_deltas_bps": deltas,
        "objective_value_milli_active": objective_milli_active,
        "objective_value_milli_shadow": objective_milli_shadow,
        "objective_delta_pct": objective_delta_pct,
        "advisory_note": _allocation_comparison_note(deltas, optimizer_result.status, objective_delta_pct),
        "candidates": candidates,
    }


def _build_shadow_comparison_with_evaluations(
    *,
    optimizer_mode: str,
    optimizer_result,
    active_weights_bps: dict[str, int],
    cma,
    goals: list,
    house_matrix_row,
    assessment,
    advisory_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int] | None,
    building_blocks_rows: list | None,
) -> dict | None:
    """V3 Sprint 1c (Commit 3): Methodenvergleich mit Apples-to-Apples Objective.

    Baut einen `OptimizerContext` mit dem **gleichen** Seed wie der Solver-Lauf
    (aus `optimizer_result.seed`) und bewertet beide Allocations
    (House-Matrix-aktiv und Shadow-Solver) unter denselben Scenarios.

    Faellt sicher zurueck (nur Gewichte + Note ohne Objective-Delta), wenn der
    Solver nicht lief oder Context-Bau scheitert.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _OPTIMIZER_N_PATHS_DEFAULT, logger

    if optimizer_mode != "shadow_stochastic" or optimizer_result is None:
        return _build_allocation_method_comparison(
            optimizer_mode=optimizer_mode,
            active_method="house_matrix",
            active_weights_bps=active_weights_bps,
            optimizer_result=optimizer_result,
        )

    active_evaluation = None
    shadow_evaluation = None
    try:
        from services.optimizer.constraints import (
            bucket_risky_fractions_from_building_blocks,
        )
        from services.optimizer.solver import (
            build_optimizer_context,
            evaluate_weights,
        )
    except ImportError as exc:
        logger.warning(
            "Shadow-comparison: optimizer module not importable (%s); "
            "falling back to weight-only comparison.", exc,
        )
        return _build_allocation_method_comparison(
            optimizer_mode=optimizer_mode,
            active_method="house_matrix",
            active_weights_bps=active_weights_bps,
            optimizer_result=optimizer_result,
        )

    rf_per_bucket: dict[str, float] | None = None
    if building_blocks_rows is not None:
        try:
            rf_per_bucket = bucket_risky_fractions_from_building_blocks(building_blocks_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Shadow-comparison: risky-fraction extraction failed: %s", exc)
            rf_per_bucket = None

    score_x10 = _assessment_score_x10(assessment)
    horizon = max(10, int(len(cashflow_projection_series_rappen) or 10))

    try:
        context = build_optimizer_context(
            cma=cma,
            goals=list(goals),
            house_matrix_row=house_matrix_row,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            horizon_years=horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            seed=int(optimizer_result.seed or 0) or None,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=rf_per_bucket,
            max_risky_fraction_bps=int(house_matrix_row.max_risky_fraction_bps),
        )
        active_evaluation = evaluate_weights(context, active_weights_bps)
        # Shadow-Weights nur bewerten wenn der Solver konvergiert ist;
        # sonst sind die Solver-Weights die House-Matrix-Mid und Vergleich
        # waere irrefuehrend.
        if _optimizer_status_is_converged(optimizer_result.status):
            shadow_evaluation = evaluate_weights(context, optimizer_result.weights_bps)
    except Exception as exc:  # noqa: BLE001 - never crash allocation flow
        logger.warning(
            "Shadow-comparison: evaluate_weights failed (%s); "
            "falling back to weight-only comparison.", exc, exc_info=True,
        )
        active_evaluation = None
        shadow_evaluation = None

    return _build_allocation_method_comparison(
        optimizer_mode=optimizer_mode,
        active_method="house_matrix",
        active_weights_bps=active_weights_bps,
        optimizer_result=optimizer_result,
        active_evaluation=active_evaluation,
        shadow_evaluation=shadow_evaluation,
    )


def _build_shadow_optimization_payload(
    *,
    optimizer_mode: str,
    optimizer_result,
    active_weights_bps: dict[str, int],
    active_risky_fraction_bps: int,
    risk_budget_bps: int,
    minimums: dict[str, int],
    maximums: dict[str, int],
    building_blocks_rows: list | None,
    mandate,
    assessment,
    comparison: dict | None,
    constraints: list[dict],
    goal_drivers: list[dict],
) -> dict | None:
    """Persistierbarer Stage-5 Shadow-Snapshot fuer Admin/Compliance.

    Sichtbare Allokation bleibt House-Matrix; dieser Payload beschreibt das
    parallel gerechnete Stochastic-Ergebnis und dessen Drift.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS, logger

    if optimizer_mode != "shadow_stochastic" or optimizer_result is None:
        return None
    shadow_weights = {
        bucket: int((optimizer_result.weights_bps or {}).get(bucket, 0) or 0)
        for bucket in _COMPARISON_BUCKETS
    }
    try:
        shadow_risky_bps = compute_portfolio_risky_fraction_bps(
            shadow_weights,
            building_blocks_rows or [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow payload: risky-fraction computation failed: %s", exc)
        shadow_risky_bps = int(active_risky_fraction_bps)
    achievability = list(getattr(optimizer_result, "goal_achievability", ()) or [])
    shadow_limiting_factor = classify_limiting_factor(
        allocation_bps=shadow_weights,
        risky_fraction=int(shadow_risky_bps),
        max_risky_fraction=int(risk_budget_bps),
        min_liquidity_bps=int(minimums.get("liquidity", 0) or 0),
        bands={bucket: (int(minimums.get(bucket, 0) or 0), int(maximums.get(bucket, 0) or 0)) for bucket in BUCKET_FIELDS},
        achievability=achievability,
        optimization_status=str(getattr(optimizer_result, "status", "") or ""),
    )
    message_context = SimpleNamespace(
        limiting_factor=shadow_limiting_factor,
        optimization_status=str(getattr(optimizer_result, "status", "") or ""),
        risky_fraction_bps_at_generation=int(shadow_risky_bps),
        risk_budget_bps_at_generation=int(risk_budget_bps),
    )
    messages = classify_messages(
        message_context,
        achievability,
        str(getattr(optimizer_result, "status", "") or ""),
        mandate,
        assessment,
    )
    return {
        "engine": "stochastic",
        "allocation_bps": shadow_weights,
        "active_allocation_bps": dict(active_weights_bps),
        "weight_deltas_bps": (comparison or {}).get("weight_deltas_bps", {
            bucket: shadow_weights[bucket] - int(active_weights_bps.get(bucket, 0) or 0)
            for bucket in _COMPARISON_BUCKETS
        }),
        "risky_fraction_bps": int(shadow_risky_bps),
        "active_risky_fraction_bps": int(active_risky_fraction_bps),
        "risk_budget_bps": int(risk_budget_bps),
        "risky_drift_bps": abs(int(shadow_risky_bps) - int(active_risky_fraction_bps)),
        "budget_compliance": bool(int(shadow_risky_bps) <= int(risk_budget_bps)),
        "active_budget_compliance": bool(int(active_risky_fraction_bps) <= int(risk_budget_bps)),
        "limiting_factor": shadow_limiting_factor,
        "achievability": achievability,
        "messages": messages,
        "elapsed_ms": int(getattr(optimizer_result, "elapsed_ms", 0) or 0),
        "optimization_status": str(getattr(optimizer_result, "status", "") or ""),
        "objective_value_milli": _objective_to_milli(getattr(optimizer_result, "objective_value", None)),
        "seed": int(getattr(optimizer_result, "seed", 0) or 0),
        "n_paths": int(getattr(optimizer_result, "n_paths", 0) or 0),
        "n_iterations": int(getattr(optimizer_result, "iterations", 0) or 0),
        "n_starts_attempted": int(getattr(optimizer_result, "n_starts_attempted", 0) or 0),
        "robustification": getattr(optimizer_result, "robustification", None),
        "reasoning": list(getattr(optimizer_result, "reasoning", []) or []),
        "comparison": comparison,
        "constraints": list(constraints or []),
        "goal_drivers": list(goal_drivers or []),
    }


# --------------------------------------------------------------------------- #
# V3 Sprint 1d (2026-05-08): Constraint Slacks + Goal Drivers Explainability
# --------------------------------------------------------------------------- #
def _build_optimizer_explainability(
    *,
    optimizer_mode: str,
    optimizer_result,
    active_weights_bps: dict[str, int],
    cma,
    goals: list,
    house_matrix_row,
    assessment,
    advisory_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int] | None,
    building_blocks_rows: list | None,
) -> tuple[list[dict], list[dict]]:
    """Liefert (constraint_slacks, goal_drivers) fuer die aktive Allocation.

    Plan §5.3 / §5.4: Macht sichtbar, welche Leitplanke wirklich begrenzt
    und welches Ziel den Shortfall dominiert.

    Nur in shadow_stochastic / stochastic Modi mit gelaufenem Solver. Sonst
    leere Listen — der House-Matrix-Default lebt ohne Solver-Context und
    waere fuer diese Erklaerbarkeit nur scheinbar bewertbar.

    Faellt sicher in `([], [])` zurueck, wenn Context-Bau scheitert.
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _OPTIMIZER_N_PATHS_DEFAULT, logger

    if optimizer_mode not in {"shadow_stochastic", "stochastic"} or optimizer_result is None:
        return ([], [])

    try:
        from services.optimizer.constraints import (
            bucket_risky_fractions_from_building_blocks,
            constraint_slacks as _constraint_slacks,
        )
        from services.optimizer.objective import shortfall_contributions
        from services.optimizer.scenario_engine import simulate_wealth_paths
        from services.optimizer.solver import (
            _weights_bps_to_array,
            build_optimizer_context,
        )
    except ImportError as exc:
        logger.warning(
            "Optimizer-explainability: module not importable (%s); "
            "returning empty lists.", exc,
        )
        return ([], [])

    rf_per_bucket: dict[str, float] | None = None
    if building_blocks_rows is not None:
        try:
            rf_per_bucket = bucket_risky_fractions_from_building_blocks(building_blocks_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Explainability: risky-fraction extraction failed: %s", exc)
            rf_per_bucket = None

    score_x10 = _assessment_score_x10(assessment)
    horizon = max(10, int(len(cashflow_projection_series_rappen) or 10))

    try:
        context = build_optimizer_context(
            cma=cma,
            goals=list(goals),
            house_matrix_row=house_matrix_row,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            horizon_years=horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            seed=int(optimizer_result.seed or 0) or None,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=rf_per_bucket,
            max_risky_fraction_bps=int(house_matrix_row.max_risky_fraction_bps),
        )
    except Exception as exc:  # noqa: BLE001 - never crash allocation flow
        logger.warning(
            "Explainability: context build failed (%s); returning empty lists.", exc,
        )
        return ([], [])

    constraint_rows = _constraint_slacks(
        active_weights_bps,
        bounds=context.bounds,
        score_x10=context.score_x10,
        risky_fraction_per_bucket=rf_per_bucket,
        max_risky_fraction_bps=int(house_matrix_row.max_risky_fraction_bps),
    )
    constraints_payload = [
        {
            "code": row.code,
            "label": row.label,
            "value_bps": int(row.value_bps),
            "limit_bps": int(row.limit_bps),
            "slack_bps": int(row.slack_bps),
            "is_binding": bool(row.is_binding),
            "is_violated": bool(row.is_violated),
        }
        for row in constraint_rows
    ]

    drivers_payload: list[dict] = []
    try:
        active_w = _weights_bps_to_array(active_weights_bps)
        wealth_paths = simulate_wealth_paths(
            initial_wealth_rappen=context.advisory_wealth_rappen,
            weights=active_w,
            return_paths=context.return_paths,
            cashflow_series_rappen=context.cashflow_series_rappen,
            liability_path_rappen=context.aggregated_liability_path,
        )
        contribution_rows = shortfall_contributions(
            context.liabilities,
            wealth_paths,
            initial_wealth_rappen=context.advisory_wealth_rappen,
            horizon_years=context.horizon_years,
        )
        for rank, row in enumerate(contribution_rows, start=1):
            drivers_payload.append({
                "goal_id": row.goal_id,
                "label": row.label,
                "target_kind": row.target_kind,
                "hardness_key": row.hardness_key,
                "weight_bps": int(row.weight_bps),
                "weighted_objective_contribution_milli": _objective_to_milli(
                    row.weighted_objective_contribution
                ),
                "rank": rank,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Explainability: shortfall_contributions failed (%s); "
            "constraints geliefert, drivers leer.", exc,
        )

    return (constraints_payload, drivers_payload)


# --------------------------------------------------------------------------- #
# V3 Sprint 2 (2026-05-09 / Plan §4.1): persistierter Audit-Trail aller
# Solver-Laufe in der eigenen Tabelle optimizer_runs.
# --------------------------------------------------------------------------- #
def _persist_optimizer_run(
    db: Session,
    *,
    mandate_id: str,
    target_allocation_id: str | None,
    optimizer_mode: str,
    optimizer_result,
    user_id: str | None,
    now: str,
) -> OptimizerRun | None:
    """Schreibt einen OptimizerRun in die DB.

    Wird nur fuer Modi 'shadow_stochastic' und 'stochastic' aufgerufen, sonst
    None. role:
    - 'shadow' -> shadow_stochastic, target_allocation bleibt House-Matrix-basiert
    - 'active' -> stochastic, weights ersetzten ggf. die TargetAllocation

    Defensive: bei JSON-Serialisierungsfehlern wird der Run trotzdem mit
    leeren Feldern persistiert (kein Crash).
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import logger

    if optimizer_mode not in {"shadow_stochastic", "stochastic"} or optimizer_result is None:
        return None
    role = "active" if optimizer_mode == "stochastic" else "shadow"
    weights_bps = optimizer_result.weights_bps or {}
    try:
        weights_bps_json = json.dumps(
            {bucket: int(weights_bps.get(bucket, 0) or 0) for bucket in (
                "equities", "bonds", "real_estate", "alternatives", "liquidity"
            )},
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("OptimizerRun: weights_bps_json failed (%s)", exc)
        weights_bps_json = "{}"

    constraint_violations_json: str | None = None
    if optimizer_result.constraint_violations:
        try:
            constraint_violations_json = json.dumps(
                list(optimizer_result.constraint_violations),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("OptimizerRun: constraint_violations_json failed (%s)", exc)
            constraint_violations_json = None

    reasoning_json: str | None = None
    if optimizer_result.reasoning:
        try:
            reasoning_json = json.dumps(
                list(optimizer_result.reasoning),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("OptimizerRun: reasoning_json failed (%s)", exc)
            reasoning_json = None

    stress_evaluations_json: str | None = None
    if optimizer_result.stress_evaluations:
        try:
            stress_evaluations_json = json.dumps(
                optimizer_result.stress_evaluations,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("OptimizerRun: stress_evaluations_json failed (%s)", exc)
            stress_evaluations_json = None

    restart_results_json: str | None = None
    restart_results = getattr(optimizer_result, "restart_results", None)
    if restart_results:
        try:
            restart_results_json = json.dumps(
                list(restart_results),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("OptimizerRun: restart_results_json failed (%s)", exc)
            restart_results_json = None

    run = OptimizerRun(
        id=new_uuid(),
        mandate_id=mandate_id,
        target_allocation_id=target_allocation_id if role == "active" else None,
        run_at=now,
        optimizer_mode=optimizer_mode,
        role=role,
        method=str(getattr(optimizer_result, "method", "stochastic")),
        status=str(getattr(optimizer_result, "status", "diverged")),
        seed=int(getattr(optimizer_result, "seed", 0) or 0),
        n_paths=int(getattr(optimizer_result, "n_paths", 0) or 0),
        n_iterations=int(getattr(optimizer_result, "iterations", 0) or 0),
        n_starts_attempted=int(getattr(optimizer_result, "n_starts_attempted", 0) or 0),
        objective_value_milli=_objective_to_milli(getattr(optimizer_result, "objective_value", None)),
        weights_bps_json=weights_bps_json,
        constraint_violations_json=constraint_violations_json,
        reasoning_json=reasoning_json,
        stress_evaluations_json=stress_evaluations_json,
        restart_results_json=restart_results_json,
        set_by=user_id,
        created_at=now,
    )
    db.add(run)
    return run
