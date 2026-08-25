/**
 * Tests für den Cashflow-API-Client (Track #68).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createCashflow,
  deleteCashflow,
  fetchCashflows,
  fetchDerivedCashflows,
  updateCashflow,
} from './cashflow';
import type { CashflowCreatePayload } from './types';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

const PAYLOAD: CashflowCreatePayload = {
  cashflow_type: 'Expense',
  label: 'Lebenshaltung',
  amount_rappen: 3_600_000,
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

describe('fetchCashflows', () => {
  it('liefert die Liste + adressiert /clients/{id}/cashflows', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-1');
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'cf1' }]));
    const rows = await fetchCashflows('c1');
    expect(rows).toHaveLength(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/cashflows');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-1');
  });

  it('liefert [] bei Nicht-Array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    expect(await fetchCashflows('c1')).toEqual([]);
  });

  it('wirft ApiError(0) bei Netzwerk-Fehler', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchCashflows('c1')).rejects.toMatchObject({ status: 0 });
  });
});

describe('fetchDerivedCashflows', () => {
  it('adressiert /clients/{id}/cashflows-derived', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'd1', is_derived: 1 }]));
    const rows = await fetchDerivedCashflows('c1');
    expect(rows[0].is_derived).toBe(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/clients/c1/cashflows-derived');
  });
});

describe('create / update / delete', () => {
  it('createCashflow POSTet den Payload', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'cf2' }, { status: 201 }));
    await createCashflow('c1', PAYLOAD);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/cashflows');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).amount_rappen).toBe(3_600_000);
  });

  it('updateCashflow adressiert /cashflows/{id} per PUT', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'cf2' }));
    await updateCashflow('c1', 'cf2', { label: 'Neu' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/cashflows/cf2');
    expect(init.method).toBe('PUT');
  });

  it('deleteCashflow löst bei 204 ohne Body auf', async () => {
    const noBody = {
      ok: true,
      status: 204,
      json: async () => {
        throw new Error('kein Body');
      },
    } as unknown as Response;
    fetchMock.mockResolvedValue(noBody);
    await expect(deleteCashflow('c1', 'cf2')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });

  it('flacht 422-Detail-Array zu ApiError.detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'cashflow_type ungültig' }] }, { ok: false, status: 422 }),
    );
    await expect(createCashflow('c1', PAYLOAD)).rejects.toMatchObject({
      status: 422,
      detail: 'cashflow_type ungültig',
    });
  });
});
