/**
 * API-Client für die Target-Allocation-Endpoints (Track #67).
 *
 * Backend-Vertrag routers/allocation.py:
 *   GET  /mandates/{id}/target-allocation/current            (92)  → TargetAllocationResponse
 *   POST /mandates/{id}/target-allocation                    (193) → TargetAllocationResponse, 201
 *   POST /mandates/{id}/target-allocation/generate           (367) → TargetAllocationGenerateResponse
 *   POST /mandates/{id}/target-allocation/sensitivity        (394) → AllocationSensitivityResponse
 *   GET  /mandates/{id}/target-allocation/current/analysis-integrity → AnalysisIntegrityReport
 *
 * Auth + Fehler-Typen aus ./client wiederverwendet. 422-Validation-Arrays
 * werden zu einem lesbaren String geflacht.
 */
import {
  ApiError,
  apiErrorFromResponse,
  formatApiErrorDetail,
  resolveAuthToken,
  SchemaError,
} from './client';
import type {
  AllocationGenerateResult,
  AllocationSensitivityRequestPayload,
  AllocationSensitivityResult,
  AnalysisIntegrityReport,
  TargetAllocationCreatePayload,
  TargetAllocationRecord,
} from './types';

interface RequestOptions {
  signal?: AbortSignal;
  baseUrl?: string;
}

/** Flacht FastAPI-Detail (string | 422-Array | Objekt) zu einem String. */
/** Delegiert an den zentralen Formatter (siehe client.ts). */
export function flattenDetail(detail: unknown): string {
  return formatApiErrorDetail(detail);
}

async function authHeaders(): Promise<HeadersInit> {
  const token = await resolveAuthToken();
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function base(mandateId: string, baseUrl: string): string {
  return `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/target-allocation`;
}

async function raiseApiError(response: Response): Promise<never> {
  throw await apiErrorFromResponse(response);
}

async function request(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { credentials: 'include', ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
}

export async function fetchCurrentAllocation(
  mandateId: string,
  options: RequestOptions = {},
): Promise<TargetAllocationRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${base(mandateId, baseUrl)}/current`, {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as TargetAllocationRecord;
}

export async function saveTargetAllocation(
  mandateId: string,
  payload: TargetAllocationCreatePayload,
  options: RequestOptions = {},
): Promise<TargetAllocationRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(base(mandateId, baseUrl), {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as TargetAllocationRecord;
}

export async function generateAllocation(
  mandateId: string,
  options: RequestOptions = {},
): Promise<AllocationGenerateResult> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${base(mandateId, baseUrl)}/generate`, {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify({ preferences: null }),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as AllocationGenerateResult;
}

export async function runSensitivity(
  mandateId: string,
  payload: AllocationSensitivityRequestPayload,
  options: RequestOptions = {},
): Promise<AllocationSensitivityResult> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${base(mandateId, baseUrl)}/sensitivity`, {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as AllocationSensitivityResult;
}

/**
 * GOAL-ANALYSIS-INTEGRITY-UI-REACT-001: Integritaetsstatus der gespeicherten
 * Zielanalyse und des Shadow-Containers. `null` = keine aktuelle
 * Soll-Allokation (404).
 */
export async function fetchAnalysisIntegrity(
  mandateId: string,
  options: RequestOptions = {},
): Promise<AnalysisIntegrityReport | null> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${base(mandateId, baseUrl)}/current/analysis-integrity`, {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (response.status === 404) return null;
  if (!response.ok) return raiseApiError(response);
  const data = (await response.json()) as { needs_attention?: unknown } | null;
  if (!data || typeof data !== 'object' || typeof data.needs_attention !== 'boolean') {
    throw new SchemaError('needs_attention');
  }
  return data as AnalysisIntegrityReport;
}
