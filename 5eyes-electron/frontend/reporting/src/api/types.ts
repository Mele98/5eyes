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
  /** Optional, wird in U-P24+ befüllt mit zeitlichen Pfaden p5/p50/p75 */
  p5?: number[];
  p50?: number[];
  p75?: number[];
  time_axis?: string[];
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
}
