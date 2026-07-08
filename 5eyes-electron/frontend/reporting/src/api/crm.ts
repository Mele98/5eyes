/**
 * API-Client für die CRM/Client-Endpoints (Track #66).
 *
 * Backend-Vertrag routers/clients.py:
 *   GET    /clients?search=&advisor_id=   (43)  → list[ClientResponse]
 *   GET    /clients/{id}                  (104) → ClientResponse
 *   PUT    /clients/{id}                  (113) → ClientResponse
 *   DELETE /clients/{id}                  (138) → 204
 *   GET    /clients/{id}/nationalities    (154) → list[NationalityResponse]
 *
 * Auth/Fehler aus ./client wiederverwendet; 422-Detail wird geflacht.
 */
import { ApiError, resolveAuthToken } from './client';
import type {
  ClientRecord,
  ClientUpdatePayload,
  NationalityRecord,
} from './types';

interface RequestOptions {
  signal?: AbortSignal;
  baseUrl?: string;
}

function flattenDetail(detail: unknown): string {
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

export async function listClients(
  options: { search?: string; advisorId?: string } & RequestOptions = {},
): Promise<ClientRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const params = new URLSearchParams();
  if (options.search) params.set('search', options.search);
  if (options.advisorId) params.set('advisor_id', options.advisorId);
  const qs = params.toString();
  const response = await request(`${baseUrl}/clients${qs ? `?${qs}` : ''}`, {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as ClientRecord[]) : [];
}

export async function fetchClient(
  clientId: string,
  options: RequestOptions = {},
): Promise<ClientRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${baseUrl}/clients/${encodeURIComponent(clientId)}`, {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as ClientRecord;
}

export async function updateClient(
  clientId: string,
  payload: ClientUpdatePayload,
  options: RequestOptions = {},
): Promise<ClientRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${baseUrl}/clients/${encodeURIComponent(clientId)}`, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as ClientRecord;
}

export async function deleteClient(
  clientId: string,
  options: RequestOptions = {},
): Promise<void> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${baseUrl}/clients/${encodeURIComponent(clientId)}`, {
    method: 'DELETE',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) {
    await raiseApiError(response);
  }
}

export async function fetchNationalities(
  clientId: string,
  options: RequestOptions = {},
): Promise<NationalityRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/clients/${encodeURIComponent(clientId)}/nationalities`,
    { method: 'GET', headers: await authHeaders(), signal: options.signal },
  );
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as NationalityRecord[]) : [];
}
