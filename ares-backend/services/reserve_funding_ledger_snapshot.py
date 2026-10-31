"""RESERVE-LEDGER-SNAPSHOT-001: der Reserve-Funding-Ledger als durable Evidence.

Codex-Closure-Review zu PR #648 (2026-10-19, Restbefunde A/B): Generate
publizierte ``ReserveFundingLedgerV1`` nur im transienten Payload. Die
``TargetAllocation`` speicherte lediglich Reservebetraege; Reload kompilierte
den Ledger mit dem *heutigen* Code neu. Eine spaetere Compilerpolicy tauschte
damit Version/Hash eines historischen Entscheids still aus, und weder
``input_snapshot_hash`` noch ``allocation_context_hash`` hielten das auf.

Vertrag (``ReserveFundingLedgerSnapshotV1``):

* Generate und der manuelle Speicherpfad persistieren den exakt publizierten
  Ledger als kanonisches, kompaktes JSON (``reserve_funding_ledger_json``:
  Version, Policy, Horizont, Tranchen, Releases, Release-Serie, Summen,
  Contract-Hash) plus ``reserve_funding_ledger_hash``.
* Die Referenz (Snapshot-Version, Ledger-Version, Policyversion, Hash) steht
  in ``effective_constraints`` und ist damit im ``allocation_context_hash``
  gebunden.
* Das Integritaets-Gate rekalkuliert den Hash aus den gespeicherten Zeilen
  und vergleicht ihn mit Spalte, Ledger-Feld und Constraint-Referenz.
* Reload = **Historical Replay**: Analyse, Simulation, MC und Payload
  verwenden ausschliesslich den gespeicherten Snapshot. Der mit dem heutigen
  Code kompilierte Ledger ist **Live-Preview** und erscheint getrennt; weicht
  er ab, ist der Entscheid ``stale`` (Finalisierung blockiert).
* Legacy ohne Snapshot ist ehrlich ``unverifiable``: kein historischer Ledger
  wird erfunden, die Analyse laeuft sichtbar auf der Live-Preview und eine
  Finalisierung verlangt eine Neuberechnung.

RESERVE-CEILING-001 (Snapshot-Version 2): derselbe Snapshot traegt den
``ReserveSplitSnapshotV1`` (intern/extern/absorbiert/Luecke, Ceiling in bps
und Rappen). Sein Hash steht zusaetzlich in der Constraint-Referenz; v1-
Snapshots ohne Split bleiben lesbar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields

from core.evidence import canonical_json
from services.reserve_funding_ledger import (
    ReserveFundingLedgerV1,
    ReserveRelease,
    ReserveTranche,
    ledger_contract_hash,
)
from services.reserve_split_snapshot import ReserveSplitSnapshotV1, split_from_dict

RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION = "reserve_funding_ledger_snapshot_v1"
RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION_V2 = "reserve_funding_ledger_snapshot_v2"
# Schluessel der Referenz in effective_constraints (-> allocation_context_hash).
CONSTRAINTS_KEY = "reserve_funding_ledger"

REPLAY_VERIFIED = "verified"
REPLAY_STALE = "stale"
REPLAY_UNVERIFIABLE = "unverifiable"
MODE_HISTORICAL_REPLAY = "historical_replay"
MODE_LEGACY_LIVE_PREVIEW = "legacy_live_preview"


def _canonical(payload: dict) -> str:
    return canonical_json(payload)


def ledger_from_dict(data: dict) -> ReserveFundingLedgerV1:
    """Strikte Rekonstruktion aus ``to_dict()`` (unbekannte/fehlende Felder -> ValueError)."""
    if not isinstance(data, dict):
        raise ValueError("ledger snapshot must be an object")
    expected = {item.name for item in fields(ReserveFundingLedgerV1)}
    if set(data) != expected:
        raise ValueError("ledger snapshot fields do not match ReserveFundingLedgerV1")
    try:
        tranches = tuple(ReserveTranche(**dict(row)) for row in data["tranches"])
        releases = tuple(ReserveRelease(**dict(row)) for row in data["releases"])
    except TypeError as exc:
        raise ValueError(f"ledger snapshot rows are malformed: {exc}") from exc
    values = dict(data)
    values["tranches"] = tranches
    values["releases"] = releases
    values["release_series_rappen"] = tuple(int(v) for v in data["release_series_rappen"])
    return ReserveFundingLedgerV1(**values)


def ledger_reference(ledger: ReserveFundingLedgerV1, split: ReserveSplitSnapshotV1 | None = None) -> dict:
    """Kompakte Referenz fuer ``effective_constraints`` (hash-gebunden)."""
    reference = {
        "snapshot_version": RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION,
        "version": str(ledger.version),
        "policy_version": str(ledger.policy_version),
        "contract_hash": str(ledger.contract_hash),
    }
    if split is not None:
        reference["snapshot_version"] = RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION_V2
        reference["reserve_split_version"] = str(split.version)
        reference["reserve_split_hash"] = str(split.contract_hash)
    return reference


def _check_split_matches_ledger(split: ReserveSplitSnapshotV1, ledger: ReserveFundingLedgerV1) -> None:
    if (split.external_rappen, split.reserve_needed_rappen) != (
        int(ledger.total_external_rappen), int(ledger.reserve_needed_rappen)
    ):
        raise ValueError("Reserve-Split und Reserve-Funding-Ledger nennen verschiedene Betraege.")


def ledger_snapshot_columns(ledger: ReserveFundingLedgerV1, split: ReserveSplitSnapshotV1 | None = None) -> dict:
    """Spaltenwerte der ``TargetAllocation`` fuer den publizierten Ledger (+ Split)."""
    if ledger_contract_hash(ledger) != ledger.contract_hash:
        raise ValueError("Reserve-Funding-Ledger: Contract-Hash stimmt nicht mit den Zeilen ueberein.")
    snapshot = {
        "snapshot_version": RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION,
        "ledger": ledger.to_dict(),
    }
    if split is not None:
        _check_split_matches_ledger(split_from_dict(split.to_dict()), ledger)
        snapshot["snapshot_version"] = RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION_V2
        snapshot["reserve_split"] = split.to_dict()
    return {
        "reserve_funding_ledger_json": _canonical(snapshot),
        "reserve_funding_ledger_hash": str(ledger.contract_hash),
    }


def verify_persisted_ledger_snapshot(allocation, stored_constraints: dict | None) -> ReserveFundingLedgerV1 | None:
    """Gespeicherten Ledger verifizieren; ``None`` = Legacy ohne Snapshot."""
    return verify_persisted_reserve_snapshot(allocation, stored_constraints)[0]


def verify_persisted_reserve_snapshot(
    allocation, stored_constraints: dict | None,
) -> tuple[ReserveFundingLedgerV1 | None, ReserveSplitSnapshotV1 | None]:
    """Gespeicherten Snapshot verifizieren -> (Ledger, Split); Legacy -> (None, None).

    Jede Teilmenge (Spalte ohne Referenz, Referenz ohne Spalte) und jede
    Abweichung zwischen Zeilen-Hash, Ledger-Feld, Hash-Spalte und
    Constraint-Referenz ist ein Integritaetsfehler (``ValueError``).
    """
    raw_json = getattr(allocation, "reserve_funding_ledger_json", None)
    raw_hash = getattr(allocation, "reserve_funding_ledger_hash", None)
    reference = (stored_constraints or {}).get(CONSTRAINTS_KEY)
    if raw_json is None and raw_hash is None and reference is None:
        return None, None
    if not (isinstance(raw_json, str) and raw_json.strip() and isinstance(raw_hash, str)
            and raw_hash.strip() and isinstance(reference, dict)):
        raise ValueError(
            "Persistierter Reserve-Funding-Ledger ist partiell: Snapshot, Hash-Spalte "
            "und gehashte Constraint-Referenz muessen gemeinsam vorliegen."
        )
    try:
        snapshot = json.loads(raw_json)
        version = snapshot.get("snapshot_version") if isinstance(snapshot, dict) else None
        expected_keys = {"snapshot_version", "ledger"} | (
            {"reserve_split"} if version == RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION_V2 else set()
        )
        if version not in (RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION, RESERVE_FUNDING_LEDGER_SNAPSHOT_VERSION_V2) or (
            set(snapshot) != expected_keys
        ):
            raise ValueError("unknown reserve ledger snapshot version")
        ledger = ledger_from_dict(snapshot.get("ledger"))
        split = split_from_dict(snapshot["reserve_split"]) if "reserve_split" in snapshot else None
        if split is not None:
            _check_split_matches_ledger(split, ledger)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Persistierter Reserve-Funding-Ledger ist ungueltig: {exc}") from exc
    recomputed = ledger_contract_hash(ledger)
    if not (recomputed == ledger.contract_hash == raw_hash == reference.get("contract_hash")):
        raise ValueError(
            "Reserve-Funding-Ledger-Hash stimmt nicht mit den persistierten "
            "Ledger-Zeilen bzw. der gehashten Referenz ueberein."
        )
    if reference != ledger_reference(ledger, split):
        raise ValueError(
            "Reserve-Funding-Ledger-Version/Policy widerspricht der gehashten Referenz."
        )
    stored_external = getattr(allocation, "external_reserve_at_generation_rappen", None)
    if split is not None and stored_external is not None and int(stored_external) != split.external_rappen:
        raise ValueError("Reserve-Split widerspricht der gespeicherten externen Reserve.")
    return ledger, split


@dataclass(frozen=True)
class ReserveLedgerReplay:
    """Ergebnis des Reloads: welcher Ledger die Analyse speist + Payload-Felder."""

    ledger: ReserveFundingLedgerV1
    status: str
    payload: dict


def replay_reserve_funding_ledger(
    allocation, stored_constraints: dict | None, *, live_ledger: ReserveFundingLedgerV1,
) -> ReserveLedgerReplay:
    """Historical Replay des gespeicherten Ledgers, Live-Preview getrennt.

    Aufruf erst NACH der Input-Staleness-Pruefung: unveraenderte Inputs plus
    abweichender Live-Ledger heisst, dass sich Compiler/Policy geaendert hat.
    """
    # Ohne verifizierten, gehashten Allocation-Context (echtes Legacy) ist ein
    # Snapshot nicht gebunden und wird nie als historische Evidence genutzt.
    stored = (
        None if stored_constraints is None
        else verify_persisted_ledger_snapshot(allocation, stored_constraints)
    )
    live_preview = {
        **live_ledger.to_dict(),
        "basis": "live_preview_current_compiler",
    }
    if stored is None:
        return ReserveLedgerReplay(
            ledger=live_ledger,
            status=REPLAY_UNVERIFIABLE,
            payload={
                # Kein historischer Ledger wird erfunden.
                "reserve_funding_ledger": None,
                "reserve_funding_ledger_replay": {
                    "mode": MODE_LEGACY_LIVE_PREVIEW,
                    "status": REPLAY_UNVERIFIABLE,
                    "analysis_basis": "live_preview",
                    "snapshot_hash": None,
                    "live_preview": live_preview,
                    "message": (
                        "Diese Soll-Allokation hat keinen gespeicherten Reserve-"
                        "Funding-Ledger und ist nicht replay-verifizierbar. Die "
                        "Analyse zeigt eine Live-Vorschau; vor einer Finalisierung "
                        "die Strategie neu berechnen."
                    ),
                },
            },
        )
    status = REPLAY_VERIFIED if live_ledger.contract_hash == stored.contract_hash else REPLAY_STALE
    replay_info = {
        "mode": MODE_HISTORICAL_REPLAY,
        "status": status,
        "analysis_basis": "persisted_snapshot",
        "snapshot_hash": stored.contract_hash,
        "live_preview": None if status == REPLAY_VERIFIED else live_preview,
    }
    if status == REPLAY_STALE:
        replay_info["message"] = (
            "Der Reserve-Funding-Ledger dieser Soll-Allokation weicht von der "
            "aktuellen Ledger-Policy ab (gespeichert "
            f"{stored.policy_version}, aktuell {live_ledger.policy_version}). "
            "Angezeigt wird der historische Entscheid; vor einer Finalisierung "
            "die Strategie neu berechnen."
        )
    return ReserveLedgerReplay(
        ledger=stored,
        status=status,
        payload={"reserve_funding_ledger": stored.to_dict(), "reserve_funding_ledger_replay": replay_info},
    )


# Finalisierungs-Sperre (CIO 2026-10-22): kundenfreundlicher Text mit
# Handlungsanweisung + maschinenlesbarer reason_code. Nach dem Deploy ist jede
# bestehende Allokation "unverifiable" -- der Berater muss sofort sehen, was zu
# tun ist (einmal neu berechnen), nicht einen technischen Integritaetsfehler.
REASON_RECALCULATION_REQUIRED = "RESERVE_LEDGER_RECALCULATION_REQUIRED"
REASON_LEDGER_STALE = "RESERVE_LEDGER_STALE"
FINALIZATION_MESSAGES = {
    REASON_RECALCULATION_REQUIRED: (
        "Die Strategie stammt aus einer früheren Version und muss einmal neu "
        "berechnet werden, bevor sie finalisiert werden kann. Bitte im "
        "Strategie-Schritt «Neu berechnen» ausführen."
    ),
    REASON_LEDGER_STALE: (
        "Die Berechnungsgrundlage der Liquiditätsreserve wurde seit dieser "
        "Strategie aktualisiert. Die Strategie muss einmal neu berechnet "
        "werden, bevor sie finalisiert werden kann. Bitte im Strategie-Schritt "
        "«Neu berechnen» ausführen."
    ),
}


def reserve_ledger_finalization_block(payload: dict | None) -> tuple[str, str] | None:
    """Fail-closed: nur ein replay-verifizierter Ledger ist finalisierbar.

    Liefert ``(reason_code, message)`` oder ``None``.
    """
    replay = (payload or {}).get("reserve_funding_ledger_replay") or {}
    status = replay.get("status")
    # RESERVE-CEILING-001: heutige Referenzdaten teilen die Reserve anders auf
    # als der gespeicherte Entscheid -> wie ein veralteter Ledger behandeln.
    split_status = ((payload or {}).get("reserve_split_replay") or {}).get("status")
    if status == REPLAY_VERIFIED and split_status == "stale":
        status = REPLAY_STALE
    if status == REPLAY_VERIFIED:
        return None
    code = REASON_LEDGER_STALE if status == REPLAY_STALE else REASON_RECALCULATION_REQUIRED
    return code, FINALIZATION_MESSAGES[code]


def reserve_ledger_finalization_error(payload: dict | None) -> str | None:
    block = reserve_ledger_finalization_block(payload)
    return None if block is None else block[1]


def finalization_reason_code(errors: list[str]) -> str | None:
    """reason_code der Ledger-Sperre, falls sie unter den Finalisierungsfehlern ist."""
    for code, message in FINALIZATION_MESSAGES.items():
        if message in errors:
            return code
    return None
