"""RESERVE-CEILING-001 (Rest): exakter Reserve-Split und sein Snapshot.

Codex-Re-Audit 2026-10-17 zu Commit 80789d7, zwei offene Vertraege:

1. Rappenexaktheit. ``_saa_internal_reserve_rappen`` verglich den Bedarf in
   bereits auf ganze Basispunkte GERUNDETEN bps mit dem Ceiling. Ein
   Ueberhang unter 0.5 bp (CHF 10 bei CHF 600'000 und 200 bps) galt als
   "innerhalb" und wurde voll intern gehalten -- das monetaere Cap wurde
   gelockert. Jetzt: Integervergleich ``R * 10000 > A * c`` und Cap
   ``floor(A * c / 10000)`` (nie mehr intern als das Cap erlaubt).
2. Snapshot. Reload leitete das Ceiling aus der HEUTIGEN HouseMatrix ab und
   publizierte fuer denselben gespeicherten Entscheid eine andere externe
   Reserve (CHF 132k statt gespeicherter CHF 138k). Jetzt persistiert
   Generate den Split als ``ReserveSplitSnapshotV1`` (hash-gebunden, im
   Reserve-Ledger-Snapshot und in der Constraint-Referenz); Reload
   publiziert ausschliesslich den gespeicherten Split, die Neubewertung mit
   heutigen Referenzdaten erscheint getrennt als Live-Preview mit Drift.

Deckungsgleichung (jeder Rappen Bedarf genau einmal):

    reserve_needed = internal + absorbed + external + coverage_gap

``internal`` liegt in der SAA (Teil von I = A - E), ``external`` wird aus A
herausgeloest. Beide zusammen koennen A nie uebersteigen; ein Bedarf ueber
dem Vermoegen erscheint als ``coverage_gap`` statt doppelt gezaehlt.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace

RESERVE_SPLIT_SNAPSHOT_VERSION = "reserve_split_snapshot_v1"
CAP_ROUNDING_POLICY = "exact_integer_compare_floor_cap_v1"

SPLIT_VERIFIED = "verified"
SPLIT_STALE = "stale"
SPLIT_LEDGER_AMOUNTS_ONLY = "ledger_amounts_only"
SPLIT_UNVERIFIABLE = "unverifiable"


def internal_reserve_cap_rappen(advisory_wealth_rappen: int, ceiling_bps: int) -> int:
    """Monetaeres Cap der internen Reserve, exakt in Rappen (abgerundet)."""
    wealth = int(advisory_wealth_rappen or 0)
    bps = int(ceiling_bps or 0)
    if wealth <= 0 or bps <= 0:
        return 0
    return wealth * bps // 10000


def exact_internal_reserve_rappen(
    reserve_needed_rappen: int, advisory_wealth_rappen: int, ceiling_bps: int,
) -> int:
    """Interner Teil: Bedarf, hoechstens das exakte Cap -- ohne bps-Vorrundung."""
    needed = int(reserve_needed_rappen or 0)
    wealth = int(advisory_wealth_rappen or 0)
    if needed <= 0 or wealth <= 0:
        return 0
    if needed * 10000 > wealth * max(0, int(ceiling_bps or 0)):
        return internal_reserve_cap_rappen(wealth, ceiling_bps)
    return needed


@dataclass(frozen=True)
class ReserveSplitSnapshotV1:
    reserve_needed_rappen: int
    internal_rappen: int
    absorbed_rappen: int
    external_rappen: int
    coverage_gap_rappen: int
    advisory_wealth_rappen: int
    investable_wealth_rappen: int
    unlocked_other_assets_rappen: int
    ceiling_bps: int
    ceiling_rappen: int
    version: str = RESERVE_SPLIT_SNAPSHOT_VERSION
    cap_rounding_policy: str = CAP_ROUNDING_POLICY
    contract_hash: str = field(default="")

    def to_dict(self) -> dict:
        return asdict(self)


def split_contract_hash(split: ReserveSplitSnapshotV1) -> str:
    payload = {key: value for key, value in split.to_dict().items() if key != "contract_hash"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def split_reserve(
    *,
    reserve_needed_rappen: int,
    advisory_wealth_rappen: int,
    ceiling_bps: int,
    unlocked_other_assets_rappen: int = 0,
) -> ReserveSplitSnapshotV1:
    """Die EINE Aufteilungsregel (intern -> anderes Vermoegen -> extern -> Luecke)."""
    needed = max(0, int(reserve_needed_rappen or 0))
    wealth = int(advisory_wealth_rappen or 0)
    unlocked = max(0, int(unlocked_other_assets_rappen or 0))
    internal = exact_internal_reserve_rappen(needed, wealth, ceiling_bps)
    absorbed = external = 0
    if wealth > 0 and internal < needed:
        remaining = needed - internal
        absorbed = min(unlocked, remaining)
        # Intern gehaltene Reserve liegt bereits in A: extern hoechstens der Rest.
        external = min(remaining - absorbed, max(0, wealth - internal))
    split = ReserveSplitSnapshotV1(
        reserve_needed_rappen=needed,
        internal_rappen=internal,
        absorbed_rappen=absorbed,
        external_rappen=external,
        coverage_gap_rappen=needed - internal - absorbed - external,
        advisory_wealth_rappen=wealth,
        investable_wealth_rappen=max(0, wealth - external),
        unlocked_other_assets_rappen=unlocked,
        ceiling_bps=int(ceiling_bps or 0),
        ceiling_rappen=internal_reserve_cap_rappen(wealth, ceiling_bps),
    )
    return replace(split, contract_hash=split_contract_hash(split))


def split_from_dict(data: dict) -> ReserveSplitSnapshotV1:
    """Strikte Rekonstruktion (unbekannte/fehlende Felder -> ValueError)."""
    if not isinstance(data, dict):
        raise ValueError("reserve split snapshot must be an object")
    if set(data) != {item.name for item in fields(ReserveSplitSnapshotV1)}:
        raise ValueError("reserve split snapshot fields do not match ReserveSplitSnapshotV1")
    split = ReserveSplitSnapshotV1(**data)
    if split.version != RESERVE_SPLIT_SNAPSHOT_VERSION:
        raise ValueError("unknown reserve split snapshot version")
    if split_contract_hash(split) != split.contract_hash:
        raise ValueError("reserve split snapshot hash does not match its fields")
    parts = split.internal_rappen + split.absorbed_rappen + split.external_rappen + split.coverage_gap_rappen
    if parts != split.reserve_needed_rappen or min(
        split.internal_rappen, split.absorbed_rappen, split.external_rappen, split.coverage_gap_rappen
    ) < 0:
        raise ValueError("reserve split snapshot violates the coverage identity")
    return split


def generation_reserve_split(
    reserve_needed_rappen: int,
    external_reserve_rappen: int,
    *,
    ceiling_bps: int,
    advisory_wealth_rappen: int,
    unlocked_other_assets_rappen: int = 0,
    **_other_reserve_inputs,
) -> ReserveSplitSnapshotV1:
    """Split zum Generierungszeitpunkt; fail-closed gegen eine zweite Herleitung.

    Nimmt die Reserve-Bemessungsinputs von Generate unveraendert entgegen
    (Ziele/Cashflows werden fuer den Split nicht gebraucht).
    """
    split = split_reserve(
        reserve_needed_rappen=reserve_needed_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        ceiling_bps=ceiling_bps,
        unlocked_other_assets_rappen=unlocked_other_assets_rappen,
    )
    if split.external_rappen != int(external_reserve_rappen or 0) or (
        split.reserve_needed_rappen != max(0, int(reserve_needed_rappen or 0))
    ):
        raise ValueError("Reserve-Split weicht von der bemessenen externen Reserve ab.")
    return split


def _chf(rappen: int) -> str:
    return f"{int(rappen) // 100:,}".replace(",", "'")


@dataclass(frozen=True)
class ReserveSplitReplay:
    """Reload: welche Reservebetraege die Analyse speisen + Payload-Felder."""

    reserve_needed_rappen: int
    external_reserve_rappen: int
    status: str
    payload: dict


def replay_reserve_split(
    *,
    stored_split: ReserveSplitSnapshotV1 | None,
    stored_ledger,
    live_split: ReserveSplitSnapshotV1,
) -> ReserveSplitReplay:
    """Historischer Split, getrennt von der Neubewertung mit heutigen Referenzdaten.

    ``stored_split``/``stored_ledger`` sind bereits verifiziert (oder ``None``).
    """
    live = {**live_split.to_dict(), "basis": "live_re_evaluation_current_reference_data"}
    if stored_split is not None:
        status = SPLIT_VERIFIED if stored_split.contract_hash == live_split.contract_hash else SPLIT_STALE
        info = {
            "mode": "historical_replay", "status": status, "snapshot_hash": stored_split.contract_hash,
            "live_re_evaluation": None if status == SPLIT_VERIFIED else live,
            "external_reserve_drift_rappen": live_split.external_rappen - stored_split.external_rappen,
        }
        if status == SPLIT_STALE:
            info["message"] = (
                "Die Liquiditaetsreserve wuerde mit den heutigen Referenzdaten anders "
                f"aufgeteilt (extern gespeichert CHF {_chf(stored_split.external_rappen)}, "
                f"heute CHF {_chf(live_split.external_rappen)}). Angezeigt wird der "
                "historische Entscheid; vor einer Finalisierung die Strategie neu berechnen."
            )
        return ReserveSplitReplay(
            stored_split.reserve_needed_rappen, stored_split.external_rappen, status,
            {"reserve_split": stored_split.to_dict(), "reserve_split_replay": info},
        )
    if stored_ledger is not None:
        # Ledger-Snapshot ohne Split (vor diesem Vertrag): die Betraege sind
        # hash-gebunden historisch, die Aufteilung selbst ist nicht belegt.
        needed, external = int(stored_ledger.reserve_needed_rappen), int(stored_ledger.total_external_rappen)
        status = SPLIT_LEDGER_AMOUNTS_ONLY
    else:
        needed, external = live_split.reserve_needed_rappen, live_split.external_rappen
        status = SPLIT_UNVERIFIABLE
    info = {
        "mode": "historical_replay" if stored_ledger is not None else "legacy_live_preview",
        "status": status, "snapshot_hash": None, "live_re_evaluation": live,
        "external_reserve_drift_rappen": live_split.external_rappen - external,
    }
    return ReserveSplitReplay(needed, external, status, {"reserve_split": None, "reserve_split_replay": info})


def replay_allocation_reserve_split(
    allocation, stored_constraints: dict | None, live_split: ReserveSplitSnapshotV1,
) -> ReserveSplitReplay:
    """Reload: gespeicherten Snapshot verifizieren und den Split replayen."""
    from services.reserve_funding_ledger_snapshot import verify_persisted_reserve_snapshot

    stored_ledger, stored_split = (
        (None, None) if stored_constraints is None
        else verify_persisted_reserve_snapshot(allocation, stored_constraints)
    )
    return replay_reserve_split(stored_split=stored_split, stored_ledger=stored_ledger, live_split=live_split)


def generation_reserve_ceiling_bps(allocation, verified_constraints: dict | None, fallback) -> int:
    """Ceiling, mit dem der gespeicherte Entscheid die Reserve aufgeteilt hat.

    Sensitivity-Baseline und -Gegenlauf referenzieren den Generation-Snapshot;
    nur ohne Split-Snapshot (Legacy) wird aus heutigen Referenzdaten
    rekonstruiert (``fallback()``).
    """
    from services.reserve_funding_ledger_snapshot import verify_persisted_reserve_snapshot

    if verified_constraints is not None:
        _ledger, split = verify_persisted_reserve_snapshot(allocation, verified_constraints)
        if split is not None:
            return int(split.ceiling_bps)
    return int(fallback())
