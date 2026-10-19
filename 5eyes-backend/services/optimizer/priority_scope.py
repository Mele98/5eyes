"""Prioritaetsgeschuetzte Vermoegenspfade per direktem Replay (Engine v10).

GOAL-ATTRIBUTION-CASHFLOW-INVERSION-001 / GOAL-FUNDING-PRIORITY-001
(Codex-Reviews 2026-10-18)
===================================================================

Ein Ziel mit Rang ``r`` wird auf dem Vermoegenspfad bewertet, von dem nur die
Abfluesse des kumulativen Scopes ``S_r = {h | rank(h) <= r}`` abgezogen sind
(``goal_attribution``-Vertrag). Bis Engine v8 wurde dieser Pfad RUECKWAERTS
aus dem gemeinsamen Pfad rekonstruiert::

    growth = (W_joint[t+1] + L_joint[t]) / W_joint[t]
    W_scope[t+1] = W_scope[t] * growth - L_scope[t]

Das ist nur exakt, wenn ``W_joint[t+1] + L_joint[t]`` reines Wachstum ist. Es
enthaelt aber auch den additiven Cashflow, die Mortalitaetsmaske (Cashflow und
Liability nach dem Tod = 0), das W2.5-Verbot der Verzinsung negativer
Vermoegen und den pfadabhaengigen Steuerdrag. Gegenbeispiel (Nullrendite,
Start 100, Rang-3-Abfluss 80 in Jahr 1, Cashflow +100 in Jahr 2):
direkter Replay 100 -> 100 -> 200, Rekonstruktion 100 -> 100 -> 600.

**Vertrag ab Engine ``saa_resampled_v10``.** Jeder eindeutige Prioritaets-
Scope, der vom gemeinsamen Pfad abweicht, wird DIREKT mit
``scenario_engine.simulate_wealth_paths`` simuliert -- mit exakt denselben
Szenarien (Common Random Numbers, dieselben Portfolio-Faktoren), Cashflows,
Steuerparametern, Kalenderjahren, Alter, Ruhestandsstatus, Dividend-Yields
und pfadweiser Todesmaske, nur mit dem Liability-Pfad des Scopes. Freigaben
der externen Reserve (``services/reserve_funding_ledger.py``), die in die
Abfluesse eines Ziels AUSSERHALB des Scopes fliessen, werden mit diesem Ziel
aus dem Cashflow entfernt: Abfluss und seine quellengebundene Finanzierung
gehoeren zusammen (jede Ziel-Tranche fliesst je Jahr hoechstens in Hoehe des
eigenen Abflusses zurueck).

Ein Replay je eindeutigem Scope (Liability-Pfad + entfallende Freigaben),
nicht je Ziel: gleichrangige Ziele -- und ein Rang ohne eigene Abfluesse --
teilen sich denselben Replay. Der Scope des hoechsten Rangs ist der
gemeinsame Pfad und kostet keinen Replay. Ohne Steuer beginnt der Replay erst
im ersten Jahr, in dem der Scope vom gemeinsamen Lauf abweicht (davor sind
beide Rekursionen Operation fuer Operation identisch).

Ohne Replay-Kontext gibt es fuer abweichende Scopes KEINE Zahl: die
Bewertung bricht fail-closed ab (``PriorityScopeUnavailableError``) statt aus
einem aggregierten Pfad etwas zu erfinden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np

from .goal_liabilities import GoalLiability
from .scenario_engine import simulate_wealth_paths

PRIORITY_SCOPE_POLICY_VERSION = "direct_crn_replay_per_rank_v1"


class PriorityScopeUnavailableError(ValueError):
    """Ein Prioritaets-Scope weicht vom gemeinsamen Pfad ab, aber es fehlt
    der Replay-Kontext, um ihn direkt zu simulieren."""


def _scope_differs(goal: GoalLiability) -> bool:
    scope = goal.priority_scope_liability_path_rappen
    joint = goal.joint_liability_path_rappen
    if not scope or not joint:
        return False
    return [int(v) for v in scope] != [int(v) for v in joint]


def _as_int_tuple(values: Iterable[int] | None) -> tuple[int, ...]:
    return tuple(int(v) for v in (values or ()))


@dataclass(frozen=True)
class ScopeReplayInputs:
    """Alles, was ``simulate_wealth_paths`` fuer den gemeinsamen Pfad bekam,
    ausser dem Liability-Pfad -- der eingefrorene Replay-Kontext.

    ``joint_liability_path_rappen``: der Liability-Pfad, mit dem der
    gemeinsame Pfad simuliert wurde (Bindung: ein Ziel aus einem anderen
    Batch wird abgewiesen). ``goal_reserve_release_series_rappen``: je
    Ziel-ID die Reserve-Freigaben, die im ``cashflow_series_rappen`` bereits
    enthalten sind und in genau die Abfluesse dieses Ziels fliessen.
    """

    initial_wealth_rappen: int
    weights: np.ndarray
    return_paths: np.ndarray
    cashflow_series_rappen: tuple[int, ...]
    joint_liability_path_rappen: tuple[int, ...] | None = None
    death_year_index_per_path: np.ndarray | None = None
    tax_regime: object | None = None
    dividend_yield_bps_per_bucket: np.ndarray | None = None
    base_calendar_year: int = 2026
    mandate_age_at_start: int | None = None
    is_retired: bool = False
    portfolio_factors: np.ndarray | None = None
    goal_reserve_release_series_rappen: tuple[tuple[str, tuple[int, ...]], ...] = ()

    def _scope_cashflow(self, excluded_release_goal_ids: Iterable[str]) -> list[int]:
        horizon = int(np.asarray(self.return_paths).shape[1])
        cashflow = list(self.cashflow_series_rappen)
        excluded = {str(goal_id) for goal_id in excluded_release_goal_ids}
        if excluded:
            cashflow = (cashflow + [0] * horizon)[:horizon]
            for goal_id, series in self.goal_reserve_release_series_rappen:
                if str(goal_id) not in excluded:
                    continue
                for index, released in enumerate(series[:horizon]):
                    cashflow[index] -= int(released)
        return cashflow

    def simulate_many(
        self,
        scopes: Sequence[tuple[Sequence[int], Iterable[str]]],
        *,
        joint: np.ndarray | None = None,
    ) -> list[np.ndarray]:
        """Mehrere Scopes -- jeder bitidentisch zu einem direkten ``simulate``.

        Ohne Steuer ist jeder Pfad unabhaengig (keine Querschnittsstatistik).
        Dann gilt: bis zum ersten Jahr ``t0``, in dem Cashflow oder Liability
        des Scopes vom gemeinsamen Lauf abweichen, sind beide Rekursionen
        Operation fuer Operation identisch -- die Spalten ``0..t0`` werden aus
        ``joint`` uebernommen und erst ab ``t0`` weitergerechnet, mit genau den
        Operationen des steuerfreien Kerns
        (``scenario_engine._simulate_wealth_paths_untaxed``). Mit Steuer
        haengen ``median``/``binned`` vom Querschnitt aller Pfade ab -- dann
        je Scope ein eigener direkter Aufruf ab Jahr 0.
        """
        scopes = list(scopes)
        if self.tax_regime is not None:
            return [
                self.simulate(path, excluded_release_goal_ids=excluded)
                for path, excluded in scopes
            ]
        return_paths = np.asarray(self.return_paths, dtype=np.float64)
        n_paths, horizon, _buckets = return_paths.shape
        factors = self.portfolio_factors
        if factors is None:
            factors = np.einsum(
                "phb,b->ph", return_paths,
                np.asarray(self.weights, dtype=np.float64).reshape(-1),
            )
        factors_by_year = np.ascontiguousarray(np.asarray(factors, dtype=np.float64).T)
        alive_by_year = None
        if self.death_year_index_per_path is not None:
            death_idx = np.asarray(self.death_year_index_per_path, dtype=np.int32)
            if death_idx.shape != (n_paths,):
                raise ValueError(
                    f"death_year_index_per_path must be shape ({n_paths},), got {death_idx.shape}"
                )
            alive_by_year = np.arange(horizon, dtype=np.int32)[:, None] < death_idx[None, :]

        def _padded(values) -> np.ndarray:
            out = np.zeros(horizon, dtype=np.float64)
            arr = np.asarray(list(values or ()), dtype=np.float64)
            n = min(horizon, arr.size)
            out[:n] = arr[:n]
            return out

        joint_cf = _padded(self.cashflow_series_rappen)
        joint_liab = (
            None if self.joint_liability_path_rappen is None
            else _padded(self.joint_liability_path_rappen)
        )
        joint_by_year = None
        if joint is not None and joint_liab is not None:
            joint_arr = np.asarray(joint, dtype=np.float64)
            if joint_arr.shape == (n_paths, horizon + 1):
                joint_by_year = joint_arr.T

        results: list[np.ndarray] = []
        grown = np.empty(n_paths, dtype=np.float64)
        positive = np.empty(n_paths, dtype=bool)
        for path, excluded in scopes:
            cashflow = _padded(self._scope_cashflow(excluded))
            liability = _padded(path)
            wealth_by_year = np.empty((horizon + 1, n_paths), dtype=np.float64)
            start = 0
            if joint_by_year is not None:
                differs = (cashflow != joint_cf) | (liability != joint_liab)
                start = int(np.argmax(differs)) if differs.any() else horizon
                wealth_by_year[: start + 1] = joint_by_year[: start + 1]
            else:
                wealth_by_year[0] = float(self.initial_wealth_rappen)
            for t in range(start, horizon):
                prev = wealth_by_year[t]
                np.greater(prev, 0, out=positive)
                np.copyto(grown, prev)
                np.multiply(prev, factors_by_year[t], out=grown, where=positive)
                nxt = wealth_by_year[t + 1]
                if alive_by_year is not None:
                    np.add(grown, cashflow[t] * alive_by_year[t], out=nxt)
                    np.subtract(nxt, liability[t] * alive_by_year[t], out=nxt)
                else:
                    np.add(grown, cashflow[t], out=nxt)
                    if liability[t] != 0.0:
                        np.subtract(nxt, liability[t], out=nxt)
            results.append(np.ascontiguousarray(wealth_by_year.T))
        return results

    def simulate(
        self,
        liability_path_rappen: Sequence[int] | None,
        *,
        excluded_release_goal_ids: Iterable[str] = (),
    ) -> np.ndarray:
        """Direkter Aufruf von ``simulate_wealth_paths`` (gleiche CRN)."""
        cashflow = self._scope_cashflow(excluded_release_goal_ids)
        return simulate_wealth_paths(
            initial_wealth_rappen=self.initial_wealth_rappen,
            weights=self.weights,
            return_paths=self.return_paths,
            cashflow_series_rappen=cashflow,
            liability_path_rappen=(
                None if liability_path_rappen is None else list(liability_path_rappen)
            ),
            tax_regime=self.tax_regime,
            dividend_yield_bps_per_bucket=self.dividend_yield_bps_per_bucket,
            base_calendar_year=self.base_calendar_year,
            mandate_age_at_start=self.mandate_age_at_start,
            is_retired=self.is_retired,
            death_year_index_per_path=self.death_year_index_per_path,
            portfolio_factors=self.portfolio_factors,
        )


@dataclass
class PriorityScopeWealth:
    """Vermoegenspfad je Finanzierungs-Scope: gemeinsam + ein Replay je Scope.

    ``joint``: der tatsaechlich simulierte gemeinsame Pfad (alle Abfluesse).
    ``liabilities``: der VOLLE Batch (bestimmt, welche Ziele ausserhalb eines
    Scopes liegen -- auch wenn ein Aufrufer nur ein einzelnes Ziel bewertet).
    Replays werden lazy und genau einmal je eindeutigem Scope gerechnet.
    """

    joint: np.ndarray
    liabilities: Sequence[GoalLiability]
    replay: ScopeReplayInputs | None = None
    _cache: dict = field(default_factory=dict, repr=False)
    _keys: dict = field(default_factory=dict, repr=False)

    @property
    def replay_count(self) -> int:
        return len(self._cache)

    def _scope_key(self, goal: GoalLiability):
        """``(scope_path, entfallende Freigaben)`` oder None (Scope = gemeinsamer Pfad); je Objekt gecacht."""
        entry = self._keys.get(id(goal))
        if entry is not None and entry[0] is goal:
            return entry[1]
        key = None
        if _scope_differs(goal):
            # Schluessel = was die Simulation tatsaechlich bestimmt: der
            # Scope-Liability-Pfad und die mit ihm entfallenden Reserve-
            # Freigaben. Ein Rang ohne eigene Abfluesse (z.B. reines
            # Vermoegensziel) teilt so den Replay des naechsthoeheren Rangs.
            released = {
                str(goal_id)
                for goal_id, _series in (
                    self.replay.goal_reserve_release_series_rappen if self.replay else ()
                )
            }
            excluded = tuple(
                goal_id for goal_id in self._excluded_ids(int(getattr(goal, "rank", 1) or 1))
                if goal_id in released
            )
            key = (_as_int_tuple(goal.priority_scope_liability_path_rappen), excluded)
        self._keys[id(goal)] = (goal, key)
        return key

    def _excluded_ids(self, rank: int) -> list[str]:
        return sorted({
            str(other.goal_id) for other in self.liabilities
            if int(getattr(other, "rank", 1) or 1) > rank
        })

    def _check_batch(self, goal: GoalLiability, replay: ScopeReplayInputs) -> None:
        joint_path = _as_int_tuple(goal.joint_liability_path_rappen)
        bound = replay.joint_liability_path_rappen
        if bound is not None:
            horizon = max(len(joint_path), len(bound))
            if (joint_path + (0,) * horizon)[:horizon] != (tuple(bound) + (0,) * horizon)[:horizon]:
                raise PriorityScopeUnavailableError(
                    f"Ziel {goal.goal_id!r} stammt aus einem anderen Liability-"
                    "Batch als der gemeinsame Pfad (joint_liability_path weicht ab)."
                )

    def for_goal(self, goal: GoalLiability) -> np.ndarray:
        """Der fuer ``goal`` massgebliche Vermoegenspfad."""
        key = self._scope_key(goal)
        if key is None:
            return self.joint
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        replay = self.replay
        if replay is None:
            raise PriorityScopeUnavailableError(
                f"Ziel {goal.goal_id!r} (Rang {goal.rank}) hat einen eigenen "
                "Prioritaets-Scope, aber keinen Replay-Kontext. Eine "
                "Rueckwaertsrekonstruktion aus dem gemeinsamen Pfad ist nicht "
                "exakt (Cashflows, Mortalitaet, W2.5, Steuer) und entfaellt."
            )
        self._check_batch(goal, replay)
        # Alle noch offenen abweichenden Scopes des Batches in einem Lauf
        # (ein Replay je eindeutigem Scope; steuerfrei ab dem ersten abweichenden Jahr).
        pending = {key: goal}
        for other in self.liabilities:
            other_key = self._scope_key(other)
            if other_key is not None and other_key not in self._cache and other_key not in pending:
                self._check_batch(other, replay)
                pending[other_key] = other
        keys = sorted(pending)
        results = replay.simulate_many(
            [(list(scope_path), list(excluded)) for scope_path, excluded in keys],
            joint=self.joint,
        )
        for pending_key, result in zip(keys, results):
            self._cache[pending_key] = result
        return self._cache[key]

    def subset(self, index) -> "PriorityScopeWealth":
        """Dieselben Scopes, eingeschraenkt auf die Pfade ``index``.

        Fuer gepaarte Bootstrap-Vergleiche: alle abweichenden Scopes werden
        zuerst auf dem vollen Wuerfel simuliert (die Steuer-Modi ``median``/
        ``binned`` haengen von Querschnittsstatistiken ueber ALLE Pfade ab),
        danach wird nur noch ausgewaehlt. Das Ergebnis hat keinen
        Replay-Kontext mehr.
        """
        for goal in self.liabilities:
            if self._scope_key(goal) is not None:
                self.for_goal(goal)
        subset = PriorityScopeWealth(
            joint=self.joint[index], liabilities=self.liabilities, replay=None,
        )
        subset._cache = {key: value[index] for key, value in self._cache.items()}
        subset._keys = dict(self._keys)
        return subset

    def verify_joint_parity(self) -> None:
        """Bindet ``joint`` an den Replay-Kontext (fail-closed bei Abweichung).

        Ein gemeinsamer Pfad, der nicht aus genau diesem Kontext stammt, darf
        keine Scope-Replays tragen -- sonst vergleicht die Publikation zwei
        verschiedene Plaene.
        """
        replay = self.replay
        if replay is None or not any(_scope_differs(g) for g in self.liabilities):
            return
        bound = replay.joint_liability_path_rappen
        expected = replay.simulate(None if bound is None else list(bound))
        joint = np.asarray(self.joint, dtype=np.float64)
        if expected.shape != joint.shape or not np.allclose(
            expected, joint, rtol=0.0, atol=1e-6,
        ):
            raise PriorityScopeUnavailableError(
                "Gemeinsamer Vermoegenspfad und Replay-Kontext stimmen nicht "
                "ueberein; Prioritaets-Scopes sind so nicht bewertbar."
            )


def scope_wealth_for(
    wealth_paths: np.ndarray,
    liabilities: Sequence[GoalLiability],
    scope_wealth: PriorityScopeWealth | None,
) -> PriorityScopeWealth:
    """``scope_wealth`` oder ein Kontext-loser Wrapper um ``wealth_paths``.

    Der Wrapper liefert fuer Ziele ohne eigenen Scope den gegebenen Pfad und
    bricht fuer abweichende Scopes fail-closed ab.
    """
    if scope_wealth is not None:
        return scope_wealth
    return PriorityScopeWealth(joint=wealth_paths, liabilities=list(liabilities))


def goal_release_series_from_ledger(ledger, horizon: int) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Ziel-Freigaben eines ``ReserveFundingLedgerV1`` je Ziel-ID (sortiert)."""
    if ledger is None:
        return ()
    by_goal: dict[str, list[int]] = {}
    for release in getattr(ledger, "releases", ()) or ():
        if str(getattr(release, "destination_kind", "")) != "goal":
            continue
        index = int(release.year_index)
        if not 0 <= index < int(horizon):
            continue
        series = by_goal.setdefault(str(release.destination_id), [0] * int(horizon))
        series[index] += int(release.amount_rappen)
    return tuple((goal_id, tuple(by_goal[goal_id])) for goal_id in sorted(by_goal))


def release_mapping(
    series: Mapping[str, Sequence[int]] | Iterable[tuple[str, Sequence[int]]] | None,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Kanonische, unveraenderliche Form der Freigaben je Ziel."""
    if not series:
        return ()
    items = series.items() if isinstance(series, Mapping) else series
    return tuple(sorted((str(k), _as_int_tuple(v)) for k, v in items))


__all__ = [
    "PRIORITY_SCOPE_POLICY_VERSION",
    "PriorityScopeUnavailableError",
    "PriorityScopeWealth",
    "ScopeReplayInputs",
    "goal_release_series_from_ledger",
    "release_mapping",
    "scope_wealth_for",
]
