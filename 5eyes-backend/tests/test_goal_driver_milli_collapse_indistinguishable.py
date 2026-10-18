"""OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 -- Goal-Driver-Praezision.

BEHOBEN am 2026-10-13, Stufe 1 (Auslieferung der verlustfreien Evidenz).
Dieses Modul war bis dahin eine Rote-Test-Datei; die Historie des Befunds
bleibt unten stehen, damit nachvollziehbar ist, was genau falsch war.

Was behoben wurde
-----------------
`_lossless_objective_evidence()` erzeugte das verlustfreie Paar
(`_decimal`, `_binary64_hex`) bereits -- aber
`schemas/allocation.py::OptimizerGoalDriverResponse` deklarierte es NICHT,
und Pydantic verwirft unbekannte Felder beim Serialisieren STILL. Gemessen:
beide Felder erreichten keinen einzigen Konsumenten, und der Monolith zeigte
das verlustbehaftete Milli-Feld. Die Berechnung war also korrigiert, die
AUSLIEFERUNG fehlte -- der Fix endete an der Schema-Grenze.

Jetzt sind beide Felder deklariert (nachgemessen: 8 von 8 Audit-Testwerten
nach Serialisierung unterscheidbar, Roundtrip bit-exakt) und der Monolith
zeigt den verlustfreien Dezimalwert, mit getrennten Zustaenden fuer "exakt
null", "kleiner positiver Beitrag" und "nicht verfuegbar".

Das Legacy-Milli-Feld bleibt BEWUSST verlustbehaftet (Zielvertrag Punkt 7
des Audits). Es umzuskalieren waere schlimmer als es zu lassen: jeder
bereits unter dieser Skala persistierte Wert und jeder Konsument, der durch
1000 teilt, wuerden falsch.

NICHT behoben (eigene Stufen, siehe PR-Beschreibung)
----------------------------------------------------
* `TargetAllocation.optimization_objective_value_milli` -- der KOPFWERT der
  Zielfunktion hat kein verlustfreies Gegenstueck und liegt als Integer in
  der DB. Derselbe Kollaps, aber persistiert; braucht Migration und den
  `legacy_precision_ambiguous`-Vertrag fuer Altzeilen.
* Getrennte Speicherung von Primary Shortfall / Chance Penalty /
  Risikokomponente (Zielvertrag Punkt 5) und Sensitivity-Deltas aus
  Rohwerten (Punkt 3).

--- Historie des Befunds (Kontrollrunde 36) -------------------------------

Audit-Dok
docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md:

`_objective_to_milli()` (services/portfolio_engine_optimizer_integration.py,
ca. Zeile 725-736) berechnet `int(round(value * 1000.0))`. Mehrere
MATERIELL VERSCHIEDENE, kleine positive Objective-/Goal-Driver-Beitraege
kollabieren dadurch auf denselben gespeicherten Integer (0) -- "voll
erfuellt" (raw objective exakt 0), "minimale Verfehlung" (raw ~4e-12) und
"materielle kleine Unterdeckung" (raw ~4e-4) werden in der persistierten
Goal-Driver-Evidenz visuell/numerisch UNUNTERSCHEIDBAR, obwohl Goal-Driver
laut Doku korrekt nach ihrem rohen (ungerundeten) Beitrag VOR der
Serialisierung sortiert bleiben sollen.

Fundstellen (verifiziert durch Lesen der echten Datei, nicht nur Behauptung):
- `_objective_to_milli`: services/portfolio_engine_optimizer_integration.py
  Zeile 725-736 -- `scaled = value * 1000.0`, dann
  `int(round(capped))`. Kein Toleranz-/Epsilon-Handling fuer kleine
  Werte -- alles unter 0.0005 (banker's rounding: auch 0.0005 selbst,
  da round-half-to-even auf 0 rundet) wird zu 0.
- Publikation des gerundeten Werts: services/portfolio_engine_optimizer_integration.py
  Funktion `_build_optimizer_explainability` (Zeile 1079ff.), Schleife
  Zeile 1196-1207:
      for rank, row in enumerate(contribution_rows, start=1):
          drivers_payload.append({
              ...
              "weighted_objective_contribution_milli": _objective_to_milli(
                  row.weighted_objective_contribution
              ),
              "rank": rank,
          })
  `row` ist eine `GoalShortfallContribution` (services/optimizer/objective.py,
  Zeile 522ff.) mit dem ROHEN Feld `weighted_objective_contribution`. Der
  publizierte/serialisierte Wert pro Goal-Driver ist also exakt der
  gerundete Milli-Integer -- NICHT der rohe Float.
- Sortierung bleibt roh: `shortfall_contributions()` (services/optimizer/objective.py,
  Zeile 591) sortiert `contribution_rows` VOR der obigen Schleife mit
      sorted(rows, key=lambda row: row.weighted_objective_contribution, reverse=True)
  -- also nach dem ungerundeten Float. Diese Sortier-Korrektheit ist der
  Positiv-Control in diesem Modul (Test c) und darf durch einen
  zukuenftigen Praezisions-Fix NICHT angetastet werden.

Verifizierte Werte (direkt gegen die echte Funktion verifiziert, nicht nur
behauptet):
    _objective_to_milli(0)        -> 0
    _objective_to_milli(4e-12)    -> 0
    _objective_to_milli(4e-6)     -> 0
    _objective_to_milli(4e-5)     -> 0
    _objective_to_milli(0.00049)  -> 0
    _objective_to_milli(0.00050)  -> 0   (round-half-to-even: 0.5 rundet auf
                                           die gerade Zahl 0, nicht 1)
    _objective_to_milli(0.00060)  -> 1
    _objective_to_milli(0.00140)  -> 1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.objective import GoalShortfallContribution
from services.portfolio_engine_optimizer_integration import (
    _lossless_objective_evidence,
    _objective_to_milli,
)


# Die acht Werte aus der Pflicht-Test-Liste des Audits (Abschnitt
# "Pflicht-Tests", Punkt 1). Sie spannen genau die Zustaende auf, die vorher
# ununterscheidbar waren: exakte Null, Sub-Epsilon, zwei materielle
# Kleinbetraege und die Rundungsgrenzen um 0.0005.
_AUDIT_ROUNDTRIP_VALUES = (0.0, 4e-12, 4e-6, 4e-5, 0.00049, 0.00050, 0.00060, 0.00140)


# ============================================================================
# (a) Die Arithmetik des Legacy-Felds -- und die verlustfreie Darstellung,
#     die den Vertrag erfuellt.
# ============================================================================


def test_legacy_milli_arithmetic_is_documented_and_unchanged():
    """Die im Audit nachgemessenen Milli-Werte, unveraendert.

    Das Legacy-Feld bleibt BEWUSST verlustbehaftet (Zielvertrag Punkt 7 des
    Audits: "Das alte `*_milli`-Feld darf uebergangsweise nur als klar
    markiertes Legacy-Feld verbleiben"). Es stillschweigend umzuskalieren
    waere schlimmer als es zu lassen: jeder bereits unter dieser Skala
    persistierte Wert und jeder Konsument, der durch 1000 teilt, wuerden
    falsch.

    Dieser Test haelt die Arithmetik deshalb als ENTSCHEIDUNG fest, nicht als
    gute Eigenschaft -- wer das Feld anfasst, kommt hier bewusst vorbei.
    """
    assert _objective_to_milli(0) == 0
    assert _objective_to_milli(4e-12) == 0
    assert _objective_to_milli(4e-6) == 0
    assert _objective_to_milli(4e-5) == 0
    assert _objective_to_milli(0.00049) == 0
    assert _objective_to_milli(0.00050) == 0  # round-half-to-even -> 0, nicht 1
    assert _objective_to_milli(0.00060) == 1
    assert _objective_to_milli(0.00140) == 1


def test_lossless_pair_distinguishes_every_audit_value():
    """Der eigentliche Vertrag: materiell verschiedene Beitraege bleiben
    nach der Serialisierung unterscheidbar.

    Pflicht-Test 1 des Audits. Geprueft wird die verlustfreie Darstellung,
    nicht das Legacy-Feld -- dort IST der Kollaps gewollt und dokumentiert.
    """
    decimals = {_lossless_objective_evidence(v)[0] for v in _AUDIT_ROUNDTRIP_VALUES}
    hexes = {_lossless_objective_evidence(v)[1] for v in _AUDIT_ROUNDTRIP_VALUES}
    assert len(decimals) == len(_AUDIT_ROUNDTRIP_VALUES), decimals
    assert len(hexes) == len(_AUDIT_ROUNDTRIP_VALUES), hexes

    # Gegenprobe zum Legacy-Feld in derselben Funktion: ohne sie liesse sich
    # nicht erkennen, dass die Unterscheidbarkeit WIRKLICH aus dem neuen Paar
    # kommt und nicht aus einer zufaellig anderen Testwertmenge.
    assert len({_objective_to_milli(v) for v in _AUDIT_ROUNDTRIP_VALUES}) == 2


@pytest.mark.parametrize("raw", _AUDIT_ROUNDTRIP_VALUES)
def test_lossless_pair_round_trips_exactly(raw):
    """Verlustfrei heisst: der Wert kommt BIT-GENAU zurueck.

    Eine Darstellung, die bloss unterschiedlich AUSSIEHT, waere kein
    Nachweis -- erst der exakte Rueckweg macht sie replaybar.
    """
    decimal, binary64_hex = _lossless_objective_evidence(raw)
    assert float(decimal) == raw
    assert float.fromhex(binary64_hex) == raw


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), None])
def test_unavailable_is_not_zero(raw):
    """Nicht endlich oder nicht vorhanden ist ein EIGENER Zustand.

    Zielvertrag Punkt 4: "Exakte Null, positive Sub-Epsilon-Werte,
    non-finite und unavailable bleiben verschiedene Zustaende." Ein
    Konsument darf `(None, None)` nicht als 0 lesen -- deshalb hier
    ausdruecklich gegen die Darstellung der exakten Null geprueft.
    """
    assert _lossless_objective_evidence(raw) == (None, None)
    assert _lossless_objective_evidence(0.0) != (None, None)


# ============================================================================
# (b) Goal-Driver-Serialisierung: dieselbe Kollaps-Pathologie entlang des
#     echten Produktionspfads (GoalShortfallContribution ->
#     weighted_objective_contribution_milli), repliziert aus der echten
#     Schleife in _build_optimizer_explainability (Zeile 1196-1207).
#     XFAIL: die publizierten Goal-Driver-Werte sind alle 0.
# ============================================================================


def _make_contribution(goal_id: str, raw_contribution: float) -> GoalShortfallContribution:
    """Synthetischer GoalShortfallContribution-Row mit vorgegebenem rohem Beitrag.

    GoalShortfallContribution ist die echte, produktionsweit genutzte
    frozen dataclass (services/optimizer/objective.py Zeile 522ff.) -- hier
    direkt mit synthetischen Objective-Komponentenwerten instanziiert statt
    ueber einen vollen Solver-Lauf, um die Serialisierungslogik isoliert zu
    pruefen.
    """
    return GoalShortfallContribution(
        goal_id=goal_id,
        label=f"goal-{goal_id}",
        target_kind="wealth_at_t",
        hardness_key="hart",
        weight_bps=5000,
        mean_shortfall_squared=raw_contribution,
        weighted_objective_contribution=raw_contribution,
    )


def _build_drivers_payload_like_production(
    contribution_rows: list[GoalShortfallContribution],
) -> list[dict]:
    """Repliziert EXAKT die Serialisierungsschleife aus
    services/portfolio_engine_optimizer_integration.py,
    _build_optimizer_explainability (gegengelesen am echten Code):
    dieselben Feldnamen, derselbe Konverter-Aufruf.

    Seit dem Praezisions-Fix (2026-10-13) sind das DREI Felder, nicht eines:
    das Legacy-Milli und das verlustfreie Paar. Haette dieser Helfer nur das
    Milli-Feld weiter nachgebildet, wuerden die Tests unten eine Produktion
    pruefen, die es nicht mehr gibt.
    """
    drivers_payload: list[dict] = []
    for rank, row in enumerate(contribution_rows, start=1):
        contribution_decimal, contribution_binary64_hex = (
            _lossless_objective_evidence(row.weighted_objective_contribution)
        )
        drivers_payload.append({
            "goal_id": row.goal_id,
            "label": row.label,
            "target_kind": row.target_kind,
            "hardness_key": row.hardness_key,
            "weight_bps": int(row.weight_bps),
            "weighted_objective_contribution_milli": _objective_to_milli(
                row.weighted_objective_contribution
            ),
            "weighted_objective_contribution_decimal": contribution_decimal,
            "weighted_objective_contribution_binary64_hex": (
                contribution_binary64_hex
            ),
            "rank": rank,
            # GOAL-ACHIEVABILITY-ATTRIBUTION-001: wie die Produktion.
            "evaluation_scope": "weighted_loss_component_under_joint_path",
        })
    return drivers_payload


def test_goal_driver_published_payload_keeps_the_four_states_apart():
    """Vier Goals mit materiell verschiedenen rohen Beitraegen -- 'voll
    erfuellt' (0), 'minimale Verfehlung' (4e-12), 'kleiner materieller
    Shortfall' (4e-5) und 'groesserer materieller Shortfall' (0.00049) --
    muessen im PUBLIZIERTEN Payload unterscheidbar bleiben.

    Vorher waren sie es nicht: der Payload trug nur das Milli-Feld, und alle
    vier standen als 0 darin. Jetzt traegt dieselbe Schleife das verlustfreie
    Paar daneben.
    """
    contribution_rows = [
        _make_contribution("fully_satisfied", 0.0),
        _make_contribution("minimal_miss", 4e-12),
        _make_contribution("small_material_shortfall", 4e-5),
        _make_contribution("larger_material_shortfall", 0.00049),
    ]
    # Sortierung wie in shortfall_contributions(): absteigend nach dem ROHEN
    # Beitrag.
    contribution_rows = sorted(
        contribution_rows,
        key=lambda row: row.weighted_objective_contribution,
        reverse=True,
    )

    drivers_payload = _build_drivers_payload_like_production(contribution_rows)

    decimals = {d["weighted_objective_contribution_decimal"] for d in drivers_payload}
    assert len(decimals) == 4, (
        "Die vier materiell verschiedenen Goal-Driver-Beitraege sind im "
        f"publizierten Payload nicht unterscheidbar: {drivers_payload}"
    )
    hexes = {d["weighted_objective_contribution_binary64_hex"] for d in drivers_payload}
    assert len(hexes) == 4, drivers_payload

    # Und das Legacy-Feld kollabiert sie weiterhin -- als Beleg, dass die
    # Unterscheidbarkeit aus dem neuen Paar kommt und nicht daher, dass
    # jemand das Milli-Feld stillschweigend umskaliert hat.
    assert {d["weighted_objective_contribution_milli"] for d in drivers_payload} == {0}

    # Jeder publizierte Dezimalwert liest den Rohwert exakt zurueck.
    for driver, row in zip(drivers_payload, contribution_rows, strict=True):
        assert float(driver["weighted_objective_contribution_decimal"]) == (
            row.weighted_objective_contribution
        )


# ============================================================================
# (c) POSITIV-CONTROL (kein xfail): Ranking/Reihenfolge der Goal-Driver nach
#     ROHEM Beitrag bleibt korrekt erhalten, auch wenn die publizierten
#     Magnituden kollabieren. Das ist die im Audit explizit bestaetigte,
#     NICHT kaputte Eigenschaft -- ein zukuenftiger Praezisions-Fix darf sie
#     nicht aus Versehen "mitreparieren" bzw. muss sie unangetastet lassen.
# ============================================================================


def test_goal_driver_ranking_order_preserved_despite_milli_collapse():
    """Ranking nach dem rohen (ungerundeten) Beitrag bleibt korrekt, obwohl
    die publizierten Milli-Werte fuer kleine Beitraege alle auf 0 kollabieren.

    Vier Goals mit rohen Beitraegen 0.00049 > 4e-5 > 4e-12 > 0 -- die
    publizierten *_milli-Werte sind dafuer (aktuell) alle 0, aber der `rank`
    im Payload und die Reihenfolge der Liste muessen trotzdem exakt die
    absteigende Reihenfolge nach dem rohen Wert widerspiegeln."""
    # Bewusst NICHT in sortierter Reihenfolge angelegt -- die Sortierung muss
    # von der echten Produktionslogik selbst hergestellt werden.
    unsorted_rows = [
        _make_contribution("fully_satisfied", 0.0),
        _make_contribution("larger_material_shortfall", 0.00049),
        _make_contribution("minimal_miss", 4e-12),
        _make_contribution("small_material_shortfall", 4e-5),
    ]

    contribution_rows = sorted(
        unsorted_rows,
        key=lambda row: row.weighted_objective_contribution,
        reverse=True,
    )
    drivers_payload = _build_drivers_payload_like_production(contribution_rows)

    expected_order = [
        "larger_material_shortfall",  # 0.00049
        "small_material_shortfall",   # 4e-5
        "minimal_miss",               # 4e-12
        "fully_satisfied",            # 0.0
    ]
    actual_order = [d["goal_id"] for d in drivers_payload]
    assert actual_order == expected_order

    # rank-Feld muss 1..N in genau dieser Reihenfolge sein.
    assert [d["rank"] for d in drivers_payload] == [1, 2, 3, 4]

    # Positiv-Control explizit: obwohl das Ranking korrekt ist, sind die
    # publizierten Magnituden fuer diese kleinen Werte (aktuell) ununterscheidbar
    # -- das ist genau die vom Audit beschriebene Pathologie, hier nur als
    # Beleg dafuer, dass sie die Sortierung NICHT betrifft.
    published_values = [d["weighted_objective_contribution_milli"] for d in drivers_payload]
    assert published_values == [0, 0, 0, 0]
