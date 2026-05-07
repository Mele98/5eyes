from pydantic import BaseModel, model_validator
from typing import Optional
from schemas.common import BaseResponse


class StrategySnapshotCreate(BaseModel):
    snapshot_date: str
    advisory_assets_rappen: int
    risk_profile_score: int
    risk_profile_label: str
    soll_equities_bps: int
    soll_bonds_bps: int
    soll_real_estate_bps: int
    soll_liquidity_bps: int
    soll_alternatives_bps: int
    band_equities_lo_bps: Optional[int] = None
    band_equities_hi_bps: Optional[int] = None
    band_bonds_lo_bps: Optional[int] = None
    band_bonds_hi_bps: Optional[int] = None
    band_real_estate_lo_bps: Optional[int] = None
    band_real_estate_hi_bps: Optional[int] = None
    band_liquidity_lo_bps: Optional[int] = None
    band_liquidity_hi_bps: Optional[int] = None
    band_alternatives_lo_bps: Optional[int] = None
    band_alternatives_hi_bps: Optional[int] = None
    advisor_note: Optional[str] = None
    goals_summary_json: Optional[str] = None

    @model_validator(mode="after")
    def check_bps_sum(self):
        total = (
            self.soll_equities_bps
            + self.soll_bonds_bps
            + self.soll_real_estate_bps
            + self.soll_liquidity_bps
            + self.soll_alternatives_bps
        )
        assert abs(total - 10000) <= 50, \
            f"BPS-Summe {total} weicht mehr als 50 BPS von 10000 ab (Rundungsfehler erlaubt)"
        return self


class StrategySnapshotResponse(BaseResponse):
    id: str
    mandate_id: str
    snapshot_date: str
    advisory_assets_rappen: int
    risk_profile_score: int
    risk_profile_label: str
    soll_equities_bps: int
    soll_bonds_bps: int
    soll_real_estate_bps: int
    soll_liquidity_bps: int
    soll_alternatives_bps: int
    band_equities_lo_bps: Optional[int]
    band_equities_hi_bps: Optional[int]
    band_bonds_lo_bps: Optional[int]
    band_bonds_hi_bps: Optional[int]
    band_real_estate_lo_bps: Optional[int]
    band_real_estate_hi_bps: Optional[int]
    band_liquidity_lo_bps: Optional[int]
    band_liquidity_hi_bps: Optional[int]
    band_alternatives_lo_bps: Optional[int]
    band_alternatives_hi_bps: Optional[int]
    advisor_note: Optional[str]
    goals_summary_json: Optional[str]
    created_by: str
    created_at: str
    updated_at: str


class DriftResult(BaseModel):
    snapshot_id: str
    snapshot_date: str
    advisory_assets_rappen: int
    risk_profile_label: str
    original: dict
    drifted: dict
    delta: dict
    bands: dict
    status: dict
    chart_years: list
    chart_strategy: list
    chart_spi_proxy: list
    chart_conservative: list
    has_drift_data: bool
