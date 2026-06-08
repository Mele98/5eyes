/**
 * Sprint U-FINMA-2.4: API-Client für AdvisoryLog-Endpoints.
 *
 * Drei Operationen:
 * - GET /mandates/{id}/advisory-log — Liste der aktiven Einträge
 * - POST /mandates/{id}/advisory-log — neuen Eintrag manuell erstellen
 * - POST /mandates/{id}/advisory-log/from-report-generation — Auto-Log
 *
 * Auth wie reportNotes.ts: Bearer aus Electron / SessionStorage / Vite-Env.
 */
import { ApiError } from './client';
import type { BeratungsprotokollEntry } from './types';

export type CommunicationChannel =
  | 'persoenlich'
  | 'video'
  | 'telefon'
  | 'schriftlich'
  | 'hybrid';

export type AdvisoryLogStatus =
  | 'Empfohlen'
  | 'Beschlossen'
  | 'Umgesetzt'
  | 'Abgelehnt'
  | 'Überarbeitung nötig';

export type AdvisoryEntryType =
  | 'Jahresreview'
  | 'Quartalscheck'
  | 'Strategie-Anpassung'
  | 'Override-Entscheid'
  | 'Ereignis-Reaktion'
  | 'Drift-Entscheid'
  | 'Zieländerung'
  | 'Restriktionsänderung'
  | 'Initialer Beratungsabschluss'
  | 'Eignungsprüfung'
  | 'Sonstiges';

export interface AdvisoryParticipant {
  role: 'client' | 'co_advisor' | 'partner' | 'guardian' | 'third_party';
  name: string;
  note?: string;
}

export interface AdvisoryLogCreatePayload {
  entry_type: AdvisoryEntryType;
  title: string;
  description: string;
  decision?: string | null;
  entry_datetime: string;
  duration_minutes: number;
  communication_channel: CommunicationChannel;
  language?: 'de' | 'fr' | 'it' | 'en';
  location?: string | null;
  participants?: AdvisoryParticipant[];
  topics: string[];
  risk_warnings_given?: string[];
  cost_disclosure_given: boolean;
  conflict_disclosure_ids?: string[];
  suitability_check_id?: string | null;
  status?: AdvisoryLogStatus;
}

declare global {
  interface Window {
    desktop?: {
      getAuthToken?: () => Promise<string | null>;
    };
  }
}

async function resolveAuthToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const t = await window.desktop?.getAuthToken?.();
    if (t) return t;
  } catch {
    /* dev fallback */
  }
  try {
    const t = window.sessionStorage.getItem('5eyes_token');
    if (t) return t;
  } catch {
    /* hardened */
  }
  try {
    const t = window.localStorage.getItem('5eyes_token');
    if (t) return t;
  } catch {
    /* hardened */
  }
  if (import.meta.env.DEV && import.meta.env.VITE_5EYES_TOKEN) {
    return import.meta.env.VITE_5EYES_TOKEN;
  }
  return null;
}

async function authHeaders(): Promise<HeadersInit> {
  const token = await resolveAuthToken();
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      else if (Array.isArray(body?.detail)) {
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) => `${e.loc?.join('.') ?? '?'}: ${e.msg ?? ''}`)
          .join('; ');
      }
    } catch {
      /* non-json body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function endpoint(mandateId: string, baseUrl: string, suffix = ''): string {
  return `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/advisory-log${suffix}`;
}

/**
 * Listet aktive (non-superseded) AdvisoryLog-Einträge für ein Mandat.
 */
export async function fetchAdvisoryLog(
  mandateId: string,
  options: { signal?: AbortSignal; baseUrl?: string; includeHistory?: boolean } = {},
): Promise<BeratungsprotokollEntry[]> {
  const baseUrl = options.baseUrl ?? '';
  const url =
    endpoint(mandateId, baseUrl) +
    (options.includeHistory ? '?include_history=true' : '');
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: await authHeaders(),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  return handleResponse<BeratungsprotokollEntry[]>(resp);
}

/**
 * POST /from-report-generation — Auto-Log mit pre-filled Daten aus Aggregator.
 * Berater kann anschließend per PUT erweitern.
 */
export async function createAutoLog(
  mandateId: string,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<BeratungsprotokollEntry> {
  const baseUrl = options.baseUrl ?? '';
  let resp: Response;
  try {
    resp = await fetch(endpoint(mandateId, baseUrl, '/from-report-generation'), {
      method: 'POST',
      credentials: 'include',
      headers: await authHeaders(),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  return handleResponse<BeratungsprotokollEntry>(resp);
}

/**
 * Manuell neuen Eintrag erstellen. Schmeißt 422 bei Validation-Fehler.
 */
export async function createAdvisoryLog(
  mandateId: string,
  payload: AdvisoryLogCreatePayload,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<BeratungsprotokollEntry> {
  const baseUrl = options.baseUrl ?? '';
  let resp: Response;
  try {
    resp = await fetch(endpoint(mandateId, baseUrl), {
      method: 'POST',
      credentials: 'include',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  return handleResponse<BeratungsprotokollEntry>(resp);
}
