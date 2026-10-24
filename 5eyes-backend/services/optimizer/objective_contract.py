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
import math
from dataclasses import dataclass
from typing import ClassVar

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
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 (Re-Audit 2026-10-14): die
    # WIRKSAMEN Haertegrad-Multiplikatoren beim Bau, eingefroren. Ohne sie
    # trugen "10x" und "11x" denselben Hash. V1 wurde nie persistiert (die
    # Persistenz kam erst zusammen mit V2), es gibt also keinen historischen
    # V1-Hash, den diese Erweiterung umdeuten koennte.
    hardness_weights: tuple | None = None

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
        if self.hardness_weights is None:
            from .objective import HARDNESS_WEIGHT

            object.__setattr__(
                self, "hardness_weights", _canonical_hardness(HARDNESS_WEIGHT),
            )

    @property
    def contract_hash(self) -> str:
        """SHA-256 ueber die feldbenannte, versionierte Vertragsdarstellung."""
        return _v1_hash(
            self.version, self.objective_mode, self.goal_weighting_mode,
            self.hardness_weights,
        )

    def as_evidence(self) -> dict:
        """Nachweis-Block fuer Persistenz und Publikation.

        Derselbe Block fuer jeden Kanal -- damit API, Modellbasis,
        OptimizerRun und TargetAllocation nicht je eigene Teilmengen
        ausweisen, die sich nicht gegeneinander pruefen lassen.
        """
        return {
            "objective_contract_version": self.version,
            "objective_mode": self.objective_mode,
            "goal_weighting_mode": self.goal_weighting_mode,
            "hardness_weights": {str(k): float(v) for k, v in self.hardness_weights},
            "objective_contract_hash": self.contract_hash,
        }


def _canonical_hardness(mapping) -> tuple:
    return tuple(sorted((str(k), float(v)) for k, v in dict(mapping).items()))


def _v1_hash(version, objective_mode, goal_weighting_mode, hardness_weights) -> str:
    payload = "|".join([
        f"version={version}",
        f"objective_mode={objective_mode}",
        f"goal_weighting_mode={goal_weighting_mode}",
        f"hardness_weights={tuple(hardness_weights)!r}",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    from .priority_scope import PRIORITY_SCOPE_POLICY_VERSION
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
        # GOAL-HIERARCHY-ALL-OBJECTIVES-001 (Engine v15): Stufe 1 in jedem
        # Modus; bis v14 "goal_shortfall_mode_only".
        "goal_hierarchy_scope": "all_objectives",
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
        # GOAL-OPTIMIZATION-PUBLICATION-SCOPE-SPLIT-001 (Engine v10):
        # Fehlbetrag, Chance-Strafe und Stufe 1 je Ziel auf seinem
        # priorisierten Scope (direkter Replay), wie die Publikation; die
        # Plan-Solvenz ist kein Term der Zielfunktion.
        "goal_evaluation_scope": "priority_funded",
        "goal_scope_replay_policy": PRIORITY_SCOPE_POLICY_VERSION,
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
    "goal_evaluation_scope",
    "goal_scope_replay_policy",
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

    # Versionskennung je Klasse: V3 erbt Felder und Hashrezept, nicht die
    # Kennung (die Kennung ist Teil der Hash-Eingabe).
    _CONTRACT_VERSION: ClassVar[str] = OBJECTIVE_CONTRACT_V2_VERSION
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
    goal_evaluation_scope: str | None = None
    goal_scope_replay_policy: str | None = None

    def __post_init__(self) -> None:
        validate_objective_mode(self.objective_mode)
        validate_goal_weighting_mode(self.goal_weighting_mode)
        if self.version != type(self)._CONTRACT_VERSION:
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
        return _policy_hash(
            self.version, self.objective_mode, self.goal_weighting_mode,
            {name: getattr(self, name) for name in _POLICY_FIELDS},
            _POLICY_FIELDS,
        )

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


def _policy_hash(version, objective_mode, goal_weighting_mode, values, field_names) -> str:
    """Hashrezept von V2/V3: feldbenannter String, Werte als Python-``repr``."""
    parts = [
        f"version={version}",
        f"objective_mode={objective_mode}",
        f"goal_weighting_mode={goal_weighting_mode}",
    ]
    parts.extend(f"{name}={values[name]!r}" for name in field_names)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


OBJECTIVE_CONTRACT_V3_VERSION = "objective-contract-v3"


@dataclass(frozen=True)
class ObjectiveContractV3(ObjectiveContractV2):
    """V2-Felder inklusive Ziel-Scope, unter einer eigenen Kennung.

    OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001, Restbefund B (Review PR #659):
    ``goal_evaluation_scope`` und ``goal_scope_replay_policy`` kamen in die
    Hash-Eingabe von V2, ohne dass die Kennung stieg -- ``objective-contract-v2``
    bezeichnet damit zwei Schemas (22 bzw. 24 Policy-Felder). Neue Laeufe
    tragen V3; V2-Evidence beider Schemas bleibt ueber
    ``verify_objective_contract_evidence`` als V2 pruefbar.
    """

    _CONTRACT_VERSION: ClassVar[str] = OBJECTIVE_CONTRACT_V3_VERSION
    version: str = OBJECTIVE_CONTRACT_V3_VERSION


# Feldsaetze je Kennung, wie sie persistiert wurden. Die zwei V2-Schemas sind
# historisch (V2 vor und nach dem Ziel-Scope); beide werden mit ihrem EIGENEN
# Feldsatz nachgerechnet und nie mit heutigen Defaults aufgefuellt.
_V2_PRE_SCOPE_FIELDS = tuple(
    name for name in _POLICY_FIELDS
    if name not in ("goal_evaluation_scope", "goal_scope_replay_policy")
)
_EVIDENCE_SCHEMAS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    OBJECTIVE_CONTRACT_V2_VERSION: (
        ("v2_policy_22", _V2_PRE_SCOPE_FIELDS),
        ("v2_policy_24", _POLICY_FIELDS),
    ),
    OBJECTIVE_CONTRACT_V3_VERSION: (("v3_policy_24", _POLICY_FIELDS),),
}
_EVIDENCE_HEAD = ("objective_contract_version", "objective_mode", "goal_weighting_mode")
_TUPLE_FIELDS = ("protected_hardness",)

# Status eines persistierten Vertragsnachweises.
CONTRACT_EVIDENCE_VERIFIED = "verified"
CONTRACT_EVIDENCE_UNVERIFIABLE = "unverifiable"
CONTRACT_EVIDENCE_UNKNOWN_VERSION = "unknown_version"
CONTRACT_EVIDENCE_CORRUPT = "corrupt"


def _verification(status: str, evidence, *, schema=None, reason=None) -> dict:
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "status": status,
        "objective_contract_version": evidence.get("objective_contract_version"),
        "objective_contract_hash": evidence.get("objective_contract_hash"),
        "schema": schema,
        "reason": reason,
    }


def _canonical_value(name: str, value):
    if name == "hardness_weights":
        if not isinstance(value, dict):
            raise TypeError("hardness_weights muss ein Mapping sein")
        for weight in value.values():
            _canonical_value("hardness_weight", weight)
        return _canonical_hardness(value)
    if name in _TUPLE_FIELDS:
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"{name} muss eine Liste sein")
        return tuple(value)
    if isinstance(value, bool) or value is None:
        raise TypeError(f"{name} hat keinen zulaessigen Wert")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise TypeError(f"{name} ist nicht endlich")
        return number
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} hat einen unzulaessigen Typ")


def verify_objective_contract_evidence(evidence) -> dict:
    """Prueft einen persistierten Vertragsnachweis streng nach seiner Kennung.

    Rechnet den Hash ausschliesslich aus den gespeicherten Feldern nach --
    nie aus der heutigen Policy oder Umgebung. ``None`` (Bestand ohne
    Nachweis) ist ``unverifiable``; eine unbekannte Kennung, ein fehlendes
    oder ueberzaehliges Feld oder ein abweichender Hash sind fail-closed.
    """
    if evidence is None:
        return _verification(
            CONTRACT_EVIDENCE_UNVERIFIABLE, None,
            reason="kein Vertragsnachweis persistiert (Bestand)",
        )
    if not isinstance(evidence, dict):
        return _verification(CONTRACT_EVIDENCE_CORRUPT, None, reason="kein Objekt")
    version = evidence.get("objective_contract_version")
    stored_hash = evidence.get("objective_contract_hash")
    if not isinstance(stored_hash, str) or len(stored_hash) != 64:
        return _verification(CONTRACT_EVIDENCE_CORRUPT, evidence, reason="Hash fehlt")
    try:
        validate_objective_mode(evidence.get("objective_mode"))
        validate_goal_weighting_mode(evidence.get("goal_weighting_mode"))
    except Exception:  # noqa: BLE001 -- jeder Validierungsfehler ist corrupt
        return _verification(CONTRACT_EVIDENCE_CORRUPT, evidence, reason="Modus ungueltig")
    keys = set(evidence)
    try:
        if version == OBJECTIVE_CONTRACT_VERSION:
            if keys != {*_EVIDENCE_HEAD, "hardness_weights", "objective_contract_hash"}:
                return _verification(CONTRACT_EVIDENCE_CORRUPT, evidence, reason="Feldsatz")
            schema = "v1"
            recomputed = _v1_hash(
                version, evidence["objective_mode"], evidence["goal_weighting_mode"],
                _canonical_value("hardness_weights", evidence["hardness_weights"]),
            )
        elif version in _EVIDENCE_SCHEMAS:
            for schema, fields in _EVIDENCE_SCHEMAS[version]:
                if keys == {*_EVIDENCE_HEAD, *fields, "objective_contract_hash"}:
                    break
            else:
                return _verification(CONTRACT_EVIDENCE_CORRUPT, evidence, reason="Feldsatz")
            recomputed = _policy_hash(
                version, evidence["objective_mode"], evidence["goal_weighting_mode"],
                {name: _canonical_value(name, evidence[name]) for name in fields},
                fields,
            )
        else:
            return _verification(
                CONTRACT_EVIDENCE_UNKNOWN_VERSION, evidence,
                reason=f"unbekannte Vertragskennung {version!r}",
            )
    except TypeError as exc:
        return _verification(CONTRACT_EVIDENCE_CORRUPT, evidence, reason=str(exc))
    if recomputed != stored_hash:
        return _verification(
            CONTRACT_EVIDENCE_CORRUPT, evidence, schema=schema, reason="Hash weicht ab",
        )
    return _verification(CONTRACT_EVIDENCE_VERIFIED, evidence, schema=schema)


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

    # Seit dem priorisierten Ziel-Scope (Engine v10): V3. V2 bleibt nur zum
    # Verifizieren historischer Evidence.
    return ObjectiveContractV3(
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
