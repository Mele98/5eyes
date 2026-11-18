"""K1: Property-/Collateral-Gate bis zur P1-Schliessung (Codex-Entscheid 2026-11-19).

Entscheid "Product-Evidence-Vertrag und Property-Launchentscheid", Kapitel
"Bis P1-Schliessung hart deaktivieren": Wohneigentum und Hypothek bleiben im
normalen Erfassungs- und Gesamtvermoegenspfad (Marktwert, Waehrung,
Bewertungsdatum, Quelle; Hypothek mit Betrag, Waehrung, Typ, Zinssatz,
Faelligkeit, verknuepfter Immobilie; Brutto/Verbindlichkeiten/Netto im
P3-FX-Snapshot; Immobilie als nicht handelbarer Sockel). Hart deaktiviert sind:

* ``is_available_for_goal_funding`` fuer Direktimmobilien und illiquide Werte
  (Alternative/Custom, Policen): keine Collateral-/Verwertungsanrechnung im
  Reserve-/Goal-Funding-Pool. Liquiditaet und Depot bleiben anrechenbar,
  uebrige Vorsorge nur mit belegtem Bezugsdatum (bestehendes Gate).
* ``goal_funding_method`` Verkauf/Belehnung/Automatisch fuer illiquide Werte;
  "Belehnung" (Collateral-Claim) fuer jede Position.
* Collateral/LTV, automatische Refinanzierungs- und Amortisationsprojektionen
  (Zinssprung nach Ablauf/SARON-Frist, sinkende Schuld, verpfaendete
  3a-Serie) und -- damit es genau EINE Cashflow-Abbildung gibt -- die
  automatisch abgeleiteten Hypothekar-Cashflows (Zins, Amortisation). Zins und
  Amortisation erfasst der Berater als Ausgaben-Cashflow; die Maske sagt das
  ausdruecklich. Keine Doppelzaehlung: die Automatik liefert 0.
* die angenommene Wertsteigerung der Direktimmobilie
  (``asset_expected_return_bps``) als Optimizer-/Prognose-Input; die Immobilie
  wird nominal flach fortgeschrieben.
* positive Claims aus Belehnung/Veraeusserung (folgen aus den Punkten oben).

Kein Laufzeitschalter: ``PROPERTY_ADVANCED_FEATURES_ENABLED`` ist eine
Code-Konstante; Wiedereinschalten erst mit dem Funding-Modus-Vertrag (P1,
OWN-PROP-02). API-Schreibversuche enden mit 409
``PROPERTY_ADVANCED_FEATURE_DISABLED``; Altbestand wird per Migration
neutralisiert und je Position als Owner-Review-Fall
(``wealth_positions.property_gate_review_json``) protokolliert.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from core.reason_codes import DomainError, ReasonCode
from services.wealth_position_semantics import (
    canonical_position_type,
    is_direct_real_estate_position,
    is_mortgage_position,
)

PROPERTY_ADVANCED_FEATURES_ENABLED = False

# Illiquide Werte, deren Anrechnung nur ueber Verwertung (Verkauf, Belehnung,
# Rueckkauf) moeglich waere: Direktimmobilie, Alternative/Custom und Policen.
# Vorsorge im Uebrigen bleibt dem bestehenden Verfuegbarkeits-Gate
# (PENSION-AVAILABILITY-001, nur mit belegtem, erreichtem Bezugsdatum) unterstellt;
# Liquiditaet und Depot sind heute verfuegbar.
ILLIQUID_GOAL_FUNDING_POSITION_TYPES = frozenset({"Immobilien", "Alternative", "Custom"})
ILLIQUID_PENSION_VEHICLES = frozenset({"Police"})
LIQUID_ONLY_FUNDING_METHODS = frozenset({"Verkauf", "Automatisch"})
COLLATERAL_FUNDING_METHODS = frozenset({"Belehnung"})
NEUTRAL_FUNDING_METHOD = "Ignorieren"
MIXED_MORTGAGE_TYPE = "Gemischt"

FEATURE_GOAL_FUNDING_COLLATERAL = "goal_funding_collateral"
FEATURE_GOAL_FUNDING_METHOD = "goal_funding_method"
FEATURE_AMORTIZATION_PROJECTION = "mortgage_amortization_projection"
FEATURE_PROPERTY_RETURN_INPUT = "property_return_input"
REVIEW_MORTGAGE_TYPE_MIXED = "mortgage_type_mixed_legacy"

REVIEW_SCHEMA = "ares/property-gate-review/1"

DISABLED_HINT = (
    "Erweiterte Immobilien-/Belehnungsfunktionen sind bis zur Abnahme deaktiviert "
    "(Verkauf/Belehnung zur Zielfinanzierung, Amortisations-/Refinanzierungsprojektion, "
    "angenommene Wertsteigerung). Immobilie und Hypothek bleiben normal erfassbar; "
    "Hypothekarzins und Amortisation bitte als Ausgaben-Cashflow erfassen."
)


def is_illiquid_goal_funding_source(position_type: Any, pension_vehicle: Any = None) -> bool:
    if canonical_position_type(position_type) in ILLIQUID_GOAL_FUNDING_POSITION_TYPES:
        return True
    return canonical_position_type(position_type) == "Vorsorge" and pension_vehicle in ILLIQUID_PENSION_VEHICLES


def goal_funding_flag_counts(position: Any) -> bool:
    """Darf das Goal-Funding-Flag dieser Position den Reserve-Pool speisen?"""
    if PROPERTY_ADVANCED_FEATURES_ENABLED:
        return True
    return not is_illiquid_goal_funding_source(
        getattr(position, "position_type", None), getattr(position, "pension_vehicle", None),
    )


def effective_property_growth_bps(position: Any) -> int:
    """Wertsteigerung der Direktimmobilie fuer Prognose/Optimizer (Gate: 0)."""
    if not PROPERTY_ADVANCED_FEATURES_ENABLED:
        return 0
    return int(getattr(position, "asset_expected_return_bps", 0) or 0)


def mortgage_projection_enabled() -> bool:
    """Automatische Hypothekar-Cashflows, Refinanzierungs- und
    Amortisationsprojektionen (Gate: aus)."""
    return PROPERTY_ADVANCED_FEATURES_ENABLED


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return int(value or 0) == 1
    except (TypeError, ValueError):
        return False


def disabled_features(position_type: Any, values: Mapping[str, Any]) -> list[str]:
    """Deaktivierte Funktionen, die ``values`` (geschriebene Felder) aktivieren
    wuerden. Nur gesetzte Schluessel zaehlen."""
    if PROPERTY_ADVANCED_FEATURES_ENABLED:
        return []
    found: list[str] = []
    liquid = not is_illiquid_goal_funding_source(position_type, values.get("pension_vehicle"))
    if "is_available_for_goal_funding" in values and _truthy(values.get("is_available_for_goal_funding")) and not liquid:
        found.append(FEATURE_GOAL_FUNDING_COLLATERAL)
    method = values.get("goal_funding_method") if "goal_funding_method" in values else None
    if method in COLLATERAL_FUNDING_METHODS or (method in LIQUID_ONLY_FUNDING_METHODS and not liquid):
        found.append(FEATURE_GOAL_FUNDING_METHOD)
    if is_mortgage_position(position_type) and int(values.get("mortgage_amortization_rappen") or 0) > 0:
        found.append(FEATURE_AMORTIZATION_PROJECTION)
    if is_direct_real_estate_position(position_type) and int(values.get("asset_expected_return_bps") or 0) != 0:
        found.append(FEATURE_PROPERTY_RETURN_INPUT)
    return found


def require_property_write_allowed(position_type: Any, values: Mapping[str, Any]) -> None:
    """409 ``PROPERTY_ADVANCED_FEATURE_DISABLED`` statt stillem Ignorieren."""
    features = disabled_features(position_type, values)
    if features:
        raise DomainError(
            ReasonCode.PROPERTY_ADVANCED_FEATURE_DISABLED,
            DISABLED_HINT,
            extra={"features": features},
        )


def require_mortgage_type_allowed(position_type: Any, new_type: Any, current_type: Any = None) -> None:
    """PROP-2: "Gemischt" fuer neue Werte abgelehnt (als zwei Hypotheken
    erfassen); ein unveraenderter Altbestand bleibt speicherbar."""
    if not is_mortgage_position(position_type):
        return
    if new_type == MIXED_MORTGAGE_TYPE and current_type != MIXED_MORTGAGE_TYPE:
        raise DomainError(
            ReasonCode.MORTGAGE_TYPE_MIXED_REJECTED,
            "Hypothekartyp 'Gemischt' wird nicht mehr angenommen: bitte als zwei Hypotheken "
            "(Festhypothek und SARON) mit je eigenem Betrag und Zinssatz erfassen.",
            http_status=422,
        )


def review_findings(position: Any) -> list[dict[str, Any]]:
    """Owner-Review-Faelle einer bestehenden Position: aktive Werte deaktivierter
    Funktionen (werden neutralisiert) und offene Altbestaende (bleiben)."""
    ptype = getattr(position, "position_type", None)
    illiquid = is_illiquid_goal_funding_source(ptype, getattr(position, "pension_vehicle", None))
    out: list[dict[str, Any]] = []
    if _truthy(getattr(position, "is_available_for_goal_funding", 0)) and illiquid:
        out.append({"feature": FEATURE_GOAL_FUNDING_COLLATERAL, "field": "is_available_for_goal_funding",
                    "previous": 1, "action": "set_0"})
    method = getattr(position, "goal_funding_method", None)
    if method in COLLATERAL_FUNDING_METHODS or (method in LIQUID_ONLY_FUNDING_METHODS and illiquid):
        out.append({"feature": FEATURE_GOAL_FUNDING_METHOD, "field": "goal_funding_method",
                    "previous": method, "action": "set_" + NEUTRAL_FUNDING_METHOD})
    if is_mortgage_position(ptype) and int(getattr(position, "mortgage_amortization_rappen", 0) or 0) > 0:
        out.append({"feature": FEATURE_AMORTIZATION_PROJECTION, "field": "mortgage_amortization_rappen",
                    "previous": int(position.mortgage_amortization_rappen), "action": "set_0"})
    if is_direct_real_estate_position(ptype) and int(getattr(position, "asset_expected_return_bps", 0) or 0) != 0:
        out.append({"feature": FEATURE_PROPERTY_RETURN_INPUT, "field": "asset_expected_return_bps",
                    "previous": int(position.asset_expected_return_bps), "action": "set_null"})
    if is_mortgage_position(ptype) and getattr(position, "mortgage_type", None) == MIXED_MORTGAGE_TYPE:
        out.append({"feature": REVIEW_MORTGAGE_TYPE_MIXED, "field": "mortgage_type",
                    "previous": MIXED_MORTGAGE_TYPE, "action": "keep_open"})
    return out


def review_json(findings: list[dict[str, Any]], *, recorded_at: str) -> str:
    return json.dumps(
        {"schema": REVIEW_SCHEMA, "reason_code": ReasonCode.PROPERTY_ADVANCED_FEATURE_DISABLED.value,
         "status": "OPEN", "recorded_at": recorded_at, "findings": findings},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


_LEGACY_COLUMNS = (
    "id", "client_id", "position_type", "pension_vehicle", "is_available_for_goal_funding",
    "goal_funding_method",
    "mortgage_amortization_rappen", "asset_expected_return_bps", "mortgage_type",
    "property_gate_review_json",
)
_NEUTRAL_VALUES = {
    "set_0": 0,
    "set_" + NEUTRAL_FUNDING_METHOD: NEUTRAL_FUNDING_METHOD,
    "set_null": None,
}

_log = logging.getLogger(__name__)


def neutralize_legacy_property_values(conn: Any, *, recorded_at: str | None = None) -> list[dict[str, Any]]:
    """Migration (Alembic und SQLite-Startpfad): aktive Werte deaktivierter
    Funktionen im Bestand auf Ignorieren/false/0 setzen und je Position als
    Owner-Review-Fall in ``property_gate_review_json`` festhalten (alter Wert,
    Aktion) -- nicht still verwerfen. Altbestand "Gemischt" bleibt unveraendert
    und wird offen gemeldet. Idempotent: ein zweiter Lauf aendert nichts."""
    from sqlalchemy import text

    recorded = recorded_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(text(
        f"SELECT {', '.join(_LEGACY_COLUMNS)} FROM wealth_positions WHERE deleted_at IS NULL ORDER BY id"
    )).mappings().all()
    cases: list[dict[str, Any]] = []
    for row in rows:
        findings = review_findings(SimpleNamespace(**dict(row)))
        actionable = [f for f in findings if f["action"] != "keep_open"]
        existing = row["property_gate_review_json"]
        if not actionable and (not findings or existing):
            continue
        previous_findings: list[dict[str, Any]] = []
        if existing:
            try:
                previous_findings = list(json.loads(existing).get("findings") or [])
            except (TypeError, ValueError, AttributeError):
                previous_findings = [{"feature": "unreadable_previous_review", "previous": str(existing)}]
        known = {json.dumps(f, sort_keys=True) for f in previous_findings}
        merged = previous_findings + [f for f in findings if json.dumps(f, sort_keys=True) not in known]
        assignments = {f["field"]: _NEUTRAL_VALUES[f["action"]] for f in actionable}
        assignments["property_gate_review_json"] = review_json(merged, recorded_at=recorded)
        set_sql = ", ".join(f"{column} = :{column}" for column in assignments)
        conn.execute(
            text(f"UPDATE wealth_positions SET {set_sql} WHERE id = :position_id"),
            {**assignments, "position_id": row["id"]},
        )
        cases.append({"position_id": row["id"], "client_id": row["client_id"], "findings": findings})
    if cases:
        _log.warning(
            "K1 Property-Gate: %d Position(en) als Owner-Review-Fall markiert "
            "(PROPERTY_ADVANCED_FEATURE_DISABLED): %s",
            len(cases), ", ".join(c["position_id"] for c in cases),
        )
    return cases


def model_basis_labels() -> dict[str, str]:
    """Ehrliche Modellbasis: welche Property-Semantik der Lauf tatsaechlich
    verwendet hat (bindet die Gate-Lage in den Basis-/Kontext-Hash)."""
    if PROPERTY_ADVANCED_FEATURES_ENABLED:
        return {
            "indirect_amortization_treatment": "pledged_asset_transfer_v1",
            "direct_real_estate_return_basis": "position_price_appreciation_plus_explicit_rent_v2",
        }
    return {
        "property_advanced_features": "disabled_until_p1_closure_v1",
        "mortgage_cashflow_treatment": "manual_cashflow_only_v1",
        "indirect_amortization_treatment": "disabled_until_p1_closure_v1",
        "direct_real_estate_return_basis": "nominal_flat_plus_explicit_rent_v1",
    }


__all__ = [
    "model_basis_labels",
    "neutralize_legacy_property_values",
    "DISABLED_HINT",
    "PROPERTY_ADVANCED_FEATURES_ENABLED",
    "disabled_features",
    "effective_property_growth_bps",
    "goal_funding_flag_counts",
    "mortgage_projection_enabled",
    "require_mortgage_type_allowed",
    "require_property_write_allowed",
    "review_findings",
    "review_json",
]
