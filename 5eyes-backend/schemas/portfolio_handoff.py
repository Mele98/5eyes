import hashlib
import json
from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

from schemas.common import BaseResponse


class PortfolioHandoffCreate(BaseModel):
    """Weiterleitung der aktuellen Handelsliste an die ausfuehrende Stelle
    (Depotbank / internes Asset Management). Die Trade-Zahlen werden NICHT
    vom Client uebernommen -- der Router berechnet den Snapshot serverseitig
    aus dem angegebenen run_id ueber denselben Code-Pfad wie die
    Handelsliste-Anzeige im Review (siehe models/portfolio_handoff.py)."""

    recipient_name: str = Field(min_length=2, max_length=200)
    recipient_channel: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=2000)
    # Kontrollrunde 2026-09-21 (Data-Classification-Gate-Coverage-Audit):
    # dieser Endpunkt war nie an das Phase-0-Gate (enforce_data_classification)
    # angeschlossen -- persistiert eine echte Handelsanweisung an eine
    # ausfuehrende Stelle.
    data_classification: Literal["synthetic", "real"] = "synthetic"
    # HANDOFF-NEW-PRODUCT-001: ausdrueckliche Bestaetigung, dass fuer dieses
    # Mandat KEIN Depotbestand existiert (Neugeld). Nur dann gelten alle
    # SOLL-Produkte als Kauf mit IST = 0. Kein stiller Default (False), nur
    # ein echtes JSON-Boolean wird akzeptiert.
    confirm_no_existing_holdings: StrictBool = False

    @field_validator("recipient_name")
    @classmethod
    def _strip_recipient_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("recipient_name darf nicht leer sein")
        return stripped


class PortfolioHandoffMarkExecuted(BaseModel):
    """HANDOFF-EXECUTION-001: ein leerer Klick ist kein Ausfuehrungsnachweis.

    Ohne Broker-/Custody-Anbindung ist die einzige moegliche Evidence eine
    manuelle Bestaetigung mit der Auftrags-/Bestaetigungsreferenz der
    ausfuehrenden Stelle und dem Ausfuehrungsdatum. Der Server speichert sie
    ausdruecklich als ``manual_attestation`` -- nie als Fill-Evidence."""

    external_order_reference: str = Field(min_length=3, max_length=200)
    executed_on: date
    executed_note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("external_order_reference")
    @classmethod
    def _strip_reference(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("external_order_reference muss die Referenz der ausfuehrenden Stelle enthalten")
        return stripped

    @field_validator("executed_on")
    @classmethod
    def _not_in_future(cls, value: date) -> date:
        if value > datetime.now(timezone.utc).date():
            raise ValueError("executed_on darf nicht in der Zukunft liegen")
        return value


class PortfolioHandoffCancel(BaseModel):
    cancelled_reason: str = Field(min_length=3, max_length=2000)

    @field_validator("cancelled_reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("cancelled_reason muss begruendet werden")
        return stripped


class PortfolioHandoffResponse(BaseResponse):
    id: str
    mandate_id: str
    recommendation_run_id: Optional[str]
    trade_list_snapshot_json: str
    live_total_value_rappen: int
    position_count: int
    recipient_name: str
    recipient_channel: Optional[str]
    note: Optional[str]
    # HANDOFF-INTEGRITY-001: nur Zustaende der Zustandsmaschine
    # (models/portfolio_handoff.py::HANDOFF_STATUSES).
    status: Literal["Vorbereitet", "Gesendet", "Ausgeführt", "Storniert"]
    created_by: str
    created_at: str
    updated_at: str
    executed_at: Optional[str]
    executed_by: Optional[str]
    executed_note: Optional[str]
    cancelled_at: Optional[str]
    cancelled_by: Optional[str]
    cancelled_reason: Optional[str]
    execution_evidence_kind: Optional[str] = None
    execution_external_reference: Optional[str] = None
    execution_confirmed_on: Optional[str] = None
    snapshot_sha256: Optional[str] = None
    holdings_basis: Optional[Literal["recorded_depot", "confirmed_no_holdings"]] = None

    @model_validator(mode="after")
    def _integrity(self):
        """HANDOFF-INTEGRITY-001: ein Datensatz, der nicht in sich stimmig
        ist, wird nicht ausgeliefert (fail-closed statt manipulierter
        Nachweis): Snapshot ist eine JSON-Liste von Tradezeilen,
        position_count entspricht ihr, ein gespeicherter Hash passt zu den
        Bytes, Statusfelder sind kohaerent."""
        try:
            trades = json.loads(self.trade_list_snapshot_json)
        except (TypeError, ValueError):
            raise ValueError("trade_list_snapshot_json ist kein gueltiges JSON") from None
        if not isinstance(trades, list) or not all(isinstance(item, dict) for item in trades):
            raise ValueError("trade_list_snapshot_json ist keine Liste von Tradezeilen")
        if self.position_count != len(trades):
            raise ValueError("position_count passt nicht zu den gespeicherten Tradezeilen")
        if self.snapshot_sha256 is not None:
            actual = hashlib.sha256(self.trade_list_snapshot_json.encode("utf-8")).hexdigest()
            if actual != self.snapshot_sha256:
                raise ValueError("snapshot_sha256 passt nicht zum gespeicherten Snapshot")
        executed = self.status == "Ausgeführt"
        cancelled = self.status == "Storniert"
        if executed != bool(self.executed_at) or cancelled != bool(self.cancelled_at):
            raise ValueError("Statusfelder sind nicht kohaerent zum Status")
        return self


class PortfolioHandoffPreviewResponse(BaseModel):
    """HANDOFF-PREVIEW-PARITY-001: read-only Vorschau der Handelsliste.

    Dieselbe Funktion wie die Snapshot-Erzeugung (``snapshot_handoff``), ohne
    Persistieren. ``trades`` und ``snapshot_sha256`` entsprechen bei gleichen
    Eingaben exakt dem Snapshot einer anschliessenden Weiterleitung."""

    recommendation_run_id: str
    holdings_basis: Literal["recorded_depot", "confirmed_no_holdings"]
    confirm_no_existing_holdings: bool
    live_total_value_rappen: int
    position_count: int
    snapshot_sha256: str
    trades: list[dict]
