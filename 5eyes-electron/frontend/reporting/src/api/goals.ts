/**
 * API-Client für die Goal-CRUD-Endpoints (Track #64).
 *
 * Backend-Vertrag `5eyes-backend/routers/wealth.py`:
 *   GET    /mandates/{id}/goals                          (675) → list[GoalResponse]
 *   POST   /mandates/{id}/goals                          (689) → GoalResponse, 201
 *   PUT    /mandates/{id}/goals/{goalId}                 (727) → GoalResponse
 *   DELETE /mandates/{id}/goals/{goalId}                 (766) → 204 (kein Body)
 *   PUT    /mandates/{id}/goals/order                    → list[GoalResponse] (409 bei Konflikt)
 *   POST   /mandates/{id}/goals/calculate-max-pension-spending (1047)
 *
 * Auth + Fehler-Typen werden aus `./client` wiederverwendet (kein Copy).
 * 422-Validation-Details werden über den zentralen `apiErrorFromResponse` zu einem String
 * geflacht, damit Komponenten eine lesbare Meldung erhalten.
 */
import { ApiError, apiErrorFromResponse, resolveAuthToken } from './client';
import type {
  GoalCreatePayload,
  GoalRecord,
  GoalUpdatePayload,
  MaxPensionSpendingRequest,
  MaxPensionSpendingResponse,
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

function goalsBase(mandateId: string, baseUrl: string): string {
  return `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/goals`;
}

/** Wandelt einen Nicht-OK-Response in einen ApiError mit lesbarem Detail. */
async function raiseApiError(response: Response): Promise<never> {
  throw await apiErrorFromResponse(response, {
    fallback: 'Unbekannter Fehler beim Speichern des Ziels.',
  });
}

/** Zentraler fetch-Wrapper: Netzwerk → ApiError(0), AbortError durchreichen. */
async function request(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { credentials: 'include', ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err;
    }
    throw new ApiError(0, `Netzwerk-Fehler: ${(err as Error).message}`, err);
  }
}

export async function fetchGoals(
  mandateId: string,
  options: RequestOptions = {},
): Promise<GoalRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(goalsBase(mandateId, baseUrl), {
    method: 'GET',
    headers: await authHeaders(),
    signal: options.signal,
  });
  if (!response.ok) {
    return raiseApiError(response);
  }
  const data = await response.json();
  // Backend liefert eine Liste; defensiv gegen unerwartete Shapes.
  return Array.isArray(data) ? (data as GoalRecord[]) : [];
}

export async function createGoal(
  mandateId: string,
  payload: GoalCreatePayload,
  options: RequestOptions = {},
): Promise<GoalRecord> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(goalsBase(mandateId, baseUrl), {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    return raiseApiError(response);
  }
  return (await response.json()) as GoalRecord;
}

export async function updateGoal(
  mandateId: string,
  goalId: string,
  payload: GoalUpdatePayload,
  options: RequestOptions = {},
): Promise<GoalRecord> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${goalsBase(mandateId, baseUrl)}/${encodeURIComponent(goalId)}`;
  const response = await request(url, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    return raiseApiError(response);
  }
  return (await response.json()) as GoalRecord;
}

/**
 * GOAL-ORDER-REACT-001: schreibt die vollstaendige Ziel-Reihenfolge atomar
 * (PUT /mandates/{id}/goals/order). `expectedGoalIds` = zuletzt gesehene
 * Folge; weicht der Serverstand ab, antwortet das Backend mit 409. Nur der
 * Rang aendert sich, die Haerte bleibt unberuehrt.
 */
export async function reorderGoals(
  mandateId: string,
  goalIds: string[],
  expectedGoalIds: string[],
  options: RequestOptions = {},
): Promise<GoalRecord[]> {
  const baseUrl = options.baseUrl ?? '';
  const response = await request(`${goalsBase(mandateId, baseUrl)}/order`, {
    method: 'PUT',
    headers: await authHeaders(),
    body: JSON.stringify({ goal_ids: goalIds, expected_goal_ids: expectedGoalIds }),
    signal: options.signal,
  });
  if (!response.ok) {
    return raiseApiError(response);
  }
  const data = await response.json();
  return Array.isArray(data) ? (data as GoalRecord[]) : [];
}

export async function deleteGoal(
  mandateId: string,
  goalId: string,
  options: RequestOptions = {},
): Promise<void> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${goalsBase(mandateId, baseUrl)}/${encodeURIComponent(goalId)}`;
  const response = await request(url, {
    method: 'DELETE',
    headers: await authHeaders(),
    signal: options.signal,
  });
  // 204 No Content → kein Body-Parse.
  if (!response.ok) {
    return raiseApiError(response).then(() => undefined);
  }
}

export async function calculateMaxPensionSpending(
  mandateId: string,
  payload: MaxPensionSpendingRequest,
  options: RequestOptions = {},
): Promise<MaxPensionSpendingResponse> {
  const baseUrl = options.baseUrl ?? '';
  const url = `${goalsBase(mandateId, baseUrl)}/calculate-max-pension-spending`;
  const response = await request(url, {
    method: 'POST',
    headers: await authHeaders(),
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    return raiseApiError(response);
  }
  return (await response.json()) as MaxPensionSpendingResponse;
}
