/**
 * API-Client für die Mandate-Endpoints (Track #65).
 *
 * Backend-Vertrag routers/mandates.py:
 *   GET  /clients/{id}/mandates       (24) → list[MandateResponse]
 *   POST /clients/{id}/mandates       (36) → MandateResponse, 201
 *   GET  /mandates/{id}               (81) → MandateResponse
 *   PUT  /mandates/{id}               (90) → MandateResponse
 *
 * Auth/Fehler aus ./client wiederverwendet; 422-Detail wird geflacht.
 */
import { ApiError, apiErrorFromResponse, resolveAuthToken } from './client';
import type {
  MandateCreatePayload,
  MandateRecord,
  MandateUpdatePayload,
} from './types';

interface RequestOptions {
  signal?: AbortSignal;
  baseUrl?: string;
}

async function authHeaders(): Promise<HeadersInit> {
  const token = await resolveAuthToken();
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
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

export async function listMandates(
  clientId: string,
  options: RequestOptions = {},
): Promise<MandateRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/clients/${encodeURIComponent(clientId)}/mandates`,
    { method: 'GET', headers: await authHeaders(), signal: options.signal },
  );
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as MandateRecord[]) : [];
}

export async function createMandate(
  clientId: string,
  payload: MandateCreatePayload,
  options: RequestOptions = {},
): Promise<MandateRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/clients/${encodeURIComponent(clientId)}/mandates`,
    {
      method: 'POST',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    },
  );
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as MandateRecord;
}

export async function fetchMandate(
  mandateId: string,
  options: RequestOptions = {},
): Promise<MandateRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/mandates/${encodeURIComponent(mandateId)}`,
    { method: 'GET', headers: await authHeaders(), signal: options.signal },
  );
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as MandateRecord;
}

export async function updateMandate(
  mandateId: string,
  payload: MandateUpdatePayload,
  options: RequestOptions = {},
): Promise<MandateRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/mandates/${encodeURIComponent(mandateId)}`,
    {
      method: 'PUT',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    },
  );
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as MandateRecord;
}
