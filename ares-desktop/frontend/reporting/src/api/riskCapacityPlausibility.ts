/**
 * RISK-CAPACITY-REPORT-001: Plausibilitaetspruefung der Risikofaehigkeit
 * (GET /mandates/{id}/risk-capacity-plausibility).
 *
 * Reiner Hinweis-Layer: die Pruefung aendert das Risikoprofil nie und
 * blockiert nichts. Stabile Schnittstelle: `status`, `reason_code`,
 * `findings[].check`, `not_evaluable[].check`. Spaetere Felder
 * (`verification_code`, `resolution_actions`) sind optional.
 *
 * Fail-closed: ein unbekannter oder fehlender Status wird als
 * `not_evaluable` behandelt -- nie still als `consistent`.
 */
import { ApiError, apiErrorFromResponse, resolveAuthToken } from './client';

export type RiskCapacityPlausibilityStatus =
  | 'consistent'
  | 'partial'
  | 'inconsistent'
  | 'not_evaluable';

export const RISK_CAPACITY_PLAUSIBILITY_STATUSES: readonly RiskCapacityPlausibilityStatus[] = [
  'consistent',
  'partial',
  'inconsistent',
  'not_evaluable',
];

export interface RiskCapacityPlausibilityFinding {
  check: string;
  question_number: number | null;
  message: string;
}

export interface RiskCapacityPlausibilityOpenCheck {
  check: string;
  question_number: number | null;
  reason: string;
}

export interface RiskCapacityPlausibility {
  status: RiskCapacityPlausibilityStatus;
  reason_code: string | null;
  findings: RiskCapacityPlausibilityFinding[];
  not_evaluable: RiskCapacityPlausibilityOpenCheck[];
  advisor_text: string;
  override_down: boolean;
  capacity_binding: boolean | null;
  version: string | null;
  /** Bewertetes Risikoprofil (Bindung, Closure-Review PR #677). */
  risk_assessment_id: string | null;
  /** Optional (Coverage-Attestation, PR #664): Code fuer "noch nicht verifiziert". */
  verification_code?: string | null;
  /** Optional (Coverage-Attestation, PR #664): naechste Schritte fuer den Berater. */
  resolution_actions?: string[];
}

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

/**
 * Bindung (Closure-Review PR #677): ein gepruefter Status gilt nur, wenn er
 * das erwartete Risikoprofil nennt. `not_evaluable` ist nie positiv und darf
 * ohne Bindung angezeigt werden.
 */
export function isBoundToAssessment(
  result: Pick<RiskCapacityPlausibility, 'status' | 'risk_assessment_id'>,
  expectedAssessmentId: string,
): boolean {
  if (result.status === 'not_evaluable') {
    return result.risk_assessment_id == null || result.risk_assessment_id === expectedAssessmentId;
  }
  return result.risk_assessment_id === expectedAssessmentId;
}

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

export function normalizeRiskCapacityStatus(value: unknown): RiskCapacityPlausibilityStatus {
  return RISK_CAPACITY_PLAUSIBILITY_STATUSES.includes(value as RiskCapacityPlausibilityStatus)
    ? (value as RiskCapacityPlausibilityStatus)
    : 'not_evaluable';
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value);
}

function asQuestion(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object')
    : [];
}

/** Defensive Normalisierung der Endpoint-Antwort (Schema-Drift tolerant). */
export function normalizeRiskCapacityPlausibility(data: unknown): RiskCapacityPlausibility {
  const raw = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
  const result: RiskCapacityPlausibility = {
    status: normalizeRiskCapacityStatus(raw.status),
    reason_code: raw.reason_code == null ? null : asString(raw.reason_code),
    findings: asRecords(raw.findings).map((row) => ({
      check: asString(row.check),
      question_number: asQuestion(row.question_number),
      message: asString(row.message),
    })),
    not_evaluable: asRecords(raw.not_evaluable).map((row) => ({
      check: asString(row.check),
      question_number: asQuestion(row.question_number),
      reason: asString(row.reason),
    })),
    advisor_text: asString(raw.advisor_text),
    override_down: raw.override_down === true,
    capacity_binding: typeof raw.capacity_binding === 'boolean' ? raw.capacity_binding : null,
    version: raw.version == null ? null : asString(raw.version),
    risk_assessment_id:
      raw.risk_assessment_id == null || raw.risk_assessment_id === ''
        ? null
        : asString(raw.risk_assessment_id),
  };
  if ('verification_code' in raw) {
    result.verification_code = raw.verification_code == null ? null : asString(raw.verification_code);
  }
  if (Array.isArray(raw.resolution_actions)) {
    result.resolution_actions = raw.resolution_actions.map(asString).filter(Boolean);
  }
  return result;
}

type RequestOptions = {
  signal?: AbortSignal;
  baseUrl?: string;
};

export async function fetchRiskCapacityPlausibility(
  mandateId: string,
  options: RequestOptions = {},
): Promise<RiskCapacityPlausibility> {
  const token = await resolveAuthToken();
  let response: Response;
  try {
    response = await fetch(
      `${options.baseUrl ?? ''}/mandates/${encodeURIComponent(mandateId)}/risk-capacity-plausibility`,
      {
        method: 'GET',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: options.signal,
      },
    );
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err;
    }
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  return normalizeRiskCapacityPlausibility(await response.json());
}
