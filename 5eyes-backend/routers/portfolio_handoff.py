"""Weiterleitung ans Asset Management (User-Direktive, 2026-08-08).

5eyes berechnet nur die Zielallokation/Handelsliste -- die tatsaechliche
Ausfuehrung (Kauf/Verkauf in den echten Kundendepots) liegt bei der
Depotbank/dem internen Asset Management. Diese Router-Datei liefert den
formalen, auditierbaren Nachweis der Uebergabe: ein unveraenderlicher
Snapshot der zum Sendezeitpunkt serverseitig berechneten Trades (siehe
services/portfolio_handoff.py) plus Status-Lebenszyklus (Gesendet ->
Ausgefuehrt/Storniert). Siehe models/portfolio_handoff.py fuer die
Rechenschaftsablegungs-Begruendung (Auftragsrecht, Art. 400 OR).
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, new_uuid
from models.mandates import Mandate
from models.portfolio_handoff import PortfolioHandoff
from models.review import RecommendationRun
from models.users import User
from routers.auth import _extract_client_ip
from schemas.portfolio_handoff import (
    PortfolioHandoffCancel,
    PortfolioHandoffCreate,
    PortfolioHandoffMarkExecuted,
    PortfolioHandoffResponse,
)
from services.audit import log
from services.auth import get_current_user, get_mandate_for_user_or_404, require_advisor
from services.portfolio_handoff import NoTradeListAvailableError, snapshot_handoff_trades

router = APIRouter(tags=["Weiterleitung Asset Management"])
logger = logging.getLogger(__name__)

# Nur "Gesendet" darf in einen Endzustand wechseln -- weder ein bereits
# ausgefuehrter noch ein stornierter Handoff ist danach nochmals aenderbar
# (Audit-Integritaet: der Endzustand ist final).
_OPEN_STATUS = "Gesendet"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


def _get_recommendation_run_or_404(mandate_id: str, run_id: str, db: Session, current_user: User) -> RecommendationRun:
    _get_mandate_or_404(mandate_id, db, current_user)
    run = db.query(RecommendationRun).filter(
        RecommendationRun.id == run_id,
        RecommendationRun.mandate_id == mandate_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Empfehlung nicht gefunden")
    return run


def _get_handoff_or_404(mandate_id: str, handoff_id: str, db: Session, current_user: User) -> PortfolioHandoff:
    _get_mandate_or_404(mandate_id, db, current_user)
    handoff = db.query(PortfolioHandoff).filter(
        PortfolioHandoff.id == handoff_id,
        PortfolioHandoff.mandate_id == mandate_id,
    ).first()
    if not handoff:
        raise HTTPException(status_code=404, detail="Weiterleitung nicht gefunden")
    return handoff


def _atomically_close_handoff_or_409(
    db: Session, handoff_id: str, mandate_id: str, *, updates: dict,
) -> None:
    """REC-005 (Codex-Audit 2026-08-25): mark-executed/cancel lasen den
    Endzustand bisher per Plain-SELECT und pruefen ihn erst danach in
    Python -- zwei nahezu gleichzeitige Aufrufe (Doppelklick, zwei Tabs)
    konnten beide denselben OFFENEN Zustand lesen, bevor eine der beiden
    Transaktionen committet, und beide Endzustaende schreiben ("Last write
    wins" statt der erwarteten 409-Ablehnung).

    with_for_update() haette hier NICHT geholfen: SQLite (der aktuelle
    Produktivpfad, Electron-Desktop) ignoriert FOR UPDATE stillschweigend
    (SQLAlchemy-Dialekt unterstuetzt die Klausel gar nicht). Stattdessen ein
    atomares bedingtes UPDATE (WHERE id=... AND status=OPEN_STATUS) -- die
    Bedingung wird von der DB selbst als Teil EINES Statements ausgewertet,
    unabhaengig vom Backend. Matcht die WHERE-Klausel 0 Zeilen, hat eine
    andere Transaktion den Zustand bereits geaendert -> 409, konsistent mit
    dem vorherigen Verhalten bei explizit falschem Vorzustand.
    """
    result = db.query(PortfolioHandoff).filter(
        PortfolioHandoff.id == handoff_id,
        PortfolioHandoff.mandate_id == mandate_id,
        PortfolioHandoff.status == _OPEN_STATUS,
    # synchronize_session='fetch' (statt False): identifiziert die
    # betroffene(n) Zeile(n) und aktualisiert bereits in dieser Session
    # geladene ORM-Objekte -- sonst haette ein vorheriges _get_handoff_or_404()
    # (siehe Aufrufer) weiterhin den veralteten Status im Speicher, auch nach
    # dem Bulk-UPDATE.
    ).update(updates, synchronize_session="fetch")
    if result == 0:
        # Mandats-/Existenz-Pruefung ist bereits durch den Aufrufer erfolgt
        # (dieser wird nach einer erfolgreichen _get_handoff_or_404() weiter
        # oben aufgerufen) -- hier nur noch der aktuelle Status fuer die
        # Fehlermeldung, kein current_user noetig.
        current_status = db.query(PortfolioHandoff.status).filter(
            PortfolioHandoff.id == handoff_id,
        ).scalar()
        raise HTTPException(
            status_code=409,
            detail=f"Weiterleitung ist bereits im Endzustand '{current_status}'.",
        )


@router.get(
    "/mandates/{mandate_id}/portfolio-handoffs",
    response_model=list[PortfolioHandoffResponse],
)
def list_portfolio_handoffs(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(PortfolioHandoff).filter(
        PortfolioHandoff.mandate_id == mandate_id,
    ).order_by(PortfolioHandoff.created_at.desc()).all()


@router.post(
    "/mandates/{mandate_id}/recommendations/{run_id}/portfolio-handoffs",
    response_model=PortfolioHandoffResponse,
    status_code=201,
)
def create_portfolio_handoff(
    mandate_id: str,
    run_id: str,
    body: PortfolioHandoffCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # mandate_type ist die Compliance-Untergrenze (identisches Prinzip wie
    # 5eyes_v2.html::_reviewIsDiscretionaryMandate() und
    # services/advisory_report.py::_erkenntnisse_is_discretionary_mandate) --
    # nur Vermoegensverwaltung hat Ausfuehrungsbefugnis gegenueber der
    # Depotstelle. Reine Anlageberatung darf keine Weiterleitung erzeugen,
    # auch nicht per direktem API-Aufruf ausserhalb der UI (die den Button
    # bereits versteckt, aber Server-Enforcement ist die eigentliche Grenze).
    if mandate.mandate_type != "Vermögensverwaltung":
        raise HTTPException(
            status_code=403,
            detail=(
                "Weiterleitung an die Ausfuehrungsstelle ist nur fuer "
                "Vermoegensverwaltungsmandate vorgesehen (keine Ausfuehrungs-"
                "befugnis bei Anlageberatung/Finanzplanung/Reporting only)."
            ),
        )
    run = _get_recommendation_run_or_404(mandate_id, run_id, db, current_user)
    try:
        trades, total_value_rappen = snapshot_handoff_trades(db, mandate, run, current_user.id)
    except NoTradeListAvailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        # z.B. fehlendes Risikoprofil/Soll-Allokation -- dieselbe Fehlerklasse
        # wie routers/review.py::get_recommendation_payload.
        raise HTTPException(status_code=409, detail=str(exc))

    now = _now()
    handoff = PortfolioHandoff(
        id=new_uuid(),
        mandate_id=mandate_id,
        recommendation_run_id=run.id,
        trade_list_snapshot_json=json.dumps(trades, ensure_ascii=False),
        live_total_value_rappen=total_value_rappen,
        position_count=len(trades),
        recipient_name=body.recipient_name,
        recipient_channel=body.recipient_channel,
        note=body.note,
        status=_OPEN_STATUS,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(handoff)
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="portfolio_handoffs",
        record_id=handoff.id,
        action="CREATE",
        new_value=f"{len(trades)} Positionen an '{body.recipient_name}'",
        mandate_id=mandate_id,
        ip_address=_extract_client_ip(request),
    )
    db.commit()
    db.refresh(handoff)
    return handoff


@router.post(
    "/mandates/{mandate_id}/portfolio-handoffs/{handoff_id}/mark-executed",
    response_model=PortfolioHandoffResponse,
)
def mark_portfolio_handoff_executed(
    mandate_id: str,
    handoff_id: str,
    body: PortfolioHandoffMarkExecuted,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    _get_handoff_or_404(mandate_id, handoff_id, db, current_user)
    now = _now()
    _atomically_close_handoff_or_409(db, handoff_id, mandate_id, updates={
        "status": "Ausgeführt",
        "executed_at": now,
        "executed_by": current_user.id,
        "executed_note": body.executed_note,
        "updated_at": now,
    })
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="portfolio_handoffs",
        record_id=handoff_id,
        action="UPDATE",
        field_name="status",
        old_value=_OPEN_STATUS,
        new_value="Ausgeführt",
        mandate_id=mandate_id,
        ip_address=_extract_client_ip(request),
    )
    db.commit()
    return db.query(PortfolioHandoff).filter(PortfolioHandoff.id == handoff_id).first()


@router.post(
    "/mandates/{mandate_id}/portfolio-handoffs/{handoff_id}/cancel",
    response_model=PortfolioHandoffResponse,
)
def cancel_portfolio_handoff(
    mandate_id: str,
    handoff_id: str,
    body: PortfolioHandoffCancel,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    _get_handoff_or_404(mandate_id, handoff_id, db, current_user)
    now = _now()
    _atomically_close_handoff_or_409(db, handoff_id, mandate_id, updates={
        "status": "Storniert",
        "cancelled_at": now,
        "cancelled_by": current_user.id,
        "cancelled_reason": body.cancelled_reason,
        "updated_at": now,
    })
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="portfolio_handoffs",
        record_id=handoff_id,
        action="UPDATE",
        field_name="status",
        old_value=_OPEN_STATUS,
        new_value="Storniert",
        mandate_id=mandate_id,
        ip_address=_extract_client_ip(request),
    )
    db.commit()
    return db.query(PortfolioHandoff).filter(PortfolioHandoff.id == handoff_id).first()
