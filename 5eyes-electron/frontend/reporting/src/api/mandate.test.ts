/**
 * Tests für den Mandate-API-Client (Track #65).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createMandate,
  fetchMandate,
  listMandates,
  updateMandate,
} from './mandate';
import type { MandateCreatePayload } from './types';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

const CREATE: MandateCreatePayload = { mandate_number: 'M-001' };

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

describe('listMandates', () => {
  it('GETtet /clients/{id}/mandates + setzt Bearer', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-5');
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'm1' }]));
    const rows = await listMandates('c1');
    expect(rows).toHaveLength(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/mandates');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-5');
  });

  it('liefert [] bei Nicht-Array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    expect(await listMandates('c1')).toEqual([]);
  });
});

describe('createMandate', () => {
  it('POSTet auf /clients/{id}/mandates', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'm2' }, { status: 201 }));
    await createMandate('c1', CREATE);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1/mandates');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).mandate_number).toBe('M-001');
  });

  it('flacht 422-Array zu ApiError.detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'mandate_number required' }] }, { ok: false, status: 422 }),
    );
    await expect(createMandate('c1', CREATE)).rejects.toMatchObject({
      status: 422,
      detail: 'mandate_number required',
    });
  });
});

describe('fetchMandate / updateMandate', () => {
  it('fetchMandate GETtet /mandates/{id}', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'm1', mandate_number: 'M-001' }));
    const rec = await fetchMandate('m1');
    expect(rec.mandate_number).toBe('M-001');
    expect(fetchMock.mock.calls[0][0]).toBe('/mandates/m1');
  });

  it('updateMandate PUTtet /mandates/{id}', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'm1' }));
    await updateMandate('m1', { status: 'Archiviert' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body).status).toBe('Archiviert');
  });

  it('wirft ApiError(0) bei Netzwerk-Fehler', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchMandate('m1')).rejects.toMatchObject({ status: 0 });
  });
});
