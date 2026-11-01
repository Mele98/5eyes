/**
 * U-1 (A3 P1-1): Zugriff auf die aus `api/openapi.json` generierten Typen.
 *
 * `./generated/openapi.ts` wird nie von Hand editiert (`npm run
 * gen:api-types`). Handgeschriebene API-Typen werden schrittweise zu Aliasen
 * auf diese Helfer; reine Typen, keine Laufzeitwirkung.
 */
import type { components } from './generated/openapi';

/** Alle Schemas aus `components.schemas` des OpenAPI-Artefakts. */
export type ApiSchemas = components['schemas'];

/**
 * Request-Body-Schema, wie der Server es annimmt.
 *
 * Optional sind genau die Felder, die das Schema nicht unter `required`
 * fuehrt (Pydantic-Felder mit Default).
 */
export type ApiRequest<N extends keyof ApiSchemas> = ApiSchemas[N];

/**
 * Antwort-Schema, wie der Server es serialisiert.
 *
 * Pydantic fuehrt Felder mit Default im JSON-Schema nicht unter `required`,
 * FastAPI serialisiert ein `response_model` aber immer mit allen Feldern
 * (kein `response_model_exclude_unset`/`_none` im Backend). Auf oberster
 * Ebene ist darum jedes Feld vorhanden; `null` bleibt erhalten, wo das
 * Schema es erlaubt. Verschachtelte Objekte bleiben unveraendert.
 */
export type ApiResponse<N extends keyof ApiSchemas> = {
  [K in keyof ApiSchemas[N]]-?: ApiSchemas[N][K];
};
