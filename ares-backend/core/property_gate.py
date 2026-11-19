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
* ``goal_funding_method`` Belehnung (jede Position) bzw. Verkauf/Automatisch
  (illiquide Werte).
* Collateral/LTV, automatische Refinanzierungs- und Amortisationsprojektionen
  (Zinssprung nach Ablauf/SARON-Frist, sinkende Schuld, verpfaendete
  3a-Serie) und -- damit es genau EINE Cashflow-Abbildung gibt -- die
  automatisch abgeleiteten Hypothekar-Cashflows (Zins, Amortisation). Zins und
  Amortisation erfasst der Berater als Ausgaben-Cashflow; die Maske sagt das.
* die angenommene Wertsteigerung der Direktimmobilie
  (``asset_expected_return_bps``) als Prognose-/Optimizer-Input.
* positive Claims aus Belehnung/Veraeusserung (folgen aus den Punkten oben).

Kein Laufzeitschalter: ``PROPERTY_ADVANCED_FEATURES_ENABLED`` ist eine
Code-Konstante; Wiedereinschalten erst mit dem Funding-Modus-Vertrag (P1,
OWN-PROP-02). API-Schreibversuche enden mit 409
``PROPERTY_ADVANCED_FEATURE_DISABLED`` (routers/wealth.py); Altbestand wird
per Migration neutralisiert und je Position als Owner-Review-Fall
(``wealth_positions.property_gate_review_json``) festgehalten
(``database.neutralize_legacy_property_values``).

Stdlib-Blatt (architecture ratchets, FAN_OUT_EXEMPT_LEAVES): nur reine
Konstanten und Funktionen, keine Projektimporte.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

PROPERTY_ADVANCED_FEATURES_ENABLED = False

DIRECT_REAL_ESTATE = "Immobilien"
MORTGAGE = "Hypothek"
PENSION = "Vorsorge"
# Bekannte Alt-Bezeichnungen (wie services.wealth_position_semantics).
_TYPE_ALIASES = {
    "Immobilie": DIRECT_REAL_ESTATE, "Liegenschaft": DIRECT_REAL_ESTATE,
    "Pensionskasse": PENSION,
}
ILLIQUID_GOAL_FUNDING_POSITION_TYPES = frozenset({DIRECT_REAL_ESTATE, "Alternative", "Custom"})
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

REASON_DISABLED = "PROPERTY_ADVANCED_FEATURE_DISABLED"
REASON_MIXED_REJECTED = "MORTGAGE_TYPE_MIXED_REJECTED"
REVIEW_SCHEMA = "ares/property-gate-review/1"

DISABLED_HINT = (
    "Erweiterte Immobilien-/Belehnungsfunktionen sind bis zur Abnahme deaktiviert "
    "(Verkauf/Belehnung zur Zielfinanzierung, Amortisations-/Refinanzierungsprojektion, "
    "angenommene Wertsteigerung). Immobilie und Hypothek bleiben normal erfassbar; "
    "Hypothekarzins und Amortisation bitte als Ausgaben-Cashflow erfassen."
)
MIXED_HINT = (
    "Hypothekartyp 'Gemischt' wird nicht mehr angenommen: bitte als zwei Hypotheken "
    "(Festhypothek und SARON) mit je eigenem Betrag und Zinssatz erfassen."
)

NEUTRAL_VALUES = {"set_0": 0, "set_" + NEUTRAL_FUNDING_METHOD: NEUTRAL_FUNDING_METHOD, "set_null": None}
LEGACY_COLUMNS = (
    "id", "client_id", "position_type", "pension_vehicle", "is_available_for_goal_funding",
    "goal_funding_method", "mortgage_amortization_rappen", "asset_expected_return_bps",
    "mortgage_type", "property_gate_review_json",
)


def canonical_type(position_type: Any) -> str:
    raw = str(position_type or "").strip()
    return _TYPE_ALIASES.get(raw, raw)


def is_illiquid_goal_funding_source(position_type: Any, pension_vehicle: Any = None) -> bool:
    ptype = canonical_type(position_type)
    if ptype in ILLIQUID_GOAL_FUNDING_POSITION_TYPES:
        return True
    return ptype == PENSION and pension_vehicle in ILLIQUID_PENSION_VEHICLES


def goal_funding_flag_counts(position_type: Any, pension_vehicle: Any = None) -> bool:
    """Darf das Goal-Funding-Flag dieser Position den Reserve-Pool speisen?"""
    if PROPERTY_ADVANCED_FEATURES_ENABLED:
        return True
    return not is_illiquid_goal_funding_source(position_type, pension_vehicle)


def effective_property_growth_bps(entered_bps: Any) -> int:
    """Wertsteigerung der Direktimmobilie fuer Prognose/Optimizer (Gate: 0)."""
    if not PROPERTY_ADVANCED_FEATURES_ENABLED:
        return 0
    return int(entered_bps or 0)


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
    """Deaktivierte Funktionen, die die geschriebenen Felder ``values``
    aktivieren wuerden (nur gesetzte Schluessel zaehlen)."""
    if PROPERTY_ADVANCED_FEATURES_ENABLED:
        return []
    ptype = canonical_type(position_type)
    illiquid = is_illiquid_goal_funding_source(ptype, values.get("pension_vehicle"))
    found: list[str] = []
    if _truthy(values.get("is_available_for_goal_funding")) and illiquid:
        found.append(FEATURE_GOAL_FUNDING_COLLATERAL)
    method = values.get("goal_funding_method")
    if method in COLLATERAL_FUNDING_METHODS or (method in LIQUID_ONLY_FUNDING_METHODS and illiquid):
        found.append(FEATURE_GOAL_FUNDING_METHOD)
    if ptype == MORTGAGE and int(values.get("mortgage_amortization_rappen") or 0) > 0:
        found.append(FEATURE_AMORTIZATION_PROJECTION)
    if ptype == DIRECT_REAL_ESTATE and int(values.get("asset_expected_return_bps") or 0) != 0:
        found.append(FEATURE_PROPERTY_RETURN_INPUT)
    return found


def mixed_mortgage_rejected(position_type: Any, new_type: Any, current_type: Any = None) -> bool:
    """PROP-2: "Gemischt" fuer neue Werte abgelehnt; unveraenderter Altbestand
    bleibt speicherbar."""
    return (
        canonical_type(position_type) == MORTGAGE
        and new_type == MIXED_MORTGAGE_TYPE
        and current_type != MIXED_MORTGAGE_TYPE
    )


def review_findings(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Owner-Review-Faelle einer bestehenden Position: aktive Werte deaktivierter
    Funktionen (werden neutralisiert) und offene Altbestaende (bleiben)."""
    ptype = canonical_type(row.get("position_type"))
    illiquid = is_illiquid_goal_funding_source(ptype, row.get("pension_vehicle"))
    out: list[dict[str, Any]] = []
    if _truthy(row.get("is_available_for_goal_funding")) and illiquid:
        out.append({"feature": FEATURE_GOAL_FUNDING_COLLATERAL, "field": "is_available_for_goal_funding",
                    "previous": 1, "action": "set_0"})
    method = row.get("goal_funding_method")
    if method in COLLATERAL_FUNDING_METHODS or (method in LIQUID_ONLY_FUNDING_METHODS and illiquid):
        out.append({"feature": FEATURE_GOAL_FUNDING_METHOD, "field": "goal_funding_method",
                    "previous": method, "action": "set_" + NEUTRAL_FUNDING_METHOD})
    amortization = int(row.get("mortgage_amortization_rappen") or 0)
    if ptype == MORTGAGE and amortization > 0:
        out.append({"feature": FEATURE_AMORTIZATION_PROJECTION, "field": "mortgage_amortization_rappen",
                    "previous": amortization, "action": "set_0"})
    growth = int(row.get("asset_expected_return_bps") or 0)
    if ptype == DIRECT_REAL_ESTATE and growth != 0:
        out.append({"feature": FEATURE_PROPERTY_RETURN_INPUT, "field": "asset_expected_return_bps",
                    "previous": growth, "action": "set_null"})
    if ptype == MORTGAGE and row.get("mortgage_type") == MIXED_MORTGAGE_TYPE:
        out.append({"feature": REVIEW_MORTGAGE_TYPE_MIXED, "field": "mortgage_type",
                    "previous": MIXED_MORTGAGE_TYPE, "action": "keep_open"})
    return out


def review_json(findings: list[dict[str, Any]], *, recorded_at: str) -> str:
    return json.dumps(
        {"schema": REVIEW_SCHEMA, "reason_code": REASON_DISABLED, "status": "OPEN",
         "recorded_at": recorded_at, "findings": findings},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def neutralization_update(row: Mapping[str, Any], *, recorded_at: str) -> dict[str, Any] | None:
    """Spaltenwerte, die eine Bestandszeile neutralisieren und den Owner-Review-
    Fall festhalten; ``None`` = nichts zu tun (idempotent)."""
    findings = review_findings(row)
    actionable = [f for f in findings if f["action"] != "keep_open"]
    existing = row.get("property_gate_review_json")
    if not actionable and (not findings or existing):
        return None
    previous: list[dict[str, Any]] = []
    if existing:
        try:
            loaded = json.loads(existing)
            previous = list(loaded.get("findings") or []) if isinstance(loaded, dict) else []
        except (TypeError, ValueError):
            previous = [{"feature": "unreadable_previous_review", "previous": str(existing)}]
    known = {json.dumps(f, sort_keys=True) for f in previous}
    merged = previous + [f for f in findings if json.dumps(f, sort_keys=True) not in known]
    update = {f["field"]: NEUTRAL_VALUES[f["action"]] for f in actionable}
    update["property_gate_review_json"] = review_json(merged, recorded_at=recorded_at)
    return update


def model_basis_labels() -> dict[str, str]:
    """Ehrliche Modellbasis: welche Property-Semantik der Lauf verwendet hat."""
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
    "DISABLED_HINT",
    "MIXED_HINT",
    "PROPERTY_ADVANCED_FEATURES_ENABLED",
    "disabled_features",
    "effective_property_growth_bps",
    "goal_funding_flag_counts",
    "mixed_mortgage_rejected",
    "model_basis_labels",
    "mortgage_projection_enabled",
    "neutralization_update",
    "review_findings",
    "review_json",
]
