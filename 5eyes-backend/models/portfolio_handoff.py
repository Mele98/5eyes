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
auszuschliessen), plus einen einfachen Status-Lebenszyklus (Vorbereitet ->
Ausgefuehrt/Storniert; "Gesendet" nur Altbestand, HANDOFF-DELIVERY-001).
Nur die Statusfelder aendern sich nach dem Anlegen;
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

from sqlalchemy import DDL, BigInteger, Column, ForeignKey, Index, Integer, String, event, text
from sqlalchemy.orm import relationship

from database import Base

# HANDOFF-DELIVERY-001: ohne Transportadapter und Empfangsquittung ist ein
# lokal angelegter Handoff hoechstens "zur manuellen Uebermittlung
# vorbereitet" -- nie "Gesendet". "Gesendet" bleibt nur als offener
# Altbestand (vor diesem Fix angelegte Zeilen) lesbar und abschliessbar.
HANDOFF_STATUS_PREPARED = "Vorbereitet"
HANDOFF_STATUS_LEGACY_SENT = "Gesendet"
HANDOFF_STATUS_EXECUTED = "Ausgeführt"
HANDOFF_STATUS_CANCELLED = "Storniert"
HANDOFF_OPEN_STATUSES = (HANDOFF_STATUS_PREPARED, HANDOFF_STATUS_LEGACY_SENT)
HANDOFF_STATUSES = HANDOFF_OPEN_STATUSES + (HANDOFF_STATUS_EXECUTED, HANDOFF_STATUS_CANCELLED)

# HANDOFF-IDEMPOTENCY-001: hoechstens EIN offener Handoff je fachlicher
# Identitaet (Mandat, Run, Snapshot, Empfaenger). Altbestand ohne Schluessel
# (NULL) bleibt unberuehrt. Textgleich in ORM, Runtime-Patch und Alembic.
HANDOFF_OPEN_BUSINESS_KEY_INDEX = "ux_portfolio_handoffs_open_business_key"
HANDOFF_OPEN_BUSINESS_KEY_PREDICATE = (
    "business_key_hash IS NOT NULL AND status IN ('Vorbereitet', 'Gesendet')"
)

# HANDOFF-EXECUTION-001: einzige Evidence-Art, die diese Installation kennt
# (kein Broker-/Custody-Feed): manuelle Bestaetigung mit externer Referenz.
EXECUTION_EVIDENCE_MANUAL_ATTESTATION = "manual_attestation"

# HANDOFF-NEW-PRODUCT-001: worauf das IST des Snapshots beruht -- erfasstes,
# vollstaendig belegtes Depot oder ausdrueckliche Bestaetigung "kein Bestand"
# (Neugeld). Konstanten: services/portfolio_handoff.py::HOLDINGS_BASIS_*.
HANDOFF_HOLDINGS_BASES = ("recorded_depot", "confirmed_no_holdings")

# HANDOFF-DB-INVARIANT-001: DB-seitige Invarianten (Trigger statt CHECK,
# Repo-Muster fuer Bestandstabellen -- SQLite kann CHECK nicht nachruesten).
# Geprueft wird jedes INSERT und jedes UPDATE, das die betroffenen Spalten
# setzt; Altzeilen (z.B. snapshot_sha256 NULL) bleiben lesbar und
# abschliessbar, weil ein Statuswechsel den Hash nicht beruehrt.
_STATUS_SQL = ", ".join(f"'{value}'" for value in HANDOFF_STATUSES)
_BASES_SQL = ", ".join(f"'{value}'" for value in HANDOFF_HOLDINGS_BASES)
_SQLITE_HASH_INVALID = (
    "NEW.snapshot_sha256 IS NULL OR length(NEW.snapshot_sha256) <> 64 "
    "OR NEW.snapshot_sha256 GLOB '*[^0-9a-f]*'"
)
_SQLITE_ROW_INVALID = (
    f"NEW.status IS NULL OR NEW.status NOT IN ({_STATUS_SQL}) "
    "OR NEW.position_count IS NULL OR NEW.position_count < 0 "
    f"OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ({_BASES_SQL}))"
)
HANDOFF_INVARIANT_SQLITE_TRIGGERS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_insert "
    "BEFORE INSERT ON portfolio_handoffs FOR EACH ROW "
    f"WHEN {_SQLITE_ROW_INVALID} OR {_SQLITE_HASH_INVALID} "
    "BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_update "
    "BEFORE UPDATE OF status, position_count, snapshot_sha256, holdings_basis "
    "ON portfolio_handoffs FOR EACH ROW "
    f"WHEN {_SQLITE_ROW_INVALID} OR (NEW.snapshot_sha256 IS NOT OLD.snapshot_sha256 "
    f"AND ({_SQLITE_HASH_INVALID})) "
    "BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END",
)
HANDOFF_INVARIANT_PG_FUNCTION = f"""
CREATE OR REPLACE FUNCTION portfolio_handoffs_invariants()
RETURNS trigger AS $$
BEGIN
    IF NEW.status IS NULL OR NEW.status NOT IN ({_STATUS_SQL})
       OR NEW.position_count IS NULL OR NEW.position_count < 0
       OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ({_BASES_SQL})) THEN
        RAISE EXCEPTION 'portfolio_handoffs invariant violated';
    END IF;
    IF (TG_OP = 'INSERT' OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256)
       AND (NEW.snapshot_sha256 IS NULL OR NEW.snapshot_sha256 !~ '^[0-9a-f]{{64}}$') THEN
        RAISE EXCEPTION 'portfolio_handoffs invariant violated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
HANDOFF_INVARIANT_PG_TRIGGER = """
CREATE TRIGGER trg_portfolio_handoffs_invariants
BEFORE INSERT OR UPDATE OF status, position_count, snapshot_sha256, holdings_basis
ON portfolio_handoffs
FOR EACH ROW EXECUTE FUNCTION portfolio_handoffs_invariants()
"""


class PortfolioHandoff(Base):
    __tablename__ = "portfolio_handoffs"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=True)

    # Unveraenderlicher Snapshot der zum Sendezeitpunkt server-berechneten
    # Trades (services/portfolio_handoff.py::snapshot_handoff()).
    trade_list_snapshot_json = Column(String, nullable=False)
    live_total_value_rappen = Column(BigInteger, nullable=False, default=0)
    position_count = Column(Integer, nullable=False, default=0)

    # Kein Bank-/Custody-API-Zugang in dieser Installation -- rein
    # dokumentarischer Nachweis, wer/wie kontaktiert wurde.
    recipient_name = Column(String, nullable=False)
    recipient_channel = Column(String)
    note = Column(String)

    status = Column(String, nullable=False, default=HANDOFF_STATUS_PREPARED)

    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    executed_at = Column(String)
    executed_by = Column(String, ForeignKey("users.id"), nullable=True)
    executed_note = Column(String)

    cancelled_at = Column(String)
    cancelled_by = Column(String, ForeignKey("users.id"), nullable=True)
    cancelled_reason = Column(String)

    # HANDOFF-INTEGRITY-001: SHA-256 ueber trade_list_snapshot_json (UTF-8),
    # beim Anlegen gesetzt; NULL nur bei Altbestand.
    snapshot_sha256 = Column(String)
    # HANDOFF-IDEMPOTENCY-001: Hash der fachlichen Identitaet, siehe
    # services/portfolio_handoff.py::handoff_business_key_hash.
    business_key_hash = Column(String)
    # HANDOFF-EXECUTION-001: Art und Inhalt der Ausfuehrungs-Evidence.
    execution_evidence_kind = Column(String)
    execution_external_reference = Column(String)
    execution_confirmed_on = Column(String)
    # HANDOFF-NEW-PRODUCT-001: Bestandsbasis des Snapshots
    # (HANDOFF_HOLDINGS_BASES); NULL nur bei Altbestand.
    holdings_basis = Column(String)

    mandate = relationship("Mandate", back_populates="portfolio_handoffs")
    recommendation_run = relationship("RecommendationRun")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_portfolio_handoffs_mandate_created", "mandate_id", "created_at"),
        Index(
            HANDOFF_OPEN_BUSINESS_KEY_INDEX, "business_key_hash", unique=True,
            sqlite_where=text(HANDOFF_OPEN_BUSINESS_KEY_PREDICATE),
            postgresql_where=text(HANDOFF_OPEN_BUSINESS_KEY_PREDICATE),
        ),
    )


for _trigger_ddl in HANDOFF_INVARIANT_SQLITE_TRIGGERS:
    event.listen(
        PortfolioHandoff.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )
for _pg_ddl in (HANDOFF_INVARIANT_PG_FUNCTION, HANDOFF_INVARIANT_PG_TRIGGER):
    event.listen(
        PortfolioHandoff.__table__,
        "after_create",
        DDL(_pg_ddl).execute_if(dialect="postgresql"),
    )
