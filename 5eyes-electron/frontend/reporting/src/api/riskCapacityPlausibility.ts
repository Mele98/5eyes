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
