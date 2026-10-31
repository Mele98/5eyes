/**
 * Fetch-Wrapper für den Ares-Backend-Advisory-Report-Endpoint.
 *
 * Auth-Strategie: gleicher Bearer-Token wie die Ares-Hauptapp. Electron
 * liefert ihn via `window.desktop.getAuthToken`; im Browser-Dev-Fallback
 * lesen wir `sessionStorage['5eyes_token']`.
 *
 * Error-Handling: Backend-4xx liefern strukturierte `{detail: string}`-
 * Responses; wir packen sie in `ApiError`. Network-Errors → ApiError mit
 * status=0. Schema-Drift (Top-Level-Key fehlt) → SchemaError.
 */
import type { AdvisoryReport } from './types';

declare global {
  interface Window {
    desktop?: {
      getAuthToken?: () => Promise<string | null>;
    };
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly raw?: unknown,
  ) {
    super(`API-Fehler ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

/**
 * Zentraler Formatter fuer FastAPI-`detail` (alle API-Module nutzen ihn).
 *
 * - String -> unveraendert;
 * - strukturierte 409/422 `{reason_code, message, ...}` -> `message [reason_code]`
 *   (identisch zum Monolithen ares.html, ESG-P0-3/P0-5,
 *   RISK-OVERRIDE-WRITE-BOUNDARY-001);
 * - FastAPI-422-Array -> `.msg`-Werte mit `; ` verbunden;
 * - Objekt mit `.msg` -> `.msg`;
 * - sonst `fallback`.
 */
export function formatApiErrorDetail(
  detail: unknown,
  fallback = 'Unbekannter Fehler.',
): string {
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
  if (detail && typeof detail === 'object') {
    const obj = detail as { reason_code?: unknown; message?: unknown; msg?: unknown };
    if (typeof obj.message === 'string' && obj.message) {
      return typeof obj.reason_code === 'string' && obj.reason_code
        ? `${obj.message} [${obj.reason_code}]`
        : obj.message;
    }
    if ('msg' in obj) return String(obj.msg);
  }
  return fallback;
}

/**
 * Zentraler API-Fehlerhandler: liest den Body eines Nicht-OK-Response und
 * baut daraus einen `ApiError` (detail via `formatApiErrorDetail`, raw =
 * rohes `detail`). Non-JSON-Body -> `HTTP <status>`.
 */
export async function apiErrorFromResponse(
  response: Response,
  options: { fallback?: string } = {},
): Promise<ApiError> {
  let detail = `HTTP ${response.status}`;
  let raw: unknown;
  try {
    const body = await response.json();
    raw = (body as { detail?: unknown })?.detail;
    if (raw !== undefined && raw !== null) {
      detail = formatApiErrorDetail(raw, options.fallback);
    }
  } catch {
    // Body war kein JSON -- Fallback auf HTTP-Status.
  }
  return new ApiError(response.status, detail, raw);
}

export class SchemaError extends Error {
  constructor(public readonly missingKey: string) {
    super(`Advisory-Report Schema-Drift: Pflichtfeld "${missingKey}" fehlt.`);
    this.name = 'SchemaError';
  }
}

/**
 * Lädt den vollen Advisory-Report eines Mandats.
 *
 * Wirft `ApiError` bei HTTP-Fehler oder Netzwerk-Problem.
 * Wirft `SchemaError` wenn der Backend-Response nicht dem erwarteten
 * Schema entspricht (Defensive vor Render-Crash in Komponenten).
 */
export async function fetchAdvisoryReport(
  mandateId: string,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<AdvisoryReport> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/advisory-report`;
  const token = await resolveAuthToken();

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err; // weiter nach oben, Caller kümmert sich
    }
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  const data = (await response.json()) as AdvisoryReport;
  validateSchemaV2(data);
  return data;
}


export async function resolveAuthToken(): Promise<string | null> {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const desktopToken = await window.desktop?.getAuthToken?.();
    if (desktopToken) {
      return desktopToken;
    }
  } catch {
    // Browser-dev fallback below.
  }
  try {
    const sessionToken = window.sessionStorage.getItem('5eyes_token');
    if (sessionToken) {
      return sessionToken;
    }
  } catch {
    // Storage can be unavailable in hardened browser contexts.
  }
  try {
    const localToken = window.localStorage.getItem('5eyes_token');
    if (localToken) {
      return localToken;
    }
  } catch {
    // Continue with Vite dev fallback.
  }
  if (import.meta.env.DEV && import.meta.env.VITE_ARES_TOKEN) {
    return import.meta.env.VITE_ARES_TOKEN;
  }
  return null;
}

/**
 * Defensive Schema-Validierung. Prüft nur die Top-Level-Keys, NICHT
 * jede Sub-Struktur — Sub-Defaults sind im Backend-Schema dokumentiert
 * und werden in den Komponenten mit Fallbacks abgefangen.
 */
function validateSchemaV2(data: unknown): asserts data is AdvisoryReport {
  if (!data || typeof data !== 'object') {
    throw new SchemaError('root (kein Objekt)');
  }
  const expectedKeys = [
    'schema_version', 'mandate_id', 'generated_at',
    'cover', 'disclaimer', 'inhaltsverzeichnis', 'ausgangslage', 'positionen',
    'pruefpunkte', 'erkenntnisse', 'asset_allocation',
    'risikowaehrungen', 'branchen', 'goal_based_investing',
    'risikoprofilierung', 'building_blocks', 'statement_pm',
    'weiteres_vorgehen',
    // U-FINMA-2.2: additive Sektion 16
    'beratungsprotokoll',
    // U-FINMA-3: additive Sektion 17
    'suitability_summary',
    // DL-1: weitere Top-Level-Sektionen, die der Aggregator unbedingt liefert
    // (advisory_report.py:289-315) und die u.a. die Compliance-Sektion liest —
    // ohne sie blieb Schema-Drift bei diesen Sektionen ungefangen.
    'stress_replay',
    'conflict_disclosures',
    'suitability_compliance',
    'methodology_models',
    'recommendation_methodology',
    'mandate_lock_status',
    'liquidity_cascade',
    'optimizer_run_history',
    'performance_attribution',
    'engine_configuration',
    'ab_backtest',
    // CERT-COST-PUBLICATION-001 (COST-PUBLICATION-001, 2026-10-09): der
    // Backend-Aggregator liefert cost_disclosure seit services/
    // advisory_report.py:411 -- hier fehlte die Pflicht-Validierung
    // komplett, ein Report ohne diese Sektion validierte trotzdem
    // erfolgreich und die Reporting-App zeigte den geschuetzten
    // Kostenausweis nirgends an.
    'cost_disclosure',
  ] as const;
  for (const key of expectedKeys) {
    if (!(key in (data as Record<string, unknown>))) {
      throw new SchemaError(key);
    }
  }
  const version = (data as { schema_version?: unknown }).schema_version;
  if (version !== 2) {
    throw new SchemaError(
      `schema_version (erwartet 2, erhalten ${String(version)})`,
    );
  }
}
