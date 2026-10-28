"""Sprint U-73 + U-74 (2026-06-03): Engine-Modell-Audit (UI-Hinweis).

Hintergrund
-----------
Sprint 6+7+8 (2026-05-17) haben in CapitalMarketAssumption Felder
fuer Nelson-Siegel Yield-Curve (Bonds), KGV-Mean-Reversion (Equity)
und Risikopraemien (RE + Alternatives) hinzugefuegt. Die Werte sind
im Admin-CMA-Editor pflegbar (5eyes_v2.html Zeile ~19099+).

ABER: im Berater-/Mandate-Workflow ist NICHT sichtbar, ob diese
Modelle fuer den aktuellen Run aktiv waren — Roadmap-Punkte 73
(NS+KGV) und 74 (Risikopraemien).

Dieses Modul liefert einen read-only Audit-Service der den Status
pro Modell zusammenfasst, damit Aggregator + Sub-App + PDF einen
Methodology-Hinweis darstellen koennen.

Activation-Regeln (= Bedingungen damit das Modell den Run beeinflusst)
- Nelson-Siegel:    bonds_ns_beta0/beta1/beta2/lambda alle gesetzt
- KGV-Mean-Reversion: equity_kgv_current/fair/alpha alle gesetzt
- Risikopraemien:    real_estate_risk_premium ODER
                     alternatives_risk_premium gesetzt UND
                     Nelson-Siegel aktiv (NS.short_rate ist Basis)

Read-only — verändert KEIN Berechnungsverhalten, schafft nur Sicht.

Kontrollrunde 2026-09-21 (Override-Begruendungs-Audit-Runde, Methodology-
Audit-Fund): "aktiv" hiess hier bisher nur "alle Felder gesetzt"
(presence-only). Der ECHTE Live-Engine-Gate (services.cma_validation.
validate_nelson_siegel_parameters / validate_equity_kgv_parameters,
aufgerufen aus services.portfolio_engine_cma._apply_cma_market_adjustments)
prueft zusaetzlich Wertebereiche (z.B. bonds_ns_lambda_x100 > 0,
equity_kgv_alpha_x100 im Bereich [0, 100]) und wirft eine
CMAValidationError (fail-closed), statt nur "inaktiv" zu melden. Ein CMA-
Datensatz konnte hier "Methodik aktiv" zeigen (PDF Sektion 20 + Client-
Portal-Hinweis), obwohl der Optimizer/Backtest denselben Datensatz
tatsaechlich ablehnt -- ein falscher, kundensichtbarer Methodik-Anspruch.
_build_ns_status/_build_kgv_status rufen die Validatoren jetzt zusaetzlich
auf und werten eine CMAValidationError als "nicht aktiv" (dieses Modul
bleibt read-only/non-blocking, die Exception wird hier abgefangen, nicht
weitergereicht).
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from services.cma_validation import (
    CMAValidationError,
    validate_equity_kgv_parameters,
    validate_nelson_siegel_parameters,
)


# Beschreibungs-Texte fuer die UI (Berater-tauglich, FINMA-bewusst,
# keine Verkaufsargumente, keine Garantien).
# NS-BOND-SLEEVE-COLLAPSE-001: dieser Text lautete "Bonds-Returns werden aus
# der Yield-Curve (5-Jahres-Yield) STATT aus festen Renditeerwartungen
# abgeleitet" und beschrieb damit das Ersetzen des Niveaus. Das war die
# Beschreibung eines Befundes: die Kurve ist eine Swap-/Staatskurve ohne
# Kreditaufschlag, die Renditeerwartungen sind Basis-plus-Spread -- das
# Ersetzen vernichtete den Aufschlag und kollabierte alle Bond-Sleeves.
# Die Kurve traegt jetzt nur die Termstruktur bei, und die Beschreibung muss
# das sagen: sie landet ueber das Methodik-Audit beim Berater.
NS_BASIS = (
    "Die Yield-Curve liefert einen Laufzeit-Zuschlag bzw. -Abschlag auf die "
    "Renditeerwartungen der Obligationen-Sub-Anlageklassen (Differenz zum "
    "5-Jahres-Punkt). Kreditaufschlaege und die Differenzierung der "
    "Sub-Anlageklassen bleiben erhalten; ohne Laufzeitpraeferenz ist der "
    "Effekt null."
)
KGV_BASIS = (
    "Aktien-Returns werden mit einem Shiller-CAPE-basierten Mean-"
    "Reversion-Adjustment versehen (zyklisch)."
)
RISK_PREMIA_BASIS = (
    "Real Estate / Alternatives koppeln an die Yield-Curve "
    "(short_rate + Risikopraemie) — atmen mit Zinsumfeld."
)


def _all_set(*values: Optional[Any]) -> bool:
    """True wenn alle Werte gesetzt sind (nicht None und nicht leer)."""
    return all(v is not None for v in values)


def _any_set(*values: Optional[Any]) -> bool:
    return any(v is not None for v in values)


def _build_ns_status(cma: Any) -> dict[str, Any]:
    """Status fuer Nelson-Siegel (U-73 Teil 1)."""
    b0 = getattr(cma, "bonds_ns_beta0_bps", None)
    b1 = getattr(cma, "bonds_ns_beta1_bps", None)
    b2 = getattr(cma, "bonds_ns_beta2_bps", None)
    lam = getattr(cma, "bonds_ns_lambda_x100", None)
    active = _all_set(b0, b1, b2, lam)
    invalid_reason = None
    if active:
        try:
            validate_nelson_siegel_parameters(cma)
        except CMAValidationError as exc:
            active = False
            invalid_reason = str(exc)
    result = {
        "model_key": "nelson_siegel",
        "label": "Nelson-Siegel Yield-Curve (Bonds)",
        "active": active,
        "basis": NS_BASIS,
        "parameters": {
            "beta0_bps": b0,
            "beta1_bps": b1,
            "beta2_bps": b2,
            "lambda_x100": lam,
        },
        "applies_to": "bonds",
        "activation_rule": "alle 4 Felder gesetzt UND wertebereichsgueltig",
    }
    if invalid_reason is not None:
        result["blocker_reason"] = "invalid_parameters"
        result["invalid_detail"] = invalid_reason
    return result


def _build_kgv_status(cma: Any) -> dict[str, Any]:
    """Status fuer KGV-Mean-Reversion (U-73 Teil 2)."""
    cur = getattr(cma, "equity_kgv_current_x10", None)
    fair = getattr(cma, "equity_kgv_fair_x10", None)
    alpha = getattr(cma, "equity_kgv_alpha_x100", None)
    active = _all_set(cur, fair, alpha)
    invalid_reason = None
    if active:
        try:
            validate_equity_kgv_parameters(cma)
        except CMAValidationError as exc:
            active = False
            invalid_reason = str(exc)
    result = {
        "model_key": "kgv_mean_reversion",
        "label": "KGV-Mean-Reversion (Equity)",
        "active": active,
        "basis": KGV_BASIS,
        "parameters": {
            "kgv_current_x10": cur,
            "kgv_fair_x10": fair,
            "alpha_x100": alpha,
        },
        "applies_to": "equity",
        "activation_rule": "alle 3 Felder gesetzt UND wertebereichsgueltig",
    }
    if invalid_reason is not None:
        result["blocker_reason"] = "invalid_parameters"
        result["invalid_detail"] = invalid_reason
    return result


def _build_risk_premia_status(
    cma: Any, *, ns_active: bool,
) -> dict[str, Any]:
    """Status fuer Risikopraemien-Modell (U-74).

    Aktivierungsregel: irgendeine Praemie gesetzt UND Nelson-Siegel
    aktiv (da short_rate die Basis liefert).
    """
    re_premium = getattr(cma, "real_estate_risk_premium_bps", None)
    alt_premium = getattr(cma, "alternatives_risk_premium_bps", None)
    any_premium_set = _any_set(re_premium, alt_premium)
    active = any_premium_set and ns_active

    blocker_reason = None
    if any_premium_set and not ns_active:
        blocker_reason = "nelson_siegel_required_as_base"
    elif not any_premium_set:
        blocker_reason = "no_premium_configured"

    return {
        "model_key": "risk_premia",
        "label": "Risikopraemien (RE + Alternatives)",
        "active": bool(active),
        "basis": RISK_PREMIA_BASIS,
        "parameters": {
            "real_estate_premium_bps": re_premium,
            "alternatives_premium_bps": alt_premium,
        },
        "applies_to": "real_estate_and_alternatives",
        "activation_rule": (
            "mindestens eine Praemie gesetzt UND Nelson-Siegel aktiv"
        ),
        "blocker_reason": blocker_reason,
    }


def _build_correlation_disclosure(cma: Any) -> dict[str, Any]:
    """CMA-001 / CMA-CORR-001: Korrelationsannahmen offenlegen statt still
    verwenden -- Bucket-Matrix (Payload oder benannte Default-Policy) und
    die globale Intra-Bucket-Korrelation der Sub-Anlageklassen."""
    from services.cma_correlation_provenance import (
        CORRELATION_DECISION_ID,
        jurisdiction_default_correlation_policy,
        normalized_jurisdiction,
    )
    from services.portfolio_engine_cma import _sub_class_intra_correlation_x100

    if getattr(cma, "correlation_matrix_json", None):
        bucket = {"source": "cma_payload", "policy": None}
        bucket_note = "Bucket-Korrelationen aus der CMA-Version (eigene Matrix)."
    else:
        policy = jurisdiction_default_correlation_policy(cma)
        if policy is not None:
            bucket = {"source": "named_default_policy", "policy": policy}
            bucket_note = (
                f"Bucket-Korrelationen: benannte Default-Policy {policy['decision_id']} "
                f"({policy['policy_name']} {policy['version']}, Ausschussfreigabe "
                "ausstehend) – die CMA-Version enthält keine eigene Matrix."
            )
        else:
            bucket = {"source": "missing", "policy": None}
            bucket_note = (
                "Bucket-Korrelationen: keine Matrix für Jurisdiktion "
                f"{normalized_jurisdiction(cma)} – stochastische Läufe sind "
                f"gesperrt ({CORRELATION_DECISION_ID})."
            )
    rho_x100 = _sub_class_intra_correlation_x100()
    if rho_x100 >= 100:
        rho_kind = "no_diversification_stress_case"
        rho_note = (
            "Sub-Anlageklassen innerhalb eines Buckets werden ohne "
            "Diversifikation gerechnet (Intra-Bucket-Korrelation 1.0): "
            "offengelegter konservativer Stressfall, keine genehmigte "
            "Sub-Asset-Korrelation."
        )
    else:
        rho_kind = "configured_without_approved_policy"
        rho_note = (
            f"Intra-Bucket-Korrelation {rho_x100 / 100:.2f} aus der "
            "Installationskonfiguration, ohne genehmigte Policy "
            f"({CORRELATION_DECISION_ID} offen)."
        )
    return {
        "decision_id": CORRELATION_DECISION_ID,
        "bucket_correlation": bucket,
        "sub_class_intra_correlation": {"value_x100": rho_x100, "kind": rho_kind},
        "notes": [bucket_note, rho_note],
    }


def audit_engine_models(db: Session) -> dict[str, Any]:
    """Liefert Methodology-Status fuer die aktuelle CMA-Version.

    Output-Schema
    -------------
    {
      'cma_id': str | None,
      'cma_version': int | None,
      'models': [
        { 'model_key', 'label', 'active', 'basis', 'parameters',
          'applies_to', 'activation_rule', [optional 'blocker_reason'] },
        ...
      ],
      'active_count': int,
      'methodology_notes': [str, ...]  # Berater-Hinweise fuer UI
    }
    """
    empty = {
        "cma_id": None,
        "cma_version": None,
        "models": [],
        "active_count": 0,
        "methodology_notes": [],
    }
    try:
        from models.allocation import CapitalMarketAssumption
        cma = (
            db.query(CapitalMarketAssumption)
            .filter(
                CapitalMarketAssumption.is_current == 1,
                CapitalMarketAssumption.deleted_at.is_(None),
            )
            .order_by(CapitalMarketAssumption.created_at.desc())
            .first()
        )
    except Exception:  # noqa: BLE001
        return empty

    if cma is None:
        return empty

    ns = _build_ns_status(cma)
    kgv = _build_kgv_status(cma)
    risk_premia = _build_risk_premia_status(cma, ns_active=ns["active"])
    models = [ns, kgv, risk_premia]
    active_count = sum(1 for m in models if m["active"])

    notes: list[str] = []
    if ns["active"]:
        notes.append(
            "Bond-Renditen aus Yield-Curve (Nelson-Siegel). "
            "Renditeerwartungen verändern sich mit der CMA-Aktualisierung."
        )
    if kgv["active"]:
        notes.append(
            "Aktien-Renditen mit zyklischem KGV-Adjustment. "
            "Bei hoher Bewertung wird konservativer projiziert."
        )
    if risk_premia["active"]:
        notes.append(
            "Real Estate / Alternatives reagieren auf Zinsumfeld. "
            "Renditeerwartung steigt mit short_rate."
        )
    if active_count == 0:
        notes.append(
            "Keine erweiterten Engine-Modelle aktiv — Optimizer arbeitet "
            "mit fixen Renditeerwartungen aus der CMA."
        )
    correlation_disclosure = _build_correlation_disclosure(cma)
    notes.extend(correlation_disclosure["notes"])

    return {
        "cma_id": getattr(cma, "id", None),
        "cma_version": getattr(cma, "version", None),
        "models": models,
        "active_count": active_count,
        "methodology_notes": notes,
        "correlation_disclosure": correlation_disclosure,
    }
