/**
 * GOAL-ORDER-REACT-001: API-Client fuer PUT /mandates/{id}/goals/order
 * (atomare Reihenfolge, Konfliktpruefung ueber expected_goal_ids).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { reorderGoals } from './goals';
import type { GoalRecord } from './types';

const fetchMock = vi.fn();

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('reorderGoals', () => {
  it('sendet die vollstaendige Folge und die zuletzt gesehene Folge per PUT', async () => {
    const rows = [{ id: 'g2', rank: 1 }, { id: 'g1', rank: 2 }] as unknown as GoalRecord[];
    fetchMock.mockResolvedValue(jsonResponse(rows));
    await expect(reorderGoals('m 1', ['g2', 'g1'], ['g1', 'g2'])).resolves.toEqual(rows);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m%201/goals/order');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({
      goal_ids: ['g2', 'g1'],
      expected_goal_ids: ['g1', 'g2'],
    });
  });

  it('reicht 409 (paralleler Stand) als ApiError mit Status durch', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Die Ziel-Reihenfolge wurde inzwischen geaendert.' }, { ok: false, status: 409 }),
    );
    await expect(reorderGoals('m1', ['g1'], ['g1'])).rejects.toMatchObject({
      status: 409,
      detail: 'Die Ziel-Reihenfolge wurde inzwischen geaendert.',
    });
  });

  it('liefert [] bei unerwarteter Nicht-Array-Antwort', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    await expect(reorderGoals('m1', ['g1'], ['g1'])).resolves.toEqual([]);
  });
});
