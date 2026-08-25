from typing import Optional

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("recipient_name")
    @classmethod
    def _strip_recipient_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("recipient_name darf nicht leer sein")
        return stripped


class PortfolioHandoffMarkExecuted(BaseModel):
    executed_note: Optional[str] = Field(default=None, max_length=2000)


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
    status: str
    created_by: str
    created_at: str
    updated_at: str
    executed_at: Optional[str]
    executed_by: Optional[str]
    executed_note: Optional[str]
    cancelled_at: Optional[str]
    cancelled_by: Optional[str]
    cancelled_reason: Optional[str]
