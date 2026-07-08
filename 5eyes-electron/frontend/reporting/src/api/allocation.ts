/**
 * API-Client für die Target-Allocation-Endpoints (Track #67).
 *
 * Backend-Vertrag routers/allocation.py:
 *   GET  /mandates/{id}/target-allocation/current            (92)  → TargetAllocationResponse
 *   POST /mandates/{id}/target-allocation                    (193) → TargetAllocationResponse, 201
 *   POST /mandates/{id}/target-allocation/generate           (367) → TargetAllocationGenerateResponse
 *   POST /mandates/{id}/target-allocation/sensitivity        (394) → AllocationSensitivityResponse
 *
 * Auth + Fehler-Typen aus ./client wiederverwendet. 422-Validation-Arrays
 * werden zu einem lesbaren String geflacht.
 */
import { ApiError, resolveAuthToken } from './client';
import type {
  AllocationGenerateResult,
  AllocationSensitivityRequestPayload,
  AllocationSensitivityResult,
  TargetAllocationCreatePayload,
  TargetAllocationRecord,
} from './types';

interface RequestOptions {
  signal?: AbortSignal;
  baseUrl?: string;
}

/** Flacht FastAPI-Detail (string | 422-Array | Objekt) zu einem String. */
export function flattenDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item
          ? String((item as { msg: unknown }).msg)
          : String(item),
      )
      .join('; ');
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg: unknown }).msg);
  }
  return 'Unbekannter Fehler.';
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
  let detail = `HTTP ${response.status}`;
  let raw: unknown;
  try {
    const body = await response.json();
    raw = (body as { detail?: unknown })?.detail;
    if (raw !== undefined) detail = flattenDetail(raw);
  } catch {
    // non-json body
  }
  throw new ApiError(response.status, detail, raw);
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
