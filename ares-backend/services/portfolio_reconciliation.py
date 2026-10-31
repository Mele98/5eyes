"""Abgleich Depotbestand <-> Beratungsvermoegen (PORTFOLIO-DATA-001, Entscheiddokument 2026-10-27 §6).

Zwei Seiten (``depot`` = Quelle/Custodian, ``advisory`` = Basis der Beratung)
werden getrennt nach Kategorien abgeglichen und nie miteinander verrechnet:

- ``quantity``: Stueckzahl je Position, exakt (Toleranz 0);
- ``cash``: Cash je Waehrung in kleinster Einheit, exakt (Toleranz 0);
- ``price``: Preis und Preiswaehrung je Position;
- ``fx``: FX-Kurs je Waehrung (als Dezimalzahl verglichen);
- ``market_value``: Marktwert je Position in Basiswaehrung;
- ``perimeter``: Position fehlt auf einer Seite oder liegt in einer anderen
  Zeile (``depot``, ``external``, ``liabilities``, ``excluded``).

Voraussetzungen (nicht erklaerbar, blockieren immer): gleiche Basiswaehrung,
gleicher Bewertungsstichtag, gleiche Perimeter-Definition. Eine unbekannte,
nicht bewertete oder nicht klassifizierte Position blockiert unabhaengig vom
Betrag; Erklaerungen koennen sie nicht uebersteuern.

Eine Differenz ist erklaert nur durch eine typisierte Erklaerung mit Quelle,
Evidenz und getrennter Freigabe (Freigebende Person != erfassende Person).
Mengen- und Cash-Reste muessen danach exakt null sein, Preis-/FX-Abweichungen
brauchen eine Erklaerung (sie sind keine Rundung). Fuer den Marktwert gilt
nach Erklaerungen der Rundungsrest der Policy: je Position
``per_position_tolerance_minor_units`` und je Zeile die Summe der absoluten
Reste ``aggregate_tolerance_major_units`` (absolute Summe: Reste duerfen sich
nicht gegenseitig aufheben).

Betraege sind ganze Zahlen in 1/100 der Waehrung (Projektkonvention ``*_rappen``).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.evidence import SCHEME_V1_ASCII, canonical_json, evidence_hash
from services.portfolio_data_policy import PortfolioDataPolicy

MINOR_UNITS_PER_MAJOR = 100

POSITION_LINES = ("depot", "external", "liabilities", "excluded")
CATEGORIES = ("quantity", "cash", "price", "fx", "market_value", "perimeter")

EXPLANATION_TYPES = {
    "PENDING_TRADE": ("quantity", "cash", "market_value"),
    "PENDING_CASH_MOVEMENT": ("cash",),
    "CORPORATE_ACTION": ("quantity", "price", "market_value"),
    "PRICE_TIMING": ("price", "market_value"),
    "FX_TIMING": ("fx", "market_value"),
    "PERIMETER_DECISION": ("perimeter",),
}
_AMOUNT_CATEGORIES = ("quantity", "cash", "market_value")

STATUS_RECONCILED = "reconciled"
STATUS_UNEXPLAINED = "unexplained_difference"
STATUS_BLOCKED = "blocked"


def _canonical(payload) -> str:
    return canonical_json(payload, scheme=SCHEME_V1_ASCII)


def _sha256(payload) -> str:
    return evidence_hash(payload, scheme=SCHEME_V1_ASCII)


def _int_or_none(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _decimal_or_none(value):
    if value is None or isinstance(value, (bool, float)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _positions_by_key(side: dict) -> tuple[dict, list[str]]:
    by_key, duplicates = {}, []
    for pos in side.get("positions") or []:
        key = str(pos.get("key") or "")
        if key in by_key:
            duplicates.append(key)
        by_key[key] = pos
    return by_key, duplicates


def _unknown_reason(pos: dict) -> str | None:
    if not str(pos.get("key") or "").strip():
        return "missing_key"
    if pos.get("line") not in POSITION_LINES:
        return "unknown_line"
    if not str(pos.get("asset_class") or "").strip():
        return "unclassified"
    if _int_or_none(pos.get("units_milli")) is None:
        return "missing_units"
    if _int_or_none(pos.get("price_minor")) is None or not str(pos.get("price_currency") or "").strip():
        return "missing_price"
    if _int_or_none(pos.get("market_value_base_minor")) is None:
        return "unvalued"
    return None


def _validate_explanation(exp: dict) -> str | None:
    exp_type, category = exp.get("type"), exp.get("category")
    if exp_type not in EXPLANATION_TYPES:
        return "unknown_type"
    if category not in EXPLANATION_TYPES[exp_type]:
        return "type_not_allowed_for_category"
    for field in ("explanation_id", "key", "source", "evidence_ref", "created_by"):
        if not str(exp.get(field) or "").strip():
            return f"missing_{field}"
    if not str(exp.get("approved_by") or "").strip() or not str(exp.get("approved_at") or "").strip():
        return "not_approved"
    if str(exp["approved_by"]).strip() == str(exp["created_by"]).strip():
        return "approver_equals_creator"
    if category in _AMOUNT_CATEGORIES and _int_or_none(exp.get("amount")) is None:
        return "missing_amount"
    return None


def reconcile_portfolio(
    depot: dict,
    advisory: dict,
    *,
    policy: PortfolioDataPolicy,
    explanations: list[dict] | None = None,
) -> dict:
    """Gleicht Depot und Beratungsvermoegen ab; Ergebnis mit ``status`` und ``result_hash``."""
    preconditions: list[str] = []
    if str(depot.get("base_currency") or "").upper() != str(advisory.get("base_currency") or "").upper() \
            or not str(depot.get("base_currency") or "").strip():
        preconditions.append("base_currency_mismatch")
    if str(depot.get("valuation_as_of") or "") != str(advisory.get("valuation_as_of") or "") \
            or not str(depot.get("valuation_as_of") or "").strip():
        preconditions.append("valuation_as_of_mismatch")
    if sorted(depot.get("perimeter_lines") or []) != sorted(advisory.get("perimeter_lines") or []):
        preconditions.append("perimeter_definition_changed")

    depot_pos, depot_dups = _positions_by_key(depot)
    adv_pos, adv_dups = _positions_by_key(advisory)
    for key in depot_dups + adv_dups:
        preconditions.append(f"duplicate_position:{key}")

    unknown: list[dict] = []
    for side_name, positions in (("depot", depot_pos), ("advisory", adv_pos)):
        for key, pos in sorted(positions.items()):
            reason = _unknown_reason(pos)
            if reason:
                unknown.append({"side": side_name, "key": key, "reason": reason})
    unknown_keys = {u["key"] for u in unknown}

    # Rohdifferenzen je Kategorie: {(category, key): {...}}
    findings: dict[tuple[str, str], dict] = {}

    for key in sorted(set(depot_pos) | set(adv_pos)):
        if key in unknown_keys:
            continue
        d, a = depot_pos.get(key), adv_pos.get(key)
        if d is None or a is None or d.get("line") != a.get("line"):
            findings[("perimeter", key)] = {
                "depot_line": d.get("line") if d else None,
                "advisory_line": a.get("line") if a else None,
                "line": (d or a).get("line"),
            }
            continue
        line = d["line"]
        if d["units_milli"] != a["units_milli"]:
            findings[("quantity", key)] = {"delta": d["units_milli"] - a["units_milli"], "line": line}
        if d["price_minor"] != a["price_minor"] or str(d["price_currency"]).upper() != str(a["price_currency"]).upper():
            findings[("price", key)] = {
                "depot": [d["price_minor"], d["price_currency"]],
                "advisory": [a["price_minor"], a["price_currency"]],
                "line": line,
            }
        mv_delta = d["market_value_base_minor"] - a["market_value_base_minor"]
        if mv_delta:
            findings[("market_value", key)] = {"delta": mv_delta, "line": line}

    depot_cash, adv_cash = depot.get("cash") or {}, advisory.get("cash") or {}
    for ccy in sorted(set(depot_cash) | set(adv_cash)):
        dv, av = _int_or_none(depot_cash.get(ccy, 0)), _int_or_none(adv_cash.get(ccy, 0))
        if dv is None or av is None:
            unknown.append({"side": "cash", "key": ccy, "reason": "invalid_cash_amount"})
            continue
        if dv != av:
            findings[("cash", ccy)] = {"delta": dv - av, "line": "cash"}

    depot_fx, adv_fx = depot.get("fx_rates") or {}, advisory.get("fx_rates") or {}
    for ccy in sorted(set(depot_fx) | set(adv_fx)):
        dv, av = _decimal_or_none(depot_fx.get(ccy)), _decimal_or_none(adv_fx.get(ccy))
        if dv is None or av is None or dv != av:
            findings[("fx", ccy)] = {"depot": depot_fx.get(ccy), "advisory": adv_fx.get(ccy), "line": None}

    # Erklaerungen: nur gueltige, freigegebene, auf bestehende Differenz bezogene.
    accepted: dict[tuple[str, str], list[dict]] = {}
    rejected: list[dict] = []
    for exp in explanations or []:
        reason = _validate_explanation(exp)
        target = (exp.get("category"), str(exp.get("key") or ""))
        if reason is None and target[1] in unknown_keys:
            reason = "unknown_position_not_overridable"
        if reason is None and target not in findings:
            reason = "no_matching_difference"
        if reason:
            rejected.append({"explanation_id": exp.get("explanation_id"), "reason": reason})
            continue
        accepted.setdefault(target, []).append(exp)

    per_position_tol = policy.per_position_tolerance_minor_units
    aggregate_tol = policy.aggregate_tolerance_major_units * MINOR_UNITS_PER_MAJOR
    differences: list[dict] = []
    line_residuals: dict[str, int] = {}
    for (category, key), finding in sorted(findings.items()):
        exps = accepted.get((category, key), [])
        entry = {
            "category": category,
            "key": key,
            "line": finding.get("line"),
            "explanation_ids": sorted(str(e["explanation_id"]) for e in exps),
        }
        if category in _AMOUNT_CATEGORIES:
            residual = finding["delta"] - sum(int(e["amount"]) for e in exps)
            entry.update(delta=finding["delta"], residual=residual)
            tolerance = per_position_tol if category == "market_value" else 0
            entry["explained"] = abs(residual) <= tolerance
            if category == "market_value":
                line_residuals[finding["line"]] = line_residuals.get(finding["line"], 0) + abs(residual)
        else:
            entry.update({k: v for k, v in finding.items() if k != "line"})
            entry["explained"] = bool(exps)
        differences.append(entry)

    aggregate = [
        {"line": line, "abs_residual": total, "tolerance": aggregate_tol, "within_tolerance": total <= aggregate_tol}
        for line, total in sorted(line_residuals.items())
    ]
    unexplained = [d for d in differences if not d["explained"]]
    aggregate_breach = [a for a in aggregate if not a["within_tolerance"]]

    if preconditions or unknown:
        status = STATUS_BLOCKED
    elif unexplained or aggregate_breach:
        status = STATUS_UNEXPLAINED
    else:
        status = STATUS_RECONCILED

    result = {
        "status": status,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "base_currency": str(depot.get("base_currency") or "").upper() or None,
        "valuation_as_of": depot.get("valuation_as_of"),
        "preconditions_failed": preconditions,
        "unknown_positions": unknown,
        "differences": differences,
        "unexplained_count": len(unexplained),
        "aggregate_by_line": aggregate,
        "rejected_explanations": rejected,
    }
    result["result_hash"] = _sha256(result)
    return result


_BINDING_FIELDS = ("snapshot_hash", "reconciliation_hash", "policy_version", "policy_hash", "advice_at")


def finalization_binding(
    *, snapshot_hash: str, reconciliation_hash: str, policy: PortfolioDataPolicy, advice_at: str,
) -> dict:
    """Bindung einer finalen Beratung/PDF an Snapshot, Abgleich, Policy und Zeitpunkt."""
    body = {
        "snapshot_hash": snapshot_hash,
        "reconciliation_hash": reconciliation_hash,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
        "advice_at": advice_at,
    }
    return {**body, "binding_digest": _sha256(body)}


def verify_finalization_binding(
    binding: dict, *, snapshot_hash: str, reconciliation_hash: str, policy: PortfolioDataPolicy,
) -> dict:
    """Prueft, ob seit der Finalisierung (z. B. PDF) eine relevante Aenderung erfolgte.

    Jede Abweichung invalidiert Digest und Finalisierungsstatus.
    """
    changed: list[str] = []
    body = {key: binding.get(key) for key in _BINDING_FIELDS}
    if binding.get("binding_digest") != _sha256(body):
        changed.append("binding_digest")
    current = {
        "snapshot_hash": snapshot_hash,
        "reconciliation_hash": reconciliation_hash,
        "policy_version": policy.version,
        "policy_hash": policy.policy_hash,
    }
    for key, value in current.items():
        if body.get(key) != value:
            changed.append(key)
    return {"valid": not changed, "changed": changed}
