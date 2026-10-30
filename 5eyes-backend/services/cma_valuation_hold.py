"""Release-Hold ADR-12a: KGV-Bewertungsanpassung bis zum Ausschussentscheid.

CMA-001 (Entscheidungsdokument 2026-10-27, "Nomenklatur- und Release-Hold
fuer ADR-12a")
=========================================================================

ADR-12a bezeichnet die offene KGV-Formel/Kalibrierung. Das Referenzbeispiel
der Planung erwartet eine andere Groessenordnung als Produktivformel und
Golden-Test liefern; welche Seite fachlich gewollt ist, entscheidet der
Investment-Ausschuss -- nicht der Code. Bis dahin gilt: jede
kundenrelevante Finalisierung, in der das ungeklaerte KGV-Adjustment
tatsaechlich wirkt, ist blockiert. Formel und Werte bleiben unveraendert;
Entwuerfe werden weiter gerechnet.

Wo das Adjustment wirkt (Stand develop)
---------------------------------------
Zwei Darstellungen derselben Anpassung erreichen die Renditeannahme:

1. ``explicit_columns`` -- die CMA-Spalten ``equity_kgv_current_x10``,
   ``equity_kgv_fair_x10``, ``equity_kgv_alpha_x100``. Die Engine addiert
   das Adjustment in ``services/optimizer/scenario_engine.py::
   _compute_equity_kgv_adjustment`` (Optimizer-Szenarien) und in
   ``services/portfolio_engine_cma.py::_apply_cma_market_adjustments``
   (Reporting-MC, Allokations-Payload, Zielrechnung). Damit traegt jede
   Allokation, Empfehlung, Zielwahrscheinlichkeit und jedes daraus
   abgeleitete PDF/Handoff die Anpassung.
2. ``embedded_in_equity_home_return`` -- die Nicht-CH-Datenpipeline
   (``services/jurisdiction/data_pipeline.py``) rechnet das Adjustment
   bereits in ``equity_home_return_bps`` ein und dokumentiert es in
   ``source_detail["equity_kgv_mean_reversion"]``.

"Nachweislich KGV-deaktiviert" heisst: keine der drei Spalten gesetzt UND
kein eingebetteter KGV-Nachweis. Eine nur teilweise gesetzte Spaltengruppe
ist kein Deaktivierungsnachweis (die Engine lehnt sie ohnehin ab) und gilt
deshalb als aktiv. Verweist eine Allokation auf eine nicht auffindbare CMA,
ist die Deaktivierung nicht belegbar -> ebenfalls Hold (fail-closed).

Dieses Modul waehlt KEINEN Wert und aendert KEINE Formel.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

CMA_ADR12A_HOLD = "CMA_ADR12A_HOLD"

REPRESENTATION_EXPLICIT = "explicit_columns"
REPRESENTATION_EMBEDDED = "embedded_in_equity_home_return"
REPRESENTATION_UNVERIFIABLE = "cma_not_resolvable"

_KGV_COLUMNS = (
    "equity_kgv_current_x10",
    "equity_kgv_fair_x10",
    "equity_kgv_alpha_x100",
)

ADR12A_HOLD_MESSAGE = (
    "Die verwendeten Kapitalmarktannahmen enthalten eine KGV-Bewertungs"
    "anpassung (ADR-12a), deren Formel und Kalibrierung noch nicht vom "
    "Investment-Ausschuss entschieden ist. Entwürfe bleiben sichtbar, die "
    "Finalisierung und Weitergabe an den Kunden sind bis zum Entscheid "
    "gesperrt. Abhilfe: eine CMA-Version ohne KGV-Anpassung verwenden."
)
_UNVERIFIABLE_MESSAGE = (
    "Die Kapitalmarktannahmen dieser Empfehlung sind nicht auffindbar; "
    "dass keine ungeklärte KGV-Bewertungsanpassung (ADR-12a) wirkt, ist "
    "nicht belegbar. Bitte die Allokation neu generieren."
)


def _embedded_kgv_present(cma: Any) -> bool:
    if getattr(cma, "equity_home_return_bps", None) is None:
        return False
    raw = getattr(cma, "source_detail", None)
    if raw in (None, ""):
        return False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    detail = parsed.get("equity_kgv_mean_reversion")
    return isinstance(detail, dict) and detail.get("pe_proxy_value_kgv_current") is not None


def kgv_adjustment_representation(cma: Any) -> Optional[str]:
    """Darstellung eines aktiven KGV-Adjustments, ``None`` = nachweislich aus."""
    if cma is None:
        return REPRESENTATION_UNVERIFIABLE
    if any(getattr(cma, column, None) is not None for column in _KGV_COLUMNS):
        return REPRESENTATION_EXPLICIT
    if _embedded_kgv_present(cma):
        return REPRESENTATION_EMBEDDED
    return None


def adr12a_hold_finding(cma: Any) -> Optional[tuple[str, str]]:
    """``(reason_code, message)`` wenn der Hold greift, sonst ``None``."""
    representation = kgv_adjustment_representation(cma)
    if representation is None:
        return None
    if representation == REPRESENTATION_UNVERIFIABLE:
        return CMA_ADR12A_HOLD, _UNVERIFIABLE_MESSAGE
    return CMA_ADR12A_HOLD, ADR12A_HOLD_MESSAGE


def adr12a_hold_status(cma: Any) -> dict[str, Any]:
    """Lesbarer Status fuer Offenlegung (Entwurf: "blockiert fuer Finalisierung")."""
    representation = kgv_adjustment_representation(cma)
    return {
        "reason_code": CMA_ADR12A_HOLD if representation is not None else None,
        "blocks_finalization": representation is not None,
        "kgv_representation": representation,
    }


def _load_cma(db: Session, cma_id: Any) -> Any:
    from models.allocation import CapitalMarketAssumption

    return (
        db.query(CapitalMarketAssumption)
        .filter(CapitalMarketAssumption.id == str(cma_id))
        .first()
    )


def assert_allocation_cma_without_adr12a_hold(
    db: Session,
    allocation: Any,
    *,
    channel: str,
    channel_label: str,
) -> None:
    """409 ``CMA_ADR12A_HOLD``, wenn die CMA der Allokation KGV-aktiv ist.

    Eine Allokation ganz ohne CMA-Referenz ist nicht Sache dieses Holds:
    sie ist ohnehin nicht finalisierbar (``_validate_recommendation_for_
    finalization`` verlangt eine CMA), und ein Handoff setzt einen
    finalisierten Run voraus. Eine gesetzte, aber nicht aufloesbare
    Referenz dagegen ist kein Deaktivierungsnachweis -> Hold.
    """
    cma_id = getattr(allocation, "capital_market_assumptions_id", None)
    if not cma_id:
        return
    cma = _load_cma(db, cma_id)
    finding = adr12a_hold_finding(cma)
    if finding is None:
        return
    reason_code, message = finding
    raise HTTPException(
        status_code=409,
        detail={
            "reason_code": reason_code,
            "message": f"{channel_label}. {message}",
            "channel": channel,
            "target_allocation_id": getattr(allocation, "id", None),
            "capital_market_assumptions_id": getattr(
                allocation, "capital_market_assumptions_id", None
            ),
            "kgv_representation": kgv_adjustment_representation(cma),
        },
    )
