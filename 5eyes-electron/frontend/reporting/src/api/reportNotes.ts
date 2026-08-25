/**
 * Sprint U-P28 PR C: GET/PUT-Client für die Berater-Override-Texte
 * (Tabelle `mandate_report_notes`, Endpoints aus U-P28 PR A).
 *
 * Backend-Vertrag siehe `schemas/review.py::ReportNotesUpdate` /
 * `ReportNotesResponse`. Felder sind alle optional — leere Strings
 * bedeuten „Auto-Default greift wieder".
 *
 * Auth: gleicher Bearer-Token-Mechanismus wie `client.ts` (Electron →
 * sessionStorage → localStorage → Vite-Env-Fallback).
 */
import { ApiError } from './client';

/** Welche Sektion ein Override-Feld betrifft. */
export type NotesField =
  | 'aa_anmerkungen'
  | 'waehrungen_erklaerung'
  | 'branchen_analyse'
  | 'vorgehen_block_optimierungen'
  | 'vorgehen_block_zielstrategie';

export interface ReportNotes {
  id: string | null;
  mandate_id: string;
  aa_anmerkungen: string | null;
  waehrungen_erklaerung: string | null;
  branchen_analyse: string | null;
  vorgehen_block_optimierungen: string | null;
  vorgehen_block_zielstrategie: string | null;
  vorgehen_offene_fragen: string[];
  vorgehen_naechster_termin: string | null;
  vorgehen_todos: string[];
  vorgehen_dokumente: string[];
  last_edited_by: string | null;
  last_edited_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * PUT-Payload. Alle Felder sind optional:
 * - `null`/`undefined` weglassen → Backend lässt das Feld unangetastet
 * - `""` (leerer String) → Backend setzt das Feld auf NULL → Auto-Default
 */
export interface ReportNotesUpdate {
  aa_anmerkungen?: string | null;
  waehrungen_erklaerung?: string | null;
  branchen_analyse?: string | null;
  vorgehen_block_optimierungen?: string | null;
  vorgehen_block_zielstrategie?: string | null;
  vorgehen_offene_fragen?: string[];
  vorgehen_naechster_termin?: string | null;
  vorgehen_todos?: string[];
  vorgehen_dokumente?: string[];
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
    const desktopToken = await window.desktop?.getAuthToken?.();
    if (desktopToken) return desktopToken;
  } catch {
    // Browser-dev fallback
  }
  try {
    const sessionToken = window.sessionStorage.getItem('5eyes_token');
    if (sessionToken) return sessionToken;
  } catch {
    /* hardened browser context */
  }
  try {
    const localToken = window.localStorage.getItem('5eyes_token');
    if (localToken) return localToken;
  } catch {
    /* hardened browser context */
  }
  if (import.meta.env.DEV && import.meta.env.VITE_5EYES_TOKEN) {
    return import.meta.env.VITE_5EYES_TOKEN;
  }
  return null;
}

function endpoint(mandateId: string, baseUrl: string): string {
  return `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/report-notes`;
}

async function authHeaders(): Promise<HeadersInit> {
  const token = await resolveAuthToken();
  return {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function handleResponse(response: Response): Promise<ReportNotes> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errBody = await response.json();
      if (typeof errBody?.detail === 'string') detail = errBody.detail;
    } catch {
      /* non-json body */
    }
    throw new ApiError(response.status, detail);
  }
  const raw = (await response.json()) as ReportNotes;
  // comp-5: Listenfelder defensiv normalisieren — buildInitial/anythingPersisted
  // spreaden/lesen sie ungeschützt ([...x]); ein fehlendes/null-Feld (ältere
  // Payloads) würde sonst beim Öffnen des Notes-Drawers crashen.
  return {
    ...raw,
    vorgehen_offene_fragen: Array.isArray(raw.vorgehen_offene_fragen) ? raw.vorgehen_offene_fragen : [],
    vorgehen_todos: Array.isArray(raw.vorgehen_todos) ? raw.vorgehen_todos : [],
    vorgehen_dokumente: Array.isArray(raw.vorgehen_dokumente) ? raw.vorgehen_dokumente : [],
  };
}

/**
 * Lädt die Override-Texte eines Mandats.
 *
 * Niemals 404 — wenn noch nichts gepflegt ist, liefert das Backend
 * eine leere Response (`mandate_id` gesetzt, alle anderen Felder
 * `null` / `[]`).
 */
export async function fetchReportNotes(
  mandateId: string,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<ReportNotes> {
  const baseUrl = options.baseUrl ?? '';
  let response: Response;
  try {
    response = await fetch(endpoint(mandateId, baseUrl), {
      method: 'GET',
      credentials: 'include',
      headers: await authHeaders(),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  return handleResponse(response);
}

/**
 * Upsert. Liefert die persistierte Zeile zurück (inklusive Audit-Anchor).
 *
 * 403 wenn der eingeloggte User kein Berater ist (Backend prüft mit
 * `require_advisor`).
 */
export async function putReportNotes(
  mandateId: string,
  payload: ReportNotesUpdate,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<ReportNotes> {
  const baseUrl = options.baseUrl ?? '';
  let response: Response;
  try {
    response = await fetch(endpoint(mandateId, baseUrl), {
      method: 'PUT',
      credentials: 'include',
      headers: await authHeaders(),
      body: JSON.stringify(payload),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
  return handleResponse(response);
}
