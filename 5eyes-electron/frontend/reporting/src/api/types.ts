/**
 * TypeScript-Typen für das Advisory-Report Schema v2.
 *
 * Spiegelt 1:1 die Datenstruktur aus
 * `5eyes-backend/services/advisory_report.py::compute_advisory_report`
 * (Sprint U-P21). Schema-Version wird über `schema_version` verifiziert.
 *
 * Bei Schema-Änderungen im Backend: hier nachziehen + Schema-Version
 * hochsetzen. Tests verhindern stilles Drift via Top-Level-Key-Vergleich.
 */

// ---------------------------------------------------------------------------
// Gemeinsame Bausteine
// ---------------------------------------------------------------------------

/** Allokations-Bucket-Identifier (5 institutionelle Anlageklassen). */
export type BucketKey =
  | 'liquidity'
  | 'bonds'
  | 'equities'
  | 'real_estate'
  | 'alternatives';

/** Verdict-Status für Erkenntnisse-Ampel. */
export type AmpelStatus = 'gruen' | 'gelb' | 'rot' | 'nicht_beurteilbar';

/** Hardness-Kategorisierung gemäss Stochastic-Optimizer-Spec. */
export type GoalHardness = 'Hart' | 'Primaer' | 'Opportunistisch' | '';

/** Status der Zielerreichung. */
export type GoalStatus =
  | 'erreichbar'
  | 'knapp'
  | 'nicht_erreichbar'
  | 'data_pending'
  | '';

// ---------------------------------------------------------------------------
// Sektion 1 — Cover
// ---------------------------------------------------------------------------

export interface CoverData {
  title: string;
  subtitle: string;
  client_name: string;
  mandate_number: string;
  /** ISO-Datum YYYY-MM-DD */
  report_date: string;
  advisor_name: string;
}

// ---------------------------------------------------------------------------
// Sektion 2 — Disclaimer
// ---------------------------------------------------------------------------

export interface DisclaimerData {
  hinweise: string[];
}

// ---------------------------------------------------------------------------
// Sektion 3 — Inhaltsverzeichnis
// ---------------------------------------------------------------------------

export interface Kapitel {
  nr: number;
  title: string;
}

export interface InhaltsverzeichnisData {
  kapitel: Kapitel[];
}

// ---------------------------------------------------------------------------
// Sektion 4 — Ausgangslage
// ---------------------------------------------------------------------------

export interface ClientInfo {
  alter: number;
  anlagehorizont_jahre: number;
  risikoprofil: string;
  anlageziel: string;
  liquiditaetsbedarf_rappen: number;
  steuerdomizil: string;
  referenzwaehrung: string;
}

export interface CashflowEntry {
  label: string;
  type: string;
  amount_rappen: number;
  frequency: string;
}

export interface ZielEntry {
  label: string;
  goal_type: string;
  target_amount_rappen: number;
  target_date: string;
  hardness: GoalHardness;
}

export interface WealthSummary {
  gesamtvermoegen_rappen: number;
  beratungsvermoegen_rappen: number;
  immobilien_rappen: number;
  vorsorge_rappen: number;
  kredite_rappen: number;
  cashflows: CashflowEntry[];
  ziele: ZielEntry[];
}

export interface KeyMetrics {
  risky_fraction_bps: number | null;
  zielerreichung_bps: number | null;
  exp_vol_bps: number | null;
  exp_return_bps: number | null;
  max_drawdown_bps: number | null;
  var_95_bps: number | null;
}

export interface AusgangslageData {
  client_info: ClientInfo;
  wealth_summary: WealthSummary;
  key_metrics: KeyMetrics;
}

// ---------------------------------------------------------------------------
// Sektion 5 — Positionen
// ---------------------------------------------------------------------------

export interface PositionEntry {
  isin: string;
  product_name: string;
  product_type: string;
  sub_asset_class: string;
  currency: string;
  market_value_rappen: number;
  ter_bps: number | null;
  provider: string;
  share_bps: number;
}

export interface PositionGroup {
  key: BucketKey;
  label: string;
  positions: PositionEntry[];
  total_rappen: number;
  share_bps: number;
}

export interface PositionenData {
  groups: PositionGroup[];
  total_rappen: number;
  has_recommendation_run: boolean;
  hinweis: string;
}

// ---------------------------------------------------------------------------
// Sektion 6 — Was wir prüfen
// ---------------------------------------------------------------------------

export interface PruefBlock {
  key: string;
  title: string;
  beschreibung: string;
}

export interface PruefpunkteData {
  bloecke: PruefBlock[];
}

// ---------------------------------------------------------------------------
// Sektion 7 — Erkenntnisse (Ampel)
// ---------------------------------------------------------------------------

export interface ErkenntnisCheck {
  pruefpunkt: string;
  bewertung: AmpelStatus;
  beurteilung: string;
  handlungsempfehlung: string;
}

export interface ErkenntnisseData {
  checks: ErkenntnisCheck[];
}

// ---------------------------------------------------------------------------
// Sektion 8 — Asset Allocation
// ---------------------------------------------------------------------------

export interface AssetAllocationItem {
  key: BucketKey;
  label: string;
  ist_bps: number;
  soll_bps: number;
  drift_bps: number;
  band_min_bps: number;
  band_max_bps: number;
  in_band: boolean | null;
}

export interface AssetAllocationData {
  items: AssetAllocationItem[];
  ist_bps: Record<string, number>;
  soll_bps: Record<string, number>;
  drift_bps: Record<string, number>;
  ist_basiert_auf_soll: boolean;
  anmerkungen: string;
}

// ---------------------------------------------------------------------------
// Sektion 9 — Risikowährungen
// ---------------------------------------------------------------------------

export interface CurrencyItem {
  label: string;
  ist_bps: number;
  soll_bps: number;
  drift_bps: number;
}

export interface RisikowaehrungenData {
  items: CurrencyItem[];
  ist_bps: Record<string, number>;
  soll_bps: Record<string, number>;
  drift_bps: Record<string, number>;
  ist_basiert_auf_soll: boolean;
  erklaerung: string;
}

// ---------------------------------------------------------------------------
// Sektion 10 — Branchen
// ---------------------------------------------------------------------------

export interface SectorItem {
  label: string;
  ist_bps: number;
  soll_bps: number;
  drift_bps: number;
}

export interface BranchenData {
  items: SectorItem[];
  ist_bps: Record<string, number>;
  soll_bps: Record<string, number>;
  drift_bps: Record<string, number>;
  anteil_aktien_bps: number;
  hinweis: string;
  ist_basiert_auf_soll: boolean;
  analyse: string;
}

// ---------------------------------------------------------------------------
// Sektion 11 — Goal-Based Investing
// ---------------------------------------------------------------------------

export interface GoalEntry {
  goal_id: string;
  label: string;
  goal_type: string;
  target_amount_rappen: number;
  target_date: string;
  hardness: GoalHardness;
  /** Wahrscheinlichkeit in bps (8500 = 85%) */
  probability_bps: number | null;
  status: GoalStatus;
}

export interface MonteCarloPaths {
  data_pending: boolean;
  note?: string;
  /**
   * Zeitliche Pfade p5/p50/p75 in Rappen. Befuellt ab U-11 (PR #111)
   * via services.monte_carlo_paths. Bei data_pending=true bleiben sie []
   * (Sub-App rendert dann Empty-State statt Chart).
   */
  p5?: number[];
  p50?: number[];
  p75?: number[];
  /** ISO-Jahresstrings, Laenge = horizon_years + 1, gleich-laenge wie pX. */
  time_axis?: string[];
  /** U-11 metadata fuer Audit / Reproduktion. */
  n_paths?: number;
  seed?: number | null;
  horizon_years?: number;
  initial_wealth_rappen?: number;
}

export interface GoalBasedInvestingData {
  goals: GoalEntry[];
  /** Gewichteter Achievement-Score in bps (10000 = 100%) */
  goal_achievement_score_bps: number;
  monte_carlo_paths: MonteCarloPaths;
}

// ---------------------------------------------------------------------------
// Sektion 12 — Risikoprofilierung
// ---------------------------------------------------------------------------

export interface RiskQuestion {
  key: string;
  frage: string;
  points: number | null;
}

export interface RisikoprofilierungData {
  risky_fraction_bps: number | null;
  risk_capacity_score_x10: number | null;
  risk_willingness_score_x10: number | null;
  final_score_x10: number | null;
  final_profile: string;
  is_overridden: boolean;
  override_reason: string | null;
  questions: RiskQuestion[];
}

// ---------------------------------------------------------------------------
// Sektion 13 — Building Blocks / iSAA
// ---------------------------------------------------------------------------

export interface BuildingBlock {
  key: BucketKey;
  label: string;
  target_bps: number;
  band_min_bps: number;
  band_max_bps: number;
}

export interface BuildingBlockConstraint {
  key: string;
  label: string;
  value_bps: number;
  beschreibung: string;
}

export interface BuildingBlocksData {
  blocks: BuildingBlock[];
  constraints: BuildingBlockConstraint[];
  methodologie: string;
}

// ---------------------------------------------------------------------------
// Sektion 14 — Statement aus dem Portfoliomanagement
// ---------------------------------------------------------------------------

export interface InvestmentPrinciple {
  key: string;
  title: string;
  body: string;
}

export interface StatementPmData {
  principles: InvestmentPrinciple[];
}

// ---------------------------------------------------------------------------
// Sektion 15 — Weiteres Vorgehen
// ---------------------------------------------------------------------------

export interface WeiteresVorgehenData {
  block_optimierungen: string;
  block_zielstrategie: string;
  offene_fragen: string[];
  naechster_termin: string | null;
  todos: string[];
  dokumente: string[];
}

// ---------------------------------------------------------------------------
// Top-Level Schema
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Sektion 16 — Beratungsprotokoll (U-FINMA-2.2)
// ---------------------------------------------------------------------------

export interface BeratungsprotokollEntry {
  id: string;
  entry_type: string;
  title: string;
  description: string | null;
  decision: string | null;
  status: string;
  entry_datetime: string | null;
  duration_minutes: number | null;
  communication_channel: string | null;
  language: string | null;
  location: string | null;
  participants: Array<{ role: string; name: string; note?: string }>;
  topics: string[];
  risk_warnings_given: string[];
  cost_disclosure_given: number;
  conflict_disclosure_ids: string[];
  suitability_check_id: string | null;
  integrity_hash: string | null;
  retain_until: string | null;
  version: number;
  supersedes_id: string | null;
  superseded_by_id: string | null;
  last_read_at: string | null;
  last_read_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface BeratungsprotokollData {
  total_active: number;
  latest_entry: BeratungsprotokollEntry | null;
  last_review_date: string | null;
  days_since_last_review: number | null;
  suitability_mismatches: string[];
  has_active_mismatches: boolean;
  retention_audit_ok: boolean;
}

// ---------------------------------------------------------------------------
// Sektion 17 — Historische Stress-Szenarien (U-70)
// ---------------------------------------------------------------------------

export interface StressReplayScenario {
  id: string;
  label: string;
  period: string;
  cumulative_return_bps: number;
  max_drawdown_bps: number;
  recovery_months: number | null;
  annual_breakdown: unknown[];
}

export interface StressReplayData {
  data_pending: boolean;
  note: string;
  weights_bps: Record<string, number>;
  scenarios: StressReplayScenario[];
}

// ---------------------------------------------------------------------------
// Sektion 18 - Interessenkonflikt-Offenlegungen (U-68)
// ---------------------------------------------------------------------------

export interface ConflictDisclosureEntry {
  id: string | null;
  conflict_type: string;
  description: string;
  inducement_provider: string | null;
  inducement_amount_rappen: number | null;
  inducement_frequency: string | null;
  disclosed_to_client: boolean;
  disclosed_at: string | null;
  client_acknowledged: boolean;
  client_acknowledged_at: string | null;
  mitigation_action: string | null;
  document_id: string | null;
}

export interface ConflictDisclosuresData {
  entries: ConflictDisclosureEntry[];
  counts: {
    total: number;
    by_type: Record<string, number>;
  };
  has_unacknowledged: boolean;
  fidleg_basis: string;
}

// ---------------------------------------------------------------------------
// Sektion 26 — A/B-HouseMatrix-Backtest (U-71, re-architektiert 2026-06-09)
// ---------------------------------------------------------------------------

export interface AbPolicySummary {
  policy_id: string;
  policy_name: string;
  version: number;
  is_current: boolean;
  profile_name?: string;
  max_risky_fraction_bps?: number;
  weights_bps?: Record<string, number>;
  expected_return_bps?: number;
  expected_volatility_bps?: number;
  expected_ter_bps?: number;
  sharpe_ratio_x100?: number;
}

export interface AbBucketDiff {
  key: string;
  label: string;
  a_bps: number;
  b_bps: number;
  delta_bps: number;
}

export interface AbStressDiff {
  id: string;
  label: string;
  period: string;
  a_cumulative_return_bps: number;
  b_cumulative_return_bps: number;
  delta_cumulative_return_bps: number;
  a_max_drawdown_bps: number;
  b_max_drawdown_bps: number;
  delta_max_drawdown_bps: number;
  a_recovery_months: number;
  b_recovery_months: number;
}

export interface AbBacktestData {
  data_pending: boolean;
  note: string;
  score_bucket?: number;
  cma_id?: string;
  cma_version?: number;
  policy_a: AbPolicySummary | null;
  policy_b: AbPolicySummary | null;
  buckets_diff: AbBucketDiff[];
  risk_metrics_diff: Record<string, number>;
  stress_diff: AbStressDiff[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Sektion 27 — Suitability-Summary (U-FINMA-3, re-architektiert 2026-06-09)
// ---------------------------------------------------------------------------

/** SuitabilityCheck-Result aus models/profiling.py::SuitabilityCheck.result. */
export type SuitabilityResult =
  | 'passed'
  | 'mismatch'
  | 'incomplete'
  | string;

/** Pflichttyp gemaess FIDLEG. */
export type SuitabilityDutyType =
  | 'suitability'
  | 'appropriateness'
  | 'informational'
  | 'execution_only'
  | string;

export interface SuitabilityReferences {
  risk_assessment_id: string | null;
  knowledge_assessment_id: string | null;
  advisory_log_id: string | null;
  recommendation_run_id: string | null;
  document_id: string | null;
}

export interface SuitabilitySummaryData {
  has_check: boolean;
  check_id: string | null;
  performed_at: string | null;
  duty_type: SuitabilityDutyType | null;
  result: SuitabilityResult | null;
  result_notes: string | null;
  missing_information: string[];
  client_proceeded_despite: boolean;
  warning_delivered: boolean;
  warning_delivered_at: string | null;
  client_acknowledged: boolean;
  client_acknowledged_at: string | null;
  references: SuitabilityReferences;
  checked_by_id: string | null;
  checked_by_name: string;
  linked_log_present: boolean;
}

// ---------------------------------------------------------------------------
// Top-Level Schema
// ---------------------------------------------------------------------------

export interface AdvisoryReport {
  schema_version: 2;
  mandate_id: string;
  /** ISO-Timestamp YYYY-MM-DDTHH:MM:SS.SSSZ */
  generated_at: string;
  cover: CoverData;
  disclaimer: DisclaimerData;
  inhaltsverzeichnis: InhaltsverzeichnisData;
  ausgangslage: AusgangslageData;
  positionen: PositionenData;
  pruefpunkte: PruefpunkteData;
  erkenntnisse: ErkenntnisseData;
  asset_allocation: AssetAllocationData;
  risikowaehrungen: RisikowaehrungenData;
  branchen: BranchenData;
  goal_based_investing: GoalBasedInvestingData;
  risikoprofilierung: RisikoprofilierungData;
  building_blocks: BuildingBlocksData;
  statement_pm: StatementPmData;
  weiteres_vorgehen: WeiteresVorgehenData;
  /** U-FINMA-2.2: FINMA-konforme Beratungsprotokoll-Übersicht */
  beratungsprotokoll: BeratungsprotokollData;
  /** U-70: Historische Stress-Szenarien auf aktueller Zielallokation */
  stress_replay: StressReplayData;
  /** U-68: FIDLEG Interessenkonflikt-Offenlegungen */
  conflict_disclosures: ConflictDisclosuresData;
  /** U-66: FIDLEG-Suitability-Compliance-Audit */
  suitability_compliance: SuitabilityComplianceData;
  /** U-73+U-74: Engine-Modell-Audit */
  methodology_models: MethodologyModelsData;
  /** U-69: Recommendation-Methodology-Audit */
  recommendation_methodology: RecommendationMethodologyData;
  /** U-22: Mandate-Lock-Status */
  mandate_lock_status: MandateLockStatusData;
  /** U-21: Liquidity-Cascade Stage-3 Warning */
  liquidity_cascade: LiquidityCascadeData;
  /** U-94: Optimizer-Run-History */
  optimizer_run_history: OptimizerRunHistoryData;
  /** U-97: Performance-Attribution */
  performance_attribution: PerformanceAttributionData;
  /** C2-Wiring: Engine-Configuration-Audit */
  engine_configuration: EngineConfigurationData;
  /** U-71 (re-architektiert 2026-06-09): A/B-HouseMatrix-Policy-Vergleich */
  ab_backtest: AbBacktestData;
  /** U-FINMA-3 (re-architektiert 2026-06-09): SuitabilityCheck per Mandat */
  suitability_summary: SuitabilitySummaryData;
}

/** C2-Wiring (2026-06-07): Stub-Type fuer engine_configuration.
 * Vollstaendige Struktur kommt mit naechstem Engine-Audit-Sprint —
 * Drift-Test verlangt nur den Top-Level-Key. */
export type EngineConfigurationData = Record<string, unknown>;

// Sprint U-66/U-73+74/U-69/U-22/U-21 (2026-06-04, konsolidiert):
// Aggregator-Sektionen 19-23. Stub-Type-Aliases damit der Drift-
// Konsistenz-Test (tests/test_reporting_api_and_cover.py) passiert.
// Vollständige Interface-Definitionen folgen im Sub-App-Render-Sprint.
export type SuitabilityComplianceData = {
  total_advisory_logs: number;
  logs_requiring_suitability: number;
  logs_with_suitability: number;
  logs_without_suitability: Array<Record<string, unknown>>;
  freshness_issues: Array<Record<string, unknown>>;
  result_issues: Array<Record<string, unknown>>;
  is_compliant: boolean;
  fidleg_basis: string;
};

export type MethodologyModelsData = {
  cma_id: string | null;
  cma_version: number | null;
  models: Array<Record<string, unknown>>;
  active_count: number;
  methodology_notes: string[];
};

export type RecommendationMethodologyData = {
  latest_run: Record<string, unknown> | null;
  latest_active_run: Record<string, unknown> | null;
  total_runs: number;
  shadow_count: number;
  active_count: number;
  fallback_count: number;
  is_compliant: boolean;
  fidleg_basis: string;
};

export type MandateLockStatusData = {
  is_editable: boolean;
  lock_reasons: string[];
  lock_reason_labels: Record<string, string>;
  mandate_status: string | null;
  latest_optimizer_status: string | null;
  fidleg_basis: string;
};

export type LiquidityCascadeData = {
  stage: 'normal' | 'hard_cap' | 'emergency' | 'unknown';
  stage_label: string;
  liquidity_bps: number | null;
  hard_cap_bps: number;
  emergency_cap_bps: number;
  over_hard_cap_by_bps: number | null;
  warning_required: boolean;
  beratungsgespraech_pruefen: boolean;
  fidleg_basis: string;
};

// Sprint U-94 (2026-06-05): Optimizer-Run-History — Audit-Trace der letzten
// Solver-Laeufe pro Mandat fuer FIDLEG Art. 9/14 Nachvollziehbarkeit.
export type OptimizerRunHistoryItem = {
  id: string;
  /** ISO-Timestamp YYYY-MM-DDTHH:MM:SS.SSSZ */
  run_at: string;
  optimizer_mode: string;
  role: string;
  method: string;
  status: string;
  seed: number;
  n_iterations: number;
  n_paths: number;
  objective_value_milli: number | null;
  target_allocation_id: string | null;
};

export type OptimizerRunHistoryData = {
  items: OptimizerRunHistoryItem[];
  limit: number;
  total_persisted: number;
  fidleg_basis: string;
  error?: string;
};

// Sprint U-97 (2026-06-06): Performance-Attribution — Brinson-Decomposition
// der erwarteten Excess-Return vs House-Matrix-Default-Benchmark.
export type AttributionBucket = {
  bucket: string;
  weight_portfolio_bps: number;
  weight_benchmark_bps: number;
  return_portfolio_bps: number;
  return_benchmark_bps: number;
  allocation_effect_bps: number;
  selection_effect_bps: number;
  interaction_effect_bps: number;
};

export type PerformanceAttributionData = {
  buckets: AttributionBucket[];
  total_portfolio_return_bps: number;
  total_benchmark_return_bps: number;
  total_excess_return_bps: number;
  total_allocation_effect_bps: number;
  total_selection_effect_bps: number;
  total_interaction_effect_bps: number;
  method: string;
  benchmark_source: string;
  fidleg_basis: string;
  error?: string;
};

// ---------------------------------------------------------------------------
// Goal-Editor (Track #64, FE-React-Migration) — Mutations-Schema.
//
// Spiegelt 1:1 die Pydantic-Modelle in `5eyes-backend/schemas/wealth.py`:
//   GoalCreate (410-438), GoalUpdate (453-476), GoalResponse (485-514),
//   MaxPensionSpendingRequest (230-240), MaxPensionSpendingResponse (243-256).
//
// WICHTIG: NICHT mit `GoalEntry` (Sektion 11, Read-Model des Advisory-Reports)
// verwechseln — `GoalRecord` ist das vollständige CRUD-Modell des Editors.
// `is_ongoing` und `is_active` liefert das Backend als int (0/1), NICHT boolean.
// ---------------------------------------------------------------------------

export type GoalFamily = 'Vermögen' | 'Cashflow' | 'Rendite' | 'Maximierung';

export type GoalType =
  | 'Kapitalerhalt'
  | 'Vermögensziel'
  | 'Vermoegensziel'
  | 'Einmalige_Ausgabe'
  | 'Wiederkehrende_Ausgabe'
  | 'Pensionsausgabe'
  | 'Renditeziel'
  | 'Maximierung';

export type GoalScope = 'Beratungsvermögen' | 'Gesamtvermögen';
export type GoalValueMode = 'nominal' | 'real';
export type PensionPillar = 'AHV' | 'BVG' | '3a' | '1e' | 'FZG';

/** UI-Auswahlwerte für Härtegrad. Backend normalisiert ä→ae; Default "Primär". */
export type GoalHardnessInput = 'Hart' | 'Primär' | 'Opportunistisch';

export interface GoalCreatePayload {
  goal_family: GoalFamily;
  goal_type: GoalType;
  label: string;
  rank: number;
  weight_bps?: number | null;
  goal_scope?: GoalScope;
  value_mode?: GoalValueMode;
  target_amount_rappen?: number | null;
  target_wealth_rappen?: number | null;
  target_return_bps?: number | null;
  success_probability_min_x100?: number | null;
  start_date?: string | null;
  horizon_years?: number | null;
  target_date?: string | null;
  is_ongoing?: boolean;
  frequency?: string | null;
  hardness?: string;
  probability_pct?: number;
  pension_pillar?: PensionPillar | null;
  linked_position_id?: string | null;
  notes?: string | null;
  /** Berater-App sendet implizit "synthetic"; NICHT im Edit-UI erfassen. */
  data_classification?: 'synthetic' | 'real';
}

/** Partial-Update (Backend `exclude_unset=True`) + reaktivierbares `is_active`. */
export type GoalUpdatePayload = Partial<GoalCreatePayload> & {
  is_active?: boolean;
};

export interface GoalRecord {
  id: string;
  mandate_id: string;
  client_id: string;
  goal_family: string;
  goal_type: string;
  label: string;
  rank: number;
  weight_bps: number | null;
  goal_scope: string;
  value_mode: string;
  target_amount_rappen: number | null;
  target_wealth_rappen: number | null;
  target_return_bps: number | null;
  success_probability_min_x100: number | null;
  start_date: string | null;
  horizon_years: number | null;
  target_date: string | null;
  /** int 0/1 (kein boolean). */
  is_ongoing: number;
  frequency: string | null;
  hardness: string;
  probability_pct: number | null;
  pension_pillar: string | null;
  linked_position_id: string | null;
  notes: string | null;
  /** int 0/1 (kein boolean). */
  is_active: number;
  achievement_score: number | null;
  last_scored_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MaxPensionSpendingRequest {
  retirement_year: number;
  life_expectancy_year: number;
  /** Default im Backend "real" (konservativer/tieferer Wert). */
  value_mode?: GoalValueMode;
  safety_margin_pct?: number;
}

export interface MaxPensionSpendingResponse {
  max_monthly_chf_rappen: number;
  max_annual_chf_rappen: number;
  retirement_year: number;
  life_expectancy_year: number;
  years_in_retirement: number;
  value_mode: string;
  expected_return_bps: number;
  expected_volatility_bps: number;
  real_return_bps: number;
  inflation_bps: number;
  advisory_wealth_rappen: number;
  safety_margin_pct: number;
  reasoning: string[];
}

// ---------------------------------------------------------------------------
// Asset-Allocation-Editor (Track #67, FE-React-Migration).
// Spiegelt schemas/allocation.py: TargetAllocationCreate (6-24),
// TargetAllocationResponse (51-100), Sensitivity (417/439).
// ---------------------------------------------------------------------------

export type AllocationBucketKey =
  | 'equities'
  | 'bonds'
  | 'real_estate'
  | 'alternatives'
  | 'liquidity';

/** POST-Body /mandates/{id}/target-allocation (TargetAllocationCreate). */
export interface TargetAllocationCreatePayload {
  target_equities_bps: number;
  target_bonds_bps: number;
  target_real_estate_bps: number;
  target_alternatives_bps: number;
  target_liquidity_bps: number;
  band_equities_min_bps: number;
  band_equities_max_bps: number;
  band_bonds_min_bps: number;
  band_bonds_max_bps: number;
  band_real_estate_min_bps: number;
  band_real_estate_max_bps: number;
  band_alternatives_min_bps: number;
  band_alternatives_max_bps: number;
  band_liquidity_min_bps: number;
  band_liquidity_max_bps: number;
  risky_fraction_bps?: number | null;
  based_on_assessment_id?: string | null;
  policy_id: string;
}

/** Response-Kernfelder (TargetAllocationResponse hat zusätzliche Audit-Felder). */
export interface TargetAllocationRecord extends TargetAllocationCreatePayload {
  id: string;
  mandate_id: string;
  version: number;
  is_current: number;
  set_by: string;
  set_at: string;
  created_at: string;
  updated_at: string;
}

/** Minimal getypte Teilmenge von TargetAllocationGenerateResponse. */
export interface AllocationGenerateResult {
  target_allocation: TargetAllocationRecord;
  expected_return_bps: number;
  expected_volatility_bps: number;
  risky_fraction_total_bps: number;
  limiting_factor: string | null;
  reasoning: string[];
  messages: Array<Record<string, unknown>>;
}

export interface AllocationSensitivityRequestPayload {
  goal_id: string;
  target_delta_pct: number;
  horizon_delta_years?: number;
}

export interface AllocationSensitivityResult {
  goal_id: string;
  delta_pct: number;
  horizon_delta_years: number;
  target_amount_rappen_baseline: number;
  target_amount_rappen_new: number;
  objective_value_milli_baseline: number | null;
  objective_value_milli_new: number | null;
  delta_objective_pct: number | null;
  weights_bps_baseline: Record<string, number>;
  weights_bps_new: Record<string, number>;
  status_baseline: string;
  status_new: string;
}
