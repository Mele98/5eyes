/**
 * API-Client für die Cashflow-Endpoints (Track #68).
 *
 * Backend-Vertrag (Cashflows hängen am CLIENT):
 *   GET    /clients/{id}/cashflows            (wealth.py:571) → list[CashflowResponse]
 *   POST   /clients/{id}/cashflows            (wealth.py:590) → CashflowResponse, 201
 *   PUT    /clients/{id}/cashflows/{cfId}     (wealth.py:641) → CashflowResponse
 *   DELETE /clients/{id}/cashflows/{cfId}     (wealth.py:619) → 204
 *   GET    /clients/{id}/cashflows-derived    (clients.py:315) → DerivedCashflow[] (READ-ONLY)
 *
 * Auth/Fehler aus ./client wiederverwendet; 422-Detail wird geflacht.
 */
import { ApiError, resolveAuthToken } from './client';
import type {
  CashflowCreatePayload,
  CashflowRecord,
  CashflowUpdatePayload,
  DerivedCashflow,
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

function cashflowsBase(clientId: string, baseUrl: string): string {
  return `${baseUrl}/clients/${encodeURIComponent(clientId)}/cashflows`;
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

export async function fetchCashflows(
  clientId: string,
  options: RequestOptions = {},
): Promise<CashflowRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(cashflowsBase(clientId, baseUrl), {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as CashflowRecord[]) : [];
}

export async function fetchDerivedCashflows(
  clientId: string,
  options: RequestOptions = {},
): Promise<DerivedCashflow[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${cashflowsBase(clientId, baseUrl)}-derived`, {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  const data = await response.json();
  return Array.isArray(data) ? (data as DerivedCashflow[]) : [];
}

export async function createCashflow(
  clientId: string,
  payload: CashflowCreatePayload,
  options: RequestOptions = {},
): Promise<CashflowRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(cashflowsBase(clientId, baseUrl), {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as CashflowRecord;
}

export async function updateCashflow(
  clientId: string,
  cashflowId: string,
  payload: CashflowUpdatePayload,
  options: RequestOptions = {},
): Promise<CashflowRecord> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${cashflowsBase(clientId, baseUrl)}/${encodeURIComponent(cashflowId)}`;
  const response = await request(url, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) return raiseApiError(response);
  return (await response.json()) as CashflowRecord;
}

export async function deleteCashflow(
  clientId: string,
  cashflowId: string,
  options: RequestOptions = {},
): Promise<void> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${cashflowsBase(clientId, baseUrl)}/${encodeURIComponent(cashflowId)}`;
  const response = await request(url, {
    method: 'DELETE',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) {
    await raiseApiError(response);
  }
}
