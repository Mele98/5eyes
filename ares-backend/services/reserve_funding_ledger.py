"""RESERVE-FUNDING-LEDGER-001: quellengebundener Ledger der externen Reserve.

Hintergrund (PR #638, Codex-Review 2026-10-18): Die externe Reserve ``E`` wird
vor Solver und Reporting aus dem Beratungsvermoegen ``A`` herausgeloest
(Start ``I = A - E``). Sie bleibt Geld des Kunden. PR #638 buchte ``E`` im
Generate-Solver als aggregierten Pool greedy in jeden spaeteren Abfluss
zurueck. Drei Luecken blieben offen:

1. Der Pool kannte keine Herkunft und konnte einen reinen ``minReserve``-/
   Policy-Floor in ein sachfremdes spaetes Ziel umetikettieren.
2. Die Ziel-Sensitivity zog ``E`` ab, gab es aber nie zurueck, und rechnete
   ``E`` fuer den Gegenlauf nicht neu.
3. Das Reporting-MC verglich IST auf ``A`` mit SOLL auf ``A - E`` -- eine
   kuenstliche Differenz ``E`` selbst bei Nullrendite.

Dieser Ledger ist die eine Stelle, die festlegt, welcher Teil von ``E`` wofuer
gebildet wurde und wann er zurueckfliesst. Generate (Solver), Sensitivity
(je Goal-Set neu kompiliert), deterministische Simulation, Reporting-MC,
Goal-Analyse und Reload konsumieren dieselbe ``release_series``.

Zerlegung von ``E`` (Policy ``need_first_pro_rata_v1``):

* Der Bedarf stammt aus derselben Herleitung wie die Reservehoehe
  (``_compute_reserve_for_inputs(need_breakdown=...)``): je Ausgabenziel ein
  Betrag (``goal``-Tranche) plus der nahe Cashflow-Fehlbetrag
  (``cashflow_deficit``-Tranche, Fenster 3 Jahre wie bei der Bemessung).
* ``R = max(Floor, Bedarf)``: Floor und Bedarf ueberlappen. Der Teil von ``R``,
  der ueber den Bedarf hinausgeht, ist ein dauerhafter Mindestbestand
  (``policy_floor``) und wird NIE freigegeben.
* ``E`` deckt zuerst den Bedarf (anteilig, groesster Rest, stabil nach
  Tranche-ID), erst der Rest ist Floor. Grund: Weil die Reservehoehe Floor
  und Bedarf ueberlappend (``max``) bemisst, muss nach Zahlung aller
  Bedarfe genau ``R - Bedarf`` uebrig bleiben; Floor-first wuerde Bedarf aus
  dem Portfolio bezahlen und zugleich mehr Bargeld dauerhaft blockieren.
* Jede Tranche fliesst nur in die Abfluesse ihrer eigenen Quelle zurueck
  (Ziel-Tranche -> Liability-Pfad genau dieses Ziels; Cashflow-Tranche ->
  negative Cashflows im Bemessungsfenster), chronologisch, je Jahr hoechstens
  in Hoehe des Abflusses, als Bargeld ohne Rendite.
* Was nicht freigegeben wird, bleibt als Reservekonto beim Kunden
  (``unspent``) und erscheint im Reporting im wirtschaftlichen Gesamtwert.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace

RESERVE_FUNDING_LEDGER_VERSION = "reserve_funding_ledger_v1"
RESERVE_RELEASE_POLICY_VERSION = "need_first_pro_rata_source_bound_v1"
# Bemessungsfenster des Cashflow-Fehlbetrags in _compute_reserve_for_inputs
# (``recurring_cashflow_projection_series_rappen[:3]`` bzw. ``abs(net) * 3``).
CASHFLOW_DEFICIT_WINDOW_YEARS = 3
# Marker im Simulations-/MC-Payload: SOLL-Pfade enthalten das Reservekonto
# (investierbarer Teil + noch nicht freigegebene externe Reserve). Konsumenten
# (Frontend, PDF) duerfen ``external_reserve_rappen`` dann NICHT erneut
# aufschlagen.
RESERVE_ACCOUNTING_BASIS = "economic_total_incl_external_reserve_v1"


@dataclass(frozen=True)
class ReserveTranche:
    tranche_id: str
    source_kind: str  # goal | cashflow_deficit | policy_floor
    source_id: str
    need_rappen: int  # bemessener Bedarf dieser Quelle (vor Intern/Extern-Split)
    amount_rappen: int  # davon extern gehalten (Teil von E)
    eligible_from_index: int
    eligible_to_index: int  # inklusive; -1 = nie freigebbar
    releasable: bool
    goal_rank: int | None = None
    hardness: str | None = None


@dataclass(frozen=True)
class ReserveRelease:
    year_index: int
    tranche_id: str
    destination_kind: str  # goal | cashflow_deficit
    destination_id: str
    amount_rappen: int


@dataclass(frozen=True)
class ReserveFundingLedgerV1:
    horizon_years: int
    reserve_needed_rappen: int
    total_external_rappen: int
    total_internal_rappen: int
    tranches: tuple[ReserveTranche, ...]
    releases: tuple[ReserveRelease, ...]
    release_series_rappen: tuple[int, ...]
    unspent_floor_rappen: int
    unreleased_need_rappen: int
    version: str = RESERVE_FUNDING_LEDGER_VERSION
    policy_version: str = RESERVE_RELEASE_POLICY_VERSION
    contract_hash: str = field(default="")

    # -- Konsumenten-API ---------------------------------------------------
    def release_prefix(self, length: int) -> list[int]:
        """Release-Serie auf ``length`` Jahre (abgeschnitten oder mit 0 aufgefuellt)."""
        series = [int(v) for v in self.release_series_rappen[: max(0, int(length))]]
        return series + [0] * (max(0, int(length)) - len(series))

    def effective_cashflow_series(self, raw_cashflows: list[int]) -> list[int]:
        """``raw + release`` -- die Cashflow-Serie, die ein Solver auf ``A - E`` sieht."""
        raw = [int(v) for v in raw_cashflows]
        return [value + rel for value, rel in zip(raw, self.release_prefix(len(raw)))]

    def to_dict(self) -> dict:
        return asdict(self)


def _hash_payload(payload: dict) -> str:
    payload = {key: value for key, value in payload.items() if key != "contract_hash"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def ledger_contract_hash(ledger: ReserveFundingLedgerV1) -> str:
    """Neuberechnung des Hashs -- Replay/Manipulationspruefung."""
    return _hash_payload(ledger.to_dict())


def _pro_rata(total: int, weights: list[tuple[str, int]]) -> dict[str, int]:
    """Groesster-Rest-Verteilung, eingabereihenfolgeunabhaengig (Tiebreak: ID)."""
    ordered = sorted(weights, key=lambda item: item[0])
    weight_sum = sum(weight for _key, weight in ordered)
    if total <= 0 or weight_sum <= 0:
        return {key: 0 for key, _weight in ordered}
    shares = {key: (total * weight) // weight_sum for key, weight in ordered}
    remainder = total - sum(shares.values())
    by_fraction = sorted(
        ordered,
        key=lambda item: (-((total * item[1]) % weight_sum), item[0]),
    )
    for key, _weight in by_fraction[:remainder]:
        shares[key] += 1
    return shares


def compile_reserve_funding_ledger(
    *,
    reserve_needed_rappen: int,
    external_reserve_rappen: int,
    goal_needs: list[dict],
    cashflow_deficit_need_rappen: int,
    cashflow_series_rappen: list[int],
    goal_liability_paths: dict[str, list[int]],
    horizon_years: int,
) -> ReserveFundingLedgerV1:
    """Reiner Compiler (keine DB, keine Engine-Imports).

    ``goal_needs``: [{"goal_id", "need_rappen", "rank", "hardness"}].
    ``goal_liability_paths``: goal_id -> Liability-Pfad (Index wie Cashflows).
    """
    from services.portfolio_engine_reserve import _tranche_release_series

    external = int(external_reserve_rappen or 0)
    needed = int(reserve_needed_rappen or 0)
    if external < 0 or needed < 0:
        raise ValueError("reserve amounts must be >= 0")
    horizon = max(0, int(horizon_years))

    # Bedarfstranchen (stabile IDs; doppelte Goal-IDs werden zusammengefasst).
    need_by_id: dict[str, dict] = {}
    for item in goal_needs:
        amount = int(item.get("need_rappen") or 0)
        if amount <= 0:
            continue
        goal_id = str(item["goal_id"])
        tranche_id = f"goal:{goal_id}"
        entry = need_by_id.setdefault(tranche_id, {
            "source_kind": "goal", "source_id": goal_id, "need": 0,
            "rank": item.get("rank"), "hardness": item.get("hardness"),
        })
        entry["need"] += amount
    if int(cashflow_deficit_need_rappen or 0) > 0:
        need_by_id["cashflow_deficit:near_term"] = {
            "source_kind": "cashflow_deficit", "source_id": "near_term",
            "need": int(cashflow_deficit_need_rappen), "rank": None, "hardness": None,
        }
    need_total = sum(entry["need"] for entry in need_by_id.values())
    # Need-first: E deckt zuerst den Bedarf (hoechstens R), der Rest ist Floor.
    external_need = min(external, need_total, needed if needed > 0 else need_total)
    shares = _pro_rata(external_need, [(key, entry["need"]) for key, entry in need_by_id.items()])

    tranches: list[ReserveTranche] = []
    releases: list[ReserveRelease] = []
    release_series = [0] * horizon
    unreleased_need = 0
    padded_cf = ([int(v) for v in cashflow_series_rappen] + [0] * horizon)[:horizon]
    for tranche_id in sorted(need_by_id):
        entry = need_by_id[tranche_id]
        amount = int(shares.get(tranche_id, 0))
        if entry["source_kind"] == "goal":
            eligible_to = horizon - 1
            path = [int(v) for v in (goal_liability_paths.get(entry["source_id"]) or [])]
            outflow_cf, outflow_liab = [0] * horizon, (path + [0] * horizon)[:horizon]
            destination_kind = "goal"
        else:
            eligible_to = min(horizon, CASHFLOW_DEFICIT_WINDOW_YEARS) - 1
            outflow_cf = [
                value if index <= eligible_to else 0 for index, value in enumerate(padded_cf)
            ]
            outflow_liab = [0] * horizon
            destination_kind = "cashflow_deficit"
        tranches.append(ReserveTranche(
            tranche_id=tranche_id, source_kind=entry["source_kind"],
            source_id=entry["source_id"], need_rappen=int(entry["need"]),
            amount_rappen=amount, eligible_from_index=0, eligible_to_index=eligible_to,
            releasable=True,
            goal_rank=None if entry["rank"] is None else int(entry["rank"]),
            hardness=None if entry["hardness"] is None else str(entry["hardness"]),
        ))
        tranche_release = _tranche_release_series(amount, outflow_cf, outflow_liab)
        for year_index, released in enumerate(tranche_release):
            if released > 0:
                release_series[year_index] += released
                releases.append(ReserveRelease(
                    year_index=year_index, tranche_id=tranche_id,
                    destination_kind=destination_kind,
                    destination_id=entry["source_id"], amount_rappen=int(released),
                ))
        unreleased_need += amount - sum(tranche_release)

    floor_amount = external - external_need
    if floor_amount > 0:
        tranches.append(ReserveTranche(
            tranche_id="policy_floor", source_kind="policy_floor", source_id="reserve_floor",
            need_rappen=max(0, needed - need_total), amount_rappen=floor_amount,
            eligible_from_index=0, eligible_to_index=-1, releasable=False,
        ))
    releases.sort(key=lambda item: (item.year_index, item.tranche_id))
    if sum(release_series) > external:  # Invariante: jede CHF hoechstens einmal
        raise ValueError("reserve release exceeds external reserve")
    ledger = ReserveFundingLedgerV1(
        horizon_years=horizon,
        reserve_needed_rappen=needed,
        total_external_rappen=external,
        total_internal_rappen=max(0, needed - external),
        tranches=tuple(tranches),
        releases=tuple(releases),
        release_series_rappen=tuple(release_series),
        unspent_floor_rappen=floor_amount,
        unreleased_need_rappen=unreleased_need,
    )
    return replace(ledger, contract_hash=ledger_contract_hash(ledger))


def compile_reserve_funding_ledger_for_inputs(
    *,
    reserve_inputs: dict,
    goals: list,
    reserve_needed_rappen: int,
    external_reserve_rappen: int,
    solver_cashflow_series_rappen: list[int],
    inflation_series_bps: list[int] | None,
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: list[int] | None = None,
    horizon_years: int | None = None,
) -> ReserveFundingLedgerV1:
    """Der EINE Compiler fuer alle Konsumenten (Generate, Sensitivity, Reload).

    ``reserve_inputs`` traegt die Bemessungsgroessen der Reserve
    (``recurring_net_cashflow_rappen``,
    ``recurring_cashflow_projection_series_rappen``,
    ``inflow_projection_series_rappen``) -- das Engine-``inputs``-Dict passt.
    Der Bedarf kommt aus derselben Herleitung wie die Reservehoehe; die
    Liability-Pfade aus demselben ``goals_to_liabilities`` wie im Solver.
    ``horizon_years`` default = Solver-Horizont ``max(10, len(cashflows))``.
    """
    from services.optimizer.goal_liabilities import goals_to_liabilities
    from services.portfolio_engine_reserve import _compute_reserve_for_inputs

    horizon = int(horizon_years or max(10, len(solver_cashflow_series_rappen) or 10))
    breakdown: dict = {}
    _compute_reserve_for_inputs(
        goals=list(goals), limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=int(reserve_inputs.get("recurring_net_cashflow_rappen") or 0),
        recurring_cashflow_projection_series_rappen=list(
            reserve_inputs.get("recurring_cashflow_projection_series_rappen") or []
        ),
        advisory_wealth_rappen=0, saa_liquidity_ceiling_bps=0, reasoning=None,
        inflow_projection_series_rappen=list(
            reserve_inputs.get("inflow_projection_series_rappen") or []
        ),
        need_breakdown=breakdown,
        goal_inflation_series_bps=inflation_series_bps,
    )
    goal_needs = [
        {
            "goal_id": str(getattr(goal, "id", None) or f"goal-index-{index}"),
            "need_rappen": int(amount),
            "rank": getattr(goal, "rank", None),
            "hardness": getattr(goal, "hardness", None),
        }
        for index, (goal, amount) in enumerate(breakdown.get("goal_needs") or [])
    ]
    liability_paths: dict[str, list[int]] = {}
    if int(external_reserve_rappen or 0) > 0 and goal_needs:
        liabilities = goals_to_liabilities(
            list(goals),
            horizon_years=horizon,
            inflation_series_bps=inflation_series_bps,
            external_wealth_rappen=max(0, int(external_wealth_rappen or 0)),
            external_wealth_series_rappen=(
                list(external_wealth_series_rappen)[: horizon + 1] or None
                if external_wealth_series_rappen is not None
                else None
            ),
        )
        for liability in liabilities:
            path = [int(v) for v in liability.liability_path_rappen[:horizon]]
            previous = liability_paths.get(str(liability.goal_id))
            liability_paths[str(liability.goal_id)] = (
                path if previous is None else [a + b for a, b in zip(previous, path)]
            )
    return compile_reserve_funding_ledger(
        reserve_needed_rappen=int(reserve_needed_rappen or 0),
        external_reserve_rappen=int(external_reserve_rappen or 0),
        goal_needs=goal_needs,
        cashflow_deficit_need_rappen=int(breakdown.get("cashflow_deficit_rappen") or 0),
        cashflow_series_rappen=list(solver_cashflow_series_rappen),
        goal_liability_paths=liability_paths,
        horizon_years=horizon,
    )


@dataclass(frozen=True)
class ReserveFundedSolverInputs:
    """Was ein Solverlauf auf ``A - E`` braucht -- aus EINEM Ledger kompiliert."""

    start_wealth_rappen: int
    cashflow_series_rappen: tuple[int, ...]
    ledger: ReserveFundingLedgerV1

    def solver_kwargs(self) -> dict:
        """Start, Cashflows und Ziel-Freigaben fuer ``run_solver``.

        GOAL-ATTRIBUTION-CASHFLOW-INVERSION-001 (Engine v10): die Freigaben je
        Ziel braucht der direkte Prioritaets-Scope-Replay, um die Freigabe
        eines Ziels ausserhalb des Scopes zusammen mit dessen Abfluss zu
        entfernen.
        """
        from services.optimizer.priority_scope import goal_release_series_from_ledger

        return {
            "advisory_wealth_rappen": self.start_wealth_rappen,
            "cashflow_series_rappen": list(self.cashflow_series_rappen),
            "reserve_goal_release_series_rappen": goal_release_series_from_ledger(
                self.ledger, int(self.ledger.horizon_years),
            ),
        }


def compile_goal_set_funding(
    *,
    reserve_inputs: dict,
    goals: list,
    limits_prefs: dict,
    asset_class_prefs: dict,
    saa_liquidity_ceiling_bps: int,
    rebase_cashflows,
    run_horizon: int,
    inflation_series_bps: list[int] | None,
    external_wealth_rappen: int,
    external_wealth_series_rappen: list[int] | None,
) -> ReserveFundedSolverInputs:
    """Sensitivity: Reserve, Startvermoegen und Release JE GOAL-SET neu.

    Baseline und Gegenlauf teilen CMA, Szenarien und Objective-Vertrag, aber
    nicht die Finanzierungsbasis: aendert sich ein reservewirksames Ziel,
    aendern sich ``R``, ``E``, ``A - E`` und das Release-Matching. Der
    Gegenlauf erbt davon nichts von der Baseline. ``rebase_cashflows(start)``
    liefert die Solver-Cashflows fuer das jeweilige investierbare Vermoegen
    (dynamische Vermoegenssteuer haengt am Startwert).
    """
    from services.portfolio_engine_reserve import _compute_reserve_for_inputs

    advisory = int(reserve_inputs["advisory_wealth_rappen"])
    reserve_needed, external = _compute_reserve_for_inputs(
        goals=list(goals),
        limits_prefs=limits_prefs,
        asset_class_prefs=asset_class_prefs,
        recurring_net_cashflow_rappen=int(reserve_inputs["recurring_net_cashflow_rappen"]),
        recurring_cashflow_projection_series_rappen=list(
            reserve_inputs["recurring_cashflow_projection_series_rappen"]
        ),
        advisory_wealth_rappen=advisory,
        saa_liquidity_ceiling_bps=int(saa_liquidity_ceiling_bps),
        reasoning=None,
        unlocked_other_assets_rappen=int(reserve_inputs.get("unlocked_other_assets_rappen") or 0),
        inflow_projection_series_rappen=list(
            reserve_inputs.get("inflow_projection_series_rappen") or []
        ),
        goal_inflation_series_bps=inflation_series_bps,
    )
    start = max(0, advisory - max(0, int(external)))
    raw = [int(v) for v in rebase_cashflows(start)][: int(run_horizon)]
    ledger = compile_reserve_funding_ledger_for_inputs(
        reserve_inputs=reserve_inputs,
        goals=goals,
        reserve_needed_rappen=reserve_needed,
        external_reserve_rappen=external,
        solver_cashflow_series_rappen=raw,
        inflation_series_bps=list(inflation_series_bps or [])[: int(run_horizon)],
        external_wealth_rappen=external_wealth_rappen,
        external_wealth_series_rappen=external_wealth_series_rappen,
        horizon_years=int(run_horizon),
    )
    return ReserveFundedSolverInputs(
        start_wealth_rappen=start,
        cashflow_series_rappen=tuple(ledger.effective_cashflow_series(raw)),
        ledger=ledger,
    )
