from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional, Literal
from schemas.common import BaseResponse
from schemas.allocation import AllocationPreferencesPayload, LiveRebalancingResponse


class ReviewTriggerCreate(BaseModel):
    trigger_type: Literal["Zeit", "Markt", "Ereignis"]
    trigger_name: str
    threshold_bps: Optional[int] = None
    frequency: Optional[str] = None
    next_due_at: Optional[str] = None


class ReviewTriggerResolve(BaseModel):
    decision: str
    triggered_notes: Optional[str] = None


class ReviewTriggerResponse(BaseResponse):
    id: str
    mandate_id: str
    trigger_type: str
    trigger_name: str
    threshold_bps: Optional[int]
    frequency: Optional[str]
    status: str
    next_due_at: Optional[str]
    last_triggered_at: Optional[str]
    triggered_value: Optional[str]
    triggered_at: Optional[str]
    triggered_notes: Optional[str]
    calendar_exported: int
    is_system: int
    created_at: str
    updated_at: str


class AdvisoryLogCreate(BaseModel):
    entry_type: Literal[
        "Jahresreview", "Quartalscheck", "Strategie-Anpassung",
        "Override-Entscheid", "Ereignis-Reaktion", "Drift-Entscheid",
        "Zieländerung", "Restriktionsänderung",
        "Initialer Beratungsabschluss", "Eignungsprüfung", "Sonstiges"
    ]
    title: str
    description: Optional[str] = None
    decision: Optional[Literal[
        "Keine Transaktion",
        "Transaktion empfohlen",
        "Strategie angepasst",
        "Profil angepasst",
        "Override bestätigt",
        "Kein Handlungsbedarf",
    ]] = None
    trigger_id: Optional[str] = None
    client_signed: bool = False
    client_signed_at: Optional[str] = None
    document_id: Optional[str] = None
    entry_date: Optional[str] = None

    @model_validator(mode="after")
    def validate_signature(self):
        if self.client_signed and not self.client_signed_at:
            raise ValueError("client_signed_at ist Pflicht wenn client_signed=True")
        return self


class AdvisoryLogResponse(BaseResponse):
    id: str
    mandate_id: str
    entry_type: str
    title: str
    description: Optional[str]
    decision: Optional[str]
    trigger_id: Optional[str]
    advisor_id: str
    client_signed: int
    client_signed_at: Optional[str]
    document_id: Optional[str]
    entry_date: str
    created_at: str
    updated_at: str


class ContractDocumentCreate(BaseModel):
    document_type: Literal[
        "Beratungsvertrag", "Anlagestrategie", "Anlagerezept",
        "Beratungsprotokoll", "Risikoprofilierung",
        "Override-Zustimmung", "Eignungsprüfung", "Sonstiges"
    ]
    title: str
    content_json: Optional[str] = None


class ContractDocumentSign(BaseModel):
    signed_by_advisor: bool = False
    signed_by_client: bool = False

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.signed_by_advisor and not self.signed_by_client:
            raise ValueError("Mindestens ein Unterzeichner muss angegeben werden")
        return self


class ContractDocumentResponse(BaseResponse):
    id: str
    mandate_id: str
    document_type: str
    title: str
    status: str
    signed_by_advisor: int
    signed_by_client: int
    signed_at: Optional[str]
    version: int
    supersedes_id: Optional[str]
    pdf_path: Optional[str]
    checksum_sha256: Optional[str]
    created_by: str
    created_at: str
    updated_at: str


class ConflictDisclosureCreate(BaseModel):
    conflict_type: Literal[
        "Retrozession / Inducement", "Eigenhandel / Eigenbestand",
        "Konzernverbindung", "Persönliches Interesse Berater",
        "Sonstiger Interessenkonflikt"
    ]
    description: str
    inducement_provider: Optional[str] = None
    inducement_amount_rappen: Optional[int] = None
    inducement_frequency: Optional[str] = None
    mitigation_action: Optional[str] = None
    document_id: Optional[str] = None


class ConflictDisclosureResponse(BaseResponse):
    id: str
    mandate_id: str
    conflict_type: str
    description: str
    inducement_provider: Optional[str]
    inducement_amount_rappen: Optional[int]
    disclosed_to_client: int
    disclosed_at: Optional[str]
    client_acknowledged: int
    mitigation_action: Optional[str]
    disclosed_by: str
    created_at: str
    updated_at: str


class ProductCreate(BaseModel):
    isin: Optional[str] = None
    symbol: Optional[str] = None
    product_name: str
    provider: Optional[str] = None
    product_type: str
    asset_class: Literal["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"]
    sub_asset_class: Optional[str] = None
    currency: str = "CHF"
    ter_bps: Optional[int] = None
    sfdr_class: Optional[Literal["6", "8", "9"]] = None
    esg_rating: Optional[str] = None


class ProductResponse(BaseResponse):
    id: str
    isin: Optional[str]
    symbol: Optional[str]
    lookup_mode_override: Optional[str] = None
    lookup_symbol_override: Optional[str] = None
    figi: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    exchange_code: Optional[str] = None
    market_sector: Optional[str] = None
    security_type: Optional[str] = None
    security_type2: Optional[str] = None
    mapping_provider: Optional[str] = None
    mapping_resolved_at: Optional[str] = None
    reference_data_provider: Optional[str] = None
    reference_data_refreshed_at: Optional[str] = None
    product_name: str
    provider: Optional[str]
    product_type: str
    asset_class: str
    sub_asset_class: Optional[str]
    currency: str
    ter_bps: Optional[int]
    sfdr_class: Optional[str]
    esg_rating: Optional[str]
    is_active: int
    created_at: str
    updated_at: str


class ProductIdMappingPreviewRequest(BaseModel):
    product_id: Optional[str] = None
    isin: Optional[str] = None
    symbol: Optional[str] = None
    exchange_code: Optional[str] = None
    mic_code: Optional[str] = None
    currency: Optional[str] = None

    @model_validator(mode="after")
    def validate_basis(self):
        if not self.product_id and not self.isin and not self.symbol:
            raise ValueError("product_id oder ISIN/Symbol ist Pflicht")
        if self.exchange_code and self.mic_code:
            raise ValueError("exchange_code und mic_code koennen nicht gleichzeitig gesetzt werden")
        return self


class ProductMarketOverrideRequest(BaseModel):
    lookup_mode_override: Optional[Literal["direct", "proxy", "synthetic_par"]] = None
    lookup_symbol_override: Optional[str] = None


class ProductMarketOverrideResponse(BaseModel):
    id: str
    product_name: str
    lookup_mode_override: Optional[str] = None
    lookup_symbol_override: Optional[str] = None
    resolved_market_profile: dict[str, Any]


class ProductIdMappingCandidate(BaseModel):
    figi: Optional[str] = None
    ticker: Optional[str] = None
    name: Optional[str] = None
    exch_code: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    security_type: Optional[str] = None
    security_type2: Optional[str] = None
    market_sector: Optional[str] = None
    security_description: Optional[str] = None


class ProductIdMappingPreviewResponse(BaseModel):
    source: str
    api_key_used: bool
    request_job: dict
    resolved_from: dict
    warning: Optional[str] = None
    error: Optional[str] = None
    candidates: list[ProductIdMappingCandidate] = Field(default_factory=list)


class ProductIdMappingApplyRequest(BaseModel):
    product_id: str
    isin: Optional[str] = None
    symbol: Optional[str] = None
    exchange_code: Optional[str] = None
    mic_code: Optional[str] = None
    currency: Optional[str] = None
    candidate_index: int = 0
    preferred_figi: Optional[str] = None
    overwrite_symbol: bool = False

    @model_validator(mode="after")
    def validate_basis(self):
        if self.candidate_index < 0:
            raise ValueError("candidate_index darf nicht negativ sein")
        if self.exchange_code and self.mic_code:
            raise ValueError("exchange_code und mic_code koennen nicht gleichzeitig gesetzt werden")
        return self


class ProductIdMappingApplyResponse(BaseModel):
    product: ProductResponse
    applied: ProductIdMappingCandidate
    preview_warning: Optional[str] = None


class ProductIdMappingBatchApplyRequest(BaseModel):
    limit: int = 20
    overwrite_symbol: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_limit(self):
        if self.limit <= 0 or self.limit > 100:
            raise ValueError("limit muss zwischen 1 und 100 liegen")
        return self


class ProductIdMappingBatchItem(BaseModel):
    product_id: str
    product_name: str
    isin: Optional[str] = None
    status: str
    detail: Optional[str] = None
    applied_candidate: Optional[ProductIdMappingCandidate] = None


class ProductIdMappingBatchApplyResponse(BaseModel):
    processed: int
    applied: int
    skipped: int
    failed: int
    dry_run: bool
    items: list[ProductIdMappingBatchItem] = Field(default_factory=list)


class ProductReferencePreviewRequest(BaseModel):
    product_id: Optional[str] = None
    isin: Optional[str] = None
    symbol: Optional[str] = None
    product_name: Optional[str] = None
    exchange_code: Optional[str] = None
    currency: Optional[str] = None

    @model_validator(mode="after")
    def validate_basis(self):
        if not self.product_id and not self.isin and not self.symbol and not self.product_name:
            raise ValueError("product_id oder ISIN/Symbol/Produktname ist Pflicht")
        return self


class ProductReferenceCandidate(BaseModel):
    symbol: Optional[str] = None
    exchange_code: Optional[str] = None
    name: Optional[str] = None
    instrument_type: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    isin: Optional[str] = None
    match_score: int = 0


class ProductReferencePreviewResponse(BaseModel):
    source: str
    api_key_used: bool
    query_used: dict
    resolved_from: dict
    warning: Optional[str] = None
    candidates: list[ProductReferenceCandidate] = Field(default_factory=list)


class ProductReferenceApplyRequest(BaseModel):
    product_id: str
    isin: Optional[str] = None
    symbol: Optional[str] = None
    product_name: Optional[str] = None
    exchange_code: Optional[str] = None
    currency: Optional[str] = None
    candidate_index: int = 0
    overwrite_symbol: bool = False
    overwrite_name: bool = False
    overwrite_currency: bool = False

    @model_validator(mode="after")
    def validate_candidate_index(self):
        if self.candidate_index < 0:
            raise ValueError("candidate_index darf nicht negativ sein")
        return self


class ProductReferenceApplyResponse(BaseModel):
    product: ProductResponse
    applied: ProductReferenceCandidate
    preview_warning: Optional[str] = None


class ProductReferenceBatchApplyRequest(BaseModel):
    limit: int = 20
    overwrite_symbol: bool = False
    overwrite_name: bool = False
    overwrite_currency: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_limit(self):
        if self.limit <= 0 or self.limit > 100:
            raise ValueError("limit muss zwischen 1 und 100 liegen")
        return self


class ProductReferenceBatchItem(BaseModel):
    product_id: str
    product_name: str
    isin: Optional[str] = None
    symbol: Optional[str] = None
    status: str
    detail: Optional[str] = None
    applied_candidate: Optional[ProductReferenceCandidate] = None


class ProductReferenceBatchApplyResponse(BaseModel):
    processed: int
    applied: int
    skipped: int
    failed: int
    dry_run: bool
    items: list[ProductReferenceBatchItem] = Field(default_factory=list)


class RecommendationRunCreate(BaseModel):
    run_type: Literal["Initial", "Review", "WhatIf", "Optimizer"]
    assessment_id: Optional[str] = None
    target_allocation_id: Optional[str] = None
    policy_id: str
    capital_market_assumptions_id: Optional[str] = None
    objective_summary: Optional[str] = None
    weighting_regime: Optional[Literal["Equal-Weight", "Ranked-Weight", "Custom"]] = None
    fee_assumptions_json: Optional[str] = None
    other_assets_included: bool = False


class RecommendationRunResponse(BaseResponse):
    id: str
    mandate_id: str
    client_id: str
    run_type: str
    assessment_id: Optional[str]
    target_allocation_id: Optional[str]
    policy_id: str
    result_status: str
    weighting_regime: Optional[str]
    other_assets_included: int
    objective_summary: Optional[str]
    created_by: str
    created_at: str
    updated_at: str


class RecommendationPositionCreate(BaseModel):
    product_id: str
    target_weight_bps: int
    target_amount_rappen: Optional[int] = None
    rationale: Optional[str] = None


class RecommendationPositionResponse(BaseResponse):
    id: str
    run_id: str
    product_id: str
    target_weight_bps: int
    target_amount_rappen: Optional[int]
    rationale: Optional[str]
    created_at: str
    updated_at: str


class RecommendationHoldingUpsert(BaseModel):
    depot_bank: Optional[str] = None
    custody_account_number: Optional[str] = None
    as_of_date: Optional[str] = None
    units_milli: Optional[int] = None
    market_value_rappen: Optional[int] = None
    avg_cost_price_rappen: Optional[int] = None
    source: Literal["manual", "custody_import"] = "manual"
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_basis(self):
        has_units = self.units_milli is not None and int(self.units_milli) > 0
        has_value = self.market_value_rappen is not None and int(self.market_value_rappen) > 0
        if not has_units and not has_value:
            raise ValueError("Holding benoetigt units_milli oder market_value_rappen")
        if self.units_milli is not None and int(self.units_milli) < 0:
            raise ValueError("units_milli darf nicht negativ sein")
        if self.market_value_rappen is not None and int(self.market_value_rappen) < 0:
            raise ValueError("market_value_rappen darf nicht negativ sein")
        if self.avg_cost_price_rappen is not None and int(self.avg_cost_price_rappen) < 0:
            raise ValueError("avg_cost_price_rappen darf nicht negativ sein")
        return self


class RecommendationHoldingResponse(BaseResponse):
    id: str
    run_id: str
    recommendation_position_id: str
    product_id: str
    depot_bank: Optional[str]
    custody_account_number: Optional[str]
    as_of_date: Optional[str]
    units_milli: Optional[int]
    market_value_rappen: Optional[int]
    avg_cost_price_rappen: Optional[int]
    source: str
    notes: Optional[str]
    created_at: str
    updated_at: str


class RecommendationGenerateRequest(BaseModel):
    run_type: Literal["Initial", "Review", "WhatIf", "Optimizer"] = "Optimizer"
    target_allocation_id: Optional[str] = None
    depot_bank: Optional[str] = None
    preferences: Optional[AllocationPreferencesPayload] = None


class RecommendationPositionDetailResponse(BaseModel):
    id: str
    run_id: str
    product_id: str
    product_name: str
    provider: Optional[str]
    isin: Optional[str]
    symbol: Optional[str]
    figi: Optional[str] = None
    exchange_code: Optional[str] = None
    mapping_provider: Optional[str] = None
    mapping_resolved_at: Optional[str] = None
    reference_data_provider: Optional[str] = None
    reference_data_refreshed_at: Optional[str] = None
    lookup_symbol: Optional[str] = None
    lookup_mode: Optional[str] = None
    pricing_note: Optional[str] = None
    product_type: str
    asset_class: str
    sub_asset_class: Optional[str]
    currency: str
    ter_bps: Optional[int]
    target_weight_bps: int
    target_amount_rappen: Optional[int]
    rationale: Optional[str]
    source_sub_asset_classes: list[str] = []
    reference_price_date: Optional[str] = None
    reference_price_rappen: Optional[int] = None
    reference_recalibrated: Optional[bool] = None
    latest_price_date: Optional[str] = None
    latest_price_rappen: Optional[int] = None
    price_source: Optional[str] = None
    price_age_days: Optional[int] = None
    price_is_fresh: Optional[bool] = None
    holding_present: bool = False
    holding_source: Optional[str] = None
    holding_as_of_date: Optional[str] = None
    holding_units_milli: Optional[int] = None
    current_units_milli: Optional[int] = None
    holding_market_value_rappen: Optional[int] = None
    holding_avg_cost_price_rappen: Optional[int] = None
    holding_depot_bank: Optional[str] = None
    holding_custody_account_number: Optional[str] = None
    holding_notes: Optional[str] = None
    valuation_basis: Optional[str] = None
    implied_units_milli: Optional[int] = None
    current_market_value_rappen: Optional[int] = None
    current_weight_bps: Optional[int] = None
    delta_weight_bps: Optional[int] = None
    rebalance_amount_rappen: Optional[int] = None
    price_change_bps: Optional[int] = None
    rebalance_action: Optional[str] = None


class RecommendationGenerateResponse(BaseModel):
    run: RecommendationRunResponse
    positions: list[RecommendationPositionDetailResponse]
    warnings: list[str]
    implementation_steps: list[str]
    advisory_wealth_rappen: int
    expected_return_bps: int
    expected_volatility_bps: int
    average_ter_bps: int
    target_allocation_id: str
    market_data_quality: dict = Field(default_factory=dict)
    live_rebalancing: Optional[LiveRebalancingResponse] = None
