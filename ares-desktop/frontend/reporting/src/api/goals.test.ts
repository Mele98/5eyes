/**
 * Tests für den Goal-CRUD-API-Client (Track #64).
 *
 * Mockt global.fetch und prüft: Array-/Non-Array-Handling, Body-Versand,
 * 204-ohne-Body, Fehler-Flattening (409/422 → ApiError), Netzwerk → ApiError(0),
 * AbortError-Durchreichung und den Bearer-Header.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './client';
import {
  calculateMaxPensionSpending,
  createGoal,
  deleteGoal,
  fetchGoals,
  updateGoal,
} from './goals';
import type { GoalCreatePayload, GoalRecord } from './types';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

const SAMPLE_PAYLOAD: GoalCreatePayload = {
  goal_family: 'Rendite',
  goal_type: 'Renditeziel',
  label: 'Wachstum',
  rank: 2,
  target_return_bps: 450,
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  window.sessionStorage.clear();
  window.localStorage.clear();
  delete (window as { desktop?: unknown }).desktop;
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe('fetchGoals', () => {
  it('liefert die Backend-Liste zurück', async () => {
    const rows = [{ id: 'g1', label: 'A' }] as unknown as GoalRecord[];
    fetchMock.mockResolvedValue(jsonResponse(rows));
    const result = await fetchGoals('m1');
    expect(result).toEqual(rows);
    expect(fetchMock).toHaveBeenCalledWith('/mandates/m1/goals', expect.objectContaining({ method: 'GET' }));
  });

  it('liefert [] bei unerwarteter Nicht-Array-Antwort', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    expect(await fetchGoals('m1')).toEqual([]);
  });

  it('setzt den Bearer-Header aus sessionStorage', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-123');
    fetchMock.mockResolvedValue(jsonResponse([]));
    await fetchGoals('m1');
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer jwt-123');
  });

  it('wirft ApiError(0) bei Netzwerk-Fehler', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchGoals('m1')).rejects.toBeInstanceOf(ApiError);
    await expect(fetchGoals('m1')).rejects.toMatchObject({ status: 0 });
  });

  it('reicht AbortError unverändert durch', async () => {
    fetchMock.mockRejectedValue(new DOMException('aborted', 'AbortError'));
    await expect(fetchGoals('m1')).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('createGoal / updateGoal', () => {
  it('createGoal sendet den Payload als POST-Body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'g1' }, { status: 201 }));
    await createGoal('m1', SAMPLE_PAYLOAD);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1/goals');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toMatchObject({ goal_type: 'Renditeziel', target_return_bps: 450 });
  });

  it('updateGoal adressiert /goals/{goalId} per PUT', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'g1' }));
    await updateGoal('m1', 'g1', { label: 'Neu' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1/goals/g1');
    expect(init.method).toBe('PUT');
  });

  it('flacht ein 422-Validation-Array zu einem ApiError-Detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { detail: [{ loc: ['body', 'rank'], msg: 'ensure >= 1' }] },
        { ok: false, status: 422 },
      ),
    );
    await expect(createGoal('m1', SAMPLE_PAYLOAD)).rejects.toMatchObject({
      status: 422,
      detail: 'ensure >= 1',
    });
  });
});

describe('deleteGoal', () => {
  it('löst bei 204 ohne Body-Parse auf', async () => {
    const noBody = {
      ok: true,
      status: 204,
      json: async () => {
        throw new Error('204 hat keinen Body');
      },
    } as unknown as Response;
    fetchMock.mockResolvedValue(noBody);
    await expect(deleteGoal('m1', 'g1')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });

  it('wirft ApiError bei 409', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Mandat gesperrt' }, { ok: false, status: 409 }),
    );
    await expect(deleteGoal('m1', 'g1')).rejects.toMatchObject({ status: 409, detail: 'Mandat gesperrt' });
  });
});

describe('calculateMaxPensionSpending', () => {
  it('postet auf den calculate-Endpoint und gibt die Antwort zurück', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ max_annual_chf_rappen: 6_000_000, reasoning: [] }));
    const res = await calculateMaxPensionSpending('m1', {
      retirement_year: 2035,
      life_expectancy_year: 2060,
    });
    expect(res.max_annual_chf_rappen).toBe(6_000_000);
    expect(fetchMock.mock.calls[0][0]).toBe('/mandates/m1/goals/calculate-max-pension-spending');
  });

  it('reicht den 409-Hinweis (kein Risikoprofil) als ApiError durch', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Bitte zuerst ein aktuelles Risikoprofil speichern.' }, { ok: false, status: 409 }),
    );
    await expect(
      calculateMaxPensionSpending('m1', { retirement_year: 2035, life_expectancy_year: 2060 }),
    ).rejects.toMatchObject({ status: 409 });
  });
});
