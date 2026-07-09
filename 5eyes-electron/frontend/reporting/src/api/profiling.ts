import {
  ApiError,
  SchemaError,
  resolveAuthToken,
} from './client';
import type {
  RiskAssessment,
  RiskAssessmentCreate,
  RiskOverride,
} from './types';

type RequestOptions = {
  signal?: AbortSignal;
  baseUrl?: string;
};

function endpoint(mandateId: string, suffix: string, baseUrl = ''): string {
  return `${baseUrl}/mandates/${encodeURIComponent(mandateId)}${suffix}`;
}

async function authHeaders(includeBody = false): Promise<HeadersInit> {
  const token = await resolveAuthToken();
  return {
    Accept: 'application/json',
    ...(includeBody ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function parseError(response: Response): Promise<ApiError> {
  let detail = `HTTP ${response.status}`;
  let raw: unknown;
  try {
    raw = await response.json();
    const maybeDetail = (raw as { detail?: unknown })?.detail;
    if (typeof maybeDetail === 'string') {
      detail = maybeDetail;
    } else if (maybeDetail) {
      detail = JSON.stringify(maybeDetail);
    }
  } catch {
    // Non-JSON body: keep HTTP fallback.
  }
  return new ApiError(response.status, detail, raw);
}

function validateRiskAssessment(data: unknown): asserts data is RiskAssessment {
  if (!data || typeof data !== 'object') {
    throw new SchemaError('risk_assessment root');
  }
  const expectedKeys = [
    'id',
    'mandate_id',
    'version',
    'is_current',
    'valid_from',
    'q_income_points',
    'q_obligations_points',
    'q_savings_points',
    'q_wealth_points',
    'risk_capacity_total',
    'risk_capacity_profile',
    'investment_horizon_years',
    'investment_horizon_label',
    'risk_capacity_score_x10',
    'q_investment_goal_points',
    'q_risk_preference_points',
    'q_risk_behavior_points',
    'risk_willingness_total',
    'risk_willingness_profile',
    'risk_willingness_score_x10',
    'final_score_x10',
    'final_profile',
    'is_overridden',
    'assessed_at',
    'assessed_by',
    'created_at',
    'answers',
  ] as const;
  for (const key of expectedKeys) {
    if (!(key in (data as Record<string, unknown>))) {
      throw new SchemaError(key);
    }
  }
}

async function requestRiskAssessment(
  url: string,
  init: RequestInit,
): Promise<RiskAssessment> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err;
    }
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  const data = await response.json();
  validateRiskAssessment(data);
  return data;
}

export async function fetchCurrentRiskAssessment(
  mandateId: string,
  options: RequestOptions = {},
): Promise<RiskAssessment> {
  return requestRiskAssessment(
    endpoint(mandateId, '/risk-assessments/current', options.baseUrl),
    {
      method: 'GET',
      credentials: 'include',
      headers: await authHeaders(),
      signal: options.signal,
    },
  );
}

export async function createRiskAssessment(
  mandateId: string,
  body: RiskAssessmentCreate,
  options: RequestOptions = {},
): Promise<RiskAssessment> {
  return requestRiskAssessment(
    endpoint(mandateId, '/risk-assessments', options.baseUrl),
    {
      method: 'POST',
      credentials: 'include',
      headers: await authHeaders(true),
      body: JSON.stringify(body),
      signal: options.signal,
    },
  );
}

export async function overrideRiskAssessment(
  mandateId: string,
  raId: string,
  body: RiskOverride,
  options: RequestOptions = {},
): Promise<RiskAssessment> {
  return requestRiskAssessment(
    endpoint(
      mandateId,
      `/risk-assessments/${encodeURIComponent(raId)}/override`,
      options.baseUrl,
    ),
    {
      method: 'POST',
      credentials: 'include',
      headers: await authHeaders(true),
      body: JSON.stringify(body),
      signal: options.signal,
    },
  );
}
