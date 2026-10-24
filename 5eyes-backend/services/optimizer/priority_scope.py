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


# Vorbereitete Scope-Eingaben je Plan-Signatur (Inhalt der Cashflows, des
# gemeinsamen Liability-Pfads und der Freigaben). Reine Performance im
# Solver-Hotpath (je Auswertung ein neuer Replay-Kontext), keine Semantik.
_PREPARED_SCOPES: dict = {}
# Identitaets-Abkuerzung darauf (die Eintraege halten die Objekte, ids bleiben
# damit eindeutig; nur fuer unveraenderliche Tupel).
_PREPARED_BY_IDENTITY: dict = {}
# Scope-Schluessel und Batch-Pruefung je Liability-Liste (Identitaet, die
# Liste wird im Eintrag gehalten) und (Freigaben, gemeinsamer Pfad).
_BATCH_KEYS: dict = {}


class PriorityScopeUnavailableError(ValueError):
    """Ein Prioritaets-Scope weicht vom gemeinsamen Pfad ab, aber es fehlt
    der Replay-Kontext, um ihn direkt zu simulieren."""


def _scope_differs(goal: GoalLiability) -> bool:
    scope = goal.priority_scope_liability_path_rappen
    joint = goal.joint_liability_path_rappen
    if not scope or not joint:
        return False
    return [int(v) for v in scope] != [int(v) for v in joint]


def _last_read_column(goal: GoalLiability, n_cols: int) -> int:
    """Hoechste Spalte des Vermoegenspfads, die die Bewertung von ``goal`` liest.

    Spiegelt ``objective.shortfall_squared_per_path``/``_goal_probability_core``/
    ``_success_margin_per_path``/``maximize_growth_per_path`` und die
    Failure-Events in ``goal_attribution`` (Spalten 1..letzte Bewertungsspalte).
    """
    last = max(1, int(n_cols) - 1)
    kind = goal.target_kind
    if kind == "wealth_at_t":
        return max(1, min(int(goal.target_year_index), last))
    if kind in ("cashflow_in_year", "outflow_stream"):
        due = [
            index + 1
            for index, amount in enumerate(goal.liability_path_rappen or ())
            if float(amount or 0) > 0.0 and index + 1 < int(n_cols)
        ]
        return max(due) if due else 0
    if kind in ("return_rate", "maximize"):
        return max(1, min(int(goal.target_year_index or last), last))
    return last


def _as_int_tuple(values: Iterable[int] | None) -> tuple[int, ...]:
    return tuple(int(v) for v in (values or ()))


def _batch_identity(goal: GoalLiability) -> tuple:
    """Was ein Ziel im Batch bestimmt (Scope-, Rang- und Pfadbezug)."""
    return (
        str(goal.goal_id),
        int(getattr(goal, "rank", 1) or 1),
        str(goal.target_kind),
        int(goal.target_amount_rappen or 0),
        int(goal.target_year_index or 0),
        _as_int_tuple(goal.liability_path_rappen),
        _as_int_tuple(goal.priority_scope_liability_path_rappen),
        _as_int_tuple(goal.joint_liability_path_rappen),
    )


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
    # DYNAMIC-RETIREMENT-PHASE-001: derselbe Jahres-Status wie im gemeinsamen Pfad.
    is_retired_series: tuple[bool, ...] | None = None

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

    def prepare_scope(
        self,
        liability_path_rappen: Sequence[int],
        excluded_release_goal_ids: Iterable[str],
    ) -> tuple[np.ndarray, np.ndarray, int]:
        """``(Cashflow, Liability, erstes abweichendes Jahr)`` eines Scopes.

        Reine Funktion der eingefrorenen Plan-Inputs (Cashflows, gemeinsamer
        Liability-Pfad, Freigaben, Horizont) -- im Solver je Kontext einmal
        berechnet und danach wiederverwendet (Cache nach Inhalt).
        """
        horizon = int(np.asarray(self.return_paths).shape[1])
        excluded = tuple(sorted(str(g) for g in excluded_release_goal_ids))
        path_key = (
            liability_path_rappen if isinstance(liability_path_rappen, tuple)
            else tuple(int(v) for v in liability_path_rappen)
        )
        key = (path_key, excluded)
        # Schneller Weg: dieselben (unveraenderlichen) Tupel-Objekte wie beim
        # letzten Aufruf -> kein Neuaufbau der Inhaltssignatur.
        identity = (
            horizon, id(self.cashflow_series_rappen),
            id(self.joint_liability_path_rappen),
            id(self.goal_reserve_release_series_rappen),
        )
        fast = _PREPARED_BY_IDENTITY.get(identity)
        if fast is not None and fast[0] is self.cashflow_series_rappen and (
            fast[1] is self.joint_liability_path_rappen
        ) and fast[2] is self.goal_reserve_release_series_rappen and isinstance(
            self.cashflow_series_rappen, tuple
        ) and isinstance(self.joint_liability_path_rappen, (tuple, type(None))):
            cache = fast[3]
        else:
            signature = (
                horizon,
                tuple(int(v) for v in self.cashflow_series_rappen),
                None if self.joint_liability_path_rappen is None
                else tuple(int(v) for v in self.joint_liability_path_rappen),
                self.goal_reserve_release_series_rappen,
            )
            cache = _PREPARED_SCOPES.get(signature)
            if cache is None:
                if len(_PREPARED_SCOPES) >= 64:
                    _PREPARED_SCOPES.pop(next(iter(_PREPARED_SCOPES)))
                cache = _PREPARED_SCOPES[signature] = {}
            if len(_PREPARED_BY_IDENTITY) >= 64:
                _PREPARED_BY_IDENTITY.pop(next(iter(_PREPARED_BY_IDENTITY)))
            _PREPARED_BY_IDENTITY[identity] = (
                self.cashflow_series_rappen, self.joint_liability_path_rappen,
                self.goal_reserve_release_series_rappen, cache,
            )
        hit = cache.get(key)
        if hit is not None:
            return hit

        def _padded(values) -> np.ndarray:
            out = np.zeros(horizon, dtype=np.float64)
            arr = np.asarray(list(values or ()), dtype=np.float64)
            n = min(horizon, arr.size)
            out[:n] = arr[:n]
            return out

        cashflow = _padded(self._scope_cashflow(excluded))
        liability = _padded(key[0])
        if self.joint_liability_path_rappen is None:
            divergence = 0
        else:
            differs = (cashflow != _padded(self.cashflow_series_rappen)) | (
                liability != _padded(self.joint_liability_path_rappen)
            )
            divergence = int(np.argmax(differs)) if differs.any() else horizon
        cashflow.setflags(write=False)
        liability.setflags(write=False)
        prepared = (cashflow, liability, divergence)
        cache[key] = prepared
        return prepared

    def simulate_many(
        self,
        scopes: Sequence[tuple[Sequence[int], Iterable[str]]],
        *,
        joint: np.ndarray | None = None,
        stops: Sequence[int] | None = None,
    ) -> list[np.ndarray]:
        """Mehrere Scopes -- auf allen bewerteten Spalten bitidentisch zu einem
        direkten ``simulate``.

        Ohne Steuer ist jeder Pfad unabhaengig (keine Querschnittsstatistik):

        * bis zum ersten Jahr ``t0``, in dem Cashflow oder Liability des
          Scopes vom gemeinsamen Lauf abweichen, sind beide Rekursionen
          Operation fuer Operation identisch -- Spalten ``0..t0`` kommen aus
          ``joint``;
        * ab ``t0`` wird mit genau den Operationen des steuerfreien Kerns
          (``scenario_engine._simulate_wealth_paths_untaxed``) weitergerechnet,
          aber nur bis zur Spalte ``stops[i]`` -- der letzten Spalte, die ein
          Ziel dieses Scopes ueberhaupt liest. Spalten danach sind ``NaN``
          (nie gelesen; ein Fehlzugriff wuerde laut statt still falsch).

        Mit Steuer haengen ``median``/``binned`` vom Querschnitt aller Pfade
        ab -- dann je Scope ein vollstaendiger direkter Aufruf ab Jahr 0.
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
        factors = np.asarray(factors, dtype=np.float64)
        death_idx = None
        if self.death_year_index_per_path is not None:
            death_idx = np.asarray(self.death_year_index_per_path, dtype=np.int32)
            if death_idx.shape != (n_paths,):
                raise ValueError(
                    f"death_year_index_per_path must be shape ({n_paths},), got {death_idx.shape}"
                )
        joint_arr = None
        if joint is not None and self.joint_liability_path_rappen is not None:
            candidate = np.asarray(joint, dtype=np.float64)
            if candidate.shape == (n_paths, horizon + 1):
                joint_arr = candidate

        results: list[np.ndarray] = []
        grown = np.empty(n_paths, dtype=np.float64)
        positive = np.empty(n_paths, dtype=bool)
        for index, (path, excluded) in enumerate(scopes):
            cashflow, liability, divergence = self.prepare_scope(path, excluded)
            stop = horizon if stops is None else max(0, min(horizon, int(stops[index])))
            if joint_arr is not None:
                start = min(divergence, stop)
                out = joint_arr.copy()
            else:
                start = 0
                out = np.empty((n_paths, horizon + 1), dtype=np.float64)
                out[:, 0] = float(self.initial_wealth_rappen)
            prev = np.ascontiguousarray(out[:, start])
            for t in range(start, stop):
                np.greater(prev, 0, out=positive)
                np.copyto(grown, prev)
                np.multiply(prev, factors[:, t], out=grown, where=positive)
                nxt = np.empty(n_paths, dtype=np.float64)
                if death_idx is not None:
                    alive = t < death_idx
                    np.add(grown, cashflow[t] * alive, out=nxt)
                    np.subtract(nxt, liability[t] * alive, out=nxt)
                else:
                    np.add(grown, cashflow[t], out=nxt)
                    if liability[t] != 0.0:
                        np.subtract(nxt, liability[t], out=nxt)
                out[:, t + 1] = nxt
                prev = nxt
            if stop < horizon:
                out[:, stop + 1:] = np.nan
            out.setflags(write=False)
            results.append(out)
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
            is_retired_series=self.is_retired_series,
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
    _checked: set = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        # Schluessel und Batch-Pruefung je (Liability-Liste, Freigaben,
        # gemeinsamer Pfad) nur einmal -- im Solver entsteht je Auswertung ein
        # neues Objekt fuer denselben Batch.
        if self.replay is None:
            return
        signature = (
            self.replay.goal_reserve_release_series_rappen,
            None if self.replay.joint_liability_path_rappen is None
            else tuple(self.replay.joint_liability_path_rappen),
        )
        entry = _BATCH_KEYS.get(id(self.liabilities))
        if entry is not None and entry[0] is self.liabilities and entry[1] == signature:
            self._keys = entry[2]
            self._checked = entry[3]
            return
        if len(_BATCH_KEYS) >= 64:
            _BATCH_KEYS.pop(next(iter(_BATCH_KEYS)))
        _BATCH_KEYS[id(self.liabilities)] = (
            self.liabilities, signature, self._keys, self._checked,
        )

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

    def _needed_column(self, key, n_cols: int) -> int:
        """Letzte Vermoegensspalte, die ein Ziel mit Scope ``key`` liest.

        Dieselben Spalten wie die Bewertung in ``objective``/``goal_attribution``
        (Faelligkeiten, Zieljahr, Renditehorizont); unbekannte Zielarten lesen
        konservativ den ganzen Pfad.
        """
        needed = 0
        for goal in self.liabilities:
            if self._scope_key(goal) != key:
                continue
            needed = max(needed, _last_read_column(goal, n_cols))
        return needed

    def _excluded_ids(self, rank: int) -> list[str]:
        return sorted({
            str(other.goal_id) for other in self.liabilities
            if int(getattr(other, "rank", 1) or 1) > rank
        })

    def _check_batch(self, goal: GoalLiability, replay: ScopeReplayInputs) -> None:
        if id(goal) in self._checked:
            return
        joint_path = _as_int_tuple(goal.joint_liability_path_rappen)
        bound = replay.joint_liability_path_rappen
        if bound is not None:
            horizon = max(len(joint_path), len(bound))
            if (joint_path + (0,) * horizon)[:horizon] != (tuple(bound) + (0,) * horizon)[:horizon]:
                raise PriorityScopeUnavailableError(
                    f"Ziel {goal.goal_id!r} stammt aus einem anderen Liability-"
                    "Batch als der gemeinsame Pfad (joint_liability_path weicht ab)."
                )
        self._checked.add(id(goal))

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
        n_cols = int(np.asarray(self.joint).shape[1])
        results = replay.simulate_many(
            [(scope_path, excluded) for scope_path, excluded in keys],
            joint=self.joint,
            stops=[self._needed_column(k, n_cols) for k in keys],
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
        subset._keys = self._keys
        return subset

    def verify_publication_binding(
        self,
        wealth_paths: np.ndarray,
        liabilities: Sequence[GoalLiability],
    ) -> None:
        """Bindet eine Publikation an genau diesen Wrapper (fail-closed).

        GOAL-ACHIEVABILITY-ATTRIBUTION-001 (Restbefund PR #659): die
        Zielzeilen lesen ``for_goal`` (also ``self.joint`` oder einen Replay
        davon), die Plan-Solvenz liest den separat uebergebenen
        ``wealth_paths``. Beide muessen derselbe Pfad sein -- bit-genau, nicht
        nur im Endwert -- und die publizierten Ziele derselbe Batch, aus dem
        die Scopes gebildet wurden. Sonst stammen Zielzeilen und Plan-Solvenz
        aus zwei verschiedenen Plaenen. Reine Pruefung, keine Rechnung.
        """
        joint = np.asarray(self.joint)
        if wealth_paths is not self.joint and not (
            joint.shape == np.shape(wealth_paths)
            and np.array_equal(joint, wealth_paths, equal_nan=True)
        ):
            raise PriorityScopeUnavailableError(
                "Publizierter gemeinsamer Vermoegenspfad und Scope-Wrapper "
                "stammen nicht aus demselben Plan; keine Zielzeile ohne "
                "eindeutige Pfadquelle."
            )
        if sorted(map(_batch_identity, liabilities)) != sorted(
            map(_batch_identity, self.liabilities)
        ):
            raise PriorityScopeUnavailableError(
                "Publizierte Ziele und Scope-Wrapper stammen aus "
                "verschiedenen Ziel-Batches."
            )

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
