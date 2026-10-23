"""PensionTransferLedgerSnapshotV1 (PENSION-TRANSFER-LEDGER-001, Restbefund B).

PR #651 erzeugte ``PensionTransferLedgerV1`` nur transient in
``build_pension_projection()``; Version, Hash und Zeilen verliessen den
Projektionsaufruf nie. Reload, API und PDF konnten deshalb nicht beweisen,
welcher Transferentscheid einer gespeicherten Soll-Allokation zugrunde lag.

Dieser Snapshot ist der unveraenderliche Run-Input:

* Ledger-Version, Policy-Version, Bewertungsjahr, Waehrung, Ledger-Hash;
* die Ledger-Zeilen (horizontinvariante ``identity()``, inkl. expliziter
  Bewertungsanpassung und Steuer-Provenienz);
* Quellen- und Zufluss-Versionen (ID, ``updated_at``, gebundene Betraege);
* FX-Evidence (Basis-ID = Fingerprint der aktiven Kurse inkl. ``valid_from``/
  Quelle, effektive Kurse der Quellwaehrungen) bzw. ``not_applied``;
* ``snapshot_hash`` (SHA-256 ueber alles oben) und ``snapshot_id``.

Bindung (Muster wie der Allocation-Context): Generate und der manuelle
Speicherpfad persistieren den Snapshot in
``target_allocations.pension_transfer_ledger_snapshot_json`` und legen eine
Referenz (ID + Hashes) in ``effective_constraints`` ab -- diese fliesst in den
``allocation_context_hash``. Zusaetzlich ist der Snapshot Teil der
Foundation-Projektion und damit des ``input_snapshot_hash``: jede Aenderung
eines gebundenen Inputs macht die alte Allokation beim Reload ``stale``.
Der Verifier (``verify_bound_pension_transfer_ledger_snapshot``) prueft beim
Reload Struktur, Snapshot-Hash, Ledger-Hash und beide Ledger-Identitaeten
jeder Zeile aus den gespeicherten Daten -- keine Neuberechnung aus heutigen
Eingaben.
"""
from __future__ import annotations

import hashlib
import json

from services.pension_transfer_ledger import (
    PENSION_TRANSFER_LEDGER_VERSION,
    PensionTransferLedgerV1,
    PensionTransferRow,
)

PENSION_TRANSFER_LEDGER_SNAPSHOT_VERSION = "PensionTransferLedgerSnapshotV1"
# Foundation-Key (Teil des input_snapshot_hash) und Referenz-Key in
# effective_constraints (Teil des allocation_context_hash).
FOUNDATION_SNAPSHOT_KEY = "pension_transfer_ledger_snapshot"
CONSTRAINTS_REF_KEY = "pension_transfer_ledger_snapshot"
FOUNDATION_LEDGER_KEY_PREFIX = "pension_transfer_ledger"

_BODY_KEYS = (
    "snapshot_version", "ledger_version", "ledger_input_hash", "policy_version",
    "valuation_year", "currency", "fx_evidence", "sources", "inflows", "rows",
)


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(payload) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _opt_str(value) -> str | None:
    return None if value is None else str(value)


def _opt_int(value) -> int | None:
    return None if value is None else int(value)


def _fx_evidence(fx_source, currencies: set[str], target_currency: str) -> dict:
    if fx_source is None:
        # Backwards-Compat-Pfad: Betraege werden nicht umgerechnet.
        return {"status": "not_applied", "target_currency": target_currency}
    signature = fx_source.canonical_model_signature(
        sorted(currencies), target_currency=target_currency,
    )
    return {"status": "applied", **signature}


def build_pension_transfer_ledger_snapshot(
    ledger: PensionTransferLedgerV1,
    *,
    positions,
    wealth_inflows,
    fx_source=None,
    target_currency: str = "CHF",
) -> dict:
    """Unveraenderlicher, horizontinvarianter Snapshot eines Ledgers."""
    target = str(target_currency or "CHF").upper()
    source_ids = {row.source_position_id for row in ledger.rows}
    inflow_ids = {row.linked_inflow_id for row in ledger.rows if row.linked_inflow_id}
    sources = sorted(
        (
            {
                "position_id": str(getattr(p, "id", "") or ""),
                "updated_at": _opt_str(getattr(p, "updated_at", None)),
                "currency": str(getattr(p, "currency", None) or target).upper(),
                "current_value_rappen": _opt_int(getattr(p, "current_value_rappen", None)),
            }
            for p in positions or []
            if str(getattr(p, "id", "") or "") in source_ids
        ),
        key=lambda item: item["position_id"],
    )
    inflows = sorted(
        (
            {
                "inflow_id": str(getattr(i, "id", "") or ""),
                "updated_at": _opt_str(getattr(i, "updated_at", None)),
                "linked_position_id": _opt_str(getattr(i, "linked_position_id", None)),
                "currency": str(getattr(i, "currency", None) or target).upper(),
                "amount_rappen": _opt_int(getattr(i, "amount_rappen", None)),
                "expected_year": _opt_int(getattr(i, "expected_year", None)),
            }
            for i in wealth_inflows or []
            if str(getattr(i, "id", "") or "") in inflow_ids
        ),
        key=lambda item: item["inflow_id"],
    )
    body = {
        "snapshot_version": PENSION_TRANSFER_LEDGER_SNAPSHOT_VERSION,
        "ledger_version": ledger.version,
        "ledger_input_hash": ledger.input_hash,
        "policy_version": ledger.policy_version,
        "valuation_year": int(ledger.valuation_year),
        "currency": ledger.currency,
        "fx_evidence": _fx_evidence(
            fx_source, {s["currency"] for s in sources} | {i["currency"] for i in inflows}, target,
        ),
        "sources": sources,
        "inflows": inflows,
        "rows": [row.identity() for row in ledger.rows],
    }
    snapshot_hash = _sha256(body)
    return {**body, "snapshot_hash": snapshot_hash, "snapshot_id": f"ptls-{snapshot_hash[:24]}"}


def verify_pension_transfer_ledger_snapshot(snapshot) -> dict:
    """Prueft einen gespeicherten Snapshot ausschliesslich aus sich selbst:
    Struktur, Snapshot-Hash, Ledger-Hash und beide Zeilen-Identitaeten.
    Wirft ``ValueError`` (fail-closed)."""
    if not isinstance(snapshot, dict):
        raise ValueError("Vorsorge-Transfer-Snapshot muss ein Objekt sein.")
    if snapshot.get("snapshot_version") != PENSION_TRANSFER_LEDGER_SNAPSHOT_VERSION:
        raise ValueError("Vorsorge-Transfer-Snapshot hat eine unbekannte Version.")
    if snapshot.get("ledger_version") != PENSION_TRANSFER_LEDGER_VERSION:
        raise ValueError("Vorsorge-Transfer-Snapshot referenziert eine unbekannte Ledger-Version.")
    missing = [key for key in _BODY_KEYS if key not in snapshot]
    if missing:
        raise ValueError(f"Vorsorge-Transfer-Snapshot unvollstaendig: {', '.join(missing)}.")
    body = {key: snapshot[key] for key in _BODY_KEYS}
    expected_hash = _sha256(body)
    if snapshot.get("snapshot_hash") != expected_hash or snapshot.get("snapshot_id") != f"ptls-{expected_hash[:24]}":
        raise ValueError("Vorsorge-Transfer-Snapshot-Hash stimmt nicht mit dem Inhalt ueberein.")
    raw_rows = body["rows"]
    if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
        raise ValueError("Vorsorge-Transfer-Snapshot: Zeilen muessen Objekte sein.")
    try:
        # __post_init__ erzwingt beide Ledger-Identitaeten erneut.
        rows = [PensionTransferRow(**row, within_horizon=False) for row in raw_rows]
    except TypeError as exc:
        raise ValueError("Vorsorge-Transfer-Snapshot: Zeilenschema ungueltig.") from exc
    rebuilt = PensionTransferLedgerV1.build(
        rows, valuation_year=int(body["valuation_year"]), currency=str(body["currency"]),
        policy_version=str(body["policy_version"]),
    )
    if rebuilt.input_hash != body["ledger_input_hash"]:
        raise ValueError("Vorsorge-Transfer-Snapshot: Ledger-Hash stimmt nicht mit den Zeilen ueberein.")
    return snapshot


def snapshot_reference(snapshot: dict) -> dict:
    return {
        "snapshot_version": snapshot["snapshot_version"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "ledger_input_hash": snapshot["ledger_input_hash"],
    }


def bind_pension_transfer_ledger_snapshot(effective_constraints: dict, foundation: dict | None) -> str | None:
    """Legt die Snapshot-Referenz in ``effective_constraints`` ab (vor dem
    allocation_context_hash) und liefert das kanonische JSON fuer die Spalte
    ``pension_transfer_ledger_snapshot_json`` (``None`` ohne externe Vorsorge
    -> Constraints und Hash bleiben byte-identisch)."""
    snapshot = (foundation or {}).get(FOUNDATION_SNAPSHOT_KEY)
    effective_constraints.pop(CONSTRAINTS_REF_KEY, None)
    if snapshot is None:
        return None
    verify_pension_transfer_ledger_snapshot(snapshot)
    effective_constraints[CONSTRAINTS_REF_KEY] = snapshot_reference(snapshot)
    return _canonical(snapshot)


def verify_bound_pension_transfer_ledger_snapshot(allocation, stored_constraints: dict) -> dict | None:
    """Reload-Gate: gespeicherter Snapshot und gehashte Referenz muessen
    gemeinsam vorliegen und zueinander passen."""
    reference = stored_constraints.get(CONSTRAINTS_REF_KEY)
    raw = getattr(allocation, "pension_transfer_ledger_snapshot_json", None)
    if reference is None and raw is None:
        return None
    if reference is None or raw is None:
        raise ValueError(
            "Vorsorge-Transfer-Snapshot und seine Referenz im Allocation-Context "
            "muessen gemeinsam vorliegen."
        )
    try:
        snapshot = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Persistierter Vorsorge-Transfer-Snapshot ist kein gueltiges JSON.") from exc
    verify_pension_transfer_ledger_snapshot(snapshot)
    if reference != snapshot_reference(snapshot):
        raise ValueError(
            "Persistierter Vorsorge-Transfer-Snapshot widerspricht der gehashten "
            "Referenz im Allocation-Context."
        )
    return snapshot


def stored_pension_transfer_ledger_snapshot(allocation) -> dict | None:
    """Verifizierter gespeicherter Snapshot einer TargetAllocation (Payload)."""
    raw_constraints = getattr(allocation, "effective_constraints_json", None)
    try:
        constraints = json.loads(raw_constraints) if raw_constraints else {}
    except (TypeError, ValueError) as exc:
        raise ValueError("Persistierte effektive Allocation-Constraints sind ungueltig.") from exc
    return verify_bound_pension_transfer_ledger_snapshot(allocation, constraints if isinstance(constraints, dict) else {})


def canonical_foundation_projection(foundation: dict) -> dict:
    """Kanonische Foundation fuer den Projektionskontext-Hash: Serien als
    int-Listen, Ledger-Identitaet (Version/Hash/Zeilen/Snapshot) unveraendert."""
    return {
        key: (value if key.startswith(FOUNDATION_LEDGER_KEY_PREFIX) else [int(v) for v in value])
        for key, value in sorted((foundation or {}).items())
    }
