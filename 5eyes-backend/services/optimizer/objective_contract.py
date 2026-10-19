"""Ein unveraenderlicher Objective-Vertrag pro Solver-Lauf.

OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001
=======================================

Befund
------
``resolve_objective_mode()`` und ``resolve_goal_weighting_mode()`` sind
beides bewusste LIVE-Reads der Umgebung -- und beide wurden pro Lauf viele
Male aufgerufen. Gemessen (tests/test_optimizer_objective_mode_not_frozen_per_run.py):
**205 Aufrufe des Primaermodus in einem einzigen Solver-Lauf**; der
Goal-Weighting-Modus noch oefter, weil ``_effective_hardness_weight()`` ihn
pro ZIEL pro Bewertung liest.

Aendert sich die Umgebung waehrend eines Laufs, bewertet SLSQP einen Teil
der Kandidaten nach dem einen Primaerterm und den Rest nach einem anderen --
etwa einen Drawdown-Anteil gegen eine Renditestandardabweichung. Das
Ergebnis loest dann kein wohldefiniertes Optimierungsproblem mehr, und
nichts erkennt es: der persistierte Nachweis nennt genau einen Modus,
naemlich den, der beim Bauen des Modell-Basis-Blocks gerade gilt.

Der Fehler ist NICHT der Live-Read. Dass eine Konfigurationsaenderung beim
naechsten Lauf ohne Prozessneustart wirkt, ist gewollt und bleibt. Der
Fehler ist, dass der gelesene Wert nicht EINMAL PRO LAUF eingefroren und
dann durchgereicht wurde. Genau diese Luecke vermerkt der Docstring von
``resolve_goal_weighting_mode()`` selbst als offene Arbeit
("binding the resolved mode into one immutable per-run ObjectiveContract ...
is tracked as further work", Zertifizierungs-Spezifikation Abschnitt
6.2-6.3).

Warum ein gemeinsames Objekt und nicht zwei eingefrorene Strings
----------------------------------------------------------------
Die beiden Modi beschreiben zusammen EINE Mathematik: welcher Primaerterm
minimiert wird und wie die Ziele darin gewichtet sind. Zwei separat
eingefrorene Werte koennten paarweise auseinanderlaufen (einer aus dem
Context, einer frisch gelesen) -- und genau dieses Auseinanderlaufen ist der
Befund. Ein Vertrag, der als Ganzes weitergegeben wird, kann das
strukturell nicht.

Der Hash
--------
``contract_hash`` identifiziert den Vertrag, nicht nur einen seiner Teile.
Damit ist rekonstruierbar, welche Mathematik eine einzelne Kandidaten-
bewertung verwendet hat -- die Forderung aus der negativen Abnahmematrix
des Review-Dokuments ("Der gespeicherte Objective-Contract-Hash
rekonstruiert exakt den Vertrag, den jede einzelne Kandidatenbewertung
verwendet hat").

Die Hash-Eingabe ist bewusst ein VERSIONIERTER, feldbenannter String und
keine Tupel-Konkatenation: kommt spaeter ein Feld hinzu (Tail-Fraction,
Chance-Penalty-Policy, Drawdown-Refinement-Policy), aendert sich der Hash
nachvollziehbar, und zwei Vertraege verschiedener Versionen koennen nicht
denselben Hash tragen.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from config import validate_goal_weighting_mode, validate_objective_mode

# Vertragsversion. Steigt, sobald sich die Menge der gebundenen Felder oder
# die Hash-Eingabe aendert -- nicht bei einer Aenderung der WERTE.
OBJECTIVE_CONTRACT_VERSION = "objective-contract-v1"


class ObjectiveContractError(ValueError):
    """Fehlender oder unzulaessiger Objective-Vertrag (nie ein Fallback)."""


@dataclass(frozen=True)
class ObjectiveContractV1:
    """Die Mathematik EINES Laufs, einmal aufgeloest und danach unveraenderlich.

    Beide Felder werden beim Bau des ``OptimizerContext`` genau einmal aus
    der Umgebung aufgeloest und von dort an jeden Konsumenten durchgereicht:
    Objective, Post-Round-Evaluation, Gewinner-Nachrechnung, Modellbasis,
    Sensitivity, Persistenz und Publikation.
    """

    objective_mode: str
    goal_weighting_mode: str
    version: str = OBJECTIVE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        # Fail-closed auch beim direkten Bau: ein Vertrag mit einem ungueltigen
        # Modus darf nicht existieren koennen. Sonst waere der Hash zwar
        # stabil, wuerde aber eine Mathematik identifizieren, die es nicht
        # gibt. `validate_*` sind dieselben zentralen Validatoren, die die
        # Live-Reads benutzen -- kein zweites Regelwerk.
        validate_objective_mode(self.objective_mode)
        validate_goal_weighting_mode(self.goal_weighting_mode)
        if self.version != OBJECTIVE_CONTRACT_VERSION:
            raise ObjectiveContractError(
                f"Unbekannte Objective-Vertragsversion: {self.version!r}"
            )

    @property
    def contract_hash(self) -> str:
        """SHA-256 ueber die feldbenannte, versionierte Vertragsdarstellung."""
        payload = "|".join([
            f"version={self.version}",
            f"objective_mode={self.objective_mode}",
            f"goal_weighting_mode={self.goal_weighting_mode}",
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_evidence(self) -> dict[str, str]:
        """Nachweis-Block fuer Persistenz und Publikation.

        Derselbe Block fuer jeden Kanal -- damit API, Modellbasis,
        OptimizerRun und TargetAllocation nicht je eigene Teilmengen
        ausweisen, die sich nicht gegeneinander pruefen lassen.
        """
        return {
            "objective_contract_version": self.version,
            "objective_mode": self.objective_mode,
            "goal_weighting_mode": self.goal_weighting_mode,
            "objective_contract_hash": self.contract_hash,
        }


OBJECTIVE_CONTRACT_V2_VERSION = "objective-contract-v2"


def implemented_objective_policy() -> dict:
    """Koeffizienten, Scopes und Policy-Versionen, die DIESER Code rechnet.

    OBJECTIVE-CROSS-TERM-GOVERNANCE-001 (Codex-Review PR #626): V1 band nur
    die beiden Modi; jede Konstantenaenderung ergab denselben Hash fuer eine
    andere Mathematik. V2 bindet jeden Wert, der die Zielfunktion des
    Default-Pfads bestimmt. Lazy Imports: Modul-Topologie unveraendert.
    """
    from .allocation_intent import (
        SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT,
        SOFT_PREFERENCE_POLICY_VERSION,
    )
    from .goal_reachability import GOAL_REACHABILITY_SCREEN_VERSION
    from .house_prior import HOUSE_PRIOR_KAPPA, HOUSE_PRIOR_VERSION
    from .objective import (
        CHANCE_PENALTY_WEIGHT,
        DEMOTED_GOAL_POLICY_VERSION,
        DEMOTED_GOAL_WEIGHT,
        GOAL_EROSION_NUMERIC_TOL,
        GOAL_EROSION_Z,
        GOAL_HARDNESS_POLICY_VERSION,
        GOAL_HIERARCHY_POLICY_VERSION,
        HARDNESS_WEIGHT,
        MAXIMIZE_GOAL_POLICY_VERSION,
        MAXIMIZE_GROWTH_WEIGHT,
        TIEBREAK_VARIANCE_WEIGHT,
    )

    return {
        "goal_hardness_policy": GOAL_HARDNESS_POLICY_VERSION,
        "hardness_weights": tuple(sorted(
            (str(k), float(v)) for k, v in HARDNESS_WEIGHT.items()
        )),
        "goal_hierarchy_policy": GOAL_HIERARCHY_POLICY_VERSION,
        "goal_hierarchy_scope": "goal_shortfall_mode_only",
        "protected_hardness": ("hart", "primaer"),
        "goal_erosion_z": float(GOAL_EROSION_Z),
        "goal_erosion_numeric_tol": float(GOAL_EROSION_NUMERIC_TOL),
        "maximize_goal_policy": MAXIMIZE_GOAL_POLICY_VERSION,
        "maximize_growth_weight": float(MAXIMIZE_GROWTH_WEIGHT),
        "chance_penalty_policy": "linear_wilson_lb_soft_regret_v1",
        "chance_penalty_weight": float(CHANCE_PENALTY_WEIGHT),
        "tiebreak_policy": "portfolio_variance_one_year_v1",
        "tiebreak_weight": float(TIEBREAK_VARIANCE_WEIGHT),
        "house_prior_policy": HOUSE_PRIOR_VERSION,
        "house_prior_kappa": float(HOUSE_PRIOR_KAPPA),
        "soft_preference_policy": SOFT_PREFERENCE_POLICY_VERSION,
        "soft_preference_lambda_default": float(SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT),
        "goal_reachability_policy": GOAL_REACHABILITY_SCREEN_VERSION,
        "goal_normalization": "relative_to_initial_wealth_squared_v1",
        # GOAL-HIERARCHY-002 / STAGE2-OBJECTIVE-SCALE-001 (CIO-Review #650).
        "goal_demotion_policy": DEMOTED_GOAL_POLICY_VERSION,
        "demoted_goal_weight": float(DEMOTED_GOAL_WEIGHT),
        "stage2_objective_scale_policy": "slsqp_relative_ftol_max1_v1",
    }


_POLICY_FIELDS = (
    "goal_hardness_policy",
    "hardness_weights",
    "goal_hierarchy_policy",
    "goal_hierarchy_scope",
    "protected_hardness",
    "goal_erosion_z",
    "goal_erosion_numeric_tol",
    "maximize_goal_policy",
    "maximize_growth_weight",
    "chance_penalty_policy",
    "chance_penalty_weight",
    "tiebreak_policy",
    "tiebreak_weight",
    "house_prior_policy",
    "house_prior_kappa",
    "soft_preference_policy",
    "soft_preference_lambda_default",
    "goal_reachability_policy",
    "goal_normalization",
    "goal_demotion_policy",
    "demoted_goal_weight",
    "stage2_objective_scale_policy",
)


@dataclass(frozen=True)
class ObjectiveContractV2(ObjectiveContractV1):
    """V1 + alle Koeffizienten, Scopes und Policies (Engine ``saa_resampled_v7``).

    Unterklasse von V1: jeder Konsument, der einen V1-Vertrag akzeptiert
    (``objective_contract_of``), akzeptiert V2. Felder ohne Angabe werden
    mit den IMPLEMENTIERTEN Werten belegt; ein explizit anderer Wert ist
    fail-closed unzulaessig -- ein Vertrag darf keine Mathematik beschreiben,
    die dieser Code nicht rechnet (Replay einer alten Vertragsversion auf
    neuem Code bricht damit laut ab statt still anders zu rechnen).
    """

    version: str = OBJECTIVE_CONTRACT_V2_VERSION
    goal_hardness_policy: str | None = None
    hardness_weights: tuple | None = None
    goal_hierarchy_policy: str | None = None
    goal_hierarchy_scope: str | None = None
    protected_hardness: tuple | None = None
    goal_erosion_z: float | None = None
    goal_erosion_numeric_tol: float | None = None
    maximize_goal_policy: str | None = None
    maximize_growth_weight: float | None = None
    chance_penalty_policy: str | None = None
    chance_penalty_weight: float | None = None
    tiebreak_policy: str | None = None
    tiebreak_weight: float | None = None
    house_prior_policy: str | None = None
    house_prior_kappa: float | None = None
    soft_preference_policy: str | None = None
    soft_preference_lambda_default: float | None = None
    goal_reachability_policy: str | None = None
    goal_normalization: str | None = None
    goal_demotion_policy: str | None = None
    demoted_goal_weight: float | None = None
    stage2_objective_scale_policy: str | None = None

    def __post_init__(self) -> None:
        validate_objective_mode(self.objective_mode)
        validate_goal_weighting_mode(self.goal_weighting_mode)
        if self.version != OBJECTIVE_CONTRACT_V2_VERSION:
            raise ObjectiveContractError(
                f"Unbekannte Objective-Vertragsversion: {self.version!r}"
            )
        implemented = implemented_objective_policy()
        for name in _POLICY_FIELDS:
            value = getattr(self, name)
            if value is None:
                object.__setattr__(self, name, implemented[name])
            elif value != implemented[name]:
                raise ObjectiveContractError(
                    f"Objective-Vertrag verlangt {name}={value!r}, dieser Code "
                    f"rechnet {implemented[name]!r} -- kein stiller Replay mit "
                    "anderer Mathematik."
                )

    @property
    def contract_hash(self) -> str:
        """SHA-256 ueber Version, Modi und ALLE Policy-Felder (feldbenannt)."""
        parts = [
            f"version={self.version}",
            f"objective_mode={self.objective_mode}",
            f"goal_weighting_mode={self.goal_weighting_mode}",
        ]
        parts.extend(f"{name}={getattr(self, name)!r}" for name in _POLICY_FIELDS)
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def as_evidence(self) -> dict:
        evidence = {
            "objective_contract_version": self.version,
            "objective_mode": self.objective_mode,
            "goal_weighting_mode": self.goal_weighting_mode,
        }
        for name in _POLICY_FIELDS:
            value = getattr(self, name)
            evidence[name] = list(value) if isinstance(value, tuple) else value
        evidence["hardness_weights"] = {
            str(k): float(v) for k, v in self.hardness_weights
        }
        evidence["objective_contract_hash"] = self.contract_hash
        return evidence


def resolve_objective_contract() -> ObjectiveContractV1:
    """Loest den Vertrag aus der Umgebung auf -- GENAU EINMAL pro Lauf.

    Aufrufstelle ist ``build_optimizer_context()``. Jeder weitere Konsument
    nimmt den Vertrag aus dem Context, nie erneut aus der Umgebung; sonst
    waere der Befund nur verschoben.

    Die Imports liegen absichtlich in der Funktion: ``objective.py`` und
    ``objective_variants.py`` importieren einander lazy, und dieses Modul
    soll an dieser Topologie nichts aendern.
    """
    from .objective import resolve_goal_weighting_mode
    from .objective_variants import resolve_objective_mode

    # Engine v7: V2 (alle Koeffizienten/Policies gebunden).
    return ObjectiveContractV2(
        objective_mode=resolve_objective_mode(),
        goal_weighting_mode=resolve_goal_weighting_mode(),
    )


def objective_contract_of(context: object) -> ObjectiveContractV1:
    """Der Vertrag eines Contexts -- fail-closed.

    Ein Context ohne Vertrag ist KEIN Grund, die Umgebung erneut zu lesen:
    das waere genau der stille Rueckfall, den dieser Befund beschreibt. Ein
    Lauf ohne eingefrorene Mathematik hat keinen Nachweis darueber, was er
    gerechnet hat, und darf deshalb nicht laufen.
    """
    contract = getattr(context, "objective_contract", None)
    if contract is None:
        raise ObjectiveContractError(
            "OptimizerContext ohne eingefrorenen ObjectiveContractV1 -- der "
            "Lauf koennte nicht nachweisen, welche Mathematik ihn erzeugt "
            "hat. Context ueber build_optimizer_context() bauen oder den "
            "Vertrag explizit setzen."
        )
    if not isinstance(contract, ObjectiveContractV1):
        raise ObjectiveContractError(
            f"objective_contract hat den falschen Typ: {type(contract)!r}"
        )
    return contract
