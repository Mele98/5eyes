"""Pydantic-Schemas fuer das CMA_POLICY-Modell (CMA-001)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class CmaPolicyComponentIn(BaseModel):
    asset_key: str = Field(..., min_length=1, max_length=64)
    component: str = Field(..., min_length=1, max_length=64)
    value_bps: int
    unit: str = "bps_pa"
    horizon_years: int
    method: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    sign: str
    confidence: Optional[str] = None
    range_min_bps: int
    range_max_bps: int


class CmaPolicyComponentOut(CmaPolicyComponentIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


class CmaPolicyCreate(BaseModel):
    policy_id: str = Field(..., min_length=1, max_length=128)
    capital_market_assumptions_id: str
    correlation_policy_ref: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    data_as_of: Optional[str] = None
    base_currency: Optional[str] = None
    return_basis: Optional[str] = None
    fee_basis: Optional[str] = None
    method_version: Optional[str] = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    rationale: Optional[str] = None
    impact_report_ref: Optional[str] = None
    supersedes_id: Optional[str] = None
    expiry_rule: Optional[str] = None
    exception_rule: Optional[str] = None
    rollback_rule: Optional[str] = None
    components: list[CmaPolicyComponentIn] = Field(default_factory=list)


class CmaPolicyComponentsReplace(BaseModel):
    components: list[CmaPolicyComponentIn]


class CmaPolicyDecision(BaseModel):
    rationale: str = Field(..., min_length=1)


class CmaPolicyApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    approver_id: str
    approved_at: str
    rationale: str
    content_hash: str


class CmaPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_id: str
    version: int
    status: str
    capital_market_assumptions_id: str
    correlation_policy_ref: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    data_as_of: Optional[str] = None
    base_currency: Optional[str] = None
    return_basis: Optional[str] = None
    fee_basis: Optional[str] = None
    method_version: Optional[str] = None
    sources_json: Optional[str] = None
    rationale: Optional[str] = None
    impact_report_ref: Optional[str] = None
    supersedes_id: Optional[str] = None
    expiry_rule: Optional[str] = None
    exception_rule: Optional[str] = None
    rollback_rule: Optional[str] = None
    content_hash: Optional[str] = None
    created_by: str
    created_at: str
    validated_by: Optional[str] = None
    validated_at: Optional[str] = None
    approved_at: Optional[str] = None
    activated_by: Optional[str] = None
    activated_at: Optional[str] = None
    retired_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    components: list[CmaPolicyComponentOut] = Field(default_factory=list)
    approvals: list[CmaPolicyApprovalOut] = Field(default_factory=list)


class CmaPolicyModelStatus(BaseModel):
    enforced: bool
    explanation: str
