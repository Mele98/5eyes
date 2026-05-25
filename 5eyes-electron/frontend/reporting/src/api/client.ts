/**
 * Fetch-Wrapper für den 5eyes-Backend-Advisory-Report-Endpoint.
 *
 * Auth-Strategie: Cookies werden mit `credentials: 'include'` mitgesendet
 * (5eyes-Backend setzt Session-Cookie nach Login via /auth/login).
 *
 * Error-Handling: Backend-4xx liefern strukturierte `{detail: string}`-
 * Responses; wir packen sie in `ApiError`. Network-Errors → ApiError mit
 * status=0. Schema-Drift (Top-Level-Key fehlt) → SchemaError.
 */
import type { AdvisoryReport } from './types';

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

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json' },
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err; // weiter nach oben, Caller kümmert sich
    }
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (typeof errBody?.detail === 'string') {
        detail = errBody.detail;
      }
    } catch {
      // body war kein JSON — Fallback auf HTTP-Status
    }
    throw new ApiError(response.status, detail);
  }

  const data = (await response.json()) as AdvisoryReport;
  validateSchemaV1(data);
  return data;
}

/**
 * Defensive Schema-Validierung. Prüft nur die Top-Level-Keys, NICHT
 * jede Sub-Struktur — Sub-Defaults sind im Backend-Schema dokumentiert
 * und werden in den Komponenten mit Fallbacks abgefangen.
 */
function validateSchemaV1(data: unknown): asserts data is AdvisoryReport {
  if (!data || typeof data !== 'object') {
    throw new SchemaError('root (kein Objekt)');
  }
  const expectedKeys = [
    'schema_version', 'mandate_id', 'generated_at',
    'cover', 'inhaltsverzeichnis', 'ausgangslage', 'positionen',
    'pruefpunkte', 'erkenntnisse', 'asset_allocation',
    'risikowaehrungen', 'branchen', 'goal_based_investing',
    'risikoprofilierung', 'building_blocks', 'statement_pm',
    'weiteres_vorgehen', 'disclaimer',
  ] as const;
  for (const key of expectedKeys) {
    if (!(key in (data as Record<string, unknown>))) {
      throw new SchemaError(key);
    }
  }
  const version = (data as { schema_version?: unknown }).schema_version;
  if (version !== 1) {
    throw new SchemaError(
      `schema_version (erwartet 1, erhalten ${String(version)})`,
    );
  }
}
