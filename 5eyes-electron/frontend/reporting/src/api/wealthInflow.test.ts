/**
 * Tests für den WealthInflow-API-Client (Roadmap #54).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createWealthInflow,
  deleteWealthInflow,
  fetchWealthInflows,
  updateWealthInflow,
} from './wealthInflow';
import type { WealthInflowCreatePayload } from './types';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

const PAYLOAD: WealthInflowCreatePayload = {
  label: 'Bonus',
  source_type: 'Bonus',
  amount_rappen: 5_000_000,
  expected_year: 2030,
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

describe('fetchWealthInflows', () => {
  it('GETtet /clients/{id}/wealth-inflows + Bearer', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-54');
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'i1' }]));
    const rows = await fetchWealthInflows('c1');
    expect(rows).toHaveLength(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/wealth-inflows');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-54');
  });

  it('liefert [] bei Nicht-Array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    expect(await fetchWealthInflows('c1')).toEqual([]);
  });

  it('wirft ApiError(0) bei Netzwerk-Fehler', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchWealthInflows('c1')).rejects.toMatchObject({ status: 0 });
  });
});

describe('createWealthInflow', () => {
  it('POSTet unter /clients/{id}/wealth-inflows', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'i2' }, { status: 201 }));
    await createWealthInflow('c1', PAYLOAD);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/wealth-inflows');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).source_type).toBe('Bonus');
  });

  it('flacht 422-Array zu ApiError.detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'is_recurring=1 erfordert duration_years' }] }, { ok: false, status: 422 }),
    );
    await expect(createWealthInflow('c1', PAYLOAD)).rejects.toMatchObject({
      status: 422,
      detail: 'is_recurring=1 erfordert duration_years',
    });
  });
});

describe('update / delete (global inflow id, NICHT unter client)', () => {
  it('updateWealthInflow PUTtet /wealth-inflows/{id}', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'i2' }));
    await updateWealthInflow('i2', { amount_rappen: 6_000_000 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/wealth-inflows/i2');
    expect(init.method).toBe('PUT');
  });

  it('deleteWealthInflow DELETEt /wealth-inflows/{id} (204)', async () => {
    const noBody = {
      ok: true,
      status: 204,
      json: async () => {
        throw new Error('kein Body');
      },
    } as unknown as Response;
    fetchMock.mockResolvedValue(noBody);
    await expect(deleteWealthInflow('i2')).resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/wealth-inflows/i2');
    expect(init.method).toBe('DELETE');
  });
});
