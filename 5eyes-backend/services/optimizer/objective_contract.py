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

    return ObjectiveContractV1(
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
