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
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session


# Beschreibungs-Texte fuer die UI (Berater-tauglich, FINMA-bewusst,
# keine Verkaufsargumente, keine Garantien).
NS_BASIS = (
    "Bonds-Returns werden aus der Yield-Curve (5-Jahres-Yield) statt "
    "aus festen Renditeerwartungen abgeleitet."
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
    return {
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
        "activation_rule": "alle 4 Felder gesetzt",
    }


def _build_kgv_status(cma: Any) -> dict[str, Any]:
    """Status fuer KGV-Mean-Reversion (U-73 Teil 2)."""
    cur = getattr(cma, "equity_kgv_current_x10", None)
    fair = getattr(cma, "equity_kgv_fair_x10", None)
    alpha = getattr(cma, "equity_kgv_alpha_x100", None)
    active = _all_set(cur, fair, alpha)
    return {
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
        "activation_rule": "alle 3 Felder gesetzt",
    }


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

    return {
        "cma_id": getattr(cma, "id", None),
        "cma_version": getattr(cma, "version", None),
        "models": models,
        "active_count": active_count,
        "methodology_notes": notes,
    }
