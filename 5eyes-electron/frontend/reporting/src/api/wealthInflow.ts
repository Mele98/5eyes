/**
 * API-Client für die WealthInflow-Endpoints (Roadmap #54).
 *
 * Backend-Vertrag routers/wealth.py:
 *   GET    /clients/{id}/wealth-inflows   (951) → list[WealthInflowResponse]
 *   POST   /clients/{id}/wealth-inflows   (964) → WealthInflowResponse, 201
 *   PUT    /wealth-inflows/{inflowId}     (993) → WealthInflowResponse
 *   DELETE /wealth-inflows/{inflowId}     (1020) → 204
 *
 * Mutationen laufen NICHT unter /clients (Inflow-ID ist global eindeutig).
 * Auth/Fehler aus ./client wiederverwendet; 422-Detail wird geflacht.
 */
import { ApiError, resolveAuthToken } from './client';
import type {
  WealthInflowCreatePayload,
  WealthInflowRecord,
  WealthInflowUpdatePayload,
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

export async function fetchWealthInflows(
  clientId: string,
  options: RequestOptions = {},
): Promise<WealthInflowRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/clients/${encodeURIComponent(clientId)}/wealth-inflows`,
    { method: 'GET', headers: await authHeaders(), signal: options.signal },
  );
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as WealthInflowRecord[]) : [];
}

export async function createWealthInflow(
  clientId: string,
  payload: WealthInflowCreatePayload,
  options: RequestOptions = {},
): Promise<WealthInflowRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/clients/${encodeURIComponent(clientId)}/wealth-inflows`,
    {
      method: 'POST',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    },
  );
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as WealthInflowRecord;
}

export async function updateWealthInflow(
  inflowId: string,
  payload: WealthInflowUpdatePayload,
  options: RequestOptions = {},
): Promise<WealthInflowRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/wealth-inflows/${encodeURIComponent(inflowId)}`,
    {
      method: 'PUT',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    },
  );
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as WealthInflowRecord;
}

export async function deleteWealthInflow(
  inflowId: string,
  options: RequestOptions = {},
): Promise<void> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(
    `${baseUrl}/wealth-inflows/${encodeURIComponent(inflowId)}`,
    { method: 'DELETE', headers: await authHeaders(), signal: options.signal },
  );
  if (!response.ok) {
    await raiseApiError(response);
  }
}
