"""CCX-02 / CCX-P1: Effective-Input-Manifest eines Beratungsentscheids.

Jede wirkende Inputgruppe bekommt einen domaenenseparierten Kind-Hash
(``ares/advisory-envelope/1/<gruppe>``) ueber die fachlich sortierte
Projektion ihrer Zeilen; das Manifest bindet alle zehn Gruppen plus
Engine-Version, Zufallsstrom und ``rounding_policy_version`` und hat selbst
einen Kind-Hash (``effective-input-manifest``). Jede Aenderung einer
wirkenden Policy, CMA, Restriktion, eines Ziels, Cashflows, Profils, einer
Praeferenz oder eines Bestands aendert damit den Manifest-Hash (CCX-02).

Gruppen und Quelle (je Mandat, nur aktive/nicht geloeschte Zeilen):

* ``client``      -- Kundenzeile des Mandats
* ``mandate``     -- Mandatszeile
* ``goals``       -- Ziele, sortiert ``(priority=rank numerisch, due_date=target_date, id)``
* ``cashflows``   -- Cashflows und Zufluesse des Kunden
* ``risk``        -- das Risikoprofil, auf dem die Allokation beruht
* ``preference``  -- alle Nachhaltigkeitspraeferenz-Versionen (append-only)
* ``cma``         -- die CMA des Laufs
* ``policy``      -- Optimizer-Policy der Allokation + gebundene CMA-Policy
* ``constraints`` -- wirkende Restriktionen/Praeferenz-Snapshot der Allokation
* ``holdings``    -- Bestaende, sortiert ``(custodian_id, depot_id, position_id)``, abgebildet
  auf ``(depot_bank, depot_account_number, id)`` (Positionen) bzw.
  ``(depot_bank, custody_account_number, id)`` (Lauf-Bestaende)

``updated_at`` ist bewusst nicht Teil der Projektion: identische Inhalte
ergeben identische Hashes. Gleitkomma-Spalten werden als exakte
Dezimal-Zeichenkette gebunden (core/advisory_envelope_codec.py).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from core.advisory_envelope_codec import (
    MANIFEST_COMPONENTS,
    MANIFEST_SCHEMA_VERSION,
    manifest_hash,
    none_sort_key,
    rows_child_hash,
)
from core.presentation_rounding import ROUNDING_POLICY_VERSION
from models.allocation import BuildingBlock, CapitalMarketAssumption, HouseMatrix, OptimizerPolicy
from models.clients import ADVISORY_HASH_EXEMPT_INFO_KEY, ADVISORY_TENANT_BOUNDARY_COLUMNS, Client
from models.cma_policy import CmaPolicy, CmaPolicyApproval, CmaPolicyComponent
from models.mandates import Mandate
from models.profiling import (
    InvestmentPreferenceDecision,
    RiskAssessment,
    RiskCapacityPlausibilityEvaluation,
    RiskOverrideDecision,
    RiskProfileSignoff,
)
from models.review import RecommendationHolding
from models.wealth import (
    Cashflow,
    FinancialCoverageAttestation,
    Goal,
    GoalLifecycleTransition,
    GoalRevisionDecision,
    PlanningAssumption,
    WealthInflow,
    WealthPosition,
)

# KN3-B / N-917R2-01: ``tenant_id`` ist Mandantengrenze, kein Beratungsinhalt
# (Begruendung bei ADVISORY_TENANT_BOUNDARY_COLUMNS in database.py) --
# dieselbe Regel wie ``DependencySource.volatile`` im Hook (models/snapshots.py).
_EXCLUDED_COLUMNS = frozenset({"updated_at"}) | ADVISORY_TENANT_BOUNDARY_COLUMNS
# Kurzname (Adapter CCX-02) -> Manifest-Feld.
_SHORT_NAMES = {name[: -len("_hash")]: name for name in MANIFEST_COMPONENTS}
_SCALARS = ("tenant_id", "mandate_id", "engine_version", "random_stream_id", "rounding_policy_version")
# CCX-P2: Pflicht-Abhaengigkeiten fuer FRESH -- die Siegel-Pflichtgruppen
# (REQUIRED_GROUPS, sonst gar kein Siegel) plus die Benchmark-Lineage
# (Hausmatrix der Policy, CCX-06): leer heisst "unknown", nie "fresh".
REQUIRED_DEPENDENCY_KINDS = frozenset({
    "client", "mandate", "risk", "constraints", "cma", "optimizer_policy", "benchmark",
})
# CCX-P2: Marker fuer ein fehlendes Objekt einer Abhaengigkeitskante.
NO_OBJECT = "none"
CONSTRAINT_COLUMNS = (
    "id", "version", "effective_constraints_json", "preferences_json", "allocation_context_hash",
    "input_snapshot_hash", "reserve_funding_ledger_hash", "pension_transfer_ledger_snapshot_json",
    "band_equities_min_bps", "band_equities_max_bps", "band_bonds_min_bps", "band_bonds_max_bps",
    "band_real_estate_min_bps", "band_real_estate_max_bps", "band_alternatives_min_bps",
    "band_alternatives_max_bps", "band_liquidity_min_bps", "band_liquidity_max_bps",
    "valuation_date",
)


def build_effective_input_record(components: Mapping[str, Any]) -> dict[str, Any]:
    """Kanonischer Manifest-Datensatz aus Komponenten (Kurz- oder Feldnamen).

    Unbekannte Komponenten sind ein Fehler; eine nicht gelieferte Komponente
    wird als explizites ``null`` gebunden (nie still weggelassen)."""
    record: dict[str, Any] = {"schema_version": MANIFEST_SCHEMA_VERSION}
    record.update({name: None for name in _SCALARS[:2]})
    record.update({name: None for name in MANIFEST_COMPONENTS})
    record.update({name: None for name in _SCALARS[2:]})
    for key, value in components.items():
        field = _SHORT_NAMES.get(key, key)
        if field not in record or field == "schema_version":
            raise ValueError(f"Unbekannte Manifest-Komponente: {key!r}")
        record[field] = value
    return record


def build_effective_input_hash(components: Mapping[str, Any]) -> str:
    """Manifest-Hash ueber alle wirkenden Inputs (Adapter CCX-02)."""
    return manifest_hash(build_effective_input_record(components))


# ── Projektion der Datenbankzeilen ───────────────────────────────────────────


def _columns(model: Any, *, include_exempt: bool = False, include_boundary: bool = False) -> list[str]:
    """Projektion: alle Spalten ausser ``updated_at``, der Mandantengrenze
    ``tenant_id`` (KN3-B) und (KN-B / E2E2-04) den als nicht beratungsrelevant
    markierten (``Column(info=...)``, z. B. Beruf). ``include_boundary`` nur fuer
    die Uebergangs-Hashes bestehender Siegel (``_legacy_hashes``)."""
    excluded = _EXCLUDED_COLUMNS - ADVISORY_TENANT_BOUNDARY_COLUMNS if include_boundary else _EXCLUDED_COLUMNS
    return [
        attr.key for attr in sa_inspect(model).column_attrs
        if attr.key not in excluded
        and (include_exempt or not any(col.info.get(ADVISORY_HASH_EXEMPT_INFO_KEY) for col in attr.columns))
    ]


def _active(query, model):
    if hasattr(model, "deleted_at"):
        query = query.filter(model.deleted_at.is_(None))
    return query


def active_included_goals(db: Session, mandate_id: str) -> list[Any]:
    """CCX P5 / M-3: aktive, einbezogene Ziele eines Mandats (Quelle der
    kanonischen Zielkennzahl; dieselbe Zeilenmenge wie die Ziel-Kante)."""
    goals = _active(db.query(Goal).filter(Goal.mandate_id == str(mandate_id)), Goal).all()
    return [g for g in goals if int(getattr(g, "is_active", 1) or 0) == 1
            and int(getattr(g, "is_included", 1) or 0) == 1]


def _hash_rows(kind: str, model: Any, rows: Sequence[Any], sort_fields: Sequence[str], *,
               include_exempt: bool = False) -> str:
    return rows_child_hash(
        kind, _columns(model, include_exempt=include_exempt), list(rows),
        lambda row: tuple(none_sort_key(getattr(row, name)) for name in sort_fields),
    )


class _BoundaryCleared:
    """Zeilensicht mit geleerter Mandantengrenze (``tenant_id = NULL``): so
    sah eine in der ersten Sitzung versiegelte Zeile vor dem Start-Backfill aus."""

    __slots__ = ("_row",)

    def __init__(self, row: Any) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:
        if name in ADVISORY_TENANT_BOUNDARY_COLUMNS:
            return None
        return getattr(self._row, name)


def _legacy_hashes(kind: str, model: Any, rows: Sequence[Any], sort_fields: Sequence[str], *,
                   exempt_variants: Sequence[bool] = (False,)) -> tuple[str, ...]:
    """KN3-B / N-917R2-01, Uebergang: Siegel vor diesem Wechsel banden die
    Mandantengrenze mit. Sie bleiben aktuell, solange sich ausser ``tenant_id``
    nichts geaendert hat -- mit dem heutigen Wert (unveraendert) oder mit
    ``NULL`` (versiegelt vor dem Start-Backfill NULL -> 'main'). Eine
    beratungsrelevante Spalte deckt das nie zu: sie ist in jeder Variante
    gebunden. Ohne ``tenant_id``-Spalte gibt es keinen Uebergang."""
    if not ADVISORY_TENANT_BOUNDARY_COLUMNS & {attr.key for attr in sa_inspect(model).column_attrs}:
        return ()
    hashes: list[str] = []
    for include_exempt in exempt_variants:
        columns = _columns(model, include_exempt=include_exempt, include_boundary=True)
        for view in (list(rows), [_BoundaryCleared(row) for row in rows]):
            value = rows_child_hash(
                kind, columns, view,
                lambda row: tuple(none_sort_key(getattr(row, name)) for name in sort_fields),
            )
            if value not in hashes:
                hashes.append(value)
    return tuple(hashes)


def _combine(kind: str, parts: Mapping[str, str]) -> str:
    names = list(parts)
    return rows_child_hash(kind, names, [dict(parts)], lambda _row: ())


def _by_id(db: Session, model: Any, row_id: Any) -> list[Any]:
    if not row_id:
        return []
    row = db.query(model).filter(model.id == str(row_id)).first()
    return [row] if row is not None else []


# N-906-06 (unknown != complete): Pflichtgruppen, ohne die kein Entscheid
# versiegelt wird. Leer zulaessig (fachlich moeglich, als Hash ueber eine leere,
# typisierte Zeilenmenge gebunden): Ziele, Cashflows/Zufluesse,
# Nachhaltigkeitspraeferenz (vor der Erfassung), Bestaende, CMA-Policy (nur
# bei aktivem CMA-Policy-Modell gebunden).
REQUIRED_GROUPS: tuple[str, ...] = ("client", "mandate", "risk", "cma", "optimizer_policy", "constraints")


class ManifestIncomplete(ValueError):
    """Eine Pflicht-Inputgruppe ist unbekannt (keine Zeile) -- nicht siegelbar."""

    def __init__(self, groups: Sequence[str]) -> None:
        super().__init__("unknown: " + ", ".join(groups))
        self.groups = tuple(groups)


@dataclass(frozen=True)
class DependencyPart:
    """CCX-P2: eine Abhaengigkeitskante -- Art, Objekt, Version, Hash.

    ``dependency_hash`` ist exakt der Kind-Hash, aus dem die Manifest-
    Komponente gebildet wird (oder die Komponente selbst); ein fehlendes Objekt
    bleibt als ``none`` sichtbar (Hash ueber die leere Menge)."""

    kind: str
    object_id: str
    version: int | None
    dependency_hash: str
    # Anzahl gebundener Zeilen (-1 = nicht gezaehlt); eine leere
    # Pflicht-Inputgruppe ist "unknown", nie "fresh" (REQUIRED_DEPENDENCY_KINDS).
    row_count: int = -1
    # Hashes frueherer Projektionen derselben Zeilen (Uebergang): KN-B /
    # E2E2-04 (ganze Kundenzeile inkl. Beruf) und KN3-B / N-917R2-01
    # (inkl. Mandantengrenze, auch mit NULL vor dem Start-Backfill). Ein vor
    # dem Wechsel versiegelter Entscheid bleibt aktuell, solange sich die
    # gebundenen Zeilen nicht geaendert haben -- der Wechsel entwertet keinen
    # Bestand.
    legacy_hashes: tuple[str, ...] = ()

    def accepts(self, bound_hash: str | None, *, allow_legacy: bool = True) -> bool:
        """Ist ``bound_hash`` (Siegel) der heutige oder -- nur fuer Altsiegel
        (``allow_legacy``) -- ein Uebergangs-Hash?"""
        if not bound_hash:
            return False
        candidates = (self.dependency_hash, *self.legacy_hashes) if allow_legacy else (self.dependency_hash,)
        return any(str(bound_hash) == str(value) for value in candidates if value)


# KN4-B / N-917R3-06 (CTO-Entscheid): Uebergangs-Hashes (KN-B Beruf, KN3-B
# Mandantengrenze) gelten nur fuer Entscheide, die VOR der neuen Projektion
# versiegelt wurden. Seit diesem Stand versiegelte Entscheide binden ohnehin die
# neue Projektion; ein Altsiegel danach (Installation erst spaeter aktualisiert)
# wird im Zweifel STALE -- die sichere Richtung.
LEGACY_PROJECTION_SEALED_BEFORE = "2026-11-20T00:00:00.000Z"


def legacy_projection_allowed(sealed_at: str | None) -> bool:
    """Altsiegel-Uebergang nur fuer ``sealed_at`` vor dem Stichtag (ISO-Text)."""
    return bool(sealed_at) and str(sealed_at)[:23] < LEGACY_PROJECTION_SEALED_BEFORE[:23]


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    return int(value) if isinstance(value, int) else None


def _object_key(value: Any) -> str:
    return str(value) if value not in (None, "") else NO_OBJECT


def collect_dependency_parts(
    db: Session, *, mandate: Any, run: Any, target_allocation: Any,
) -> list[DependencyPart]:
    """Alle Abhaengigkeiten eines Beratungsentscheids als Kanten (frisch
    gelesen). Die Manifest-Komponenten (CCX-02) werden aus genau diesen
    Kind-Hashes gebildet; ``benchmark`` (Hausmatrix der Policy, CCX-06) ist
    eine zusaetzliche Kante ausserhalb des Manifests."""
    ta = target_allocation
    mandate_id = str(mandate.id)
    client_id = str(mandate.client_id)

    goals = _active(db.query(Goal).filter(Goal.mandate_id == mandate_id), Goal).all()
    cashflows = _active(db.query(Cashflow).filter(Cashflow.client_id == client_id), Cashflow).all()
    inflows = _active(db.query(WealthInflow).filter(WealthInflow.client_id == client_id), WealthInflow).all()
    positions = _active(
        db.query(WealthPosition).filter(WealthPosition.client_id == client_id), WealthPosition,
    ).all()
    run_holdings = _active(
        db.query(RecommendationHolding).filter(RecommendationHolding.run_id == str(run.id)),
        RecommendationHolding,
    ).all()
    preferences = (
        db.query(InvestmentPreferenceDecision)
        .filter(InvestmentPreferenceDecision.mandate_id == mandate_id)
        .all()
    )
    risk_id = getattr(ta, "based_on_assessment_id", None) or getattr(run, "assessment_id", None)
    cma_id = getattr(run, "capital_market_assumptions_id", None) or getattr(
        ta, "capital_market_assumptions_id", None,
    )
    policy_id = getattr(ta, "policy_id", None) or getattr(run, "policy_id", None)
    cma_policy_id = getattr(run, "cma_policy_row_id", None)
    constraints_rows = (
        [{name: getattr(ta, name, None) for name in CONSTRAINT_COLUMNS}] if ta is not None else []
    )
    cma_rows = _by_id(db, CapitalMarketAssumption, cma_id)
    policy_rows = _by_id(db, OptimizerPolicy, policy_id)
    house_matrix = (
        db.query(HouseMatrix).filter(HouseMatrix.policy_id == str(policy_id)).all() if policy_id else []
    )
    counts = {
        "client": 1 if client_id else 0, "goals": len(goals), "cashflows": len(cashflows),
        "wealth_inflows": len(inflows), "positions": len(positions), "run_holdings": len(run_holdings),
        "preference": len(preferences), "constraints": len(constraints_rows), "cma": len(cma_rows),
        "optimizer_policy": len(policy_rows), "benchmark": len(house_matrix),
    }
    def part(kind, object_id, version, hash_kind, model, rows, sort_fields, exempt_variants=(False,)):
        rows = list(rows)
        return DependencyPart(
            kind, object_id, version, _hash_rows(hash_kind, model, rows, sort_fields),
            legacy_hashes=_legacy_hashes(hash_kind, model, rows, sort_fields, exempt_variants=exempt_variants),
        )

    client_rows = _by_id(db, Client, client_id)
    parts = [
        # Kunde: Uebergang auch fuer die ganze Zeile inkl. Beruf (KN-B / E2E2-04).
        part("client", client_id, None, "client", Client, client_rows, ("id",), exempt_variants=(False, True)),
        part("mandate", mandate_id, None, "mandate", Mandate, _by_id(db, Mandate, mandate_id), ("id",)),
        part("goals", mandate_id, None, "goals", Goal, goals, ("rank", "target_date", "id")),
        part("cashflows", client_id, None, "cashflow-rows", Cashflow, cashflows, ("id",)),
        part("wealth_inflows", client_id, None, "inflow-rows", WealthInflow, inflows, ("id",)),
        part("positions", client_id, None, "position-rows", WealthPosition, positions,
             ("depot_bank", "depot_account_number", "id")),
        part("run_holdings", str(run.id), None, "run-holding-rows", RecommendationHolding, run_holdings,
             ("depot_bank", "custody_account_number", "id")),
        part("risk", _object_key(risk_id), None, "risk", RiskAssessment, _by_id(db, RiskAssessment, risk_id),
             ("id",)),
        part("preference", mandate_id, None, "preference", InvestmentPreferenceDecision, preferences,
             ("sequence_no", "id")),
        DependencyPart("constraints", _object_key(getattr(ta, "id", None)), _int_or_none(getattr(ta, "version", None)),
                       rows_child_hash("constraints", list(CONSTRAINT_COLUMNS), constraints_rows,
                                       lambda row: (str(row["id"]),))),
        part("cma", _object_key(cma_id), _int_or_none(getattr(cma_rows[0], "version", None)) if cma_rows else None,
             "cma", CapitalMarketAssumption, cma_rows, ("id",)),
        part("optimizer_policy", _object_key(policy_id),
             _int_or_none(getattr(policy_rows[0], "version", None)) if policy_rows else None,
             "optimizer-policy", OptimizerPolicy, policy_rows, ("id",)),
        part("cma_policy", _object_key(cma_policy_id), None, "cma-policy", CmaPolicy,
             _by_id(db, CmaPolicy, cma_policy_id), ("id",)),
        part("benchmark", _object_key(policy_id),
             _int_or_none(getattr(policy_rows[0], "version", None)) if policy_rows else None,
             "benchmark", HouseMatrix, house_matrix, ("score_from", "score_to", "id")),
    ]
    # N-908-04: auch die Tabellen, die der Hook bisher nur ueber die Reichweite
    # traf, bekommen eine Kante -- damit greift die Pull-Pruefung auch dort.
    def mandate_rows(model):
        return _active(db.query(model).filter(model.mandate_id == mandate_id), model).all()

    def rows_by(model, column, value):
        if not value:
            return []
        return _active(db.query(model).filter(getattr(model, column) == str(value)), model).all()

    for kind, model, rows, object_id in (
        ("goal_revisions", GoalRevisionDecision, mandate_rows(GoalRevisionDecision), mandate_id),
        ("goal_transitions", GoalLifecycleTransition, mandate_rows(GoalLifecycleTransition), mandate_id),
        ("planning", PlanningAssumption, mandate_rows(PlanningAssumption), mandate_id),
        ("risk_overrides", RiskOverrideDecision, mandate_rows(RiskOverrideDecision), mandate_id),
        ("risk_signoffs", RiskProfileSignoff, mandate_rows(RiskProfileSignoff), mandate_id),
        ("risk_plausibility", RiskCapacityPlausibilityEvaluation,
         mandate_rows(RiskCapacityPlausibilityEvaluation), mandate_id),
        ("coverage_attestations", FinancialCoverageAttestation,
         mandate_rows(FinancialCoverageAttestation), mandate_id),
        ("building_blocks", BuildingBlock, rows_by(BuildingBlock, "policy_id", policy_id), _object_key(policy_id)),
        ("cma_policy_components", CmaPolicyComponent,
         rows_by(CmaPolicyComponent, "policy_row_id", cma_policy_id), _object_key(cma_policy_id)),
        ("cma_policy_approvals", CmaPolicyApproval,
         rows_by(CmaPolicyApproval, "policy_row_id", cma_policy_id), _object_key(cma_policy_id)),
    ):
        parts.append(part(kind, object_id, None, kind.replace("_", "-"), model, rows, ("id",)))
        counts[kind] = len(rows)
    counts["mandate"] = 1 if _by_id(db, Mandate, mandate_id) else 0
    counts["client"] = 1 if _by_id(db, Client, client_id) else 0
    counts["risk"] = 1 if _by_id(db, RiskAssessment, risk_id) else 0
    counts["cma_policy"] = 1 if _by_id(db, CmaPolicy, cma_policy_id) else 0
    return [replace(part, row_count=counts.get(part.kind, -1)) for part in parts]


def empty_required_kinds(parts: Sequence[DependencyPart]) -> list[str]:
    """Pflicht-Inputgruppen ohne gebundene Zeile (CCX-P2: unknown != fresh)."""
    return sorted(part.kind for part in parts if part.kind in REQUIRED_DEPENDENCY_KINDS and part.row_count == 0)


def components_from_parts(parts: Sequence[DependencyPart]) -> dict[str, str]:
    """Zehn Manifest-Komponenten aus den Kanten (byte-gleich zu P1)."""
    by_kind = {part.kind: part.dependency_hash for part in parts}
    return {
        "client_hash": by_kind["client"],
        "mandate_hash": by_kind["mandate"],
        "goals_hash": by_kind["goals"],
        "cashflows_hash": _combine("cashflows", {
            "cashflows": by_kind["cashflows"], "inflows": by_kind["wealth_inflows"],
        }),
        "risk_hash": by_kind["risk"],
        "preference_hash": by_kind["preference"],
        "cma_hash": by_kind["cma"],
        "policy_hash": _combine("policy", {
            "optimizer_policy": by_kind["optimizer_policy"], "cma_policy": by_kind["cma_policy"],
        }),
        "constraints_hash": by_kind["constraints"],
        "holdings_hash": _combine("holdings", {
            "positions": by_kind["positions"], "run_holdings": by_kind["run_holdings"],
        }),
    }


def collect_effective_input_components(
    db: Session, *, mandate: Any, run: Any, target_allocation: Any,
    parts_out: list[DependencyPart] | None = None,
) -> dict[str, str]:
    """Kind-Hash je Inputgruppe (zehn Manifest-Komponenten), frisch gelesen.
    ``parts_out`` (CCX-P2) erhaelt die Kanten derselben Lesung.

    Fehlt eine Pflichtgruppe (``REQUIRED_GROUPS``), wirft die Funktion
    ``ManifestIncomplete`` statt einen Hash ueber null Zeilen zu binden."""
    parts = collect_dependency_parts(db, mandate=mandate, run=run, target_allocation=target_allocation)
    counts = {part.kind: part.row_count for part in parts}
    missing = [name for name in REQUIRED_GROUPS if counts.get(name, 0) <= 0]
    if missing:
        raise ManifestIncomplete(missing)
    if parts_out is not None:
        parts_out.extend(parts)
    return components_from_parts(parts)


def engine_version_of(run: Any, target_allocation: Any) -> str:
    version = str(getattr(run, "optimizer_version", None) or "").strip()
    method = str(getattr(target_allocation, "optimization_method", None) or "").strip()
    return f"optimizer={version or 'unknown'};method={method or 'unknown'}"


def random_stream_id_of(target_allocation: Any) -> str:
    """Zufallsstrom der Allokation, wie gespeichert (P6 versioniert den
    vollstaendigen CRN-Vertrag); ein fehlender Seed bleibt sichtbar."""
    seed = getattr(target_allocation, "optimization_seed", None)
    method = str(getattr(target_allocation, "optimization_method", None) or "").strip() or "unknown"
    return f"{method}:seed={seed if seed is not None else 'none'}"


def build_manifest_record(
    *, tenant_id: str, mandate_id: str, components: Mapping[str, str], run: Any, target_allocation: Any,
) -> dict[str, Any]:
    record = build_effective_input_record({
        "tenant_id": tenant_id,
        "mandate_id": mandate_id,
        **components,
        "engine_version": engine_version_of(run, target_allocation),
        "random_stream_id": random_stream_id_of(target_allocation),
        "rounding_policy_version": ROUNDING_POLICY_VERSION,
    })
    missing = [name for name in MANIFEST_COMPONENTS if not record.get(name)]
    if missing:
        raise ValueError(f"Manifest unvollstaendig: {missing}")
    return record


__all__ = [
    "CONSTRAINT_COLUMNS",
    "DependencyPart",
    "NO_OBJECT",
    "REQUIRED_DEPENDENCY_KINDS",
    "REQUIRED_GROUPS",
    "ManifestIncomplete",
    "build_effective_input_hash",
    "build_effective_input_record",
    "build_manifest_record",
    "collect_dependency_parts",
    "collect_effective_input_components",
    "components_from_parts",
    "empty_required_kinds",
    "engine_version_of",
    "random_stream_id_of",
    "legacy_projection_allowed",
    "LEGACY_PROJECTION_SEALED_BEFORE",
]
