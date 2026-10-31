"""Eingefrorener Simulationskontext eines gemeinsamen Vermoegenspfads.

GOAL-FUNDING-PRIORITY-001 / MORT-CHANNEL-001 (Restvertrag nach Engine v10)
=========================================================================

``simulate_wealth_paths`` maskiert Cashflow und Liability je Pfad ab dem
Todesjahr. Aus dem fertigen Vermoegenspfad allein ist diese Maske nicht mehr
ablesbar: eine Rueckwaertsrekonstruktion eines Prioritaets-Scopes behandelt
eine nach dem Tod nie bezahlte Liability als Wachstum (Nullrendite,
Start 100, Joint-Liability 80 nach Tod: 100 -> 100 -> 160 statt 100).

Engine v10 simuliert jeden abweichenden Scope deshalb direkt auf dem
eingefrorenen Kontext (``priority_scope.ScopeReplayInputs``). Fehlte der
Kontext, brach die Bewertung bisher fail-closed ab. Dieses Modul haelt den
Kontext zu jedem von ``simulate_wealth_paths`` gelieferten Array fest
(dieselben Szenarien, Gewichte, Cashflows, Liability, Steuer- und
Altersparameter und dieselbe pfadweise Todesmaske), damit ein Aufrufer, der
nur den Pfad weiterreicht, den Scope trotzdem exakt direkt simulieren kann.

Vertrag
-------
* Gebunden wird an die IDENTITAET des zurueckgegebenen Arrays (schwache
  Referenz). Kopien, Slices oder abgeleitete Arrays haben keinen Kontext --
  dort bleibt es beim fail-closed-Abbruch.
* Der Kontext wird nur genutzt, nachdem der gemeinsame Pfad aus ihm
  bit-/toleranzgleich nachgerechnet wurde (``verify_joint_parity``). Ein
  nachtraeglich veraendertes Array oder veraenderte Eingaben fuehren zum
  Abbruch, nie zu einer stillen Zahl.
* Ziel-gebundene Reserve-Freigaben im Cashflow sind dem Kontext nicht
  bekannt. Der Solver, dessen Cashflow solche Freigaben enthaelt, uebergibt
  deshalb immer seinen expliziten Replay-Kontext und haelt keinen Kontext
  fest (``retain_scope_context=False``).
* Nur fuer den Steuer-Modus, den der Replay reproduziert
  (``tax_mode="median"``, ``tax_n_bins=20``); sonst kein Kontext.

Die Registry ist reine Bindung, keine Rechnung: ein Pfad, fuer den kein
Scope abweicht, liest den Kontext nie.
"""
from __future__ import annotations

import weakref
from typing import Any

import numpy as np

RETAINED_SIMULATION_CONTEXT_POLICY_VERSION = "retained_joint_context_v1"

# id(array) -> (schwache Referenz auf das Array, Kontext). Der Callback
# entfernt den Eintrag beim Freigeben des Arrays, also bevor die id neu
# vergeben werden kann.
_RETAINED: dict[int, tuple[weakref.ref, dict[str, Any]]] = {}


def retain(wealth: np.ndarray, context: dict[str, Any]) -> np.ndarray:
    """Haelt ``context`` fuer genau dieses ``wealth``-Array fest."""
    key = id(wealth)

    def _drop(ref: weakref.ref, key: int = key) -> None:
        entry = _RETAINED.get(key)
        if entry is not None and entry[0] is ref:
            _RETAINED.pop(key, None)

    try:
        ref = weakref.ref(wealth, _drop)
    except TypeError:  # pragma: no cover - ndarray unterstuetzt weakref
        return wealth
    _RETAINED[key] = (ref, context)
    return wealth


def retained(wealth: Any) -> dict[str, Any] | None:
    """Kontext zu genau diesem Array oder ``None`` (Kopie, Slice, fremd)."""
    entry = _RETAINED.get(id(wealth))
    if entry is None or entry[0]() is not wealth:
        return None
    return entry[1]


def retained_count() -> int:
    """Anzahl lebender Eintraege (Diagnose/Tests)."""
    return sum(1 for ref, _ctx in list(_RETAINED.values()) if ref() is not None)


__all__ = [
    "RETAINED_SIMULATION_CONTEXT_POLICY_VERSION",
    "retain",
    "retained",
    "retained_count",
]
