"""Weiterleitung ans Asset Management (User-Direktive, 2026-08-08).

5eyes ist eine Beratungs-/Allokations-Engine, keine Depotstelle -- es haelt
keine echten Konten/Depots. Die Handelsliste (Rebalancing-Trades), die im
Review bei einem discretionaeren Mandat entsteht, war bislang nur eine
Anzeige/PDF-Ausgabe (openTradeList() in 5eyes_v2.html) ohne jeden Nachweis,
DASS und WANN sie tatsaechlich an die ausfuehrende Stelle (Depotbank /
internes Asset Management) uebergeben wurde. Fuer die Rechenschaftsablegung
bei einem Vermoegensverwaltungsmandat (Auftragsrecht, Art. 400 OR) muss
diese Uebergabe nachweisbar sein.

Dieses Modell haelt einen UNVERAENDERLICHEN Snapshot der Trade-Liste, wie sie
zum Zeitpunkt der Weiterleitung serverseitig ueber
services.portfolio_engine.build_recommendation_payload_from_run() berechnet
wurde (derselbe Code-Pfad wie routers/review.py::get_recommendation_payload,
den auch die Handelsliste-Anzeige im Review nutzt -- keine zweite,
unabhaengige Berechnung, um Drift zwischen Anzeige und Nachweis
auszuschliessen), plus einen einfachen Status-Lebenszyklus (Gesendet ->
Ausgefuehrt/Storniert). Nur die Statusfelder aendern sich nach dem Anlegen;
Snapshot-Inhalt und Provenienz-Felder werden nie mehr geschrieben (kein
Router-Endpoint bietet das an).

Tenant-Isolation erfolgt transitiv ueber mandate_id (kein eigenes
tenant_id-Feld -- identisches Muster zu Goal/Cashflow/ContractDocument,
durchgesetzt ueber services.auth.get_mandate_for_user_or_404()).

recommendation_run_id ist bewusst NULLABLE (identisches Muster zu
AdvisoryLog.recommendation_run_id, models/review.py) -- services/
recommendation_run_cleanup.py loescht alte RecommendationRun-Zeilen per
Retention; ein Handoff darf diese Bereinigung nicht blockieren, verliert im
Cleanup-Fall nur die Provenienz-Referenz, nicht seinen eigenen
(unveraenderten) Snapshot-Inhalt.
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class PortfolioHandoff(Base):
    __tablename__ = "portfolio_handoffs"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=True)

    # Unveraenderlicher Snapshot der zum Sendezeitpunkt server-berechneten
    # Trades (services/portfolio_handoff.py::snapshot_handoff_trades()).
    trade_list_snapshot_json = Column(String, nullable=False)
    live_total_value_rappen = Column(Integer, nullable=False, default=0)
    position_count = Column(Integer, nullable=False, default=0)

    # Kein Bank-/Custody-API-Zugang in dieser Installation -- rein
    # dokumentarischer Nachweis, wer/wie kontaktiert wurde.
    recipient_name = Column(String, nullable=False)
    recipient_channel = Column(String)
    note = Column(String)

    status = Column(String, nullable=False, default="Gesendet")

    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    executed_at = Column(String)
    executed_by = Column(String, ForeignKey("users.id"), nullable=True)
    executed_note = Column(String)

    cancelled_at = Column(String)
    cancelled_by = Column(String, ForeignKey("users.id"), nullable=True)
    cancelled_reason = Column(String)

    mandate = relationship("Mandate", back_populates="portfolio_handoffs")
    recommendation_run = relationship("RecommendationRun")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_portfolio_handoffs_mandate_created", "mandate_id", "created_at"),
    )
