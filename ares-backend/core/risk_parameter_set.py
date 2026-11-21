"""CCX P5 / M-2: ein kanonischer Risikoparametersatz (Vertrag 2026-11-13 §8.1).

Stdlib-Blatt (architecture ratchets, FAN_OUT_EXEMPT_LEAVES): keine Projekt-
Importe; DB, Konfiguration und Hausprior liefert der Aufrufer.

Kanonisch ist nach Dok. 113 (E-113-1, Nachtrag) und Codex-Vertrag §8.1 der
Risikokoeffizient je Anlageklasse = **IC-Subklassenwerte (BuildingBlock-
Risky-Fraction der Policy) x tatsaechliche Suballokation**. Bis P5 gab es
daneben zwei hart codierte Bucket-Saetze (Engine 7900/2450/5000/6000 bps,
Optimizer 0.80/0.25/0.60/0.60), die als stille Fallbacks griffen -- gemessen
an d1dc: ein nicht investierbarer Bucket (Obergrenze 0) zeigte 7900 bzw. 5000
bps im Payload, obwohl kein IC-Wert dahinter stand. Beide Saetze sind
entfernt; keiner wird kanonisch.

Regeln (eine Quelle fuer Solver-Constraint, Budgetpruefung, Persistenz,
Snapshot, API und PDF):

* Bucket mit Suballokationszeilen (inkl. der 0-Gewicht-Blaupause eines leeren,
  aber investierbaren Buckets im stochastischen Plan): gewichteter Mittelwert
  der Subklassen-Risky-Fractions mit dem Mischgewicht innerhalb des Buckets.
* Bucket ohne Zeile: nicht investierbar (Obergrenze 0) -- Koeffizient 0 mit
  ``basis = "not_investable"``. Er ist inert, weil das Gewicht 0 sein muss;
  traegt so ein Bucket Gewicht, endet die Rechnung mit
  ``CCX_PARAMETER_SET_MISSING`` statt mit einer Konstanten.
* Fehlt fuer eine verwendete Subklasse der IC-Wert, ebenfalls
  ``CCX_PARAMETER_SET_MISSING``.

IC-Freigabe: die Freigabe der Vorlagewerte ist Owner/IC (Dok. 113 E-113-7,
M-4) und hat heute keinen Datensatz. Der Satz traegt deshalb immer
``ic_release_status = "UNRELEASED"`` -- nie "freigegeben" behauptet. In
Produktion (``app_env == production``, dieselbe Linie wie das Verbot des
Runtime-Autoseedings) ist das fail-closed: keine Allokation, kein Siegel, kein
Kanal.

"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

PARAMETER_CONTRACT_VERSION = "ares-risk-parameter-set/1"
PARAMETER_HASH_DOMAIN = b"Ares\x00ares/risk-parameter-set/1\x00"
IC_RELEASE_UNRELEASED = "UNRELEASED"
BASIS_SUB_ALLOCATION = "sub_allocation"
BASIS_NOT_INVESTABLE = "not_investable"
BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")

_ASSET_CLASS_TO_BUCKET = {
    "aktien": "equities",
    "equities": "equities",
    "obligationen": "bonds",
    "bonds": "bonds",
    "immobilien": "real_estate",
    "real_estate": "real_estate",
    "alternative": "alternatives",
    "alternativen": "alternatives",
    "alternatives": "alternatives",
    "liquiditaet": "liquidity",
    "liquidität": "liquidity",
    "liquidity": "liquidity",
}


class ParameterSetMissing(ValueError):
    """``CCX_PARAMETER_SET_MISSING``: kein IC-Wert, wo einer gebraucht wird.

    ValueError-Unterklasse, damit die Engine-Fehlerpfade (OptimizerInputError
    usw.) ihn wie bisher als fachlichen Fehler behandeln; ``reason_code``
    erlaubt der API die typisierte Antwort."""

    reason_code = "CCX_PARAMETER_SET_MISSING"

    def __init__(self, message: str) -> None:
        super().__init__(message)


def bucket_of(asset_class: Any) -> str | None:
    return _ASSET_CLASS_TO_BUCKET.get(str(asset_class or "").strip().lower())


def _valid_bps(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000


def canonical_bucket_coefficients(
    sub_allocations: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, str]]:
    """Bucket-Koeffizienten (bps) und ihre Basis aus bereits angereicherten
    Suballokationszeilen (jede Zeile traegt ``risky_fraction_bps``)."""
    weighted = {bucket: 0 for bucket in BUCKETS}
    weights = {bucket: 0 for bucket in BUCKETS}
    for sub in sub_allocations or ():
        bucket = bucket_of(sub.get("asset_class"))
        if bucket is None:
            continue
        risky = sub.get("risky_fraction_bps")
        if not _valid_bps(risky):
            raise ParameterSetMissing(
                "Für die Unterklasse "
                f"«{sub.get('sub_asset_class')}» fehlt ein gültiger IC-Risikoanteil "
                "(0..10000 bps). Ohne freigegebenen Wert wird nicht gerechnet."
            )
        mix = sub.get("within_bucket_weight_bps")
        mix_weight = int(mix if mix is not None else (sub.get("target_weight_bps") or 0))
        weighted[bucket] += max(0, mix_weight) * int(risky)
        weights[bucket] += max(0, mix_weight)
    coefficients: dict[str, int] = {}
    basis: dict[str, str] = {}
    for bucket in BUCKETS:
        if weights[bucket] > 0:
            coefficients[bucket] = int(round(weighted[bucket] / weights[bucket]))
            basis[bucket] = BASIS_SUB_ALLOCATION
        else:
            # Ohne Zeile oder ohne Mischgewicht: nicht investierbar (inert);
            # Gewicht darauf sperrt ``assert_weights_investable``.
            coefficients[bucket] = 0
            basis[bucket] = BASIS_NOT_INVESTABLE
    return coefficients, basis


def assert_weights_investable(targets: Mapping[str, Any], basis: Mapping[str, str]) -> None:
    """Gewicht auf einem Bucket ohne IC-Subklasse ist nie zulaessig."""
    for bucket in BUCKETS:
        if basis.get(bucket) == BASIS_NOT_INVESTABLE and int(targets.get(bucket, 0) or 0) > 0:
            raise ParameterSetMissing(
                f"Die Anlageklasse «{bucket}» trägt Gewicht, hat aber keine Unterklasse mit "
                "IC-Risikoanteil. Ohne freigegebenen Wert wird nicht gerechnet."
            )


def risk_from_targets(targets: Mapping[str, Any], coefficients: Mapping[str, Any]) -> int:
    """sum_b w_b * rf_b in bps (einmal gerundet, wie bisher)."""
    return int(round(sum(
        int(targets.get(bucket, 0) or 0) * int(coefficients.get(bucket, 0) or 0) for bucket in BUCKETS
    ) / 10000))


def ic_bucket_means_bps(risky_map: Mapping[tuple[str, str], Any]) -> dict[str, int]:
    """Ungewichtetes Mittel der IC-Subklassenwerte je Bucket (nur fuer die
    Umverteilungs-Heuristik der House-Matrix-Kaskade; nie Anzeige/Budget).
    Fehlt fuer einen Bucket jeder IC-Wert -> ``CCX_PARAMETER_SET_MISSING``."""
    values: dict[str, list[int]] = {bucket: [] for bucket in BUCKETS}
    for (asset_class, _sub), risky in (risky_map or {}).items():
        bucket = bucket_of(asset_class)
        if bucket is not None and _valid_bps(risky):
            values[bucket].append(int(risky))
    missing = [bucket for bucket in BUCKETS if not values[bucket]]
    if missing:
        raise ParameterSetMissing(
            "Für folgende Anlageklassen fehlt jeder IC-Risikoanteil: " + ", ".join(missing) + "."
        )
    return {bucket: int(round(sum(values[bucket]) / len(values[bucket]))) for bucket in BUCKETS}


def _nfc(value: Any) -> Any:
    """Kanonische Form (Integer-only; Texte unveraendert, ASCII-escaped im Hash)."""
    if isinstance(value, Mapping):
        return {str(k): _nfc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nfc(v) for v in value]
    if isinstance(value, float):
        raise ParameterSetMissing("Der Risikoparametersatz enthält eine Fliesskommazahl.")
    return value


def parameter_set_hash(record: Mapping[str, Any]) -> str:
    """SHA-256, domaenensepariert, ueber die kanonischen Bytes (ohne Hashfeld)."""
    body = {key: value for key, value in record.items() if key != "parameter_set_hash"}
    canonical = json.dumps(_nfc(body), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(PARAMETER_HASH_DOMAIN + canonical.encode("utf-8")).hexdigest()


def ic_release_for(policy: Any) -> tuple[str, str | None]:
    """IC-Freigabe der Risikoparameter dieser Policy.

    Heute existiert kein Freigabedatensatz (M-4 ist Owner/IC); deshalb immer
    ``UNRELEASED``. Ein spaeterer Freigabe-Import ersetzt nur diese Funktion."""
    del policy
    return IC_RELEASE_UNRELEASED, None


def production_requires_release(app_env: Any) -> bool:
    return str(app_env or "").strip().lower() == "production"


def assert_release_allowed(record: Mapping[str, Any], *, app_env: Any) -> None:
    """Produktion: ohne IC-Freigabe fail-closed (``CCX_PARAMETER_SET_MISSING``).
    ``app_env`` liefert der Aufrufer (``config.settings.app_env``; dieses Modul
    ist ein Stdlib-Blatt ohne Projekt-Importe)."""
    if production_requires_release(app_env) and record.get("ic_release_status") != "RELEASED":
        raise ParameterSetMissing(
            "Die Risikoparameter (Risikoanteile je Unterklasse, Obergrenzen, Bänder) sind nicht "
            "vom Anlagekomitee freigegeben. In Produktion wird ohne Freigabe nicht gerechnet."
        )


def build_parameter_set(
    *,
    policy: Any,
    sub_allocations: Iterable[Mapping[str, Any]],
    bounds_bps: Mapping[str, Any],
    risk_budget_bps: int,
    house_matrix_profile: str | None,
    max_risky_fraction_bps: int | None,
    rounding_policy_version: str,
    house_prior: Mapping[str, Any],
) -> dict[str, Any]:
    """Kanonischer Parametersatz einer Allokation inklusive Hash.
    ``house_prior``: ``house_prior_from_model_basis(...)`` (Integer-Felder)."""
    rows = list(sub_allocations or ())
    coefficients, basis = canonical_bucket_coefficients(rows)
    status, release_ref = ic_release_for(policy)
    sub_rows = sorted(
        (
            {
                "asset_class": str(row.get("asset_class") or ""),
                "sub_asset_class": str(row.get("sub_asset_class") or ""),
                "risky_fraction_bps": int(row.get("risky_fraction_bps")),
                "within_bucket_weight_bps": int(
                    row.get("within_bucket_weight_bps")
                    if row.get("within_bucket_weight_bps") is not None
                    else (row.get("target_weight_bps") or 0)
                ),
                "target_weight_bps": int(row.get("target_weight_bps") or 0),
            }
            for row in rows
            if bucket_of(row.get("asset_class")) is not None
        ),
        key=lambda item: (BUCKETS.index(bucket_of(item["asset_class"])), item["sub_asset_class"]),
    )
    record: dict[str, Any] = {
        "contract_version": PARAMETER_CONTRACT_VERSION,
        "policy": {
            "policy_id": str(getattr(policy, "id", "") or ""),
            "policy_version": int(getattr(policy, "version", 0) or 0),
            "valid_from": str(getattr(policy, "valid_from", "") or ""),
        },
        "ic_release_status": status,
        "ic_release_ref": release_ref,
        "sub_asset_classes": sub_rows,
        "bucket_coefficients_bps": {bucket: int(coefficients[bucket]) for bucket in BUCKETS},
        "bucket_basis": {bucket: basis[bucket] for bucket in BUCKETS},
        "caps_bps": {
            "max_real_estate": int(getattr(policy, "max_real_estate_bps", 0) or 0),
            "max_alternatives": int(getattr(policy, "max_alternatives_bps", 0) or 0),
            "min_liquidity": int(getattr(policy, "min_liquidity_bps", 0) or 0),
        },
        "bands_bps": {
            bucket: [int(bounds_bps[bucket][0]), int(bounds_bps[bucket][1])] for bucket in BUCKETS
        },
        "house_matrix": {
            "profile": str(house_matrix_profile or ""),
            "max_risky_fraction_bps": None if max_risky_fraction_bps is None else int(max_risky_fraction_bps),
        },
        "risk_budget_bps": int(risk_budget_bps),
        "house_prior": {key: house_prior[key] for key in sorted(house_prior)},
        "rounding_policy_version": str(rounding_policy_version),
    }
    record["parameter_set_hash"] = parameter_set_hash(record)
    return record


def allocation_parameter_set(
    policy: Any, sub_allocations: Iterable[Mapping[str, Any]], minimums: Mapping[str, Any],
    maximums: Mapping[str, Any], risk_budget_bps: int, house_matrix: Any, asset_risky_weights: Mapping[str, Any],
    *, house_prior: Mapping[str, Any], app_env: Any, rounding_policy_version: str,
) -> dict[str, Any]:
    """Satz einer neu berechneten Allokation (Generate): derselbe Vektor wie
    Solver-Constraint und Budgetpruefung, sonst ``CCX_PARAMETER_SET_MISSING``;
    ohne IC-Freigabe in Produktion fail-closed."""
    record = build_parameter_set(
        policy=policy, sub_allocations=sub_allocations,
        bounds_bps={bucket: (int(minimums[bucket]), int(maximums[bucket])) for bucket in BUCKETS},
        risk_budget_bps=int(risk_budget_bps), house_matrix_profile=getattr(house_matrix, "profile_name", None),
        max_risky_fraction_bps=getattr(house_matrix, "max_risky_fraction_bps", None),
        rounding_policy_version=rounding_policy_version, house_prior=house_prior,
    )
    assert_release_allowed(record, app_env=app_env)
    if record["bucket_coefficients_bps"] != {b: int(asset_risky_weights[b]) for b in BUCKETS}:
        raise ParameterSetMissing("Risikoparametersatz und Allokationskoeffizienten weichen ab.")
    return record


def verify_parameter_set(record: Any, *, persisted_coefficients: Mapping[str, Any] | None = None) -> str:
    """Prueft einen gespeicherten Satz (Version, Hash, Kohaerenz mit den
    integritaetsgeprueften Bucket-Koeffizienten). Liefert den Hash oder wirft
    ``ParameterSetMissing``."""
    if not isinstance(record, Mapping) or record.get("contract_version") != PARAMETER_CONTRACT_VERSION:
        raise ParameterSetMissing(
            "Zu dieser Soll-Allokation ist kein Risikoparametersatz gespeichert. Bitte neu berechnen."
        )
    stored = record.get("parameter_set_hash")
    if not isinstance(stored, str) or parameter_set_hash(record) != stored:
        raise ParameterSetMissing("Der gespeicherte Risikoparametersatz ist nicht integer.")
    if persisted_coefficients is not None:
        coefficients = record.get("bucket_coefficients_bps") or {}
        if any(int(coefficients.get(b, -1)) != int(persisted_coefficients.get(b, -2) or 0) for b in BUCKETS):
            raise ParameterSetMissing(
                "Der Risikoparametersatz widerspricht den gespeicherten Risikoanteilen der Allokation."
            )
    return stored


def house_prior_from_model_basis(optimization_basis: Any) -> dict[str, Any]:
    """Hausprior-Version und kappa (x100, Integer) aus der gespeicherten
    Optimierer-Modellbasis (``objective_contract``); ohne Optimierer (manuelle
    Allokation, House-Matrix) ausdruecklich ``not_applicable``."""
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in ("house_prior_policy", "house_prior_kappa") and key not in found:
                    found[key] = value
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(optimization_basis)
    if "house_prior_policy" not in found:
        return {"version": "not_applicable", "kappa_x100": None}
    kappa = found.get("house_prior_kappa")
    return {
        "version": str(found["house_prior_policy"]),
        "kappa_x100": None if kappa is None else int(round(float(kappa) * 100)),
    }


def stored_risk_parameter_set(allocation: Any) -> dict[str, Any] | None:
    """Der bei der Berechnung gespeicherte Satz einer Soll-Allokation (oder
    ``None`` bei Bestand vor P5). Nur lesen, nie neu ableiten."""
    try:
        constraints = json.loads(getattr(allocation, "effective_constraints_json", None) or "{}")
    except (TypeError, ValueError):
        return None
    record = constraints.get("risk_parameter_set") if isinstance(constraints, dict) else None
    return dict(record) if isinstance(record, Mapping) else None


__all__ = [
    "allocation_parameter_set",
    "BASIS_NOT_INVESTABLE",
    "BASIS_SUB_ALLOCATION",
    "BUCKETS",
    "IC_RELEASE_UNRELEASED",
    "PARAMETER_CONTRACT_VERSION",
    "ParameterSetMissing",
    "assert_release_allowed",
    "assert_weights_investable",
    "bucket_of",
    "build_parameter_set",
    "canonical_bucket_coefficients",
    "house_prior_from_model_basis",
    "ic_bucket_means_bps",
    "ic_release_for",
    "parameter_set_hash",
    "production_requires_release",
    "risk_from_targets",
    "stored_risk_parameter_set",
    "verify_parameter_set",
]
