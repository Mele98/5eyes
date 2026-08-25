"""ADR-014, Schritt 3: CMA-Verarbeitung (Capital Market Assumptions),
extrahiert aus `services/portfolio_engine.py` (God-Modul-Split, Welle 3.2).

Reine Datei-Grenz-Verschiebung, 0 Zeilen Fachlogik-Aenderung: die Funktionen
unten sind Byte-fuer-Byte-Kopien ihrer vormaligen Definitionen in
`portfolio_engine.py` (Zeilen 1563-2270 und 2686-2695 zum Zeitpunkt der
Extraktion, siehe ADR-014). `portfolio_engine.py` re-exportiert sie
weiterhin unter denselben Namen (Rueckwaerts-Kompatibilitaet fuer
`services/backtest_ab.py`, `services/advisory_report.py`, `routers/clients.py`,
`routers/wealth.py`, `services/optimizer/scenario_engine.py` und alle
bestehenden Tests, die z.B. `from services.portfolio_engine import
_expected_metrics` o.ae. nutzen).

Cluster-Abhaengigkeit (laut ADR-014): reine Ein-Richtungs-Abhaengigkeit --
MC-Simulation und House-Matrix/Tilt lesen von hier, CMA-Verarbeitung liest
von nichts anderem (nur BUCKET_FIELDS/settings/Modelle + ein paar Modul-
Konstanten, die physisch in `portfolio_engine.py` stehen).

Zirkular-Import-Haertung (identisches Muster zu
`services/portfolio_engine_gesamtvermoegen.py`, Schritt 1): Funktionen, die
Konstanten/Helfer aus `services.portfolio_engine` selbst brauchen
(`BUCKET_FIELDS`, `logger`, `_DEFAULT_CORRELATION_MATRIX`,
`_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS`, `_ASSET_CLASS_LABEL_TO_BUCKET`)
importieren diese function-local (lazy), NICHT auf Modul-Ebene -- ein
Modul-Top-Level-Import waere nur sicher, wenn `portfolio_engine.py` IMMER
der Einstiegspunkt der Import-Kette ist, was nicht garantiert ist (ein
direkter `import services.portfolio_engine_cma` als allererster Import
wuerde sonst mit ImportError auf einem partiell initialisierten Modul
scheitern). Modelle/externe Services (`CapitalMarketAssumption`, `Session`,
`resolve_home_bias_defaults`, `DE_DEFAULT_EQUITIES_GEO`, `settings`) sind
dagegen ganz normale Modul-Top-Level-Importe -- sie haengen nicht von
`services.portfolio_engine` ab, also kein Zyklus moeglich.

`_apply_cma_market_adjustments()` behaelt ihren bereits im Original
vorhandenen LAZY Import aus `services.optimizer.scenario_engine` unveraendert
(kein Modul-Top-Level-Import -- das war schon im Original so, siehe
Sprint U-P2 Fix C6). `_expected_metrics()` behaelt ebenso ihren bereits
vorhandenen lazy Import aus `services.risk_metrics_kpi` unveraendert.

Strict-CMA-Haertung (2026-08-11): Leere optionale JSON-Felder behalten ihre
historischen Defaults. Sobald ein Korrelations-/Sub-CMA-Payload vorhanden
ist, wird es als verbindlicher Modelleingang strikt validiert und bei
Fehlern nie durch Swiss Defaults/Identity ersetzt. Erwartete Renditen bleiben
vorzeichenbehaftet; negative Netto-Erwartungen werden nicht auf 0 bps geklemmt.
"""
from __future__ import annotations

import json
import math
from numbers import Integral

from sqlalchemy.orm import Session

from config import settings
from models.allocation import CapitalMarketAssumption
from services.cma_validation import (
    correlation_factor,
    parse_correlation_matrix_json,
    parse_sub_asset_class_assumptions_json,
    validate_correlation_matrix,
    validate_runtime_cma_completeness,
)
from services.jurisdiction.de_seed import DE_DEFAULT_EQUITIES_GEO
from services.jurisdiction.resolve import resolve_home_bias_defaults


def _bare_market_token(label: str) -> str:
    """Entfernt ein bekanntes Asset-Class-Praefix von einem Home-Bias-Label.

    "Aktien Deutschland" -> "Deutschland". Label ohne bekanntes Praefix
    werden unveraendert zurueckgegeben (defensiv, kein Crash bei
    unerwarteten Label-Formen)."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _SUB_ASSET_CLASS_LABEL_PREFIXES

    for prefix in _SUB_ASSET_CLASS_LABEL_PREFIXES:
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


def _resolve_home_equity_label(db: Session, jurisdiction: str) -> str:
    """Staerkstes (hoechstgewichtetes) Label aus den equitiesGeo-Home-Bias-
    DEFAULT-Splits einer Nicht-CH-Jurisdiktion (z.B. "Aktien Deutschland").

    Pragmatische, dokumentierte Wahl (die Aufgabenstellung raeumt hier
    explizit Wahlfreiheit ein): der equitiesGeo-DEFAULT ("<Land> Fokus")
    enthaelt naturgemaess den Heimmarkt mit dem hoechsten split_bps-Gewicht
    -- unabhaengig davon, welche equitiesGeo-Praeferenz das Mandat tatsaechlich
    gewaehlt hat. Wird u.a. fuer den Small/Mid-Cap-Satelliten in
    _build_sub_allocations() benoetigt (Ersatz fuer das CH-hartcodierte
    "Aktien Schweiz").

    NUR fuer jurisdiction NICHT in (None, "CH") aufrufen -- ruft
    resolve_home_bias_defaults() auf, die fuer CH einen ValueError wirft.
    """
    splits = resolve_home_bias_defaults(db, jurisdiction, "equitiesGeo", DE_DEFAULT_EQUITIES_GEO)
    return max(splits, key=lambda item: item[1])[0]


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    """Lower-triangular Cholesky decomposition of a positive-definite matrix.
    Returns L such that L @ L^T == matrix."""
    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                L[i][j] = math.sqrt(max(0.0, matrix[i][i] - s))
            else:
                L[i][j] = (matrix[i][j] - s) / L[j][j] if L[j][j] > 1e-12 else 0.0
    return L


def _is_valid_cholesky(L: list[list[float]]) -> bool:
    """Return True if all diagonal entries of L are above numerical threshold.
    A zero diagonal means the input matrix was not positive-definite and the
    decomposition silently zeroed that row/column, producing wrong correlations."""
    return all(L[i][i] > 1e-10 for i in range(len(L)))


def _identity_cholesky(n: int) -> list[list[float]]:
    """Return identity matrix of size n (= uncorrelated assets)."""
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _cornish_fisher_transform(z: float, skew: float, excess_kurt: float) -> float:
    """Sprint U-P4 Fix M6: Cornish-Fisher-Expansion bis 4. Ordnung.

    Transformiert eine Standard-Normal-Sample z in eine Sample mit
    gegebener Skewness und Excess-Kurtosis. Bei skew=0 + excess_kurt=0
    bleibt z unverändert (Backwards-Compat).

    Formula: z' = z + (z²-1)*S/6 + (z³-3z)*K/24 - (2z³-5z)*S²/36

    2026-07-24 (Audit, portfoliotheoretische Formel-Ueberpruefung): skew/
    excess_kurt werden hier NICHT validiert, bevor sie in die Formel
    einfliessen. Die CF-Expansion ist bei extremen Skew/Kurt-Kombinationen
    bekanntermassen nicht-monoton (liefert keine gueltige Quantilfunktion
    mehr) -- ein Dateneingabefehler in der CMA-Admin-UI (z.B. ein Tippfehler
    um eine Grössenordnung) wuerde das unbemerkt durchreichen. Clamp auf
    einen Bereich, der jeden real beobachteten/plausiblen Markt-Skew/-Kurt
    weit uebersteigt (typische Aktien-Skew ~ -1..0, Exzess-Kurtosis ~ 1..10),
    aber grobe Fat-Finger-Fehler abfaengt.
    """
    skew = max(-3.0, min(3.0, skew))
    excess_kurt = max(-2.0, min(30.0, excess_kurt))
    if skew == 0.0 and excess_kurt == 0.0:
        return z
    z2 = z * z
    z3 = z2 * z
    return (
        z
        + (z2 - 1.0) * skew / 6.0
        + (z3 - 3.0 * z) * excess_kurt / 24.0
        - (2.0 * z3 - 5.0 * z) * skew * skew / 36.0
    )


def _crisis_stress_matrix(base_matrix: list[list[float]], crisis_strength: float = 1.0) -> list[list[float]]:
    """Sprint U-P4 Fix M5: Crisis-Korrelations-Matrix.

    In Tail-Stress-Szenarien (2008, 2020) konvergieren ALLE Risky-Asset-
    Korrelationen gegen +0.9 — Diversifikation bricht zusammen. Liquidity
    bleibt unkorreliert (Geldmarkt ist Safe-Haven).

    crisis_strength=0.0 → base_matrix, 1.0 → vollständiger Crisis-Mode.
    BUCKET_FIELDS-Reihenfolge: equities, bonds, real_estate, alternatives, liquidity.
    Index 4 = liquidity bleibt diagonal.
    """
    s = max(0.0, min(1.0, float(crisis_strength)))
    if s <= 0:
        return [list(row) for row in base_matrix]
    n = len(base_matrix)
    crisis_target = 0.9
    out = [list(row) for row in base_matrix]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # Liquidity bleibt unkorreliert (Safe-Haven)
            if i == 4 or j == 4:
                continue
            out[i][j] = (1 - s) * base_matrix[i][j] + s * crisis_target
    return out


def _build_cholesky_from_cma(
    cma: CapitalMarketAssumption,
    crisis_strength: float = 0.0,
) -> list[list[float]]:
    """Return a correlation factor for the five asset classes.

    An absent payload uses the canonical Swiss-market default.  A present
    invalid payload is a CMA domain error and is never replaced by Swiss
    defaults or identity.  Valid singular (PSD) matrices retain their
    intended dependence through an eigen-factor.

    Sprint U-P4 Fix M5: optional crisis_strength in [0,1] biased Korrelationen
    Richtung +0.9 (alle Risky-Assets, Liquidity bleibt unkorreliert).
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _DEFAULT_CORRELATION_MATRIX

    matrix = parse_correlation_matrix_json(
        getattr(cma, "correlation_matrix_json", None),
        default_matrix=_DEFAULT_CORRELATION_MATRIX,
    )
    assert matrix is not None  # default_matrix guarantees a matrix

    if crisis_strength > 0:
        matrix = validate_correlation_matrix(
            _crisis_stress_matrix([list(row) for row in matrix], crisis_strength)
        )

    return correlation_factor(matrix).tolist()


def _sub_asset_class_assumption_map(cma: CapitalMarketAssumption) -> dict[str, dict[str, int | str]]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS

    return parse_sub_asset_class_assumptions_json(
        getattr(cma, "sub_asset_class_assumptions_json", None),
        defaults=_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS,
        require_complete=True,
    )


def _sub_asset_class_metrics(
    sub_asset_class: str,
    asset_class: str,
    cma: CapitalMarketAssumption,
    fallback_returns: dict[str, int],
    fallback_vols: dict[str, int],
) -> tuple[int, int]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _ASSET_CLASS_LABEL_TO_BUCKET

    assumptions = _sub_asset_class_assumption_map(cma)
    item = assumptions.get(str(sub_asset_class))
    bucket = _ASSET_CLASS_LABEL_TO_BUCKET.get(str(asset_class), "liquidity")
    if item:
        return int(item["expected_return_bps"]), int(item["expected_volatility_bps"])
    return int(fallback_returns[bucket]), int(fallback_vols[bucket])


def _apply_cma_market_adjustments(returns: dict[str, int], cma: CapitalMarketAssumption) -> dict[str, int]:
    """Sprint U-P2 Fix C6: NS/KGV/Risikoprämien-Adjustments aus scenario_engine
    auch im Haupt-MC-Pfad anwenden.

    Vorher: NS (Sprint 6), KGV-Mean-Reversion (Sprint 7) und Risikoprämien
    (Sprint 8) wirkten NUR im Optimizer-Solver (services/optimizer/scenario_engine).
    Der Haupt-MC, PDF und Allokations-Ansicht ignorierten diese Felder
    komplett — Berater sah zwei divergierende Wahrheiten je nach OPTIMIZER_MODE.

    Backwards-Compat: jede Adjustment-Funktion gibt None/0.0 zurück wenn die
    nötigen CMA-Felder fehlen → in dem Fall bleiben Returns unverändert.
    """
    try:
        from services.optimizer.scenario_engine import (
            _compute_bonds_return_from_nelson_siegel,
            _compute_equity_kgv_adjustment,
            _compute_return_from_risk_premium,
        )
    except ImportError:
        return returns

    adjusted = dict(returns)

    # Bonds: Nelson-Siegel Yield-Curve (5J-Maturity-Default) ersetzt fixen Wert
    ns_bonds = _compute_bonds_return_from_nelson_siegel(cma)
    if ns_bonds is not None:
        adjusted["bonds"] = int(round(ns_bonds))

    # Equity: KGV-Mean-Reversion-Adjustment additiv (10J-Horizont-Default)
    kgv_adj = _compute_equity_kgv_adjustment(cma)
    if kgv_adj:
        adjusted["equities"] = int(round(adjusted["equities"] + kgv_adj))

    # Real Estate + Alternatives: NS-short-rate + Risikoprämie (nur wenn NS aktiv)
    re_from_premium = _compute_return_from_risk_premium(cma, "real_estate_risk_premium_bps")
    if re_from_premium is not None:
        adjusted["real_estate"] = int(round(re_from_premium))
    alt_from_premium = _compute_return_from_risk_premium(cma, "alternatives_risk_premium_bps")
    if alt_from_premium is not None:
        adjusted["alternatives"] = int(round(alt_from_premium))

    return adjusted


def _cma_value_or_default(value, default: int) -> int:
    """Preserve an explicit 0 bps CMA; only NULL means 'use fallback'."""
    return int(default if value is None else value)


def _asset_class_expected_metrics(
    cma: CapitalMarketAssumption,
    *,
    apply_market_adjustments: bool = True,
) -> tuple[dict[str, int], dict[str, int]]:
    """Reine CMA-Bucket-Defaults. KEIN Mischen mit Sub-Asset-Class-Annahmen.

    C3: Vor dem Fix wurden die Bucket-Returns mit dem ungewichteten Mittel
    aller Sub-Asset-Class-Annahmen ueberschrieben. Damit fuehrte das blosse
    Vorhandensein einer EM-Annahme im CMA-JSON dazu, dass die Equity-Rendite
    insgesamt nach oben gezogen wurde - selbst wenn die tatsaechliche
    Sub-Allocation 0% EM enthielt. Diese Funktion liefert nun nur die
    CMA-Bucket-Felder; tatsaechliche Bucket-Metriken aus Sub-Allocation
    werden ueber _weighted_bucket_metrics() berechnet.

    Sprint U-P2 Fix C6: zusaetzlich werden NS/KGV/RP-Adjustments angewendet
    (vorher nur im Optimizer-Solver aktiv).

    WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): fuer cma.jurisdiction NICHT
    in (None, "CH") werden statt der equity_ch_*/bonds_chf_ig_*/real_estate_ch_*-
    Spalten die generischen equity_home_*/bonds_home_ig_*/real_estate_home_*-
    Spalten DERSELBEN CMA-Zeile gelesen (additive Spalten aus WP1, siehe
    models/allocation.py). Die Jurisdiktion wird bewusst aus cma.jurisdiction
    abgeleitet statt als eigener Parameter durchgereicht -- die beiden
    Aufrufer (siehe unten) haben ohnehin nur `cma` im Scope, und cma.jurisdiction
    ist nach WP1 die Quelle der Wahrheit fuer "zu welcher Jurisdiktion gehoert
    diese CMA-Zeile". alternatives_*/liquidity_* bleiben jurisdiktionsunabhaengige,
    generische Marktannahmen (kein Home-*-Gegenstueck im Schema) -- unveraendert.
    Fehlende equity_home_*/bonds_home_ig_*/real_estate_home_*-Werte (z.B. eine
    "provisional"-CMA-Zeile ohne PE-Proxy) fallen auf dieselben generischen
    Sentinel-Defaults zurueck wie der CH-Zweig (500/180/350/1200/350/700 bps) --
    das sind KEINE fuer eine neue Jurisdiktion erfundenen Zahlen, sondern die
    bereits bestehenden, jurisdiktionsunabhaengigen Engine-Sicherheitsnetz-Werte.
    """
    validate_runtime_cma_completeness(cma)
    if getattr(cma, "jurisdiction", None) in (None, "CH"):
        returns = {
            "equities": int(round((
                _cma_value_or_default(cma.equity_ch_return_bps, 500)
                + _cma_value_or_default(cma.equity_intl_return_bps, 650)
            ) / 2)),
            "bonds": int(round((
                _cma_value_or_default(cma.bonds_chf_ig_return_bps, 180)
                + _cma_value_or_default(cma.bonds_fx_hedged_return_bps, 220)
            ) / 2)),
            "real_estate": _cma_value_or_default(
                cma.real_estate_ch_return_bps,
                350,
            ),
            "alternatives": _cma_value_or_default(
                cma.alternatives_gold_return_bps,
                120,
            ),
            "liquidity": _cma_value_or_default(cma.liquidity_return_bps, 80),
        }
        if apply_market_adjustments:
            returns = _apply_cma_market_adjustments(returns, cma)
        vols = {
            "equities": int(round((
                _cma_value_or_default(cma.equity_ch_vol_bps, 1200)
                + _cma_value_or_default(cma.equity_intl_vol_bps, 1450)
            ) / 2)),
            "bonds": int(round((
                _cma_value_or_default(cma.bonds_chf_ig_vol_bps, 350)
                + _cma_value_or_default(cma.bonds_fx_hedged_vol_bps, 450)
            ) / 2)),
            "real_estate": _cma_value_or_default(cma.real_estate_ch_vol_bps, 700),
            "alternatives": _cma_value_or_default(
                cma.alternatives_gold_vol_bps,
                950,
            ),
            "liquidity": _cma_value_or_default(cma.liquidity_vol_bps, 20),
        }
        return returns, vols

    returns = {
        "equities": int(cma.equity_home_return_bps if cma.equity_home_return_bps is not None else 500),
        "bonds": int(cma.bonds_home_ig_return_bps if cma.bonds_home_ig_return_bps is not None else 180),
        "real_estate": int(cma.real_estate_home_return_bps if cma.real_estate_home_return_bps is not None else 350),
        "alternatives": _cma_value_or_default(
            cma.alternatives_gold_return_bps,
            120,
        ),
        "liquidity": _cma_value_or_default(cma.liquidity_return_bps, 80),
    }
    if apply_market_adjustments:
        returns = _apply_cma_market_adjustments(returns, cma)
    vols = {
        "equities": int(cma.equity_home_vol_bps if cma.equity_home_vol_bps is not None else 1200),
        "bonds": int(cma.bonds_home_ig_vol_bps if cma.bonds_home_ig_vol_bps is not None else 350),
        "real_estate": int(cma.real_estate_home_vol_bps if cma.real_estate_home_vol_bps is not None else 700),
        "alternatives": _cma_value_or_default(cma.alternatives_gold_vol_bps, 950),
        "liquidity": _cma_value_or_default(cma.liquidity_vol_bps, 20),
    }
    return returns, vols


def _weighted_bucket_metrics(
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None,
    *,
    strict: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    """Bucket-Return/Vol gewichtet aus tatsaechlichen Sub-Allocations.

    C3: Pro Bucket wird der gewichtete Mittelwert aus Sub-Asset-Class-
    target_weight_bps und Sub-Asset-Class-CMA-Annahmen gebildet.
    Ohne Sub-Allocations oder fuer einen Bucket ohne Sub-Eintrag wird
    auf die CMA-Bucket-Defaults aus _asset_class_expected_metrics()
    zurueckgegriffen.

    Sprint U-P8 Fix M1: wenn settings.sub_class_intra_correlation < 1.0
    aktiviert ist, wird die Bucket-Vola nicht mehr als gewichteter Skalar,
    sondern als √(w' Σ w) mit Sub-Class-Diversifikation berechnet (Block-
    Diagonal: innerhalb Bucket ρ, zwischen Buckets wie zuvor 5×5).
    """
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import _ASSET_CLASS_LABEL_TO_BUCKET

    # Start from raw bucket assumptions. Market adjustments are applied once,
    # after any sub-asset weighting, so Solver, expected metrics and reporting
    # cannot double-apply (or omit) KGV/NS/risk-premium adjustments.
    fallback_returns, fallback_vols = _asset_class_expected_metrics(
        cma,
        apply_market_adjustments=False,
    )
    # Parse before the no-sleeve return: a present malformed Sub-CMA payload
    # is corrupted model input even when this call only needs bucket totals.
    assumptions = _sub_asset_class_assumption_map(cma)
    if not sub_allocations:
        return _apply_cma_market_adjustments(fallback_returns, cma), fallback_vols
    weighted_ret_bps: dict[str, int] = {key: 0 for key in fallback_returns}
    weighted_vol_bps: dict[str, int] = {key: 0 for key in fallback_vols}
    weight_sum: dict[str, int] = {key: 0 for key in fallback_returns}
    # Sprint U-P8 Fix M1: pro Bucket die Sub-Vola-Liste sammeln fuer
    # echte Block-Diagonal-Berechnung
    bucket_sub_vols: dict[str, list[tuple[int, int]]] = {key: [] for key in fallback_vols}

    for index, item in enumerate(sub_allocations):
        if not isinstance(item, dict):
            if strict:
                raise ValueError(
                    f"sub_allocations[{index}] must be an object"
                )
            continue
        asset_class_label = str(item.get("asset_class") or "")
        sub_label = str(item.get("sub_asset_class") or "")
        # Stochastic materialisation keeps the exact within-bucket blueprint
        # alongside integer portfolio bps. Use that blueprint for CMA metrics
        # so rounding a bucket to tradable bps cannot change the assumptions
        # on which it was optimized.
        metric_weight = (
            item.get("within_bucket_weight_bps")
            if item.get("within_bucket_weight_bps") is not None
            else item.get("target_weight_bps")
        )
        bucket = _ASSET_CLASS_LABEL_TO_BUCKET.get(asset_class_label)
        if strict and not bucket:
            raise ValueError(
                f"sub_allocations[{index}] has unknown asset_class "
                f"{asset_class_label!r}"
            )
        if strict and not sub_label:
            raise ValueError(
                f"sub_allocations[{index}] is missing sub_asset_class"
            )
        if strict and metric_weight is None:
            raise ValueError(
                f"sub_allocations[{index}] is missing a metric weight"
            )
        try:
            weight = int(metric_weight or 0)
        except (TypeError, ValueError) as exc:
            if strict:
                raise ValueError(
                    f"sub_allocations[{index}] has an invalid metric weight"
                ) from exc
            continue
        if strict and (
            isinstance(metric_weight, bool)
            or not isinstance(metric_weight, Integral)
            or weight <= 0
        ):
            raise ValueError(
                f"sub_allocations[{index}] metric weight must be a positive "
                "integer number of basis points"
            )
        if not bucket or weight <= 0:
            continue
        sub = assumptions.get(sub_label)
        if sub:
            assumption_asset_class = str(sub.get("asset_class") or "")
            if strict and assumption_asset_class != asset_class_label:
                raise ValueError(
                    f"sub_allocations[{index}] assigns {sub_label!r} to "
                    f"{asset_class_label!r}, but its CMA asset class is "
                    f"{assumption_asset_class!r}"
                )
            ret_bps = int(sub.get("expected_return_bps") or 0)
            vol_bps = int(sub.get("expected_volatility_bps") or 0)
        else:
            if strict:
                raise ValueError(
                    f"sub_allocations[{index}] has no CMA assumption for "
                    f"{sub_label!r}"
                )
            ret_bps = fallback_returns[bucket]
            vol_bps = fallback_vols[bucket]
        weighted_ret_bps[bucket] += ret_bps * weight
        weighted_vol_bps[bucket] += vol_bps * weight
        weight_sum[bucket] += weight
        bucket_sub_vols[bucket].append((weight, vol_bps))

    # Sprint U-P8 Fix M1: opt-in Block-Diagonal-Vola
    intra_rho = float(getattr(settings, "sub_class_intra_correlation", 1.0))
    use_intra_diversification = intra_rho < 1.0

    returns = dict(fallback_returns)
    vols = dict(fallback_vols)
    for bucket in fallback_returns:
        ws = weight_sum[bucket]
        if ws <= 0:
            continue
        returns[bucket] = int(round(weighted_ret_bps[bucket] / ws))
        if use_intra_diversification and len(bucket_sub_vols[bucket]) > 1:
            # σ_bucket² = Σ w_i² σ_i² + 2 Σ_{i<j} w_i w_j ρ σ_i σ_j
            subs = bucket_sub_vols[bucket]
            variance = 0.0
            for i, (w_i, sigma_i) in enumerate(subs):
                wf_i = w_i / ws
                variance += wf_i * wf_i * sigma_i * sigma_i
                for j in range(i + 1, len(subs)):
                    w_j, sigma_j = subs[j]
                    wf_j = w_j / ws
                    variance += 2 * wf_i * wf_j * intra_rho * sigma_i * sigma_j
            vols[bucket] = int(round(math.sqrt(max(0.0, variance))))
        else:
            vols[bucket] = int(round(weighted_vol_bps[bucket] / ws))
    return _apply_cma_market_adjustments(returns, cma), vols


def _validate_sub_cma_universe(
    cma: CapitalMarketAssumption,
    allowed_sub_asset_classes: set[str],
) -> None:
    """Reject configured assumptions that no active model sleeve can consume.

    Jurisdiction-specific labels are valid, but a fully shaped typo must not
    be persisted and then silently ignored while the real sleeve uses a bucket
    default. Runtime callers derive ``allowed_sub_asset_classes`` from the
    active BuildingBlock/sub-allocation universe.
    """
    # Parse/validate first, then inspect only explicitly configured labels.
    # The materialised map also contains inherited canonical defaults, which
    # need not all be active in every jurisdiction/universe.
    _sub_asset_class_assumption_map(cma)
    raw_payload = getattr(cma, "sub_asset_class_assumptions_json", None)
    if raw_payload is None or raw_payload == "":
        return
    configured = json.loads(raw_payload)
    allowed = {str(label).strip() for label in allowed_sub_asset_classes if str(label).strip()}
    unknown = sorted(str(label).strip() for label in configured if str(label).strip() not in allowed)
    if unknown:
        raise ValueError(
            "Sub-CMA assumptions are not referenced by the active model "
            f"universe: {unknown}."
        )


def _bucket_expected_metrics(
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Backward-compatible name used by regression tests and older callers."""
    return _weighted_bucket_metrics(cma, sub_allocations)


def _portfolio_volatility_bps(
    targets: dict[str, int],
    bucket_vols_bps: dict[str, int],
    cma: CapitalMarketAssumption,
) -> int:
    """Berechnet Portfolio-Volatilitaet via w' Sigma w statt linearer Vol-Summe."""
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS

    cholesky = _build_cholesky_from_cma(cma)
    exposures = [
        (int(targets.get(key, 0) or 0) / 10000.0) * (int(bucket_vols_bps.get(key, 0) or 0) / 10000.0)
        for key in BUCKET_FIELDS
    ]
    variance = 0.0
    for col in range(len(BUCKET_FIELDS)):
        factor_loading = 0.0
        for row in range(len(BUCKET_FIELDS)):
            factor_loading += exposures[row] * float(cholesky[row][col])
        variance += factor_loading * factor_loading
    return int(round(math.sqrt(max(0.0, variance)) * 10000))


def _portfolio_weighted_ter_bps(
    sub_allocations: list[dict] | None,
    products: list[dict] | None = None,
) -> int:
    """Sprint U-P2 Fix M2: gewichtete TER aus Produktselektion. Wird vom
    expected_return abgezogen damit der Berater den Netto-Wert sieht.

    Backwards-Compat: ohne products und ohne sub_allocations gibt 0 zurueck
    (frueheres Verhalten = Brutto-Return). Erst sobald RecommendationRun
    konkrete Produkte mit ter_bps-Feldern liefert, kommt das echte TER-Drag.
    """
    if products:
        total_weight = 0
        weighted_ter = 0
        for prod in products:
            weight = max(0, int((prod or {}).get("target_weight_bps", 0) or 0))
            ter = max(0, int((prod or {}).get("ter_bps", 0) or 0))
            if weight > 0:
                weighted_ter += weight * ter
                total_weight += weight
        if total_weight > 0:
            return int(round(weighted_ter / total_weight))
    return 0


def _expected_metrics(
    targets: dict[str, int],
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
    products: list[dict] | None = None,
) -> dict[str, int]:
    # Lazy Import (Zirkular-Import-Haertung, siehe Modul-Docstring).
    from services.portfolio_engine import BUCKET_FIELDS

    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    gross_return_bps = int(round(sum(targets[key] * returns[key] for key in BUCKET_FIELDS) / 10000))
    vol_bps = _portfolio_volatility_bps(targets, vols, cma)
    # Sprint U-P2 Fix M2: Net-of-fees Return
    weighted_ter_bps = _portfolio_weighted_ter_bps(sub_allocations, products)
    # Expected return is signed model output. A loss expectation must not be
    # relabelled as 0%, including after TER drag.
    net_return_bps = gross_return_bps - weighted_ter_bps
    # Sprint U-P2 Fix L2: Sharpe-Ratio = (Netto-Return − Risk-Free) / Vola
    risk_free_bps = _cma_value_or_default(
        getattr(cma, "liquidity_return_bps", None),
        80,
    )
    sharpe_x100 = 0
    if vol_bps > 0:
        sharpe_x100 = int(round(((net_return_bps - risk_free_bps) / vol_bps) * 100))
    # Sprint U-96 (2026-06-05): Erweiterte Risikokennzahlen
    # (Sortino/Calmar/Information-Ratio) — Pure-Math-Helper, Annahmen
    # dokumentiert in services/risk_metrics_kpi.py.
    from services.risk_metrics_kpi import compute_extended_risk_metrics
    extended = compute_extended_risk_metrics(
        return_bps=net_return_bps,
        vol_bps=vol_bps,
        risk_free_bps=risk_free_bps,
    )
    return {
        "expected_return_bps": net_return_bps,
        "expected_return_gross_bps": gross_return_bps,
        "expected_ter_bps": weighted_ter_bps,
        "expected_volatility_bps": vol_bps,
        "sharpe_ratio_x100": sharpe_x100,
        "risk_free_bps": risk_free_bps,
        **extended,
    }


def _inflation_path_series(cma: CapitalMarketAssumption, years: int, start_year: int) -> list[int]:
    try:
        raw_path = json.loads(cma.inflation_path_json or "{}")
    except json.JSONDecodeError:
        raw_path = {}
    normalized: dict[int, int] = {}
    for raw_year, raw_value in (raw_path or {}).items():
        try:
            year = int(str(raw_year).strip())
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        normalized[year] = value
    fallback = normalized[max(normalized)] if normalized else 70
    series: list[int] = []
    for offset in range(max(0, years)):
        year = start_year + offset
        if year in normalized:
            fallback = normalized[year]
        series.append(int(fallback))
    return series


def _real_series_from_nominal(series_rappen: list[int], inflation_series_bps: list[int]) -> list[int]:
    if not series_rappen:
        return []
    real = [int(series_rappen[0])]
    inflation_factor = 1.0
    for idx in range(1, len(series_rappen)):
        inflation_bps = inflation_series_bps[idx - 1] if idx - 1 < len(inflation_series_bps) else (
            inflation_series_bps[-1] if inflation_series_bps else 0
        )
        inflation_factor *= 1 + (inflation_bps / 10000)
        real.append(int(round(series_rappen[idx] / max(inflation_factor, 0.0001))))
    return real


def _goal_inflation_series_bps(
    cma: CapitalMarketAssumption,
    horizon_years: int,
    start_year: int,
    planning_inflation_bps: int | None = None,
) -> list[int]:
    years = max(1, int(horizon_years or 1))
    if planning_inflation_bps is not None:
        return [int(planning_inflation_bps)] * years
    return _inflation_path_series(cma, years, start_year)
