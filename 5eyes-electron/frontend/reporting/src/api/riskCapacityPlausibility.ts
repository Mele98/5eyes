/**
 * RISK-CAPACITY-REPORT-001: Plausibilitaetspruefung der Risikofaehigkeit,
 * kompakter Auszug im Advisory-Report-Payload. Reiner Hinweis-Layer: die
 * Pruefung aendert das Risikoprofil nie und blockiert nichts.
 */

export type RiskCapacityPlausibilityStatus =
  | 'consistent'
  | 'partial'
  | 'inconsistent'
  | 'not_evaluable';

/**
 * Betragsfreier Auszug im Advisory-Report-Payload
 * (`suitability_summary.risk_capacity_plausibility`).
 */
export interface RiskCapacityPlausibilityCompact {
  status: RiskCapacityPlausibilityStatus;
  reason_code: string | null;
  finding_checks: string[];
  open_checks: string[];
  verification_code?: string | null;
  /** Neutraler Beraterhinweis (nur partial/inconsistent), sonst leer. */
  note: string;
  /** Bewertetes Risikoprofil; null ohne aktuelles Profil. */
  risk_assessment_id?: string | null;
  /** evaluated | missing_input | unavailable | integrity_mismatch */
  availability?: RiskCapacityAvailability;
  evaluation_basis?: string;
  rules_version?: string | null;
  evaluation_hash?: string | null;
  /** true/false = gleiches/anderes Profil als die Suitability-Referenz. */
  suitability_reference_match?: boolean | null;
}

export type RiskCapacityAvailability =
  | 'evaluated'
  | 'missing_input'
  | 'unavailable'
  | 'integrity_mismatch';

/** Kurzlabels je Pruef-ID (gespiegelt aus CHECK_SHORT_LABELS im Backend). */
export const RISK_CAPACITY_CHECK_LABELS: Record<string, string> = {
  INCOME_ABOVE_RECORDED: 'Frage 3 Einkommen',
  OBLIGATIONS_BELOW_RECORDED: 'Frage 5 Verpflichtungen',
  FREE_WEALTH_ABOVE_RECORDED: 'Frage 6 freies Vermögen',
  SAVINGS_RATE_ABOVE_RECORDED: 'Frage 7 Sparquote',
  LEVERAGE_HIGH: 'Verschuldung',
  NEAR_TERM_GOALS_HIGH: 'Nahziele',
  ALL: 'Gesamtprüfung',
};

export function riskCapacityCheckLabel(check: string): string {
  return RISK_CAPACITY_CHECK_LABELS[check] ?? check;
}
