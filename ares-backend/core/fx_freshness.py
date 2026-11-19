"""K1 / E2E-03: FX im Allokations-Pruefwert nur ueber die effektiven Kurse.

Vorher band ``canonical_model_signature`` die ``basis_id`` -- den
Fingerabdruck der GANZEN Kurstabelle -- in den ``input_snapshot_hash``. Jede
Kursaenderung, auch GBP/JPY bei einem reinen CHF-Mandat, machte alle
gespeicherten und publizierten Allokationen veraltet.

Ab Snapshot-Version ``INPUT_SNAPSHOT_VERSION_FX_EFFECTIVE`` wird der
Projektionskontext vor dem Hash auf die Freshness-Sicht reduziert:
Zielwaehrung, ``uses_versioned_defaults`` und ``effective_rates_x1e8`` der
tatsaechlich verwendeten Waehrungen. ``basis_id`` bleibt Provenienz in den
Signaturen/Snapshots, ist aber kein Rechen-Input: die Engine liest aus der
Kursquelle nur ``cross_rate(ccy, ziel)`` fuer genau diese Waehrungen.
Dasselbe gilt fuer die FX-Evidence des Vorsorge-Transfer-Snapshots in der
Foundation (dort zusaetzlich ohne die daraus abgeleiteten snapshot_hash/-id).

Stdlib-Blatt (architecture ratchets, FAN_OUT_EXEMPT_LEAVES).
"""
from __future__ import annotations

import json
from typing import Any

INPUT_SNAPSHOT_VERSION_FX_EFFECTIVE = "strategy_inputs_v5_fx_effective_rates"
PENSION_LEDGER_SNAPSHOT_KEY = "pension_transfer_ledger_snapshot"


def fx_signature_freshness_view(signature: Any) -> Any:
    if not isinstance(signature, dict):
        return signature
    return {key: value for key, value in signature.items() if key != "basis_id"}


def fx_freshness_projection_context(projection_context: Any) -> Any:
    """Projektionskontext ohne tabellenweite FX-Provenienz (Original bleibt)."""
    if not isinstance(projection_context, dict):
        return projection_context
    view = dict(projection_context)
    if "fx_basis" in view:
        view["fx_basis"] = fx_signature_freshness_view(view["fx_basis"])
    foundation = view.get("external_foundation_projection")
    key = PENSION_LEDGER_SNAPSHOT_KEY
    if isinstance(foundation, dict) and isinstance(foundation.get(key), dict):
        snapshot = {
            name: value for name, value in foundation[key].items()
            if name not in {"snapshot_hash", "snapshot_id"}
        }
        snapshot["fx_evidence"] = fx_signature_freshness_view(snapshot.get("fx_evidence"))
        view["external_foundation_projection"] = {**foundation, key: snapshot}
    return view


def used_foreign_currencies(projection_context: Any) -> list[str]:
    """Verwendete Nicht-CHF-Waehrungen laut gebundener FX-Signatur."""
    signature = (projection_context or {}).get("fx_basis") if isinstance(projection_context, dict) else None
    rates = signature.get("effective_rates_x1e8") if isinstance(signature, dict) else None
    return sorted({
        str(item[0]).upper() for item in rates or []
        if isinstance(item, (list, tuple)) and item
    } - {"CHF"})


STALE_INPUTS_MESSAGE = (
    "Die gespeicherte Soll-Allokation ist veraltet: Vermögen, Cashflows oder Ziele haben sich seit "
    "der Berechnung geändert. Bitte Strategie neu berechnen; alte Targets werden nicht mit einer "
    "aktuellen Analyse kombiniert."
)
STALE_BASIS_UPDATED_MESSAGE = (
    "Die gespeicherte Soll-Allokation ist veraltet: Berechnungsgrundlage aktualisiert (Wechselkurs-"
    "Bindung seit diesem Update nur noch über die verwendeten Kurse) -- bitte neu berechnen."
)


def predates_fx_effective_hash(effective_constraints_json: Any) -> bool:
    """N-913-02: vor K1 erzeugte Engine-Allokation (v4-Pruefwert inkl. tabellen-
    weiter basis_id)? Erkennbar an der gespeicherten Modellbasis ohne die mit K1
    eingefuehrte Property-Gate-Bindung. Ohne Modellbasis (manuell): unbekannt."""
    try:
        constraints = json.loads(effective_constraints_json or "")
    except (TypeError, ValueError):
        return False
    basis = constraints.get("optimization_model_basis") if isinstance(constraints, dict) else None
    return isinstance(basis, dict) and "property_advanced_features" not in basis


class StaleAllocationReason(str):
    """KN-B / E2E2-05: Veraltet-Meldung mit maschinenlesbarer Ursache --
    ``kind`` ("fx_rate", "calculation_basis", "inputs") und ``currencies``."""


def _stale_reason(text: str, kind: str, currencies: Any = ()) -> StaleAllocationReason:
    reason = StaleAllocationReason(text)
    reason.kind = kind
    reason.currencies = tuple(currencies)
    return reason


def stale_allocation_message(fx_changed: list[str], predates_v5: bool) -> StaleAllocationReason:
    """Wahre Ursache einer Veraltung: relevanter Kurs, einmaliger Uebergang
    v4 -> v5 oder Eingaben."""
    if fx_changed:
        return _stale_reason(
            f"Die gespeicherte Soll-Allokation ist veraltet: Wechselkurs {', '.join(fx_changed)} seit der "
            "Berechnung geaendert. Bitte Strategie neu berechnen; alte Targets werden nicht mit einer "
            "aktuellen Analyse kombiniert.",
            "fx_rate", fx_changed,
        )
    if predates_v5:
        return _stale_reason(STALE_BASIS_UPDATED_MESSAGE, "calculation_basis")
    return _stale_reason(STALE_INPUTS_MESSAGE, "inputs")


# KN-B / E2E2-05: Ursachen einer Veraltung fuer die Status-APIs (Publikation,
# Envelope). Schluessel: Ursachenart der Allokationspruefung bzw. die
# Abhaengigkeitsart der Invalidierung (models/snapshots.DEPENDENCY_SOURCES).
FRESHNESS_CAUSE_TEXTS = {
    "fx_rate": "Wechselkurs geändert",
    "calculation_basis": "Berechnungsgrundlage aktualisiert",
    "inputs": "Vermögen, Cashflows oder Ziele geändert",
    "client": "Stammdaten des Kunden geändert",
    "mandate": "Mandatsdaten geändert",
    "planning": "Planungsannahmen geändert",
    "goals": "Ziele geändert",
    "goal_revisions": "Ziele geändert",
    "goal_transitions": "Ziele geändert",
    "cashflows": "Cashflows geändert",
    "wealth_inflows": "Vermögenszuflüsse geändert",
    "positions": "Vermögen geändert",
    "run_holdings": "Bestände der Empfehlung geändert",
    "risk": "Risikoprofil geändert",
    "risk_overrides": "Risikoprofil geändert",
    "risk_signoffs": "Risikoprofil geändert",
    "risk_plausibility": "Risikoprofil geändert",
    "coverage_attestations": "Deckungsnachweis geändert",
    "preference": "Nachhaltigkeitspräferenz geändert",
    "constraints": "Restriktionen oder Bandbreiten geändert",
    "cma": "Kapitalmarktannahmen geändert",
    "optimizer_policy": "Hausmeinung geändert",
    "cma_policy": "Hausmeinung geändert",
    "cma_policy_components": "Hausmeinung geändert",
    "cma_policy_approvals": "Hausmeinung geändert",
    "building_blocks": "Hausmeinung geändert",
    "benchmark": "Hausmeinung geändert",
}


def freshness_cause(kind: str, currencies: Any = ()) -> dict:
    """Eine Ursache als ``{kind, text, currencies}``; bei Kursen mit Waehrung
    ("Wechselkurs USD geändert")."""
    codes = sorted({str(code).upper() for code in currencies or ()})
    if kind == "fx_rate" and codes:
        text = f"Wechselkurs {', '.join(codes)} geändert"
    else:
        text = FRESHNESS_CAUSE_TEXTS.get(kind, "Beratungsdaten geändert")
    return {"kind": kind, "text": text, "currencies": codes}


__all__ = [
    "FRESHNESS_CAUSE_TEXTS",
    "StaleAllocationReason",
    "freshness_cause",
    "predates_fx_effective_hash",
    "stale_allocation_message",
    "INPUT_SNAPSHOT_VERSION_FX_EFFECTIVE",
    "fx_freshness_projection_context",
    "fx_signature_freshness_view",
    "used_foreign_currencies",
]
