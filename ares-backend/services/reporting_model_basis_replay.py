"""REPORTING-BASIS-DURABILITY-001 -- Replay der gespeicherten Reporting-Basis.

Die Methodik des Projektionskanals (``model_basis["reporting"]``: Tail-Modell,
Rebalancing, Transaktionskosten, Stress-Multiplikator, Zeitgitter des
Drawdown, Seed/Pfade/Horizont) wird bei der Generierung in
``effective_constraints_json["reporting_model_basis"]`` persistiert und ist
damit Teil des ``allocation_context_hash``. Sie beschreibt die Kennzahlen, die
auf derselben Zeile stehen (``mc_max_drawdown_bps``, ``mc_var_95_bps`` ...).

Beim Reload wurde dieser Block bisher aus der heutigen Umgebung neu gebaut.
Aendert sich danach eine Methode (z. B. das Drawdown-Zeitgitter), stand die
HEUTIGE Methodik neben einer Zahl, die unter der ALTEN entstanden ist -- und
nichts zeigte die Abweichung an.

Dieses Modul spielt den gespeicherten Block wortgetreu ab (wie
``optimization_model_basis``) und vergleicht ihn mit der Live-Basis:

* ``verified``      -- gespeichert und identisch mit der heutigen Basis.
* ``stale``         -- gespeichert, aber die heutige Basis weicht ab. Angezeigt
  wird weiterhin die gespeicherte Basis; die Abweichung wird mit den
  betroffenen Schluesseln und einer Live-Vorschau offengelegt ("veraltet").
* ``not_persisted`` -- keine gespeicherte Basis (Allokation aus der Zeit vor
  der Persistierung, manuelle Allokation oder unverifizierter Altbestand).
  Die Live-Basis wird ausdruecklich als Live-Vorschau gekennzeichnet, nie als
  gespeichert ausgegeben.

Die Live-Monte-Carlo-Projektion des Reloads (``monte_carlo["model_basis"]``)
bleibt davon unberuehrt: sie ist eine heutige Rechnung und traegt deshalb
ehrlich die heutige Methodik.
"""

from __future__ import annotations

import json

REPORTING_BASIS_CONSTRAINTS_KEY = "reporting_model_basis"
REPORTING_REPLAY_KEY = "reporting_model_basis_replay"

REPLAY_VERIFIED = "verified"
REPLAY_STALE = "stale"
REPLAY_NOT_PERSISTED = "not_persisted"
MODE_HISTORICAL_REPLAY = "historical_replay"
MODE_LIVE_PREVIEW = "live_preview_not_persisted"

STALE_MESSAGE = (
    "Die Reporting-Methodik dieser Soll-Allokation ist veraltet: die heutige "
    "Berechnungsgrundlage weicht von der gespeicherten ab ({keys}). Die "
    "gespeicherten Kennzahlen gelten fuer die gespeicherte Methodik; fuer "
    "aktuelle Kennzahlen die Strategie neu berechnen."
)
NOT_PERSISTED_MESSAGE = (
    "Fuer diese Soll-Allokation ist keine Reporting-Methodik gespeichert "
    "(Basis nicht gespeichert). Die angezeigte Methodik ist eine Live-"
    "Vorschau nach heutigem Stand; fuer eine nachvollziehbare Basis die "
    "Strategie neu berechnen."
)


def _canonical(value):
    """JSON-Normalform, damit Tupel/Listen und Schluesselreihenfolge nicht als
    Abweichung zaehlen -- persistiert wird ebenfalls ueber JSON."""
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))


def replay_reporting_model_basis(
    model_basis: dict, stored_constraints: dict | None
) -> tuple[dict, dict]:
    """Gibt ``(model_basis, payload)`` zurueck: ``model_basis`` mit wortgetreu
    abgespielter Reporting-Basis (weiterhin genau die zwei Kanaele
    ``optimization``/``reporting``) und die Payload-Felder mit dem
    Replay-Status unter ``reporting_model_basis_replay``.

    ``model_basis["reporting"]`` muss beim Aufruf die LIVE gebaute Basis sein.
    ``stored_constraints`` ist der bereits hash-verifizierte
    ``effective_constraints_json``-Inhalt (``None`` bei unverifiziertem
    Altbestand). Ein vorhandener, aber nicht-objektfoermiger Block ist ein
    Integritaetsfehler (fail-closed, wie bei der Optimizer-Basis).
    """
    live = _canonical(dict(model_basis["reporting"]))
    stored = (stored_constraints or {}).get(REPORTING_BASIS_CONSTRAINTS_KEY)
    result = dict(model_basis)
    if stored is None:
        result["reporting"] = live
        return result, {REPORTING_REPLAY_KEY: {
            "mode": MODE_LIVE_PREVIEW,
            "status": REPLAY_NOT_PERSISTED,
            "analysis_basis": "live_preview",
            "divergent_keys": [],
            "live_preview": live,
            "message": NOT_PERSISTED_MESSAGE,
        }}
    if not isinstance(stored, dict):
        raise ValueError("Persistierte Reporting-Modellbasis muss ein Objekt sein.")
    stored = dict(stored)
    divergent = sorted(
        key for key in set(stored) | set(live) if stored.get(key) != live.get(key)
    )
    status = REPLAY_STALE if divergent else REPLAY_VERIFIED
    result["reporting"] = stored
    return result, {REPORTING_REPLAY_KEY: {
        "mode": MODE_HISTORICAL_REPLAY,
        "status": status,
        "analysis_basis": "persisted_snapshot",
        "divergent_keys": divergent,
        "live_preview": live if divergent else None,
        "message": (
            STALE_MESSAGE.format(keys=", ".join(divergent)) if divergent else None
        ),
    }}


def reporting_replay_warnings(replay_payload: dict) -> list[str]:
    """Hinweiszeile fuer die Begruendungsliste (leer bei ``verified``)."""
    message = (replay_payload.get(REPORTING_REPLAY_KEY) or {}).get("message")
    return [message] if message else []
