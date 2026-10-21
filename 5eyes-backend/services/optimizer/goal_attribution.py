"""Publizierte Zielerreichung mit typisiertem Evaluation-Scope.

GOAL-ACHIEVABILITY-ATTRIBUTION-001 (Owner-Entscheid 2026-10-14)
==============================================================

Audit: docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

**Befund.** Der Solver simuliert genau einen Vermoegenspfad nach der Summe
aller Ziel-Abfluesse. Die publizierte "Wahrscheinlichkeit" je Ziel war die
Frage "war der GEMEINSAME Portfoliozustand nach allen bis zum Faelligkeits-
termin ausgefuehrten Abfluessen nicht negativ?" -- eine Planbedingung, die pro
Zielzeile wiederholt wurde. Zwei gleichzeitig faellige Ausgaben von CHF 90
(Rang 1, hart) und CHF 20 (Rang 2, opportunistisch) auf CHF 100 bekamen beide
0 % und denselben Fehlbetrag, und ein einziger Liquiditaetsengpass wurde als
zwei unabhaengige Zielkonflikte gezaehlt.

**Vertrag.** Jede publizierte Zeile traegt einen diskriminierten
``evaluation_scope``:

``priority_funded`` (eine Zeile je Ziel)
    Funding-Ledger nach Rang. Auf jedem Pfad werden die Ziele in kanonischer
    Rangfolge finanziert, Rang 1 zuerst. Ein Ziel mit Rang ``r`` gilt auf
    einem Pfad als erreicht, wenn es NACH allen Zielen mit Rang ``< r``
    vollstaendig finanziert ist -- formal: bewertet auf dem Vermoegenspfad,
    von dem nur die Abfluesse des kumulativen Scopes
    ``S_r = {h | rank(h) <= r}`` abgezogen werden
    (``goals_to_liabilities``). Seit Engine ``saa_resampled_v10`` wird dieser
    Pfad DIREKT simuliert -- ein Replay je eindeutigem Scope auf denselben
    Szenarien, Cashflows, Steuern, Todesmasken und Reserve-Freigaben
    (``priority_scope.PriorityScopeWealth``); die bis v8 benutzte
    Rueckwaertsrekonstruktion aus dem gemeinsamen Pfad ist entfernt
    (GOAL-ATTRIBUTION-CASHFLOW-INVERSION-001). Ohne Replay-Kontext wird ein
    abweichender Scope nicht bewertet (fail-closed).

    *Gleichrang:* Ziele mit demselben Rang teilen sich einen Scope und werden
    gemeinsam finanziert -- es wird keine Reihenfolge erfunden, die der Kunde
    nicht festgelegt hat (Permutationsinvarianz).
    *Haerte:* wirkt ausschliesslich ueber Gewicht und Chance-Penalty der
    Zielfunktion, nie ueber die Finanzierungsreihenfolge
    (GOAL-FUNDING-PRIORITY-001: der Rang ist die einzige Funding-Prioritaet;
    GOAL-RANK-HARDNESS-ROUNDTRIP-001 haelt Rang und Haerte getrennt).
    *Keine Vorausreservierung:* hoeher priorisierte Abfluesse werden bedient,
    wenn sie faellig sind. Eine Vermoegens-SCHWELLE ist kein Abfluss und
    reserviert nichts fuer die Zukunft -- eine solche Reservierung braeuchte
    die kuenftigen Renditen des Pfades (Lookahead). Was dadurch gemeinsam
    scheitert, zeigt die Plan-Solvenz.
    *Renditeziele:* die Rendite ist eine Portfolioeigenschaft und wird nicht
    finanziert; sie wird auf der cashflow-neutralen Rendite bewertet, wenn
    diese vorliegt.

``joint_plan`` (genau eine Zeile)
    Plan-Solvenz: auf dem tatsaechlich simulierten Pfad (alle Abfluesse)
    sind ALLE bewertbaren Ziele gleichzeitig erreicht. Derselbe Wert wird nie
    als individuelle Zielwahrscheinlichkeit wiederholt. Schwelle ist die
    strengste Zielschwelle der einbezogenen Ziele.

Beide Scopes verwenden dieselbe Zertifizierungsregel
(``objective.certify_success_indicator``: Wilson-Untergrenze, Kish-ESS,
Validierungsanker) wie die Chance-Penalty.

**Failure-Events.** Fuer jedes nicht immer erreichte Ziel wird die Ursache
je verfehltem Pfad typisiert: das erste Jahr, in dem der fuer dieses Ziel
massgebliche Finanzierungspfad negativ wird (``liquiditaetsengpass-jahr-<t>``),
sonst das eigene Ziel (``zielschwelle-<goal_id>`` / ``renditeziel-<goal_id>``).
GOAL-FAILURE-EVENT-MODE-COLLAPSE-001 (Engine v10): persistiert wird die
VOLLE Ursachenverteilung (``failure_event_distribution``: Event-ID,
gewichtete Masse, Anteil; deterministisch sortiert nach Anteil absteigend,
dann frueheres Jahr, dann eigene Schwelle). ``failure_event_id`` /
``failure_event_share`` bleiben als Modus der Verteilung erhalten. Ein
``gemeinsamer_engpass`` liegt nur vor, wenn die GESAMTE Fehlschlagsmasse
jedes betroffenen Ziels auf dasselbe eine Ereignis faellt
(``shared_failure_event``); 60 % gemeinsam + 40 % eigene Ursachen ist ein
Zielkonflikt, kein einzelner Engpass.

**Zielfunktion (Engine v10).** Fehlbetrag, Chance-Strafe und Stufe-1-Niveau
bewerten jedes Ziel auf DEMSELBEN priorisierten Scope wie diese
Publikation (GOAL-OPTIMIZATION-PUBLICATION-SCOPE-SPLIT-001). Die
Plan-Solvenz ist reine Information: sie ist kein Term der Zielfunktion und
ihre Schwelle (strengste Zielschwelle) ist keine bestaetigte Kundenangabe
(JOINT-PLAN-TAU-POLICY-001, offen).
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np

from .goal_liabilities import GoalLiability
from .objective import (
    _default_tau_x100,
    _display_hardness,
    _goal_probability_core,
    _hardness_key,
    _positive_due_wealth_indices,
    certify_success_indicator,
    scheduled_outside_wealth_horizon,
)
from .priority_scope import (
    PRIORITY_SCOPE_POLICY_VERSION,
    PriorityScopeWealth,
    scope_wealth_for,
)

EVALUATION_SCOPE_PRIORITY_FUNDED = "priority_funded"
EVALUATION_SCOPE_JOINT_PLAN = "joint_plan"
EVALUATION_SCOPE_LEGACY = "legacy_aggregate_unknown"
# Interne Sicht der Chance-Penalty (objective.chance_constraint_penalty). Nie
# als individuelle Zielwahrscheinlichkeit zu publizieren.
EVALUATION_SCOPE_PENALTY_INTERNAL = "priority_funded_chance_penalty"

# Bei jeder Aenderung der Funding-Regel (Gleichrang, Reservierung, ...)
# hochziehen. Wird pro Zeile mitpersistiert, damit eine gespeicherte Zahl
# ihre Regel mitbringt. v2 (Engine v10): Scope per direktem Replay statt
# Rueckwaertsrekonstruktion; Reserve-Freigaben ausserhalb des Scopes entfallen.
GOAL_FUNDING_POLICY_VERSION = "rank_cumulative_scope_v2_direct_replay"
# GOAL-FAILURE-EVENT-MODE-COLLAPSE-001: Version der Ursachenverteilung.
FAILURE_EVENT_POLICY_VERSION = "failure_event_distribution_v1"
# Numerische Toleranz fuer "gesamte Fehlschlagsmasse" (Anteile sind
# Quotienten von Gewichtssummen).
_FULL_MASS_TOL = 1e-12

PLAN_SOLVENCY_LABEL = "Plan-Solvenz (alle Ziele gemeinsam)"
PRIORITY_FUNDED_LABEL = "Zielerreichung nach Priorität"

_INDIVIDUAL_SCOPES = frozenset({EVALUATION_SCOPE_PRIORITY_FUNDED})


def _weights_and_sum(
    weights: np.ndarray | None, n_paths: int
) -> tuple[np.ndarray | None, float | None]:
    if weights is None:
        return None, None
    weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
    if weights_arr.shape[0] != n_paths:
        raise ValueError(
            f"weights.shape[0]={weights_arr.shape[0]} != n_paths={n_paths}"
        )
    weight_sum = float(np.sum(weights_arr))
    if weight_sum <= 0:
        raise ValueError("Sum-of-weights must be > 0")
    return weights_arr, weight_sum


def _evaluation_columns(goal: GoalLiability, n_wealth_columns: int) -> np.ndarray:
    """Spalten des Vermoegenspfads, an denen das Ziel geprueft wird."""
    if goal.target_kind in ("cashflow_in_year", "outflow_stream"):
        return _positive_due_wealth_indices(goal, n_wealth_columns=n_wealth_columns)
    if goal.target_kind == "wealth_at_t":
        idx = max(1, min(int(goal.target_year_index), n_wealth_columns - 1))
        return np.asarray([idx], dtype=np.intp)
    return np.zeros(0, dtype=np.intp)


def _failure_event_distribution(
    *,
    success: np.ndarray,
    funding_paths: np.ndarray,
    last_column: int,
    own_event_id: str,
    weights_arr: np.ndarray | None,
) -> list[dict]:
    """Volle, deterministische Ursachenverteilung ueber die verfehlten Pfade.

    Ursache je Pfad: erstes Jahr ``t <= last_column`` mit negativem
    Finanzierungspfad; ohne Insolvenz das Ziel selbst. Sortierung: Anteil
    absteigend, dann frueheres Jahr, dann eigene Schwelle (Gleichstand
    deterministisch). Leer, wenn kein Pfad verfehlt.
    """
    failing = np.asarray(success, dtype=np.int8) == 0
    if not np.any(failing):
        return []
    path_weights = (
        np.ones(success.shape[0], dtype=np.float64)
        if weights_arr is None
        else np.asarray(weights_arr, dtype=np.float64)
    )
    tally: dict[tuple[int, str], float] = {}
    if last_column >= 1:
        window = funding_paths[:, 1 : last_column + 1] < 0.0
        has_insolvency = window.any(axis=1)
        first_year = np.where(has_insolvency, window.argmax(axis=1) + 1, 0)
    else:
        has_insolvency = np.zeros(success.shape[0], dtype=bool)
        first_year = np.zeros(success.shape[0], dtype=np.intp)
    for index in np.flatnonzero(failing):
        if has_insolvency[index]:
            key = (int(first_year[index]), f"liquiditaetsengpass-jahr-{int(first_year[index])}")
        else:
            key = (10**9, own_event_id)
        tally[key] = tally.get(key, 0.0) + float(path_weights[index])
    total = float(sum(tally.values()))
    ordered = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "event_id": event_id,
            "weighted_mass": float(weight),
            "share": float(weight / total) if total > 0 else None,
        }
        for (_order, event_id), weight in ordered
    ]


def _dominant_failure_event(
    *,
    success: np.ndarray,
    funding_paths: np.ndarray,
    last_column: int,
    own_event_id: str,
    weights_arr: np.ndarray | None,
) -> tuple[str | None, float | None]:
    """Modus der Ursachenverteilung (Rueckwaertskompatibilitaet)."""
    distribution = _failure_event_distribution(
        success=success, funding_paths=funding_paths, last_column=last_column,
        own_event_id=own_event_id, weights_arr=weights_arr,
    )
    if not distribution:
        return None, None
    return distribution[0]["event_id"], distribution[0]["share"]


def full_mass_failure_event(row: Mapping) -> str | None:
    """Event-ID, wenn die GESAMTE Fehlschlagsmasse der Zeile darauf faellt.

    Mit ``failure_event_distribution``: genau ein Eintrag mit Anteil 1.
    Alte Zeilen ohne Verteilung: ``failure_event_share`` == 1. Sonst None
    (Teilmasse oder unbekannte Masse ist kein gemeinsamer Engpass).
    """
    distribution = row.get("failure_event_distribution")
    if isinstance(distribution, (list, tuple)):
        entries = [entry for entry in distribution if isinstance(entry, Mapping)]
        if len(entries) != 1:
            return None
        share = entries[0].get("share")
        event_id = entries[0].get("event_id")
        if event_id and share is not None and float(share) >= 1.0 - _FULL_MASS_TOL:
            return str(event_id)
        return None
    event_id = row.get("failure_event_id")
    share = row.get("failure_event_share")
    if event_id and share is not None and float(share) >= 1.0 - _FULL_MASS_TOL:
        return str(event_id)
    return None


def shared_failure_event(rows: Sequence[Mapping]) -> str | None:
    """Das EINE Ereignis, das die volle Fehlschlagsmasse ALLER Zeilen traegt.

    None, sobald eine Zeile Teilmasse anderer Ursachen hat, keine typisierte
    Ursache traegt oder die Ereignisse verschieden sind.
    """
    events = {full_mass_failure_event(row) for row in rows}
    if len(events) == 1:
        return next(iter(events))
    return None


def _priority_funded_success(
    goal_wealth: np.ndarray,
    goal: GoalLiability,
    initial_value_rappen: int,
    annualized_return_bps_per_path: np.ndarray | None,
) -> np.ndarray:
    """Erfolgsindikator eines Ziels auf seinem (bereits replayten) Scope-Pfad.

    Rendite ist eine Portfolioeigenschaft (cashflow-neutrale TWR) und damit
    scope-unabhaengig; Zielfunktion und Publikation verwenden dieselbe.
    """
    return _goal_probability_core(
        goal_wealth, goal, initial_value_rappen,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
    )


def _own_event_id(goal: GoalLiability) -> str:
    prefix = "renditeziel" if goal.target_kind == "return_rate" else "zielschwelle"
    return f"{prefix}-{goal.goal_id}"


def publish_goal_achievability(
    wealth_paths: np.ndarray,
    goal_liabilities: Sequence[GoalLiability],
    initial_value_rappen: int,
    *,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
    validation_seed: int | None = None,
    scope_wealth: PriorityScopeWealth | None = None,
) -> list[dict]:
    """Publizierbare Zielerreichung: priorisierte Zielzeilen + eine Planzeile.

    Siehe Modul-Docstring fuer den Vertrag. Die Zielzeilen behalten die
    Reihenfolge von ``goal_liabilities``; die Plan-Solvenz-Zeile steht am
    Ende. Fehlen bewertbare Ziele, gibt es keine Planzeile.

    ``scope_wealth``: die direkten Scope-Replays zu ``wealth_paths``
    (``priority_scope.PriorityScopeWealth``). Pflicht, sobald ein Ziel einen
    vom gemeinsamen Pfad abweichenden Scope hat; der gemeinsame Pfad wird
    vorher gegen den Replay-Kontext geprueft (fail-closed).
    """
    goal_liabilities = list(goal_liabilities)
    wealth_paths = np.asarray(wealth_paths, dtype=np.float64)
    scoped = scope_wealth_for(wealth_paths, goal_liabilities, scope_wealth)
    if scope_wealth is not None:
        scoped.verify_joint_parity()
    n_paths = int(wealth_paths.shape[0]) if wealth_paths.ndim == 2 else 0
    n_cols = int(wealth_paths.shape[1]) if wealth_paths.ndim == 2 else 0
    weights_arr, weight_sum = _weights_and_sum(weights, n_paths)

    rows: list[dict] = []
    joint_successes: list[np.ndarray] = []
    joint_last_column = 0
    plan_goal_ids: list[str] = []
    plan_tau = 0.0
    for goal in goal_liabilities:
        tau = _default_tau_x100(goal) / 10000.0
        outside_horizon = goal.target_kind in (
            "cashflow_in_year", "outflow_stream",
        ) and scheduled_outside_wealth_horizon(goal, n_wealth_columns=n_cols)
        funding_paths = scoped.for_goal(goal)
        success = _priority_funded_success(
            funding_paths, goal, initial_value_rappen, annualized_return_bps_per_path,
        )
        estimate = certify_success_indicator(
            success,
            tau=tau,
            weights_arr=weights_arr,
            weight_sum=weight_sum,
            validation_seed=validation_seed,
            outside_horizon=outside_horizon,
        )
        eval_cols = _evaluation_columns(goal, n_cols)
        last_column = int(eval_cols.max()) if eval_cols.size else 0
        distribution: list[dict] = []
        if not outside_horizon and goal.target_kind != "maximize" and n_paths:
            distribution = _failure_event_distribution(
                success=success,
                funding_paths=funding_paths,
                last_column=last_column,
                own_event_id=_own_event_id(goal),
                weights_arr=weights_arr,
            )
        hardness = _hardness_key(getattr(goal, "hardness_key", None))
        rows.append({
            "goal_id": str(goal.goal_id),
            "label": str(goal.label),
            "target_kind": str(goal.target_kind),
            "probability": estimate["probability"],
            "tau": tau,
            "status": estimate["status"],
            "hardness": _display_hardness(hardness),
            "lower_confidence_bound": estimate["lower_confidence_bound"],
            "effective_sample_size": estimate["effective_sample_size"],
            "validation_seed": validation_seed,
            "reliability_verdict": estimate["reliability_verdict"],
            "outside_simulation_horizon": outside_horizon,
            "evaluation_scope": EVALUATION_SCOPE_PRIORITY_FUNDED,
            "funding_policy_version": GOAL_FUNDING_POLICY_VERSION,
            "funding_rank": int(getattr(goal, "rank", 1) or 1),
            "priority_scope_policy_version": PRIORITY_SCOPE_POLICY_VERSION,
            "failure_event_id": distribution[0]["event_id"] if distribution else None,
            "failure_event_share": distribution[0]["share"] if distribution else None,
            "failure_event_distribution": distribution,
            "failure_event_policy_version": FAILURE_EVENT_POLICY_VERSION,
        })

        if outside_horizon or goal.target_kind == "maximize":
            continue
        joint_successes.append(
            _goal_probability_core(
                wealth_paths, goal, initial_value_rappen,
                annualized_return_bps_per_path=annualized_return_bps_per_path,
            ).astype(np.int8)
        )
        joint_last_column = max(joint_last_column, last_column)
        plan_goal_ids.append(str(goal.goal_id))
        plan_tau = max(plan_tau, tau)

    if joint_successes and n_paths:
        plan_success = np.logical_and.reduce(joint_successes).astype(np.int8)
        estimate = certify_success_indicator(
            plan_success,
            tau=plan_tau,
            weights_arr=weights_arr,
            weight_sum=weight_sum,
            validation_seed=validation_seed,
        )
        plan_distribution = _failure_event_distribution(
            success=plan_success,
            funding_paths=wealth_paths,
            last_column=joint_last_column,
            own_event_id="zielschwelle",
            weights_arr=weights_arr,
        )
        rows.append({
            "goal_id": None,
            "label": PLAN_SOLVENCY_LABEL,
            "target_kind": EVALUATION_SCOPE_JOINT_PLAN,
            "probability": estimate["probability"],
            "tau": plan_tau,
            "status": estimate["status"],
            "hardness": None,
            "lower_confidence_bound": estimate["lower_confidence_bound"],
            "effective_sample_size": estimate["effective_sample_size"],
            "validation_seed": validation_seed,
            "reliability_verdict": estimate["reliability_verdict"],
            "outside_simulation_horizon": False,
            "evaluation_scope": EVALUATION_SCOPE_JOINT_PLAN,
            "funding_policy_version": GOAL_FUNDING_POLICY_VERSION,
            "goal_ids": sorted(plan_goal_ids),
            "failure_event_id": plan_distribution[0]["event_id"] if plan_distribution else None,
            "failure_event_share": plan_distribution[0]["share"] if plan_distribution else None,
            "failure_event_distribution": plan_distribution,
            "failure_event_policy_version": FAILURE_EVENT_POLICY_VERSION,
        })
    return rows


def row_evaluation_scope(row: Mapping) -> str:
    """Scope einer (ggf. alten) Zeile; ohne Scope -> ``legacy_aggregate_unknown``."""
    scope = str((row or {}).get("evaluation_scope") or "").strip()
    return scope or EVALUATION_SCOPE_LEGACY


def is_individual_goal_row(row: Mapping) -> bool:
    """True nur fuer zielindividuelle Evidenz (``priority_funded``)."""
    return row_evaluation_scope(row) in _INDIVIDUAL_SCOPES


def split_goal_achievability(
    rows: Iterable[Mapping] | None,
) -> tuple[list[dict], dict | None]:
    """Trennt gespeicherte/publizierte Zeilen in (Zielzeilen, Plan-Solvenz).

    * Zielzeilen: Kopien, sortiert nach kanonischem Rang (stabil); Zeilen
      ohne Scope erhalten ``legacy_aggregate_unknown`` (Publikations-
      quarantaene: sie sind Aggregatwerte unbekannter Semantik und duerfen
      keine individuelle Ampel tragen).
    * Plan-Solvenz: die eine ``joint_plan``-Zeile oder None.

    Die Eingabe wird nicht veraendert.
    """
    goal_rows: list[tuple[int, int, dict]] = []
    plan_row: dict | None = None
    for index, raw in enumerate(rows or []):
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        scope = row_evaluation_scope(row)
        if scope == EVALUATION_SCOPE_JOINT_PLAN:
            if plan_row is None:
                plan_row = row
            continue
        row["evaluation_scope"] = scope
        try:
            rank = int(row.get("funding_rank"))
        except (TypeError, ValueError):
            rank = 10**9
        goal_rows.append((rank, index, row))
    goal_rows.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in goal_rows], plan_row


__all__ = [
    "FAILURE_EVENT_POLICY_VERSION",
    "EVALUATION_SCOPE_JOINT_PLAN",
    "EVALUATION_SCOPE_LEGACY",
    "EVALUATION_SCOPE_PENALTY_INTERNAL",
    "EVALUATION_SCOPE_PRIORITY_FUNDED",
    "GOAL_FUNDING_POLICY_VERSION",
    "PLAN_SOLVENCY_LABEL",
    "PRIORITY_FUNDED_LABEL",
    "full_mass_failure_event",
    "is_individual_goal_row",
    "publish_goal_achievability",
    "row_evaluation_scope",
    "shared_failure_event",
    "split_goal_achievability",
]
